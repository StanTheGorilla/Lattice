# Lattice — Improvement Plan (2026-06-12)

Produced from a full codebase review (SPEC.md, PLAN.md, backend/bot/frontend source,
test run). Current test state: **190 passed, 3 failed** (see P0-3).

**Execution pass (2026-06-12):** P0-1 → P0-4, P1-2 → P1-7, V-1 → V-5, P2-1 done.

**Execution pass 2 (2026-06-12):** P1-1, V-4 (routine seed), P2-2, P2-3, P3-1, P3-2,
P3-3 all done. Every IMPROVEMENT_PLAN item is now complete. Backend tests green,
frontend `npm run check` green (0 errors/0 warnings), `mypy --strict` baseline
recorded (90 pre-existing errors; all new code clean). See COMMIT_GROUPS.md for the
per-commit file split.

Overall: the architecture is sound. AI-as-brain rework is coherent, the
recommendation-store invariant is right, syncs are idempotent, LLM failure modes
degrade gracefully. No subsystem needs deletion. The work below is ordered by risk.

---

## P0 — Protect the work (do first, low effort)

### P0-1 Commit the working tree  — done (initial commit c52a9c3 + COMMIT_GROUPS.md)
The repo has exactly ONE commit; ~40 modified + ~40 new files (including 6 Alembic
migrations 0010–0015) are uncommitted on a Pi SD card. Commit in logical chunks per
CLAUDE.md conventions (suggested split: rework R / memory / algorithms+sandbox /
dashboard cards / routines / nutrition / research / frontend pages), then push to a
private GitHub remote.

### P0-2 Nightly SQLite backup job  — done
`data/lattice.db` on an SD card is the single point of failure; SD corruption is the
most common Pi failure mode. Add a scheduler job (e.g. daily 03:30):
- `VACUUM INTO 'backups/lattice-YYYYMMDD.db'` (or `sqlite3 .backup`)
- keep ~14, prune older
- ideally rsync/rclone off-device; also cover `data/research/` and `.env`

### P0-3 Fix the 3 failing tests  — done
- `tests/test_entries_schema.py::test_drink_free_text_kind_accepted`
- `tests/test_sleep_stages.py::test_extract_sleep_stages_from_levels_array`
- `tests/test_weekly_stats.py::test_habits_appear_with_completed_count`
Decide per-test whether the function or the test drifted.

### P0-4 Fail closed on auth  — done
The systemd unit binds `0.0.0.0:8000` (LAN-exposed), but `require_auth` is
*permissive when no password is set* — that design assumed the original
`127.0.0.1` bind. Make startup refuse (or force localhost bind) when
`WEB_UI_PASSWORD` / `BOT_SHARED_SECRET` are empty while host ≠ 127.0.0.1.
Add basic rate-limiting on `/auth/login`.

---

## P1 — Function-level fixes (correctness)

### P1-1 Timestamp comparison audit (cross-cutting)  — done (normalize at the write edge)
Timestamps are stored as ISO strings with **mixed offsets** (chat rows are UTC,
function queries build local-offset cutoffs, `sandbox.fetch_algorithm_data` uses UTC
cutoffs). Lexicographic SQL comparison across different offsets is wrong by up to the
offset delta. Affected examples: `_conversation_prune_job`, `fetch_algorithm_data`,
every `Entry.timestamp >= local_iso` filter.
**Resolution (lower-risk, correctness-preserving):** the offset hazard came from
the *write* edge — `create_entry`/`patch_entry`/`log_entry` wrote UTC while every
`functions/` cutoff and the Garmin sync write local-offset rows. New helper
`lattice.utils.normalize_to_local_iso` now converts entry timestamps to the
configured local offset on write, so all comparable rows share one offset family.
`sandbox.fetch_algorithm_data` already builds local-TZ cutoffs (verified). No
historical-row migration required. Covered by `tests/test_timestamp_normalization.py`.

### P1-2 `sleep_debt.py` must reuse F4's healthy envelope  — done (via V-2 store)
Sleep debt currently measures against `Profile.target_sleep_min` or a flat 7.5 h
fallback, while F4 computes an age-aware floor (teens 8–10 h via `Profile.birthday`).
Two tools give two different answers to "am I sleep-deprived?" — the exact
incoherence Rework R fixed elsewhere. Fallback target should be F4's
`_healthy_sleep_bounds_min(age)` floor.

### P1-3 Unify "what counts as caffeinated" between F4 and F5  — done
- F4's late-caffeine flag matches kind substrings ("coffee, tea, latte … energy") —
  misses cola/yerba/etc.
- F5 uses the classified `caffeine_mg` field.
Both should treat an entry as caffeinated iff `caffeine_mg > 0` (with F5's existing
legacy-coffee fallback).

### P1-4 F5 misses after-midnight caffeine  — done
`_today_caffeine` only queries entries on the target *date*, but bedtime is often
past midnight: a 00:30 energy drink would not count against tonight's residual.
Query window should extend to the bedtime instant (target date start → bedtime).

### P1-5 F5: add a daily caffeine cap  — done (value owned by V-2 store; flag is informative)
F5 only guards the 50 mg bedtime residual. Add a configurable daily total cap
(profile field; conservative adolescent guideline ≈100 mg/day as default) surfaced
as a **flag/warning** in `get_caffeine_status` and entry markers — informative, not
blocking.

### P1-6 `allostatic_load.py` adjustments  — done
- **Drop `readiness_score` from the marker list**: readiness is derived from
  HRV/RHR/sleep/BB/stress which are all separate ALI markers — one bad system
  currently moves 2+ of the 8 points. The published ALI framework uses independent
  systems.
- By construction ~25 % of normal days sit in an "adverse quartile" of one's own
  baseline, so a healthy week can score 2/8 — soften/clarify the interpretation text.
- Remove dead `_QUARTILE_WINDOW` constant.

### P1-7 Harden the algorithm sandbox (`llm/sandbox.py`)  — done (dunder + reflection helpers blocked; thread limitation documented + warn-logged)
AST validation blocks imports/eval but NOT attribute-walk escapes
(`"".__class__.__mro__[1].__subclasses__()` reaches `os`). The research agent means
web-sourced text can influence AI-authored code (prompt-injection → code execution).
- Cheap fix: reject any dunder attribute access (`ast.Attribute` whose attr starts
  with `__`) and `getattr`/`setattr`/`vars`/`globals` names in validation.
- Note: the daemon-thread "timeout" does not kill the thread — an infinite loop
  burns a Pi core forever. Consider subprocess execution with `resource` limits,
  or at minimum log + alert when a thread is left running.

---

## V — AI-as-expert personalization (versatility rework)

**Goal (owner request):** stop hard-coding age-bracket rules. The AI already knows
the user's age (Profile.birthday) and all biometric data — it should decide target
sleep duration, caffeine limits, and how to interpret metrics like a personalized
expert, with the static tables demoted to fallback seeds + outer safety bounds.

This mirrors the existing AI-as-brain pattern (Rework R): a stored, AI-writable
decision that every surface reads, with provenance.

### V-1 `health_targets` keyed store  — done (in `recommendations` table, sentinel `target_date='*'`)
New kinds in the existing `recommendations` store (or a small `health_targets`
table following the same pattern): AI-writable targets with rationale + provenance:
- `sleep_floor_min` / `sleep_ceiling_min` (replaces direct use of `_HEALTHY_BOUNDS_MIN`)
- `caffeine_daily_cap_mg`
- `caffeine_bedtime_residual_mg` (currently hard-coded 50)
- `caffeine_cutoff_hour`
Write tool `set_health_targets` (chat) + read surface in Profile/Settings UI with an
`AI`/`default` provenance badge and rationale, same as the sleep card.

### V-2 Deterministic functions read the store  — done (F4, F5, sleep_debt)
F4, F5, sleep_debt, allostatic_load (duration threshold), entry markers read the
stored targets first; fall back to age-derived defaults when no AI row exists.
The current age table (`_HEALTHY_BOUNDS_MIN`) becomes the **seed/fallback**, not the law.

### V-3 Wide outer guardrails (few, medically defensible — not rules)  — done
AI-set targets are clamped to broad bounds derived from age, e.g. for <18:
sleep floor never below 7 h, ceiling never above 11 h, daily caffeine cap never
above 200 mg. For adults proportionally wider. These exist only to stop a bad
LLM day from persisting a harmful target; inside them the AI's judgment wins.
Clamping is logged + surfaced in the rationale ("requested X, clamped to Y").

### V-4 Prompt + routine  — done (prompt + idempotent weekly `ai_review` routine seed)
- System prompt: add an "EXPERT TARGETS" section — the AI is expected to set and
  periodically revisit personalized targets using profile age + observed data
  (sleep response, HRV trends, caffeine sensitivity from sleep-impact correlations),
  citing data when it changes a target.
- Seed an `ai_review` routine (weekly Sunday 19:00) that reviews stored health
  targets vs the last weeks of data and updates them with rationale. Migration
  `0016_seed_ai_review_routine.py` is idempotent (skips if a routine of that name
  already exists).

### V-5 Tests  — done (`backend/tests/test_health_targets.py`, 7 cases)
- Store invariants (AI row wins, fallback seeds, clamping at bounds).
- F4/F5/sleep_debt read stored targets; behavior unchanged when store empty.

---

## P2 — Drift & maintainability

### P2-1 Backfill PLAN.md  — done (Phase 2L sections + Improvement Pass 2026-06-12 added)
SPEC's amendment points to PLAN.md for memory, custom algorithms, dashboard cards,
nutrition, and research — but PLAN.md ends at 2K + Rework R (sandbox.py references a
"Phase 2L-a" that is documented nowhere). Future sessions follow CLAUDE.md's reading
order and will work from stale state. Backfill the missing phase sections (scope,
decisions, follow-ups) in the established format.

### P2-2 Test coverage for newer modules  — done (mypy baseline recorded below)
No pytest coverage for: `llm/sandbox.py` (validation + escape attempts + timeout),
`functions/entry_markers.py`, `functions/nutrition*.py`, `functions/data_freshness.py`,
memory tools, `integrations/tavily.py` / `research.py`. Then establish the deferred
`mypy --strict` baseline (CLAUDE.md requires it; never re-run since 2J).
**Added:** `test_sandbox.py` (validation/rejections incl. dunder-walk + reflection
escapes, execute_algorithm happy path + timeout), `test_data_freshness.py`,
`test_research.py` (httpx mocked), `test_nutrition.py`, `test_entry_markers.py`,
`test_memory_tools.py`.
**`mypy --strict lattice/` baseline: 90 errors in 23 files** (113 source files
checked). All pre-existing — concentrated in `llm/router.py`, `functions/weekly_*`,
SQLAlchemy `insert()` arg-types, and untyped `apscheduler` stubs. **All new modules
this pass (`functions/llm_observability.py`, `api/observability.py`,
`functions/routine_runner.py` changes, `functions/alert_checker.py` changes,
`utils/__init__.py`) are mypy-clean.** Burning down the 90-error baseline is a
separate dedicated task (left untouched to keep this pass low-risk).

### P2-3 Persist compact tool-result context across chat turns  — done
History replay drops all tool results (decision 2G-9), so on a follow-up question the
agent either re-fetches everything or answers without data. Persist a short digest
("data consulted: readiness=77, sleep 6h42m, …") on the assistant row and replay it
as plain text — keeps the OpenAI message contract intact.
**Done:** `Conversation.data_digest` column (migration `0017_conversation_data_digest`),
`build_data_digest` builds a short plain-text digest in `_persist_turn`, `_load_history`
replays it as a system/plain line. Covered by `tests/test_chat_digest.py`.

---

## P3 — Nice-to-have

### P3-1 LLM observability page  — done
`llm_usage` table already exists — surface daily input/output tokens (+ a cost
estimate) and recent routine runs on the web UI.
**Done:** `functions/llm_observability.get_llm_usage_summary` aggregates trailing-N-day
tokens + DeepSeek cache-miss cost estimate; `GET /api/observability/llm-usage`
endpoint; new `/usage` frontend page (totals cards + daily table with token bars).
Covered by `tests/test_llm_observability.py`. `npm run check` green.

### P3-2 Routine run history  — done
A suppressed `only_notable` routine is currently invisible outside journalctl. Add a
small `routine_runs` table (routine_id, fired_at, sent/suppressed, reply excerpt) and
show last N runs on /routines.
**Done:** `routine_runs` table + model (migration `0018_routine_runs`); recording
moved into `run_routine` so both the scheduler and the manual-run API path capture a
row; `GET /api/routines/runs?limit=` endpoint; "Recent runs" card on /routines.
Covered by `tests/test_routine_runs.py`.

### P3-3 Data-staleness watchdog  — done
`functions/data_freshness.py` exists — wire a default alert: DM when Garmin data is
>24 h stale (auth breakage is currently only an ERROR log line + DM on the auth
exception path).
**Done:** `alert_checker._check_staleness_watchdog` fires a Discord DM when
`get_data_freshness` reports `stale_today`/`stale_severe`, rate-limited to once per
24h via a sentinel-rule AlertEvent (`rule_id = -1`) so a persistent outage doesn't
spam. Covered by `tests/test_staleness_watchdog.py`.

---

## Explicitly NOT changing

- The large system prompt and ~80-tool surface — correctness preferred over token
  savings; just watch `llm_usage` (P3-1).
- In-process tool dispatch (2G-6), SQLite, the AI-as-brain recommendation store,
  routine architecture, F9a rule tables, F4's recovery-debt model (well designed —
  age-aware envelope, debt fraction, acute nudge, feasibility switch).
- No function deletions: overlap between analytics tools (sleep_debt vs F4 internals,
  recovery vs recovery_trajectory) is acceptable — they serve different query shapes
  for the agent.
