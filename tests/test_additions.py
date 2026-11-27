"""Non-GUI coverage for Docker mode, quick setup, ports, allowlists, and backup."""

from io import BytesIO
from pathlib import Path

import tarfile

from hermes_wizard.health import run_checks
from hermes_wizard.catalog import load_checks, load_steps
from hermes_wizard.progress import load as load_progress
from hermes_wizard.progress import save as save_progress
from hermes_wizard.runtime import (
    allowlist_gaps,
    backup_home,
    cli_chat_argv,
    exposure,
    flow_pages,
    gateway_run_argv,
    listeners_for,
    required_step_ids,
    restore_home,
    update_hermes_commands,
)


def test_defaults_stay_native_and_full():
    assert flow_pages("full", "telegram")[0:3] == ("install", "provider", "cli-chat")
    assert "telegram" in flow_pages("full", "line")
    assert flow_pages("quick", "line") == ("install", "provider", "cli-chat", "line", "health")
    assert required_step_ids("native") == ("check-os", "apt-prereqs", "install-hermes", "verify-cli")
    assert "install-docker" in required_step_ids("docker")
    assert "install-hermes" not in required_step_ids("docker")


def test_docker_gateway_does_not_publish_public_ports(tmp_path: Path):
    argv = gateway_run_argv(tmp_path, uid=1000, gid=1000)
    text = " ".join(argv)
    assert "nousresearch/hermes-agent" in argv
    assert f"{tmp_path.resolve()}:/opt/data" in argv
    assert "gateway" in argv and "run" in argv
    assert "-p" not in argv
    assert "0.0.0.0" not in text
    native = cli_chat_argv("native", "Reply with exactly: pong", home=tmp_path)
    assert native[:3] == ["hermes", "chat", "-q"]
    docker = cli_chat_argv("docker", "Reply with exactly: pong", home=tmp_path)
    assert docker[:3] == ["docker", "run", "--rm"]
    assert "chat" in docker and "-q" in docker
    commands = update_hermes_commands("docker", home=tmp_path, uid=1000, gid=1000)
    assert commands[0][:3] == ["docker", "pull", "nousresearch/hermes-agent:latest"]
    assert commands[1][:3] == ["docker", "rm", "-f"]
    assert "-p" not in commands[2]
    assert update_hermes_commands("native", home=tmp_path, uid=1, gid=1) == [["hermes", "update"]]


def test_steps_split_by_mode():
    steps = {step.id: step for step in load_steps()}
    assert "docker" in steps["check-os"].modes and "native" in steps["check-os"].modes
    assert steps["install-hermes"].modes == ["native"]
    assert steps["docker-gateway"].modes == ["docker"]
    assert "nousresearch/hermes-agent" in steps["docker-gateway"].shell
    assert "-p 8642" not in steps["docker-gateway"].shell
    assert "-p 9119" not in steps["docker-gateway"].shell


def test_port_exposure_accepts_only_loopback():
    tcp = (
        "  sl  local_address rem_address   st\n"
        "   0: 0100007F:21C2 00000000:0000 0A\n"  # 127.0.0.1:8642
        "   1: 00000000:239F 00000000:0000 0A\n"  # 0.0.0.0:9119
    )
    assert listeners_for(8642, tcp) == ["127.0.0.1"]
    assert exposure(listeners_for(8642, tcp)) == "loopback"
    assert exposure(listeners_for(9119, tcp)) == "public"
    assert exposure(listeners_for(1, tcp)) == "closed"
    tcp6 = "  sl  local_address rem_address   st\n" "   0: 00000000000000000000000001000000:21C2 00000000000000000000000000000000:0000 0A\n"
    assert listeners_for(8642, "", tcp6) == ["::1"]
    checks = [item for item in load_checks() if item.kind == "loopback_ports"]
    report = run_checks(checks, tcp_text=tcp, tcp6_text="")
    assert report.results[0].status == "fail"
    assert "9119" in report.results[0].detail
    quiet = "  sl  local_address rem_address   st\n" "   0: 0100007F:21C2 00000000:0000 0A\n"
    ok = run_checks(checks, tcp_text=quiet, tcp6_text="")
    assert ok.results[0].status == "pass"


def test_allowlists_fail_when_an_enabled_bot_has_no_ids():
    config = {"platforms": {"telegram": {"enabled": True}, "line": {"enabled": True}, "discord": {"enabled": False}}}
    gaps = allowlist_gaps(config, {"LINE_ALLOWED_GROUPS": "C0123"})
    assert [name for name, _reason in gaps] == ["telegram"]
    assert allowlist_gaps(config, {"TELEGRAM_ALLOWED_USERS": "123", "LINE_ALLOWED_USERS": "Uabc"}) == []
    assert "TELEGRAM_ALLOWED_USERS" in gaps[0][1]


def test_allowlist_check_fix_page(tmp_path: Path):
    config = tmp_path / "config.yaml"
    env = tmp_path / ".env"
    config.write_text("platforms:\n  discord:\n    enabled: true\n", encoding="utf-8")
    env.write_text("DISCORD_BOT_TOKEN=placeholder\n", encoding="utf-8")
    env.chmod(0o600)
    check = next(item for item in load_checks() if item.id == "allowlists")
    report = run_checks([check], config_file=config, env_file=env, tcp_text="", tcp6_text="")
    assert report.results[0].status == "fail"
    assert report.results[0].fix_page == "discord"
    assert "DISCORD_ALLOWED_USERS" in report.results[0].detail


def test_backup_is_mode_600_and_restores(tmp_path: Path):
    home = tmp_path / "hermes"
    home.mkdir()
    (home / "config.yaml").write_text("model:\n  provider: openrouter\n", encoding="utf-8")
    secret = home / ".env"
    secret.write_text("OPENROUTER_API_KEY=sk-or-v1-backup\n", encoding="utf-8")
    archive = backup_home(home, tmp_path / "backups")
    assert archive.name.startswith("hermes-")
    assert archive.stat().st_mode & 0o077 == 0
    home_copy = tmp_path / "restored"
    restore_home(archive, home_copy)
    assert "openrouter" in (home_copy / "config.yaml").read_text(encoding="utf-8")
    assert "sk-or-v1-backup" in (home_copy / ".env").read_text(encoding="utf-8")


def test_restore_rejects_an_archive_inside_the_data_dir(tmp_path: Path):
    home = tmp_path / "hermes"
    home.mkdir()
    (home / "config.yaml").write_text("ok: true\n", encoding="utf-8")
    archive = backup_home(home, home / "nested")
    try:
        restore_home(archive, home)
    except ValueError as exc:
        assert "inside" in str(exc)
    else:
        raise AssertionError("restore should refuse an archive stored inside ~/.hermes")


def test_progress_keeps_mode_and_drops_secrets(tmp_path: Path):
    path = tmp_path / "progress.json"
    save_progress(
        {
            "password": "super-secret-value",
            "install_mode": "docker",
            "setup_profile": "quick",
            "quick_bot": "line",
            "health_status": "pass",
            "language": "th",
        },
        path,
    )
    text = path.read_text(encoding="utf-8")
    assert "super-secret-value" not in text
    loaded = load_progress(path)
    assert loaded["install_mode"] == "docker"
    assert loaded["setup_profile"] == "quick"
    assert loaded["quick_bot"] == "line"
    assert loaded["health_status"] == "pass"


def test_bad_tar_member_is_not_extracted(tmp_path: Path):
    archive = tmp_path / "evil.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        payload = b"nope"
        info = tarfile.TarInfo("../escaped.txt")
        info.size = len(payload)
        tar.addfile(info, BytesIO(payload))
    home = tmp_path / "hermes"
    try:
        restore_home(archive, home)
    except Exception:
        pass
    assert not (tmp_path / "escaped.txt").exists()
