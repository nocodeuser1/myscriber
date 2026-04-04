#!/usr/bin/env python3
"""
myScriber — local Whisper dictation in your Mac menubar.
Hold Option+Space anywhere to record; release to transcribe and paste.
"""

import rumps
import sounddevice as sd
import numpy as np
import threading
import tempfile
import os
import sys
import json
import subprocess
import wave
import time
import logging
import math
from pathlib import Path

# ── Patch process identity for notifications ─────────────────────────────────
# macOS notifications get their icon from the sending process's bundle.
# Since we run as Python, we need to override the bundle identity so macOS
# looks up the icon from /Applications/myScriber.app instead.
try:
    from Foundation import NSBundle
    _main_bundle = NSBundle.mainBundle()
    if _main_bundle:
        _main_info = _main_bundle.infoDictionary()
        if _main_info is not None:
            _main_info['CFBundleIdentifier'] = 'com.myscriber.app'
            _main_info['CFBundleName'] = 'myScriber'
            _main_info['CFBundleDisplayName'] = 'myScriber'
except Exception:
    pass

# ── Logging to file ───────────────────────────────────────────────────────────
LOG_FILE = Path.home() / ".myscriber" / "myscriber.log"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(str(LOG_FILE))],
)
log = logging.getLogger("myscriber")

# ── Whisper backend detection ─────────────────────────────────────────────────
# Apple Silicon uses mlx_whisper; Intel uses openai-whisper.
# They have different APIs so we abstract them here.

# ── Force anonymous HuggingFace access ────────────────────────────────────────
# A stale cached HF token on this machine causes 401 errors on public model
# downloads.  MUST set env vars BEFORE importing huggingface_hub because
# its constants module caches them at import time.
os.environ["HF_HUB_DISABLE_IMPLICIT_TOKEN"] = "1"
os.environ.pop("HF_TOKEN", None)
os.environ.pop("HUGGING_FACE_HUB_TOKEN", None)
os.environ["HF_HUB_OFFLINE"] = "0"

# Delete stale cached token file if it exists
_hf_token_path = Path.home() / ".cache" / "huggingface" / "token"
try:
    if _hf_token_path.exists():
        _hf_token_path.unlink()
        log.info("Deleted stale HuggingFace token file")
except Exception:
    pass

from huggingface_hub import snapshot_download as _hf_snapshot_download

USE_MLX = False
try:
    import mlx_whisper
    USE_MLX = True
    log.info("Using mlx_whisper backend (Apple Silicon)")
except ImportError:
    try:
        import whisper
        log.info("Using openai-whisper backend")
    except ImportError:
        log.error("No whisper backend found! Install mlx-whisper or openai-whisper.")

# mlx_whisper uses HuggingFace repo paths
MLX_MODEL_MAP = {
    "tiny":     "mlx-community/whisper-tiny",
    "base":     "mlx-community/whisper-base-mlx",
    "small":    "mlx-community/whisper-small-mlx",
    "medium":   "mlx-community/whisper-medium-mlx",
    "large-v3": "mlx-community/whisper-large-v3-mlx",
}

APP_VERSION  = "1.0.0"
GITHUB_REPO  = "nocodeuser1/myscriber"  # GitHub repo for update checks
UPDATE_URL   = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

CONFIG_PATH  = Path.home() / ".myscriber" / "config.json"
ASSETS_DIR   = Path(__file__).parent.parent / "assets"
MIC_ICON     = str(ASSETS_DIR / "mic_template.png")

SAMPLE_RATE = 16000
CHANNELS    = 1

DEFAULT_CONFIG = {
    "model":    "base",
    "language": "auto",
    "hotkey":   "cmd+l",
    "mode":     "push_to_talk",
}


def load_config():
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH) as f:
                return {**DEFAULT_CONFIG, **json.load(f)}
        except Exception:
            pass
    return DEFAULT_CONFIG.copy()


def save_config(cfg):
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)


# ── ObjC helper for overlay button actions (must be defined once at module level) ──
try:
    from Foundation import NSObject as _NSObject
    import objc as _objc

    class _OverlayBtnHelper(_NSObject):
        """NSObject subclass to wire NSButton target/action for the overlay panel."""
        @_objc.python_method
        def setup(self, close_fn, copy_fn):
            self._close = close_fn
            self._copy = copy_fn

        @_objc.IBAction
        def doClose_(self, sender):
            self._close()

        @_objc.IBAction
        def doCopy_(self, sender):
            self._copy()
except Exception:
    _OverlayBtnHelper = None


class MyScriber(rumps.App):
    def __init__(self):
        # Prefer @2x retina icon for crisp menubar rendering
        retina_icon = ASSETS_DIR / "mic_template@2x.png"
        if retina_icon.exists():
            icon = str(retina_icon)
        elif Path(MIC_ICON).exists():
            icon = MIC_ICON
        else:
            icon = None
        super().__init__("myScriber", icon=icon, template=True, quit_button=None)
        # Force logical size to 18x18 pt so the 36px retina image renders at correct size
        try:
            from AppKit import NSSize
            btn = self._nsapp.nsstatusitem.button()
            if btn and btn.image():
                btn.image().setSize_(NSSize(18, 18))
        except Exception:
            pass

        self.config         = load_config()
        self.recording      = False
        self.audio_frames   = []
        self.stream         = None
        self.whisper_model  = None
        self.model_loaded   = False
        self._hotkey_listener = None
        self._event_tap = None
        self._last_vol_level = -1
        self._volume_icons  = []  # NSImages for volume levels (blue mic)

        self._set_app_icon()
        self._load_volume_icons()
        self._build_menu()
        self._request_accessibility()
        self._load_model_async()
        self._register_hotkey()

        # Schedule crisp retina icon once the run loop is ready
        try:
            from PyObjCTools import AppHelper
            AppHelper.callAfter(self._restore_template_icon)
        except Exception:
            pass

    # ── Application icon (shown on all dialogs) ────────────────────────────

    _app_icon_image = None  # cached NSImage for reuse on every dialog

    def _set_app_icon(self):
        """Load the app icon into an NSImage and cache it for dialogs."""
        try:
            from AppKit import NSApplication, NSImage

            candidates = [
                ASSETS_DIR / "AppIcon.icns",
                ASSETS_DIR / "AppIcon.iconset" / "icon_256x256.png",
                ASSETS_DIR / "AppIcon.iconset" / "icon_128x128.png",
                Path(MIC_ICON),
            ]
            log.info(f"Looking for app icon, ASSETS_DIR={ASSETS_DIR}")

            # Try loading from file
            for p in candidates:
                if p.exists():
                    img = NSImage.alloc().initWithContentsOfFile_(str(p))
                    if img:
                        self.__class__._app_icon_image = img
                        NSApplication.sharedApplication().setApplicationIconImage_(img)
                        log.info(f"App icon loaded from {p}")
                        return

            # Generate icons on the fly if not found
            make_icons = Path(__file__).parent / "make_icons.py"
            if make_icons.exists():
                log.info("No icon files found — generating")
                try:
                    subprocess.run(
                        [sys.executable, str(make_icons)],
                        capture_output=True, timeout=30,
                    )
                    for p in candidates:
                        if p.exists():
                            img = NSImage.alloc().initWithContentsOfFile_(str(p))
                            if img:
                                self.__class__._app_icon_image = img
                                NSApplication.sharedApplication().setApplicationIconImage_(img)
                                log.info(f"App icon loaded from generated {p}")
                                return
                except Exception as e2:
                    log.warning(f"Icon generation failed: {e2}")

            log.warning("No app icon available")
        except Exception as e:
            log.warning(f"Could not set app icon: {e}")

    def _load_volume_icons(self):
        """Pre-load blue volume-level icons for recording feedback."""
        try:
            from AppKit import NSImage, NSSize
            for i in range(6):
                retina = ASSETS_DIR / f"mic_vol_{i}@2x.png"
                normal = ASSETS_DIR / f"mic_vol_{i}.png"
                img = None
                if retina.exists():
                    img = NSImage.alloc().initWithContentsOfFile_(str(retina))
                    if img:
                        img.setSize_(NSSize(18, 18))  # retina: 36px at 18pt
                        img.setTemplate_(False)  # show actual blue color
                elif normal.exists():
                    img = NSImage.alloc().initWithContentsOfFile_(str(normal))
                    if img:
                        img.setTemplate_(False)
                self._volume_icons.append(img)
            log.info(f"Loaded {len([i for i in self._volume_icons if i])} volume icons")
        except Exception as e:
            log.warning(f"Could not load volume icons: {e}")

    def _set_volume_icon(self, level):
        """Set the menubar icon to a blue volume-level indicator."""
        if not self._volume_icons or level >= len(self._volume_icons):
            return
        img = self._volume_icons[level]
        if not img:
            return
        try:
            btn = self._nsapp.nsstatusitem.button()
            if btn:
                btn.setImage_(img)
        except Exception as e:
            log.warning(f"Could not set volume icon: {e}")

    _cached_template_icon = None  # cached multi-rep NSImage

    def _make_template_icon(self):
        """Build an NSImage with both 1x and 2x representations for crisp retina."""
        if self._cached_template_icon:
            return self._cached_template_icon
        try:
            from AppKit import NSImage, NSSize, NSBitmapImageRep
            img = NSImage.alloc().initWithSize_(NSSize(18, 18))
            # Add both resolutions as separate representations
            for path in [ASSETS_DIR / "mic_template.png", ASSETS_DIR / "mic_template@2x.png"]:
                if path.exists():
                    rep = NSBitmapImageRep.imageRepWithContentsOfFile_(str(path))
                    if rep:
                        img.addRepresentation_(rep)
            img.setTemplate_(True)
            self.__class__._cached_template_icon = img
            return img
        except Exception as e:
            log.warning(f"Could not build template icon: {e}")
            return None

    def _restore_template_icon(self):
        """Restore the normal template (monochrome) menubar icon."""
        try:
            img = self._make_template_icon()
            if img:
                btn = self._nsapp.nsstatusitem.button()
                if btn:
                    btn.setImage_(img)
        except Exception as e:
            log.warning(f"Could not restore template icon: {e}")
            try:
                self.icon = MIC_ICON
            except Exception:
                pass

    def _notify(self, title, message, subtitle=""):
        """Send a macOS notification with the myScriber icon.

        Uses NSUserNotification with contentImage set to our icon as a
        fallback in case the bundle identity patch alone isn't enough.
        """
        try:
            from Foundation import NSUserNotification, NSUserNotificationCenter
            notif = NSUserNotification.alloc().init()
            notif.setTitle_(title)
            if subtitle:
                notif.setSubtitle_(subtitle)
            notif.setInformativeText_(message)
            # Set our icon as the content image (appears alongside text)
            if self._app_icon_image:
                notif.setContentImage_(self._app_icon_image)
            center = NSUserNotificationCenter.defaultUserNotificationCenter()
            center.deliverNotification_(notif)
        except Exception as e:
            log.warning(f"Custom notification failed, falling back to rumps: {e}")
            rumps.notification(title, subtitle, message)

    def _branded_alert(self, title, message, ok="OK", cancel=None, dimensions=None, default_text=""):
        """Show an NSAlert with the myScriber icon.

        rumps.Window doesn't expose NSAlert.setIcon_, so we build the
        alert ourselves via PyObjC for full control over branding.

        Returns (clicked: bool, text: str).
        """
        try:
            from AppKit import (
                NSAlert, NSAlertFirstButtonReturn,
                NSScrollView, NSTextView, NSFont,
                NSMakeRect, NSViewWidthSizable, NSViewHeightSizable,
            )

            alert = NSAlert.alloc().init()
            alert.setMessageText_(title)
            alert.setInformativeText_(message)
            alert.addButtonWithTitle_(ok)
            if cancel:
                alert.addButtonWithTitle_(cancel)

            # Set our branded icon
            if self._app_icon_image:
                alert.setIcon_(self._app_icon_image)

            # Optional editable text area
            text_view = None
            if dimensions and dimensions != (0, 0):
                w, h = dimensions
                scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(0, 0, w, h))
                scroll.setHasVerticalScroller_(True)
                scroll.setBorderType_(2)  # NSBezelBorder

                content_size = scroll.contentSize()
                text_view = NSTextView.alloc().initWithFrame_(
                    NSMakeRect(0, 0, content_size.width, content_size.height)
                )
                text_view.setMinSize_((0, content_size.height))
                text_view.setMaxSize_((1e7, 1e7))
                text_view.setVerticallyResizable_(True)
                text_view.setHorizontallyResizable_(False)
                text_view.textContainer().setWidthTracksTextView_(True)
                text_view.setFont_(NSFont.systemFontOfSize_(13))
                text_view.setString_(default_text)
                text_view.setEditable_(True)
                text_view.setSelectable_(True)

                scroll.setDocumentView_(text_view)
                alert.setAccessoryView_(scroll)

            result = alert.runModal()
            clicked = (result == NSAlertFirstButtonReturn)
            text = ""
            if text_view:
                text = text_view.string()
            return clicked, text

        except Exception as e:
            log.error(f"Branded alert failed, using rumps fallback: {e}")
            # Fallback to rumps.Window
            try:
                w = rumps.Window(
                    message=message, title=title, default_text=default_text,
                    ok=ok, cancel=cancel or "",
                    dimensions=dimensions or (0, 0),
                )
                r = w.run()
                return bool(r.clicked), r.text
            except Exception as e2:
                log.error(f"rumps.Window fallback also failed: {e2}")
                return False, ""

    # ── Accessibility permission ────────────────────────────────────────────

    def _request_accessibility(self):
        """Prompt macOS for Accessibility access (required for global hotkeys)."""
        try:
            import ctypes
            # Load ApplicationServices for AXIsProcessTrustedWithOptions
            appserv = ctypes.cdll.LoadLibrary(
                "/System/Library/Frameworks/ApplicationServices.framework"
                "/ApplicationServices"
            )
            appserv.AXIsProcessTrustedWithOptions.restype = ctypes.c_bool
            appserv.AXIsProcessTrustedWithOptions.argtypes = [ctypes.c_void_p]

            # Build CFDictionary {kAXTrustedCheckOptionPrompt: kCFBooleanTrue}
            # via PyObjC toll-free bridging (NSDictionary == CFDictionaryRef)
            from Foundation import NSDictionary, NSNumber
            import objc
            options = NSDictionary.dictionaryWithObject_forKey_(
                NSNumber.numberWithBool_(True),
                "AXTrustedCheckOptionPrompt",
            )
            trusted = appserv.AXIsProcessTrustedWithOptions(
                objc.pyobjc_id(options)
            )
            if trusted:
                log.info("Accessibility access: granted")
            else:
                log.warning(
                    "Accessibility access: NOT granted — "
                    "global hotkey will not work until permission is enabled in "
                    "System Settings → Privacy & Security → Accessibility"
                )
        except Exception as e:
            log.warning(f"Could not check Accessibility permission: {e}")

    # ── Menu ────────────────────────────────────────────────────────────────

    def _build_menu(self):
        self.status_item = rumps.MenuItem("Loading model…")

        self.model_menu = rumps.MenuItem("Model")
        for m in ["tiny", "base", "small", "medium", "large-v3"]:
            lbl = ("✓ " if m == self.config["model"] else "    ") + m
            self.model_menu.add(rumps.MenuItem(lbl, callback=self._make_model_setter(m)))

        self.mode_item = rumps.MenuItem(
            "Mode: Push-to-talk" if self.config["mode"] == "push_to_talk" else "Mode: Toggle",
            callback=self._toggle_mode,
        )
        self.hotkey_display = rumps.MenuItem(
            f"Hotkey: {self._pretty_hotkey()}"
        )
        self.set_hotkey_item = rumps.MenuItem(
            "Set Hotkey…", callback=self._learn_hotkey,
        )

        self.menu = [
            self.status_item,
            None,
            self.model_menu,
            self.mode_item,
            self.hotkey_display,
            self.set_hotkey_item,
            None,
            rumps.MenuItem("Check for Updates…", callback=self._check_for_updates),
            rumps.MenuItem(f"Version {APP_VERSION}"),
            None,
            rumps.MenuItem("Uninstall myScriber…", callback=self._uninstall),
            rumps.MenuItem("Quit myScriber", callback=self._quit),
        ]

    # ── Whisper model ────────────────────────────────────────────────────────

    def _load_model_async(self):
        def _load():
            model_name = self.config["model"]
            self._set_status(f"Loading {model_name}…")
            try:
                if USE_MLX:
                    repo = MLX_MODEL_MAP.get(model_name, f"mlx-community/whisper-{model_name}-mlx")
                    log.info(f"Downloading {repo} with token=False …")
                    local_path = _hf_snapshot_download(repo_id=repo, token=False)
                    log.info(f"Model cached at {local_path}")
                    mlx_whisper.load_models.load_model(local_path)
                    self.whisper_model = repo
                else:
                    self.whisper_model = whisper.load_model(model_name)
                self.model_loaded = True
                self._set_status(f"Ready · {model_name}")
                log.info(f"Model '{model_name}' loaded successfully")
            except Exception as e:
                log.error(f"Failed to load model: {e}")
                self._set_status(f"Error loading model")

        threading.Thread(target=_load, daemon=True).start()

    # ── Hotkey ───────────────────────────────────────────────────────────────
    # macOS virtual keycodes for common keys
    _KEYCODES = {
        "space": 49, "return": 36, "tab": 48, "escape": 53,
        "delete": 51, "backspace": 51,
        "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97,
        "f7": 98, "f8": 100, "f9": 101, "f10": 109, "f11": 103, "f12": 111,
        "a": 0, "b": 11, "c": 8, "d": 2, "e": 14, "f": 3, "g": 5, "h": 4,
        "i": 34, "j": 38, "k": 40, "l": 37, "m": 46, "n": 45, "o": 31,
        "p": 35, "q": 12, "r": 15, "s": 1, "t": 17, "u": 32, "v": 9,
        "w": 13, "x": 7, "y": 16, "z": 6,
    }
    # CGEvent modifier flag masks
    _MOD_FLAGS = {
        "option": 0x00080000, "alt": 0x00080000,
        "ctrl": 0x00040000, "control": 0x00040000,
        "cmd": 0x00100000, "command": 0x00100000,
        "shift": 0x00020000,
    }

    def _parse_hotkey(self):
        """Parse config hotkey string into (modifier_mask, keycode)."""
        parts = [p.strip().lower() for p in self.config["hotkey"].split("+")]
        mod_mask = 0
        keycode = None
        for part in parts:
            if part in self._MOD_FLAGS:
                mod_mask |= self._MOD_FLAGS[part]
            elif part in self._KEYCODES:
                keycode = self._KEYCODES[part]
        return mod_mask, keycode

    def _stop_hotkey(self):
        """Tear down the current hotkey listener.  Safe to call multiple times."""
        # Grab and CLEAR references first — prevents double-free if called twice
        tap = getattr(self, '_event_tap', None)
        source = getattr(self, '_event_tap_source', None)
        self._event_tap = None
        self._event_tap_source = None
        self._tap_callback_ref = None

        if tap:
            try:
                import Quartz
                Quartz.CGEventTapEnable(tap, False)
                if source:
                    Quartz.CFRunLoopRemoveSource(
                        Quartz.CFRunLoopGetMain(), source,
                        Quartz.kCFRunLoopCommonModes,
                    )
            except Exception:
                pass

        listener = self._hotkey_listener
        self._hotkey_listener = None
        if listener:
            try:
                listener.stop()
            except Exception:
                pass

    def _register_hotkey(self):
        """Register the global hotkey.

        Push-to-talk mode uses a native macOS CGEventTap so we can
        *suppress* the key event — no stray characters get typed.
        Toggle mode uses pynput GlobalHotKeys (suppression not needed).
        """
        # Always tear down existing listeners first to prevent duplicates
        self._stop_hotkey()

        if self.config["mode"] == "push_to_talk":
            if self._register_hotkey_eventtap():
                return  # success
            log.warning("CGEventTap failed — falling back to pynput")
        self._register_hotkey_pynput()

    # ── CGEventTap implementation (push-to-talk, suppresses keys) ────────

    def _register_hotkey_eventtap(self):
        """Set up a CGEventTap that intercepts and suppresses the hotkey.

        Uses PyObjC Quartz bindings (not raw ctypes) for reliable bridging
        of CoreGraphics event tap types on both Intel and Apple Silicon.
        """
        try:
            import Quartz
        except ImportError:
            log.error("pyobjc-framework-Quartz not installed — cannot use CGEventTap")
            return False

        mod_mask, keycode = self._parse_hotkey()
        if keycode is None:
            log.error(f"Cannot parse hotkey: {self.config['hotkey']}")
            return False

        log.info(f"CGEventTap hotkey: keycode={keycode}, mod_mask=0x{mod_mask:x}")

        kCGKeyboardEventKeycode = 9
        kCGEventNull = getattr(Quartz, 'kCGEventNull', 0)  # = 0
        pressed = {"down": False}
        # "wait_for_up" prevents re-triggering from key-repeat events
        # after a safety stop fires while the key is still physically held.
        wait_for_up = {"active": False}
        app = self

        # Safety timer: auto-stop recording if key-up is missed (e.g. tap was
        # disabled by macOS timeout and key-up event was lost).
        MAX_RECORD_SECS = 120  # 2 minutes max

        def _safety_stop():
            """Called on main thread if recording exceeds MAX_RECORD_SECS."""
            if pressed["down"] and app.recording:
                log.warning("Safety timeout — stopping stuck recording")
                pressed["down"] = False
                wait_for_up["active"] = True  # ignore repeats until real key-up
                app._stop_and_transcribe()

        def _tap_cb(proxy, etype, event, refcon):
            try:
                # Re-enable tap if macOS disabled it (callback took too long)
                if etype == Quartz.kCGEventTapDisabledByTimeout:
                    Quartz.CGEventTapEnable(app._event_tap, True)
                    log.info("CGEventTap re-enabled after timeout")
                    # Don't auto-stop recording here — the user may still
                    # be holding the key.  The 2-min safety timer handles
                    # truly stuck recordings.  Re-enabling the tap is
                    # enough; we'll catch the real key-up event now.
                    return event

                if etype not in (Quartz.kCGEventKeyDown, Quartz.kCGEventKeyUp):
                    return event

                kc = Quartz.CGEventGetIntegerValueField(event, kCGKeyboardEventKeycode)
                flags = Quartz.CGEventGetFlags(event)
                mods = flags & 0x00FF0000  # isolate modifier bits

                if kc == keycode and (mods & mod_mask) == mod_mask:
                    if etype == Quartz.kCGEventKeyDown:
                        # Ignore key-repeat events after a safety stop
                        if wait_for_up["active"]:
                            pass  # swallow repeats until real key-up
                        elif not pressed["down"]:
                            pressed["down"] = True
                            app._start_recording()
                            # Start safety timer in case key-up is lost
                            def _safety_timeout():
                                if pressed["down"] and app.recording:
                                    try:
                                        from PyObjCTools import AppHelper
                                        AppHelper.callAfter(_safety_stop)
                                    except Exception:
                                        _safety_stop()
                            t = threading.Timer(MAX_RECORD_SECS, _safety_timeout)
                            t.daemon = True
                            t.start()
                    else:  # kCGEventKeyUp
                        wait_for_up["active"] = False  # real key-up clears the lock
                        if pressed["down"]:
                            pressed["down"] = False
                            app._stop_and_transcribe()
                    # Suppress by converting to a null event type.
                    # NEVER return None — PyObjC bridges that to NULL
                    # which segfaults CoreGraphics.
                    try:
                        Quartz.CGEventSetType(event, kCGEventNull)
                    except Exception:
                        pass  # if SetType fails, event passes through unsuppressed
                    return event

                # Also check for modifier-only key-up (user released modifier
                # before releasing the trigger key).  If our hotkey modifier
                # is no longer held, treat it as a release.
                if pressed["down"] and (mods & mod_mask) != mod_mask:
                    pressed["down"] = False
                    app._stop_and_transcribe()

            except Exception as e:
                log.error(f"CGEventTap callback error: {e}")
            return event  # pass through everything else

        # Keep reference to prevent garbage collection
        self._tap_callback_ref = _tap_cb

        event_mask = (
            Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown)
            | Quartz.CGEventMaskBit(Quartz.kCGEventKeyUp)
        )
        tap = Quartz.CGEventTapCreate(
            Quartz.kCGHIDEventTap,
            Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionDefault,
            event_mask,
            _tap_cb,
            None,
        )
        if tap is None:
            log.error(
                "CGEventTapCreate returned None — "
                "Accessibility permission probably not granted. "
                "Check System Settings → Privacy & Security → Accessibility"
            )
            return False

        self._event_tap = tap

        source = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
        if source is None:
            log.error("CFMachPortCreateRunLoopSource returned None")
            try:
                Quartz.CGEventTapEnable(tap, False)
            except Exception:
                pass
            self._event_tap = None
            return False

        self._event_tap_source = source
        main_loop = Quartz.CFRunLoopGetMain()
        Quartz.CFRunLoopAddSource(main_loop, source, Quartz.kCFRunLoopCommonModes)
        Quartz.CGEventTapEnable(tap, True)

        log.info("CGEventTap hotkey registered (Quartz) — key events will be suppressed")
        return True

    # ── pynput fallback (toggle mode / no Accessibility) ─────────────────

    def _register_hotkey_pynput(self):
        """Fallback: use pynput for toggle mode or when CGEventTap fails."""
        from pynput import keyboard

        key_map = {
            "option": "<alt>", "alt": "<alt>", "ctrl": "<ctrl>",
            "control": "<ctrl>", "cmd": "<cmd>", "command": "<cmd>",
            "shift": "<shift>", "space": "<space>",
            **{f"f{i}": f"<f{i}>" for i in range(1, 13)},
        }
        parts = [p.strip().lower() for p in self.config["hotkey"].split("+")]
        combo = "+".join(key_map.get(p, p) for p in parts)

        if self.config["mode"] == "toggle":
            def on_activate():
                if self.recording:
                    self._stop_and_transcribe()
                else:
                    self._start_recording()
            self._hotkey_listener = keyboard.GlobalHotKeys({combo: on_activate})
        else:
            # push-to-talk via pynput (characters will leak through)
            parsed = keyboard.HotKey.parse(combo)
            modifier_keys = {k for k in parsed if isinstance(k, keyboard.Key)}
            trigger_key = next((k for k in parsed if not isinstance(k, keyboard.Key)), parsed[-1] if parsed else None)
            held = set()
            pressed = {"down": False}

            def on_press(key):
                try:
                    ck = self._canonical_key(key)
                    if ck in modifier_keys:
                        held.add(ck)
                except Exception:
                    pass
                if pressed["down"]:
                    return
                try:
                    if self._trigger_matches(key, trigger_key) and modifier_keys.issubset(held):
                        pressed["down"] = True
                        self._start_recording()
                except Exception:
                    pass

            def on_release(key):
                try:
                    ck = self._canonical_key(key)
                    held.discard(ck)
                except Exception:
                    pass
                if not pressed["down"]:
                    return
                try:
                    if self._trigger_matches(key, trigger_key) or self._canonical_key(key) in modifier_keys:
                        pressed["down"] = False
                        self._stop_and_transcribe()
                except Exception:
                    pass

            self._hotkey_listener = keyboard.Listener(on_press=on_press, on_release=on_release)

        self._hotkey_listener.daemon = True
        self._hotkey_listener.start()
        log.info(f"pynput hotkey registered: {combo}")

    @staticmethod
    def _canonical_key(key):
        """Normalize left/right modifier variants to canonical Key enum."""
        from pynput import keyboard
        if key in (keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r, keyboard.Key.alt_gr):
            return keyboard.Key.alt
        if key in (keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r):
            return keyboard.Key.ctrl
        if key in (keyboard.Key.cmd, keyboard.Key.cmd_l, keyboard.Key.cmd_r):
            return keyboard.Key.cmd
        if key in (keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r):
            return keyboard.Key.shift
        return key

    @staticmethod
    def _trigger_matches(key, trigger):
        """Check if a key event matches the trigger (vk-based for macOS)."""
        if key == trigger:
            return True
        def _vk(k):
            v = getattr(k, 'vk', None)
            if v is not None:
                return v
            val = getattr(k, 'value', None)
            return getattr(val, 'vk', None) if val else None
        a, b = _vk(key), _vk(trigger)
        if a is not None and b is not None:
            return a == b
        if hasattr(key, 'char') and hasattr(trigger, 'char'):
            return key.char == trigger.char
        return False

    # ── Recording ────────────────────────────────────────────────────────────

    _transcribing = False  # guard against overlapping transcriptions

    def _start_recording(self):
        if not self.model_loaded:
            self._notify("myScriber", "Model still loading — please wait.")
            return
        if self._transcribing:
            log.info("Transcription in progress — ignoring new recording request")
            self._notify("myScriber", "Still transcribing — please wait.")
            return
        self.recording    = True
        self.audio_frames = []
        self._last_vol_level = -1

        # Show blue mic at level 0 (outline only = "listening, no sound yet")
        self.title = ""  # clear text title
        try:
            from PyObjCTools import AppHelper
            AppHelper.callAfter(lambda: self._set_volume_icon(0))
        except Exception:
            pass

        # If overlay is open, update hint to show recording state
        if self._overlay_panel:
            self._overlay_set_recording(True)

        app = self
        try:
            from PyObjCTools import AppHelper as _AH
        except ImportError:
            _AH = None

        def callback(indata, frames, time_info, status):
            if not app.recording:
                return
            app.audio_frames.append(indata.copy())

            # Compute RMS volume and update blue fill level
            if _AH and app._volume_icons:
                try:
                    rms = float(np.sqrt(np.mean(indata ** 2)))
                    if rms > 0.002:
                        # Logarithmic (dB) scale — matches human volume perception
                        # Maps ~-54 dB to ~-14 dB onto levels 1-5
                        db = 20.0 * math.log10(rms)
                        level = max(1, min(int((db + 54) / 8), 5))
                    else:
                        level = 0
                    if level != app._last_vol_level:
                        app._last_vol_level = level
                        _AH.callAfter(lambda l=level: app._set_volume_icon(l))
                except Exception:
                    pass

        self.stream = sd.InputStream(
            samplerate=SAMPLE_RATE, channels=CHANNELS,
            dtype="float32", callback=callback,
        )
        self.stream.start()

    def _stop_and_transcribe(self):
        if not self.recording:
            return
        self.recording = False
        self._last_vol_level = -1
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None

        # Restore normal template icon and show "transcribing" indicator
        try:
            from PyObjCTools import AppHelper
            AppHelper.callAfter(self._restore_template_icon)
        except Exception:
            pass
        self.title = ""

        # If overlay is open, update hint back to idle
        if self._overlay_panel:
            self._overlay_set_recording(False)

        def _transcribe():
            self._transcribing = True
            tmp = None
            try:
                if not self.audio_frames:
                    self.title = ""
                    return

                audio = np.concatenate(self.audio_frames, axis=0).flatten()
                self.audio_frames = []  # free memory early

                lang = None if self.config.get("language") == "auto" else self.config["language"]

                if USE_MLX:
                    # mlx_whisper can take a numpy array directly (no ffmpeg needed)
                    kwargs = {"path_or_hf_repo": self.whisper_model}
                    if lang:
                        kwargs["language"] = lang
                    try:
                        result = mlx_whisper.transcribe(audio, **kwargs)
                    except (TypeError, Exception) as e:
                        # Fallback: some versions need a file path
                        log.info(f"mlx_whisper numpy failed ({e}), trying wav file")
                        tmp = self._write_wav(audio)
                        result = mlx_whisper.transcribe(tmp, **kwargs)
                else:
                    # openai-whisper: try numpy first, fall back to wav file
                    try:
                        result = self.whisper_model.transcribe(audio, language=lang, fp16=False)
                    except (TypeError, Exception) as e:
                        log.info(f"whisper numpy failed ({e}), trying wav file")
                        tmp = self._write_wav(audio)
                        result = self.whisper_model.transcribe(tmp, language=lang, fp16=False)

                text = result["text"].strip()

                if text:
                    # Deliver on main thread — AX API + AppKit must run there
                    from PyObjCTools import AppHelper
                    AppHelper.callAfter(lambda t=text: self._deliver_text(t))
                self._set_title("")
            except Exception as e:
                log.error(f"Transcription error: {e}")
            finally:
                self._transcribing = False
                self._set_title("")
                if tmp:
                    try:
                        os.unlink(tmp)
                    except Exception:
                        pass

        threading.Thread(target=_transcribe, daemon=True).start()

    def _write_wav(self, audio):
        """Write float32 audio numpy array to a temporary .wav file."""
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            tmp = f.name
        with wave.open(tmp, "wb") as wf:
            wf.setnchannels(CHANNELS)
            wf.setsampwidth(2)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes((audio * 32767).astype(np.int16).tobytes())
        return tmp

    def _set_title(self, text):
        """Thread-safe status item title update via main thread."""
        try:
            from PyObjCTools import AppHelper
            AppHelper.callAfter(lambda: setattr(self, 'title', text))
        except Exception:
            self.title = text

    def _set_status(self, text):
        """Thread-safe update of the status menu item (in the dropdown menu)."""
        try:
            from PyObjCTools import AppHelper
            AppHelper.callAfter(lambda: setattr(self.status_item, 'title', text))
        except Exception:
            self.status_item.title = text

    # ── Smart paste / overlay ────────────────────────────────────────────────

    def _deliver_text(self, text):
        """Paste text directly if focused element is editable, else show overlay.
        If overlay is already open, append new text there instead."""
        try:
            # If overlay is already open, always append there
            if self._overlay_panel and self._overlay_panel.isVisible():
                log.info("Overlay open — appending new transcription")
                self._show_overlay(text)
                return

            editable = False
            try:
                editable = self._focused_element_is_editable()
            except Exception as e:
                log.warning(f"Editable check failed: {e} — will show overlay")

            if editable:
                log.info("Editable field focused — pasting directly")
                self._paste_to_cursor(text)
            else:
                log.info("No editable field — showing overlay")
                self._show_overlay(text)
        except Exception as e:
            log.error(f"Deliver text error: {e} — falling back to overlay")
            try:
                self._show_overlay(text)
            except Exception:
                # Last resort: clipboard
                try:
                    proc = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
                    proc.communicate(text.encode("utf-8"))
                    self._notify("myScriber", "Copied to clipboard!")
                except Exception:
                    pass

    @staticmethod
    def _focused_element_is_editable():
        """Use macOS Accessibility API to check if the focused UI element is a text field.

        Uses ctypes to call AX* functions directly, avoiding the need for
        pyobjc-framework-ApplicationServices.

        Checks multiple signals:
        1. AXRole (AXTextField, AXTextArea, etc.)
        2. AXSubrole (AXContentEditable — used by Electron apps like Claude)
        3. AXSelectedText attribute existence (definitive text-editing marker)
        4. AXValue settable (writable means editable)
        """
        try:
            import ctypes
            from AppKit import NSWorkspace
            import objc

            # Load HIServices (contains AX* functions)
            hi = ctypes.cdll.LoadLibrary(
                "/System/Library/Frameworks/ApplicationServices.framework"
                "/Frameworks/HIServices.framework/HIServices"
            )
            cf = ctypes.cdll.LoadLibrary(
                "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
            )

            hi.AXUIElementCreateApplication.restype = ctypes.c_void_p
            hi.AXUIElementCreateApplication.argtypes = [ctypes.c_int32]

            hi.AXUIElementCopyAttributeValue.restype = ctypes.c_int32
            hi.AXUIElementCopyAttributeValue.argtypes = [
                ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
            ]

            hi.AXUIElementIsAttributeSettable.restype = ctypes.c_int32
            hi.AXUIElementIsAttributeSettable.argtypes = [
                ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_bool),
            ]

            cf.CFStringCreateWithCString.restype = ctypes.c_void_p
            cf.CFStringCreateWithCString.argtypes = [
                ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32,
            ]
            kCFStringEncodingUTF8 = 0x08000100

            cf.CFGetTypeID.restype = ctypes.c_ulong
            cf.CFGetTypeID.argtypes = [ctypes.c_void_p]
            cf.CFStringGetTypeID.restype = ctypes.c_ulong
            cf.CFStringGetCStringPtr.restype = ctypes.c_char_p
            cf.CFStringGetCStringPtr.argtypes = [ctypes.c_void_p, ctypes.c_uint32]

            def _cfstr(s):
                return cf.CFStringCreateWithCString(None, s.encode(), kCFStringEncodingUTF8)

            def _read_cfstr(ptr):
                if not ptr:
                    return None
                p = cf.CFStringGetCStringPtr(ptr, kCFStringEncodingUTF8)
                return p.decode() if p else None

            # Get front application PID
            front_app = NSWorkspace.sharedWorkspace().frontmostApplication()
            if not front_app:
                return False
            pid = front_app.processIdentifier()

            app_ref = hi.AXUIElementCreateApplication(pid)
            if not app_ref:
                return False

            # Get focused element
            focused = ctypes.c_void_p()
            attr_focus = _cfstr("AXFocusedUIElement")
            err = hi.AXUIElementCopyAttributeValue(app_ref, attr_focus, ctypes.byref(focused))
            if err != 0 or not focused.value:
                return False

            # ── Check 1: AXRole ──
            role_ptr = ctypes.c_void_p()
            attr_role = _cfstr("AXRole")
            err = hi.AXUIElementCopyAttributeValue(focused, attr_role, ctypes.byref(role_ptr))
            role = _read_cfstr(role_ptr.value) if (err == 0 and role_ptr.value) else None

            editable_roles = {
                "AXTextField", "AXTextArea", "AXComboBox",
                "AXSearchField", "AXWebArea",
            }
            if role in editable_roles:
                return True

            # ── Check 2: AXSubrole (catches contenteditable in Electron/web apps) ──
            subrole_ptr = ctypes.c_void_p()
            attr_subrole = _cfstr("AXSubrole")
            err = hi.AXUIElementCopyAttributeValue(focused, attr_subrole, ctypes.byref(subrole_ptr))
            if err == 0 and subrole_ptr.value:
                subrole = _read_cfstr(subrole_ptr.value)
                if subrole in ("AXContentEditable", "AXTextEntry"):
                    return True

            # ── Check 3: AXSelectedText attribute exists (text-editing marker) ──
            selected_ptr = ctypes.c_void_p()
            attr_sel = _cfstr("AXSelectedText")
            err = hi.AXUIElementCopyAttributeValue(focused, attr_sel, ctypes.byref(selected_ptr))
            if err == 0:
                # If we can read AXSelectedText at all, it's a text editing context
                return True

            # ── Check 4: AXValue is settable (writable = editable) ──
            attr_value = _cfstr("AXValue")
            writable = ctypes.c_bool(False)
            err = hi.AXUIElementIsAttributeSettable(
                focused, attr_value, ctypes.byref(writable)
            )
            if err == 0 and writable.value:
                return True

            # ── Check 5: AXInsertionPointLineNumber exists (another text marker) ──
            line_ptr = ctypes.c_void_p()
            attr_line = _cfstr("AXInsertionPointLineNumber")
            err = hi.AXUIElementCopyAttributeValue(focused, attr_line, ctypes.byref(line_ptr))
            if err == 0:
                return True

            # ── Check 6: Walk up the AXParent chain (up to 6 levels) ──
            # Electron/web apps often focus a child element (AXGroup, AXStaticText)
            # inside the actual editable container.  Walk up to find it.
            attr_parent = _cfstr("AXParent")
            current = focused.value
            for _ in range(6):
                parent_ptr = ctypes.c_void_p()
                err = hi.AXUIElementCopyAttributeValue(
                    current, attr_parent, ctypes.byref(parent_ptr)
                )
                if err != 0 or not parent_ptr.value:
                    break
                current = parent_ptr.value

                # Check parent role
                p_role_ptr = ctypes.c_void_p()
                err = hi.AXUIElementCopyAttributeValue(
                    current, attr_role, ctypes.byref(p_role_ptr)
                )
                if err == 0 and p_role_ptr.value:
                    p_role = _read_cfstr(p_role_ptr.value)
                    if p_role in editable_roles:
                        return True

                # Check parent subrole
                p_sub_ptr = ctypes.c_void_p()
                err = hi.AXUIElementCopyAttributeValue(
                    current, attr_subrole, ctypes.byref(p_sub_ptr)
                )
                if err == 0 and p_sub_ptr.value:
                    p_sub = _read_cfstr(p_sub_ptr.value)
                    if p_sub in ("AXContentEditable", "AXTextEntry"):
                        return True

                # Check parent for AXSelectedText
                p_sel_ptr = ctypes.c_void_p()
                err = hi.AXUIElementCopyAttributeValue(
                    current, attr_sel, ctypes.byref(p_sel_ptr)
                )
                if err == 0:
                    return True

            # ── Check 7: Electron/browser app heuristic ──
            # If the frontmost app is a known Electron or browser app,
            # Cmd+V paste is safe to attempt (worst case: nothing happens).
            bundle_id = front_app.bundleIdentifier() or ""
            electron_ids = {
                "com.anthropic.claudedesktop",   # Claude Desktop
                "com.electron.",                  # generic Electron prefix
                "com.microsoft.VSCode",
                "com.hnc.Discord",
                "com.slack.Slack",
                "com.spotify.client",
                "com.figma.Desktop",
                "com.notion.id",
                "com.linear",
            }
            # Check exact match or prefix match
            for eid in electron_ids:
                if bundle_id == eid or bundle_id.startswith(eid):
                    log.info(f"Electron/browser heuristic match: {bundle_id}")
                    return True

            # Also check if the app's executable contains "Electron" or "electron"
            try:
                exe_url = front_app.executableURL()
                if exe_url:
                    exe_path = exe_url.path()
                    if exe_path and ("Electron" in exe_path or "electron" in exe_path):
                        log.info(f"Electron executable detected: {exe_path}")
                        return True
            except Exception:
                pass

            return False
        except Exception as e:
            log.warning(f"Could not check focused element: {e}")
            return False  # default to overlay on error

    def _paste_to_cursor(self, text):
        """Copy text to clipboard and Cmd+V paste into the active field."""
        proc = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
        proc.communicate(text.encode("utf-8"))
        time.sleep(0.15)
        subprocess.run(
            ["osascript", "-e",
             'tell application "System Events" to keystroke "v" using command down'],
            capture_output=True,
        )

    # ── Overlay panel (persistent, supports re-dictation) ──────────────────

    _overlay_panel = None       # the floating NSPanel
    _overlay_text_view = None   # the NSTextView inside it
    _overlay_hint = None        # hint label (updates during recording)

    def _show_overlay(self, text):
        """Show or update the floating transcription panel.

        If the panel is already open, appends new text at the cursor.
        If not, creates a new panel.  The panel is non-modal so the
        hotkey keeps working — hold to dictate again, release to append.
        """
        from PyObjCTools import AppHelper

        def _on_main():
            if self._overlay_panel and self._overlay_panel.isVisible():
                # Panel already open — append at cursor position
                tv = self._overlay_text_view
                if tv:
                    sel = tv.selectedRange()
                    current = tv.string()
                    # Add a space before appending if needed
                    insert = text
                    if sel.location > 0 and sel.location <= len(current):
                        ch_before = current[sel.location - 1]
                        if ch_before not in (" ", "\n", "\t"):
                            insert = " " + insert
                    tv.insertText_(insert)
                    tv.scrollRangeToVisible_(tv.selectedRange())
                return
            # Create new panel
            self._create_overlay_panel(text)

        AppHelper.callAfter(_on_main)

    def _create_overlay_panel(self, text):
        """Build and show the floating transcription panel."""
        try:
            from AppKit import (
                NSPanel, NSView, NSTextField, NSTextView, NSScrollView,
                NSFont, NSColor, NSImageView, NSButton,
                NSMakeRect, NSMakeSize,
                NSApplication, NSScreen,
                NSWindowStyleMaskTitled, NSWindowStyleMaskClosable,
                NSWindowStyleMaskResizable,
                NSWindowStyleMaskFullSizeContentView,
                NSBackingStoreBuffered,
                NSBezelStyleRounded,
                NSImageScaleProportionallyDown,
                NSFloatingWindowLevel,
            )

            W, H = 500, 360
            PAD = 20

            screen = NSScreen.mainScreen().frame()
            x = (screen.size.width - W) / 2
            y = (screen.size.height - H) / 2

            panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
                NSMakeRect(x, y, W, H),
                NSWindowStyleMaskTitled
                | NSWindowStyleMaskClosable
                | NSWindowStyleMaskResizable
                | NSWindowStyleMaskFullSizeContentView,
                NSBackingStoreBuffered,
                False,
            )
            panel.setTitle_("myScriber")
            panel.setTitlebarAppearsTransparent_(True)
            panel.setTitleVisibility_(1)  # NSWindowTitleHidden
            panel.setLevel_(NSFloatingWindowLevel)
            panel.setMovableByWindowBackground_(True)
            panel.setMinSize_(NSMakeSize(360, 240))
            # Keep panel visible even when user clicks other apps
            panel.setHidesOnDeactivate_(False)
            # Non-activating so hotkey still works while panel is showing
            panel.setBecomesKeyOnlyIfNeeded_(True)

            # Round corners
            panel.contentView().setWantsLayer_(True)
            panel.contentView().layer().setCornerRadius_(14)
            panel.contentView().layer().setMasksToBounds_(True)

            bg = panel.contentView()

            # ── Icon + Title row ──
            # Offset below the titlebar (traffic light buttons are ~28px tall)
            icon_size = 32
            row_y = H - 72
            if self._app_icon_image:
                icon_view = NSImageView.alloc().initWithFrame_(
                    NSMakeRect(PAD, row_y, icon_size, icon_size)
                )
                icon_view.setImage_(self._app_icon_image)
                icon_view.setImageScaling_(NSImageScaleProportionallyDown)
                bg.addSubview_(icon_view)

            title_x = PAD + icon_size + 10
            title = NSTextField.alloc().initWithFrame_(
                NSMakeRect(title_x, row_y + 7, 200, 20)
            )
            title.setStringValue_("myScriber")
            title.setFont_(NSFont.boldSystemFontOfSize_(15))
            title.setBezeled_(False)
            title.setDrawsBackground_(False)
            title.setEditable_(False)
            title.setSelectable_(False)
            bg.addSubview_(title)

            # ── Hint label (changes to "Recording..." during dictation) ──
            hint = NSTextField.alloc().initWithFrame_(
                NSMakeRect(PAD, row_y - 20, W - PAD * 2, 16)
            )
            hint.setStringValue_(f"Hold {self._pretty_hotkey()} to dictate more  ·  Edit below")
            hint.setFont_(NSFont.systemFontOfSize_(11))
            hint.setTextColor_(NSColor.secondaryLabelColor())
            hint.setBezeled_(False)
            hint.setDrawsBackground_(False)
            hint.setEditable_(False)
            hint.setSelectable_(False)
            bg.addSubview_(hint)
            self._overlay_hint = hint

            # ── Separator ──
            sep_y = row_y - 32
            sep = NSView.alloc().initWithFrame_(NSMakeRect(PAD, sep_y, W - PAD * 2, 1))
            sep.setWantsLayer_(True)
            sep.layer().setBackgroundColor_(NSColor.separatorColor().CGColor())
            bg.addSubview_(sep)

            # ── Text area ──
            text_h = sep_y - 56  # room for buttons
            scroll = NSScrollView.alloc().initWithFrame_(
                NSMakeRect(PAD, 52, W - PAD * 2, text_h)
            )
            scroll.setHasVerticalScroller_(True)
            scroll.setBorderType_(0)
            scroll.setDrawsBackground_(False)
            scroll.setAutoresizingMask_(2 | 16)  # width + height flexible

            cs = scroll.contentSize()
            tv = NSTextView.alloc().initWithFrame_(
                NSMakeRect(0, 0, cs.width, cs.height)
            )
            tv.setFont_(NSFont.systemFontOfSize_(14))
            tv.setTextColor_(NSColor.labelColor())
            tv.setString_(text)
            tv.setEditable_(True)
            tv.setSelectable_(True)
            tv.setRichText_(False)
            tv.setDrawsBackground_(False)
            tv.setTextContainerInset_(NSMakeSize(4, 6))
            tv.setVerticallyResizable_(True)
            tv.setHorizontallyResizable_(False)
            tv.textContainer().setWidthTracksTextView_(True)
            scroll.setDocumentView_(tv)
            bg.addSubview_(scroll)
            self._overlay_text_view = tv

            # Move cursor to end
            tv.setSelectedRange_((len(text), 0))

            # ── Buttons ──
            btn_y = 14
            btn_h = 30

            # Close (left)
            close_btn = NSButton.alloc().initWithFrame_(
                NSMakeRect(PAD, btn_y, 80, btn_h)
            )
            close_btn.setTitle_("Close")
            close_btn.setBezelStyle_(NSBezelStyleRounded)
            close_btn.setFont_(NSFont.systemFontOfSize_(13))
            bg.addSubview_(close_btn)

            # Copy to Clipboard (right, primary — copies and closes)
            copy_btn = NSButton.alloc().initWithFrame_(
                NSMakeRect(W - PAD - 160, btn_y, 160, btn_h)
            )
            copy_btn.setTitle_("Copy to Clipboard")
            copy_btn.setBezelStyle_(NSBezelStyleRounded)
            copy_btn.setFont_(NSFont.boldSystemFontOfSize_(13))
            copy_btn.setKeyEquivalent_("\r")  # Enter key
            bg.addSubview_(copy_btn)

            # Wire button actions using block-based approach
            def _do_close(_=None):
                self._close_overlay()

            def _do_copy(_=None):
                edited = tv.string().strip()
                if edited:
                    proc = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
                    proc.communicate(edited.encode("utf-8"))
                    self._notify("myScriber", "Copied to clipboard!")
                self._close_overlay()

            # Use module-level _OverlayBtnHelper (defined once to avoid
            # PyObjC crash from re-registering the same ObjC class name)
            helper = _OverlayBtnHelper.alloc().init()
            helper.setup(_do_close, _do_copy)
            self._overlay_btn_helper = helper  # prevent GC

            close_btn.setTarget_(helper)
            close_btn.setAction_(b'doClose:')
            copy_btn.setTarget_(helper)
            copy_btn.setAction_(b'doCopy:')

            # ── Show ──
            self._overlay_panel = panel
            panel.makeKeyAndOrderFront_(None)
            NSApplication.sharedApplication().activateIgnoringOtherApps_(True)

        except Exception as e:
            log.error(f"Overlay panel failed: {e}")
            # Fallback: copy to clipboard
            proc = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
            proc.communicate(text.encode("utf-8"))
            self._notify("myScriber", f"Copied: {text[:60]}…")

    def _close_overlay(self):
        """Dismiss the overlay panel."""
        if self._overlay_panel:
            self._overlay_panel.orderOut_(None)
            self._overlay_panel = None
        self._overlay_text_view = None
        self._overlay_hint = None
        self._overlay_btn_helper = None

    def _overlay_set_recording(self, is_recording):
        """Update the overlay hint to show recording state."""
        if self._overlay_hint:
            try:
                from PyObjCTools import AppHelper
                if is_recording:
                    AppHelper.callAfter(
                        lambda: self._overlay_hint.setStringValue_("Recording…")
                    )
                else:
                    AppHelper.callAfter(
                        lambda: self._overlay_hint.setStringValue_(
                            f"Hold {self._pretty_hotkey()} to dictate more  ·  Edit below"
                        )
                    )
            except Exception:
                pass

    # ── Hotkey learning ────────────────────────────────────────────────────

    # Reverse maps: keycode → name, flag → name (for display)
    _KEYCODE_NAMES = {v: k for k, v in _KEYCODES.items()}
    _MOD_SYMBOLS = {
        0x00100000: "\u2318",   # Cmd ⌘
        0x00080000: "\u2325",   # Option ⌥
        0x00040000: "\u2303",   # Ctrl ⌃
        0x00020000: "\u21E7",   # Shift ⇧
    }
    _MOD_NAMES = {
        0x00100000: "cmd",
        0x00080000: "option",
        0x00040000: "ctrl",
        0x00020000: "shift",
    }

    def _pretty_hotkey(self):
        """Return a human-readable display string for the current hotkey."""
        parts = [p.strip().lower() for p in self.config["hotkey"].split("+")]
        symbols = {
            "cmd": "\u2318", "command": "\u2318",
            "option": "\u2325", "alt": "\u2325",
            "ctrl": "\u2303", "control": "\u2303",
            "shift": "\u21E7",
        }
        display = []
        for p in parts:
            if p in symbols:
                display.append(symbols[p])
            else:
                display.append(p.upper() if len(p) == 1 else p.capitalize())
        return "".join(display)

    def _learn_hotkey(self, _):
        """Listen for a key combo press and set it as the new hotkey.

        Uses a single synchronous dialog with an NSEvent monitor running
        behind it.  The monitor captures key combos while the dialog is
        open (modal NSAlert still pumps the event loop).  When the user
        clicks Done/Cancel, the monitor is removed and everything is
        handled in one clean call — no async callAfter chains.
        """
        log.info("Hotkey learning: starting")

        # Pause the live hotkey tap so it doesn't interfere
        self._stop_hotkey()

        # Try the NSEvent-based approach
        if not self._learn_hotkey_nsevent():
            log.warning("NSEvent learning failed — falling back to text input")
            self._learn_hotkey_text_fallback()

    def _learn_hotkey_nsevent(self):
        """Capture a hotkey combo using NSEvent monitors.

        Flow:
        1. Install local + global NSEvent monitors (no dialog blocking)
        2. Show a macOS notification: "Press your hotkey now…"
        3. First valid modifier+key combo captured → remove monitors
        4. Show a confirmation dialog (after capture, not during)
        5. On confirm: save + re-register.  On cancel: re-register old.
        """
        try:
            from AppKit import NSEvent
            from PyObjCTools import AppHelper
        except ImportError:
            log.error("AppKit not available")
            return False

        app = self
        state = {"done": False}
        monitors = {"local": None, "global": None}

        NSKeyDownMask = 1 << 10

        def _remove_monitors():
            for key in ("local", "global"):
                if monitors[key]:
                    try:
                        NSEvent.removeMonitor_(monitors[key])
                    except Exception:
                        pass
                    monitors[key] = None

        def _process_event(event):
            """Extract modifier+key; on valid combo, tear down and confirm."""
            if state["done"]:
                return
            try:
                keycode = event.keyCode()
                flags = event.modifierFlags()

                mods = []
                if flags & (1 << 20):
                    mods.append("cmd")
                if flags & (1 << 19):
                    mods.append("option")
                if flags & (1 << 18):
                    mods.append("ctrl")
                if flags & (1 << 17):
                    mods.append("shift")

                key_name = app._KEYCODE_NAMES.get(keycode)
                if not key_name or not mods:
                    return  # need at least one modifier + a key

                state["done"] = True
                _remove_monitors()

                config_str = "+".join(mods + [key_name])
                display_str = app._pretty_hotkey_from(config_str)
                log.info(f"Hotkey learning captured: {config_str} ({display_str})")

                # Show confirmation on main thread (safe — monitors are gone)
                def _confirm():
                    try:
                        clicked, _ = app._branded_alert(
                            title="myScriber \u2014 Confirm Hotkey",
                            message=f"Detected:  {display_str}\n\nUse this as your hotkey?",
                            ok="Use This Hotkey",
                            cancel="Cancel",
                        )
                        if clicked:
                            log.info(f"New hotkey set: {config_str} ({display_str})")
                            app.config["hotkey"] = config_str
                            save_config(app.config)
                            app.hotkey_display.title = f"Hotkey: {display_str}"
                            app._notify("myScriber", f"Hotkey set to {display_str}")
                    except Exception as e:
                        log.error(f"Hotkey confirm error: {e}")
                    # Always re-register (new or old hotkey)
                    try:
                        app._register_hotkey()
                    except Exception as e:
                        log.error(f"Hotkey re-register error: {e}")
                        try:
                            app._register_hotkey_pynput()
                        except Exception:
                            pass

                AppHelper.callAfter(_confirm)

            except Exception as e:
                log.error(f"Hotkey learning handler error: {e}")

        def _local_handler(event):
            _process_event(event)
            return event  # must return event for local monitors

        def _global_handler(event):
            _process_event(event)

        # Install both monitors
        try:
            monitors["local"] = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
                NSKeyDownMask, _local_handler
            )
            monitors["global"] = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
                NSKeyDownMask, _global_handler
            )
        except Exception as e:
            log.error(f"Failed to install NSEvent monitors: {e}")
            _remove_monitors()
            return False

        if not monitors["local"] and not monitors["global"]:
            log.error("Both NSEvent monitors returned None")
            return False

        # Prevent GC
        self._learn_refs = (_local_handler, _global_handler)

        # Timeout: clean up after 15 seconds if no combo pressed
        def _timeout():
            def _on_main():
                if not state["done"]:
                    state["done"] = True
                    _remove_monitors()
                    log.info("Hotkey learning timed out")
                    app._notify("myScriber", "Hotkey learning timed out. Try again.")
                    try:
                        app._register_hotkey()
                    except Exception:
                        try:
                            app._register_hotkey_pynput()
                        except Exception:
                            pass
            AppHelper.callAfter(_on_main)

        timer = threading.Timer(15.0, _timeout)
        timer.daemon = True
        timer.start()

        self._notify(
            "myScriber",
            "Press your desired hotkey combination now\u2026"
        )
        log.info("Hotkey learning: monitors active, waiting for key combo")
        return True

    def _learn_hotkey_text_fallback(self):
        """Fallback: text-input dialog for setting hotkey manually."""
        valid_mods = {"cmd", "command", "option", "alt", "ctrl", "control", "shift"}
        valid_keys = set(self._KEYCODES.keys())
        current = self.config["hotkey"]

        clicked, raw_text = self._branded_alert(
            title="myScriber \u2014 Set Hotkey",
            message=(
                "Type your hotkey combo using + to separate parts.\n\n"
                "Modifiers: cmd, option, ctrl, shift\n"
                "Keys: a-z, f1-f12, space, return, tab, escape\n\n"
                "Examples:  cmd+l   option+space   ctrl+shift+r"
            ),
            ok="Set Hotkey",
            cancel="Cancel",
            dimensions=(340, 24),
            default_text=current,
        )

        if not clicked:
            self._register_hotkey()
            return

        raw = raw_text.strip().lower()
        if not raw:
            self._notify("myScriber", "No hotkey entered.")
            self._register_hotkey()
            return

        parts = [p.strip() for p in raw.split("+")]
        mods = []
        trigger = None
        for p in parts:
            if p in valid_mods:
                if p == "command": p = "cmd"
                elif p == "alt": p = "option"
                elif p == "control": p = "ctrl"
                mods.append(p)
            elif p in valid_keys:
                trigger = p
            else:
                self._notify("myScriber", f"Unknown key: '{p}'.")
                self._register_hotkey()
                return

        if trigger is None:
            self._notify("myScriber", "Need a trigger key (not just modifiers).")
            self._register_hotkey()
            return

        config_str = "+".join(mods + [trigger])
        display_str = self._pretty_hotkey_from(config_str)
        self.config["hotkey"] = config_str
        save_config(self.config)
        self.hotkey_display.title = f"Hotkey: {display_str}"
        self._register_hotkey()
        self._notify("myScriber", f"Hotkey set to {display_str}")

    def _pretty_hotkey_from(self, hotkey_str):
        """Return a symbol-rich display string from a config hotkey string."""
        parts = [p.strip().lower() for p in hotkey_str.split("+")]
        symbols = {
            "cmd": "\u2318", "command": "\u2318",
            "option": "\u2325", "alt": "\u2325",
            "ctrl": "\u2303", "control": "\u2303",
            "shift": "\u21E7",
        }
        display = []
        for p in parts:
            if p in symbols:
                display.append(symbols[p])
            else:
                display.append(p.upper() if len(p) == 1 else p.capitalize())
        return "".join(display)

    # ── Menu callbacks ───────────────────────────────────────────────────────

    def _toggle_mode(self, _):
        new = "toggle" if self.config["mode"] == "push_to_talk" else "push_to_talk"
        self.config["mode"] = new
        self.mode_item.title = "Mode: Push-to-talk" if new == "push_to_talk" else "Mode: Toggle"
        save_config(self.config)
        self._stop_hotkey()
        self._register_hotkey()

    def _make_model_setter(self, model_name):
        def _set(_):
            if self.config["model"] == model_name:
                return
            self.config["model"] = model_name
            save_config(self.config)
            for item in self.model_menu.values():
                raw = item.title.lstrip("✓ ").lstrip()
                item.title = ("✓ " if raw == model_name else "    ") + raw
            self.model_loaded  = False
            self.whisper_model = None
            self._load_model_async()
        return _set

    # ── Update checker ───────────────────────────────────────────────────────

    def _check_for_updates(self, _):
        """Check GitHub Releases for a newer version."""
        def _check():
            try:
                import urllib.request, json as _json
                req = urllib.request.Request(
                    UPDATE_URL,
                    headers={"Accept": "application/vnd.github.v3+json",
                             "User-Agent": "myScriber-updater"},
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = _json.loads(resp.read().decode())

                remote_tag = data.get("tag_name", "").lstrip("v")
                if not remote_tag:
                    self._notify("myScriber", "Could not determine latest version.")
                    return

                # Compare versions (simple tuple comparison)
                def ver(s):
                    return tuple(int(x) for x in s.split("."))

                if ver(remote_tag) > ver(APP_VERSION):
                    # Newer version available
                    body = data.get("body", "")[:200]
                    dl_url = data.get("html_url", f"https://github.com/{GITHUB_REPO}/releases/latest")

                    from PyObjCTools import AppHelper
                    def _prompt():
                        result = subprocess.run(
                            ["osascript", "-e",
                             f'display dialog "myScriber {remote_tag} is available!'
                             f'\\n\\nYou have version {APP_VERSION}.'
                             f'\\n\\nWould you like to download the update?" '
                             f'buttons {{"Later", "Download"}} '
                             f'default button "Download" '
                             f'with title "myScriber Update"'],
                            capture_output=True,
                        )
                        if result.returncode == 0 and b"Download" in result.stdout:
                            subprocess.Popen(["open", dl_url])
                    AppHelper.callAfter(_prompt)
                else:
                    def _show_up_to_date():
                        subprocess.run(
                            ["osascript", "-e",
                             'display dialog "You are up to date!\\n\\n'
                             'myScriber version ' + APP_VERSION + ' is the latest." '
                             'buttons {"OK"} default button "OK" '
                             'with title "myScriber Update"'],
                            capture_output=True,
                        )
                    from PyObjCTools import AppHelper
                    AppHelper.callAfter(_show_up_to_date)

            except Exception as e:
                log.error(f"Update check failed: {e}")
                def _show_error():
                    subprocess.run(
                        ["osascript", "-e",
                         'display dialog "Could not check for updates.\\n\\n'
                         'The update server may not be configured yet.\\n\\n'
                         'You are running version ' + APP_VERSION + '." '
                         'buttons {"OK"} default button "OK" '
                         'with title "myScriber Update"'],
                        capture_output=True,
                    )
                from PyObjCTools import AppHelper
                AppHelper.callAfter(_show_error)

        threading.Thread(target=_check, daemon=True).start()

    def _uninstall(self, _):
        """Prompt to uninstall, then remove all files and quit."""
        result = subprocess.run(
            ["osascript", "-e",
             'display dialog "Uninstall myScriber?\\n\\nThis will remove the app, '
             'all models, and settings." buttons {"Cancel", "Uninstall"} '
             'default button "Cancel" cancel button "Cancel" '
             'with title "myScriber" with icon caution'],
            capture_output=True,
        )
        if result.returncode != 0:
            return

        self.recording = False
        if self.stream:
            self.stream.stop()
            self.stream.close()

        home = str(Path.home())
        script = (
            f'rm -rf "{home}/.myscriber" ; '
            f'rm -rf "/Applications/myScriber.app" ; '
            f'osascript -e \'tell application "System Events" to try\n'
            f'delete login item "myScriber"\nend try\' 2>/dev/null ; '
            f'osascript -e \'display dialog "myScriber has been uninstalled." '
            f'buttons {{"OK"}} default button "OK" with title "myScriber"\''
        )
        subprocess.Popen(["bash", "-c", script])
        rumps.quit_application()

    def _quit(self, _):
        if self.recording:
            self.recording = False
            if self.stream:
                self.stream.stop()
                self.stream.close()
        rumps.quit_application()


if __name__ == "__main__":
    # Hide Python from Dock — must happen after imports but before run()
    try:
        from AppKit import NSApplication
        NSApplication.sharedApplication().setActivationPolicy_(1)
    except Exception:
        pass

    MyScriber().run()
