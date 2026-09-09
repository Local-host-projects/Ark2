import os
import tempfile
import unittest
from pathlib import Path

from ark import auth, core, db
from tests import fake_llm


class ArkCoreTests(unittest.TestCase):
    def setUp(self):
        os.environ["ARK_TESTING"] = "1"
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.old_db = db.DB_PATH
        db.DB_PATH = str(Path(self.tmp.name) / "test.db")
        db.init_db()
        core.seed_builtin("ww2")
        fake_llm.install()

    def tearDown(self):
        fake_llm.uninstall()
        db.DB_PATH = self.old_db
        os.environ.pop("ARK_TESTING", None)
        self.tmp.cleanup()

    def user(self, name="owner"):
        return auth.create_user(name, "correct-horse")

    def test_seed_is_idempotent(self):
        event = core.get_timeline("ww2")[0]
        with db.get_conn() as connection:
            connection.execute("UPDATE events SET generated=1 WHERE id=?", (event["id"],))
        core.seed_builtin("ww2")
        again = core.get_timeline("ww2")
        self.assertGreaterEqual(len(again), 27)
        self.assertEqual(again[0]["id"], event["id"])
        self.assertEqual(again[0]["generated"], 1)

    def test_generation_is_idempotent_and_has_no_private_thoughts(self):
        event = core.get_timeline("ww2")[0]
        self.assertGreater(core.generate_event("ww2", event["id"]), 0)
        self.assertEqual(core.generate_event("ww2", event["id"]), 0)
        posts = core.get_feed("ww2", 0)
        self.assertGreater(len(posts), 0)
        self.assertTrue(all(post["thought"] == "" for post in posts))

    def test_votes_toggle_and_persist_totals(self):
        user = self.user()
        event = core.get_timeline("ww2")[0]
        core.generate_event("ww2", event["id"])
        post = core.get_feed("ww2", 0, user["id"])[0]
        likes, dislikes, vote = core.vote(user["id"], post["id"], 1)
        self.assertEqual(vote, 1)
        refreshed = next(p for p in core.get_feed("ww2", 0, user["id"]) if p["id"] == post["id"])
        self.assertEqual(refreshed["likes"], likes)
        self.assertEqual(refreshed["dislikes"], dislikes)
        _likes, _dislikes, vote = core.vote(user["id"], post["id"], 1)
        self.assertEqual(vote, 0)

    def test_custom_scenario_has_owner_and_valid_schema(self):
        user = self.user()
        key = core.create_custom_scenario(
            "Analytical Engine",
            "Ada Lovelace and Charles Babbage build an analytical engine in London.",
            [],
            owner_id=user["id"],
        )
        scenario = core.get_scenario(key)
        self.assertEqual(scenario["owner_id"], user["id"])
        agents = core.list_agents(key)
        events = core.get_timeline(key)
        self.assertGreaterEqual(len(agents), 2)
        self.assertEqual({e["day"] for e in events}, set(range(scenario["days"])))
        core.delete_scenario(key, owner_id=user["id"])
        self.assertIsNone(core.get_scenario(key))

    def test_street_population_voices_and_backfill(self):
        # The world ships with a crowd, not just a cast.
        pool = core._population_pool("ww2")
        self.assertGreaterEqual(len(pool), 40)

        event = core.get_timeline("ww2")[0]
        core.generate_event("ww2", event["id"])
        with db.cursor() as cur:
            rows = cur.execute(
                "SELECT a.agent_key FROM posts p "
                "JOIN agents a ON a.scenario_key=p.scenario_key AND a.agent_key=p.agent_key "
                "WHERE p.event_id=? AND a.background=1", (event["id"],)
            ).fetchall()
        self.assertGreaterEqual(len(rows), 2)

        # Backfill finds a generated event missing its street and fills it.
        # Simulate a world generated before the street existed.
        with db.get_conn() as c:
            c.execute(
                "DELETE FROM posts WHERE event_id=? AND agent_key IN ("
                "SELECT agent_key FROM agents WHERE scenario_key='ww2' AND background=1)",
                (event["id"],),
            )
        bf = core.next_street_backfill()
        self.assertIsNotNone(bf)
        key, event_id = bf
        added = core.backfill_street(key, event_id)
        self.assertGreater(added, 0)

    def test_media_event_gets_street_reactions(self):
        media_event = next(e for e in core.get_timeline("ww2") if e["media"])
        self.assertGreater(core.generate_event("ww2", media_event["id"]), 0)
        with db.cursor() as cur:
            rows = cur.execute(
                "SELECT p.kind FROM posts p "
                "JOIN agents a ON a.scenario_key=p.scenario_key AND a.agent_key=p.agent_key "
                "WHERE p.event_id=? AND a.background=1", (media_event["id"],)
            ).fetchall()
        self.assertGreater(len(rows), 0)

    def test_validation_and_integrity_errors(self):
        user = self.user()
        with self.assertRaises(KeyError):
            core.follow(user["id"], "ww2", "not-real")
        with self.assertRaises(KeyError):
            core.vote(user["id"], 999999, 1)
        with self.assertRaises(ValueError):
            core.research_topic("ww2", -1)

    def test_media_event_gets_archival_footage(self):
        # Speech/broadcast events get real, embeddable public-domain footage.
        speeches = [e for e in core.get_timeline("ww2") if e["media"]]
        self.assertTrue(speeches)
        for ev in speeches[:2]:
            self.assertGreater(core.generate_event("ww2", ev["id"]), 0)
            post = next(
                p for p in core.get_feed("ww2", up_to_day=ev["day"])
                if p["event_id"] == ev["id"] and p["kind"] == ev["media"]
            )
            self.assertTrue(post["video_url"].startswith("https://"), ev["title"])
            self.assertTrue(post["footage_label"])

    def test_footage_backfill_fills_preexisting_media_posts(self):
        # A media post generated before the footage map had no video_url;
        # the backfill worker attaches the real reel later.
        ev = next(e for e in core.get_timeline("ww2") if e["media"])
        core.generate_event("ww2", ev["id"])
        with db.get_conn() as c:
            c.execute(
                "UPDATE posts SET video_url='', footage_label='' "
                "WHERE scenario_key='ww2' AND event_id=? AND kind=?",
                (ev["id"], ev["media"]),
            )
        nxt = core.next_footage_backfill()
        self.assertEqual(nxt, ("ww2", ev["id"]))
        added = core.backfill_footage("ww2", ev["id"])
        self.assertGreater(added, 0)
        self.assertIsNone(core.next_footage_backfill())
        with db.cursor() as cur:
            post = cur.execute(
                "SELECT video_url, footage_label FROM posts "
                "WHERE scenario_key='ww2' AND event_id=? AND kind=?",
                (ev["id"], ev["media"]),
            ).fetchone()
        self.assertTrue(post["video_url"].startswith("https://"))
        self.assertTrue(post["footage_label"])

    def test_front_page_lead_and_stories(self):
        core.generate_day("ww2", 0)
        page = core.front_page("ww2", up_to_day=0)
        self.assertIsNotNone(page["masthead"])
        self.assertIsNotNone(page["lead"])
        self.assertTrue(page["lead"]["headline"])
        self.assertTrue(page["lead"]["lede"])
        self.assertTrue(page["lead"]["byline"])
        self.assertIn("post_id", page["lead"])
        for story in page["stories"]:
            self.assertTrue(story["headline"])
            self.assertTrue(story["byline"])

    def test_trending_ranks_engagement(self):
        user = self.user()
        for day in (0, 1):
            core.generate_day("ww2", day)
        trend = core.trending("ww2", up_to_day=1, user_id=user["id"])
        self.assertTrue(trend)
        scores = [t["score"] for t in trend]
        self.assertEqual(scores, sorted(scores, reverse=True))
        for t in trend:
            self.assertIn("title", t)
            self.assertGreaterEqual(t["post_count"], 1)

    def test_search_finds_posts_agents_and_events(self):
        core.generate_day("ww2", 0)
        res = core.search("ww2", "war", up_to_day=0)
        self.assertIn("posts", res)
        self.assertIn("agents", res)
        self.assertIn("events", res)
        res = core.search("ww2", "poland", up_to_day=0)
        self.assertTrue(res["events"], "expected a matching event")
        res = core.search("ww2", "churchill", up_to_day=0)
        self.assertTrue(res["agents"], "expected a matching agent")

    def test_street_panel_reports_population_and_voices(self):
        core.generate_day("ww2", 0)
        panel = core.recent_street("ww2", up_to_day=0)
        self.assertGreaterEqual(panel["population"], 40)
        for voice in panel["voices"]:
            self.assertTrue(voice["agent"])

    def test_generation_requires_llm(self):
        from ark import llm as _llm
        old = _llm.llm_available
        _llm.llm_available = lambda: False
        try:
            event = core.get_timeline("ww2")[0]
            with self.assertRaises(core.LLMRequiredError):
                core.generate_event("ww2", event["id"])
            with self.assertRaises(core.LLMRequiredError):
                core.create_custom_scenario("x", "some source", [], owner_id=None)
            with self.assertRaises(core.LLMRequiredError):
                core.research_topic("ww2", 0)
            # The failed claim leaves the event ungenerated for retry.
            again = core.get_timeline("ww2")[0]
            self.assertEqual(again["generated"], 0)
        finally:
            _llm.llm_available = old

    def test_research_harness_returns_six_cached_sections(self):
        sections = core.research_harness("ww2", 0)
        self.assertEqual(
            set(sections),
            {"culture", "characters", "other_events", "humor", "main_events", "regional"},
        )
        for text in sections.values():
            self.assertTrue(text)
        again = core.research_harness("ww2", 0)
        self.assertEqual(sections, again)

    def test_research_brief_feeds_generation_prompts(self):
        brief = core._research_brief_for_prompt("ww2", 0)
        self.assertTrue(brief)
        self.assertIn("mock briefing", brief)

    def test_harness_model_pref_keys(self):
        self.assertEqual(core._harness_model({"preferred_model": "some-exact-model"}), "some-exact-model")
        self.assertEqual(core._harness_model({"model_pref": "other-model"}), "other-model")
        self.assertIsNone(core._harness_model({}))
        self.assertIsNone(core._harness_model(None))

    def test_normalize_location(self):
        self.assertEqual(
            core._normalize_location({"place": "Berlin", "lat": 52.5, "lon": 13.4}),
            ("Berlin", 52.5, 13.4),
        )
        place, lat, lon = core._normalize_location({"place": "X", "lat": 999, "lon": -999})
        self.assertEqual((lat, lon), (90.0, -180.0))
        self.assertEqual(core._normalize_location("Paris"), ("Paris", 0.0, 0.0))
        self.assertEqual(core._normalize_location(None), ("", 0.0, 0.0))

    def test_custom_cities_derive_from_event_locations(self):
        user = self.user()
        key = core.create_custom_scenario(
            "Test World", "Engines stir in Testville.", [], owner_id=user["id"]
        )
        try:
            cities = core.get_scenario_cities(key)
            by_name = {c["name"]: c for c in cities}
            self.assertEqual(set(by_name), {"Testville", "Old Town"})
            self.assertAlmostEqual(by_name["Testville"]["lat"], 10.0)
            self.assertAlmostEqual(by_name["Testville"]["lon"], 20.0)
            core.generate_day(key, 0)
            feed = core.get_city_feed(key, by_name["Testville"]["key"])
            self.assertTrue(feed, "expected posts pinned to Testville")
            self.assertTrue(all(p["agent"] for p in feed))
            self.assertTrue(
                any(p["resources"] for p in feed),
                "expected harvested resources attached to posts",
            )
        finally:
            core.delete_scenario(key, owner_id=user["id"])

    def test_agent_avatar_prefers_stored_photo_then_dicebear(self):
        user = self.user()
        key = core.create_custom_scenario(
            "Test World", "Engines stir in Testville.", [], owner_id=user["id"]
        )
        try:
            # Unverified street-level figures keep initials avatars.
            url = core.ensure_agent_avatar(key, "wire")
            self.assertIn("dicebear.com", url)
            # A stored photo wins over the fallback.
            with db.get_conn() as c:
                c.execute(
                    "UPDATE agents SET avatar_url=? WHERE scenario_key=? AND agent_key=?",
                    ("https://example.com/ada.jpg", key, "ada"),
                )
            self.assertEqual(core.ensure_agent_avatar(key, "ada"), "https://example.com/ada.jpg")
            # Verified figures get a lazily fetched portrait (mocked here).
            old_fetch = core._fetch_wiki_image
            core._fetch_wiki_image = lambda name, timeout=4: "https://example.com/wiki.jpg"
            try:
                with db.get_conn() as c:
                    c.execute(
                        "UPDATE agents SET verified=1, avatar_url='' WHERE scenario_key=? AND agent_key=?",
                        (key, "wire"),
                    )
                self.assertEqual(core.ensure_agent_avatar(key, "wire"), "https://example.com/wiki.jpg")
            finally:
                core._fetch_wiki_image = old_fetch
        finally:
            core.delete_scenario(key, owner_id=user["id"])


if __name__ == "__main__":
    unittest.main()
