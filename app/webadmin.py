#!/usr/bin/env python3
"""AVAkiOSC WebAdmin - HTTP admin panel for the AVAkiOSC service"""

import os
import re
import socket
import subprocess
from functools import wraps

import yaml
from flask import Flask, Response, jsonify, request
from pythonosc.udp_client import SimpleUDPClient

CONFIG_FILE = os.environ.get('AVAKIOSC_CONFIG', '/etc/avakiosc/config.yaml')
LOGO_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'pke-logo.svg')

app = Flask(__name__)


def read_config():
    with open(CONFIG_FILE) as f:
        return yaml.safe_load(f) or {}


def write_config(cfg):
    with open(CONFIG_FILE, 'w') as f:
        yaml.safe_dump(cfg, f, default_flow_style=False)


def send_osc(command, *args):
    cfg = read_config()
    client = SimpleUDPClient(
        cfg.get('osc_bind') if cfg.get('osc_bind') not in ('0.0.0.0', '') else '127.0.0.1',
        cfg.get('osc_port', 9000)
    )
    client.send_message(f"/{command}", list(args))


def restart_avakiosc_service():
    # Relies on the NOPASSWD sudoers rule installed by setup-avakiosc.sh
    subprocess.run(['sudo', 'systemctl', 'restart', 'avakiosc.service'], check=False)


def get_ip_addresses():
    try:
        out = subprocess.check_output(['hostname', '-I'], text=True, timeout=2).strip()
        return out.split() if out else []
    except Exception:
        return []


def is_chrome_active(cfg):
    try:
        with socket.create_connection(('127.0.0.1', cfg.get('debug_port', 9222)), timeout=0.3):
            return True
    except OSError:
        return False


VALID_ROTATIONS = {'normal', 'left', 'right', 'inverted'}


def get_xrandr_output():
    try:
        out = subprocess.check_output(['xrandr', '--query'], text=True, timeout=3)
        for line in out.splitlines():
            if ' connected' in line:
                return line.split()[0]
    except Exception:
        pass
    return None


# Coordinate Transformation Matrix per rotation, so touch input stays aligned with the rotated display.
TOUCH_MATRIX = {
    'normal':   ('1', '0', '0', '0', '1', '0', '0', '0', '1'),
    'left':     ('0', '-1', '1', '1', '0', '0', '0', '0', '1'),
    'right':    ('0', '1', '0', '-1', '0', '1', '0', '0', '1'),
    'inverted': ('-1', '0', '1', '0', '-1', '1', '0', '0', '1'),
}


def get_touch_device_ids():
    ids = []
    try:
        out = subprocess.check_output(['xinput', 'list'], text=True, timeout=3)
        for line in out.splitlines():
            if 'slave  pointer' in line and 'XTEST' not in line and 'touch' in line.lower():
                m = re.search(r'id=(\d+)', line)
                if m:
                    ids.append(m.group(1))
    except Exception:
        pass
    return ids


def apply_touch_rotation(rotation):
    matrix = TOUCH_MATRIX.get(rotation, TOUCH_MATRIX['normal'])
    for dev_id in get_touch_device_ids():
        subprocess.run(
            ['xinput', 'set-prop', dev_id, 'Coordinate Transformation Matrix', *matrix],
            check=False, timeout=3
        )


def apply_rotation(rotation):
    output = get_xrandr_output()
    if not output:
        raise RuntimeError('No connected display output found')
    subprocess.run(['xrandr', '--output', output, '--rotate', rotation], check=True, timeout=5)
    apply_touch_rotation(rotation)


def is_onboard_running():
    try:
        subprocess.check_output(['pgrep', '-x', 'onboard'], timeout=2)
        return True
    except Exception:
        return False


def start_onboard():
    if is_onboard_running():
        return
    env = os.environ.copy()
    # Join the kiosk X session's real D-Bus session bus so onboard's AT-SPI focus
    # detection actually sees Chromium's accessibility events (instead of spawning
    # its own isolated private bus when DBUS_SESSION_BUS_ADDRESS is unset).
    bus_path = f"/run/user/{os.getuid()}/bus"
    if os.path.exists(bus_path):
        env['DBUS_SESSION_BUS_ADDRESS'] = f"unix:path={bus_path}"
    subprocess.Popen(['onboard'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)


def stop_onboard():
    subprocess.run(['pkill', '-x', 'onboard'], check=False)


def require_auth(handler):
    @wraps(handler)
    def wrapped(*args, **kwargs):
        cfg = read_config()
        auth = request.authorization
        if not auth or auth.username != cfg.get('web_user') or auth.password != cfg.get('web_pass'):
            return Response(
                'Unauthorized', 401,
                {'WWW-Authenticate': 'Basic realm="AVAkiOSC Admin"'}
            )
        return handler(*args, **kwargs)
    return wrapped


PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AVAkiOSC Admin</title>
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --bg:       #0d1117;
  --surface:  #161b22;
  --border:   #253040;
  --accent:   #128FCF;
  --accent2:  #4bb8f0;
  --danger:   #f87171;
  --text:     #e5e7eb;
  --muted:    #7d9ab5;
  --radius:   10px;
}

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  background: var(--bg);
  color: var(--text);
  min-height: 100vh;
  padding: 0 0 40px;
}

header {
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  padding: 18px 28px;
  display: flex;
  align-items: center;
  gap: 16px;
}
header h1 { font-size: 1.25rem; font-weight: 700; color: var(--accent); letter-spacing: -0.5px; }
header .dot { width: 10px; height: 10px; border-radius: 50%; background: var(--muted); flex-shrink: 0; transition: background 0.3s; }
header .dot.active { background: var(--accent); box-shadow: 0 0 8px var(--accent); }
header .status-text { font-size: 0.85rem; color: var(--muted); }
header .spacer { flex: 1; }
header .hostname { font-size: 0.85rem; color: var(--accent2); font-family: 'SF Mono', 'Fira Code', monospace; }

main {
  max-width: 1100px;
  margin: 28px auto;
  padding: 0 20px;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 20px;
}

.card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); padding: 22px 24px; }
.card.wide { grid-column: 1 / -1; }
.card h2 { font-size: 0.7rem; font-weight: 600; text-transform: uppercase; letter-spacing: 1px; color: var(--muted); margin-bottom: 16px; }

.mdns-name { font-size: 1.5rem; font-weight: 700; color: var(--accent); font-family: 'SF Mono', 'Fira Code', monospace; margin-bottom: 16px; word-break: break-all; }
.addr-table { width: 100%; border-collapse: collapse; }
.addr-table td { padding: 6px 8px; font-size: 0.85rem; border-bottom: 1px solid var(--border); }
.addr-table td:first-child { color: var(--muted); width: 90px; }
.addr-table td:last-child { font-family: 'SF Mono', 'Fira Code', monospace; }
.addr-table tr:last-child td { border-bottom: none; }
.addr-table .copy-btn { float: right; background: none; border: 1px solid var(--border); color: var(--muted); padding: 1px 7px; border-radius: 4px; font-size: 0.72rem; cursor: pointer; }
.addr-table .copy-btn:hover { color: var(--accent); border-color: var(--accent); }
.ip-row { margin-top: 12px; font-size: 0.8rem; color: var(--muted); }
.ip-row span { color: var(--text); font-family: 'SF Mono', 'Fira Code', monospace; }

.status-badge { display: inline-flex; align-items: center; gap: 8px; padding: 6px 14px; border-radius: 20px; font-size: 0.82rem; font-weight: 600; margin-bottom: 14px; background: rgba(107,114,128,0.15); color: var(--muted); border: 1px solid var(--border); }
.status-badge.active { background: rgba(52,211,153,0.1); color: var(--accent); border-color: rgba(52,211,153,0.3); }
.status-badge .led { width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
.current-url { font-size: 0.83rem; color: var(--muted); word-break: break-all; margin-bottom: 4px; }
.current-url strong { color: var(--text); font-weight: 400; }

.url-row { display: flex; gap: 8px; margin-bottom: 12px; }
input[type="url"], input[type="text"], input[type="number"] {
  background: var(--bg); border: 1px solid var(--border); border-radius: 6px; color: var(--text);
  padding: 9px 12px; font-size: 0.88rem; width: 100%; outline: none; transition: border-color 0.2s;
}
input:focus { border-color: var(--accent2); }
.btn { padding: 9px 18px; border-radius: 6px; border: none; font-size: 0.88rem; font-weight: 600; cursor: pointer; white-space: nowrap; transition: opacity 0.15s; }
.btn:hover { opacity: 0.85; }
.btn-primary   { background: var(--accent);  color: #111; }
.btn-secondary { background: var(--border);  color: var(--text); }
.btn-danger    { background: rgba(248,113,113,0.15); color: var(--danger); border: 1px solid rgba(248,113,113,0.3); }
.action-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(100px, 1fr)); gap: 8px; }

.field { margin-bottom: 14px; }
.field label { display: block; font-size: 0.78rem; color: var(--muted); margin-bottom: 5px; }

#toast {
  position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%) translateY(20px);
  background: #1a1a2e; border: 1px solid var(--accent); color: var(--accent); padding: 10px 24px;
  border-radius: 24px; font-size: 0.85rem; font-weight: 500; pointer-events: none; opacity: 0;
  transition: opacity 0.25s, transform 0.25s; z-index: 999;
}
#toast.show { opacity: 1; transform: translateX(-50%) translateY(0); }
</style>
</head>
<body>

<header>
  <img src="/pke-logo.svg" alt="PKE" style="height:26px;width:auto;flex-shrink:0" onerror="this.style.display='none'">
  <div style="width:1px;height:22px;background:var(--border);flex-shrink:0"></div>
  <div class="dot" id="hdr-dot"></div>
  <h1>AVAkiOSC</h1>
  <span class="status-text" id="hdr-status">connecting…</span>
  <div class="spacer"></div>
  <span class="hostname" id="hdr-hostname"></span>
</header>

<main>

  <div class="card wide">
    <h2>Find this device on the network</h2>
    <table class="addr-table">
      <tbody>
        <tr><td>OSC (UDP)</td><td id="addr-osc">—</td></tr>
        <tr><td>UDP Text</td><td id="addr-udp">—</td></tr>
        <tr><td>Web Admin</td><td id="addr-web">—</td></tr>
      </tbody>
    </table>
    <div class="ip-row">IP addresses: <span id="ip-list">—</span></div>
  </div>

  <div class="card">
    <h2>Status</h2>
    <div class="status-badge" id="status-badge">
      <span class="led"></span>
      <span id="status-label">Inactive</span>
    </div>
    <p class="current-url">Home: <strong id="status-home">—</strong></p>
    <p class="current-url" style="margin-top:6px">Auto-reset: <strong id="status-reset">—</strong></p>
  </div>

  <div class="card">
    <h2>Navigate</h2>
    <div class="url-row">
      <input type="url" id="nav-url" placeholder="https://…" autocomplete="off">
      <button class="btn btn-primary" onclick="sendNav()">Go</button>
    </div>
    <div class="action-grid">
      <button class="btn btn-secondary" onclick="cmd('reload')">Reload</button>
      <button class="btn btn-secondary" onclick="cmd('start')">Start</button>
      <button class="btn btn-secondary" onclick="cmd('restart')">Restart</button>
      <button class="btn btn-secondary" onclick="cmd('stop')">Stop</button>
      <button class="btn btn-danger"    onclick="cmd('clear')">Clear Cache</button>
    </div>
  </div>

  <div class="card">
    <h2>Settings</h2>
    <div class="field">
      <label>Home URL</label>
      <input type="url" id="cfg-start-url" placeholder="https://example.com">
    </div>
    <div class="field">
      <label>Auto-reset timer (seconds, 0 = disabled)</label>
      <input type="number" id="cfg-reset-time" min="0" step="60">
    </div>
    <button class="btn btn-primary" style="width:100%" onclick="saveSettings()">Save &amp; restart service</button>
  </div>

  <div class="card">
    <h2>Display</h2>
    <div class="field">
      <label>Screen rotation</label>
      <select id="cfg-rotation">
        <option value="normal">Normal (0&deg;)</option>
        <option value="left">Left (90&deg; CCW)</option>
        <option value="right">Right (90&deg; CW)</option>
        <option value="inverted">Inverted (180&deg;)</option>
      </select>
    </div>
    <button class="btn btn-primary" style="width:100%" onclick="applyRotation()">Apply rotation</button>
  </div>

  <div class="card">
    <h2>Virtual Keyboard</h2>
    <div class="status-badge" id="kbd-badge">
      <span class="led"></span>
      <span id="kbd-label">Unknown</span>
    </div>
    <p class="current-url" style="margin-bottom:12px">Shows an on-screen keyboard automatically when a text field is focused in the kiosk browser.</p>
    <div class="action-grid">
      <button class="btn btn-primary" onclick="setKeyboard(true)">Enable</button>
      <button class="btn btn-secondary" onclick="setKeyboard(false)">Disable</button>
    </div>
  </div>

</main>

<div id="toast"></div>

<script>
  async function apiFetch(method, pathname, body) {
    const opts = { method, headers: {} }
    if (body !== undefined) {
      opts.body = JSON.stringify(body)
      opts.headers['Content-Type'] = 'application/json'
    }
    const r = await fetch(pathname, opts)
    const data = await r.json()
    if (!r.ok || data.error) throw new Error(data.error || `HTTP ${r.status}`)
    return data
  }

  function $(id) { return document.getElementById(id) }

  async function refresh() {
    try {
      const s = await apiFetch('GET', '/api/status')
      $('hdr-hostname').textContent = s.hostname || ''
      $('hdr-status').textContent = s.active ? 'Active' : 'Inactive'
      $('hdr-dot').className = 'dot' + (s.active ? ' active' : '')

      $('addr-osc').textContent = `${s.hostname}:${s.osc_port}`
      $('addr-udp').textContent = `${s.hostname}:${s.udp_text_port}`
      $('addr-web').textContent = `http://${s.hostname}:${s.web_port}`
      $('ip-list').textContent = (s.ip_addresses && s.ip_addresses.length) ? s.ip_addresses.join(', ') : '—'

      const badge = $('status-badge')
      badge.className = 'status-badge' + (s.active ? ' active' : '')
      $('status-label').textContent = s.active ? 'Active' : 'Inactive'
      $('status-home').textContent = s.start_url || '—'
      $('status-reset').textContent = s.reset_time > 0 ? `${s.reset_time}s` : 'disabled'
    } catch (e) {
      $('hdr-status').textContent = 'offline'
      $('hdr-dot').className = 'dot'
    }
  }

  async function loadSettings() {
    try {
      const c = await apiFetch('GET', '/api/status')
      $('cfg-start-url').value  = c.start_url  || ''
      $('cfg-reset-time').value = c.reset_time != null ? c.reset_time : 3600
      $('cfg-rotation').value   = c.screen_rotation || 'normal'
    } catch (e) { /* ignore */ }
  }

  async function sendNav() {
    const url = $('nav-url').value.trim()
    if (!url) return
    await apiFetch('POST', '/api/command', { cmd: 'goto', params: { url } })
    toast('Navigating…')
    $('nav-url').value = ''
    setTimeout(refresh, 600)
  }

  async function cmd(name) {
    await apiFetch('POST', '/api/command', { cmd: name })
    toast(name + '…')
    setTimeout(refresh, 600)
  }

  async function saveSettings() {
    const patch = {
      start_url:  $('cfg-start-url').value.trim(),
      reset_time: parseInt($('cfg-reset-time').value, 10) || 0
    }
    try {
      await apiFetch('POST', '/api/config', patch)
      toast('Settings saved, restarting service…')
      setTimeout(() => { refresh(); loadSettings() }, 1500)
    } catch (e) {
      toast('Save failed: ' + e.message)
    }
  }

  async function applyRotation() {
    const rotation = $('cfg-rotation').value
    try {
      const r = await apiFetch('POST', '/api/screen', { rotation })
      toast(r.warning || 'Rotation applied')
    } catch (e) {
      toast('Failed: ' + e.message)
    }
  }

  async function loadKeyboard() {
    try {
      const k = await apiFetch('GET', '/api/keyboard')
      $('kbd-badge').className = 'status-badge' + (k.enabled ? ' active' : '')
      $('kbd-label').textContent = k.enabled ? 'Enabled' : 'Disabled'
    } catch (e) { /* ignore */ }
  }

  async function setKeyboard(enabled) {
    try {
      await apiFetch('POST', '/api/keyboard', { enabled })
      toast(enabled ? 'Virtual keyboard enabled' : 'Virtual keyboard disabled')
      loadKeyboard()
    } catch (e) {
      toast('Failed: ' + e.message)
    }
  }

  function toast(msg) {
    const el = $('toast')
    el.textContent = msg
    el.classList.add('show')
    clearTimeout(el._t)
    el._t = setTimeout(() => el.classList.remove('show'), 2500)
  }

  refresh()
  loadSettings()
  loadKeyboard()
  setInterval(refresh, 5000)
</script>
</body>
</html>
"""


@app.route('/')
@require_auth
def index():
    return PAGE_TEMPLATE


@app.route('/pke-logo.svg')
@require_auth
def logo():
    if not os.path.isfile(LOGO_FILE):
        return '', 404
    with open(LOGO_FILE, 'rb') as f:
        return Response(f.read(), mimetype='image/svg+xml')


@app.route('/api/status')
@require_auth
def status():
    cfg = read_config()
    safe = {k: v for k, v in cfg.items() if k not in ('web_pass', 'hmac_secret')}
    safe['hostname'] = socket.gethostname()
    safe['ip_addresses'] = get_ip_addresses()
    safe['active'] = is_chrome_active(cfg)
    return jsonify(safe)


@app.route('/api/command', methods=['POST'])
@require_auth
def command():
    body = request.get_json(force=True, silent=True) or {}
    cmd = body.get('cmd')
    if not isinstance(cmd, str):
        return jsonify({'error': 'cmd must be a string'}), 400
    params = body.get('params') or {}
    args = [params['url']] if cmd in ('start', 'restart', 'goto') and params.get('url') else []
    send_osc(cmd, *args)
    return jsonify({'ok': True})


@app.route('/api/config', methods=['POST'])
@require_auth
def update_config():
    body = request.get_json(force=True, silent=True) or {}
    cfg = read_config()
    for key in ('start_url', 'reset_time'):
        if key in body:
            cfg[key] = body[key]
    write_config(cfg)
    restart_avakiosc_service()
    return jsonify({'ok': True})


@app.route('/api/screen', methods=['GET'])
@require_auth
def get_screen():
    cfg = read_config()
    return jsonify({
        'rotation': cfg.get('screen_rotation', 'normal'),
        'output': get_xrandr_output()
    })


@app.route('/api/screen', methods=['POST'])
@require_auth
def set_screen():
    body = request.get_json(force=True, silent=True) or {}
    rotation = body.get('rotation')
    if rotation not in VALID_ROTATIONS:
        return jsonify({'error': f'rotation must be one of {sorted(VALID_ROTATIONS)}'}), 400
    cfg = read_config()
    cfg['screen_rotation'] = rotation
    write_config(cfg)
    try:
        apply_rotation(rotation)
    except Exception as e:
        return jsonify({'ok': True, 'warning': f'Saved, but live apply failed: {e}'})
    return jsonify({'ok': True})


@app.route('/api/keyboard', methods=['GET'])
@require_auth
def get_keyboard():
    cfg = read_config()
    return jsonify({
        'enabled': cfg.get('virtual_keyboard', True),
        'running': is_onboard_running()
    })


@app.route('/api/keyboard', methods=['POST'])
@require_auth
def set_keyboard():
    body = request.get_json(force=True, silent=True) or {}
    enabled = body.get('enabled')
    if not isinstance(enabled, bool):
        return jsonify({'error': 'enabled must be a boolean'}), 400
    cfg = read_config()
    cfg['virtual_keyboard'] = enabled
    write_config(cfg)
    if enabled:
        start_onboard()
    else:
        stop_onboard()
    return jsonify({'ok': True})


if __name__ == '__main__':
    cfg = read_config()
    app.run(host=cfg.get('web_bind', '0.0.0.0'), port=cfg.get('web_port', 8080))
