#!/usr/bin/env python3
"""
myScriber Installer — lightweight local HTTP server that serves a beautiful
HTML installer page in the user's default browser.  Zero external dependencies.

Flow:
  1.  Shell script launches this server
  2.  Browser opens to http://localhost:<port>
  3.  User picks a model and clicks Install
  4.  Server writes the choice to a temp file and returns it to stdout
  5.  Shell script reads the choice and runs install.sh
"""

import http.server
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from urllib.parse import parse_qs

CHOSEN_MODEL = None
SERVER_SHOULD_STOP = False
INSTALL_DIR = Path.home() / ".myscriber"
SCRIPT_DIR = Path(__file__).parent.parent


def get_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


INSTALLER_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>myScriber Installer</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

  * { margin: 0; padding: 0; box-sizing: border-box; }

  body {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    background: #0F0F1A;
    color: #E0E0F0;
    min-height: 100vh;
    display: flex;
    justify-content: center;
    align-items: center;
    padding: 20px;
  }

  .container {
    width: 100%;
    max-width: 540px;
  }

  /* ── Header ─────────────────────────────────────────────── */
  .header {
    text-align: center;
    margin-bottom: 32px;
  }

  .logo {
    width: 88px;
    height: 88px;
    margin: 0 auto 20px;
    background: linear-gradient(135deg, #4A3FC7 0%, #6C5CE7 100%);
    border-radius: 22px;
    display: flex;
    align-items: center;
    justify-content: center;
    box-shadow: 0 8px 32px rgba(74, 63, 199, 0.35);
  }

  .logo svg { width: 48px; height: 48px; }

  .header h1 {
    font-size: 28px;
    font-weight: 700;
    letter-spacing: -0.5px;
    margin-bottom: 6px;
  }

  .header p {
    color: #8888AA;
    font-size: 15px;
    font-weight: 400;
  }

  /* ── Card ────────────────────────────────────────────────── */
  .card {
    background: #1A1A2E;
    border: 1px solid #2A2A40;
    border-radius: 16px;
    padding: 28px;
    margin-bottom: 20px;
  }

  .card-title {
    font-size: 14px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    color: #6C5CE7;
    margin-bottom: 16px;
  }

  /* ── Model list ─────────────────────────────────────────── */
  .model-option {
    display: flex;
    align-items: center;
    padding: 14px 16px;
    border: 2px solid transparent;
    border-radius: 12px;
    cursor: pointer;
    transition: all 0.15s ease;
    margin-bottom: 8px;
    background: #12121F;
  }

  .model-option:last-child { margin-bottom: 0; }
  .model-option:hover { background: #1E1E34; border-color: #3A3A55; }

  .model-option.selected {
    background: rgba(74, 63, 199, 0.12);
    border-color: #4A3FC7;
  }

  .model-radio {
    width: 20px;
    height: 20px;
    border: 2px solid #3A3A55;
    border-radius: 50%;
    margin-right: 14px;
    flex-shrink: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: all 0.15s ease;
  }

  .model-option.selected .model-radio {
    border-color: #4A3FC7;
  }

  .model-radio-inner {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background: #4A3FC7;
    transform: scale(0);
    transition: transform 0.15s ease;
  }

  .model-option.selected .model-radio-inner {
    transform: scale(1);
  }

  .model-info { flex: 1; }

  .model-name {
    font-size: 15px;
    font-weight: 600;
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .model-badge {
    font-size: 10px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    padding: 2px 7px;
    border-radius: 4px;
    background: rgba(74, 63, 199, 0.25);
    color: #9D91FF;
  }

  .model-desc {
    font-size: 13px;
    color: #6A6A88;
    margin-top: 2px;
  }

  .model-size {
    font-size: 13px;
    font-weight: 600;
    color: #F9E2AF;
    flex-shrink: 0;
    margin-left: 12px;
  }

  /* ── Features ────────────────────────────────────────────── */
  .features {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10px;
    margin-bottom: 8px;
  }

  .feature {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 13px;
    color: #8888AA;
  }

  .feature-icon {
    width: 18px;
    height: 18px;
    border-radius: 50%;
    background: rgba(166, 227, 161, 0.12);
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }

  .feature-icon svg { width: 10px; height: 10px; }

  /* ── Buttons ─────────────────────────────────────────────── */
  .actions {
    display: flex;
    justify-content: flex-end;
    gap: 12px;
  }

  .btn {
    padding: 12px 28px;
    border-radius: 10px;
    font-size: 15px;
    font-weight: 600;
    border: none;
    cursor: pointer;
    transition: all 0.15s ease;
    font-family: inherit;
  }

  .btn-secondary {
    background: #1A1A2E;
    color: #8888AA;
    border: 1px solid #2A2A40;
  }

  .btn-secondary:hover { background: #222238; color: #AAAACC; }

  .btn-primary {
    background: linear-gradient(135deg, #4A3FC7 0%, #5A4FD7 100%);
    color: white;
    box-shadow: 0 4px 16px rgba(74, 63, 199, 0.3);
  }

  .btn-primary:hover {
    background: linear-gradient(135deg, #5548D0 0%, #6558E0 100%);
    box-shadow: 0 6px 24px rgba(74, 63, 199, 0.4);
    transform: translateY(-1px);
  }

  .btn-primary:active { transform: translateY(0); }

  /* ── Note ────────────────────────────────────────────────── */
  .note {
    text-align: center;
    font-size: 12px;
    color: #555570;
    margin-top: 16px;
  }

  /* ── Progress page ──────────────────────────────────────── */
  .progress-section { display: none; }
  .progress-section.active { display: block; }
  .welcome-section.hidden { display: none; }

  .progress-bar-track {
    width: 100%;
    height: 6px;
    background: #12121F;
    border-radius: 3px;
    overflow: hidden;
    margin: 16px 0;
  }

  .progress-bar-fill {
    height: 100%;
    background: linear-gradient(90deg, #4A3FC7, #6C5CE7);
    border-radius: 3px;
    width: 0%;
    transition: width 0.5s ease;
  }

  .progress-status {
    font-size: 14px;
    color: #8888AA;
    margin-bottom: 12px;
  }

  .log-output {
    background: #0A0A14;
    border: 1px solid #1E1E30;
    border-radius: 10px;
    padding: 14px;
    font-family: 'Menlo', 'Monaco', monospace;
    font-size: 11px;
    color: #6A6A88;
    height: 200px;
    overflow-y: auto;
    line-height: 1.6;
    white-space: pre-wrap;
    word-break: break-all;
  }

  .log-output .log-success { color: #A6E3A1; }
  .log-output .log-warning { color: #F9E2AF; }
  .log-output .log-info { color: #89B4FA; }

  /* ── Done page ──────────────────────────────────────────── */
  .done-section { display: none; }
  .done-section.active { display: block; }

  .done-icon {
    width: 64px;
    height: 64px;
    margin: 0 auto 16px;
    background: rgba(166, 227, 161, 0.12);
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
  }

  .done-icon svg { width: 32px; height: 32px; }

  .done-title {
    font-size: 22px;
    font-weight: 700;
    text-align: center;
    margin-bottom: 8px;
  }

  .done-subtitle {
    text-align: center;
    color: #8888AA;
    font-size: 14px;
    margin-bottom: 24px;
  }

  .step-list { list-style: none; }

  .step-list li {
    display: flex;
    align-items: flex-start;
    gap: 12px;
    padding: 12px 0;
    border-bottom: 1px solid #1E1E30;
  }

  .step-list li:last-child { border-bottom: none; }

  .step-num {
    width: 24px;
    height: 24px;
    border-radius: 50%;
    background: rgba(74, 63, 199, 0.2);
    color: #9D91FF;
    font-size: 12px;
    font-weight: 700;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    margin-top: 1px;
  }

  .step-text strong { display: block; font-size: 14px; margin-bottom: 2px; }
  .step-text span { font-size: 13px; color: #6A6A88; }
</style>
</head>
<body>

<!-- ── WELCOME PAGE ──────────────────────────────────────── -->
<div class="container">
<div class="welcome-section" id="welcomePage">

  <div class="header">
    <div class="logo">
      <svg viewBox="0 0 48 48" fill="none">
        <rect x="16" y="6" width="16" height="24" rx="8" fill="white"/>
        <path d="M12 26c0 6.627 5.373 12 12 12s12-5.373 12-12" stroke="white" stroke-width="3" stroke-linecap="round"/>
        <line x1="24" y1="38" x2="24" y2="44" stroke="white" stroke-width="3" stroke-linecap="round"/>
        <line x1="18" y1="44" x2="30" y2="44" stroke="white" stroke-width="3" stroke-linecap="round"/>
      </svg>
    </div>
    <h1>myScriber</h1>
    <p>Local Whisper dictation for your Mac menubar</p>
  </div>

  <div class="card">
    <div class="card-title">Choose a Whisper Model</div>

    <div class="model-option selected" data-model="tiny" onclick="selectModel(this)">
      <div class="model-radio"><div class="model-radio-inner"></div></div>
      <div class="model-info">
        <div class="model-name">tiny</div>
        <div class="model-desc">Instant speed, decent quality</div>
      </div>
      <div class="model-size">40 MB</div>
    </div>

    <div class="model-option" data-model="base" onclick="selectModel(this)">
      <div class="model-radio"><div class="model-radio-inner"></div></div>
      <div class="model-info">
        <div class="model-name">base <span class="model-badge">Recommended</span></div>
        <div class="model-desc">~1 second delay, good quality</div>
      </div>
      <div class="model-size">150 MB</div>
    </div>

    <div class="model-option" data-model="small" onclick="selectModel(this)">
      <div class="model-radio"><div class="model-radio-inner"></div></div>
      <div class="model-info">
        <div class="model-name">small</div>
        <div class="model-desc">~2 second delay, better quality</div>
      </div>
      <div class="model-size">500 MB</div>
    </div>

    <div class="model-option" data-model="medium" onclick="selectModel(this)">
      <div class="model-radio"><div class="model-radio-inner"></div></div>
      <div class="model-info">
        <div class="model-name">medium</div>
        <div class="model-desc">~4 second delay, great quality</div>
      </div>
      <div class="model-size">1.5 GB</div>
    </div>

    <div class="model-option" data-model="large-v3" onclick="selectModel(this)">
      <div class="model-radio"><div class="model-radio-inner"></div></div>
      <div class="model-info">
        <div class="model-name">large-v3</div>
        <div class="model-desc">~6 second delay, best quality</div>
      </div>
      <div class="model-size">3 GB</div>
    </div>
  </div>

  <div class="card">
    <div class="card-title">Included</div>
    <div class="features">
      <div class="feature">
        <div class="feature-icon"><svg viewBox="0 0 10 10" fill="none"><path d="M2 5l2 2 4-4" stroke="#A6E3A1" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg></div>
        100% local &amp; private
      </div>
      <div class="feature">
        <div class="feature-icon"><svg viewBox="0 0 10 10" fill="none"><path d="M2 5l2 2 4-4" stroke="#A6E3A1" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg></div>
        No API costs
      </div>
      <div class="feature">
        <div class="feature-icon"><svg viewBox="0 0 10 10" fill="none"><path d="M2 5l2 2 4-4" stroke="#A6E3A1" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg></div>
        Works offline
      </div>
      <div class="feature">
        <div class="feature-icon"><svg viewBox="0 0 10 10" fill="none"><path d="M2 5l2 2 4-4" stroke="#A6E3A1" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg></div>
        Apple Silicon optimized
      </div>
    </div>
  </div>

  <div class="actions">
    <button class="btn btn-secondary" onclick="cancelInstall()">Cancel</button>
    <button class="btn btn-primary" id="installBtn" onclick="startInstall()">Install myScriber</button>
  </div>

  <div class="note">You can switch models anytime from the menubar menu.</div>
</div>

<!-- ── PROGRESS PAGE ─────────────────────────────────────── -->
<div class="progress-section" id="progressPage">
  <div class="header">
    <div class="logo">
      <svg viewBox="0 0 48 48" fill="none">
        <rect x="16" y="6" width="16" height="24" rx="8" fill="white"/>
        <path d="M12 26c0 6.627 5.373 12 12 12s12-5.373 12-12" stroke="white" stroke-width="3" stroke-linecap="round"/>
        <line x1="24" y1="38" x2="24" y2="44" stroke="white" stroke-width="3" stroke-linecap="round"/>
        <line x1="18" y1="44" x2="30" y2="44" stroke="white" stroke-width="3" stroke-linecap="round"/>
      </svg>
    </div>
    <h1>Installing…</h1>
    <p id="progressStatus">Preparing installation</p>
  </div>

  <div class="card">
    <div class="progress-bar-track">
      <div class="progress-bar-fill" id="progressBar"></div>
    </div>
    <div class="log-output" id="logOutput"></div>
  </div>

  <div class="note">This may take a few minutes depending on your connection.</div>
</div>

<!-- ── DONE PAGE ──────────────────────────────────────────── -->
<div class="done-section" id="donePage">
  <div class="header">
    <div class="done-icon">
      <svg viewBox="0 0 32 32" fill="none">
        <path d="M8 16l5 5 11-11" stroke="#A6E3A1" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
    </div>
    <div class="done-title">You're all set!</div>
    <div class="done-subtitle">myScriber is installed and ready to go.</div>
  </div>

  <div class="card">
    <div class="card-title">Before you start</div>
    <ul class="step-list">
      <li>
        <div class="step-num">1</div>
        <div class="step-text">
          <strong>Grant Microphone access</strong>
          <span>System Settings → Privacy & Security → Microphone → myScriber</span>
        </div>
      </li>
      <li>
        <div class="step-num">2</div>
        <div class="step-text">
          <strong>Grant Accessibility access</strong>
          <span>System Settings → Privacy & Security → Accessibility → myScriber</span>
        </div>
      </li>
      <li>
        <div class="step-num">3</div>
        <div class="step-text">
          <strong>Hold Option + Space anywhere</strong>
          <span>Speak, release, and the transcription pastes automatically</span>
        </div>
      </li>
    </ul>
  </div>

  <div class="actions">
    <button class="btn btn-secondary" onclick="closePage()">Close</button>
    <button class="btn btn-primary" onclick="launchApp()">Launch myScriber</button>
  </div>
</div>

</div>

<script>
  let selectedModel = 'base';
  let pollTimer = null;

  // Default-select "base"
  document.addEventListener('DOMContentLoaded', () => {
    const base = document.querySelector('[data-model="base"]');
    if (base) selectModel(base);
  });

  function selectModel(el) {
    document.querySelectorAll('.model-option').forEach(o => o.classList.remove('selected'));
    el.classList.add('selected');
    selectedModel = el.dataset.model;
  }

  function cancelInstall() {
    fetch('/cancel', { method: 'POST' }).then(() => {
      document.body.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100vh;color:#6A6A88;font-family:Inter,sans-serif;">You can close this tab.</div>';
    });
  }

  function startInstall() {
    document.getElementById('welcomePage').classList.add('hidden');
    document.getElementById('progressPage').classList.add('active');

    fetch('/install', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model: selectedModel })
    });

    // Poll for progress
    pollTimer = setInterval(pollProgress, 800);
  }

  function pollProgress() {
    fetch('/progress')
      .then(r => r.json())
      .then(data => {
        document.getElementById('progressBar').style.width = data.percent + '%';
        document.getElementById('progressStatus').textContent = data.status || 'Installing…';

        const log = document.getElementById('logOutput');
        if (data.log) {
          log.innerHTML = colorize(data.log);
          log.scrollTop = log.scrollHeight;
        }

        if (data.done) {
          clearInterval(pollTimer);
          setTimeout(() => {
            document.getElementById('progressPage').classList.remove('active');
            document.getElementById('donePage').classList.add('active');
          }, 600);
        }
      })
      .catch(() => {});
  }

  function colorize(text) {
    return text
      .replace(/✓[^\n]*/g, '<span class="log-success">$&</span>')
      .replace(/⚠[^\n]*/g, '<span class="log-warning">$&</span>')
      .replace(/→[^\n]*/g, '<span class="log-info">$&</span>');
  }

  function launchApp() {
    fetch('/launch', { method: 'POST' });
    document.body.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100vh;color:#6A6A88;font-family:Inter,sans-serif;">myScriber is running — look for the mic icon in your menubar. You can close this tab.</div>';
  }

  function closePage() {
    fetch('/cancel', { method: 'POST' });
    document.body.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100vh;color:#6A6A88;font-family:Inter,sans-serif;">You can close this tab.</div>';
  }
</script>

</body>
</html>"""


class InstallerState:
    """Shared state between the HTTP handler and the install thread."""
    def __init__(self):
        self.percent = 0
        self.status = "Preparing…"
        self.log = ""
        self.done = False
        self.model = "base"


state = InstallerState()


class InstallerHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(INSTALLER_HTML.encode("utf-8"))
        elif self.path == "/progress":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "percent": state.percent,
                "status": state.status,
                "log": state.log,
                "done": state.done,
            }).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/install":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            state.model = body.get("model", "base")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')
            # Kick off install in background
            threading.Thread(target=run_install, daemon=True).start()
        elif self.path == "/launch":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"ok":true}')
            subprocess.Popen(["open", "/Applications/myScriber.app"])
            schedule_shutdown()
        elif self.path == "/cancel":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"ok":true}')
            schedule_shutdown()
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # Suppress console output


def schedule_shutdown():
    def _stop():
        time.sleep(1)
        os._exit(0)
    threading.Thread(target=_stop, daemon=True).start()


# ── Install runner ────────────────────────────────────────────────────────────

STEP_MAP = [
    ("macOS",       5,  "Checking macOS version…"),
    ("Homebrew",   10,  "Checking Homebrew…"),
    ("Python",     18,  "Setting up Python…"),
    ("ffmpeg",     22,  "Checking ffmpeg…"),
    ("virtual env", 30, "Creating virtual environment…"),
    ("Installing packages", 38, "Installing Python packages…"),
    ("Packages installed",  55, "Packages installed"),
    ("Copying",    60,  "Copying app files…"),
    ("icons",      65,  "Generating icons…"),
    ("Icons ready", 70, "Icons ready"),
    ("Building",   75,  "Building myScriber.app…"),
    (".app installed", 82, "App bundle created"),
    ("Downloading", 85, "Downloading Whisper model…"),
    ("Model ready", 95, "Model downloaded"),
    ("All done",  100,  "Installation complete!"),
]


def strip_ansi(text):
    import re
    return re.sub(r'\x1b\[[0-9;]*m', '', text)


def run_install():
    import re

    state.status = "Starting installation…"
    state.percent = 2

    # Write config with chosen model
    INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    config = {
        "model": state.model,
        "language": "auto",
        "hotkey": "option+space",
        "mode": "push_to_talk",
    }
    with open(INSTALL_DIR / "config.json", "w") as f:
        json.dump(config, f, indent=2)

    env = os.environ.copy()
    env["MYSCRIBER_MODEL"] = state.model
    env["MYSCRIBER_GUI"] = "1"

    script = str(SCRIPT_DIR / "install.sh")

    try:
        proc = subprocess.Popen(
            ["bash", script],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            cwd=str(SCRIPT_DIR), env=env,
            bufsize=1, universal_newlines=True,
        )

        for line in proc.stdout:
            clean = strip_ansi(line.rstrip())
            if not clean:
                continue
            state.log += clean + "\n"

            for keyword, pct, label in STEP_MAP:
                if keyword.lower() in clean.lower():
                    state.percent = pct
                    state.status = label
                    break

        proc.wait()

        if proc.returncode == 0:
            state.percent = 100
            state.status = "Installation complete!"
        else:
            state.status = "Installation failed — check log"

    except Exception as e:
        state.log += f"\nError: {e}\n"
        state.status = f"Error: {e}"

    state.done = True


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    port = get_free_port()
    server = http.server.HTTPServer(("127.0.0.1", port), InstallerHandler)

    url = f"http://127.0.0.1:{port}"
    print(f"INSTALLER_URL={url}")
    sys.stdout.flush()

    # Open browser after a short delay
    def open_browser():
        time.sleep(0.4)
        webbrowser.open(url)
    threading.Thread(target=open_browser, daemon=True).start()

    server.serve_forever()


if __name__ == "__main__":
    main()
