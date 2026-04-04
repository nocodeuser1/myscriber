# OpenClaw Handoff — myScriber Transcriber

**Telegram Topic:** `myScriber Transcriber`

---

## What myScriber Is

myScriber is a macOS menubar app that provides local, on-device voice-to-text dictation powered by OpenAI's Whisper model. The user holds a hotkey (default Cmd+L), speaks, and upon release the audio is transcribed and either pasted directly into the active text field or shown in a floating overlay panel if no editable field is focused. All processing happens locally — no audio data ever leaves the user's machine.

### Core Features

- **Menubar app** built with `rumps` (Python), lives in the macOS status bar with a microphone template icon
- **Push-to-talk or toggle mode** — user chooses their preference
- **Configurable hotkey** — defaults to Cmd+L, changeable via "Set Hotkey..." menu item (uses CGEventTap for global key capture)
- **Multiple Whisper models** — tiny, base, small, medium, large-v3 (selectable from menu)
- **Apple Silicon optimized** — uses `mlx_whisper` on M-series Macs for fast local inference; falls back to `openai-whisper` on Intel
- **Smart text delivery** — auto-pastes into editable fields via accessibility API, or shows a floating NSPanel overlay with copy-to-clipboard when no text field is active
- **Overlay panel** — floating NSPanel (stays on top of all windows, persists until dismissed), shows transcribed text with a Copy button
- **In-app update checker** — checks a public GitHub Gist for new version info
- **Uninstaller** — built into the menu ("Uninstall myScriber...")
- **DMG packaging** — `build_dmg.command` creates a distributable .dmg installer

### Tech Stack

- Python 3.10+ with PyObjC (NSPanel, NSImage, CGEventTap, Accessibility APIs)
- `rumps` for menubar app framework
- `mlx_whisper` (Apple Silicon) or `openai-whisper` (Intel) for transcription
- `sounddevice` + `numpy` for audio capture
- HuggingFace Hub for model downloads
- macOS native notifications, Accessibility permission for hotkey suppression

---

## Repository

- **Repo:** `nocodeuser1/myscriber` (PRIVATE)
- **URL:** https://github.com/nocodeuser1/myscriber
- **Branch:** `main`
- **Current version:** `1.0.0`

### File Structure

```
myscriber/
├── app/
│   ├── myscriber.py          # Main application (~1920 lines)
│   ├── make_icons.py         # Generates menubar icons (SDF rendering, 8x supersampling)
│   ├── installer_gui.py      # GUI installer (tkinter)
│   └── installer_server.py   # Installer backend
├── assets/                   # Generated icons (mic_template.png, @2x, AppIcon.iconset/)
├── install.sh                # CLI installer (sets up venv, deps, .app bundle)
├── update.command            # Quick update — copies code + relaunches (double-clickable)
├── build_dmg.command         # Builds distributable .dmg (double-clickable)
├── Install myScriber.command # User-facing installer (double-clickable)
├── Uninstall myScriber.command
├── .gitignore
└── README.md
```

### Key Locations on User's Mac (Post-Install)

- `~/.myscriber/` — app runtime (venv, app code, config, models, logs)
- `~/.myscriber/config.json` — user settings (model, hotkey, mode)
- `~/.myscriber/myscriber.log` — runtime log
- `/Applications/myScriber.app` — macOS .app bundle (thin launcher shell script)

---

## Update System — How It Works

The app checks for updates against a **public GitHub Gist** (not the private repo's API). This is critical because the repo is private and unauthenticated API calls to private repos return 404.

### Version Check Gist

- **Gist URL:** https://gist.github.com/nocodeuser1/19ae5cbd0057f2f7a3b04ac2f667118f
- **Raw URL (used by the app):** `https://gist.githubusercontent.com/nocodeuser1/19ae5cbd0057f2f7a3b04ac2f667118f/raw/version.json`
- **Visibility:** Public (anyone can read it, which is required for the app to check)

The gist contains a single file `version.json`:

```json
{
  "version": "1.0.0",
  "download_url": "https://github.com/nocodeuser1/myscriber/releases/latest",
  "notes": "Initial release of myScriber."
}
```

### How the App Checks

In `myscriber.py`, the `_check_for_updates` method (triggered from the "Check for Updates..." menu item):

1. Fetches the raw gist URL via `urllib.request`
2. Parses the JSON and reads the `version` field
3. Compares it to `APP_VERSION` (defined at the top of myscriber.py, currently `"1.0.0"`)
4. If the gist version is newer, shows an osascript dialog offering to open `download_url`
5. If up to date, shows an "up to date" dialog
6. If the request fails, shows an error dialog

The relevant constants at the top of `myscriber.py`:

```python
APP_VERSION  = "1.0.0"
GITHUB_REPO  = "nocodeuser1/myscriber"  # GitHub repo (private)
UPDATE_URL   = "https://gist.githubusercontent.com/nocodeuser1/19ae5cbd0057f2f7a3b04ac2f667118f/raw/version.json"
```

### How to Push an Update (Step by Step)

When you release a new version:

1. **Make your code changes** in the repo and update `APP_VERSION` in `app/myscriber.py`:
   ```python
   APP_VERSION  = "1.1.0"  # bump this
   ```

2. **Commit and push** to the `main` branch:
   ```bash
   git add -A
   git commit -m "Release 1.1.0 — description of changes"
   git push origin main
   ```

3. **Build the DMG** (on a Mac with the repo cloned):
   ```bash
   # Double-click build_dmg.command, or:
   bash build_dmg.command
   ```
   This reads the version from `myscriber.py`, stages files, and creates `dist/myScriber-1.1.0.dmg`.

4. **Create a GitHub Release** and attach the DMG:
   ```bash
   gh release create v1.1.0 'dist/myScriber-1.1.0.dmg' \
     --title 'myScriber 1.1.0' \
     --notes 'Release notes here'
   ```
   Or create the release manually on GitHub and upload the DMG.

5. **Update the version gist** so existing users see the update. Edit the gist at https://gist.github.com/nocodeuser1/19ae5cbd0057f2f7a3b04ac2f667118f and change `version.json` to:
   ```json
   {
     "version": "1.1.0",
     "download_url": "https://github.com/nocodeuser1/myscriber/releases/tag/v1.1.0",
     "notes": "What's new in this version."
   }
   ```
   Or via CLI:
   ```bash
   gh gist edit 19ae5cbd0057f2f7a3b04ac2f667118f -f version.json
   ```

   **This step is what triggers the "update available" dialog for users.** If you forget to update the gist, users will keep seeing "You are up to date" even after a new release exists.

### Important Notes

- The `download_url` in the gist should point to the GitHub Release page (or wherever the DMG is hosted for purchase/download). Even though the repo is private, GitHub Release pages for private repos are accessible to anyone with the direct link if the release assets are public. If you want the download hosted elsewhere (e.g., a website), just change `download_url` to that URL.
- The gist must remain **public**. If it becomes private/secret, the update checker will fail with the same error as before.
- Version comparison is simple semantic tuple comparison (`1.1.0 > 1.0.0`). Use standard semver format.

---

## Known Issues and Technical Notes

### Things That Were Fixed (for context if they resurface)

- **ObjC class re-registration crash:** `_OverlayBtnHelper(NSObject)` must be defined at module level, never inside a method. PyObjC registers ObjC classes globally and crashes if the same class name is registered twice.
- **CGEventTap timeout:** macOS disables slow event tap callbacks. The handler re-enables the tap on `kCGEventTapDisabledByTimeout` but does NOT auto-stop recording (that caused a premature transcription loop).
- **wait_for_up mechanism:** Prevents key-repeat events from restarting recording after a forced stop. The hotkey handler swallows key-down events while `wait_for_up` is active, until a real key-up arrives.
- **Transcription overlap guard:** A `_transcribing` boolean prevents overlapping transcription threads that caused app freezes.
- **Overlay persistence:** The NSPanel uses `setHidesOnDeactivate_(False)` so it stays visible when the user clicks other apps.
- **Retina menubar icon:** Uses multi-representation NSImage with `NSBitmapImageRep` for 1x and 2x PNGs, 8x supersampling in the icon generator.

### Virtual Memory

The app may show very high virtual memory in Activity Monitor (hundreds of GB). This is normal for Python apps with ML models on macOS — it's virtual address space, not actual RAM usage. Look at "Memory" (real memory) instead.

---

## Config File Format

`~/.myscriber/config.json`:

```json
{
  "model": "base",
  "hotkey": "cmd+l",
  "mode": "push_to_talk"
}
```

- `model`: one of `tiny`, `base`, `small`, `medium`, `large-v3`
- `hotkey`: modifier+key format (e.g., `cmd+l`, `option+space`, `cmd+shift+k`)
- `mode`: `push_to_talk` (hold to record) or `toggle` (press to start/stop)
