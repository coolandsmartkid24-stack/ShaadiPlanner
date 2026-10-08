"""Shaadi Planner API  -  run:  uvicorn main:app --reload      (reads places.json made by sort_places.py)
Data files: <backend>/places.json (crawler + sorter, read relative to this file) and discovered
vendors found at runtime, which are written to the system temp directory because the filesystem
next to the code is read-only on Vercel.  Both are re-read automatically whenever their
modified time changes."""
import base64, hashlib, hmac, json, math, os, re, tempfile, threading, time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qsl
from dotenv import load_dotenv
load_dotenv()                           # .env first: areas/llm read the environment at import time
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
import areas
import db
import llm
import paypak
import pdfquote
import quotations as qdb
import users as userdb

SECRET = os.environ.get("SHAADI_SECRET", "change-me").encode()
HERE = Path(__file__).resolve().parent
DATA = Path(os.environ.get("PLACES_JSON") or HERE / "places.json").resolve()
DISCOVERED = Path(os.environ.get("DISCOVERED_PLACES_JSON") or HERE / "discovered_places.json").resolve()
# web-found vendors are appended here at runtime: /tmp is the only writable place on Vercel
DISCOVERED_TMP = Path(tempfile.gettempdir()) / "discovered_places.json"
SECTIONS = {"venue": "Marquee / Venue", "planner": "Event planner", "makeup": "Parlour / Makeup",
            "dj": "DJ / Sound", "photo": "Photographer", "sweets": "Sweets"}
# Plans (search depth, 24-hour hall-send allowance, price) live in quotations.PLANS - one config.
VENDOR_FIELDS = ("id", "name", "rating", "reviews", "phone", "address", "hours",
                 "website", "maps_url", "area", "category", "review_text", "source", "source_url")
NEAR_KM = 12.0        # nothing further than this from the centre of the searched area counts as "near" it
IN_AREA_KM = 2.5      # an address that never names the sector only counts as in-area inside this radius
NEAR_BAND = 3.0       # nearby rows are ranked in 3 km bands: nearest band first, best score inside a band

@asynccontextmanager
async def lifespan(_app):
    """Anything that wants the database at boot (legacy plan migration, demo accounts) runs
    here, once per process and never at import time: on Vercel a database hiccup during the
    import would turn every route - /health included - into FUNCTION_INVOCATION_FAILED."""
    try:
        bootstrap()
    except Exception as x:
        print("bootstrap failed (the API still starts):", str(x)[:300])
    yield


app = FastAPI(title="Shaadi Planner API", lifespan=lifespan)
CORS_ORIGINS = [o.strip() for o in os.environ.get(
    "CORS_ORIGINS",
    "https://frontend-psi-blush-74.vercel.app,http://localhost:5173,http://localhost:5174",
).split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
def health():
    """Liveness probe: always 200. `db` tells whether the database answered `select 1`, so
    a broken DATABASE_URL degrades the check instead of failing the invocation."""
    return {"ok": True, "db": db.ping()}


@app.exception_handler(db.DBError)
async def _db_error_handler(_request, exc):
    """A missing DATABASE_URL or a wrong password becomes a 503 with the real reason,
    never an unhandled 500."""
    return JSONResponse(status_code=503, content={"detail": str(exc)})

# ---- area helpers: the crawler stores the *searched* area when the address has no sector, so a PWD
#      vendor crawled from "I-8" arrives labelled I-8.  Everything below re-reads the real address.
SECTOR_RE = re.compile(r"\b([A-I])[\s-]?(\d{1,2})(?:/\d{1,2})?\b", re.I)
ROMAN = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8, "ix": 9, "x": 10}
LOCALITIES = [("soan gardens", "Soan Gardens"), ("satellite town", "Satellite Town"), ("westridge", "Westridge"),
              ("court road", "Court Road"), ("bank road", "Bank Road"), ("peoples colony", "Peoples Colony"),
              ("gulberg green", "Gulberg Green"), ("gulberg", "Gulberg"),
              ("bahria enclave", "Bahria Enclave"), ("bahria town", "Bahria Town"), ("bahria", "Bahria Enclave"),
              ("chaklala scheme 3", "Chaklala Scheme 3"), ("chaklala", "Chaklala"),
              ("margalla town", "Margalla Town"), ("korang town", "Korang Town"), ("jinnah garden", "Jinnah Garden"),
              ("bani gala", "Bani Gala"), ("ghauri town", "Ghauri Town"), ("saddar", "Saddar"),
              ("sohan", "Sohan"), ("nawaz", "Nawaz"), ("barakahu", "Barakahu"), ("khanna", "Khanna"),
              ("pwd", "PWD")]

def norm_area(s):
    """'I 8/4', 'i-08', 'I-8' -> 'I8'.  Anything else -> comparable lowercase words."""
    m = re.match(r"^\s*([A-I])[\s/-]?0*(\d{1,2})(?:/\d+)?\s*$", (s or "").upper())
    if m: return m.group(1) + str(int(m.group(2)))
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()

def is_sector(a):
    return bool(re.match(r"^[A-I][\s/-]?0*\d", (a or "").strip(), re.I))

def addr_sectors(addr):
    return ["%s-%d" % (a.upper(), int(n)) for a, n in SECTOR_RE.findall(addr or "")]

def addr_locality(addr):
    """A named colony/town in the address, when no sector is written in it."""
    t = (addr or "").lower()
    m = re.search(r"\bdha\b(?:\s*phase\s*)?\s*([0-9]+|[ivxl]+)\b", t)
    if m:
        n = m.group(1)
        return "DHA Phase %s" % (n if n.isdigit() else ROMAN.get(n, n))
    for k, v in LOCALITIES:
        if k in t: return v
    return None

def km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))

def _postprocess(data):
    """Give every row a trustworthy locality ('loc') and a centre per (city, area) taken only from
    rows whose address really names that area."""
    buckets, names = {}, {}
    for r in data:
        if r.get("lat") is None: continue
        s = addr_sectors(r.get("address"))
        key = norm_area(s[0]) if s else norm_area(r.get("area"))
        if not key: continue
        buckets.setdefault((r["city"], key), []).append((r["lat"], r["lon"]))
        names.setdefault((r["city"], key), s[0] if s else r.get("area"))
    cent = {k: (sum(p[0] for p in v) / len(v), sum(p[1] for p in v) / len(v)) for k, v in buckets.items()}
    for r in data:
        s, l = addr_sectors(r.get("address")), addr_locality(r.get("address"))
        if s: r["loc"] = s[0]
        elif l: r["loc"] = l
        elif r.get("lat") is not None:
            best, bd = None, NEAR_KM
            for k, c in cent.items():
                if k[0] != r["city"]: continue
                d = km(c, (r["lat"], r["lon"]))
                if d < bd: best, bd = k, d
            r["loc"] = names.get(best) or r.get("area")
        else:
            r["loc"] = r.get("area")
    return cent

def _read(path):
    """One data file -> list of records. Missing/broken files are skipped, never fatal."""
    try:
        recs = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        if path.exists(): print("cannot read", path.name, str(e)[:100])
        return []
    return [r for r in recs if isinstance(r, dict)] if isinstance(recs, list) else []

def _data_files():
    """places.json first, then every discovered-vendors file (the shipped one, then the one
    appended at runtime in the temp directory)."""
    return (DATA, DISCOVERED, DISCOVERED_TMP)


def _load():
    """places.json + discovered_places.json. Only Islamabad and Rawalpindi rows survive;
    a vendor present in more than one file is loaded once."""
    out, seen = [], set()
    for path in _data_files():
        for r in _read(path):
            if r.get("city") not in areas.CITIES: continue
            rid = r.get("id")
            if rid is not None:
                if rid in seen: continue
                seen.add(rid)
            r["area"] = areas.normalize(r.get("area")) or "Other areas"
            out.append(r)
    return out

def _mtimes():
    m = []
    for p in _data_files():
        try: m.append(p.stat().st_mtime)
        except OSError: m.append(0.0)
    return tuple(m)

_cache = {"mtime": None, "rows": [], "cent": {}, "areas": {}}
def rows():
    m = _mtimes()                                  # reload automatically when either file is refreshed
    if m != _cache["mtime"]:
        data = _load()
        _cache.update(mtime=m, rows=data, cent=_postprocess(data), areas=_area_lists(data))
    return _cache["rows"]

# ---- the area menu: every real area of the city, data first, junk never ----
def _allowed_area(city, a):
    if not a or a == "Other areas": return False
    own = areas.WHITELIST_SET[city]
    if areas.is_sector(a): return a in own                     # G-95, H-77, B-05, G-06, G-1 ... never
    if a in own: return True
    return a not in areas.WHITELIST_SET[_other(city)]          # a named area that only belongs to the other city

def _other(city):
    return "Rawalpindi" if city == "Islamabad" else "Islamabad"

def _area_lists(data):
    counts = {c: {} for c in areas.CITIES}
    for r in data:
        c = r.get("city")
        if c in counts and _allowed_area(c, r["area"]):
            counts[c][r["area"]] = counts[c].get(r["area"], 0) + 1
    out = {}
    for c in areas.CITIES:
        names = {n for n in areas.WHITELIST_SET[c] | set(counts[c]) if _allowed_area(c, n)}
        busy = sorted((n for n in names if counts[c].get(n)), key=lambda n: (-counts[c][n], areas.natural_key(n)))
        idle = sorted((n for n in names if not counts[c].get(n)), key=areas.natural_key)
        out[c] = [{"name": n, "count": counts[c].get(n, 0)} for n in busy + idle]
    return out

def area_names(city):
    rows()
    return [a["name"] for a in _cache["areas"].get(city, [])]

def canonical_area(city, area):
    """The label this city actually offers, or None when the area is not one of ours."""
    if city not in areas.CITIES or not area: return None
    n = areas.normalize(area)
    return next((x for x in area_names(city) if areas.normalize(x) == n), None)


# ---- auth: accounts live in Supabase (the `users` table, backend/db.py) so they survive a
#      restart.  See backend/users.py - PBKDF2-hashed passwords, no local email verification.
class Login(BaseModel):
    email: str; password: str

class Signup(BaseModel):
    email: str; password: str; name: str = ""; phone: str = ""

class Reset(BaseModel):
    email: str; password: str

class Profile(BaseModel):
    name: Optional[str] = None
    phone: Optional[str] = None

PHONE_RE = re.compile(r"^(?:\+?92|0092)?[\s-]?0?3\d{2}[\s-]?\d{7}$")

def clean_phone(v):
    """Any Pakistani mobile format -> 03XXXXXXXXX. Refused server-side: the number is printed on
    the quotation and is the only way a hall can reply, so a typo must never reach the database."""
    s = (v or "").strip()
    if not PHONE_RE.match(s):
        raise HTTPException(400, "Enter your WhatsApp number, e.g. 0300 1234567")
    d = "".join(ch for ch in s if ch.isdigit())
    if d.startswith("0092"): d = d[4:]
    elif d.startswith("92"): d = d[2:]
    if d.startswith("0"): d = d[1:]
    return "0" + d

def _client(request: Request) -> str:
    return request.client.host if request.client else "-"

def _rate(key, ident):
    """Per-address / per-account throttle (limits live in quotations.RATE)."""
    try:
        qdb.rate(key, ident)
    except qdb.RateLimited as x:
        raise HTTPException(429, str(x))

class Checkout(BaseModel):
    plan: str
    method: str = "card"

def require_account(authorization: Optional[str] = Header(None)) -> dict:
    """Any logged-in account (with an email) - payments and quotations are never anonymous."""
    u = current_user(authorization)
    if not u.get("email"):
        raise HTTPException(401, "Log in to continue")
    return u

def _return_base(request: Request) -> str:
    """Where PayPak sends the browser back and posts the IPN: APP_BASE_URL when set, else the
    origin the checkout was started from (the frontend), so the return trip lands on the app
    instead of on this API's 404."""
    base = (os.environ.get("APP_BASE_URL") or "").strip() or (request.headers.get("origin") or "")
    return base.rstrip("/") or "http://localhost:5174"

def sign(payload: dict) -> str:
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    return body + "." + hmac.new(SECRET, body.encode(), hashlib.sha256).hexdigest()

def _issue(u: dict) -> dict:
    return {"token": sign({"uid": u["id"], "plan": u["plan"], "exp": time.time() + 7 * 86400}),
            "plan": u["plan"], "name": u["name"], "email": u["email"], "phone": u.get("phone") or ""}

def current_user(authorization: Optional[str] = Header(None)) -> dict:
    """Bearer token -> account row (live plan from the DB, not a frozen copy in the token).
    Missing/expired token -> anonymous free user, so the API stays usable without a login."""
    if not authorization:
        return {"id": None, "plan": "free", "name": "", "email": "", "phone": ""}
    try:
        body, sig = authorization.removeprefix("Bearer ").split(".")
        if not hmac.compare_digest(sig, hmac.new(SECRET, body.encode(), hashlib.sha256).hexdigest()):
            raise ValueError
        p = json.loads(base64.urlsafe_b64decode(body))
        if p["exp"] <= time.time():
            raise ValueError
        if p.get("uid"):
            with userdb._connect() as c:
                r = c.execute("select * from users where id = ?", (p["uid"],)).fetchone()
            if r:
                return userdb._row_to_dict(r)
        return {"id": p.get("uid"), "plan": p["plan"], "name": p.get("name", ""),
                "email": p.get("email", ""), "phone": p.get("phone", "")}
    except Exception:
        return {"id": None, "plan": "free", "name": "", "email": "", "phone": ""}

def current_plan(authorization: Optional[str] = Header(None)) -> str:
    return current_user(authorization)["plan"]

@app.post("/api/login")
def login(b: Login, request: Request):
    _rate("login", _client(request))
    bootstrap()                        # demo accounts, in case the startup attempt found the DB down
    u = userdb.authenticate(b.email, b.password)
    if not u: raise HTTPException(401, "Wrong email or password")
    return _issue(u)

@app.post("/api/signup")
def signup(b: Signup, request: Request):
    """Password 8+ and a real Pakistani WhatsApp number are checked here - the browser's own
    checks are only there to save a round trip."""
    _rate("signup", _client(request))
    bootstrap()
    e = b.email.lower().strip()
    if "@" not in e or "." not in e.split("@")[-1]:
        raise HTTPException(400, "Enter a valid email address")
    if not b.name.strip():
        raise HTTPException(400, "Enter your name")
    if len(b.password) < 8:
        raise HTTPException(400, "Use a password of 8 or more characters")
    phone = clean_phone(b.phone)
    try:
        u = userdb.create(e, b.password, b.name, phone)
    except ValueError as ex:
        raise HTTPException(409, str(ex))
    return _issue(u)

@app.post("/api/forgot")
def forgot(b: Reset, request: Request):
    """Password reset. Locally there is no mail server and no verification step: the new
    password is applied straight away so the flow stays one screen."""
    _rate("login", _client(request))
    bootstrap()
    if len(b.password) < 8:
        raise HTTPException(400, "Use a password of 8 or more characters")
    if userdb.reset_password(b.email, b.password) is None:
        raise HTTPException(404, "No account with that email — sign up instead")
    return {"ok": True}

def _dev_checkout() -> bool:
    """PAYPAK_DEV_GRANT=1 lets a machine with no gateway keys grant a plan (offline work on the
    UI). Off by default and never meant for a deployment: without it a plan starts only when
    PayPak has confirmed the money."""
    return (os.environ.get("PAYPAK_DEV_GRANT") or "").strip().lower() in ("1", "true", "yes", "on")


@app.post("/api/checkout")
def checkout(request: Request, b: Checkout, user: dict = Depends(require_account)):
    """Opens the PayPak hosted checkout page for a plan. No money moves in this handler and no
    card data is ever accepted here - the browser goes to PayPak's own page (the returned url).
    The plan is stored later, by /api/payments/ipn or the return-trip confirm, once the HMAC
    signature on the notification checks out.

    When the gateway keys are missing this answers 503 instead of granting the plan: a plan is
    never activated without a payment, so "keys not configured" can never be read as "free"."""
    _rate("checkout", user["email"])
    cfg = qdb.PLANS.get(b.plan)
    if cfg is None or cfg["pkr"] <= 0:
        raise HTTPException(400, "Choose the 5 Search (Rs 100) or the 10 Search (Rs 500) plan")
    if b.method not in ("jazzcash", "easypaisa", "card"):
        raise HTTPException(400, "Choose JazzCash, Easypaisa or card")
    if user.get("plan") == b.plan:
        raise HTTPException(400, f"You are already on the {cfg['name']} plan")
    if not paypak.configured():
        if not _dev_checkout():
            raise HTTPException(503, "Payments are not set up on this server yet ("
                                     + ", ".join(paypak.missing())
                                     + " missing). A plan starts only after the payment is confirmed.")
        userdb.set_plan(user["email"], b.plan)
        return {"ok": True, "dev": True, "plan": b.plan, "plan_name": cfg["name"],
                "pkr": cfg["pkr"], "method": b.method,
                "token": sign({"uid": user.get("id"), "plan": b.plan, "exp": time.time() + 7 * 86400})}

    base = _return_base(request)
    ident = qdb.payment_create(user["email"], "", b.plan, b.method)
    try:
        started = paypak.initiate(
            identifier=ident,
            amount=cfg["pkr"],
            details=f"Shaadi Planner - {cfg['name']} plan",
            ipn_url=f"{base}/api/payments/ipn",
            success_url=f"{base}/?paid={ident}",
            cancel_url=f"{base}/?cancelled=1",
            customer_name=user.get("name") or "",
            customer_email=user["email"],
        )
    except ValueError as x:
        qdb.payment_finish(ident, "failed")
        raise HTTPException(502, str(x))
    return {"ok": True, "identifier": ident, "url": started["url"], "status": "pending",
            "plan": b.plan, "plan_name": cfg["name"], "pkr": cfg["pkr"], "method": b.method}

def _me(user: dict) -> dict:
    """Everything the header/profile needs. next_free_at is the moment the free hall contact
    refreshes (0 when one is available right now) - the server owns that number."""
    email = user.get("email") or ""
    return {"email": email, "name": user.get("name") or "", "plan": user.get("plan") or "free",
            "id": user.get("id"), "phone": user.get("phone") or "",
            "next_free_at": qdb.next_free_at(email) if email else 0}

@app.get("/api/me")
def me(authorization: Optional[str] = Header(None)):
    """The account behind the bearer token, plus a re-signed token: the session slides forward
    on every call, so somebody who keeps coming back is never dropped in the middle of their
    work. A token that no longer resolves to an account is a 401 (the browser then shows the
    login screen) instead of a silent fall back to Free with somebody else's allowances."""
    bootstrap()
    u = current_user(authorization)
    if authorization and not u.get("email"):
        raise HTTPException(401, "Your session has expired - log in again")
    out = _me(u)
    if u.get("id"):
        out["token"] = sign({"uid": u["id"], "plan": u["plan"], "exp": time.time() + 7 * 86400})
    return out

@app.patch("/api/me")
def patch_me(b: Profile, user: dict = Depends(current_user)):
    if not user.get("email"):
        raise HTTPException(401, "Log in to continue")
    fields = {}
    if b.name is not None:
        n = b.name.strip()
        if not n or len(n) > 100:
            raise HTTPException(400, "Enter a name of up to 100 characters")
        fields["name"] = n
    if b.phone is not None:
        fields["phone"] = clean_phone(b.phone)
    if not fields:
        raise HTTPException(400, "Nothing to update")
    userdb.set_profile(user["email"], fields)
    return _me(userdb.find(user["email"]) or user)

# ---- boot: legacy rows first (the old premium/pro plan ids became p5/p10, and a paid pass
#      bought before the subscription existed is honoured by activating the matching plan on
#      that account), then the demo logins, so the demo accounts work against the SQL store.
#      Run once per process from the lifespan hook above - never at import time, so the module
#      always loads even when the database is down or DATABASE_URL is missing.

_bootstrapped = False
_bootstrap_lock = threading.Lock()


def bootstrap():
    global _bootstrapped
    if _bootstrapped:
        return
    with _bootstrap_lock:
        if _bootstrapped:
            return
        userdb.legacy_plan_migration()
        for _em, _pw, _pl in (("free@demo.pk", "free", "free"),
                              ("premium@demo.pk", "premium", "p5"),
                              ("pro@demo.pk", "pro", "p10")):
            _u = userdb.find(_em)
            if _u is None:
                userdb.create(_em, _pw, _pl.title(), "03001234567")
                userdb.set_plan(_em, _pl)
            else:
                if _u["plan"] != _pl:
                    userdb.set_plan(_em, _pl)
                if not _u.get("phone"):
                    userdb.set_profile(_em, {"phone": "03001234567"})   # quotations print the reply number
        _bootstrapped = True

@app.get("/api/meta")
def meta():
    """{vendors, sections, cities: {city: [{name, count}...]},
    plans: {id: {name, price, results, halls, note}}}."""
    rows()
    plans = {k: {"name": v["name"], "price": {"pkr": v["pkr"], "usd": round(v["pkr"] / 278, 2)},
                 "results": v["searches"], "halls": v["halls"], "note": v["note"]}
             for k, v in qdb.PLANS.items()}
    # Whether the hosted checkout can actually open here. The browser shows the pay button only
    # when this says so, and names the missing keys when it does not - never a silent upgrade.
    return {"vendors": len(rows()), "sections": SECTIONS, "cities": _cache["areas"], "plans": plans,
            "pay": {"configured": paypak.configured(), "mode": paypak.MODE,
                    "missing": paypak.missing()}}

AREA_ALIASES = {
    "pwd": "I-8", "pwd housing society": "I-8", "pwd society": "I-8",
    "sattelite town": "Satellite Town", "satellite town": "Satellite Town",
    "satellite": "Satellite Town",
    "dha": "DHA Phase 2", "dha phase 1": "DHA Phase 2", "dha phase 3": "DHA Phase 2",
    "dha phase 4": "DHA Phase 2", "dha phase 5": "DHA Phase 2",
    "bahria": "Bahria Enclave", "bahria town": "Bahria Enclave",
    "gulberg": "F-10", "gulberg green": "F-10",
    "chaklala": "Chaklala Scheme 3", "chaklala scheme 3": "Chaklala Scheme 3",
    "saddar": "Saddar", "saddar rawalpindi": "Saddar",
}

def resolve_area(city, area):
    """Map whatever the user typed onto an area this city really has (raw text when it is not one)."""
    if not area:
        return area
    names = area_names(city)
    hit = next((x for x in names if areas.normalize(x) == areas.normalize(area)), None)
    if hit:
        return hit
    if areas.is_sector(area):
        return area                    # a sector is ours or it is a 422: 'G-95' must never fuzzy-match 'G-9'
    key = area.strip().lower()
    if key in AREA_ALIASES and AREA_ALIASES[key] in names:
        return AREA_ALIASES[key]
    for a in names:
        if key in a.lower() or a.lower() in key:
            return a
    return area

def require_city(city):
    if city not in areas.CITIES: raise HTTPException(422, f"Unknown city '{city}'")
    return city

def require_area(city, area):
    """422 for anything that is not an area of this city - it also keeps the OpenAI budget safe."""
    a = canonical_area(city, resolve_area(city, area))
    if not a: raise HTTPException(422, f"Unknown area '{area}' for {city}")
    return a


def in_area(r, area, centre):
    """True only when the address (or, failing that, a short distance from the area centre) says so."""
    na = norm_area(area)
    if not na: return False
    if not is_sector(area):                             # Rawalpindi / named areas: the label is the address
        return norm_area(r.get("area")) == na
    s = addr_sectors(r.get("address"))
    if s: return na in {norm_area(x) for x in s}
    l = addr_locality(r.get("address"))
    if l: return norm_area(l) == na                     # PWD, Gulberg, Bahria, Soan Gardens ... never "I-8"
    if norm_area(r.get("area")) != na: return False
    if centre is None or r.get("lat") is None: return True
    return km(centre, (r["lat"], r["lon"])) <= IN_AREA_KM

def area_centre(city, area):
    """Centre of the searched area, taken only from rows whose address names it (never the mislabelled ones)."""
    na, sec, pts = norm_area(area), is_sector(area), []
    for r in rows():
        if r["city"] != city or r.get("lat") is None: continue
        if sec:
            s = addr_sectors(r.get("address"))
            if s and na in {norm_area(x) for x in s}: pts.append((r["lat"], r["lon"]))
        elif norm_area(r.get("area")) == na:
            pts.append((r["lat"], r["lon"]))
    return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)) if pts else None

def pick(city, area, section, centre):
    """Vendors confirmed in the area first (ranked like places.json), then the nearest ones to fill the list."""
    pool = [r for r in rows() if r["city"] == city and section in r["sections"]]
    here, near = [], []
    for r in pool:
        if in_area(r, area, centre):
            here.append(r)
        elif centre is not None and r.get("lat") is not None:
            d = km(centre, (r["lat"], r["lon"]))
            if d <= NEAR_KM: near.append((d, r))
    near.sort(key=lambda t: (t[0] // NEAR_BAND, -t[1]["score"]))   # closest first, best score inside a band
    return here, [r for _, r in near]

def pool(city, area, section, centre=None):
    """Every row of this category, ranked the way places.json is: best score inside the area first,
    then the nearest ones (never further than NEAR_KM from the centre)."""
    if centre is None:
        centre = area_centre(city, area)
    here, near = pick(city, area, section, centre)
    return sorted(here, key=lambda r: -(r["score"] or 0.0)) + near

def check_list(city, area, section):
    """The ten vendors the online check is asked about first: id | name | phone."""
    return [{"id": r["id"], "name": r.get("name") or "", "phone": r.get("phone") or ""}
            for r in pool(city, area, section)[:10]]

def append_discovered(records):
    """Save web-found vendors to the system temp directory (the code directory is read-only
    on Vercel - nothing is ever written next to it).  Temp file + os.replace, so a concurrent
    reader either sees the old file or the new one, never a half-written one."""
    if not records: return
    old, seen = [], set()
    for path in (DISCOVERED, DISCOVERED_TMP):
        for r in _read(path):
            if r.get("id") in seen: continue
            seen.add(r.get("id")); old.append(r)
    keep = [r for r in records if r.get("id") not in seen]
    if not keep: return
    DISCOVERED_TMP.parent.mkdir(parents=True, exist_ok=True)
    tmp = DISCOVERED_TMP.with_name(DISCOVERED_TMP.name + ".tmp")
    tmp.write_text(json.dumps(old + keep, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, DISCOVERED_TMP)
    _cache["mtime"] = None

def _stats(ranked):
    rated = [r["rating"] for r in ranked if r.get("rating")]
    return {"count": len(ranked), "avg": round(sum(rated) / len(rated), 2) if rated else 0,
            "reviews": sum(r.get("reviews") or 0 for r in ranked)}

def vendor(r, area, centre):
    """One result exactly as the API shows it."""
    here = in_area(r, area, centre)
    v = {k: r.get(k) for k in VENDOR_FIELDS}
    v["area"] = area if here else (r.get("loc") or r.get("area"))
    v["in_area"] = here
    v["verified"] = bool(v.get("source_url"))
    return v

@app.get("/api/plan")
def plan_endpoint(city: str, area: str, min_rating: float = 0, guests: int = 0, plan: str = Depends(current_plan)):
    city = require_city(city)
    area = require_area(city, area)
    return plan_for(city, area, plan, min_rating, guests)

def plan_for(city, area, plan, min_rating=0, guests=0):
    """Excel only and fast: it feeds the six category cards, their counts and the free list."""
    centre = area_centre(city, area)
    limit = qdb.PLANS.get(plan, qdb.PLANS["free"])["searches"]
    out = {"plan": plan, "city": city, "area": area, "sections": []}
    for code, label in SECTIONS.items():
        ranked = pool(city, area, code, centre)
        stats = _stats(ranked)
        # FREE: the single top result per category; PAID: top N (min rating filter applies to paid only)
        top = ranked[:limit] if plan == "free" else [r for r in ranked if (r.get("rating") or 0) >= min_rating][:limit]
        vend = [vendor(r, area, centre) for r in top]
        if plan == "free": vend = [_free_vendor(v) for v in vend]
        out["sections"].append({"code": code, "label": label, "available": stats["count"], "stats": stats,
                                "vendors": vend})
    return out

@app.get("/api/section")
def section_endpoint(city: str, area: str, section: str, guests: int = 0, min_rating: float = 0,
                     plan: str = Depends(current_plan)):
    city = require_city(city)
    area = require_area(city, area)
    if section not in SECTIONS: raise HTTPException(422, f"Unknown category '{section}'")
    return section_for(city, area, section, plan, min_rating, guests)

VERIFIED_BOOST = 0.05        # a web-verified twin of two equal rows wins the tie, nothing more

def section_for(city, area, section, plan, min_rating=0, guests=0):
    """The category the user has open. ONE online call per (city, area, section) - shared by every
    plan - checks the vendors we already have and looks for more. Never raises: when the call is
    impossible the saved results are returned unchanged with a discovery status."""
    disc = llm.verify_and_discover(city, area, section, guests)
    centre = area_centre(city, area)
    merged = _merge(pool(city, area, section, centre), disc, area, centre, guests)   # re-read: new rows may have landed
    stats = _stats(merged)
    ranked = merged if plan == "free" else [v for v in merged if (v.get("rating") or 0) >= min_rating]
    ranked.sort(key=lambda v: -v["_rank"])
    if guests: ranked.sort(key=lambda v: v["fits_guests"] is False)      # guests only re-order, never the cache key
    top = [{k: v for k, v in x.items() if k != "_rank"}
           for x in ranked[:qdb.PLANS.get(plan, qdb.PLANS["free"])["searches"]]]
    if plan == "free": top = [_free_vendor(v) for v in top]
    return {"code": section, "label": SECTIONS[section], "available": stats["count"], "stats": stats,
            "vendors": top, "discovery": {"status": disc.get("status") or "unavailable"}}

def _merge(ranked, disc, area, centre, guests):
    """Web vendors join the Excel rows in one list: closed ones disappear, verified facts land on the
    row they belong to, everyone gets the same Bayesian score."""
    checks, items, closed = disc.get("checks") or {}, {i["id"]: i for i in (disc.get("items") or [])}, set(disc.get("closed") or [])
    merged, seen = [], set()

    def add(r):
        v, c, it = vendor(r, area, centre), checks.get(r["id"]), items.get(r["id"])
        if c:
            if c.get("name"): v["name"] = c["name"]
            if c.get("address"): v["address"] = c["address"]
            if c.get("phone_verified"): v["phone"] = c["phone_verified"]
        for src in (c, it):                       # the check's verdict, then the fresh item (same id after a re-discovery)
            if not src: continue
            for k in ("phone_verified", "source_url", "capacity_guests", "price_note", "instagram", "website", "hours"):
                if src.get(k): v[k] = src[k]
            if it is src:
                if it.get("phone"): v["phone"] = it["phone"]
                if it.get("rating"): v["rating"] = it["rating"]
                if it.get("reviews") is not None: v["reviews"] = it["reviews"]
        v["verified"] = bool(v.get("source_url"))
        v["fits_guests"] = None if not (guests and v.get("capacity_guests")) else v["capacity_guests"] >= guests
        v["_rank"] = (r.get("score") or 0.0) + (VERIFIED_BOOST if v["verified"] else 0.0)
        merged.append(v); seen.add(r["id"])

    for r in ranked:
        if r["id"] in closed or r["id"] in seen: continue
        add(r)
    for iid, it in items.items():                 # a vendor found in a neighbouring area is not in the pool
        if iid in closed or iid in seen: continue
        add(it)
    return merged

def _free_vendor(v):
    """Free: one result, and only what the free card shows (with the verified phone when we have one)."""
    out = {k: v.get(k) for k in ("id", "name", "area", "address", "rating", "reviews", "phone")}
    out["limited"] = True
    return out

class Ask(BaseModel):
    text: str

@app.post("/api/ask")
def ask(b: Ask, plan: str = Depends(current_plan)):
    """Natural-language search. Rules first (free), ChatGPT only when a rule cannot place the query."""
    cities = {c: area_names(c) for c in areas.CITIES}
    intent, source = llm.parse_rules(b.text[:300], cities), "rules"
    if not (intent["area"] and intent["section"]):
        extra = llm.llm_intent(b.text, cities)
        if extra:
            source = "chatgpt"
            for k, v in extra.items(): intent[k] = intent.get(k) or v
    city = require_city(intent["city"] or "Islamabad")
    area = canonical_area(city, intent["area"]) if intent["area"] else None
    if not area:
        area = next((a["name"] for a in _cache["areas"][city] if a["count"]), cities[city][0])
    intent["area"] = area
    res = plan_for(city, area, plan, 0, intent["guests"] or 0)
    if intent["section"] in SECTIONS:              # the category the user asked for gets the online check
        live = section_for(city, area, intent["section"], plan, 0, intent["guests"] or 0)
        res["sections"] = [live if s["code"] == intent["section"] else s for s in res["sections"]]
    return {"intent": {**intent, "city": city}, "source": source, "result": res}


# ---- quotation planner: the main flow after login.  Allowances come from quotations.PLANS and
#      contact_log - the browser only ever asks; it is never trusted with how many halls are left.

def _checked(body: dict) -> dict:
    try:
        return qdb.validate(body)
    except ValueError as x:
        raise HTTPException(422, str(x))

def _own(email: str, qid: str) -> dict:
    q = qdb.find(email, qid)
    if q is None:
        raise HTTPException(404, "Quotation not found")
    return q

def _pdf_response(q: dict, who: dict) -> Response:
    ids = qdb.hall_ids(q["id"])
    data = pdfquote.quotation_pdf(q, qdb.hall(ids[0]) if ids else None,
                                  {"name": who.get("name") or "", "phone": who.get("phone") or ""})
    return Response(data, media_type="application/pdf",
                    headers={"Content-Disposition": 'attachment; filename="Quotation.pdf"'})

def signed_url(request: Request, qid: str):
    """A link the hall can open without an account, valid 30 days. The expiry rides inside sig
    so the URL stays exactly /q/<id>?sig=..."""
    exp = int(time.time() + 30 * 86400)
    sig = f"{exp}.{hmac.new(SECRET, f'{qid}.{exp}'.encode(), hashlib.sha256).hexdigest()}"
    return str(request.base_url).rstrip("/") + f"/q/{qid}?sig={sig}", exp

def _valid_sig(qid: str, sig: str) -> bool:
    try:
        exp_s, mac = sig.split(".", 1)
        exp = int(exp_s)
    except Exception:
        return False
    want = hmac.new(SECRET, f"{qid}.{exp}".encode(), hashlib.sha256).hexdigest()
    return exp >= time.time() and hmac.compare_digest(mac, want)

def _spent(user: dict, st: dict) -> str:
    """The 403 wording when the plan's 24-hour window has no sends left in it."""
    name = qdb.PLANS.get(user.get("plan") or "free", qdb.PLANS["free"])["name"]
    if st["next_free_at"]:
        mins = max(0, int((st["next_free_at"] - time.time()) // 60))
        return (f"Your {name} plan gives {st['allow']} hall sends every 24 hours and they are all "
                f"used for now. The next one unlocks in {mins // 60}h {mins % 60}m.")
    return f"Your {name} plan gives {st['allow']} hall sends every 24 hours - they are all used for now."

@app.get("/api/halls")
def halls_endpoint(city: str = "", q: str = "", wa: int = 0):
    """Venue list behind the Hall step: city and name filters, optionally WhatsApp-ready."""
    return qdb.search_halls(city.strip(), q.strip(), wa)

@app.get("/api/quotations")
def quotations_list(user: dict = Depends(require_account)):
    email = user["email"]
    return [qdb.serialize(email, row) for row in qdb.listing(email)]

@app.post("/api/quotations")
def quotation_create(body: dict, user: dict = Depends(require_account)):
    return qdb.serialize(user["email"], qdb.create(user["email"], _checked(body)))

@app.get("/api/quotations/{qid}")
def quotation_get(qid: str, user: dict = Depends(require_account)):
    return qdb.serialize(user["email"], _own(user["email"], qid))

@app.patch("/api/quotations/{qid}")
def quotation_patch(qid: str, body: dict, user: dict = Depends(require_account)):
    _own(user["email"], qid)
    return qdb.serialize(user["email"], qdb.update(user["email"], qid, _checked(body)))

@app.delete("/api/quotations/{qid}")
def quotation_delete(qid: str, user: dict = Depends(require_account)):
    if not qdb.remove(user["email"], qid):
        raise HTTPException(404, "Quotation not found")
    return {"ok": True}

@app.post("/api/quotations/{qid}/contact")
def quotation_contact(qid: str, body: dict, user: dict = Depends(require_account)):
    """The click on "Send on WhatsApp" - the only place a contact is counted, and the only place
    the allowance is enforced."""
    _rate("contact", user["email"])
    q = _own(user["email"], qid)
    hall_id = body.get("hall_id") or ""
    if hall_id not in qdb.hall_ids(qid):
        raise HTTPException(400, "Choose that hall in the Hall step first")
    st = qdb.allowance(user["email"], q)
    if hall_id not in st["sent"]:          # re-opening a hall already contacted never spends anything
        if st["left"] <= 0:
            raise HTTPException(403, _spent(user, st))
        try:
            qdb.validate({"event_date": q["event_date"]})   # the date may have gone past since it was saved
        except ValueError as x:
            raise HTTPException(422, str(x))
        if not q["menu"]:
            raise HTTPException(422, "Add at least one dish to the menu before sending")
    qdb.log_contact(user["email"], q, hall_id)
    return qdb.serialize(user["email"], qdb.find(user["email"], qid))

@app.post("/api/quotations/{qid}/share-link")
def quotation_share(qid: str, body: dict, request: Request, user: dict = Depends(require_account)):
    """Mints the signed PDF link and the exact wording of the message. Both are built here so the
    text a hall receives can never drift from what the product approved."""
    _rate("share", user["email"])
    q = _own(user["email"], qid)
    hall_id = body.get("hall_id") or ""
    hall = qdb.hall(hall_id)
    if hall is None or hall_id not in qdb.hall_ids(qid):
        raise HTTPException(400, "Choose that hall in the Hall step first")
    url, exp = signed_url(request, qid)
    text = qdb.message(q, hall, user.get("phone") or "", url)
    num = hall.get("whatsappNumber")
    return {"hall_id": hall_id, "url": url, "expires_at": exp, "message": text,
            "wa_url": qdb.wa_link(num, text) if num else "", "has_whatsapp": bool(num)}

@app.get("/api/quotations/{qid}/pdf")
def quotation_pdf_endpoint(qid: str, user: dict = Depends(require_account)):
    return _pdf_response(_own(user["email"], qid), user)

@app.get("/q/{qid}")
def public_quotation_pdf(qid: str, sig: str = ""):
    """The link the hall opens: signed, 30 days, PDF only - no session, no other field."""
    if not _valid_sig(qid, sig):
        raise HTTPException(403, "This link has expired or is not valid")
    q = qdb.find_any(qid)
    if q is None:
        raise HTTPException(404, "Quotation not found")
    owner = userdb.find(q["user_email"]) or {}
    return _pdf_response(q, {"name": q["host"] or owner.get("name") or "", "phone": owner.get("phone") or ""})

# ---- payments: PayPak (paybost.com) owns the money, we only own the record ------------------
#      /api/checkout redirects the browser to the gateway's hosted page; the plan is stored on
#      the account by /api/payments/ipn once the HMAC signature on the notification checks out
#      (and by the return-trip confirm when the IPN cannot reach localhost).

async def _payload(request: Request) -> dict:
    """PayPak may post form-encoded (PHP default) or JSON - both come back as a plain dict."""
    try:
        if "json" in (request.headers.get("content-type") or "").lower():
            body = await request.json()
            return dict(body) if isinstance(body, dict) else {}
        try:
            form = await request.form()
            return {k: v for k, v in form.items()}
        except Exception:
            # python-multipart missing on this machine: urlencoded still parses by hand
            raw = (await request.body()).decode("utf-8", "replace")
            return dict(parse_qsl(raw, keep_blank_values=True))
    except Exception:
        return {}

def _ipn_data(form: dict) -> dict:
    """`data` is an array: a nested dict, a JSON string, or PHP-style data[amount] keys. A return
    trip that carries the same fields flat on the query string counts as the same data."""
    d = form.get("data")
    if isinstance(d, dict):
        return d
    if isinstance(d, str) and d.strip().startswith("{"):
        try:
            return json.loads(d)
        except ValueError:
            return {}
    nested = {str(k)[5:-1]: v for k, v in form.items()
              if str(k).startswith("data[") and str(k).endswith("]")}
    if nested:
        return nested
    return {k: v for k, v in form.items() if k in ("amount", "status", "transaction_id", "txn_id")}

def _amount_matches(p: dict, data: dict) -> bool:
    """The gateway signs the amount it received - it must still be the amount we asked for."""
    try:
        return abs(float(data.get("amount") or 0) - float(p["pkr"])) < 0.011
    except (TypeError, ValueError):
        return False

def _payment_view(p: dict, email: str) -> dict:
    q = qdb.find(email, p["quotation_id"])
    return {"identifier": p["identifier"], "status": p["status"], "pass": p["pass_id"],
            "plan": p["pass_id"], "pkr": p["pkr"], "method": p["method"],
            "quotation_id": p["quotation_id"], "quotation": qdb.serialize(email, q) if q else None}

@app.post("/api/payments/ipn")
async def payments_ipn(request: Request):
    """Instant Payment Notification. We trust nothing but the HMAC signature over amount+identifier,
    checked against the payment row we created: a forged POST unlocks nothing (it simply answers
    ok:false). Always 200, so the gateway does not retry a payload we already rejected."""
    form = await _payload(request)
    ident = str(form.get("identifier") or "")
    data = _ipn_data(form)
    p = qdb.payment_get(ident) if ident else None
    ok = False
    if p and _amount_matches(p, data) and paypak.verify(form.get("status"), ident,
                                                       form.get("signature"), data.get("amount", "")):
        qdb.payment_complete(ident, str(data.get("transaction_id") or data.get("txn_id") or ""))
        ok = True
    return {"ok": ok}

@app.get("/api/payments/{identifier}")
def payment_status(identifier: str, user: dict = Depends(require_account)):
    """Where the browser lands after PayPak: poll this until the payment is no longer pending."""
    p = qdb.payment_get(identifier)
    if p is None or p["user_email"] != user["email"]:
        raise HTTPException(404, "Payment not found")
    return _payment_view(p, user["email"])

@app.post("/api/payments/{identifier}/confirm")
async def payment_confirm(request: Request, identifier: str, user: dict = Depends(require_account)):
    """Return-trip fallback. The IPN is the real confirmation, but PayPak can only POST it to a
    public ipn_url - on localhost it never arrives - so the browser asks us to re-check once it
    is back. With a signature attached it is verified in any mode; without one it is allowed only
    in sandbox mode, because a live payment must always be confirmed by the gateway itself."""
    p = qdb.payment_get(identifier)
    if p is None or p["user_email"] != user["email"]:
        raise HTTPException(404, "Payment not found")
    if p["status"] == "success":
        return _payment_view(p, user["email"])
    if p["status"] != "pending":
        raise HTTPException(409, f"This payment is {p['status']}")
    if time.time() - p["created"] > 1800:
        qdb.payment_finish(identifier, "expired")
        raise HTTPException(410, "This payment link has expired - start the checkout again")
    form = await _payload(request)
    # The gateway may hand the browser back a status of its own. A clearly failed answer closes
    # the payment here instead of letting the UI wait for a confirmation that never comes; any
    # other value (PayPak sends nothing on a plain success redirect) is treated as success.
    st = str(form.get("status") or "").strip().lower()
    if st in ("failed", "fail", "cancel", "cancelled", "declined", "error", "expired"):
        qdb.payment_finish(identifier, "cancelled" if st.startswith("cancel") else "failed")
        raise HTTPException(409, f"This payment was {st} - your plan was not changed")
    sent = str(form.get("signature") or "")
    if sent:
        data = _ipn_data(form)
        if not _amount_matches(p, data) or not paypak.verify("success", identifier,
                                                             sent, data.get("amount", "")):
            raise HTTPException(400, "PayPak signature did not match")
    elif paypak.MODE == "live":
        raise HTTPException(403, "Waiting for PayPak to confirm this payment")
    done = qdb.payment_complete(identifier, str(form.get("transaction_id") or ""))
    if done is None:
        raise HTTPException(409, "This payment could not be completed")
    return _payment_view(done, user["email"])

