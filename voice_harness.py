"""Compare providers/models on "socialness" + historical voice for ARK.

Tests each configured provider directly (skipping AgentRouter), one character
prompt, same temperature. Prints raw outputs so we can judge which model
sounds most like a real person and least like AI.
"""
import os
import sys
import time

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

SYSTEM = (
    "You are ARK, a living temporal simulation. You are writing a social-media post "
    "as ONE real person, in-character, at one exact moment. Rules: exist only in this "
    "present moment; no hindsight; speak in the person's own true voice; it can be "
    "short, mundane, rambling, angry or trivial; a post is a public broadcast with a "
    "cause, not a history lesson; never mention AI or the simulation; era-appropriate "
    "vocabulary only; no emoji; 1-3 short sentences. Do NOT smooth the voice into a "
    "polite modern tone. Never explain anything; just be this person."
)

USER = (
    "Character: Kevin M., a 40-year-old record store regular in 1995 who hates CDs "
    "and misses vinyl. The event: his favorite band just released a CD-only album. "
    "Write one post as him."
)

TARGETS = []

def register_targets():
    # Meta (Muse Spark)
    for m in llm.META_MODELS:
        TARGETS.append(("meta", m))
    # Gemini variants
    for m in llm.GEMINI_MODELS:
        TARGETS.append(("gemini", m))
    # OpenRouter models
    for m in llm.OPENROUTER_MODELS:
        TARGETS.append(("openrouter", m))


def single_try(target):
    label, model = target
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": USER},
    ]
    start = time.time()
    try:
        if label == "gemini":
            out, err = llm._gemini_call(llm.GEMINI_KEY, [model], messages, 0.85, 500)
        else:
            base = {"meta": llm.META_URL, "openrouter": llm.OPENROUTER_URL}[label]
            key = {"meta": llm.META_KEY, "openrouter": llm.OPENROUTER_KEY}[label]
            out, err = llm._call(base, key, [model], messages, 0.85, 500)
        elapsed = time.time() - start
        if out:
            return out, err, elapsed
        return None, err, elapsed
    except Exception as e:  # noqa
        return None, str(e), time.time() - start


def main():
    register_targets()
    print("=" * 60)
    for target in TARGETS:
        label, model = target
        if not {"meta": llm.META_KEY, "gemini": llm.GEMINI_KEY, "openrouter": llm.OPENROUTER_KEY}[label]:
            print(f"[{label}] {model}: not configured, skipped")
            continue
        out, err, elapsed = single_try(target)
        print(f"[{label}] {model} — {elapsed:.1f}s")
        if out:
            print("  ->", out.replace("\n", " / ")[:300])
        else:
            print("  !!", (err or "no output")[:200])
        print("-" * 60)
        time.sleep(1)


if __name__ == "__main__":
    main()