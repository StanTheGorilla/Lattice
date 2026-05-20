"""Unit tests for functions.stats — the LLM's analytical surface."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from lattice.functions.stats import (
    _summarize,
    compare_windows,
    correlate,
    daily_series,
    stats_by_hour,
    stats_by_weekday,
    stats_for_metric,
    stress_burden_by_zone,
    time_of_day_distribution,
)
from lattice.models import Metric, MetricSample

TZ = "Europe/Warsaw"


def _iso(y: int, mo: int, d: int, h: int = 0, mi: int = 0) -> str:
    return datetime(y, mo, d, h, mi, tzinfo=ZoneInfo(TZ)).isoformat()


def _midnight(y: int, mo: int, d: int) -> str:
    return datetime(y, mo, d, tzinfo=ZoneInfo(TZ)).isoformat()


# --------------------------------------------------------------------------- #
# pure summarize
# --------------------------------------------------------------------------- #


def test_summarize_basic() -> None:
    s = _summarize([10, 20, 30, 40, 50])
    assert s["n"] == 5
    assert s["median"] == 30
    assert s["mean"] == 30
    assert s["min"] == 10
    assert s["max"] == 50
    assert s["low_confidence"] is False


def test_summarize_low_n() -> None:
    s = _summarize([42])
    assert s["n"] == 1
    assert s["median"] == 42
    assert s["sd"] == 0.0
    assert s["low_confidence"] is True


def test_summarize_empty() -> None:
    s = _summarize([])
    assert s == {
        "n": 0, "median": None, "mean": None, "min": None, "max": None,
        "p25": None, "p75": None, "sd": None, "low_confidence": True,
    }


# --------------------------------------------------------------------------- #
# db-backed tests
# --------------------------------------------------------------------------- #


@pytest_asyncio.fixture
async def seeded_metrics(db_session: AsyncSession) -> None:
    # Daily HRV values: 50 51 52 ... 56 over 7 days
    for i, v in enumerate([50, 51, 52, 53, 54, 55, 56]):
        db_session.add(Metric(
            timestamp=_midnight(2026, 5, 8 + i),
            metric_name="hrv_overnight_avg",
            value=float(v),
            unit="ms",
            source="garmin",
        ))
    # Sleep duration values
    for i, v in enumerate([420, 430, 410, 450, 440, 460, 430]):
        db_session.add(Metric(
            timestamp=_midnight(2026, 5, 8 + i),
            metric_name="sleep_duration_min",
            value=float(v),
            unit="min",
            source="garmin",
        ))
    await db_session.commit()


@pytest_asyncio.fixture
async def seeded_hr_samples(db_session: AsyncSession) -> None:
    """One HR sample per hour for 3 days, morning (8-12) HR=60, afternoon (13-17) HR=80."""
    for day in range(8, 11):
        for hour in range(24):
            value = 60 if 8 <= hour < 12 else (80 if 13 <= hour < 18 else 65)
            db_session.add(MetricSample(
                timestamp=_iso(2026, 5, day, hour, 30),
                metric_name="hr",
                value=float(value),
                source="garmin",
            ))
    await db_session.commit()


@pytest.mark.asyncio
async def test_stats_for_metric_daily(
    db_session: AsyncSession, seeded_metrics: None,
) -> None:
    out = await stats_for_metric(
        db_session, "hrv_overnight_avg",
        from_iso="2026-05-08", to_iso="2026-05-14",
    )
    assert out["n"] == 7
    assert out["median"] == 53
    assert out["mean"] == 53
    assert out["min"] == 50
    assert out["max"] == 56
    assert out["low_confidence"] is False


@pytest.mark.asyncio
async def test_stats_for_metric_default_lookback(
    db_session: AsyncSession, seeded_metrics: None,
) -> None:
    # No from/to → 7 days back from today. Seeded data is in May 2026; today
    # in the test environment is the system clock, so this may return 0 rows.
    # The function should still return a well-formed payload.
    out = await stats_for_metric(db_session, "hrv_overnight_avg")
    assert "n" in out
    assert "low_confidence" in out


@pytest.mark.asyncio
async def test_stats_by_hour_morning(
    db_session: AsyncSession, seeded_hr_samples: None,
) -> None:
    out = await stats_by_hour(
        db_session, "hr", 8, 12,
        from_iso="2026-05-08", to_iso="2026-05-10",
    )
    assert out["n"] == 12  # 3 days × 4 hours (8,9,10,11)
    assert out["median"] == 60
    assert out["mean"] == 60


@pytest.mark.asyncio
async def test_stats_by_hour_afternoon(
    db_session: AsyncSession, seeded_hr_samples: None,
) -> None:
    out = await stats_by_hour(
        db_session, "hr", 13, 18,
        from_iso="2026-05-08", to_iso="2026-05-10",
    )
    assert out["n"] == 15  # 3 days × 5 hours
    assert out["median"] == 80


@pytest.mark.asyncio
async def test_stats_by_hour_rejects_daily_metric(db_session: AsyncSession) -> None:
    out = await stats_by_hour(db_session, "hrv_overnight_avg", 8, 12)
    assert "error" in out
    assert out["error"] == "not_intra_day"


@pytest.mark.asyncio
async def test_stats_by_hour_invalid_hours(db_session: AsyncSession) -> None:
    assert (await stats_by_hour(db_session, "hr", -1, 5)).get("error") == "invalid_hours"
    assert (await stats_by_hour(db_session, "hr", 10, 5)).get("error") == "invalid_hours"
    assert (await stats_by_hour(db_session, "hr", 0, 25)).get("error") == "invalid_hours"


@pytest.mark.asyncio
async def test_stats_by_weekday(
    db_session: AsyncSession, seeded_metrics: None,
) -> None:
    # 2026-05-08 is a Friday (weekday 4). 8 Fri, 9 Sat, 10 Sun, 11 Mon, ...
    out = await stats_by_weekday(
        db_session, "hrv_overnight_avg", [5, 6],  # Sat, Sun
        from_iso="2026-05-08", to_iso="2026-05-14",
    )
    assert out["n"] == 2  # the 9th + 10th
    assert out["median"] == 51.5  # (51 + 52) / 2


@pytest.mark.asyncio
async def test_daily_series(
    db_session: AsyncSession, seeded_metrics: None,
) -> None:
    out = await daily_series(
        db_session, "sleep_duration_min",
        from_iso="2026-05-08", to_iso="2026-05-14",
    )
    assert out["n"] == 7
    assert out["series"][0] == {"date": "2026-05-08", "value": 420}
    assert out["series"][-1] == {"date": "2026-05-14", "value": 430}


@pytest.mark.asyncio
async def test_compare_windows(
    db_session: AsyncSession, seeded_metrics: None,
) -> None:
    out = await compare_windows(
        db_session, "hrv_overnight_avg",
        a_from="2026-05-08", a_to="2026-05-10",
        b_from="2026-05-12", b_to="2026-05-14",
    )
    assert out["a"]["median"] == 51
    assert out["b"]["median"] == 55
    assert out["delta_pct"] is not None and out["delta_pct"] > 0


@pytest.mark.asyncio
async def test_correlate_strong_signal(db_session: AsyncSession) -> None:
    # Perfect positive correlation: name_a = i, name_b = 2*i
    for i in range(7):
        db_session.add(Metric(
            timestamp=_midnight(2026, 5, 8 + i),
            metric_name="x_test", value=float(i), unit="x", source="manual",
        ))
        db_session.add(Metric(
            timestamp=_midnight(2026, 5, 8 + i),
            metric_name="y_test", value=float(2 * i), unit="y", source="manual",
        ))
    await db_session.commit()
    out = await correlate(
        db_session, "x_test", "y_test",
        from_iso="2026-05-08", to_iso="2026-05-14",
    )
    assert out["n"] == 7
    assert out["r"] is not None and out["r"] > 0.99
    assert out["direction"] == "positive"


@pytest.mark.asyncio
async def test_correlate_insufficient(db_session: AsyncSession) -> None:
    out = await correlate(db_session, "no_data_a", "no_data_b")
    assert out["r"] is None
    assert "insufficient" in out["reason"]


@pytest.mark.asyncio
async def test_stress_burden_by_zone(db_session: AsyncSession) -> None:
    # Seed stress samples spanning all four zones over one day.
    for h, v in [
        (8, 10),  (9, 15),  (10, 22),   # rest (3)
        (11, 35), (12, 45),              # low (2)
        (13, 60), (14, 70), (15, 65),    # medium (3)
        (16, 80), (17, 90),              # high (2)
    ]:
        db_session.add(MetricSample(
            timestamp=_iso(2026, 5, 14, h, 0),
            metric_name="stress", value=float(v), source="garmin",
        ))
    await db_session.commit()
    out = await stress_burden_by_zone(
        db_session, from_iso="2026-05-14", to_iso="2026-05-14",
    )
    assert out["n"] == 10
    assert out["zones"]["rest"]["n"] == 3
    assert out["zones"]["low"]["n"] == 2
    assert out["zones"]["medium"]["n"] == 3
    assert out["zones"]["high"]["n"] == 2
    assert out["burden_pct"] == 50.0  # (3 medium + 2 high) / 10


@pytest.mark.asyncio
async def test_stress_burden_by_zone_hour_filter(db_session: AsyncSession) -> None:
    # Calm morning (8-12), spiky afternoon (13-17)
    for h in range(8, 12):
        db_session.add(MetricSample(
            timestamp=_iso(2026, 5, 14, h, 0),
            metric_name="stress", value=15.0, source="garmin",
        ))
    for h in range(13, 17):
        db_session.add(MetricSample(
            timestamp=_iso(2026, 5, 14, h, 0),
            metric_name="stress", value=80.0, source="garmin",
        ))
    await db_session.commit()
    morning = await stress_burden_by_zone(
        db_session, from_iso="2026-05-14", to_iso="2026-05-14",
        hour_start=8, hour_end=12,
    )
    afternoon = await stress_burden_by_zone(
        db_session, from_iso="2026-05-14", to_iso="2026-05-14",
        hour_start=13, hour_end=17,
    )
    assert morning["burden_pct"] == 0.0
    assert afternoon["burden_pct"] == 100.0


@pytest.mark.asyncio
async def test_time_of_day_distribution(
    db_session: AsyncSession, seeded_hr_samples: None,
) -> None:
    out = await time_of_day_distribution(
        db_session, "hr",
        from_iso="2026-05-08", to_iso="2026-05-10",
    )
    assert out["hours"][8]["median"] == 60
    assert out["hours"][14]["median"] == 80
    assert out["hours"][8]["n"] == 3  # one sample per day × 3 days
