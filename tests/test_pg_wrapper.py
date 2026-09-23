"""Tests for the Postgres cursor/connection wrappers (no live DB).

A fake psycopg cursor stands in for the server so we can verify RETURNING
handling, lastrowid, row conversion, LIKE translation, and commit/rollback
+ pool-return semantics.
"""
import unittest
from collections import namedtuple

from ark import db

Col = namedtuple("Col", ["name"])


class FakeCursor:
    def __init__(self):
        self.statements = []
        self._fetchone_result = None
        self._fetchall_results = []
        self.description = None
        self.rowcount = 0
        self.closed = False

    def execute(self, sql, params=()):
        self.statements.append((sql, params))
        return self

    def fetchone(self):
        return self._fetchone_result

    def fetchall(self):
        return self._fetchall_results

    def close(self):
        self.closed = True


class FakeConn:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    def cursor(self):
        return FakeCursor()

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class FakePool:
    def __init__(self):
        self.returned = []

    def putconn(self, conn):
        self.returned.append(conn)


class PgWrapperTests(unittest.TestCase):
    def test_insert_appends_returning_and_sets_lastrowid(self):
        inner = FakeCursor()
        inner._fetchone_result = (42,)
        inner.description = [Col("id")]
        cur = db._PGCursor(inner)
        out = cur.execute(
            "INSERT INTO posts (scenario_key,day) VALUES (?,?)", ("ww2", 0)
        )
        self.assertIs(out, cur)
        sql, params = inner.statements[0]
        self.assertTrue(sql.endswith(" RETURNING id"), sql)
        self.assertIn("%s", sql)
        self.assertNotIn("?", sql)
        self.assertEqual(cur.lastrowid, 42)

    def test_non_id_insert_has_no_returning(self):
        inner = FakeCursor()
        cur = db._PGCursor(inner)
        cur.execute("INSERT INTO votes (user_id, post_id, value) VALUES (?,?,?)", (1, 2, 1))
        sql, _ = inner.statements[0]
        self.assertNotIn("RETURNING", sql)
        self.assertIsNone(cur.lastrowid)

    def test_select_translates_like_and_params(self):
        inner = FakeCursor()
        inner._fetchall_results = []
        inner.description = []
        cur = db._PGCursor(inner)
        cur.execute("SELECT * FROM posts WHERE text LIKE ? AND day<=?", ("%x%", 3))
        sql, params = inner.statements[0]
        self.assertEqual(sql, "SELECT * FROM posts WHERE text ILIKE %s AND day<=%s")
        self.assertEqual(params, ("%x%", 3))

    def test_fetchall_returns_dual_access_rows(self):
        inner = FakeCursor()
        inner._fetchall_results = [(1, "hi")]
        inner.description = [Col("id"), Col("text")]
        cur = db._PGCursor(inner)
        rows = cur.fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], 1)
        self.assertEqual(rows[0][0], 1)
        self.assertEqual(dict(rows[0]), {"id": 1, "text": "hi"})

    def test_fetchone_none_stays_none(self):
        inner = FakeCursor()
        inner._fetchone_result = None
        cur = db._PGCursor(inner)
        self.assertIsNone(cur.fetchone())

    def test_conn_exit_commits_and_returns_to_pool(self):
        pool, raw = FakePool(), FakeConn()
        conn = db._PGConn(raw, pool)
        with conn as c:
            c.execute("UPDATE events SET generated=? WHERE id=?", (1, 2))
        self.assertEqual(raw.commits, 1)
        self.assertEqual(raw.rollbacks, 0)
        self.assertEqual(pool.returned, [raw])

    def test_conn_exit_rolls_back_on_error(self):
        pool, raw = FakePool(), FakeConn()
        conn = db._PGConn(raw, pool)
        with self.assertRaises(RuntimeError):
            with conn as c:
                c.execute("UPDATE events SET generated=? WHERE id=?", (1, 2))
                raise RuntimeError("boom")
        self.assertEqual(raw.commits, 0)
        self.assertEqual(raw.rollbacks, 1)
        self.assertEqual(pool.returned, [raw])

    def test_conn_execute_returns_cursor_with_lastrowid(self):
        pool, raw = FakePool(), FakeConn()
        conn = db._PGConn(raw, pool)
        # Patch cursor() to return a canned inner cursor.
        inner = FakeCursor()
        inner._fetchone_result = (9,)
        inner.description = [Col("id")]
        raw.cursor = lambda: inner
        cur = conn.execute("INSERT INTO users (username) VALUES (?)", ("amy",))
        self.assertEqual(cur.lastrowid, 9)


if __name__ == "__main__":
    unittest.main()
