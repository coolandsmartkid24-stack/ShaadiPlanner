"""One-off copy of the old SQLite rows into Supabase.

Everything the API kept in backend/users.sqlite (accounts, quotations, hall picks, contact
log, passes, payments) and the LLM cache in backend/enrich_cache.sqlite is moved to the
Supabase database.  Run it once, it is safe to run again: every insert is ON CONFLICT DO
NOTHING, so a second run only adds rows that are missing.

    py migrate_sqlite_to_supabase.py
"""
import json, sqlite3, sys
from pathlib import Path

import db

HERE = Path(__file__).parent

JOBS = [
    # (sqlite file, sqlite table, supabase table, columns copied as they are)
    ("users.sqlite", "users", "users",
     ["id", "name", "email", "phone", "password", "plan", "created_at", "updated_at", "last_login_at"]),
    ("users.sqlite", "quotations", "quotations",
     ["id", "user_email", "title", "host", "event_type", "event_date", "slot", "time", "guests",
      "budget", "menu_json", "services_json", "notes", "pass_id", "status", "created", "updated",
      "deleted"]),
    ("users.sqlite", "quotation_halls", "quotation_halls",
     ["quotation_id", "hall_id", "whatsapp_clicked_at"]),
    ("users.sqlite", "contact_log", "contact_log",
     ["id", "user_email", "quotation_id", "hall_id", "at"]),
    ("users.sqlite", "passes", "passes",
     ["id", "user_email", "quotation_id", "halls", "pkr", "status", "order_id", "created"]),
    ("users.sqlite", "payments", "payments",
     ["identifier", "user_email", "quotation_id", "pass_id", "pkr", "method", "status", "tx_id",
      "created", "updated"]),
    ("enrich_cache.sqlite", "enrich", "enrich", ["id", "data", "ts"]),
    ("enrich_cache.sqlite", "usage", "llm_usage", ["day", "calls"]),
    ("enrich_cache.sqlite", "verified", "verified", ["city", "area", "section", "data", "ts"]),
]

# tables with an identity id column: their sequence must start after the copied rows
SEQUENCES = {"users": "id", "contact_log": "id", "passes": "id", "quotation_halls": "seq"}


def _rows(path: Path, table: str, columns):
    if not path.exists():
        print(f"  - {path.name}: not there, skipped")
        return []
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        have = {r[1] for r in con.execute(f"pragma table_info({table})")}
        if not have:
            print(f"  - {path.name}:{table}: not there, skipped")
            return []
        cols = [c for c in columns if c in have]
        return con.execute(f"select {', '.join(cols)} from {table}").fetchall(), cols
    finally:
        con.close()


def main():
    db.ensure_schema(force=True)
    copied = 0
    for filename, table, target, columns in JOBS:
        got = _rows(HERE / filename, table, columns)
        if not got:
            continue
        rows, cols = got if isinstance(got, tuple) else (got, columns)
        if not rows:
            print(f"  - {filename}:{table}: empty")
            continue
        sql = (f"insert into {target} ({', '.join(cols)}) values ({', '.join('?' for _ in cols)})"
               " on conflict do nothing")
        with db._connect() as c:
            for row in rows:
                c.execute(sql, tuple(row))
        print(f"  - {filename}:{table} -> {target}: {len(rows)} rows")
        copied += len(rows)

    with db._connect() as c:
        for table, column in SEQUENCES.items():
            c.execute(
                f"select setval(pg_get_serial_sequence('{table}', '{column}'),"
                f" coalesce(max({column}), 1), max({column}) is not null) from {table}")
    print(f"done: {copied} rows copied into Supabase")
    return 0


if __name__ == "__main__":
    sys.exit(main())
