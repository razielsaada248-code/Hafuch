# Hafuch - הפוך

Fixes words typed in the wrong keyboard layout, Hebrew ↔ English, for Windows and macOS.
Typed `akuo` instead of שלום? Press **Pause** (or **Ctrl+Shift+Space**) and the word flips, and the keyboard switches to the right language.

כתבת באנגלית במקום בעברית? לוחצים Pause והמילה מתהפכת, והמקלדת עוברת לשפה הנכונה.

- Manual by default; optional automatic mode after Space
- **Shift+Pause** flips selected text
- Shortcuts can be changed in the settings window (tray icon > הגדרות...)
- What you type stays in memory only until the end of the word. Nothing is saved or sent anywhere

## Download
- Windows: build from source (below)
- macOS (experimental, not yet tested by a person): [Releases > mac-latest](../../releases/tag/mac-latest)

## Run from source
```
pip install -r requirements.txt
python -m hafuch
```
Tests: `python -m unittest tests.test_engine tests.test_hotkeys tests.test_mac_logic`

## Credits
The word frequency lists in `hafuch/data/en.txt` and `hafuch/data/he.txt` are derived from
[wordfreq](https://github.com/rspeer/wordfreq) by Robyn Speer, whose data is licensed under
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). These two files are shared under the same license.
