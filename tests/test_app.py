import io
import os
import tempfile
import unittest
from pathlib import Path

try:
    from fastapi.testclient import TestClient
except Exception as error:  # pragma: no cover - environment compatibility
    TestClient = None
    TEST_CLIENT_ERROR = error

from ark import auth, core, db, llm
import main


@unittest.skipIf(TestClient is None, f"FastAPI TestClient unavailable: {globals().get('TEST_CLIENT_ERROR')}")
class ArkAppTests(unittest.TestCase):
    def setUp(self):
        os.environ["ARK_TESTING"] = "1"
        self.tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.old_db = db.DB_PATH
        db.DB_PATH = str(Path(self.tmp.name) / "test.db")
        db.init_db()
        core.seed_builtin("ww2")
        self.old_available = llm.llm_available
        llm.llm_available = lambda: False
        self.client = TestClient(main.app)

    def tearDown(self):
        self.client.close()
        llm.llm_available = self.old_available
        db.DB_PATH = self.old_db
        os.environ.pop("ARK_TESTING", None)
        self.tmp.cleanup()

    def register(self, username="audit_user"):
        response = self.client.post(
            "/api/auth/register",
            data={"username": username, "password": "correct-horse"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        return body["user"], {"Authorization": f"Bearer {body['token']}"}

    def test_seed_is_idempotent_and_preserves_generated_state(self):
        timeline = core.get_timeline("ww2")
        event_id = timeline[0]["id"]
        with db.get_conn() as connection:
            connection.execute("UPDATE events SET generated=1 WHERE id=?", (event_id,))
        core.seed_builtin("ww2")
        again = core.get_timeline("ww2")
        self.assertEqual(len(again), 27)
        self.assertEqual(again[0]["id"], event_id)
        self.assertEqual(again[0]["generated"], 1)

    def test_generation_is_idempotent_and_votes_toggle(self):
        user, headers = self.register()
        event = core.get_timeline("ww2")[0]
        self.assertGreater(core.generate_event("ww2", event["id"]), 0)
        self.assertEqual(core.generate_event("ww2", event["id"]), 0)
        posts = core.get_feed("ww2", 0, user["id"])
        self.assertGreater(len(posts), 0)
        post = posts[0]

        vote = self.client.post(
            f"/api/post/{post['id']}/vote", data={"value": 1}, headers=headers
        )
        self.assertEqual(vote.status_code, 200, vote.text)
        self.assertEqual(vote.json()["my_vote"], 1)
        toggle = self.client.post(
            f"/api/post/{post['id']}/vote", data={"value": 1}, headers=headers
        )
        self.assertEqual(toggle.json()["my_vote"], 0)

    def test_authz_follow_thread_research_and_create(self):
        user, headers = self.register("owner")
        self.assertEqual(self.client.post("/api/scenario/ww2/generate_all").status_code, 401)
        self.assertEqual(
            self.client.post("/api/scenario/ww2/generate_all", headers=headers).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                "/api/scenario/ww2/follow/not-real", headers=headers
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.get("/api/research?key=ww2&day=-1", headers=headers).status_code,
            400,
        )

        created = self.client.post(
            "/api/experience/create",
            data={"prompt": "Ada and Charles build an analytical engine in London."},
            headers=headers,
        )
        self.assertEqual(created.status_code, 200, created.text)
        key = created.json()["key"]
        scenario = core.get_scenario(key)
        self.assertEqual(scenario["owner_id"], user["id"])
        self.assertGreaterEqual(len(core.list_agents(key)), 2)

        event = core.get_timeline(key)[0]
        core.generate_event(key, event["id"])
        post = core.get_feed(key, 0, user["id"])[0]
        thread = self.client.get(f"/api/post/{post['id']}", headers=headers)
        self.assertEqual(thread.status_code, 200, thread.text)
        self.assertEqual(thread.json()["scenario"]["key"], key)
        self.assertIsNotNone(thread.json()["post"]["agent"])

        deleted = self.client.delete(f"/api/scenario/{key}", headers=headers)
        self.assertEqual(deleted.status_code, 200, deleted.text)
        self.assertIsNone(core.get_scenario(key))

    def test_avatar_rejects_extension_spoofing(self):
        _user, headers = self.register("avatar_owner")
        fake = self.client.post(
            "/api/me/avatar",
            headers=headers,
            files={"file": ("face.png", io.BytesIO(b"not an image"), "image/png")},
        )
        self.assertEqual(fake.status_code, 400)


if __name__ == "__main__":
    unittest.main()
