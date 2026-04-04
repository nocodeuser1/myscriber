#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# myScriber DMG Builder
# Creates a professional .dmg installer for distribution.
# Double-click this file or run: bash build_dmg.command
# ─────────────────────────────────────────────────────────────────────────────

set -e
cd "$(dirname "$0")" || exit 1

BLUE='\033[0;34m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'

# Read version from the app source
VERSION=$(python3 -c "
import re
with open('app/myscriber.py') as f:
    m = re.search(r'APP_VERSION\s*=\s*\"(.+?)\"', f.read())
    print(m.group(1) if m else '1.0.0')
")

SCRIPT_DIR="$(pwd)"
DMG_NAME="myScriber-${VERSION}"
DMG_DIR="$SCRIPT_DIR/dist"
STAGING="$DMG_DIR/staging"
DMG_FILE="$DMG_DIR/${DMG_NAME}.dmg"

echo ""
echo -e "${BLUE}╔══════════════════════════════════════╗${NC}"
echo -e "${BLUE}║       myScriber DMG Builder          ║${NC}"
echo -e "${BLUE}║       Version: ${VERSION}                 ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════╝${NC}"
echo ""

# ── Clean previous builds ───────────────────────────────────────────────────
rm -rf "$STAGING" "$DMG_FILE"
mkdir -p "$STAGING"

# ── Generate icons fresh ────────────────────────────────────────────────────
echo -e "${YELLOW}→ Generating icons...${NC}"
python3 app/make_icons.py 2>/dev/null || true

# Build .icns if iconutil available
ICONSET="$SCRIPT_DIR/assets/AppIcon.iconset"
ICNS="$SCRIPT_DIR/assets/AppIcon.icns"
if [ -d "$ICONSET" ] && command -v iconutil &>/dev/null; then
    iconutil -c icns "$ICONSET" -o "$ICNS" 2>/dev/null && echo -e "${GREEN}✓ AppIcon.icns built${NC}"
fi

# ── Stage the installer package ─────────────────────────────────────────────
echo -e "${YELLOW}→ Staging files...${NC}"

# Copy app source
mkdir -p "$STAGING/myScriber/app"
cp app/myscriber.py "$STAGING/myScriber/app/"
cp app/make_icons.py "$STAGING/myScriber/app/"

# Copy assets
mkdir -p "$STAGING/myScriber/assets"
cp -R assets/* "$STAGING/myScriber/assets/" 2>/dev/null || true

# Copy install script
cp install.sh "$STAGING/myScriber/install.sh"
chmod +x "$STAGING/myScriber/install.sh"

# Create the double-clickable installer
cat > "$STAGING/Install myScriber.command" << 'INSTALLER'
#!/bin/bash
# myScriber Installer — double-click to install
cd "$(dirname "$0")/myScriber" || { echo "Error: installer files not found."; exit 1; }
bash install.sh
INSTALLER
chmod +x "$STAGING/Install myScriber.command"

# Create a README
cat > "$STAGING/README.txt" << 'README'
═══════════════════════════════════════════
  myScriber — Local Voice-to-Text for Mac
═══════════════════════════════════════════

  Installation:
  1. Double-click "Install myScriber.command"
  2. Follow the prompts in Terminal
  3. Grant Microphone + Accessibility permissions when asked

  Usage:
  • Hold Cmd+L anywhere to record your voice
  • Release to transcribe and paste instantly
  • Everything runs locally — your audio never leaves your Mac

  Requirements:
  • macOS 12 or later
  • 500 MB disk space (for the AI model)

  Support: https://myscriber.com/support
═══════════════════════════════════════════
README

echo -e "${GREEN}✓ Files staged${NC}"

# ── Create the DMG ──────────────────────────────────────────────────────────
echo -e "${YELLOW}→ Creating DMG...${NC}"

# Create a temporary DMG
TEMP_DMG="$DMG_DIR/${DMG_NAME}-temp.dmg"
hdiutil create -srcfolder "$STAGING" \
    -volname "myScriber ${VERSION}" \
    -fs HFS+ \
    -fsargs "-c c=64,a=16,e=16" \
    -format UDRW \
    "$TEMP_DMG" -ov

# Mount it to customize
MOUNT_DIR=$(hdiutil attach -readwrite -noverify "$TEMP_DMG" | grep "/Volumes/" | sed 's/.*\/Volumes/\/Volumes/')
echo "Mounted at: $MOUNT_DIR"

# Set background and icon layout via AppleScript
osascript << APPLESCRIPT
tell application "Finder"
    tell disk "myScriber ${VERSION}"
        open
        set current view of container window to icon view
        set toolbar visible of container window to false
        set statusbar visible of container window to false
        set the bounds of container window to {200, 120, 750, 450}
        set viewOptions to the icon view options of container window
        set arrangement of viewOptions to not arranged
        set icon size of viewOptions to 80
        close
    end tell
end tell
APPLESCRIPT

# Set the volume icon if we have one
if [ -f "$ICNS" ]; then
    cp "$ICNS" "$MOUNT_DIR/.VolumeIcon.icns"
    SetFile -c icnC "$MOUNT_DIR/.VolumeIcon.icns" 2>/dev/null || true
    SetFile -a C "$MOUNT_DIR" 2>/dev/null || true
fi

# Unmount
hdiutil detach "$MOUNT_DIR" -force

# Compress to final DMG
hdiutil convert "$TEMP_DMG" -format UDZO -imagekey zlib-level=9 -o "$DMG_FILE"
rm -f "$TEMP_DMG"

# Clean up staging
rm -rf "$STAGING"

echo ""
echo -e "${GREEN}╔══════════════════════════════════════╗${NC}"
echo -e "${GREEN}║           DMG Ready!                 ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${BLUE}${DMG_FILE}${NC}"
echo ""
echo "  Upload this file to your website or GitHub Release."
echo ""
echo "  To create a GitHub Release:"
echo "    gh release create v${VERSION} '${DMG_FILE}' --title 'myScriber ${VERSION}' --notes 'Release notes here'"
echo ""
