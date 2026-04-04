#!/bin/bash
echo "=== myScriber Status Check ==="
echo ""

echo "1. Installed file has CGEventTap?"
grep -c "CGEventTap" "$HOME/.myscriber/app/myscriber.py" 2>/dev/null
if [ $? -eq 0 ]; then
    echo "   YES — CGEventTap code is present"
else
    echo "   NO — update.command may not have run properly"
fi
echo ""

echo "2. Last 30 lines of log:"
echo "---"
tail -30 "$HOME/.myscriber/myscriber.log" 2>/dev/null || echo "(no log file found)"
echo "---"
echo ""

echo "3. Is myScriber running?"
pgrep -f "myscriber.py" >/dev/null && echo "   YES" || echo "   NO"
echo ""

echo "4. Accessibility status for current app:"
# Check if Accessibility is granted
"$HOME/.myscriber/venv/bin/python" -c "
import ctypes
appserv = ctypes.cdll.LoadLibrary('/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices')
appserv.AXIsProcessTrusted.restype = ctypes.c_bool
trusted = appserv.AXIsProcessTrusted()
print(f'   Accessibility trusted: {trusted}')
" 2>/dev/null || echo "   (could not check)"
echo ""

read -p "Press Enter to close..."
