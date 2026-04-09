# Windows Port Instructions — myScriber Transcriber

## Task

Build a Windows version of myScriber that is feature-equivalent to the macOS version. The app should run as a system tray application on Windows 10/11, providing local Whisper voice-to-text dictation.

## Step 1 — Pull the Repo and Study the macOS Version

Clone the private repo (you have access):

```bash
git clone https://github.com/nocodeuser1/myscriber.git
cd myscriber
```

Read `HANDOFF.md` for full context on the project. Then thoroughly read `app/myscriber.py` — this is the entire macOS application (~1920 lines). You'll be modeling the Windows version off of it.

Create the Windows version in a separate directory inside the repo:

```
myscriber/
├── app/                  # existing macOS version (DO NOT MODIFY)
├── windows/              # NEW — Windows version goes here
│   ├── myscriber_win.py  # main Windows application
│   ├── make_icons.py     # Windows icon generator (.ico)
│   └── installer.iss     # Inno Setup installer script
├── core/                 # NEW — shared cross-platform logic (extracted)
│   ├── __init__.py
│   ├── transcriber.py    # Whisper transcription engine
│   ├── audio.py          # Audio capture
│   └── config.py         # Config file handling
├── HANDOFF.md
└── ...
```

## Step 2 — Extract Shared Core

Before building the Windows version, extract the platform-independent logic from `app/myscriber.py` into `core/`. This code is identical on both platforms:

### What goes in `core/transcriber.py`:
- Whisper model loading (both `openai-whisper` and `faster-whisper` backends)
- `MLX_MODEL_MAP` dictionary (macOS only uses mlx_whisper, but Windows will use `faster-whisper` or `openai-whisper`)
- The `_transcribe()` inner function logic: numpy array → Whisper → text result
- WAV file writing helper (`_write_wav`)
- Model download via HuggingFace Hub

### What goes in `core/audio.py`:
- `sounddevice` audio capture (stream setup, callback, frames collection)
- RMS volume calculation for the visual level indicator
- Constants: `SAMPLE_RATE = 16000`, `CHANNELS = 1`

### What goes in `core/config.py`:
- Config file read/write (`config.json` — same format on both platforms)
- `APP_VERSION`, `UPDATE_URL`, `GITHUB_REPO` constants
- Default config values
- Version comparison logic for update checker

### Important for Windows backend selection:
- macOS uses `mlx_whisper` (Apple Silicon) or `openai-whisper` (Intel)
- Windows should use `faster-whisper` (CTranslate2-based, much faster than openai-whisper on CPU/CUDA) as primary, falling back to `openai-whisper`
- If the Windows machine has an NVIDIA GPU, `faster-whisper` will use CUDA automatically

## Step 3 — Build the Windows Application

### 3A. System Tray (replaces macOS menubar)

macOS uses `rumps` for the menubar. On Windows, use `pystray` with `Pillow` for the system tray icon.

The tray menu must include all the same items:
- Status text ("Loading model..." / "Ready — hold Ctrl+L")
- Model submenu (tiny, base, small, medium, large-v3) with checkmark on active model
- Mode: Push-to-talk / Toggle
- Hotkey display ("Hotkey: Ctrl+L")
- Set Hotkey...
- Check for Updates...
- Version 1.0.0
- Uninstall myScriber...
- Quit myScriber

Tray icon should be a microphone `.ico` file. Generate it in `windows/make_icons.py` using the same SDF approach as `app/make_icons.py` but output `.ico` format.

### 3B. Global Hotkey (replaces CGEventTap)

macOS uses `CGEventTap` from the Quartz framework for global hotkey capture with key suppression. On Windows, use the `keyboard` library or `pynput`.

**Key behaviors to replicate:**
- Default hotkey: `Ctrl+L` (Windows equivalent of Cmd+L)
- Push-to-talk: hold hotkey → record, release → transcribe
- Toggle mode: press → start recording, press again → stop and transcribe
- **Key suppression**: The hotkey should NOT type "L" into the active field. On macOS this is done by returning `None` from the CGEventTap callback. On Windows, `keyboard` library's `hook` with `suppress=True` achieves this, or use `pynput` with event suppression.
- **wait_for_up mechanism**: When transcription completes while the key is still held, ignore further key-down events until a real key-up arrives. This prevents key-repeat from restarting recording. See the macOS code's `wait_for_up` dict for the pattern.

**Hotkey learning ("Set Hotkey..."):**
The macOS version opens an osascript dialog, then uses CGEventTap to capture the next keypress. On Windows, create a small tkinter or PyQt dialog that captures the next keypress using `keyboard.read_event()` or similar.

### 3C. Smart Text Delivery (replaces Accessibility API + pbcopy)

macOS checks if the focused element is an editable text field using the Accessibility API (`AXUIElement`). On Windows, use `UI Automation` via `comtypes` or `pywinaui`:

```python
import comtypes.client

def focused_element_is_editable():
    """Check if the focused UI element is a text input on Windows."""
    try:
        uia = comtypes.client.CreateObject("{ff48dba4-60ef-4201-aa87-54103eef594e}")  # CUIAutomation
        focused = uia.GetFocusedElement()
        # Check control type
        control_type = focused.CurrentControlType
        editable_types = {
            50004,  # UIA_EditControlTypeId
            50025,  # UIA_DocumentControlTypeId
        }
        if control_type in editable_types:
            return True
        # Check if element supports ValuePattern (writable)
        try:
            focused.GetCurrentPattern(10002)  # UIA_ValuePatternId
            return True
        except:
            pass
        return False
    except:
        return False
```

**Paste mechanism:**
- macOS: `pbcopy` + osascript Cmd+V
- Windows: `pyperclip.copy(text)` or `win32clipboard`, then simulate `Ctrl+V` via `keyboard.send('ctrl+v')` or `pyautogui`

### 3D. Overlay Panel (replaces NSPanel)

macOS uses a floating `NSPanel` with `setHidesOnDeactivate_(False)`. On Windows, create a `tkinter.Toplevel` or PyQt `QDialog` with these properties:

- Always on top (`wm_attributes('-topmost', True)` in tkinter)
- Does NOT steal focus from the active window (use `overrideredirect` carefully, or `-toolwindow` style)
- Shows transcribed text in an editable text area
- "Close" and "Copy to Clipboard" buttons
- Supports re-dictation: holding the hotkey while overlay is open appends new text
- Hint label showing "Hold Ctrl+L to dictate more · Edit below"
- Persists until explicitly closed or copied

**Critical:** The overlay must not deactivate the previously active window. On macOS this is `setBecomesKeyOnlyIfNeeded_(True)`. On Windows, use `WS_EX_NOACTIVATE` window style or show the window without activating it.

### 3E. Notifications (replaces macOS NSUserNotification)

macOS uses `rumps.notification()`. On Windows, use `win10toast` or `plyer`:

```python
from plyer import notification
notification.notify(title="myScriber", message="Copied to clipboard!", timeout=3)
```

### 3F. Update Checker (same mechanism)

The update checker works identically — it fetches the same public gist URL. The only difference: instead of `osascript` dialogs, use `tkinter.messagebox` or a native Windows dialog. And `subprocess.Popen(["open", url])` becomes `os.startfile(url)` or `webbrowser.open(url)`.

### 3G. Logging

Same approach — log to `%APPDATA%\myScriber\myscriber.log` instead of `~/.myscriber/myscriber.log`.

Config file: `%APPDATA%\myScriber\config.json`.

## Step 4 — Windows Installer

### Option A: Inno Setup (recommended)
Create an `installer.iss` script that:
- Installs Python if not present (or bundles it)
- Creates a venv and installs pip dependencies
- Places app files in `%PROGRAMFILES%\myScriber\` or `%LOCALAPPDATA%\myScriber\`
- Creates a Start Menu shortcut
- Adds "Run at startup" registry entry (optional)
- Creates an uninstaller

### Option B: PyInstaller
Bundle everything into a single `.exe`:
```bash
pyinstaller --onefile --windowed --icon=assets/myscriber.ico windows/myscriber_win.py
```
This avoids requiring Python to be installed but produces a larger executable.

**Recommended approach:** Use PyInstaller to create the `.exe`, then wrap it in an Inno Setup installer for a professional install experience.

## Step 5 — Windows Dependencies

```
# requirements-windows.txt
sounddevice
numpy
faster-whisper        # primary Whisper backend for Windows (CUDA support)
openai-whisper        # fallback
pystray               # system tray
Pillow                # icon/image handling
keyboard              # global hotkey with suppression
pyperclip             # clipboard
plyer                 # notifications
huggingface-hub       # model downloads
comtypes              # UI Automation (editable field detection)
```

## Step 6 — Platform Equivalence Reference Table

| Feature | macOS | Windows |
|---------|-------|---------|
| System tray/menubar | `rumps` | `pystray` + `Pillow` |
| Global hotkey | `CGEventTap` (Quartz) | `keyboard` library |
| Key suppression | Return `None` from tap callback | `keyboard.hook(suppress=True)` |
| Editable field check | `AXUIElement` (ctypes HIServices) | `UI Automation` (comtypes) |
| Clipboard | `pbcopy` subprocess | `pyperclip` or `win32clipboard` |
| Paste simulation | `osascript` Cmd+V | `keyboard.send('ctrl+v')` |
| Floating overlay | `NSPanel` (AppKit) | `tkinter.Toplevel` or PyQt |
| Notifications | `rumps.notification()` | `plyer.notification` |
| Dialogs | `osascript display dialog` | `tkinter.messagebox` |
| Whisper backend | `mlx_whisper` / `openai-whisper` | `faster-whisper` / `openai-whisper` |
| Config location | `~/.myscriber/` | `%APPDATA%\myScriber\` |
| App bundle | `/Applications/myScriber.app` | `%LOCALAPPDATA%\myScriber\` |
| Installer | DMG (`hdiutil`) | Inno Setup + PyInstaller |
| Open URL | `subprocess.Popen(["open", url])` | `webbrowser.open(url)` |
| Auto-start | Login Items | Registry `HKCU\...\Run` |

## Step 7 — Testing Checklist

After building, verify all of these work:

- [ ] App starts and shows system tray icon
- [ ] Tray menu has all items (model, mode, hotkey, update, version, quit)
- [ ] Holding Ctrl+L records audio (tray icon changes to indicate recording)
- [ ] Releasing Ctrl+L transcribes and pastes into active text field
- [ ] Hotkey does NOT type "L" into the active field
- [ ] When no text field is focused, overlay panel appears
- [ ] Overlay stays on top when clicking other windows
- [ ] Re-dictation into open overlay appends text
- [ ] Copy to Clipboard button works and dismisses overlay
- [ ] Model switching works (tray menu → Model submenu)
- [ ] "Set Hotkey..." captures a new hotkey combination
- [ ] "Check for Updates" shows correct dialog
- [ ] Notifications appear (transcription complete, errors)
- [ ] App survives 20+ consecutive dictations without crash or freeze
- [ ] Config persists across restarts
- [ ] Installer creates working installation
- [ ] Uninstaller removes all files

## Important Notes

- **Do NOT modify the macOS code** in `app/`. The Windows version is separate.
- Keep `APP_VERSION` in sync between macOS and Windows if releasing together.
- The update gist (`version.json`) may need platform-specific download URLs in the future. For now, a single version number works since the gist just triggers the "update available" dialog.
- The repo is private. Push the Windows code to a `windows-port` branch first for review, then merge to `main`.
