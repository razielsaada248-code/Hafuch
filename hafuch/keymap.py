"""Physical keys -> English / Hebrew characters.

A "key id" is the character the key prints on a US keyboard without Shift
('a', ',', ';' ...). Platform layers translate their scan codes to key ids,
so the engine never depends on which layout is active.
Hebrew = the standard Israeli layout (SI-1452, Windows "Hebrew" / Mac "Hebrew - PC").
"""

KEY_IDS = list("`1234567890-=qwertyuiop[]\\asdfghjkl;'zxcvbnm,./")

EN_SHIFT = {
    '`': '~', '1': '!', '2': '@', '3': '#', '4': '$', '5': '%', '6': '^',
    '7': '&', '8': '*', '9': '(', '0': ')', '-': '_', '=': '+', '[': '{',
    ']': '}', '\\': '|', ';': ':', "'": '"', ',': '<', '.': '>', '/': '?',
}

HE = {
    '`': ';', 'q': '/', 'w': "'", 'e': 'ק', 'r': 'ר', 't': 'א', 'y': 'ט',
    'u': 'ו', 'i': 'ן', 'o': 'ם', 'p': 'פ', '[': ']', ']': '[',
    'a': 'ש', 's': 'ד', 'd': 'ג', 'f': 'כ', 'g': 'ע', 'h': 'י', 'j': 'ח',
    'k': 'ל', 'l': 'ך', ';': 'ף', "'": ',',
    'z': 'ז', 'x': 'ס', 'c': 'ב', 'v': 'ה', 'b': 'נ', 'n': 'מ', 'm': 'צ',
    ',': 'ת', '.': 'ץ', '/': '.',
}

HEBREW_LETTERS = set('אבגדהוזחטיכךלמםנןסעפףצץקרשת')
FINAL_LETTERS = set('ךםןףץ')


def en_char(key, shift=False, caps=False):
    if key.isalpha():
        return key.upper() if shift != caps else key
    return EN_SHIFT.get(key, key) if shift else key


def he_char(key, shift=False):
    if shift:  # Shift in the Hebrew layout gives English capitals / US symbols
        return key.upper() if key.isalpha() else EN_SHIFT.get(key, key)
    return HE.get(key, key)


def render(keys, lang, caps=False):
    """keys: list of (key_id, shift)."""
    if lang == 'he':
        return ''.join(he_char(k, s) for k, s in keys)
    return ''.join(en_char(k, s, caps) for k, s in keys)


# ---- converting text that is already on screen (selection) ----
_HE_TO_KEY = {v: k for k, v in HE.items()}
_HE_TO_KEY["'"] = 'w'


def convert_text(text):
    """Re-type text as if the other layout had been active. Returns (new_text, target_lang)."""
    he = sum(c in HEBREW_LETTERS for c in text)
    latin = sum(c.isascii() and c.isalpha() for c in text)
    if he > latin:
        return ''.join(_HE_TO_KEY.get(c, c) for c in text), 'en'
    return ''.join(HE.get(c.lower(), c) for c in text), 'he'
