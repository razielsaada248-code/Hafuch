"""Pure decision logic: no keyboard hooks, no OS calls. Unit-tested in tests/."""
import os
import re
from dataclasses import dataclass

from . import keymap

DATA = os.path.join(os.path.dirname(__file__), 'data')
HE_PREFIXES = set('ושהבכלמ')
_EN_CORE = re.compile(r"^[^a-zA-Z]*([a-zA-Z]+(?:'[a-zA-Z]+)?)[^a-zA-Z]*$")
_HE_CORE = re.compile(r"^[^א-ת]*([א-ת]+)[^א-ת]*$")
_BAD = re.compile(r'[0-9@]|://')


def _load(name):
    out = {}
    with open(os.path.join(DATA, name), encoding='utf-8') as f:
        for line in f:
            w, _, z = line.rstrip('\n').partition('\t')
            out[w] = float(z or 0)
    return out


class Dictionary:
    """Word frequencies (zipf: 7 = very common, 3 = rare, 0 = unknown)."""

    def __init__(self):
        self.freq = {'en': _load('en.txt'), 'he': _load('he.txt')}

    def zipf(self, word, lang):
        f = self.freq[lang]
        if lang == 'en':
            return f.get(word.lower(), 0.0)
        z = f.get(word, 0.0)
        if not z and len(word) >= 4:          # ו/ה/ב/ל/מ/ש/כ + known word
            for i in range(1, min(3, len(word) - 3) + 1):   # stem >= 3 letters
                if word[i - 1] not in HE_PREFIXES:
                    break
                stem = f.get(word[i:], 0.0)
                if stem:
                    return max(stem - 1.5, 0.5)
        return z


@dataclass
class Action:
    backspaces: int
    text: str
    switch_to: str      # 'he' / 'en'
    epoch: int = 0      # set by the controller
    hold: bool = False  # user keys are held back while this is typed


def core(text, lang):
    m = (_HE_CORE if lang == 'he' else _EN_CORE).match(text)
    return m.group(1) if m else None


def bad_hebrew(word):
    """Final letter in the middle of a word = certainly not Hebrew."""
    return any(c in keymap.FINAL_LETTERS for c in word[:-1])


class Engine:
    def __init__(self, dictionary=None, min_len=2):
        self.d = dictionary or Dictionary()
        self.min_len = min_len
        self.keys = []           # current word: list of (key_id, shift)
        self.last = None         # (keys, boundary_char, lang_on_screen) of the word just finished
        self.ignore = set()      # words the user un-converted this session (memory only)

    # ---- buffer ----
    def feed(self, key, shift):
        self.keys.append((key, shift))
        if len(self.keys) > 40:
            self.reset()

    def backspace(self):
        if self.keys:
            self.keys.pop()
        else:
            self.last = None

    def reset(self):
        self.keys = []
        self.last = None

    # ---- decisions ----
    # tuning: how much more common the other reading must be
    MIN_ZIPF_SHORT = 3.5     # 2-letter words: must be really common
    MIN_ZIPF = 2.0
    MARGIN = 1.5             # when the typed text is itself a known word

    def should_convert(self, keys, layout, caps=False):
        """Returns the target language, or None."""
        if not keys or layout not in ('he', 'en') or caps:
            return None
        other = 'en' if layout == 'he' else 'he'
        typed = keymap.render(keys, layout)
        wanted = keymap.render(keys, other)
        if _BAD.search(typed) or _BAD.search(wanted) or typed in self.ignore:
            return None
        t_core, w_core = core(typed, layout), core(wanted, other)
        if not w_core or len(w_core) < self.min_len:
            return None
        if other == 'he' and bad_hebrew(w_core):
            return None
        zw = self.d.zipf(w_core, other)
        if zw < (self.MIN_ZIPF_SHORT if len(w_core) <= 2 else self.MIN_ZIPF):
            return None
        zt = self.d.zipf(t_core, layout) if t_core else 0.0
        if layout == 'he' and t_core and bad_hebrew(t_core):
            zt = 0.0
        if t_core and len(t_core) < len(w_core):
            zt = max(zt - 1.5, 0.0)   # stray symbols around it are letters in the other language
        if t_core and len(w_core) < len(t_core):
            zw -= 1.5                 # same, the other way round (",he" for תיק)
        if zt and zw - zt < self.MARGIN:
            return None
        return other

    def on_boundary(self, boundary, layout, caps=False, auto=True):
        """Space/Tab/Enter typed. Returns Action if the word should be re-typed."""
        keys, self.keys = self.keys, []
        if not keys:
            self.last = None
            return None
        target = self.should_convert(keys, layout, caps) if auto else None
        if target is None:
            self.last = (keys, boundary, layout)
            return None
        text = keymap.render(keys, target)
        self.last = (keys, boundary, target)
        return Action(len(keys) + len(boundary), text + boundary, target)

    def manual(self, layout):
        """Hotkey: flip the current word, or the word just finished (also = undo)."""
        if self.keys:
            keys = self.keys
            target = 'en' if layout == 'he' else 'he'
            self.keys = []
            self.last = (keys, '', target)
            return Action(len(keys), keymap.render(keys, target), target)
        if self.last:
            keys, boundary, shown = self.last
            target = 'en' if shown == 'he' else 'he'
            self.ignore.add(keymap.render(keys, target))   # don't auto-flip it again
            self.last = (keys, boundary, target)
            return Action(len(keys) + len(boundary),
                          keymap.render(keys, target) + boundary, target)
        return None
