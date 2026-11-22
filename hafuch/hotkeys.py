"""Hotkey strings ("ctrl+shift+space") - parsing, display, validation. Pure, unit-tested."""
import sys

MOD_ORDER = ['ctrl', 'alt', 'shift', 'win']
NAMED = ['pause', 'space', 'tab', 'enter'] + [f'f{i}' for i in range(1, 25)]

# Shortcuts the system or almost every app already uses
RESERVED = {
    'alt+tab', 'alt+space', 'alt+f4', 'win+space', 'ctrl+alt+delete', 'shift+tab', 'ctrl+tab',
    'ctrl+a', 'ctrl+c', 'ctrl+v', 'ctrl+x', 'ctrl+z', 'ctrl+y', 'ctrl+s', 'ctrl+f', 'ctrl+p',
    'ctrl+n', 'ctrl+w', 'ctrl+t', 'ctrl+o', 'ctrl+enter', 'shift+enter', 'shift+space',
    'win+c', 'win+v', 'win+x', 'win+q', 'win+tab', 'win+a', 'win+s', 'win+z', 'win+w',  # Cmd+... on Mac
}


def parse(s):
    parts = [p for p in s.lower().replace(' ', '').split('+') if p] if s else []
    if not parts:
        return frozenset(), ''
    return frozenset(p for p in parts[:-1]), parts[-1]


def build(mods, key):
    return '+'.join([m for m in MOD_ORDER if m in mods] + [key])


def normalize(s):
    mods, key = parse(s)
    return build(mods, key)


def display(s, mac=None):
    mac = sys.platform == 'darwin' if mac is None else mac
    names = {'ctrl': 'Ctrl', 'alt': 'Option' if mac else 'Alt', 'shift': 'Shift',
             'win': 'Cmd' if mac else 'Win', 'space': 'Space', 'pause': 'F15' if mac else 'Pause',
             'tab': 'Tab', 'enter': 'Enter'}
    mods, key = parse(s)
    parts = [names[m] for m in MOD_ORDER if m in mods]
    k = names.get(key) or (key.upper() if len(key) > 1 else key.upper())
    return '+'.join(parts + [k])


def problem(s, others=()):
    """Hebrew reason why this hotkey can't be used, or None if it's fine."""
    mods, key = parse(s)
    if not key:
        return 'לא נבחר מקש'
    if key in MOD_ORDER:
        return 'צריך מקש אחד אמיתי, לא רק Ctrl/Shift/Alt'
    if key not in NAMED and len(key) != 1:
        return 'המקש הזה לא נתמך'
    alone_ok = key == 'pause' or (key[0] == 'f' and key[1:].isdigit())   # Pause / F-keys
    if not alone_ok and not (mods - {'shift'}):
        return 'בלי Ctrl, Alt או Win הקיצור יפריע להקלדה רגילה'
    if mods == {'alt', 'shift'}:
        return 'Alt+Shift מחליף שפה בווינדוס. צריך להוסיף Ctrl או לבחור צירוף אחר'
    if build(mods, key) in RESERVED:
        return 'הקיצור הזה כבר תפוס במערכת או ברוב התוכנות'
    if build(mods, key) in {normalize(o) for o in others if o}:
        return 'הקיצור הזה כבר בשימוש לפעולה אחרת'
    return None
