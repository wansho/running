#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
根据 running.csv 绘制美观的跑步统计 SVG（去掉心率展示，添加最近12个月跑量柱状图，横坐标为月份，纵坐标为跑量，柱状图使用斜线填充）。
"""

from __future__ import annotations
import math
import calendar
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional, TypeVar
from dateutil.relativedelta import relativedelta

import matplotlib
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import matplotlib.ticker as tick
import numpy as np

from matplotlib.offsetbox import AnnotationBbox, OffsetImage

T = TypeVar("T")
K = TypeVar("K")

# ---- 配置 ----
CSV_FILE = Path("data/running.csv")
OUT_SVG = Path("running.svg")
RUNNER = "wanshuo"


def groupby(data: list[T], key_func: Callable[[T], K]) -> dict[K, list[T]]:
    grouped_data = {}
    for item in data:
        key = key_func(item)
        if key in grouped_data:
            grouped_data[key].append(item)
        else:
            grouped_data[key] = [item]
    return grouped_data


def get_days_monthly(
        year_start: int,
        year_end: int,
        month_start: Optional[int] = None,
        month_end: Optional[int] = None,
) -> dict[int, int]:
    days_monthly = {}
    for y in range(year_start, year_end + 1):
        for m in range(
                month_start if month_start and y == year_start else 1,
                (month_end if month_end and y == year_end else 12) + 1,
        ):
            days = calendar.monthrange(y, m)[1]
            if m in days_monthly:
                days_monthly[m] += days
            else:
                days_monthly[m] = days
    return days_monthly


def get_attendance(dts: list[datetime]) -> tuple[list[float], list[float]]:
    dts_all_monthly = groupby(dts, lambda d: d.month)
    this_year = datetime.now().year
    dts_this_year = [d for d in dts if d.year == this_year]
    dts_this_year_monthly = groupby(dts_this_year, lambda d: d.month)
    days_all_monthly = get_days_monthly(
        dts[0].year, dts[-1].year, dts[0].month, dts[-1].month
    )
    days_this_year_monthly = get_days_monthly(this_year, this_year)
    attendance_all = []
    attendance_this_year = []
    for m in range(1, 13):
        if m in dts_all_monthly:
            attendance_all.append(len(dts_all_monthly[m]) / days_all_monthly[m] * 100)
        else:
            attendance_all.append(0.0)

        if m in dts_this_year_monthly:
            attendance_this_year.append(
                len(dts_this_year_monthly[m]) / days_this_year_monthly[m] * 100
            )
        else:
            attendance_this_year.append(0.0)

    return attendance_all, attendance_this_year


def pace_label_fmt(val: float, pos) -> str:
    min = val // 60
    sec = val % 60
    return f"{min:.0f}'{sec:.0f}\""


def make_circular(lst: list[T]) -> list[T]:
    if len(lst) > 1:
        lst.append(lst[0])
    return lst


def get_running_data() -> tuple[
    list[datetime], list[float], list[float], list[int]
]:
    """返回 dts, accs, distances, paces"""
    data = []
    with open(CSV_FILE) as file:
        for line in file:
            cols = line.rstrip().split(",")
            if cols[0] == "DT":
                continue
            dt = datetime.strptime(cols[0], "%Y-%m-%d %H:%M:%S")
            distance = float(cols[1])
            mins, secs = [int(i) for i in cols[3].split(":")]
            if secs == 60:
                mins = mins + 1
                secs = 0
            if distance <= 0.0:
                continue
            data.append((dt, distance, mins * 60 + secs))
    data.sort(key=lambda t: t[0])
    acc = 0.0
    dts = []
    accs = []
    distances = []
    paces = []
    for dt, distance, pace in data:
        acc += distance
        dts.append(dt)
        accs.append(acc)
        distances.append(distance)
        paces.append(pace)
    return dts, accs, distances, paces


def get_last_12_months_distances(dts: list[datetime], distances: list[float]) -> list[tuple[str, float]]:
    """Calculate total distance for each of the last 12 months."""
    today = datetime.now()
    last_12_months = []

    # 生成最近12个月的年月列表
    for i in range(11, -1, -1):
        month_date = today - relativedelta(months=i)
        year_month = month_date.strftime("%Y-%m")
        last_12_months.append((year_month, 0.0))

    # 按年月分组跑步数据
    monthly_distances = groupby(zip(dts, distances), lambda x: x[0].strftime("%Y-%m"))

    # 累加每个月的跑量
    for year_month, _ in last_12_months:
        if year_month in monthly_distances:
            total_distance = sum(dist for _, dist in monthly_distances[year_month])
            last_12_months = [(ym, total_distance if ym == year_month else dist) for ym, dist in last_12_months]

    print("Generated months:", last_12_months)
    return last_12_months

def plot_running() -> None:
    with plt.xkcd():
        fig, ax = plt.subplots(figsize=(8, 5), constrained_layout=True)
        ax.spines[["top", "right"]].set_visible(False)
        locator = mdates.AutoDateLocator(minticks=3, maxticks=7)
        formatter = mdates.ConciseDateFormatter(locator)
        ax.xaxis.set_major_locator(locator)
        ax.xaxis.set_major_formatter(formatter)
        ax.tick_params(axis="both", which="major", labelsize="small", length=5)
        ax.tick_params(axis="both", which="minor", labelsize="small", length=5)
        ax.set_title("running")

        dts, accs, distances, paces = get_running_data()
        this_year = datetime.now().year

        ax.plot(dts, accs, color="#d62728")

        # 配速小提琴图
        ax_pace = plt.axes([0.1, 0.72, 0.3, 0.1])
        v_all = ax_pace.violinplot(
            paces,
            orientation="horizontal",
            showmedians=True,
            showmeans=True,
            showextrema=False,
            side="low",
        )
        paces_this_year = [paces[i] for i, dt in enumerate(dts) if dt.year == this_year]
        v_year = ax_pace.violinplot(
            paces_this_year,
            orientation="horizontal",
            showmedians=True,
            showmeans=True,
            showextrema=False,
            side="high",
        )
        for body in v_all["bodies"]:
            body.set_facecolor("#ff7f0e")
            body.set_edgecolor("#ff7f0e")
        for body in v_year["bodies"]:
            body.set_facecolor("#2ca02c")
            body.set_edgecolor("#2ca02c")
        v_all["cmedians"].set_linewidth(1)
        v_all["cmedians"].set_color("#ff7f0e")
        v_year["cmedians"].set_linewidth(1)
        v_year["cmedians"].set_color("#2ca02c")
        v_all["cmeans"].set_linewidth(1)
        v_all["cmeans"].set_color("#ff7f0e")
        v_year["cmeans"].set_linewidth(1)
        v_year["cmeans"].set_color("#2ca02c")
        v_all["cmeans"].set_linestyle("--")
        v_year["cmeans"].set_linestyle("--")

        paces_percentile = np.percentile(paces, [5, 95])
        ax_pace.set_xlim(tuple(paces_percentile))
        ax_pace.set_yticklabels([])
        ax_pace.spines[["top", "right", "left", "bottom"]].set_visible(False)
        ax_pace.tick_params(axis="x", which="major", labelsize="xx-small", length=2)
        ax_pace.tick_params(axis="y", which="major", labelsize="xx-small", length=0)
        ax_pace.xaxis.set_major_locator(tick.MaxNLocator(6))
        ax_pace.xaxis.set_major_formatter(tick.FuncFormatter(pace_label_fmt))

        # 出勤率雷达图
        attendance_all, attendance_this_year = tuple(
            map(make_circular, get_attendance(dts))
        )
        feature = make_circular(
            [
                "Jan",
                "",
                "",
                "Apr",
                "",
                "",
                "Jul",
                "",
                "",
                "Oct",
                "",
                "",
            ]
        )
        angles_deg = make_circular([a for a in range(0, 360, 30)])
        angles_rad = make_circular([a * math.pi / 180 for a in range(0, 360, 30)])

        ax_att = plt.axes([0.1, 0.28, 0.25, 0.25], polar=True)
        ax_att.plot(angles_rad, attendance_all, "-", linewidth=1, color="#ff7f0e")
        ax_att.fill(angles_rad, attendance_all, alpha=0.15, zorder=2, color="#ff7f0e")
        ax_att.plot(angles_rad, attendance_this_year, "-", linewidth=1, color="#2ca02c")
        ax_att.fill(
            angles_rad, attendance_this_year, alpha=0.15, zorder=3, color="#2ca02c"
        )
        ax_att.spines["polar"].set_linestyle("--")
        ax_att.spines["polar"].set_linewidth(0.5)
        ax_att.spines["polar"].set_color("grey")
        ax_att.tick_params(axis="x", which="major", labelsize="xx-small", length=0)
        ax_att.tick_params(axis="y", which="major", labelsize="xx-small", length=0)
        ax_att.set_thetagrids(angles_deg, feature)
        ax_att.set_yticks([20, 40, 60, 80, 100])
        ax_att.set_yticklabels(["", "", "", "", "100%"])
        ax_att.set_ylim(0, 100)
        ax_att.grid(visible=True, lw=0.5, ls="--")

        # 信息文字
        years = dts[-1].year - dts[0].year + 1
        distance_this_year = sum(
            [distances[i] for i, dt in enumerate(dts) if dt.year == this_year]
        )
        fig.text(
            0.97,
            0.15,
            f"{RUNNER}\n"
            f"{years} years\n"
            f"{len(dts)} times\n"
            f"total {accs[-1]:.2f}Km\n"
            f"this year {distance_this_year:.2f}Km\n"
            f"latest {dts[-1]: %Y-%m-%d} {distances[-1]:.2f}Km",
            ha="right",
            va="bottom",
            fontsize="small",
            linespacing=1.5,
        )

        # 最近12个月跑量柱状图
        monthly_distances = get_last_12_months_distances(dts, distances)
        months = [ym for ym, _ in monthly_distances]
        distances_monthly = [dist for _, dist in monthly_distances]
        ax_bar = plt.axes([0.45, 0.72, 0.25, 0.2])
        ax_bar.bar(months, distances_monthly, color="#cbe2c5")
        ax_bar.tick_params(axis="both", which="both", labelsize=6)
        ax_bar.spines[["top", "right"]].set_visible(False)
        ax_bar.spines[["left", "bottom"]].set_linewidth(0.5)
        ax_bar.xaxis.set_major_locator(tick.MaxNLocator(12))
        ax_bar.set_xticks(range(len(months)))  # 明确设置横轴刻度位置
        ax_bar.set_xticklabels(months, rotation=45, ha="right", fontsize=6)  # 调整旋转角度
        ax_bar.yaxis.set_major_locator(tick.MaxNLocator(5))
        ax_bar.tick_params(axis="x", which="major", labelsize=6, width=0.5, color="grey")  # 调整横轴刻度点
        ax_bar.tick_params(axis="y", which="major", labelsize=6, width=0.5, color="grey")  # 调整纵轴刻度点

        # 添加跑步者图片
        img = plt.imread("runner.png")
        ax.add_artist(
            AnnotationBbox(
                OffsetImage(img, zoom=0.03),
                (0.95, 0.05),
                xycoords="axes fraction",
                frameon=False,
            )
        )
        fig.savefig(OUT_SVG)


if __name__ == "__main__":
    plot_running()