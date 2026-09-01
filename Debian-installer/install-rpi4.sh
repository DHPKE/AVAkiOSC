#!/usr/bin/env bash
# install-rpi4.sh — AVAkiOSC installer for Raspberry Pi 4 (Raspberry Pi OS 64-bit)
#
# Run as the desktop user (not root). Uses sudo internally where required.
# Usage:
#   bash install-rpi4.sh [OPTIONS]
#
# Options:
#   --url URL           Kiosk start URL (default: https://example.com)
#   --resolution WxH    Force display resolution, e.g. 1920x1200 or 1920x1080
#                       Appends video=HDMI-A-1:WxH_MR@60 to /boot/firmware/cmdline.txt
#                       (reduced-blanking CVT timing — required for most non-TV monitors)
#   --appimage-url URL  Install from a specific AppImage URL instead of latest release
#   --appimage-file PATH Install from a local AppImage file on the Pi instead of downloading
#   --desktop-bg HEX    Desktop background color (default: #000000)
#   --no-autostart      Skip XDG autostart entry
#   --help              Show this help
#
# What this script does:
#   1. Downloads the latest arm64 AppImage from GitHub (or uses a provided AppImage URL/file)
#   2. Extracts and installs to /opt/AVAkiOSC/
#   3. Creates a .desktop launcher
#   4. Creates an XDG autostart entry so the app launches at login
#   5. Optionally sets the display resolution in /boot/firmware/cmdline.txt
#   6. Writes a starter config.yaml if none exists
#   7. Sets a non-default desktop background color for pcmanfm (user profile)
#   8. Hides Raspberry Pi OS panel/taskbar desktop chrome in labwc session
#   9. Disables Raspberry Pi boot splash welcome screen (plymouth)

set -euo pipefail

# ── Defaults ──────────────────────────────────────────────────────────────────
GITHUB_REPO="DHPKE/AVAkiOSC"
INSTALL_DIR="/opt/AVAkiOSC"
BINARY="avakiosc"
KIOSK_URL="https://example.com"
RESOLUTION=""
AUTOSTART=true
APPIMAGE_URL_OVERRIDE=""
APPIMAGE_FILE_OVERRIDE=""
DESKTOP_BG="#000000"
APPIMAGE_SOURCE=""
TMPDIR_WORK="$(mktemp -d)"
trap 'rm -rf "$TMPDIR_WORK"' EXIT

# ── Argument parsing ───────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --url)         KIOSK_URL="$2"; shift 2 ;;
    --resolution)  RESOLUTION="$2"; shift 2 ;;
    --appimage-url) APPIMAGE_URL_OVERRIDE="$2"; shift 2 ;;
    --appimage-file) APPIMAGE_FILE_OVERRIDE="$2"; shift 2 ;;
    --desktop-bg)  DESKTOP_BG="$2"; shift 2 ;;
    --no-autostart) AUTOSTART=false; shift ;;
    --help)
      sed -n '/^# /s/^# //p' "$0" | head -30
      exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 1 ;;
  esac
done

# ── Sanity checks ─────────────────────────────────────────────────────────────
ARCH="$(uname -m)"
if [[ "$ARCH" != "aarch64" ]]; then
  echo "ERROR: This script is for aarch64 (Raspberry Pi OS 64-bit). Detected: $ARCH" >&2
  exit 1
fi

if [[ "$EUID" -eq 0 ]]; then
  echo "ERROR: Run as your desktop user, not root. sudo will be called automatically." >&2
  exit 1
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "Installing curl..."
  sudo apt-get install -y curl
fi

if [[ -n "$APPIMAGE_URL_OVERRIDE" && -n "$APPIMAGE_FILE_OVERRIDE" ]]; then
  echo "ERROR: Use only one of --appimage-url or --appimage-file." >&2
  exit 1
fi

if [[ ! "$DESKTOP_BG" =~ ^#?[0-9A-Fa-f]{6}$ ]]; then
  echo "ERROR: --desktop-bg must be a 6-digit hex color (example: #000000)." >&2
  exit 1
fi

if [[ "$DESKTOP_BG" != \#* ]]; then
  DESKTOP_BG="#${DESKTOP_BG}"
fi

# ── Download latest arm64 AppImage ────────────────────────────────────────────
APPIMAGE_FILE="$TMPDIR_WORK/AVAkiOSC-arm64.AppImage"
VERSION="custom"

if [[ -n "$APPIMAGE_FILE_OVERRIDE" ]]; then
  if [[ ! -f "$APPIMAGE_FILE_OVERRIDE" ]]; then
    echo "ERROR: AppImage file not found: $APPIMAGE_FILE_OVERRIDE" >&2
    exit 1
  fi
  VERSION="$(basename "$APPIMAGE_FILE_OVERRIDE")"
  APPIMAGE_SOURCE="file:$APPIMAGE_FILE_OVERRIDE"
  echo "Using local AppImage: $APPIMAGE_FILE_OVERRIDE"
  cp "$APPIMAGE_FILE_OVERRIDE" "$APPIMAGE_FILE"
elif [[ -n "$APPIMAGE_URL_OVERRIDE" ]]; then
  VERSION="$(basename "$APPIMAGE_URL_OVERRIDE")"
  APPIMAGE_SOURCE="url:$APPIMAGE_URL_OVERRIDE"
  echo "Downloading AVAkiOSC from explicit URL..."
  curl -fL --progress-bar "$APPIMAGE_URL_OVERRIDE" -o "$APPIMAGE_FILE"
else
  echo "Fetching latest release info from GitHub..."
  RELEASE_JSON="$(curl -fsSL "https://api.github.com/repos/${GITHUB_REPO}/releases/latest")"
  APPIMAGE_URL="$(echo "$RELEASE_JSON" | grep -o '"browser_download_url": *"[^"]*arm64\.AppImage"' | grep -o 'https://[^"]*')"
  VERSION="$(echo "$RELEASE_JSON" | grep -o '"tag_name": *"[^"]*"' | grep -o 'v[^"]*')"

  if [[ -z "$APPIMAGE_URL" ]]; then
    echo "ERROR: Could not find arm64 AppImage in latest release." >&2
    echo "Check https://github.com/${GITHUB_REPO}/releases" >&2
    exit 1
  fi

  APPIMAGE_SOURCE="latest-release:$APPIMAGE_URL"
  echo "Downloading AVAkiOSC ${VERSION} (arm64)..."
  curl -fL --progress-bar "$APPIMAGE_URL" -o "$APPIMAGE_FILE"
fi

chmod +x "$APPIMAGE_FILE"

# ── Extract AppImage ───────────────────────────────────────────────────────────
echo "Extracting..."
cd "$TMPDIR_WORK"
"$APPIMAGE_FILE" --appimage-extract >/dev/null
cd - >/dev/null

# ── Install to /opt/AVAkiOSC ──────────────────────────────────────────────
echo "Installing to ${INSTALL_DIR}..."
sudo mkdir -p "$INSTALL_DIR"
sudo cp -r "$TMPDIR_WORK/squashfs-root/." "$INSTALL_DIR/"
sudo chmod +x "${INSTALL_DIR}/${BINARY}"

# Fix permissions — resources/ is copied as root but must be world-readable
sudo chmod -R a+rX "${INSTALL_DIR}/resources/"
sudo chmod -R a+rX "${INSTALL_DIR}/locales/" 2>/dev/null || true

# ── Write .desktop file ───────────────────────────────────────────────────────
DESKTOP_CONTENT="[Desktop Entry]
Name=AVAkiOSC
Exec=env LD_LIBRARY_PATH=${INSTALL_DIR} ${INSTALL_DIR}/${BINARY} --no-sandbox %U
Terminal=false
Type=Application
Icon=avakiosc
StartupWMClass=AVAkiOSC
Comment=OSC/UDP-controlled browser kiosk
Categories=Utility;"

echo "$DESKTOP_CONTENT" | sudo tee "${INSTALL_DIR}/avakiosc.desktop" >/dev/null
sudo mkdir -p /usr/share/applications
echo "$DESKTOP_CONTENT" | sudo tee /usr/share/applications/avakiosc.desktop >/dev/null
echo "Desktop file written."

# ── XDG autostart ─────────────────────────────────────────────────────────────
if [[ "$AUTOSTART" == "true" ]]; then
  AUTOSTART_DIR="$HOME/.config/autostart"
  mkdir -p "$AUTOSTART_DIR"
  echo "$DESKTOP_CONTENT" > "$AUTOSTART_DIR/avakiosc.desktop"
  echo "Autostart entry created: ${AUTOSTART_DIR}/avakiosc.desktop"
fi

# ── labwc kiosk shell cleanup (remove panel/taskbar) ─────────────────────────
LABWC_USER_DIR="$HOME/.config/labwc"
LABWC_USER_AUTOSTART="${LABWC_USER_DIR}/autostart"
mkdir -p "$LABWC_USER_DIR"
cat > "$LABWC_USER_AUTOSTART" <<'EOF'
/usr/bin/lwrespawn /usr/bin/pcmanfm-pi &
/usr/bin/kanshi &
/usr/bin/lxsession-xdg-autostart
EOF
chmod 0644 "$LABWC_USER_AUTOSTART"

LABWC_SYSTEM_AUTOSTART="/etc/xdg/labwc/autostart"
if [[ -f "$LABWC_SYSTEM_AUTOSTART" ]]; then
  # Some images still execute the system autostart file directly in the current
  # session. Disable wf-panel there too so the taskbar cannot respawn.
  if grep -q '^/usr/bin/lwrespawn /usr/bin/wf-panel-pi &$' "$LABWC_SYSTEM_AUTOSTART"; then
    sudo sed -i 's|^/usr/bin/lwrespawn /usr/bin/wf-panel-pi &$|# disabled by AVAkiOSC: /usr/bin/lwrespawn /usr/bin/wf-panel-pi \&|' "$LABWC_SYSTEM_AUTOSTART"
  fi
fi

if pgrep -x wf-panel-pi >/dev/null 2>&1; then
  # Stop panel now; user/system autostart overrides keep it off after login/reboot.
  pkill -x wf-panel-pi || true
fi
if pgrep -f '/usr/bin/lwrespawn /usr/bin/wf-panel-pi' >/dev/null 2>&1; then
  pkill -f '/usr/bin/lwrespawn /usr/bin/wf-panel-pi' || true
fi
echo "Desktop shell set to kiosk mode: panel/taskbar disabled."

# ── Desktop background (pcmanfm user profile) ─────────────────────────────────
PCMANFM_USER_DIR="$HOME/.config/pcmanfm/default"
PCMANFM_USER_CONF="${PCMANFM_USER_DIR}/desktop-items-0.conf"
PCMANFM_SYSTEM_CONF="/etc/xdg/pcmanfm/default/desktop-items-0.conf"
mkdir -p "$PCMANFM_USER_DIR"

if [[ ! -f "$PCMANFM_USER_CONF" && -f "$PCMANFM_SYSTEM_CONF" ]]; then
  cp "$PCMANFM_SYSTEM_CONF" "$PCMANFM_USER_CONF"
fi

touch "$PCMANFM_USER_CONF"

RGB_HEX="${DESKTOP_BG#\#}"
R="${RGB_HEX:0:2}"
G="${RGB_HEX:2:2}"
B="${RGB_HEX:4:2}"
PCMANFM_BG="#${R}${R}${G}${G}${B}${B}"

if grep -q '^wallpaper_mode=' "$PCMANFM_USER_CONF"; then
  sed -i 's/^wallpaper_mode=.*/wallpaper_mode=color/' "$PCMANFM_USER_CONF"
else
  printf 'wallpaper_mode=color\n' >> "$PCMANFM_USER_CONF"
fi

if grep -q '^wallpaper_common=' "$PCMANFM_USER_CONF"; then
  sed -i 's/^wallpaper_common=.*/wallpaper_common=1/' "$PCMANFM_USER_CONF"
else
  printf 'wallpaper_common=1\n' >> "$PCMANFM_USER_CONF"
fi

if grep -q '^wallpaper=' "$PCMANFM_USER_CONF"; then
  sed -i 's#^wallpaper=.*#wallpaper=#' "$PCMANFM_USER_CONF"
else
  printf 'wallpaper=\n' >> "$PCMANFM_USER_CONF"
fi

if grep -q '^desktop_bg=' "$PCMANFM_USER_CONF"; then
  sed -i "s/^desktop_bg=.*/desktop_bg=${PCMANFM_BG}/" "$PCMANFM_USER_CONF"
else
  printf 'desktop_bg=%s\n' "$PCMANFM_BG" >> "$PCMANFM_USER_CONF"
fi

if grep -q '^show_wm_menu=' "$PCMANFM_USER_CONF"; then
  sed -i 's/^show_wm_menu=.*/show_wm_menu=0/' "$PCMANFM_USER_CONF"
else
  printf 'show_wm_menu=0\n' >> "$PCMANFM_USER_CONF"
fi

if grep -q '^show_documents=' "$PCMANFM_USER_CONF"; then
  sed -i 's/^show_documents=.*/show_documents=0/' "$PCMANFM_USER_CONF"
else
  printf 'show_documents=0\n' >> "$PCMANFM_USER_CONF"
fi

if grep -q '^show_trash=' "$PCMANFM_USER_CONF"; then
  sed -i 's/^show_trash=.*/show_trash=0/' "$PCMANFM_USER_CONF"
else
  printf 'show_trash=0\n' >> "$PCMANFM_USER_CONF"
fi

if grep -q '^show_mounts=' "$PCMANFM_USER_CONF"; then
  sed -i 's/^show_mounts=.*/show_mounts=0/' "$PCMANFM_USER_CONF"
else
  printf 'show_mounts=0\n' >> "$PCMANFM_USER_CONF"
fi

if pgrep -x pcmanfm >/dev/null 2>&1; then
  # Reconfigure live desktop process so wallpaper change applies without reboot.
  pcmanfm --reconfigure >/dev/null 2>&1 || true
fi
echo "Desktop background set: ${DESKTOP_BG}"

# ── Starter config.yaml ───────────────────────────────────────────────────────
CONFIG_DIR="$HOME/.config/avakiosc"
CONFIG_FILE="$CONFIG_DIR/config.yaml"
if [[ ! -f "$CONFIG_FILE" ]]; then
  mkdir -p "$CONFIG_DIR"
  cat > "$CONFIG_FILE" <<YAML
start_url: "${KIOSK_URL}"
osc_bind: "0.0.0.0"
osc_port: 9000
udp_text_bind: "0.0.0.0"
udp_text_port: 9100
web_bind: "0.0.0.0"
web_port: 8080
web_user: "admin"
web_pass: "changeme"
reset_time: 3600
hmac_secret: ""
allowed_ips: []
kiosk: true
autostart: true
hide_cursor: false
test_mode: false
YAML
  echo "Config written: ${CONFIG_FILE}"
  echo "  --> Edit web_pass before exposing port 8080 to the network!"
else
  echo "Config already exists, skipping: ${CONFIG_FILE}"
fi

# ── Display resolution ─────────────────────────────────────────────────────────
if [[ -n "$RESOLUTION" ]]; then
  # Locate cmdline.txt (Raspberry Pi OS >= bookworm uses /boot/firmware/)
  if [[ -f /boot/firmware/cmdline.txt ]]; then
    CMDLINE=/boot/firmware/cmdline.txt
  elif [[ -f /boot/cmdline.txt ]]; then
    CMDLINE=/boot/cmdline.txt
  else
    echo "WARNING: Could not find cmdline.txt — skipping resolution change." >&2
    CMDLINE=""
  fi

  if [[ -n "$CMDLINE" ]]; then
    CURRENT="$(cat "$CMDLINE")"
    # Remove any existing video= parameter
    CLEANED="$(echo "$CURRENT" | sed 's/ *video=[^ ]*//g' | tr -s ' ')"
    NEW_LINE="${CLEANED} video=HDMI-A-1:${RESOLUTION}MR@60"
    echo "$NEW_LINE" | sudo tee "$CMDLINE" >/dev/null
    echo "Resolution set: video=HDMI-A-1:${RESOLUTION}MR@60"
    echo "  --> cmdline.txt updated. Changes take effect after reboot."
    echo "  --> If the display shows 'Signal error fD:', the pixel clock is still"
    echo "      too high for your monitor — try a lower resolution or use"
    echo "      config.txt hdmi_group/hdmi_mode settings instead."
  fi
fi

# ── Boot splash (disable Raspberry Pi welcome splash) ─────────────────────────
if [[ -f /boot/firmware/cmdline.txt ]]; then
  CMDLINE=/boot/firmware/cmdline.txt
elif [[ -f /boot/cmdline.txt ]]; then
  CMDLINE=/boot/cmdline.txt
else
  CMDLINE=""
fi

if [[ -n "$CMDLINE" ]]; then
  BEFORE_CMDLINE="$(cat "$CMDLINE")"
  sudo sed -i -E 's/(^| )splash( |$)/ /g; s/(^| )plymouth\.ignore-serial-consoles( |$)/ /g; s/ +/ /g; s/^ //; s/ $//' "$CMDLINE"
  if ! grep -q 'plymouth.enable=0' "$CMDLINE"; then
    sudo sed -i -e 's|$| plymouth.enable=0|' "$CMDLINE"
  fi
  if ! grep -q 'logo.nologo' "$CMDLINE"; then
    sudo sed -i -e 's|$| logo.nologo|' "$CMDLINE"
  fi
  AFTER_CMDLINE="$(cat "$CMDLINE")"
  if [[ "$BEFORE_CMDLINE" != "$AFTER_CMDLINE" ]]; then
    echo "Boot splash disabled (plymouth disabled + kernel logo hidden)."
    echo "  --> Reboot required for boot-screen change to take effect."
  fi
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "AVAkiOSC ${VERSION} installed successfully."
echo ""
echo "  Install dir : ${INSTALL_DIR}"
echo "  Config      : ${CONFIG_FILE}"
echo "  Source      : ${APPIMAGE_SOURCE}"
echo "  Desktop BG  : ${DESKTOP_BG}"
echo "  Web admin   : http://$(hostname -I | awk '{print $1}'):8080"
[[ "$AUTOSTART" == "true" ]] && echo "  Autostart   : enabled (launches at next desktop login)"
[[ -n "$RESOLUTION" ]] && echo "  Resolution  : ${RESOLUTION} (effective after reboot)"
echo ""
echo "To start now (without rebooting):"
echo "  LD_LIBRARY_PATH=${INSTALL_DIR} ${INSTALL_DIR}/${BINARY} --no-sandbox &"
echo ""
echo "To update later, re-run this script."
