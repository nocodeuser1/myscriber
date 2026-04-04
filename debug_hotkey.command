#!/bin/bash
echo "=== Debug Set Hotkey ==="
echo ""

echo "1. Does installed file have _learn_hotkey?"
grep -c "_learn_hotkey" "$HOME/.myscriber/app/myscriber.py" 2>/dev/null
echo ""

echo "2. Does it have osascript dialog approach?"
grep -c "Press your desired key" "$HOME/.myscriber/app/myscriber.py" 2>/dev/null
echo ""

echo "3. Does it still have CGEventTapCreate in learn?"
grep -c "learning event tap" "$HOME/.myscriber/app/myscriber.py" 2>/dev/null
echo ""

echo "4. Last 40 lines of log:"
tail -40 "$HOME/.myscriber/myscriber.log" 2>/dev/null || echo "(no log)"
echo ""

read -p "Press Enter to close..."
