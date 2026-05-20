"""Garmin sync — transforms API responses into `metrics` rows and UPSERTs them.

Extract functions are pure: they take a Garmin JSON payload and return a list
of `MetricRow` tuples. The orchestrator calls each endpoint, accumulates rows,
and writes them idempotently (UPSERT on `(metric_name, timestamp, source)`).

Each daily metric is anchored at midnight of its calendar date in the user's
TZ — gives a stable key for idempotent re-runs.

Coverage in v1: the high-confidence subset of SPEC §4.2 metrics. The remainder
(active_minutes, calories_active) can be wired post-v1; they are not required
by any F1–F9 function.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from lattice.config import settings
from lattice.integrations.garmin import (
    GarminAuthError,
    GarminClient,
    GarminUnavailable,
    get_client,
)
from lattice.models import Metric, MetricSample, SleepStage, Workout

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# pure transforms
# --------------------------------------------------------------------------- #

@dataclass(slots=True)
class MetricRow:
    timestamp: str
    metric_name: str
    value: float
    unit: str | None = None
    source: str = "garmin"
    metadata: dict[str, Any] | None = None


def _midnight_iso(day: date, tz: str) -> str:
    """Return midnight of `day` in `tz` as ISO 8601 with offset."""
    return datetime.combine(day, time.min, tzinfo=ZoneInfo(tz)).isoformat()


def _to_min(seconds: float | int | None) -> float | None:
    if seconds is None:
        return None
    return round(float(seconds) / 60.0, 2)


def _gmt_millis_to_local_minutes(
    value: Any, tz: str,
) -> tuple[float | None, str | None]:
    """Garmin GMT epoch-millis → (minutes_past_local_midnight, iso_local).

    The "minutes_past_local_midnight" reference is the LOCAL date the event
    actually happened on (NOT necessarily the row's `day` anchor). Stored in
    `value`; the full ISO local timestamp is stashed in `metadata` for
    downstream consumers that need the wraparound-aware value.
    """
    if not isinstance(value, (int, float)):
        return None, None
    try:
        local = (
            datetime.fromtimestamp(float(value) / 1000.0, tz=ZoneInfo("UTC"))
            .astimezone(ZoneInfo(tz))
        )
    except (OverflowError, OSError, ValueError):
        return None, None
    mins = local.hour * 60 + local.minute + local.second / 60.0
    return round(mins, 2), local.isoformat()


def _get(d: dict[str, Any] | None, *path: str) -> Any:
    """Defensive nested-dict access — returns None on any missing key/None."""
    cur: Any = d
    for k in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
        if cur is None:
            return None
    return cur


HRV_STATUS_CODE = {
    "BALANCED": 2,
    "BASELINE": 1,
    "NO_STATUS": 0,
    "UNBALANCED": -1,
    "POOR": -2,
    "LOW": -2,
}


def extract_sleep(data: dict[str, Any] | None, day: date, tz: str) -> list[MetricRow]:
    """SPEC §4.2 sleep_* + respiration_avg + spo2_avg from get_sleep_data."""
    if not data:
        return []
    sleep = data.get("dailySleepDTO") or {}
    ts = _midnight_iso(day, tz)
    rows: list[MetricRow] = []

    score = _get(sleep, "sleepScores", "overall", "value")
    if score is None:
        # Older payloads put overall score at top level.
        score = sleep.get("sleepScoreFeedback")  # rarely numeric; ignore string
        if not isinstance(score, (int, float)):
            score = None
    if score is not None:
        rows.append(MetricRow(ts, "sleep_score", float(score), "score"))

    if (dur := _to_min(sleep.get("sleepTimeSeconds"))) is not None:
        rows.append(MetricRow(ts, "sleep_duration_min", dur, "min"))
    if (deep := _to_min(sleep.get("deepSleepSeconds"))) is not None:
        rows.append(MetricRow(ts, "sleep_deep_min", deep, "min"))
    if (light := _to_min(sleep.get("lightSleepSeconds"))) is not None:
        rows.append(MetricRow(ts, "sleep_light_min", light, "min"))
    if (rem := _to_min(sleep.get("remSleepSeconds"))) is not None:
        rows.append(MetricRow(ts, "sleep_rem_min", rem, "min"))
    if (awake := _to_min(sleep.get("awakeSleepSeconds"))) is not None:
        rows.append(MetricRow(ts, "sleep_awake_min", awake, "min"))

    if (resp := sleep.get("averageRespirationValue")) is not None:
        rows.append(MetricRow(ts, "respiration_avg", float(resp), "bpm"))
    elif (resp := sleep.get("averageRespiration")) is not None:
        rows.append(MetricRow(ts, "respiration_avg", float(resp), "bpm"))

    if (spo2 := sleep.get("averageSpO2Value")) is not None:
        rows.append(MetricRow(ts, "spo2_avg", float(spo2), "%"))
    elif (spo2 := sleep.get("averageSpO2")) is not None:
        rows.append(MetricRow(ts, "spo2_avg", float(spo2), "%"))

    # ----- new in 2K: sleep timing / efficiency / sleep-only HR + stress -----
    start_mins, start_iso = _gmt_millis_to_local_minutes(
        sleep.get("sleepStartTimestampGMT"), tz,
    )
    end_mins, end_iso = _gmt_millis_to_local_minutes(
        sleep.get("sleepEndTimestampGMT"), tz,
    )
    if start_mins is not None:
        rows.append(MetricRow(
            ts, "sleep_start_time", start_mins, "min_of_day",
            metadata={"iso_local": start_iso},
        ))
    if end_mins is not None:
        rows.append(MetricRow(
            ts, "sleep_end_time", end_mins, "min_of_day",
            metadata={"iso_local": end_iso},
        ))

    # Sleep efficiency = time_asleep / time_in_bed * 100.
    sleep_sec = sleep.get("sleepTimeSeconds")
    start_ms = sleep.get("sleepStartTimestampGMT")
    end_ms = sleep.get("sleepEndTimestampGMT")
    if (
        isinstance(sleep_sec, (int, float))
        and isinstance(start_ms, (int, float))
        and isinstance(end_ms, (int, float))
        and end_ms > start_ms
    ):
        in_bed_sec = (float(end_ms) - float(start_ms)) / 1000.0
        if in_bed_sec > 0:
            eff = max(0.0, min(100.0, float(sleep_sec) / in_bed_sec * 100.0))
            rows.append(MetricRow(ts, "sleep_efficiency", round(eff, 2), "%"))

    if (stress_sleep := sleep.get("avgSleepStress")) is not None:
        try:
            rows.append(MetricRow(
                ts, "avg_sleep_stress", float(stress_sleep), "score",
            ))
        except (TypeError, ValueError):
            pass

    # avg HR during sleep — payloads vary; try common shapes.
    sleep_hr = (
        sleep.get("averageHR")
        or sleep.get("averageHr")
        or sleep.get("averageHeartRate")
    )
    if isinstance(sleep_hr, (int, float)) and sleep_hr > 0:
        rows.append(MetricRow(ts, "avg_sleep_hr", float(sleep_hr), "bpm"))

    restless = data.get("restlessMomentsCount")
    if restless is None:
        restless = sleep.get("restlessMomentsCount")
    if isinstance(restless, (int, float)) and restless >= 0:
        rows.append(MetricRow(
            ts, "restless_moments_count", float(restless), "count",
        ))

    return rows


def extract_hrv(data: dict[str, Any] | None, day: date, tz: str) -> list[MetricRow]:
    if not data:
        return []
    summary = data.get("hrvSummary") or {}
    ts = _midnight_iso(day, tz)
    rows: list[MetricRow] = []

    if (avg := summary.get("lastNightAvg")) is not None:
        rows.append(MetricRow(ts, "hrv_overnight_avg", float(avg), "ms"))

    status = summary.get("status")
    if status:
        code = HRV_STATUS_CODE.get(str(status).upper(), 0)
        rows.append(MetricRow(
            ts, "hrv_status", float(code), "ordinal",
            metadata={"status": status},
        ))
    return rows


def extract_stress(data: dict[str, Any] | None, day: date, tz: str) -> list[MetricRow]:
    if not data:
        return []
    ts = _midnight_iso(day, tz)
    rows: list[MetricRow] = []
    avg = data.get("avgStressLevel")
    if avg is not None and avg >= 0:  # Garmin uses -1/-2 for "not enough data"
        rows.append(MetricRow(ts, "stress_avg", float(avg), "score"))
    mx = data.get("maxStressLevel")
    if isinstance(mx, (int, float)) and mx >= 0:
        rows.append(MetricRow(ts, "stress_max", float(mx), "score"))
    mapping = {
        "stress_rest_min":   "restStressDuration",
        "stress_low_min":    "lowStressDuration",
        "stress_medium_min": "mediumStressDuration",
        "stress_high_min":   "highStressDuration",
    }
    for name, key in mapping.items():
        v = _to_min(data.get(key))
        if v is not None:
            rows.append(MetricRow(ts, name, v, "min"))
    return rows


def extract_body_battery(data: Any, day: date, tz: str) -> list[MetricRow]:
    """`get_body_battery` may return either a list of day-dicts or a single dict.

    The raw response carries `bodyBatteryValuesArray` as a sparse list of
    `[timestamp_ms, body_battery_level]` rows (sometimes `[ts, status, level]`
    in older payloads). The values are event markers, not minute-by-minute.

    Semantics:
      - `body_battery_start` — morning post-recharge peak (max of the day).
        Used by F1 readiness (10% weight) as the "starting body battery"
        after overnight recovery.
      - `body_battery_end`   — last reading of the day.
      - `body_battery_min`   — lowest reading of the day.
    """
    if not data:
        return []
    day_entry: dict[str, Any] | None = None
    if isinstance(data, list):
        for entry in data:
            if entry.get("date") == day.isoformat() or len(data) == 1:
                day_entry = entry
                break
    elif isinstance(data, dict):
        day_entry = data
    if not day_entry:
        return []

    raw = day_entry.get("bodyBatteryValuesArray") or []
    values: list[float] = []
    for row in raw:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        # 3-tuple: [ts, status, value]. 2-tuple: [ts, value].
        v = row[-1] if len(row) >= 3 else row[1]
        if isinstance(v, (int, float)):
            values.append(float(v))
    if not values:
        return []
    ts = _midnight_iso(day, tz)
    rows = [
        MetricRow(ts, "body_battery_start", max(values), "score"),
        MetricRow(ts, "body_battery_end",   values[-1],  "score"),
        MetricRow(ts, "body_battery_min",   min(values), "score"),
    ]
    charged = day_entry.get("charged")
    if isinstance(charged, (int, float)) and charged >= 0:
        rows.append(MetricRow(
            ts, "body_battery_charged", float(charged), "score",
        ))
    drained = day_entry.get("drained")
    if isinstance(drained, (int, float)) and drained >= 0:
        rows.append(MetricRow(
            ts, "body_battery_drained", float(drained), "score",
        ))
    return rows


def extract_resting_hr(data: dict[str, Any] | None, day: date, tz: str) -> list[MetricRow]:
    """Resting HR + full-day HR summary (max/min/avg) from get_heart_rates.

    Name kept for backward compat; the function now also emits hr_max_day,
    hr_min_day, and hr_avg_day when those fields are present in the payload.
    """
    if not data:
        return []
    ts = _midnight_iso(day, tz)
    rows: list[MetricRow] = []
    rhr = data.get("restingHeartRate")
    if isinstance(rhr, (int, float)) and rhr > 0:
        rows.append(MetricRow(ts, "resting_hr", float(rhr), "bpm"))
    mx = data.get("maxHeartRate")
    if isinstance(mx, (int, float)) and mx > 0:
        rows.append(MetricRow(ts, "hr_max_day", float(mx), "bpm"))
    mn = data.get("minHeartRate")
    if isinstance(mn, (int, float)) and mn > 0:
        rows.append(MetricRow(ts, "hr_min_day", float(mn), "bpm"))

    # heartRateValues is a [[ts, value], ...] sparse list; ignore None values.
    hr_values = data.get("heartRateValues")
    if isinstance(hr_values, list):
        nums: list[float] = []
        for row in hr_values:
            if not isinstance(row, (list, tuple)) or len(row) < 2:
                continue
            v = row[-1]
            if isinstance(v, (int, float)) and v > 0:
                nums.append(float(v))
        if nums:
            avg = sum(nums) / len(nums)
            rows.append(MetricRow(ts, "hr_avg_day", round(avg, 2), "bpm"))
    return rows


def extract_training_status(
    data: dict[str, Any] | None, day: date, tz: str,
) -> list[MetricRow]:
    if not data:
        return []
    ts = _midnight_iso(day, tz)
    rows: list[MetricRow] = []

    vo2 = _get(data, "mostRecentVO2Max", "generic", "vo2MaxPreciseValue")
    if vo2 is None:
        vo2 = _get(data, "mostRecentVO2Max", "generic", "vo2MaxValue")
    if vo2 is not None:
        rows.append(MetricRow(ts, "vo2_max", float(vo2), "ml/kg/min"))

    # latest_*Data lives under a device-id key; pick the first non-empty.
    status_data = _get(data, "mostRecentTrainingStatus", "latestTrainingStatusData") or {}
    if isinstance(status_data, dict) and status_data:
        first = next(iter(status_data.values()), {})
        load = first.get("acuteTrainingLoadDTO") or {}
        if (acute := load.get("acuteTrainingLoad")) is not None:
            rows.append(MetricRow(ts, "training_load_acute", float(acute), "TL"))
        if (chronic := load.get("chronicTrainingLoad")) is not None:
            rows.append(MetricRow(ts, "training_load_chronic", float(chronic), "TL"))
        status_str = first.get("trainingStatus") or first.get("trainingStatusKey")
        if isinstance(status_str, str):
            rows.append(MetricRow(
                ts, "training_status", 0.0, "label",
                metadata={"status": status_str},
            ))
    return rows


def extract_steps(data: Any, day: date, tz: str) -> list[MetricRow]:
    """`get_steps_data` returns hourly buckets; sum to a daily total."""
    if not data:
        return []
    total: float = 0.0
    if isinstance(data, list):
        for row in data:
            if isinstance(row, dict) and isinstance(row.get("steps"), (int, float)):
                total += float(row["steps"])
    elif isinstance(data, dict) and isinstance(data.get("totalSteps"), (int, float)):
        total = float(data["totalSteps"])
    if total <= 0:
        return []
    return [MetricRow(_midnight_iso(day, tz), "steps", total, "count")]


def extract_user_summary(
    data: dict[str, Any] | None, day: date, tz: str,
) -> list[MetricRow]:
    """Daily user-summary metrics from `get_stats(day)`:
    active_minutes, calories_active, calories_total,
    intensity_minutes_moderate / _vigorous, floors_climbed, distance_m.
    """
    if not data:
        return []
    ts = _midnight_iso(day, tz)
    rows: list[MetricRow] = []

    active_sec = data.get("activeSeconds")
    if isinstance(active_sec, (int, float)) and active_sec >= 0:
        rows.append(MetricRow(
            ts, "active_minutes", round(float(active_sec) / 60.0, 2), "min",
        ))

    active_cals = data.get("activeKilocalories")
    if isinstance(active_cals, (int, float)) and active_cals >= 0:
        rows.append(MetricRow(
            ts, "calories_active", float(active_cals), "kcal",
        ))
    total_cals = data.get("totalKilocalories")
    if isinstance(total_cals, (int, float)) and total_cals >= 0:
        rows.append(MetricRow(
            ts, "calories_total", float(total_cals), "kcal",
        ))

    mod = data.get("moderateIntensityMinutes")
    if isinstance(mod, (int, float)) and mod >= 0:
        rows.append(MetricRow(
            ts, "intensity_minutes_moderate", float(mod), "min",
        ))
    vig = data.get("vigorousIntensityMinutes")
    if isinstance(vig, (int, float)) and vig >= 0:
        rows.append(MetricRow(
            ts, "intensity_minutes_vigorous", float(vig), "min",
        ))

    floors = data.get("floorsAscended")
    if isinstance(floors, (int, float)) and floors >= 0:
        rows.append(MetricRow(ts, "floors_climbed", float(floors), "count"))

    distance = data.get("totalDistanceMeters")
    if not isinstance(distance, (int, float)):
        distance = data.get("dailyDistanceMeters")
    if isinstance(distance, (int, float)) and distance >= 0:
        rows.append(MetricRow(ts, "distance_m", float(distance), "m"))

    return rows


# --------------------------------------------------------------------------- #
# orchestration
# --------------------------------------------------------------------------- #

@dataclass(slots=True)
class SampleRow:
    """One intra-day measurement row, written to `metric_samples`."""
    timestamp: str
    metric_name: str
    value: float
    source: str = "garmin"


@dataclass(slots=True)
class SleepStageRow:
    """One sleep-stage segment, written to `sleep_stages`."""
    night_date: str  # YYYY-MM-DD of the wake day
    start: str
    end: str
    stage: str       # "awake" | "light" | "deep" | "rem"
    duration_min: float


# Garmin's activityLevel float → canonical stage label.
# Garmin encodes: 0 = deep, 1 = light, 2 = REM, 3 = awake.
_STAGE_FROM_LEVEL: dict[float, str] = {
    0.0: "deep",
    1.0: "light",
    2.0: "rem",
    3.0: "awake",
    -1.0: "awake",  # very old "unmeasurable" rows; treat as awake
}

# String forms Garmin sometimes uses on the `sleep_level` field.
_STAGE_FROM_STR: dict[str, str] = {
    "awake": "awake",
    "light": "light",
    "deep": "deep",
    "rem": "rem",
}


def _normalize_stage(value: Any) -> str | None:
    if isinstance(value, (int, float)):
        return _STAGE_FROM_LEVEL.get(float(value))
    if isinstance(value, str):
        return _STAGE_FROM_STR.get(value.strip().lower())
    return None


def _parse_garmin_ts(value: Any, tz: str) -> str | None:
    """Garmin stage timestamps come as either epoch-millis or `YYYY-MM-DDTHH:MM:SS.0`.

    Always returned in local-TZ ISO-8601 with offset so SQLite sorts cleanly
    and downstream consumers see one format.
    """
    if value is None:
        return None
    zone = ZoneInfo(tz)
    if isinstance(value, (int, float)):
        try:
            return (
                datetime.fromtimestamp(float(value) / 1000.0, tz=ZoneInfo("UTC"))
                .astimezone(zone)
                .isoformat()
            )
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        try:
            # Tolerate trailing ".0" / ".000" microsecond noise; strip it.
            base = value.split(".")[0]
            dt = datetime.fromisoformat(base)
            if dt.tzinfo is None:
                # Garmin "GMT" suffix means UTC.
                dt = dt.replace(tzinfo=ZoneInfo("UTC"))
            return dt.astimezone(zone).isoformat()
        except (TypeError, ValueError):
            return None
    return None


def extract_sleep_stages(
    data: dict[str, Any] | None, day: date, tz: str,
) -> list[SleepStageRow]:
    """Parse `sleepLevels` from a `get_sleep_data` payload into stage segments.

    Each segment has start/end timestamps + a level (float 0-3) OR a string.
    Skips segments with bad timestamps, zero duration, or unknown stage labels.
    """
    if not data:
        return []
    raw = data.get("sleepLevels") or []
    if not isinstance(raw, list):
        return []

    night = day.isoformat()
    rows: list[SleepStageRow] = []
    for seg in raw:
        if not isinstance(seg, dict):
            continue
        start_iso = _parse_garmin_ts(
            seg.get("startGMT") or seg.get("startTimeGMT"), tz,
        )
        end_iso = _parse_garmin_ts(
            seg.get("endGMT") or seg.get("endTimeGMT"), tz,
        )
        if not start_iso or not end_iso:
            continue
        stage = _normalize_stage(
            seg.get("activityLevel")
            if "activityLevel" in seg
            else seg.get("level") or seg.get("sleep_level") or seg.get("sleepLevel"),
        )
        if stage is None:
            continue
        try:
            start_dt = datetime.fromisoformat(start_iso)
            end_dt = datetime.fromisoformat(end_iso)
        except ValueError:
            continue
        duration_sec = (end_dt - start_dt).total_seconds()
        if duration_sec <= 0:
            continue
        rows.append(SleepStageRow(
            night_date=night,
            start=start_iso,
            end=end_iso,
            stage=stage,
            duration_min=round(duration_sec / 60.0, 2),
        ))
    return rows


def _ms_to_iso(ms: Any, tz: str) -> str | None:
    """Garmin epoch-millis (UTC) → ISO local string. Returns None on bad input."""
    if not isinstance(ms, (int, float)):
        return None
    try:
        return (
            datetime.fromtimestamp(float(ms) / 1000.0, tz=ZoneInfo("UTC"))
            .astimezone(ZoneInfo(tz))
            .isoformat()
        )
    except (OverflowError, OSError, ValueError):
        return None


def extract_hr_samples(
    data: dict[str, Any] | None, tz: str,
) -> list[SampleRow]:
    """Per-minute heart rate readings from `get_heart_rates(day)`.

    Garmin shape: `heartRateValues = [[ts_ms, bpm], ...]` with `None` for gaps.
    """
    if not data:
        return []
    raw = data.get("heartRateValues")
    if not isinstance(raw, list):
        return []
    rows: list[SampleRow] = []
    for r in raw:
        if not isinstance(r, (list, tuple)) or len(r) < 2:
            continue
        ts_ms, value = r[0], r[-1]
        if not isinstance(value, (int, float)) or value <= 0:
            continue
        iso = _ms_to_iso(ts_ms, tz)
        if iso is None:
            continue
        rows.append(SampleRow(iso, "hr", float(value)))
    return rows


def extract_stress_samples(
    data: dict[str, Any] | None, tz: str,
) -> list[SampleRow]:
    """Per-minute stress score from `get_stress_data(day)`.

    Garmin shape: `stressValuesArray = [[ts_ms, value], ...]` with negative
    values (-1 / -2) meaning "no measurement"; those are dropped.
    """
    if not data:
        return []
    raw = data.get("stressValuesArray")
    if not isinstance(raw, list):
        return []
    rows: list[SampleRow] = []
    for r in raw:
        if not isinstance(r, (list, tuple)) or len(r) < 2:
            continue
        ts_ms, value = r[0], r[-1]
        if not isinstance(value, (int, float)) or value < 0:
            continue
        iso = _ms_to_iso(ts_ms, tz)
        if iso is None:
            continue
        rows.append(SampleRow(iso, "stress", float(value)))
    return rows


def extract_body_battery_samples(
    data: Any, day: date, tz: str,
) -> list[SampleRow]:
    """Body battery samples from `get_body_battery(day)`.

    Two shapes: list-of-day-dicts (current Garmin) or single dict (older).
    Each `bodyBatteryValuesArray` entry is `[ts_ms, value]` or
    `[ts_ms, status, value]`. `None` values dropped.
    """
    if not data:
        return []
    day_entry: dict[str, Any] | None = None
    if isinstance(data, list):
        for entry in data:
            if entry.get("date") == day.isoformat() or len(data) == 1:
                day_entry = entry
                break
    elif isinstance(data, dict):
        day_entry = data
    if not day_entry:
        return []
    raw = day_entry.get("bodyBatteryValuesArray") or []
    rows: list[SampleRow] = []
    for r in raw:
        if not isinstance(r, (list, tuple)) or len(r) < 2:
            continue
        ts_ms = r[0]
        value = r[-1] if len(r) >= 3 else r[1]
        if not isinstance(value, (int, float)):
            continue
        iso = _ms_to_iso(ts_ms, tz)
        if iso is None:
            continue
        rows.append(SampleRow(iso, "body_battery", float(value)))
    return rows


@dataclass(slots=True)
class WorkoutRow:
    garmin_activity_id: str
    start: str
    duration_min: float
    kind: str
    distance_m: float | None = None
    avg_hr: float | None = None
    max_hr: float | None = None
    calories: float | None = None
    training_effect: float | None = None
    metadata: dict[str, Any] | None = None


def extract_workouts(
    activities: list[dict[str, Any]] | None, tz: str,
) -> list[WorkoutRow]:
    """Convert a list of Garmin activities into WorkoutRow tuples.

    Skips activities lacking a stable id, a parseable start time, or a
    positive duration. Optional fields (HR, distance, calories, training
    effect) are only emitted when present and sensible.
    """
    if not activities:
        return []
    rows: list[WorkoutRow] = []
    for act in activities:
        if not isinstance(act, dict):
            continue
        aid = act.get("activityId")
        if aid is None:
            continue

        start_iso: str | None = None
        local = act.get("startTimeLocal")
        if isinstance(local, str):
            try:
                dt = datetime.fromisoformat(local).replace(tzinfo=ZoneInfo(tz))
                start_iso = dt.isoformat()
            except ValueError:
                start_iso = None
        if start_iso is None:
            gmt = act.get("startTimeGMT")
            if isinstance(gmt, str):
                try:
                    dt = datetime.fromisoformat(gmt).replace(tzinfo=ZoneInfo("UTC"))
                    start_iso = dt.astimezone(ZoneInfo(tz)).isoformat()
                except ValueError:
                    start_iso = None
        if start_iso is None:
            continue

        dur_sec = act.get("duration")
        if not isinstance(dur_sec, (int, float)) or dur_sec <= 0:
            continue

        # activityType can be a dict {typeKey: "running"} or a string.
        atype = act.get("activityType")
        if isinstance(atype, dict):
            kind = str(atype.get("typeKey") or "unknown")
        elif isinstance(atype, str):
            kind = atype
        else:
            kind = "unknown"

        def _opt_pos(v: Any) -> float | None:
            return float(v) if isinstance(v, (int, float)) and v > 0 else None

        def _opt_nonneg(v: Any) -> float | None:
            return float(v) if isinstance(v, (int, float)) and v >= 0 else None

        meta: dict[str, Any] = {}
        for k in ("activityName", "anaerobicTrainingEffect"):
            if isinstance(act.get(k), (int, float, str)):
                meta[k] = act[k]

        rows.append(WorkoutRow(
            garmin_activity_id=str(aid),
            start=start_iso,
            duration_min=round(float(dur_sec) / 60.0, 2),
            kind=kind,
            distance_m=_opt_pos(act.get("distance")),
            avg_hr=_opt_pos(act.get("averageHR")),
            max_hr=_opt_pos(act.get("maxHR")),
            calories=_opt_nonneg(act.get("calories")),
            training_effect=_opt_nonneg(act.get("aerobicTrainingEffect")),
            metadata=meta or None,
        ))
    return rows


@dataclass
class SyncReport:
    dates: list[str] = field(default_factory=list)
    rows_written: int = 0
    workouts_written: int = 0
    samples_written: int = 0
    stages_written: int = 0
    errors: list[str] = field(default_factory=list)


async def _fetch_all(
    client: GarminClient, day: date, tz: str,
) -> tuple[list[MetricRow], list[SampleRow], list[SleepStageRow], list[str]]:
    """Pull every endpoint. Returns (daily_rows, samples, sleep_stages, errors).

    Some endpoints (sleep, heart_rates, stress, body_battery) feed multiple
    extractors. We fetch each payload once and dispatch all of them.
    """
    rows: list[MetricRow] = []
    samples: list[SampleRow] = []
    stages: list[SleepStageRow] = []
    errors: list[str] = []

    async def _fetch(name: str, coro: Any) -> Any | None:
        try:
            return await coro
        except GarminAuthError:
            raise
        except GarminUnavailable as exc:
            errors.append(f"{name}: {exc}")
            return None
        except Exception as exc:  # noqa: BLE001 — third-party
            logger.warning("garmin %s failed for %s: %s", name, day, exc)
            errors.append(f"{name}: {exc}")
            return None

    def _xform(name: str, fn: Any, *args: Any) -> Any:
        try:
            return fn(*args)
        except Exception as exc:  # noqa: BLE001 — defensive
            logger.warning("transform %s failed for %s: %s", name, day, exc)
            errors.append(f"{name} transform: {exc}")
            return []

    # Sleep payload feeds the daily aggregate extractor + the stage timeline.
    sleep_data = await _fetch("sleep", client.get_sleep(day))
    rows.extend(_xform("sleep", extract_sleep, sleep_data, day, tz))
    stages.extend(_xform("sleep_stages", extract_sleep_stages, sleep_data, day, tz))

    hrv_data = await _fetch("hrv", client.get_hrv(day))
    rows.extend(_xform("hrv", extract_hrv, hrv_data, day, tz))

    training_data = await _fetch("training_status", client.get_training_status(day))
    rows.extend(_xform("training_status", extract_training_status, training_data, day, tz))

    steps_data = await _fetch("steps", client.get_steps(day))
    rows.extend(_xform("steps", extract_steps, steps_data, day, tz))

    stats_data = await _fetch("user_summary", client.get_stats(day))
    rows.extend(_xform("user_summary", extract_user_summary, stats_data, day, tz))

    # Dual-dispatch: same payload feeds daily aggregate + intra-day samples.
    stress_data = await _fetch("stress", client.get_stress(day))
    rows.extend(_xform("stress", extract_stress, stress_data, day, tz))
    samples.extend(_xform("stress_samples", extract_stress_samples, stress_data, tz))

    bb_data = await _fetch("body_battery", client.get_body_battery(day))
    rows.extend(_xform("body_battery", extract_body_battery, bb_data, day, tz))
    samples.extend(_xform("bb_samples", extract_body_battery_samples, bb_data, day, tz))

    hr_data = await _fetch("heart_rates", client.get_heart_rates(day))
    rows.extend(_xform("heart_rates", extract_resting_hr, hr_data, day, tz))
    samples.extend(_xform("hr_samples", extract_hr_samples, hr_data, tz))

    return rows, samples, stages, errors


async def _upsert_sleep_stages(
    session: AsyncSession, rows: list[SleepStageRow],
) -> int:
    """Idempotent UPSERT into `sleep_stages` keyed on `(night_date, start, stage)`.

    On conflict we update `end` and `duration_min` so a re-sync with a corrected
    sleep timeline (Garmin occasionally adjusts boundaries) overwrites cleanly.
    """
    if not rows:
        return 0
    payload = [
        {
            "night_date": r.night_date,
            "start": r.start,
            "end": r.end,
            "stage": r.stage,
            "duration_min": r.duration_min,
        }
        for r in rows
    ]
    stmt = sqlite_insert(SleepStage.__table__).values(payload)
    stmt = stmt.on_conflict_do_update(
        index_elements=["night_date", "start", "stage"],
        set_={
            "end": stmt.excluded.end,
            "duration_min": stmt.excluded.duration_min,
        },
    )
    await session.execute(stmt)
    await session.commit()
    return len(payload)


async def _upsert_samples(
    session: AsyncSession, rows: list[SampleRow],
) -> int:
    """Idempotent UPSERT into `metric_samples`.

    Batches at 500 rows per statement — SQLite has a 999-parameter limit and
    each row uses 4 parameters, so 500 keeps us well under.
    """
    if not rows:
        return 0
    BATCH = 500
    total = 0
    for i in range(0, len(rows), BATCH):
        chunk = rows[i : i + BATCH]
        payload = [
            {
                "timestamp": r.timestamp,
                "metric_name": r.metric_name,
                "value": r.value,
                "source": r.source,
            }
            for r in chunk
        ]
        stmt = sqlite_insert(MetricSample.__table__).values(payload)
        stmt = stmt.on_conflict_do_update(
            index_elements=["metric_name", "timestamp", "source"],
            set_={"value": stmt.excluded.value},
        )
        await session.execute(stmt)
        total += len(payload)
    await session.commit()
    return total


async def _upsert_workouts(
    session: AsyncSession, rows: list[WorkoutRow],
) -> int:
    """Idempotent UPSERT into `workouts`, keyed on `garmin_activity_id`."""
    if not rows:
        return 0
    payload = [
        {
            "garmin_activity_id": r.garmin_activity_id,
            "start": r.start,
            "duration_min": r.duration_min,
            "kind": r.kind,
            "distance_m": r.distance_m,
            "avg_hr": r.avg_hr,
            "max_hr": r.max_hr,
            "calories": r.calories,
            "training_effect": r.training_effect,
            "metadata": json.dumps(r.metadata) if r.metadata is not None else None,
        }
        for r in rows
    ]
    stmt = sqlite_insert(Workout.__table__).values(payload)
    stmt = stmt.on_conflict_do_update(
        index_elements=["garmin_activity_id"],
        set_={
            "start": stmt.excluded.start,
            "duration_min": stmt.excluded.duration_min,
            "kind": stmt.excluded.kind,
            "distance_m": stmt.excluded.distance_m,
            "avg_hr": stmt.excluded.avg_hr,
            "max_hr": stmt.excluded.max_hr,
            "calories": stmt.excluded.calories,
            "training_effect": stmt.excluded.training_effect,
            "metadata": stmt.excluded.metadata,
        },
    )
    await session.execute(stmt)
    await session.commit()
    return len(payload)


async def _upsert_rows(session: AsyncSession, rows: list[MetricRow]) -> int:
    """Idempotent UPSERT into `metrics`. Returns count of rows written (insert or update)."""
    if not rows:
        return 0
    payload = [
        {
            "timestamp": r.timestamp,
            "metric_name": r.metric_name,
            "value": r.value,
            "unit": r.unit,
            "source": r.source,
            "metadata": json.dumps(r.metadata) if r.metadata is not None else None,
        }
        for r in rows
    ]
    stmt = sqlite_insert(Metric.__table__).values(payload)
    stmt = stmt.on_conflict_do_update(
        index_elements=["metric_name", "timestamp", "source"],
        set_={
            "value": stmt.excluded.value,
            "unit": stmt.excluded.unit,
            "metadata": stmt.excluded.metadata,
        },
    )
    await session.execute(stmt)
    await session.commit()
    return len(payload)


async def sync_date(
    session: AsyncSession, day: date, client: GarminClient | None = None,
) -> SyncReport:
    """Fetch + UPSERT one day's metrics, samples, sleep stages, and workouts."""
    client = client or get_client()
    report = SyncReport(dates=[day.isoformat()])
    rows, samples, stages, errors = await _fetch_all(client, day, settings.timezone)
    report.errors.extend(errors)
    report.rows_written = await _upsert_rows(session, rows)
    report.samples_written = await _upsert_samples(session, samples)
    report.stages_written = await _upsert_sleep_stages(session, stages)

    # Workouts — separate call (get_activities_by_date) per day.
    try:
        activities = await client.get_activities(day, day)
        workout_rows = extract_workouts(activities, settings.timezone)
        report.workouts_written = await _upsert_workouts(session, workout_rows)
    except GarminAuthError:
        raise
    except GarminUnavailable as exc:
        report.errors.append(f"activities: {exc}")
    except Exception as exc:  # noqa: BLE001 — third-party
        logger.warning("garmin activities failed for %s: %s", day, exc)
        report.errors.append(f"activities: {exc}")

    return report


async def sync_range(
    session: AsyncSession, start: date, end: date,
    client: GarminClient | None = None,
) -> SyncReport:
    """Inclusive date range; oldest → newest."""
    if start > end:
        raise ValueError("start must be <= end")
    client = client or get_client()
    report = SyncReport()
    day = start
    while day <= end:
        sub = await sync_date(session, day, client)
        report.dates.extend(sub.dates)
        report.rows_written += sub.rows_written
        report.workouts_written += sub.workouts_written
        report.samples_written += sub.samples_written
        report.stages_written += sub.stages_written
        report.errors.extend(sub.errors)
        day += timedelta(days=1)
    return report


async def sync_recent(
    session: AsyncSession, days: int = 1, client: GarminClient | None = None,
) -> SyncReport:
    """Sync the last `days` days ending today (in the user's TZ)."""
    tz = ZoneInfo(settings.timezone)
    today = datetime.now(tz).date()
    start = today - timedelta(days=max(0, days - 1))
    return await sync_range(session, start, today, client)


# --------------------------------------------------------------------------- #
# helpers used by the API layer
# --------------------------------------------------------------------------- #

async def latest_for(
    session: AsyncSession, metric_name: str,
) -> Metric | None:
    """Return the most recent row for a metric, or None."""
    stmt = (
        select(Metric)
        .where(Metric.metric_name == metric_name)
        .order_by(Metric.timestamp.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()
