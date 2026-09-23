"""Persistence for ARK: local SQLite by default, Neon Postgres when set.

Backend selection:
  DATABASE_URL set -> Postgres via a psycopg3 connection pool (Neon).
                      Use the pooled connection string from the Neon dashboard.
  otherwise         -> local SQLite file (DB_PATH / ARK_DB_PATH).

The Postgres path translates the codebase's SQLite dialect on the fly, so
core.py / auth.py / main.py need no SQL changes:
  ? placeholders      -> %s
  LIKE                -> ILIKE (SQLite LIKE is case-insensitive; PG LIKE is not)
  INSERT (id tables)  -> appends RETURNING id, exposed as cursor.lastrowid
  rows                -> support both row["col"] and row[0]
"""
import os
import re
import json
import sqlite3
from contextlib import contextmanager

DB_PATH = os.environ.get("ARK_DB_PATH") or os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "ark.db"
)

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
USE_POSTGRES = bool(DATABASE_URL)


# ---------------------------------------------------------------------------
# Shared row type (Postgres path): name AND index access, dict-compatible.
# ---------------------------------------------------------------------------
class Row(dict):
    """A row supporting row["col"], row[0], dict(row), and iteration."""

    def __init__(self, columns, values):
        super().__init__(zip(columns, values))
        self._values = tuple(values)

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return super().__getitem__(key)


# ---------------------------------------------------------------------------
# SQL translation (Postgres path only; SQLite runs untouched).
# ---------------------------------------------------------------------------
_ID_TABLES = {"posts", "events", "agents", "users", "post_resources"}
_INSERT_RE = re.compile(r"^\s*INSERT\s+INTO\s+\"?([A-Za-z_][\w$]*)\"?", re.IGNORECASE)
_LIKE_RE = re.compile(r"\bLIKE\b")


def translate_sql(sql):
    """Translate SQLite-dialect SQL to Postgres. Pure function (tested)."""
    out = sql.replace("?", "%s")
    out = _LIKE_RE.sub("ILIKE", out)
    return out


def _wants_returning(sql):
    """True when an INSERT targets an id table and has no RETURNING yet."""
    m = _INSERT_RE.match(sql)
    return bool(m) and m.group(1).lower() in _ID_TABLES and "returning" not in sql.lower()


def _row_from_cursor(cur, tup):
    cols = [d.name for d in (cur.description or [])]
    return Row(cols, tup)


# ---------------------------------------------------------------------------
# Postgres connection pool (lazy: no import, thread, or socket until used).
# ---------------------------------------------------------------------------
_pool = None


def _pool():
    global _pool
    if _pool is None:
        try:
            from psycopg_pool import ConnectionPool
        except ImportError as e:
            raise RuntimeError(
                "DATABASE_URL is set but psycopg is not installed. "
                "Run: pip install 'psycopg[binary,pool]'"
            ) from e
        _pool = ConnectionPool(
            DATABASE_URL,
            min_size=0,
            max_size=25,
            timeout=30,
            kwargs={"prepare_threshold": None, "connect_timeout": 10},
        )
    return _pool


def close_pool():
    """Close the Postgres pool if one was opened (safe no-op otherwise)."""
    global _pool
    if _pool is not None:
        try:
            _pool.close()
        except Exception:
            pass
        _pool = None


class _PGCursor:
    """psycopg cursor with SQLite-compatible surface."""

    def __init__(self, cur):
        self._cur = cur
        self._lastrowid = None

    def execute(self, sql, params=()):
        translated = translate_sql(sql)
        if _wants_returning(translated):
            self._cur.execute(translated + " RETURNING id", params)
            row = self._cur.fetchone()
            self._lastrowid = row[0] if row else None
        else:
            self._cur.execute(translated, params)
        return self

    @property
    def lastrowid(self):
        return self._lastrowid

    @property
    def rowcount(self):
        return self._cur.rowcount

    @property
    def description(self):
        return self._cur.description

    def fetchone(self):
        r = self._cur.fetchone()
        return None if r is None else _row_from_cursor(self._cur, r)

    def fetchall(self):
        return [_row_from_cursor(self._cur, r) for r in self._cur.fetchall()]

    def fetchmany(self, size=None):
        rows = self._cur.fetchmany(size) if size else self._cur.fetchall()
        return [_row_from_cursor(self._cur, r) for r in rows]

    def __iter__(self):
        return iter(self.fetchall())

    def close(self):
        try:
            self._cur.close()
        except Exception:
            pass


class _PGConn:
    """Pooled Postgres connection with sqlite3-like context semantics.

    `with get_conn() as c:` commits on success, rolls back on error, and
    always returns the connection to the pool — mirroring sqlite3's
    context-manager behavior the codebase relies on.
    """

    def __init__(self, conn, pool):
        self._conn = conn
        self._pool = pool

    def cursor(self):
        return _PGCursor(self._conn.cursor())

    def execute(self, sql, params=()):
        return self.cursor().execute(sql, params)

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        try:
            self._pool.putconn(self._conn)
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                self._conn.commit()
            else:
                self._conn.rollback()
        finally:
            try:
                self._pool.putconn(self._conn)
            except Exception:
                pass
        return False


def get_conn():
    """Open a connection: pooled Postgres when DATABASE_URL is set, else SQLite."""
    if USE_POSTGRES:
        pool = _pool()
        return _PGConn(pool.getconn(), pool)
    # Create the parent dir on demand: on first boot against a fresh
    # volume mount (e.g. /data on PXXL/Railway) the directory may not
    # exist yet, and sqlite cannot create the file without it.
    try:
        os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    except Exception:
        pass
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=20)
    conn.row_factory = sqlite3.Row
    journal_mode = "MEMORY" if os.environ.get("ARK_TESTING") == "1" else "WAL"
    conn.execute(f"PRAGMA journal_mode={journal_mode}")
    conn.execute("PRAGMA busy_timeout=20000")
    # NORMAL is crash-safe under WAL and avoids an fsync per commit.
    # Generation opens many short transactions; FULL would stall every one.
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def _col_names(conn, table):
    if USE_POSTGRES:
        rows = conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name=?",
            (table,),
        ).fetchall()
        return {r["column_name"] for r in rows}
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _ensure_cols(conn, table, cols):
    existing = _col_names(conn, table)
    for name, ddl in cols.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def _dedupe_events(conn):
    """Collapse legacy seed duplicates while preserving every referenced post."""
    groups = conn.execute(
        "SELECT scenario_key, day, date, title, MIN(id) AS keep_id, "
        "MAX(generated) AS generated, COUNT(*) AS n "
        "FROM events GROUP BY scenario_key, day, date, title HAVING COUNT(*) > 1"
    ).fetchall()
    for group in groups:
        duplicate_ids = conn.execute(
            "SELECT id FROM events WHERE scenario_key=? AND day=? AND date=? AND title=? AND id<>?",
            (
                group["scenario_key"],
                group["day"],
                group["date"],
                group["title"],
                group["keep_id"],
            ),
        ).fetchall()
        for duplicate in duplicate_ids:
            conn.execute(
                "UPDATE posts SET event_id=? WHERE scenario_key=? AND event_id=?",
                (group["keep_id"], group["scenario_key"], duplicate["id"]),
            )
            conn.execute("DELETE FROM events WHERE id=?", (duplicate["id"],))
        conn.execute(
            "UPDATE events SET generated=? WHERE id=?",
            (group["generated"], group["keep_id"]),
        )


_PG_DDL = [
    """CREATE TABLE IF NOT EXISTS scenarios (
        key TEXT PRIMARY KEY,
        title TEXT, date_range TEXT, days INTEGER,
        tagline TEXT, sim_badge TEXT, hook TEXT,
        origin TEXT DEFAULT 'builtin',
        source_text TEXT DEFAULT '',
        owner_id INTEGER DEFAULT NULL,
        created_at TEXT DEFAULT (now()::text)
    )""",
    """CREATE TABLE IF NOT EXISTS population_cache (
        scenario_key TEXT PRIMARY KEY,
        data TEXT DEFAULT '[]',
        created_at TEXT DEFAULT (now()::text)
    )""",
    """CREATE TABLE IF NOT EXISTS agents (
        id SERIAL PRIMARY KEY,
        scenario_key TEXT,
        agent_key TEXT,
        name TEXT, handle TEXT, category TEXT, verified INTEGER,
        avatar_type TEXT, avatar_text TEXT, avatar_url TEXT DEFAULT '',
        bio TEXT, voice TEXT, interests TEXT,
        emotion TEXT DEFAULT '{}',
        relationships TEXT DEFAULT '{}',
        news_style TEXT DEFAULT '',
        background INTEGER DEFAULT 0,
        outspoken INTEGER DEFAULT 1,
        UNIQUE(scenario_key, agent_key)
    )""",
    """CREATE TABLE IF NOT EXISTS events (
        id SERIAL PRIMARY KEY,
        scenario_key TEXT,
        day INTEGER, date TEXT, title TEXT,
        involved TEXT, tags TEXT,
        generated INTEGER DEFAULT 0,
        media TEXT DEFAULT '',
        media_title TEXT DEFAULT '',
        location TEXT DEFAULT '',
        lat DOUBLE PRECISION DEFAULT 0,
        lon DOUBLE PRECISION DEFAULT 0
    )""",
    """CREATE TABLE IF NOT EXISTS posts (
        id SERIAL PRIMARY KEY,
        scenario_key TEXT,
        day INTEGER, date TEXT,
        agent_key TEXT, event_id INTEGER,
        parent_id INTEGER DEFAULT NULL,
        kind TEXT DEFAULT 'post',
        text TEXT,
        thought TEXT DEFAULT '',
        likes INTEGER DEFAULT 0,
        dislikes INTEGER DEFAULT 0,
        clock TEXT DEFAULT '',
        image_url TEXT DEFAULT '',
        video_url TEXT DEFAULT '',
        footage_label TEXT DEFAULT '',
        resources TEXT DEFAULT '[]',
        ts TEXT DEFAULT (now()::text)
    )""",
    """CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        username TEXT UNIQUE,
        handle TEXT UNIQUE,
        pw_hash TEXT,
        avatar TEXT DEFAULT '',
        created_at TEXT DEFAULT (now()::text)
    )""",
    """CREATE TABLE IF NOT EXISTS sessions (
        token TEXT PRIMARY KEY,
        user_id INTEGER,
        created_at TEXT DEFAULT (now()::text)
    )""",
    """CREATE TABLE IF NOT EXISTS follows (
        user_id INTEGER,
        scenario_key TEXT,
        agent_key TEXT,
        created_at TEXT DEFAULT (now()::text),
        PRIMARY KEY (user_id, scenario_key, agent_key)
    )""",
    """CREATE TABLE IF NOT EXISTS votes (
        user_id INTEGER,
        post_id INTEGER,
        value INTEGER,
        PRIMARY KEY (user_id, post_id)
    )""",
    """CREATE TABLE IF NOT EXISTS players (
        user_id INTEGER,
        scenario_key TEXT,
        started_at DOUBLE PRECISION,
        PRIMARY KEY (user_id, scenario_key)
    )""",
    """CREATE TABLE IF NOT EXISTS signals (
        user_id INTEGER,
        scenario_key TEXT,
        agent_key TEXT,
        kind TEXT,
        count INTEGER DEFAULT 0,
        PRIMARY KEY (user_id, scenario_key, agent_key, kind)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_posts_scen_day ON posts(scenario_key, day)",
    "CREATE INDEX IF NOT EXISTS idx_posts_parent ON posts(parent_id)",
    "CREATE INDEX IF NOT EXISTS idx_events_scen_day ON events(scenario_key, day)",
    "CREATE INDEX IF NOT EXISTS idx_votes_post ON votes(post_id)",
    """CREATE TABLE IF NOT EXISTS research_cache (
        scenario_key TEXT,
        day INTEGER,
        section TEXT,
        data TEXT DEFAULT '',
        created_at TEXT DEFAULT (now()::text),
        PRIMARY KEY (scenario_key, day, section)
    )""",
    """CREATE TABLE IF NOT EXISTS post_resources (
        id SERIAL PRIMARY KEY,
        scenario_key TEXT,
        day INTEGER,
        post_id INTEGER,
        resource_type TEXT,
        url TEXT,
        title TEXT,
        source TEXT,
        description TEXT DEFAULT '',
        attribution TEXT DEFAULT '',
        metadata TEXT DEFAULT '{}',
        created_at TEXT DEFAULT (now()::text)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_res_scen_day ON post_resources(scenario_key, day)",
    "CREATE INDEX IF NOT EXISTS idx_res_post ON post_resources(post_id)",
    "CREATE INDEX IF NOT EXISTS idx_res_type ON post_resources(resource_type)",
    """CREATE TABLE IF NOT EXISTS resource_cache (
        scenario_key TEXT,
        day INTEGER,
        source TEXT,
        query TEXT,
        data TEXT DEFAULT '[]',
        created_at TEXT DEFAULT (now()::text),
        PRIMARY KEY (scenario_key, day, source, query)
    )""",
]


def init_db():
    with get_conn() as c:
        if USE_POSTGRES:
            for stmt in _PG_DDL:
                c.execute(stmt)
        else:
            c.executescript(
                """
                CREATE TABLE IF NOT EXISTS scenarios (
                    key TEXT PRIMARY KEY,
                    title TEXT, date_range TEXT, days INTEGER,
                    tagline TEXT, sim_badge TEXT, hook TEXT,
                    origin TEXT DEFAULT 'builtin',
                    source_text TEXT DEFAULT '',
                    owner_id INTEGER DEFAULT NULL,
                    created_at TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS population_cache (
                    scenario_key TEXT PRIMARY KEY,
                    data TEXT DEFAULT '[]',
                    created_at TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS agents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scenario_key TEXT,
                    agent_key TEXT,
                    name TEXT, handle TEXT, category TEXT, verified INTEGER,
                    avatar_type TEXT, avatar_text TEXT, avatar_url TEXT DEFAULT '',
                    bio TEXT, voice TEXT, interests TEXT,
                    emotion TEXT DEFAULT '{}',
                    relationships TEXT DEFAULT '{}',
                    news_style TEXT DEFAULT '',
                    background INTEGER DEFAULT 0,
                    outspoken INTEGER DEFAULT 1,
                    UNIQUE(scenario_key, agent_key)
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scenario_key TEXT,
                    day INTEGER, date TEXT, title TEXT,
                    involved TEXT, tags TEXT,
                    generated INTEGER DEFAULT 0,
                    media TEXT DEFAULT '',
                    location TEXT DEFAULT '',
                    lat REAL DEFAULT 0,
                    lon REAL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scenario_key TEXT,
                    day INTEGER, date TEXT,
                    agent_key TEXT, event_id INTEGER,
                    parent_id INTEGER DEFAULT NULL,
                    kind TEXT DEFAULT 'post',
                    text TEXT,
                    thought TEXT DEFAULT '',
                    likes INTEGER DEFAULT 0,
                    dislikes INTEGER DEFAULT 0,
                    clock TEXT DEFAULT '',
                    image_url TEXT DEFAULT '',
                    ts TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE,
                    handle TEXT UNIQUE,
                    pw_hash TEXT,
                    created_at TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY,
                    user_id INTEGER,
                    created_at TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS follows (
                    user_id INTEGER,
                    scenario_key TEXT,
                    agent_key TEXT,
                    created_at TEXT DEFAULT (datetime('now')),
                    PRIMARY KEY (user_id, scenario_key, agent_key)
                );
                CREATE TABLE IF NOT EXISTS votes (
                    user_id INTEGER,
                    post_id INTEGER,
                    value INTEGER,          -- +1 like, -1 dislike
                    PRIMARY KEY (user_id, post_id)
                );
                CREATE TABLE IF NOT EXISTS players (
                    user_id INTEGER,
                    scenario_key TEXT,
                    started_at REAL,
                    PRIMARY KEY (user_id, scenario_key)
                );
                CREATE TABLE IF NOT EXISTS signals (
                    user_id INTEGER,
                    scenario_key TEXT,
                    agent_key TEXT,
                    kind TEXT,              -- 'profile' | 'read' | 'media'
                    count INTEGER DEFAULT 0,
                    PRIMARY KEY (user_id, scenario_key, agent_key, kind)
                );
                CREATE INDEX IF NOT EXISTS idx_posts_scen_day ON posts(scenario_key, day);
                CREATE INDEX IF NOT EXISTS idx_posts_parent ON posts(parent_id);
                CREATE INDEX IF NOT EXISTS idx_events_scen_day ON events(scenario_key, day);
                CREATE INDEX IF NOT EXISTS idx_votes_post ON votes(post_id);
                CREATE TABLE IF NOT EXISTS research_cache (
                    scenario_key TEXT,
                    day INTEGER,
                    section TEXT,
                    data TEXT DEFAULT '',
                    created_at TEXT DEFAULT (datetime('now')),
                    PRIMARY KEY (scenario_key, day, section)
                );
                CREATE TABLE IF NOT EXISTS post_resources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scenario_key TEXT,
                    day INTEGER,
                    post_id INTEGER,
                    resource_type TEXT,
                    url TEXT,
                    title TEXT,
                    source TEXT,
                    description TEXT DEFAULT '',
                    attribution TEXT DEFAULT '',
                    metadata TEXT DEFAULT '{}',
                    created_at TEXT DEFAULT (datetime('now'))
                );
                CREATE INDEX IF NOT EXISTS idx_res_scen_day ON post_resources(scenario_key, day);
                CREATE INDEX IF NOT EXISTS idx_res_post ON post_resources(post_id);
                CREATE INDEX IF NOT EXISTS idx_res_type ON post_resources(resource_type);
                CREATE TABLE IF NOT EXISTS resource_cache (
                    scenario_key TEXT,
                    day INTEGER,
                    source TEXT,
                    query TEXT,
                    data TEXT DEFAULT '[]',
                    created_at TEXT DEFAULT (datetime('now')),
                    PRIMARY KEY (scenario_key, day, source, query)
                );
                """
            )
        # migrations for older DBs (same DDL works on both backends)
        _ensure_cols(
            c,
            "scenarios",
            {"owner_id": "INTEGER DEFAULT NULL", "source_text": "TEXT DEFAULT ''"},
        )
        _ensure_cols(
            c,
            "agents",
            {
                "emotion": "TEXT DEFAULT '{}'",
                "relationships": "TEXT DEFAULT '{}'",
                "news_style": "TEXT DEFAULT ''",
                "background": "INTEGER DEFAULT 0",
                "outspoken": "INTEGER DEFAULT 1",
            },
        )
        _ensure_cols(
            c,
            "posts",
            {"thought": "TEXT DEFAULT ''", "likes": "INTEGER DEFAULT 0", "dislikes": "INTEGER DEFAULT 0", "clock": "TEXT DEFAULT ''", "image_url": "TEXT DEFAULT ''", "video_url": "TEXT DEFAULT ''", "footage_label": "TEXT DEFAULT ''", "resources": "TEXT DEFAULT '[]'"},
        )
        _ensure_cols(
            c,
            "events",
            {"media": "TEXT DEFAULT ''", "media_title": "TEXT DEFAULT ''", "location": "TEXT DEFAULT ''", "lat": "REAL DEFAULT 0", "lon": "REAL DEFAULT 0"},
        )
        _ensure_cols(c, "users", {"avatar": "TEXT DEFAULT ''"})
        _ensure_cols(c, "agents", {"avatar_url": "TEXT DEFAULT ''"})
        _dedupe_events(c)
        c.execute("UPDATE posts SET thought='' WHERE thought<>''")
        c.execute(
            "UPDATE events SET generated=1 WHERE EXISTS ("
            "SELECT 1 FROM posts WHERE posts.scenario_key=events.scenario_key "
            "AND posts.event_id=events.id)"
        )
        # A process that died while generating leaves no committed posts under
        # the transactional generator, so its claim can be retried on startup.
        c.execute("UPDATE events SET generated=0 WHERE generated=2")
        c.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_events_identity "
            "ON events(scenario_key, day, date, title)"
        )


@contextmanager
def cursor():
    with get_conn() as c:
        cur = c.cursor()
        yield cur


def row_to_dict(row):
    return dict(row) if row else None


def json_dumps(v):
    return json.dumps(v, ensure_ascii=False)


def json_loads(v, default=None):
    if not v:
        return default if default is not None else []
    try:
        return json.loads(v)
    except Exception:
        return default if default is not None else []
