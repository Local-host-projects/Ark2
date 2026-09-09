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
from tests import fake_llm
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
        fake_llm.install()
        self.client = TestClient(main.app)

    def tearDown(self):
        self.client.close()
        fake_llm.uninstall()
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
        from ark.scenarios import ww2 as _ww2mod
        timeline = core.get_timeline("ww2")
        event_id = timeline[0]["id"]
        with db.get_conn() as connection:
            connection.execute("UPDATE events SET generated=1 WHERE id=?", (event_id,))
        core.seed_builtin("ww2")
        again = core.get_timeline("ww2")
        self.assertEqual(len(again), len(_ww2mod.EVENTS))
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

    def test_create_accepts_pdf_and_enforces_5mb_limit(self):
        _user, headers = self.register("pdf_owner")
        pdf = _mini_pdf("Engines stir in Testville for the test world.")
        created = self.client.post(
            "/api/experience/create",
            data={"prompt": "A world from a PDF."},
            files={"files": ("source.pdf", io.BytesIO(pdf), "application/pdf")},
            headers=headers,
        )
        self.assertEqual(created.status_code, 200, created.text)
        self.assertTrue(created.json()["key"].startswith("custom_"))

        big = self.client.post(
            "/api/experience/create",
            data={"prompt": "Too big."},
            files={"files": ("big.txt", io.BytesIO(b"x" * 5_000_001), "text/plain")},
            headers=headers,
        )
        self.assertEqual(big.status_code, 413, big.text)

    def test_create_reports_missing_llm_as_503(self):
        _user, headers = self.register("nollm_owner")
        old = llm.llm_available
        llm.llm_available = lambda: False
        try:
            res = self.client.post(
                "/api/experience/create",
                data={"prompt": "A world with no provider."},
                headers=headers,
            )
            self.assertEqual(res.status_code, 503, res.text)
            self.assertIn("LLM", res.json()["detail"])
        finally:
            llm.llm_available = old


def _mini_pdf(text):
    """Build a minimal valid single-page PDF holding one text line."""
    safe = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 24 Tf 100 700 Td ({safe}) Tj ET".encode("latin-1")
    objs = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R"
        b"/Resources<</Font<</F1 5 0 R>>>>>>",
        b"<</Length " + str(len(stream)).encode() + b">>stream\n" + stream + b"\nendstream",
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += str(i).encode() + b" 0 obj\n" + body + b"\nendobj\n"
    xref = len(out)
    out += ("xref\n0 %d\n" % (len(objs) + 1)).encode()
    out += b"0000000000 65535 f \n"
    for o in offsets:
        out += ("%010d 00000 n \n" % o).encode()
    out += ("trailer\n<</Size %d/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)).encode()
    return bytes(out)


if __name__ == "__main__":
    unittest.main()
