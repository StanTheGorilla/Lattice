# Claude Code Prompt — Lattice Implementation

**How to use this file:**
1. Open an empty directory on your Windows machine (e.g. `C:\Users\Stan\projects\lattice\`).
2. Place `SPEC.md` and `lattice_ui_mockup.html` (renamed if needed) in that directory.
3. Open Claude Code in that directory: `claude` (from the terminal in that folder).
4. Paste the entire prompt below as your first message.
5. Attach `SPEC.md` and `lattice_ui_mockup.html` to that message.
6. Claude Code executes phase 2A, stops, awaits your approval. Repeat for each phase.

---

## PROMPT TO PASTE BEGINS BELOW

---

You are building **Lattice**, a personal optimization system for a single user (Stan) running on Windows. The full specification is in the attached `SPEC.md`. The web UI visual reference is in the attached `lattice_ui_mockup.html`. **Read both files in full before writing any code.** They are the contract.

## Operating principles (non-negotiable)

1. **SPEC.md is the source of truth.** Do not invent fields, endpoints, table columns, function behaviors, or scope items not in SPEC.md. If something is ambiguous in SPEC.md, ask before deciding.

2. **The UI mockup is the visual reference.** During the frontend phase, your SvelteKit implementation must match the mockup's layout, components, type scale, color tokens, and information density. Translate the vanilla HTML/JS structure into idiomatic SvelteKit 5; do not redesign.

3. **Build in strict phase order (SPEC.md Section 12).** Phases 2A through 2J. Do not interleave. Do not start a phase before the previous one is verified.

4. **Stop after every phase and await user approval before continuing.** This is the most important rule. After completing each phase's deliverables and running its verify step, summarize what was built, what the verify result was, and what's next. Then stop. Do not proceed to the next phase until the user explicitly says to.

5. **Maintain `PLAN.md` at the repo root.** Update it as you go. Use it as a checklist with phase status (pending / in-progress / done / verified).

6. **No silent decisions.** If you encounter a choice not covered by SPEC.md (library version conflicts, Windows path edge cases, library API changes since SPEC.md was written), ask. Do not pick silently. Examples that warrant a question: the `garminconnect` library exposes a different method name than expected; a Pydantic v2 vs v1 syntax difference matters for the schemas; the user's Python version on Windows is older than 3.11.

7. **Verify steps are not optional.** Each phase in SPEC.md Section 12 has a "Verify" condition. Run it. Report the actual output. If it fails, fix before claiming the phase is done.

## Initial setup (do this first, before phase 2A)

Before any code, do this once:

1. **Read** `SPEC.md` and `lattice_ui_mockup.html` end to end.
2. **Confirm understanding** by summarizing back to the user in 5-10 bullet points: what Lattice is, the tech stack, the two recommendation paths (F9a deterministic, F9b LLM second opinion), the phase order, and any spec ambiguities you noticed.
3. **List any questions** that need answering before phase 2A. Do not assume; ask.
4. **Wait** for the user's go-ahead before creating any files.

## Repository conventions (write these into `CLAUDE.md` at the repo root)

Create `CLAUDE.md` during phase 2A. It must contain:

```markdown
# Lattice — Claude Code Conventions

## Reading order for any session
1. Read `SPEC.md` for current scope
2. Read `PLAN.md` for current phase state
3. Read this file for conventions

## Python (backend, bot)
- Python 3.11+, type hints required on all public functions and class methods
- `uv` for dependency management
- Async-first: FastAPI async routes, SQLAlchemy async sessions, httpx for HTTP
- `ruff` for linting + formatting; `mypy --strict` clean on `lattice/` and `lattice_bot/`
- No global state in `functions/`; pure functions take DB session + params
- Pydantic v2 for all request/response schemas in `schemas/`
- Use `pathlib.Path` for all file paths; never hardcode `/` separators
- Token cache and credential paths use `%USERPROFILE%`; resolve with `Path.home()`
- All datetime values stored in DB as ISO 8601 strings with TZ offset
- Logging via stdlib `logging`, configured in `config.py`, rotating files in `logs/`

## SvelteKit (frontend)
- SvelteKit 5 with runes (`$state`, `$derived`, `$effect`, `$props`)
- No Svelte 4 patterns (`export let`, reactive `$:`, stores-as-default-state)
- TypeScript strict mode
- TailwindCSS 4 utility classes; no custom CSS unless unavoidable
- Component types from `$lib/api/types.ts`, generated to mirror backend Pydantic schemas
- ECharts for charts via `svelte-echarts` or direct binding
- No third-party UI component libraries; build primitives in `$lib/components/ui/`

## Git
- Conventional commits: `feat:`, `fix:`, `chore:`, `refactor:`, `docs:`, `test:`
- One logical change per commit
- Branch off `main`; no PR workflow needed (single dev), commit to `main` directly
- `.gitignore` covers `.env`, `data/`, `logs/`, `__pycache__/`, `node_modules/`, `.venv/`, `dist/`, `.svelte-kit/`, OAuth tokens

## Testing
- pytest for backend; tests live in `backend/tests/` mirroring source structure
- Unit tests required for all F1–F5, F8, F9a rule tables
- Schema round-trip tests for all Pydantic models
- No integration tests against live Garmin/Google/DeepSeek in v1 (manual verification)
- Frontend tests not required in v1

## Error handling
- Integration errors (Garmin, Google, DeepSeek) log at WARNING with full context
- Authentication errors log at ERROR and trigger Discord DM to user
- Never silently swallow exceptions
- HTTP errors return appropriate status codes with structured error bodies:
  `{ "error": "code", "message": "human readable", "details": {...} }`

## File naming
- Python: `snake_case.py`
- Svelte components: `PascalCase.svelte`
- Routes: `+page.svelte`, `+layout.svelte` per SvelteKit convention
- Tests: `test_<module>.py`
```

## `PLAN.md` template (write this during phase 2A)

```markdown
# Lattice — Build Plan

Strict phase order. Each phase verified before next begins.

## Phase 2A — Scaffolding
Status: pending
- [ ] Directory structure per SPEC.md Section 3
- [ ] `pyproject.toml` for backend (uv)
- [ ] `pyproject.toml` for bot (uv)
- [ ] SvelteKit project init in `frontend/`
- [ ] `.env.example`, `.gitignore`, `README.md` stub
- [ ] Alembic init + first migration creating all tables from SPEC.md Section 4
- [ ] FastAPI app with `/api/health` endpoint returning `200 {"status": "ok"}`
- [ ] SvelteKit project renders blank login route at `/login`
- [ ] `start.bat` launches backend and SvelteKit dev in two separate terminal windows
- [ ] `CLAUDE.md` created with conventions
- [ ] `PLAN.md` created (this file)
Verify:
- [ ] `curl http://localhost:8000/api/health` returns 200
- [ ] `http://localhost:5173/login` renders without console errors

## Phase 2B — Garmin integration
Status: pending
- [ ] `integrations/garmin.py` wrapping garminconnect with auth caching
- [ ] All metric pulls per SPEC.md Section 8.1
- [ ] `sync/garmin_sync.py` idempotent UPSERT into `metrics`
- [ ] APScheduler hourly job
- [ ] API: `GET /api/metrics`, `GET /api/metrics/latest`, `GET /api/metrics/baseline`, `POST /api/sync/garmin`
- [ ] Pydantic schemas in `schemas/metrics.py`
Verify:
- [ ] `POST /api/sync/garmin` against real Garmin credentials returns metrics_written > 0
- [ ] `GET /api/metrics/latest?names=sleep_score,hrv_overnight_avg,resting_hr` returns recent values
- [ ] Re-running sync does not create duplicate rows (idempotency check)

## Phase 2C — Calendar integration
Status: pending
[fill in per SPEC.md Section 8.2 and 5.4]

## Phase 2D — Entries + habits
[per SPEC.md 4.1, 4.5, 4.6, 5.2]

## Phase 2E — Deterministic functions F1–F5, F8, F9a
[per SPEC.md Section 6]

## Phase 2F — Frontend
[per UI mockup, SPEC.md Section 11 IN list]

## Phase 2G — Discord bot skeleton
[per SPEC.md 8.4]

## Phase 2H — LLM integration (F9a paraphrase + F9b second opinion)
[per SPEC.md Section 7]

## Phase 2I — Briefings + F7 weekly report
[per SPEC.md 8.4 briefings, Section 6 F7]

## Phase 2J — Polish
[per SPEC.md Section 12]
```

Fill in details for each phase as you reach it; do not pre-fill the whole document.

## Phase execution protocol

For each phase 2A through 2J:

1. **Pre-flight:** re-read the relevant SPEC.md sections for the phase. State which sections you're using.
2. **Plan:** list the files you will create or modify in this phase.
3. **Execute:** create / modify the files. Run any necessary commands (migrations, package installs, etc.).
4. **Verify:** run the verify step from SPEC.md Section 12 for this phase. Paste the actual output.
5. **Update `PLAN.md`:** check off completed items, set phase status to "done — awaiting verification".
6. **Summarize and stop:**
   - What was built
   - Verify command output
   - Any deviations from SPEC.md and why
   - Any questions
   - **"Phase 2X complete. Awaiting your approval to proceed to phase 2Y."**
7. **Wait.** Do not start the next phase until the user types "proceed", "go", "continue", or similar approval.

## Phase-specific guidance

### Phase 2A — Scaffolding
- Use `uv init` for backend and bot.
- Use `npm create svelte@latest frontend` (TypeScript, no demo app, ESLint, Prettier, Tailwind plugin if available; otherwise install Tailwind 4 manually).
- Alembic: `alembic init alembic` inside `backend/`. Configure `env.py` to import models from `lattice.models`.
- First migration creates ALL tables from SPEC.md Section 4 in one revision. Do not split.
- `start.bat` should use `start` command with appropriate titles:
  ```bat
  @echo off
  start "Lattice Backend" cmd /k "cd backend && uv run uvicorn lattice.main:app --reload --port 8000"
  start "Lattice Frontend" cmd /k "cd frontend && npm run dev"
  start "Lattice Bot" cmd /k "cd bot && uv run python -m lattice_bot.main"
  ```
  (Bot terminal will fail until phase 2G; that's expected. Document this in README.)

### Phase 2B — Garmin
- Use `garminconnect` library, current 0.3.x.
- Auth flow uses `garth` under the hood. Token cache lives at `Path.home() / ".garminconnect"`.
- Wrap all library calls in try/except for `GarminConnectAuthenticationError` and `GarminConnectConnectionError`.
- The sync function takes a date or date range and returns a list of `Metric` rows to upsert. Keep the integration layer thin; conversion logic lives in `sync/garmin_sync.py`.
- For idempotency, use SQLAlchemy's `dialect.insert(...).on_conflict_do_update()` for SQLite. Unique constraint is `(metric_name, timestamp, source)`.
- Pull at least: sleep, HRV, RHR, body battery, stress, activities (last 7 days), training status.

### Phase 2C — Calendar
- `credentials.json` lives at `backend/lattice/integrations/credentials.json`, gitignored.
- `token.json` lives at `Path.home() / ".lattice" / "google_token.json"`, gitignored.
- On first run, if `token.json` doesn't exist, the integration should print a clear message: "Run `uv run python -m lattice.integrations.google_calendar init` to authorize."
- Implement that init command as a module-level entry point.
- Cache layer: when `/api/calendar/events` is called, check `calendar_cache.fetched_at`; if < 5 min, return cached; else fetch from Google and upsert.

### Phase 2D — Entries + habits
- Pydantic schemas for each entry type's `data` JSON. Validate on POST.
- For each entry `type`, the `data` field accepts only the schema for that type (use Pydantic discriminated unions).
- `GET /api/entries` supports filtering by type, date range, full-text search (use SQLite FTS5 if simple; else LIKE on description/note fields).

### Phase 2E — Functions
- Each function module exports a single function plus its Pydantic output schema.
- Functions take `(db: AsyncSession, **params)` and return the schema.
- Unit tests live at `backend/tests/test_functions/`. Use fixtures for seeded metric data.
- For F1 readiness: test the weighted-composite math at minimum, with edge cases for missing data and `<7 days history → provisional`.
- For F9a: test each rule table per intent. At least 2 test cases per rule (firing condition + non-firing condition).
- F9a's `get_advice(intent, date)` is a thin orchestrator that calls F1, F2, F3, F4 as needed and applies the rule table.

### Phase 2F — Frontend
- This is the largest phase. Break into sub-tasks; commit after each route.
- Order: `/login`, layout + sidebar, `/` (Today dashboard), `/trends`, `/log`, `/habits`, `/report`.
- Generate `$lib/api/types.ts` from backend Pydantic schemas — either manually (smaller surface) or via FastAPI's OpenAPI schema + a generator like `openapi-typescript`. Manual is fine for v1.
- ECharts: install `svelte-echarts` or use ECharts directly. Wrap chart components in `$lib/components/charts/` with typed props.
- Match the mockup: dark mode default, the color tokens from the mockup, type scale, spacing, component shapes. Do not redesign.
- Loading states use skeletons matching mockup. Empty states match mockup. Error states match mockup.
- Auth: simple POST to `/api/auth/login`; on success, navigate to `/`; cookie is set by backend, no client-side token handling.
- All API calls go through a typed client in `$lib/api/client.ts` that handles errors uniformly.

### Phase 2G — Discord bot skeleton
- Bot runs as separate process. Reads `DISCORD_BOT_TOKEN` and `BOT_SHARED_SECRET` from `.env`.
- Backend client uses httpx with `X-Bot-Token` header.
- Implement slash commands: `/today`, `/log <type> <args>`, `/sync`, `/report`.
- DM handler: for now, echo received messages with metadata (user, timestamp) plus a note "LLM not yet wired (phase 2H)."
- Use `discord.py` 2.x with intents: `message_content` (privileged), `members` (privileged), `guilds`.

### Phase 2H — LLM integration
- Use `openai` Python SDK pointed at `https://api.deepseek.com`.
- `llm/client.py` exposes `chat_completion(messages, model, tools, thinking)`.
- `llm/tools.py` defines all tool schemas from SPEC.md Section 7.1 in OpenAI tool format.
- `llm/router.py` is the heart of this phase. It:
  1. Receives the user message + session_id
  2. Loads conversation history from DB (last 30 min)
  3. Classifies intent (rule-based keyword match — "when should I", "should I", "what do you think", etc.) → determines model + thinking flag + whether F9b path is required
  4. Calls LLM with tools
  5. Executes returned tool calls (with confirmation policy from Section 7.2)
  6. If multiple turns needed (LLM wants to chain tool calls), iterate up to 5 round trips
  7. For F9b path: validates output structure ("Algorithm recommends" + "My take" present); if missing, fall back to F9a paraphrase
  8. Returns final reply + audit trail of tool calls and actions taken
- System prompt template lives in `llm/prompts.py`, format string with `{current_datetime}`, `{timezone}`, `{user_name}`.
- Wire bot's DM handler to `POST /api/chat`.
- Test: send "log coffee" → entry appears. Send "when should I learn?" → F9a paraphrase reply. Send "what do you think about learning today?" → F9b structured reply with "Algorithm recommends" and "My take" sections.

### Phase 2I — Briefings + weekly report
- Morning brief job in bot process (APScheduler): 07:30 daily. Calls backend `/api/functions/readiness`, `/api/functions/advisor?intent=learn`, `/api/functions/advisor?intent=train`, formats Discord embed, DMs user.
- Evening brief: 21:00 daily. Calls `/api/functions/sleep_window`, `/api/functions/caffeine_status`, today's entries summary, formats and DMs.
- F7 weekly report: Sunday 22:00. Backend job. Two stages:
  1. Python computes the stat layer (averages, best/worst day, correlations, deltas)
  2. DeepSeek v4-pro with thinking generates the prose summary from structured input
  - Output stored in `weekly_reports` table (add to migration if not present; otherwise serialize as JSON in a generic `reports` table — decide and update SPEC.md if you add a table)
- `/report` page in frontend renders latest by default, with week selector.

### Phase 2J — Polish
- Logging configured: rotating file handler in `logs/backend.log` and `logs/bot.log`, 10MB per file, 5 backups.
- Frontend error pages: 404, 500, network error states.
- README.md filled in: setup steps for all integrations (Garmin, Google, Discord, DeepSeek), how to run, how to back up `data/lattice.db`.
- Final smoke test: cold start the system, sync Garmin, view dashboard, log a meal via Discord, ask for a recommendation via Discord (both F9a and F9b paths), trigger a weekly report manually, view it in the UI.

## Things you must NOT do

- **Do not invent scope.** No food photo upload UI. No F6, F7-other-than-spec, F10. No multi-user. No mobile responsive design. No Docker. No tests for the LLM layer beyond contract tests for the router.
- **Do not mock Garmin/Google/DeepSeek for development.** Use real credentials from `.env`. If credentials aren't available, ask the user; don't fake responses.
- **Do not skip the verify step** to claim a phase is done.
- **Do not "improve" SPEC.md decisions** mid-build (changing the readiness weights, adding a feature you think is missing, swapping libraries). If you think the spec is wrong, raise it as a question, don't act on it.
- **Do not over-engineer the frontend.** No state management library (Svelte 5 runes are sufficient). No animation libraries. No service workers. No PWA features.
- **Do not optimize prematurely.** No caching layers beyond what SPEC.md mandates. No background workers beyond APScheduler. No Redis. No message queues. SQLite + APScheduler + two Python processes + one SvelteKit dev server is the entire deployment.
- **Do not write to files in `/mnt/` or `/usr/` or `/etc/`.** This is a Windows machine, but more importantly, all project files live under the project root.
- **Do not commit secrets.** `.env` is gitignored. `credentials.json` is gitignored. `token.json` is gitignored. Verify with `git status` before any commit.

## Failure modes you should expect

- **`garminconnect` library breaks on Garmin auth update.** Reported in their GitHub issues. When it happens, check the library's latest release; usually a patch is out within days. Mitigation: wrap library calls so user gets a clear DM, not a silent failure.
- **Google OAuth flow needs the user's browser.** First-time setup requires running an init command interactively. Document this clearly in README.
- **DeepSeek API rate limits or transient 500s.** Build retry once on 5xx; on persistent failure, the bot replies with raw deterministic data and "AI offline" note. Never block deterministic queries on LLM availability.
- **SvelteKit dev hot-reload races with backend restart.** Frontend should retry API calls on network error with exponential backoff (max 3 attempts).
- **APScheduler in Windows with `--reload`.** Uvicorn's reload mode can spawn duplicate schedulers. In dev, set `LATTICE_DISABLE_SCHEDULER=true` to avoid this; only run scheduler in production-mode launch (no reload). Document in README.

## Communication style during the build

- Concise. No filler. The user prefers direct technical communication.
- Show actual command output for verify steps, not paraphrased summaries.
- When you have a question, ask one question with a clear default suggestion. Don't ask three open-ended questions in a row.
- Use code blocks for code, paths, and commands. Use prose for explanations and decisions.
- After each phase: short summary, verify output, explicit "awaiting approval" line.

## Begin

Now: read `SPEC.md` and `lattice_ui_mockup.html` end to end. Then summarize them back as instructed in the "Initial setup" section above. List any questions. Wait for approval before phase 2A.

---

## PROMPT TO PASTE ENDS HERE
