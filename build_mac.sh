#!/bin/sh
# Builds dist/Hafuch.app - must run ON a Mac (PyInstaller does not cross-compile).
set -e
python3 -m pip install -r requirements.txt pyinstaller
python3 -m PyInstaller --noconfirm --windowed --name Hafuch \
  --add-data "hafuch/data:hafuch/data" \
  --icon hafuch/data/icon.png --osx-bundle-identifier com.hafuch.app run.py
# Hide from the Dock (tray-only app)
/usr/libexec/PlistBuddy -c "Add :LSUIElement bool true" dist/Hafuch.app/Contents/Info.plist || true
echo "Then: System Settings > Privacy & Security > Accessibility + Input Monitoring > allow Hafuch"
