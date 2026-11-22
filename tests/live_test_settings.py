"""Live test of the settings window on Windows, with real key presses.

Opens `hafuch --settings` (or `Hafuch.exe --settings`) on a temporary config,
presses Tab, Space (= "שנה" on the first slot), Ctrl+Alt+H, then Enter (= save),
and checks the saved config. Stops before typing if the window is not in front.
Run from PowerShell: python tests/live_test_settings.py [path\\to\\Hafuch.exe]
"""
import ctypes
import json
import os
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
EXE = sys.argv[1] if len(sys.argv) > 1 else None
TITLE = 'Hafuch - הגדרות'


def find_window(timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        h = user32.FindWindowW(None, TITLE)
        if h:
            return h
        time.sleep(0.2)
    return 0


def focus(hwnd):
    fg = user32.GetForegroundWindow()
    if fg != hwnd:
        me = kernel32.GetCurrentThreadId()
        other = user32.GetWindowThreadProcessId(fg, None)
        user32.AttachThreadInput(me, other, True)
        user32.BringWindowToTop(hwnd)
        user32.SetForegroundWindow(hwnd)
        user32.AttachThreadInput(me, other, False)
        time.sleep(0.4)


def tap(hwnd, vk, mods=()):
    if user32.GetForegroundWindow() != hwnd:
        raise SystemExit('settings window lost focus - stopping before typing anywhere else')
    for m in mods:
        user32.keybd_event(m, 0, 0, 0)
    user32.keybd_event(vk, 0, 0, 0)
    user32.keybd_event(vk, 0, 2, 0)
    for m in reversed(mods):
        user32.keybd_event(m, 0, 2, 0)
    time.sleep(0.5)


def main():
    cfg_dir = tempfile.mkdtemp(prefix='hafuch-settings-')
    env = dict(os.environ, HAFUCH_CONFIG_DIR=cfg_dir)
    cmd = [EXE, '--settings'] if EXE else [sys.executable, '-m', 'hafuch', '--settings']
    proc = subprocess.Popen(cmd, cwd=ROOT, env=env)
    results = []
    try:
        hwnd = find_window()
        results.append((bool(hwnd), 'window opened'))
        if not hwnd:
            return
        time.sleep(0.6)
        focus(hwnd)
        tap(hwnd, 0x09)                          # Tab -> first "שנה" button
        tap(hwnd, 0x20)                          # Space -> start recording
        tap(hwnd, 0x48, (0x11, 0x12))            # Ctrl+Alt+H
        tap(hwnd, 0x0D)                          # Enter -> save and close
        code = proc.wait(timeout=5)
        results.append((code == 0, f'saved and closed (exit {code})'))
        with open(os.path.join(cfg_dir, 'config.json'), encoding='utf-8') as f:
            word = json.load(f)['hotkeys']['convert_word']
        results.append((word[0] == 'ctrl+alt+h', f'convert_word = {word}'))
        results.append((len(word) == 2 and word[1] == 'ctrl+shift+space', 'second slot kept'))
    except Exception as e:
        results.append((False, f'aborted: {e}'))
    finally:
        if proc.poll() is None:
            subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'], capture_output=True)
        for ok, name in results:
            print('PASS' if ok else 'FAIL', name)
        print(f'{sum(ok for ok, _ in results)}/{len(results)}')


if __name__ == '__main__':
    main()
