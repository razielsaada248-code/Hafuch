import json
import os
import sys

from . import APP_NAME

DEFAULTS = {
    'auto_convert': False,      # default: flip only on the hotkey
    'hotkeys': {
        # flip current/previous word (also undoes an automatic flip)
        'convert_word': ['pause', 'ctrl+shift+space'],
        # flip the selected text
        'convert_selection': ['shift+pause', 'ctrl+shift+alt+space'],
    },
    # processes where Hafuch does nothing (lower-case exe name, no extension)
    'excluded_apps': [
        'keepass', 'keepassxc', '1password', 'bitwarden', 'lastpass', 'proton pass',
        'mstsc', 'windowsterminal', 'cmd', 'powershell', 'pwsh', 'conhost',
        'putty', 'teamviewer', 'anydesk', 'terminal', 'iterm2',
    ],
    'min_word_length': 2,
}


def config_dir():
    if sys.platform == 'darwin':
        base = os.path.expanduser('~/Library/Application Support')
    else:
        base = os.environ.get('APPDATA', os.path.expanduser('~'))
    path = os.environ.get('HAFUCH_CONFIG_DIR') or os.path.join(base, APP_NAME)   # env: tests
    os.makedirs(path, exist_ok=True)
    return path


def config_path():
    return os.path.join(config_dir(), 'config.json')


def load():
    cfg = json.loads(json.dumps(DEFAULTS))
    try:
        with open(config_path(), encoding='utf-8') as f:
            user = json.load(f)
        for k, v in user.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v
    except FileNotFoundError:
        save(cfg)
    except (ValueError, OSError):
        pass        # broken file -> defaults, don't overwrite the user's file
    return cfg


def save(cfg):
    with open(config_path(), 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
