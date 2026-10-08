"""SQL user store (SQLite, stdlib only - no new dependencies).

Why SQL: signup/login used to mutate an in-memory dict, so every account vanished on restart.
Records now persist in backend/users.sqlite.

Passwords are never stored in the clear: PBKDF2-HMAC-SHA256 with a per-user random salt.
No email verification locally (nothing sends mail here) - the row is written straight away,
which is what "locally no need of verification, but save the record in db" means.
"""
import hashlib, os, secrets, sqlite3, time
from pathlib import Path

DB = Path(os.environ.get("SHAADI_DB", Path(__file__).parent / "users.sqlite"))
ALGO = "pbkdf2_sha256"
ITERATIONS = 200_000

SCHEMA = """
create table if not exists users (
  id            integer primary key autoincrement,
  name          text    not null default '',
  email         text    not null unique,
  phone         text    not null default '',
  password      text    not null,          -- 'pbkdf2_sha256$<iterations>$<salt>$<hash>'
  plan          text    not null default 'free',
  created_at    real    not null,
  updated_at    real    not null,
  last_login_at real
)
"""


def _connect():
    DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute("pragma journal_mode=wal")
    c.execute(SCHEMA)
    # databases created before phone existed gain it here (quotations.py checks too - harmless)
    if "phone" not in {r[1] for r in c.execute("pragma table_info(users)")}:
        c.execute("alter table users add column phone text not null default ''")
    return c


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), ITERATIONS).hex()
    return f"{ALGO}${ITERATIONS}${salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt, digest = stored.split("$")
        if algo != ALGO:
            return False
        got = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt),
                                  int(iterations)).hex()
        return secrets.compare_digest(got, digest)
    except (ValueError, AttributeError):        # malformed row -> never a match, never a crash
        return False


def _row_to_dict(r):
    keys = r.keys()
    return {"id": r["id"], "name": r["name"], "email": r["email"], "plan": r["plan"],
            "created_at": r["created_at"], "phone": r["phone"] if "phone" in keys else ""}


def find(email: str):
    """-> dict or None. Email is matched case-insensitively."""
    with _connect() as c:
        r = c.execute("select * from users where email = ?", (email.strip().lower(),)).fetchone()
    return _row_to_dict(r) if r else None


def authenticate(email: str, password: str):
    """-> user dict on success, None when the email or password is wrong."""
    with _connect() as c:
        r = c.execute("select * from users where email = ?", (email.strip().lower(),)).fetchone()
        if not r or not verify_password(password, r["password"]):
            return None
        c.execute("update users set last_login_at = ? where id = ?", (time.time(), r["id"]))
    return _row_to_dict(r)


def create(email: str, password: str, name: str = "", phone: str = ""):
    """Insert a new account. Raises ValueError when the email is already taken.
    The record is written immediately - no verification step exists locally."""
    email = email.strip().lower()
    now = time.time()
    with _connect() as c:
        try:
            cur = c.execute(
                "insert into users (name, email, phone, password, plan, created_at, updated_at, last_login_at)"
                " values (?, ?, ?, ?, 'free', ?, ?, ?)",
                (name.strip(), email, phone.strip(), hash_password(password), now, now, now))
        except sqlite3.IntegrityError:
            raise ValueError("An account with this email already exists — log in instead")
        uid = cur.lastrowid
    return {"id": uid, "name": name.strip(), "email": email, "plan": "free", "created_at": now,
            "phone": phone.strip()}


def set_profile(email: str, fields: dict):
    """name / phone, the two things a user may edit about themselves."""
    allowed = {k: v for k, v in fields.items() if k in ("name", "phone")}
    if not allowed:
        return
    cols = ", ".join(f"{k} = ?" for k in allowed)
    with _connect() as c:
        c.execute(f"update users set {cols}, updated_at = ? where email = ?",
                  (*allowed.values(), time.time(), email.strip().lower()))


def reset_password(email: str, new_password: str):
    """Forgot-password: swap in a new password. Returns the user dict, or None when the
    email is unknown. No token/email round-trip locally - verification is disabled on purpose."""
    email = email.strip().lower()
    now = time.time()
    with _connect() as c:
        r = c.execute("select * from users where email = ?", (email,)).fetchone()
        if not r:
            return None
        c.execute("update users set password = ?, updated_at = ? where id = ?",
                  (hash_password(new_password), now, r["id"]))
    return {"id": r["id"], "name": r["name"], "email": email, "plan": r["plan"],
            "created_at": r["created_at"]}


def set_plan(email: str, plan: str):
    with _connect() as c:
        c.execute("update users set plan = ?, updated_at = ? where email = ?",
                  (plan, time.time(), email.strip().lower()))


def count():
    with _connect() as c:
        return c.execute("select count(*) from users").fetchone()[0]
