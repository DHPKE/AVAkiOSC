#!/usr/bin/env python3
"""AVAkiOSC WebAdmin - HTTP admin panel for the AVAkiOSC service"""

import os
import subprocess
from functools import wraps

import yaml
from flask import Flask, Response, jsonify, request
from pythonosc.udp_client import SimpleUDPClient

CONFIG_FILE = os.environ.get('AVAKIOSC_CONFIG', '/etc/avakiosc/config.yaml')

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
<title>AVAkiOSC WebAdmin</title>
<style>
body {{ font-family: sans-serif; max-width: 640px; margin: 2rem auto; padding: 0 1rem; }}
h1 {{ font-size: 1.4rem; }}
label {{ display: block; margin-top: 1rem; font-weight: bold; }}
input {{ width: 100%; padding: 0.4rem; box-sizing: border-box; }}
button {{ margin: 0.5rem 0.5rem 0 0; padding: 0.5rem 1rem; }}
#status {{ margin-top: 1rem; white-space: pre-wrap; background: #f2f2f2; padding: 0.5rem; }}
</style>
</head>
<body>
<h1>AVAkiOSC WebAdmin</h1>

<label for="start_url">Start URL</label>
<input id="start_url" value="{start_url}">

<label for="reset_time">Auto-reset interval (seconds, 0 = disabled)</label>
<input id="reset_time" type="number" value="{reset_time}">

<button onclick="saveConfig()">Save &amp; restart service</button>

<h1>Controls</h1>
<button onclick="cmd('start')">Start</button>
<button onclick="cmd('stop')">Stop</button>
<button onclick="cmd('restart')">Restart</button>
<button onclick="cmd('reload')">Reload page</button>
<button onclick="cmd('clear')">Clear cache/cookies</button>
<button onclick="goTo()">Go to URL</button>

<div id="status"></div>

<script>
function log(msg) {{ document.getElementById('status').textContent = msg; }}

function cmd(name) {{
  fetch('/api/command', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{cmd: name}})
  }}).then(r => r.json()).then(d => log(JSON.stringify(d))).catch(e => log(String(e)));
}}

function goTo() {{
  const url = document.getElementById('start_url').value;
  fetch('/api/command', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{cmd: 'goto', params: {{url}}}})
  }}).then(r => r.json()).then(d => log(JSON.stringify(d))).catch(e => log(String(e)));
}}

function saveConfig() {{
  const body = {{
    start_url: document.getElementById('start_url').value,
    reset_time: parseInt(document.getElementById('reset_time').value, 10) || 0
  }};
  fetch('/api/config', {{
    method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify(body)
  }}).then(r => r.json()).then(d => log(JSON.stringify(d))).catch(e => log(String(e)));
}}
</script>
</body>
</html>
"""


@app.route('/')
@require_auth
def index():
    cfg = read_config()
    return PAGE_TEMPLATE.format(
        start_url=cfg.get('start_url', ''),
        reset_time=cfg.get('reset_time', 0)
    )


@app.route('/api/status')
@require_auth
def status():
    cfg = read_config()
    safe = {k: v for k, v in cfg.items() if k not in ('web_pass', 'hmac_secret')}
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


if __name__ == '__main__':
    cfg = read_config()
    app.run(host=cfg.get('web_bind', '0.0.0.0'), port=cfg.get('web_port', 8080))
