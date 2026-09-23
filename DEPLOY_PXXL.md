# Deploying & migrating ARK to PXXL

## 1. What PXXL is (research notes)

**PXXL (pxxl.app)** is a Nigerian-built, Africa-first cloud deployment platform —
a Render/Vercel/Netlify alternative aimed at African developers. How it works:

- **Git push → live URL.** Connect a GitHub (or GitLab) repo; every push triggers
  a fresh build and zero-downtime deploy to `yourproject.pxxl.pro` with automatic HTTPS.
- **Framework auto-detection.** Python is detected from `requirements.txt`
  (also `pyproject.toml`, `Pipfile`, `setup.py`); pip/uv/Poetry/Pipenv supported.
  FastAPI is a first-class citizen, deployed as a **Web Service**.
- **Build plan review.** Before the first deploy you review install / build /
  start commands, runtime version, port, and env vars — then submit.
- **Always-on services.** No cold starts or sleeping; crashed apps auto-restart.
  (Matters for ARK: the background generation worker lives in-process.)
- **Persistent volumes.** Compute & Scaling → Add Volume (nickname + mount path)
  keeps data across redeploys and restarts.
- **Managed databases** (Postgres/MySQL/Mongo), **custom domains** with SSL,
  **live logs**, **terminal** (shell into the running container), **cron jobs**
  (HTTP endpoints on a schedule), plus CLI (`@pxxlapp/pxxl`), REST API, and SDKs.
- **Pricing:** free tier exists; Free Plus $5/mo (100 projects, 1.5 GB RAM,
  1 vCPU, 5k build minutes). Docs: <https://docs.pxxl.app>, index:
  <https://docs.pxxl.app/llms.txt>.

### Why ARK fits as-is

| Requirement | ARK status |
|---|---|
| Python detected | `requirements.txt` at repo root ✓ |
| Long-running start command | `uvicorn main:app --host 0.0.0.0 --port $PORT` ✓ (`Procfile`) |
| Listens on configured port | reads `$PORT`, falls back to 8000 ✓ |
| Health check | `GET /api/health` (returns LLM status too) ✓ |
| No build step | pure Python + static files; build command can be empty ✓ |
| Python version | `.python-version` pins 3.12 (needs ≥3.10 for `X \| None` syntax); confirm under runtime version at review |
| State that must survive redeploys | `ark.db` + `static/uploads` — both volume-backed via `ARK_DB_PATH` / `ARK_UPLOADS_DIR` (see §3) |

## 2. Deploy steps (dashboard)

1. **Create project → connect repo.** In PXXL: new project, link GitHub, pick the
   Ark2 repo and the `main` branch.
2. **Review the build plan.** Override if detection guesses wrong:
   - Install command: `pip install -r requirements.txt`
   - Build command: *(empty — nothing to compile)*
   - Start command: `uvicorn main:app --host 0.0.0.0 --port $PORT`
   - Port: the `$PORT` variable PXXL injects (do **not** hardcode 8000)
   - Target: **Web Service** (not Static App)
3. **Add secrets first** (Project → Secrets — same values as Railway Variables):

   | Variable | Required | Notes |
   |---|---|---|
   | `GEMINI_API_KEY` (and/or `META_API_KEY`, `AGENTROUTER_API_KEY`, `OPENROUTER_API_KEY`) | one of them, yes | Without any LLM provider the app runs but every generation endpoint returns **503** with setup instructions (by design — no synthetic content) |
   | `EXA_API_KEY` | no | Enables live web grounding for research + resource harvest |
   | `DATABASE_URL` | yes (prod) | **Neon Postgres** — paste the *pooled* connection string from the Neon dashboard (`...-pooler....neon.tech/...?sslmode=require`). When set, ARK uses Postgres and ignores `ARK_DB_PATH` entirely |
   | `ARK_DB_PATH` | only without `DATABASE_URL` | `/data/ark.db` — must match the volume mount. Not needed when on Neon |
   | `ARK_UPLOADS_DIR` | yes (prod) | `/data/uploads` — profile photos, else redeploys wipe avatars (still needs the volume even on Neon) |
   | `ARK_ALLOWED_ORIGINS` | yes | `https://<your-project>.pxxl.pro` (comma-separated with localhost for dev) |
   | `ARK_PACE_MINUTES`, `ARK_GEN_INTERVAL` | no | Pacing + worker tick; defaults fine |
   | `YOUTUBE_API_KEY`, `SMITHSONIAN_API_KEY`, `PEXELS_API_KEY` | no | Extra resource sources; all degrade gracefully |

   **Set up Neon first:** Neon dashboard → new project → copy the pooled
   connection string → paste as `DATABASE_URL`. The app creates the full
   schema on first boot (`init_db`), so the database can start empty.

4. **Add the volume.** Compute & Scaling → **Add Volume**, mount path `/data`.
   On Neon this holds uploads (`ARK_UPLOADS_DIR`); without Neon it holds the
   SQLite file too (`ARK_DB_PATH`).
5. **Deploy.** Submit → watch build logs → health check hits the port →
   live at `https://<your-project>.pxxl.pro`.
6. **Verify:** open `/api/health` (expect `{"ok": true, "llm": {...}}`),
   load the landing page, sign in, create a test world. The create screen
   shows a banner if no LLM provider is configured.

### CLI alternative

```bash
npm install -g @pxxlapp/pxxl
pxxl login --api-key pxxl_...
pxxl deploy  # then review the detected build plan when prompted
```

## 3. Data migration (Railway → PXXL)

Three options, simplest first:

### Option A — fresh start (simplest)
Do nothing. On first boot `_startup` re-seeds the builtin WW2 archive and
users re-register; custom worlds are rebuilt from prompts. Avatars re-uploaded.
Acceptable if Railway history doesn't matter.

### Option B — carry SQLite + avatars over (no Neon)
SQLite is just files, so migration is a file copy. Only use this if you are
*not* moving to Neon (with Neon, use Option C instead).

### Option B — carry the database + avatars over
1. **Export from Railway.** From a shell with the Railway CLI (volume attached
   at `/data`):
   ```bash
   railway run -- sqlite3 /data/ark.db ".dump" > ark-backup.sql
   # avatars:
   railway run -- tar -czf uploads-backup.tgz -C /data/uploads .
   ```
   (If `sqlite3` isn't on the Railway image, `railway ssh` + `python -c`
   with `iterdump()` works too — `ark/db.py` is plain sqlite3.)
2. **Create the PXXL volume first** (§2 step 4), deploy once so `/data` exists.
3. **Restore via the PXXL terminal** (project workspace → Terminal):
   ```bash
   sqlite3 /data/ark.db < ark-backup.sql   # paste/upload the dump first
   mkdir -p /data/uploads && tar -xzf uploads-backup.tgz -C /data/uploads
   ```
   Upload the dump through the dashboard/CLI file flow, or paste it in chunks.
   Then **restart** the service so the running process reopens the fresh DB.
4. **Sanity check:** `/api/health`, log in as an existing user, open an old
   world — posts, follows, and avatars should all be there.

> ⚠️ Never run two writers against one SQLite file. Migrate with the Railway
> service **stopped or scaled to zero** to avoid a split-brain DB.

### Option C — migrate SQLite into Neon Postgres (recommended)
ARK speaks Postgres natively when `DATABASE_URL` is set (same queries, same
ids — the adapter translates the dialect). Migrate with the bundled script:

1. **Stop the Railway service** (or scale to zero) so nothing writes mid-copy.
2. **Download the SQLite file** from the Railway volume to your machine:
   ```bash
   railway run -- cat /data/ark.db > ark-backup.db
   # avatars still travel as files:
   railway run -- tar -czf uploads-backup.tgz -C /data/uploads .
   ```
3. **Run the migration** (needs the driver once: `pip install 'psycopg[binary]'`):
   ```bash
   ARK_SQLITE_PATH=./ark-backup.db \
   DATABASE_URL='postgresql://user:pass@ep-xxx-pooler...neon.tech/ark?sslmode=require' \
   python scripts/migrate_sqlite_to_pg.py
   ```
   The script creates the schema, copies every table with ids intact
   (threads, votes, follows keep pointing at the right rows), resets the
   id sequences, and prints a per-table `sqlite=N pg=N OK` verification.
4. **Restore avatars** via the PXXL terminal (uploads stay on the volume):
   ```bash
   mkdir -p /data/uploads && tar -xzf uploads-backup.tgz -C /data/uploads
   ```
5. **Set `DATABASE_URL` in PXXL Secrets and redeploy.** Sanity check:
   `/api/health`, log in as an existing user, open an old world.

## 4. Cutover checklist

- [ ] PXXL deploy green + `/api/health` OK + test world generates
- [ ] Neon: `DATABASE_URL` (pooled string) in Secrets; schema auto-created on boot
- [ ] Volume mounted at `/data`; `ARK_UPLOADS_DIR=/data/uploads`
      (`ARK_DB_PATH` only needed if you skip Neon)
- [ ] Data migrated (C for Neon, B for SQLite-on-volume) or fresh start accepted (A)
- [ ] Custom domain routed (Domains tab; update DNS A/CNAME as shown), SSL active
- [ ] `ARK_ALLOWED_ORIGINS` includes the PXXL/custom domain
- [ ] Railway service kept (stopped, not deleted) for one week as rollback
- [ ] Delete Railway deployment only after the week passes with no issues

## 5. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `sqlite3.OperationalError: unable to open database file` at `db.init_db()` | Gone on Neon (no SQLite file at all). On SQLite: `ARK_DB_PATH` points somewhere that doesn't exist — **add the volume** (mount `/data`, keep `ARK_DB_PATH=/data/ark.db`) or unset `ARK_DB_PATH` to use the bundled `ark.db` (ephemeral). The app creates the parent dir on boot but cannot invent the volume |
| `DATABASE_URL is set but psycopg is not installed` at boot | The image predates the `psycopg` requirement — redeploy so `pip install -r requirements.txt` picks it up |
| Neon connection errors / timeouts | Use the **pooled** connection string (`...-pooler...`), keep `?sslmode=require`, and confirm the secret has no trailing spaces/newlines; Neon projects auto-suspend on the free tier — first request after idle takes a few seconds |
| Build fails on install | Package manager mismatch — force pip + `pip install -r requirements.txt`; check `requirements.txt` is at repo root |
| Start command exits / port errors | Must listen on `$PORT` exactly: `uvicorn main:app --host 0.0.0.0 --port $PORT`. `127.0.0.1` or hardcoded `8000` fails the health check |
| 503 "No LLM provider is configured" | By design — add at least one LLM key in Secrets and redeploy |
| Empty world / no posts after create | Check Live Logs for `background generation paused: no LLM provider configured` |
| DB resets on every deploy | Volume missing or wrong mount path; confirm `ARK_DB_PATH=/data/ark.db` matches the mount |
| Avatars 404 after redeploy | `ARK_UPLOADS_DIR` not on the volume (defaults to `static/uploads`, ephemeral) |
| Python version errors | Set runtime version at build-plan review (needs ≥3.10); `.python-version` pins 3.12 |
| Slow first build | Expected — pip resolves ~10 packages; later builds use the build cache |

## 6. What was changed in-repo for PXXL

- `main.py`: `ARK_UPLOADS_DIR` env (default `static/uploads`); avatars + static mount use it;
  pool closed on shutdown
- `ark/db.py`: dual backend — SQLite locally, **Neon Postgres when `DATABASE_URL`
  is set** (`?`→`%s`, `LIKE`→`ILIKE`, auto `RETURNING id`, dual-access rows,
  pooled connections). No SQL changes needed anywhere else
- `ark/auth.py`: session-expiry cutoff computed in Python (was SQLite-only `datetime()`)
- `scripts/migrate_sqlite_to_pg.py`: row-for-row copy preserving ids + sequence reset + verification
- `requirements.txt`: `psycopg[binary,pool]`
- `.env.example`: `DATABASE_URL` + PXXL volume/env notes
- `.python-version`: pins 3.12
- This file: research + migration runbook
- Unchanged and PXXL-ready: `Procfile` start command shape, `/api/health`,
  always-on background worker, `railway.json` (kept until cutover completes)
