# Installing KiOSC-BrowsR

KiOSC-BrowsR ships two different ways to run it. Pick the one that matches your machine.

| Path | Use case | Browser engine |
|---|---|---|
| **Electron app** (`.deb` / `.dmg` / `.exe` / `.AppImage`) | Desktop machines (macOS, Windows, Ubuntu Desktop), Raspberry Pi | Chromium embedded in Electron |
| **Debian/Ubuntu kiosk installer** ([`Debian-installer/`](Debian-installer/)) | Dedicated headless/kiosk box that boots straight into a locked-down browser | Chromium (apt), falls back to Google Chrome |

---

## 1. macOS / Windows / Ubuntu Desktop (Electron app)

Download the file for your platform from [Releases](https://github.com/DHPKE/KiOSC-BROSR/releases):

| Platform | File |
|---|---|
| macOS (Apple Silicon) | `KiOSC-BrowsR-*-arm64.dmg` |
| macOS (Intel) | `KiOSC-BrowsR-*.dmg` |
| Ubuntu / Debian | `kiosc-browsr_*_amd64.deb` (or `arm64.deb` on ARM) |
| Linux (any distro) | `KiOSC-BrowsR-*.AppImage` |
| Windows | `KiOSC-BrowsR-Setup-*.exe` |

### Ubuntu / Debian install

```bash
sudo apt update
sudo apt install ./kiosc-browsr_*.deb
```

Launch it:

```bash
kiosc-browsr
```

### Configuration

Config file lookup order:

1. `$KIOSC_CONFIG` environment variable
2. `<userData>/config.yaml` (e.g. `~/.config/kiosc-browsr/` on Linux)
3. `/etc/kiosc-browsr/config.yaml` (Linux system-wide)

See [`config/config.yaml.example`](config/config.yaml.example) for all available options (start URL, kiosk mode, OSC/UDP ports, web admin credentials, etc).

### Autostart on login (Ubuntu Desktop)

```bash
mkdir -p ~/.config/autostart
cp /usr/share/applications/kiosc-browsr.desktop ~/.config/autostart/
```

Then enable automatic login for the user in Settings.

### Building from source

```bash
git clone https://github.com/DHPKE/KiOSC-BROSR.git
cd KiOSC-BROSR
npm install
npm run build:linux    # → dist/*.deb + *.AppImage
npm run build:mac      # → dist/*.dmg
npm run build:win      # → dist/*-Setup.exe
```

Requires Node.js 22+.

---

## 2. Raspberry Pi 4 (Raspberry Pi OS 64-bit)

Use [`Debian-installer/install-rpi4.sh`](Debian-installer/install-rpi4.sh). Run as the desktop user (not root):

```bash
curl -fsSL https://raw.githubusercontent.com/DHPKE/KiOSC-BROSR/main/Debian-installer/install-rpi4.sh -o install-rpi4.sh
bash install-rpi4.sh --url https://example.com
```

Common options:

```bash
--url URL             Kiosk start URL (default: https://example.com)
--resolution WxH       Force display resolution, e.g. 1920x1080
--appimage-url URL     Install from a specific AppImage URL
--appimage-file PATH   Install from a local AppImage file
--desktop-bg HEX       Desktop background color (default: #000000)
--no-autostart         Skip XDG autostart entry
```

This downloads the latest arm64 AppImage, installs it to `/opt/KiOSC-BrowsR/`, creates a `.desktop` launcher, sets up XDG autostart, and cleans up the labwc/pcmanfm desktop chrome for a kiosk look.

---

## 3. Dedicated Debian/Ubuntu kiosk machine (legacy Python installer)

For a headless machine that should boot straight into a locked-down Chromium kiosk (no desktop environment required), use [`Debian-installer/setup-kioscbrowsr.sh`](Debian-installer/setup-kioscbrowsr.sh). This installs Chromium (or Google Chrome as a fallback), a Python-based OSC/UDP + WebAdmin service, and configures autologin + X on `tty1`.

Run as root on Debian 12/13 or Ubuntu:

```bash
sudo bash Debian-installer/setup-kioscbrowsr.sh
```

Or fetch it directly from the repo:

```bash
curl -fsSL https://raw.githubusercontent.com/DHPKE/KiOSC-BROSR/main/Debian-installer/setup-kioscbrowsr.sh -o setup-kioscbrowsr.sh
sudo bash setup-kioscbrowsr.sh
```

Override defaults via environment variables before running:

```bash
KIOSK_URL="https://my-show-page.com" \
WEBADMIN_PASS="a-strong-password" \
sudo -E bash setup-kioscbrowsr.sh
```

| Variable | Default | Description |
|---|---|---|
| `KIOSK_USER` | `kiosk` | Linux user created for the kiosk session |
| `KIOSK_URL` | `https://example.com` | Start URL |
| `OSC_BIND` / `OSC_PORT` | `0.0.0.0` / `9000` | OSC UDP listener |
| `UDP_TEXT_PORT` | `9100` | Plaintext UDP listener |
| `WEBADMIN_BIND` / `WEBADMIN_PORT` | `127.0.0.1` / `8080` | Web admin panel |
| `WEBADMIN_USER` / `WEBADMIN_PASS` | `admin` / `changeme` | Web admin credentials — **change this** |

What the script does:

1. Installs `xserver-xorg`, `openbox`, `chromium` (or Google Chrome fallback), Python 3 + venv, and supporting tools.
2. Creates the `kiosk` Linux user with a passwordless sudo rule scoped to restarting the two services.
3. Sets up a Python virtualenv at `/opt/kiosc-browsr/venv` with `python-osc`, `pychrome`, `flask`, `pyyaml`.
4. Writes `/etc/kiosc-browsr/config.yaml`.
5. Installs the systemd units [`Debian-installer/kiosc-browsr.service`](Debian-installer/kiosc-browsr.service) and [`Debian-installer/kiosc-webadmin.service`](Debian-installer/kiosc-webadmin.service).
6. Configures autologin on `tty1` and an `.xinitrc` that starts Openbox.
7. Applies Chromium managed policies to lock the homepage and disable incognito/download prompts/password manager.
8. Enables and starts both services.

After install, review `/etc/kiosc-browsr/config.yaml`, change the web admin password, then reboot.

### Managing the services

```bash
sudo systemctl status kiosc-browsr kiosc-webadmin
sudo systemctl restart kiosc-browsr
sudo journalctl -u kiosc-browsr -f
```

---

## Uninstalling

**Electron `.deb` package:**

```bash
sudo apt remove kiosc-browsr
```

**Legacy Debian kiosk installer:**

```bash
sudo systemctl disable --now kiosc-browsr kiosc-webadmin
sudo rm -rf /opt/kiosc-browsr /etc/kiosc-browsr
sudo rm /etc/systemd/system/kiosc-browsr.service /etc/systemd/system/kiosc-webadmin.service
sudo rm /etc/systemd/system/getty@tty1.service.d/override.conf
sudo userdel -r kiosk   # optional — removes the kiosk user and its home directory
sudo systemctl daemon-reload
```

**Raspberry Pi AppImage install:**

```bash
sudo rm -rf /opt/KiOSC-BrowsR /usr/share/applications/kiosc-browsr.desktop
rm -f ~/.config/autostart/kiosc-browsr.desktop
```
