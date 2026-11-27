"""Background work so the window keeps painting command output."""

from __future__ import annotations

import shutil
import threading

from PySide6.QtCore import QThread, Signal

from hermes_wizard.catalog import Step
from hermes_wizard.redact import redact
from hermes_wizard.runner import NeedPassword, StepRunner


class CallThread(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self._fn = fn

    def run(self) -> None:
        try:
            self.succeeded.emit(self._fn())
        except Exception as exc:
            self.failed.emit(redact(f"{exc.__class__.__name__}: {exc}"))


class InstallThread(QThread):
    line = Signal(str)
    step_changed = Signal(str, str, str)
    password_needed = Signal(str)
    finished_run = Signal()

    def __init__(self, steps: list[Step], prefer_pkexec: bool):
        super().__init__()
        self.steps = steps
        self.prefer_pkexec = prefer_pkexec
        self.cancel = threading.Event()
        self._password_event = threading.Event()
        self._password: str | None = None
        self.runner = StepRunner()

    def provide_password(self, password: str | None) -> None:
        self._password = password
        self._password_event.set()

    def stop(self) -> None:
        self.cancel.set()
        self.runner.stop()
        self._password_event.set()

    def run(self) -> None:
        for step in self.steps:
            if self.cancel.is_set():
                break
            self.step_changed.emit(step.id, "running", "")
            password = None
            wants_pkexec = (
                self.prefer_pkexec
                and step.privilege == "root"
                and shutil.which("pkexec") is not None
            )
            if step.privilege != "none" and not wants_pkexec:
                self._password = None
                self._password_event.clear()
                self.password_needed.emit(step.id)
                self._password_event.wait()
                password = self._password
                self._password = None
                if self.cancel.is_set():
                    break
                if not password:
                    self.step_changed.emit(step.id, "failed", "password not provided")
                    continue
            try:
                result = self.runner.run(
                    step,
                    on_line=self.line.emit,
                    cancel=self.cancel,
                    password=password,
                    prefer_pkexec=wants_pkexec,
                )
            except NeedPassword:
                self.step_changed.emit(step.id, "failed", "password required")
                continue
            finally:
                password = None
            self.step_changed.emit(step.id, result.status, result.message)
        self.finished_run.emit()
