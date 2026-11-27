"""Write provider and setting values the way Hermes reads them.

Secrets go to the keyring and to ~/.hermes/.env (mode 0600). Other values go
to config.yaml. Callers get back key names only, never the secret text.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from hermes_wizard import configio, secrets
from hermes_wizard.catalog import Provider, Setting, is_denied_key, key_is_secret_name
from hermes_wizard.configio import UNSET, ConfigError

_PROVIDER_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")

# Documented values for this no-GPU desktop. Applied only when the user asks.
LOW_SPEC_PRESET: dict[str, Any] = {
    "terminal.backend": "local",
    "timezone": "Asia/Bangkok",
    "approvals.mode": "smart",
    "provider_routing.sort": "price",
}


def save_settings(
    items: list[tuple[Setting, Any]],
    *,
    config_file: Path,
    env_file: Path,
) -> list[str]:
    yaml_updates: dict[str, Any] = {}
    changed: list[str] = []
    for setting, raw in items:
        if setting.secret and not isinstance(raw, bool) and str(raw).strip() == "":
            # An empty secret box means "leave the stored key alone".
            continue
        value = configio.coerce(setting, raw)
        if setting.storage == "env" or setting.secret:
            _write_env(setting.key, value, secret=setting.secret, env_file=env_file)
        else:
            yaml_updates[setting.key] = value
        changed.append(setting.key)
    if yaml_updates:
        configio.apply_yaml_updates(config_file, yaml_updates)
    return changed


def save_provider(
    provider: Provider,
    *,
    model: str,
    api_key: str,
    base_url: str,
    context_length: str,
    typed_provider: str,
    typed_key_env: str,
    also_preset: bool,
    config_file: Path,
    env_file: Path,
) -> list[str]:
    provider_id = typed_provider.strip() if provider.allow_typed_provider else provider.config_provider
    if not provider_id or not _PROVIDER_ID.match(provider_id):
        raise ConfigError("Provider id must match the Hermes guide (letters, numbers, hyphen).")
    model_id = model.strip()
    if provider.id != "nous" and not model_id:
        raise ConfigError("Choose a model id.")

    yaml_updates: dict[str, Any] = {"model.provider": provider_id}
    if model_id:
        yaml_updates["model.default"] = model_id
    elif provider.id == "nous":
        yaml_updates["model.default"] = UNSET

    if provider.base_in_config:
        chosen = base_url.strip() or provider.default_base_url
        if chosen:
            _check_base(chosen)
            yaml_updates["model.base_url"] = chosen
        else:
            yaml_updates["model.base_url"] = UNSET
    else:
        # Hermes clears a stale custom base URL when you switch to a built-in.
        yaml_updates["model.base_url"] = UNSET

    if provider.show_context and context_length.strip():
        try:
            size = int(context_length.strip())
        except ValueError as exc:
            raise ConfigError("Context length must be a whole number.") from exc
        yaml_updates["model.context_length"] = size
        yaml_updates["model.ollama_num_ctx"] = size

    if also_preset:
        yaml_updates.update(LOW_SPEC_PRESET)

    changed = ["model.provider"]
    key_name = typed_key_env.strip() if provider.allow_typed_key_env else provider.key_env
    secret_value = api_key.strip()
    if key_name:
        if is_denied_key(key_name) or not re.match(r"^[A-Z][A-Z0-9_]*$", key_name):
            raise ConfigError("The key variable must be UPPER_SNAKE, for example OPENROUTER_API_KEY.")
        if not key_is_secret_name(key_name):
            raise ConfigError("The key variable name should contain KEY, TOKEN, or SECRET.")
        if secret_value:
            secrets.save(key_name, secret_value, env_file)
            changed.append(key_name)
        elif provider.key_required and secrets.status(key_name, env_file) == "missing":
            raise ConfigError("Paste the API key. Nothing is stored for it yet.")
    if provider.base_url_env and base_url.strip():
        _check_base(base_url.strip())
        configio.upsert_env(env_file, provider.base_url_env, base_url.strip())
        changed.append(provider.base_url_env)

    configio.apply_yaml_updates(config_file, yaml_updates)
    return changed


def save_gateway(
    *,
    enabled_key: str,
    enabled: bool,
    fields: list[tuple[str, str, bool]],
    config_file: Path,
    env_file: Path,
) -> list[str]:
    """fields are (env name, value, is_secret). Empty secret boxes keep the stored value."""
    changed: list[str] = []
    if enabled_key:
        configio.apply_yaml_updates(config_file, {enabled_key: bool(enabled)})
        changed.append(enabled_key)
    for name, value, is_secret in fields:
        if is_denied_key(name):
            raise ConfigError(f"refusing to write {name}")
        text = value.strip()
        if text == "":
            if not is_secret:
                configio.remove_env(env_file, name)
                changed.append(name)
            continue
        if is_secret or key_is_secret_name(name):
            secrets.save(name, text, env_file)
        else:
            configio.upsert_env(env_file, name, text)
        changed.append(name)
    return changed


def save_extra_key(key: str, value: str, *, secret: bool, config_file: Path, env_file: Path) -> str:
    configio.validate_key(key)
    text = value.strip()
    if secret or key_is_secret_name(key):
        if "." in key:
            raise ConfigError("Put secrets in an UPPER_SNAKE .env name, not a dotted config key.")
        if text == "":
            secrets.delete(key, env_file)
        else:
            secrets.save(key, text, env_file)
        return key
    configio.apply_yaml_updates(config_file, {key: UNSET if text == "" else _guess_scalar(text)})
    return key


def _write_env(key: str, value: Any, *, secret: bool, env_file: Path) -> None:
    if value is UNSET or value == "":
        if secret:
            secrets.delete(key, env_file)
        else:
            configio.remove_env(env_file, key)
        return
    text = "true" if value is True else "false" if value is False else str(value)
    if secret or key_is_secret_name(key):
        secrets.save(key, text, env_file)
    else:
        configio.upsert_env(env_file, key, text)


def _check_base(url: str) -> None:
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ConfigError("Base URL must start with http:// or https://")
    if parsed.username or parsed.password:
        raise ConfigError("Base URL must not include a password")


def _guess_scalar(text: str) -> Any:
    lower = text.lower()
    if lower in {"true", "false"}:
        return lower == "true"
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    if re.fullmatch(r"-?\d+\.\d+", text):
        return float(text)
    return text
