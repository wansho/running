import json
from datetime import date, datetime
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from garmin_tokens import decrypt_tokenstore, encrypt_tokenstore
from sync import (
    SyncPaths,
    export_csv_atomic,
    fetch_garmin_activities,
    parse_garmin_activity,
    run_sync,
    update_garmin_records,
)


CUTOFF = datetime.fromisoformat("2026-09-02 22:14:05")
GARMIN_RUN = {
    "activityId": 24216312645,
    "activityName": "跑步",
    "activityType": {"typeId": 1, "typeKey": "running", "parentTypeId": 17},
    "startTimeGMT": "2026-09-02 22:14:05",
    "startTimeLocal": "2026-09-03 06:14:05",
    "distance": 705.030029296875,
    "duration": 543.4320068359375,
    "movingDuration": 536.0,
    "elapsedDuration": 543.4320068359375,
    "averageSpeed": 1.2970000505447388,
    "averageHR": 98.0,
    "startLatitude": 31.862460281699896,
    "startLongitude": 118.8369410019368,
}


def test_parse_garmin_activity_maps_existing_schema():
    row = parse_garmin_activity(GARMIN_RUN)

    assert row["run_id"] == 24216312645
    assert row["type"] == "running"
    assert row["pace"] == "12:40"
    assert row["source"] == "garmin"
    assert row["start_lat"] == pytest.approx(31.86246)


def test_fetch_excludes_activity_with_cycling_parent():
    ride = {
        **GARMIN_RUN,
        "activityId": 99,
        "activityType": {"typeId": 10, "typeKey": "road_biking", "parentTypeId": 2},
    }
    client = FakeClient([GARMIN_RUN, ride])

    result = fetch_garmin_activities(client, date(2026, 9, 1), date(2026, 9, 3))

    assert [row["run_id"] for row in result] == [24216312645]
    assert client.query == ("2026-09-01", "2026-09-03", "asc")


def test_update_rejects_cutoff_and_accepts_later_activity():
    at_cutoff = parse_garmin_activity(GARMIN_RUN)
    after_cutoff = parse_garmin_activity(
        {
            **GARMIN_RUN,
            "activityId": 24220000000,
            "startTimeGMT": "2026-09-03 22:00:00",
            "startTimeLocal": "2026-09-04 06:00:00",
        }
    )

    result = update_garmin_records([], [at_cutoff, after_cutoff], CUTOFF)

    assert [row["run_id"] for row in result] == [24220000000]


def test_update_replaces_same_garmin_id_without_duplicate():
    current = parse_garmin_activity(
        {
            **GARMIN_RUN,
            "activityId": 24220000000,
            "startTimeGMT": "2026-09-03 22:00:00",
            "startTimeLocal": "2026-09-04 06:00:00",
        }
    )
    old = [{**current, "distance": 999.0}]

    result = update_garmin_records(old, [current], CUTOFF)

    assert len(result) == 1
    assert result[0]["distance"] == current["distance"]


def test_export_csv_uses_unix_line_endings(tmp_path):
    output = tmp_path / "running.csv"

    export_csv_atomic([parse_garmin_activity(GARMIN_RUN)], output)

    assert b"\r\n" not in output.read_bytes()


def test_fetch_failure_keeps_existing_data_and_persists_rotated_refresh_token(tmp_path):
    paths, key = make_sync_paths(tmp_path)
    original_garmin = paths.garmin.read_text()
    client = FailingRotatingClient([])

    with pytest.raises(RuntimeError, match="Garmin unavailable"):
        run_sync(
            paths,
            key,
            client_factory=lambda: client,
            today=date(2026, 9, 3),
        )

    assert paths.garmin.read_text() == original_garmin
    restored = decrypt_tokenstore(paths.encrypted_token, tmp_path / "restored", key)
    assert json.loads(restored.read_text())["di_refresh_token"] == "new-refresh"


class FakeClient:
    def __init__(self, activities):
        self.activities = activities
        self.query = None

    def login(self, _tokenstore):
        return None

    def get_activities_by_date(self, start, end, sortorder=None):
        self.query = (start, end, sortorder)
        return self.activities


class FailingRotatingClient(FakeClient):
    def login(self, tokenstore):
        token_path = Path(tokenstore) / "garmin_tokens.json"
        data = json.loads(token_path.read_text())
        data["di_token"] = "new-access"
        data["di_refresh_token"] = "new-refresh"
        token_path.write_text(json.dumps(data))

    def get_activities_by_date(self, start, end, sortorder=None):
        raise RuntimeError("Garmin unavailable")


def make_sync_paths(tmp_path):
    manual = tmp_path / "manual.json"
    strava = tmp_path / "strava.json"
    garmin = tmp_path / "garmin.json"
    combined = tmp_path / "combined.json"
    csv_path = tmp_path / "running.csv"
    encrypted = tmp_path / "garmin_tokens.enc"
    manual.write_text(json.dumps({"records": [], "data_source": "manual_add"}))
    strava.write_text(
        json.dumps(
            {
                "records": [],
                "data_source": "strava_export",
                "last_activity_start_utc": "2026-09-02 22:14:05",
                "last_activity_start_local": "2026-09-03 06:14:05",
            }
        )
    )
    garmin.write_text(json.dumps({"records": [], "data_source": "garmin_sync"}))
    plain = tmp_path / "seed.json"
    plain.write_text(
        json.dumps(
            {
                "di_token": "old-access",
                "di_refresh_token": "old-refresh",
                "di_client_id": "client",
            }
        )
    )
    key = Fernet.generate_key().decode()
    encrypt_tokenstore(plain, encrypted, key)
    return (
        SyncPaths(
            manual=manual,
            strava=strava,
            garmin=garmin,
            combined=combined,
            csv=csv_path,
            encrypted_token=encrypted,
        ),
        key,
    )
