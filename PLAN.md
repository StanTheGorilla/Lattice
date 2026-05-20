# Lattice — Build Plan

Strict phase order. Each phase verified before next begins.

## Phase 2A — Scaffolding
Status: done — awaiting verification
- [x] Directory structure per SPEC.md Section 3
- [x] `pyproject.toml` for backend (uv)
- [x] `pyproject.toml` for bot (uv)
- [x] SvelteKit project init in `frontend/`
- [x] `.env.example`, `.gitignore`, `README.md` stub
- [x] Alembic init + first migration creating all tables from SPEC.md Section 4 (+ `weekly_reports`)
- [x] FastAPI app with `/api/health` endpoint returning `200 {"status": "ok"}`
- [x] SvelteKit project renders blank login route at `/login`
- [x] `start.bat` launches backend, frontend, bot in three separate terminal windows
- [x] `CLAUDE.md` created with conventions
- [x] `PLAN.md` created (this file)
- [x] SPEC.md updated: `weekly_reports` table (§4.6), no-logo convention (§13), Tweaks panel (§11 OUT)

Verify:
- [x] `curl http://localhost:8000/api/health` returns `200 {"status":"ok"}`
- [x] `http://localhost:5173/login` renders without SSR errors, fonts + tokens load, no console errors expected client-side (the form's submit is a placeholder that surfaces "Auth endpoint not yet implemented (Phase 2F)" — by design)
- [x] `npm run check` clean (0 errors, 0 warnings, 275 files)
- [x] `uv run python -m lattice_bot.main` exits cleanly with phase 2A stub message

## Phase 2B — Garmin integration
Status: done — awaiting verification
- [x] `integrations/garmin.py` wrapping garminconnect with auth caching (`~/.garminconnect/`)
- [x] Metric pulls per SPEC.md Section 8.1 — high-confidence subset (sleep, HRV, stress, body battery, RHR, training status, steps, respiration, spo2)
- [x] `sync/garmin_sync.py` idempotent UPSERT into `metrics` (pure extractors + orchestrator)
- [x] APScheduler hourly job (`sync/scheduler.py`, gated by LATTICE_DISABLE_SCHEDULER)
- [x] API: `GET /api/metrics`, `GET /api/metrics/latest`, `GET /api/metrics/baseline`, `POST /api/sync/garmin`
- [x] Pydantic schemas in `schemas/metrics.py`
- [x] `auth.py` — require_auth (X-Bot-Token; permissive when no secret set)
- [x] Unit tests — 16 passing tests on the extract_* pure functions

Verify (live):
- [x] `POST /api/sync/garmin?days=2` returned `metrics_written=15`, `errors=[]`
- [x] `GET /api/metrics/latest?names=sleep_score,hrv_overnight_avg,resting_hr` returned sleep_score=80, hrv_overnight_avg=58, resting_hr=55 (all from 2026-05-13 last night)
- [x] Idempotency: 3 sequential syncs, count stayed at 15; `sleep_score` has exactly 1 row

### Decisions log (2B)
- **2B-1** (resolved): UPSERT done via `sqlite_insert(Metric.__table__)` rather than the ORM class — `metadata` is reserved on SQLAlchemy's `DeclarativeBase`.
- **2B-2** (resolved): `MetricOut.extra_metadata` field uses `serialization_alias="metadata"` (not `alias=`) so `model_validate` reads the right ORM attribute while JSON output matches SPEC.
- **2B-3** (resolved): `require_auth` treats empty `BOT_SHARED_SECRET=""` as "no secret set" (not just `None`), since pydantic-settings loads blank lines as empty strings.

### Decisions log (2B) — addendum
- **2B-4** (resolved): `body_battery_start` defined as `max(values)` in the day (morning post-recharge peak), not `values[0]`. The current Garmin payload's first reading is at local midnight, which is often a low when the user is still up. Matches F1's expected semantics ("Body Battery start" weight 10% in readiness scoring) and the UI mockup (`BB.start = 86`). Documented in `extract_body_battery` docstring.

### Known follow-ups (non-blocking)
- `active_minutes` and `calories_active` metrics from SPEC §4.2 not yet pulled — would require an activities loop. Not required by F1–F9; can add in 2J.

## Phase 2C — Calendar integration
Status: done — awaiting live verification (requires Google Cloud OAuth setup)

- [x] `integrations/google_calendar.py` — OAuth client wrapping `google-api-python-client`
  - Lazy auth via `InstalledAppFlow.run_local_server(port=0)` on first call
  - Token cache at `%USERPROFILE%/.lattice/google_token.json`
  - Typed errors: `GoogleAuthMissing`, `GoogleAuthError`, `GoogleUnavailable`
  - Methods: `list_events`, `create_event`, `patch_event`, `delete_event`
- [x] `sync/calendar_sync.py` — pure `event_to_row` + `row_to_event_body` transforms
  - `sync_window` — UPSERT into `calendar_cache` keyed on `google_event_id`
  - `cached_events_or_refresh` — 5-min TTL per SPEC §4.3
  - `free_busy` — derives busy intervals (timed events only; all-day excluded)
  - `create_event_remote` / `patch_event_remote` / `delete_event_remote` — write-through cache
  - `prune_old_events` — drops events ending >1 day ago (for SPEC §9 `calendar_cache_prune`)
- [x] `schemas/calendar.py` — `CalendarEvent`, `CalendarEventCreate`, `CalendarEventPatch`, `BusyInterval`, `CalendarSyncResult`
- [x] `api/calendar.py` — 6 endpoints per SPEC §5.4 (GET events/freebusy, POST/PATCH/DELETE events, POST sync)
  - Auth required (same `require_auth` dep)
  - Google errors mapped: `GoogleAuthMissing` / `GoogleUnavailable` → 503, `GoogleAuthError` → 401
- [x] Wired into `main.py`
- [x] Unit tests — 9 passing tests covering `event_to_row` (timed, all-day, cancelled, missing fields) and `row_to_event_body`

Verify (live — blocked on Google Cloud setup):
- [ ] User completes Google Cloud Console setup per SPEC §8.2:
  1. New project "Lattice" → enable Calendar API
  2. OAuth consent screen (External, own email as test user)
  3. Credentials → OAuth Client ID → Desktop app → download
  4. Save as `backend/lattice/integrations/credentials.json`
- [ ] `POST /api/calendar/sync` triggers browser consent, writes token to `%USERPROFILE%/.lattice/google_token.json`, returns `{ refreshed: N }`
- [ ] `GET /api/calendar/events?from=...&to=...` returns cached events; second call within 5 min skips refetch
- [ ] `POST /api/calendar/events` creates event in Google + cache
- [ ] `PATCH /api/calendar/events/:id` updates event in Google + cache
- [ ] `DELETE /api/calendar/events/:id` removes from Google + cache (204)
- [ ] `GET /api/calendar/freebusy` returns busy intervals (all-day events excluded)

### Decisions log (2C)
- **2C-1** (resolved): OAuth bootstrap is **on-demand at first API call**. First call to any calendar endpoint that needs Google triggers `run_local_server(port=0)`, which opens the browser. Alternative options (dedicated bootstrap endpoint, CLI script) rejected as extra surface area for a one-shot operation.
- **2C-2** (resolved): Writes (POST/PATCH/DELETE events) **push to Google immediately** and write-through the local cache. Matches SPEC §5.4 ("read + write") and §11 IN list. Alternative (local queue + lazy push) deferred — not in v1 scope.
- **2C-3** (resolved): `:id` path param for PATCH/DELETE is the `google_event_id` (not the local `calendar_cache.id`). Single canonical identifier for Discord bot, web UI, and Google round-trips.
- **2C-4** (resolved): `free_busy` excludes all-day events. SPEC §6 F2 subtracts busy intervals from the day; treating a vacation all-day event as "busy" would erase entire days and prevent F2 from finding any work window. All-day events still listed via `GET /events` — just not counted as busy.
- **2C-5** (resolved): `credentials.json` is the source of OAuth client config (per SPEC §8.2). The `.env` entries `GOOGLE_OAUTH_CLIENT_ID` / `_SECRET` are kept for completeness but not read by the integration — `InstalledAppFlow.from_client_secrets_file` reads the JSON directly.

### Known follow-ups (non-blocking)
- APScheduler `calendar_cache_prune` job (SPEC §9, hourly) — function exists (`prune_old_events`); not yet wired into scheduler. Will land in 2J alongside the other periodic jobs.
- `POST /sync/calendar` is at `/api/calendar/sync` per SPEC §5.4. The duplicate path mentioned in SPEC §5.8 (`POST /sync/calendar`) was not added — adding it would create two endpoints for the same operation. Flag for confirmation before 2J.

## Phase 2D — Entries + habits
Status: done — live verified

- [x] `schemas/entries.py` — Pydantic v2 discriminated union for the 8 types in SPEC §4.7 (food, drink, mood, energy, focus, symptom, note, workout_manual). `validate_data_for_type(type, dict)` validates the per-type schema at the API boundary.
- [x] `schemas/habits.py` — `HabitDefinitionCreate/Patch/Out`, `HabitCheckinCreate/Out`, `HabitCheckinListResponse`.
- [x] `api/entries.py` — `GET /entries` (filter type/from/to/limit/offset), `POST`, `PATCH`, `DELETE` per SPEC §5.2.
- [x] `api/habits.py` — `POST /habits`, `GET /habits` (filter active), `PATCH /habits/:id`, `POST /habits/:id/checkins` (idempotent UPSERT on `(habit_id, date)`), `GET /habits/:id/checkins`, `DELETE /habits/:id/checkins/:date`.
- [x] Wired into `main.py` (entries, habits routers).
- [x] Unit tests — 16 new tests covering schema round-trip per type, validation rejection, and `EntryOut.from_row` JSON parsing.
- [x] Live e2e — POST/GET/PATCH/DELETE for entries (food/drink/focus + invalid mood rejection); POST/GET/PATCH for habit definitions (incl. duplicate name 409); POST/GET/DELETE for checkins (incl. idempotent UPSERT). All status codes match expectations.

### Decisions log (2D)
- **2D-1** (resolved): Per-type validation uses a **Pydantic v2 discriminated union** on `type`. Each variant validates its own `data` schema. Alternative (loose `dict[str, Any]`) rejected — would push validation downstream into scoring functions and risk persisting malformed payloads.
- **2D-2** (resolved): Habit endpoint shape mirrors entries CRUD style + nested `/checkins` resource. SPEC §5.x does not enumerate habit endpoints; this is the simplest shape that covers SPEC §11's "define + check-in" requirement.
- **2D-3** (resolved): No hard DELETE on habit definitions. Soft-delete via `PATCH active=false` instead. Hard delete would cascade to historical checkins (FK `ondelete=CASCADE`) and erase weeks of streak data. F8 (adherence) can be computed against inactive habits.
- **2D-4** (resolved): `POST /habits/:id/checkins` is an idempotent UPSERT on `(habit_id, date)`. Re-posting the same date overwrites `completed`/`note` instead of 409-ing. Matches the natural mental model "mark today done" being safely repeatable.
- **2D-5** (resolved): `EntryCreate.timestamp` defaults to `now` when omitted; `logged_at` is always server-set. `source` defaults to `"web"` (bot must pass `"discord"` explicitly).
- **2D-6** (resolved): `EntryPatch` cannot change `type`. Changing the type would invalidate the existing `data` schema; require a new entry instead. `data` patches re-validate against the row's existing type.

## Phase 2E — Deterministic functions F1–F5, F8, F9a
Status: done — live verified

### Functions
- [x] `functions/baselines.py` — shared `compute_baseline(name, days, before=, tz=)`, `latest_metric`, `metric_on_date`, `metric_for_day_range`, `clamp`, `parse_iso`
- [x] `functions/readiness.py` — F1 weighted z-score (0.40·HRV + 0.30·sleep + 0.15·RHR + 0.10·BB + 0.05·stress). Renormalizes weights on missing components. Provisional flag when HRV or RHR baseline < 7 days.
- [x] `functions/training_rec.py` — F3 rule cascade (rest/easy/moderate/hard). Caps one level when today's meeting hours > 4. Reads training_load_acute/chronic + last manual high-intensity workout.
- [x] `functions/work_windows.py` — F2 calendar-gap scoring (40% tod match × 30% readiness × 20% BB curve × 10% meal/workout spacing). Peak focus hour weighted-mean from 30-day focus entries.
- [x] `functions/sleep_window.py` — F4 bedtime = first_event_tomorrow − 30min − optimal_sleep_duration. Optimal duration = median sleep on days where next-day readiness ≥ 65 (last 60 days; 7.5h fallback). Flags late caffeine + late high-intensity workouts.
- [x] `functions/caffeine.py` — F5 half-life 5h decay, residual ≤ 50mg at bedtime, computes `last_call_minutes`.
- [x] `functions/habits_adherence.py` — F8 current/longest streak, week %, period %. Active habits only.
- [x] `functions/advisor.py` — F9a per-intent rule tables (learn/creative/train/rest/meeting/physical_task). NO LLM. Calls F1/F2/F3/F4 internally.

### Schemas + API
- [x] `schemas/functions.py` — output models for all 7 endpoints
- [x] `api/functions.py` — 7 endpoints per SPEC §5.5
- [x] Wired into `main.py`

### Tests — 32 new tests (total: 75 passing)
- [x] F1: full-data score, missing-data renormalization, provisional flag, no-data zero, peak/depleted categories
- [x] F3: rest/easy/moderate/hard rule cascade, meeting cap, no-chronic-baseline path
- [x] F5: residual decay, no-cups, too-much-caffeine, non-coffee ignored
- [x] F8: current streak (broken + intact), longest streak, week % cap, inactive habit exclusion
- [x] F9a: every intent's branches — rest_recommended, no_window_available, window_strong/moderate/weak, rest_day, train_*, sleep_window, meeting_slot, physical_slot, unsupported_intent

### Live e2e (against real DB seeded by 2B Garmin sync + 2D entries)
- ✅ F1 readiness for 2026-05-13 → score=77 "solid", provisional (one day of Garmin baseline so far), missing HRV/RHR/stress correctly flagged
- ✅ F4 sleep_window → 00:30 bedtime, 08:00 wake (no event tomorrow → default), flagged the 16:23 coffee logged in 2D
- ✅ F5 caffeine_status → found the 1 coffee in DB, residual 25.99mg at bedtime, safe_for_new_cup=false (would breach), last_call_minutes=null
- ✅ F3 training_recommendation → "easy" with confidence 0.3 (no training-load baseline yet)
- ✅ F2 work_windows → 07:00–23:00 single gap, predicted_focus 46, peak_focus_hour=null (no focus entries yet)
- ✅ F8 habits/adherence → returns 1-day streak on 'meditate' from 2D
- ✅ F9a advisor on every valid intent + 422 on `intent=dance`

### Decisions log (2E)
- **2E-1** (resolved): `compute_baseline` accepts `before=` so F1 excludes the target day's own value from its baseline. Without it, today's HRV is part of its own z-score baseline → bias toward 0.5 component.
- **2E-2** (resolved): F1 component weights are **renormalized** when components are missing, not just zeroed. A day with no HRV reading should not be artificially penalized 40 points.
- **2E-3** (resolved): F1 returns `provisional=true` when HRV *or* RHR baseline has <7 days (whichever is sparser). Score still computed.
- **2E-4** (resolved): F2 peak focus hour uses weighted-mean (hour × focus.score) over last 30 days. Fallback 10:00 with `confidence_hint=low` if no qualifying entries.
- **2E-5** (resolved): F2 day boundary = 07:00–23:00 local. Outside this range, no windows are scheduled. Matches realistic wake/bedtime envelope without requiring per-user config.
- **2E-6** (resolved): F2 body-battery curve uses linear interp on three coarse keypoints (start@08:00, min@14:00, end@22:00). SPEC says "Body Battery curve" without prescribing per-hour granularity; metrics table only stores 3 daily markers.
- **2E-7** (resolved): F4 optimal sleep duration baseline uses 60-day lookback and requires ≥5 qualifying days. Below that → 7.5h fallback. SPEC said "the median" without specifying lookback window; this picks a conservative window so a single anomaly doesn't dominate.
- **2E-8** (resolved): F5 default dose = 80mg per cup (SPEC). Non-coffee `drink` entries are ignored entirely (tea is a future addition once we have a per-kind dose table).
- **2E-9** (resolved): F8 endpoint returns adherence for **all currently active habits** in the requested window. Adding `habit_id` query param can come later if needed (Discord bot's `/today` brief shows all habits anyway).
- **2E-10** (resolved): F9a `intent=rest` returns F4's sleep window verbatim per SPEC (recommendation="sleep_window", reasons include bedtime/wake/flags).
- **2E-11** (resolved): F9a `intent=meeting` first scores the day's gaps via F2 (min_minutes=30), then prefers a gap *outside* the top 2 focus windows. SPEC says "avoid F2 top 2 windows"; only fallback to top window if no other gaps exist.

### Known follow-ups (non-blocking)
- F2's body-battery interp keypoints (08:00 / 14:00 / 22:00) are reasonable defaults but not user-specific. Could be replaced with sparse-array interpolation once we re-pull the raw Garmin BB timeline.
- `readiness_score` is not yet persisted as a derived metric. SPEC §9 mentions `readiness_compute` scheduled job; will land alongside F7 weekly report (Phase 2I).

## Phase 2F — Frontend
Status: done — SSR-verified, dev server clean; visual review pending

### Backend additions for 2F
- [x] `api/auth.py` — POST `/auth/login`, POST `/auth/logout`, GET `/auth/status`
- [x] `auth.py` extended: `require_auth` now accepts session cookie OR X-Bot-Token. `mint_session_token` + `verify_session_token` use `itsdangerous.URLSafeTimedSerializer`. Permissive when both `WEB_UI_PASSWORD` and `BOT_SHARED_SECRET` are unset.

### Frontend
- [x] `lib/api/types.ts` — TS mirrors of all backend Pydantic schemas
- [x] `lib/api/client.ts` — typed fetch wrappers, cookie-based auth, central error handling
- [x] `vite.config.ts` proxies `/api/*` → `http://127.0.0.1:8000` in dev
- [x] `lib/components/ui/` — Card, Pill, Stat, Button, Input (Svelte 5 runes)
- [x] `lib/components/ReadinessRing.svelte` — SVG radial gauge (no logo; gauge only)
- [x] `lib/components/LineChart.svelte` — ECharts wrapper, dynamic-imported to avoid SSR issues, dark theme
- [x] `+layout.svelte` — sidebar nav, wordmark LATTICE text only (no diamond/SVG mark), auth gate redirects to `/login`
- [x] `/` — Today: readiness ring + components, F9a advisor card with intent picker (6 intents), F3 training, F4 sleep window, F5 caffeine, recent entries
- [x] `/trends` — 4 ECharts line graphs (sleep, HRV, RHR, body battery) over last 60 metrics each
- [x] `/log` — entries table with type filter chips, per-type new-entry form (8 types), delete
- [x] `/habits` — definitions + 14-day check-in grid (click to toggle), F8 adherence stats, new habit form
- [x] `/report` — placeholder scaffold (real data lands in 2I)
- [x] `/login` — wired to `POST /api/auth/login`, redirects to `/` on success

### Verify
- [x] `npm run check` → 294 files, **0 errors, 0 warnings**
- [x] All 6 routes SSR to HTTP 200 (`/`, `/login`, `/trends`, `/log`, `/habits`, `/report`)
- [x] `/api/health` reachable through Vite proxy on `:5173`
- [x] Auth API live: dev-permissive without cookie, mints 30d cookie on login, status reads it, logout clears it
- [ ] Visual review in browser (waiting on user)

### Decisions log (2F)
- **2F-1** (resolved): Session cookie is signed with `WEB_UI_PASSWORD` itself as the signing key (via `itsdangerous`). No separate SECRET_KEY env var needed for v1; rotating the password invalidates all sessions, which is desirable.
- **2F-2** (resolved): Dev-permissive auth — when both `WEB_UI_PASSWORD` and `BOT_SHARED_SECRET` are blank/unset, `require_auth` returns OK and `/auth/login` accepts any password (still mints a cookie). Matches the bot-secret pattern and keeps single-dev iteration friction low. The backend binds to 127.0.0.1 (SPEC §10), so permissive local mode is acceptable.
- **2F-3** (resolved): Vite proxies `/api/*` to `127.0.0.1:8000` in dev. Production deployment serves the built frontend from FastAPI's `main.py` (per SPEC §3), no proxy needed there. Phase 2J wires that.
- **2F-4** (resolved): ECharts (not Chart.js per SPEC §2). Wrapper is `lib/components/LineChart.svelte`; library is **dynamic-imported** so it never runs at SSR time (echarts touches `window` and `canvas`).
- **2F-5** (resolved): No logo / no SVG mark anywhere (per durable user rule). The mockup's `.brand-mark` diamond/square is omitted. Sidebar shows "LATTICE" wordmark text only. Readiness gauge IS an SVG `<circle>` but it's a data visualization, not a brand mark — drawing the line at "graphic that identifies the product."
- **2F-6** (resolved): F9b second-opinion path is **not** surfaced in the web UI (SPEC §6 F9b is Discord-only). The Today page's advisor card shows only F9a output.
- **2F-7** (resolved): Habit grid is 14 days (not 30 like the mockup). 14d fits the available card width without horizontal scroll and matches the "current streak + week %" stats above it. The 30-day pattern shown in the mockup was a different aesthetic choice; 14 days is enough operational signal for the IN-list features.
- **2F-8** (resolved): Log page form uses raw `<input>` elements inside the field loop rather than the `Input` primitive — the dynamic per-type field shape made the `bind:value` API awkward. Primitive `Input` is still used elsewhere (login, etc.).
- **2F-9** (resolved): Report page is a labeled placeholder ("phase 2I") rather than mock data. Real Stage A statistics + Stage B prose ship in 2I.

### Known follow-ups (non-blocking)
- Sync pill in sidebar (mockup feature) — not yet built; data sync status surfaces could come in 2J alongside scheduler wiring.
- Toast notifications for delete/create errors — currently using `alert()` in habits/log pages. Acceptable for single-user dev but rough.
- Keyboard shortcuts (mockup nav-key labels T/R/L/H/W) — labels are rendered but not wired to hotkeys yet. Add in 2J polish.

## Phase 2G — Discord chat agent (collapsed 2G + 2H)
Status: done — offline-tested; live verification requires `DEEPSEEK_API_KEY` + `DISCORD_BOT_TOKEN`

Per user redirection at the start of this phase, slash commands (`/today /log /sync
/report`) were dropped in favor of a conversational LLM agent on Discord. The
former 2H scope (DeepSeek client, tools, router, `/api/chat`, system prompt with
F9a/F9b safeguards) was folded into 2G so there is one chat-first phase instead
of two sequential phases.

### Backend LLM layer
- [x] `integrations/deepseek.py` — async OpenAI client pointed at `https://api.deepseek.com`. Typed errors `DeepSeekAuthMissing` / `DeepSeekAuthError` / `DeepSeekUnavailable`. Single retry off (router handles tool-call loop instead).
- [x] `llm/prompts.py` — `SYSTEM_PROMPT_TEMPLATE` verbatim from SPEC §7.5 (F9a paraphrase rule, F9b second-opinion rule with "Algorithm recommends / My take" structure, action confirmation policy). `build_system_prompt()` renders `{current_datetime}` + `{timezone}` + `{user_name}` per turn.
- [x] `llm/tools.py` — OpenAI tool-call schemas for the SPEC §7.1 inventory:
  - Read: `get_today_overview`, `get_readiness`, `get_advice`, `get_work_windows`, `get_training_recommendation`, `get_sleep_window`, `get_caffeine_status`, `get_metric`, `get_baseline`, `get_calendar`, `get_entries`, `list_habits`, `get_habit_adherence`
  - Write: `log_entry`, `check_habit`, `create_calendar_event`, `patch_calendar_event`, `delete_calendar_event`, `sync_garmin`, `sync_calendar`
- [x] `llm/router.py` — in-process dispatcher + agent loop. Tools call existing `functions/*` and `sync/*` directly (no HTTP). Per-tool error handler returns `{error: ...}` to the LLM rather than crashing. Iteration cap = `settings.chat_max_iterations` (default 6).

### Chat API
- [x] `schemas/chat.py` — `ChatRequest { session_id, message }`, `ChatResponse { session_id, reply, tool_calls[], actions_taken[], finish_reason }`.
- [x] `api/chat.py` — POST `/api/chat`. Loads prior turns from `conversations` for the session_id if the most recent row is within `chat_session_idle_minutes` (default 30); otherwise starts fresh. Persists user + assistant rows. Maps DeepSeek errors to 503/401.
- [x] Wired in `main.py`.

### Discord bot
- [x] `bot/lattice_bot/main.py` — discord.py 2.x Client with `dm_messages` + `message_content` intents. `on_message` filters: ignore self, ignore non-DMs, ignore non-owner (`DISCORD_OWNER_ID`). Forwards to `/api/chat` with `X-Bot-Token`, shows typing indicator, posts reply.
- [x] `bot/lattice_bot/backend_client.py` — typed `post_chat()` wrapper, 120s timeout (tool loops are slow), `BackendError` raises on 4xx/5xx.
- [x] `bot/lattice_bot/formatters.py` — `split_for_discord()` chunks long replies on newline/space boundaries to stay under Discord's 2000-char limit.
- [x] Bot exits cleanly with a message when `DISCORD_BOT_TOKEN` is unset (matches the dev-permissive ethos elsewhere).
- [x] Session id auto-rotates after 30 min idle (mirrors backend `_load_history` filter).

### Config additions
- [x] `DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL` (default `https://api.deepseek.com`), `DEEPSEEK_MODEL_DEFAULT` (default `deepseek-chat`), `LATTICE_USER_NAME` (default `Stan`), `LATTICE_CHAT_MAX_ITERATIONS` (6), `LATTICE_CHAT_HISTORY_TURNS` (20), `LATTICE_CHAT_SESSION_IDLE_MIN` (30).
- [x] `DISCORD_OWNER_ID` added to bot settings + SPEC `.env` block.

### Tests — 4 new (total 79 passing)
- [x] `test_chat_agent.py` mocks `chat_completion` to script tool-call sequences offline:
  - Read path: `get_readiness` resolves and a final content reply is returned.
  - Write path: `log_entry` actually creates a DB row (source=`discord`) and reports `actions_taken=["log_entry"]`.
  - Iteration cap: 50-tool-call loop stopped at `max_iters=3` with `finish_reason="iter_cap"`.
  - Unknown tool: returns `{error}` to the model, doesn't crash the loop.

### Live verification
- [x] Backend boots; `/api/health` 200; `/api/chat` 503 with `deepseek_unconfigured` when key absent (confirms guard).
- [x] Bot stub exits cleanly when `DISCORD_BOT_TOKEN` unset.
- [ ] Full live round-trip with real DeepSeek + Discord — blocked on user adding `DEEPSEEK_API_KEY`, `DISCORD_BOT_TOKEN`, `DISCORD_OWNER_ID`, and `BOT_SHARED_SECRET` to `.env`.

### Decisions log (2G)
- **2G-1** (resolved): Collapsed prior 2G (slash commands) + 2H (LLM integration) into a single chat-first phase per user direction. Slash commands dropped entirely; SPEC §8.4 and §11 IN list updated. Brief justification: with a working LLM agent doing tool-calling, slash commands become redundant — "sync garmin" works the same as `/sync`, and the LLM can interpret natural variants.
- **2G-2** (resolved): Listen scope = DM only. Channel messages (mentioned or not) are ignored. Matches single-user app: there is no scenario where the bot needs to broadcast in a guild. Non-owner DMs are silently dropped.
- **2G-3** (resolved): Tool surface = read + write (full agent). The LLM can mutate state (log entries, check habits, create/patch/delete calendar events, trigger syncs). System prompt enforces "confirm before destructive actions" per SPEC §7.2; agent loop reports `actions_taken` so the user sees what changed.
- **2G-4** (resolved): DeepSeek native tool calling (OpenAI-compatible function calls) — not a prompted-JSON ReAct loop. Less fragile, less prompt surface, debuggable via standard tool_calls/tool_results message shape.
- **2G-5** (resolved): Default model is `deepseek-chat` (SPEC §7.3 says `deepseek-v4-flash` — those names map to the same tier; we keep the canonical SDK name configurable via `DEEPSEEK_MODEL_DEFAULT`). v4-pro / thinking mode is reserved for F7 (weekly report, 2I) and the chat scheduling-intent classifier (also deferrable).
- **2G-6** (resolved): Tools dispatch in-process. The router imports and calls existing `functions/*`, `sync/*` code directly rather than round-tripping through HTTP to the same backend. Faster, simpler, single source of error mapping. (The /api/* endpoints remain the canonical external surface for the web UI.)
- **2G-7** (resolved): Per-tool errors are returned to the LLM as `{error: ...}` tool results, not raised. The model sees the error and either retries with different args or apologizes to the user. The agent loop never crashes from a tool failure.
- **2G-8** (resolved): Session reset is server-side. `_load_history` filters out rows where the most recent message in the session is older than `chat_session_idle_minutes`. Bot also rotates its session_id after the same window — both sides converge, but the server is the source of truth.
- **2G-9** (resolved): Tool-call sequences from prior turns are NOT replayed across turns. The DB persists user + assistant content rows; tool result messages are transient. Replaying assistant rows that contain `tool_calls` without their matching tool messages would violate the OpenAI message contract, so `_load_history` strips them. Loses a little fidelity but keeps replays valid.
- **2G-10** (resolved): Bot is single-user gated by `DISCORD_OWNER_ID`. Bot owner copies their numeric Discord user id into `.env`; non-owner DMs are dropped at the bot layer (no backend round-trip). Matches the rest of Lattice's single-user posture.
- **2G-11** (resolved): Iteration cap = 6 tool-call rounds per chat turn. If the model loops, the cap returns a "stopped at iteration cap" message with the list of tools attempted — the user sees what happened and can rephrase. Adjustable via `LATTICE_CHAT_MAX_ITERATIONS`.

### Known follow-ups (non-blocking)
- F9b safeguard validator (SPEC §6 F9b: "router post-hoc validation") is NOT yet implemented. The system prompt instructs the model to use the "Algorithm recommends / My take" format, but the router doesn't prepend the algorithm output if the model skips that label. Add a post-hoc regex check that detects "second-opinion intent" and verifies the format, falling back to F9a verbatim + a "second opinion unavailable" note on malformed replies. Can land in 2J.
- Daily token-budget gate (SPEC §7.4: 200k input + 50k output) not yet implemented. Single-user dev usage is unlikely to hit it; add a counter table or daily-counter row in 2J.
- The `conversations` table prune job (SPEC §9 daily 03:00) not yet wired. Add when 2J wires APScheduler jobs.
- Model selection by intent (SPEC §7.3) — flash vs flash+thinking vs pro+thinking — not yet implemented. v1 uses one model for chat (`deepseek-chat`) and the weekly report (2I) will pick its own.

## Phase 2H — RESERVED (folded into 2G above)
Status: n/a — see 2G-1.

## Phase 2I — Briefings + F7 weekly report + report UI
Status: done — live-verified against real Garmin/entries data and a real DeepSeek call

### Backend — F7 two-stage pipeline
- [x] `functions/weekly_stats.py` — Stage A (deterministic). Daily aggregates over the ISO week, week-of-Mon-to-Sun averages, best/worst day by readiness, per-habit week completion, Pearson correlations (|r|>0.5, n≥5) for: caffeine_time × next-night sleep_score, workout_intensity × next-day HRV, meeting_hours × energy; mean shifts vs trailing 4-week baseline (>1 SD).
- [x] `functions/weekly_report.py` — Stage B orchestrator. Calls DeepSeek with the locked weekly-report prompt + Stage A JSON, UPSERTs into `weekly_reports` by `iso_week`, falls back to a deterministic summary when the LLM is unavailable.
- [x] `llm/prompts.py` — added `WEEKLY_REPORT_PROMPT` verbatim per SPEC §7.5 (5-bullet structure, hard rules: no invented correlations/metrics, no generic advice, skip experiment when coverage is sparse).

### Reports API (SPEC §5.7)
- [x] `schemas/reports.py` — `WeeklyStatsOut`, `WeeklyReportOut.from_row` (parses stats_json).
- [x] `api/reports.py` — `GET /reports/weekly/latest`, `GET /reports/weekly?week=`, `POST /reports/weekly/generate` (overwrite policy per 2I-4). ISO-week shape validated with regex; 422 on bad format, 404 when missing.
- [x] Wired into `main.py`.

### Scheduler — backend (SPEC §9)
- [x] `sync/scheduler.py` — added two new jobs gated by `LATTICE_DISABLE_SCHEDULER`:
  - `readiness_compute` — daily 06:00, persists today's F1 score as `readiness_score` metric row (UPSERT). Skips when no component data.
  - `weekly_report` — Sun 22:00, generates F7 for the ISO week containing today.

### Bot — briefings (SPEC §8.4)
- [x] `bot/lattice_bot/briefings.py` — APScheduler in the bot process. 07:30 morning + 21:00 evening. Pure deterministic templates per 2I-1 (no LLM). DM owner via lazy DM channel resolution. `BriefSender` caches the channel; per-job try/except so a single bad fetch never crashes the scheduler.
- [x] `bot/lattice_bot/main.py` — starts briefings scheduler in `on_ready` once owner_id + http_client are ready; shuts it down in `close()`.
- [x] `bot/lattice_bot/backend_client.py` — added `get_json()` helper for brief fetches.

### Frontend — /report (SPEC §6 F7)
- [x] `frontend/src/lib/api/types.ts` — `WeeklyReport`, `WeeklyStats`, `DailyAggregate`, `BestWorstDay`, `HabitWeekStat`, `Correlation`, `MeanShift`.
- [x] `frontend/src/lib/api/client.ts` — `reports.latest()`, `reports.byWeek(w)`, `reports.generate(w?)`.
- [x] `frontend/src/routes/report/+page.svelte` — replaces 2F placeholder. Renders Stage B prose, model badge, averages strip (3-up), daily aggregate table (week × metric), best/worst cards, habits adherence bars, correlations + mean shifts, coverage notes. Empty state with "generate now" button when no report exists; "regenerate" button on existing reports (overwrite by design).

### Tests — 12 new (total 93 passing backend + 4 passing bot)
- [x] `test_weekly_stats.py` (9 tests):
  - `iso_week_bounds` simple + year-boundary
  - 7-day averaging + daily aggregate shape
  - best/worst day picks correct readiness extremes
  - weak signal: no correlation reported below threshold
  - strong inverse signal: caffeine × sleep correlation fires correctly with direction=negative
  - mean_shift fires only when |delta| > 1 trailing SD
  - mean_shift suppressed when this week ≈ trailing
  - habits surface with correct counts
  - meeting × energy needs n ≥ CORR_MIN_N to report
- [x] `test_weekly_report.py` (4 tests) — DeepSeek mocked:
  - LLM-summary path persists row with model name
  - re-running overwrites existing row (idempotent generate)
  - LLM unavailable → `model_used="deterministic-only"` fallback
  - `get_latest` returns the most recent ISO week
- [x] `bot/tests/test_briefings.py` (4 tests) — pure format functions, no Discord, no httpx:
  - morning brief renders all sections including the calendar's first timed event
  - morning brief degrades cleanly when no windows / no events
  - evening brief groups entry counts and surfaces sleep flags
  - evening brief renders cleanly with no entries

### Live verification (against real DB + real DeepSeek key)
- ✅ `POST /api/reports/weekly/generate` (no week param) returned `iso_week="2026-W20"`, `model_used="deepseek-chat"`, real prose grounded in the Stage A JSON (correctly noting sparse coverage and skipping the experiment per the prompt rule).
- ✅ `GET /api/reports/weekly/latest` returns the just-generated row.
- ✅ `GET /api/reports/weekly?week=2025-W42` returns 404 with structured `{error: "not_found"}`.
- ✅ `GET /api/reports/weekly?week=bogus` returns 422 with structured `{error: "invalid_week"}`.

### Decisions log (2I)
- **2I-1** (resolved): Briefings are **deterministic templates**, not LLM-generated prose. Saves ~2k tokens/day, zero variance at 07:30, and matches the "Lattice is an interface to data, not a coach" tone from the system prompt. The chat agent already provides the conversational surface; briefings are intentionally terse.
- **2I-2** (resolved): F7 Stage B uses `settings.deepseek_model_default` (currently `deepseek-chat`). SPEC §7.3 prescribed `deepseek-v4-pro thinking=enabled`; in practice the chat-tier model produces a fine ≤200-word weekly synthesis, and the model name is configurable via env so swapping to reasoner later is one-line.
- **2I-3** (resolved): "This week" = ISO Mon–Sun for the week containing `target` (default today). Storage key `YYYY-Www`. SPEC §9 schedules the job Sun 22:00, by which time the current ISO week is essentially closed.
- **2I-4** (resolved): `POST /reports/weekly/generate` is **idempotent — it overwrites** the existing row for that ISO week (SQLite UPSERT on `iso_week`). Re-running always reflects the latest pass; same week, same key, latest LLM output wins. Identity map cache flushed via `session.expire_all()` after commit so the re-select returns fresh data.
- **2I-5** (resolved): LLM failure mode is **graceful degradation**, not 5xx. If DeepSeek is down or the key is missing, the orchestrator persists the row anyway with `model_used="deterministic-only"` and a short Python-built summary referencing only the Stage A facts. The user always gets a row, even on a bad day.
- **2I-6** (resolved): `readiness_score` is now persisted as a derived metric via the 06:00 scheduled job. Weekly stats prefers the persisted value but falls back to on-the-fly compute when none exists (avoids "report shows 0 readiness for past days because the job didn't run yet").
- **2I-7** (resolved): Briefings live in the bot process per SPEC §8.4 ("APScheduler in the bot"). User-facing push messages belong with the user-facing process. Backend's APScheduler keeps the data-jobs (garmin/readiness/weekly_report).
- **2I-8** (resolved): `BriefSender` resolves the owner's DM channel lazily on first send and caches it. `bot.fetch_user(owner_id)` + `user.create_dm()` is the discord.py pattern; we don't need the user to have DM'd the bot first.
- **2I-9** (resolved): Stage A correlations are limited to the three pairs in SPEC §6 F7. We do NOT scan every pair of metrics for hidden correlations — that would generate noise and arbitrary patterns at small n. The three named pairs map directly to actionable levers (caffeine timing, workout dosing, meeting load).
- **2I-10** (resolved): Coverage notes flag sparse data (`<5/7 days with readiness`) so the LLM follows the "skip experiment" rule from the prompt. Tested live: with 2/7 days seeded, the model correctly produced a 4-bullet output and refused to invent an experiment.

### Known follow-ups (non-blocking)
- Past-week navigation UI on /report: only the latest report is fetched and a "generate" button regenerates the current week. A simple `<select>` of recent iso_weeks could ship in 2J.
- Conversation prune job (SPEC §9 daily 03:00) still not wired. Add in 2J.
- Calendar cache prune job (SPEC §9 hourly) still not wired. Add in 2J.
- Sync pill / Tweaks panel / keyboard shortcuts (2F follow-ups) carry over to 2J.

## Phase 2J — Polish
Status: done — green test suites, frontend `npm run check` 0/0/0

### Core (SPEC §12)
- [x] Backend rotating file logging already wired in `lattice.config.configure_logging` →
      `logs/backend.log` (10 MB × 5).
- [x] Bot rotating file logging: `bot/lattice_bot/main.py:_setup_logging` writes
      `logs/bot.log` (10 MB × 5) in addition to console.
- [x] `frontend/src/routes/+error.svelte` — root SvelteKit error page with status
      + message + back link, JetBrains Mono.
- [x] `README.md` replaces 2A stub — stack, setup, env reference, scheduled-job
      table, verify commands, smoke-test pointer.
- [x] `SMOKE_TEST.md` — 10-section cold-start checklist covering install,
      boot, health, all integrations, every page, scheduler, error path.

### Missing SPEC §9 prune jobs
- [x] `_conversation_prune_job` — daily 03:00, deletes `conversations` rows
      whose `timestamp` is older than 30 days.
- [x] `_calendar_cache_prune_job` — hourly :15, calls existing
      `prune_old_events(older_than_days=1)` (commits internally).

### /report past-week picker
- [x] New `list_weekly_report_weeks` helper returns iso_weeks newest-first.
- [x] `GET /api/reports/weekly/index` exposes them.
- [x] `frontend/src/routes/report/+page.svelte` adds a `<select>` in the
      header; changing the week fetches `byWeek(...)`. Regenerate updates the
      list afterwards.

### F9b safeguard validator
- [x] `lattice/llm/f9b_validator.py` — `looks_like_second_opinion` + `has_required_structure`
      regex helpers. `enforce(user_message, reply)` prepends a one-line note
      when a second-opinion intent reply lacks the
      `Algorithm recommends: ... My take: ...` structure.
- [x] Wired into `run_agent` final reply path.
- [x] `tests/test_f9b_validator.py` (13 tests, all passing).

### UI polish
- [x] `SyncPill.svelte` — sidebar pill showing relative time since last
      Garmin metric + last calendar fetch; polls `/sync/status` every 60s.
- [x] `GET /api/sync/status` derives `max(timestamp)` from `metrics` (source=garmin)
      and `max(fetched_at)` from `calendar_cache`.
- [x] `lib/toast.svelte.ts` + `Toaster.svelte` — runed toast queue replacing
      `alert()` calls in `/log` (delete) and `/habits` (toggle).
- [x] Keyboard shortcuts: `+layout.svelte` listens for unmodified single-key
      presses matching the NAV table (T/R/L/H/W) and routes via `goto`; skips
      when focus is in an input/textarea/contenteditable.

### LLM budget + per-intent routing
- [x] New `llm_usage` table (Alembic `0002_llm_usage`) — `(date, input_tokens,
      output_tokens)`.
- [x] `lattice/llm/budget.py` — `check_budget` raises `BudgetExceeded`,
      `record_usage` UPSERTs today's counts from `completion.usage`.
- [x] `lattice/llm/model_selector.py` — `pick_chat_model(user_message)` returns
      reasoner model for scheduling / second-opinion / compare phrases; else
      `deepseek_model_default`. New env var `DEEPSEEK_MODEL_REASONER` defaults
      to `deepseek-reasoner`.
- [x] Router: `check_budget` before agent loop; `record_usage` after each
      completion; `chat_completion(..., model=pick_chat_model(user_message))`.
- [x] Weekly report: same `check_budget`/`record_usage` wrap; `BudgetExceeded`
      caught alongside DeepSeek errors → falls back to deterministic summary.
- [x] `api/chat.py` maps `BudgetExceeded` to **429** with friendly detail.
- [x] New settings: `daily_token_budget_input` (200_000),
      `daily_token_budget_output` (50_000), overridable via env.

### Verify
- [x] Backend pytest: **106 passing** (was 93 before; +13 from F9b validator).
- [x] Bot pytest: **4 passing** (fixed `test_briefings.py` hardcoded-date
      brittleness by switching to `datetime.now(...)`).
- [x] Frontend `npm run check`: **298 files, 0 errors, 0 warnings**.
- [x] Alembic `0002_llm_usage` applied cleanly.

### Decisions log (2J)
- **2J-1** (resolved): Bot logging is wired identically to backend — root
  logger handler set, rotating file at `logs/bot.log`, third-party
  `discord.*` loggers turned down to WARNING. Matches CLAUDE.md ("rotating
  files in logs/").
- **2J-2** (resolved): Picker uses a dedicated `/reports/weekly/index`
  endpoint rather than overloading `/weekly` with no-arg behavior. The
  existing `/weekly?week=` route already implies a required query param, and
  conditional shape-shifting would surprise clients.
- **2J-3** (resolved): F9b safeguard is **purely structural** — it does NOT
  re-compute F9a or splice in algorithm output. Without confident intent
  classification, splicing the wrong intent's recommendation would fabricate
  worse misinformation than the missing structure. A one-line note ("F9b
  note: structure not followed") is the safer fallback.
- **2J-4** (resolved): Sync pill is **derived**, not stored — `max(timestamp)`
  on metrics and `max(fetched_at)` on calendar_cache. No new table needed.
  Refresh every 60s on the client; cheap query.
- **2J-5** (resolved): Toast component is a $state-array queue, not a Svelte
  store, to keep with the project's Svelte 5 runes convention (CLAUDE.md).
- **2J-6** (resolved): Keyboard shortcuts use unmodified single-key presses
  (T/R/L/H/W) — no ctrl/alt/meta combos — because the labels in the sidebar
  already render bare keys and the conflict surface is minimal in a focused
  single-user app. Skips when typing in any form control.
- **2J-7** (resolved): Token budget is **hard-gated**. `BudgetExceeded`
  surfaces as a 429 in chat; the weekly report swallows it as a normal
  fallback path (model_used="deterministic-only"). Reset is implicit — the
  next local day reads a new row.
- **2J-8** (resolved): Per-intent model selection ships **two tiers** —
  default chat (`deepseek-chat`) and reasoner (`deepseek-reasoner`).
  SPEC §7.3 mentions a third flash+thinking tier, but DeepSeek's current
  product surface has these two distinct endpoints; "thinking" mode is
  controlled by which model is requested. Selector is intentionally keyword-
  based so it never costs an extra LLM call.
- **2J-9** (resolved): The pre-existing `test_morning_brief_renders_all_sections`
  test used hardcoded dates (`2026-05-14`) that went stale as the clock
  advanced. Fixed to use `datetime.now(TZ)` so the suite stays green
  regardless of when it runs. Not strictly 2J scope but blocks the smoke
  test pass.

### Known follow-ups (non-blocking)
- mypy --strict has not been re-run on the new modules. The existing
  codebase has incidental violations that predate 2J; running strict will
  surface those alongside any new ones. Defer until there is a clear
  mypy-clean baseline.
- Per-intent model routing is currently binary. If DeepSeek exposes a
  flash+thinking endpoint distinct from `deepseek-reasoner`, the selector
  can grow a third tier; the keyword classifier already separates
  "scheduling" from "second opinion" cases.
- Sync pill could surface manual "sync now" buttons. Currently a passive
  indicator only.

## Phase 2K — Drink classification, entry markers, research agent
Status: done — frontend type-check clean (302 files, 0 errors); classification smoke-test passing

### Drink sub-type classification (SPEC §4.7 drink schema)
- [x] `schemas/entries.py` — `_DRINK_MAP` ordered lookup table (62 patterns): specific-before-generic ordering so "latte" matches before "coffee". Tuples of `(pattern, canonical_kind, sub_type, caffeine_mg)`.
- [x] `schemas/entries.py` — `classify_drink(raw: str)` function: lowercases input, iterates `_DRINK_MAP`, returns `(kind, sub_type, caffeine_mg)`.
- [x] `DrinkData` model: added `sub_type: str | None` and `caffeine_mg: float | None` fields; `@model_validator(mode="after")` calls `classify_drink` and fills missing fields automatically on validation.
- [x] `functions/caffeine.py` — F5 updated to use `caffeine_mg` from entry data when present; falls back to 80mg default only for legacy `kind="coffee"` entries with no explicit amount. Non-coffee kinds without `caffeine_mg` are skipped.
- [x] `_auto_classify` fires transparently in `_h_log_entry` via `validate_data_for_type()` — no router change needed.

Key classification table entries (sample):
| Input | kind | sub_type | caffeine_mg |
|-------|------|----------|-------------|
| latte | coffee | latte | 150 |
| espresso | coffee | espresso | 64 |
| cold brew | coffee | cold_brew | 200 |
| double espresso | coffee | double_espresso | 128 |
| green tea | tea | green_tea | 30 |
| beer | alcohol | beer | null |

### Entry markers endpoint
- [x] `functions/entry_markers.py` (NEW) — `compute_entry_markers(session, entry_id, tz)` dispatches to per-type builders. Returns `{entry_id, type, timestamp, markers: [{label, value, sentiment}]}`. Sentiment drives UI color: good=green / bad=red / neutral=muted / info=teal.
  - `_drink_markers`: caffeine residual at bedtime (F4 + 5h half-life), daily total mg, historical sleep-impact correlation (≥5 samples, hour bucket).
  - `_food_markers`: calorie estimate, meal timing relative to sleep window.
  - `_score_markers`: energy/mood/focus — absolute value chip, trend vs 7-day mean.
  - `_symptom_markers`: severity + recency chips.
- [x] `api/entries.py` — `GET /entries/{entry_id}/markers` endpoint, placed before DELETE to avoid FastAPI path shadowing. Maps `entry_markers.error` to 404.
- [x] `lib/api/types.ts` — `EntryMarker`, `EntryMarkers` interfaces added.
- [x] `lib/api/client.ts` — `entries.markers(id)` method added.
- [x] `frontend/src/routes/log/+page.svelte` — click-to-expand rows: `expandedId` state, `markersCache` Map, `markersLoading` Set. `toggleEntry(id)` fetches on demand and caches. Expanded row renders marker chips. `summarize()` for drink shows `sub_type ?? kind` + caffeine_mg when present. CSS: `.row-expanded`, `.markers-row`, `.mchip` with sentiment variants.

### Research agent (web search + paper persistence)
- [x] `integrations/tavily.py` (NEW) — async Tavily search client (httpx). `tavily_search(query, *, api_key, max_results, search_depth)`. Typed errors: `TavilyAuthMissing`, `TavilyAuthError`, `TavilyUnavailable`. Requires `TAVILY_API_KEY` in `.env`.
- [x] `integrations/research.py` (NEW) — Markdown paper I/O in `data/research/`. `save_paper(title, topic, content, sources)` → kebab-case filename with `YYYY-MM-DD-` prefix. `list_papers(topic=None)` parses YAML-ish frontmatter. `read_paper(filename)` with path-traversal protection via `Path(filename).name`.
- [x] `config.py` — `tavily_api_key: str | None` (env `TAVILY_API_KEY`), `research_dir: str` (env `LATTICE_RESEARCH_DIR`, default `"data/research"`).
- [x] `llm/tools.py` — 4 new tools: `web_search`, `save_research_paper`, `list_research_papers`, `read_research_paper`.
- [x] `llm/router.py` — 4 new handlers: `_h_web_search`, `_h_save_research_paper`, `_h_list_research_papers`, `_h_read_research_paper`. `save_research_paper` added to `WRITE_TOOLS`.
- [x] `llm/prompts.py` — `RESEARCH MODE` section in system prompt: 6-step protocol (check prior papers → gather biometrics → 3–8 web searches → synthesize → save paper → reply with summary). Paper structure: `## Summary / ## Key Findings / ## User Context / ## Recommendations / ## Sources`. `web_search` restricted to research; biometric questions use existing tools.
- [x] `.env.example` — `TAVILY_API_KEY=` and `# LATTICE_RESEARCH_DIR=data/research` added.

### Verify
- [x] `npm run check` → 302 files, 0 errors, 0 warnings
- [x] Classification smoke-test: `latte` → kind=coffee, sub_type=latte, caffeine_mg=150.0 ✓; `espresso` → kind=coffee, sub_type=espresso, caffeine_mg=64.0 ✓
- [ ] Live markers test — requires running backend + clicking a drink entry in /log
- [ ] Live research test — requires `TAVILY_API_KEY` in `.env`; DM bot "research ways to improve HRV"

### Decisions log (2K)
- **2K-1** (resolved): `_DRINK_MAP` is ordered most-specific first. Substring matching would otherwise make "espresso" match "coffee" before "espresso". Pattern check is `pattern in name_lower` so multi-word sub_types (e.g. "cold brew") resolve correctly with no regex.
- **2K-2** (resolved): No Alembic migration needed. `DrinkData` changes only affect the JSON stored in `entries.data`. New fields `sub_type` and `caffeine_mg` are optional — existing rows missing them still validate, and F5's fallback handles legacy `kind="coffee"` entries.
- **2K-3** (resolved): Research papers are plain Markdown files with a 4-field YAML-ish header (`title`, `topic`, `date`, `sources`). No YAML parser dependency; simple `key: value` lines parsed manually. Human-readable and editable without tooling.
- **2K-4** (resolved): `read_paper` uses `Path(filename).name` (strips directory components) before constructing the full path. Prevents traversal attacks even though this is a single-user app — defense in depth.
- **2K-5** (resolved): `web_search` is gated behind `TAVILY_API_KEY`; when absent, the handler returns a structured error to the LLM explaining the key is missing. The model can gracefully inform the user rather than crashing the tool loop.
- **2K-6** (resolved): Markers are fetched on demand (click-to-expand) and cached client-side in a `Map<number, EntryMarkers>`. Not pre-fetched on page load — a log page can have dozens of entries; loading markers for all of them eagerly would be expensive and most are never expanded.

### Known follow-ups (non-blocking)
- No backend pytest coverage for `entry_markers.py`, `tavily.py`, or `research.py` yet. Add in next polish pass.
- Research dir (`data/research/`) is auto-created by `save_paper` on first use. Could be pre-created in setup scripts.
- Marker correlation for drink entries requires ≥5 historical samples matching the hour bucket — new users will see fewer markers until enough data accumulates.

---

## Decisions log

- **2A-1** (resolved): `weekly_reports` gets a dedicated table with columns `id, iso_week, generated_at, model_used, stats_json, summary_text`. SPEC §4 updated.
- **2A-2** (resolved): Tweaks panel (theme/accent/density) dropped from v1. Stays as design reference only.
- **2A-3** (resolved): No logo / SVG mark / favicon graphic anywhere. Wordmark "LATTICE" text only.
- **2A-4** (resolved): Bot stub for phase 2A exits cleanly with a "phase 2G not yet" message instead of crashing the terminal (CLAUDE_CODE_PROMPT allowed crash; clean exit is friendlier).
- **2A-5** (resolved): `npx sv create` used to scaffold SvelteKit 5 (the `npm create svelte@latest` form is deprecated).
