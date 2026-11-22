import os
import subprocess
import sys

import pystray
from PIL import Image, ImageDraw, ImageFont

from . import config

FONTS = ['arialbd.ttf', 'arial.ttf', '/System/Library/Fonts/Supplemental/Arial Bold.ttf',
         '/System/Library/Fonts/Supplemental/Arial.ttf']


def _font(size):
    for f in FONTS:
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            continue
    return ImageFont.load_default()


def make_icon(active=True, auto=True):
    img = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    bg = (37, 99, 235) if active and auto else (217, 119, 6) if active else (120, 120, 120)
    d.rounded_rectangle((2, 2, 62, 62), radius=14, fill=bg)
    f = _font(30)
    d.text((17, 32), 'A', font=f, fill='white', anchor='mm')
    d.text((46, 32), 'א', font=f, fill='white', anchor='mm')
    d.line((32, 14, 32, 50), fill=(255, 255, 255, 140), width=2)
    return img


def _open(path):
    if sys.platform == 'win32':
        os.startfile(path)
    else:
        subprocess.Popen(['open', path])


def run(controller, platform_mod, on_quit):
    c = controller
    items = [
        pystray.MenuItem('פעיל', lambda: c.toggle_enabled(), checked=lambda _: c.enabled),
        pystray.MenuItem('החלפה אוטומטית', lambda: c.toggle_auto(), checked=lambda _: c.auto),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem('Pause - הפוך מילה אחרונה', None, enabled=False),
        pystray.MenuItem('Shift+Pause - הפוך טקסט מסומן', None, enabled=False),
        pystray.Menu.SEPARATOR,
    ]
    if hasattr(platform_mod, 'set_autostart') and getattr(sys, 'frozen', False):  # installed exe only
        def toggle_start():
            platform_mod.set_autostart(not platform_mod.get_autostart(), f'"{sys.executable}"')
        items.append(pystray.MenuItem('הפעל עם המחשב', toggle_start,
                                      checked=lambda _: platform_mod.get_autostart()))
    items += [
        pystray.MenuItem('הגדרות (קובץ)', lambda: _open(config.config_path())),
        pystray.MenuItem('יציאה', lambda icon: (on_quit(), icon.stop())),
    ]
    icon = pystray.Icon('Hafuch', make_icon(), 'Hafuch - הפוך', pystray.Menu(*items))

    def refresh():
        icon.icon = make_icon(c.enabled, c.auto)
        icon.title = 'Hafuch - ' + ('מושהה' if not c.enabled else 'אוטומטי' if c.auto else 'ידני בלבד')
        icon.update_menu()
    c.on_change = refresh
    icon.run()
