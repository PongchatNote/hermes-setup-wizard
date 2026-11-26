"""Update this private checkout with git pull. Never pushes."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class UpdateResult:
    ok: bool
    summary: str
    output: str


def git_status(repo: Path) -> str:
    completed = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(repo),
        check=False,
        capture_output=True,
        text=True,
    )
    return (completed.stdout or "") + (completed.stderr or "")


def pull_ff_only(repo: Path) -> UpdateResult:
    """Fast-forward this repo. Refuses to run if it is not a git checkout.

    Local uncommitted changes are left in place and the pull is skipped so a
    wizard edit cannot be mixed with upstream by accident.
    """
    if not (repo / ".git").exists():
        return UpdateResult(False, "This folder is not a git checkout.", "")
    dirty = git_status(repo).strip()
    if dirty:
        return UpdateResult(
            False,
            "The wizard checkout has local changes. Commit or stash them, then try again.",
            dirty,
        )
    completed = subprocess.run(
        ["git", "pull", "--ff-only"],
        cwd=str(repo),
        check=False,
        capture_output=True,
        text=True,
    )
    output = ((completed.stdout or "") + (completed.stderr or "")).strip()
    if completed.returncode != 0:
        return UpdateResult(False, "git pull --ff-only failed.", output)
    return UpdateResult(True, "Update finished. Restart the wizard to load it.", output)
