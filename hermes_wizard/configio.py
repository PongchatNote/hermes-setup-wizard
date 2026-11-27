"""Read and write Hermes config.yaml and .env.

Secrets belong in ``.env`` (mode 0600), which is what Hermes reads. Non-secret
settings belong in ``config.yaml``. This module never prints values.
"""

from __future__ import annotations

import os
import re
import stat
import tempfile
from pathlib import Path
from typing import Any

import yaml

from hermes_wizard.catalog import Setting, is_denied_key, key_is_secret_name

UNSET = object()

_ENV_LINE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$")
_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")


class ConfigError(ValueError):
    pass


def ensure_hermes_home(home: Path) -> None:
    home.mkdir(parents=True, exist_ok=True)
    if home.stat().st_mode & 0o077:
        # Tighten a home this wizard created or that is world/group readable.
        # Hermes stores credentials beside config.yaml.
        try:
            os.chmod(home, 0o700)
        except OSError:
            pass


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path} is not a YAML mapping")
    return data


def save_yaml(path: Path, data: dict[str, Any]) -> None:
    ensure_hermes_home(path.parent)
    _atomic_write(path, yaml.safe_dump(data, sort_keys=False, allow_unicode=True), mode=0o600)


def get_dotted(data: dict[str, Any], key: str) -> Any:
    current: Any = data
    for part in key.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def set_dotted(data: dict[str, Any], key: str, value: Any) -> None:
    parts = key.split(".")
    current = data
    for part in parts[:-1]:
        nxt = current.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            current[part] = nxt
        current = nxt
    current[parts[-1]] = value


def unset_dotted(data: dict[str, Any], key: str) -> None:
    parts = key.split(".")
    stack: list[tuple[dict[str, Any], str]] = []
    current: Any = data
    for part in parts[:-1]:
        if not isinstance(current, dict) or part not in current:
            return
        stack.append((current, part))
        current = current[part]
    if isinstance(current, dict):
        current.pop(parts[-1], None)
    for parent, part in reversed(stack):
        child = parent.get(part)
        if child == {} or child is None:
            parent.pop(part, None)


def read_env(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = _ENV_LINE.match(line)
        if not match:
            continue
        values[match.group(1)] = _unquote(match.group(2))
    return values


def env_has(path: Path, key: str) -> bool:
    return key in read_env(path)


def upsert_env(path: Path, key: str, value: str) -> None:
    if is_denied_key(key):
        raise ConfigError(f"refusing to write {key}")
    if "\n" in value or "\r" in value:
        raise ConfigError("env values cannot contain newlines")
    ensure_hermes_home(path.parent)
    lines: list[str] = []
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
    rendered = f"{key}={_quote(value)}"
    replaced = False
    output: list[str] = []
    for line in lines:
        match = _ENV_LINE.match(line.strip())
        if match and match.group(1) == key:
            if not replaced:
                output.append(rendered)
                replaced = True
            continue
        output.append(line)
    if not replaced:
        if output and output[-1] != "":
            output.append(rendered)
        else:
            # Drop a trailing blank line then append.
            while output and output[-1] == "":
                output.pop()
            output.append(rendered)
    text = "\n".join(output)
    if text and not text.endswith("\n"):
        text += "\n"
    _atomic_write(path, text, mode=0o600)


def remove_env(path: Path, key: str) -> None:
    if not path.exists():
        return
    output: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _ENV_LINE.match(line.strip())
        if match and match.group(1) == key:
            continue
        output.append(line)
    text = "\n".join(output)
    if text and not text.endswith("\n"):
        text += "\n"
    _atomic_write(path, text, mode=0o600)


def file_mode(path: Path) -> int | None:
    if not path.exists():
        return None
    return stat.S_IMODE(path.stat().st_mode)


def validate_key(key: str) -> None:
    if not _KEY_RE.match(key):
        raise ConfigError("key must be letters, numbers, and dots")
    if is_denied_key(key):
        raise ConfigError(f"refusing to write {key}")


def coerce(setting: Setting, raw: Any) -> Any:
    """Convert a widget value into the type Hermes stores.

    An empty optional value returns ``UNSET`` so the key is removed and the
    Hermes default applies.
    """
    if setting.type == "bool":
        if isinstance(raw, bool):
            return raw
        text = str(raw).strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
        raise ConfigError(f"{setting.key} must be true or false")

    if setting.type in {"str", "text", "choice"}:
        text = "" if raw is None else str(raw).strip()
        if setting.type == "choice" and text and setting.choices and text not in setting.choices:
            raise ConfigError(f"{setting.key} must be one of: {', '.join(setting.choices)}")
        if text == "":
            return UNSET if setting.optional else ""
        if setting.type == "choice" and text in {"true", "false"} and "auto" not in setting.choices:
            return text == "true"
        if setting.type == "choice" and text in {"true", "false"} and "auto" in setting.choices:
            return text == "true"
        return text

    if setting.type == "int":
        text = "" if raw is None else str(raw).strip()
        if text == "":
            return UNSET
        try:
            return int(text)
        except ValueError as exc:
            raise ConfigError(f"{setting.key} must be an integer") from exc

    if setting.type == "float":
        text = "" if raw is None else str(raw).strip()
        if text == "":
            return UNSET
        try:
            return float(text)
        except ValueError as exc:
            raise ConfigError(f"{setting.key} must be a number") from exc

    raise ConfigError(f"unknown type for {setting.key}")


def format_loaded(setting: Setting, value: Any) -> str:
    if value is None:
        if setting.default is None:
            return ""
        value = setting.default
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def apply_yaml_updates(path: Path, updates: dict[str, Any]) -> list[str]:
    """Merge dotted keys into config.yaml. ``UNSET`` removes a key."""
    for key in updates:
        validate_key(key)
        if key_is_secret_name(key.split(".")[-1]) and "." not in key:
            raise ConfigError(f"{key} looks like a secret and must go in .env")
    data = load_yaml(path)
    changed: list[str] = []
    for key, value in updates.items():
        if value is UNSET:
            unset_dotted(data, key)
        else:
            set_dotted(data, key, value)
        changed.append(key)
    save_yaml(path, data)
    return changed


def _quote(value: str) -> str:
    if value == "":
        return '""'
    if re.search(r'[\s#"\'\\]', value):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        inner = value[1:-1]
        if value[0] == '"':
            return inner.replace('\\"', '"').replace("\\\\", "\\")
        return inner
    return value


def _atomic_write(path: Path, text: str, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
        os.chmod(path, mode)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
