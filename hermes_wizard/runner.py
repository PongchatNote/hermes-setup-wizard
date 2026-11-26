"""Run install steps and stream redacted output.

Sudo passwords are written to the process stdin and then dropped. They are
never placed on the command line and never written to the log.
"""

from __future__ import annotations

import os
import signal
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from hermes_wizard.catalog import Step
from hermes_wizard.paths import command_env, log_dir
from hermes_wizard.redact import redact

LineCallback = Callable[[str], None]


class NeedPassword(RuntimeError):
    pass


@dataclass
class RunResult:
    status: str  # ok | failed | skipped
    returncode: int | None
    log_path: Path | None
    message: str = ""


class StepRunner:
    def __init__(
        self,
        popen: Callable[..., subprocess.Popen] | None = None,
        which: Callable[[str], str | None] | None = None,
    ) -> None:
        self._popen = popen or subprocess.Popen
        self._which = which or _which
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None

    def run(
        self,
        step: Step,
        *,
        on_line: LineCallback,
        cancel: threading.Event | None = None,
        password: str | None = None,
        prefer_pkexec: bool = True,
        env: dict[str, str] | None = None,
        log_file: Path | None = None,
    ) -> RunResult:
        cancel = cancel or threading.Event()
        secrets = [password] if password else []
        try:
            argv, stdin_text = self._plan(step, password=password, prefer_pkexec=prefer_pkexec)
        except NeedPassword:
            raise
        shown = " ".join(argv[:4])
        if len(argv) > 4:
            shown += " …"
        self._emit(on_line, f"$ {shown}", secrets)
        log_handle = None
        if log_file is None:
            safe_id = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in step.id)
            log_file = log_dir() / f"{safe_id}.log"
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            log_handle = log_file.open("w", encoding="utf-8")
            os.chmod(log_file, 0o600)
        except OSError:
            log_handle = None
            log_file = None

        proc = self._popen(
            argv,
            stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=command_env(env),
            start_new_session=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        with self._lock:
            self._proc = proc
        try:
            if stdin_text is not None and proc.stdin is not None:
                proc.stdin.write(stdin_text)
                proc.stdin.flush()
                proc.stdin.close()
            assert proc.stdout is not None
            for line in proc.stdout:
                if cancel.is_set():
                    self.stop()
                    self._emit(on_line, "stopped", secrets)
                    return RunResult("failed", None, log_file, "stopped")
                clean = line.rstrip("\n")
                self._emit(on_line, clean, secrets, log_handle)
            code = proc.wait()
        finally:
            with self._lock:
                if self._proc is proc:
                    self._proc = None
            if log_handle is not None:
                log_handle.close()
            # Drop the password buffer.
            stdin_text = None
            password = None
        if code == 0:
            return RunResult("ok", code, log_file, "ok")
        return RunResult("failed", code, log_file, f"exit {code}")

    def stop(self) -> None:
        with self._lock:
            proc = self._proc
        if proc is None or proc.poll() is not None:
            return
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                proc.terminate()
            except OSError:
                return
        try:
            proc.wait(timeout=3)
        except Exception:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                try:
                    proc.kill()
                except OSError:
                    pass

    def _plan(
        self,
        step: Step,
        *,
        password: str | None,
        prefer_pkexec: bool,
    ) -> tuple[list[str], str | None]:
        script = step.shell
        if step.privilege == "none":
            return ["bash", "-lc", script], None
        use_pkexec = (
            prefer_pkexec
            and step.privilege == "root"
            and self._which("pkexec") is not None
            and not password
        )
        if use_pkexec:
            return ["pkexec", "bash", "-lc", script], None
        if not password:
            raise NeedPassword(step.id)
        if step.privilege == "root":
            return ["sudo", "-S", "-p", "", "--", "bash", "-lc", script], password + "\n"
        # Cache sudo credentials, then run the script as the user so Hermes
        # stays in the user account. Child commands may call sudo -n.
        wrapped = "sudo -S -p '' -v\n" + script
        return ["bash", "-lc", wrapped], password + "\n"

    @staticmethod
    def _emit(
        on_line: LineCallback,
        line: str,
        secrets: list[str | None],
        log_handle=None,
    ) -> None:
        clean = redact(line, [item for item in secrets if item])
        on_line(clean)
        if log_handle is not None:
            log_handle.write(clean + "\n")
            log_handle.flush()


def _which(name: str) -> str | None:
    from shutil import which

    return which(name)
