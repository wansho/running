#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import gzip
import logging
import tempfile
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from activity_records import calculate_pace, is_cycling_type, parse_datetime, write_json_atomic


logger = logging.getLogger("strava_export")
SHANGHAI = ZoneInfo("Asia/Shanghai")
TYPE_NAMES = {"跑步": "Run", "健走": "Walk", "远足": "Hike", "骑行": "Ride"}


def _number(value: str | None, default: float = 0.0) -> float:
    try:
        return float(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default


def _format_datetime(value: datetime) -> str:
    return value.replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")


def _normalize_coordinate(value: object, latitude: bool) -> float | None:
    if value is None:
        return None
    coordinate = float(value)
    limit = 90 if latitude else 180
    if abs(coordinate) > limit:
        coordinate = coordinate * 180 / 2**31
    return coordinate if abs(coordinate) <= limit else None


def extract_gpx_metadata(path: Path) -> dict[str, object]:
    root = ET.parse(path).getroot()
    point = root.find(".//{*}trkpt")
    if point is None:
        return {}
    result: dict[str, object] = {
        "start_lat": float(point.attrib["lat"]),
        "start_lng": float(point.attrib["lon"]),
    }
    time_node = point.find("{*}time")
    if time_node is not None and time_node.text:
        utc_time = datetime.fromisoformat(time_node.text.replace("Z", "+00:00"))
        result["start_date_local"] = _format_datetime(utc_time.astimezone(SHANGHAI))
    return result


def extract_fit_metadata(path: Path, reader_factory=None) -> dict[str, object]:
    if reader_factory is None:
        from fitdecode import FitReader

        reader_factory = FitReader

    temporary_path: Path | None = None
    source_path = path
    try:
        if path.suffix == ".gz":
            with gzip.open(path, "rb") as source, tempfile.NamedTemporaryFile(
                suffix=".fit", delete=False
            ) as target:
                target.write(source.read())
                temporary_path = Path(target.name)
            source_path = temporary_path

        fallback: dict[str, object] = {}
        with reader_factory(source_path) as frames:
            for frame in frames:
                if not hasattr(frame, "get_value"):
                    continue
                prefix = "start_position_" if getattr(frame, "name", "") == "session" else "position_"
                lat = _normalize_coordinate(frame.get_value(f"{prefix}lat"), latitude=True)
                lng = _normalize_coordinate(frame.get_value(f"{prefix}long"), latitude=False)
                if lat is None or lng is None:
                    continue
                result: dict[str, object] = {"start_lat": lat, "start_lng": lng}
                local_time = frame.get_value("local_timestamp")
                if isinstance(local_time, datetime):
                    result["start_date_local"] = _format_datetime(local_time)
                if getattr(frame, "name", "") == "session":
                    return result
                if not fallback:
                    fallback = result
        return fallback
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def extract_track_metadata(path: Path) -> dict[str, object]:
    if not path.exists():
        logger.warning("轨迹文件不存在：%s", path.name)
        return {}
    try:
        if path.name.lower().endswith(".gpx"):
            return extract_gpx_metadata(path)
        if path.name.lower().endswith((".fit", ".fit.gz")):
            return extract_fit_metadata(path)
        logger.warning("不支持的轨迹格式：%s", path.name)
    except Exception as exc:
        logger.warning("解析轨迹失败：%s (%s)", path.name, type(exc).__name__)
    return {}


def parse_strava_csv(export_dir: Path) -> list[dict]:
    export_dir = Path(export_dir)
    with (export_dir / "activities.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    records = []
    for row in rows:
        raw_type = str(row.get("活动类型") or "").strip()
        if is_cycling_type(None, None, raw_type):
            continue
        try:
            activity_id = int(str(row["活动 ID"]).strip())
            start_utc = datetime.strptime(str(row["活动日期"]).strip(), "%Y年%m月%d日 %H:%M:%S")
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("跳过无效 Strava 汇总行：%s", type(exc).__name__)
            continue

        distance = _number(row.get("距离"))
        moving_time = _number(row.get("移动时间"))
        elapsed_time = _number(row.get("全程耗时"), moving_time)
        filename = str(row.get("文件名") or "").strip()
        track = extract_track_metadata(export_dir / filename) if filename else {}
        local_time = track.get("start_date_local") or _format_datetime(
            start_utc.replace(tzinfo=timezone.utc).astimezone(SHANGHAI)
        )
        record = {
            "run_id": activity_id,
            "name": str(row.get("活动名称") or ""),
            "distance": distance,
            "moving_time": moving_time,
            "elapsed_time": elapsed_time,
            "type": TYPE_NAMES.get(raw_type, raw_type),
            "start_date": _format_datetime(start_utc),
            "start_date_local": local_time,
            "location_country": None,
            "average_heartrate": _number(row.get("平均心率"), default=0.0) or None,
            "average_speed": _number(row.get("平均速度"), default=0.0) or None,
            "pace": calculate_pace(distance, moving_time),
            "summary_polyline": None,
            "source": "strava",
        }
        record.update({key: value for key, value in track.items() if key in {"start_lat", "start_lng"}})
        records.append(record)
    return records


def build_strava_snapshot(export_dir: Path) -> dict:
    records = parse_strava_csv(Path(export_dir))
    records.sort(key=lambda record: parse_datetime(record["start_date"]) or datetime.min)
    if not records:
        raise ValueError("Strava 导出中没有有效的非骑行活动")
    latest = records[-1]
    return {
        "records": records,
        "data_source": "strava_export",
        "exported_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "last_activity_start_utc": latest["start_date"],
        "last_activity_start_local": latest["start_date_local"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="导入 Strava 官网导出活动")
    parser.add_argument("export_dir", type=Path)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/running_records_strava_export.json"),
    )
    args = parser.parse_args()
    snapshot = build_strava_snapshot(args.export_dir)
    write_json_atomic(args.output, snapshot)
    types = Counter(record["type"] for record in snapshot["records"])
    coordinates = sum("start_lat" in record for record in snapshot["records"])
    logger.info(
        "Strava 导入完成：records=%d types=%s coordinates=%d cutoff=%s",
        len(snapshot["records"]),
        dict(types),
        coordinates,
        snapshot["last_activity_start_utc"],
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    main()
