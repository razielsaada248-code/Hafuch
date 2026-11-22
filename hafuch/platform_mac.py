"""macOS layer - NOT YET RUN ON A REAL MAC. Its logic is tested on Windows with
fakes (tests/test_mac_logic.py); the Apple calls themselves need a Mac.

Same contract as platform_win:
  * Quartz CGEventTap (pyobjc) for keys and clicks; it can swallow keys, so the
    "hold and replay" that keeps fast typing safe works here too.
  * CGEventPost for typing (unicode strings, marked with MAGIC).
  * Carbon TIS (ctypes) for keyboard layouts. Apple requires TIS on the MAIN
    thread, so the current layout is cached and refreshed by a system
    notification, and switching is dispatched to the main thread.
Permissions: System Settings > Privacy & Security > Accessibility AND
Input Monitoring must allow Hafuch. Recommended Hebrew layout: "Hebrew - PC".
"""
import ctypes
import os
import threading
import time

import objc
import Quartz
from AppKit import NSPasteboard, NSPasteboardTypeString, NSWorkspace
from Foundation import NSDistributedNotificationCenter, NSObject
from PyObjCTools import AppHelper

MAGIC = 0x48414655           # events we type
MAGIC_REPLAY = 0x48414652    # user keys we held and gave back
USER_DATA = Quartz.kCGEventSourceUserData

# mac virtual keycode -> US key id (physical position, layout independent)
KEYCODES = {
    0: 'a', 1: 's', 2: 'd', 3: 'f', 4: 'h', 5: 'g', 6: 'z', 7: 'x', 8: 'c', 9: 'v',
    11: 'b', 12: 'q', 13: 'w', 14: 'e', 15: 'r', 16: 'y', 17: 't', 18: '1', 19: '2',
    20: '3', 21: '4', 22: '6', 23: '5', 24: '=', 25: '9', 26: '7', 27: '-', 28: '8',
    29: '0', 30: ']', 31: 'o', 32: 'u', 33: '[', 34: 'i', 35: 'p', 37: 'l', 38: 'j',
    39: "'", 40: 'k', 41: ';', 42: '\\', 43: ',', 44: '/', 45: 'n', 46: 'm', 47: '.',
    50: '`',
}
NAMES = {49: 'space', 48: 'tab', 36: 'enter', 76: 'enter', 51: 'backspace',
         113: 'pause',  # F15 - Macs have no Pause key
         57: 'capslock'}
KC_DELETE, KC_RETURN, KC_TAB, KC_C, KC_V = 51, 36, 48, 8, 9
LAYOUT_CHANGED = 'com.apple.Carbon.TISNotifySelectedKeyboardInputSourceChanged'


def lang_of(source_id):
    s = (source_id or '').lower()
    if 'hebrew' in s and 'qwerty' not in s:        # Hebrew-QWERTY is phonetic, different keys
        return 'he'
    if any(x in s for x in ('keylayout.us', 'keylayout.abc', 'british', 'usinternational',
                            'australian', 'canadian', 'irish', 'colemak', 'dvorak')):
        return 'en' if 'colemak' not in s and 'dvorak' not in s else None
    return None


class _TIS:
    """Carbon Text Input Sources via ctypes. Call only on the main thread."""

    def __init__(self):
        carbon = ctypes.cdll.LoadLibrary('/System/Library/Frameworks/Carbon.framework/Carbon')
        cf = ctypes.cdll.LoadLibrary('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
        carbon.TISCopyCurrentKeyboardInputSource.restype = ctypes.c_void_p
        carbon.TISGetInputSourceProperty.restype = ctypes.c_void_p
        carbon.TISGetInputSourceProperty.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        carbon.TISCreateInputSourceList.restype = ctypes.c_void_p
        carbon.TISCreateInputSourceList.argtypes = [ctypes.c_void_p, ctypes.c_bool]
        carbon.TISSelectInputSource.argtypes = [ctypes.c_void_p]
        cf.CFArrayGetCount.restype = ctypes.c_long
        cf.CFArrayGetCount.argtypes = [ctypes.c_void_p]
        cf.CFArrayGetValueAtIndex.restype = ctypes.c_void_p
        cf.CFArrayGetValueAtIndex.argtypes = [ctypes.c_void_p, ctypes.c_long]
        cf.CFStringGetCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32]
        cf.CFRelease.argtypes = [ctypes.c_void_p]
        self.carbon, self.cf = carbon, cf
        self.prop_id = ctypes.c_void_p.in_dll(carbon, 'kTISPropertyInputSourceID')

    def _id(self, src):
        ref = self.carbon.TISGetInputSourceProperty(src, self.prop_id)
        buf = ctypes.create_string_buffer(256)
        if ref and self.cf.CFStringGetCString(ref, buf, 256, 0x08000100):   # UTF-8
            return buf.value.decode()
        return ''

    def current(self):
        src = self.carbon.TISCopyCurrentKeyboardInputSource()
        try:
            return lang_of(self._id(src))
        finally:
            self.cf.CFRelease(src)

    def select(self, lang):
        lst = self.carbon.TISCreateInputSourceList(None, False)    # enabled sources only
        try:
            for i in range(self.cf.CFArrayGetCount(lst)):
                src = self.cf.CFArrayGetValueAtIndex(lst, i)
                if lang_of(self._id(src)) == lang:
                    self.carbon.TISSelectInputSource(src)
                    return True
        finally:
            self.cf.CFRelease(lst)
        return False


class _Observer(NSObject):
    def initWithPlatform_(self, platform):
        self = objc.super(_Observer, self).init()
        if self is not None:
            self.platform = platform
        return self

    def layoutChanged_(self, note):
        self.platform._refresh_layout()

    def appChanged_(self, note):
        self.platform._refresh_app()


class MacPlatform:
    can_hold = True

    def __init__(self, tis=None):
        self.c = None
        self._loop = None
        self._tap = None
        self._tis = tis
        self._layout = None          # cached on the main thread
        self._app = ''
        self._caps = False
        self._held = []              # (keycode, flags, down) swallowed during a flip
        self._held_lock = threading.Lock()
        self._replay_seen = 0

    # ---------- start: called on the MAIN thread ----------
    def start(self, controller):
        self.c = controller
        if self._tis is None:
            self._tis = _TIS()
        self._refresh_layout()
        self._refresh_app()
        self._observer = _Observer.alloc().initWithPlatform_(self)
        NSDistributedNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            self._observer, 'layoutChanged:', LAYOUT_CHANGED, None)
        NSWorkspace.sharedWorkspace().notificationCenter().addObserver_selector_name_object_(
            self._observer, 'appChanged:', 'NSWorkspaceDidActivateApplicationNotification', None)
        ready = threading.Event()
        threading.Thread(target=self._run, args=(ready,), daemon=True, name='hafuch-tap').start()
        ready.wait(5)

    def stop(self):
        if self._loop:
            Quartz.CFRunLoopStop(self._loop)

    def run_without_tray(self):
        AppHelper.runConsoleEventLoop(installInterrupt=True)   # main run loop for notifications

    def _refresh_layout(self):
        try:
            self._layout = self._tis.current()
        except Exception:
            self._layout = None

    def _refresh_app(self):
        try:
            app = NSWorkspace.sharedWorkspace().frontmostApplication()
            self._app = (app.localizedName() or '').lower() if app else ''
        except Exception:
            self._app = ''

    # ---------- event tap (own thread) ----------
    def _run(self, ready):
        mask = 0
        for t in (Quartz.kCGEventKeyDown, Quartz.kCGEventKeyUp,
                  Quartz.kCGEventLeftMouseDown, Quartz.kCGEventRightMouseDown):
            mask |= Quartz.CGEventMaskBit(t)
        self._tap = Quartz.CGEventTapCreate(Quartz.kCGSessionEventTap, Quartz.kCGHeadInsertEventTap,
                                            Quartz.kCGEventTapOptionDefault, mask, self._on_event, None)
        if not self._tap:
            print('Hafuch: no permission. Allow it in Privacy & Security > Accessibility + Input Monitoring.')
            ready.set()
            return
        src = Quartz.CFMachPortCreateRunLoopSource(None, self._tap, 0)
        self._loop = Quartz.CFRunLoopGetCurrent()
        Quartz.CFRunLoopAddSource(self._loop, src, Quartz.kCFRunLoopCommonModes)
        Quartz.CGEventTapEnable(self._tap, True)
        ready.set()
        Quartz.CFRunLoopRun()

    def _on_event(self, proxy, etype, event, refcon):
        try:
            if etype in (Quartz.kCGEventTapDisabledByTimeout, Quartz.kCGEventTapDisabledByUserInput):
                Quartz.CGEventTapEnable(self._tap, True)        # macOS turns slow taps off
                return event
            tag = Quartz.CGEventGetIntegerValueField(event, USER_DATA)
            if tag == MAGIC:
                return event                                     # ours
            replay = tag == MAGIC_REPLAY
            if replay:
                self._replay_seen += 1
            is_key = etype in (Quartz.kCGEventKeyDown, Quartz.kCGEventKeyUp)
            if not is_key:
                self.c.on_mouse()
                return event
            kc = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGKeyboardEventKeycode)
            flags = Quartz.CGEventGetFlags(event)
            down = etype == Quartz.kCGEventKeyDown
            if not replay:
                with self._held_lock:
                    if self.c.hold_active():                     # a flip is being typed
                        self._held.append((kc, flags, down))
                        return None
            if not down:
                return event
            mods = set()
            if flags & Quartz.kCGEventFlagMaskShift: mods.add('shift')
            if flags & Quartz.kCGEventFlagMaskControl: mods.add('ctrl')
            if flags & Quartz.kCGEventFlagMaskAlternate: mods.add('alt')
            if flags & Quartz.kCGEventFlagMaskCommand: mods.add('win')
            self._caps = bool(flags & Quartz.kCGEventFlagMaskAlphaShift)
            name = NAMES.get(kc)
            key_id = KEYCODES.get(kc) if name is None else None
            if name is None:
                name = 'char' if key_id else 'other'
            if self.c.on_key(name, key_id, mods, self._app, replay):
                if self.c.holding:                               # the Space that started a flip
                    with self._held_lock:
                        self._held.insert(0, (kc, flags, True))
                return None                                      # swallow
        except Exception:
            pass
        return event

    def release_hold(self):
        """Give back the keys swallowed during a flip, in order, as if typed now."""
        seq = self.c.hold_seq
        while True:
            with self._held_lock:
                if not self._held:
                    self.c.holding = False
                    return
                kc, flags, down = self._held.pop(0)
            seen = self._replay_seen
            self._post(kc, down, flags=flags, tag=MAGIC_REPLAY)
            end = time.time() + 0.2                  # wait until the tap has seen it
            while self._replay_seen == seen and time.time() < end:
                time.sleep(0.001)
            if self.c.hold_seq != seq:
                return                               # a replayed key started the next flip

    # ---------- state ----------
    def caps_lock(self):
        return self._caps

    def foreground_app(self):
        return self._app

    def current_layout(self):
        return self._layout

    def set_layout(self, lang):
        self._layout = lang                                       # optimistic; notification confirms
        AppHelper.callAfter(self._tis.select, lang)              # TIS must run on the main thread
        return True

    # ---------- typing ----------
    def _post(self, keycode, down, text=None, flags=0, tag=MAGIC):
        ev = Quartz.CGEventCreateKeyboardEvent(None, keycode, down)
        if text is not None:
            Quartz.CGEventKeyboardSetUnicodeString(ev, len(text.encode('utf-16-le')) // 2, text)
        Quartz.CGEventSetFlags(ev, flags)
        Quartz.CGEventSetIntegerValueField(ev, USER_DATA, tag)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)

    def send(self, backspaces, text):
        for _ in range(backspaces):
            self._post(KC_DELETE, True); self._post(KC_DELETE, False)
        for ch in text:
            if ch == '\n':
                self._post(KC_RETURN, True); self._post(KC_RETURN, False)
            elif ch == '\t':
                self._post(KC_TAB, True); self._post(KC_TAB, False)
            else:
                self._post(0, True, ch); self._post(0, False, ch)
            time.sleep(0.002)          # some apps drop unicode events sent too fast

    def wait_modifiers_released(self, timeout=1.5):
        end = time.time() + timeout
        mask = (Quartz.kCGEventFlagMaskShift | Quartz.kCGEventFlagMaskControl
                | Quartz.kCGEventFlagMaskAlternate | Quartz.kCGEventFlagMaskCommand)
        while time.time() < end and Quartz.CGEventSourceFlagsState(
                Quartz.kCGEventSourceStateHIDSystemState) & mask:
            time.sleep(0.02)

    def _cmd(self, keycode):
        f = Quartz.kCGEventFlagMaskCommand
        self._post(keycode, True, flags=f); self._post(keycode, False, flags=f)

    # ---------- clipboard ----------
    def copy_selection(self):
        pb = NSPasteboard.generalPasteboard()
        self._saved = pb.stringForType_(NSPasteboardTypeString)
        count = pb.changeCount()
        self._cmd(KC_C)
        end = time.time() + 0.5
        while time.time() < end and pb.changeCount() == count:
            time.sleep(0.02)
        if pb.changeCount() == count:
            return None                                           # nothing selected
        return pb.stringForType_(NSPasteboardTypeString)

    def paste_text(self, text):
        pb = NSPasteboard.generalPasteboard()
        pb.clearContents(); pb.setString_forType_(text, NSPasteboardTypeString)
        self._cmd(KC_V)
        time.sleep(0.25)
        pb.clearContents()
        if getattr(self, '_saved', None):
            pb.setString_forType_(self._saved, NSPasteboardTypeString)


_lock = None


def single_instance():
    import fcntl
    global _lock
    path = os.path.join(os.path.expanduser('~/Library/Application Support/Hafuch'), '.lock')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    _lock = open(path, 'w')
    try:
        fcntl.flock(_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


# ---------- start with the Mac (LaunchAgent) ----------
_AGENT = os.path.expanduser('~/Library/LaunchAgents/com.hafuch.app.plist')


def set_autostart(enable, command):
    """command: path to the app's executable (Hafuch.app/Contents/MacOS/Hafuch)."""
    if not enable:
        if os.path.exists(_AGENT):
            os.remove(_AGENT)
        return
    import plistlib
    os.makedirs(os.path.dirname(_AGENT), exist_ok=True)
    with open(_AGENT, 'wb') as f:
        plistlib.dump({'Label': 'com.hafuch.app', 'ProgramArguments': [command.strip('"')],
                       'RunAtLoad': True}, f)


def get_autostart():
    return os.path.exists(_AGENT)
