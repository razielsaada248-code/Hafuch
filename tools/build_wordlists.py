"""Generates hafuch/data/en.txt and he.txt from wordfreq (run once, at dev time).

Data licence: wordfreq data is CC-BY-SA 4.0 (code Apache 2.0). Each line: word<TAB>zipf
frequency (log10 per billion words), comparable across languages.
"""
import os
import re

import wordfreq

OUT = os.path.join(os.path.dirname(__file__), '..', 'hafuch', 'data')
os.makedirs(OUT, exist_ok=True)


def dump(lang, n, pattern):
    words, seen = [], set()
    for w in wordfreq.top_n_list(lang, n * 2):
        w = w.lower()
        if re.fullmatch(pattern, w) and w not in seen:
            seen.add(w)
            words.append(w)
        if len(words) >= n:
            break
    with open(os.path.join(OUT, f'{lang}.txt'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(f'{w}\t{wordfreq.zipf_frequency(w, lang):.2f}' for w in words))
    print(lang, len(words))


dump('en', 60000, r"[a-z]+(?:'[a-z]+)?")
dump('he', 50000, r"[א-ת]+")
