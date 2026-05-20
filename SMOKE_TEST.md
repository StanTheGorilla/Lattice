# Lattice — Cold-start Smoke Test

Run this end-to-end after a fresh checkout to verify the full v1 journey.
Mark each step as it passes; investigate any failure before moving on.

Pre-reqs:
- `.env` filled per `.env.example`
- `uv` installed, Node 20+ installed
- Discord bot invited to DM with you (optional but recommended)
- `backend/lattice/integrations/credentials.json` present (Google Cloud OAuth client)

## 0. Install + migrate

- [ ] `cd backend && uv sync` — exits 0
- [ ] `cd ../bot && uv sync` — exits 0
- [ ] `cd ../frontend && npm install` — exits 0
- [ ] `cd ../backend && uv run alembic upgrade head` — prints `INFO  [alembic.runtime.migration] Running upgrade …`

## 1. Process boot

- [ ] `start.bat` opens three terminals
- [ ] Backend terminal shows `Uvicorn running on http://127.0.0.1:8000`
- [ ] Frontend terminal shows `Local: http://localhost:5173/`
- [ ] Bot terminal shows either `logged in as <name>` (if token set) or
      `DISCORD_BOT_TOKEN not set, nothing to do` (clean exit)
- [ ] `logs/backend.log` and `logs/bot.log` exist and receive INFO entries

## 2. Health + auth

- [ ] `curl http://localhost:8000/api/health` → `{"status":"ok"}`
- [ ] `curl http://localhost:8000/api/auth/status` → `authenticated:true, permissive:true`
      (with empty `WEB_UI_PASSWORD`)
- [ ] Open `http://localhost:5173/login`, submit any password → redirected to `/`
- [ ] Sidebar wordmark reads **LATTICE** (no SVG mark, no diamond, no favicon graphic)

## 3. Garmin sync (Phase 2B)

- [ ] `POST /api/sync/garmin?days=2` → `metrics_written > 0`, `errors=[]`
- [ ] `GET /api/metrics/latest?names=sleep_score,hrv_overnight_avg,resting_hr` returns values
- [ ] Re-run the sync → idempotent (counts unchanged for the same window)

## 4. Calendar sync (Phase 2C)

- [ ] `POST /api/calendar/sync` → browser opens once on cold start, then
      `{"refreshed": N}`
- [ ] `GET /api/calendar/events?from=<today>&to=<today+1d>` returns events
- [ ] `POST /api/calendar/events` creates an event in Google + cache
- [ ] `DELETE /api/calendar/events/:id` removes it from both

## 5. Entries + habits (Phase 2D)

- [ ] On `/log`, create one entry per type that you care about (food, drink,
      focus, mood, energy, symptom, note, workout_manual). PATCH + DELETE work.
- [ ] On `/habits`, create a habit, check it off, observe streak update.
- [ ] `GET /api/habits/:id/checkins?from=...&to=...` returns the checkin.

## 6. Deterministic functions (Phase 2E)

- [ ] `/` Today page renders F1 readiness ring, F3 training, F4 sleep, F5
      caffeine, F2 work windows.
- [ ] Pick each intent on the advisor card (learn / creative / train / rest /
      meeting / physical_task); F9a returns a recommendation with reasons.
- [ ] `GET /api/advice?intent=dance` → 422 `unsupported_intent`.

## 7. Chat agent (Phase 2G)

If Discord bot is configured:
- [ ] DM the bot "what was my resting heart rate" → answers with the latest value
- [ ] DM "log a coffee" → bot confirms, `/log` page shows a new drink entry
      with `source=discord`
- [ ] DM "create a 30-minute focus block tomorrow at 10am" → bot confirms,
      event appears in Google Calendar + `/api/calendar/events`
- [ ] DM "second opinion: should I train hard today?" → reply has both
      `Algorithm recommends:` and `My take:` blocks (F9b safeguard)

If Discord not configured, exercise the same flows via:
- [ ] `POST /api/chat` `{ "session_id": "smoke", "message": "..." }`

## 8. Weekly report (Phase 2I)

- [ ] Navigate to `/report`; if no report exists, "generate now" button shows
- [ ] Click generate → loads with model badge (`deepseek-chat` or
      `deterministic-only`), Stage B prose, daily aggregate table, correlations
- [ ] Past-week picker (`<select>`) lists this week and any prior weeks; selecting
      a prior week loads that report
- [ ] `POST /api/reports/weekly/generate` again → idempotent overwrite

## 9. Scheduler (prod-mode)

Set `LATTICE_DISABLE_SCHEDULER=false`, restart backend without `--reload`:
- [ ] `logs/backend.log` shows
      `scheduler started (tz=...) — jobs: garmin_sync, readiness_compute, weekly_report, conversation_prune, calendar_cache_prune`
- [ ] Wait for the next hourly tick; confirm garmin job entry in log
- [ ] Bot log shows `briefings scheduled (morning 07:30, evening 21:00)`

## 10. Error handling

- [ ] Open `http://localhost:5173/this-route-does-not-exist` → custom error
      page renders with 404 + "back to today"
- [ ] Stop the backend; reload `/`; auth gate redirects to `/login` cleanly
      (no console errors)

## Pass criteria

All checkboxes ticked. Logs (`logs/backend.log`, `logs/bot.log`) contain no
`ERROR`-level lines that weren't intentional.
