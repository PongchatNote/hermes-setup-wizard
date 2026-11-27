"""Wizard pages. Each one can be opened again from the sidebar."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from hermes_wizard import apply as apply_mod
from hermes_wizard import configio, progress, secrets
from hermes_wizard.catalog import (
    Check,
    FaqItem,
    Gateway,
    Provider,
    Setting,
    Step,
    load_checks,
    load_faq,
    load_gateways,
    load_providers,
    load_secrets,
    load_settings,
    load_steps,
)
from hermes_wizard.configio import ConfigError, format_loaded
from hermes_wizard.gui.widgets import CopyButton, Explain, FieldBlock, SecretEdit, card
from hermes_wizard.gui.workers import CallThread, InstallThread
from hermes_wizard.health import run_checks
from hermes_wizard.i18n import join
from hermes_wizard.paths import config_path, env_path, hermes_home, repo_root
from hermes_wizard.runtime import backup_home, cli_chat_argv, flow_pages, restore_home, update_hermes_commands
from hermes_wizard.provider_test import fetch_model_ids, probe_gateway, probe_provider
from hermes_wizard.redact import redact_mapping_preview
from hermes_wizard.updater import pull_ff_only


def _scroll(inner: QWidget) -> QScrollArea:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QScrollArea.Shape.NoFrame)
    area.setWidget(inner)
    return area


class LanguageMixin:
    mode = "both"

    def apply_language(self, mode: str) -> None:
        self.mode = mode


class ChoiceBar(QWidget, LanguageMixin):
    """Full/Quick, the one Quick bot, and Native/Docker. Defaults stay Full and Native."""

    changed = Signal()

    def __init__(self, session):
        super().__init__()
        self.session = session
        self._guard = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.profile_label = QLabel()
        self.full = QRadioButton()
        self.quick = QRadioButton()
        self.profile_group = QButtonGroup(self)
        self.profile_group.addButton(self.full)
        self.profile_group.addButton(self.quick)
        self.bot_label = QLabel()
        self.bot_row = QWidget()
        bot_layout = QHBoxLayout(self.bot_row)
        bot_layout.setContentsMargins(0, 0, 0, 0)
        self.bots = {}
        self.bot_group = QButtonGroup(self)
        for bot_id in ("telegram", "discord", "line"):
            button = QRadioButton(bot_id)
            self.bots[bot_id] = button
            self.bot_group.addButton(button)
            bot_layout.addWidget(button)
        bot_layout.addStretch(1)
        self.mode_label = QLabel()
        self.native = QRadioButton()
        self.docker = QRadioButton()
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.native)
        self.mode_group.addButton(self.docker)
        self.note = QLabel()
        self.note.setWordWrap(True)
        layout.addWidget(self.profile_label)
        layout.addWidget(self.full)
        layout.addWidget(self.quick)
        layout.addWidget(self.bot_label)
        layout.addWidget(self.bot_row)
        layout.addWidget(self.mode_label)
        layout.addWidget(self.native)
        layout.addWidget(self.docker)
        layout.addWidget(self.note)
        self.profile_group.buttonClicked.connect(lambda _button: self._save())
        self.bot_group.buttonClicked.connect(lambda _button: self._save())
        self.mode_group.buttonClicked.connect(lambda _button: self._save())
        self.apply_language("both")

    def apply_language(self, mode: str) -> None:
        super().apply_language(mode)
        self.profile_label.setText(join("How much to set up", "จะตั้งค่ามากแค่ไหน", mode))
        self.full.setText(join("Full setup (default)", "ตั้งค่าทั้งหมด (ค่าเริ่มต้น)", mode))
        self.quick.setText(join("Quick setup", "ตั้งค่าแบบย่อ", mode))
        self.bot_label.setText(join("Quick setup uses this one bot", "แบบย่อใช้บอทตัวนี้ตัวเดียว", mode))
        self.mode_label.setText(join("How to install Hermes", "วิธีติดตั้ง Hermes", mode))
        self.native.setText(join("Native install.sh (default)", "ติดตั้งด้วย install.sh (ค่าเริ่มต้น)", mode))
        self.docker.setText(join("Docker image nousresearch/hermes-agent", "อิมเมจ Docker nousresearch/hermes-agent", mode))
        self.note.setText(
            join(
                "Full setup is every page. Quick setup is install, the provider, one test chat, the bot you pick, and the final check. You can switch later. Native is the current source install. Docker uses the official image and mounts ~/.hermes at /opt/data.",
                "ตั้งค่าทั้งหมดคือทุกหน้า แบบย่อคือติดตั้ง ผู้ให้บริการ แชททดลองหนึ่งครั้ง บอทที่เลือก และตรวจครั้งสุดท้าย สลับทีหลังได้ แบบในเครื่องคือการติดตั้งจากซอร์สแบบเดิม Docker ใช้อิมเมจทางการและเมานต์ ~/.hermes ที่ /opt/data",
                mode,
            )
        )
        self._load()

    def _load(self) -> None:
        data = self.session.progress
        self._guard = True
        (self.quick if data.get("setup_profile") == "quick" else self.full).setChecked(True)
        bot = data.get("quick_bot") or "telegram"
        self.bots.get(bot, self.bots["telegram"]).setChecked(True)
        (self.docker if data.get("install_mode") == "docker" else self.native).setChecked(True)
        self.bot_label.setVisible(self.quick.isChecked())
        self.bot_row.setVisible(self.quick.isChecked())
        self._guard = False

    def _save(self) -> None:
        if self._guard:
            return
        self.session.progress["setup_profile"] = "quick" if self.quick.isChecked() else "full"
        for bot_id, button in self.bots.items():
            if button.isChecked():
                self.session.progress["quick_bot"] = bot_id
        self.session.progress["install_mode"] = "docker" if self.docker.isChecked() else "native"
        progress.save(self.session.progress)
        self.bot_label.setVisible(self.quick.isChecked())
        self.bot_row.setVisible(self.quick.isChecked())
        self.changed.emit()
        self.session.profile_changed.emit()


class WelcomePage(QWidget, LanguageMixin):
    open_page = Signal(str)

    def __init__(self, session):
        super().__init__()
        self.session = session
        root = QVBoxLayout(self)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        self.title = QLabel()
        self.title.setObjectName("title")
        self.lead = QLabel()
        self.lead.setWordWrap(True)
        self.choices = ChoiceBar(session)
        self.steps = QLabel()
        self.steps.setWordWrap(True)
        frame, body = card()
        body.addWidget(self.lead)
        body.addWidget(self.choices)
        body.addWidget(self.steps)
        self.start = QPushButton()
        self.start.clicked.connect(lambda: self.open_page.emit("install"))
        self.path_copy = CopyButton('export PATH="$HOME/.local/bin:$PATH"', "Copy PATH line", "คัดลอกบรรทัด PATH")
        layout.addWidget(self.title)
        layout.addWidget(frame)
        layout.addWidget(self.start, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.path_copy, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addStretch(1)
        root.addWidget(_scroll(inner))
        self.choices.changed.connect(lambda: self.apply_language(self.mode))
        self.apply_language("both")

    def apply_language(self, mode: str) -> None:
        super().apply_language(mode)
        self.title.setText(join("Welcome", "เริ่มต้น", mode))
        self.lead.setText(
            join(
                "This window installs Hermes Agent and fills its real config files. "
                "Nothing runs until you press a button. You can jump back to any page. "
                "The machine this was written for is a Dell OptiPlex 3050: Intel i5, 16 GB RAM, no GPU, Ubuntu.",
                "หน้าต่างนี้ติดตั้ง Hermes Agent และกรอกไฟล์คอนฟิกจริงของมัน "
                "ไม่มีอะไรทำงานจนกว่าคุณจะกดปุ่ม ย้อนกลับไปหน้าไหนก็ได้ "
                "เครื่องที่เขียนให้คือ Dell OptiPlex 3050: Intel i5, แรม 16 GB, ไม่มี GPU, Ubuntu",
                mode,
            )
        )
        pages = flow_pages(
            self.session.progress.get("setup_profile") or "full",
            self.session.progress.get("quick_bot") or "telegram",
        )
        self.steps.setText(join("Order: ", "ลำดับ: ", mode) + " → ".join(pages))
        self.choices.apply_language(mode)
        self.start.setText(join("Go to install", "ไปหน้าติดตั้ง", mode))
        self.path_copy.apply_language(mode)


class InstallPage(QWidget, LanguageMixin):
    def __init__(self, session):
        super().__init__()
        self.session = session
        self.steps = load_steps()
        self._thread: InstallThread | None = None
        self._rows: dict[str, tuple[QLabel, QLabel, QPushButton]] = {}
        root = QVBoxLayout(self)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        self.title = QLabel()
        self.title.setObjectName("title")
        self.choices = ChoiceBar(session)
        self.choices.changed.connect(lambda: self.apply_language(self.mode))
        self.intro = Explain()
        self.intro.set_copy(
            help_en="Each button runs one step from the official Hermes install guide. Required steps are the Ubuntu check, the named apt packages, the official install.sh, and a check that hermes starts. Desktop, the gateway service, linger, and the AppArmor profile are optional.",
            help_th="แต่ละปุ่มรันหนึ่งขั้นตอนจากคู่มือติดตั้ง Hermes ขั้นตอนที่จำเป็นคือตรวจ Ubuntu, แพ็กเกจ apt ที่เอกสารระบุ, install.sh ทางการ, และตรวจว่า hermes เริ่มได้ แอปเดสก์ท็อป เซอร์วิสเกตเวย์ linger และโปรไฟล์ AppArmor ไม่บังคับ",
            where_en="Administrator steps ask with pkexec, or with a masked sudo prompt. The password is not stored and is not written here.",
            where_th="ขั้นตอนที่ต้องใช้สิทธิ์ผู้ดูแลจะถามผ่าน pkexec หรือช่อง sudo ที่ปิดบังรหัส รหัสไม่ถูกเก็บและไม่ถูกเขียนที่นี่",
            links=[],
        )
        self.pkexec = QCheckBox()
        self.pkexec.setChecked(True)
        self._copies: list[CopyButton] = []
        buttons = QHBoxLayout()
        self.run_required = QPushButton()
        self.run_required.clicked.connect(self._run_required)
        self.stop = QPushButton()
        self.stop.setProperty("secondary", True)
        self.stop.clicked.connect(self._stop)
        buttons.addWidget(self.run_required)
        buttons.addWidget(self.stop)
        buttons.addStretch(1)
        layout.addWidget(self.title)
        layout.addWidget(self.choices)
        layout.addWidget(self.intro)
        layout.addWidget(self.pkexec)
        layout.addLayout(buttons)
        for step in self.steps:
            frame, body = card()
            title = QLabel()
            summary = QLabel()
            summary.setWordWrap(True)
            status = QLabel("pending")
            row = QHBoxLayout()
            run = QPushButton()
            run.clicked.connect(lambda _checked=False, step_id=step.id: self._run_one(step_id))
            row.addWidget(status)
            row.addStretch(1)
            row.addWidget(run)
            if step.command_hint:
                copy = CopyButton(step.command_hint)
                self._copies.append(copy)
                row.addWidget(copy)
            body.addWidget(title)
            body.addWidget(summary)
            explain = Explain()
            explain.set_copy(
                help_en=step.summary_en,
                help_th=step.summary_th,
                where_en=step.source,
                where_th=step.source,
            )
            body.addWidget(explain)
            body.addLayout(row)
            layout.addWidget(frame)
            self._rows[step.id] = (title, summary, status, run, explain, frame)
        layout.addStretch(1)
        root.addWidget(_scroll(inner))
        self._refresh_status()
        self.apply_language("both")

    def apply_language(self, mode: str) -> None:
        super().apply_language(mode)
        self.title.setText(join("Install", "ติดตั้ง", mode))
        self.choices.apply_language(mode)
        self.intro.apply_language(mode)
        install_mode = self.session.progress.get("install_mode") or "native"
        self.pkexec.setText(
            join(
                "Use the system password dialog (pkexec) for apt steps when it is available",
                "ใช้หน้าต่างรหัสผ่านของระบบ (pkexec) สำหรับขั้นตอน apt เมื่อมี",
                mode,
            )
        )
        self.run_required.setText(join("Run required steps", "รันขั้นตอนที่จำเป็น", mode))
        self.stop.setText(join("Stop", "หยุด", mode))
        saved = self.session.progress
        for step in self.steps:
            title, summary, status, run, explain, frame = self._rows[step.id]
            frame.setVisible(install_mode in step.modes)
            mark = join("optional", "ไม่บังคับ", mode) if step.optional else join("required", "จำเป็น", mode)
            title.setText(f"{join(step.title_en, step.title_th, mode)}  ·  {mark}")
            summary.setText(join(step.summary_en, step.summary_th, mode))
            state = progress.step_status(saved, step.id)
            status.setText(state)
            run.setText(join("Run", "รัน", mode))
            explain.apply_language(mode)
        for copy in self._copies:
            copy.apply_language(mode)

    def _refresh_status(self) -> None:
        self.apply_language(self.mode)

    def _run_required(self) -> None:
        install_mode = self.session.progress.get("install_mode") or "native"
        self._start(
            [step for step in self.steps if not step.optional and install_mode in step.modes]
        )

    def _run_one(self, step_id: str) -> None:
        self._start([step for step in self.steps if step.id == step_id])

    def _start(self, steps: list[Step]) -> None:
        if self._thread and self._thread.isRunning():
            return
        self._thread = InstallThread(steps, self.pkexec.isChecked())
        self._thread.line.connect(self.session.log)
        self._thread.step_changed.connect(self._on_step)
        self._thread.password_needed.connect(self._ask_password)
        self._thread.finished_run.connect(self._refresh_status)
        self._thread.start()

    def _ask_password(self, step_id: str) -> None:
        text, ok = QInputDialog.getText(
            self,
            "sudo",
            join(
                "Administrator password for this step. It is sent only to sudo and is not saved.",
                "รหัสผ่านผู้ดูแลสำหรับขั้นตอนนี้ ส่งให้ sudo เท่านั้น และไม่ถูกบันทึก",
                self.mode,
            ),
            QLineEdit.EchoMode.Password,
        )
        if self._thread:
            self._thread.provide_password(text if ok else None)

    def _on_step(self, step_id: str, status: str, message: str) -> None:
        progress.set_step(self.session.progress, step_id, status, message)
        progress.save(self.session.progress)
        self._refresh_status()
        self.session.milestones_changed.emit()

    def _stop(self) -> None:
        if self._thread:
            self._thread.stop()


class ProviderPage(QWidget, LanguageMixin):
    def __init__(self, session):
        super().__init__()
        self.session = session
        self.providers = load_providers()
        self._thread: CallThread | None = None
        root = QVBoxLayout(self)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        self.title = QLabel()
        self.title.setObjectName("title")
        self.preset_button = QPushButton()
        self.preset_button.clicked.connect(self._apply_preset_click)
        self.preset_check = QCheckBox()
        self.preset_check.setChecked(True)
        self.provider_box = QComboBox()
        for item in self.providers:
            self.provider_box.addItem(item.title_en, item.id)
        self.provider_box.currentIndexChanged.connect(self._show_provider)
        self.about = Explain()
        self.typed_provider = QLineEdit()
        self.typed_key_env = QLineEdit()
        self.key = SecretEdit()
        self.model = QComboBox()
        self.model.setEditable(True)
        self.base = QLineEdit()
        self.context = QLineEdit()
        self.fetch = QPushButton()
        self.fetch.setProperty("secondary", True)
        self.fetch.clicked.connect(self._fetch)
        self.save = QPushButton()
        self.save.clicked.connect(self._save)
        self.test = QPushButton()
        self.test.setProperty("secondary", True)
        self.test.clicked.connect(self._test)
        self.result = QLabel()
        self.result.setWordWrap(True)
        self.key_explain = Explain()
        self.model_explain = Explain()
        layout.addWidget(self.title)
        layout.addWidget(self.preset_button, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.preset_check)
        layout.addWidget(QLabel("Provider"))
        layout.addWidget(self.provider_box)
        layout.addWidget(self.about)
        self.form_provider = self.typed_provider
        self.form_key_env = self.typed_key_env
        layout.addWidget(self.typed_provider)
        layout.addWidget(self.typed_key_env)
        layout.addWidget(self.key)
        layout.addWidget(self.key_explain)
        layout.addWidget(self.model)
        layout.addWidget(self.fetch, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.model_explain)
        layout.addWidget(self.base)
        layout.addWidget(self.context)
        row = QHBoxLayout()
        row.addWidget(self.save)
        row.addWidget(self.test)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addWidget(self.result)
        portal = CopyButton("hermes setup --portal", "Copy Nous login command", "คัดลอกคำสั่งล็อกอิน Nous")
        model_cmd = CopyButton("hermes model", "Copy hermes model", "คัดลอก hermes model")
        layout.addWidget(portal, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(model_cmd, alignment=Qt.AlignmentFlag.AlignLeft)
        self._copies = (portal, model_cmd)
        layout.addStretch(1)
        root.addWidget(_scroll(inner))
        self._show_provider()
        self.apply_language("both")

    def current(self) -> Provider:
        provider_id = self.provider_box.currentData()
        return next(item for item in self.providers if item.id == provider_id)

    def _show_provider(self) -> None:
        item = self.current()
        self.about.set_copy(
            help_en=item.about_en,
            help_th=item.about_th,
            where_en=item.where_en + ("\n\n" + item.low_spec_en if item.low_spec_en else ""),
            where_th=item.where_th + ("\n\n" + item.low_spec_th if item.low_spec_th else ""),
            example=item.example_key,
            links=item.links,
        )
        self.typed_provider.setVisible(item.allow_typed_provider)
        self.typed_key_env.setVisible(item.allow_typed_key_env)
        self.key.setVisible(bool(item.key_env) or item.allow_typed_key_env)
        self.base.setVisible(bool(item.base_url_env) or item.base_in_config or item.id == "other")
        self.context.setVisible(item.show_context)
        self.model.clear()
        if item.example_model:
            self.model.addItem(item.example_model)
            self.model.setCurrentText(item.default_model or item.example_model)
        elif item.default_model:
            self.model.addItem(item.default_model)
            self.model.setCurrentText(item.default_model)
        if item.default_base_url:
            self.base.setText(item.default_base_url)
        else:
            self.base.clear()
        self.key_explain.set_copy(
            help_en="The key is masked. Show reveals it on this screen only. Save writes the OS keyring and ~/.hermes/.env with mode 0600.",
            help_th="คีย์ถูกปิดบัง ปุ่ม Show เปิดให้เห็นบนจอนี้เท่านั้น การบันทึกเขียนพวงกุญแจของระบบและ ~/.hermes/.env ด้วยสิทธิ์ 0600",
            example=item.example_key,
            links=item.links,
        )
        self.model_explain.set_copy(
            help_en="Type or pick a model id. For OpenRouter, DeepSeek ids look like deepseek/deepseek-... . Fetch models asks the provider's model list and keeps only ids containing 'deepseek' for the OpenRouter choice.",
            help_th="พิมพ์หรือเลือกชื่อโมเดล บน OpenRouter ชื่อ DeepSeek มีรูป deepseek/deepseek-... ปุ่มดึงรายการขอรายชื่อจากผู้ให้บริการ และสำหรับ OpenRouter จะเหลือเฉพาะชื่อที่มีคำว่า deepseek",
            example=item.example_model,
        )
        self.about.apply_language(self.mode)
        self.key_explain.apply_language(self.mode)
        self.model_explain.apply_language(self.mode)

    def apply_language(self, mode: str) -> None:
        super().apply_language(mode)
        self.title.setText(join("Provider and AI model", "ผู้ให้บริการและโมเดล AI", mode))
        self.preset_button.setText(
            join(
                "Fill the recommended preset (OpenRouter + DeepSeek)",
                "เติมค่าที่แนะนำ (OpenRouter + DeepSeek)",
                mode,
            )
        )
        self.preset_check.setText(
            join(
                "Also save the low-spec config: local terminal, Asia/Bangkok, smart approvals, OpenRouter price routing",
                "บันทึกค่าเครื่องสเปกต่ำด้วย: เทอร์มินัล local, Asia/Bangkok, การอนุมัติแบบ smart, จัดเส้นทาง OpenRouter ตามราคา",
                mode,
            )
        )
        self.fetch.setText(join("Fetch DeepSeek models", "ดึงรายชื่อโมเดล DeepSeek", mode))
        self.save.setText(join("Save", "บันทึก", mode))
        self.test.setText(join("Test connection", "ทดสอบการเชื่อมต่อ", mode))
        self.typed_provider.setPlaceholderText("provider id, for example minimax")
        self.typed_key_env.setPlaceholderText("KEY VARIABLE, for example MINIMAX_API_KEY")
        self.base.setPlaceholderText("base URL")
        self.context.setPlaceholderText("context length, for example 64000")
        self.about.apply_language(mode)
        self.key_explain.apply_language(mode)
        self.model_explain.apply_language(mode)
        for button in self._copies:
            button.apply_language(mode)

    def _apply_preset_click(self) -> None:
        index = self.provider_box.findData("openrouter")
        if index >= 0:
            self.provider_box.setCurrentIndex(index)
        provider = next(item for item in self.providers if item.id == "openrouter")
        self.model.setCurrentText(provider.default_model)
        self.result.setText(
            join(
                "Preset filled. Paste your OpenRouter key, then Save.",
                "เติมค่าแล้ว วางคีย์ OpenRouter แล้วกดบันทึก",
                self.mode,
            )
        )

    def _save(self) -> None:
        item = self.current()
        try:
            changed = apply_mod.save_provider(
                item,
                model=self.model.currentText(),
                api_key=self.key.text(),
                base_url=self.base.text(),
                context_length=self.context.text(),
                typed_provider=self.typed_provider.text(),
                typed_key_env=self.typed_key_env.text(),
                also_preset=self.preset_check.isChecked() and item.recommended,
                config_file=config_path(),
                env_file=env_path(),
            )
        except ConfigError as exc:
            self.result.setText(str(exc))
            return
        self.key.setText("")
        self.session.log("Saved " + redact_mapping_preview(changed))
        self.result.setText(join("Saved.", "บันทึกแล้ว", self.mode) + " " + ", ".join(changed))
        self.session.milestones_changed.emit()

    def _test(self) -> None:
        self._run_probe(test=True)

    def _fetch(self) -> None:
        self._run_probe(test=False)

    def _run_probe(self, test: bool) -> None:
        item = self.current()
        key = self.key.text().strip()
        if not key and item.key_env:
            key = secrets.load(item.key_env, env_path()) or ""
        model = "" if not test else self.model.currentText()
        base = self.base.text()

        def work():
            if test:
                return probe_provider(item, api_key=key, model=model, base_url=base)
            needle = "deepseek" if item.id == "openrouter" else ""
            return fetch_model_ids(item, api_key=key, base_url=base, contains=needle)

        self.result.setText(join("Contacting the provider…", "กำลังติดต่อผู้ให้บริการ…", self.mode))
        self._fill_models = not test
        self._thread = CallThread(work)
        self._thread.succeeded.connect(self._probe_done)
        self._thread.failed.connect(lambda message: self.result.setText(message))
        self._thread.start()

    def _probe_done(self, probe) -> None:
        self.result.setText(f"{probe.status}: {probe.detail}")
        self.session.log(f"Provider test {probe.status}: {probe.detail}")
        if self._fill_models and probe.models:
            current = self.model.currentText()
            self.model.clear()
            for model_id in probe.models[:200]:
                self.model.addItem(model_id)
            if current:
                self.model.setCurrentText(current)


class CliChatPage(QWidget, LanguageMixin):
    def __init__(self, session):
        super().__init__()
        self.session = session
        self._thread: CallThread | None = None
        root = QVBoxLayout(self)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        self.title = QLabel()
        self.title.setObjectName("title")
        self.explain = Explain()
        self.explain.set_copy(
            help_en="Sends one short prompt and shows the reply before you set up Telegram, Discord, or LINE. Native mode runs hermes chat -q, which the docs describe as a one-shot chat. Docker mode runs docker run --rm -v ~/.hermes:/opt/data nousresearch/hermes-agent chat -q, the entrypoint form the Docker guide lists. The prompt is one line and is not a secret. Save the provider first so this call has a key.",
            help_th="ส่งพรอมต์สั้นหนึ่งครั้งและแสดงคำตอบ ก่อนตั้ง Telegram, Discord หรือ LINE โหมดในเครื่องรัน hermes chat -q ซึ่งเอกสารบอกว่าเป็นแชทครั้งเดียว โหมด Docker รัน docker run --rm -v ~/.hermes:/opt/data nousresearch/hermes-agent chat -q ตามรูปแบบที่คู่มือ Docker ระบุ พรอมต์เป็นบรรทัดเดียวและไม่ใช่ความลับ บันทึกผู้ให้บริการก่อน เพื่อให้การเรียกนี้มีคีย์",
            where_en="https://hermes-agent.nousresearch.com/docs/user-guide/docker",
            where_th="https://hermes-agent.nousresearch.com/docs/user-guide/docker",
        )
        self.prompt = QLineEdit("Reply with exactly: pong")
        self.run = QPushButton()
        self.run.clicked.connect(self._run)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.result = QLabel()
        self.result.setWordWrap(True)
        layout.addWidget(self.title)
        layout.addWidget(self.explain)
        layout.addWidget(self.prompt)
        layout.addWidget(self.run, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.result)
        layout.addWidget(self.output)
        root.addWidget(_scroll(inner))
        self.apply_language("both")

    def apply_language(self, mode: str) -> None:
        super().apply_language(mode)
        self.title.setText(join("Test CLI chat", "ทดลองแชทบรรทัดคำสั่ง", mode))
        self.explain.apply_language(mode)
        self.run.setText(join("Send test prompt", "ส่งพรอมต์ทดสอบ", mode))

    def _run(self) -> None:
        mode = self.session.progress.get("install_mode") or "native"
        prompt = self.prompt.text()

        def work():
            import subprocess

            argv = cli_chat_argv(mode, prompt, home=hermes_home())
            completed = subprocess.run(
                argv,
                check=False,
                capture_output=True,
                text=True,
                timeout=180,
                env=__import__("hermes_wizard.paths", fromlist=["command_env"]).command_env(),
            )
            text = ((completed.stdout or "") + (completed.stderr or "")).strip()
            return completed.returncode, text

        self.result.setText(join("Waiting for Hermes…", "กำลังรอ Hermes…", self.mode))
        self._thread = CallThread(work)
        self._thread.succeeded.connect(self._done)
        self._thread.failed.connect(self._failed)
        self._thread.start()

    def _done(self, payload) -> None:
        code, text = payload
        from hermes_wizard.redact import redact

        shown = redact(text)[:8000]
        self.output.setPlainText(shown)
        status = "ok" if code == 0 and shown else "failed"
        progress.set_step(self.session.progress, "cli-chat", status, f"exit {code}")
        progress.save(self.session.progress)
        self.result.setText("ok" if status == "ok" else f"exit {code}")
        self.session.log(f"CLI chat {status}")
        self.session.profile_changed.emit()

    def _failed(self, message: str) -> None:
        progress.set_step(self.session.progress, "cli-chat", "failed", message)
        progress.save(self.session.progress)
        self.result.setText(message)
        self.session.log(message)
        self.session.profile_changed.emit()


class GatewayPage(QWidget, LanguageMixin):
    def __init__(self, session, gateway: Gateway):
        super().__init__()
        self.session = session
        self.gateway = gateway
        self._thread: CallThread | None = None
        self.blocks: list[tuple[str, FieldBlock, bool]] = []
        root = QVBoxLayout(self)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        self.title = QLabel()
        self.title.setObjectName("title")
        self.cli_warning = QLabel()
        self.cli_warning.setWordWrap(True)
        self.cli_warning.setStyleSheet("background:#fef3c7;padding:8px;border-radius:6px;")
        self.banner = QLabel()
        self.banner.setWordWrap(True)
        self.steps = QLabel()
        self.steps.setWordWrap(True)
        self.steps.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.enabled = QCheckBox()
        stored = _safe_config() or {}
        current_enabled = configio.get_dotted(stored, gateway.enabled_key) if gateway.enabled_key else None
        self.enabled.setChecked(True if current_enabled is None else bool(current_enabled))
        self.save = QPushButton()
        self.save.clicked.connect(self._save)
        self.test = QPushButton()
        self.test.setProperty("secondary", True)
        self.test.setVisible(gateway.test != "none")
        self.test.clicked.connect(self._test)
        self.result = QLabel()
        self.result.setWordWrap(True)
        self.doc_copy = CopyButton(gateway.doc, "Copy documentation link", "คัดลอกลิงก์เอกสาร")
        self.setup_copy = CopyButton("hermes gateway setup", "Copy gateway setup command", "คัดลอกคำสั่งตั้งเกตเวย์")
        self.start_copy = CopyButton("hermes gateway start", "Copy start command", "คัดลอกคำสั่งเริ่มเกตเวย์")
        layout.addWidget(self.title)
        layout.addWidget(self.cli_warning)
        layout.addWidget(self.banner)
        layout.addWidget(self.steps)
        layout.addWidget(self.doc_copy, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.setup_copy, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.start_copy, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.enabled)
        for field in gateway.fields:
            block = FieldBlock(field.title_en, field.title_th, "str", secret=field.secret)
            block.explain.set_copy(
                help_en=field.help_en,
                help_th=field.help_th,
                where_en=field.where_en,
                where_th=field.where_th,
                example=field.example,
                links=field.links,
            )
            if field.placeholder and isinstance(block.editor, (QLineEdit, SecretEdit)):
                if isinstance(block.editor, QLineEdit):
                    block.editor.setPlaceholderText(field.placeholder)
                else:
                    block.editor.edit.setPlaceholderText(field.placeholder)
            self.blocks.append((field.key, block, field.secret))
            layout.addWidget(block)
        row = QHBoxLayout()
        row.addWidget(self.save)
        row.addWidget(self.test)
        row.addStretch(1)
        layout.addLayout(row)
        layout.addWidget(self.result)
        layout.addStretch(1)
        root.addWidget(_scroll(inner))
        self.apply_language("both")

    def apply_language(self, mode: str) -> None:
        super().apply_language(mode)
        gate = self.gateway
        self.title.setText(join(gate.title_en, gate.title_th, mode))
        passed = progress.step_status(self.session.progress, "cli-chat") == "ok"
        self.cli_warning.setVisible(not passed)
        self.cli_warning.setText(
            join(
                "The CLI test chat has not passed yet. Open Test CLI chat and send the prompt before relying on this bot.",
                "แชททดลองบรรทัดคำสั่งยังไม่ผ่าน เปิดหน้าทดลองแชทแล้วส่งพรอมต์ก่อนพึ่งบอทนี้",
                mode,
            )
        )
        self.banner.setText(join(gate.banner_en, gate.banner_th, mode))
        self.steps.setText(join(gate.steps_en, gate.steps_th, mode))
        self.enabled.setText(join(f"Enable {gate.title_en}", f"เปิดใช้ {gate.title_th}", mode))
        self.save.setText(join("Save", "บันทึก", mode))
        self.test.setText(join("Test connection", "ทดสอบการเชื่อมต่อ", mode))
        for _key, block, _secret in self.blocks:
            block.apply_language(mode)
        for button in (self.doc_copy, self.setup_copy, self.start_copy):
            button.apply_language(mode)

    def _save(self) -> None:
        try:
            changed = apply_mod.save_gateway(
                enabled_key=self.gateway.enabled_key,
                enabled=self.enabled.isChecked(),
                fields=[(key, str(block.value()), secret) for key, block, secret in self.blocks],
                config_file=config_path(),
                env_file=env_path(),
            )
        except ConfigError as exc:
            self.result.setText(str(exc))
            return
        for _key, block, secret in self.blocks:
            if secret:
                block.set_value("")
        self.session.log("Saved " + redact_mapping_preview(changed))
        self.result.setText(join("Saved.", "บันทึกแล้ว", self.mode))
        self.session.milestones_changed.emit()

    def _test(self) -> None:
        gate = self.gateway
        token = ""
        if gate.token_key:
            for key, block, _secret in self.blocks:
                if key == gate.token_key:
                    token = str(block.value()).strip()
            if not token:
                token = secrets.load(gate.token_key, env_path()) or ""

        def work():
            return probe_gateway(gate.test, token)

        self.result.setText(join("Testing…", "กำลังทดสอบ…", self.mode))
        self._thread = CallThread(work)
        self._thread.succeeded.connect(self._show_probe)
        self._thread.failed.connect(lambda message: self.result.setText(message))
        self._thread.start()

    def _show_probe(self, probe) -> None:
        text = f"{probe.status}: {probe.detail}"
        self.result.setText(text)
        self.session.log(f"{self.gateway.id} test {text}")


class SettingsPage(QWidget, LanguageMixin):
    def __init__(self, session, group_id: str, title_en: str, title_th: str, settings: list[Setting]):
        super().__init__()
        self.session = session
        self.group_id = group_id
        self.title_en = title_en
        self.title_th = title_th
        self.settings = settings
        self.blocks: list[tuple[Setting, FieldBlock]] = []
        root = QVBoxLayout(self)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        self.title = QLabel()
        self.title.setObjectName("title")
        self.note = QLabel()
        self.note.setWordWrap(True)
        layout.addWidget(self.title)
        layout.addWidget(self.note)
        data = _safe_config()
        env = configio.read_env(env_path()) if env_path().exists() else {}
        for setting in settings:
            block = FieldBlock(
                setting.title_en,
                setting.title_th,
                "bool" if setting.type == "bool" else "choice" if setting.type == "choice" else "str",
                choices=setting.choices,
                secret=setting.secret,
            )
            source = f"\n{setting.source}" if setting.source else ""
            block.explain.set_copy(
                help_en=setting.help_en,
                help_th=setting.help_th,
                where_en=(setting.where_en + source).strip(),
                where_th=(setting.where_th + source).strip(),
                example=setting.example,
                links=setting.links,
            )
            if setting.secret:
                state = secrets.status(setting.key, env_path())
                if state != "missing" and isinstance(block.editor, SecretEdit):
                    block.editor.edit.setPlaceholderText("saved")
            else:
                if setting.storage == "env":
                    current = env.get(setting.key)
                else:
                    current = configio.get_dotted(data, setting.key) if data is not None else None
                shown = format_loaded(setting, current)
                if setting.type == "bool":
                    block.set_value(shown == "true" or (shown == "" and setting.default is True))
                else:
                    block.set_value(shown)
            self.blocks.append((setting, block))
            layout.addWidget(block)
        self.save = QPushButton()
        self.save.clicked.connect(self._save)
        self.result = QLabel()
        self.result.setWordWrap(True)
        layout.addWidget(self.save, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.result)
        layout.addStretch(1)
        root.addWidget(_scroll(inner))
        self.apply_language("both")

    def apply_language(self, mode: str) -> None:
        super().apply_language(mode)
        self.title.setText(join(self.title_en, self.title_th, mode))
        self.note.setText(
            join(
                "Blank optional text is removed on save, so Hermes keeps its own default. Open the hint under each field.",
                "ข้อความที่ไม่บังคับถ้าเว้นว่างจะถูกลบตอนบันทึก Hermes จึงใช้ค่าเริ่มต้นของมัน เปิดคำอธิบายใต้แต่ละช่องได้",
                mode,
            )
        )
        self.save.setText(join("Save this page", "บันทึกหน้านี้", mode))
        for _setting, block in self.blocks:
            block.apply_language(mode)

    def _save(self) -> None:
        if self.group_id == "security":
            for setting, block in self.blocks:
                if setting.key == "approvals.mode" and str(block.value()) == "off":
                    answer = QMessageBox.question(
                        self,
                        "approvals.mode",
                        join(
                            "off disables command approval checks. Save it anyway?",
                            "ค่า off ปิดการตรวจคำสั่ง ยังจะบันทึกไหม",
                            self.mode,
                        ),
                    )
                    if answer != QMessageBox.StandardButton.Yes:
                        return
        try:
            changed = apply_mod.save_settings(
                [(setting, block.value()) for setting, block in self.blocks],
                config_file=config_path(),
                env_file=env_path(),
            )
        except ConfigError as exc:
            self.result.setText(str(exc))
            return
        self.session.log("Saved " + redact_mapping_preview(changed))
        self.result.setText(join("Saved.", "บันทึกแล้ว", self.mode))


class ExtraKeyPage(QWidget, LanguageMixin):
    def __init__(self, session):
        super().__init__()
        self.session = session
        root = QVBoxLayout(self)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        self.title = QLabel()
        self.title.setObjectName("title")
        self.explain = Explain()
        self.explain.set_copy(
            help_en="Use this when a Hermes setting is not on the other pages. Type the exact key from the official docs. UPPER_SNAKE names go to ~/.hermes/.env. Dotted names go to config.yaml. Names that look like secrets cannot be dotted, so a raw API key is not written into config.yaml. PATH and HERMES_YOLO_MODE are refused.",
            help_th="ใช้เมื่อการตั้งค่าของ Hermes ไม่อยู่ในหน้าอื่น พิมพ์ชื่อคีย์ให้ตรงเอกสาร ชื่อตัวใหญ่ขีดล่างไปที่ ~/.hermes/.env ชื่อที่มีจุดไปที่ config.yaml ชื่อที่ดูเหมือนความลับจะใส่แบบมีจุดไม่ได้ เพื่อไม่ให้คีย์ดิบไปอยู่ใน config.yaml PATH และ HERMES_YOLO_MODE ถูกปฏิเสธ",
            where_en="https://hermes-agent.nousresearch.com/docs/user-guide/configuration and the environment-variable reference.",
            where_th="หน้า configuration และหน้ารายการตัวแปรสภาพแวดล้อมของ Hermes",
            example="model.provider or OPENROUTER_API_KEY",
            links=[],
        )
        self.key = QLineEdit()
        self.key.setPlaceholderText("model.context_length")
        self.value = SecretEdit()
        self.secret = QCheckBox()
        self.save = QPushButton()
        self.save.clicked.connect(self._save)
        self.result = QLabel()
        self.result.setWordWrap(True)
        layout.addWidget(self.title)
        layout.addWidget(self.explain)
        layout.addWidget(self.key)
        layout.addWidget(self.value)
        layout.addWidget(self.secret)
        layout.addWidget(self.save, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.result)
        layout.addStretch(1)
        root.addWidget(_scroll(inner))
        self.apply_language("both")

    def apply_language(self, mode: str) -> None:
        super().apply_language(mode)
        self.title.setText(join("More keys", "คีย์เพิ่มเติม", mode))
        self.explain.apply_language(mode)
        self.secret.setText(join("This value is a secret", "ค่านี้เป็นความลับ", mode))
        self.save.setText(join("Save", "บันทึก", mode))

    def _save(self) -> None:
        try:
            name = apply_mod.save_extra_key(
                self.key.text().strip(),
                self.value.text(),
                secret=self.secret.isChecked(),
                config_file=config_path(),
                env_file=env_path(),
            )
        except ConfigError as exc:
            self.result.setText(str(exc))
            return
        self.value.setText("")
        self.session.log("Saved " + redact_mapping_preview([name]))
        self.result.setText(join("Saved.", "บันทึกแล้ว", self.mode) + " " + name)


class HealthPage(QWidget, LanguageMixin):
    open_page = Signal(str)

    def __init__(self, session):
        super().__init__()
        self.session = session
        self.checks = load_checks()
        self._thread: CallThread | None = None
        self.rows: dict[str, tuple[QLabel, QLabel, QPushButton]] = {}
        root = QVBoxLayout(self)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        self.title = QLabel()
        self.title.setObjectName("title")
        self.intro = QLabel()
        self.intro.setWordWrap(True)
        self.run = QPushButton()
        self.run.clicked.connect(self._run)
        layout.addWidget(self.title)
        layout.addWidget(self.intro)
        layout.addWidget(self.run, alignment=Qt.AlignmentFlag.AlignLeft)
        for check in self.checks:
            frame, body = card()
            title = QLabel()
            detail = QLabel()
            detail.setWordWrap(True)
            fix = QPushButton()
            fix.setProperty("secondary", True)
            fix.clicked.connect(lambda _checked=False, page=check.fix_page: self.open_page.emit(page))
            body.addWidget(title)
            body.addWidget(detail)
            body.addWidget(fix, alignment=Qt.AlignmentFlag.AlignLeft)
            layout.addWidget(frame)
            self.rows[check.id] = (title, detail, fix)
        layout.addStretch(1)
        root.addWidget(_scroll(inner))
        self.apply_language("both")

    def apply_language(self, mode: str) -> None:
        super().apply_language(mode)
        self.title.setText(join("Final check", "ตรวจครั้งสุดท้าย", mode))
        self.intro.setText(
            join(
                "Runs the install, config, OpenRouter key, gateway, and chat-bot checks. Fix jumps back to the page that owns that item. A skipped chat bot means its token is not stored yet.",
                "ตรวจการติดตั้ง คอนฟิก คีย์ OpenRouter เกตเวย์ และแชทบอท ปุ่มไปแก้พากลับไปหน้าที่เกี่ยวข้อง แชทบอทที่ถูกข้ามแปลว่ายังไม่ได้เก็บโทเคน",
                mode,
            )
        )
        self.run.setText(join("Run checks", "ตรวจใหม่", mode))
        for check in self.checks:
            title, _detail, fix = self.rows[check.id]
            mark = join("optional", "ไม่บังคับ", mode) if check.optional else join("required", "จำเป็น", mode)
            title.setText(f"{join(check.title_en, check.title_th, mode)}  ·  {mark}")
            fix.setText(join("Fix", "ไปแก้", mode))

    def _run(self) -> None:
        checks = self.checks
        install_mode = self.session.progress.get("install_mode") or "native"

        def work():
            return run_checks(checks, install_mode=install_mode)

        self._thread = CallThread(work)
        self._thread.succeeded.connect(self._show)
        self._thread.failed.connect(lambda message: self.session.log(message))
        self._thread.start()

    def _show(self, report) -> None:
        failed_required = False
        for item in report.results:
            title, detail, _fix = self.rows[item.id]
            detail.setText(f"{item.status}: {item.detail}")
            self.session.log(f"check {item.id} {item.status}")
            if item.status == "fail" and not item.optional:
                failed_required = True
        self.session.progress["health_status"] = "fail" if failed_required else "pass"
        progress.save(self.session.progress)
        self.session.milestones_changed.emit()


class FaqPage(QWidget, LanguageMixin):
    def __init__(self):
        super().__init__()
        self.items = load_faq()
        self.blocks: list[tuple[FaqItem, QLabel, Explain, CopyButton | None]] = []
        root = QVBoxLayout(self)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        self.title = QLabel()
        self.title.setObjectName("title")
        layout.addWidget(self.title)
        for item in self.items:
            question = QLabel()
            question.setWordWrap(True)
            question.setStyleSheet("font-weight: 600;")
            explain = Explain()
            explain.set_copy(help_en=item.a_en, help_th=item.a_th)
            explain.toggle.setChecked(True)
            copy = CopyButton(item.command) if item.command else None
            layout.addWidget(question)
            layout.addWidget(explain)
            if copy:
                layout.addWidget(copy, alignment=Qt.AlignmentFlag.AlignLeft)
            self.blocks.append((item, question, explain, copy))
        layout.addStretch(1)
        root.addWidget(_scroll(inner))
        self.apply_language("both")

    def apply_language(self, mode: str) -> None:
        super().apply_language(mode)
        self.title.setText(join("Troubleshooting", "แก้ปัญหา", mode))
        for item, question, explain, copy in self.blocks:
            question.setText(join(item.q_en, item.q_th, mode))
            explain.apply_language(mode)
            if copy:
                copy.apply_language(mode)


class UpdatesPage(QWidget, LanguageMixin):
    def __init__(self, session):
        super().__init__()
        self.session = session
        root = QVBoxLayout(self)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        self.title = QLabel()
        self.title.setObjectName("title")
        self.explain = Explain()
        self.explain.set_copy(
            help_en="This updates the wizard checkout with git pull --ff-only. It does not push, and it does not publish the private repository. If you edited files here, commit or stash them first. Restart the wizard after a successful pull. Updating Hermes itself is hermes update, which is a different command.",
            help_th="ปุ่มนี้อัปเดตโฟลเดอร์ตัวช่วยด้วย git pull --ff-only มันไม่ push และไม่เผยแพร่ที่เก็บส่วนตัว ถ้าคุณแก้ไฟล์ไว้ ให้ commit หรือ stash ก่อน เปิดตัวช่วยใหม่หลังดึงสำเร็จ การอัปเดตตัว Hermes คือ hermes update คนละคำสั่ง",
        )
        self.pull = QPushButton()
        self.pull.clicked.connect(self._pull)
        self.hermes_update = QPushButton()
        self.hermes_update.clicked.connect(self._update_hermes)
        self.copy = CopyButton("hermes update", "Copy hermes update", "คัดลอก hermes update")
        self.backup_explain = Explain()
        self.backup_explain.set_copy(
            help_en="The archive is a timestamped tar.gz of ~/.hermes. It contains API keys and bot tokens. The file mode is 0600. Keep it on this PC. Restore replaces the current ~/.hermes directory.",
            help_th="ไฟล์สำรองคือ tar.gz ตามเวลาของ ~/.hermes ข้างในมีคีย์ API และโทเคนบอท สิทธิ์ไฟล์เป็น 0600 เก็บไว้บนเครื่องนี้ การกู้คืนจะแทนที่โฟลเดอร์ ~/.hermes ปัจจุบัน",
        )
        self.backup = QPushButton()
        self.backup.setProperty("secondary", True)
        self.backup.clicked.connect(self._backup)
        self.restore_path = QLineEdit()
        self.restore_path.setPlaceholderText("/home/you/hermes-backups/hermes-YYYYMMDD-HHMMSS.tar.gz")
        self.restore = QPushButton()
        self.restore.setProperty("secondary", True)
        self.restore.clicked.connect(self._restore)
        self.result = QLabel()
        self.result.setWordWrap(True)
        self._thread: CallThread | None = None
        layout.addWidget(self.title)
        layout.addWidget(self.explain)
        layout.addWidget(self.hermes_update, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.pull, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.copy, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.backup_explain)
        layout.addWidget(self.backup, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.restore_path)
        layout.addWidget(self.restore, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.result)
        layout.addStretch(1)
        root.addWidget(_scroll(inner))
        self.apply_language("both")

    def apply_language(self, mode: str) -> None:
        super().apply_language(mode)
        self.title.setText(join("Updates", "อัปเดต", mode))
        self.explain.apply_language(mode)
        self.backup_explain.apply_language(mode)
        install_mode = self.session.progress.get("install_mode") or "native"
        if install_mode == "docker":
            self.hermes_update.setText(
                join(
                    "Update Hermes (docker pull and recreate)",
                    "อัปเดต Hermes (docker pull แล้วสร้างคอนเทนเนอร์ใหม่)",
                    mode,
                )
            )
        else:
            self.hermes_update.setText(join("Update Hermes (hermes update)", "อัปเดต Hermes (hermes update)", mode))
        self.pull.setText(join("Update this wizard (git pull)", "อัปเดตตัวช่วยนี้ (git pull)", mode))
        self.backup.setText(join("Back up ~/.hermes", "สำรอง ~/.hermes", mode))
        self.restore.setText(join("Restore from the archive path", "กู้คืนจากพาธไฟล์สำรอง", mode))
        self.copy.apply_language(mode)

    def _pull(self) -> None:
        result = pull_ff_only(repo_root())
        self.result.setText(result.summary + ("\n" + result.output if result.output else ""))
        self.session.log(result.summary)

    def _update_hermes(self) -> None:
        mode = self.session.progress.get("install_mode") or "native"
        home = hermes_home()
        commands = update_hermes_commands(mode, home=home, uid=os.getuid(), gid=os.getgid())

        def work():
            import subprocess

            from hermes_wizard.paths import command_env

            chunks = []
            for argv in commands:
                completed = subprocess.run(
                    argv,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=600,
                    env=command_env(),
                )
                chunks.append("$ " + " ".join(argv[:6]))
                chunks.append(((completed.stdout or "") + (completed.stderr or "")).strip())
                if completed.returncode != 0:
                    return completed.returncode, "\n".join(chunks)
            return 0, "\n".join(chunks)

        self._run_background(work)

    def _backup(self) -> None:
        home = hermes_home()
        dest = Path.home() / "hermes-backups"

        def work():
            path = backup_home(home, dest)
            return 0, str(path)

        self._run_background(work)

    def _restore(self) -> None:
        archive = Path(self.restore_path.text().strip())
        answer = QMessageBox.question(
            self,
            "restore",
            join(
                "Replace ~/.hermes with this archive? It overwrites config and keys.",
                "แทนที่ ~/.hermes ด้วยไฟล์นี้ไหม มันจะเขียนทับคอนฟิกและคีย์",
                self.mode,
            ),
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        def work():
            restore_home(archive, hermes_home())
            return 0, f"restored {archive.name}"

        self._run_background(work)

    def _run_background(self, work) -> None:
        from hermes_wizard.redact import redact

        self.result.setText(join("Working…", "กำลังทำ…", self.mode))
        self._thread = CallThread(work)
        self._thread.succeeded.connect(lambda payload: self._show_job(payload, redact))
        self._thread.failed.connect(lambda message: self.result.setText(message))
        self._thread.start()

    def _show_job(self, payload, redact) -> None:
        code, text = payload
        self.result.setText(redact(text)[:4000])
        self.session.log("update/backup finished" if code == 0 else "update/backup failed")


def _safe_config():
    path = config_path()
    if not path.exists():
        return {}
    try:
        return configio.load_yaml(path)
    except ConfigError:
        return None

