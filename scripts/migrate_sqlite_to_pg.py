"""Copy an ARK SQLite database into Postgres (Neon), preserving every id.

Usage:
    ARK_SQLITE_PATH=./ark.db DATABASE_URL=postgresql://... python scripts/migrate_sqlite_to_pg.py

What it does:
  1. Creates the Postgres schema (same DDL the app boots with).
  2. Copies every table row-for-row, ids included, so post/thread/vote
     references stay intact.
  3. Resets each SERIAL sequence past the copied max(id).
  4. Verifies row counts match on both sides.

Safe to re-run: rows are inserted with explicit ids, so run it against an
EMPTY Postgres database (fresh Neon project). Re-running against a filled
database will raise unique violations instead of duplicating.
"""
import os
import sqlite3
import sys

TABLES = [
    "scenarios",
    "population_cache",
    "agents",
    "events",
    "posts",
    "users",
    "sessions",
    "follows",
    "votes",
    "players",
    "signals",
    "research_cache",
    "post_resources",
    "resource_cache",
]

ID_TABLES = {"agents", "events", "posts", "users", "post_resources"}


def main():
    sqlite_path = os.environ.get("ARK_SQLITE_PATH") or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ark.db"
    )
    database_url = os.environ.get("DATABASE_URL", "").strip()
    if not database_url:
        print("DATABASE_URL is not set.", flush=True)
        return 2
    if not os.path.exists(sqlite_path):
        print(f"SQLite file not found: {sqlite_path}", flush=True)
        return 2
    try:
        import psycopg
    except ImportError:
        print("psycopg is not installed. Run: pip install 'psycopg[binary]'", flush=True)
        return 2

    # Fresh schema on the Postgres side (same DDL the app uses at boot).
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from ark import db as _db

    if not _db.USE_POSTGRES:
        print("Refusing: DATABASE_URL did not select the Postgres backend.", flush=True)
        return 2
    _db.init_db()

    src = sqlite3.connect(sqlite_path)
    src.row_factory = sqlite3.Row
    dst = psycopg.connect(database_url, connect_timeout=20)
    try:
        with dst.cursor() as cur:
            for table in TABLES:
                rows = src.execute(f"SELECT * FROM {table}").fetchall()
                if not rows:
                    print(f"{table}: 0 rows, skipped", flush=True)
                    continue
                cols = [d[0] for d in src.execute(f"SELECT * FROM {table} LIMIT 0").description]
                placeholders = ",".join(["%s"] * len(cols))
                cur.executemany(
                    f'INSERT INTO {table} ({",".join(cols)}) VALUES ({placeholders})',
                    [[r[c] for c in cols] for r in rows],
                )
                print(f"{table}: copied {len(rows)} rows", flush=True)
            dst.commit()
            for table in sorted(ID_TABLES):
                # Table names come from the hardcoded ID_TABLES set above.
                cur.execute(
                    f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
                    f"COALESCE((SELECT max(id) FROM {table}), 1), false)"
                )
            dst.commit()
            ok = True
            for table in TABLES:
                n_src = src.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                n_dst = cur.fetchone()[0]
                mark = "OK" if n_src == n_dst else "MISMATCH"
                if n_src != n_dst:
                    ok = False
                print(f"verify {table}: sqlite={n_src} postgres={n_dst} {mark}", flush=True)
    finally:
        dst.close()
        src.close()
    print("Migration complete." if ok else "Migration completed WITH MISMATCHES.", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
