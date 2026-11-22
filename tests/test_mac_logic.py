"""Runs platform_mac's logic on any OS against a simulated Mac.

The Apple APIs are replaced by fakes: a fake event tap that feeds every key
(the user's and Hafuch's own) through MacPlatform._on_event, a fake text field
that applies them using the active layout, and fake layout switching. This
proves the Mac glue logic (keycodes, hold/replay, own-event filtering, hotkeys,
clipboard flow) - NOT that the real Apple calls behave. That needs a Mac.
"""
import os
import sys
import threading
import time
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hafuch import keymap  # noqa: E402

# ------------------------------------------------------------------ fakes
SYSTEM = None
Q = types.ModuleType('Quartz')
for i, n in enumerate(['kCGEventKeyDown', 'kCGEventKeyUp', 'kCGEventLeftMouseDown', 'kCGEventRightMouseDown',
                       'kCGEventTapDisabledByTimeout', 'kCGEventTapDisabledByUserInput', 'kCGEventSourceUserData',
                       'kCGKeyboardEventKeycode', 'kCGHIDEventTap', 'kCGSessionEventTap',
                       'kCGHeadInsertEventTap', 'kCGEventTapOptionDefault', 'kCFRunLoopCommonModes',
                       'kCGEventSourceStateHIDSystemState'], start=1):
    setattr(Q, n, 1000 + i)
Q.kCGEventFlagMaskShift, Q.kCGEventFlagMaskControl = 1 << 17, 1 << 18
Q.kCGEventFlagMaskAlternate, Q.kCGEventFlagMaskCommand, Q.kCGEventFlagMaskAlphaShift = 1 << 19, 1 << 20, 1 << 16
Q.CGEventMaskBit = lambda t: 1 << (t - 1000)
Q.CGEventCreateKeyboardEvent = lambda src, kc, down: {'kc': kc, 'down': down, 'flags': 0, 'tag': 0, 'text': None}
Q.CGEventKeyboardSetUnicodeString = lambda ev, n, s: ev.__setitem__('text', s)
Q.CGEventSetFlags = lambda ev, f: ev.__setitem__('flags', f)
Q.CGEventGetFlags = lambda ev: ev['flags']
Q.CGEventSetIntegerValueField = lambda ev, field, v: ev.__setitem__('tag', v)


def _get_field(ev, field):
    return ev['tag'] if field == Q.kCGEventSourceUserData else ev['kc']


Q.CGEventGetIntegerValueField = _get_field
Q.CGEventPost = lambda tap, ev: SYSTEM.deliver(ev)
Q.CGEventSourceFlagsState = lambda state: 0
Q.CGEventTapEnable = lambda tap, on: None


class _Pasteboard:
    def __init__(self):
        self.value, self.count = 'old clipboard', 0

    def stringForType_(self, t): return self.value
    def changeCount(self): return self.count
    def clearContents(self): self.value = None; self.count += 1
    def setString_forType_(self, s, t): self.value = s; self.count += 1


PB = _Pasteboard()
AK = types.ModuleType('AppKit')
AK.NSPasteboardTypeString = 'public.utf8-plain-text'
AK.NSPasteboard = types.SimpleNamespace(generalPasteboard=lambda: PB)
_app = types.SimpleNamespace(localizedName=lambda: 'TextEdit')
_center = types.SimpleNamespace(addObserver_selector_name_object_=lambda *a: None)
AK.NSWorkspace = types.SimpleNamespace(sharedWorkspace=lambda: types.SimpleNamespace(
    frontmostApplication=lambda: _app, notificationCenter=lambda: _center))
FD = types.ModuleType('Foundation')


class _NSObject:
    @classmethod
    def alloc(cls): return cls.__new__(cls)
    def init(self): return self


FD.NSObject = _NSObject
FD.NSDistributedNotificationCenter = types.SimpleNamespace(defaultCenter=lambda: _center)
OBJC = types.ModuleType('objc')
OBJC.super = super
PT = types.ModuleType('PyObjCTools')
PT.AppHelper = types.SimpleNamespace(callAfter=lambda f, *a: f(*a), runConsoleEventLoop=lambda **k: None)
sys.modules.update({'Quartz': Q, 'AppKit': AK, 'Foundation': FD, 'objc': OBJC,
                    'PyObjCTools': PT, 'PyObjCTools.AppHelper': PT.AppHelper})

from hafuch import platform_mac as pm  # noqa: E402
from hafuch.app import Controller  # noqa: E402

KC = {v: k for k, v in pm.KEYCODES.items()}
INV_HE = {v: k for k, v in keymap.HE.items()}


class FakeTIS:
    def current(self): return SYSTEM.layout
    def select(self, lang): SYSTEM.layout = lang; return True


class FakeMac:
    """The OS: routes every event through the tap, then into a text field."""

    def __init__(self, platform):
        self.p = platform
        self.layout = 'en'
        self.text = ''
        self.lock = threading.RLock()

    def deliver(self, ev):
        with self.lock:
            et = Q.kCGEventKeyDown if ev['down'] else Q.kCGEventKeyUp
            if self.p._on_event(None, et, ev, None) is None:
                return                                   # swallowed by the tap
            if not ev['down']:
                return
            if ev['flags'] & Q.kCGEventFlagMaskCommand:
                if ev['kc'] == pm.KC_C:
                    PB.setString_forType_(self.text, None)       # whole field is "selected"
                elif ev['kc'] == pm.KC_V:
                    self.text = PB.value
                return
            if ev['text'] is not None:
                self.text += ev['text']
            elif ev['kc'] == pm.KC_DELETE:
                self.text = self.text[:-1]
            elif ev['kc'] == 49:
                self.text += ' '
            elif ev['kc'] in pm.KEYCODES:
                k, shift = pm.KEYCODES[ev['kc']], bool(ev['flags'] & Q.kCGEventFlagMaskShift)
                self.text += keymap.he_char(k, shift) if self.layout == 'he' else keymap.en_char(k, shift)

    def user(self, kc, flags=0):
        for down in (True, False):
            ev = Q.CGEventCreateKeyboardEvent(None, kc, down)
            ev['flags'] = flags
            self.deliver(ev)

    def type(self, keys, delay=0.0):
        for k in keys:
            self.user(49 if k == ' ' else KC[k])
            if delay:
                time.sleep(delay)


class MacLogicTests(unittest.TestCase):
    def setUp(self):
        global SYSTEM
        self.p = pm.MacPlatform(tis=FakeTIS())
        SYSTEM = self.mac = FakeMac(self.p)
        self.c = Controller(self.p, {'auto_convert': True, 'hotkeys': {
            'convert_word': ['pause', 'ctrl+shift+space'],
            'convert_selection': ['shift+pause']}, 'excluded_apps': ['1password']})
        self.p.c = self.c
        self.p._refresh_layout()
        self.p._refresh_app()

    def settle(self):
        for _ in range(200):
            if self.c.jobs.empty() and not self.c.holding and not self.c.busy:
                time.sleep(0.05)
                if self.c.jobs.empty() and not self.c.holding and not self.c.busy:
                    return
            time.sleep(0.01)

    def test_hebrew_typed_in_english(self):
        self.mac.type('akuo '); self.settle()
        self.assertEqual((self.mac.text, self.mac.layout), ('שלום ', 'he'))

    def test_english_typed_in_hebrew(self):
        self.mac.layout = 'he'; self.p._refresh_layout()
        self.mac.type([INV_HE[c] for c in 'יקךךם'] + [' ']); self.settle()
        self.assertEqual((self.mac.text, self.mac.layout), ('hello ', 'en'))

    def test_real_words_untouched(self):
        self.mac.type('the house '); self.settle()
        self.assertEqual(self.mac.text, 'the house ')

    def test_fast_typing_never_corrupted(self):
        self.mac.type('nhkv ,usv the '); self.settle()
        self.assertEqual((self.mac.text, self.mac.layout), ('מילה תודה the ', 'en'))   # 'the' typed in Hebrew -> flipped back

    def test_hotkey_flips_and_is_swallowed(self):
        self.mac.type('go')
        self.mac.user(49, Q.kCGEventFlagMaskControl | Q.kCGEventFlagMaskShift)   # Ctrl+Shift+Space
        self.settle()
        self.assertEqual((self.mac.text, self.mac.layout), ('עם', 'he'))

    def test_undo_after_auto(self):
        self.mac.type('akuo '); self.settle()
        self.mac.user(113); self.settle()                                      # F15 = Pause
        self.assertEqual((self.mac.text, self.mac.layout), ('akuo ', 'en'))

    def test_selection_and_clipboard_restored(self):
        self.mac.text = 'akuo ,usv'
        PB.value = 'old clipboard'
        self.mac.user(113, Q.kCGEventFlagMaskShift); self.settle()
        self.assertEqual((self.mac.text, self.mac.layout), ('שלום תודה', 'he'))
        self.assertEqual(PB.value, 'old clipboard')

    def test_excluded_app(self):
        self.p._app = '1password'
        self.mac.type('akuo '); self.settle()
        self.assertEqual(self.mac.text, 'akuo ')

    def test_layout_ids(self):
        self.assertEqual(pm.lang_of('com.apple.keylayout.Hebrew-PC'), 'he')
        self.assertEqual(pm.lang_of('com.apple.keylayout.Hebrew'), 'he')
        self.assertIsNone(pm.lang_of('com.apple.keylayout.Hebrew-QWERTY'))
        self.assertEqual(pm.lang_of('com.apple.keylayout.ABC'), 'en')
        self.assertEqual(pm.lang_of('com.apple.keylayout.US'), 'en')
        self.assertIsNone(pm.lang_of('com.apple.keylayout.Dvorak'))

    def test_keycode_table_complete(self):
        self.assertEqual(set(pm.KEYCODES.values()), set(keymap.KEY_IDS))


if __name__ == '__main__':
    unittest.main()
