# ตัวช่วยติดตั้ง Hermes / Hermes Setup Wizard

โปรแกรมเดสก์ท็อปบน Ubuntu สำหรับติดตั้งและตั้งค่า [Hermes Agent](https://github.com/NousResearch/hermes-agent) ของ Nous Research
ที่เก็บนี้เป็นส่วนตัว ใช้ในเครื่องของเจ้าของเท่านั้น ตัวช่วยไม่ push โค้ดและไม่เผยแพร่ที่เก็บ

This is a private Ubuntu desktop wizard for [Hermes Agent](https://github.com/NousResearch/hermes-agent).
It does not push the repository and it does not publish it.

เครื่องที่ตั้งใจไว้: Ubuntu 22.04 หรือ 24.04, Dell OptiPlex 3050, Intel i5, แรม 16 GB, ไม่มี GPU
ทางที่แนะนำคือ OpenRouter กับโมเดล DeepSeek เพราะโมเดลรันบนคลาวด์

## วิธีเปิด / How to run

ในโฟลเดอร์นี้:

```bash
chmod +x install.sh
./install.sh
hermes-setup-wizard
```

`./install.sh` ติดตั้งของที่ตัวช่วยต้องใช้เอง (Python venv, PySide6, keyring, libsecret) และสร้างรายการเมนู
`Hermes Setup Wizard` / `ตัวช่วยติดตั้ง Hermes` ถ้าหาคำสั่งไม่เจอ ให้เปิดเทอร์มินัลใหม่ หรือรัน

```bash
export PATH="$HOME/.local/bin:$PATH"
```

จากนั้นกดตามแถบด้านบน: ติดตั้ง → ผู้ให้บริการและโมเดล → Telegram → Discord → LINE → ตรวจครั้งสุดท้าย
แชทบอทไม่บังคับ ทุกหน้าเปิดซ้ำได้จากแถบซ้าย

The top bar follows Install, Provider, Telegram, Discord, LINE, then the final check.
Chat bots are optional. Any page can be opened again from the sidebar.

## สิ่งที่ตัวช่วยทำ / What it writes

| ที่ | ใช้ทำอะไร |
| --- | --- |
| `~/.hermes/config.yaml` | ค่าที่ไม่ใช่ความลับ เช่น `model.provider`, `timezone` |
| `~/.hermes/.env` | คีย์และโทเคน สิทธิ์ไฟล์ `0600` ตามที่ Hermes อ่าน |
| พวงกุญแจของระบบ (Secret Service) | สำเนาคีย์ไว้ให้ตัวช่วยเติมช่องอีกครั้ง โดยไม่พิมพ์ลงบันทึก |
| `~/.local/share/hermes-setup-wizard/progress.json` | สถานะขั้นตอน ไม่มีรหัสผ่าน |

รหัส sudo ถูกส่งให้ `pkexec` หรือ `sudo -S` เท่านั้น ไม่ถูกเก็บและไม่ลงบันทึก
แผงผลคำสั่งตัดค่าที่ดูเหมือนคีย์ออกก่อนแสดง

## เพิ่มขั้นตอนหรือการตั้งค่า / Add a step or a setting

แก้ไฟล์ YAML แล้วเปิดโปรแกรมใหม่ ไม่ต้องแก้หน้าต่าง

- `hermes_wizard/data/steps.yaml` — ขั้นตอนติดตั้ง เรียงจากบนลงล่าง
  ฟิลด์ที่ใช้: `id`, `title_en`, `title_th`, `summary_en`, `summary_th`, `shell`, `privilege` (`none`, `root`, หรือ `sudo-cache`), `optional`, `source`, `command_hint`
- `hermes_wizard/data/providers.yaml` — ผู้ให้บริการบนหน้า Provider
- `hermes_wizard/data/gateways.yaml` — แชทบอท คำแนะนำสองภาษา และช่องโทเคน
  คำอธิบายเพิ่มของแต่ละช่องอยู่ที่ `field_meta` (`where_en`, `where_th`, `example`, `links`)
- `hermes_wizard/data/settings.yaml` — ค่าใน `config.yaml` ที่ไม่ใช่ความลับ
- `hermes_wizard/data/secrets.yaml` — คีย์อื่นใน `.env`
- `hermes_wizard/data/checks.yaml` — รายการในหน้าตรวจครั้งสุดท้าย
- `hermes_wizard/data/faq.yaml` — หน้าแก้ปัญหา

แต่ละรายการต้องมีข้อความภาษาไทยและภาษาอังกฤษ ชื่อคีย์ต้องตรงเอกสารของ Hermes
หน้า More keys รับชื่อที่ยังไม่มีในรายการ: ชื่อ `UPPER_SNAKE` ลง `.env` ชื่อมีจุดลง `config.yaml`

## อัปเดต / Update

ในโปรแกรม เปิดหน้า Updates แล้วกด git pull
คำสั่งจริงคือ `git pull --ff-only` ในโฟลเดอร์นี้ มันไม่ push
ถ้ามีไฟล์ที่แก้ค้างอยู่ ปุ่มจะไม่ดึง ให้ commit หรือ stash ก่อน แล้วเปิดโปรแกรมใหม่

อัปเดตตัว Hermes คนละปุ่ม: `hermes update`

## ทดสอบ / Tests

```bash
python3 -m pip install pytest PyYAML keyring
PYTHONPATH=. python3 -m pytest
```

เทสต์ครอบคลุมตัวรันขั้นตอน การอ่านเขียนคอนฟิก และการตัดความลับ ไม่เปิดหน้าต่าง

## แหล่งที่อ้างอิง / Sources

ตัวช่วยไม่แต่งชื่อคีย์เอง ค่าด้านล่างมาจากเอกสารทางการ ตรวจเมื่อจัดทำตัวช่วยนี้

- ติดตั้ง: <https://hermes-agent.nousresearch.com/docs/getting-started/installation>
  `install.sh`, `--non-interactive`, แพ็กเกจที่ POSIX ต้องมี (git, curl, tar, SHA-256), `libatomic1` บน apt, โครง `~/.hermes` และ `~/.local/bin/hermes`, `loginctl enable-linger`
- เดสก์ท็อปบนลินุกซ์: <https://hermes-agent.nousresearch.com/docs/user-guide/desktop>
  `hermes desktop`, `--build-only`, `--install-apparmor-profile`
- ผู้ให้บริการ: <https://hermes-agent.nousresearch.com/docs/integrations/providers>
  OpenRouter (`OPENROUTER_API_KEY`), OpenAI (`openai-api`), Anthropic, DeepSeek ตรง, Gemini, xAI, Ollama Cloud, LM Studio, Ollama ในเครื่องผ่าน custom endpoint `http://localhost:11434/v1`, Nous Portal ด้วย `hermes setup --portal`
  ชื่อ DeepSeek ที่ปลั๊กอิน OpenRouter Everything ของ Hermes อ้างเป็นค่าข้อความ: `deepseek/deepseek-v4.1-flash-1017`
  ตัวอย่างในคู่มือ delegation: `deepseek/deepseek-v4-flash-0731`
  ปุ่มดึงรายการโมเดลอ่านรายการสดจาก OpenRouter เพราะชื่อโมเดลเปลี่ยนได้
- คอนฟิก: <https://hermes-agent.nousresearch.com/docs/user-guide/configuration>
  ความลับอยู่ที่ `~/.hermes/.env` ค่าอื่นอยู่ที่ `config.yaml`
- ตัวแปรสภาพแวดล้อม: <https://hermes-agent.nousresearch.com/docs/reference/environment-variables>
- เกตเวย์: <https://hermes-agent.nousresearch.com/docs/user-guide/messaging>
  Telegram, Discord, LINE (`plugins/platforms/line/`), Slack, Signal, Matrix, Email, WhatsApp Cloud API, Teams, ntfy
- LINE: <https://hermes-agent.nousresearch.com/docs/user-guide/messaging/line>
- Telegram: <https://hermes-agent.nousresearch.com/docs/user-guide/messaging/telegram>
- Discord: <https://hermes-agent.nousresearch.com/docs/user-guide/messaging/discord>

## สิ่งที่ยังไม่ได้ลองบนเครื่อง OptiPlex

ตัวช่วยนี้ตรวจตรรกะที่ไม่ใช่หน้าต่างด้วย pytest
การติดตั้ง Hermes จริง การบิลด์เดสก์ท็อป และการเรียก OpenRouter / Telegram / Discord / LINE ต้องกดบนเครื่อง Ubuntu ที่มีเครือข่ายและคีย์จริง
เครื่องที่ใช้พัฒนาตัวช่วยไม่มีจอเดสก์ท็อปของ OptiPlex จึงไม่ได้คลิกผ่านทุกหน้าบนเครื่องนั้น
