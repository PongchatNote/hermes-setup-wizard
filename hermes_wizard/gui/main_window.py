"""Main window: sidebar, progress strip, and the shared log."""

from __future__ import annotations

import sys

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from hermes_wizard import progress, secrets
from hermes_wizard.catalog import MAIN_FLOW, load_gateways, load_groups, load_secrets, load_settings
from hermes_wizard.configio import get_dotted, load_yaml
from hermes_wizard.gui.pages import (
    ExtraKeyPage,
    FaqPage,
    GatewayPage,
    HealthPage,
    InstallPage,
    ProviderPage,
    SettingsPage,
    UpdatesPage,
    WelcomePage,
)
from hermes_wizard.gui.theme import APP_STYLE
from hermes_wizard.i18n import join
from hermes_wizard.paths import config_path, env_path
from hermes_wizard.redact import redact


class Session(QObject):
    milestones_changed = Signal()

    def __init__(self):
        super().__init__()
        self.progress = progress.load()
        self.mode = self.progress.get("language") or "both"

    def log(self, line: str) -> None:
        window = self.parent()
        if hasattr(window, "append_log"):
            window.append_log(redact(line))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.session = Session()
        self.session.setParent(self)
        self.pages: dict[str, QWidget] = {}
        self.nav_ids: list[str] = []
        self._build()
        self.session.milestones_changed.connect(self._paint_progress)
        self._paint_progress()
        last = self.session.progress.get("last_page") or "welcome"
        self.open_page(last if last in self.pages else "welcome")
        self.apply_language(self.session.mode)

    def _build(self) -> None:
        shell = QWidget()
        outer = QVBoxLayout(shell)
        self.progress_row = QHBoxLayout()
        self.progress_buttons: dict[str, QPushButton] = {}
        labels = {
            "install": ("1 Install", "1 ติดตั้ง"),
            "provider": ("2 Provider", "2 ผู้ให้บริการ"),
            "telegram": ("3 Telegram", "3 Telegram"),
            "discord": ("4 Discord", "4 Discord"),
            "line": ("5 LINE", "5 LINE"),
            "health": ("6 Check", "6 ตรวจ"),
        }
        for page_id in MAIN_FLOW:
            button = QPushButton(labels[page_id][0])
            button.setProperty("secondary", True)
            button.clicked.connect(lambda _checked=False, target=page_id: self.open_page(target))
            self.progress_buttons[page_id] = button
            self.progress_row.addWidget(button)
        outer.addLayout(self.progress_row)

        body = QSplitter()
        self.nav = QListWidget()
        self.nav.currentRowChanged.connect(self._nav_changed)
        self.stack_host = QWidget()
        self.stack_layout = QVBoxLayout(self.stack_host)
        self.stack_layout.setContentsMargins(12, 8, 12, 8)
        body.addWidget(self.nav)
        body.addWidget(self.stack_host)
        body.setStretchFactor(1, 1)
        self.nav.setMinimumWidth(240)
        outer.addWidget(body, 1)

        self.log = QPlainTextEdit()
        self.log.setObjectName("log")
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(4000)
        self.log.setPlaceholderText("Command output. Secrets are removed.")
        log_bar = QHBoxLayout()
        self.log_title = QLabel()
        clear = QPushButton("Clear panel")
        clear.setProperty("secondary", True)
        clear.clicked.connect(self.log.clear)
        self.clear_button = clear
        log_bar.addWidget(self.log_title)
        log_bar.addStretch(1)
        log_bar.addWidget(clear)
        outer.addLayout(log_bar)
        outer.addWidget(self.log, 0)
        self.log.setFixedHeight(160)

        lang = QHBoxLayout()
        self.lang_buttons = {}
        for mode, label in (("en", "English"), ("th", "ไทย"), ("both", "EN + TH")):
            button = QPushButton(label)
            button.setProperty("secondary", True)
            button.clicked.connect(lambda _checked=False, value=mode: self.apply_language(value))
            self.lang_buttons[mode] = button
            lang.addWidget(button)
        lang.addStretch(1)
        outer.addLayout(lang)
        self.setCentralWidget(shell)

        self._add("welcome", WelcomePage(), "Welcome", "เริ่มต้น")
        self.pages["welcome"].open_page.connect(self.open_page)
        install = InstallPage(self.session)
        self._add("install", install, "Install", "ติดตั้ง")
        self._add("provider", ProviderPage(self.session), "Provider & model", "ผู้ให้บริการและโมเดล")
        gateways = {item.id: item for item in load_gateways()}
        for gate_id, en, th in (
            ("telegram", "Telegram", "Telegram"),
            ("discord", "Discord", "Discord"),
            ("line", "LINE", "LINE"),
        ):
            page = GatewayPage(self.session, gateways[gate_id])
            self._add(gate_id, page, en, th)
        self._add_heading("more-chats", "More chat apps", "แชทแอปอื่น")
        for gate_id, gateway in gateways.items():
            if gate_id in {"telegram", "discord", "line"}:
                continue
            self._add(f"gateway:{gate_id}", GatewayPage(self.session, gateway), gateway.title_en, gateway.title_th)
        self._add_heading("settings-head", "Hermes settings", "การตั้งค่า Hermes")
        grouped: dict[str, list] = {}
        for setting in load_settings():
            grouped.setdefault(setting.group, []).append(setting)
        for group in load_groups():
            self._add(
                f"settings:{group.id}",
                SettingsPage(self.session, group.id, group.title_en, group.title_th, grouped.get(group.id, [])),
                group.title_en,
                group.title_th,
            )
        self._add("secrets", SettingsPage(self.session, "secrets", "Other API keys", "คีย์ API อื่น", load_secrets()), "Other API keys", "คีย์ API อื่น")
        self._add("more", ExtraKeyPage(self.session), "More keys", "คีย์เพิ่มเติม")
        health = HealthPage(self.session)
        health.open_page.connect(self.open_page)
        self._add("health", health, "Final check", "ตรวจครั้งสุดท้าย")
        self._add("faq", FaqPage(), "Troubleshooting", "แก้ปัญหา")
        self._add("updates", UpdatesPage(self.session), "Updates", "อัปเดต")
        self.setStyleSheet(APP_STYLE)

    def _add(self, page_id: str, widget: QWidget, en: str, th: str) -> None:
        widget.setProperty("nav_en", en)
        widget.setProperty("nav_th", th)
        self.pages[page_id] = widget
        self.stack_layout.addWidget(widget)
        widget.hide()
        item = QListWidgetItem(en)
        item.setData(Qt.ItemDataRole.UserRole, page_id)
        self.nav.addItem(item)
        self.nav_ids.append(page_id)

    def _add_heading(self, page_id: str, en: str, th: str) -> None:
        item = QListWidgetItem(en)
        item.setData(Qt.ItemDataRole.UserRole, page_id)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        item.setData(Qt.ItemDataRole.UserRole + 1, (en, th))
        self.nav.addItem(item)

    def append_log(self, line: str) -> None:
        self.log.appendPlainText(redact(line))

    def open_page(self, page_id: str) -> None:
        target = page_id
        if page_id.startswith("install:"):
            target = "install"
        if target not in self.pages:
            return
        for widget in self.pages.values():
            widget.hide()
        self.pages[target].show()
        if page_id.startswith("install:") and hasattr(self.pages["install"], "_rows"):
            pass
        index = self.nav_ids.index(target)
        self.nav.blockSignals(True)
        self.nav.setCurrentRow(self._row_for(target))
        self.nav.blockSignals(False)
        self.session.progress["last_page"] = target
        progress.save(self.session.progress)
        self._paint_progress()

    def _row_for(self, page_id: str) -> int:
        for row in range(self.nav.count()):
            if self.nav.item(row).data(Qt.ItemDataRole.UserRole) == page_id:
                return row
        return 0

    def _nav_changed(self, row: int) -> None:
        if row < 0:
            return
        page_id = self.nav.item(row).data(Qt.ItemDataRole.UserRole)
        if page_id in self.pages:
            self.open_page(page_id)

    def apply_language(self, mode: str) -> None:
        self.session.mode = mode
        self.session.progress["language"] = mode
        progress.save(self.session.progress)
        self.setWindowTitle(join("Hermes Setup Wizard", "ตัวช่วยติดตั้ง Hermes", mode).replace("\n", " · "))
        self.log_title.setText(join("Command output — secrets are removed", "ผลคำสั่ง — ความลับถูกตัดออก", mode))
        self.clear_button.setText(join("Clear panel", "ล้างแผง", mode))
        labels = {
            "install": ("1 Install", "1 ติดตั้ง"),
            "provider": ("2 Provider", "2 ผู้ให้บริการ"),
            "telegram": ("3 Telegram", "3 Telegram"),
            "discord": ("4 Discord", "4 Discord"),
            "line": ("5 LINE", "5 LINE"),
            "health": ("6 Check", "6 ตรวจ"),
        }
        for page_id, button in self.progress_buttons.items():
            button.setText(join(*labels[page_id], mode).replace("\n", " "))
        for row in range(self.nav.count()):
            item = self.nav.item(row)
            page_id = item.data(Qt.ItemDataRole.UserRole)
            heading = item.data(Qt.ItemDataRole.UserRole + 1)
            if heading:
                item.setText(join(heading[0], heading[1], mode).replace("\n", " "))
            elif page_id in self.pages:
                widget = self.pages[page_id]
                item.setText(join(widget.property("nav_en"), widget.property("nav_th"), mode).replace("\n", " "))
        for widget in self.pages.values():
            if hasattr(widget, "apply_language"):
                widget.apply_language(mode)
        self._paint_progress()

    def _paint_progress(self) -> None:
        flags = milestone_flags(self.session.progress)
        for page_id, button in self.progress_buttons.items():
            state = flags.get(page_id, "pending")
            button.setStyleSheet("")
            if state == "ok":
                button.setStyleSheet("background:#166534;color:white;")
            elif state == "optional":
                button.setStyleSheet("background:#fef3c7;color:#1c1917;")


def milestone_flags(data: dict) -> dict[str, str]:
    """ok = done, optional = saved but not required, pending = not done."""
    flags = {}
    required = [step_id for step_id in ("check-os", "apt-prereqs", "install-hermes", "verify-cli")]
    steps = data.get("steps") or {}
    flags["install"] = "ok" if all(steps.get(step_id, {}).get("status") == "ok" for step_id in required) else "pending"
    flags["provider"] = "ok" if _provider_ready() else "pending"
    for gate, key in (
        ("telegram", "TELEGRAM_BOT_TOKEN"),
        ("discord", "DISCORD_BOT_TOKEN"),
        ("line", "LINE_CHANNEL_ACCESS_TOKEN"),
    ):
        flags[gate] = "ok" if secrets.status(key, env_path()) != "missing" else "pending"
    flags["health"] = "ok" if data.get("health_status") == "pass" else "pending"
    return flags


def _provider_ready() -> bool:
    path = config_path()
    if not path.exists():
        return False
    try:
        data = load_yaml(path)
    except Exception:
        return False
    provider = str(get_dotted(data, "model.provider") or "")
    model = get_dotted(data, "model.default") or get_dotted(data, "model.model")
    if provider == "nous":
        return True
    if provider == "custom":
        return bool(model) and bool(get_dotted(data, "model.base_url"))
    if not provider or not model:
        return False
    key_by_provider = {
        "openrouter": "OPENROUTER_API_KEY",
        "openai-api": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "deepseek": "DEEPSEEK_API_KEY",
        "gemini": "GEMINI_API_KEY",
        "xai": "XAI_API_KEY",
        "ollama-cloud": "OLLAMA_API_KEY",
    }
    key = key_by_provider.get(provider)
    if key is None:
        return True
    return secrets.status(key, env_path()) != "missing"


def run() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setFont(QFont("Noto Sans Thai", 11))
    window = MainWindow()
    window.resize(1100, 760)
    window.show()
    return app.exec()
