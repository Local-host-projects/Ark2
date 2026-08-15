"""LLM service for ARK.

Provider priority (the first configured provider is used by default):
  1. AgentRouter     — gpt-5.6-sol (GPT-5.6 Sol) primary (AGENTROUTER_API_KEY), OpenAI-compatible
  2. Google Gemini (Google AI Studio) — GEMINI_API_KEY, OpenAI-compatible endpoint
  3. OpenRouter       — DeepSeek + Gemini + GPT (OPENROUTER_API_KEY)
  4. Meta Model API   — Muse Spark (META_API_KEY / MODEL_API_KEY), OpenAI-compatible
Set ARK_LLM_PROVIDER_FALLBACK=1 to try later providers after a failure.
The deterministic offline generator keeps the app available either way.
"""
import os
import re
import json
import time
import requests

REQUEST_CONNECT_TIMEOUT = float(os.environ.get("ARK_LLM_CONNECT_TIMEOUT", "8"))
REQUEST_READ_TIMEOUT = float(os.environ.get("ARK_LLM_READ_TIMEOUT", "45"))
ALLOW_PROVIDER_FALLBACK = os.environ.get("ARK_LLM_PROVIDER_FALLBACK", "0") == "1"

GEMINI_URL = os.environ.get(
    "ARK_GEMINI_URL", "https://generativelanguage.googleapis.com/v1beta/models"
).rstrip("/")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODELS = [
    m.strip()
    for m in os.environ.get(
        "ARK_GEMINI_MODEL", "gemini-3.5-flash, gemini-3.5-flash-lite, gemini-3.1-flash-lite"
    ).split(",")
    if m.strip()
]

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY", "").strip()
OPENROUTER_MODELS = [
    m.strip()
    for m in os.environ.get(
        "ARK_MODELS",
        "deepseek/deepseek-chat, google/gemini-2.5-flash, openai/gpt-4o-mini",
    ).split(",")
    if m.strip()
]

META_URL = os.environ.get("ARK_META_URL", "https://api.meta.ai/v1/chat/completions")
META_KEY = os.environ.get("META_API_KEY", "") or os.environ.get("MODEL_API_KEY", "")
META_MODELS = [
    m.strip()
    for m in os.environ.get(
        "ARK_META_MODEL", "muse-spark-1.1, muse-spark-1.2"
    ).split(",")
    if m.strip()
]

# AgentRouter — OpenAI-compatible gateway; primary provider.
AGENTROUTER_URL = os.environ.get(
    "ARK_AGENTROUTER_URL", "https://agentrouter.org/v1/chat/completions"
)
AGENTROUTER_KEY = os.environ.get("AGENTROUTER_API_KEY", "").strip()
AGENTROUTER_MODELS = [
    m.strip()
    for m in os.environ.get(
        "ARK_AGENTROUTER_MODEL", "gpt-5.6-sol"
    ).split(",")
    if m.strip()
]

SYSTEM_BASE = (
    "You are writing the social-media posts, replies, profiles and research notes for ARK, "
    "a historical-immersion app. A historical event is being reconstructed, temporally compressed. "
    "You write in the voice of a real person in that moment. Few, short, vivid lines. "
    "No emoji unless the period plausibly had them (it didn't). Keep it era-appropriate, human, and specific. "
    "Never break character. Never mention you are an AI. Stay inside the given date."
)


def _providers():
    """Yield (label, base_url, key, models) for each configured provider."""
    if AGENTROUTER_KEY:
        yield ("agentrouter", AGENTROUTER_URL, AGENTROUTER_KEY, AGENTROUTER_MODELS)
    if GEMINI_KEY:
        yield ("gemini", GEMINI_URL, GEMINI_KEY, GEMINI_MODELS)
    if OPENROUTER_KEY:
        yield ("openrouter", OPENROUTER_URL, OPENROUTER_KEY, OPENROUTER_MODELS)
    if META_KEY:
        yield ("meta", META_URL, META_KEY, META_MODELS)


def llm_status():
    providers = list(_providers())
    if not providers:
        return {"configured": False, "provider": None, "model": None, "fallback_enabled": False}
    label, _base, _key, models = providers[0]
    return {
        "configured": True,
        "provider": label,
        "model": models[0] if models else None,
        "fallback_enabled": ALLOW_PROVIDER_FALLBACK,
    }


def _targets():
    providers = list(_providers())
    return providers if ALLOW_PROVIDER_FALLBACK else providers[:1]


def _chat(messages, temperature=0.9, max_tokens=420, model=None):
    if model:
        # explicit single-model call: try each provider with that model id
        targets = []
        if AGENTROUTER_KEY:
            targets.append(("agentrouter", AGENTROUTER_URL, AGENTROUTER_KEY, [model]))
        if GEMINI_KEY:
            targets.append(("gemini", GEMINI_URL, GEMINI_KEY, [model]))
        if OPENROUTER_KEY:
            targets.append(("openrouter", OPENROUTER_URL, OPENROUTER_KEY, [model]))
        if META_KEY:
            targets.append(("meta", META_URL, META_KEY, [model]))
        if not ALLOW_PROVIDER_FALLBACK:
            targets = targets[:1]
        for label, base, key, models in targets:
            if label == "gemini":
                out, _err = _gemini_call(key, models, messages, temperature, max_tokens)
            else:
                out, _err = _call(base, key, models, messages, temperature, max_tokens)
            if out is not None:
                return out
        return None
    targets = _targets()
    if not targets:
        return None
    last_err = None
    for label, base, key, models in targets:
        if label == "gemini":
            out, err = _gemini_call(key, models, messages, temperature, max_tokens)
        else:
            out, err = _call(base, key, models, messages, temperature, max_tokens)
        if out is not None:
            return out
        if err:
            last_err = f"[{label}] {err}"
    if last_err:
        print("[ark] LLM unavailable; using offline generation:", last_err)
    return None


def _gemini_call(key, models, messages, temperature, max_tokens):
    """Gemini native REST API (generateContent). Returns (content, error)."""
    base = GEMINI_URL
    headers = {"Content-Type": "application/json"}
    system_parts = []
    contents = []
    for m in messages:
        if m.get("role") == "system":
            system_parts.append(m["content"])
        else:
            role = "model" if m.get("role") == "assistant" else "user"
            contents.append({"role": role, "parts": [{"text": m["content"]}]})
    last_err = None
    for m in models:
        body = {
            "contents": contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        if system_parts:
            body["system_instruction"] = {"parts": [{"text": "\n".join(system_parts)}]}
        try:
            r = requests.post(
                f"{base}/{m}:generateContent",
                headers=headers,
                params={"key": key},
                json=body,
                timeout=(REQUEST_CONNECT_TIMEOUT, REQUEST_READ_TIMEOUT),
            )
            if r.status_code == 200:
                j = r.json()
                cand = (j.get("candidates") or [{}])[0]
                text = "".join(
                    p.get("text", "")
                    for p in (cand.get("content", {}).get("parts") or [])
                ).strip()
                reason = cand.get("finishReason")
                # Schema docs can be long: if the output was cut off, grow the
                # budget and retry instead of returning a truncated payload.
                if reason == "MAX_TOKENS" and max_tokens < 8192:
                    budget = min(8192, max_tokens * 2)
                    last_err = f"{m}: MAX_TOKENS (growing to {budget})"
                    max_tokens = budget
                    time.sleep(0.4)
                    continue
                if text:
                    return text, None
                last_err = f"{m}: empty finish={reason}"
            else:
                last_err = f"{m}: HTTP {r.status_code} {r.text[:200]}"
        except Exception as e:  # noqa
            last_err = f"{m}: {e}"
        time.sleep(0.4)
    return None, last_err


def _call(base, key, models, messages, temperature, max_tokens):
    """Returns (content_or_None, error_string_or_None)."""
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if "openrouter" in base:
        headers["HTTP-Referer"] = "https://ark.local"
        headers["X-Title"] = "ARK"
    last_err = None
    for m in models:
        body = {
            "model": m,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        for attempt in range(2):
            try:
                r = requests.post(
                    base,
                    headers=headers,
                    json=body,
                    timeout=(REQUEST_CONNECT_TIMEOUT, REQUEST_READ_TIMEOUT),
                )
                if r.status_code == 200:
                    content = r.json()["choices"][0]["message"].get("content", "")
                    if isinstance(content, list):
                        content = "".join(
                            item.get("text", "") for item in content if isinstance(item, dict)
                        )
                    if isinstance(content, str) and content.strip():
                        return content.strip(), None
                    last_err = f"{m}: empty response"
                    break
                error_text = r.text[:500]
                lower_error = error_text.lower()
                if r.status_code == 400 and attempt == 0:
                    changed = False
                    if "max_tokens" in lower_error and "max_completion_tokens" not in body:
                        body["max_completion_tokens"] = body.pop("max_tokens")
                        changed = True
                    if "temperature" in lower_error and "unsupported" in lower_error:
                        body.pop("temperature", None)
                        changed = True
                    if changed:
                        continue
                last_err = f"{m}: HTTP {r.status_code} {error_text[:200]}"
            except Exception as e:  # noqa
                last_err = f"{m}: {e}"
            break
        time.sleep(0.4)
    return None, last_err


def _clean(text):
    if not text:
        return text
    text = re.sub(r"^```(json|python)?\s*", "", text.strip())
    text = re.sub(r"\s*```$", "", text)
    text = re.sub(r'^"|"$', "", text.strip())
    return text.strip()


def _extract_json(text):
    """Pull the first balanced JSON object or array out of arbitrary text.

    Models love to wrap pure JSON in fences and paragraphs; a greedy regex
    breaks on prose after the payload, so find the first '{' or '[' and walk
    to its matching bracket while respecting strings and escapes.
    """
    if not text:
        return None
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        if start == -1:
            continue
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == opener:
                depth += 1
            elif ch == closer:
                depth -= 1
                if depth == 0:
                    candidate = text[start : i + 1]
                    try:
                        return json.loads(candidate)
                    except Exception:
                        break
        if depth != 0:
            last = text.rfind(closer)
            if last > start:
                try:
                    return json.loads(text[start : last + 1])
                except Exception:
                    pass
    return None


def complete(system, user, temperature=0.9, model=None):
    """Try LLM; return (llm_or_none, text) where text is always available."""
    text = _chat(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=temperature,
        model=model,
    )
    if text:
        return text, True
    return None, False


def complete_json(system, user, temperature=0.6, max_tokens=3000, model=None):
    """Ask for a JSON document; return parsed dict/list or None.

    Pass model='...' to target a specific model id (e.g. a Muse Spark model)
    instead of the default provider's model.
    """
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    raw = _chat(messages, temperature=temperature, max_tokens=max_tokens, model=model)
    if not raw:
        return None
    raw = _clean(raw)
    parsed = _extract_json(raw)
    if parsed is not None:
        return parsed
    try:
        return json.loads(raw)
    except Exception:
        return None


def muse_model():
    """The Muse Spark model id when the Meta provider is configured, else None."""
    return META_MODELS[0] if META_KEY else None


def llm_available():
    return llm_status()["configured"]
