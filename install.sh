#!/bin/bash
# myScriber Installer
# Double-click this file in Terminal or run: bash install.sh

set -e

BLUE='\033[0;34m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'

INSTALL_DIR="$HOME/.myscriber"
APP_BUNDLE="/Applications/myScriber.app"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo ""
echo -e "${BLUE}╔══════════════════════════════════════╗${NC}"
echo -e "${BLUE}║           myScriber Installer        ║${NC}"
echo -e "${BLUE}║    Local Whisper Menubar Dictation   ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════╝${NC}"
echo ""

# ── macOS check ──────────────────────────────────────────────────────────────
[[ "$OSTYPE" == "darwin"* ]] || { echo -e "${RED}macOS only.${NC}"; exit 1; }
echo -e "${GREEN}✓ macOS $(sw_vers -productVersion)${NC}"

# ── Homebrew ─────────────────────────────────────────────────────────────────
if ! command -v brew &>/dev/null; then
  echo -e "${YELLOW}→ Installing Homebrew...${NC}"
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  [[ -f "/opt/homebrew/bin/brew" ]] && eval "$(/opt/homebrew/bin/brew shellenv)"
else
  echo -e "${GREEN}✓ Homebrew found${NC}"
fi

# ── Python ───────────────────────────────────────────────────────────────────
PYTHON=""
for c in python3.12 python3.11 python3.10 python3; do
  if command -v "$c" &>/dev/null; then
    OK=$("$c" -c "import sys; print(sys.version_info>=(3,10))" 2>/dev/null)
    [[ "$OK" == "True" ]] && { PYTHON="$c"; break; }
  fi
done
if [[ -z "$PYTHON" ]]; then
  echo -e "${YELLOW}→ Installing Python 3.11...${NC}"
  brew install python@3.11
  PYTHON=python3.11
fi
echo -e "${GREEN}✓ $($PYTHON --version)${NC}"

# ── ffmpeg ───────────────────────────────────────────────────────────────────
if ! command -v ffmpeg &>/dev/null; then
  echo -e "${YELLOW}→ Installing ffmpeg...${NC}"
  brew install ffmpeg
else
  echo -e "${GREEN}✓ ffmpeg${NC}"
fi

# ── Virtual environment ──────────────────────────────────────────────────────
echo -e "${YELLOW}→ Creating virtual environment...${NC}"
mkdir -p "$INSTALL_DIR"
$PYTHON -m venv "$INSTALL_DIR/venv"
source "$INSTALL_DIR/venv/bin/activate"
PIP="$INSTALL_DIR/venv/bin/pip"
$PIP install --upgrade pip --quiet

# ── Python packages ──────────────────────────────────────────────────────────
echo -e "${YELLOW}→ Installing packages...${NC}"
ARCH=$(uname -m)
if [[ "$ARCH" == "arm64" ]]; then
  echo -e "${BLUE}   Apple Silicon — using mlx-whisper${NC}"
  $PIP install mlx-whisper --quiet 2>/dev/null || $PIP install openai-whisper --quiet
else
  echo -e "${BLUE}   Intel Mac — using openai-whisper${NC}"
  $PIP install openai-whisper --quiet
fi
$PIP install rumps sounddevice numpy pynput pyobjc-framework-Cocoa pyobjc-framework-Quartz --quiet
echo -e "${GREEN}✓ Packages installed${NC}"

# ── Copy app files ───────────────────────────────────────────────────────────
echo -e "${YELLOW}→ Copying app files...${NC}"
cp -r "$SCRIPT_DIR/app"    "$INSTALL_DIR/"
mkdir -p "$INSTALL_DIR/assets"

# ── Generate icons ───────────────────────────────────────────────────────────
echo -e "${YELLOW}→ Generating icons...${NC}"
"$INSTALL_DIR/venv/bin/python" "$INSTALL_DIR/app/make_icons.py"
echo -e "${GREEN}✓ Icons ready${NC}"

# ── Build .app bundle ────────────────────────────────────────────────────────
echo -e "${YELLOW}→ Building myScriber.app...${NC}"
rm -rf "$APP_BUNDLE"
mkdir -p "$APP_BUNDLE/Contents/MacOS"
mkdir -p "$APP_BUNDLE/Contents/Resources"

# Copy icns icon into the bundle
ICNS="$INSTALL_DIR/assets/AppIcon.icns"
[[ -f "$ICNS" ]] && cp "$ICNS" "$APP_BUNDLE/Contents/Resources/AppIcon.icns"

cat > "$APP_BUNDLE/Contents/Info.plist" << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key>              <string>myScriber</string>
  <key>CFBundleDisplayName</key>       <string>myScriber</string>
  <key>CFBundleIdentifier</key>        <string>com.myscriber.app</string>
  <key>CFBundleVersion</key>           <string>1.0.0</string>
  <key>CFBundleShortVersionString</key> <string>1.0.0</string>
  <key>CFBundlePackageType</key>       <string>APPL</string>
  <key>CFBundleExecutable</key>        <string>myScriber</string>
  <key>CFBundleIconFile</key>          <string>AppIcon</string>
  <key>LSUIElement</key>               <true/>
  <key>NSMicrophoneUsageDescription</key>
    <string>myScriber records your voice to transcribe it locally on your device.</string>
  <key>NSAppleEventsUsageDescription</key>
    <string>myScriber uses AppleScript to paste transcribed text into the active field.</string>
</dict>
</plist>
PLIST

cat > "$APP_BUNDLE/Contents/MacOS/myScriber" << 'EXEC'
#!/bin/bash
source "$HOME/.myscriber/venv/bin/activate"
python "$HOME/.myscriber/app/myscriber.py" 2>>"$HOME/.myscriber/launch.log"
EXEC
chmod +x "$APP_BUNDLE/Contents/MacOS/myScriber"
echo -e "${GREEN}✓ myScriber.app installed to /Applications${NC}"

# ── Pre-download Whisper model ──────────────────────────────────────────────
# Use model from GUI env var, or from config, or default to 'base'
MODEL="${MYSCRIBER_MODEL:-base}"
if [[ -f "$INSTALL_DIR/config.json" ]]; then
  CFG_MODEL=$(python3 -c "import json; print(json.load(open('$INSTALL_DIR/config.json')).get('model','base'))" 2>/dev/null || echo "$MODEL")
  MODEL="${MYSCRIBER_MODEL:-$CFG_MODEL}"
fi

MODEL_SIZES="tiny:40MB base:150MB small:500MB medium:1.5GB large-v3:3GB"
MODEL_SIZE=""
for entry in $MODEL_SIZES; do
  IFS=: read -r name size <<< "$entry"
  [[ "$name" == "$MODEL" ]] && MODEL_SIZE="$size"
done

echo -e "${YELLOW}→ Downloading Whisper '$MODEL' model (~${MODEL_SIZE:-unknown})...${NC}"

# Delete any stale HuggingFace token that causes 401 errors
rm -f "$HOME/.cache/huggingface/token" 2>/dev/null

HF_HUB_DISABLE_IMPLICIT_TOKEN=1 HF_TOKEN="" HUGGING_FACE_HUB_TOKEN="" \
"$INSTALL_DIR/venv/bin/python" -c "
import os
os.environ['HF_HUB_DISABLE_IMPLICIT_TOKEN'] = '1'
os.environ.pop('HF_TOKEN', None)
os.environ.pop('HUGGING_FACE_HUB_TOKEN', None)
from huggingface_hub import snapshot_download
model = '$MODEL'
mlx_map = {'tiny':'mlx-community/whisper-tiny','base':'mlx-community/whisper-base-mlx','small':'mlx-community/whisper-small-mlx','medium':'mlx-community/whisper-medium-mlx','large-v3':'mlx-community/whisper-large-v3-mlx'}
try:
    import mlx_whisper
    repo = mlx_map.get(model, f'mlx-community/whisper-{model}-mlx')
    local_path = snapshot_download(repo_id=repo, token=False)
    mlx_whisper.load_models.load_model(local_path)
except ImportError:
    import whisper; whisper.load_model(model)
print('Model ready.')
" && echo -e "${GREEN}✓ Model downloaded${NC}" || echo -e "${YELLOW}⚠ Will download on first launch${NC}"

# ── Permissions reminder ─────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}All done!${NC}"

# When launched from the GUI installer, skip interactive prompts
if [[ "$MYSCRIBER_GUI" == "1" ]]; then
  echo "Install complete. Return to the installer window."
  exit 0
fi

echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"
echo -e "${YELLOW}  Two permissions needed in System Settings (one-time)${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"
echo ""
echo "  1. Microphone"
echo "     System Settings → Privacy & Security → Microphone"
echo "     Toggle on myScriber"
echo ""
echo "  2. Accessibility  ← required for paste to work"
echo "     System Settings → Privacy & Security → Accessibility"
echo "     Toggle on myScriber"
echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════════${NC}"
echo ""
echo "  → myScriber.app is in your /Applications folder"
echo "  → Launch it — look for the mic icon in your menubar"
echo "  → Hold Cmd+L anywhere to dictate"
echo "  → Release to transcribe and paste"
echo ""

read -p "Launch myScriber now? (y/n): " -n 1 -r; echo ""
[[ $REPLY =~ ^[Yy]$ ]] && open "$APP_BUNDLE" && echo -e "${GREEN}myScriber launched.${NC}"
