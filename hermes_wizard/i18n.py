"""Short bilingual strings for the wizard chrome.

Setting and step copy lives in the YAML catalogs. This module is only the
window around them.
"""

from __future__ import annotations

Mode = str  # "en" | "th" | "both"

STRINGS: dict[str, tuple[str, str]] = {
    "app_title": ("Hermes Setup Wizard", "ตัวช่วยติดตั้ง Hermes"),
    "lang_en": ("English", "English"),
    "lang_th": ("ไทย", "ไทย"),
    "lang_both": ("EN + TH", "EN + TH"),
    "nav_welcome": ("Welcome", "เริ่มต้น"),
    "nav_install": ("Install", "ติดตั้ง"),
    "nav_secrets": ("API keys", "คีย์ API"),
    "nav_gateways": ("Chat bots", "แชทบอท"),
    "nav_health": ("Final check", "ตรวจครั้งสุดท้าย"),
    "nav_updates": ("Updates", "อัปเดต"),
    "nav_more": ("More keys", "คีย์เพิ่มเติม"),
    "log_title": ("Command output", "ผลคำสั่ง"),
    "log_hint": (
        "Secrets are removed from this panel and from the log file.",
        "คีย์และรหัสผ่านถูกตัดออกจากแผงนี้และจากไฟล์บันทึก",
    ),
    "clear_log": ("Clear panel", "ล้างแผง"),
    "status_pending": ("pending", "รอ"),
    "status_running": ("running", "กำลังทำ"),
    "status_ok": ("ok", "ผ่าน"),
    "status_failed": ("failed", "ไม่ผ่าน"),
    "status_skipped": ("skipped", "ข้าม"),
    "run": ("Run", "รัน"),
    "run_again": ("Run again", "รันอีกครั้ง"),
    "run_required": ("Run required steps", "รันขั้นตอนที่จำเป็น"),
    "stop": ("Stop", "หยุด"),
    "save": ("Save this page", "บันทึกหน้านี้"),
    "saved": ("Saved.", "บันทึกแล้ว"),
    "optional": ("optional", "ไม่บังคับ"),
    "required": ("required", "จำเป็น"),
    "sudo_title": ("Administrator password", "รหัสผ่านผู้ดูแล"),
    "sudo_body": (
        "This step needs sudo. The password is sent only to sudo and is not stored or written to the log.",
        "ขั้นตอนนี้ต้องใช้ sudo รหัสผ่านถูกส่งให้ sudo เท่านั้น ไม่ถูกเก็บและไม่ถูกเขียนลงบันทึก",
    ),
    "sudo_pkexec": (
        "Use the system password dialog (pkexec) when it is available",
        "ใช้หน้าต่างรหัสผ่านของระบบ (pkexec) เมื่อมี",
    ),
    "show": ("Show", "แสดง"),
    "hide": ("Hide", "ซ่อน"),
    "test": ("Test connection", "ทดสอบการเชื่อมต่อ"),
    "fix": ("Fix", "ไปแก้"),
    "refresh": ("Run checks", "ตรวจใหม่"),
    "preset": ("Fill OpenRouter + DeepSeek preset", "เติมค่า OpenRouter + DeepSeek"),
    "fetch_models": ("Fetch DeepSeek models from OpenRouter", "ดึงรายชื่อโมเดล DeepSeek จาก OpenRouter"),
    "search": ("Search settings", "ค้นหาการตั้งค่า"),
    "pull": ("Check for wizard updates (git pull)", "ตรวจอัปเดตตัวช่วย (git pull)"),
    "welcome_lead": (
        "This wizard installs and configures Hermes Agent on Ubuntu. Commands run only when you press a button. You can leave and come back; progress is saved on this computer.",
        "ตัวช่วยนี้ติดตั้งและตั้งค่า Hermes Agent บน Ubuntu คำสั่งจะรันเมื่อกดปุ่มเท่านั้น ออกแล้วกลับมาได้ ความคืบหน้าถูกเก็บบนเครื่องนี้",
    ),
}


def text(key: str, mode: Mode) -> str:
    en, th = STRINGS.get(key, (key, key))
    return join(en, th, mode)


def join(en: str, th: str, mode: Mode) -> str:
    en = (en or "").strip()
    th = (th or "").strip()
    if mode == "th":
        return th or en
    if mode == "en":
        return en or th
    if en and th and en != th:
        return f"{en}\n{th}"
    return en or th
