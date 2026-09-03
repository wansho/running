from datetime import datetime, timezone
from pathlib import Path

import pytest

from import_strava_export import (
    build_strava_snapshot,
    extract_fit_metadata,
    extract_track_metadata,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "strava_export"


def test_build_snapshot_filters_ride_and_keeps_missing_track(caplog):
    snapshot = build_strava_snapshot(FIXTURE_DIR)

    assert [record["type"] for record in snapshot["records"]] == ["Walk", "Run"]
    run = snapshot["records"][1]
    walk = snapshot["records"][0]
    assert run["start_lat"] == 31.86246
    assert run["start_lng"] == 118.83694
    assert run["start_date_local"] == "2026-09-03 06:14:05"
    assert walk.get("start_lat") is None
    assert "missing.gpx" in caplog.text
    assert snapshot["last_activity_start_utc"] == "2026-09-02 22:14:05"
    assert snapshot["last_activity_start_local"] == "2026-09-03 06:14:05"


def test_extract_track_metadata_returns_empty_for_bad_gpx(tmp_path, caplog):
    bad_gpx = tmp_path / "bad.gpx"
    bad_gpx.write_text("not xml")

    assert extract_track_metadata(bad_gpx) == {}
    assert "bad.gpx" in caplog.text


def test_extracts_fit_session_position_and_local_timestamp(monkeypatch, tmp_path):
    class FakeMessage:
        name = "session"

        def get_value(self, key):
            return {
                "start_position_lat": 31.86246 * 2**31 / 180,
                "start_position_long": 118.83694 * 2**31 / 180,
                "local_timestamp": datetime(2026, 9, 3, 6, 14, 5, tzinfo=timezone.utc),
            }.get(key)

    class FakeReader:
        def __init__(self, _source):
            pass

        def __enter__(self):
            return iter([FakeMessage()])

        def __exit__(self, *_args):
            return False

    fit_path = tmp_path / "sample.fit"
    fit_path.write_bytes(b"fit")

    result = extract_fit_metadata(fit_path, reader_factory=FakeReader)

    assert result["start_lat"] == pytest.approx(31.86246, abs=0.0001)
    assert result["start_lng"] == pytest.approx(118.83694, abs=0.0001)
    assert result["start_date_local"] == "2026-09-03 06:14:05"
