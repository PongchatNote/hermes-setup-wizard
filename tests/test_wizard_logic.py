"""Tests for the non-GUI wizard: catalogs, config files, redaction, steps."""

from __future__ import annotations

import io
import stat
from pathlib import Path

import keyring
import pytest
import yaml
from urllib.error import HTTPError

from hermes_wizard.apply import save_provider, save_settings
from hermes_wizard.catalog import (
    MAIN_FLOW,
    Setting,
    load_checks,
    load_faq,
    load_gateways,
    load_providers,
    load_secrets,
    load_settings,
    load_steps,
)
from hermes_wizard.configio import file_mode, read_env, upsert_env
from hermes_wizard.health import run_checks
from hermes_wizard.progress import load as load_progress
from hermes_wizard.progress import save as save_progress
from hermes_wizard.provider_test import probe_gateway, probe_provider
from hermes_wizard.redact import redact
from hermes_wizard.runner import NeedPassword, StepRunner


class MemoryKeyring(keyring.backend.KeyringBackend):
    priority = 1

    def __init__(self):
        self.data: dict[tuple[str, str], str] = {}

    def set_password(self, service, username, password):
        self.data[(service, username)] = password

    def get_password(self, service, username):
        return self.data.get((service, username))

    def delete_password(self, service, username):
        self.data.pop((service, username), None)


@pytest.fixture(autouse=True)
def memory_keyring():
    keyring.set_keyring(MemoryKeyring())
    yield


def test_main_flow_order():
    assert MAIN_FLOW == ("install", "provider", "cli-chat", "telegram", "discord", "line", "health")


def test_catalogs_load_and_are_bilingual():
    steps = load_steps()
    assert [step.id for step in steps][:4] == ["check-os", "apt-prereqs", "install-hermes", "verify-cli"]
    assert any(step.privilege == "root" for step in steps)
    settings = load_settings()
    assert settings
    for setting in settings:
        assert setting.where_en and setting.where_th
        assert setting.example or setting.type == "bool"
    providers = load_providers()
    assert providers[0].id == "openrouter" and providers[0].recommended
    assert any(item.id == "ollama-local" and item.config_provider == "custom" for item in providers)
    assert any(item.id == "nous" and item.key_required is False for item in providers)
    gates = {item.id: item for item in load_gateways()}
    for name in ("telegram", "discord", "line"):
        gate = gates[name]
        assert gate.steps_en and gate.steps_th
        assert gate.token_key
        for field in gate.fields:
            assert field.help_en and field.help_th
            assert field.where_en and field.example
    assert "plugins/platforms/line" in gates["line"].banner_en
    assert load_faq() and load_checks() and load_secrets()


def test_redact_hides_keys_tokens_and_exact_password():
    password = "correct-horse"
    text = "\n".join(
        [
            f"typed {password}",
            "OPENROUTER_API_KEY=sk-or-v1-supersecretvalue",
            "Authorization: Bearer sk-live-abcdefghijklmnop",
            "https://api.telegram.org/bot123456789:AA" + ("B" * 24) + "/getMe",
            "SLACK_BOT_TOKEN=xoxb-1234-secret",
        ]
    )
    clean = redact(text, extra=[password])
    assert password not in clean
    assert "supersecretvalue" not in clean
    assert "sk-live-abcdefghijklmnop" not in clean
    assert "AA" + ("B" * 24) not in clean
    assert "xoxb-1234-secret" not in clean
    assert "OPENROUTER_API_KEY=" in clean


def test_env_roundtrip_preserves_comments_and_mode(tmp_path: Path):
    path = tmp_path / ".env"
    path.write_text("# keep me\nOTHER=value\nOPENROUTER_API_KEY=old\n", encoding="utf-8")
    upsert_env(path, "OPENROUTER_API_KEY", "sk-or-v1-newvalue")
    upsert_env(path, "TELEGRAM_ALLOWED_USERS", "123456789")
    text = path.read_text(encoding="utf-8")
    assert "# keep me" in text
    assert "OTHER=value" in text
    assert "TELEGRAM_ALLOWED_USERS=123456789" in text
    assert read_env(path)["OPENROUTER_API_KEY"] == "sk-or-v1-newvalue"
    assert file_mode(path) == 0o600
    assert stat.S_IMODE(path.stat().st_mode) & 0o077 == 0


def test_provider_save_keeps_the_key_out_of_yaml(tmp_path: Path):
    config = tmp_path / "config.yaml"
    env = tmp_path / ".env"
    provider = next(item for item in load_providers() if item.id == "openrouter")
    secret = "sk-or-v1-not-for-yaml"
    changed = save_provider(
        provider,
        model="deepseek/deepseek-v4.1-flash-1017",
        api_key=secret,
        base_url="",
        context_length="",
        typed_provider="",
        typed_key_env="",
        also_preset=True,
        config_file=config,
        env_file=env,
    )
    yaml_text = config.read_text(encoding="utf-8")
    assert secret not in yaml_text
    data = yaml.safe_load(yaml_text)
    assert data["model"]["provider"] == "openrouter"
    assert data["model"]["default"] == "deepseek/deepseek-v4.1-flash-1017"
    assert "base_url" not in data["model"]
    assert data["timezone"] == "Asia/Bangkok"
    assert data["terminal"]["backend"] == "local"
    assert data["approvals"]["mode"] == "smart"
    assert read_env(env)["OPENROUTER_API_KEY"] == secret
    assert "OPENROUTER_API_KEY" in changed
    assert file_mode(env) == 0o600


def test_empty_secret_box_does_not_delete_a_stored_key(tmp_path: Path):
    env = tmp_path / ".env"
    config = tmp_path / "config.yaml"
    upsert_env(env, "OPENROUTER_API_KEY", "sk-or-v1-keep")
    setting = next(item for item in load_secrets() if item.key == "OPENROUTER_API_KEY")
    save_settings([(setting, "")], config_file=config, env_file=env)
    assert read_env(env)["OPENROUTER_API_KEY"] == "sk-or-v1-keep"


def test_runner_redacts_password_and_streams_status(tmp_path: Path):
    password = "sudo-secret-value"
    seen: list[str] = []

    class Proc:
        def __init__(self, argv, **kwargs):
            self.argv = argv
            self.pid = 4242
            self.returncode = 0
            self.stdin_was = kwargs.get("stdin")
            self.stdin = _Stdin()
            self.stdout = iter([f"password was {password}\n", "OPENROUTER_API_KEY=sk-or-v1-zzzzzzzzzzzz\n"])

        def wait(self):
            return 0

        def poll(self):
            return 0

    step = load_steps()[1]
    assert step.privilege == "root"
    result = StepRunner(popen=Proc, which=lambda _name: None).run(
        step,
        on_line=seen.append,
        password=password,
        prefer_pkexec=False,
        log_file=tmp_path / "step.log",
    )
    assert result.status == "ok"
    blob = "\n".join(seen)
    assert password not in blob
    assert "sk-or-v1-zzzzzzzzzzzz" not in blob
    assert "sudo" in seen[0]
    log_text = (tmp_path / "step.log").read_text(encoding="utf-8")
    assert password not in log_text


def test_runner_asks_for_a_password_instead_of_inventing_one():
    step = next(item for item in load_steps() if item.privilege == "root")
    with pytest.raises(NeedPassword):
        StepRunner(which=lambda _name: None).run(step, on_line=lambda _line: None, password=None, prefer_pkexec=False)


def test_failed_command_is_failed(tmp_path: Path):
    class Proc:
        def __init__(self, argv, **kwargs):
            self.pid = 7
            self.stdin = None
            self.stdout = iter(["boom\n"])

        def wait(self):
            return 3

        def poll(self):
            return 3

    step = load_steps()[0]
    result = StepRunner(popen=Proc).run(step, on_line=lambda _line: None, log_file=tmp_path / "a.log")
    assert result.status == "failed"
    assert result.returncode == 3


class _Stdin:
    def write(self, text):
        return len(text)

    def flush(self):
        return None

    def close(self):
        return None


class _Body:
    def __init__(self, payload: bytes, status: int = 200):
        self._payload = payload
        self.status = status

    def read(self, _n):
        return self._payload

    def getcode(self):
        return self.status

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


def test_openrouter_probe_and_telegram_error_hide_the_secret():
    token = "sk-or-v1-" + ("k" * 20)
    bot = "123456789:" + ("A" * 30)

    def opener(request, timeout=20):
        url = request.full_url
        if url.endswith("/api/v1/key"):
            return _Body(b'{"data":{"label":"ok"}}')
        if url.endswith("/api/v1/models"):
            return _Body(b'{"data":[{"id":"deepseek/deepseek-v4.1-flash-1017"}]}')
        if "api.telegram.org" in url:
            raise HTTPError(url, 401, "no", hdrs=None, fp=io.BytesIO(b"{}"))
        raise AssertionError(url)

    provider = next(item for item in load_providers() if item.id == "openrouter")
    ok = probe_provider(provider, api_key=token, model="deepseek/deepseek-v4.1-flash-1017", opener=opener)
    assert ok.status == "pass"
    assert token not in ok.detail
    missing = probe_provider(provider, api_key=token, model="deepseek/not-a-real-model", opener=opener)
    assert missing.status == "fail"
    assert token not in missing.detail
    bad = probe_gateway("telegram", bot, opener)
    assert bad.status == "fail"
    assert bot not in bad.detail
    assert "401" in bad.detail


def test_health_config_and_env_mode(tmp_path: Path):
    config = tmp_path / "config.yaml"
    env = tmp_path / ".env"
    config.write_text("model:\n  provider: openrouter\n  default: deepseek/example\n", encoding="utf-8")
    env.write_text("OPENROUTER_API_KEY=sk-or-v1-health\n", encoding="utf-8")
    env.chmod(0o644)
    checks = [item for item in load_checks() if item.kind in {"config", "env_mode"}]

    def opener(request, timeout=20):
        return _Body(b'{"data":{}}')

    report = run_checks(checks, config_file=config, env_file=env, urlopen_fn=opener)
    by_id = {item.id: item for item in report.results}
    assert by_id["config-yaml"].status == "pass"
    assert by_id["env-mode"].status == "fail"
    assert "sk-or" not in by_id["config-yaml"].detail


def test_progress_file_drops_a_password(tmp_path: Path):
    path = tmp_path / "progress.json"
    save_progress({"password": "super-secret-value", "language": "th", "steps": {"check-os": {"status": "ok"}}}, path)
    text = path.read_text(encoding="utf-8")
    assert "super-secret-value" not in text
    loaded = load_progress(path)
    assert loaded["language"] == "th"
    assert loaded["steps"]["check-os"]["status"] == "ok"


def test_nous_probe_does_not_invent_a_key():
    provider = next(item for item in load_providers() if item.id == "nous")
    probe = probe_provider(provider, api_key="should-not-be-sent")
    assert probe.status == "skipped"
    assert "hermes setup --portal" in probe.detail
    assert "should-not-be-sent" not in probe.detail


def test_setting_type_matches_yaml():
    for setting in load_settings():
        assert isinstance(setting, Setting)
        if setting.type == "choice" and setting.default not in (None, ""):
            assert str(setting.default) in setting.choices
