"""Clean, de-duplicate and rank crawler output. Produces backend/places.json (what the API reads,
next to backend/main.py) and places_sorted.xlsx.
Usage: python sort_places.py existing.tsv   (or the crawler's *_progress.json)
       [--out places.json]   (defaults to backend/places.json)"""
import csv, json, re, sys, math
from pathlib import Path

ROOT = Path(__file__).resolve().parent

SECTIONS = {"venue": "Marquee / Venue", "planner": "Event planner", "makeup": "Parlour / Makeup",
            "dj": "DJ / Sound", "photo": "Photographer", "sweets": "Sweets"}
CODE = {"Marquee / Venue": "venue", "Event planner": "planner", "Parlour / Makeup": "makeup",
        "DJ / Sound": "dj", "Photographer": "photo", "Sweets": "sweets"}
BOX = (33.40, 33.90, 72.80, 73.40)
SECTOR = re.compile(r"\b([A-Ia-i])[- ]?(\d{1,2})(?:/\d)?\b")

def phone(p):
    d = re.sub(r"\D", "", p or "")
    if d.startswith("92"): d = "0" + d[2:]
    if d.startswith("0092"): d = "0" + d[4:]
    if len(d) == 10 and d[0] == "3": d = "0" + d
    return ("+92 %s %s" % (d[1:4], d[4:]) if d.startswith("03") and len(d) == 11 else
            "+92 %s %s" % (d[1:3], d[3:]) if d.startswith("0") and len(d) in (10, 11) else "")

def num(x):
    try: return float(x)
    except Exception: return None

def score(rating, n):
    """Bayesian average: 5.0 from 2 reviews must not beat 4.7 from 300."""
    if rating is None: return 0.0
    n = n or 0; m, C = 15, 4.2
    return (n * rating + m * C) / (n + m)

def slug(s): return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")

# A vendor only counts for a section if Google's own category fits it (removes jewellers, dentists, offices ...).
REL = {"venue": ["wedding venue", "banquet", "event venue", "marquee", "function room", "auditorium", "community center", "convention", "marriage hall", "party"],
       "planner": ["event planner", "event management", "wedding planner", "wedding service", "event"],
       "makeup": ["beauty", "make-up", "makeup", "salon", "hair", "bridal", "mehndi", "spa", "beautician"],
       "dj": ["event management", "wedding service", "dj", "musician", "band", "sound", "audio", "entertain", "music", "recording studio", "disc jockey"],
       "photo": ["photo", "video production", "film", "video"],
       "sweets": ["sweet", "bakery", "dessert", "candy", "confection", "cake", "chocolate", "mithai", "ice cream"]}
def fits(sec, cat):
    c = (cat or "").lower()
    return not c or any(k in c for k in REL[sec])

def area_of(addr, searched, city):
    s = re.sub(r"\s*(Islamabad|Rawalpindi)\s*$", "", (searched or "").strip(), flags=re.I).strip()
    if city == "Islamabad":
        m = SECTOR.search(addr or "") or SECTOR.search(s)
        if m: return f"{m.group(1).upper()}-{m.group(2)}"
    elif SECTOR.fullmatch(s): s = ""            # a sector label can't be a Rawalpindi area
    return s if s and s.lower() not in ("islamabad", "rawalpindi") else "Other areas"

def load(path):
    if path.endswith(".json"):
        return [{"name": r["name"], "types": r["group"], "cat": r.get("category", ""), "city": r["city"], "area": r["area"],
                 "rating": num(r["rating"]), "reviews": r.get("rating_count"), "address": r["address"], "hours": r["hours"],
                 "phone": r["phone"], "website": r["website"], "lat": r["lat"], "lon": r["lon"], "url": r["maps_url"],
                 "review_text": r.get("reviews_text", "")} for r in json.load(open(path, encoding="utf-8"))["places"].values()]
    return [{"name": r["Name"], "types": r["Type"], "cat": r["Google category"], "city": r["City"], "area": r["Area searched"],
             "rating": num(r["Rating"]), "reviews": int(num(r["Total reviews"]) or 0), "address": r["Address"], "hours": r["Timing"],
             "phone": r["Phone"], "website": r["Website"], "lat": num(r["Latitude"]), "lon": num(r["Longitude"]),
             "url": r["Google Maps link"], "review_text": r["Top reviews"]}
            for r in csv.DictReader(open(path, encoding="utf-8-sig"), delimiter="\t")]

def main():
    src = sys.argv[1]
    given = "--out" in sys.argv
    out = sys.argv[sys.argv.index("--out") + 1] if given else str(ROOT / "backend" / "places.json")
    seen, rows, dropped = {}, [], {"outside": 0, "no_phone": 0, "dup": 0, "no_name": 0}
    for r in load(src):
        if not r["name"].strip(): dropped["no_name"] += 1; continue
        if r["lat"] is not None and not (BOX[0] <= r["lat"] <= BOX[1] and BOX[2] <= r["lon"] <= BOX[3]):
            dropped["outside"] += 1; continue
        ph = phone(r["phone"])
        if not ph: dropped["no_phone"] += 1; continue          # a vendor without a number is useless to a couple
        a = (r["address"] or "").lower()
        city = "Rawalpindi" if "rawalpindi" in a else "Islamabad" if "islamabad" in a else r["city"]
        key = (re.sub(r"\W", "", r["name"].lower()), ph)
        types = [CODE[t.strip()] for t in dict.fromkeys(r["types"].split(" / ")) if t.strip() in CODE] if False else \
                list(dict.fromkeys(CODE[t] for t in re.split(r" / (?=Marquee|Event|Parlour|DJ|Photo|Sweets)", r["types"]) if t in CODE))
        types = [t for t in types if fits(t, r["cat"])]
        if not types: continue
        if key in seen:
            seen[key]["sections"] = list(dict.fromkeys(seen[key]["sections"] + types)); dropped["dup"] += 1; continue
        rec = {"id": slug(r["name"]) + "-" + ph[-4:], "name": r["name"].strip(), "sections": types, "city": city,
               "area": area_of(r["address"], r["area"], city), "rating": r["rating"], "reviews": r["reviews"] or 0, "score": round(score(r["rating"], r["reviews"]), 3),
               "phone": ph, "address": r["address"], "hours": r["hours"], "website": r["website"], "category": r["cat"],
               "lat": r["lat"], "lon": r["lon"], "maps_url": r["url"], "review_text": (r["review_text"] or "")[:600]}
        seen[key] = rec; rows.append(rec)
    rows.sort(key=lambda x: (x["city"], x["area"], -x["score"]))
    json.dump(rows, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    from openpyxl import Workbook
    wb = Workbook(); ws = wb.active; ws.title = "Sorted"
    ws.append(["City", "Area", "Section", "Name", "Rating", "Reviews", "Rank score", "Phone", "Address", "Website", "Maps"])
    for r in sorted(rows, key=lambda x: (x["city"], x["area"], x["sections"][0], -x["score"])):
        ws.append([r["city"], r["area"], SECTIONS[r["sections"][0]], r["name"], r["rating"], r["reviews"], r["score"], r["phone"], r["address"], r["website"], r["maps_url"]])
    ws.freeze_panes = "A2"; ws.auto_filter.ref = ws.dimensions
    wb.save(out.replace(".json", "_sorted.xlsx") if given else str(ROOT / "places_sorted.xlsx"))
    print(f"kept {len(rows)}; dropped {dropped}")
    for c in SECTIONS: print(c, sum(c in r['sections'] for r in rows))
main()
