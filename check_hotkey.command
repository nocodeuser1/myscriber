#!/bin/bash
# Check if the CGEventTap hotkey fix is active
echo "=== myScriber Hotkey Diagnostics ==="
echo ""

echo "1. Is the CGEventTap code installed?"
if grep -q "CGEventTapCreate" "$HOME/.myscriber/app/myscriber.py" 2>/dev/null; then
    echo "   YES — CGEventTap code is present"
else
    echo "   NO — update.command needs to be run first!"
fi
echo ""

echo "2. Recent log entries (last 30 lines):"
echo "   ---"
tail -30 "$HOME/.myscriber/myscriber.log" 2>/dev/null || echo "   (no log file found)"
echo "   ---"
echo ""

echo "3. Is Accessibility enabled for myScriber?"
echo "   (Check System Settings → Privacy & Security → Accessibility)"
echo "   If myScriber is NOT listed, you need to click '+' and add /Applications/myScriber.app"
echo ""

read -p "Press Enter to close..."
