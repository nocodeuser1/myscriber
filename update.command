#!/bin/bash
# Quick update — copies fixed app code to installed location without full reinstall.
# Double-click this file in Finder to run.

# Change to the directory where this script lives (so double-click works)
cd "$(dirname "$0")" || exit 1

set -e
SCRIPT_DIR="$(pwd)"
INSTALL_DIR="$HOME/.myscriber"

echo ""
echo "Updating myScriber..."

# Kill running instance
pkill -f "myscriber.py" 2>/dev/null || true
sleep 1

# Delete stale HuggingFace token
rm -f "$HOME/.cache/huggingface/token" 2>/dev/null

# Install pyobjc-framework-Quartz (needed for CGEventTap hotkey suppression)
echo "Installing Quartz framework binding..."
"$INSTALL_DIR/venv/bin/pip" install pyobjc-framework-Quartz --quiet 2>/dev/null && echo "✓ Quartz installed" || echo "⚠ Quartz install failed — hotkey suppression may not work"

# Copy updated app files
cp "$SCRIPT_DIR/app/myscriber.py" "$INSTALL_DIR/app/myscriber.py"
echo "✓ Updated myscriber.py"

# ── Generate and install app icons ──────────────────────────────────────
cp "$SCRIPT_DIR/app/make_icons.py" "$INSTALL_DIR/app/make_icons.py" 2>/dev/null

# Always regenerate icons to ensure they're up to date
echo "Generating app icons..."
"$INSTALL_DIR/venv/bin/python" "$INSTALL_DIR/app/make_icons.py" 2>/dev/null && echo "✓ Icon PNGs generated" || true

# Also copy pre-generated assets from repo
if [ -d "$SCRIPT_DIR/assets" ]; then
    mkdir -p "$INSTALL_DIR/assets"
    cp -R "$SCRIPT_DIR/assets/"* "$INSTALL_DIR/assets/" 2>/dev/null
fi

# Build .icns from iconset (macOS only — needed for notifications)
ICONSET="$INSTALL_DIR/assets/AppIcon.iconset"
ICNS="$INSTALL_DIR/assets/AppIcon.icns"
if [ -d "$ICONSET" ] && command -v iconutil &>/dev/null; then
    iconutil -c icns "$ICONSET" -o "$ICNS" 2>/dev/null && echo "✓ AppIcon.icns built" || true
fi

# Update the .app bundle icon so notifications show the correct logo
APP_BUNDLE="/Applications/myScriber.app"
if [ -f "$ICNS" ] && [ -d "$APP_BUNDLE" ]; then
    mkdir -p "$APP_BUNDLE/Contents/Resources"
    cp "$ICNS" "$APP_BUNDLE/Contents/Resources/AppIcon.icns"
    echo "✓ App bundle icon updated"
    # Touch the bundle so macOS refreshes its icon cache
    touch "$APP_BUNDLE"
elif [ -d "$ICONSET" ] && [ -d "$APP_BUNDLE" ]; then
    # No .icns but we have PNGs — copy the largest as a fallback
    mkdir -p "$APP_BUNDLE/Contents/Resources"
    LARGEST=$(ls -S "$ICONSET"/icon_*.png 2>/dev/null | head -1)
    if [ -n "$LARGEST" ]; then
        cp "$LARGEST" "$APP_BUNDLE/Contents/Resources/AppIcon.png"
        echo "✓ App bundle icon updated (PNG fallback)"
        touch "$APP_BUNDLE"
    fi
fi

# Ensure launcher script is correct and logs errors for debugging
LAUNCHER="$APP_BUNDLE/Contents/MacOS/myScriber"
if [ -f "$LAUNCHER" ]; then
    cat > "$LAUNCHER" << 'EXEC'
#!/bin/bash
source "$HOME/.myscriber/venv/bin/activate"
python "$HOME/.myscriber/app/myscriber.py" 2>>"$HOME/.myscriber/launch.log"
EXEC
    chmod +x "$LAUNCHER"
    echo "✓ Launcher script updated"
fi

# Update hotkey in config.json from old defaults to cmd+l
if [ -f "$INSTALL_DIR/config.json" ]; then
    python3 -c "
import json
with open('$INSTALL_DIR/config.json') as f:
    cfg = json.load(f)
old = cfg.get('hotkey', '')
if old in ('option+space', 'cmd+k'):
    cfg['hotkey'] = 'cmd+l'
    with open('$INSTALL_DIR/config.json', 'w') as f:
        json.dump(cfg, f, indent=2)
    print(f'✓ Hotkey updated: {old} → cmd+l')
else:
    print('✓ Hotkey unchanged: ' + old)
"
fi

# Push latest changes to GitHub
echo "Pushing to GitHub..."
git add -A && git commit -m "Update via update.command" 2>/dev/null || true
git push 2>/dev/null && echo "✓ Pushed to GitHub" || echo "⚠ Git push failed — you may need to push manually"

# Relaunch
echo "Launching myScriber..."
open /Applications/myScriber.app

echo ""
echo "Done! myScriber should appear in the menubar."
echo ""
echo "IMPORTANT: When the Accessibility permission prompt appears,"
echo "click 'Open System Settings', find myScriber, and toggle it ON."
echo "Without Accessibility, the hotkey cannot suppress key events."
echo ""
echo "Your hotkey is now Cmd+L (hold to record, release to transcribe)."
echo "Click 'Set Hotkey…' in the menubar menu to change it anytime."
echo ""
echo "You can close this window now."
echo ""
