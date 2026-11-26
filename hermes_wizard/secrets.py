"""Store Hermes credentials in the OS keyring and in ~/.hermes/.env.

Hermes reads secrets from ``.env``. The keyring copy lets the wizard fill the
form again without printing the secret. Neither copy is written to the log.
"""

from __future__ import annotations

from pathlib import Path

from hermes_wizard import configio

SERVICE = "hermes-setup-wizard"


class SecretStoreError(RuntimeError):
    pass


def _keyring():
    import keyring

    return keyring


def keyring_available() -> tuple[bool, str]:
    try:
        ring = _keyring()
        ring.get_keyring()
        return True, type(ring.get_keyring()).__name__
    except Exception as exc:  # keyring missing or Secret Service down
        return False, str(exc)


def status(name: str, env_file: Path) -> str:
    """Return where a secret lives, without returning the secret."""
    in_ring = False
    try:
        in_ring = _keyring().get_password(SERVICE, name) not in (None, "")
    except Exception:
        in_ring = False
    in_env = configio.env_has(env_file, name)
    if in_ring and in_env:
        return "both"
    if in_ring:
        return "keyring"
    if in_env:
        return "env"
    return "missing"


def load(name: str, env_file: Path) -> str | None:
    """Return the secret for a form field. Callers must not log the result."""
    try:
        stored = _keyring().get_password(SERVICE, name)
    except Exception:
        stored = None
    if stored:
        return stored
    return configio.read_env(env_file).get(name)


def save(name: str, value: str, env_file: Path, *, also_env: bool = True) -> str:
    """Save a secret. Returns a short status such as ``both`` or ``env``.

    ``.env`` is always attempted when ``also_env`` is true because Hermes
    requires it. Keyring failure does not block the ``.env`` write.
    """
    if also_env:
        configio.upsert_env(env_file, name, value)
    ring_ok = False
    try:
        _keyring().set_password(SERVICE, name, value)
        ring_ok = True
    except Exception:
        ring_ok = False
    if also_env and ring_ok:
        return "both"
    if also_env:
        return "env"
    if ring_ok:
        return "keyring"
    raise SecretStoreError("could not store the secret in the keyring or .env")


def delete(name: str, env_file: Path) -> None:
    try:
        _keyring().delete_password(SERVICE, name)
    except Exception:
        pass
    configio.remove_env(env_file, name)
