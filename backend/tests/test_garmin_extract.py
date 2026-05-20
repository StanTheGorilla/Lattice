"""Unit tests for sync.garmin_sync extract_* pure functions."""

from __future__ import annotations

from datetime import date

from lattice.sync.garmin_sync import (
    HRV_STATUS_CODE,
    extract_body_battery,
    extract_hrv,
    extract_resting_hr,
    extract_sleep,
    extract_steps,
    extract_stress,
    extract_training_status,
)

TZ = "Europe/Warsaw"
DAY = date(2026, 5, 13)


def _by_name(rows: list, name: str):
    matches = [r for r in rows if r.metric_name == name]
    assert len(matches) == 1, f"expected exactly one {name}, got {len(matches)}"
    return matches[0]


# --------------------------------------------------------------------------- #
# sleep
# --------------------------------------------------------------------------- #

def test_extract_sleep_full_payload() -> None:
    payload = {
        "dailySleepDTO": {
            "sleepTimeSeconds": 26640,        # 7h24m → 444 min
            "deepSleepSeconds": 4680,         # 78 min
            "lightSleepSeconds": 14640,       # 244 min
            "remSleepSeconds": 5760,          # 96 min
            "awakeSleepSeconds": 1560,        # 26 min
            "sleepScores": {"overall": {"value": 82}},
            "averageRespirationValue": 14.2,
            "averageSpO2Value": 96,
        }
    }
    rows = extract_sleep(payload, DAY, TZ)
    names = [r.metric_name for r in rows]
    for required in [
        "sleep_score", "sleep_duration_min", "sleep_deep_min",
        "sleep_light_min", "sleep_rem_min", "sleep_awake_min",
        "respiration_avg", "spo2_avg",
    ]:
        assert required in names, f"missing {required}"
    assert _by_name(rows, "sleep_score").value == 82
    assert _by_name(rows, "sleep_duration_min").value == 444.0
    assert _by_name(rows, "sleep_deep_min").value == 78.0
    assert _by_name(rows, "spo2_avg").value == 96.0


def test_extract_sleep_handles_missing_fields() -> None:
    rows = extract_sleep({"dailySleepDTO": {}}, DAY, TZ)
    assert rows == []


def test_extract_sleep_handles_none() -> None:
    assert extract_sleep(None, DAY, TZ) == []
    assert extract_sleep({}, DAY, TZ) == []


def test_extract_sleep_timestamp_format() -> None:
    rows = extract_sleep(
        {"dailySleepDTO": {"sleepScores": {"overall": {"value": 80}}}}, DAY, TZ,
    )
    # Anchored at midnight of DAY in tz — must have +02:00 offset for Europe/Warsaw in May
    assert rows[0].timestamp.startswith("2026-05-13T00:00:00")
    assert rows[0].timestamp.endswith("+02:00")


# --------------------------------------------------------------------------- #
# hrv
# --------------------------------------------------------------------------- #

def test_extract_hrv_balanced() -> None:
    payload = {"hrvSummary": {"lastNightAvg": 58, "status": "BALANCED"}}
    rows = extract_hrv(payload, DAY, TZ)
    avg = _by_name(rows, "hrv_overnight_avg")
    status = _by_name(rows, "hrv_status")
    assert avg.value == 58.0
    assert avg.unit == "ms"
    assert status.value == float(HRV_STATUS_CODE["BALANCED"])
    assert status.metadata == {"status": "BALANCED"}


def test_extract_hrv_no_data() -> None:
    assert extract_hrv(None, DAY, TZ) == []
    assert extract_hrv({"hrvSummary": {}}, DAY, TZ) == []


# --------------------------------------------------------------------------- #
# stress
# --------------------------------------------------------------------------- #

def test_extract_stress_full() -> None:
    payload = {
        "avgStressLevel": 32,
        "restStressDuration": 14400,    # 240 min
        "lowStressDuration": 7200,      # 120 min
        "mediumStressDuration": 3600,   # 60 min
        "highStressDuration": 1800,     # 30 min
    }
    rows = extract_stress(payload, DAY, TZ)
    assert _by_name(rows, "stress_avg").value == 32.0
    assert _by_name(rows, "stress_rest_min").value == 240.0
    assert _by_name(rows, "stress_high_min").value == 30.0


def test_extract_stress_skips_negative_avg() -> None:
    """Garmin returns avgStressLevel=-1 or -2 for insufficient data."""
    payload = {"avgStressLevel": -1, "restStressDuration": 14400}
    rows = extract_stress(payload, DAY, TZ)
    names = [r.metric_name for r in rows]
    assert "stress_avg" not in names
    assert "stress_rest_min" in names


# --------------------------------------------------------------------------- #
# body battery
# --------------------------------------------------------------------------- #

def test_extract_body_battery_3tuple_form() -> None:
    """Older payload shape: [timestamp_ms, status, value]."""
    payload = [{
        "date": "2026-05-13",
        "bodyBatteryValuesArray": [
            [1715559300000, "MEASURED", 46],
            [1715562900000, "MEASURED", 62],
            [1715566500000, "MEASURED", 86],
            [1715570100000, "MEASURED", 38],
            [1715573700000, "MEASURED", 71],
        ],
    }]
    rows = extract_body_battery(payload, DAY, TZ)
    # start = max (morning post-recharge peak), not first value.
    assert _by_name(rows, "body_battery_start").value == 86.0
    assert _by_name(rows, "body_battery_end").value == 71.0
    assert _by_name(rows, "body_battery_min").value == 38.0


def test_extract_body_battery_2tuple_real_payload() -> None:
    """Current Garmin shape: [timestamp_ms, value] — matches Stan's real account."""
    payload = [{
        "date": "2026-05-13",
        "bodyBatteryValuesArray": [
            [1778623200000, 5],   # midnight — still up, drained
            [1778650920000, 68],  # morning post-recharge
            [1778652540000, 69],  # morning peak
            [1778678640000, 30],  # afternoon
            [1778679360000, 29],
            [1778706540000, 10],  # end of day
        ],
    }]
    rows = extract_body_battery(payload, DAY, TZ)
    assert _by_name(rows, "body_battery_start").value == 69.0  # morning peak
    assert _by_name(rows, "body_battery_end").value == 10.0     # last reading
    assert _by_name(rows, "body_battery_min").value == 5.0      # day's lowest


def test_extract_body_battery_filters_none_values() -> None:
    """Today's payload before any data: every value is None."""
    payload = [{
        "date": "2026-05-14",
        "bodyBatteryValuesArray": [
            [1778716800001, None],
            [1778716800002, None],
        ],
    }]
    assert extract_body_battery(payload, DAY, TZ) == []


def test_extract_body_battery_empty() -> None:
    assert extract_body_battery([], DAY, TZ) == []
    assert extract_body_battery([{"bodyBatteryValuesArray": []}], DAY, TZ) == []


# --------------------------------------------------------------------------- #
# resting hr
# --------------------------------------------------------------------------- #

def test_extract_resting_hr() -> None:
    rows = extract_resting_hr({"restingHeartRate": 54}, DAY, TZ)
    assert len(rows) == 1
    assert rows[0].metric_name == "resting_hr"
    assert rows[0].value == 54.0


def test_extract_resting_hr_zero_skipped() -> None:
    assert extract_resting_hr({"restingHeartRate": 0}, DAY, TZ) == []
    assert extract_resting_hr({}, DAY, TZ) == []


# --------------------------------------------------------------------------- #
# training status
# --------------------------------------------------------------------------- #

def test_extract_training_status_full() -> None:
    payload = {
        "mostRecentVO2Max": {"generic": {"vo2MaxPreciseValue": 49.6}},
        "mostRecentTrainingStatus": {
            "latestTrainingStatusData": {
                "1234567": {
                    "trainingStatus": "PRODUCTIVE",
                    "acuteTrainingLoadDTO": {
                        "acuteTrainingLoad": 380,
                        "chronicTrainingLoad": 420,
                    },
                }
            }
        },
    }
    rows = extract_training_status(payload, DAY, TZ)
    assert _by_name(rows, "vo2_max").value == 49.6
    assert _by_name(rows, "training_load_acute").value == 380.0
    assert _by_name(rows, "training_load_chronic").value == 420.0
    status_row = _by_name(rows, "training_status")
    assert status_row.metadata == {"status": "PRODUCTIVE"}


def test_extract_training_status_missing() -> None:
    assert extract_training_status({}, DAY, TZ) == []
    assert extract_training_status(None, DAY, TZ) == []


# --------------------------------------------------------------------------- #
# steps
# --------------------------------------------------------------------------- #

def test_extract_steps_hourly_sum() -> None:
    payload = [{"steps": 1500}, {"steps": 3000}, {"steps": 0}, {"steps": 2400}]
    rows = extract_steps(payload, DAY, TZ)
    assert _by_name(rows, "steps").value == 6900.0


def test_extract_steps_zero_skipped() -> None:
    assert extract_steps([{"steps": 0}], DAY, TZ) == []
    assert extract_steps([], DAY, TZ) == []
