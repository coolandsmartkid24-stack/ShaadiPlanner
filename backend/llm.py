"""ChatGPT layer. Design goal: pay for as few tokens as possible and trust nothing the model says without a source.

 1. Rules first (free):   your Excel + regex answer most requests, no API call at all.
 2. Intent call (tiny):   only if rules cannot find the area / section. No web search, ~150 output tokens.
 3. Enrich call (batched): ONE web-search call fills missing facts for the top vendors of a section
                            (verified phone, capacity, price, hours, website, instagram). Cached in Supabase for 30 days.
 4. Guards: daily call budget, per-plan access, strict JSON schema, every fact needs a source_url, phone must look Pakistani.
"""
import hashlib, json, os, re, threading, time

from db import _connect as _transaction          # Supabase, one transaction per block (backend/db.py)

MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")          # cheap + supports the web_search tool
MAX_CALLS_PER_DAY = int(os.environ.get("MAX_LLM_CALLS_PER_DAY", "200"))
CACHE_DAYS = 30
DISCOVER_N = 15                                                # fetched once per area/section, cached 30 days


def _slug(s):
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()

def bayes(rating, n):
    """Same Bayesian average as sort_places.py: 5.0 from 2 reviews must not beat 4.7 from 300."""
    if not rating: return 0.0
    n = n or 0; m, C = 15, 4.2
    return (n * rating + m * C) / (n + m)

# ---------------------------------------------------------------- GENERIC PROMPTS (short, static prefix => prompt-cache friendly)
INTENT_PROMPT = """Extract a Pakistani wedding-vendor search. Reply with JSON only.
city: Islamabad|Rawalpindi. area: closest match from AREAS; if the query names a place that is not in AREAS
(return the place name exactly as written), else null. guests: integer or null.
section: venue(marquee/hall)|planner|makeup(parlour/bridal)|dj|photo|sweets, or null.
AREAS: {areas}"""

GEOCODE_PROMPT = """You locate places with web search (Google Maps). Return the approximate centre of the locality
as latitude/longitude. Only answer when the place is in Islamabad or Rawalpindi, Pakistan; otherwise lat/lon null.
label: the place name you found, or null. Reply with JSON only."""

ENRICH_PROMPT = """You verify wedding vendors in Islamabad/Rawalpindi, Pakistan, using web search.
For each input line (id|name|city|area|known_phone) find the vendor's own site, Google Maps, Facebook or Instagram page.
Rules:
- Use only facts a source states. Never guess or infer. Unknown => null.
- phone: Pakistani number in +92 format. capacity_guests: seating/hall capacity as one integer. price_note: short quote like "Rs 1,800/head" or null.
- hours: one short line. instagram: handle or URL. website: URL.
- Every non-null fact needs source_url (the page that states it). If nothing is found for a vendor return all nulls.
Reply with JSON only, one item per input id."""

DISCOVER_PROMPT = """You find wedding vendors in Islamabad/Rawalpindi, Pakistan, using web search (Google Maps, the
vendor's own site, Facebook). List up to {n} real {section} businesses that are physically located in {area}, {city},
or immediately next to it. Leave out anything you cannot place in {area}: a business in another part of {city} is not a result.
For each item give name, address (full, with the locality), phone in +92 format or null, Google rating (0-5) and review
count, hours, website, price_note, capacity_guests, and source_url (the page that states it).
Only use facts a source states; never guess; unknown => null. Reply with JSON only."""

ITEM = {"type": "object", "additionalProperties": False,
        "properties": {k: {"type": ["string", "null"]} for k in ("id", "phone", "website", "price_note", "hours", "instagram", "source_url", "name", "address")}
                      | {"capacity_guests": {"type": ["integer", "null"]}},
        "required": ["id", "phone", "website", "price_note", "hours", "instagram", "source_url", "name", "address", "capacity_guests"]}
ENRICH_SCHEMA = {"type": "object", "additionalProperties": False, "properties": {"items": {"type": "array", "items": ITEM}}, "required": ["items"]}
DITEM = {"type": "object", "additionalProperties": False,
         "properties": {"name": {"type": "string"}, "rating": {"type": ["number", "null"]},
                        "reviews": {"type": ["integer", "null"]}, "phone": {"type": ["string", "null"]},
                        "address": {"type": ["string", "null"]}, "hours": {"type": ["string", "null"]},
                        "website": {"type": ["string", "null"]}, "price_note": {"type": ["string", "null"]},
                        "capacity_guests": {"type": ["integer", "null"]}, "source_url": {"type": ["string", "null"]}},
         "required": ["name", "rating", "reviews", "phone", "address", "hours", "website", "price_note",
                      "capacity_guests", "source_url"]}
DISCOVER_SCHEMA = {"type": "object", "additionalProperties": False,
                   "properties": {"items": {"type": "array", "items": DITEM}}, "required": ["items"]}
INTENT_SCHEMA = {"type": "object", "additionalProperties": False,
                 "properties": {"city": {"type": ["string", "null"]}, "area": {"type": ["string", "null"]}, "guests": {"type": ["integer", "null"]},
                                "section": {"type": ["string", "null"]}}, "required": ["city", "area", "guests", "section"]}
GEOCODE_SCHEMA = {"type": "object", "additionalProperties": False,
                  "properties": {"lat": {"type": ["number", "null"]}, "lon": {"type": ["number", "null"]},
                                 "label": {"type": ["string", "null"]}}, "required": ["lat", "lon", "label"]}
BOX = (33.40, 33.90, 72.80, 73.40)                      # the crawler's window over Islamabad + Rawalpindi

# ---------------------------------------------------------------- storage: cache + budget (Supabase, see backend/db.py)
def db():
    """One Supabase transaction - the three cache tables (enrich / llm_usage / verified) live
    there and are created by db.ensure_schema()."""
    return _transaction()

def cached(ids):
    out, cutoff = {}, time.time() - CACHE_DAYS * 86400
    with db() as c:
        for i in ids:
            r = c.execute("select data, ts from enrich where id=?", (i,)).fetchone()
            if r and r[1] > cutoff: out[i] = json.loads(r[0])
    return out

def store(i, data):
    with db() as c:
        c.execute("insert into enrich (id, data, ts) values (?, ?, ?)"
                  " on conflict (id) do update set data = excluded.data, ts = excluded.ts",
                  (i, json.dumps(data), time.time()))

def spend_call():
    day = time.strftime("%Y-%m-%d")
    with db() as c:
        n = (c.execute("select calls from llm_usage where day=?", (day,)).fetchone() or [0])[0]
        if n >= MAX_CALLS_PER_DAY: return False
        c.execute("insert into llm_usage (day, calls) values (?, ?)"
                  " on conflict (day) do update set calls = excluded.calls", (day, n + 1))
        return True

# ---------------------------------------------------------------- rules parser (free)
WORDS = {"venue": ["marquee", "hall", "venue", "banquet", "lawn", "barat", "walima"], "planner": ["planner", "event", "decor"],
         "makeup": ["makeup", "make-up", "parlour", "parlor", "salon", "bridal", "beautician"], "dj": ["dj", "sound", "music", "band", "dholki"],
         "photo": ["photo", "camera", "video", "cinema", "shoot"], "sweets": ["sweet", "mithai", "bakery", "cake", "dessert"]}

def parse_rules(text, cities):
    t = " " + text.lower().replace(",", " ") + " "
    city = "Rawalpindi" if re.search(r"rawalpindi|pindi|rwp", t) else "Islamabad" if re.search(r"islamabad|isb", t) else None
    area, rest = None, t
    pool = [city] if city else list(cities)
    m = re.search(r"\b([a-i])[\s-]?(\d{1,2})(?:/\d)?\b(?!\s*(guests|people|persons|log|mehmaan))", t)
    if m:
        a = "%s-%d" % (m.group(1).upper(), int(m.group(2)))
        c = next((c for c in pool if a in cities[c]), None)
        if c: area, city, rest = a, city or c, t.replace(m.group(0), " ")
    if not area:
        for c in pool:
            a = next((x for x in cities[c] if x != "Other areas" and not re.match(r"^[A-I]-\d", x) and x.lower() in t), None)
            if a: area, city = a, city or c; break
    guests = next((n for n in (int(x.replace(",", "")) for x in re.findall(r"\d[\d,]{1,5}", rest)) if 20 <= n <= 5000), None)
    section = next((k for k, ws in WORDS.items() if any(w in t for w in ws)), None)
    return {"city": city, "area": area, "guests": guests, "section": section}

# ---------------------------------------------------------------- OpenAI calls
_client = None
def client():
    global _client
    if _client is None and os.environ.get("OPENAI_API_KEY"):
        from openai import OpenAI
        _client = OpenAI()
    return _client

def _json(resp):
    return json.loads(resp.output_text)

def llm_intent(text, cities):
    c = client()
    if not c or not spend_call(): return {}
    areas = ", ".join(sorted({a for v in cities.values() for a in v if a != "Other areas"}))
    kw = {} if MODEL.startswith(("gpt-5", "gpt-6", "o1", "o3", "o4")) else {"temperature": 0}
    r = c.responses.create(model=MODEL, instructions=INTENT_PROMPT.format(areas=areas), input=text[:300], max_output_tokens=120, **kw,
                           text={"format": {"type": "json_schema", "name": "intent", "schema": INTENT_SCHEMA, "strict": True}})
    return _json(r)

PK_PHONE = re.compile(r"^\+92\s?\d{2,3}\s?\d{6,8}$")
def clean_item(it, known):
    """Keep only facts that carry a source and look sane."""
    if not it.get("source_url") or not str(it["source_url"]).startswith("http"): return {}
    out = {"source_url": it["source_url"]}
    if it.get("phone") and PK_PHONE.match(it["phone"].strip()): out["phone_verified"] = it["phone"].strip()
    if isinstance(it.get("capacity_guests"), int) and 20 <= it["capacity_guests"] <= 5000: out["capacity_guests"] = it["capacity_guests"]
    for k in ("website", "price_note", "hours", "instagram"):
        if it.get(k): out[k] = str(it[k])[:160]
    return out if len(out) > 1 else {}

def enrich(vendors):
    """vendors: list of dicts with id,name,city,area,phone. One batched web-search call for everything not cached."""
    ids = [v["id"] for v in vendors]; have = cached(ids)
    todo = [v for v in vendors if v["id"] not in have]
    c = client()
    if todo and c and spend_call():
        lines = "\n".join(f'{v["id"]}|{v["name"]}|{v["city"]}|{v["area"]}|{v["phone"]}' for v in todo)
        try:
            r = c.responses.create(model=MODEL, instructions=ENRICH_PROMPT, input=lines, max_output_tokens=900,
                                   tools=[{"type": "web_search", "search_context_size": "low"}],
                                   text={"format": {"type": "json_schema", "name": "enrich", "schema": ENRICH_SCHEMA, "strict": True}})
            got = {it["id"]: clean_item(it, None) for it in _json(r)["items"]}
        except Exception as e:
            print("enrich failed:", str(e)[:120]); got = {}
        for v in todo:
            have[v["id"]] = got.get(v["id"], {}); store(v["id"], have[v["id"]])
    return have

def discover(area, city, section, n=10, query=""):
    """Web-search real vendors for an area we have no rows for. Cached, and ranked like places.json."""
    if not area and not query: return []
    label = {"venue": "Marquee / Venue", "planner": "Event planner", "makeup": "Parlour / Makeup",
             "dj": "DJ / Sound", "photo": "Photographer", "sweets": "Sweets"}.get(section, section)
    key = "disc::%s::%s::%s" % (city, _slug(area), section)
    have = cached([key])
    if isinstance(have.get(key), list):
        return have[key][:n]
    c = client()
    if not c or not spend_call(): return []
    ask = (query[:200] + " | " if query else "") + f"Find {label} in {area}, {city}"
    try:
        r = c.responses.create(model=MODEL,
                               instructions=DISCOVER_PROMPT.format(n=DISCOVER_N, section=label, area=area, city=city),
                               input=ask, max_output_tokens=2500,
                               tools=[{"type": "web_search", "search_context_size": "low"}],
                               text={"format": {"type": "json_schema", "name": "discover", "schema": DISCOVER_SCHEMA, "strict": True}})
        items = _json(r).get("items", [])
    except Exception as e:
        print("discover failed:", str(e)[:120]); return []
    out = []
    for it in items:
        name = (it.get("name") or "").strip()
        src = str(it.get("source_url") or "")
        if not name or not src.startswith("http"): continue
        phone = (it.get("phone") or "").strip()
        if phone and not PK_PHONE.match(phone): phone = ""
        rating = it.get("rating")
        rating = float(rating) if isinstance(rating, (int, float)) and 0 <= rating <= 5 else None
        reviews = it.get("reviews") if isinstance(it.get("reviews"), int) and it["reviews"] > 0 else 0
        vid = "disc-" + hashlib.md5((name + phone).encode()).hexdigest()[:8]
        store(vid, clean_item({**it, "source_url": src}, None) or {"source_url": src})
        out.append({"id": vid, "name": name, "rating": rating, "reviews": reviews, "phone": phone or None,
                    "address": (it.get("address") or "").strip() or f"{area}, {city}, Pakistan",
                    "hours": it.get("hours"), "website": it.get("website"), "maps_url": None,
                    "area": area, "loc": area, "category": label, "review_text": None,
                    "lat": None, "lon": None, "score": bayes(rating, reviews), "sections": [section],
                    "in_area": True, "discovered": True})
    out.sort(key=lambda r: -r["score"])                    # same order as places.json: best score first
    store(key, out)
    return out[:n]

# ---------------------------------------------------------------- verify + discover: ONE call per open category
CATEGORY_TERMS = {
    "venue": "marriage hall, marquee, banquet hall, lawn, wedding venue",
    "planner": "wedding planner, event planner, event management, wedding decor",
    "makeup": "bridal makeup artist, bridal makeup, ladies salon, beautician",
    "dj": "wedding dj, dj, sound system rental, dholki",
    "photo": "wedding photographer, photography, videographer",
    "sweets": "mithai, sweets shop, bakery, wedding cakes",
}
LABELS = {"venue": "Marquee / Venue", "planner": "Event planner", "makeup": "Parlour / Makeup",
          "dj": "DJ / Sound", "photo": "Photographer", "sweets": "Sweets"}

VERIFY_SYSTEM = """You verify wedding vendors in Islamabad/Rawalpindi, Pakistan, using web search.

You get one input block: city, area, category, guests, how many new vendors are needed (need),
and a check_list of vendors we already have, each line "id|name|phone".

Do two things, in one reply:

1. check: for EVERY line of check_list, find the vendor on the web (own site, Google Maps, Facebook,
   Instagram, a directory) and answer with its id:
   - confirmed - the vendor really is in this area, still open, facts match. source_url = the page that says so.
   - changed   - still open but our name/address/phone is wrong. Give the corrected values, source_url = the page.
   - closed    - the page says it shut down / permanently closed. source_url = that page.
   - not_found - you could not find a page that is really about this exact vendor in this area.
2. items - up to "need" NEW vendors of this category that you find in this area (or immediately next to it).
   Real businesses only: no venues in other parts of the city, no directories, no duplicates of check_list.

Rules:
- Use only facts a source states. Never guess or infer. Unknown => null.
- source_url is required for confirmed, changed and closed, and for every item; it must be an http(s) link
  to the page that states those facts.
- phone: Pakistani number in +92 format (example +92 300 1234567) or null. capacity_guests: seating/hall
  capacity as one integer. price_note: short quote like "Rs 1,800/head". hours: one short line.
  instagram: handle or URL. website: URL. rating: Google rating 0-5. review_count: integer.
- address must include the city name and the locality.
Reply with JSON only: check, items."""

VERIFY_INPUT = """city: {city}
area: {area}
category: {label}
search_terms: {terms}
guests: {guests}
need: {need}
check_list (id|name|phone):
{check}"""

CITEM = {"type": "object", "additionalProperties": False,
         "properties": {"id": {"type": "string"},
                        "status": {"type": "string", "enum": ["confirmed", "changed", "closed", "not_found"]},
                        "source_url": {"type": ["string", "null"]},
                        "name": {"type": ["string", "null"]}, "address": {"type": ["string", "null"]},
                        "phone": {"type": ["string", "null"]}, "website": {"type": ["string", "null"]},
                        "hours": {"type": ["string", "null"]}, "price_note": {"type": ["string", "null"]},
                        "instagram": {"type": ["string", "null"]},
                        "capacity_guests": {"type": ["integer", "null"]}},
         "required": ["id", "status", "source_url", "name", "address", "phone", "website", "hours",
                      "price_note", "instagram", "capacity_guests"]}
NITEM = {"type": "object", "additionalProperties": False,
         "properties": {"name": {"type": "string"}, "address": {"type": "string"},
                        "phone": {"type": ["string", "null"]}, "rating": {"type": ["number", "null"]},
                        "review_count": {"type": ["integer", "null"]}, "hours": {"type": ["string", "null"]},
                        "website": {"type": ["string", "null"]}, "price_note": {"type": ["string", "null"]},
                        "capacity_guests": {"type": ["integer", "null"]},
                        "instagram": {"type": ["string", "null"]},
                        "source_url": {"type": ["string", "null"]}},
         "required": ["name", "address", "phone", "rating", "review_count", "hours", "website",
                      "price_note", "capacity_guests", "instagram", "source_url"]}
VERIFY_SCHEMA = {"type": "object", "additionalProperties": False,
                 "properties": {"check": {"type": "array", "items": CITEM},
                                "items": {"type": "array", "items": NITEM}},
                 "required": ["check", "items"]}

_verify_client = None
def verify_client():
    """The verify call gets its own client: a hard 45 s budget, so one slow search never hangs a page."""
    global _verify_client
    if _verify_client is None and os.environ.get("OPENAI_API_KEY"):
        from openai import OpenAI
        _verify_client = OpenAI(timeout=45)
    return _verify_client

def verified_get(city, area, section):
    with db() as c:
        row = c.execute("select data, ts from verified where city=? and area=? and section=?",
                        (city, area, section)).fetchone()
    if not row or time.time() - row[1] > CACHE_DAYS * 86400: return None
    try: return json.loads(row[0])
    except Exception: return None

def verified_put(city, area, section, data):
    with db() as c:
        c.execute("insert into verified (city, area, section, data, ts) values (?, ?, ?, ?, ?)"
                  " on conflict (city, area, section) do update set data = excluded.data, ts = excluded.ts",
                  (city, area, section, json.dumps(data, ensure_ascii=False), time.time()))

def _empty(status):
    return {"status": status, "checks": {}, "items": [], "closed": []}

_vlock = threading.Lock()
_vflying = {}          # (city, area, section) -> Event: everybody else waits for the one paying call

def verify_and_discover(city, area, section, guests=0):
    """Verify what we already have for this open category and look for more - ONE web call, shared by
    every plan, cached 30 days on (city, area, section) only (guests just re-orders the merge later).
    Never raises: no key / no budget / no answer / too slow => saved results stay as they are."""
    if not area or section not in CATEGORY_TERMS: return _empty("unavailable")
    try:
        hit = verified_get(city, area, section)
        if hit is not None: return {**hit, "status": "cached"}
        key = (city, area, section)
        with _vlock:
            ev = _vflying.get(key)
            owner = ev is None
            if owner:
                ev = threading.Event(); _vflying[key] = ev
        if not owner:                      # someone else is already paying for exactly this answer
            ev.wait(60)
            hit = verified_get(city, area, section)
            return {**hit, "status": "cached"} if hit is not None else _empty("unavailable")
        try:
            return _verify_now(city, area, section, guests)
        finally:
            with _vlock: _vflying.pop(key, None)
            ev.set()
    except Exception as e:
        print("verify_and_discover failed:", str(e)[:160])
        return _empty("unavailable")

def _verify_now(city, area, section, guests):
    c = verify_client()
    if c is None: return _empty("unavailable")            # no key configured
    import main                                           # data lives there; import at call time (avoids a cycle)
    checked_in = main.check_list(city, area, section)     # top 10 by score, area + nearby 12 km
    need = max(0, 10 - len(checked_in))
    if not spend_call(): return _empty("budget")
    msg = VERIFY_INPUT.format(city=city, area=area, label=LABELS[section],
                              terms=CATEGORY_TERMS[section], guests=guests or 0, need=need,
                              check="\n".join('%s|%s|%s' % (v["id"], v["name"], v["phone"])
                                              for v in checked_in) or "(none)")
    try:
        r = c.responses.create(model=MODEL, instructions=VERIFY_SYSTEM, input=msg, max_output_tokens=2200,
                               tools=[{"type": "web_search", "search_context_size": "low"}],
                               text={"format": {"type": "json_schema", "name": "verify",
                                                "schema": VERIFY_SCHEMA, "strict": True}})
        ans = _json(r)
    except Exception as e:
        print("verify failed:", str(e)[:120])
        return _empty("unavailable")
    checks, closed = _apply_checks(ans.get("check"), checked_in)
    items = _apply_items(ans.get("items"), city, area, section, need, checked_in)
    data = {"checks": checks, "items": items, "closed": closed}
    verified_put(city, area, section, data)               # empty answers are cached too: never pay twice
    try: main.append_discovered(items)
    except Exception as e: print("append_discovered failed:", str(e)[:120])
    return {**data, "status": "searched"}

def _apply_checks(raw, checked_in):
    """The model's verdicts become facts we store. A verdict without a page that links to us is not a verdict."""
    by_id = {v["id"]: v for v in checked_in}
    checks, closed = {}, []
    for c in raw if isinstance(raw, list) else []:
        if not isinstance(c, dict): continue
        cid = str(c.get("id") or "")
        orig = by_id.get(cid)
        if orig is None: continue                          # only ids we sent come back
        src = str(c.get("source_url") or "").strip()
        status = c.get("status") if c.get("status") in ("confirmed", "changed", "closed", "not_found") else "not_found"
        if status in ("confirmed", "changed") and not src.startswith("http"):
            status = "not_found"                           # an unsourced "confirmed" is nothing
        rec = {"status": status}
        if status in ("confirmed", "changed"):
            rec["source_url"] = src
            if c.get("name"): rec["name"] = str(c["name"]).strip()[:120]
            if c.get("address"): rec["address"] = str(c["address"]).strip()[:300]
            ph = str(c.get("phone") or "").strip()
            if PK_PHONE.match(ph) and _digits(ph) != _digits(orig.get("phone")):
                rec["phone_verified"] = ph                 # only a different, sane number counts as new
            for k, n in (("website", 200), ("hours", 300), ("price_note", 160), ("instagram", 120)):
                if c.get(k): rec[k] = str(c[k])[:n]
            if isinstance(c.get("capacity_guests"), int) and 20 <= c["capacity_guests"] <= 5000:
                rec["capacity_guests"] = c["capacity_guests"]
        elif status == "closed":
            closed.append(cid)                             # hidden from results, never deleted from places.json
            if src.startswith("http"): rec["source_url"] = src
        checks[cid] = rec
    return checks, closed

def _digits(p):
    return re.sub(r"\D", "", p or "")

def _name_key(name):
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())

def _id_of(name, phone):
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-") + "-" + _digits(phone)[-4:]

def _apply_items(raw, city, area, section, need, checked_in):
    """New vendors are proven server-side before they are used: a page that links to it, a Pakistani
    phone, an address in this city, and no twin of anything we already know."""
    import main
    known, phones, names = main.rows(), set(), set()
    for r in known:
        phones.add(_digits(r.get("phone"))); names.add(_name_key(r.get("name")))
    for v in checked_in:
        phones.add(_digits(v.get("phone"))); names.add(_name_key(v.get("name")))
    out = []
    for it in (raw or [])[:need]:                          # only as many as were asked for
        if not isinstance(it, dict): continue
        name = str(it.get("name") or "").strip()[:120]
        address = str(it.get("address") or "").strip()[:300]
        phone = str(it.get("phone") or "").strip()
        src = str(it.get("source_url") or "").strip()
        if not name or not src.startswith("http"): continue
        if not PK_PHONE.match(phone): continue             # no usable number => not listable
        if city.lower() not in address.lower(): continue   # it must really be in this city
        if _digits(phone) in phones or _name_key(name) in names: continue
        rating = it.get("rating")
        rating = float(rating) if isinstance(rating, (int, float)) and not isinstance(rating, bool) and 1 <= rating <= 5 else None
        rc = it.get("review_count")
        rc = int(rc) if isinstance(rc, int) and not isinstance(rc, bool) and rc >= 0 else None
        cap = it.get("capacity_guests")
        cap = cap if isinstance(cap, int) and not isinstance(cap, bool) and 20 <= cap <= 5000 else None
        phones.add(_digits(phone)); names.add(_name_key(name))
        out.append({"id": _id_of(name, phone), "name": name, "sections": [section], "city": city,
                    "area": area, "rating": rating, "reviews": rc, "score": bayes(rating, rc),
                    "phone": phone, "address": address, "hours": (it.get("hours") or None),
                    "website": (it.get("website") or None), "maps_url": None, "category": LABELS[section],
                    "review_text": None, "lat": None, "lon": None,
                    "capacity_guests": cap, "price_note": (it.get("price_note") or None),
                    "instagram": (it.get("instagram") or None),
                    "source": "web", "source_url": src})
    return out

def geocode(area, city):
    """Where is a place we have never crawled? One web-search call, cached, null if it is not in the twin cities."""
    if not area: return None
    key = "geo::%s::%s" % (city, _slug(area))
    have = cached([key])
    if key in have:
        g = have[key] or {}
        return (g["lat"], g["lon"]) if g.get("lat") and g.get("lon") else None
    c = client()
    if not c or not spend_call(): return None
    try:
        r = c.responses.create(model=MODEL, instructions=GEOCODE_PROMPT, input=f"{area}, {city}, Pakistan",
                               max_output_tokens=150,
                               tools=[{"type": "web_search", "search_context_size": "low"}],
                               text={"format": {"type": "json_schema", "name": "geocode", "schema": GEOCODE_SCHEMA, "strict": True}})
        d = _json(r)
        lat, lon = d.get("lat"), d.get("lon")
        ok = (isinstance(lat, (int, float)) and isinstance(lon, (int, float))
              and BOX[0] <= lat <= BOX[1] and BOX[2] <= lon <= BOX[3])
    except Exception as e:
        print("geocode failed:", str(e)[:120]); return None
    store(key, {"lat": lat if ok else None, "lon": lon if ok else None, "label": d.get("label")})
    return (lat, lon) if ok else None

if __name__ == "__main__":      # warm the cache offline:  python llm.py warm venue 40
    import sys, main
    if sys.argv[1:2] == ["warm"]:
        sec, n = sys.argv[2], int(sys.argv[3]); rows = [r for r in main.rows() if sec in r["sections"]]
        rows.sort(key=lambda r: -r["score"])
        for i in range(0, n, 8):
            enrich([{"id": r["id"], "name": r["name"], "city": r["city"], "area": r["area"], "phone": r["phone"]} for r in rows[i:i + 8]]); print("batch", i // 8 + 1)
