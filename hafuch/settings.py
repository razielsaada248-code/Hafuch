"""Settings window. Runs as its own process (`Hafuch --settings`), so its Tk loop
never fights the tray for the main thread (macOS requires both on the main thread).
Exit code 0 = saved; the running Hafuch then reloads config.json.
The tray pauses Hafuch while this window is open, so even the current hotkey
can be pressed here to be recorded.
"""
import os
import sys
import time
import tkinter as tk

from . import config, hotkeys

TITLE = 'Hafuch - הגדרות'
ACTIONS = [('convert_word', 'הפוך את המילה האחרונה'),
           ('convert_selection', 'הפוך טקסט מסומן')]
SLOTS = 2
IS_MAC = sys.platform == 'darwin'
DEBUG = os.environ.get('HAFUCH_DEBUG_KEYS') == '1'
FONT = ('Segoe UI', 10) if sys.platform == 'win32' else ('Helvetica', 13)
BOLD = (FONT[0], FONT[1], 'bold')

# ---- turning a Tk key event into our key names ----
WIN_MOD_VK = {0x10: 'shift', 0xA0: 'shift', 0xA1: 'shift', 0x11: 'ctrl', 0xA2: 'ctrl', 0xA3: 'ctrl',
              0x12: 'alt', 0xA4: 'alt', 0xA5: 'alt', 0x5B: 'win', 0x5C: 'win'}
MOD_KEYSYMS = {'Shift_L': 'shift', 'Shift_R': 'shift', 'Control_L': 'ctrl', 'Control_R': 'ctrl',
               'Alt_L': 'alt', 'Alt_R': 'alt', 'Option_L': 'alt', 'Option_R': 'alt',
               'Meta_L': 'win', 'Meta_R': 'win', 'Super_L': 'win', 'Super_R': 'win',
               'Win_L': 'win', 'Win_R': 'win', 'Command': 'win'}


def key_from_event(event):
    """Returns ('mod', name) for a modifier, ('key', name) for a real key, or (None, None)."""
    if event.keysym in MOD_KEYSYMS:
        return 'mod', MOD_KEYSYMS[event.keysym]
    if sys.platform == 'win32':
        vk = event.keycode
        if vk in WIN_MOD_VK:
            return 'mod', WIN_MOD_VK[vk]
        if vk in (0x13, 0x03):
            return 'key', 'pause'
        if 0x70 <= vk <= 0x87:
            return 'key', f'f{vk - 0x6F}'
        named = {0x20: 'space', 0x09: 'tab', 0x0D: 'enter', 0x1B: 'escape'}
        if vk in named:
            return 'key', named[vk]
        from .platform_win import VK            # layout-independent: same key in Hebrew or English
        return ('key', VK[vk]) if vk in VK else (None, None)
    ks = event.keysym
    low = {'space': 'space', 'Tab': 'tab', 'Return': 'enter', 'Escape': 'escape', 'Pause': 'pause',
           'F15': 'pause'}
    if ks in low:
        return 'key', low[ks]
    if ks[0] == 'F' and ks[1:].isdigit():
        return 'key', ks.lower()
    if len(ks) == 1 and ks.isascii():
        return 'key', ks.lower()
    return None, None


def mods_from_state(state):
    mods = set()
    if state & 0x1:
        mods.add('shift')
    if state & 0x4:
        mods.add('ctrl')
    if IS_MAC:
        if state & 0x10: mods.add('alt')
        if state & 0x8: mods.add('win')
    elif state & 0x20000:
        mods.add('alt')
    return mods


class SettingsWindow:
    def __init__(self, root):
        self.root = root
        self.cfg = config.load()
        self.values = {a: list(self.cfg['hotkeys'].get(a, []))[:SLOTS] for a, _ in ACTIONS}
        for a in self.values:
            self.values[a] += [''] * (SLOTS - len(self.values[a]))
        self.capturing = None
        self.capture_since = 0.0
        self.held = set()
        self.saved = False

        root.title(TITLE)
        root.resizable(False, False)
        root.configure(padx=18, pady=14)
        root.option_add('*Font', FONT)

        tk.Label(root, text='קיצורי מקלדת', font=BOLD, anchor='e').grid(row=0, column=0, columnspan=4, sticky='e')
        tk.Label(root, text='לוחצים "שנה" ואז את הצירוף החדש', fg='#555',
                 anchor='e').grid(row=1, column=0, columnspan=4, sticky='e', pady=(0, 8))

        self.labels = {}
        row = 2
        for action, title in ACTIONS:
            tk.Label(root, text=title, anchor='e').grid(row=row, column=3, sticky='e', padx=(10, 0))
            for i in range(SLOTS):
                lab = tk.Label(root, width=22, relief='groove', bg='white', anchor='center')
                lab.grid(row=row, column=2, pady=3)
                tk.Button(root, text='שנה', width=6,
                          command=lambda a=action, k=i: self.start_capture(a, k)).grid(row=row, column=1, padx=6)
                tk.Button(root, text='נקה', width=5,
                          command=lambda a=action, k=i: self.set_slot(a, k, '')).grid(row=row, column=0)
                self.labels[(action, i)] = lab
                row += 1
            row += 1

        self.status = tk.Label(root, text='', fg='#b42318', anchor='e')
        self.status.grid(row=row, column=0, columnspan=4, sticky='e', pady=(2, 6))
        row += 1

        self.auto = tk.BooleanVar(value=bool(self.cfg.get('auto_convert')))
        self._check(row, 'החלפה אוטומטית אחרי רווח', self.auto)
        row += 1

        self.autostart_mod = self._autostart_module()
        if self.autostart_mod:
            self.autostart = tk.BooleanVar(value=self.autostart_mod.get_autostart())
            self._check(row, 'הפעל עם המחשב', self.autostart)
            row += 1

        bar = tk.Frame(root)
        bar.grid(row=row, column=0, columnspan=4, sticky='ew', pady=(14, 0))
        tk.Button(bar, text='שמור', width=10, command=self.save, default='active').pack(side='right')
        tk.Button(bar, text='ביטול', width=10, command=root.destroy).pack(side='right', padx=6)
        tk.Button(bar, text='ברירת מחדל', command=self.defaults).pack(side='left')

        root.bind('<KeyPress>', self.on_press)
        root.bind('<KeyRelease>', self.on_release)
        root.bind('<FocusOut>', lambda e: self.held.clear())
        self.refresh()

    def _check(self, row, text, var):
        """Right-to-left checkbox: the box on the right of its text."""
        f = tk.Frame(self.root)
        f.grid(row=row, column=0, columnspan=4, sticky='e')
        cb = tk.Checkbutton(f, variable=var)
        cb.pack(side='right')
        lab = tk.Label(f, text=text)
        lab.pack(side='right')
        lab.bind('<Button-1>', lambda e: cb.invoke())

    @staticmethod
    def _autostart_module():
        if not getattr(sys, 'frozen', False):
            return None                             # only the installed app can start itself
        if sys.platform == 'win32':
            from . import platform_win as m
        elif IS_MAC:
            from . import platform_mac as m
        else:
            return None
        return m if hasattr(m, 'set_autostart') else None

    # ---- slots ----
    def refresh(self):
        for (action, i), lab in self.labels.items():
            if self.capturing == (action, i):
                lab.configure(text='לחץ על הצירוף...', bg='#fff7d6')
            else:
                v = self.values[action][i]
                lab.configure(text=hotkeys.display(v) if v else '—', bg='white')

    def set_slot(self, action, i, value):
        self.values[action][i] = value
        self.capturing = None
        self.status.configure(text='')
        self.refresh()

    def start_capture(self, action, i):
        self.capturing = (action, i)
        self.capture_since = time.time()
        self.held.clear()
        self.status.configure(text='')
        self.refresh()
        self.root.focus_force()

    def others(self, action, i):
        return [v for (a, k), _ in self.labels.items() for v in [self.values[a][k]]
                if v and (a, k) != (action, i)]

    # ---- keys ----
    def on_press(self, event):
        kind, name = key_from_event(event)
        if DEBUG:                               # what the system really sends (setup only, never while typing elsewhere)
            print('key', repr(event.keysym), hex(event.keycode), hex(event.state), '->', kind, name, flush=True)
        if not self.capturing:
            if name == 'enter' and not (self.held | mods_from_state(event.state)):
                self.save()
            elif name == 'escape':
                self.root.destroy()
            return
        if name in ('space', 'enter') and time.time() - self.capture_since < 0.4:
            return 'break'                      # the key that pressed the "שנה" button itself
        if kind == 'mod':
            self.held.add(name)
            mods = self.held | mods_from_state(event.state)
            self.labels[self.capturing].configure(
                text='+'.join(hotkeys.display(m + '+x').split('+')[0] for m in hotkeys.MOD_ORDER if m in mods) + '+...')
            return 'break'
        if kind is None:
            self.status.configure(text=f'המקש הזה לא נתמך ({event.keysym})')
            return 'break'
        mods = self.held | mods_from_state(event.state)
        if name == 'escape' and not mods:
            self.capturing = None
            self.refresh()
            return 'break'
        combo = hotkeys.build(mods, name)
        reason = hotkeys.problem(combo, self.others(*self.capturing))
        if reason:
            self.status.configure(text=f'{hotkeys.display(combo)}: {reason}')
            return 'break'
        self.set_slot(*self.capturing, combo)
        return 'break'

    def on_release(self, event):
        kind, name = key_from_event(event)
        if kind == 'mod':
            self.held.discard(name)

    # ---- buttons ----
    def defaults(self):
        for action, _ in ACTIONS:
            vals = list(config.DEFAULTS['hotkeys'][action])[:SLOTS]
            self.values[action] = vals + [''] * (SLOTS - len(vals))
        self.auto.set(config.DEFAULTS['auto_convert'])
        self.capturing = None
        self.status.configure(text='')
        self.refresh()

    def save(self):
        if not any(self.values['convert_word']):
            self.status.configure(text='צריך לפחות קיצור אחד ל"הפוך את המילה האחרונה"')
            return
        for action, _ in ACTIONS:
            self.cfg['hotkeys'][action] = [v for v in self.values[action] if v]
        self.cfg['auto_convert'] = bool(self.auto.get())
        config.save(self.cfg)
        if self.autostart_mod and self.autostart.get() != self.autostart_mod.get_autostart():
            self.autostart_mod.set_autostart(self.autostart.get(), f'"{sys.executable}"')
        self.saved = True
        self.root.destroy()


def run():
    root = tk.Tk()
    if sys.platform == 'win32':
        try:
            root.iconbitmap(default=_icon_path())
        except tk.TclError:
            pass
    w = SettingsWindow(root)
    root.lift()
    root.attributes('-topmost', True)
    root.after(300, lambda: root.attributes('-topmost', False))
    root.mainloop()
    return 0 if w.saved else 1


def _icon_path():
    import os
    return os.path.join(os.path.dirname(__file__), 'data', 'icon.ico')
