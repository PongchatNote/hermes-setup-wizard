"""Filesystem locations used by the wizard."""

from __future__ import annotations

import os
from pathlib import Path


def package_dir() -> Path:
    return Path(__file__).resolve().parent


def data_dir() -> Path:
    return package_dir() / "data"


def repo_root() -> Path:
    """Directory that contains this checkout, walking up from the package."""
    start = package_dir()
    for candidate in [start, *start.parents]:
        if (candidate / ".git").exists() and (candidate / "install.sh").exists():
            return candidate
    return package_dir().parent


def hermes_home() -> Path:
    override = os.environ.get("HERMES_HOME", "").strip()
    if override:
        return Path(os.path.expanduser(override)).resolve()
    return Path.home() / ".hermes"


def config_path() -> Path:
    return hermes_home() / "config.yaml"


def env_path() -> Path:
    return hermes_home() / ".env"


def state_dir() -> Path:
    root = os.environ.get("XDG_DATA_HOME", "").strip()
    base = Path(root).expanduser() if root else Path.home() / ".local" / "share"
    path = base / "hermes-setup-wizard"
    path.mkdir(parents=True, exist_ok=True)
    return path


def progress_path() -> Path:
    return state_dir() / "progress.json"


def log_dir() -> Path:
    path = state_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def hermes_bin_dir() -> Path:
    return Path.home() / ".local" / "bin"


def command_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """Environment for Hermes commands, with the user launcher on PATH.

    Secret values already in the parent environment are left as the user set
    them. The wizard itself never injects API keys into this mapping.
    """
    env = dict(base or os.environ)
    bin_dir = str(hermes_bin_dir())
    current = env.get("PATH", "")
    parts = current.split(os.pathsep) if current else []
    if bin_dir not in parts:
        env["PATH"] = bin_dir + (os.pathsep + current if current else "")
    env.setdefault("DEBIAN_FRONTEND", "noninteractive")
    return env
