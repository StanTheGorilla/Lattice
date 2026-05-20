"""OpenAI-format tool schemas (SPEC §7.1).

These mirror the in-process router dispatch in `router.py`. Schemas are kept
in this single file so the LLM's tool surface is reviewable at a glance.

Read tools: paraphrase-only in F9a path; reasoning material in F9b path.
Write tools: execute on user intent with the confirmation policy enforced in
the system prompt (SPEC §7.2).
"""

from __future__ import annotations

from typing import Any

# --------------------------------------------------------------------------- #
# Shared param fragments
# --------------------------------------------------------------------------- #

_DATE_PARAM = {
    "type": "string",
    "description": "Optional YYYY-MM-DD date; omit to use today (local timezone).",
}

_INTENT_ENUM = ["learn", "train", "rest", "creative", "meeting", "physical_task"]
_ENTRY_TYPES = [
    "food", "drink", "mood", "energy", "focus", "symptom", "note", "workout_manual",
]

# --------------------------------------------------------------------------- #
# Tool inventory
# --------------------------------------------------------------------------- #

TOOL_SCHEMAS: list[dict[str, Any]] = [
    # ---- read / data ----
    {
        "type": "function",
        "function": {
            "name": "get_today_overview",
            "description": (
                "Bundled snapshot of today's state: readiness (F1), training rec (F3), "
                "sleep window (F4), caffeine status (F5), and the top work window (F2). "
                "Use as the first call when the user asks 'how am I today' or similar."
            ),
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_readiness",
            "description": "F1 readiness score (0-100) with category and explanation.",
            "parameters": {
                "type": "object",
                "properties": {"date": _DATE_PARAM},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_advice",
            "description": (
                "F9a — the canonical algorithm recommendation. MUST be the first call "
                "for any recommendation question ('when should I X', 'should I Y'). "
                "Returns structured { recommendation, confidence, window?, reasons[] }."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "intent": {"type": "string", "enum": _INTENT_ENUM},
                    "date": _DATE_PARAM,
                },
                "required": ["intent"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_work_windows",
            "description": "F2 — ranked focus windows in today's calendar gaps.",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": _DATE_PARAM,
                    "min_minutes": {
                        "type": "integer",
                        "minimum": 15,
                        "maximum": 480,
                        "description": "Minimum gap length; default 60.",
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_training_recommendation",
            "description": "F3 — rest / easy / moderate / hard with rationale.",
            "parameters": {
                "type": "object",
                "properties": {"date": _DATE_PARAM},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_sleep_window",
            "description": "F4 — bedtime and wake_time derived from tomorrow's first event.",
            "parameters": {
                "type": "object",
                "properties": {"date": _DATE_PARAM},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_caffeine_status",
            "description": "F5 — caffeine residual at bedtime + 'last call' minutes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "at": {
                        "type": "string",
                        "description": "Optional ISO 8601 instant; defaults to now.",
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_metric",
            "description": (
                "Latest value or recent series of a single metric (e.g. resting_hr, "
                "hrv_overnight_avg, sleep_score, body_battery_start). "
                "Use limit=365 for a full year of daily values."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Metric name per SPEC §4.2."},
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 365,
                        "description": "How many recent rows to return (default 1 = latest).",
                    },
                },
                "required": ["name"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_baseline",
            "description": (
                "Rolling mean/SD over the last `days` rows of a metric. "
                "Use days=90 or days=365 for long-range personal baselines."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "days": {"type": "integer", "minimum": 2, "maximum": 365},
                },
                "required": ["name"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_calendar",
            "description": "List Google Calendar events in [from, to].",
            "parameters": {
                "type": "object",
                "properties": {
                    "from": {
                        "type": "string",
                        "description": "YYYY-MM-DD or full ISO 8601 with TZ. Lower bound.",
                    },
                    "to": {
                        "type": "string",
                        "description": "YYYY-MM-DD or full ISO 8601 with TZ. Upper bound.",
                    },
                },
                "required": ["from", "to"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_entries",
            "description": "Search/filter manual entries (food, mood, focus, etc.).",
            "parameters": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": _ENTRY_TYPES},
                    "from": {"type": "string"},
                    "to": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 200},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_habits",
            "description": "List habit definitions (id, name, target_per_week, active).",
            "parameters": {
                "type": "object",
                "properties": {
                    "active_only": {"type": "boolean"},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_habit_adherence",
            "description": "F8 — streak + completion % per habit over a window.",
            "parameters": {
                "type": "object",
                "properties": {
                    "from": {
                        "type": "string",
                        "description": "YYYY-MM-DD start (default first of month).",
                    },
                    "to": {
                        "type": "string",
                        "description": "YYYY-MM-DD end (default today).",
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    # ---- write / action ----
    {
        "type": "function",
        "function": {
            "name": "log_entry",
            "description": (
                "Create a manual entry. `data` shape depends on `type` — see SPEC §4.7. "
                "Examples: type='food', data={description: 'eggs and toast', meal_type: 'breakfast'} | "
                "type='drink', data={kind: 'coffee', count: 1} | "
                "type='mood', data={score: 4} | "
                "type='focus', data={score: 4, session_duration_min: 45, task: 'PRD draft'}."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": _ENTRY_TYPES},
                    "data": {"type": "object", "description": "Per-type payload (SPEC §4.7)."},
                    "timestamp": {
                        "type": "string",
                        "description": "ISO 8601 when the event happened; defaults to now.",
                    },
                },
                "required": ["type", "data"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_entry",
            "description": (
                "Permanently delete a log entry by its ID. "
                "Use this to remove a wrongly logged entry instead of leaving it in the log. "
                "Always confirm the entry ID using get_entries before deleting."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "entry_id": {"type": "integer", "description": "The ID of the entry to delete."},
                },
                "required": ["entry_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "patch_entry",
            "description": (
                "Edit an existing log entry — fix its data or timestamp. "
                "Use this instead of deleting + re-creating when only a field needs correcting. "
                "The `data` object must match the original entry type's schema."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "entry_id": {"type": "integer", "description": "ID of the entry to update."},
                    "timestamp": {
                        "type": "string",
                        "description": "ISO 8601 corrected timestamp. Omit to leave unchanged.",
                    },
                    "data": {
                        "type": "object",
                        "description": "Full replacement data payload matching the entry type schema.",
                    },
                },
                "required": ["entry_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_habit",
            "description": "Mark a habit done/undone for a date. Pass habit name OR habit_id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "habit_id": {"type": "integer"},
                    "name": {"type": "string", "description": "Match by name; case-insensitive."},
                    "date": {"type": "string", "description": "YYYY-MM-DD; default today."},
                    "completed": {"type": "boolean", "description": "Default true."},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_calendar_event",
            "description": "Create a Google Calendar event (writes through to Google + cache).",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "start": {
                        "type": "string",
                        "description": (
                            "ISO 8601 with TZ offset for timed events, or YYYY-MM-DD for all-day."
                        ),
                    },
                    "end": {"type": "string", "description": "Same format as start."},
                    "description": {"type": "string"},
                    "location": {"type": "string"},
                    "is_all_day": {"type": "boolean"},
                },
                "required": ["title", "start", "end"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "patch_calendar_event",
            "description": "Modify an existing calendar event by Google event id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_id": {"type": "string"},
                    "title": {"type": "string"},
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "description": {"type": "string"},
                    "location": {"type": "string"},
                    "is_all_day": {"type": "boolean"},
                },
                "required": ["event_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_calendar_event",
            "description": "Delete a Google Calendar event by id. CONFIRM with the user first.",
            "parameters": {
                "type": "object",
                "properties": {"event_id": {"type": "string"}},
                "required": ["event_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sync_garmin",
            "description": "Pull recent Garmin metrics. Default last 1 day; max 400.",
            "parameters": {
                "type": "object",
                "properties": {"days": {"type": "integer", "minimum": 1, "maximum": 400}},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sync_calendar",
            "description": "Force-refresh the Google Calendar cache for the next 14 days.",
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    # --------------------------------------------------------------------- #
    # Analytical tool surface (the bot's professional-analyzer toolkit).
    # Intra-day sample names: "hr", "stress", "body_battery".
    # Daily metric names: anything in SPEC §4.2 (sleep_score, hrv_overnight_avg, …).
    # All stats tools accept optional `from`/`to` (ISO date or datetime).
    # When both omitted, the default range is the last 7 days.
    # --------------------------------------------------------------------- #
    {
        "type": "function",
        "function": {
            "name": "get_quick_context",
            "description": (
                "Default first call for any new chat thread. Returns a 7-day "
                "snapshot: today's readiness, 7-day medians for the headline "
                "metrics (HRV, RHR, sleep, BB, stress), recent sleep pattern, "
                "last workout, and weekly habit adherence. Cheap and bundled. "
                "Use this BEFORE diving into specific stats so you have baseline "
                "context."
            ),
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "stats_for_metric",
            "description": (
                "Aggregate stats for a metric over [from, to]: median, mean, "
                "min, max, p25, p75, sd, n, low_confidence. Works for daily "
                "aggregates (sleep_score, hrv_overnight_avg, etc.) AND for "
                "intra-day samples (hr, stress, body_battery). "
                "Set from=1 year ago for year-long personal norms."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "from": {"type": "string", "description": "YYYY-MM-DD or ISO 8601; default = 7 days back. Use from=1 year ago for long-range baselines."},
                    "to": {"type": "string", "description": "YYYY-MM-DD or ISO 8601; default = today."},
                },
                "required": ["name"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "stats_by_hour",
            "description": (
                "Stats restricted to a local-time window [hour_start, hour_end). "
                "Only works for intra-day metrics (hr, stress, body_battery). "
                "Use this to answer 'what's my median HR between 3am and 2pm?' "
                "Set from=1 year ago to get the annual pattern for any hour window."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "enum": ["hr", "stress", "body_battery"]},
                    "hour_start": {"type": "integer", "minimum": 0, "maximum": 23},
                    "hour_end": {"type": "integer", "minimum": 1, "maximum": 24},
                    "from": {"type": "string", "description": "YYYY-MM-DD; can span a full year."},
                    "to": {"type": "string"},
                },
                "required": ["name", "hour_start", "hour_end"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "stats_by_weekday",
            "description": (
                "Stats restricted to specific weekdays (0=Mon ... 6=Sun). "
                "Use to compare e.g. workdays vs weekends."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "weekdays": {
                        "type": "array",
                        "items": {"type": "integer", "minimum": 0, "maximum": 6},
                    },
                    "from": {"type": "string"},
                    "to": {"type": "string"},
                },
                "required": ["name", "weekdays"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "daily_series",
            "description": (
                "Per-day values for charting/inspection. For intra-day metrics, "
                "value = day median. Capped at 365 rows."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "from": {"type": "string"},
                    "to": {"type": "string"},
                },
                "required": ["name"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compare_windows",
            "description": (
                "Compare two date windows (optionally with hour filters) for the "
                "same metric. Returns both stats blocks + delta_pct + a 'significant' "
                "flag. Use for 'is my HRV better on rest days vs training days?' "
                "or 'morning vs afternoon HR.'"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "a_from": {"type": "string"},
                    "a_to": {"type": "string"},
                    "b_from": {"type": "string"},
                    "b_to": {"type": "string"},
                    "a_hour_start": {"type": "integer", "minimum": 0, "maximum": 23},
                    "a_hour_end": {"type": "integer", "minimum": 1, "maximum": 24},
                    "b_hour_start": {"type": "integer", "minimum": 0, "maximum": 23},
                    "b_hour_end": {"type": "integer", "minimum": 1, "maximum": 24},
                },
                "required": ["name"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "correlate",
            "description": (
                "Pearson correlation between two metrics, paired by day. "
                "Returns r + n; only flags correlations with |r|>=0.3 and n>=5. "
                "Reports `reason: insufficient/weak` otherwise."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "metric_a": {"type": "string"},
                    "metric_b": {"type": "string"},
                    "from": {"type": "string"},
                    "to": {"type": "string"},
                },
                "required": ["metric_a", "metric_b"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "stress_burden_by_zone",
            "description": (
                "% of recorded time in each Garmin stress zone (rest 0-25, "
                "low 26-50, medium 51-75, high 76-100) plus a 'burden_pct' "
                "(medium+high combined). Optionally restrict to a local-time "
                "hour window. Use this INSTEAD OF the stress average — a flat "
                "60 for 4h and 0 for 3.5h + 95 for 30 min produce the same "
                "mean but very different physiological pictures."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "from": {"type": "string"},
                    "to": {"type": "string"},
                    "hour_start": {"type": "integer", "minimum": 0, "maximum": 23},
                    "hour_end": {"type": "integer", "minimum": 1, "maximum": 24},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "time_of_day_distribution",
            "description": (
                "Per-hour median + n for an intra-day metric (hr, stress, body_battery) "
                "over [from, to]. Surfaces 'when is your HR lowest/highest?'"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "enum": ["hr", "stress", "body_battery"]},
                    "from": {"type": "string"},
                    "to": {"type": "string"},
                },
                "required": ["name"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_workouts",
            "description": "Up to 50 workouts newest-first in [from, to], optionally filtered by kind.",
            "parameters": {
                "type": "object",
                "properties": {
                    "from": {"type": "string"},
                    "to": {"type": "string"},
                    "kind": {
                        "type": "string",
                        "description": "e.g. running, cycling, strength_training, walking",
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "workout_stats",
            "description": (
                "Per-kind counts + median duration / distance / avg HR / training "
                "effect over [from, to]."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "from": {"type": "string"},
                    "to": {"type": "string"},
                    "kind": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "last_workout",
            "description": "Most recent workout (optionally filtered by kind).",
            "parameters": {
                "type": "object",
                "properties": {"kind": {"type": "string"}},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sleep_stages_for_night",
            "description": (
                "Full sleep-stage timeline for one night: every segment of "
                "awake/light/deep/rem with start/end timestamps + total "
                "minutes per stage + wake-event count. `night_date` is the "
                "WAKE date (YYYY-MM-DD) — e.g. waking up Wednesday morning "
                "from Tuesday-night sleep uses night_date=Wednesday."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "night_date": {
                        "type": "string",
                        "description": "YYYY-MM-DD wake date",
                    },
                },
                "required": ["night_date"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sleep_stages_pattern",
            "description": (
                "Multi-night aggregate of sleep-stage timing and cycling: "
                "per-stage median minutes, median offset (in min after sleep "
                "onset) when each stage FIRST occurs, median longest "
                "contiguous block per stage, median REM cycles per night, "
                "median wake events per night. Default range = last 14 days. "
                "Use this to answer 'when does my deep sleep usually happen?' "
                "or 'how many REM cycles do I average?'"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "from": {"type": "string"},
                    "to": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "body_battery_drop_rate",
            "description": (
                "Median Body Battery drop RATE (points/hour) over the window, "
                "optionally restricted to local-time hours. Negative = drain, "
                "positive = gain. Use this to spot 'fast drain' hours vs "
                "personal baseline — BB always drops during waking hours; "
                "the question is HOW FAST. Returns daily breakdown so the "
                "caller can check consistency."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "from": {"type": "string"},
                    "to": {"type": "string"},
                    "hour_start": {"type": "integer", "minimum": 0, "maximum": 23},
                    "hour_end": {"type": "integer", "minimum": 1, "maximum": 24},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "body_battery_hourly_deltas",
            "description": (
                "For each hour 0-23: median net Body Battery change INSIDE "
                "that hour (last reading − first reading), across days in "
                "the window. Negative = typical drain hour, positive = "
                "typical recovery hour. Use to spot recurring patterns like "
                "'every day at 14:00 BB drops ~12 points' without composing "
                "from raw samples."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "from": {"type": "string"},
                    "to": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sleep_pattern",
            "description": (
                "Median bedtime / wake time (HH:MM, circular-mean aware) + "
                "duration + efficiency over [from, to]. Default lookback = 14 days. "
                "MUST be used when the user asks about typical sleep timing — never invent."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "from": {"type": "string"},
                    "to": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recovery_after",
            "description": (
                "How HRV / RHR / readiness behave the day after workouts of a given kind. "
                "Returns median deltas vs personal 14-day baseline + the last 20 occurrences."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "activity_kind": {"type": "string"},
                    "lookback_days": {"type": "integer", "minimum": 14, "maximum": 365},
                },
                "required": ["activity_kind"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "busy_hours_per_day",
            "description": (
                "Total busy hours per calendar day (timed events only) over [from, to]. "
                "Use to correlate meeting load with energy/focus/sleep."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "from": {"type": "string"},
                    "to": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
    },
    # --------------------------------------------------------------------- #
    # Trend, debt, and planning↔data tools
    # --------------------------------------------------------------------- #
    {
        "type": "function",
        "function": {
            "name": "trend_direction",
            "description": (
                "OLS linear regression on daily metric values → direction: "
                "'improving' | 'declining' | 'stable'. "
                "The direction is pre-interpreted using each metric's sign "
                "convention (HRV: higher=better, RHR: lower=better, etc.) so "
                "you never need to invert signs. "
                "Always call this after get_quick_context when the user asks "
                "whether something is 'getting better' or 'trending.' "
                "Set from=90 days ago for a meaningful trend window. "
                "Example: is my HRV improving? → trend_direction('hrv_overnight_avg', from='90 days ago'). "
                "Returns: direction, slope_per_day, r_squared, n, low_confidence, interpretation."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "metric_name": {
                        "type": "string",
                        "description": (
                            "Metric name. Daily: hrv_overnight_avg, resting_hr, "
                            "sleep_score, sleep_duration_min, body_battery_start, "
                            "stress_avg, vo2_max, steps, etc. "
                            "Intra-day: hr, stress, body_battery."
                        ),
                    },
                    "from": {
                        "type": "string",
                        "description": "YYYY-MM-DD lower bound (default = 30 days ago).",
                    },
                    "to": {
                        "type": "string",
                        "description": "YYYY-MM-DD upper bound (default = today).",
                    },
                },
                "required": ["metric_name"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sleep_debt",
            "description": (
                "Cumulative sleep deficit vs the user's nightly target "
                "(from profile or 7.5h fallback) over the last N nights. "
                "Returns total_deficit_min, days_below_target, per_day breakdown, "
                "worst and best nights. "
                "Use whenever the user asks about sleep debt, recovery debt, "
                "or accumulated sleep deficit."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "minimum": 2,
                        "maximum": 90,
                        "description": "How many recent nights to analyse (default 7).",
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_initiative_metrics",
            "description": (
                "For every active initiative that has a target_metric set, "
                "return the CURRENT metric value vs the target, plus 14-day "
                "baseline. Use this to close the planning↔data loop: "
                "'how am I progressing on my sleep initiative?', "
                "'am I hitting my HRV target?', "
                "or whenever the user asks about goal progress. "
                "Returns: [{initiative_title, area, target_metric, target_value, "
                "current_value, baseline_14d_mean, progress_note}]"
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_food",
            "description": (
                "Estimate the nutritional content of a food item: calories, protein, "
                "carbs, fat, fiber, sugar, and estimated portion weight. "
                "Use this when the user asks about nutrition in a specific food, "
                "or to provide nutritional context after logging a food entry. "
                "Returns a confidence flag (high/medium/low) so you can calibrate "
                "how firmly to state the numbers."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "Food description, e.g. 'chicken salad with avocado and olive oil'.",
                    },
                    "grams": {
                        "type": "number",
                        "description": "Portion weight in grams. Omit to let the model estimate a typical serving.",
                    },
                },
                "required": ["description"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_daily_nutrition",
            "description": (
                "Return the nutritional totals for all food entries logged on a given date: "
                "total calories, protein, carbs, fat, fiber, sugar, and a per-meal breakdown. "
                "Use this when the user asks 'how many calories did I eat today?', "
                "'what's my protein intake?', or similar nutrition-tracking questions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "YYYY-MM-DD date. Omit for today.",
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_nutrition_goals",
            "description": (
                "Return the user's current daily macro nutrition goals: calories, protein, carbs, "
                "fat, fiber, and sugar. If the user has set explicit goals they are returned as-is "
                "(source='set'); otherwise the algorithm suggests goals based on their profile "
                "data (source='suggested' or source='default'). "
                "Call this before answering any question about nutrition targets or progress."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_nutrition_history",
            "description": (
                "Return daily macro nutrition totals for the last N days, compared against goals. "
                "Each day includes the totals consumed, whether each macro goal was hit (true/false), "
                "and an overall hit flag. Also returns a summary (days logged, days hit calories, days hit protein). "
                "Use this to answer questions like 'how many days did I hit my protein goal this week?', "
                "'show me my nutrition history', or 'was I over on carbs last week?'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "description": "How many past days to include (1–90). Default 14.",
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_nutrition_goals",
            "description": (
                "Persist updated daily macro nutrition goals to the user's profile. "
                "Call this when the user asks to change a goal, or after suggesting revised targets "
                "based on their data. You may set any subset of fields — omitted fields are left unchanged."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "calorie_goal": {"type": "number", "description": "Daily calorie target (kcal)."},
                    "protein_g_goal": {"type": "number", "description": "Daily protein target (g)."},
                    "carbs_g_goal": {"type": "number", "description": "Daily carbohydrate target (g)."},
                    "fat_g_goal": {"type": "number", "description": "Daily fat target (g)."},
                    "fiber_g_goal": {"type": "number", "description": "Daily fiber target (g)."},
                    "sugar_g_goal": {"type": "number", "description": "Daily sugar limit (g)."},
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_plan",
            "description": (
                "Save an AI-created goal plan to the database. "
                "Call this ONLY after you have used tools to research the user's data "
                "and have written a concrete, evidence-based plan. "
                "The plan should include specific actions, a rationale grounded in the "
                "user's actual metrics, and optionally a tracked metric + target value. "
                "After saving, confirm to the user that the plan has been created and "
                "summarise what it contains."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "goal": {
                        "type": "string",
                        "description": "One-sentence statement of what the user wants to achieve.",
                    },
                    "plan": {
                        "type": "string",
                        "description": (
                            "Full plan text: specific actions, why each is supported by "
                            "the user's data, and how progress will be measured. "
                            "Use markdown bullet lists."
                        ),
                    },
                    "metric": {
                        "type": "string",
                        "description": "Optional: the primary metric to track (e.g. 'hrv_overnight_avg').",
                    },
                    "target_value": {
                        "type": "number",
                        "description": "Optional: numeric target for the metric.",
                    },
                    "target_date": {
                        "type": "string",
                        "description": "Optional: YYYY-MM-DD target date.",
                    },
                },
                "required": ["goal", "plan"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_plans",
            "description": (
                "List the user's active AI-created plans. Returns goal, plan text, "
                "tracked metric, target, progress_note, and creation date for each. "
                "Use this when the user asks 'what plans do I have?' or when the "
                "topic relates to a goal the user may have set previously."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    # --------------------------------------------------------------------- #
    # Scientific analytics (F10 — doctor-grade biomarker analysis)
    # --------------------------------------------------------------------- #
    {
        "type": "function",
        "function": {
            "name": "sleep_regularity",
            "description": (
                "Sleep Regularity Index (SRI) and social jetlag over the last N days. "
                "SRI (0-100): how consistent sleep timing is; predicts mental health "
                "and metabolic outcomes independently of duration (Phillips et al. 2017). "
                "Social jetlag: absolute weekday vs weekend mid-sleep difference in hours; "
                ">1h linked to metabolic effects, >2h clinically significant. "
                "Use when the user asks about sleep consistency, circadian rhythm, "
                "or why they feel worse on Mondays."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "minimum": 7,
                        "maximum": 90,
                        "description": "Look-back window in days (default 30).",
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "lagged_correlation",
            "description": (
                "Lagged cross-correlation between two daily metrics at lags -N..+N days. "
                "Identifies delayed relationships — e.g. 'does yesterday's stress predict "
                "today's HRV drop?' (lag=-1 on stress vs HRV). "
                "Peak lag and r value are returned with a plain-language interpretation. "
                "Use to answer 'does X affect Y and with how much delay?'"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "metric_a": {
                        "type": "string",
                        "description": "Leading metric (cause side), e.g. 'stress_avg'.",
                    },
                    "metric_b": {
                        "type": "string",
                        "description": "Lagged metric (effect side), e.g. 'hrv_overnight_avg'.",
                    },
                    "max_lag": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 14,
                        "description": "Maximum lag in days to test each side (default 7).",
                    },
                    "days": {
                        "type": "integer",
                        "minimum": 30,
                        "maximum": 365,
                        "description": "Data window in days (default 90).",
                    },
                },
                "required": ["metric_a", "metric_b"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "detect_changepoints",
            "description": (
                "Detect significant mean-shift change points in a metric's recent history. "
                "Compares the trailing 7-day mean against the preceding 28-day baseline "
                "using a z-score threshold. Returns change point dates, direction (up/down), "
                "before/after means, and z-score. "
                "Use to answer 'when did my HRV start dropping?' or 'has anything changed "
                "in my sleep pattern recently?'"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "metric_name": {
                        "type": "string",
                        "description": "Daily metric name, e.g. 'hrv_overnight_avg'.",
                    },
                    "days": {
                        "type": "integer",
                        "minimum": 21,
                        "maximum": 365,
                        "description": "Total data window in days (default 90).",
                    },
                },
                "required": ["metric_name"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recovery_trajectory",
            "description": (
                "Personal recovery fingerprint after a given activity type. "
                "Tracks how HRV, RHR, and readiness change day-by-day for up to 5 days "
                "after workouts, then averages to a 'typical recovery curve'. "
                "Also detects whether the most recent recovery is on track or deviating. "
                "Use to answer 'how long does it take me to recover from a run?' or "
                "'is my recovery after yesterday's workout normal?'"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "activity_kind": {
                        "type": "string",
                        "description": "Workout kind, e.g. 'running', 'strength_training', 'cycling'.",
                    },
                    "lookback_days": {
                        "type": "integer",
                        "minimum": 30,
                        "maximum": 365,
                        "description": "How far back to look for workouts (default 180).",
                    },
                },
                "required": ["activity_kind"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "allostatic_load",
            "description": (
                "Personalised Allostatic Load Index (ALI) — composite score of cumulative "
                "physiological stress across 8 biomarker systems (HRV, RHR, sleep quality, "
                "sleep duration, stress, body battery, VO2max, readiness). "
                "Each marker is flagged 0/1 by comparing recent values to the user's own "
                "trailing distribution (not population norms). Score 0-8: 0-1=low, 2-3=moderate, "
                "4-5=high, 6+=very high. "
                "Use when the user asks 'am I overloaded?' or 'how stressed is my body?'"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "baseline_days": {
                        "type": "integer",
                        "minimum": 30,
                        "maximum": 365,
                        "description": "Baseline distribution window in days (default 90).",
                    },
                    "recent_days": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 14,
                        "description": "Recent averaging window in days (default 7).",
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sleep_architecture",
            "description": (
                "Deep sleep stage architecture analysis from Garmin stage data: "
                "(1) REM latency — time from sleep onset to first REM (normal 70-120 min); "
                "(2) deep-sleep front-loading ratio — fraction of deep sleep in first half "
                "of sleep period (should be >0.5, normally >0.65); "
                "(3) fragmentation index — wake events per hour (normal <5); "
                "(4) REM cycles per night (normal 4-6). "
                "Use when the user asks about sleep quality beyond just duration, "
                "or 'why am I tired despite 8 hours?'"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "minimum": 3,
                        "maximum": 30,
                        "description": "Number of recent nights to analyse (default 14).",
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    # --------------------------------------------------------------------- #
    # Research agent tools
    # --------------------------------------------------------------------- #
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the web via Tavily for up-to-date research, articles, and "
                "information. Use when the user asks about recent research, best "
                "practices, or topics requiring current web data. For health/performance "
                "research use search_depth='advanced' and target authoritative sources "
                "(PubMed, journals, established practitioners). Call 3-8 times with "
                "distinct, focused queries during deep research tasks. Each call returns "
                "title, url, content snippet, and an optional AI-synthesized answer."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Specific research query. Be precise; vague queries return noise.",
                    },
                    "max_results": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 10,
                        "description": "Number of results (default 5).",
                    },
                    "search_depth": {
                        "type": "string",
                        "enum": ["basic", "advanced"],
                        "description": "'advanced' for research; 'basic' for quick lookups.",
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "save_research_paper",
            "description": (
                "Save a research paper to disk after completing a research task. "
                "Call only after: gathering user stats, running 3+ web searches, and "
                "synthesising findings into an actionable paper. Papers persist across "
                "sessions and are retrievable by the bot in future conversations. "
                "Structure: ## Summary, ## Key Findings, ## User Context (user's "
                "relevant metrics), ## Recommendations (specific + measurable), ## Sources."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Short descriptive title.",
                    },
                    "topic": {
                        "type": "string",
                        "description": "Topic category, e.g. 'HRV improvement', 'sleep optimization'.",
                    },
                    "content": {
                        "type": "string",
                        "description": "Full Markdown paper content.",
                    },
                    "sources": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "URLs or references used.",
                    },
                },
                "required": ["title", "topic", "content"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_research_papers",
            "description": (
                "List saved research papers (filename, title, topic, date). "
                "Always check this before starting a research task — prior work may exist."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "description": "Optional topic filter. Omit to list all.",
                    },
                },
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_research_paper",
            "description": (
                "Read the full content of a saved research paper. "
                "Use list_research_papers first to get the exact filename."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "Exact filename from list_research_papers.",
                    },
                },
                "required": ["filename"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "training_load_response",
            "description": (
                "Acute:Chronic Workload Ratio (A:C) — the evidence-based training load "
                "management framework (Gabbett 2016). "
                "Acute load (ATL) = 7-day EWMA, Chronic load (CTL) = 28-day EWMA. "
                "A:C < 0.8 = undertraining; 0.8-1.3 = optimal; 1.3-1.5 = caution; >1.5 = injury risk. "
                "Returns current ratio, risk zone, 7-day trend, and a daily series for charting. "
                "Use when the user asks about training volume, injury risk, or whether to "
                "add or reduce training load."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {
                        "type": "integer",
                        "minimum": 14,
                        "maximum": 180,
                        "description": "Window for the output series in days (default 60).",
                    },
                },
                "additionalProperties": False,
            },
        },
    },
]


__all__ = ["TOOL_SCHEMAS"]
