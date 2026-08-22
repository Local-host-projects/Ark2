import os
import sys
import time
import requests

BASE_DIR = r"C:\Users\Ramadan\Documents\Default Project"


def _load_dotenv(path):
    try:
        for line in open(path, encoding="utf-8-sig").read().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v
    except FileNotFoundError:
        pass


_load_dotenv(os.path.join(BASE_DIR, ".env"))
sys.path.insert(0, BASE_DIR)

from ark import llm  # noqa: E402

messages = [
    {"role": "system", "content": "You are a person in 1995 posting on social media. Speak as that person, not as an assistant. No emoji. 2-4 short sentences."},
    {"role": "user", "content": "Kevin M., 40, record store regular, hates CDs, misses vinyl. His favorite band just released a CD-only album. Write one post as him."},
]
for model in llm.META_MODELS:
    for budget in (4000, 2000):
        r = requests.post(
            llm.META_URL,
            headers={"Authorization": f"Bearer {llm.META_KEY}", "Content-Type": "application/json"},
            json={"model": model, "messages": messages, "temperature": 0.85, "max_tokens": budget},
            timeout=(10, 90),
        )
        data = r.json()
        content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content")
        usage = data.get("usage", {})
        print(f"--- {model} budget={budget} HTTP {r.status_code} ---")
        print("usage:", usage)
        print("content:", (content or "<none>")[:500])
        time.sleep(1)