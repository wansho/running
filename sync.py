#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
同步 Strava 与 小米数据，合并为一个 JSON，并生成一张 SVG 跑步统计图。
输出:
  - data/running_records_combined.json
  - data/running_stats.svg
注意:
  - 需要安装 stravalib: pip install stravalib
  - 请把你的 mi 导出文件放在 data/mi_running_history.txt
  - 为安全起见，建议把 CLIENT_SECRET/REFRESH_TOKEN 放到环境变量（当前脚本里为演示硬编码）
"""

import logging
import json
import os
from datetime import datetime
from pathlib import Path
import csv

import stravalib  # type: ignore

# ---- 配置 ----
DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
RECORDS_XIAOMI_HIS = str(DATA_DIR / "mi_running_history.txt")
MI_OUTPUT_FILE = str(DATA_DIR / "running_records_manual_add.json")
STRAVA_OUTPUT_FILE = str(DATA_DIR / "running_records_strava_sync.json")
COMBINED_OUTPUT_FILE = str(DATA_DIR / "running_records_combined.json")
SVG_OUTPUT_FILE = str(DATA_DIR / "running_stats.svg")
CSV_OUTPUT_FILE = str(DATA_DIR / "running.csv")

# OAuth（建议改为环境变量）
CLIENT_ID = os.environ.get("STRAVA_CLIENT_ID")
CLIENT_SECRET = os.environ.get("STRAVA_CLIENT_SECRET")
REFRESH_TOKEN = os.environ.get("STRAVA_REFRESH_TOKEN")

# ---- 日志 ----
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("running_sync")

# ---- client ----
strava_client = stravalib.Client()

def export_csv(records, out_path):
    """导出 CSV 文件: DT, distance(Km), heart, pace"""
    if not records:
        logger.warning("没有可导出的数据")
        return

    with open(out_path, "w", encoding="utf8", newline="") as fw:
        writer = csv.writer(fw, delimiter=",")
        # 写表头
        writer.writerow(["DT", "distance(Km)", "heart", "pace"])

        for r in records:
            dt = r.get("start_date_local") or r.get("start_date") or ""
            dist_km = (r.get("distance") or 0) / 1000.0
            pace = r.get("pace") or "-"
            writer.writerow([dt, f"{dist_km:.2f}", 120, pace])

    logger.info("写出 CSV 文件：%s (records=%d)", out_path, len(records))


def calculate_pace(distance_m, moving_time_s):
    """计算配速，返回 mm:ss/km 字符串或 None"""
    try:
        if not distance_m or not moving_time_s:
            return None
        pace_sec_per_km = moving_time_s / (distance_m / 1000.0)
        total_seconds = int(round(pace_sec_per_km))
        minutes, seconds = divmod(total_seconds, 60)
        return "%d:%02d" % (minutes, seconds)
    except Exception:
        return None


def parse_mi_records():
    """解析小米导出文件 -> 返回 list of dict 与写文件到 MI_OUTPUT_FILE"""
    results = []
    run_id = 100000  # 与 strava id 区分开

    if not Path(RECORDS_XIAOMI_HIS).exists():
        logger.warning("小米导出文件不存在：%s，跳过解析", RECORDS_XIAOMI_HIS)
        return results

    with open(RECORDS_XIAOMI_HIS, "r", encoding="utf8") as fr:
        lines = fr.readlines()

    if len(lines) <= 1:
        logger.info("小米导出文件只有表头或为空")
        return results

    raw = lines[1:]
    logger.info("解析小米记录：%d 行", len(raw))

    for line in raw:
        parts = line.strip().split()
        if len(parts) < 8:
            logger.warning("跳过格式错误行: %s", line.strip())
            continue
        try:
            name = parts[0]
            # 原始 distance 单位为 km，转换为米
            distance = round(float(parts[1]) * 1000.0, 1)
        except Exception:
            logger.warning("distance 解析失败，跳过: %s", line.strip())
            continue

        # parse moving_time: 形如 mm:ss 或 hh:mm:ss
        mt = parts[2]
        moving_time = 0
        try:
            segs = mt.split(":")
            if len(segs) == 2:
                moving_time = int(segs[0]) * 60 + int(segs[1])
            elif len(segs) == 3:
                moving_time = int(segs[0]) * 3600 + int(segs[1]) * 60 + int(segs[2])
            else:
                moving_time = int(float(mt))
        except Exception:
            moving_time = 0

        elapsed_time = moving_time
        start_date = parts[3] + " " + parts[4]
        # 尽量确保与 strava 的格式一致：YYYY-MM-DD HH:MM:SS
        # 若用户导出不是这个格式，合并时会尝试解析，失败则放原始字符串
        start_date_local = start_date
        location_country = parts[5]
        average_heartrate = None if parts[6].lower() == "null" else None
        try:
            if parts[6].lower() != "null":
                average_heartrate = int(parts[6])
        except Exception:
            average_heartrate = None

        average_speed = parts[7]  # 保留原始展示
        pace = calculate_pace(distance, moving_time)

        rec = {
            "run_id": run_id,
            "name": name,
            "distance": distance,
            "moving_time": moving_time,
            "elapsed_time": elapsed_time,
            "type": "Run",
            "start_date": start_date,
            "start_date_local": start_date_local,
            "location_country": location_country,
            "average_heartrate": average_heartrate,
            "average_speed": average_speed,
            "pace": pace,
            "summary_polyline": None,
            "source": "mi",
        }
        results.append(rec)
        run_id += 1

    # 写出 MI 输出（保留原样）
    with open(MI_OUTPUT_FILE, "w", encoding="utf8") as fw:
        json.dump({"records": results, "data_source": "manual_add"}, fw, indent=2, ensure_ascii=False)
    logger.info("写出小米解析文件：%s (records=%d)", MI_OUTPUT_FILE, len(results))
    return results


def check_access():
    """刷新 Strava token 并设置 client.access_token"""
    try:
        r = strava_client.refresh_access_token(
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            refresh_token=REFRESH_TOKEN,
        )
        strava_client.access_token = r["access_token"]
        logger.info("Strava token 刷新成功")
    except Exception as e:
        logger.error("Strava token 刷新失败: %s", e)
        raise


def parse_activity(activity):
    """把 stravalib 返回的 activity 转为 dict，并加上 pace"""
    distance = 0.0
    try:
        distance = float(activity.distance) if activity.distance is not None else 0.0
    except Exception:
        distance = 0.0

    moving_time = 0
    try:
        moving_time = float(activity.moving_time) if activity.moving_time else 0
    except Exception:
        moving_time = 0

    elapsed_time = 0
    try:
        elapsed_time = float(activity.elapsed_time) if activity.elapsed_time else moving_time
    except Exception:
        elapsed_time = moving_time

    avg_speed = None
    try:
        avg_speed = float(activity.average_speed) if activity.average_speed is not None else None
    except Exception:
        avg_speed = None

    pace = calculate_pace(distance, moving_time)

    # 格式化时间为 "YYYY-MM-DD HH:MM:SS"
    sd = ""
    sdl = ""
    try:
        if getattr(activity, "start_date", None):
            sd = activity.start_date.strftime("%Y-%m-%d %H:%M:%S")
        if getattr(activity, "start_date_local", None):
            sdl = activity.start_date_local.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        sd = str(getattr(activity, "start_date", ""))
        sdl = str(getattr(activity, "start_date_local", ""))

    rec = {
        "run_id": activity.id,
        "name": activity.name,
        "distance": distance,
        "moving_time": moving_time,
        "elapsed_time": elapsed_time,
        "type": str(activity.sport_type.root),
        "start_date": sd,
        "start_date_local": sdl,
        "location_country": None,
        "average_heartrate": getattr(activity, "average_heartrate", None),
        "average_speed": avg_speed,
        "pace": pace,
        "summary_polyline": None,
        "source": "strava",
    }
    return rec


def fetch_strava_activities():
    """拉取 Strava 活动并写出 STRAVA_OUTPUT_FILE"""
    try:
        check_access()
    except Exception:
        logger.error("无法刷新 Strava token，跳过 Strava 拉取")
        return []

    results = []
    try:
        for a in strava_client.get_activities(after="2010-01-01T00:00:00Z"):
            try:
                rec = parse_activity(a)
                results.append(rec)
            except Exception as e:
                logger.warning("解析某条 Strava 活动失败，跳过: %s", e)
    except Exception as e:
        logger.error("拉取 Strava 活动时出错: %s", e)

    with open(STRAVA_OUTPUT_FILE, "w", encoding="utf8") as fw:
        json.dump({"records": results, "data_source": "strava_sync"}, fw, indent=2, ensure_ascii=False)
    logger.info("写出 Strava 数据：%s (records=%d)", STRAVA_OUTPUT_FILE, len(results))
    return results


def parse_datetime_safe(s):
    """尝试把时间字符串转换为 datetime，若失败返回 None"""
    if not s:
        return None
    fmts = ["%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d"]
    for f in fmts:
        try:
            return datetime.strptime(s, f)
        except Exception:
            continue
    # 最后尝试 ISO parse
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def merge_and_write(mi_recs, strava_recs):
    """合并两者按时间排序，写出合并 JSON，返回合并列表"""
    combined = []
    combined.extend(mi_recs)
    combined.extend(strava_recs)

    # 对没有 start_date 的记录尽量置后，解析 datetime 失败也置后
    def key_func(r):
        dt = parse_datetime_safe(r.get("start_date_local") or r.get("start_date") or "")
        # 将 None 变为 very old? we want None at end -> return (1, None)
        if dt is None:
            return (1, r.get("run_id", 0))
        return (0, dt)

    combined_sorted = sorted(combined, key=key_func)
    with open(COMBINED_OUTPUT_FILE, "w", encoding="utf8") as fw:
        json.dump({"records": combined_sorted, "data_source": "combined"}, fw, indent=2, ensure_ascii=False)
    logger.info("写出合并文件：%s (records=%d)", COMBINED_OUTPUT_FILE, len(combined_sorted))
    return combined_sorted


def generate_svg(records, out_path, max_items=30):
    """
    用合并后的 records 生成一张 svg 条形图，展示最近 max_items 条记录的距离（km）与配速。
    """
    if not records:
        svg = '<svg xmlns="http://www.w3.org/2000/svg" width="600" height="120"><text x="10" y="20">No data</text></svg>'
        Path(out_path).write_text(svg, encoding="utf8")
        logger.info("生成空 SVG: %s", out_path)
        return

    # 取最近 max_items 条（按时间排序，取最后面的）
    # 先尝试按 start_date_local/start_date 解析时间，如果都没有，按原顺序
    annotated = []
    for r in records:
        dt = parse_datetime_safe(r.get("start_date_local") or r.get("start_date") or "")
        annotated.append((dt, r))
    # 保持 None 在前，按时间排序后取最近的
    annotated_sorted = sorted(annotated, key=lambda x: (x[0] is None, x[0] or datetime.min))
    last = annotated_sorted[-max_items:] if len(annotated_sorted) >= max_items else annotated_sorted
    last = [r for (_, r) in last]

    # 图形参数
    w_per_bar = 48
    gap = 8
    margin = 40
    n = len(last)
    width = margin * 2 + n * w_per_bar + (n - 1) * gap
    height = 320
    chart_h = 220
    chart_y = 60

    # 找到最大距离（km）
    dists_km = []
    for r in last:
        try:
            dists_km.append((r.get("distance") or 0) / 1000.0)
        except Exception:
            dists_km.append(0.0)
    max_km = max(dists_km) if dists_km else 1.0
    if max_km <= 0:
        max_km = 1.0

    # 开始构建 svg
    svglines = []
    svglines.append('<?xml version="1.0" encoding="utf-8"?>')
    svglines.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">')
    svglines.append('<style>')
    svglines.append('  .bg{fill:#0f1720;} .label{font-family:Arial, Helvetica, sans-serif;font-size:12px;fill:#cbd5e1;}')
    svglines.append('  .title{font-family:Arial, Helvetica, sans-serif;font-size:18px;fill:#ffffff;}')
    svglines.append('  .bar{fill:#60a5fa;} .bar:hover{fill:#3b82f6;} .small{font-size:11px;fill:#94a3b8;}')
    svglines.append('</style>')
    svglines.append(f'<rect width="100%" height="100%" fill="#071029"/>')

    # Title / summary
    total_runs = len(records)
    total_distance_km = sum(dists_km)
    svglines.append(f'<text x="{margin}" y="26" class="title">Running stats (last {n} records shown)</text>')
    svglines.append(f'<text x="{width - margin}" y="26" class="label" text-anchor="end">Total runs: {total_runs}  Total km(shown): {total_distance_km:.2f}</text>')

    # Draw axis line
    svglines.append(f'<line x1="{margin}" y1="{chart_y + chart_h}" x2="{width - margin}" y2="{chart_y + chart_h}" stroke="#1f2937" stroke-width="1"/>')

    # Bars
    for i, r in enumerate(last):
        x = margin + i * (w_per_bar + gap)
        km = (r.get("distance") or 0) / 1000.0
        bar_h = (km / max_km) * (chart_h - 20)
        y = chart_y + (chart_h - bar_h)
        # bar rect
        svglines.append(f'<rect class="bar" x="{x}" y="{y}" width="{w_per_bar}" height="{bar_h}" rx="4" />')
        # distance label above bar
        svglines.append(f'<text x="{x + w_per_bar/2}" y="{y - 6}" class="label" text-anchor="middle">{km:.2f} km</text>')
        # date label below
        sd = r.get("start_date_local") or r.get("start_date") or ""
        sd_short = ""
        dt = parse_datetime_safe(sd)
        if dt:
            sd_short = dt.strftime("%m-%d")
        else:
            sd_short = sd[:10]
        svglines.append(f'<text x="{x + w_per_bar/2}" y="{chart_y + chart_h + 16}" class="small" text-anchor="middle">{sd_short}</text>')
        # pace label
        pace = r.get("pace") or "-"
        svglines.append(f'<text x="{x + w_per_bar/2}" y="{y + max(12, bar_h/2)}" class="small" text-anchor="middle">{pace}</text>')

    # footer / legend
    svglines.append(f'<text x="{margin}" y="{height - 10}" class="small">Generated by sync_and_draw.py</text>')
    svglines.append('</svg>')

    Path(out_path).write_text("\n".join(svglines), encoding="utf8")
    logger.info("生成 SVG: %s", out_path)


def main():
    # 1) 解析小米
    mi = parse_mi_records()

    # 2) 拉 Strava
    strava = fetch_strava_activities()

    # 3) 合并并写出 combined json
    combined = merge_and_write(mi, strava)

    # 4) 生成 svg（展示最近 30 条）
    # generate_svg(combined, SVG_OUTPUT_FILE, max_items=30)

    # 5) 导出 CSV
    export_csv(combined, CSV_OUTPUT_FILE)


if __name__ == "__main__":
    main()
