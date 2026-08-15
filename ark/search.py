"""Web search for the ARK research desk, powered by Exa.

Exa is a neural / AI-native search API — ideal for grounding research
briefings in live sources. Configure with EXA_API_KEY. The desk degrades
gracefully to plain LLM or offline output when it is not set.
"""
import os

import requests

EXA_URL = os.environ.get("ARK_EXA_URL", "https://api.exa.ai/search").rstrip("/")
EXA_KEY = os.environ.get("EXA_API_KEY", "").strip()
EXA_DEFAULT_NUM = int(os.environ.get("ARK_EXA_NUM_RESULTS", "5") or "5")


def exa_configured():
    return bool(EXA_KEY)


def exa_search(query, num=EXA_DEFAULT_NUM):
    """Top web results for a query: list of {title, url, snippet} dicts.

    Tolerant of Exa v1 and v2 response shapes; never raises.
    """
    if not EXA_KEY or not query:
        return []
    headers = {
        "Content-Type": "application/json",
        "x-api-key": EXA_KEY,
    }
    body = {
        "query": query[:500],
        "numResults": max(1, min(int(num), 10)),
        "contents": {"text": {"max_characters": 800}},
        "highlights": {"num_sentences": 2},
    }
    try:
        r = requests.post(EXA_URL, headers=headers, json=body, timeout=(8, 30))
        if r.status_code != 200:
            return []
        results = (r.json() or {}).get("results") or []
    except Exception:
        return []
    out = []
    seen = set()
    for res in results:
        if not isinstance(res, dict):
            continue
        url = res.get("url") or ""
        if not url or url in seen:
            continue
        seen.add(url)
        title = str(res.get("title") or "")[:200]
        snippet = str(
            res.get("text")
            or res.get("highlights")
            or res.get("summary")
            or ""
        )[:800]
        out.append({"title": title, "url": url, "snippet": snippet})
    return out
