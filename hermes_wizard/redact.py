"""Redact secrets before they reach logs, files, or the status panel."""

from __future__ import annotations

import re
from collections.abc import Iterable

_MASK = "***"

# Assignment-style secrets: keep the name, hide the value.
_ASSIGNMENT = re.compile(
    r"(?i)\b([A-Z0-9_]*(?:API_KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|AUTH)[A-Z0-9_]*)"
    r"(\s*[=:]\s*)([^\s#]+)"
)

_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)\bsk-or-v1-[a-z0-9_\-]{6,}"), "sk-or-v1-***"),
    (re.compile(r"(?i)\bsk-or-[a-z0-9_\-]{6,}"), "sk-or-***"),
    (re.compile(r"(?i)\bsk-[a-z0-9_\-]{12,}"), "sk-***"),
    (re.compile(r"\b\d{6,12}:[A-Za-z0-9_\-]{20,}"), "telegram-bot-***"),
    (re.compile(r"(?i)(/bot)(\d{6,12}:[A-Za-z0-9_\-]{10,})"), r"\1***"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]+"), "xox-***"),
    (re.compile(r"\bxapp-[A-Za-z0-9\-]+"), "xapp-***"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9\-._~+/]+=*"), "Bearer ***"),
    (re.compile(r"(?i)(authorization\s*[:=]\s*)(\S+)"), r"\1***"),
    (re.compile(r"(?i)([?&](?:access_)?token=)([^&\s]+)"), r"\1***"),
    (re.compile(r"(?i)([?&](?:api_key|key)=)([^&\s]+)"), r"\1***"),
)


def redact(text: str, extra: Iterable[str] | None = None) -> str:
    """Return text with secret-shaped values replaced.

    ``extra`` is for exact values the caller is holding (a password typed into
    the sudo prompt, a token just saved). Values shorter than 4 characters are
    ignored so a one-letter password cannot blank the log.
    """
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)
    for secret in extra or ():
        if isinstance(secret, str) and len(secret) >= 4 and secret in text:
            text = text.replace(secret, _MASK)
    text = _ASSIGNMENT.sub(lambda match: f"{match.group(1)}{match.group(2)}{_MASK}", text)
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text


def redact_mapping_preview(keys: Iterable[str]) -> str:
    """Describe which keys changed without showing values."""
    names = [key for key in keys if key]
    if not names:
        return "no keys"
    return ", ".join(names) + " (values redacted)"
