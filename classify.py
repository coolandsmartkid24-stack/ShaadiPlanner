"""Classify a vendor into the section(s) it truly belongs to, from its NAME and its Google
category.

Why this exists: the crawler's `group` field only records *which search query found the row*, not
what the business is. A "Dhol Party" surfaced by a marriage-hall search therefore arrived tagged
`venue`, and a "Steel Works & Welding Gate Grill" arrived tagged `dj` - which is how unrelated
vendors ended up inside the Marquee card.

Rules, in order:
  1. A name that names exactly one section wins outright (overrides Google's category).
  2. A name naming several sections keeps all of them (a hall that is also a marquee).
  3. Otherwise fall back to the Google category.
  4. If neither recognises anything, return [] and let the caller keep the original tags -
     never silently drop a vendor.

Used by sort_places.py (fresh crawls) and reclassify.py (rewriting an existing places.json).
"""
import re

SECTIONS = {"venue": "Marquee / Venue", "planner": "Event planner", "makeup": "Parlour / Makeup",
            "dj": "DJ / Sound", "photo": "Photographer", "sweets": "Sweets"}

# ---- name signals. Deliberately narrow: every extra word here can misfile a vendor, so vague
#      words (studio, party, light, artist, garden, event, sound-on-its-own) are excluded.
NAME_PAT = {
    "venue": r"\bmarquee[s]?\b|\bmarque\b|\bmarriage hall\b|\bwedding hall\b|\bshadi hall\b"
             r"|\bbanquet\b|\bfunction hall\b|\bevent venue\b|\bvenue\b|\bauditorium\b"
             r"|\bcommunity cent(?:er|re)s?\b|\bconvention cent|\bmarriage garden\b",
    "planner": r"\bplanner[s]?\b|\bplanning\b|\bevent manag|\bevent organi|\bwedding service\b"
               r"|\bwedding decor\b|\btent house\b|\bparty organiser|\bparty organizer\b"
               r"|\bdecorator[s]?\b|\bdecorations\b",
    "makeup": r"\bsalon[s]?\b|\bsaloon[s]?\b|\bbeauty\b|\bmake.?up\b|\bmakup\b|\bbridal\b"
              r"|\bmehndi\b|\bhenna\b|\bhair\b|\bspa\b|\bbeautician\b|\bparlou?r[s]?\b"
              r"|\bstylist\b|\bcosmetic",
    "dj": r"\bdhol\b|\bqawal|\bdj\b|\bsound[s]?\b|\bmusic\b|\bband\b|\baudio\b|\bentertain"
          r"|\bdisc jockey\b|\bsinger[s]?\b|\bbaja\b|\bdholki\b|\blive band\b|\blighting\b",
    "photo": r"\bphoto|\bphotography\b|\bcamera\b|\bvideo\b|\bfilm\b|\bgrapher\b|\bproductions\b",
    "sweets": r"\bsweet[s]?\b|\bbakery\b|\bbakeshop\b|\bbake shop\b|\bcake shop\b|\bdessert\b"
              r"|\bmithai\b|\bconfection|\bchocolate\b|\bcandy\b|\bice cream\b|\bpastry\b"
              r"|\bbakers\b|\bnaan khatai\b",
}

# ---- Google-category signals, used only when the name says nothing.
CAT_PAT = {
    "venue": r"wedding venue|banquet hall|event venue|marquee|marriage hall|community cent"
             r"|auditorium|convention|function room|event hall",
    "planner": r"event planner|event management|wedding planner|wedding service|party planner",
    "makeup": r"beauty salon|make.?up|hairdresser|hair salon|\bspa\b|beautician|mehndi"
              r"|health and beauty|cosmetic",
    "dj": r"dj service|musician|recording studio|entertainment agency|disc jockey"
          r"|audio.?visual|music management|entertainer",
    "photo": r"photograph|video production|film production|photo booth|photo lab|photo shop"
             r"|film and photograph",
    "sweets": r"bakery|dessert shop|candy store|sweets|confection|cake shop|chocolate"
              r"|ice cream|mithai|bakeshop|patisserie",
}


def _hits(pats, text):
    return {s for s, p in pats.items() if re.search(p, text)}


def classify(name, category, fallback=()):
    """-> list of section codes for this vendor. Falls back to `fallback` (the crawler's own tag)
    when neither the name nor the category is recognised, so no vendor is ever dropped."""
    from_name = _hits(NAME_PAT, (name or "").lower())
    from_cat = _hits(CAT_PAT, (category or "").lower())

    if len(from_name) == 1:
        return sorted(from_name)          # a trading name beats Google's category
    if from_name:
        return sorted(from_name)          # genuinely does two things ("Shadi Hall & Marquee")
    if from_cat:
        return sorted(from_cat)
    return sorted(dict.fromkeys(fallback))
