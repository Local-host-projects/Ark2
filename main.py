import os
import json
import logging
import secrets
import threading
import time as _time
from pathlib import Path
from datetime import datetime, timezone

# Load .env before any ark module reads env vars at import time.
def _load_dotenv(path: Path) -> None:
    try:
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v
    except FileNotFoundError:
        pass

_load_dotenv(Path(__file__).resolve().parent / ".env")

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse

from ark import db, core, llm, auth

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("ark")

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"

db.init_db()

app = FastAPI(title="ARK")
allowed_origins = [
    origin.strip()
    for origin in os.environ.get(
        "ARK_ALLOWED_ORIGINS", "http://127.0.0.1:8000,http://localhost:8000"
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _user(authorization: str | None) -> dict | None:
    token = auth.bearer_token(authorization)
    return auth.user_for_token(token)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _allowed_days(key: str, u: dict | None, days: int) -> int:
    """How many feed-days the clock has opened for this user (1 for visitors)."""
    if u:
        started = core.start_playing(u["id"], key)
        return core.unlocked_day(key, started, days)
    return 1


@app.on_event("startup")
def _startup():
    try:
        core.seed_builtin("ww2")
        log.info("seeded: %s", [s["key"] for s in core.list_scenarios()])
    except Exception as e:  # noqa
        log.exception("seed failed: %s", e)
    _start_generation_worker()


_GEN_WORKER = None


def _start_generation_worker():
    """Build custom worlds in the background so timelines fill up over time.

    One event is generated per tick. Progress lives in the database, so the
    build continues even when the browser tab is closed.
    """
    global _GEN_WORKER
    if _GEN_WORKER is not None or os.environ.get("ARK_TESTING") == "1":
        return
    interval = max(1.0, float(os.environ.get("ARK_GEN_INTERVAL", "4")))
    stop = threading.Event()

    def loop():
        while not stop.is_set():
            try:
                pending = core.next_pending_event()
                if pending:
                    key, event_id = pending
                    core.generate_event(key, event_id)
                else:
                    bf = core.next_street_backfill()
                    if bf:
                        key, event_id = bf
                        core.backfill_street(key, event_id)
                    else:
                        ff = core.next_footage_backfill()
                        if ff:
                            key, event_id = ff
                            core.backfill_footage(key, event_id)
            except Exception as e:  # noqa
                log.warning("background generation: %s", e)
            stop.wait(interval)

    _GEN_WORKER = threading.Thread(target=loop, name="ark-generator", daemon=True)
    _GEN_WORKER.start()
    log.info("background generation worker started (interval %.1fs)", interval)


@app.on_event("shutdown")
def _shutdown():
    global _GEN_WORKER
    if _GEN_WORKER is not None:
        _GEN_WORKER = None  # daemon thread; process is exiting anyway


# ---------------------------------------------------------------- health


@app.get("/api/health")
def health():
    return {"ok": True, "llm": llm.llm_status()}


# ---------------------------------------------------------------- auth


@app.post("/api/auth/register")
def register(username: str = Form(...), password: str = Form(...)):
    username = username.strip()
    if not 2 <= len(username) <= 50:
        raise HTTPException(400, "Name must be between 2 and 50 characters.")
    if len(password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters.")
    try:
        user = auth.create_user(username, password)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    token = auth.issue_token(user["id"])
    return {"token": token, "user": user}


@app.post("/api/auth/login")
def login(username: str = Form(...), password: str = Form(...)):
    user = auth.authenticate(username.strip(), password)
    if not user:
        raise HTTPException(401, "Wrong name or password.")
    token = auth.issue_token(user["id"])
    return {"token": token, "user": user}


@app.get("/api/auth/me")
def me(authorization: str | None = Header(None)):
    u = _user(authorization)
    if not u:
        raise HTTPException(401, "Not signed in.")
    return {"user": u}


@app.post("/api/auth/logout")
def logout(authorization: str | None = Header(None)):
    token = auth.bearer_token(authorization)
    if token:
        auth.revoke_token(token)
    return {"ok": True}


# ---------------------------------------------------------------- scenarios


@app.get("/api/scenarios")
def scenarios(authorization: str | None = Header(None)):
    scs = core.list_scenarios()
    u = _user(authorization)
    for s in scs:
        s["can_delete"] = s.get("is_custom") and bool(u) and (
            s.get("owner_id") is None or s["owner_id"] == u["id"]
        )
        if u:
            s["following_count"] = _follow_count(u["id"], s["key"])
    return scs


def _follow_count(user_id, scenario_key):
    with db.cursor() as cur:
        row = cur.execute(
            "SELECT COUNT(*) AS n FROM follows WHERE user_id=? AND scenario_key=?",
            (user_id, scenario_key),
        ).fetchone()
    return row["n"] if row else 0


@app.get("/api/scenario/{key}")
def scenario_detail(key: str, authorization: str | None = Header(None)):
    sc = core.get_scenario(key)
    if not sc:
        raise HTTPException(404, "scenario not found")
    u = _user(authorization)
    sc["agents"] = core.list_agents(key, user_id=(u["id"] if u else None))
    sc["timeline"] = core.get_timeline(key)
    sc["generated_days"] = core._generated_days(key)
    sc["is_custom"] = sc.get("origin") != "builtin"
    sc["can_delete"] = sc["is_custom"] and bool(u) and (
        sc.get("owner_id") is None or sc["owner_id"] == u["id"]
    )
    sc["pacing_minutes"] = core.pacing_minutes(key)
    if u:
        sc["following_count"] = _follow_count(u["id"], key)
    return sc


@app.get("/api/scenario/{key}/timeline")
def timeline(key: str):
    return core.get_timeline(key)


@app.post("/api/scenario/{key}/enter")
def enter_scenario(key: str, authorization: str | None = Header(None)):
    """A player starts the clock for a scenario. Returns pacing info."""
    u = _user(authorization)
    if not u:
        raise HTTPException(401, "Sign in to enter a simulation.")
    sc = core.get_scenario(key)
    if not sc:
        raise HTTPException(404, "scenario not found")
    started = core.start_playing(u["id"], key)
    open_days = core.unlocked_day(key, started, sc["days"])
    next_in = core.next_unlock_seconds(key, started)
    return {
        "key": key,
        "started_at": started,
        "open_days": open_days,
        "days": sc["days"],
        "pacing_minutes": core.pacing_minutes(key),
        "next_unlock_seconds": next_in,
    }


@app.get("/api/scenario/{key}/feed")
def feed(
    key: str,
    authorization: str | None = Header(None),
    up_to: int | None = None,
    auto: int = 1,
    mode: str = "chrono",
):
    u = _user(authorization)
    sc = core.get_scenario(key)
    if not sc:
        raise HTTPException(404, "scenario not found")
    # Pacing gate: only reveal what the real clock has unlocked for this player.
    if u:
        started = core.start_playing(u["id"], key)
        allowed = core.unlocked_day(key, started, sc["days"])
    else:
        allowed = 1  # signed-out visitors only ever see the opening day
        started = None

    if up_to is None:
        up_to = min(allowed - 1, max(core._generated_days(key), 1) - 1)
    else:
        up_to = max(0, min(up_to, allowed - 1))

    if auto and u:
        core.generate_up_to(key, up_to)

    if mode not in ("chrono", "following", "for_you"):
        mode = "chrono"
    posts = core.get_feed(key, up_to, user_id=(u["id"] if u else None), mode=mode)
    return {
        "scenario": key,
        "up_to": up_to,
        "open_days": allowed,
        "days": sc["days"],
        "pacing_minutes": core.pacing_minutes(key),
        "next_unlock_seconds": core.next_unlock_seconds(key, started) if started else 0,
        "posts": posts,
        "generated_days": core._generated_days(key),
        "mode": mode,
        "followed_count": len(core.followed_agents(u["id"], key)) if u else 0,
    }


@app.get("/api/scenario/{key}/progress")
def scenario_progress(key: str):
    """How far a world has been built — used by the city-building screen."""
    prog = core.generation_progress(key)
    if prog is None:
        raise HTTPException(404, "scenario not found")
    return prog


def _open_window(key: str, u, up_to: int | None):
    """Shared pacing gate for the front page / trending / search / street."""
    sc = core.get_scenario(key)
    if not sc:
        raise HTTPException(404, "scenario not found")
    if u:
        started = core.start_playing(u["id"], key)
        allowed = core.unlocked_day(key, started, sc["days"])
    else:
        allowed = 1
    if up_to is None:
        up_to = min(allowed - 1, max(core._generated_days(key), 1) - 1)
    else:
        up_to = max(0, min(up_to, allowed - 1))
    return sc, up_to


@app.get("/api/scenario/{key}/frontpage")
def frontpage(
    key: str,
    authorization: str | None = Header(None),
    up_to: int | None = None,
):
    u = _user(authorization)
    sc, up_to = _open_window(key, u, up_to)
    page = core.front_page(key, up_to, user_id=(u["id"] if u else None))
    page["up_to"] = up_to
    page["open_days"] = sc["days"] if not u else min(sc["days"], core.unlocked_day(key, core.start_playing(u["id"], key), sc["days"]))
    return page


@app.get("/api/scenario/{key}/trending")
def trending(
    key: str,
    authorization: str | None = Header(None),
    up_to: int | None = None,
    limit: int = 6,
):
    u = _user(authorization)
    sc, up_to = _open_window(key, u, up_to)
    return {
        "scenario": key,
        "up_to": up_to,
        "trending": core.trending(key, up_to, user_id=(u["id"] if u else None), limit=limit),
    }


@app.get("/api/scenario/{key}/search")
def scenario_search(
    key: str,
    q: str = "",
    authorization: str | None = Header(None),
    up_to: int | None = None,
):
    u = _user(authorization)
    sc, up_to = _open_window(key, u, up_to)
    return {
        "scenario": key,
        "query": q[:120],
        "up_to": up_to,
        "results": core.search(key, q, up_to, user_id=(u["id"] if u else None)),
    }


@app.get("/api/scenario/{key}/street")
def street(
    key: str,
    authorization: str | None = Header(None),
    up_to: int | None = None,
):
    u = _user(authorization)
    sc, up_to = _open_window(key, u, up_to)
    return {
        "scenario": key,
        "up_to": up_to,
        "street": core.recent_street(key, up_to),
    }


@app.post("/api/scenario/{key}/day/{day}/generate")
def generate_a_day(key: str, day: int, authorization: str | None = Header(None)):
    u = _user(authorization)
    if not u:
        raise HTTPException(401, "Sign in to generate a feed-day.")
    sc = core.get_scenario(key)
    if not sc:
        raise HTTPException(404, "scenario not found")
    if day < 0 or day >= sc["days"]:
        raise HTTPException(400, "feed-day is outside this scenario")
    started = core.start_playing(u["id"], key)
    if day >= core.unlocked_day(key, started, sc["days"]):
        raise HTTPException(403, "That feed-day is still sealed.")
    n = core.generate_day(key, day)
    return {"ok": True, "day": day, "events_generated": n}


@app.post("/api/scenario/{key}/generate_all")
def gen_all(key: str, authorization: str | None = Header(None)):
    u = _user(authorization)
    if not u:
        raise HTTPException(401, "Sign in to generate a simulation.")
    sc = core.get_scenario(key)
    if not sc:
        raise HTTPException(404, "scenario not found")
    if sc.get("origin") == "builtin" or sc.get("owner_id") != u["id"]:
        raise HTTPException(403, "Only a custom simulation's owner can generate it in full.")
    n = core.generate_all(key)
    return {"ok": True, "events_generated": n}


# ---------------------------------------------------------------- agents / posts


@app.get("/api/scenario/{key}/agents")
def agents(key: str, authorization: str | None = Header(None)):
    u = _user(authorization)
    if not core.get_scenario(key):
        raise HTTPException(404, "scenario not found")
    return core.list_agents(key, user_id=(u["id"] if u else None))


@app.get("/api/agent/{key}/{agent_key}")
def agent_profile(key: str, agent_key: str, authorization: str | None = Header(None)):
    u = _user(authorization)
    sc = core.get_scenario(key)
    if not sc:
        raise HTTPException(404, "scenario not found")
    allowed = _allowed_days(key, u, sc["days"])
    agent = None
    for a in core.list_agents(key):
        if a["agent_key"] == agent_key:
            agent = a
            break
    if not agent:
        raise HTTPException(404, "agent not found")
    posts = core.get_agent_posts(
        key, agent_key, user_id=(u["id"] if u else None), up_to_day=allowed - 1
    )
    replies = [p for p in posts if p["parent_id"]]
    originals = [p for p in posts if not p["parent_id"]]
    following = bool(u) and core.is_following(u["id"], key, agent_key)
    first_post = originals[0] if originals else (posts[0] if posts else None)
    talked_to = {}
    if u:
        talked_to = core.agent_conversation_partners(key, agent_key, allowed - 1)
    return {
        "agent": agent,
        "originals": len(originals),
        "replies": len(replies),
        "posts": posts,
        "following": following,
        "first_seen": (
            {
                "day": first_post["day"],
                "date": first_post.get("date", ""),
                "text": first_post.get("text", ""),
                "clock": first_post.get("clock", ""),
            }
            if first_post
            else None
        ),
        "talked_to": talked_to,
    }


@app.get("/api/post/{post_id}")
def post_thread(post_id: int, authorization: str | None = Header(None)):
    u = _user(authorization)
    t = core.get_post_thread(post_id, user_id=(u["id"] if u else None))
    if not t:
        raise HTTPException(404, "post not found")
    allowed = _allowed_days(t["scenario"]["key"], u, t["scenario"]["days"])
    if t["post"]["day"] >= allowed:
        raise HTTPException(404, "post not found")
    return t


@app.post("/api/post/{post_id}/vote")
def vote(post_id: int, value: int = Form(...), authorization: str | None = Header(None)):
    u = _user(authorization)
    if not u:
        raise HTTPException(401, "Sign in to react.")
    try:
        likes, dislikes, normalized = core.vote(u["id"], post_id, value)
    except KeyError as e:
        raise HTTPException(404, str(e)) from e
    return {"likes": likes, "dislikes": dislikes, "my_vote": normalized}


@app.post("/api/signal")
def signal(
    scenario_key: str = Form(...),
    agent_key: str = Form(...),
    kind: str = Form("read"),
    authorization: str | None = Header(None),
):
    """Record a soft attention signal: profile view, thread read, media open."""
    u = _user(authorization)
    if not u:
        raise HTTPException(401, "Sign in to record activity.")
    core.record_signal(u["id"], scenario_key, agent_key, kind)
    return {"ok": True}


# ---------------------------------------------------------------- follow


@app.post("/api/scenario/{key}/follow/{agent_key}")
def do_follow(key: str, agent_key: str, authorization: str | None = Header(None)):
    u = _user(authorization)
    if not u:
        raise HTTPException(401, "Sign in to follow.")
    try:
        core.follow(u["id"], key, agent_key)
    except KeyError as e:
        raise HTTPException(404, str(e)) from e
    return {"ok": True, "following": True}


@app.delete("/api/scenario/{key}/follow/{agent_key}")
def do_unfollow(key: str, agent_key: str, authorization: str | None = Header(None)):
    u = _user(authorization)
    if not u:
        raise HTTPException(401, "Sign in to unfollow.")
    core.unfollow(u["id"], key, agent_key)
    return {"ok": True, "following": False}


@app.get("/api/me/follows")
def my_follows(authorization: str | None = Header(None)):
    u = _user(authorization)
    if not u:
        raise HTTPException(401, "Sign in.")
    with db.cursor() as cur:
        rows = cur.execute(
            "SELECT scenario_key, agent_key FROM follows WHERE user_id=? ORDER BY created_at",
            (u["id"],),
        ).fetchall()
    return [{"scenario_key": r["scenario_key"], "agent_key": r["agent_key"]} for r in rows]


# ---------------------------------------------------------------- research


@app.get("/api/research")
def research(key: str, day: int = 0, q: str = "", authorization: str | None = Header(None)):
    u = _user(authorization)
    sc = core.get_scenario(key)
    if not sc:
        raise HTTPException(404, "scenario not found")
    # Pacing gate: the desk cannot research a day the clock has not opened.
    if u:
        started = core.start_playing(u["id"], key)
        allowed = core.unlocked_day(key, started, sc["days"])
    else:
        allowed = 1
    if day < 0 or day >= sc["days"]:
        raise HTTPException(400, "feed-day is outside this scenario")
    if day >= allowed:
        raise HTTPException(403, "That day is still sealed. The desk cannot research the future.")
    source_text = sc.get("source_text", "") if sc.get("origin") != "builtin" else ""
    return core.research_topic(key, int(day), (q or "")[:500], source_text)


# ---------------------------------------------------------------- create custom


@app.post("/api/experience/create")
async def create_experience(
    prompt: str = Form(""),
    files: list[UploadFile] | None = File(None),
    authorization: str | None = Header(None),
):
    u = _user(authorization)
    if not u:
        raise HTTPException(401, "Sign in to create a simulation.")
    source_text = (prompt or "")[:6000]
    source_files = []
    if files:
        if len(files) > 5:
            raise HTTPException(400, "Attach at most 5 text files.")
        total_bytes = 0
        allowed = {".txt", ".md", ".csv", ".json", ".html"}
        for f in files:
            filename = os.path.basename(f.filename or "file")
            if Path(filename).suffix.lower() not in allowed:
                raise HTTPException(400, f"Unsupported file: {filename}")
            raw = await f.read(1_000_001)
            if len(raw) > 1_000_000:
                raise HTTPException(413, f"{filename} is larger than 1 MB.")
            total_bytes += len(raw)
            if total_bytes > 3_000_000:
                raise HTTPException(413, "Attachments must total under 3 MB.")
            text = _decode(raw)
            source_files.append({"filename": filename, "text": text[:6000]})
    if not source_text.strip() and not source_files:
        raise HTTPException(400, "give us a prompt or a file to work from")
    try:
        key = core.create_custom_scenario(
            source_text or "A small story", source_text, source_files,
            owner_id=u["id"],
        )
        return {"ok": True, "key": key}
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.delete("/api/scenario/{key}")
def delete_experience(key: str, authorization: str | None = Header(None)):
    """Remove a custom simulation and all of its feed-days.

    Builtin archives cannot be deleted. Custom scenarios may be deleted by
    their creator, or by any signed-in user if no creator was recorded.
    """
    sc = core.get_scenario(key)
    if not sc:
        raise HTTPException(404, "SCENARIO NOT FOUND")
    if sc.get("origin") == "builtin":
        raise HTTPException(403, "builtin archives are part of the permanent collection; they cannot be deleted")
    u = _user(authorization)
    if not u:
        raise HTTPException(401, "sign in to delete simulations")
    owner = sc.get("owner_id")
    if owner is None or owner != u["id"]:
        raise HTTPException(403, "you can only delete simulations you created")
    try:
        core.delete_scenario(key, owner_id=u["id"])
    except KeyError as e:
        raise HTTPException(404, str(e)) from e
    return {"ok": True, "key": key}


def _decode(raw: bytes) -> str:
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode("utf-8", errors="replace")


# ---------------------------------------------------------------- profile photo


@app.post("/api/me/avatar")
async def upload_avatar(
    authorization: str | None = Header(None),
    file: UploadFile = File(...),
):
    u = _user(authorization)
    if not u:
        raise HTTPException(401, "Not signed in.")
    raw = await file.read(8 * 1024 * 1024 + 1)
    if len(raw) > 8 * 1024 * 1024:
        raise HTTPException(413, "Photo must be under 8 MB.")
    signatures = (
        (b"\x89PNG\r\n\x1a\n", "png"),
        (b"\xff\xd8\xff", "jpg"),
        (b"GIF87a", "gif"),
        (b"GIF89a", "gif"),
    )
    ext = next((kind for signature, kind in signatures if raw.startswith(signature)), None)
    if len(raw) >= 12 and raw.startswith(b"RIFF") and raw[8:12] == b"WEBP":
        ext = "webp"
    if not ext:
        raise HTTPException(400, "Use a PNG, JPG, WEBP or GIF image.")
    uploads = STATIC / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    for old in uploads.glob(f"user{u['id']}.*"):
        old.unlink(missing_ok=True)
    dest = uploads / f"user{u['id']}_{secrets.token_hex(6)}.{ext}"
    dest.write_bytes(raw)
    url = f"/uploads/{dest.name}"
    with db.get_conn() as c:
        c.execute("UPDATE users SET avatar=? WHERE id=?", (url, u["id"]))
    u["avatar"] = url
    return {"user": u}


# ---------------------------------------------------------------- static

from fastapi.responses import FileResponse


@app.get("/landing")
def landing():
    return FileResponse(str(STATIC / "landing.html"))

uploads_dir = STATIC / "uploads"
uploads_dir.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=str(uploads_dir)), name="uploads")
app.mount("/", StaticFiles(directory=str(STATIC), html=True), name="static")
