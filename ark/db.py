"""SQLite persistence for ARK."""
import os
import json
import sqlite3
from contextlib import contextmanager

DB_PATH = os.environ.get("ARK_DB_PATH") or os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "ark.db"
)


def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=20)
    conn.row_factory = sqlite3.Row
    journal_mode = "MEMORY" if os.environ.get("ARK_TESTING") == "1" else "WAL"
    conn.execute(f"PRAGMA journal_mode={journal_mode}")
    conn.execute("PRAGMA busy_timeout=20000")
    return conn


def _col_names(conn, table):
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


def init_db():
    with get_conn() as c:
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
                avatar_type TEXT, avatar_text TEXT,
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
                media TEXT DEFAULT ''
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
            """
        )
        # migrations for older DBs
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
            {"thought": "TEXT DEFAULT ''", "likes": "INTEGER DEFAULT 0", "dislikes": "INTEGER DEFAULT 0", "clock": "TEXT DEFAULT ''", "image_url": "TEXT DEFAULT ''", "video_url": "TEXT DEFAULT ''", "footage_label": "TEXT DEFAULT ''"},
        )
        _ensure_cols(
            c,
            "events",
            {"media": "TEXT DEFAULT ''", "media_title": "TEXT DEFAULT ''"},
        )
        _ensure_cols(c, "users", {"avatar": "TEXT DEFAULT ''"})
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
