APP_STYLE = """
QMainWindow, QWidget { background: #f6f3ec; color: #1c1917; }
QListWidget { background: #fffdf8; border: none; padding: 6px; font-size: 14px; }
QListWidget::item { padding: 8px 10px; border-radius: 6px; }
QListWidget::item:selected { background: #0f766e; color: white; }
QListWidget::item:disabled { color: #78716c; font-weight: 600; }
QPushButton {
  background: #0f766e; color: white; border: none; border-radius: 6px;
  padding: 8px 14px; font-size: 14px;
}
QPushButton:disabled { background: #a8a29e; }
QPushButton[secondary="true"] { background: #e7e5e4; color: #1c1917; }
QLineEdit, QComboBox, QPlainTextEdit, QSpinBox {
  background: white; border: 1px solid #d6d3d1; border-radius: 6px; padding: 6px; font-size: 14px;
}
QPlainTextEdit#log {
  background: #1c1917; color: #e7e5e4; font-family: "Ubuntu Mono", monospace; font-size: 12px;
}
QLabel#title { font-size: 22px; font-weight: 650; }
QLabel#hint { color: #44403c; }
QFrame#card { background: white; border: 1px solid #e7e5e4; border-radius: 10px; }
QFrame#explain { background: #f0fdfa; border-left: 4px solid #0f766e; }
QLabel#pill { padding: 2px 8px; border-radius: 8px; font-weight: 600; }
"""


def status_color(status: str) -> str:
    return {
        "pending": "#78716c",
        "running": "#1d4ed8",
        "ok": "#15803d",
        "pass": "#15803d",
        "failed": "#b91c1c",
        "fail": "#b91c1c",
        "skipped": "#a16207",
    }.get(status, "#44403c")
