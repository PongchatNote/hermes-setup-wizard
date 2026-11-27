"""Native and Docker command lines, port exposure, allowlists, backup.

The Docker shape follows the Hermes Docker guide: image
``nousresearch/hermes-agent``, host data directory mounted at ``/opt/data``,
and upgrades via ``docker pull`` plus recreating the container. Ports 8642
and 9119 are not published. The guide's ``-p 8642:8642`` listens on every
interface; this wizard leaves them unpublished, and the final check fails if
either port is later bound somewhere other than loopback.
"""

from __future__ import annotations

import os
import tarfile
from datetime import datetime
from pathlib import Path
from typing import Iterable

IMAGE = "nousresearch/hermes-agent"
IMAGE_LATEST = "nousresearch/hermes-agent:latest"
CONTAINER = "hermes"
API_PORT = 8642
DASHBOARD_PORT = 9119
LOOPBACK = frozenset({"127.0.0.1", "::1"})

# Env names from the messaging guide. Any one non-empty value satisfies the
# platform. Line accepts a user, a group, or a room.
ALLOWLIST_ANY: dict[str, tuple[str, ...]] = {
    "telegram": ("TELEGRAM_ALLOWED_USERS",),
    "discord": ("DISCORD_ALLOWED_USERS",),
    "line": ("LINE_ALLOWED_USERS", "LINE_ALLOWED_GROUPS", "LINE_ALLOWED_ROOMS"),
    "slack": ("SLACK_ALLOWED_USERS",),
    "signal": ("SIGNAL_ALLOWED_USERS",),
    "matrix": ("MATRIX_ALLOWED_USERS",),
    "email": ("EMAIL_ALLOWED_USERS",),
    "whatsapp-cloud": ("WHATSAPP_CLOUD_ALLOWED_USERS",),
    "whatsapp_cloud": ("WHATSAPP_CLOUD_ALLOWED_USERS",),
    "teams": ("TEAMS_ALLOWED_USERS",),
    "ntfy": ("NTFY_ALLOWED_USERS",),
}


def flow_pages(profile: str, quick_bot: str) -> tuple[str, ...]:
    """Pages on the progress strip. Full is the original path plus the CLI test."""
    if profile == "quick":
        bot = quick_bot if quick_bot in {"telegram", "discord", "line"} else "telegram"
        return ("install", "provider", "cli-chat", bot, "health")
    return ("install", "provider", "cli-chat", "telegram", "discord", "line", "health")


def required_step_ids(mode: str) -> tuple[str, ...]:
    if mode == "docker":
        return ("check-os", "install-docker", "docker-group", "docker-pull", "docker-gateway")
    return ("check-os", "apt-prereqs", "install-hermes", "verify-cli")


def data_mount(home: Path) -> str:
    return f"{home.resolve()}:/opt/data"


def _docker(prefix: list[str] | None) -> list[str]:
    return list(prefix) if prefix else ["docker"]


def gateway_run_argv(home: Path, uid: int, gid: int, *, docker: list[str] | None = None) -> list[str]:
    """Background gateway. No ``-p`` flag, so 8642 and 9119 are not published."""
    return [
        *_docker(docker),
        "run",
        "-d",
        "--name",
        CONTAINER,
        "--restart",
        "unless-stopped",
        "-e",
        f"PUID={uid}",
        "-e",
        f"PGID={gid}",
        "-v",
        data_mount(home),
        IMAGE,
        "gateway",
        "run",
    ]


def hermes_argv(mode: str, args: list[str], *, home: Path, docker: list[str] | None = None) -> list[str]:
    """How to run a hermes subcommand for the selected install path."""
    if mode == "docker":
        if args[:1] == ["chat"]:
            return [*_docker(docker), "run", "--rm", "-v", data_mount(home), IMAGE, *args]
        return [*_docker(docker), "exec", CONTAINER, "hermes", *args]
    return ["hermes", *args]


def cli_chat_argv(mode: str, prompt: str, *, home: Path, docker: list[str] | None = None) -> list[str]:
    """One-shot chat. Docker docs list ``chat -q`` as an entrypoint form."""
    text = prompt.strip()
    if not text or "\n" in text or "\r" in text:
        raise ValueError("The test prompt must be one line.")
    return hermes_argv(mode, ["chat", "-q", text], home=home, docker=docker)


def update_hermes_commands(
    mode: str,
    *,
    home: Path,
    uid: int,
    gid: int,
    docker: list[str] | None = None,
) -> list[list[str]]:
    """Native ``hermes update``, or the documented pull + rm + run sequence."""
    if mode != "docker":
        return [["hermes", "update"]]
    return [
        [*_docker(docker), "pull", IMAGE_LATEST],
        [*_docker(docker), "rm", "-f", CONTAINER],
        gateway_run_argv(home, uid, gid, docker=docker),
    ]


def parse_proc_net(text: str, *, ipv6: bool) -> list[tuple[str, int]]:
    """Listening addresses from ``/proc/net/tcp`` or ``tcp6``. State 0A is LISTEN."""
    found: list[tuple[str, int]] = []
    for line in text.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 4:
            continue
        if parts[3].upper() != "0A":
            continue
        local = parts[1]
        if ":" not in local:
            continue
        ip_hex, port_hex = local.rsplit(":", 1)
        try:
            port = int(port_hex, 16)
            addr = _decode_ip(ip_hex, ipv6=ipv6)
        except ValueError:
            continue
        found.append((addr, port))
    return found


def listeners_for(port: int, tcp: str, tcp6: str = "") -> list[str]:
    rows = parse_proc_net(tcp, ipv6=False) + parse_proc_net(tcp6, ipv6=True)
    return [addr for addr, found in rows if found == port]


def exposure(addresses: Iterable[str]) -> str:
    """``closed``, ``loopback``, or ``public``."""
    items = list(addresses)
    if not items:
        return "closed"
    if all(_is_loopback(addr) for addr in items):
        return "loopback"
    return "public"


def enabled_platforms(config: dict | None) -> list[str]:
    platforms = (config or {}).get("platforms") or {}
    if not isinstance(platforms, dict):
        return []
    names: list[str] = []
    for name, block in platforms.items():
        if isinstance(block, dict) and block.get("enabled") is True:
            names.append(str(name))
    return names


def allowlist_gaps(config: dict | None, env: dict[str, str]) -> list[tuple[str, str]]:
    """Enabled platforms whose allowlist env vars are all empty.

    Returns ``(platform id, reason)``. ``GATEWAY_ALLOW_ALL_USERS`` does not
    count: the messaging guide marks that as a dev-only escape hatch.
    """
    gaps: list[tuple[str, str]] = []
    for name in enabled_platforms(config):
        keys = ALLOWLIST_ANY.get(name)
        if not keys:
            gaps.append((name, f"{name} is enabled and this wizard has no allowlist field for it"))
            continue
        if not any(_filled(env.get(key, "")) for key in keys):
            shown = ", ".join(keys)
            gaps.append((name, f"{name} is enabled and {shown} is empty"))
    return gaps


def backup_home(home: Path, dest_dir: Path, *, now: datetime | None = None) -> Path:
    """Archive ``home`` to a timestamped ``.tar.gz`` and chmod it 0600.

    The archive contains credentials. It is not world-readable.
    """
    if not home.is_dir():
        raise FileNotFoundError(f"missing {home}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    target = dest_dir / f"hermes-{stamp}.tar.gz"
    with tarfile.open(target, "w:gz") as archive:
        archive.add(home, arcname="hermes", filter=_tar_filter)
    os.chmod(target, 0o600)
    return target


def restore_home(archive: Path, home: Path) -> None:
    """Replace ``home`` with the ``hermes/`` tree inside a wizard backup."""
    if archive.suffixes[-2:] != [".tar", ".gz"] and not archive.name.endswith(".tar.gz"):
        raise ValueError("Restore only accepts a .tar.gz archive.")
    resolved_archive = archive.resolve()
    home.mkdir(parents=True, exist_ok=True)
    if _is_relative_to(resolved_archive, home.resolve()):
        raise ValueError("The archive is inside the Hermes data directory. Move it out first.")
    staging = home.parent / f".hermes-restore-{os.getpid()}"
    if staging.exists():
        raise FileExistsError(staging)
    staging.mkdir(mode=0o700)
    try:
        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(staging, filter="data")
        source = staging / "hermes"
        if not source.is_dir():
            raise ValueError("The archive does not contain a hermes/ directory.")
        # Swap into place: move existing home aside, then move the extracted tree.
        backup_aside = home.parent / f".hermes-before-restore-{os.getpid()}"
        home.rename(backup_aside)
        try:
            source.rename(home)
        except Exception:
            if not home.exists() and backup_aside.exists():
                backup_aside.rename(home)
            raise
        _rm_tree(backup_aside)
    finally:
        if staging.exists():
            _rm_tree(staging)


def _filled(value: str) -> bool:
    return bool(value.strip().strip(","))


def _is_loopback(addr: str) -> bool:
    return addr in LOOPBACK or addr.startswith("127.")


def _decode_ip(ip_hex: str, *, ipv6: bool) -> str:
    if not ipv6:
        if len(ip_hex) != 8:
            raise ValueError(ip_hex)
        raw = bytes.fromhex(ip_hex)
        return ".".join(str(b) for b in reversed(raw))
    if len(ip_hex) != 32:
        raise ValueError(ip_hex)
    # /proc/net/tcp6 stores each 32-bit word little-endian.
    words = [ip_hex[i : i + 8] for i in range(0, 32, 8)]
    pieces: list[str] = []
    for word in words:
        raw = bytes.fromhex(word)
        pieces.append(raw[::-1].hex())
    text = "".join(pieces)
    if set(text) == {"0"}:
        return "::"
    if text == "00000000000000000000000000000001":
        return "::1"
    return text


def _tar_filter(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
    if info.issym() or info.islnk():
        return info
    if info.isdir() or info.isfile():
        return info
    return None


def _rm_tree(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
        return
    for child in path.iterdir():
        _rm_tree(child)
    path.rmdir()


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False
