"""Live end-to-end test on Windows.

Opens its own test window, starts Hafuch in a child process, types into the window
like a real keyboard (scan codes, no Hafuch marker) and checks the result.
Hafuch is killed at the end, so it never stays running in the background.
Run: python tests/live_test_win.py
"""
import ctypes
import os
import subprocess
import sys
import threading
import time
import queue
import tkinter as tk

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from hafuch import platform_win as pw  # noqa: E402

user32 = pw.user32
SC = {v: k for k, v in pw.SCAN.items()}
SC.update({' ': 0x39})
KEYEVENTF_SCANCODE = 0x0008
INV_HE = {}
from hafuch import keymap  # noqa: E402
INV_HE = {v: k for k, v in keymap.HE.items()}


def press_scan(scan, up=False):
    ev = pw.INPUT(1, pw._INPUTUNION(ki=pw.KEYBDINPUT(0, scan, KEYEVENTF_SCANCODE | (2 if up else 0), 0, 0)))
    user32.SendInput(1, ctypes.byref(ev), ctypes.sizeof(pw.INPUT))


def tap_vk(vk, mods=()):
    guard()
    for m in mods:
        user32.keybd_event(m, 0, 0, 0)
    user32.keybd_event(vk, 0, 0, 0)
    user32.keybd_event(vk, 0, 2, 0)
    for m in reversed(mods):
        user32.keybd_event(m, 0, 2, 0)


TARGET = {'hwnd': None}


class NotFocused(Exception):
    pass


def focus():
    hwnd = TARGET['hwnd']
    fg = user32.GetForegroundWindow()
    if fg == hwnd:
        return
    me = pw.kernel32.GetCurrentThreadId()
    other = user32.GetWindowThreadProcessId(fg, None)
    user32.AttachThreadInput(me, other, True)
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)
    user32.AttachThreadInput(me, other, False)
    time.sleep(0.3)


def guard():
    if user32.GetForegroundWindow() != TARGET['hwnd']:
        raise NotFocused('test window lost focus - stopping before typing anywhere else')


def type_keys(key_ids, delay=0.03):
    for k in key_ids:
        guard()
        press_scan(SC[k]); press_scan(SC[k], True)
        if delay:
            time.sleep(delay)


results = []
EXE = sys.argv[1] if len(sys.argv) > 1 else None   # optional: path to Hafuch.exe


def run_tests(root, text, hwnd):
    try:
        run_suite(root, auto=True)
        run_suite(root, auto=False)
        run_suite(root, auto=False, hotkeys={'convert_word': ['ctrl+alt+h', 'f9'],
                                             'convert_selection': ['ctrl+alt+k']})
    finally:
        root.cmds.put(('done', None))


def run_suite(root, auto, hotkeys=None):
    plat = pw.WindowsPlatform()
    cmd = [EXE, '--no-tray'] if EXE else [sys.executable, '-m', 'hafuch', '--no-tray']
    import json, tempfile
    cfg_dir = tempfile.mkdtemp(prefix='hafuch-test-')
    with open(os.path.join(cfg_dir, 'config.json'), 'w') as f:
        json.dump({'auto_convert': auto, **({'hotkeys': hotkeys} if hotkeys else {})}, f)
    env = dict(os.environ, HAFUCH_CONFIG_DIR=cfg_dir)
    proc = subprocess.Popen(cmd, cwd=ROOT, env=env,
                            stdout=subprocess.DEVNULL if EXE else subprocess.PIPE,
                            stderr=subprocess.STDOUT)
    try:
        time.sleep(4.0 if EXE else 2.0)               # one-file exe unpacks first
        focus()
        guard()

        def ui(cmd):
            reply = queue.Queue()
            root.cmds.put((cmd, reply))
            return reply.get(timeout=5)

        def content():
            return ui('read')

        def check(name, expected, layout=None):
            time.sleep(0.8)
            got = content()
            lay = plat.current_layout()
            ok = got == expected and (layout is None or lay == layout)
            results.append((ok, name, repr(got), lay))
            print('PASS' if ok else 'FAIL', name, repr(got), lay, flush=True)

        def clear():
            focus()
            ui('clear')
            time.sleep(0.2)

        def set_layout(lang):
            focus()
            plat.set_layout(lang)
            time.sleep(0.4)

        if hotkeys:                                   # keys chosen in the settings window
            clear(); set_layout('en')
            type_keys('akuo'); tap_vk(0x48, (0x11, 0x12)); check('custom Ctrl+Alt+H flips the word', 'שלום', 'he')
            clear(); set_layout('en')
            type_keys('akuo'); tap_vk(0x78); check('custom F9 flips the word', 'שלום', 'he')
            clear(); set_layout('en')
            type_keys('akuo'); tap_vk(0x13); check('old Pause no longer flips', 'akuo', 'en')
            clear(); set_layout('en')
            ui('fill'); tap_vk(0x4B, (0x11, 0x12)); check('custom Ctrl+Alt+K flips selection', 'שלום תודה', 'he')
            return
        if not auto:                                  # the user's real mode: manual only
            clear(); set_layout('en')
            type_keys('akuo the '); check('manual mode: nothing changes by itself', 'akuo the ', 'en')
            clear(); set_layout('en')
            type_keys('akuo '); tap_vk(0x20, (0x11, 0x10))
            check('manual mode: Ctrl+Shift+Space flips the last word', 'שלום ', 'he')
            clear(); set_layout('en')
            type_keys('akuo'); tap_vk(0x13); check('manual mode: Pause flips the current word', 'שלום', 'he')
            return
        set_layout('en')
        type_keys('akuo '); check('Hebrew typed in English -> שלום', 'שלום ', 'he')
        clear()
        type_keys([INV_HE[c] for c in 'יקךךם'] + [' ']); check('English typed in Hebrew -> hello', 'hello ', 'en')
        clear(); set_layout('en')
        type_keys('the house '); check('real English words untouched', 'the house ', 'en')
        clear(); set_layout('he')
        type_keys([INV_HE[c] for c in 'שלום'] + [' ']); check('real Hebrew word untouched', 'שלום ', 'he')
        clear(); set_layout('en')
        type_keys('go'); tap_vk(0x13); check('Pause flips current word go -> עם', 'עם', 'he')
        clear(); set_layout('en')
        type_keys('akuo '); time.sleep(0.5); tap_vk(0x13); check('Pause right after auto flip = undo', 'akuo ', 'en')
        clear(); set_layout('en')
        type_keys('nhkv ,usv ', delay=0); check('fast typing, no pause: never corrupted', 'מילה תודה ', 'he')
        clear(); set_layout('en')
        type_keys('nhkv', delay=0.01); type_keys(' ,u', delay=0); time.sleep(0.01); type_keys('sv ', delay=0)
        check('keeps typing right after the space', 'מילה תודה ', 'he')
        clear(); set_layout('en')
        type_keys('nhkv ,usv the ', delay=0)        # 'the' lands in Hebrew -> flipped back
        check('three flips in a row, fast', 'מילה תודה the ', 'en')
        clear(); set_layout('en')
        type_keys('go'); tap_vk(0x20, (0x11, 0x10)); check('Ctrl+Shift+Space flips go -> עם', 'עם', 'he')
        clear(); set_layout('en')
        ui('fill')                                       # text already on screen, selected
        tap_vk(0x13, (0x10,)); check('Shift+Pause flips selection', 'שלום תודה', 'he')
    except Exception as e:
        results.append((False, 'aborted', str(e), ''))
    finally:
        # /T: the exe is a launcher + child; kill the whole tree so no hook stays alive
        subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'], capture_output=True)
        try:
            out = (proc.communicate(timeout=5)[0] or b'').decode('utf-8', 'replace')
            if out.strip():
                results.append((True, 'hafuch output', out.strip()[:300], ''))
        except Exception as e:
            results.append((False, 'cleanup', repr(e), ''))


def main():
    root = tk.Tk()
    root.title('Hafuch live test')
    root.geometry('500x200+200+200')
    text = tk.Text(root, font=('Arial', 16))
    text.pack(fill='both', expand=True)
    root.cmds = queue.Queue()

    def pump():
        while not root.cmds.empty():
            cmd, reply = root.cmds.get()
            if cmd == 'read':
                reply.put(text.get('1.0', 'end-1c'))
            elif cmd == 'clear':
                text.delete('1.0', 'end'); reply.put(None)
            elif cmd == 'fill':
                text.delete('1.0', 'end'); text.insert('1.0', 'akuo ,usv')
                text.tag_add('sel', '1.0', 'end-1c'); reply.put(None)
            elif cmd == 'done':
                root.quit(); return
        root.after(30, pump)
    root.after(30, pump)
    root.attributes('-topmost', True)

    def grab_focus():
        hwnd = user32.GetParent(text.winfo_id())
        hwnd = user32.GetAncestor(hwnd, 2) or hwnd           # GA_ROOT
        TARGET['hwnd'] = hwnd
        focus()          # no Alt trick: Alt puts the Tk window into menu mode and freezes its timers
        text.focus_force()

    def start():
        threading.Thread(target=run_tests, args=(root, text, TARGET['hwnd']), daemon=True).start()
    root.after(400, grab_focus)
    root.after(1200, start)
    root.mainloop()
    passed = sum(1 for r in results if r[0])
    for ok, name, got, lay in results:
        print('PASS' if ok else 'FAIL', '|', name, '|', got, '|', lay)
    print(f'{passed}/{len(results)}')


if __name__ == '__main__':
    main()
