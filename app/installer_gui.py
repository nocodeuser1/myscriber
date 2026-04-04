#!/usr/bin/env python3
"""
myScriber Installer GUI — a tkinter window that:
  1. Shows a welcome screen
  2. Lets the user pick a Whisper model (with sizes)
  3. Runs install.sh in a subprocess, streaming output
  4. Shows a progress bar and log
"""

import tkinter as tk
from tkinter import ttk, messagebox
import subprocess
import threading
import os
import sys
import json
from pathlib import Path

# ── Model definitions ─────────────────────────────────────────────────────────

MODELS = [
    ("tiny",     "40 MB",   "Instant speed, decent quality"),
    ("base",     "150 MB",  "~1s delay, good quality — recommended"),
    ("small",    "500 MB",  "~2s delay, better quality"),
    ("medium",   "1.5 GB",  "~4s delay, great quality"),
    ("large-v3", "3 GB",    "~6s delay, best quality"),
]

# ── Colour palette ────────────────────────────────────────────────────────────

BG       = "#1E1E2E"
BG_LIGHT = "#2A2A3C"
FG       = "#CDD6F4"
FG_DIM   = "#7F849C"
ACCENT   = "#4A3FC7"
ACCENT_H = "#5A4FD7"
GREEN    = "#A6E3A1"
YELLOW   = "#F9E2AF"
RED      = "#F38BA8"
WHITE    = "#FFFFFF"

FONT_FAMILY = "Helvetica"


class InstallerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("myScriber Installer")
        self.root.configure(bg=BG)
        self.root.resizable(False, False)

        # Centre on screen
        w, h = 560, 620
        sx = (self.root.winfo_screenwidth() - w) // 2
        sy = (self.root.winfo_screenheight() - h) // 2
        self.root.geometry(f"{w}x{h}+{sx}+{sy}")

        self.selected_model = tk.StringVar(value="base")
        self.install_dir = os.path.join(str(Path.home()), ".myscriber")
        self.script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

        self._build_welcome()

    # ── Page 1: Welcome + model picker ────────────────────────────────────────

    def _build_welcome(self):
        self._clear()

        # Header
        hdr = tk.Frame(self.root, bg=ACCENT, height=90)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        tk.Label(hdr, text="myScriber", font=(FONT_FAMILY, 28, "bold"),
                 fg=WHITE, bg=ACCENT).pack(pady=(18, 0))
        tk.Label(hdr, text="Local Whisper Dictation for macOS",
                 font=(FONT_FAMILY, 12), fg="#D0CCFF", bg=ACCENT).pack()

        # Body
        body = tk.Frame(self.root, bg=BG, padx=30, pady=20)
        body.pack(fill="both", expand=True)

        tk.Label(body, text="Choose a Whisper model to install:",
                 font=(FONT_FAMILY, 14, "bold"), fg=FG, bg=BG,
                 anchor="w").pack(fill="x", pady=(0, 12))

        # Model radio buttons
        self.model_frame = tk.Frame(body, bg=BG)
        self.model_frame.pack(fill="x")

        for name, size, desc in MODELS:
            row = tk.Frame(self.model_frame, bg=BG_LIGHT, padx=14, pady=10,
                           highlightbackground="#3A3A4C", highlightthickness=1)
            row.pack(fill="x", pady=3)

            rb = tk.Radiobutton(
                row, variable=self.selected_model, value=name,
                bg=BG_LIGHT, fg=FG, selectcolor=BG_LIGHT,
                activebackground=BG_LIGHT, activeforeground=FG,
                highlightthickness=0, font=(FONT_FAMILY, 13),
                text=f"  {name}",
            )
            rb.pack(side="left")

            tk.Label(row, text=size, font=(FONT_FAMILY, 11, "bold"),
                     fg=YELLOW, bg=BG_LIGHT, width=8).pack(side="right")

            tk.Label(row, text=desc, font=(FONT_FAMILY, 11),
                     fg=FG_DIM, bg=BG_LIGHT).pack(side="right", padx=(0, 10))

            # Let clicking anywhere on the row select it
            for widget in [row, rb]:
                widget.bind("<Button-1>", lambda e, n=name: self.selected_model.set(n))

        # Note
        tk.Label(body, text="You can switch models later from the menubar menu.",
                 font=(FONT_FAMILY, 11), fg=FG_DIM, bg=BG,
                 anchor="w").pack(fill="x", pady=(14, 0))

        tk.Label(body, text="M-series Macs use mlx-whisper automatically for faster performance.",
                 font=(FONT_FAMILY, 11), fg=FG_DIM, bg=BG,
                 anchor="w").pack(fill="x", pady=(4, 0))

        # Install button
        btn_frame = tk.Frame(body, bg=BG)
        btn_frame.pack(fill="x", pady=(20, 0))

        self.install_btn = tk.Button(
            btn_frame, text="Install myScriber", font=(FONT_FAMILY, 14, "bold"),
            bg=ACCENT, fg=WHITE, activebackground=ACCENT_H, activeforeground=WHITE,
            relief="flat", padx=24, pady=10, cursor="hand2",
            command=self._start_install,
        )
        self.install_btn.pack(side="right")

        quit_btn = tk.Button(
            btn_frame, text="Cancel", font=(FONT_FAMILY, 12),
            bg=BG_LIGHT, fg=FG_DIM, activebackground=BG_LIGHT, activeforeground=FG,
            relief="flat", padx=16, pady=8, cursor="hand2",
            command=self.root.destroy,
        )
        quit_btn.pack(side="right", padx=(0, 10))

    # ── Page 2: Installing ────────────────────────────────────────────────────

    def _build_progress(self):
        self._clear()

        hdr = tk.Frame(self.root, bg=ACCENT, height=70)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text="Installing myScriber…", font=(FONT_FAMILY, 20, "bold"),
                 fg=WHITE, bg=ACCENT).pack(pady=18)

        body = tk.Frame(self.root, bg=BG, padx=30, pady=20)
        body.pack(fill="both", expand=True)

        # Current step label
        self.step_label = tk.Label(body, text="Preparing…",
                                   font=(FONT_FAMILY, 13), fg=FG, bg=BG, anchor="w")
        self.step_label.pack(fill="x", pady=(0, 8))

        # Progress bar
        style = ttk.Style()
        style.theme_use("default")
        style.configure("Custom.Horizontal.TProgressbar",
                        troughcolor=BG_LIGHT, background=ACCENT,
                        darkcolor=ACCENT, lightcolor=ACCENT_H,
                        bordercolor=BG_LIGHT, thickness=18)

        self.progress = ttk.Progressbar(body, style="Custom.Horizontal.TProgressbar",
                                         mode="determinate", maximum=100)
        self.progress.pack(fill="x", pady=(0, 16))

        # Log output
        tk.Label(body, text="Log:", font=(FONT_FAMILY, 11, "bold"),
                 fg=FG_DIM, bg=BG, anchor="w").pack(fill="x")

        log_frame = tk.Frame(body, bg="#11111B", highlightbackground="#3A3A4C",
                             highlightthickness=1)
        log_frame.pack(fill="both", expand=True, pady=(4, 0))

        self.log_text = tk.Text(log_frame, bg="#11111B", fg="#A6ADC8",
                                font=("Menlo", 10), wrap="word",
                                relief="flat", padx=8, pady=8,
                                state="disabled", highlightthickness=0)
        self.log_text.pack(fill="both", expand=True)

        scrollbar = ttk.Scrollbar(self.log_text, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")

    # ── Page 3: Done ──────────────────────────────────────────────────────────

    def _build_done(self, success):
        self._clear()

        colour = GREEN if success else RED
        title = "Installation Complete!" if success else "Installation Failed"
        emoji = "✓" if success else "✗"

        hdr = tk.Frame(self.root, bg=ACCENT, height=90)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        tk.Label(hdr, text=f"{emoji}  {title}", font=(FONT_FAMILY, 22, "bold"),
                 fg=colour, bg=ACCENT).pack(pady=28)

        body = tk.Frame(self.root, bg=BG, padx=30, pady=30)
        body.pack(fill="both", expand=True)

        if success:
            steps = [
                ("1.", "Grant Microphone access", "System Settings → Privacy & Security → Microphone → myScriber"),
                ("2.", "Grant Accessibility access", "System Settings → Privacy & Security → Accessibility → myScriber"),
                ("3.", "Launch myScriber from /Applications", "Hold Option+Space anywhere to dictate"),
            ]
            tk.Label(body, text="Next steps:", font=(FONT_FAMILY, 14, "bold"),
                     fg=FG, bg=BG, anchor="w").pack(fill="x", pady=(0, 12))

            for num, title, detail in steps:
                row = tk.Frame(body, bg=BG)
                row.pack(fill="x", pady=4)
                tk.Label(row, text=num, font=(FONT_FAMILY, 13, "bold"),
                         fg=ACCENT_H, bg=BG, width=3, anchor="ne").pack(side="left", padx=(0, 4))
                col = tk.Frame(row, bg=BG)
                col.pack(side="left", fill="x")
                tk.Label(col, text=title, font=(FONT_FAMILY, 13, "bold"),
                         fg=FG, bg=BG, anchor="w").pack(fill="x")
                tk.Label(col, text=detail, font=(FONT_FAMILY, 11),
                         fg=FG_DIM, bg=BG, anchor="w").pack(fill="x")

            btn_frame = tk.Frame(body, bg=BG)
            btn_frame.pack(fill="x", pady=(24, 0))

            launch_btn = tk.Button(
                btn_frame, text="Launch myScriber", font=(FONT_FAMILY, 14, "bold"),
                bg=ACCENT, fg=WHITE, activebackground=ACCENT_H, activeforeground=WHITE,
                relief="flat", padx=24, pady=10, cursor="hand2",
                command=self._launch_app,
            )
            launch_btn.pack(side="right")

            close_btn = tk.Button(
                btn_frame, text="Close", font=(FONT_FAMILY, 12),
                bg=BG_LIGHT, fg=FG_DIM, activebackground=BG_LIGHT, activeforeground=FG,
                relief="flat", padx=16, pady=8, cursor="hand2",
                command=self.root.destroy,
            )
            close_btn.pack(side="right", padx=(0, 10))
        else:
            tk.Label(body, text="Something went wrong. Check the log output above.",
                     font=(FONT_FAMILY, 13), fg=FG, bg=BG, anchor="w").pack(fill="x")

            close_btn = tk.Button(
                body, text="Close", font=(FONT_FAMILY, 14, "bold"),
                bg=RED, fg=WHITE, relief="flat", padx=24, pady=10,
                cursor="hand2", command=self.root.destroy,
            )
            close_btn.pack(pady=(20, 0), anchor="e")

    # ── Install logic ─────────────────────────────────────────────────────────

    def _start_install(self):
        model = self.selected_model.get()

        # Write model choice to config before install runs
        config_path = os.path.join(self.install_dir, "config.json")
        os.makedirs(self.install_dir, exist_ok=True)
        config = {
            "model": model,
            "language": "auto",
            "hotkey": "option+space",
            "mode": "push_to_talk",
        }
        with open(config_path, "w") as f:
            json.dump(config, f, indent=2)

        self._build_progress()

        # Steps with rough progress percentages
        self.step_map = {
            "macOS":           5,
            "Homebrew":       10,
            "Python":         15,
            "ffmpeg":         20,
            "virtual env":    30,
            "packages":       40,
            "Packages":       55,
            "Copying":        60,
            "icons":          65,
            "Icons":          70,
            "Building":       75,
            ".app installed": 80,
            "Downloading":    85,
            "Model":          95,
            "All done":      100,
        }

        threading.Thread(target=self._run_install, args=(model,), daemon=True).start()

    def _run_install(self, model):
        script = os.path.join(self.script_dir, "install.sh")
        env = os.environ.copy()
        env["MYSCRIBER_MODEL"] = model
        env["MYSCRIBER_GUI"] = "1"  # Tell install.sh we're running from GUI

        try:
            proc = subprocess.Popen(
                ["bash", script],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                cwd=self.script_dir, env=env,
                bufsize=1, universal_newlines=True,
            )

            for line in proc.stdout:
                line = line.rstrip()
                if not line:
                    continue
                self._log(line)

                # Update progress based on keywords
                for keyword, pct in self.step_map.items():
                    if keyword.lower() in line.lower():
                        self._set_progress(pct)
                        # Update step label with a clean version
                        clean = line
                        # Strip ANSI escape codes
                        import re
                        clean = re.sub(r'\x1b\[[0-9;]*m', '', clean)
                        clean = clean.strip()
                        if clean:
                            self._set_step(clean[:80])
                        break

            proc.wait()
            success = proc.returncode == 0
        except Exception as e:
            self._log(f"Error: {e}")
            success = False

        self.root.after(500, lambda: self._build_done(success))

    def _log(self, text):
        import re
        text = re.sub(r'\x1b\[[0-9;]*m', '', text)

        def _do():
            self.log_text.configure(state="normal")
            self.log_text.insert("end", text + "\n")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        self.root.after(0, _do)

    def _set_progress(self, value):
        self.root.after(0, lambda: self.progress.configure(value=value))

    def _set_step(self, text):
        self.root.after(0, lambda: self.step_label.configure(text=text))

    def _launch_app(self):
        subprocess.Popen(["open", "/Applications/myScriber.app"])
        self.root.after(500, self.root.destroy)

    def _clear(self):
        for w in self.root.winfo_children():
            w.destroy()


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    root = tk.Tk()

    # macOS-specific styling
    try:
        root.tk.call("::tk::unsupported::MacWindowStyle", "style",
                      root._w, "moveableModal", "")
    except tk.TclError:
        pass

    InstallerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
