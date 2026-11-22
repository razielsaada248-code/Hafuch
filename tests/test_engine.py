import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from hafuch import engine, keymap  # noqa: E402

INV = {v: k for k, v in keymap.HE.items()}


def keys_from_en(text):
    return [(c.lower(), c.isupper()) for c in text]


def keys_from_he(text):
    return [(INV[c], False) for c in text]


class KeymapTests(unittest.TestCase):
    def test_hebrew_letters_on_punctuation_keys(self):
        self.assertEqual(keymap.render(keys_from_en(',.;'), 'he'), 'תץף')
        self.assertEqual(keymap.render(keys_from_en("w/q'"), 'he'), "'./,")

    def test_render_both_ways(self):
        self.assertEqual(keymap.render(keys_from_en('akuo'), 'he'), 'שלום')
        self.assertEqual(keymap.render(keys_from_he('יקךךם'), 'en'), 'hello')

    def test_shift_gives_english_capitals(self):
        self.assertEqual(keymap.render([('a', True)], 'he'), 'A')

    def test_convert_selection(self):
        self.assertEqual(keymap.convert_text('akuo ,usv'), ('שלום תודה', 'he'))
        self.assertEqual(keymap.convert_text('יקךךם'), ('hello', 'en'))


class EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.d = engine.Dictionary()

    def setUp(self):
        self.e = engine.Engine(self.d)

    def type(self, keys):
        for k, s in keys:
            self.e.feed(k, s)

    def test_hebrew_typed_in_english(self):
        self.type(keys_from_en('akuo'))
        a = self.e.on_boundary(' ', 'en')
        self.assertEqual((a.backspaces, a.text, a.switch_to), (5, 'שלום ', 'he'))

    def test_english_typed_in_hebrew(self):
        self.type(keys_from_he('יקךךם'))
        a = self.e.on_boundary(' ', 'he')
        self.assertEqual((a.backspaces, a.text, a.switch_to), (6, 'hello ', 'en'))

    def test_punctuation_key_inside_hebrew_word(self):
        self.type(keys_from_en(',usv'))          # תודה
        self.assertEqual(self.e.on_boundary(' ', 'en').text, 'תודה ')

    def test_real_words_stay(self):
        for w in ('hello', 'world', 'the', 'house', 'computer'):
            self.type(keys_from_en(w))
            self.assertIsNone(self.e.on_boundary(' ', 'en'), w)
        for w in ('שלום', 'תודה', 'מחשב', 'ובבית'):
            self.type(keys_from_he(w))
            self.assertIsNone(self.e.on_boundary(' ', 'he'), w)

    def test_skip_numbers_emails_links(self):
        for t in ('a1b2', 'me@x', 'http://x'):
            self.type(keys_from_en(t))
            self.assertIsNone(self.e.on_boundary(' ', 'en'), t)

    def test_caps_lock_and_unknown_layout_never_convert(self):
        self.type(keys_from_en('akuo'))
        self.assertIsNone(self.e.on_boundary(' ', 'en', caps=True))
        self.type(keys_from_en('akuo'))
        self.assertIsNone(self.e.on_boundary(' ', None))

    def test_auto_off(self):
        self.type(keys_from_en('akuo'))
        self.assertIsNone(self.e.on_boundary(' ', 'en', auto=False))

    def test_backspace_edits_buffer(self):
        self.type(keys_from_en('akuox'))
        self.e.backspace()
        self.assertEqual(self.e.on_boundary(' ', 'en').text, 'שלום ')

    def test_manual_current_word(self):
        self.type(keys_from_en('go'))
        a = self.e.manual('en')
        self.assertEqual((a.backspaces, a.text, a.switch_to), (2, 'עם', 'he'))

    def test_manual_after_auto_is_undo_and_remembered(self):
        self.type(keys_from_en('akuo'))
        self.e.on_boundary(' ', 'en')             # -> שלום
        a = self.e.manual('he')
        self.assertEqual((a.backspaces, a.text, a.switch_to), (5, 'akuo ', 'en'))
        self.type(keys_from_en('akuo'))
        self.assertIsNone(self.e.on_boundary(' ', 'en'))   # not flipped again this session

    def test_manual_previous_word(self):
        self.type(keys_from_en('go'))
        self.e.on_boundary(' ', 'en')
        a = self.e.manual('en')
        self.assertEqual((a.backspaces, a.text), (3, 'עם '))

    def test_reset_forgets(self):
        self.type(keys_from_en('akuo'))
        self.e.reset()
        self.assertIsNone(self.e.manual('en'))


if __name__ == '__main__':
    unittest.main()
