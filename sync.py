#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import logging
import os
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from garminconnect import Garmin

from activity_records import calculate_pace, is_cycling_type, merge_records, parse_datetime, write_json_atomic
from garmin_tokens import decrypt_tokenstore, persist_tokenstore_if_changed, remove_plaintext_token


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("running_sync")


@dataclass(frozen=True)
class SyncPaths:
    manual: Path
    strava: Path
    garmin: Path
    combined: Path
    csv: Path
    encrypted_token: Path


DEFAULT_PATHS = SyncPaths(
    manual=Path("data/running_records_manual_add.json"),
    strava=Path("data/running_records_strava_export.json"),
    garmin=Path("data/running_records_garmin_sync.json"),
    combined=Path("data/running_records_combined.json"),
    csv=Path("data/running.csv"),
    encrypted_token=Path("data/garmin_tokens.enc"),
)


def _seconds(value: object, fallback: float = 0.0) -> float:
    try:
        return float(value) if value is not None else fallback
    except (TypeError, ValueError):
        return fallback


def parse_garmin_activity(activity: dict) -> dict:
    activity_type = activity.get("activityType") or {}
    distance = _seconds(activity.get("distance"))
    moving_time = _seconds(activity.get("movingDuration"), _seconds(activity.get("duration")))
    elapsed_time = _seconds(
        activity.get("elapsedDuration"),
        _seconds(activity.get("duration"), moving_time),
    )
    record = {
        "run_id": activity["activityId"],
        "name": activity.get("activityName") or "Garmin 活动",
        "distance": distance,
        "moving_time": moving_time,
        "elapsed_time": elapsed_time,
        "type": activity_type.get("typeKey") or "unknown",
        "type_id": activity_type.get("typeId"),
        "parent_type_id": activity_type.get("parentTypeId"),
        "start_date": activity["startTimeGMT"],
        "start_date_local": activity.get("startTimeLocal") or activity["startTimeGMT"],
        "location_country": activity.get("locationName"),
        "average_heartrate": activity.get("averageHR"),
        "average_speed": activity.get("averageSpeed"),
        "pace": calculate_pace(distance, moving_time),
        "summary_polyline": None,
        "source": "garmin",
    }
    if activity.get("startLatitude") is not None:
        record["start_lat"] = float(activity["startLatitude"])
    if activity.get("startLongitude") is not None:
        record["start_lng"] = float(activity["startLongitude"])
    return record


def fetch_garmin_activities(client, start_date: date, end_date: date) -> list[dict]:
    raw_activities = client.get_activities_by_date(
        start_date.isoformat(), end_date.isoformat(), sortorder="asc"
    )
    records = []
    excluded = 0
    for activity in raw_activities:
        activity_type = activity.get("activityType") or {}
        if is_cycling_type(
            activity_type.get("typeId"),
            activity_type.get("parentTypeId"),
            str(activity_type.get("typeKey") or ""),
        ):
            excluded += 1
            continue
        try:
            records.append(parse_garmin_activity(activity))
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning(
                "跳过无效 Garmin 活动：activity_id=%s error=%s",
                activity.get("activityId"),
                type(exc).__name__,
            )
    logger.info(
        "Garmin 查询完成：start=%s end=%s fetched=%d excluded_cycling=%d accepted=%d",
        start_date,
        end_date,
        len(raw_activities),
        excluded,
        len(records),
    )
    return records


def update_garmin_records(existing: list[dict], fetched: list[dict], cutoff_utc: datetime) -> list[dict]:
    by_id = {
        str(record.get("run_id")): record
        for record in existing
        if (parse_datetime(str(record.get("start_date") or "")) or datetime.min) > cutoff_utc
    }
    for record in fetched:
        started_at = parse_datetime(str(record.get("start_date") or ""))
        if started_at is None or started_at <= cutoff_utc:
            continue
        by_id[str(record["run_id"])] = record
    return sorted(
        by_id.values(),
        key=lambda record: parse_datetime(str(record.get("start_date") or "")) or datetime.max,
    )


def _read_payload(path: Path) -> dict:
    with Path(path).open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict) or not isinstance(payload.get("records"), list):
        raise ValueError(f"数据文件格式无效：{path}")
    return payload


def _query_start_date(strava_payload: dict, garmin_records: list[dict]) -> date:
    if garmin_records:
        latest = max(
            parse_datetime(str(record.get("start_date_local") or record.get("start_date") or ""))
            or datetime.min
            for record in garmin_records
        )
    else:
        latest = parse_datetime(str(strava_payload.get("last_activity_start_local") or ""))
    if latest is None:
        raise ValueError("无法确定 Garmin 增量查询起点")
    return latest.date() - timedelta(days=1)


def export_csv_atomic(records: list[dict], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            writer = csv.writer(handle)
            writer.writerow(["DT", "distance(Km)", "heart", "pace", "start_lat", "start_lng"])
            for record in records:
                writer.writerow(
                    [
                        record.get("start_date_local") or record.get("start_date") or "",
                        f"{_seconds(record.get('distance')) / 1000.0:.2f}",
                        record.get("average_heartrate") or 120,
                        record.get("pace") or "-",
                        record.get("start_lat", ""),
                        record.get("start_lng", ""),
                    ]
                )
            handle.flush()
            os.fsync(handle.fileno())
            temporary_path = Path(handle.name)
        temporary_path.replace(output_path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def run_sync(
    paths: SyncPaths,
    token_key: str,
    client_factory: Callable[[], object] = Garmin,
    today: date | None = None,
) -> list[dict]:
    manual_payload = _read_payload(paths.manual)
    strava_payload = _read_payload(paths.strava)
    garmin_payload = _read_payload(paths.garmin)
    cutoff_utc = parse_datetime(str(strava_payload.get("last_activity_start_utc") or ""))
    if cutoff_utc is None:
        raise ValueError("Strava 快照缺少有效截止时间")

    temporary_dir = Path(tempfile.mkdtemp(prefix="running-garmin-"))
    token_path: Path | None = None
    original_token = ""
    try:
        token_path = decrypt_tokenstore(paths.encrypted_token, temporary_dir, token_key)
        original_token = token_path.read_text(encoding="utf-8")
        client = client_factory()
        client.login(str(token_path.parent))
        query_start = _query_start_date(strava_payload, garmin_payload["records"])
        fetched = fetch_garmin_activities(client, query_start, today or date.today())
        garmin_records = update_garmin_records(garmin_payload["records"], fetched, cutoff_utc)
        combined = merge_records(
            manual_payload["records"], strava_payload["records"], garmin_records, cutoff_utc
        )
        write_json_atomic(
            paths.garmin,
            {
                "records": garmin_records,
                "data_source": "garmin_sync",
                "last_successful_sync_at": datetime.now(timezone.utc).strftime(
                    "%Y-%m-%d %H:%M:%S UTC"
                ),
            },
        )
        write_json_atomic(paths.combined, {"records": combined, "data_source": "combined"})
        export_csv_atomic(combined, paths.csv)
        logger.info(
            "三源合并完成：manual=%d strava=%d garmin=%d combined=%d",
            len(manual_payload["records"]),
            len(strava_payload["records"]),
            len(garmin_records),
            len(combined),
        )
        return combined
    finally:
        try:
            if token_path is not None and token_path.exists():
                changed = persist_tokenstore_if_changed(
                    token_path, original_token, paths.encrypted_token, token_key
                )
                if changed:
                    logger.info("Garmin token 已刷新并重新加密")
        finally:
            if token_path is not None:
                remove_plaintext_token(token_path)
            else:
                temporary_dir.rmdir()


def main() -> None:
    token_key = os.environ.get("GARMIN_TOKEN_KEY")
    if not token_key:
        raise SystemExit("环境变量 GARMIN_TOKEN_KEY 未设置")
    run_sync(DEFAULT_PATHS, token_key)


if __name__ == "__main__":
    main()
