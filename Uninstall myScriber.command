#!/bin/bash
# Double-click this file in Finder to uninstall myScriber.

set -e

BLUE='\033[0;34m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'

echo ""
echo -e "${RED}╔══════════════════════════════════════╗${NC}"
echo -e "${RED}║        myScriber Uninstaller         ║${NC}"
echo -e "${RED}╚══════════════════════════════════════╝${NC}"
echo ""

echo "This will remove:"
echo "  • /Applications/myScriber.app"
echo "  • ~/.myscriber/ (config, models, venv, logs)"
echo "  • myScriber from Login Items (if added)"
echo ""

read -p "Are you sure you want to uninstall myScriber? (y/n): " -n 1 -r; echo ""
[[ ! $REPLY =~ ^[Yy]$ ]] && { echo -e "${BLUE}Cancelled.${NC}"; exit 0; }

echo ""

# Quit the app if running
if pgrep -f "myscriber.py" >/dev/null 2>&1; then
  echo -e "${YELLOW}→ Quitting myScriber...${NC}"
  pkill -f "myscriber.py" 2>/dev/null || true
  sleep 1
fi

# Remove app bundle
if [ -d "/Applications/myScriber.app" ]; then
  echo -e "${YELLOW}→ Removing /Applications/myScriber.app...${NC}"
  rm -rf "/Applications/myScriber.app"
  echo -e "${GREEN}✓ App removed${NC}"
else
  echo -e "${GREEN}✓ App bundle not found (already removed)${NC}"
fi

# Remove data directory
if [ -d "$HOME/.myscriber" ]; then
  echo -e "${YELLOW}→ Removing ~/.myscriber/...${NC}"
  rm -rf "$HOME/.myscriber"
  echo -e "${GREEN}✓ Data directory removed${NC}"
else
  echo -e "${GREEN}✓ Data directory not found (already removed)${NC}"
fi

# Remove from Login Items (best-effort)
echo -e "${YELLOW}→ Removing from Login Items...${NC}"
osascript -e '
  tell application "System Events"
    try
      delete login item "myScriber"
    end try
  end tell
' 2>/dev/null || true
echo -e "${GREEN}✓ Login Items cleaned${NC}"

echo ""
echo -e "${GREEN}╔══════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   myScriber has been uninstalled.    ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════╝${NC}"
echo ""
echo "You can delete this uninstaller file too if you like."
echo ""
read -p "Press Enter to close..."
