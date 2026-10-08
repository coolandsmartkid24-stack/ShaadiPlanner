"""Quotation store, venue list and the single config that decides the plans.

PLANS below is the only place a plan is defined: how many search results it shows, how many
halls may be contacted every 24 hours and what it costs.  The API re-derives usage from
contact_log on every request, so nothing the browser sends can grant an extra hall.
Storage reuses backend/users.sqlite (see users.py): accounts, quotations, contacts and payments
live in one file.  Tables are created/added on first import - existing rows are never touched.
"""
import json, secrets, time
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

import users as userdb

# ---- the plans: ONE dict.  searches = results per category, halls = sends allowed in the
#      rolling window_s period (24 hours for every plan), pkr = price of the subscription.
PLANS = {
    "free": {"name": "Free", "searches": 1, "halls": 1, "pkr": 0, "window_s": 86400,
             "note": "1 hall every 24 hours"},
    "p5":   {"name": "5 Search", "searches": 5, "halls": 8, "pkr": 100, "window_s": 86400,
             "note": "8 halls every 24 hours"},
    "p10":  {"name": "10 Search", "searches": 10, "halls": 20, "pkr": 500, "window_s": 86400,
             "note": "20 halls every 24 hours"},
}
RATE = {"signup": (10, 3600), "login": (20, 300), "contact": (60, 3600),
        "checkout": (30, 3600), "share": (240, 3600)}

EVENTS = ("Mehndi", "Barat", "Walima", "Nikah", "Engagement", "Other")
SLOTS = ("Morning", "Evening")
FIELDS = ("title", "host", "event_type", "event_date", "slot", "time", "guests",
          "budget", "menu", "services", "notes", "halls")

TABLES = """
create table if not exists quotations (
  id            text    primary key,
  user_email    text    not null,
  title         text    not null default '',
  host          text    not null default '',
  event_type    text    not null default 'Barat',
  event_date    text    not null default '',
  slot          text    not null default 'Evening',
  time          text    not null default '7:00 PM',
  guests        integer not null default 300,
  budget        integer not null default 1500000,
  menu_json     text    not null default '[]',
  services_json text    not null default '[]',
  notes         text    not null default '',
  pass_id       text    not null default 'free',
  status        text    not null default 'draft',
  created       real    not null,
  updated       real    not null,
  deleted       integer not null default 0
);
create table if not exists quotation_halls (
  quotation_id       text not null,
  hall_id            text not null,
  whatsapp_clicked_at real,
  primary key (quotation_id, hall_id)
);
create table if not exists contact_log (
  id            integer primary key autoincrement,
  user_email    text not null,
  quotation_id  text not null,
  hall_id       text not null,
  at            real not null
);
create index if not exists ix_contact_user on contact_log (user_email, at);
create index if not exists ix_contact_quote on contact_log (quotation_id);
create table if not exists passes (
  id            integer primary key autoincrement,
  user_email    text not null,
  quotation_id  text not null,
  halls         integer not null,
  pkr           integer not null,
  status        text not null default 'paid',
  order_id      text not null,
  created       real not null
);
create table if not exists payments (
  identifier    text    primary key,   -- PayPak identifier (<= 20 chars), also the order id
  user_email    text    not null,
  quotation_id  text    not null,
  pass_id       text    not null,
  pkr           integer not null,
  method        text    not null default '',
  status        text    not null default 'pending',  -- pending | success | failed | cancelled | expired
  tx_id         text    not null default '',
  created       real    not null,
  updated       real    not null
);
create index if not exists ix_payments_user on payments (user_email, created);
"""

HALLS_FILE = Path(__file__).parent / "halls.json"
HALLS = json.loads(HALLS_FILE.read_text(encoding="utf-8")) if HALLS_FILE.exists() else []
HALLS_BY_ID = {h["id"]: h for h in HALLS}

_migrated = False


def _connect():
    """The users table first (users.py owns its schema), then ours, once per process."""
    global _migrated
    c = userdb._connect()
    if not _migrated:
        cols = {r[1] for r in c.execute("pragma table_info(users)")}
        if "phone" not in cols:
            c.execute("alter table users add column phone text not null default ''")
        c.executescript(TABLES)
        c.commit()
        _migrated = True
    return c


_connect().close()          # migrate at import: a signup straight after boot must find its columns


# ---- venues ----
def search_halls(city="", text="", wa=0):
    rows = HALLS
    if city:
        rows = [h for h in rows if h.get("city") == city]
    if text:
        rows = [h for h in rows if text.lower() in (h.get("name") or "").lower()]
    if wa:
        rows = [h for h in rows if h.get("whatsappNumber")]
    return sorted(rows, key=lambda h: -(h.get("reviewCount") or 0))


def hall(hall_id):
    return HALLS_BY_ID.get(hall_id)


# ---- validation: every rule that can reject a quotation lives here ----
def _str(v, n, label):
    if v is None:
        return ""
    if not isinstance(v, str):
        raise ValueError(f"{label} must be text")
    v = v.strip()
    if len(v) > n:
        raise ValueError(f"{label} is too long (max {n} characters)")
    return v


def _int(v, lo, hi, label):
    try:
        n = int(v)
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be a number")
    if not lo <= n <= hi:
        raise ValueError(f"{label} must be between {lo} and {hi:,}")
    return n


def _list(v, n, item_n, label):
    if not isinstance(v, list):
        raise ValueError(f"{label} must be a list")
    if len(v) > n:
        raise ValueError(f"Too many {label.lower()} (max {n})")
    out = []
    for x in v:
        x = _str(x, item_n, label[:-1] if label.endswith("s") else label)
        if x:
            out.append(x)
    return out


def validate(data):
    """-> {field: value} for the keys present in `data`.  Raises ValueError with a user-facing message.
    Unknown keys are refused so a client can never write a column it should not touch."""
    bad = set(data) - set(FIELDS)
    if bad:
        raise ValueError("Unknown field: " + ", ".join(sorted(bad)))
    out = {}
    for k, v in data.items():
        if k == "title":
            out[k] = _str(v, 100, "Event name")
        elif k == "host":
            out[k] = _str(v, 100, "Your name")
        elif k == "event_type":
            if v not in EVENTS:
                raise ValueError("Pick one of: " + ", ".join(EVENTS))
            out[k] = v
        elif k == "event_date":
            v = _str(v, 10, "Date")
            if v:
                try:
                    d = datetime.strptime(v, "%Y-%m-%d").date()
                except ValueError:
                    raise ValueError("Date must be YYYY-MM-DD")
                if d < date.today():
                    raise ValueError("The event date cannot be in the past")
            out[k] = v
        elif k == "slot":
            if v not in SLOTS:
                raise ValueError("Pick Morning or Evening")
            out[k] = v
        elif k == "time":
            out[k] = _str(v, 20, "Start time") or "7:00 PM"
        elif k == "guests":
            out[k] = _int(v, 20, 5000, "Number of guests")
        elif k == "budget":
            out[k] = _int(v, 0, 1_000_000_000, "Budget")
        elif k == "menu":
            out[k] = _list(v, 40, 60, "Dishes")
        elif k == "services":
            out[k] = _list(v, 20, 40, "Services")
        elif k == "notes":
            out[k] = _str(v, 500, "Notes")
        elif k == "halls":
            if not isinstance(v, list) or len(v) > PLANS["p10"]["halls"]:
                raise ValueError(f"Choose at most {PLANS['p10']['halls']} halls")
            for hid in v:
                if hid not in HALLS_BY_ID:
                    raise ValueError("That hall is not in our list")
            out[k] = list(dict.fromkeys(v))
    return out


# ---- rows -> API ----
def _row(r):
    return {"id": r["id"], "user_email": r["user_email"], "title": r["title"], "host": r["host"],
            "event_type": r["event_type"], "event_date": r["event_date"], "slot": r["slot"],
            "time": r["time"], "guests": r["guests"], "budget": r["budget"],
            "menu": json.loads(r["menu_json"] or "[]"), "services": json.loads(r["services_json"] or "[]"),
            "notes": r["notes"], "pass_id": r["pass_id"], "status": r["status"],
            "created": r["created"], "updated": r["updated"]}


def find(email, qid):
    with _connect() as c:
        r = c.execute("select * from quotations where id = ? and user_email = ? and deleted = 0",
                      (qid, email)).fetchone()
    return _row(r) if r else None


def listing(email):
    with _connect() as c:
        rows = c.execute("select * from quotations where user_email = ? and deleted = 0 order by updated desc",
                         (email,)).fetchall()
    return [_row(r) for r in rows]


def hall_ids(qid):
    with _connect() as c:
        return _hall_ids(c, qid)


def _hall_ids(c, qid):
    rows = c.execute("select hall_id from quotation_halls where quotation_id = ? order by rowid",
                     (qid,)).fetchall()
    return [r[0] for r in rows]


def _set_halls(c, qid, halls):
    """Selection is replaced, but rows keep their whatsapp_clicked_at: a hall the user re-picks
    must still show as already contacted."""
    keep = set(halls)
    for hid in _hall_ids(c, qid):
        if hid not in keep:
            c.execute("delete from quotation_halls where quotation_id = ? and hall_id = ?", (qid, hid))
    for hid in halls:
        c.execute("insert or ignore into quotation_halls (quotation_id, hall_id) values (?, ?)", (qid, hid))


def create(email, data):
    now, qid = time.time(), secrets.token_urlsafe(9)
    halls = data.pop("halls", [])
    with _connect() as c:
        c.execute("insert into quotations (id, user_email, title, host, event_type, event_date, slot, time,"
                  " guests, budget, menu_json, services_json, notes, created, updated)"
                  " values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (qid, email, data.get("title", ""), data.get("host", ""), data.get("event_type", "Barat"),
                   data.get("event_date", ""), data.get("slot", "Evening"), data.get("time", "7:00 PM"),
                   data.get("guests", 300), data.get("budget", 1500000),
                   json.dumps(data.get("menu", [])), json.dumps(data.get("services", [])),
                   data.get("notes", ""), now, now))
        _set_halls(c, qid, halls)
    return find(email, qid)


def update(email, qid, data):
    q = find(email, qid)
    if q is None:
        return None
    halls = data.pop("halls", None)
    cols, vals = [], []
    for k, v in data.items():
        col = {"menu": "menu_json", "services": "services_json"}.get(k, k)
        cols.append(f"{col} = ?")
        vals.append(json.dumps(v) if k in ("menu", "services") else v)
    if cols:
        vals.extend((time.time(), qid, email))
        with _connect() as c:
            c.execute(f"update quotations set {', '.join(cols)}, updated = ? where id = ? and user_email = ?",
                      tuple(vals))
            if halls is not None:
                _set_halls(c, qid, halls)
    elif halls is not None:
        with _connect() as c:
            c.execute("update quotations set updated = ? where id = ? and user_email = ?",
                      (time.time(), qid, email))
            _set_halls(c, qid, halls)
    return find(email, qid)


def remove(email, qid):
    with _connect() as c:
        cur = c.execute("update quotations set deleted = 1, updated = ? where id = ? and user_email = ?",
                        (time.time(), qid, email))
    return cur.rowcount > 0


# ---- allowances: every plan gets its halls in a rolling 24-hour window ----
def sent_halls(qid):
    """Hall ids already contacted on this quotation, oldest first.  contact_log is the record of
    truth, so un-selecting a hall never gives the allowance back."""
    with _connect() as c:
        rows = c.execute("select hall_id from contact_log where quotation_id = ? order by at", (qid,)).fetchall()
    return [r[0] for r in rows]


def plan_of(email):
    """The account's plan id ('free' when there is no account) - the server decides, never the browser."""
    u = userdb.find(email) if email else None
    return (u or {}).get("plan") or "free"


def window(email, cfg, now=None):
    """-> (sends still free this window, when the next one unlocks / 0 when one is free now).
    The window is per account: contacts of the last cfg['window_s'] seconds count against it."""
    now = time.time() if now is None else now
    with _connect() as c:
        rows = [r[0] for r in c.execute(
            "select at from contact_log where user_email = ? and at > ?", (email, now - cfg["window_s"]))]
    if len(rows) >= cfg["halls"]:
        return 0, max(rows) + cfg["window_s"]
    return cfg["halls"] - len(rows), 0


def allowance(email, q):
    """allow = halls the plan may pick (1 / 8 / 20), left = sends left in the 24-hour window."""
    sent = sent_halls(q["id"])
    cfg = PLANS.get(plan_of(email), PLANS["free"])
    left, unlock = window(email, cfg)
    return {"allow": cfg["halls"], "left": left, "sent": sent, "next_free_at": unlock}


def next_free_at(email):
    return window(email, PLANS.get(plan_of(email), PLANS["free"]))[1]


def log_contact(email, q, hall_id):
    """Idempotent: clicking the same hall twice never spends the allowance twice."""
    now = time.time()
    with _connect() as c:
        if not c.execute("select 1 from contact_log where quotation_id = ? and hall_id = ?",
                         (q["id"], hall_id)).fetchone():
            c.execute("insert into contact_log (user_email, quotation_id, hall_id, at) values (?,?,?,?)",
                      (email, q["id"], hall_id, now))
        c.execute("update quotation_halls set whatsapp_clicked_at = coalesce(whatsapp_clicked_at, ?)"
                  " where quotation_id = ? and hall_id = ?", (now, q["id"], hall_id))
        c.execute("update quotations set status = 'sent' where id = ? and status = 'draft'", (q["id"],))


# ---- payments: the plan is granted only when PayPak says the money is in ----
def payment_create(email, qid, pass_id, method):
    """A pending payment row for a plan purchase. Nothing is unlocked here - that happens in
    payment_complete(), once the IPN's HMAC signature has been checked."""
    cfg = PLANS.get(pass_id)
    if cfg is None or cfg["pkr"] <= 0:
        raise ValueError("Unknown plan")
    ident = secrets.token_hex(8).upper()          # 16 chars, fits the gateway's string(20)
    now = time.time()
    with _connect() as c:
        c.execute("insert into payments (identifier, user_email, quotation_id, pass_id, pkr,"
                  " method, status, created, updated) values (?,?,?,?,?,?,'pending',?,?)",
                  (ident, email, qid, pass_id, cfg["pkr"], method, now, now))
    return ident


def payment_get(identifier):
    with _connect() as c:
        r = c.execute("select * from payments where identifier = ?", (identifier or "",)).fetchone()
    return dict(r) if r else None


def payment_finish(identifier, status):
    """Close a payment that will not be completed (gateway refused, cancelled, link expired)."""
    with _connect() as c:
        c.execute("update payments set status = ?, updated = ? where identifier = ? and status = 'pending'",
                  (status, time.time(), identifier))


def payment_complete(identifier, tx_id=""):
    """Activate the plan. Idempotent: a repeated IPN for the same identifier is a no-op, so a
    retry can never buy the plan twice, and the plan still ends up set exactly once."""
    with _connect() as c:
        p = c.execute("select * from payments where identifier = ?", (identifier,)).fetchone()
        if p is None:
            return None
        if p["status"] == "success":
            return dict(p)
        if p["status"] != "pending":
            return None
        cfg = PLANS.get(p["pass_id"])
        if cfg is None:
            return None
        now = time.time()
        cur = c.execute("update payments set status = 'success', tx_id = ?, updated = ?"
                        " where identifier = ? and status = 'pending'",
                        (tx_id or identifier, now, identifier))
        if cur.rowcount != 1:                      # lost the race: another request finished it
            return None
        # store the purchase on the account - same connection, so payment and plan land together
        c.execute("update users set plan = ?, updated_at = ? where email = ?",
                  (p["pass_id"], now, p["user_email"].strip().lower()))
        if p["quotation_id"]:                      # legacy per-quotation receipts stay in step too
            c.execute("insert into passes (user_email, quotation_id, halls, pkr, status, order_id, created)"
                      " values (?,?,?,?,?,?,?)",
                      (p["user_email"], p["quotation_id"], cfg["halls"], cfg["pkr"], "paid", identifier, now))
            c.execute("update quotations set pass_id = ?, updated = ? where id = ? and user_email = ?",
                      (p["pass_id"], now, p["quotation_id"], p["user_email"]))
        out = dict(p)
        out["status"] = "success"
        out["tx_id"] = tx_id or identifier
        return out


def serialize(email, q):
    """The quotation exactly as the wizard sees it (snake_case, like the rest of the API)."""
    a = allowance(email, q)
    return {"id": q["id"], "title": q["title"], "host": q["host"], "event_type": q["event_type"],
            "event_date": q["event_date"], "slot": q["slot"], "time": q["time"], "guests": q["guests"],
            "budget": q["budget"], "menu": q["menu"], "services": q["services"], "notes": q["notes"],
            "pass_id": q["pass_id"], "status": q["status"], "halls": [HALLS_BY_ID[h] for h in hall_ids(q["id"])],
            "sent": a["sent"], "allow": a["allow"], "left": a["left"], "next_free_at": a["next_free_at"],
            "created": q["created"], "updated": q["updated"]}


# ---- rate limits: (count, window) from RATE, in memory, per client address / account ----
class RateLimited(Exception):
    """Too many attempts - main.py turns this into a 429."""


_hits = {}


def rate(key, ident):
    limit, window = RATE[key]
    slot = int(time.time() // window)
    if len(_hits) > 400:                       # drop buckets from windows that have moved on
        for k in [k for k in _hits if not k.endswith(f":{slot}")]:
            _hits.pop(k, None)
    bucket = _hits.setdefault(f"{key}:{ident}:{slot}", [])
    if len(bucket) >= limit:
        raise RateLimited(f"Too many {key} attempts - wait a few minutes and try again.")
    bucket.append(time.time())


# ---- the message the hall receives on WhatsApp (server-filled, never assembled in the browser) ----
def group(n):
    """1500000 -> '15,00,000' (Indian grouping, the way prices and totals are written here)."""
    s = str(int(n or 0))
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join(parts) + "," + tail


def money(n):
    return "Rs " + group(n)


def day_name(yyyy_mm_dd):
    if not yyyy_mm_dd:
        return ""
    try:
        return datetime.strptime(yyyy_mm_dd, "%Y-%m-%d").strftime("%A")
    except ValueError:
        return ""


def nice_date(yyyy_mm_dd):
    if not yyyy_mm_dd:
        return "Date not chosen"
    try:
        d = datetime.strptime(yyyy_mm_dd, "%Y-%m-%d")
    except ValueError:
        return yyyy_mm_dd
    return f"{d.day} {d.strftime('%B %Y')}"


def wa_number(num):
    """Any local format -> the digits wa.me wants (0300... -> 92300...)."""
    d = "".join(ch for ch in str(num or "") if ch.isdigit())
    if d.startswith("00"):
        d = d[2:]
    elif d.startswith("0"):
        d = "92" + d[1:]
    elif d.startswith("3"):
        d = "92" + d
    return d


def message(q, hall, phone, link):
    """Fixed wording, filled in by the server - the PDF link is the only thing that varies."""
    who = q["host"] or ""
    return (f"Assalam o Alaikum {hall['name']} team,\n"
            f"I am {who}. I am planning a {q['event_type']} on {day_name(q['event_date'])}, "
            f"{nice_date(q['event_date'])} ({q['slot']}, {q['time']}) for {q['guests']} guests "
            f"with a budget of {money(q['budget'])}.\n"
            f"Kindly see this quotation and let us know: {link}\n"
            f"Thank you.")


def wa_link(number, text):
    return f"https://wa.me/{wa_number(number)}?text={quote(text, safe='')}"


def find_any(qid):
    """Public lookup for the signed /q/ link - same row, no account filter."""
    with _connect() as c:
        r = c.execute("select * from quotations where id = ? and deleted = 0", (qid,)).fetchone()
    return _row(r) if r else None
