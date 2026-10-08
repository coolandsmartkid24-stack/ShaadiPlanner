"""
Google Maps crawler -> Excel list (generic version).
Default: marriage halls, event planners, parlours / bridal makeup, DJ, photographers and sweets across ALL sectors and
areas of Islamabad + Rawalpindi. Categories and areas can be replaced with your own JSON files.

SETUP (once):
    pip install playwright openpyxl
    playwright install chromium
RUN:
    python google_places_crawler.py --list-areas        # see every area that will be searched
    python google_places_crawler.py --quick             # small test first (about 5 minutes)
    python google_places_crawler.py                     # full run (many hours; Ctrl+C is safe, run again to resume)
OPTIONS:
    --city Islamabad|Rawalpindi|both   which city to crawl (default both)
    --areas-file areas.json            your own areas: {"Islamabad": ["F-7", "G-9"], "Lahore": ["Gulberg"]}
    --terms-file terms.json            your own categories: [["pharmacy", "Pharmacy"], ["gym", "Gym"]]
    --fast                             skip reviews, menu items and timings (about 3x quicker)
    --batch N                          stop after N NEW places (default 50); run again / schedule daily to continue
    --import FILE.tsv                  seed progress from an earlier Excel/TSV export (Places sheet) so nothing is re-crawled
    --recrawl-days D                   re-run a finished search after D days to pick up new places (default 30)
    --loop MIN                         keep running forever: one batch, sleep MIN minutes, repeat (fully autonomous)
    --no-geofilter                     don't skip places whose map coordinates are outside Islamabad/Rawalpindi
    --max-hours H                      stop cleanly after H hours (resume later with the same command)
    --reviews N                        reviews saved per place (default 10, 0 = skip)
    --max-per-search N                 max places per search (default 120)
    --inspect                          print tabs / info buttons Google shows per place (to fix selectors)
    --headless                         hide the browser (Google may block more often)
    --out FILE.xlsx                    output file (default islamabad_rawalpindi_places.xlsx)

NOTES:
 * Reading Google Maps pages automatically is against Google's Terms of Service; expect CAPTCHAs / temporary
   blocks. Slow random pauses are built in. The official Places API is the compliant alternative.
 * Google changes its layout often. All CSS selectors live in SEL; if a column comes out empty, fix only that.
 * Untested against the live site. Run --quick first.
"""
import argparse, csv, json, os, random, re, sys, time
from urllib.parse import quote

SEL = {
    "consent": "button:has-text('Accept all'), button:has-text('Reject all')",
    "feed": 'div[role="feed"]',
    "result_link": 'div[role="feed"] a[href*="/maps/place/"]',
    "name": "h1.DUwDvf",
    "rating": 'div.F7nice span[aria-hidden="true"]',
    "rating_count": 'div.F7nice span[aria-label*="review"]',
    "category": "button.DkEaL",
    "address": 'button[data-item-id="address"]',
    "phone": 'button[data-item-id^="phone"]',
    "website": 'a[data-item-id="authority"]',
    "menu": 'a[data-item-id="menu"], a[data-item-id*="menu"], a[aria-label^="Menu"]',
    "menu_tab": 'button[role="tab"][aria-label*="Menu"], button[role="tab"]:has-text("Menu")',
    "panel": 'div[role="main"]',
    "hours_btn": '[data-item-id="oh"]',
    "hours_rows": "table.eK4R0e tr, table.WgFkxc tr",
    "reviews_tab": 'button[role="tab"][aria-label*="Reviews"], button[role="tab"]:has-text("Reviews")',
    "review_item": "div.jftiEf",
    "review_name": "div.d4r55",
    "review_stars": "span.kvMYJc",
    "review_when": "span.rsqaWe",
    "review_text": "span.wiI7pd",
    "review_more": "button.w8nwRe",
}

# Venues depend on the exact area, so they are searched area by area.
AREA_TERMS = [("marriage hall", "Marquee / Venue"), ("marquee", "Marquee / Venue"), ("banquet hall", "Marquee / Venue")]
# Vendors usually serve the whole city, so they are searched once per city + a few big zones.
CITY_TERMS = [("wedding venue", "Marquee / Venue"), ("marriage hall", "Marquee / Venue"),
              ("wedding planner", "Event planner"), ("event management company", "Event planner"),
              ("bridal makeup artist", "Parlour / Makeup"), ("beauty parlour bridal", "Parlour / Makeup"),
              ("wedding DJ", "DJ / Sound"), ("sound system DJ rental", "DJ / Sound"),
              ("wedding photographer", "Photographer"), ("wedding photography studio", "Photographer"),
              ("sweets shop mithai", "Sweets")]
ZONES = {"Islamabad": ["F-7", "G-9", "I-8", "G-11", "DHA Phase 2 Islamabad", "Bahria Enclave"],
         "Rawalpindi": ["Saddar", "Satellite Town", "Bahria Town Rawalpindi", "Chaklala Scheme 3", "Westridge 1", "Adiala Road"]}

# ---------- AREAS ----------
def _sec(letter, lo, hi):
    return [f"{letter}-{i}" for i in range(lo, hi + 1)]

# Every sector of the Islamabad grid (some outer ones are still under development; empty searches are quick).
ISB_SECTORS = (_sec("D", 12, 17) + _sec("E", 7, 17) + _sec("F", 5, 17) + _sec("G", 5, 16)
               + _sec("H", 8, 17) + _sec("I", 8, 18) + ["B-17", "C-15", "C-16", "C-17"])

ISB_OTHER = [
    "Blue Area",
    "Zero Point", "Aabpara", "Satrah Meel", "Faizabad", "Margalla Road", "Park Road", "Diplomatic Enclave",
    "Saidpur Village", "Bari Imam", "Shahdara", "Chak Shahzad", "Bhara Kahu", "Bani Gala", "Tarlai", "Tarnol", "Golra Mor",
    "Golra Sharif", "Koral Chowk", "Lehtrar Road", "Alipur Farash", "Humak", "Sihala", "Kahuta Road", "Express Highway",
    "Islamabad Highway", "Rawat", "Gulberg Greens", "Gulberg Residencia", "Gulberg Islamabad", "DHA Phase 1 Islamabad",
    "DHA Phase 2 Islamabad", "DHA Phase 3 Islamabad", "DHA Phase 5 Islamabad", "Bahria Enclave", "Naval Anchorage",
    "Media Town", "PWD Housing Society", "Soan Garden", "CBR Town", "Jinnah Garden", "Top City", "Capital Smart City",
    "Park Enclave", "Faisal Town", "Pakistan Town", "Shahzad Town", "Korang Town", "Ghauri Town", "Mumtaz City",
    "University Town", "Police Foundation", "Airport Housing Society", "Ali Pur", "Zaraj Housing", "Tramri Chowk",
    "Sector Gulshan-e-Jinnah",
]

RWP_AREAS = [
    "Saddar", "Committee Chowk", "Satellite Town", "Chaklala Scheme 1", "Chaklala Scheme 2", "Chaklala Scheme 3",
    "Chandni Chowk", "Murree Road", "Peshawar Road", "Adiala Road", "Airport Road", "Khayaban-e-Sir Syed",
    "Tipu Road", "Lalazar", "Westridge 1", "Westridge 2", "Westridge 3", "Dhoke Kala Khan", "Dhoke Hassu", "Dhoke Ratta",
    "Dhoke Khabba", "Gulzar-e-Quaid", "Misrial Road", "Scheme 3", "Bahria Town Phase 1", "Bahria Town Phase 2",
    "Bahria Town Phase 3", "Bahria Town Phase 4", "Bahria Town Phase 5", "Bahria Town Phase 6", "Bahria Town Phase 7",
    "Bahria Town Phase 8", "Bahria Town Rawalpindi", "DHA Phase 1 Rawalpindi", "DHA Phase 2 Rawalpindi", "Gulraiz Housing Society",
    "Pirwadhai", "Faizabad Rawalpindi", "Lal Kurti", "Cantt Rawalpindi", "GHQ Road", "Tench Bhatta", "Khanna Pul", "Kurri Road",
    "Sadiqabad", "Shamsabad", "Allama Iqbal Colony", "Tulsa Road", "Morgah", "Ratta Amral", "Fauji Colony", "Gulistan Colony",
    "Gulshan Abad", "Rehmanabad", "Jhanda Chichi", "Dhamyal Road", "Chakri Road", "Defence Road", "Range Road", "Harley Street",
    "Judicial Colony", "Media Town Rawalpindi", "PWD Rawalpindi", "Airport Housing Society Rawalpindi", "Rawal Town", "Shalley Valley",
    "Kashmir Road", "Sixth Road", "Quaid-e-Azam Colony", "Ghazanfar Colony",
    "Rawat Rawalpindi", "Gorakhpur", "Dhoke Chiragh Din", "Sher Zaman Colony",
]

AREAS = {"Islamabad": ISB_SECTORS + ISB_OTHER, "Rawalpindi": RWP_AREAS}

# ---------- helpers ----------
def place_key(url):
    m = re.search(r"!1s(0x[0-9a-f]+:0x[0-9a-f]+)", url)
    return m.group(1) if m else url.split("?")[0]

def coords(url):
    m = re.search(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)", url) or re.search(r"@(-?\d+\.\d+),(-?\d+\.\d+)", url)
    return (float(m.group(1)), float(m.group(2))) if m else (None, None)

def clean(s):
    return " ".join((s or "").replace("\u00a0", " ").split())

def txt(scope, sel):
    try:
        loc = scope.locator(sel).first
        return clean(loc.inner_text(timeout=1500)) if loc.count() else ""
    except Exception:
        return ""

def attr(scope, sel, name, strip=""):
    try:
        loc = scope.locator(sel).first
        v = loc.get_attribute(name, timeout=1500) if loc.count() else ""
        return clean((v or "").replace(strip, "", 1)) if strip else clean(v)
    except Exception:
        return ""

def pause(a=1.5, b=3.0):
    time.sleep(random.uniform(a, b))

def check_block(page, headless):
    if "/sorry/" in page.url or page.locator("iframe[src*='recaptcha']").count():
        if headless:
            raise SystemExit("Google asked for a CAPTCHA. Run again without --headless, wait a while, then continue.")
        input("\nGoogle shows a CAPTCHA. Solve it in the browser window, then press Enter here... ")

def consent(page):
    try:
        page.locator(SEL["consent"]).first.click(timeout=2500)
    except Exception:
        pass

def collect_links(page, query, max_places, headless):
    page.goto(f"https://www.google.com/maps/search/{quote(query)}?hl=en", wait_until="domcontentloaded")
    consent(page); check_block(page, headless)
    try:
        page.wait_for_selector(SEL["feed"], timeout=15000)
    except Exception:
        return [page.url] if "/maps/place/" in page.url else []
    links, last, stable = {}, -1, 0
    for _ in range(80):
        for a in page.locator(SEL["result_link"]).all():
            href = a.get_attribute("href")
            if href: links[place_key(href)] = href
        if len(links) >= max_places or page.locator("text=You've reached the end of the list").count(): break
        stable = stable + 1 if len(links) == last else 0
        if stable >= 4: break
        last = len(links)
        try:
            page.locator(SEL["feed"]).hover(); page.mouse.wheel(0, 4000)
        except Exception:
            break
        page.wait_for_timeout(1300)
    return list(links.values())[:max_places]

def get_hours(page):
    try:
        btn = page.locator(SEL["hours_btn"]).first
        if btn.count():
            try: btn.click(timeout=2000); page.wait_for_timeout(600)
            except Exception: pass
        rows, out = page.locator(SEL["hours_rows"]), []
        for i in range(rows.count()):
            out.append(clean(rows.nth(i).inner_text()))
        return "; ".join(x for x in out if x) or txt(page, SEL["hours_btn"])
    except Exception:
        return ""

def get_reviews(page, n):
    if n <= 0: return []
    try:
        page.locator(SEL["reviews_tab"]).first.click(timeout=3000); page.wait_for_timeout(1800)
    except Exception:
        return []
    for _ in range(10):
        if page.locator(SEL["review_item"]).count() >= n: break
        try:
            page.locator(SEL["review_item"]).last.hover(); page.mouse.wheel(0, 3500)
        except Exception:
            break
        page.wait_for_timeout(1000)
    for b in page.locator(SEL["review_more"]).all()[:n]:
        try: b.click(timeout=400)
        except Exception: pass
    items, out = page.locator(SEL["review_item"]), []
    for i in range(min(n, items.count())):
        it = items.nth(i)
        m = re.search(r"(\d)", attr(it, SEL["review_stars"], "aria-label"))
        out.append({"reviewer": txt(it, SEL["review_name"]), "stars": int(m.group(1)) if m else None,
                    "when": txt(it, SEL["review_when"]), "text": txt(it, SEL["review_text"])})
    return out

PRICE = re.compile(r"^(rs\.?|pkr|\u20a8)?\s*[\d,]{2,7}(\.\d+)?\s*(rs\.?|pkr)?$", re.I)
INSPECT = False
FAST = False

def pair_menu_lines(lines):
    """A price line belongs to the line just above it."""
    out, prev = [], ""
    for ln in lines:
        if PRICE.match(ln) and prev and not PRICE.match(prev):
            out.append({"item": prev, "price": ln}); prev = ""
        else:
            if prev and len(prev) < 80: out.append({"item": prev, "price": ""})
            prev = ln
    if prev and len(prev) < 80: out.append({"item": prev, "price": ""})
    return out[:80]

def get_menu_items(page):
    try:
        tab = page.locator(SEL["menu_tab"]).first
        if not tab.count(): return []
        tab.click(timeout=3000); page.wait_for_timeout(1800)
        for _ in range(4):
            try: page.locator(SEL["panel"]).first.hover(); page.mouse.wheel(0, 2500)
            except Exception: break
            page.wait_for_timeout(700)
        lines = [clean(x) for x in page.locator(SEL["panel"]).first.inner_text(timeout=3000).split("\n") if clean(x)]
        if "Menu" in lines[:60]: lines = lines[lines.index("Menu", 0) + 1:]
        return pair_menu_lines(lines)
    except Exception:
        return []

def inspect(page):
    tabs = [clean(b.get_attribute("aria-label") or b.inner_text()) for b in page.locator('button[role="tab"]').all()]
    ids = [x.get_attribute("data-item-id") for x in page.locator("[data-item-id]").all()]
    print(f"    [inspect] tabs={tabs} info-buttons={ids}")

KNOWN_CITIES = ["Rawalpindi", "Islamabad"]

def scrape_place(page, url, n_reviews, group, area, city):
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_selector(SEL["name"], timeout=15000)
    name = txt(page, SEL["name"])
    addr = attr(page, SEL["address"], "aria-label", "Address:")
    rc = re.sub(r"[^\d]", "", attr(page, SEL["rating_count"], "aria-label"))
    lat, lon = coords(page.url)
    if INSPECT: inspect(page)
    low = addr.lower()
    real_city = next((c for c in KNOWN_CITIES if c.lower() in low), city)
    return {"name": name, "group": group, "category": txt(page, SEL["category"]), "city": real_city, "area": area,
            "rating": txt(page, SEL["rating"]).replace(",", "."), "rating_count": int(rc) if rc else None,
            "address": addr, "hours": "" if FAST else get_hours(page), "phone": attr(page, SEL["phone"], "aria-label", "Phone:"),
            "website": attr(page, SEL["website"], "href"), "menu": attr(page, SEL["menu"], "href"),
            "lat": lat, "lon": lon, "maps_url": page.url, "reviews": [] if FAST else get_reviews(page, n_reviews), "menu_items": [] if FAST else get_menu_items(page)}

def write_excel(places, path):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    wb = Workbook(); ws = wb.active; ws.title = "Places"
    cols = ["Name", "Type", "Google category", "City", "Area searched", "Rating", "Total reviews", "Address", "Timing", "Phone",
            "Website", "Menu link", "Menu items", "Latitude", "Longitude", "Google Maps link", "Top reviews"]
    ws.append(cols)
    for p in sorted(places, key=lambda p: (p["city"], p["group"], p["name"])):
        rv = p.get("reviews_text") or " | ".join(f'{r["stars"] or "?"}* {r["reviewer"]}: {r["text"]}' for r in p["reviews"] if r["text"])
        r = p["rating"]
        try: r = float(r)
        except Exception: pass
        ws.append([p["name"], p["group"], p["category"], p["city"], p["area"], r, p["rating_count"], p["address"], p["hours"],
                   p["phone"], p["website"], p["menu"], (p.get("menu_text") or "; ".join(f'{m["item"]} {m["price"]}'.strip() for m in p.get("menu_items", [])))[:32000],
                   p["lat"], p["lon"], p["maps_url"], rv[:32000]])
    r2 = wb.create_sheet("Reviews"); r2.append(["Place", "City", "Reviewer", "Stars", "When", "Review"])
    for p in places:
        for r in p["reviews"]:
            r2.append([p["name"], p["city"], r["reviewer"], r["stars"], r["when"], r["text"][:32000]])
    r3 = wb.create_sheet("Menus"); r3.append(["Place", "City", "Menu item", "Price"])
    for p in places:
        for m in p.get("menu_items", []):
            r3.append([p["name"], p["city"], m["item"], m["price"]])
    widths = {"Places": [32, 15, 22, 12, 18, 8, 10, 45, 55, 18, 30, 30, 45, 11, 11, 35, 80], "Reviews": [32, 12, 22, 7, 14, 90], "Menus": [32, 12, 45, 14]}
    for sh in (ws, r2, r3):
        for c in sh[1]: c.font = Font(bold=True, color="FFFFFF"); c.fill = PatternFill("solid", fgColor="303030")
        for i, w in enumerate(widths[sh.title]): sh.column_dimensions[chr(65 + i)].width = w
        sh.freeze_panes = "B2"; sh.auto_filter.ref = sh.dimensions
    wb.save(path)

def safe_write(places, path):
    """Never crash if the Excel file is open: save to a *_part.xlsx copy instead."""
    try:
        write_excel(places, path); return path
    except PermissionError:
        alt = (path[:-5] if path.lower().endswith(".xlsx") else path) + "_part.xlsx"
        try:
            write_excel(places, alt)
            print(f"  [!] '{path}' is open in Excel, saved to '{alt}' instead.")
            return alt
        except PermissionError:
            print("  [!] Excel file is open and locked. Data is safe in the progress file; continuing.")
            return None

def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class TimeUp(Exception):
    pass

class BatchDone(Exception):
    pass

# Islamabad + Rawalpindi bounding box. Google often returns far-away places (e.g. Lahore) for a vague query;
# their coordinates are in the result link, so we skip them WITHOUT opening the page (saves ~10 s each).
GEO = (33.40, 33.90, 72.80, 73.40)   # lat_min, lat_max, lon_min, lon_max
def in_area(url):
    la, lo = coords(url)
    return la is None or (GEO[0] <= la <= GEO[1] and GEO[2] <= lo <= GEO[3])

def build_jobs(areas, area_terms, city_terms, zones):
    """Order: venues in big zones -> vendors (city + zones) -> venues in all remaining areas."""
    def q(term, place, city):
        return f"{term} in {place} {city}" if place != city else f"{term} in {city}"
    venues_zone, vendors, venues_rest = [], [], []
    for city, lst in areas.items():
        z = [x for x in zones.get(city, []) if x in lst] or []
        for area in z:
            for t, g in area_terms: venues_zone.append((q(t, area, city), g, area, city))
        for place in [city] + zones.get(city, []):
            for t, g in city_terms: vendors.append((q(t, place, city), g, place, city))
        for area in lst:
            if area in z: continue
            for t, g in area_terms: venues_rest.append((q(t, area, city), g, area, city))
    return venues_zone, vendors, venues_rest

def import_tsv(path, prog):
    """Seed progress from a previous export so those places are never opened again."""
    added = skipped = dup = 0
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            url = r.get("Google Maps link") or ""
            if not url: continue
            k = place_key(url)
            if k in prog["places"]: dup += 1; continue
            if not in_area(url): skipped += 1; continue
            def num(x):
                try: return float(x)
                except Exception: return None
            rc = num(r.get("Total reviews"))
            prog["places"][k] = {"name": r.get("Name", ""), "group": r.get("Type", ""), "category": r.get("Google category", ""),
                "city": r.get("City", ""), "area": r.get("Area searched", ""), "rating": r.get("Rating", ""),
                "rating_count": int(rc) if rc is not None else None, "address": r.get("Address", ""), "hours": r.get("Timing", ""),
                "phone": r.get("Phone", ""), "website": r.get("Website", ""), "menu": r.get("Menu link", ""),
                "lat": num(r.get("Latitude")), "lon": num(r.get("Longitude")), "maps_url": url,
                "reviews": [], "reviews_text": r.get("Top reviews", ""), "menu_items": [], "menu_text": r.get("Menu items", "")}
            added += 1
    print(f"Imported {added} places from {path} ({dup} duplicates, {skipped} skipped as outside Islamabad/Rawalpindi).")

def run_batch(a, jobs, maxp, nrev, prog, prog_file):
    done = prog["done"]                       # {query: unix time finished}
    now = time.time(); stale = a.recrawl_days * 86400
    todo = [j for j in jobs if j[0] not in done or now - done[j[0]] > stale]
    deadline = time.time() + a.max_hours * 3600 if a.max_hours else None
    def save():
        tmp = prog_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f: json.dump(prog, f, ensure_ascii=False)
        os.replace(tmp, prog_file)             # atomic: power loss can never corrupt the progress file
    new_count = 0
    def tick():
        if deadline and time.time() > deadline: raise TimeUp()
        if new_count >= a.batch: raise BatchDone()
    if not todo:
        print("Every search is up to date. Nothing to do today."); return 0

    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=a.headless)
        ctx = browser.new_context(locale="en-US", viewport={"width": 1400, "height": 900})
        page = ctx.new_page()
        try:
            for n, (query, group, area, city) in enumerate(todo, 1):
                tick()
                pend = prog.get("pending")
                if pend and pend["query"] == query:          # resume a search that was cut off: no re-scrolling
                    queue = pend["links"]; print(f"\n[RESUME {n}/{len(todo)}] {query} ({len(queue)} places left)")
                else:
                    print(f"\n[SEARCH {n}/{len(todo)}] {query}")
                    try: links = collect_links(page, query, maxp, a.headless)
                    except Exception as e: print("  search failed:", e); continue
                    queue, skipped = [], 0
                    for u in links:
                        k = place_key(u)
                        if k in prog["places"]:
                            old = prog["places"][k]
                            if group not in old["group"].split(" / "): old["group"] += f" / {group}"
                        elif not a.no_geofilter and not in_area(u): skipped += 1
                        else: queue.append(u)
                    print(f"  {len(links)} found, {len(queue)} new, {skipped} skipped (outside area)")
                    prog["pending"] = {"query": query, "links": queue}; save()
                while queue:
                    tick()
                    u = queue[0]
                    if place_key(u) not in prog["places"]:
                        try:
                            rec = scrape_place(page, u, nrev, group, area, city)
                            prog["places"][place_key(u)] = rec; new_count += 1
                            print(f'  + [{new_count}/{a.batch}] {rec["name"]} | {rec["rating"]} ({rec["rating_count"]}) | {rec["city"]}')
                        except Exception as e:
                            print("  skipped one place:", str(e)[:80])
                        pause(0.8, 1.6) if a.fast else pause()
                    queue.pop(0)
                    prog["pending"] = {"query": query, "links": queue}; save()   # saved after EVERY place
                done[query] = time.time(); prog["pending"] = None; save()
                pause(1, 2) if a.fast else pause(2, 4)
        except BatchDone:
            print(f"\nBatch of {a.batch} new places complete.")
        except TimeUp:
            print(f"\nTime limit of {a.max_hours} h reached.")
        except KeyboardInterrupt:
            print("\nStopped.")
            raise
        finally:
            save(); browser.close()
    return new_count

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true"); ap.add_argument("--inspect", action="store_true")
    ap.add_argument("--headless", action="store_true"); ap.add_argument("--list-areas", action="store_true")
    ap.add_argument("--fast", action="store_true"); ap.add_argument("--max-hours", type=float, default=0)
    ap.add_argument("--batch", type=int, default=50); ap.add_argument("--import", dest="import_file")
    ap.add_argument("--recrawl-days", type=float, default=30); ap.add_argument("--loop", type=float, default=0)
    ap.add_argument("--no-geofilter", action="store_true")
    ap.add_argument("--city", default="both", help="Islamabad, Rawalpindi, both, or any city name from your areas file")
    ap.add_argument("--areas-file"); ap.add_argument("--terms-file")
    ap.add_argument("--reviews", type=int, default=10); ap.add_argument("--max-per-search", type=int, default=120)
    ap.add_argument("--out", default="islamabad_rawalpindi_places.xlsx")
    a = ap.parse_args()
    global INSPECT, FAST; INSPECT = a.inspect; FAST = a.fast

    areas = load_json(a.areas_file) if a.areas_file else AREAS
    if a.city.lower() != "both":
        areas = {c: v for c, v in areas.items() if c.lower() == a.city.lower()}
        if not areas: raise SystemExit(f"No areas for city '{a.city}'. Check --city / --areas-file.")
    for c in areas:
        if c not in KNOWN_CITIES: KNOWN_CITIES.append(c)
    if a.terms_file: area_terms, city_terms = [tuple(t) for t in load_json(a.terms_file)], []
    else: area_terms, city_terms = AREA_TERMS, CITY_TERMS
    vz, vend, vrest = build_jobs(areas, area_terms, city_terms, ZONES)
    jobs = vz + vend + vrest
    if a.list_areas:
        for c, v in areas.items(): print(f"\n{c} ({len(v)} areas):\n  " + ", ".join(v))
        print(f"\nSearch plan: {len(jobs)} searches."); return

    maxp, nrev = a.max_per_search, (0 if a.fast else a.reviews)
    if a.quick: jobs, maxp, nrev, a.batch = vz[:1] + vend[:1], 5, min(nrev, 3), min(a.batch, 5)
    prog_file = os.path.splitext(a.out)[0] + "_progress.json" + (".quick" if a.quick else "")
    prog = load_json(prog_file) if os.path.exists(prog_file) else {}
    prog.setdefault("places", {}); prog.setdefault("pending", None)
    d = prog.get("done", {})
    if isinstance(d, list): d = {q: 0 for q in d}      # old progress files: keep them, they simply count as done
    prog["done"] = d
    if a.import_file: import_tsv(a.import_file, prog)

    while True:
        try: run_batch(a, jobs, maxp, nrev, prog, prog_file)
        except KeyboardInterrupt: pass
        else:
            saved = safe_write(list(prog["places"].values()), a.out)
            left = sum(1 for j in jobs if j[0] not in prog["done"])
            print(f"Total {len(prog['places'])} places in {saved or prog_file}. Searches never finished: {left}.")
            if a.loop:
                print(f"Sleeping {a.loop} min, then the next batch... (Ctrl+C to stop)")
                try: time.sleep(a.loop * 60); continue
                except KeyboardInterrupt: pass
            break
        safe_write(list(prog["places"].values()), a.out); break

if __name__ == "__main__":
    main()
