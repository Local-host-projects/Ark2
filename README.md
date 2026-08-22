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

Open http://localhost:8000. Copy `.env.example` to `.env` and fill provider keys
(`AGENTROUTER_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`, `META_API_KEY`,
`EXA_API_KEY` for live research). All env vars are documented in `.env.example`
and `ark/llm.py:17`, `ark/core.py:1809`, `main.py:44`.

## Deploy — Railway

No extra config needed beyond env vars. The repo now includes `Procfile:1`,
`railway.json:1`, `nixpacks.toml:1`.

1. Create project from GitHub, set **Variables**:
   `AGENTROUTER_API_KEY` (or `GEMINI_API_KEY` / `OPENROUTER_API_KEY` / `META_API_KEY`),
   `EXA_API_KEY` (optional), `ARK_VOICE_MODEL=gemini-3.5-flash-lite`.
   Set `ARK_ALLOWED_ORIGINS=https://<your-app>.up.railway.app,http://localhost:8000`.
2. **Persistence**: Railway's filesystem is ephemeral. Add a Volume mounted at
   `/data` and set `ARK_DB_PATH=/data/ark.db` (`ark/db.py:7`). Without it,
   `ark.db` resets on each deploy.
3. Deploy — healthcheck is `GET /api/health` (`main.py:136`). `PORT` is injected
   by Railway; `Procfile` and `nixpacks.toml` already use `$PORT`.
4. No `Dockerfile` needed; Nixpacks builds from `requirements.txt:1`.

## Test

```
python -m unittest discover -s tests -p "test_*.py"
```
