"""Resource harness for ARK — fetches real historical resources from 15+ sources.

Sources:
  Images:  Wikipedia, Wikimedia Commons, Library of Congress, Smithsonian,
           PICRYL, Unsplash, Pexels, British Library Flickr
  Quotes:  Wikiquote, API Ninjas, ZenQuotes, Oanor
  Docs:    Chronicling America, LOC JSON, Exa Web Search
  Video:   Archive.org, YouTube Data API, AAPB, LOC Streaming
  Bonus:   Numbers API, Poetry API
"""
import os
import re
import json
import time
import hashlib
import logging
import random
from datetime import datetime, timedelta

import requests

from . import db
from . import llm

log = logging.getLogger("ark.resources")

# ---------------------------------------------------------------------------
# API keys (all optional — sources degrade gracefully when key is missing)
# ---------------------------------------------------------------------------
YOUTUBE_KEY = os.environ.get("YOUTUBE_API_KEY", "").strip()
SMITHSONIAN_KEY = os.environ.get("SMITHSONIAN_API_KEY", "").strip()
PEXELS_KEY = os.environ.get("PEXELS_API_KEY", "").strip()
UNSPLASH_KEY = os.environ.get("UNSPLASH_ACCESS_KEY", "").strip()
API_NINJAS_KEY = os.environ.get("API_NINJAS_KEY", "").strip()
FLICKR_KEY = os.environ.get("FLICKR_API_KEY", "").strip()

_EXA = None


def _exa():
    global _EXA
    if _EXA is None:
        try:
            from . import search as _s
            _EXA = _s
        except Exception:
            _EXA = False
    return _EXA if _EXA else None


def _get(url, params=None, timeout=10, headers=None):
    """GET with timeout and error swallowing."""
    try:
        r = requests.get(url, params=params, headers=headers, timeout=timeout)
        if r.status_code == 200:
            return r.json() if "json" in (r.headers.get("content-type") or "") else r.text
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------
def _cache_key(scenario_key, day, source, query):
    h = hashlib.md5(query.encode()).hexdigest()[:12]
    return (scenario_key, day, source, h)


def _get_cache(scenario_key, day, source, query):
    key = _cache_key(scenario_key, day, source, query)
    with db.cursor() as cur:
        row = cur.execute(
            "SELECT data FROM resource_cache WHERE scenario_key=? AND day=? AND source=? AND query=?",
            key,
        ).fetchone()
    if row:
        try:
            return json.loads(row["data"])
        except Exception:
            pass
    return None


def _set_cache(scenario_key, day, source, query, data):
    key = _cache_key(scenario_key, day, source, query)
    with db.get_conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO resource_cache (scenario_key,day,source,query,data) VALUES (?,?,?,?,?)",
            (*key, json.dumps(data, ensure_ascii=False)),
        )


def _resource(type, url, title, source, description="", attribution="", metadata=None):
    return {
        "type": type,
        "url": url,
        "title": title[:300],
        "source": source,
        "description": description[:500],
        "attribution": attribution[:300],
        "metadata": metadata or {},
    }


# ===========================================================================
# IMAGE SOURCES
# ===========================================================================

def _fetch_wikipedia_images(events, agents, date):
    """Fetch images from Wikipedia summaries for agents and events."""
    resources = []
    seen = set()

    # Agent images
    for a in (agents or [])[:8]:
        wiki_page = a.get("wikipedia_page") or a.get("name", "")
        if not wiki_page or wiki_page in seen:
            continue
        seen.add(wiki_page)
        data = _get(
            f"https://en.wikipedia.org/api/rest_v1/page/summary/{wiki_page}",
            headers={"User-Agent": "ARK-ResourceHarness/1.0"},
        )
        if isinstance(data, dict) and data.get("thumbnail", {}).get("source"):
            thumb = data["thumbnail"]["source"]
            resources.append(_resource(
                "image", thumb,
                data.get("title", wiki_page),
                "wikipedia",
                data.get("extract", "")[:200],
                "Wikipedia",
                {"license": "CC BY-SA", "page": wiki_page},
            ))

    # Event images
    for ev in (events or [])[:6]:
        title = ev.get("title", "")
        if not title or title in seen:
            continue
        seen.add(title)
        # Search Wikipedia for event
        search_title = title.split(":")[0].strip()[:80]
        data = _get(
            f"https://en.wikipedia.org/api/rest_v1/page/summary/{search_title}",
            headers={"User-Agent": "ARK-ResourceHarness/1.0"},
        )
        if isinstance(data, dict) and data.get("thumbnail", {}).get("source"):
            thumb = data["thumbnail"]["source"]
            resources.append(_resource(
                "image", thumb,
                data.get("title", search_title),
                "wikipedia",
                data.get("extract", "")[:200],
                "Wikipedia",
                {"license": "CC BY-SA"},
            ))

    return resources


def _fetch_wikimedia_images(events, date):
    """Search Wikimedia Commons for historical images."""
    resources = []
    queries = []
    for ev in (events or [])[:5]:
        title = ev.get("title", "")
        if title:
            queries.append(title.split(":")[0].strip()[:60])
    if date:
        queries.append(f"historical {date}")

    for q in queries[:4]:
        cache = _get_cache("", 0, "wikimedia", q)
        if cache:
            resources.extend(cache)
            continue
        data = _get(
            "https://commons.wikimedia.org/w/api.php",
            params={
                "action": "query",
                "list": "search",
                "srsearch": q,
                "srnamespace": "6",
                "srlimit": "3",
                "format": "json",
            },
            timeout=12,
        )
        batch = []
        if isinstance(data, dict):
            for item in (data.get("query", {}).get("search") or [])[:3]:
                title = item.get("title", "")
                if not title:
                    continue
                # Get image info
                info = _get(
                    "https://commons.wikimedia.org/w/api.php",
                    params={
                        "action": "query",
                        "titles": title,
                        "prop": "imageinfo",
                        "iiprop": "url|extmetadata",
                        "iiurlwidth": "800",
                        "format": "json",
                    },
                    timeout=10,
                )
                if isinstance(info, dict):
                    pages = info.get("query", {}).get("pages", {})
                    for page in pages.values():
                        for img in page.get("imageinfo", []):
                            url = img.get("thumburl") or img.get("url", "")
                            if url:
                                ext = img.get("extmetadata", {})
                                desc = ext.get("ImageDescription", {}).get("value", "")[:200]
                                lic = ext.get("LicenseShortName", {}).get("value", "")
                                batch.append(_resource(
                                    "image", url, title.replace("File:", ""),
                                    "wikimedia", desc, "Wikimedia Commons",
                                    {"license": lic},
                                ))
        _set_cache("", 0, "wikimedia", q, batch)
        resources.extend(batch)

    return resources


def _fetch_loc_images(events, date):
    """Search Library of Congress digital collections."""
    resources = []
    queries = []
    for ev in (events or [])[:4]:
        title = ev.get("title", "")
        if title:
            queries.append(title.split(":")[0].strip()[:60])
    if date:
        queries.append(f"historical {date}")

    for q in queries[:3]:
        cache = _get_cache("", 0, "loc", q)
        if cache:
            resources.extend(cache)
            continue
        data = _get(
            "https://www.loc.gov/search/",
            params={"q": q, "fa": "online-format:image", "fo": "json", "c": "5"},
            timeout=15,
        )
        batch = []
        if isinstance(data, dict):
            for item in (data.get("results") or [])[:5]:
                img_url = ""
                for fmt in item.get("formats", []):
                    if "image" in str(fmt.get("mimetype", "")).lower():
                        img_url = fmt.get("url", "")
                        break
                if not img_url:
                    img_url = item.get("image_url", [""])[0] if isinstance(item.get("image_url"), list) else item.get("image_url", "")
                if img_url:
                    batch.append(_resource(
                        "image", img_url,
                        item.get("title", q)[:200],
                        "loc",
                        item.get("description", [""])[0][:200] if isinstance(item.get("description"), list) else str(item.get("description", ""))[:200],
                        "Library of Congress",
                        {"license": "Public Domain"},
                    ))
        _set_cache("", 0, "loc", q, batch)
        resources.extend(batch)

    return resources


def _fetch_smithsonian_images(events, date):
    """Search Smithsonian Open Access (5.1M CC0 images)."""
    if not SMITHSONIAN_KEY:
        return []
    resources = []
    queries = []
    for ev in (events or [])[:3]:
        title = ev.get("title", "")
        if title:
            queries.append(title.split(":")[0].strip()[:60])

    for q in queries[:2]:
        cache = _get_cache("", 0, "smithsonian", q)
        if cache:
            resources.extend(cache)
            continue
        data = _get(
            "https://api.si.edu/openaccess/api/v1.0/search",
            params={"q": q, "api_key": SMITHSONIAN_KEY, "rows": "3"},
            timeout=15,
        )
        batch = []
        if isinstance(data, dict):
            for row in (data.get("response", {}).get("rows") or [])[:3]:
                content = row.get("content", {})
                desc = content.get("descriptiveNonRepeating", {})
                img_url = desc.get("online_media", {}).get("media", [{}])[0].get("content", "")
                if img_url:
                    title_text = desc.get("title", {}).get("content", q)[:200]
                    batch.append(_resource(
                        "image", img_url, title_text,
                        "smithsonian",
                        content.get("freetext", {}).get("notes", [{}])[0].get("content", "")[:200] if content.get("freetext", {}).get("notes") else "",
                        "Smithsonian Open Access",
                        {"license": "CC0"},
                    ))
        _set_cache("", 0, "smithsonian", q, batch)
        resources.extend(batch)

    return resources


def _fetch_picryl_images(events, date):
    """Search PICRYL for public domain images."""
    resources = []
    queries = []
    for ev in (events or [])[:3]:
        title = ev.get("title", "")
        if title:
            queries.append(title.split(":")[0].strip()[:60])

    for q in queries[:2]:
        cache = _get_cache("", 0, "picryl", q)
        if cache:
            resources.extend(cache)
            continue
        data = _get(
            "https://picryl.com/api/search",
            params={"query": q, "per_page": "3"},
            timeout=12,
        )
        batch = []
        if isinstance(data, dict):
            for item in (data.get("results") or [])[:3]:
                img_url = item.get("image_url") or item.get("source_url", "")
                if img_url:
                    batch.append(_resource(
                        "image", img_url,
                        item.get("title", q)[:200],
                        "picryl",
                        item.get("description", "")[:200],
                        "PICRYL",
                        {"license": "Public Domain"},
                    ))
        _set_cache("", 0, "picryl", q, batch)
        resources.extend(batch)

    return resources


def _fetch_unsplash_images(events, date):
    """Search Unsplash for atmospheric images."""
    if not UNSPLASH_KEY:
        return []
    resources = []
    queries = []
    for ev in (events or [])[:2]:
        title = ev.get("title", "")
        if title:
            queries.append(title.split(":")[0].strip()[:40])

    for q in queries[:2]:
        cache = _get_cache("", 0, "unsplash", q)
        if cache:
            resources.extend(cache)
            continue
        data = _get(
            "https://api.unsplash.com/search/photos",
            params={"query": q, "per_page": "2", "orientation": "landscape"},
            headers={"Authorization": f"Client-ID {UNSPLASH_KEY}"},
            timeout=10,
        )
        batch = []
        if isinstance(data, dict):
            for item in (data.get("results") or [])[:2]:
                img_url = item.get("urls", {}).get("regular", "")
                if img_url:
                    batch.append(_resource(
                        "image", img_url,
                        item.get("description") or item.get("alt_description") or q,
                        "unsplash",
                        f"Photo by {item.get('user', {}).get('name', 'Unknown')}",
                        "Unsplash",
                        {"license": "Unsplash License"},
                    ))
        _set_cache("", 0, "unsplash", q, batch)
        resources.extend(batch)

    return resources


def _fetch_pexels_images(events, date):
    """Search Pexels for stock images."""
    if not PEXELS_KEY:
        return []
    resources = []
    queries = []
    for ev in (events or [])[:2]:
        title = ev.get("title", "")
        if title:
            queries.append(title.split(":")[0].strip()[:40])

    for q in queries[:2]:
        cache = _get_cache("", 0, "pexels", q)
        if cache:
            resources.extend(cache)
            continue
        data = _get(
            "https://api.pexels.com/v1/search",
            params={"query": q, "per_page": "2", "orientation": "landscape"},
            headers={"Authorization": PEXELS_KEY},
            timeout=10,
        )
        batch = []
        if isinstance(data, dict):
            for item in (data.get("photos") or [])[:2]:
                img_url = item.get("src", {}).get("large", "")
                if img_url:
                    batch.append(_resource(
                        "image", img_url,
                        item.get("alt") or q,
                        "pexels",
                        f"Photo by {item.get('photographer', 'Unknown')}",
                        "Pexels",
                        {"license": "Pexels License"},
                    ))
        _set_cache("", 0, "pexels", q, batch)
        resources.extend(batch)

    return resources


def _fetch_flickr_images(events, date):
    """Search British Library Flickr for 17-19th century images."""
    if not FLICKR_KEY:
        return []
    resources = []
    queries = []
    for ev in (events or [])[:2]:
        title = ev.get("title", "")
        if title:
            queries.append(title.split(":")[0].strip()[:40])

    for q in queries[:2]:
        cache = _get_cache("", 0, "flickr", q)
        if cache:
            resources.extend(cache)
            continue
        data = _get(
            "https://api.flickr.com/services/rest/",
            params={
                "method": "flickr.photos.search",
                "api_key": FLICKR_KEY,
                "text": q,
                "user_id": "12403504@N02",  # British Library
                "per_page": "3",
                "format": "json",
                "nojsoncallback": "1",
            },
            timeout=10,
        )
        batch = []
        if isinstance(data, dict):
            for item in (data.get("photos", {}).get("photo") or [])[:3]:
                farm = item.get("farm", "")
                server = item.get("server", "")
                pid = item.get("id", "")
                secret = item.get("secret", "")
                if farm and server and pid and secret:
                    img_url = f"https://live.staticflickr.com/{server}/{pid}_{secret}_b.jpg"
                    batch.append(_resource(
                        "image", img_url,
                        item.get("title", q)[:200],
                        "flickr_british_library",
                        "British Library Historical Collection",
                        "British Library / Flickr",
                        {"license": "No known copyright restrictions"},
                    ))
        _set_cache("", 0, "flickr", q, batch)
        resources.extend(batch)

    return resources


# ===========================================================================
# QUOTE SOURCES
# ===========================================================================

def _fetch_wikiquote_quotes(agents, date):
    """Fetch quotes from Wikiquote for historical figures."""
    resources = []
    names = []
    for a in (agents or [])[:6]:
        name = a.get("name", "")
        if name and a.get("verified"):
            names.append(name)

    for name in names[:4]:
        cache = _get_cache("", 0, "wikiquote", name)
        if cache:
            resources.extend(cache)
            continue
        data = _get(
            "https://en.wikiquote.org/w/api.php",
            params={
                "action": "parse",
                "page": name,
                "prop": "wikitext",
                "format": "json",
            },
            timeout=10,
        )
        batch = []
        if isinstance(data, dict) and data.get("parse"):
            wikitext = data["parse"].get("wikitext", {}).get("*", "")
            # Extract quoted text (lines starting with * or :*)
            quotes = []
            for line in wikitext.split("\n"):
                line = line.strip()
                if line.startswith("::"):
                    continue
                if line.startswith(":*") or line.startswith("*"):
                    q = re.sub(r"\[\[.*?\]\]", "", line.lstrip(":*")).strip()
                    q = re.sub(r"{{.*?}}", "", q).strip()
                    if len(q) > 20 and len(q) < 500:
                        quotes.append(q)
                if len(quotes) >= 3:
                    break
            for q in quotes:
                batch.append(_resource(
                    "quote", "",
                    q, "wikiquote",
                    f"Attributed to {name}",
                    "Wikiquote",
                    {"author": name},
                ))
        _set_cache("", 0, "wikiquote", name, batch)
        resources.extend(batch)

    return resources


def _fetch_apininjas_quotes(agents, date):
    """Fetch quotes from API Ninjas by category."""
    if not API_NINJAS_KEY:
        return []
    resources = []
    categories = ["wisdom", "courage", "truth", "leadership", "war"]
    random.shuffle(categories)

    for cat in categories[:2]:
        cache = _get_cache("", 0, "api-ninjas", cat)
        if cache:
            resources.extend(cache)
            continue
        data = _get(
            "https://api.api-ninjas.com/v2/quotes",
            params={"category": cat},
            headers={"X-Api-Key": API_NINJAS_KEY},
            timeout=8,
        )
        batch = []
        if isinstance(data, list):
            for item in data[:2]:
                batch.append(_resource(
                    "quote", "",
                    item.get("quote", ""),
                    "api-ninjas",
                    item.get("author", ""),
                    "API Ninjas",
                    {"category": cat, "author": item.get("author", ""), "work": item.get("work", "")},
                ))
        _set_cache("", 0, "api-ninjas", cat, batch)
        resources.extend(batch)

    return resources


def _fetch_zenquotes(date):
    """Fetch inspirational quotes from ZenQuotes."""
    cache = _get_cache("", 0, "zenquotes", date or "daily")
    if cache:
        return cache
    data = _get("https://zenquotes.io/api/quotes", timeout=8)
    batch = []
    if isinstance(data, list):
        for item in data[:3]:
            batch.append(_resource(
                "quote", "",
                item.get("q", ""),
                "zenquotes",
                item.get("a", ""),
                "ZenQuotes.io",
                {"author": item.get("a", "")},
            ))
    _set_cache("", 0, "zenquotes", date or "daily", batch)
    return batch


def _fetch_oanor_quotes(date):
    """Fetch quotes from Oanor API."""
    cache = _get_cache("", 0, "oanor", date or "daily")
    if cache:
        return cache
    data = _get("https://api.oanor.com/quotes-api/random", timeout=8)
    batch = []
    if isinstance(data, dict) and data.get("quote"):
        batch.append(_resource(
            "quote", "",
            data.get("quote", ""),
            "oanor",
            data.get("author", ""),
            "Oanor Quotes API",
            {"author": data.get("author", "")},
        ))
    _set_cache("", 0, "oanor", date or "daily", batch)
    return batch


# ===========================================================================
# DOCUMENT / NEWSPAPER SOURCES
# ===========================================================================

def _fetch_chronam_documents(events, date):
    """Fetch historic newspaper pages from Chronicling America (LOC)."""
    resources = []
    # Build date range
    if date:
        try:
            dt = datetime.strptime(date, "%Y-%m-%d")
            date_str = dt.strftime("%Y%m%d")
            date1 = dt.strftime("%Y-%m-%d")
            date2 = (dt + timedelta(days=1)).strftime("%Y-%m-%d")
        except Exception:
            date1 = date2 = date_str = ""
    else:
        date1 = date2 = date_str = ""

    if not date1:
        return resources

    queries = []
    for ev in (events or [])[:3]:
        title = ev.get("title", "")
        if title:
            queries.append(title.split(":")[0].strip()[:60])

    for q in queries[:2]:
        cache = _get_cache("", 0, "chronam", f"{date1}:{q}")
        if cache:
            resources.extend(cache)
            continue
        data = _get(
            "https://chroniclingamerica.loc.gov/search/pages/results/",
            params={
                "andtext": q,
                "date1": date1,
                "date2": date2,
                "dateFilterType": "yearRange",
                "format": "json",
                "rows": "3",
            },
            timeout=15,
        )
        batch = []
        if isinstance(data, dict):
            for item in (data.get("items") or [])[:3]:
                page_url = item.get("url", "")
                title_text = item.get("title", q)[:200]
                ocr_url = item.get("ocr_eng", "")
                if page_url:
                    batch.append(_resource(
                        "document",
                        f"https://chroniclingamerica.loc.gov{page_url}",
                        title_text,
                        "chronam",
                        ocr_url[:200] if ocr_url else f"Newspaper page from {date1}",
                        "Library of Congress / Chronicling America",
                        {"date": date1, "state": item.get("state", ""), "language": item.get("language", "")},
                    ))
        _set_cache("", 0, "chronam", f"{date1}:{q}", batch)
        resources.extend(batch)

    return resources


def _fetch_loc_documents(events, date):
    """Fetch structured documents from LOC JSON API."""
    resources = []
    queries = []
    for ev in (events or [])[:3]:
        title = ev.get("title", "")
        if title:
            queries.append(title.split(":")[0].strip()[:60])

    for q in queries[:2]:
        cache = _get_cache("", 0, "loc-docs", q)
        if cache:
            resources.extend(cache)
            continue
        data = _get(
            "https://www.loc.gov/search/",
            params={"q": q, "fo": "json", "c": "3"},
            timeout=15,
        )
        batch = []
        if isinstance(data, dict):
            for item in (data.get("results") or [])[:3]:
                item_url = item.get("url", "")
                title_text = item.get("title", q)[:200]
                desc = item.get("description", "")[:200]
                if isinstance(desc, list):
                    desc = desc[0] if desc else ""
                if item_url:
                    batch.append(_resource(
                        "document", item_url, title_text,
                        "loc",
                        desc,
                        "Library of Congress",
                        {"date": item.get("date", "")},
                    ))
        _set_cache("", 0, "loc-docs", q, batch)
        resources.extend(batch)

    return resources


def _fetch_exa_documents(events, date):
    """Search Exa for era-specific articles and documents."""
    exa = _exa()
    if not exa:
        return []
    resources = []
    queries = []
    for ev in (events or [])[:3]:
        title = ev.get("title", "")
        if title:
            queries.append(f"historical {title.split(':')[0].strip()[:50]}")
    if date:
        queries.append(f"historical events {date}")

    for q in queries[:2]:
        cache = _get_cache("", 0, "exa", q)
        if cache:
            resources.extend(cache)
            continue
        results = exa.exa_search(q, num=3)
        batch = []
        for r in results:
            batch.append(_resource(
                "document",
                r.get("url", ""),
                r.get("title", q)[:200],
                "exa",
                r.get("snippet", "")[:200],
                "Exa Web Search",
                {},
            ))
        _set_cache("", 0, "exa", q, batch)
        resources.extend(batch)

    return resources


# ===========================================================================
# VIDEO / AUDIO SOURCES
# ===========================================================================

def _fetch_archive_videos(events, date):
    """Search Archive.org for public domain videos."""
    resources = []
    queries = []
    for ev in (events or [])[:3]:
        title = ev.get("title", "")
        if title:
            queries.append(title.split(":")[0].strip()[:60])

    for q in queries[:2]:
        cache = _get_cache("", 0, "archive-org", q)
        if cache:
            resources.extend(cache)
            continue
        data = _get(
            "https://archive.org/advancedsearch.php",
            params={
                "q": f"{q} AND mediatype:movies",
                "fl[]": "identifier,title,description",
                "rows": "3",
                "output": "json",
            },
            timeout=15,
        )
        batch = []
        if isinstance(data, dict):
            for item in (data.get("response", {}).get("docs") or [])[:3]:
                ident = item.get("identifier", "")
                title_text = item.get("title", q)[:200]
                if ident:
                    embed_url = f"https://archive.org/embed/{ident}"
                    batch.append(_resource(
                        "video", embed_url, title_text,
                        "archive.org",
                        item.get("description", "")[:200],
                        "Internet Archive",
                        {"identifier": ident},
                    ))
        _set_cache("", 0, "archive-org", q, batch)
        resources.extend(batch)

    return resources


def _fetch_youtube_videos(events, date):
    """Search YouTube for CC-licensed historical videos."""
    if not YOUTUBE_KEY:
        return []
    resources = []
    queries = []
    for ev in (events or [])[:3]:
        title = ev.get("title", "")
        if title:
            queries.append(f"{title.split(':')[0].strip()[:50]} historical")

    for q in queries[:2]:
        cache = _get_cache("", 0, "youtube", q)
        if cache:
            resources.extend(cache)
            continue
        data = _get(
            "https://www.googleapis.com/youtube/v3/search",
            params={
                "part": "snippet",
                "q": q,
                "type": "video",
                "videoLicense": "creativeCommon",
                "maxResults": "3",
                "key": YOUTUBE_KEY,
            },
            timeout=10,
        )
        batch = []
        if isinstance(data, dict):
            for item in (data.get("items") or [])[:3]:
                vid = item.get("id", {}).get("videoId", "")
                snippet = item.get("snippet", {})
                if vid:
                    embed_url = f"https://www.youtube.com/embed/{vid}"
                    batch.append(_resource(
                        "video", embed_url,
                        snippet.get("title", q)[:200],
                        "youtube",
                        snippet.get("description", "")[:200],
                        "YouTube (Creative Commons)",
                        {"videoId": vid, "channel": snippet.get("channelTitle", "")},
                    ))
        _set_cache("", 0, "youtube", q, batch)
        resources.extend(batch)

    return resources


def _fetch_aapb_audio(events, date):
    """American Archive of Public Broadcasting has no public search API.

    Returns [] — ARK only attaches resources it actually fetched.
    """
    return []


def _fetch_loc_audio(events, date):
    """LOC audio is covered by document search; no synthetic links."""
    return []


# ===========================================================================
# BONUS SOURCES
# ===========================================================================

def _fetch_numbers_trivia(date):
    """Fetch "on this day" trivia from Numbers API."""
    if not date:
        return []
    try:
        dt = datetime.strptime(date, "%Y-%m-%d")
        day_of_year = dt.timetuple().tm_yday
    except Exception:
        return []

    cache = _get_cache("", 0, "numbers", date)
    if cache:
        return cache

    batch = []
    data = _get(f"http://numbersapi.com/{day_of_year}/date?json", timeout=5)
    if isinstance(data, dict) and data.get("text"):
        batch.append(_resource(
            "document", "",
            data["text"],
            "numbersapi",
            f"On this date: {date}",
            "Numbers API",
            {"date": date, "number": day_of_year},
        ))
    _set_cache("", 0, "numbers", date, batch)
    return batch


def _fetch_poetry(agents, date):
    """Fetch period-appropriate poems from Poetry API."""
    resources = []
    authors = ["Shakespeare", "Dickinson", "Whitman", "Frost", "Poe"]
    random.shuffle(authors)

    for author in authors[:1]:
        cache = _get_cache("", 0, "poetry", author)
        if cache:
            resources.extend(cache)
            continue
        data = _get(
            f"https://poetrydb.org/author.json",
            params={"author": author},
            timeout=8,
        )
        batch = []
        if isinstance(data, dict) and data.get("poems"):
            for poem in data["poems"][:1]:
                title_text = poem.get("title", "")
                lines = poem.get("lines", [])
                excerpt = "\n".join(lines[:4])[:300]
                if excerpt:
                    batch.append(_resource(
                        "poem", "",
                        f"{title_text}\n\n{excerpt}",
                        "poetrydb",
                        f"By {author}",
                        "Poetry Database",
                        {"author": author, "title": title_text},
                    ))
        _set_cache("", 0, "poetry", author, batch)
        resources.extend(batch)

    return resources


# ===========================================================================
# MAIN HARNESS
# ===========================================================================

def resource_harness(scenario_key, day):
    """Fetch all resources for a given day.

    Returns dict with keys: images, quotes, documents, videos, audio, poems.
    Each is a list of Resource dicts. Results are cached.
    """
    from .core import get_scenario, get_events_for_day, _agent_meta

    sc = get_scenario(scenario_key)
    if not sc:
        return {"images": [], "quotes": [], "documents": [], "videos": [], "audio": [], "poems": []}

    # Get events for this day
    events = get_events_for_day(scenario_key, day)

    # Get agents for this scenario
    with db.cursor() as cur:
        agent_rows = cur.execute(
            "SELECT * FROM agents WHERE scenario_key=?", (scenario_key,)
        ).fetchall()
    agents = [dict(a) for a in agent_rows]

    # Compute date string
    date_str = ""
    if events:
        date_str = events[0].get("date", "")
    if not date_str:
        try:
            from .core import _day_range
            dr = _day_range(sc)
            if day < len(dr):
                date_str = dr[day]
        except Exception:
            pass

    # Gather resources from all sources
    log.info("Resource harness: fetching for day %d (%s)", day, date_str)

    images = []
    images.extend(_fetch_wikipedia_images(events, agents, date_str))
    images.extend(_fetch_wikimedia_images(events, date_str))
    images.extend(_fetch_loc_images(events, date_str))
    images.extend(_fetch_smithsonian_images(events, date_str))
    images.extend(_fetch_picryl_images(events, date_str))
    images.extend(_fetch_pexels_images(events, date_str))
    images.extend(_fetch_flickr_images(events, date_str))

    quotes = []
    quotes.extend(_fetch_wikiquote_quotes(agents, date_str))
    quotes.extend(_fetch_apininjas_quotes(agents, date_str))
    quotes.extend(_fetch_zenquotes(date_str))
    quotes.extend(_fetch_oanor_quotes(date_str))

    documents = []
    documents.extend(_fetch_chronam_documents(events, date_str))
    documents.extend(_fetch_loc_documents(events, date_str))
    documents.extend(_fetch_exa_documents(events, date_str))

    videos = []
    videos.extend(_fetch_archive_videos(events, date_str))
    videos.extend(_fetch_youtube_videos(events, date_str))

    audio = []
    audio.extend(_fetch_aapb_audio(events, date_str))
    audio.extend(_fetch_loc_audio(events, date_str))

    poems = []
    poems.extend(_fetch_numbers_trivia(date_str))
    poems.extend(_fetch_poetry(agents, date_str))

    log.info(
        "Resource harness: %d images, %d quotes, %d docs, %d videos, %d audio, %d poems",
        len(images), len(quotes), len(documents), len(videos), len(audio), len(poems),
    )

    return {
        "images": images,
        "quotes": quotes,
        "documents": documents,
        "videos": videos,
        "audio": audio,
        "poems": poems,
    }


def select_resources_for_post(agent, event, all_resources, max_resources=3):
    """Select the most relevant resources for a single post."""
    selected = []
    agent_key = agent.get("agent_key", "")
    event_title = event.get("title", "") if event else ""
    event_tags = []
    if event:
        try:
            event_tags = json.loads(event.get("tags", "[]"))
        except Exception:
            pass

    # Priority 1: Wikipedia image for this agent
    for r in all_resources.get("images", []):
        if r.get("source") == "wikipedia" and agent_key.lower() in r.get("title", "").lower():
            selected.append(r)
            break

    # Priority 2: Quote from this agent (if verified/leader)
    if agent.get("verified"):
        for r in all_resources.get("quotes", []):
            author = r.get("metadata", {}).get("author", "").lower()
            if agent.get("name", "").lower() in author or agent_key.lower() in author:
                selected.append(r)
                break

    # Priority 3: Document related to event
    for r in all_resources.get("documents", []):
        if event_title and event_title.split(":")[0].strip().lower() in r.get("title", "").lower():
            selected.append(r)
            break

    # Priority 4: Video related to event
    for r in all_resources.get("videos", []):
        if event_title and event_title.split(":")[0].strip().lower() in r.get("title", "").lower():
            selected.append(r)
            break

    # Fill remaining slots with random images/quotes
    remaining = max_resources - len(selected)
    if remaining > 0:
        pool = (
            random.sample(all_resources.get("images", []), min(remaining, len(all_resources.get("images", []))))
            + random.sample(all_resources.get("quotes", []), min(remaining, len(all_resources.get("quotes", []))))
        )
        random.shuffle(pool)
        for r in pool:
            if len(selected) >= max_resources:
                break
            if r not in selected:
                selected.append(r)

    return selected[:max_resources]


def store_post_resources(post_id, scenario_key, day, resources):
    """Store resource references for a post in the database."""
    store_posts_resources([(post_id, scenario_key, day, resources)])


def store_posts_resources(rows):
    """Store resource references for many posts in one transaction.

    rows: iterable of (post_id, scenario_key, day, resources).
    """
    batch = []
    for post_id, scenario_key, day, resources in rows:
        for r in resources or []:
            batch.append((
                scenario_key, day, post_id,
                r.get("type", ""),
                r.get("url", ""),
                r.get("title", ""),
                r.get("source", ""),
                r.get("description", ""),
                r.get("attribution", ""),
                json.dumps(r.get("metadata", {}), ensure_ascii=False),
            ))
    if not batch:
        return
    with db.get_conn() as c:
        for row in batch:
            c.execute(
                "INSERT INTO post_resources "
                "(scenario_key,day,post_id,resource_type,url,title,source,description,attribution,metadata) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                row,
            )


def get_post_resources(post_id):
    """Get resources attached to a post."""
    with db.cursor() as cur:
        rows = cur.execute(
            "SELECT * FROM post_resources WHERE post_id=?", (post_id,)
        ).fetchall()
    return [dict(r) for r in rows]
