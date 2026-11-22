import os
import sys
import tempfile
import types
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hafuch import hotkeys  # noqa: E402


class HotkeyStrings(unittest.TestCase):
    def test_build_orders_modifiers(self):
        self.assertEqual(hotkeys.build({'shift', 'ctrl'}, 'space'), 'ctrl+shift+space')
        self.assertEqual(hotkeys.normalize('Shift + Ctrl + Space'), 'ctrl+shift+space')

    def test_display(self):
        self.assertEqual(hotkeys.display('ctrl+shift+space', mac=False), 'Ctrl+Shift+Space')
        self.assertEqual(hotkeys.display('pause', mac=True), 'F15')
        self.assertEqual(hotkeys.display('alt+win+k', mac=True), 'Option+Cmd+K')
        self.assertEqual(hotkeys.display('f9', mac=False), 'F9')

    def test_allowed(self):
        for ok in ['pause', 'shift+pause', 'f9', 'ctrl+shift+space', 'ctrl+alt+h', 'win+shift+z']:
            self.assertIsNone(hotkeys.problem(ok), ok)

    def test_rejected(self):
        self.assertIsNotNone(hotkeys.problem(''))
        self.assertIsNotNone(hotkeys.problem('ctrl+shift'))      # modifiers only
        self.assertIsNotNone(hotkeys.problem('k'))               # would block typing
        self.assertIsNotNone(hotkeys.problem('shift+k'))
        self.assertIsNotNone(hotkeys.problem('space'))
        self.assertIsNotNone(hotkeys.problem('ctrl+c'))          # reserved
        self.assertIsNotNone(hotkeys.problem('alt+tab'))
        self.assertIsNotNone(hotkeys.problem('alt+shift+k'))     # Windows language switch
        self.assertIsNotNone(hotkeys.problem('ctrl+shift+space', ['shift+ctrl+space']))  # duplicate

    def test_controller_reload(self):
        from hafuch.app import Controller
        p = types.SimpleNamespace(can_hold=False)
        c = Controller(p, {'hotkeys': {'convert_word': ['pause']}, 'auto_convert': False})
        self.assertEqual(c.hotkeys, {(frozenset(), 'pause'): 'convert_word'})
        c.reload({'hotkeys': {'convert_word': ['ctrl+alt+h', ''], 'convert_selection': ['f9']},
                  'auto_convert': True})
        self.assertEqual(c.hotkeys[(frozenset({'ctrl', 'alt'}), 'h')], 'convert_word')
        self.assertEqual(c.hotkeys[(frozenset(), 'f9')], 'convert_selection')
        self.assertNotIn((frozenset(), 'pause'), c.hotkeys)
        self.assertTrue(c.auto)

    def test_suspended_ignores_keys(self):
        from hafuch.app import Controller
        p = types.SimpleNamespace(can_hold=False)
        c = Controller(p, {'hotkeys': {'convert_word': ['pause']}})
        import queue
        c.jobs = queue.Queue()                 # the worker keeps waiting on the old queue
        c.suspended = True
        self.assertFalse(c.on_key('pause', None, set(), 1))
        self.assertTrue(c.jobs.empty())
        c.suspended = False
        self.assertTrue(c.on_key('pause', None, set(), 1))


class SettingsWindow(unittest.TestCase):
    """Drives the real Tk window with fake key events."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix='hafuch-set-')
        os.environ['HAFUCH_CONFIG_DIR'] = self.dir
        import tkinter as tk
        from hafuch import settings
        self.settings = settings
        try:
            self.root = tk.Tk()
        except tk.TclError:
            self.skipTest('no display')
        self.root.withdraw()
        self.w = settings.SettingsWindow(self.root)

    def tearDown(self):
        os.environ.pop('HAFUCH_CONFIG_DIR', None)
        try:
            self.root.destroy()
        except Exception:
            pass

    def key(self, keysym, keycode, state=0):
        ev = types.SimpleNamespace(keysym=keysym, keycode=keycode, state=state)
        return self.w.on_press(ev)

    def test_capture_and_save(self):
        from hafuch import config
        win = sys.platform == 'win32'
        self.w.start_capture('convert_word', 0)
        self.key('Control_L', 0x11 if win else 0)
        self.key('Alt_L', 0x12 if win else 0)
        self.key('h', 0x48 if win else 0)
        self.assertEqual(self.w.values['convert_word'][0], 'ctrl+alt+h')
        self.assertIsNone(self.w.capturing)
        # a bad one is refused and the slot stays as it was
        self.w.held.clear()
        self.w.start_capture('convert_word', 1)
        self.key('c', 0x43 if win else 0, state=0x4)           # Ctrl+C
        self.assertEqual(self.w.values['convert_word'][1], 'ctrl+shift+space')
        self.assertTrue(self.w.status.cget('text'))
        self.key('Escape', 0x1B if win else 0)
        self.assertIsNone(self.w.capturing)
        self.w.save()
        self.assertEqual(config.load()['hotkeys']['convert_word'], ['ctrl+alt+h', 'ctrl+shift+space'])

    def test_pause_and_fkey(self):
        win = sys.platform == 'win32'
        self.w.start_capture('convert_selection', 0)
        self.key('F9', 0x78 if win else 0)
        self.assertEqual(self.w.values['convert_selection'][0], 'f9')
        self.w.start_capture('convert_word', 0)
        self.key('Pause', 0x13 if win else 0)
        self.assertEqual(self.w.values['convert_word'][0], 'pause')

    def test_cleared_slot_stays_cleared(self):
        from hafuch import config
        self.w.set_slot('convert_selection', 0, '')
        self.w.set_slot('convert_selection', 1, '')
        self.w.save()
        self.assertEqual(config.load()['hotkeys']['convert_selection'], [])

    def test_needs_one_word_hotkey(self):
        from hafuch import config
        self.w.set_slot('convert_word', 0, '')
        self.w.set_slot('convert_word', 1, '')
        self.w.save()
        self.assertFalse(self.w.saved)
        self.assertEqual(config.load()['hotkeys']['convert_word'], config.DEFAULTS['hotkeys']['convert_word'])


if __name__ == '__main__':
    unittest.main()
