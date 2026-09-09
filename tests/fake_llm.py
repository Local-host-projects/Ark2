"""Deterministic fake LLM for tests.

ARK generates every word with a real model — there is no offline fallback.
Tests therefore stub the provider boundary (llm_available / complete /
complete_json) with fixed, era-neutral copy instead of hitting the network.
"""
import json

from ark import llm

_SAVED = {}


def _payload(user):
    try:
        data = llm._extract_json(user or "")
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _schema():
    agents = [
        {"key": "ada", "name": "Ada Test", "handle": "ada_test",
         "category": "leader", "verified": True,
         "bio": "A test leader.", "voice": "Plain and direct.",
         "interests": ["engines"]},
        {"key": "wire", "name": "Wire Test", "handle": "wire_test",
         "category": "news", "verified": False,
         "bio": "A test wire.", "voice": "Dry and factual.",
         "interests": ["news"]},
        {"key": "neighbour", "name": "Neighbour Test", "handle": "neighbour",
         "category": "individual", "verified": False,
         "bio": "A test neighbour.", "voice": "Warm and plain.",
         "interests": ["daily-life"]},
    ]
    events = [
        {"day": 1, "date": "1900-01-01", "title": "Engines stir in Testville",
         "involved": ["ada"], "tags": ["engines"], "media": "", "media_title": "",
         "location": {"place": "Testville", "lat": 10.0, "lon": 20.0}},
        {"day": 2, "date": "1900-01-02", "title": "The wire reports movement",
         "involved": ["ada", "wire"], "tags": ["news"], "media": "broadcast",
         "media_title": "Wire bulletin from Testville",
         "location": {"place": "Testville", "lat": 10.0, "lon": 20.0}},
        {"day": 3, "date": "1900-01-03", "title": "Neighbours gather quietly",
         "involved": ["wire", "neighbour"], "tags": ["daily-life"], "media": "",
         "media_title": "",
         "location": {"place": "Old Town", "lat": 11.0, "lon": 21.0}},
    ]
    return {
        "title": "Test World", "date_range": "1900", "days": 3,
        "tagline": "A world for tests.", "hook": "Testing.",
        "agents": agents, "events": events, "population": [],
    }


def _population():
    pool = []
    for i in range(40):
        pool.append({
            "name": f"Person{i:02d} Testman",
            "handle": f"person{i:02d}_testman",
            "bio": f"An ordinary test person.",
            "voice": "Plain-spoken and brief.",
            "interests": ["daily-life", "gossip"],
        })
    return {"population": pool}


def fake_complete(system, user, temperature=0.9, model=None):
    return ("A mock briefing on the moment: streets, voices, prices and songs.", True)


def _fake_resources():
    """Deterministic resources: exercises the attach path with no network."""
    def res(rtype, title):
        return {
            "type": rtype,
            "url": f"https://example.com/{rtype}.jpg",
            "title": title,
            "source": "test",
            "description": "",
            "attribution": "test fixture",
            "metadata": {},
        }
    return {
        "images": [res("image", "Test image of the moment")],
        "quotes": [res("quote", "A test quote for the day")],
        "documents": [],
        "videos": [],
        "audio": [],
        "poems": [],
    }


def fake_resource_harness(scenario_key, day):
    return _fake_resources()


def fake_complete_json(system, user, temperature=0.6, max_tokens=3000, model=None):
    system = system or ""
    if "scenario architect" in system:
        return _schema()
    if "street-casting director" in system:
        return _population()
    payload = _payload(user)
    if not payload:
        return {"text": "A mock line about the unfolding events."}
    if "posters" in payload:
        event = payload.get("event", {}) if isinstance(payload.get("event"), dict) else {}
        title = str(event.get("title", "the events"))[:80]
        posts = []
        for p in payload["posters"] or []:
            if not isinstance(p, dict):
                continue
            key = p.get("agent_key")
            if not key:
                continue
            name = p.get("name") or key
            posts.append({
                "agent_key": key,
                "text": f"{name} notes: {title}. This is being watched closely.",
            })
        targets = payload.get("allowed_reply_targets") or []
        first_target = None
        if targets and isinstance(targets[0], dict):
            first_target = targets[0].get("agent_key")
        if not first_target and posts:
            first_target = posts[0]["agent_key"]
        replies = []
        for r in payload.get("repliers", []) or []:
            if not isinstance(r, dict) or not r.get("agent_key") or not first_target:
                continue
            replies.append({
                "agent_key": r["agent_key"],
                "target_agent_key": first_target,
                "text": "Heard. This changes the shape of the day.",
            })
        return {"posts": posts, "replies": replies}
    if "media" in payload:
        speaker = payload.get("speaker", {}) if isinstance(payload.get("speaker"), dict) else {}
        key = speaker.get("agent_key") or "speaker"
        title = str(payload.get("media_title") or payload.get("title") or "A statement")[:120]
        return {
            "agent_key": key,
            "text": f"{title}. The full statement follows in the transcript. "
                    f"These are the words as delivered on the day.",
        }
    if "replying_to" in payload:
        return {"text": "Heard. This changes the shape of the day."}
    if "agent" in payload:
        event = payload.get("event", {}) if isinstance(payload.get("event"), dict) else {}
        title = str(event.get("title", "the events"))[:80]
        return {"text": f"{title}. This is being watched closely."}
    return {"text": "A mock line about the unfolding events."}


def install():
    """Patch the LLM boundary with the fake. Returns nothing."""
    from ark import resources as _res_mod
    _SAVED["llm_available"] = llm.llm_available
    _SAVED["complete"] = llm.complete
    _SAVED["complete_json"] = llm.complete_json
    _SAVED["resource_harness"] = _res_mod.resource_harness
    llm.llm_available = lambda: True
    llm.complete = fake_complete
    llm.complete_json = fake_complete_json
    _res_mod.resource_harness = fake_resource_harness


def uninstall():
    """Restore the real LLM boundary."""
    from ark import resources as _res_mod
    if "llm_available" in _SAVED:
        llm.llm_available = _SAVED.pop("llm_available")
    if "complete" in _SAVED:
        llm.complete = _SAVED.pop("complete")
    if "complete_json" in _SAVED:
        llm.complete_json = _SAVED.pop("complete_json")
    if "resource_harness" in _SAVED:
        _res_mod.resource_harness = _SAVED.pop("resource_harness")


def payload_json(user):
    """Helper for debugging: parse an EVENT_DATA payload."""
    return _payload(user)
