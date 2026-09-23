"""Unit tests for the Postgres adapter in ark/db.py.

These need no live database: they cover SQL translation, RETURNING
detection, and the dual-access Row type. The full suite keeps running
against SQLite; production Neon Postgres goes through this translation.
"""
import unittest

from ark import db


class PgAdapterTests(unittest.TestCase):
    def test_placeholders_translate(self):
        self.assertEqual(
            db.translate_sql("SELECT * FROM posts WHERE scenario_key=? AND day<=?"),
            "SELECT * FROM posts WHERE scenario_key=%s AND day<=%s",
        )
        self.assertEqual(
            db.translate_sql("INSERT INTO votes (user_id, post_id, value) VALUES (?,?,?)"),
            "INSERT INTO votes (user_id, post_id, value) VALUES (%s,%s,%s)",
        )

    def test_like_becomes_ilike(self):
        self.assertEqual(
            db.translate_sql("SELECT * FROM posts WHERE text LIKE ?"),
            "SELECT * FROM posts WHERE text ILIKE %s",
        )
        self.assertEqual(
            db.translate_sql("SELECT * FROM events WHERE e.tags LIKE ? OR x LIKE ?"),
            "SELECT * FROM events WHERE e.tags ILIKE %s OR x ILIKE %s",
        )

    def test_lowercase_like_in_prose_is_untouched(self):
        # Only the uppercase SQL keyword is rewritten.
        sql = "SELECT '-- +1 like, -1 dislike' AS note WHERE a=? "
        self.assertEqual(
            db.translate_sql(sql + "AND b LIKE ?"),
            sql.replace("?", "%s") + "AND b ILIKE %s",
        )

    def test_wants_returning_for_id_tables(self):
        for table in ("posts", "events", "agents", "users", "post_resources"):
            self.assertTrue(
                db._wants_returning(f"INSERT INTO {table} (a) VALUES (?)"),
                table,
            )
        for table in ("votes", "sessions", "research_cache", "scenarios", "players"):
            self.assertFalse(
                db._wants_returning(f"INSERT INTO {table} (a) VALUES (?)"),
                table,
            )
        self.assertFalse(
            db._wants_returning("UPDATE posts SET text=? WHERE id=?"),
        )
        self.assertFalse(
            db._wants_returning("INSERT INTO posts (a) VALUES (?) RETURNING id"),
        )

    def test_row_dual_access(self):
        r = db.Row(["id", "title"], [7, "Hello"])
        self.assertEqual(r["id"], 7)
        self.assertEqual(r[0], 7)
        self.assertEqual(r["title"], "Hello")
        self.assertEqual(r[1], "Hello")
        self.assertEqual(dict(r), {"id": 7, "title": "Hello"})
        self.assertEqual(list(r), ["id", "title"])

    def test_backend_follows_database_url(self):
        import os
        self.assertEqual(db.USE_POSTGRES, bool(os.environ.get("DATABASE_URL", "").strip()))


if __name__ == "__main__":
    unittest.main()
