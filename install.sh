#!/usr/bin/env bash
# Standalone installer for Xattendo Desktop Widget.
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/ael-biss/xattendo-widget/main/install.sh | bash
# Or override the release download URL:
#   XATTENDO_BUNDLE_URL="https://..." bash install.sh

set -euo pipefail

BUNDLE_URL="${XATTENDO_BUNDLE_URL:-https://github.com/ael-biss/xattendo-widget/releases/latest/download/xattendo-widget.pyz}"
BIN_DIR="$HOME/.local/bin"
BIN_PATH="$BIN_DIR/xattendo-widget"
AUTOSTART_DIR="$HOME/.config/autostart"
AUTOSTART_FILE="$AUTOSTART_DIR/xattendo-desktop-widget.desktop"

echo "Installing Xattendo Desktop Widget..."
mkdir -p "$BIN_DIR" "$AUTOSTART_DIR"

TMP_FILE="${BIN_PATH}.tmp"
curl -fsSL "$BUNDLE_URL" -o "$TMP_FILE"
chmod +x "$TMP_FILE"
mv -f "$TMP_FILE" "$BIN_PATH"

cat > "$AUTOSTART_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=Xattendo Desktop Widget
Comment=1337 Campus Attendance & Lock Time Widget
Exec=$BIN_PATH
Terminal=false
X-GNOME-Autostart-enabled=true
EOF

pkill -f "[x]attendo-widget" 2>/dev/null || true
nohup "$BIN_PATH" >/dev/null 2>&1 </dev/null &

echo "✔ Installed to $BIN_PATH"
echo "✔ Autostart enabled at $AUTOSTART_FILE"
echo "✔ Widget is running!"
