"""Supabase user store (PostgreSQL through backend/db.py).

History: signup/login first mutated an in-memory dict, then persisted in backend/users.sqlite.
Accounts, plans and phone numbers now live in the Supabase `users` table, so they survive a
restart and follow the app to any host.

Passwords are never stored in the clear: PBKDF2-HMAC-SHA256 with a per-user random salt.
No email verification locally (nothing sends mail here) - the row is written straight away,
which is what "locally no need of verification, but save the record in db" means.
"""
import hashlib, secrets, time

import db

# Every caller shares db's one transaction helper: `with userdb._connect() as c:`.
_connect = db._connect

ALGO = "pbkdf2_sha256"
ITERATIONS = 200_000


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
    try:
        with _connect() as c:
            r = c.execute(
                "insert into users (name, email, phone, password, plan, created_at, updated_at, last_login_at)"
                " values (?, ?, ?, ?, 'free', ?, ?, ?) returning id",
                (name.strip(), email, phone.strip(), hash_password(password), now, now, now)).fetchone()
    except Exception as x:
        if db.unique_violation(x):
            raise ValueError("An account with this email already exists — log in instead")
        raise
    return {"id": r["id"], "name": name.strip(), "email": email, "plan": "free", "created_at": now,
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


def set_plan_by_id(user_id, plan: str):
    with _connect() as c:
        c.execute("update users set plan = ?, updated_at = ? where id = ?",
                  (plan, time.time(), user_id))


def find_by_id(user_id):
    with _connect() as c:
        r = c.execute("select * from users where id = ?", (user_id,)).fetchone()
    return _row_to_dict(r) if r else None


def legacy_plan_migration():
    """Rows written before the plan ids were renamed (premium/pro -> p5/p10), plus paid
    passes bought before the subscription existed. Idempotent, runs once at boot."""
    with _connect() as c:
        c.execute("update users set plan = 'p5' where plan = 'premium'")
        c.execute("update users set plan = 'p10' where plan = 'pro'")
        c.execute("update users set plan = 'p5' where plan = 'free' and email in"
                  " (select user_email from passes where status = 'paid' and halls >= 5 and halls < 10)")
        c.execute("update users set plan = 'p10' where plan = 'free' and email in"
                  " (select user_email from passes where status = 'paid' and halls >= 10)")


def count():
    with _connect() as c:
        return c.execute("select count(*) from users").fetchone()[0]
