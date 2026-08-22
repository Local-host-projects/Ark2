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
    {"role": "system", "content": "Write a short social post. No AI talk. Human voice."},
    {"role": "user", "content": "Kevin M., 1995, hates CDs, misses vinyl. One post."},
]
for model in llm.META_MODELS:
    r = requests.post(
        llm.META_URL,
        headers={"Authorization": f"Bearer {llm.META_KEY}", "Content-Type": "application/json"},
        json={"model": model, "messages": messages, "temperature": 0.85, "max_tokens": 200},
        timeout=(8, 45),
    )
    print(f"--- {model} HTTP {r.status_code} ---")
    print(r.text[:800])
    time.sleep(1)