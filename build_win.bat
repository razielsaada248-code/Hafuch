@echo off
REM Builds dist\Hafuch.exe (one file, no console, ~15MB). Run from this folder.
python -m pip install -r requirements.txt pyinstaller
python -m PyInstaller --noconfirm --onefile --windowed --name Hafuch ^
  --add-data "hafuch\data;hafuch\data" --icon hafuch\data\icon.ico ^
  --exclude-module wordfreq --exclude-module numpy --exclude-module regex --exclude-module msgpack ^
  --exclude-module langcodes --exclude-module ftfy --exclude-module pynput run.py
del Hafuch.spec 2>nul
