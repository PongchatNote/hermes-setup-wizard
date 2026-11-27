"""Health checks for an installed Hermes profile.

HTTP helpers never include request URLs in errors, because the Telegram test
puts the bot token in the path.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from hermes_wizard import configio
from hermes_wizard.catalog import Check
from hermes_wizard.paths import command_env, config_path, env_path
from hermes_wizard.redact import redact
from hermes_wizard.runtime import allowlist_gaps, exposure, hermes_argv, listeners_for
from hermes_wizard.secrets import load as load_secret
from hermes_wizard.secrets import status as secret_status

Urlopen = Callable[..., Any]


@dataclass
class CheckResult:
    id: str
    status: str  # pass | fail | skipped
    title_en: str
    title_th: str
    detail: str
    fix_page: str
    optional: bool = False


@dataclass
class HealthReport:
    results: list[CheckResult] = field(default_factory=list)

    @property
    def failed(self) -> list[CheckResult]:
        return [item for item in self.results if item.status == "fail"]


def run_checks(
    checks: list[Check],
    *,
    config_file: Path | None = None,
    env_file: Path | None = None,
    urlopen_fn: Urlopen | None = None,
    runner: Callable[[list[str]], subprocess.CompletedProcess] | None = None,
    install_mode: str = "native",
    tcp_text: str | None = None,
    tcp6_text: str | None = None,
) -> HealthReport:
    config_file = config_file or config_path()
    env_file = env_file or env_path()
    opener = urlopen_fn or urlopen
    report = HealthReport()
    config = _safe_config(config_file)
    for check in checks:
        report.results.append(
            _run_one(
                check,
                config=config,
                config_file=config_file,
                env_file=env_file,
                opener=opener,
                runner=runner,
                install_mode=install_mode,
                tcp_text=tcp_text,
                tcp6_text=tcp6_text,
            )
        )
    return report


def _run_one(
    check: Check,
    *,
    config: dict[str, Any] | None,
    config_file: Path,
    env_file: Path,
    opener: Urlopen,
    runner: Callable[[list[str]], subprocess.CompletedProcess] | None,
    install_mode: str = "native",
    tcp_text: str | None = None,
    tcp6_text: str | None = None,
) -> CheckResult:
    try:
        if check.kind == "command":
            return _command(check, runner)
        if check.kind == "hermes":
            return _hermes(check, runner, install_mode, env_file)
        if check.kind == "config":
            return _config(check, config, config_file)
        if check.kind == "env_mode":
            return _env_mode(check, env_file)
        if check.kind == "openrouter":
            return _openrouter(check, config, env_file, opener)
        if check.kind == "allowlists":
            return _allowlists(check, config, env_file)
        if check.kind == "loopback_ports":
            return _ports(check, tcp_text, tcp6_text)
        if check.kind == "telegram":
            return _token_api(check, env_file, opener, "telegram")
        if check.kind == "discord":
            return _token_api(check, env_file, opener, "discord")
        if check.kind == "line":
            return _token_api(check, env_file, opener, "line")
        if check.kind == "slack":
            return _token_api(check, env_file, opener, "slack")
        return _result(check, "fail", f"unknown check kind {check.kind}")
    except Exception as exc:  # a check bug should fail the row, not the page
        return _result(check, "fail", redact(str(exc)))


def _result(check: Check, status: str, detail: str) -> CheckResult:
    return CheckResult(
        id=check.id,
        status=status,
        title_en=check.title_en,
        title_th=check.title_th,
        detail=redact(detail),
        fix_page=check.fix_page,
        optional=check.optional,
    )


def _safe_config(path: Path) -> dict[str, Any] | None:
    try:
        return configio.load_yaml(path)
    except Exception:
        return None


def _command(
    check: Check,
    runner: Callable[[list[str]], subprocess.CompletedProcess] | None,
) -> CheckResult:
    script = check.shell or "false"
    run = runner or _default_run
    completed = run(["bash", "-lc", script])
    output = redact(((completed.stdout or "") + (completed.stderr or "")).strip())
    if completed.returncode == 0:
        return _result(check, "pass", output or "ok")
    return _result(check, "fail", output or f"exit {completed.returncode}")


def _hermes(
    check: Check,
    runner: Callable[[list[str]], subprocess.CompletedProcess] | None,
    install_mode: str,
    env_file: Path,
) -> CheckResult:
    home = env_file.parent
    argv = hermes_argv(install_mode, check.args or ["--version"], home=home)
    run = runner or _default_run
    completed = run(argv)
    output = redact(((completed.stdout or "") + (completed.stderr or "")).strip())
    if completed.returncode == 0:
        return _result(check, "pass", output[:2000] or "ok")
    return _result(check, "fail", (output or f"exit {completed.returncode}")[:2000])


def _allowlists(check: Check, config: dict[str, Any] | None, env_file: Path) -> CheckResult:
    env = {}
    if env_file.exists():
        env = configio.read_env(env_file)
    gaps = allowlist_gaps(config, env)
    if not gaps:
        return _result(check, "pass", "Every enabled gateway has an allowlist.")
    lines = [reason for _name, reason in gaps]
    result = _result(check, "fail", "; ".join(lines))
    first = gaps[0][0]
    aliases = {"whatsapp_cloud": "whatsapp-cloud"}
    page = aliases.get(first, first)
    result.fix_page = page if page in {"telegram", "discord", "line"} else f"gateway:{page}"
    return result


def _ports(check: Check, tcp_text: str | None, tcp6_text: str | None) -> CheckResult:
    ports = check.ports or [8642, 9119]
    if tcp_text is None:
        tcp_text = _read_proc("/proc/net/tcp")
        tcp6_text = _read_proc("/proc/net/tcp6")
    problems: list[str] = []
    notes: list[str] = []
    for port in ports:
        addresses = listeners_for(port, tcp_text or "", tcp6_text or "")
        state = exposure(addresses)
        if state == "public":
            problems.append(f"port {port} is listening on {', '.join(addresses)}")
        elif state == "loopback":
            notes.append(f"port {port} is only on loopback")
        else:
            notes.append(f"port {port} is not listening")
    if problems:
        return _result(
            check,
            "fail",
            "; ".join(problems) + ". Only 127.0.0.1 or ::1 is accepted. "
            "The Docker guide's -p 8642:8642 publishes every interface; use 127.0.0.1:8642:8642.",
        )
    return _result(check, "pass", "; ".join(notes))


def _read_proc(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _default_run(argv: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        argv,
        check=False,
        capture_output=True,
        text=True,
        env=command_env(),
        timeout=90,
    )


def _config(check: Check, config: dict[str, Any] | None, path: Path) -> CheckResult:
    if not path.exists():
        return _result(check, "fail", f"missing {path}")
    if config is None:
        return _result(check, "fail", f"{path.name} is not valid YAML")
    provider = configio.get_dotted(config, "model.provider")
    model = configio.get_dotted(config, "model.default")
    if model in (None, ""):
        model = configio.get_dotted(config, "model.model")
    if not provider or not model:
        return _result(
            check,
            "fail",
            "model.provider and model.default (or model.model) need a value",
        )
    return _result(check, "pass", f"provider {provider}, model {model}")


def _env_mode(check: Check, env_file: Path) -> CheckResult:
    if not env_file.exists():
        return _result(check, "fail", f"missing {env_file}")
    mode = stat.S_IMODE(env_file.stat().st_mode)
    if mode != 0o600:
        return _result(check, "fail", f"mode is {mode:04o}, Hermes expects 0600")
    return _result(check, "pass", "mode 0600")


def _openrouter(
    check: Check,
    config: dict[str, Any] | None,
    env_file: Path,
    opener: Urlopen,
) -> CheckResult:
    provider = ""
    if config:
        provider = str(configio.get_dotted(config, "model.provider") or "")
    present = secret_status("OPENROUTER_API_KEY", env_file) != "missing"
    if not present:
        if provider in {"", "openrouter"}:
            return _result(check, "fail", "OPENROUTER_API_KEY is not stored")
        return _result(check, "skipped", f"provider is {provider}; OpenRouter key not set")
    token = load_secret("OPENROUTER_API_KEY", env_file) or ""
    status, detail = _request(
        opener,
        "https://openrouter.ai/api/v1/key",
        {"Authorization": f"Bearer {token}"},
    )
    if status == 200:
        return _result(check, "pass", "OpenRouter accepted the key")
    return _result(check, "fail", f"OpenRouter HTTP {status}: {detail}")


def _token_api(check: Check, env_file: Path, opener: Urlopen, platform: str) -> CheckResult:
    spec = {
        "telegram": ("TELEGRAM_BOT_TOKEN", "telegram"),
        "discord": ("DISCORD_BOT_TOKEN", "discord"),
        "line": ("LINE_CHANNEL_ACCESS_TOKEN", "line"),
        "slack": ("SLACK_BOT_TOKEN", "slack"),
    }[platform]
    key, _name = spec
    if secret_status(key, env_file) == "missing":
        return _result(check, "skipped", f"{key} is not stored")
    token = load_secret(key, env_file) or ""
    if platform == "telegram":
        status, detail = _request(opener, f"https://api.telegram.org/bot{token}/getMe", {})
        ok = status == 200 and '"ok": true' in detail.replace(" ", "").lower() or (
            status == 200 and '"ok":true' in detail.replace(" ", "").lower()
        )
        # Parse properly.
        if status == 200:
            try:
                payload = json.loads(detail)
                ok = bool(payload.get("ok"))
                user = (payload.get("result") or {}).get("username", "")
                detail = f"Telegram bot @{user}" if user else "Telegram getMe ok"
            except json.JSONDecodeError:
                ok = False
                detail = "Telegram returned a body that is not JSON"
        if ok:
            return _result(check, "pass", detail)
        return _result(check, "fail", f"Telegram HTTP {status}")
    if platform == "discord":
        status, detail = _request(
            opener,
            "https://discord.com/api/v10/users/@me",
            {"Authorization": f"Bot {token}"},
        )
        if status == 200:
            try:
                payload = json.loads(detail)
                name = payload.get("username", "")
                return _result(check, "pass", f"Discord bot {name}".strip())
            except json.JSONDecodeError:
                return _result(check, "pass", "Discord accepted the token")
        return _result(check, "fail", f"Discord HTTP {status}. Message Content Intent is still required for the bot to stay online.")
    if platform == "line":
        status, _detail = _request(
            opener,
            "https://api.line.me/v2/bot/info",
            {"Authorization": f"Bearer {token}"},
        )
        if status == 200:
            return _result(check, "pass", "LINE accepted the channel access token")
        return _result(check, "fail", f"LINE HTTP {status}")
    status, detail = _request(
        opener,
        "https://slack.com/api/auth.test",
        {"Authorization": f"Bearer {token}"},
        method="POST",
        data=b"",
    )
    if status == 200:
        try:
            payload = json.loads(detail)
        except json.JSONDecodeError:
            payload = {}
        if payload.get("ok"):
            return _result(check, "pass", f"Slack team {payload.get('team', '')}".strip())
        return _result(check, "fail", "Slack auth.test returned ok=false")
    return _result(check, "fail", f"Slack HTTP {status}")


def _request(
    opener: Urlopen,
    url: str,
    headers: dict[str, str],
    *,
    method: str = "GET",
    data: bytes | None = None,
) -> tuple[int, str]:
    request = Request(url, data=data, headers={"User-Agent": "hermes-setup-wizard", **headers}, method=method)
    try:
        with opener(request, timeout=20) as response:
            body = response.read(8192).decode("utf-8", "replace")
            code = getattr(response, "status", None) or response.getcode()
            return int(code), body
    except HTTPError as exc:
        try:
            body = exc.read(2048).decode("utf-8", "replace")
        except Exception:
            body = ""
        # Do not include exc (it contains the URL) in the return value.
        return int(exc.code), redact(body)[:500]
    except URLError as exc:
        reason = getattr(exc, "reason", "")
        return 0, redact(str(reason))[:300]
    except TimeoutError:
        return 0, "timed out"
    except OSError as exc:
        return 0, redact(exc.__class__.__name__)


def chmod_env_if_loose(env_file: Path) -> bool:
    """Tighten .env to 0600 when it exists and is looser. Returns True if changed."""
    if not env_file.exists():
        return False
    mode = stat.S_IMODE(env_file.stat().st_mode)
    if mode == 0o600:
        return False
    os.chmod(env_file, 0o600)
    return True
