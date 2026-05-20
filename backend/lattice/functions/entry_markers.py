"""Contextual markers for a single entry — timing, daily context, and historical patterns.

Called by GET /entries/:id/markers. Returns a flat list of labeled chips so the
frontend can render them uniformly without needing to know entry type specifics.
"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from lattice.functions.baselines import parse_iso
from lattice.models import Entry
from lattice.schemas.entries import classify_drink


def _chip(label: str, value: str, sentiment: str = "neutral") -> dict[str, str]:
    return {"label": label, "value": value, "sentiment": sentiment}


def _hour_label(h: int) -> str:
    if h < 6:
        return "night"
    if h < 12:
        return "morning"
    if h < 14:
        return "midday"
    if h < 18:
        return "afternoon"
    if h < 21:
        return "evening"
    return "night"


async def compute_entry_markers(
    session: AsyncSession,
    entry_id: int,
    tz: str,
) -> dict[str, Any]:
    """Compute contextual markers for entry `entry_id`. Returns serializable dict."""
    row = await session.get(Entry, entry_id)
    if row is None:
        return {"error": "not_found", "entry_id": entry_id}

    try:
        data = json.loads(row.data)
    except (json.JSONDecodeError, TypeError):
        data = {}

    zone = ZoneInfo(tz)
    try:
        entry_ts = parse_iso(row.timestamp).astimezone(zone)
    except (ValueError, AttributeError):
        entry_ts = datetime.now(zone)

    entry_date = entry_ts.date()

    if row.type == "drink":
        markers = await _drink_markers(session, data, entry_ts, entry_date, tz, zone)
    elif row.type == "food":
        markers = await _food_markers(session, data, entry_ts, entry_date, zone)
    elif row.type in ("mood", "energy", "focus"):
        markers = await _score_markers(session, row.type, data, entry_ts, entry_date)
    elif row.type == "symptom":
        markers = _symptom_markers(data, entry_ts)
    else:
        markers = [_chip("time", f"{entry_ts.strftime('%H:%M')} · {_hour_label(entry_ts.hour)}", "info")]

    return {
        "entry_id": entry_id,
        "type": row.type,
        "timestamp": row.timestamp,
        "markers": markers,
    }


# ---------------------------------------------------------------------------
# Per-type marker builders
# ---------------------------------------------------------------------------


async def _drink_markers(
    session: AsyncSession,
    data: dict[str, Any],
    entry_ts: datetime,
    entry_date: date,
    tz: str,
    zone: ZoneInfo,
) -> list[dict[str, str]]:
    from lattice.functions.sleep_window import compute_sleep_window

    markers: list[dict[str, str]] = []
    hour = entry_ts.hour
    count = float(data.get("count") or 1)
    kind = data.get("kind", "")
    sub_type = data.get("sub_type")
    caffeine_mg = data.get("caffeine_mg")

    # Estimate caffeine for entries that pre-date the sub_type field.
    if caffeine_mg is None and kind:
        _, _, caffeine_mg = classify_drink(sub_type or kind)

    if caffeine_mg and float(caffeine_mg) > 0:
        total_this = float(caffeine_mg) * count
        drink_label = sub_type or kind or "drink"
        markers.append(_chip("caffeine", f"{total_this:.0f}mg ({drink_label})", "neutral"))

        # --- daily caffeine total ---
        day_start = datetime.combine(entry_date, time.min, tzinfo=zone)
        day_end = day_start + timedelta(days=1)
        rows = (await session.execute(text(
            "SELECT data FROM entries WHERE type='drink' "
            "AND timestamp >= :s AND timestamp < :e"
        ), {"s": day_start.isoformat(), "e": day_end.isoformat()})).fetchall()

        daily_total = 0.0
        daily_count = 0
        for (raw,) in rows:
            try:
                d = json.loads(raw)
            except Exception:
                continue
            mg = d.get("caffeine_mg")
            if mg is None:
                dk = d.get("kind", "")
                _, _, mg = classify_drink(d.get("sub_type") or dk)
            if mg and float(mg) > 0:
                daily_total += float(mg) * float(d.get("count") or 1)
                daily_count += 1

        if daily_count > 0:
            daily_sent = "neutral" if daily_total <= 300 else "bad"
            markers.append(_chip(
                "daily total",
                f"{daily_count} drink{'s' if daily_count != 1 else ''} · {daily_total:.0f}mg",
                daily_sent,
            ))

        # --- residual at bedtime ---
        try:
            sleep_w = await compute_sleep_window(session, target=entry_date, tz=tz)
            bedtime = parse_iso(sleep_w.bedtime).astimezone(zone)
            h_to_bed = (bedtime - entry_ts).total_seconds() / 3600.0
            if h_to_bed > 0:
                residual = total_this * (0.5 ** (h_to_bed / 5.0))
                safe = residual <= 50.0
                markers.append(_chip(
                    "residual at bedtime",
                    f"{residual:.0f}mg at {bedtime.strftime('%H:%M')} · {'safe' if safe else 'over limit'}",
                    "good" if safe else "bad",
                ))
                timing_sent = "good" if h_to_bed >= 6 else ("neutral" if h_to_bed >= 4 else "bad")
                markers.append(_chip(
                    "timing",
                    f"{h_to_bed:.1f}h before target sleep ({bedtime.strftime('%H:%M')})",
                    timing_sent,
                ))
        except Exception:
            pass

        # --- historical sleep impact ---
        try:
            hour_str = f"{hour:02d}"
            since = (entry_date - timedelta(days=30)).isoformat()
            caffeinated_days = set(r[0] for r in (await session.execute(text("""
                SELECT DISTINCT strftime('%Y-%m-%d', timestamp) as day
                FROM entries
                WHERE type = 'drink'
                  AND (json_extract(data, '$.caffeine_mg') IS NOT NULL
                       OR json_extract(data, '$.kind') = 'coffee')
                  AND strftime('%H', timestamp) >= :h
                  AND timestamp >= :since
            """), {"h": hour_str, "since": since})).fetchall())

            if len(caffeinated_days) >= 5:
                phs = ",".join(f"'{d}'" for d in caffeinated_days)
                scores_with = [float(r[0]) for r in (await session.execute(text(
                    f"SELECT value FROM metrics WHERE metric_name='sleep_score' "
                    f"AND strftime('%Y-%m-%d', timestamp) IN ({phs})"
                ))).fetchall() if r[0] is not None]
                baseline_row = (await session.execute(text(
                    "SELECT avg(value) FROM metrics WHERE metric_name='sleep_score' AND timestamp >= :s"
                ), {"s": since})).fetchone()
                baseline = float(baseline_row[0]) if baseline_row and baseline_row[0] else None
                if scores_with and baseline is not None:
                    avg_w = sum(scores_with) / len(scores_with)
                    delta = avg_w - baseline
                    n = len(scores_with)
                    markers.append(_chip(
                        "sleep impact",
                        f"Caffeine after {hour:02d}:00 → sleep_score {delta:+.0f}pts vs {baseline:.0f} baseline (n={n}, 30d)",
                        "bad" if delta <= -5 else ("good" if delta >= 3 else "neutral"),
                    ))
        except Exception:
            pass

    else:
        drink_label = sub_type or kind or "drink"
        markers.append(_chip("drink", drink_label, "info"))
        markers.append(_chip("time", f"{entry_ts.strftime('%H:%M')} · {_hour_label(hour)}", "info"))

    return markers


async def _food_markers(
    session: AsyncSession,
    data: dict[str, Any],
    entry_ts: datetime,
    entry_date: date,
    zone: ZoneInfo,
) -> list[dict[str, str]]:
    markers: list[dict[str, str]] = []
    meal_type = data.get("meal_type")
    hour = entry_ts.hour

    # --- nutrition — individual macro chips ---
    nutrition = data.get("nutrition")
    if nutrition:
        kcal = nutrition.get("calories")
        protein = nutrition.get("protein_g")
        carbs = nutrition.get("carbs_g")
        fat = nutrition.get("fat_g")
        fiber = nutrition.get("fiber_g")
        sugar = nutrition.get("sugar_g")
        portion = nutrition.get("estimated_grams")
        confidence = nutrition.get("confidence")
        notes = nutrition.get("notes")

        if kcal is not None:
            markers.append(_chip("calories", f"{kcal:.0f} kcal", "info"))
        if protein is not None:
            markers.append(_chip("protein", f"{protein:.1f}g", "neutral"))
        if carbs is not None:
            markers.append(_chip("carbs", f"{carbs:.1f}g", "neutral"))
        if fat is not None:
            markers.append(_chip("fat", f"{fat:.1f}g", "neutral"))
        if fiber is not None:
            markers.append(_chip("fiber", f"{fiber:.1f}g", "good"))
        if sugar is not None:
            sugar_sent = "bad" if float(sugar) > 30 else "neutral"
            markers.append(_chip("sugar", f"{sugar:.1f}g", sugar_sent))
        if portion:
            markers.append(_chip("portion", f"{portion:.0f}g estimated", "neutral"))
        if confidence and confidence != "high":
            markers.append(_chip("confidence", str(confidence), "neutral"))
        if notes:
            markers.append(_chip("note", str(notes), "info"))

    # --- meal timing ---
    timing_str = entry_ts.strftime("%H:%M") + f" · {_hour_label(hour)}"
    if meal_type:
        timing_str += f" · {meal_type}"
    markers.append(_chip("timing", timing_str, "info"))

    # --- daily nutrition totals ---
    day_start = datetime.combine(entry_date, time.min, tzinfo=zone)
    day_end = day_start + timedelta(days=1)
    rows = (await session.execute(text(
        "SELECT data FROM entries WHERE type='food' AND timestamp >= :s AND timestamp < :e"
    ), {"s": day_start.isoformat(), "e": day_end.isoformat()})).fetchall()

    daily_kcal = daily_protein = daily_carbs = daily_fat = daily_fiber = daily_sugar = 0.0
    n_with = 0
    for (raw,) in rows:
        try:
            d = json.loads(raw)
            n = d.get("nutrition") or {}
            k = n.get("calories")
            if k is not None:
                daily_kcal += float(k)
                daily_protein += float(n.get("protein_g") or 0)
                daily_carbs += float(n.get("carbs_g") or 0)
                daily_fat += float(n.get("fat_g") or 0)
                daily_fiber += float(n.get("fiber_g") or 0)
                daily_sugar += float(n.get("sugar_g") or 0)
                n_with += 1
        except Exception:
            continue

    if n_with > 1:
        markers.append(_chip(
            "day kcal",
            f"{daily_kcal:.0f} kcal ({n_with} meals)",
            "info",
        ))
        markers.append(_chip("day protein", f"{daily_protein:.0f}g", "neutral"))
        markers.append(_chip("day carbs", f"{daily_carbs:.0f}g", "neutral"))
        markers.append(_chip("day fat", f"{daily_fat:.0f}g", "neutral"))
        markers.append(_chip("day fiber", f"{daily_fiber:.0f}g", "good"))
        markers.append(_chip("day sugar", f"{daily_sugar:.0f}g",
                             "bad" if daily_sugar > 50 else "neutral"))

    # --- historical energy pattern ---
    if meal_type:
        try:
            since = (entry_date - timedelta(days=30)).isoformat()
            meal_days = [r[0] for r in (await session.execute(text("""
                SELECT DISTINCT strftime('%Y-%m-%d', timestamp)
                FROM entries
                WHERE type = 'food'
                  AND json_extract(data, '$.meal_type') = :mt
                  AND timestamp >= :since
            """), {"mt": meal_type, "since": since})).fetchall()]
            if len(meal_days) >= 5:
                phs = ",".join(f"'{d}'" for d in meal_days)
                energy_row = (await session.execute(text(
                    f"SELECT avg(CAST(json_extract(data, '$.score') AS REAL)), count(*) "
                    f"FROM entries WHERE type='energy' "
                    f"AND strftime('%Y-%m-%d', timestamp) IN ({phs})"
                ))).fetchone()
                if energy_row and energy_row[0] is not None:
                    avg_e = float(energy_row[0])
                    n = int(energy_row[1])
                    sent = "good" if avg_e >= 3.5 else ("neutral" if avg_e >= 2.5 else "bad")
                    markers.append(_chip(
                        "energy pattern",
                        f"Days with {meal_type}: energy avg {avg_e:.1f}/5 (n={n}, 30d)",
                        sent,
                    ))
        except Exception:
            pass

    return markers


async def _score_markers(
    session: AsyncSession,
    entry_type: str,
    data: dict[str, Any],
    entry_ts: datetime,
    entry_date: date,
) -> list[dict[str, str]]:
    markers: list[dict[str, str]] = []
    score = data.get("score")
    hour = entry_ts.hour

    if score is not None:
        since = (entry_date - timedelta(days=7)).isoformat()
        row = (await session.execute(text(
            "SELECT avg(CAST(json_extract(data, '$.score') AS REAL)), count(*) "
            "FROM entries WHERE type=:t AND timestamp >= :s"
        ), {"t": entry_type, "s": since})).fetchone()
        mean_7d = float(row[0]) if row and row[0] is not None else None
        n_7d = int(row[1]) if row else 0

        if mean_7d is not None and n_7d >= 2:
            delta = float(score) - mean_7d
            if abs(delta) >= 0.2:
                delta_str = f"{delta:+.1f} vs 7d avg {mean_7d:.1f}"
            else:
                delta_str = f"≈ 7d avg {mean_7d:.1f}"
            sent = "good" if delta >= 0.5 else ("bad" if delta <= -0.5 else "neutral")
            markers.append(_chip(f"{entry_type}", f"{score}/5 ({delta_str})", sent))
        else:
            markers.append(_chip(entry_type, f"{score}/5", "info"))

    # --- same-day readiness ---
    try:
        r = (await session.execute(text(
            "SELECT value FROM metrics WHERE metric_name='readiness_score' "
            "AND strftime('%Y-%m-%d', timestamp) = :d "
            "ORDER BY timestamp DESC LIMIT 1"
        ), {"d": entry_date.isoformat()})).fetchone()
        if r:
            readiness = float(r[0])
            cat = (
                "peak" if readiness >= 80 else
                "solid" if readiness >= 65 else
                "average" if readiness >= 50 else "low"
            )
            sent = "good" if readiness >= 65 else ("neutral" if readiness >= 50 else "bad")
            markers.append(_chip("readiness", f"{readiness:.0f} ({cat})", sent))
    except Exception:
        pass

    markers.append(_chip("time", f"{entry_ts.strftime('%H:%M')} · {_hour_label(hour)}", "info"))
    return markers


def _symptom_markers(data: dict[str, Any], entry_ts: datetime) -> list[dict[str, str]]:
    markers: list[dict[str, str]] = []
    tag = data.get("tag", "symptom")
    severity = data.get("severity")
    hour = entry_ts.hour

    if severity is not None:
        sent = "bad" if severity >= 4 else ("neutral" if severity >= 2 else "good")
        markers.append(_chip(str(tag), f"severity {severity}/5", sent))

    markers.append(_chip("time", f"{entry_ts.strftime('%H:%M')} · {_hour_label(hour)}", "info"))
    return markers


__all__ = ["compute_entry_markers"]
