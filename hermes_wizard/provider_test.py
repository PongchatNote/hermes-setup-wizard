"""Test a provider key without printing it.

Endpoints follow the Hermes provider guide. Errors never include the request
URL, because some APIs would otherwise echo a token back in the exception.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlparse

from hermes_wizard.catalog import Provider
from hermes_wizard.health import _request

Urlopen = Callable[..., Any]


@dataclass
class Probe:
    status: str  # pass | fail | skipped
    detail: str
    models: list[str] | None = None


def probe_provider(
    provider: Provider,
    *,
    api_key: str = "",
    model: str = "",
    base_url: str = "",
    opener: Urlopen | None = None,
) -> Probe:
    if provider.test == "nous" or provider.id == "nous":
        return Probe(
            "skipped",
            "Nous Portal uses a browser login. Run: hermes setup --portal. "
            "There is no API key to test on this page.",
        )
    if provider.test == "none":
        return Probe("skipped", "This provider has no paste-key test in the wizard.")

    key = (api_key or "").strip()
    if provider.key_required and not key:
        return Probe("fail", "Paste the API key first.")

    try:
        if provider.test == "openrouter":
            return _openrouter(key, model.strip(), opener)
        if provider.test == "anthropic":
            return _anthropic(key, model.strip(), opener)
        if provider.test == "gemini":
            return _gemini(key, model.strip(), opener)
        if provider.test == "openai_models":
            return _openai_models(provider, key, model.strip(), base_url, opener)
    except ValueError as exc:
        return Probe("fail", str(exc))
    return Probe("fail", f"Unknown test {provider.test}")


def fetch_model_ids(
    provider: Provider,
    *,
    api_key: str = "",
    base_url: str = "",
    opener: Urlopen | None = None,
    contains: str = "",
) -> Probe:
    """Return model ids from the provider catalog. The key is not included."""
    probe = probe_provider(
        provider,
        api_key=api_key,
        model="",
        base_url=base_url,
        opener=opener,
    )
    if provider.test == "openrouter" and (api_key or "").strip():
        code, body = _request(
            opener or _default_opener(),
            "https://openrouter.ai/api/v1/models",
            {"Authorization": f"Bearer {api_key.strip()}"},
        )
        if code == 200:
            ids = _ids(body)
            if contains:
                needle = contains.lower()
                ids = [item for item in ids if needle in item.lower()]
            return Probe("pass", f"{len(ids)} models", ids)
    if probe.models is not None:
        ids = probe.models
        if contains:
            needle = contains.lower()
            ids = [item for item in ids if needle in item.lower()]
        return Probe(probe.status, probe.detail, ids)
    return probe


def _openrouter(key: str, model: str, opener: Urlopen | None) -> Probe:
    code, body = _request(
        opener or _default_opener(),
        "https://openrouter.ai/api/v1/key",
        {"Authorization": f"Bearer {key}"},
    )
    if code != 200:
        return Probe("fail", f"OpenRouter rejected the key (HTTP {code}).")
    if not model:
        return Probe("pass", "OpenRouter accepted the key. Choose a model id to finish.")
    listed = _catalog("https://openrouter.ai/api/v1/models", {"Authorization": f"Bearer {key}"}, opener)
    if listed is None:
        return Probe("pass", "OpenRouter accepted the key. The model list was unavailable, so the id was not checked.")
    if model not in listed:
        return Probe(
            "fail",
            "OpenRouter accepted the key, and that model id is not in the live catalog. "
            "Press Fetch models and pick an id that is listed.",
            listed,
        )
    return Probe("pass", f"OpenRouter accepted the key and lists {model}.", listed)


def _anthropic(key: str, model: str, opener: Urlopen | None) -> Probe:
    headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
    code, body = _request(opener or _default_opener(), "https://api.anthropic.com/v1/models", headers)
    if code != 200:
        return Probe("fail", f"Anthropic rejected the key (HTTP {code}).")
    return _match("Anthropic accepted the key", model, _ids(body))


def _gemini(key: str, model: str, opener: Urlopen | None) -> Probe:
    code, body = _request(
        opener or _default_opener(),
        "https://generativelanguage.googleapis.com/v1beta/models",
        {"x-goog-api-key": key},
    )
    if code != 200:
        return Probe("fail", f"Google rejected the key (HTTP {code}).")
    ids = _ids(body)
    short = [item.split("/")[-1] for item in ids]
    if model and model not in ids and model not in short:
        return Probe("fail", "Google accepted the key, and that model id is not in the list it returned.", ids)
    if model:
        return Probe("pass", f"Google accepted the key and lists {model}.", ids)
    return Probe("pass", "Google accepted the key.", ids)


def _openai_models(
    provider: Provider,
    key: str,
    model: str,
    base_url: str,
    opener: Urlopen | None,
) -> Probe:
    raw = (base_url or provider.default_base_url or "").strip()
    if not raw:
        return Probe(
            "skipped",
            "No base URL to test. Save the provider id and key, or fill the base URL from the Hermes provider guide.",
        )
    base = _safe_base(raw)
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    code, body = _request(opener or _default_opener(), _models_url(base), headers)
    if code != 200:
        return Probe("fail", f"The models endpoint returned HTTP {code}.")
    return _match("The endpoint accepted the connection", model, _ids(body))


def _catalog(url: str, headers: dict[str, str], opener: Urlopen | None) -> list[str] | None:
    code, body = _request(opener or _default_opener(), url, headers)
    if code != 200:
        return None
    return _ids(body)


def _match(prefix: str, model: str, ids: list[str]) -> Probe:
    if model and ids and model not in ids:
        return Probe("fail", f"{prefix}, and that model id is not in the list it returned.", ids)
    if model:
        return Probe("pass", f"{prefix} and lists {model}.", ids)
    return Probe("pass", f"{prefix}.", ids)


def _models_url(base: str) -> str:
    if base.endswith("/models"):
        return base
    return base + "/models"


def _safe_base(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("The base URL must start with http:// or https://")
    if parsed.username or parsed.password:
        raise ValueError("The base URL must not include a username or password")
    return url.rstrip("/")


def _ids(body: str) -> list[str]:
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return []
    rows = payload.get("data") if isinstance(payload, dict) else None
    if rows is None and isinstance(payload, dict):
        rows = payload.get("models")
    ids: list[str] = []
    for row in rows or []:
        if isinstance(row, str):
            ids.append(row)
        elif isinstance(row, dict):
            value = row.get("id") or row.get("name") or ""
            if value:
                ids.append(str(value))
    return ids


def probe_gateway(kind: str, token: str, opener: Urlopen | None = None) -> Probe:
    """Check a chat-bot token. The token is not included in the result text."""
    token = (token or "").strip()
    if not token:
        return Probe("fail", "Paste the token first.")
    open_ = opener or _default_opener()
    if kind == "telegram":
        code, body = _request(open_, f"https://api.telegram.org/bot{token}/getMe", {})
        if code != 200:
            return Probe("fail", f"Telegram HTTP {code}. Check the token from BotFather.")
        username = ""
        try:
            payload = json.loads(body)
            username = str((payload.get("result") or {}).get("username") or "")
            if not payload.get("ok"):
                return Probe("fail", "Telegram getMe did not return ok.")
        except json.JSONDecodeError:
            return Probe("fail", "Telegram returned a body that is not JSON.")
        return Probe("pass", f"Telegram bot @{username}" if username else "Telegram getMe succeeded.")
    if kind == "discord":
        code, _body = _request(open_, "https://discord.com/api/v10/users/@me", {"Authorization": f"Bot {token}"})
        if code != 200:
            return Probe("fail", f"Discord HTTP {code}.")
        return Probe(
            "pass",
            "Discord accepted the token. Message Content Intent and Server Members Intent must still be on, or the bot stays offline.",
        )
    if kind == "line":
        code, _body = _request(open_, "https://api.line.me/v2/bot/info", {"Authorization": f"Bearer {token}"})
        if code != 200:
            return Probe("fail", f"LINE HTTP {code}. Check the long-lived channel access token.")
        return Probe("pass", "LINE accepted the channel access token.")
    if kind == "slack":
        code, body = _request(
            open_,
            "https://slack.com/api/auth.test",
            {"Authorization": f"Bearer {token}"},
            method="POST",
            data=b"",
        )
        if code != 200:
            return Probe("fail", f"Slack HTTP {code}.")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            payload = {}
        if not payload.get("ok"):
            return Probe("fail", "Slack auth.test returned ok=false. Check the xoxb- bot token.")
        return Probe("pass", "Slack accepted the bot token.")
    return Probe("skipped", "This platform has no one-click test. Save the values and use hermes gateway status.")


def _default_opener():
    from urllib.request import urlopen

    return urlopen
