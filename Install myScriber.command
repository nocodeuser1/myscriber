#!/bin/bash
# Double-click this file in Finder to install myScriber.
# Opens a graphical installer in your browser.

cd "$(dirname "$0")"

# Minimize Terminal so the user only sees the browser UI
osascript -e 'tell application "Terminal" to set miniaturized of front window to true' 2>/dev/null &

# Launch the HTML installer server (uses system Python, no dependencies)
python3 app/installer_server.py
