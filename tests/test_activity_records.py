import json
from datetime import datetime

from activity_records import (
    calculate_pace,
    is_cycling_type,
    merge_records,
    write_json_atomic,
)


def test_cycling_parent_and_root_are_excluded():
    assert is_cycling_type(2, 17, "cycling") is True
    assert is_cycling_type(10, 2, "road_biking") is True
    assert is_cycling_type(None, None, "Ride") is True
    assert is_cycling_type(1, 17, "running") is False


def test_merge_uses_strava_at_cutoff_and_garmin_after_cutoff():
    cutoff = datetime.fromisoformat("2026-09-02 22:14:05")
    strava_record = {
        "run_id": 20012158657,
        "start_date": "2026-09-02 22:14:05",
        "start_date_local": "2026-09-03 06:14:05",
        "distance": 705.0,
        "moving_time": 536.0,
        "source": "strava",
    }
    garmin = [
        {**strava_record, "run_id": 24216312645, "source": "garmin"},
        {
            "run_id": 24220000000,
            "start_date": "2026-09-03 22:00:00",
            "start_date_local": "2026-09-04 06:00:00",
            "distance": 1000.0,
            "moving_time": 600.0,
            "source": "garmin",
        },
    ]

    result = merge_records([], [strava_record], garmin, cutoff)

    assert [row["run_id"] for row in result] == [20012158657, 24220000000]


def test_merge_prefers_manual_record_for_same_activity():
    cutoff = datetime.fromisoformat("2026-09-02 22:14:05")
    manual = {
        "run_id": 100001,
        "start_date": "2020-01-01 00:00:00",
        "start_date_local": "2020-01-01 08:00:00",
        "distance": 1000.2,
        "moving_time": 600.2,
        "source": "mi",
    }
    strava = {**manual, "run_id": 200001, "source": "strava"}

    result = merge_records([manual], [strava], [], cutoff)

    assert result == [manual]


def test_pace_rounds_to_minutes_and_seconds():
    assert calculate_pace(1000.0, 359.6) == "6:00"
    assert calculate_pace(0, 100) is None


def test_atomic_write_keeps_valid_json(tmp_path):
    target = tmp_path / "records.json"

    write_json_atomic(target, {"records": [{"run_id": 1}]})

    assert json.loads(target.read_text())["records"][0]["run_id"] == 1
    assert list(tmp_path.glob("*.tmp")) == []
