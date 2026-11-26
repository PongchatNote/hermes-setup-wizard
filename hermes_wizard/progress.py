"""Persist step status and the last page. Secrets are not stored here."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hermes_wizard.paths import progress_path


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load(path: Path | None = None) -> dict[str, Any]:
    target = path or progress_path()
    if not target.exists():
        return {"version": 1, "language": "both", "steps": {}, "last_page": "welcome"}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "language": "both", "steps": {}, "last_page": "welcome"}
    if not isinstance(data, dict):
        return {"version": 1, "language": "both", "steps": {}, "last_page": "welcome"}
    data.setdefault("version", 1)
    data.setdefault("language", "both")
    data.setdefault("steps", {})
    data.setdefault("last_page", "welcome")
    return data


def save(data: dict[str, Any], path: Path | None = None) -> None:
    target = path or progress_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    # Never persist a password or token if a caller stuffed one into the dict.
    cleaned = {
        "version": 1,
        "language": data.get("language", "both"),
        "last_page": data.get("last_page", "welcome"),
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
