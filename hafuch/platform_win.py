"""Windows layer: low-level keyboard/mouse hooks, SendInput, keyboard layouts, clipboard.
Pure ctypes, no extra packages."""
import ctypes
import os
import threading
import time
from ctypes import wintypes as wt

user32 = ctypes.WinDLL('user32', use_last_error=True)
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

MAGIC = 0x48414655                     # dwExtraInfo on everything we inject ("HAFU")
MAGIC_REPLAY = 0x48414652              # user keys we held and gave back - treated as user input
WH_KEYBOARD_LL, WH_MOUSE_LL = 13, 14
WM_KEYDOWN, WM_SYSKEYDOWN = 0x0100, 0x0104
WM_KEYUP, WM_SYSKEYUP = 0x0101, 0x0105
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_SCANCODE = 0x0001, 0x0008
WM_QUIT = 0x0012
WM_INPUTLANGCHANGEREQUEST = 0x0050
MOUSE_DOWN = {0x0201, 0x0204, 0x0207, 0x020B}
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP, KEYEVENTF_UNICODE = 0x0002, 0x0004
CF_UNICODETEXT = 13
LANG_HE, LANG_EN = 0x0D, 0x09

LRESULT = ctypes.c_ssize_t
ULONG_PTR = ctypes.c_size_t


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [('vkCode', wt.DWORD), ('scanCode', wt.DWORD), ('flags', wt.DWORD),
                ('time', wt.DWORD), ('dwExtraInfo', ULONG_PTR)]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [('pt', wt.POINT), ('mouseData', wt.DWORD), ('flags', wt.DWORD),
                ('time', wt.DWORD), ('dwExtraInfo', ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [('wVk', wt.WORD), ('wScan', wt.WORD), ('dwFlags', wt.DWORD),
                ('time', wt.DWORD), ('dwExtraInfo', ULONG_PTR)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [('dx', wt.LONG), ('dy', wt.LONG), ('mouseData', wt.DWORD),
                ('dwFlags', wt.DWORD), ('time', wt.DWORD), ('dwExtraInfo', ULONG_PTR)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [('ki', KEYBDINPUT), ('mi', MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [('type', wt.DWORD), ('u', _INPUTUNION)]


HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wt.WPARAM, wt.LPARAM)
user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wt.HINSTANCE, wt.DWORD]
user32.SetWindowsHookExW.restype = wt.HHOOK
user32.CallNextHookEx.argtypes = [wt.HHOOK, ctypes.c_int, wt.WPARAM, wt.LPARAM]
user32.CallNextHookEx.restype = LRESULT
user32.UnhookWindowsHookEx.argtypes = [wt.HHOOK]
user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
user32.SendInput.argtypes = [wt.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.GetForegroundWindow.restype = wt.HWND
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
user32.GetKeyboardLayout.argtypes = [wt.DWORD]
user32.GetKeyboardLayout.restype = ctypes.c_void_p
user32.GetKeyboardLayoutList.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)]
user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.GetKeyState.restype = ctypes.c_short
user32.PostThreadMessageW.argtypes = [wt.DWORD, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.GetClipboardData.restype = wt.HANDLE
user32.SetClipboardData.argtypes = [wt.UINT, wt.HANDLE]
user32.SetClipboardData.restype = wt.HANDLE
kernel32.GlobalAlloc.restype = wt.HGLOBAL
kernel32.GlobalAlloc.argtypes = [wt.UINT, ctypes.c_size_t]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalLock.argtypes = [wt.HGLOBAL]
kernel32.GlobalUnlock.argtypes = [wt.HGLOBAL]
kernel32.GetModuleHandleW.restype = wt.HMODULE
kernel32.OpenProcess.restype = wt.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
kernel32.CloseHandle.argtypes = [wt.HANDLE]
kernel32.CreateMutexW.restype = wt.HANDLE

# Physical keys by scan code (set 1) -> US key id. Layout independent.
SCAN = {}
for _row, _start in (('1234567890-=', 0x02), ('qwertyuiop[]', 0x10),
                     ("asdfghjkl;'`", 0x1E), ('zxcvbnm,./', 0x2C)):
    for _i, _c in enumerate(_row):
        SCAN[_start + _i] = _c
SCAN[0x2B] = '\\'
# Fallback when an injected event has no scan code: US virtual keys.
VK = {0x30 + i: str(i) for i in range(10)}
VK.update({0x41 + i: chr(0x61 + i) for i in range(26)})
VK.update({0xBA: ';', 0xBB: '=', 0xBC: ',', 0xBD: '-', 0xBE: '.', 0xBF: '/',
           0xC0: '`', 0xDB: '[', 0xDC: '\\', 0xDD: ']', 0xDE: "'"})
NAMES = {0x08: 'backspace', 0x09: 'tab', 0x0D: 'enter', 0x20: 'space', 0x13: 'pause',
         0x10: 'shift', 0xA0: 'shift', 0xA1: 'shift', 0x14: 'capslock',
         0x11: 'ctrl', 0xA2: 'ctrl', 0xA3: 'ctrl', 0x12: 'alt', 0xA4: 'alt', 0xA5: 'alt',
         0x5B: 'win', 0x5C: 'win'}
NAMES.update({0x70 + i: f'f{i + 1}' for i in range(24)})
NAMES[0x03] = 'pause'          # Ctrl+Pause arrives as VK_CANCEL   # F1-F24 (usable as hotkeys)
MOD_VKS = {'shift': 0x10, 'ctrl': 0x11, 'alt': 0x12}


def _down(vk):
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


def _key(vk=0, scan=0, flags=0):
    return INPUT(INPUT_KEYBOARD, _INPUTUNION(ki=KEYBDINPUT(vk, scan, flags, 0, MAGIC)))


class WindowsPlatform:
    can_hold = True

    def __init__(self):
        self._held = []                    # (vk, scan, flags, up) swallowed during a flip
        self._replay_seen = 0              # replayed events the hook has processed
        self._held_lock = threading.Lock()
        self._thread = None
        self._tid = None
        self._procs = []
        self._app_cache = (None, '')

    # ---------- hooks ----------
    def start(self, controller):
        self.c = controller
        ready = threading.Event()
        self._thread = threading.Thread(target=self._loop, args=(ready,), daemon=True, name='hafuch-hook')
        self._thread.start()
        ready.wait(5)

    def stop(self):
        if self._tid:
            user32.PostThreadMessageW(self._tid, WM_QUIT, 0, 0)

    def _loop(self, ready):
        self._tid = kernel32.GetCurrentThreadId()
        kb_proc, ms_proc = HOOKPROC(self._on_kb), HOOKPROC(self._on_mouse)
        self._procs = [kb_proc, ms_proc]                  # keep alive
        hmod = kernel32.GetModuleHandleW(None)
        kb = user32.SetWindowsHookExW(WH_KEYBOARD_LL, kb_proc, hmod, 0)
        ms = user32.SetWindowsHookExW(WH_MOUSE_LL, ms_proc, hmod, 0)
        ready.set()
        msg = wt.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            pass
        user32.UnhookWindowsHookEx(kb)
        user32.UnhookWindowsHookEx(ms)

    def _on_kb(self, code, wparam, lparam):
        try:
            if code == 0:
                d = ctypes.cast(lparam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
                if d.dwExtraInfo == MAGIC or d.vkCode == 0xE7:    # ours / unicode packet
                    return user32.CallNextHookEx(None, code, wparam, lparam)
                replay = d.dwExtraInfo == MAGIC_REPLAY
                up = wparam in (WM_KEYUP, WM_SYSKEYUP)
                if not replay:
                    with self._held_lock:
                        if self.c.hold_active():                   # a flip is being typed
                            self._held.append((d.vkCode, d.scanCode, d.flags, up))
                            return 1
                if replay:
                    self._replay_seen += 1
                if not up and wparam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                    if self._handle(d, replay):
                        if self.c.holding:                         # the Space that started a flip
                            with self._held_lock:
                                self._held.insert(0, (d.vkCode, d.scanCode, d.flags, False))
                        return 1
        except Exception:
            pass
        return user32.CallNextHookEx(None, code, wparam, lparam)

    def release_hold(self):
        """Give back the keys swallowed during a flip, in order, as if typed now."""
        seq = self.c.hold_seq
        while True:
            with self._held_lock:
                if not self._held:
                    self.c.holding = False
                    return
                vk, scan, flags, up = self._held.pop(0)
            f = (KEYEVENTF_KEYUP if up else 0) | (KEYEVENTF_EXTENDEDKEY if flags & 1 else 0)
            if scan:
                ki = KEYBDINPUT(0, scan, f | KEYEVENTF_SCANCODE, 0, MAGIC_REPLAY)
            else:
                ki = KEYBDINPUT(vk, 0, f, 0, MAGIC_REPLAY)
            seen = self._replay_seen
            self._send([INPUT(INPUT_KEYBOARD, _INPUTUNION(ki=ki))])
            end = time.time() + 0.2                  # wait until the hook has seen it
            while self._replay_seen == seen and time.time() < end:
                time.sleep(0.001)
            if self.c.hold_seq != seq:
                return                               # a replayed key started the next flip

    def _handle(self, d, replay=False):
        vk = d.vkCode
        name = NAMES.get(vk)
        key_id = None
        if name is None:
            extended = d.flags & 0x01
            key_id = None if extended else SCAN.get(d.scanCode)
            if key_id is None and not d.scanCode:
                key_id = VK.get(vk)
            name = 'char' if key_id else 'other'
        mods = set()
        if _down(0x10): mods.add('shift')
        if _down(0x11): mods.add('ctrl')
        if _down(0x12): mods.add('alt')
        if _down(0x5B) or _down(0x5C): mods.add('win')
        if name in mods:                       # the modifier itself
            return False
        hwnd = user32.GetForegroundWindow()
        return self.c.on_key(name, key_id, mods, hwnd, replay)

    def _on_mouse(self, code, wparam, lparam):
        try:
            if code == 0 and wparam in MOUSE_DOWN:
                self.c.on_mouse()
        except Exception:
            pass
        return user32.CallNextHookEx(None, code, wparam, lparam)

    # ---------- state ----------
    def caps_lock(self):
        return bool(user32.GetKeyState(0x14) & 1)

    def _fg_thread(self):
        return user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)

    def current_layout(self):
        hkl = user32.GetKeyboardLayout(self._fg_thread()) or 0
        prim = hkl & 0x3FF
        return 'he' if prim == LANG_HE else 'en' if prim == LANG_EN else None

    def installed(self):
        n = user32.GetKeyboardLayoutList(0, None)
        arr = (ctypes.c_void_p * n)()
        user32.GetKeyboardLayoutList(n, arr)
        return [h or 0 for h in arr]

    def set_layout(self, lang):
        want = LANG_HE if lang == 'he' else LANG_EN
        for hkl in self.installed():
            if hkl & 0x3FF == want:
                user32.PostMessageW(user32.GetForegroundWindow(), WM_INPUTLANGCHANGEREQUEST, 0, hkl)
                return True
        return False

    def foreground_app(self):
        hwnd = user32.GetForegroundWindow()
        if self._app_cache[0] == hwnd:
            return self._app_cache[1]
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        name = ''
        h = kernel32.OpenProcess(0x1000, False, pid.value)   # QUERY_LIMITED_INFORMATION
        if h:
            buf = ctypes.create_unicode_buffer(520)
            size = wt.DWORD(520)
            if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                name = os.path.splitext(os.path.basename(buf.value))[0].lower()
            kernel32.CloseHandle(h)
        self._app_cache = (hwnd, name)
        return name

    # ---------- typing ----------
    def _send(self, events):
        arr = (INPUT * len(events))(*events)
        user32.SendInput(len(events), arr, ctypes.sizeof(INPUT))

    def send(self, backspaces, text):
        ev = []
        for _ in range(backspaces):
            ev += [_key(0x08), _key(0x08, flags=KEYEVENTF_KEYUP)]
        for ch in text:
            if ch == '\n':
                ev += [_key(0x0D), _key(0x0D, flags=KEYEVENTF_KEYUP)]
            elif ch == '\t':
                ev += [_key(0x09), _key(0x09, flags=KEYEVENTF_KEYUP)]
            else:
                for unit in _utf16(ch):
                    ev += [_key(0, unit, KEYEVENTF_UNICODE),
                           _key(0, unit, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP)]
        self._send(ev)

    def mask_modifiers(self):
        """The hotkey's Space was swallowed, so the app would see a bare Ctrl+Shift
        (= paragraph direction in Word/Notepad). A neutral key in between prevents it."""
        self._send([_key(0xE8), _key(0xE8, flags=KEYEVENTF_KEYUP)])   # 0xE8: unassigned VK

    def wait_modifiers_released(self, timeout=1.5):
        end = time.time() + timeout
        while time.time() < end and any(_down(v) for v in (0x10, 0x11, 0x12, 0x5B, 0x5C)):
            time.sleep(0.02)

    def _chord(self, letter_vk):
        self._send([_key(0x11), _key(letter_vk), _key(letter_vk, flags=KEYEVENTF_KEYUP),
                    _key(0x11, flags=KEYEVENTF_KEYUP)])

    # ---------- clipboard ----------
    def _clip_get(self):
        for _ in range(10):
            if user32.OpenClipboard(None):
                break
            time.sleep(0.02)
        else:
            return None
        try:
            h = user32.GetClipboardData(CF_UNICODETEXT)
            if not h:
                return None
            p = kernel32.GlobalLock(h)
            try:
                return ctypes.wstring_at(p)
            finally:
                kernel32.GlobalUnlock(h)
        finally:
            user32.CloseClipboard()

    def _clip_set(self, text):
        for _ in range(10):
            if user32.OpenClipboard(None):
                break
            time.sleep(0.02)
        else:
            return False
        try:
            user32.EmptyClipboard()
            if text is None:
                return True
            data = ctypes.create_unicode_buffer(text)
            h = kernel32.GlobalAlloc(0x0002, ctypes.sizeof(data))      # GMEM_MOVEABLE
            p = kernel32.GlobalLock(h)
            ctypes.memmove(p, data, ctypes.sizeof(data))
            kernel32.GlobalUnlock(h)
            user32.SetClipboardData(CF_UNICODETEXT, h)
            return True
        finally:
            user32.CloseClipboard()

    def copy_selection(self):
        self._saved_clip = self._clip_get()
        seq = user32.GetClipboardSequenceNumber()
        self._chord(0x43)                                           # Ctrl+C
        end = time.time() + 0.5
        while time.time() < end and user32.GetClipboardSequenceNumber() == seq:
            time.sleep(0.02)
        if user32.GetClipboardSequenceNumber() == seq:
            return None                                             # nothing selected
        return self._clip_get()

    def paste_text(self, text):
        self._clip_set(text)
        self._chord(0x56)                                           # Ctrl+V
        time.sleep(0.25)
        self._clip_set(getattr(self, '_saved_clip', None))          # restore user's clipboard


def _utf16(ch):
    b = ch.encode('utf-16-le')
    return [int.from_bytes(b[i:i + 2], 'little') for i in range(0, len(b), 2)]


def single_instance():
    """True if no other Hafuch is running."""
    kernel32.CreateMutexW(None, False, 'Local\\HafuchSingleInstance')
    return ctypes.get_last_error() != 183          # ERROR_ALREADY_EXISTS


def set_autostart(enable, command):
    import winreg
    key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                         r'Software\Microsoft\Windows\CurrentVersion\Run', 0, winreg.KEY_SET_VALUE)
    with key:
        if enable:
            winreg.SetValueEx(key, 'Hafuch', 0, winreg.REG_SZ, command)
        else:
            try:
                winreg.DeleteValue(key, 'Hafuch')
            except FileNotFoundError:
                pass


def get_autostart():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
            winreg.QueryValueEx(key, 'Hafuch')
            return True
    except OSError:
        return False
