"""Every area each city really offers - the source of truth behind the dropdown and the 422s.

main.py builds the menu from WHITELIST_SET plus whatever places.json already holds, and drops
everything else, so crawler junk never reaches the screen: G-95, H-77, B-05, C-27, G-1 are shop
numbers, Plus Codes or plots - not Islamabad sectors - and "Saddar" belongs to Rawalpindi only.

normalize() folds any spelling onto the label the menu offers, so 'i 08', 'I 8/4' and 'G-06'
become 'I-8', 'I-8' and 'G-6' before anything is matched, resolved or counted.
"""
import re

CITIES = ["Islamabad", "Rawalpindi"]

# Islamabad's grid: which sector per letter exists (master plan / CDA sector lists).
# Rawalpindi has no sector grid at all - its localities are named areas only.
SECTORS = {
    "A": range(17, 19),          # A-17, A-18
    "B": range(17, 19),          # B-17, B-18 (Multi Gardens ...)
    "C": range(13, 19),          # C-13 .. C-18 (newly launched, near Margalla Avenue)
    "D": range(10, 19),          # D-10 .. D-18 (D-12 is the developed one)
    "E": range(7, 19),           # E-7 .. E-18 (E-8/E-9 institutional)
    "F": range(5, 18),           # F-5 .. F-17 (the most developed series)
    "G": range(5, 19),           # G-5 .. G-18 (G-15/G-16/JKHS are society sectors on the grid)
    "H": range(8, 19),           # H-8 .. H-18 (universities, industry)
    "I": range(8, 19),           # I-8 .. I-18 (market + residential)
}

# Named localities. Only what a bride/groom would actually search for; the crawler's odd
# labels (Saddar-in-Islamabad, Chaklala-in-Koral) stay out of the city they are not in.
NAMED = {
    "Islamabad": ["Bahria Enclave", "Bani Gala", "Barakahu", "Chaklala Scheme 3", "DHA Phase 2",
                  "Ghauri Town", "Gulberg", "Gulberg Green", "Jinnah Garden", "Khanna",
                  "Korang Town", "Margalla Town", "Soan Gardens"],
    "Rawalpindi": ["Bank Road", "Bahria Enclave", "Bahria Town", "Chaklala Scheme 3", "Court Road",
                   "DHA Phase 2", "Peoples Colony", "Saddar", "Satellite Town", "Sohan", "Westridge"],
}


def is_sector(a):
    """True for anything written like a sector: 'I-8', 'i 08', 'G-06', even the junk 'B 05-06' -
    so main.py can ask the strict question (is it one of *our* sectors?) instead of guessing."""
    return bool(re.match(r"^[A-I][\s/-]?0*\d", (a or "").strip(), re.I))


_SECTOR = re.compile(r"^\s*([A-I])[\s/-]*0*(\d{1,2})(?:\s*/\s*\d{1,2})?", re.I)


def _key(s):
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def normalize(x):
    """Any spelling -> the label the menu offers: 'i 08', 'I 8/4' -> 'I-8'; 'G-06' -> 'G-6';
    named areas match ignoring case and punctuation ('dha phase-2' -> 'DHA Phase 2').
    Unknown text is only trimmed - never invented - so main.py can 422 it."""
    t = " ".join(str(x or "").split())
    if not t:
        return ""
    m = _SECTOR.match(t)
    if m:
        t = "%s-%d" % (m.group(1).upper(), int(m.group(2)))
    return _CANON.get(_key(t)) or t


def natural_key(s):
    """Sort 'I-8' before 'I-10' (numbers as numbers) and mix named areas in alphabetically -
    tuples keep int and str tokens from ever being compared to each other."""
    return [(0, int(t)) if t.isdigit() else (1, t.lower()) for t in re.split(r"(\d+)", s or "")]


def _build():
    wl = {}
    for city in CITIES:
        items = []
        if city == "Islamabad":
            items += ["%s-%d" % (letter, n) for letter, nums in SECTORS.items() for n in nums]
        items += NAMED[city]
        wl[city] = sorted(items, key=natural_key)
    return wl


WHITELIST = _build()                                   # city -> every label the menu may offer
WHITELIST_SET = {c: set(v) for c, v in WHITELIST.items()}
_CANON = {_key(n): n for v in WHITELIST.values() for n in v}   # case/punctuation-insensitive lookup
