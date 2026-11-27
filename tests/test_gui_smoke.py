"""Build the window offscreen when PySide6 is installed."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")


def test_window_builds(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "share"))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))
    from PySide6.QtWidgets import QApplication

    from hermes_wizard.catalog import MAIN_FLOW
    from hermes_wizard.gui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    titles = [window.nav.item(i).text() for i in range(window.nav.count())]
    assert any("Provider" in title or "ผู้ให้บริการ" in title for title in titles)
    for page_id in ("welcome", "install", "provider", "telegram", "discord", "line", "health", "faq"):
        assert page_id in window.pages
    order = [page_id for page_id in window.nav_ids if page_id in MAIN_FLOW]
    assert order == list(MAIN_FLOW)
    window.open_page("provider")
    window.open_page("line")
    window.open_page("telegram")
    window.apply_language("th")
    window.append_log("OPENROUTER_API_KEY=sk-or-v1-should-not-stay")
    assert "sk-or-v1-should-not-stay" not in window.log.toPlainText()
    window.close()
    app.processEvents()
