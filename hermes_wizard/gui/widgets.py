"""Shared widgets: bilingual hints, masked fields, copy buttons."""

from __future__ import annotations

from PySide6.QtCore import QTimer, QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from hermes_wizard.catalog import Link
from hermes_wizard.i18n import join


class CopyButton(QPushButton):
    def __init__(self, command: str, label_en: str = "Copy command", label_th: str = "คัดลอกคำสั่ง"):
        super().__init__(label_en)
        self.command = command
        self.label_en = label_en
        self.label_th = label_th
        self.setProperty("secondary", True)
        self.clicked.connect(self._copy)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._restore)
        self._mode = "both"

    def apply_language(self, mode: str) -> None:
        self._mode = mode
        self.setText(join(self.label_en, self.label_th, mode).replace("\n", " / "))

    def _copy(self) -> None:
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(self.command)
        self.setText("Copied / คัดลอกแล้ว")
        self._timer.start(1600)

    def _restore(self) -> None:
        self.apply_language(self._mode)


class SecretEdit(QWidget):
    def __init__(self, placeholder: str = ""):
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit()
        self.edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.edit.setPlaceholderText(placeholder)
        self.button = QPushButton("Show")
        self.button.setProperty("secondary", True)
        self.button.clicked.connect(self._flip)
        row.addWidget(self.edit, 1)
        row.addWidget(self.button)
        self._shown = False

    def text(self) -> str:
        return self.edit.text()

    def setText(self, value: str) -> None:
        self.edit.setText(value)

    def _flip(self) -> None:
        self._shown = not self._shown
        self.edit.setEchoMode(QLineEdit.EchoMode.Normal if self._shown else QLineEdit.EchoMode.Password)
        self.button.setText("Hide" if self._shown else "Show")


class Explain(QFrame):
    """Expandable Thai+English hint. Links open in the browser."""

    def __init__(self):
        super().__init__()
        self.setObjectName("explain")
        layout = QVBoxLayout(self)
        self.toggle = QToolButton()
        self.toggle.setCheckable(True)
        self.toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.toggle.setText("What is this?  /  นี่คืออะไร?")
        self.toggle.toggled.connect(self._toggled)
        self.body = QLabel()
        self.body.setWordWrap(True)
        self.body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.body.hide()
        self.link_row = QHBoxLayout()
        layout.addWidget(self.toggle)
        layout.addWidget(self.body)
        layout.addLayout(self.link_row)
        self._mode = "both"
        self.help_en = self.help_th = ""
        self.where_en = self.where_th = ""
        self.example = ""
        self._links: list[Link] = []

    def set_copy(
        self,
        *,
        help_en: str = "",
        help_th: str = "",
        where_en: str = "",
        where_th: str = "",
        example: str = "",
        links: list[Link] | None = None,
    ) -> None:
        self.help_en = help_en
        self.help_th = help_th
        self.where_en = where_en
        self.where_th = where_th
        self.example = example
        self._links = list(links or [])
        self.apply_language(self._mode)

    def apply_language(self, mode: str) -> None:
        self._mode = mode
        chunks = [
            join(self.help_en, self.help_th, mode),
            join(self.where_en, self.where_th, mode),
        ]
        if self.example:
            label = join("Example format (not a real secret)", "รูปแบบตัวอย่าง (ไม่ใช่ความลับจริง)", mode)
            chunks.append(f"{label}: {self.example}")
        self.body.setText("\n\n".join(part for part in chunks if part))
        while self.link_row.count():
            item = self.link_row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        for link in self._links:
            button = QPushButton(join(link.label_en, link.label_th, mode).replace("\n", " / "))
            button.setProperty("secondary", True)
            button.clicked.connect(lambda _checked=False, url=link.url: QDesktopServices.openUrl(QUrl(url)))
            self.link_row.addWidget(button)
        self.link_row.addStretch(1)

    def _toggled(self, open_: bool) -> None:
        self.toggle.setArrowType(Qt.ArrowType.DownArrow if open_ else Qt.ArrowType.RightArrow)
        self.body.setVisible(open_)


class FieldBlock(QWidget):
    """Label, editor, and the expandable explanation for one setting."""

    def __init__(self, title_en: str, title_th: str, kind: str, choices: list[str] | None = None, secret: bool = False):
        super().__init__()
        self.title_en = title_en
        self.title_th = title_th
        self.kind = kind
        self.secret = secret
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 8)
        self.title = QLabel()
        self.title.setStyleSheet("font-weight: 600;")
        layout.addWidget(self.title)
        self.editor: QWidget
        if kind == "bool":
            self.editor = QCheckBox()
        elif kind == "choice":
            box = QComboBox()
            box.setEditable(False)
            for choice in choices or []:
                box.addItem(choice if choice else "(leave unset)", choice)
            self.editor = box
        elif secret:
            self.editor = SecretEdit()
        else:
            self.editor = QLineEdit()
        layout.addWidget(self.editor)
        self.explain = Explain()
        layout.addWidget(self.explain)
        self.apply_language("both")

    def apply_language(self, mode: str) -> None:
        self.title.setText(join(self.title_en, self.title_th, mode))
        self.explain.apply_language(mode)
        if isinstance(self.editor, QCheckBox):
            self.editor.setText(join(self.title_en, self.title_th, mode))

    def value(self) -> str | bool:
        if isinstance(self.editor, QCheckBox):
            return self.editor.isChecked()
        if isinstance(self.editor, QComboBox):
            return str(self.editor.currentData())
        if isinstance(self.editor, SecretEdit):
            return self.editor.text()
        if isinstance(self.editor, QLineEdit):
            return self.editor.text()
        return ""

    def set_value(self, value: str | bool | None) -> None:
        if isinstance(self.editor, QCheckBox):
            self.editor.setChecked(value is True or str(value).lower() == "true")
            return
        if isinstance(self.editor, QComboBox):
            target = "" if value is None else str(value)
            index = self.editor.findData(target)
            if index < 0:
                index = self.editor.findText(target)
            if index < 0 and target == "":
                index = 0
            if index >= 0:
                self.editor.setCurrentIndex(index)
            return
        text = "" if value is None else str(value)
        if isinstance(self.editor, SecretEdit):
            self.editor.setText(text)
        elif isinstance(self.editor, QLineEdit):
            self.editor.setText(text)


def card() -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("card")
    layout = QVBoxLayout(frame)
    return frame, layout
