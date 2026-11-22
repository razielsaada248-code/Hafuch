#!/bin/sh
# Builds dist/Hafuch.app - must run ON a Mac (PyInstaller does not cross-compile).
set -e
python3 -m pip install -r requirements.txt pyinstaller
python3 -m PyInstaller --noconfirm --windowed --name Hafuch \
  --add-data "hafuch/data:hafuch/data" \
  --icon hafuch/data/icon.png --osx-bundle-identifier com.hafuch.app run.py
# Hide from the Dock (tray-only app)
/usr/libexec/PlistBuddy -c "Add :LSUIElement bool true" dist/Hafuch.app/Contents/Info.plist || true
# Editing Info.plist breaks PyInstaller's signature, and Apple-chip Macs then call the app
# "damaged". Re-sign it (ad-hoc, free) and make sure the signature holds.
codesign --force --deep --sign - dist/Hafuch.app
codesign --verify --deep --strict --verbose=2 dist/Hafuch.app
echo "Then: System Settings > Privacy & Security > Accessibility + Input Monitoring > allow Hafuch"
