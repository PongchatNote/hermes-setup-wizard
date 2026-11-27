"""Persist step status and the last page. Secrets are not stored here."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hermes_wizard.paths import progress_path


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _blank() -> dict[str, Any]:
    return {"version": 1, "language": "both", "steps": {}, "last_page": "welcome"}


def _normalize(data: dict[str, Any]) -> dict[str, Any]:
    data.setdefault("version", 1)
    data.setdefault("language", "both")
    data.setdefault("steps", {})
    data.setdefault("last_page", "welcome")
    data["install_mode"] = _choice(data.get("install_mode"), {"native", "docker"}, "native")
    data["setup_profile"] = _choice(data.get("setup_profile"), {"full", "quick"}, "full")
    data["quick_bot"] = _choice(data.get("quick_bot"), {"telegram", "discord", "line"}, "telegram")
    data["health_status"] = _choice(data.get("health_status"), {"pass", "fail", ""}, "")
    return data


def load(path: Path | None = None) -> dict[str, Any]:
    target = path or progress_path()
    if not target.exists():
        return _normalize(_blank())
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _normalize(_blank())
    if not isinstance(data, dict):
        return _normalize(_blank())
    return _normalize(data)


def save(data: dict[str, Any], path: Path | None = None) -> None:
    target = path or progress_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    # Never persist a password or token if a caller stuffed one into the dict.
    cleaned = {
        "version": 1,
        "language": data.get("language", "both"),
        "last_page": data.get("last_page", "welcome"),
        "install_mode": _choice(data.get("install_mode"), {"native", "docker"}, "native"),
        "setup_profile": _choice(data.get("setup_profile"), {"full", "quick"}, "full"),
        "quick_bot": _choice(data.get("quick_bot"), {"telegram", "discord", "line"}, "telegram"),
        "health_status": _choice(data.get("health_status"), {"pass", "fail", ""}, ""),
        "steps": {},
    }
    for step_id, info in (data.get("steps") or {}).items():
        if not isinstance(info, dict):
            continue
        cleaned["steps"][step_id] = {
            "status": info.get("status", "pending"),
            "finished_at": info.get("finished_at"),
            "message": info.get("message", ""),
        }
    target.write_text(json.dumps(cleaned, indent=2) + "\n", encoding="utf-8")


def _choice(value: Any, allowed: set[str], default: str) -> str:
    text = str(value or "")
    return text if text in allowed else default


def set_step(data: dict[str, Any], step_id: str, status: str, message: str = "") -> None:
    data.setdefault("steps", {})
    data["steps"][step_id] = {
        "status": status,
        "finished_at": _now(),
        "message": message,
    }


def step_status(data: dict[str, Any], step_id: str) -> str:
    info = (data.get("steps") or {}).get(step_id) or {}
    return str(info.get("status") or "pending")
