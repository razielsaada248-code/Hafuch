"""Quality check over the word lists: how many real words would flip by mistake, how many typos are caught."""
import sys
sys.path.insert(0, __file__.rsplit('tests', 1)[0])
from hafuch import engine, keymap

E = engine.Engine()
inv = {v: k for k, v in keymap.HE.items()}
kh = lambda w: [(inv[c], False) for c in w]
ke = lambda w: [(c.lower(), c.isupper()) for c in w]
en = list(E.d.freq['en'])[:20000]
he = [w for w in list(E.d.freq['he'])[:20000] if all(c in inv for c in w)]
en = [w for w in en if "'" not in w]
fp_en = [w for w in en if E.should_convert(ke(w), 'en')]
fp_he = [w for w in he if E.should_convert(kh(w), 'he')]
print('real EN words flipped:', len(fp_en), fp_en[:25])
print('real HE words flipped:', len(fp_he), fp_he[:25])
for name, ws, lay, k, tgt in (('HE typed in EN', he[:5000], 'en', kh, 'he'), ('EN typed in HE', en[:5000], 'he', ke, 'en')):
    miss = [w for w in ws if E.should_convert(k(w), lay) != tgt]
    print(name, 'caught', len(ws) - len(miss), '/', len(ws), 'top misses:', [(w, keymap.render(k(w), lay)) for w in miss[:15]])
