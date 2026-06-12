# Lattice — Project Specification (v1)

**Status:** Original v1 spec. Partly superseded — see the **amendment** below and
`PLAN.md` → *Rework R (Coherence)* for the current architecture.
**Owner:** Stan (single user)
**Target platform:** ~~Windows~~ → now runs on a Raspberry Pi via `start.sh`.
**Visibility:** Private repo (GitHub possible, not public)

> ### Amendment (2026-06-03): AI-as-brain
> Section 1 below says the LLM is *"an interface and synthesis layer, never the reasoning
> core."* After two weeks of real use this was **reversed**. The AI is now the single brain:
> it owns one stored recommendation (the `recommendations` keyed store) that the website,
> Discord briefs, and chat all read, so the surfaces can no longer disagree. The deterministic
> functions (readiness, sleep window F4, advisor F9a, etc.) remain — but as **inputs the AI
> weighs**, not as competing displayed answers. The three fixed Discord briefings are replaced
> by user-configurable **routines** (scheduled AI check-ins + reminders, each with per-routine
> proactive chattiness). Subsystems added since this spec was frozen and not described below:
> recommendations store, routines, alerts UI/tools, custom algorithms, dashboard cards, user
> memory, research agent, nutrition. See `PLAN.md` for all of them.

---

## 1. Summary

Lattice is a single-user personal optimization system. It aggregates biometric data (Garmin Fenix 6 via Garmin Connect), calendar data (Google Calendar), and manual life-logging entries (food, drinks, mood, energy, notes, habits) into a unified backend. It exposes them through:

- **Discord bot** — primary daily interface; chat input, queries, scheduled briefings
- **Web UI** — secondary review interface; dashboards, trend graphs, history, manual entry fallback

Lattice computes deterministic scoring functions (readiness, optimal work window, training recommendation, sleep window, caffeine cutoff, habit adherence) entirely in Python. An LLM (DeepSeek) is used **only** for natural-language chat parsing, the scheduling assistant, and the weekly synthesis report. The LLM is an interface and synthesis layer, never the reasoning core.

---

## 2. Tech Stack (locked)

| Layer | Choice | Rationale |
|---|---|---|
| Language (backend) | Python 3.11+ | Match Stan's existing CT-2-WebUI stack |
| Backend framework | FastAPI | Async-first, OpenAPI built-in |
| Database | SQLite (WAL mode) | Single-user, file-based, zero ops |
| ORM | SQLAlchemy 2.x async | Standard, future-proof |
| Migrations | Alembic | Schema versioning |
| Frontend | SvelteKit 5 (runes) + TypeScript | Match Stan's existing CT-2-WebUI stack |
| Styling | TailwindCSS 4.x | Standard, fast |
| Charts | ECharts (preferred) or Chart.js | Lightweight, no React dep |
| Discord bot | discord.py 2.x | Async, mature |
| LLM provider | DeepSeek API (v4) | Existing billing |
| LLM SDK | `openai` Python SDK | DeepSeek is OpenAI-compatible |
| Garmin | `garminconnect` (cyberjunky) 0.3.x | Only viable free option |
| Google Calendar | `google-api-python-client` + `google-auth-oauthlib` | Official |
| Scheduling | APScheduler 3.x | In-process, no broker |
| HTTP client | `httpx` | Async-friendly |
| Bot ↔ backend | HTTP over localhost | Separate processes |
| Process management | `start.bat` launching two terminals | Windows-native |
| Reverse access (optional) | Tailscale | Phone access without exposing ports |
| Python deps manager | `uv` | Fast, simple |
| Vision (deferred) | Pluggable interface | Not built in v1 |

---

## 3. Directory Layout

```
lattice/
├── README.md
├── SPEC.md                          ← this file
├── CLAUDE.md                        ← conventions for Claude Code
├── PLAN.md                          ← sub-phase tracker (Claude Code maintains)
├── UI_REFERENCE/                    ← Claude Design output dropped here
│   └── (artifact files from Claude Design)
├── .env.example
├── .env                             ← gitignored
├── .gitignore
├── start.bat                        ← launches backend + bot in two terminals
│
├── data/                            ← gitignored
│   └── lattice.db                   ← SQLite
│
├── logs/                            ← gitignored
│   ├── backend.log
│   └── bot.log
│
├── backend/
│   ├── pyproject.toml
│   ├── alembic.ini
│   ├── alembic/versions/
│   ├── lattice/
│   │   ├── main.py                  ← FastAPI entry, serves built frontend in prod
│   │   ├── config.py                ← pydantic-settings
│   │   ├── db.py                    ← engine + session
│   │   ├── auth.py                  ← single-password session auth
│   │   ├── models/                  ← SQLAlchemy ORM
│   │   ├── schemas/                 ← Pydantic request/response
│   │   ├── api/                     ← FastAPI routers
│   │   ├── functions/               ← F1-F5, F8, F9a deterministic logic
│   │   ├── integrations/            ← garmin, google_calendar, deepseek
│   │   ├── sync/                    ← APScheduler jobs
│   │   ├── llm/                     ← client, tool schemas, router, prompts, F7
│   │   └── utils/
│   └── tests/
│
├── bot/
│   ├── pyproject.toml
│   ├── lattice_bot/
│   │   ├── main.py                  ← discord.py entry; DM listener → /api/chat
│   │   ├── config.py
│   │   ├── backend_client.py        ← httpx → backend
│   │   ├── briefings.py             ← morning + evening (lands in 2I)
│   │   └── formatters.py            ← Discord 2000-char split
│   └── tests/
│
└── frontend/
    ├── package.json
    ├── svelte.config.js, vite.config.ts, tailwind.config.js, tsconfig.json
    └── src/
        ├── app.html, app.css
        ├── routes/
        │   ├── +layout.svelte
        │   ├── +page.svelte         ← Today dashboard
        │   ├── trends/+page.svelte
        │   ├── log/+page.svelte     ← entries browser
        │   ├── habits/+page.svelte
        │   ├── report/+page.svelte  ← weekly report
        │   └── login/+page.svelte
        └── lib/
            ├── api/{client.ts, types.ts}
            ├── components/{dashboard, charts, entries, ui}
            └── stores/
```

---

## 4. Data Model

SQLite, WAL mode. Timestamps as ISO 8601 strings with TZ offset.

### 4.1 `entries` — generic event log

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | autoincrement |
| timestamp | TEXT NOT NULL | when event happened |
| logged_at | TEXT NOT NULL | when entry was created |
| type | TEXT NOT NULL | `food`/`drink`/`mood`/`energy`/`focus`/`symptom`/`note`/`workout_manual` |
| data | TEXT NOT NULL | JSON, schema varies by type |
| source | TEXT NOT NULL | `discord`/`web` |

Indexes: `(type, timestamp)`, `(timestamp)`

### 4.2 `metrics` — time-series numeric data

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| timestamp | TEXT NOT NULL | reference moment |
| metric_name | TEXT NOT NULL | enum below |
| value | REAL NOT NULL | |
| unit | TEXT NULL | "ms", "bpm", "%", "score" |
| source | TEXT NOT NULL | `garmin`/`manual`/`derived` |
| metadata | TEXT NULL | optional JSON (e.g. sleep stages) |

Indexes: `(metric_name, timestamp)`, `(timestamp)`
Unique: `(metric_name, timestamp, source)`

**Metric names:**
`sleep_score`, `sleep_duration_min`, `sleep_deep_min`, `sleep_light_min`, `sleep_rem_min`, `sleep_awake_min`, `sleep_start_time`, `sleep_end_time`, `sleep_efficiency`, `avg_sleep_hr`, `avg_sleep_stress`, `restless_moments_count`, `hrv_overnight_avg`, `hrv_status`, `resting_hr`, `hr_max_day`, `hr_min_day`, `hr_avg_day`, `body_battery_start`, `body_battery_end`, `body_battery_min`, `body_battery_charged`, `body_battery_drained`, `stress_avg`, `stress_max`, `stress_rest_min`, `stress_low_min`, `stress_medium_min`, `stress_high_min`, `training_load_acute`, `training_load_chronic`, `training_status`, `vo2_max`, `respiration_avg`, `spo2_avg`, `steps`, `active_minutes`, `calories_active`, `calories_total`, `intensity_minutes_moderate`, `intensity_minutes_vigorous`, `floors_climbed`, `distance_m`, `readiness_score` (derived)

**Time-of-day metrics** (`sleep_start_time`, `sleep_end_time`):
- `value` = minutes past the **event's own local midnight** (range 0–1439).
  Example: bedtime 23:45 → 1425; wake 06:30 → 390; bedtime 00:30 → 30.
- Full ISO local timestamp is stashed in `metadata.iso_local` for callers
  that need the wraparound-aware moment (e.g., bed-to-wake duration).
- Anchored at midnight of the **wake day** (so `sleep_end_time` and
  `sleep_start_time` for the same night share the same row timestamp).

### 4.3 `calendar_cache` — Google Calendar snapshot

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| google_event_id | TEXT NOT NULL UNIQUE | for upserts |
| start | TEXT NOT NULL | |
| end | TEXT NOT NULL | |
| title | TEXT NOT NULL | |
| description | TEXT NULL | |
| location | TEXT NULL | |
| is_all_day | INTEGER NOT NULL DEFAULT 0 | |
| fetched_at | TEXT NOT NULL | for TTL |

5-minute TTL.

### 4.4 `conversations` — Discord chat memory

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| timestamp | TEXT NOT NULL | |
| role | TEXT NOT NULL | `user`/`assistant`/`tool` |
| content | TEXT NOT NULL | |
| tool_calls | TEXT NULL | JSON |
| session_id | TEXT NOT NULL | resets after 30 min idle |

Retention: 30 days. Pruned nightly.

### 4.5 `habit_definitions` + `habit_checkins`

`habit_definitions`: `id`, `name UNIQUE`, `target_per_week INT DEFAULT 7`, `active BOOL DEFAULT 1`, `created_at`.

`habit_checkins`: `id`, `habit_id FK`, `date YYYY-MM-DD`, `completed BOOL`, `note TEXT NULL`. Unique `(habit_id, date)`.

### 4.6 `weekly_reports` — F7 storage

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | |
| iso_week | TEXT NOT NULL UNIQUE | e.g. `2026-W19` |
| generated_at | TEXT NOT NULL | ISO 8601 with TZ offset |
| model_used | TEXT NOT NULL | e.g. `deepseek-v4-pro` or `deterministic-only` |
| stats_json | TEXT NOT NULL | Stage A pre-computed statistics |
| summary_text | TEXT NOT NULL | Stage B LLM prose, ≤200 words |

### 4.10 `sleep_stages` — per-night stage timeline

One row per stage segment within a night, parsed from Garmin's `sleepLevels`
array. Lets the analytical surface answer "when does first deep sleep
occur?", "how many wake events?", "what's the longest deep block?" — none
of which are answerable from the daily aggregates alone.

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | autoincrement |
| night_date | TEXT NOT NULL | YYYY-MM-DD of the WAKE date |
| start | TEXT NOT NULL | ISO 8601 with TZ (local) |
| end | TEXT NOT NULL | ISO 8601 with TZ (local) |
| stage | TEXT NOT NULL | `awake` \| `light` \| `deep` \| `rem` |
| duration_min | REAL NOT NULL | |

Indexes: `(night_date)`, `(start)`. Unique: `(night_date, start, stage)`.

### 4.9 `metric_samples` — intra-day Garmin samples

Separate from `metrics` (daily aggregates). One row per measurement; keyed
on `(metric_name, timestamp, source)` so re-syncs are idempotent.

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | autoincrement |
| timestamp | TEXT NOT NULL | ISO 8601 with TZ offset (local) |
| metric_name | TEXT NOT NULL | enum: `hr`, `stress`, `body_battery` |
| value | REAL NOT NULL | |
| source | TEXT NOT NULL | `garmin` |

Indexes: `(metric_name, timestamp)`, `(timestamp)`. Unique: `(metric_name, timestamp, source)`.

Sample density (per day):
- `hr`: ~1 row per 2 minutes (~720/day)
- `stress`: ~1 row per 3 minutes (~480/day)
- `body_battery`: ~1 row per 3 minutes (~480/day)

A full year of sync ≈ 600k rows total; SQLite handles this comfortably.

### 4.8 `workouts` — Garmin-synced activities

Distinct from `entries.type='workout_manual'` (user-logged). One row per
Garmin activity, keyed on `garmin_activity_id` so re-syncs are idempotent.

| Column | Type | Notes |
|---|---|---|
| id | INTEGER PK | autoincrement |
| garmin_activity_id | TEXT NOT NULL UNIQUE | stable id from Garmin |
| start | TEXT NOT NULL | ISO 8601 with TZ offset (local) |
| duration_min | REAL NOT NULL | |
| kind | TEXT NOT NULL | `activityType.typeKey` (e.g. `running`, `cycling`, `strength_training`) |
| distance_m | REAL NULL | metres; null for non-distance activities |
| avg_hr | REAL NULL | bpm |
| max_hr | REAL NULL | bpm |
| calories | REAL NULL | kcal |
| training_effect | REAL NULL | aerobic training effect (0–5) |
| metadata | TEXT NULL | optional JSON (activity name, anaerobic effect, etc.) |

Indexes: `(start)`, `(kind, start)`

### 4.7 Entry `data` JSON schemas

```jsonc
food:     { "description": "string", "meal_type": "breakfast|lunch|dinner|snack|null" }
drink:    { "kind": "coffee|alcohol|water|tea|other", "volume_ml": null|number, "count": null|number }
mood:     { "score": 1-5, "note": "string|null" }
energy:   { "score": 1-5, "note": "string|null" }
focus:    { "score": 1-5, "session_duration_min": null|number, "task": "string|null" }
symptom:  { "tag": "headache|fatigue|gut|other", "severity": 1-5, "note": "string|null" }
note:     { "text": "string" }
workout_manual: { "kind": "string", "duration_min": number, "intensity": "low|medium|high", "note": "string|null" }
```

---

## 5. REST API Contracts

Base: `http://localhost:8000/api/`
Auth: session cookie OR `X-Bot-Token` header (bot only).

### 5.1 Auth
```
POST /auth/login          { password } → 200 + cookie | 401
POST /auth/logout         → 204
GET  /auth/status         → { authenticated: bool }
```

### 5.2 Entries
```
GET    /entries?type=&from=&to=&limit=&offset=   → { items: Entry[], total }
POST   /entries           { type, timestamp?, data, source }     → Entry
PATCH  /entries/:id       partial → Entry
DELETE /entries/:id       → 204
```

### 5.3 Metrics
```
GET /metrics?name=&from=&to=                → { items: Metric[] }
GET /metrics/latest?names=name1,name2,...   → { [name]: Metric }
GET /metrics/baseline?name=&days=14         → { mean, sd, n }
```

### 5.4 Calendar
```
GET    /calendar/events?from=&to=    → CalendarEvent[]
GET    /calendar/freebusy?from=&to=  → BusyInterval[]
POST   /calendar/events              { title, start, end, description?, location? } → CalendarEvent
PATCH  /calendar/events/:id          partial → CalendarEvent
DELETE /calendar/events/:id          → 204
POST   /calendar/sync                → { refreshed: number }
```

### 5.5 Functions
```
GET /functions/readiness?date=                          → ReadinessOutput
GET /functions/work_windows?date=&min_minutes=60        → WorkWindowsOutput
GET /functions/training_recommendation?date=            → TrainingRecOutput
GET /functions/sleep_window?date=                       → SleepWindowOutput
GET /functions/caffeine_status?at=                      → CaffeineStatusOutput
GET /functions/advisor?intent=&date=                    → AdvisorOutput  (F9a)
GET /functions/habits/adherence?from=&to=               → HabitAdherenceOutput
```

### 5.6 Chat
```
POST /chat                { session_id, message }
                          → { reply, tool_calls, actions_taken }
```

### 5.7 Reports
```
GET  /reports/weekly/latest        → WeeklyReport
GET  /reports/weekly?week=YYYY-Www → WeeklyReport
POST /reports/weekly/generate      → WeeklyReport
```

### 5.8 Sync (manual triggers)
```
GET  /sync/status         → { garmin_last_metric_at, calendar_last_fetched_at }
POST /sync/garmin?days=N  → { metrics_written, workouts_written, dates[], errors[] }
POST /sync/garmin/stream?days=N
                          → SSE: text/event-stream, one `data:` event per day:
                            {type:"progress", day, done, total, metrics_written, workouts_written, errors[]}
                            then {type:"done", metrics_total, workouts_total, total}
                            (or {type:"error", code, message} on fatal auth failure).
POST /sync/calendar       → { events_refreshed: number }
```

`days` is capped at 400 (covers 1 year + slack for historical backfill).

---

## 6. Function Specifications

### F1 — Daily Readiness Score
**Inputs:** `hrv_overnight_avg`, `sleep_score`, `resting_hr`, `body_battery_start`, `stress_avg` (yesterday), plus 14-day baselines for HRV and RHR.
**Algorithm:**
1. `hrv_z = clamp((hrv_today − mean_hrv_14d) / sd_hrv_14d, -2, +2)`; `rhr_z = clamp(-(rhr_today − mean_rhr_14d) / sd_rhr_14d, -2, +2)` (negated; lower RHR is better).
2. Map z → 0-1 via `(z + 2) / 4`.
3. `sleep_c = sleep_score / 100`, `bb_c = body_battery_start / 100`, `stress_c = 1 − stress_yesterday / 100`.
4. `raw = 0.40·hrv + 0.30·sleep_c + 0.15·rhr + 0.10·bb_c + 0.05·stress_c`
5. `score = round(raw · 100)`
6. Category: ≥80 peak / 65–79 solid / 50–64 average / 35–49 low / <35 depleted.
**Missing data:** renormalize weights, flag in `explanation`. <7 days history → `provisional`.

### F2 — Optimal Work Window
**Inputs:** today's calendar busy intervals, today's readiness, last 30d `focus` entries, Body Battery curve.
**Algorithm:**
1. Find calendar gaps ≥ `min_minutes`.
2. Score each:
   - 40%: time-of-day match to historical peak focus hour (mean hour weighted by focus score).
   - 30%: today's readiness score.
   - 20%: linear-interp Body Battery prediction at window midpoint.
   - 10%: ≥30 min spacing from meals/workouts.
3. Top 3 returned.

### F3 — Training Recommendation
**Inputs:** readiness, `training_load_acute`, `training_load_chronic`, last workout date, today's meeting hours.
**Algorithm:**
1. `ac_ratio = acute / chronic` (chronic=0 → easy, low confidence).
2. readiness <40 → **rest**.
3. ac_ratio >1.5 → **easy**.
4. ac_ratio <0.8 AND readiness >60 → **moderate**.
5. readiness >75 AND days_since_hard ≥2 → **hard**.
6. Else → **moderate**.
7. Cap one level if meeting_hours_today >4.

### F4 — Sleep Window
**Inputs:** tomorrow's first event, optimal_sleep_duration (median sleep on days with next-day readiness ≥65; fallback 7.5h), today's caffeine entries, today's late workouts.
**Algorithm:**
1. `wake = first_event_tomorrow − 30 min`
2. `bedtime = wake − optimal_sleep_duration`
3. Flags: caffeine after 14:00, high-intensity workout within 3h of bedtime.

### F5 — Caffeine Cutoff Advisor
**Inputs:** current time, planned bedtime (from F4), today's coffee entries.
**Algorithm:**
1. Half-life 5h, default dose 80mg per cup.
2. Existing residual at bedtime: sum over all existing cups `dose · 0.5^(hours_until_bed / 5)`.
3. If new cup at `at` would push bedtime residual >50mg → not OK.
4. `last_call_minutes`: latest moment a new cup keeps residual ≤50mg.

### F7 — Weekly Pattern Report (LLM-assisted)
**Stage A — Python stats:**
- Daily averages: sleep, HRV, RHR, stress, readiness.
- Best/worst day (by readiness).
- Habit adherence per habit.
- Correlations (Pearson) if `|r|>0.5` and n≥5: caffeine-time × sleep_score, workout-intensity × next-day-HRV, meeting-hours × energy.
- Weekly mean shifts vs 4-week trailing (flag if >1 SD).

**Stage B — DeepSeek v4-pro thinking:** receives structured JSON + the weekly report prompt (Section 7.5). Token output capped at 1000. The LLM cannot invent correlations or recommend anything outside the structured input.

### F8 — Habit Adherence
Pure SQL. Current streak (consecutive days ending today with `completed=1`), longest streak, week % vs `target_per_week`.

### F9a — Intent-Based Advisor (deterministic algorithm)

This is the **canonical recommendation**. Surfaced in web UI dashboard and via `/today` slash command. The LLM does not modify its output — it can only quote it (in F9b) when relevant.

**Endpoint:** `GET /api/functions/advisor?intent=&date=`

**Intent enum:** `learn` | `train` | `rest` | `creative` | `meeting` | `physical_task`

**Inputs:** intent, readiness (F1), work windows (F2), training rec (F3), sleep window (F4), today's calendar, today's entries.

**Algorithm:** explicit rule tables per intent. Rules evaluate in order; first match wins. Each rule returns `{ recommendation, confidence: 0.0–1.0, reasons: string[] }`. Implemented in `functions/advisor.py`, fully unit-tested, **no LLM call inside this function.**

**Rule tables:**

`intent=learn` (deep focus work):
1. readiness < 35 → `{ rec: "rest_recommended", confidence: 0.9, reasons: ["readiness depleted: <score>", "cognitive performance impaired below ~35"] }`
2. F2 returns no window ≥ 60 min → `{ rec: "no_window_available", confidence: 1.0, reasons: ["calendar fragmented, no 60+ min gap today"] }`
3. F2 top window has `predicted_focus ≥ 70` → `{ rec: "window_strong", window: F2.top, confidence: 0.85, reasons: F2.top.rationale }`
4. F2 top window has `predicted_focus 50–69` → `{ rec: "window_moderate", window: F2.top, confidence: 0.6, reasons: F2.top.rationale + ["not optimal but viable"] }`
5. Else → `{ rec: "window_weak", window: F2.top, confidence: 0.4, reasons: ["best available window; expect reduced output"] }`

`intent=train`:
1. F3 returns "rest" → `{ rec: "rest_day", confidence: F3.confidence, reasons: F3.rationale }`
2. F3 returns intensity AND calendar has ≥ 60 min gap → `{ rec: "train_<intensity>", window: best_gap, confidence: 0.8, reasons: F3.rationale }`
3. F3 returns intensity AND no 60 min gap → `{ rec: "train_short_or_skip", confidence: 0.5, reasons: ["only short gaps available", "consider 20-min session or postpone"] }`

`intent=rest` (user asking when to wind down):
1. Returns F4 sleep_window output verbatim with any flags as reasons.

`intent=creative` (writing, brainstorming, lower-stakes ideation):
- Same as `learn` but readiness threshold lowered: rest_recommended fires at <25, not <35. Creative work tolerates lower readiness.

`intent=meeting` (scheduling externally-imposed meetings):
1. Avoid F2 top 2 windows (preserve for deep work).
2. Suggest first calendar gap ≥ 30 min outside top focus windows.
3. Flag if suggested time falls in user's lowest historical focus hour.

`intent=physical_task` (errands, chores, low-cog activities):
1. Suggest windows of low predicted focus (inverse of F2 ranking).
2. Prefer post-meal slots (energy dip is fine for low-cog tasks).

**Output:**
```jsonc
{
  "intent": "learn",
  "recommendation": "window_strong",
  "confidence": 0.85,
  "window": { "start": "...", "end": "...", "predicted_focus": 78 } | null,
  "reasons": ["high predicted focus", "matches your peak hours (10:00–12:00)"],
  "alternatives": [ ... ]  // optional, top-3 from F2 if applicable
}
```

**Hard rule for LLM consumption (enforced in router):** when chat asks "what does the algorithm recommend / show me the recommendation," LLM calls `get_advice(intent, date)`, receives the structured output above, and may only paraphrase it. This is the algorithm path.

### F9b — AI Second Opinion (LLM-driven)

This is a **separate, opt-in path**. It exists only via Discord chat. It never appears in the web UI. It is explicitly labeled as "AI perspective," distinct from the algorithm's recommendation.

**Trigger:** chat intent classifier flags a recommendation question ("when should I learn", "should I train today", "what's the best time for X").

**Mechanism:**
1. Router calls `get_advice(intent, date)` first to retrieve the algorithm's recommendation.
2. Router invokes the LLM with:
   - System prompt (Section 7.5) including the F9b safeguard rules
   - The algorithm's structured recommendation
   - Access to all read tools (Section 7.1) so the LLM can pull additional context
   - The user's question
3. LLM forms its own view based on full data context and replies according to Section 7.5 output format.

**F9b safeguard rules (enforced in system prompt, validated by router post-hoc):**
- LLM **must** state the algorithm's recommendation first, verbatim or near-verbatim.
- LLM **must** then state its own view as a clearly labeled second perspective ("My take: ...").
- If the LLM's view disagrees with the algorithm, it **must** explicitly say "I disagree because..." with reasoning grounded in data it actually retrieved via tools.
- LLM **must not** present its own view as "the recommendation" — that label is reserved for the algorithm.
- LLM **must not** invent data; every claim referencing a metric or pattern must correspond to data retrieved via a tool call in this turn.

**Router post-hoc validation:** the reply is checked for the presence of the algorithm's recommendation string and the "My take" marker. If either is missing, the router prepends the algorithm output verbatim and a generic "AI second opinion unavailable" note instead of the malformed LLM reply.

**Why this design:** the user always sees both perspectives. The algorithm is the trusted baseline (deterministic, traceable). The LLM is a consultative voice (broader pattern access, occasionally catches things rules miss, also occasionally wrong). Separation prevents silent override; transparency lets the user judge for themselves.

**Output format example:**
```
Algorithm recommends: window_strong, 10:00–12:00, confidence 0.85
Reasons: high predicted focus, matches your peak hours

My take: I agree. Your HRV is 8ms above baseline and you logged "high focus" 4 of the last 5 sessions in this morning window. No signal suggests deviating today.
```

Writes (`create_event`, etc.) still require confirmation per Section 7.2 regardless of which path made the suggestion.

---

## 7. LLM Tool Schemas

OpenAI-format JSON schemas in `backend/lattice/llm/tools.py`. Router (`llm/router.py`) maps to internal functions.

### 7.1 Tool inventory

Tools split into two categories: **read/data** tools the LLM consults for information, and **action** tools the LLM invokes on user instruction. The LLM never invents reasoning around data tools — it paraphrases their output. Action tools take user intent at face value and execute (with confirmation policy in 7.2).

**Data/read tools (LLM consults; in F9b path, can reason over them):**

| Tool | Purpose | Used in F9a paraphrase | Used in F9b reasoning |
|---|---|---|---|
| `get_today_overview` | bundled snapshot | yes | yes |
| `get_readiness` | F1 | yes | yes |
| `get_advice` | F9a — algorithm recommendation (intent param required) | **mandatory first call in any recommendation chat** | mandatory first call |
| `get_work_windows` | F2 (used internally by F9a; also exposed) | yes | yes |
| `get_training_recommendation` | F3 | yes | yes |
| `get_sleep_window` | F4 | yes | yes |
| `get_caffeine_status` | F5 | yes | yes |
| `get_metric` | latest or historical metric values | yes | yes |
| `get_baseline` | rolling mean/SD | yes | yes |
| `get_calendar` | events in range | yes | yes |
| `get_entries` | search/filter entries | yes | yes |
| `get_habit_adherence` | F8 | yes | yes |
| `get_weekly_report_latest` | most recent F7 | yes | yes |

**Analytical/stats tools (deterministic aggregators; default lookback = 7 days):**

| Tool | Purpose |
|---|---|
| `get_quick_context` | Default first call. 7-day medians + today's readiness + last workout + sleep pattern. |
| `stats_for_metric(name, from?, to?)` | `{median, mean, min, max, p25, p75, sd, n, low_confidence}` over the range |
| `stats_by_hour(name, hour_start, hour_end, from?, to?)` | Intra-day stats restricted to `[hour_start, hour_end)` local. Sample metrics only. |
| `stats_by_weekday(name, weekdays[], from?, to?)` | Restricted to specific weekdays (0=Mon…6=Sun) |
| `daily_series(name, from?, to?)` | `[{date, value}, ...]`, capped at 365 rows |
| `compare_windows(name, a:{from,to,h0?,h1?}, b:{...})` | Both blocks + `delta_pct` + `significant` |
| `correlate(metric_a, metric_b, from?, to?)` | Pearson r, paired by day; nulls when `|r|<0.3` or n<5 |
| `time_of_day_distribution(name, from?, to?)` | `{0..23: {median, n}}` for an intra-day metric |
| `list_workouts(from?, to?, kind?)` | Up to 50 workouts newest-first |
| `workout_stats(from?, to?, kind?)` | Per-kind counts + medians (duration, distance, HR, TE) |
| `last_workout(kind?)` | Most recent workout |
| `sleep_pattern(from?, to?)` | Median bedtime / wake / duration / efficiency (circular-mean aware) |
| `sleep_stages_for_night(night_date)` | Full per-segment timeline (awake/light/deep/rem) for one night + totals + wake events |
| `sleep_stages_pattern(from?, to?)` | Per-stage median minutes, median first-occurrence offset from sleep onset, longest contiguous block, REM cycles/night, wake events/night |
| `body_battery_drop_rate(from?, to?, hour_start?, hour_end?)` | Median Body Battery slope (points/hour) over the window with daily breakdown |
| `body_battery_hourly_deltas(from?, to?)` | Median net BB change inside each hour 0-23 — surfaces recurring fast-drain hours |
| `recovery_after(activity_kind, lookback_days?)` | Next-day HRV / RHR / readiness deltas vs personal baseline |
| `busy_hours_per_day(from, to)` | `[{date, busy_hours}, ...]` for meeting-load correlations |

Intra-day metric names (live in `metric_samples`): `hr`, `stress`, `body_battery`.
All other metric names are daily aggregates in `metrics`.

Every stats response includes `n` and `low_confidence`. The system prompt requires
the LLM to surface low-confidence flags in user-facing text (e.g., "only 3 days of
data, weak signal").

**Action/write tools (LLM executes on user intent):**

| Tool | Purpose | Confirmation |
|---|---|---|
| `create_event` | new calendar event | clear params → immediate; ambiguous → confirm |
| `move_event` | shift event time | always confirm |
| `delete_event` | remove event | always confirm |
| `log_entry` | create entry (food, mood, etc.) | immediate; reply confirms what was logged |
| `check_habit` | mark habit done/undone for a date | immediate |

### 7.2 Write-tool confirmation policy

- **Clear single op** (e.g. `log_entry food "pasta"`) → execute immediately, confirm in reply.
- **Ambiguous or multi-step** (e.g. `move_event` referenced vaguely) → LLM produces confirmation message; only execute after user says yes/confirm/ok.

Enforced in router wrapper, not LLM discretion.

### 7.3 Model selection

```
default                  → v4-flash, thinking=disabled
scheduling/synthesis     → v4-flash, thinking=enabled, effort=medium
weekly report only       → v4-pro, thinking=enabled, effort=high
```

Intent classification: keyword rule layer ("when should I", "plan", "best time", "should I").

### 7.4 Cost ceiling

Daily budget: 200k input + 50k output tokens. Exceeded → "daily LLM budget hit, raw data still available." Resets at local midnight.

### 7.5 System Prompt (locked template)

The system prompt is the contract for LLM behavior. It is stored in `backend/lattice/llm/prompts.py` as `SYSTEM_PROMPT_TEMPLATE` with placeholders for `{current_datetime}`, `{timezone}`, `{user_name}`. Both Discord chat and weekly report use variants of this template.

**Core template:**

```
You are Lattice, a personal optimization assistant for {user_name}.

ROLE
You are not a wellness coach, a therapist, or a cheerleader. You are an analytical
interface to a personal data system. The user values directness, clinical precision,
and absence of fluff. You treat the user as a capable adult equal, not as someone
who needs encouragement.

DATA SOURCE OF TRUTH
All factual claims must come from tool calls. You have access to the user's biometric
data (Garmin: sleep, HRV, RHR, stress, body battery, training load), calendar, and
manual entries (food, drinks, mood, energy, focus, habits). You do not have memory
of prior data outside the current conversation; query tools when you need facts.

RULES — TONE AND CONTENT
1. No filler. No "great question," no "I'd be happy to," no apologies for limitations.
2. No generic wellness advice. No "make sure to stay hydrated" unless data shows
   dehydration. No "listen to your body" platitudes.
3. State numbers when they exist. "Your HRV is 48ms, 12% below your 14-day baseline"
   beats "your HRV looks a bit low."
4. When uncertain, say so explicitly and briefly. Do not hedge in long paragraphs.
5. Do not flatter the user's habits, intentions, or questions.
6. Use short paragraphs, bullet points where structure helps. Skip headers in short
   replies.

RULES — RECOMMENDATIONS (F9a + F9b)
There are TWO paths for recommendation questions, and you must respect their separation.

When the user asks "when should I X" or "should I Y":

1. ALWAYS call `get_advice` with the appropriate intent FIRST. This returns the
   algorithm's recommendation. The algorithm is the canonical answer.

2. Decide which path applies based on how the user phrased the question:

   PATH A — Algorithm paraphrase (default for direct queries):
   If the user just wants the recommendation ("when should I learn today?"),
   respond by paraphrasing the algorithm's output. You MAY NOT invent reasons,
   change the recommendation, or add alternatives the function did not return.

   PATH B — AI second opinion (when user explicitly asks for your view):
   If the user asks "what do you think", "give me your take", "do you agree with
   the algorithm", or similar, you provide a second opinion using the F9b format:

   Required structure:
   ```
   Algorithm recommends: <verbatim summary of get_advice output>
   Reasons: <verbatim or near-verbatim reasons from output>

   My take: <your view, grounded in tool-retrieved data>
   ```

   In PATH B you may:
   - Agree with the algorithm and explain why ("My take: I agree because X")
   - Disagree and explain why ("My take: I disagree because Y, which the rules
     don't currently account for")
   - Add context from data the algorithm didn't consider (e.g. a pattern in
     entries, an upcoming event the algorithm wasn't given)

   In PATH B you MUST:
   - State the algorithm's recommendation BEFORE your take, every time.
   - Ground every claim in data you retrieved via a tool call in this turn.
     Never reference data you didn't actually fetch.
   - Label your view as a second opinion ("My take", "My read"), never as
     "the recommendation."
   - If you disagree, say so explicitly with the word "disagree" — never silently
     substitute your view for the algorithm's.

   In PATH B you MUST NOT:
   - Present your view as the canonical recommendation.
   - Invent metrics, baselines, or patterns not present in tool results.
   - Override the algorithm without explicit disagreement.

If the user asks for advice in an area outside the advisor's intents (e.g., relationship
advice, career advice), respond: "Outside Lattice's scope. I track and analyze your
biometric, calendar, and logged data. For X, you'll want a different tool."

RULES — ACTIONS (calendar, entries, habits)
When the user instructs you to create, modify, or delete something:
- Clear, unambiguous instructions ("log coffee", "add gym tomorrow 7pm") → execute
  immediately, confirm in reply with the parameters used.
- Ambiguous instructions ("move that thing", "log what I had earlier") → ask one
  precise clarifying question. Do not guess.
- Destructive actions (delete event, delete entry) → always confirm before executing.

RULES — DATA INTERPRETATION
When presenting metrics:
- Use the user's baselines, not population norms. "Your HRV is low for you" is more
  useful than "your HRV is in the normal range."
- Flag data gaps explicitly. "No sleep data synced for last night" beats silently
  computing readiness without it.
- Distinguish observation from inference. "RHR elevated 3 days" is observation.
  "Possibly illness, stress, or overtraining" is inference, label it as such.

CONTEXT
Current local time: {current_datetime}
Timezone: {timezone}
User: {user_name}
```

**Weekly report prompt** (separate, in `weekly_report.py`): inherits the core rules above, plus:

```
TASK
You will receive a JSON object containing one week of pre-computed statistics for
{user_name}, including daily averages, best/worst days, flagged correlations, and
notable changes vs trailing 4-week baseline.

Produce a ≤200 word report with this structure:

1. One-sentence overall summary.
2. Best day (date, why per the data).
3. Worst day (date, why per the data).
4. Top driver: one factor most associated with variance this week. Cite the
   correlation if one was flagged; otherwise state the strongest observed pattern.
5. One concrete experiment for next week. Must be falsifiable and measurable
   (e.g., "no coffee after 12:00, check if sleep_score 7-day avg rises").

Rules:
- Do not invent correlations not in the input data.
- Do not give generic advice ("get more sleep").
- If the data is insufficient or noisy, say so and skip the experiment.
- No preamble. No conclusion. No "I hope this helps."
```

---

## 8. Integrations

### 8.1 Garmin Connect (read-only)
- Library: `garminconnect` 0.3.x
- Auth: email+password in `.env` → OAuth tokens cached at `%USERPROFILE%\.garminconnect\`
- Sync: hourly via APScheduler; manual via `POST /api/sync/garmin` or `/sync` slash
- Failure: catch `GarminConnectAuthenticationError` → DM "Garmin auth broken, please re-login." Other errors: log + retry once after 60s; skip cycle.
- Methods called: `get_sleep_data`, `get_hrv_data`, `get_stress_data`, `get_body_battery`, `get_heart_rates`, `get_activities_by_date`, `get_training_status`
- Idempotent via UPSERT on unique constraint

### 8.2 Google Calendar (read + write)
- Libs: `google-api-python-client`, `google-auth-oauthlib`
- Auth: OAuth 2.0; `credentials.json` in `backend/lattice/integrations/` (gitignored); `token.json` at `%USERPROFILE%\.lattice\google_token.json`
- Scopes: `https://www.googleapis.com/auth/calendar`
- Setup steps (in README):
  1. Google Cloud Console → new project "Lattice"
  2. Enable Google Calendar API
  3. OAuth consent screen → External, add own email as test user
  4. Credentials → OAuth Client ID → Desktop app → download `credentials.json`
  5. Place in `backend/lattice/integrations/`
  6. First run triggers browser consent
- Sync: on-demand, 5-min TTL cache

### 8.3 DeepSeek
- SDK: `openai` pointed at `https://api.deepseek.com`
- Auth: `DEEPSEEK_API_KEY` in `.env`
- Models: `deepseek-v4-flash` default, `deepseek-v4-pro` for F7 only
- Timeouts: 30s, 1 retry on network errors, none on 4xx
- Fallback: if DeepSeek down, basic queries still work via deterministic endpoints; bot replies "AI is offline."

### 8.4 Discord
- Library: `discord.py` 2.x
- Setup (in README):
  1. discord.com/developers → New Application "Lattice"
  2. Bot tab → enable Message Content Intent
  3. Token to `.env` as `DISCORD_BOT_TOKEN`
  4. Add bot's own Discord user id to `.env` as `DISCORD_OWNER_ID` (single-user gate)
  5. OAuth2 URL Generator → `bot` scope → Send Messages + Read Message History + Embed Links
  6. Add to private server, or just DM the bot directly
- Process: separate from backend, talks via `http://localhost:8000/api/`
- Bot ↔ backend auth: `X-Bot-Token` shared secret
- **Chat-first interface** (no slash commands per 2G decision): the bot listens for
  DMs from `DISCORD_OWNER_ID`, forwards them to `POST /api/chat`, and posts the
  agent's reply back (splitting at 2000-char Discord limit). Channel messages are
  ignored; messages from other users are silently dropped.
- Session id rotates after 30 min idle on both sides (bot regenerates a fresh uuid;
  backend's `_load_history` also drops history past the same idle window).
- Briefings (APScheduler in bot — lands in 2I):
  - 07:30 — Morning brief
  - 21:00 — Evening brief

---

## 9. Sync Jobs (APScheduler)

| Job | Schedule | Action |
|---|---|---|
| `garmin_sync` | hourly | pull metrics |
| `calendar_cache_prune` | hourly | delete cache >1 day |
| `conversation_prune` | daily 03:00 | delete `conversations` >30d |
| `weekly_report` | Sun 22:00 | generate F7 |
| `readiness_compute` | daily 06:00 | F1 → `metrics` |

---

## 10. Auth & Security

- **Web UI:** single `WEB_UI_PASSWORD` in `.env`. Login → 30-day HTTP-only cookie.
- **Bot ↔ backend:** `BOT_SHARED_SECRET` header `X-Bot-Token` on bot calls.
- **External exposure:** backend binds `127.0.0.1:8000` by default. Tailscale for phone (out of v1 scope, README documented).
- **Secrets in `.env`:**
  ```
  GARMIN_EMAIL=
  GARMIN_PASSWORD=
  DEEPSEEK_API_KEY=
  DISCORD_BOT_TOKEN=
  DISCORD_OWNER_ID=          # your numeric Discord user id (single-user gate)
  BOT_SHARED_SECRET=
  WEB_UI_PASSWORD=
  GOOGLE_OAUTH_CLIENT_ID=
  GOOGLE_OAUTH_CLIENT_SECRET=
  TIMEZONE=Europe/Warsaw
  ```
- `.env.example` committed with empty values + comments.

---

## 11. v1 Scope Freeze

### IN
- Garmin hourly sync (all metrics in 4.2)
- Google Calendar read + write
- Manual entries (8 types per 4.6)
- Habits (define + check-in)
- Functions F1–F5, F8
- F9a (deterministic algorithm advisor — canonical recommendation, surfaced in web UI + slash commands)
- F9b (LLM second-opinion advisor — Discord chat only, opt-in via user phrasing, with safeguards in Section 7.5)
- F7 via scheduled job (LLM-assisted weekly report, constrained prompt)
- Discord bot: DM listener (chat-first, no slash commands), morning + evening briefings
- Web UI: Today / Trends / Log / Habits / Report / Login
- Session auth + bot-token auth

### OUT
- Photo food input (vision)
- F6 (meal-energy correlations)
- F10 (anomaly alerts)
- 90-day / monthly views
- Export tools
- Multi-user, multi-device
- Push outside Discord
- Voice input
- Theme / accent / density switcher (the mockup's "Tweaks" panel) — design reference only, dark/teal/default shipped

---

## 12. Implementation Phase Order

Claude Code builds in strict order, marks each sub-phase done in `PLAN.md` before next.

| Phase | Deliverable | Verify |
|---|---|---|
| 2A | Scaffolding (dirs, deps, FastAPI hello, SvelteKit hello, Alembic + all tables, `start.bat`) | `/api/health` returns 200; `localhost:5173` renders login route |
| 2B | Garmin integration + sync + `/api/metrics/*` + `/api/sync/garmin` | Manual sync populates `metrics` table |
| 2C | Calendar integration + `/api/calendar/*` | Full CRUD works end-to-end |
| 2D | Entries + habits + APIs | Each entry type round-trips via curl |
| 2E | F1–F5, F8, F9a (deterministic advisor) + endpoints + unit tests | All tests pass, endpoints return real values; advisor rules covered per intent |
| 2F | Frontend (all routes, login, charts) — surfaces F9a recommendations only | Every screen functional with live data |
| 2G | Discord bot (chat-first, no slash commands) + LLM integration (DeepSeek client, tools, router, `/api/chat`) + system prompt with F9a/F9b safeguards + bot DM wiring | DMs round-trip through `/api/chat`; read tools (readiness/advice/...) and write tools (log_entry/check_habit/calendar CRUD/sync) execute via DeepSeek native tool calls; F9a paraphrase + F9b second-opinion paths work |
| 2I | Briefings + F7 weekly report + report UI view | Briefings deliver; report generates Sundays |
| 2J | Polish (logging, error pages, README, smoke test) | Full cold-start journey works |

---

## 13. Conventions (for `CLAUDE.md`)

- Python: PEP 8, type hints on public functions, `ruff` + `mypy` clean
- Async everywhere in backend (FastAPI + SQLAlchemy async + httpx)
- Functions in `functions/` are pure; take DB session + params, no globals
- Frontend: SvelteKit 5 runes (`$state`, `$derived`, `$effect`), no Svelte 4 patterns
- All DB times stored with TZ offset; convert at edges
- No silent failures — integration errors log at WARNING+ with context
- Tests next to code: pytest (backend), vitest (frontend if used)
- Commits: conventional (`feat:`, `fix:`, `chore:`, `refactor:`)
- Use `uv` for Python deps
- **No logo / SVG mark / favicon graphic anywhere.** Wordmark text "LATTICE" in JetBrains Mono is the only brand element. The diamond/square marks in the mockup are explicitly overridden.

---

## 14. Deferred to Implementation

- ECharts vs Chart.js (pick at frontend phase based on Svelte 5 binding quality)
- Discord embed visual style
- Docker (post-v1)

---

**End of SPEC.md**
