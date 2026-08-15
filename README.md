# ARK

Don't read history — scroll it.

ARK is a living temporal simulation: real people and organizations post
in-character on an exact date, and the feed unlocks one day at a time on a
real clock. It runs as a local FastAPI app with a SQLite store, an offline
generation engine, and an optional LLM layer (Gemini / OpenRouter / AgentRouter)
plus an Exa-powered research desk.

## Run

```
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

Open http://localhost:8000. Configure providers in `.env` (see `.env` for the
key names: `OPENROUTER_API_KEY`, `AGENTROUTER_API_KEY`, `META_API_KEY`,
`GEMINI_API_KEY`, and `EXA_API_KEY` for live research grounding).

## Test

```
python -m unittest discover -s tests -p "test_*.py"
```
