#!/usr/bin/env bash
# Install this wizard's own dependencies and a desktop launcher.
# Hermes Agent itself is installed later, from inside the wizard.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required" >&2
  exit 1
fi

need_apt=0
python3 -c "import venv" >/dev/null 2>&1 || need_apt=1
command -v pip3 >/dev/null 2>&1 || need_apt=1
dpkg -s libsecret-1-0 >/dev/null 2>&1 || need_apt=1
if [ "$need_apt" -eq 1 ]; then
  if [ "$(id -u)" -eq 0 ]; then
    apt-get update
    apt-get install -y python3 python3-venv python3-pip libsecret-1-0 gnome-keyring
  else
    sudo apt-get update
    sudo apt-get install -y python3 python3-venv python3-pip libsecret-1-0 gnome-keyring
  fi
fi

python3 -m venv "$ROOT/.venv"
"$ROOT/.venv/bin/pip" install -U pip
"$ROOT/.venv/bin/pip" install -e "$ROOT"

mkdir -p "$HOME/.local/bin" "$HOME/.local/share/applications"
cat > "$HOME/.local/bin/hermes-setup-wizard" << EOF
#!/usr/bin/env bash
exec "$ROOT/.venv/bin/python" -m hermes_wizard "\$@"
EOF
chmod 755 "$HOME/.local/bin/hermes-setup-wizard"

sed "s|@EXEC@|$HOME/.local/bin/hermes-setup-wizard|g" \
  "$ROOT/assets/hermes-setup-wizard.desktop.in" \
  > "$HOME/.local/share/applications/hermes-setup-wizard.desktop"
chmod 644 "$HOME/.local/share/applications/hermes-setup-wizard.desktop"
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$HOME/.local/share/applications" >/dev/null 2>&1 || true
fi

echo "Wizard ready."
echo "Launch: hermes-setup-wizard"
echo "Or search the application menu for Hermes Setup Wizard."
echo "If the command is not found, open a new terminal or run: export PATH=\"\$HOME/.local/bin:\$PATH\""
