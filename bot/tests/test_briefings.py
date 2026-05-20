"""Briefing formatter tests — pure render functions, no Discord, no httpx."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from lattice_bot.briefings import format_evening, format_morning

TZ = "Europe/Warsaw"


def _today_at(hour: int, minute: int) -> str:
    now = datetime.now(ZoneInfo(TZ))
    return now.replace(hour=hour, minute=minute, second=0, microsecond=0).isoformat()


def test_morning_brief_renders_all_sections() -> None:
    body = format_morning(
        readiness={"score": 77, "category": "solid", "provisional": False},
        sleep_window={
            "bedtime": _today_at(23, 0),
            "wake_time": _today_at(6, 30),
            "target_duration_min": 450,
            "flags": [],
            "inputs": {"sleep_score_today": 82, "sleep_duration_min_today": 452},
        },
        training={"recommendation": "easy", "confidence": 0.6, "rationale": ["HRV stable"]},
        work_windows={
            "windows": [
                {
                    "start": _today_at(9, 30),
                    "end": _today_at(11, 30),
                    "predicted_focus": 76,
                    "rationale": [],
                },
            ],
        },
        calendar_events=[
            {
                "start": _today_at(12, 0),
                "end": _today_at(12, 30),
                "title": "Standup",
                "is_all_day": False,
            },
        ],
        tz=TZ,
    )
    assert "Morning brief" in body
    assert "77" in body
    assert "solid" in body
    assert "09:30" in body
    assert "11:30" in body
    assert "predicted focus 76" in body
    assert "easy" in body
    assert "12:00" in body
    assert "Standup" in body


def test_morning_brief_handles_no_window_and_no_events() -> None:
    body = format_morning(
        readiness={"score": 60, "category": "average", "provisional": True},
        sleep_window={"inputs": {}},
        training={"recommendation": "rest", "rationale": []},
        work_windows={"windows": []},
        calendar_events=[],
        tz="Europe/Warsaw",
    )
    assert "provisional" in body
    assert "no 60-min gap" in body
    assert "none scheduled" in body


def test_evening_brief_groups_entry_counts_and_flags_caffeine() -> None:
    body = format_evening(
        entries={
            "items": [
                {"type": "drink"}, {"type": "drink"}, {"type": "food"}, {"type": "mood"},
            ],
        },
        sleep_window={
            "bedtime": "2026-05-14T23:00:00+02:00",
            "wake_time": "2026-05-15T06:30:00+02:00",
            "target_duration_min": 450,
            "flags": ["late caffeine: coffee at 16:23"],
        },
        caffeine={
            "residual_at_bedtime_mg": 35.0,
            "last_call_minutes": 90,
            "safe_for_new_cup": True,
        },
        habits_adherence={
            "items": [
                {
                    "habit_id": 1, "name": "meditate", "target_per_week": 7,
                    "current_streak_days": 0, "week_completion_pct": 0,
                },
            ],
        },
        tz="Europe/Warsaw",
    )
    assert "drink 2" in body
    assert "food 1" in body
    assert "mood 1" in body
    assert "23:00" in body
    assert "residual 35mg" in body
    assert "late caffeine" in body
    assert "meditate" in body  # habit listed as not-checked


def test_evening_brief_no_entries() -> None:
    body = format_evening(
        entries={"items": []},
        sleep_window={},
        caffeine={},
        habits_adherence={"items": []},
        tz="Europe/Warsaw",
    )
    assert "nothing" in body
    assert "Habits: all daily ones logged or n/a" in body
