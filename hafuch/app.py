"""Controller: glues the platform layer (keyboard hook, injection, layouts) to the engine.

Platform contract (platform_win / platform_mac):
    start(controller) / stop()
    current_layout() -> 'he' | 'en' | None
    set_layout(lang)
    send(backspaces, text)                    # one atomic batch, marked as ours
    copy_selection() -> str | None ; paste_text(text)
    wait_modifiers_released()
    foreground_app() -> lower-case process name
    caps_lock() -> bool

The hook thread calls on_key()/on_mouse(); they must return fast. All typing
happens on the worker thread. Typed text is kept in memory only, never logged
to disk.
"""
import os
import queue
import threading
import time

from . import keymap
from .engine import Engine

DEBUG = os.environ.get('HAFUCH_DEBUG_KEYS') == '1'
BOUNDARIES = {'space': ' ', 'tab': '\t', 'enter': '\n'}
AUTO_BOUNDARIES = {'space'}      # Enter may already have sent a chat message
# A bare modifier press must not reset: Ctrl+Shift+Space starts with Ctrl alone.
# Real combos (Ctrl+C ...) still reset, via the mods check.
IGNORED = {'shift', 'capslock', 'ctrl', 'alt', 'win'}


from .hotkeys import parse as parse_hotkey  # noqa: E402


class Controller:
    def __init__(self, platform, cfg, dry_run=False):
        self.p = platform
        self.cfg = cfg
        self.dry_run = dry_run
        self.engine = Engine(min_len=cfg.get('min_word_length', 2))
        self.enabled = True                    # whole app (tray pause)
        self.suspended = False                 # settings window open: keys there are being recorded
        self.auto = cfg.get('auto_convert', True)
        self.jobs = queue.Queue()
        self.window = None
        self.lock = threading.Lock()           # engine is shared by hook + worker threads
        self.epoch = 0                         # bumps on anything except a plain letter
        # "hold": while an automatic flip is being typed, the platform swallows the
        # user's keys and replays them right after, so nothing interleaves.
        self.holding = False
        self.can_hold = getattr(platform, 'can_hold', False)
        self.hold_seq = 0
        self.hold_since = 0.0                      # +1 each time a hold starts (see release_hold)
        self.busy = False                      # worker is running a job (tests wait on it)
        self.on_change = lambda: None          # tray refresh
        self._load_hotkeys()
        threading.Thread(target=self._worker, daemon=True, name='hafuch-worker').start()

    def _load_hotkeys(self):
        hk = {}
        for action, keys in self.cfg.get('hotkeys', {}).items():
            for k in ([keys] if isinstance(keys, str) else keys):
                if k:
                    hk[parse_hotkey(k)] = action
        self.hotkeys = hk                      # swapped in one step (the hook thread reads it)

    def reload(self, cfg):
        """Settings were saved in the settings window: take the new values now."""
        with self.lock:
            self.cfg = cfg
            self.auto = cfg.get('auto_convert', False)
            self.engine.min_len = cfg.get('min_word_length', 2)
            self.engine.reset()
            self._load_hotkeys()
        self.on_change()

    # ---------- called on the hook thread ----------
    def on_key(self, name, key_id, mods, window, replay=False):
        """name: 'char', 'space', 'backspace', 'pause', ... ; key_id for 'char';
        mods: set of 'shift','ctrl','alt','win'. replay: a key we held and gave back.
        Returns True to swallow the key."""
        if not self.enabled or self.suspended:
            return False
        if DEBUG and name != 'char':           # tests only: control keys, never letters
            print('key', name, sorted(mods), 'replay' if replay else '', flush=True)
        with self.lock:
            if replay and name in BOUNDARIES and not self.engine.keys and self.engine.last:
                return False                   # the held Space itself - keep "last word" for undo
            return self._on_key(name, key_id, mods, window)

    def _on_key(self, name, key_id, mods, window):
        if name != 'char' or mods & {'ctrl', 'alt', 'win'}:
            self.epoch += 1
        if window != self.window:
            self.window = window
            self.engine.reset()

        hk = (frozenset(mods), key_id if name == 'char' else name)
        action = self.hotkeys.get(hk)
        if action:
            self.jobs.put(action)
            return True

        if name in IGNORED:
            return False                       # a modifier on its own (even Shift while Ctrl is held)
        if mods & {'ctrl', 'alt', 'win'}:
            self.engine.reset()
        elif name == 'char':
            self.engine.feed(key_id, 'shift' in mods)
        elif name == 'backspace':
            self.engine.backspace()
        elif name in BOUNDARIES:
            return self._boundary(name)
        else:
            self.engine.reset()                # arrows, Home, Delete, F-keys ...
        return False

    def hold_active(self):
        """Platforms hold keys only while this is True. Safety net: never longer
        than 1 second, so a failed flip can't leave the keyboard dead."""
        return self.holding and time.time() - self.hold_since < 1.0

    def on_mouse(self):
        with self.lock:
            self.epoch += 1
            self.engine.reset()

    def _boundary(self, name):
        excluded = self._excluded()
        layout = None if excluded else self.p.current_layout()
        auto = self.auto and not excluded and name in AUTO_BOUNDARIES
        act = self.engine.on_boundary(BOUNDARIES[name], layout, self.p.caps_lock(), auto)
        if not act:
            return False
        act.epoch = self.epoch
        act.hold = self.can_hold and not self.dry_run
        if act.hold:
            # swallow the Space: it is replayed after the fix, so the fix erases
            # only the word and nothing typed later can slip in between
            n = len(BOUNDARIES[name])
            act.backspaces -= n
            act.text = act.text[:-n]
            self.holding = True
            self.hold_seq += 1
            self.hold_since = time.time()
        self.jobs.put(act)
        return act.hold

    def _excluded(self):
        app = (self.p.foreground_app() or '').lower()
        return app in set(self.cfg.get('excluded_apps', []))

    # ---------- worker thread ----------
    def _worker(self):
        while True:
            job = self.jobs.get()
            self.busy = True
            try:
                if job in ('convert_word', 'convert_selection') and hasattr(self.p, 'mask_modifiers'):
                    self.p.mask_modifiers()
                if job == 'convert_word':
                    self._manual_word()
                elif job == 'convert_selection':
                    self._selection()
                elif job.hold:
                    try:
                        self._apply_auto(job)
                    finally:
                        self.p.release_hold()   # always give the user's keys back
                else:
                    time.sleep(0.02)           # let the real Space reach the app first
                    self._apply_auto(job)
            except Exception as e:              # never let the worker die
                print('hafuch worker error:', type(e).__name__)
            finally:
                self.busy = not self.jobs.empty()

    def _apply_auto(self, act):
        """(Without hold, i.e. Mac.) The user may have kept typing since the space. Letters typed after it
        are re-typed in the new language too; anything else (Backspace, another
        space, a click) cancels the flip rather than risk deleting real text."""
        with self.lock:
            if self.epoch != act.epoch:
                return
            extra = list(self.engine.keys)
        act.backspaces += len(extra)
        act.text += keymap.render(extra, act.switch_to)
        self._apply(act)

    def _apply(self, act):
        if self.dry_run:
            print(f'[dry-run] would erase {act.backspaces}, type {act.text!r}, switch to {act.switch_to}')
            return
        self.p.send(act.backspaces, act.text)
        self.p.set_layout(act.switch_to)

    def _manual_word(self):
        if self._excluded():
            return
        self.p.wait_modifiers_released()
        layout = self.p.current_layout() or 'en'
        with self.lock:
            self.epoch += 1
            act = self.engine.manual(layout)
        if act:
            self._apply(act)

    def _selection(self):
        if self._excluded():
            return
        self.p.wait_modifiers_released()
        text = self.p.copy_selection()
        if not text:
            return
        new, target = keymap.convert_text(text)
        with self.lock:
            self.epoch += 1
            self.engine.reset()
        if self.dry_run:
            print(f'[dry-run] selection -> {target}')
            return
        self.p.paste_text(new)
        self.p.set_layout(target)

    # ---------- tray ----------
    def toggle_enabled(self):
        self.enabled = not self.enabled
        with self.lock:
            self.engine.reset()
        self.on_change()

    def toggle_auto(self):
        self.auto = not self.auto
        self.cfg['auto_convert'] = self.auto
        from . import config
        config.save(self.cfg)
        self.on_change()
