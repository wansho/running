from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def parse_datetime(value: str) -> datetime | None:
    if not value:
        return None
    normalized = str(value).strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    for fmt in (
        None,
        "%Y-%m-%d %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
        "%Y-%m-%d",
        "%Y/%m/%d",
    ):
        try:
            parsed = datetime.fromisoformat(normalized) if fmt is None else datetime.strptime(normalized, fmt)
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
            return parsed
        except ValueError:
            continue
    return None


def calculate_pace(distance_m: float, moving_time_s: float) -> str | None:
    if not distance_m or not moving_time_s:
        return None
    pace_seconds = round(float(moving_time_s) / (float(distance_m) / 1000.0))
    minutes, seconds = divmod(pace_seconds, 60)
    return f"{minutes}:{seconds:02d}"


def is_cycling_type(
    type_id: int | None,
    parent_type_id: int | None,
    type_key: str,
) -> bool:
    return type_id == 2 or parent_type_id == 2 or str(type_key).strip().lower() in {
        "ride",
        "cycling",
        "骑行",
    }


def activity_fingerprint(record: dict) -> tuple[str, int, int]:
    start = str(record.get("start_date") or "")
    distance = round(float(record.get("distance") or 0))
    duration = round(float(record.get("moving_time") or record.get("elapsed_time") or 0))
    return start, distance, duration


def merge_records(
    manual: list[dict],
    strava: list[dict],
    garmin: list[dict],
    cutoff_utc: datetime,
) -> list[dict]:
    candidates = list(manual)
    candidates.extend(
        record
        for record in strava
        if (parse_datetime(str(record.get("start_date") or "")) or datetime.min) <= cutoff_utc
    )
    candidates.extend(
        record
        for record in garmin
        if (parse_datetime(str(record.get("start_date") or "")) or datetime.min) > cutoff_utc
    )

    merged = []
    seen_ids: set[tuple[str, str]] = set()
    seen_fingerprints: set[tuple[str, int, int]] = set()
    for record in candidates:
        if is_cycling_type(
            record.get("type_id"),
            record.get("parent_type_id"),
            str(record.get("type") or ""),
        ):
            continue
        source_id = (str(record.get("source") or ""), str(record.get("run_id") or ""))
        fingerprint = activity_fingerprint(record)
        if source_id in seen_ids or fingerprint in seen_fingerprints:
            continue
        seen_ids.add(source_id)
        seen_fingerprints.add(fingerprint)
        merged.append(record)

    return sorted(
        merged,
        key=lambda record: (
            parse_datetime(str(record.get("start_date_local") or record.get("start_date") or ""))
            is None,
            parse_datetime(str(record.get("start_date_local") or record.get("start_date") or ""))
            or datetime.max,
            str(record.get("run_id") or ""),
        ),
    )


def write_json_atomic(path: Path, payload: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
            temporary_path = Path(handle.name)
        temporary_path.replace(path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
