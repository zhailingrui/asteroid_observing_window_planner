#!/usr/bin/env python3
"""Find proposal-ready observing windows from a JPL Horizons ephemeris.

The program accepts either the compact CSV exported by this repository or a
Horizons observer-table text file.  A solar ephemeris may be supplied to add a
seasonal, latitude-only visibility estimate.
"""

from __future__ import annotations

import argparse
import csv
import math
import json
import re
from html import escape
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen


FIELDS = ("date", "ra", "dec", "mag", "r", "delta", "elong", "phase", "moon_sep", "moon_illum", "rate", "psang", "psamv", "plane", "true_anomaly")


def number(value: str | None) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except ValueError:
        return None


def raw_rows(path: Path) -> list[list[str]]:
    text = path.read_text()
    try:
        block = text.split("$$SOE", 1)[1].split("$$EOE", 1)[0].strip()
    except IndexError as exc:
        raise ValueError(f"{path} is not a Horizons table (missing $$SOE/$$EOE).") from exc
    return [[value.strip() for value in row] for row in csv.reader(block.splitlines())]


def load_horizons(path: Path) -> list[dict[str, float | str | None]]:
    result = []
    for row in raw_rows(path):
        result.append({
            "date": datetime.strptime(row[0], "%Y-%b-%d %H:%M").strftime("%Y-%m-%d"),
            "ra": number(row[3]), "dec": number(row[4]),
            "rate": math.hypot(number(row[5]) or 0, number(row[6]) or 0),
            "mag": number(row[7]), "r": number(row[9]), "delta": number(row[11]),
            "elong": number(row[13]), "phase": number(row[15]),
            "moon_sep": number(row[16]), "moon_illum": number(row[17]),
            "psang": number(row[18]), "psamv": number(row[19]),
            "plane": number(row[20]), "true_anomaly": number(row[21]),
        })
    return result


def load_csv(path: Path) -> list[dict[str, float | str | None]]:
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        missing = {"date", "mag", "elong", "moon_sep", "moon_illum", "plane"} - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path} is missing required columns: {', '.join(sorted(missing))}")
        return [{key: row["date"] if key == "date" else number(row.get(key)) for key in FIELDS} for row in reader]


def load_sun(path: Path) -> list[dict[str, float | str | None]]:
    """Load the shorter RA/Dec-only Horizons table used for the Sun."""
    return [
        {
            "date": datetime.strptime(row[0], "%Y-%b-%d %H:%M").strftime("%Y-%m-%d"),
            "ra": number(row[3]),
            "dec": number(row[4]),
        }
        for row in raw_rows(path)
    ]


def horizons_api(target: str, start: str, stop: str) -> tuple[str, list[dict[str, float | str | None]]]:
    """Fetch daily geocentric observer ephemerides from JPL Horizons."""
    if not re.fullmatch(r"[A-Za-z0-9 .()_+\-/]+", target):
        raise ValueError("Use a simple Horizons number or designation.")
    params = {
        "format": "json", "COMMAND": f"'{target}'", "OBJ_DATA": "NO", "MAKE_EPHEM": "YES",
        "EPHEM_TYPE": "OBSERVER", "CENTER": "500@399", "START_TIME": start, "STOP_TIME": stop,
        "STEP_SIZE": "1 d", "CSV_FORMAT": "YES", "ANG_FORMAT": "DEG", "APPARENT": "AIRLESS", "REF_SYSTEM": "ICRF",
    }
    with urlopen("https://ssd.jpl.nasa.gov/api/horizons.api?" + urlencode(params), timeout=60) as response:
        result = json.load(response)["result"]
    try:
        block = result.split("$$SOE", 1)[1].split("$$EOE", 1)[0].strip()
    except IndexError as exc:
        raise ValueError("Horizons did not return an ephemeris table for that target/date range.") from exc
    rows = []
    months = {m: f"{i:02d}" for i, m in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), 1)}
    for values in csv.reader(block.splitlines()):
        row = [v.strip() for v in values]
        year, month, day = row[0].split()[0].split("-")
        rows.append({
            "date": f"{year}-{months[month]}-{day}", "ra": number(row[3]), "dec": number(row[4]),
            "rate": number(row[84]), "mag": number(row[19]), "r": number(row[36]), "delta": number(row[38]),
            "elong": number(row[43]), "phase": number(row[45]), "moon_sep": number(row[46]),
            "moon_illum": number(row[47]), "psang": number(row[49]), "psamv": number(row[50]),
            "plane": number(row[51]), "true_anomaly": number(row[74]),
        })
    name = re.search(r"Target body name:\s*([^\n{]+)", result)
    return (name.group(1).strip() if name else target), rows


def horizons_vectors_api(target: str, start: str, stop: str) -> tuple[str, list[dict[str, float | str]]]:
    """Fetch daily heliocentric ecliptic position vectors from JPL Horizons."""
    if not re.fullmatch(r"[A-Za-z0-9 .()_+\-/]+", target):
        raise ValueError("Use a simple Horizons number or designation.")
    params = {
        "format": "json", "COMMAND": f"'{target}'", "OBJ_DATA": "NO", "MAKE_EPHEM": "YES",
        "EPHEM_TYPE": "VECTORS", "CENTER": "500@10", "START_TIME": start, "STOP_TIME": stop,
        "STEP_SIZE": "1 d", "OUT_UNITS": "AU-D", "REF_PLANE": "ECLIPTIC", "REF_SYSTEM": "J2000",
        "VEC_TABLE": "2", "CSV_FORMAT": "YES",
    }
    with urlopen("https://ssd.jpl.nasa.gov/api/horizons.api?" + urlencode(params), timeout=60) as response:
        result = json.load(response)["result"]
    try:
        block = result.split("$$SOE", 1)[1].split("$$EOE", 1)[0].strip()
    except IndexError as exc:
        raise ValueError("Horizons did not return a heliocentric vector table for that target/date range.") from exc
    vectors = []
    for values in csv.reader(block.splitlines()):
        row = [value.strip() for value in values]
        timestamp = datetime.strptime(row[1].replace("A.D. ", "").split(".")[0], "%Y-%b-%d %H:%M:%S")
        vectors.append({"date": timestamp, "x": float(row[2]), "y": float(row[3]), "z": float(row[4])})
    name = re.search(r"Target body name:\s*([^\n{]+)", result)
    return (name.group(1).strip() if name else target), vectors


def altitude(latitude: float, dec: float, hour_angle: float) -> float:
    lat, dec, hour_angle = map(math.radians, (latitude, dec, hour_angle))
    return math.degrees(math.asin(math.sin(lat) * math.sin(dec) + math.cos(lat) * math.cos(dec) * math.cos(hour_angle)))


def visible_hours(target: dict, sun: dict, latitude: float, samples: int = 288) -> float:
    if any(target.get(key) is None for key in ("ra", "dec")) or any(sun.get(key) is None for key in ("ra", "dec")):
        return 0.0
    visible = sum(
        altitude(latitude, float(target["dec"]), 360 * (i + .5) / samples - float(target["ra"])) >= 30
        and altitude(latitude, float(sun["dec"]), 360 * (i + .5) / samples - float(sun["ra"])) <= -18
        for i in range(samples)
    )
    return round(24 * visible / samples, 2)


def qualifying(row: dict, args: argparse.Namespace) -> bool:
    return (
        (row["mag"] is not None and row["mag"] <= args.max_mag)
        and (row["elong"] is not None and row["elong"] >= args.min_elongation)
        and (row["moon_sep"] is not None and row["moon_sep"] >= args.min_moon_separation)
        and (row["moon_illum"] is not None and row["moon_illum"] <= args.max_moon_illumination)
        and (row["plane"] is not None and abs(float(row["plane"])) <= args.max_plane_angle)
        and (row.get("visible_hours") is None or float(row["visible_hours"]) >= args.min_visible_hours)
    )


def windows(rows: Iterable[dict]) -> list[list[dict]]:
    groups: list[list[dict]] = []
    for row in rows:
        day = datetime.fromisoformat(str(row["date"]))
        if not groups or (day - datetime.fromisoformat(str(groups[-1][-1]["date"]))).days > 1:
            groups.append([row])
        else:
            groups[-1].append(row)
    return groups


def fmt(value: float | str | None, digits: int = 2) -> str:
    return "—" if value is None else f"{float(value):.{digits}f}" if isinstance(value, float) else str(value)


def equatorial_to_galactic(ra: float, dec: float) -> tuple[float, float]:
    """Convert ICRF/J2000 RA, Dec (degrees) to Galactic longitude, latitude."""
    ra_r, dec_r = math.radians(ra), math.radians(dec)
    vector = (math.cos(dec_r) * math.cos(ra_r), math.cos(dec_r) * math.sin(ra_r), math.sin(dec_r))
    matrix = ((-0.0548755604, -0.8734370902, -0.4838350155),
              ( 0.4941094279, -0.4448296300,  0.7469822445),
              (-0.8676661490, -0.1980763734,  0.4559837762))
    x, y, z = (sum(row[i] * vector[i] for i in range(3)) for row in matrix)
    return math.degrees(math.atan2(y, x)) % 360, math.degrees(math.asin(max(-1, min(1, z))))


def write_orbit_products(rows: list[dict], target_vectors: list[dict], earth_vectors: list[dict], output: Path) -> None:
    """Write static, 2D animated and 3D animated heliocentric orbit products."""
    try:
        import matplotlib.pyplot as plt
        import numpy as np
        from matplotlib.animation import FFMpegWriter, FuncAnimation, PillowWriter, writers
    except ModuleNotFoundError as exc:
        raise RuntimeError("Run with .venv/bin/python after installing plotting dependencies.") from exc
    count = min(len(target_vectors), len(earth_vectors))
    if count < 2:
        raise RuntimeError("Horizons returned too few vector rows for an orbit animation.")
    target_vectors, earth_vectors = target_vectors[:count], earth_vectors[:count]
    frame_indices = list(range(0, count, 10))
    if frame_indices[-1] != count - 1:
        frame_indices.append(count - 1)

    key_date = min(rows, key=lambda row: float(row["mag"]) if row["mag"] is not None else float("inf"))["date"]
    key_time = datetime.fromisoformat(str(key_date))
    key_index = min(range(count), key=lambda i: abs((target_vectors[i]["date"] - key_time).total_seconds()))
    earth_key, target_key = earth_vectors[key_index], target_vectors[key_index]
    xs = [float(item["x"]) for item in target_vectors + earth_vectors]
    ys = [float(item["y"]) for item in target_vectors + earth_vectors]
    zs = [float(item["z"]) for item in target_vectors + earth_vectors]
    extent = max(max(map(abs, xs)), max(map(abs, ys)), 1.0) * 1.12
    z_extent = max(max(map(abs, zs)), 0.4) * 1.25

    # Static overview at the brightest predicted date in the requested interval.
    fig = plt.figure(figsize=(11, 5.2), constrained_layout=True)
    ax_top = fig.add_subplot(1, 2, 1)
    ax_3d = fig.add_subplot(1, 2, 2, projection="3d")
    for ax in (ax_top,):
        ax.plot([item["x"] for item in earth_vectors], [item["y"] for item in earth_vectors], color="tab:blue", lw=1.5, label="Earth")
        ax.plot([item["x"] for item in target_vectors], [item["y"] for item in target_vectors], color="tab:orange", lw=1.7, label="Target")
        ax.scatter(0, 0, marker="*", s=160, color="gold", edgecolor="0.35", zorder=5, label="Sun")
        ax.scatter(earth_key["x"], earth_key["y"], color="tab:blue", s=38, zorder=6)
        ax.scatter(target_key["x"], target_key["y"], color="tab:orange", s=38, zorder=6)
        ax.plot([0, earth_key["x"], target_key["x"], 0], [0, earth_key["y"], target_key["y"], 0], color="0.35", ls="--", lw=0.9)
        ax.set(xlim=(-extent, extent), ylim=(-extent, extent), title="Ecliptic-plane view", xlabel="Heliocentric X (au)", ylabel="Heliocentric Y (au)")
        ax.set_aspect("equal", adjustable="box"); ax.legend(loc="best", fontsize=8)
    ax_3d.plot([item["x"] for item in earth_vectors], [item["y"] for item in earth_vectors], [item["z"] for item in earth_vectors], color="tab:blue", lw=1.5, label="Earth")
    ax_3d.plot([item["x"] for item in target_vectors], [item["y"] for item in target_vectors], [item["z"] for item in target_vectors], color="tab:orange", lw=1.7, label="Target")
    ax_3d.scatter([0], [0], [0], marker="*", s=160, color="gold", edgecolor="0.35", label="Sun")
    ax_3d.scatter([earth_key["x"]], [earth_key["y"]], [earth_key["z"]], color="tab:blue", s=30)
    ax_3d.scatter([target_key["x"]], [target_key["y"]], [target_key["z"]], color="tab:orange", s=30)
    ax_3d.plot([0, earth_key["x"], target_key["x"], 0], [0, earth_key["y"], target_key["y"], 0], [0, earth_key["z"], target_key["z"], 0], color="0.35", ls="--", lw=0.9)
    ax_3d.set(xlim=(-extent, extent), ylim=(-extent, extent), zlim=(-z_extent, z_extent), title="3D heliocentric view", xlabel="X (au)", ylabel="Y (au)", zlabel="Z (au)")
    ax_3d.set_box_aspect((1, 1, max(.35, z_extent / extent))); ax_3d.view_init(elev=24, azim=-58); ax_3d.legend(loc="upper left", fontsize=8)
    fig.suptitle(f"Earth–Sun–target geometry · {key_date}", fontsize=12)
    fig.savefig(output / "07_heliocentric_orbits.png", dpi=300, bbox_inches="tight", facecolor="white"); plt.close(fig)

    # Two-panel 2D animation: ecliptic top-down and side view.
    fig, (ax_top, ax_side) = plt.subplots(1, 2, figsize=(10.5, 5.0), constrained_layout=True)
    for ax in (ax_top, ax_side): ax.grid(True, alpha=.25)
    ax_top.plot([item["x"] for item in earth_vectors], [item["y"] for item in earth_vectors], color="tab:blue", alpha=.75, lw=1.2, label="Earth")
    ax_top.plot([item["x"] for item in target_vectors], [item["y"] for item in target_vectors], color="tab:orange", alpha=.75, lw=1.4, label="Target")
    ax_top.scatter(0, 0, marker="*", s=130, color="gold", edgecolor="0.35", zorder=5, label="Sun")
    ax_top.set(xlim=(-extent, extent), ylim=(-extent, extent), title="Ecliptic-plane view", xlabel="Heliocentric X (au)", ylabel="Heliocentric Y (au)"); ax_top.set_aspect("equal", adjustable="box"); ax_top.legend(loc="upper left", fontsize=8)
    ax_side.plot([item["x"] for item in earth_vectors], [item["z"] for item in earth_vectors], color="tab:blue", alpha=.75, lw=1.2, label="Earth")
    ax_side.plot([item["x"] for item in target_vectors], [item["z"] for item in target_vectors], color="tab:orange", alpha=.75, lw=1.4, label="Target")
    ax_side.scatter(0, 0, marker="*", s=130, color="gold", edgecolor="0.35", zorder=5, label="Sun")
    ax_side.axhline(0, color="0.5", lw=.8, ls=":")
    ax_side.set(xlim=(-extent, extent), ylim=(-z_extent, z_extent), title="Side view relative to the ecliptic", xlabel="Heliocentric X (au)", ylabel="Heliocentric Z (au)")
    earth_top, = ax_top.plot([], [], "o", color="tab:blue", ms=6); target_top, = ax_top.plot([], [], "o", color="tab:orange", ms=6); geometry_top, = ax_top.plot([], [], color="0.3", ls="--", lw=.9)
    earth_side, = ax_side.plot([], [], "o", color="tab:blue", ms=6); target_side, = ax_side.plot([], [], "o", color="tab:orange", ms=6); geometry_side, = ax_side.plot([], [], color="0.3", ls="--", lw=.9)
    title = fig.suptitle("", fontsize=12)
    def update_2d(frame: int):
        i = frame_indices[frame]; earth, target = earth_vectors[i], target_vectors[i]
        earth_top.set_data([earth["x"]], [earth["y"]]); target_top.set_data([target["x"]], [target["y"]]); geometry_top.set_data([0, earth["x"], target["x"], 0], [0, earth["y"], target["y"], 0])
        earth_side.set_data([earth["x"]], [earth["z"]]); target_side.set_data([target["x"]], [target["z"]]); geometry_side.set_data([0, earth["x"], target["x"], 0], [0, earth["z"], target["z"], 0])
        title.set_text(f"Earth–Sun–target geometry · {target['date']:%Y-%m-%d}")
        return earth_top, target_top, geometry_top, earth_side, target_side, geometry_side, title
    animation_2d = FuncAnimation(fig, update_2d, frames=len(frame_indices), interval=85, blit=False)
    animation_2d.save(output / "08_heliocentric_orbit_2d.gif", writer=PillowWriter(fps=12), dpi=105)
    if writers.is_available("ffmpeg"):
        animation_2d.save(output / "08_heliocentric_orbit_2d.mp4", writer=FFMpegWriter(fps=12, codec="libx264", bitrate=1800, extra_args=["-pix_fmt", "yuv420p", "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-movflags", "+faststart"]), dpi=105)
    plt.close(fig)

    # Fixed-camera 3D animation with a translucent ecliptic reference plane.
    fig = plt.figure(figsize=(7.5, 6.6), constrained_layout=True); ax = fig.add_subplot(111, projection="3d")
    ax.plot([item["x"] for item in earth_vectors], [item["y"] for item in earth_vectors], [item["z"] for item in earth_vectors], color="tab:blue", alpha=.75, lw=1.3, label="Earth")
    ax.plot([item["x"] for item in target_vectors], [item["y"] for item in target_vectors], [item["z"] for item in target_vectors], color="tab:orange", alpha=.75, lw=1.5, label="Target")
    plane = np.linspace(-extent, extent, 2)
    plane_x, plane_y = np.meshgrid(plane, plane)
    ax.plot_surface(plane_x, plane_y, np.zeros_like(plane_x), color="0.6", alpha=.08, shade=False)
    ax.scatter([0], [0], [0], marker="*", s=150, color="gold", edgecolor="0.35", label="Sun")
    earth_point, = ax.plot([], [], [], "o", color="tab:blue", ms=7, label="Earth"); target_point, = ax.plot([], [], [], "o", color="tab:orange", ms=7, label="Target"); geometry, = ax.plot([], [], [], color="0.3", ls="--", lw=.9)
    ax.set(xlim=(-extent, extent), ylim=(-extent, extent), zlim=(-z_extent, z_extent), xlabel="Heliocentric X (au)", ylabel="Heliocentric Y (au)", zlabel="Heliocentric Z (au)")
    ax.set_box_aspect((1, 1, max(.35, z_extent / extent))); ax.view_init(elev=6, azim=-176.44); ax.legend(loc="upper left", fontsize=8)
    title = fig.suptitle("", fontsize=12)
    def update_3d(frame: int):
        i = frame_indices[frame]; earth, target = earth_vectors[i], target_vectors[i]
        earth_point.set_data_3d([earth["x"]], [earth["y"]], [earth["z"]]); target_point.set_data_3d([target["x"]], [target["y"]], [target["z"]]); geometry.set_data_3d([0, earth["x"], target["x"], 0], [0, earth["y"], target["y"], 0], [0, earth["z"], target["z"], 0])
        title.set_text(f"3D Earth–Sun–target geometry · {target['date']:%Y-%m-%d}")
        return earth_point, target_point, geometry, title
    animation_3d = FuncAnimation(fig, update_3d, frames=len(frame_indices), interval=100, blit=False)
    animation_3d.save(output / "09_heliocentric_orbit_3d.gif", writer=PillowWriter(fps=10), dpi=100)
    if writers.is_available("ffmpeg"):
        animation_3d.save(output / "09_heliocentric_orbit_3d.mp4", writer=FFMpegWriter(fps=10, codec="libx264", bitrate=1800, extra_args=["-pix_fmt", "yuv420p", "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2", "-movflags", "+faststart"]), dpi=100)
    plt.close(fig)


def write_outputs(rows: list[dict], args: argparse.Namespace) -> None:
    args.output.mkdir(parents=True, exist_ok=True)
    if args.figures_only:
        write_svg_plots(rows, args.output)
        print(f"Wrote figures only to {args.output}")
        return
    candidates = [row for row in rows if qualifying(row, args)]
    columns = list(FIELDS) + (["visible_hours"] if any("visible_hours" in row for row in rows) else [])
    with (args.output / "candidate_nights.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader(); writer.writerows(candidates)

    groups = windows(candidates)
    lines = ["# Observing-window shortlist", "", "## Criteria", "",
             f"- V ≤ {args.max_mag:.1f} mag; solar elongation ≥ {args.min_elongation:.0f}°.",
             f"- Moon separation ≥ {args.min_moon_separation:.0f}°; Moon illumination ≤ {args.max_moon_illumination:.0f}%.",
             f"- |Orbit-plane angle| ≤ {args.max_plane_angle:.1f}°."]
    if args.sun: lines.append(f"- Seasonal visibility at latitude {args.latitude:.1f}°: ≥ {args.min_visible_hours:.1f} h/night (target altitude ≥30°, Sun altitude ≤−18°).")
    lines += ["", "## Consecutive candidate windows", "", "| Window | Nights | Best V | Mean Moon separation | |Plane angle| range |", "|---|---:|---:|---:|---:|"]
    for group in groups:
        dates = f"{group[0]['date']} — {group[-1]['date']}"
        best = min(float(row["mag"]) for row in group)
        moon = sum(float(row["moon_sep"]) for row in group) / len(group)
        planes = [abs(float(row["plane"])) for row in group]
        lines.append(f"| {dates} | {len(group)} | {best:.2f} | {moon:.1f}° | {min(planes):.2f}–{max(planes):.2f}° |")
    if not groups: lines += ["| No dates satisfy all current criteria. | 0 | — | — | — |", "", "Relax one or more constraints and run again."]
    (args.output / "observing_window_report.md").write_text("\n".join(lines) + "\n")
    if args.plots:
        write_svg_plots(rows, args.output)
    print(f"{len(candidates)} candidate nights in {len(groups)} window(s)")
    print(args.output / "candidate_nights.csv")
    print(args.output / "observing_window_report.md")


def write_svg_plots(rows: list[dict], output: Path) -> None:
    """Write dependency-free SVG analysis figures for any queried target."""
    try:
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        from matplotlib.ticker import FuncFormatter
    except ModuleNotFoundError as exc:
        raise RuntimeError("Run with .venv/bin/python after installing plotting dependencies.") from exc
    dates = [datetime.fromisoformat(str(r["date"])) for r in rows]
    def save(fig, name):
        fig.savefig(output / name, dpi=300, bbox_inches="tight", facecolor="white")
        plt.close(fig)
    fig, ax = plt.subplots(figsize=(9, 4.8)); ax2 = ax.twinx()
    ax.plot(dates, [r["mag"] for r in rows], label="Predicted V magnitude", color="tab:blue"); ax.invert_yaxis()
    ax2.plot(dates, [r["r"] for r in rows], label="Heliocentric distance r", color="tab:orange"); ax2.plot(dates, [r["delta"] for r in rows], label="Geocentric distance Δ", color="tab:green")
    ax.set(title="Predicted brightness and distance", xlabel="Date (UTC)", ylabel="V magnitude"); ax2.set_ylabel("Distance (au)"); ax.xaxis.set_major_locator(mdates.MonthLocator(interval=max(1,len(rows)//180))); fig.autofmt_xdate(); save(fig, "01_brightness_distance.png")
    fig, ax = plt.subplots(figsize=(9, 4.8))
    for key, label in [("elong","Solar elongation"),("phase","Phase angle"),("moon_sep","Target–Moon separation")]: ax.plot(dates,[r[key] for r in rows],label=label)
    ax.set(title="Observing geometry", xlabel="Date (UTC)", ylabel="Angle (deg)", ylim=(0,190)); ax.legend(); fig.autofmt_xdate(); save(fig, "02_observing_geometry.png")
    # Unwrap RA so a crossing of 0°/360° remains a continuous sky track.
    ra_unwrapped = [float(rows[0]["ra"])]
    for row in rows[1:]:
        ra = float(row["ra"])
        previous = ra_unwrapped[-1]
        while ra - previous > 180: ra -= 360
        while ra - previous < -180: ra += 360
        ra_unwrapped.append(ra)
    fig, ax = plt.subplots(figsize=(8, 5.7)); ax.plot(ra_unwrapped, [r["dec"] for r in rows], color="tab:blue")
    for i in range(0, len(rows), max(1, len(rows)//6)):
        r = rows[i]; offset = (5, 5) if (i // max(1, len(rows)//6)) % 2 == 0 else (5, -13)
        ax.scatter(ra_unwrapped[i], r["dec"], color="tab:orange", s=22, zorder=3); ax.annotate(r["date"], (ra_unwrapped[i], r["dec"]), xytext=offset, textcoords="offset points", fontsize=8)
    ax.invert_xaxis(); ax.xaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value % 360:.0f}°")); ax.set(title="Apparent sky track",xlabel="Right ascension (deg, increasing left)",ylabel="Declination (deg)"); save(fig, "03_radec_track.png")
    if all("sun_ra" in r and "sun_dec" in r for r in rows):
        latitudes = list(range(-50, 51, 10)); weekly = rows[::7]
        heat = [[visible_hours(r, {"ra":r["sun_ra"], "dec":r["sun_dec"]}, lat) for r in weekly] for lat in latitudes]
        start_num = mdates.date2num(datetime.fromisoformat(weekly[0]["date"])); end_num = mdates.date2num(datetime.fromisoformat(weekly[-1]["date"]))
        if end_num <= start_num: end_num = start_num + 1
        fig, ax = plt.subplots(figsize=(10, 4.9)); image = ax.imshow(heat, origin="lower", aspect="auto", cmap="viridis", extent=[start_num, end_num, latitudes[0]-5, latitudes[-1]+5])
        ax.xaxis_date(); ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m")); ax.set(title="Available astronomical-night time by site latitude", xlabel="Date (UTC; weekly sampling)", ylabel="Site latitude (deg)"); fig.colorbar(image, ax=ax, label="Observable hours per night"); fig.autofmt_xdate(); save(fig, "04_visibility_latitude.png")
    fig, axes = plt.subplots(2,1,figsize=(9,5.8),sharex=True); axes[0].plot(dates,[r["rate"] for r in rows],color="tab:blue"); axes[0].set_ylabel("Sky rate\n(arcsec h$^{-1}$)"); axes[1].plot(dates,[r["plane"] for r in rows],color="tab:green"); axes[1].axhline(0,color="0.4",ls="--"); axes[1].set_ylabel("Orbit-plane\nangle (deg)"); axes[1].set_xlabel("Date (UTC)"); fig.autofmt_xdate(); save(fig, "05_tracking_plane.png")
    galactic = [equatorial_to_galactic(float(r["ra"]), float(r["dec"])) for r in rows]
    longitudes = [galactic[0][0]]
    for longitude, _ in galactic[1:]:
        previous = longitudes[-1]
        while longitude - previous > 180: longitude -= 360
        while longitude - previous < -180: longitude += 360
        longitudes.append(longitude)
    fig, ax = plt.subplots(figsize=(8, 5.2)); ax.plot(longitudes, [latitude for _, latitude in galactic], color="tab:blue")
    ax.axhline(0, color="tab:orange", ls="--", label="Galactic plane (b = 0°)")
    for i in range(0, len(rows), max(1, len(rows)//6)):
        offset = (5, 5) if (i // max(1, len(rows)//6)) % 2 == 0 else (5, -13)
        ax.scatter(longitudes[i], galactic[i][1], color="tab:blue", s=18, zorder=3); ax.annotate(rows[i]["date"], (longitudes[i], galactic[i][1]), xytext=offset, textcoords="offset points", fontsize=8)
    ax.invert_xaxis(); ax.xaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value % 360:.0f}°")); ax.set(title="Sky track relative to the Galactic plane", xlabel="Galactic longitude l (deg, increasing left)", ylabel="Galactic latitude b (deg)"); ax.legend(); save(fig, "06_galactic_plane_track.png")
    return
    def plot(name: str, title: str, series: list[tuple[str, str, callable]], invert=False):
        width, height, left, top, right, bottom = 1100, 520, 86, 42, 38, 70
        values = [float(fn(r)) for _, _, fn in series for r in rows if fn(r) is not None]
        lo, hi = min(values), max(values)
        pad = (hi - lo or 1) * .08; lo -= pad; hi += pad
        def xy(i, value):
            x = left + i * (width-left-right) / max(1, len(rows)-1)
            fraction = (value-lo)/(hi-lo)
            y = top + (height-top-bottom) * (fraction if invert else 1-fraction)
            return x, y
        paths = []
        legend = []
        for label, color, fn in series:
            points = [xy(i, float(fn(r))) for i, r in enumerate(rows) if fn(r) is not None]
            paths.append(f'<path d="M' + ' L'.join(f'{x:.1f},{y:.1f}' for x,y in points) + f'" fill="none" stroke="{color}" stroke-width="2.4"/>')
            legend.append(f'<span style="color:{color}">■</span> {escape(label)}')
        dates = [rows[0]["date"], rows[len(rows)//2]["date"], rows[-1]["date"]]
        svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<rect width="100%" height="100%" fill="white"/><style>text{{font-family:Arial,sans-serif;fill:#17233a}}.t{{font-size:22px;font-weight:bold}}.a{{font-size:14px;fill:#526070}}</style>
<text x="{left}" y="27" class="t">{escape(title)}</text><rect x="{left}" y="{top}" width="{width-left-right}" height="{height-top-bottom}" fill="none" stroke="#9aa8b8"/>
<text x="12" y="{top+5}" class="a">{hi:.2f}</text><text x="12" y="{height-bottom}" class="a">{lo:.2f}</text>
{''.join(paths)}<text x="{left}" y="{height-28}" class="a">{dates[0]}</text><text x="{width/2}" y="{height-28}" text-anchor="middle" class="a">{dates[1]}</text><text x="{width-right}" y="{height-28}" text-anchor="end" class="a">{dates[2]}</text>
<foreignObject x="{left}" y="{height-20}" width="850" height="20"><div xmlns="http://www.w3.org/1999/xhtml" style="font:14px Arial">{' &nbsp; '.join(legend)}</div></foreignObject></svg>'''
        (output / name).write_text(svg)
    plot("01_brightness_distance.svg", "Predicted brightness and distance", [("V magnitude (inverted)", "#1677b8", lambda r: -r["mag"]), ("Heliocentric r (au)", "#ed8b00", lambda r: r["r"]), ("Geocentric Δ (au)", "#25935b", lambda r: r["delta"])])
    plot("02_observing_geometry.svg", "Solar elongation, phase angle and Moon separation", [("Solar elongation (deg)", "#1677b8", lambda r: r["elong"]), ("Phase angle (deg)", "#ed8b00", lambda r: r["phase"]), ("Moon separation (deg)", "#9d3cb0", lambda r: r["moon_sep"])])
    plot("03_tracking_plane.svg", "Sky motion and orbit-plane angle", [("Sky motion (arcsec h-1)", "#1677b8", lambda r: r["rate"]), ("Absolute plane angle (deg)", "#25935b", lambda r: abs(r["plane"]))])
    # RA/Dec track is a dedicated x-y plot.
    ra = [float(r["ra"]) for r in rows]; dec = [float(r["dec"]) for r in rows]; w,h,p=900,560,70
    xmin,xmax=min(ra),max(ra); ymin,ymax=min(dec),max(dec)
    pts = [(p+(xmax-x)*(w-2*p)/(xmax-xmin or 1), p+(ymax-y)*(h-2*p)/(ymax-ymin or 1)) for x,y in zip(ra,dec)]
    track = f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}"><rect width="100%" height="100%" fill="white"/><text x="{p}" y="30" font-family="Arial" font-size="22" font-weight="bold">RA/Dec sky track (RA increases leftward)</text><rect x="{p}" y="{p}" width="{w-2*p}" height="{h-2*p}" fill="none" stroke="#9aa8b8"/><path d="M'+' L'.join(f'{x:.1f},{y:.1f}' for x,y in pts)+'" fill="none" stroke="#1677b8" stroke-width="2.5"/></svg>'
    (output / "04_radec_track.svg").write_text(track)
    print("Wrote SVG analysis figures to", output)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, nargs="?", help="Compact ephemeris CSV or Horizons target table")
    parser.add_argument("--target", help="Horizons number or designation, e.g. 311P or Gault")
    parser.add_argument("--start", help="UTC start date, YYYY-MM-DD (with --target)")
    parser.add_argument("--stop", help="UTC stop date, YYYY-MM-DD (with --target)")
    parser.add_argument("--sun", type=Path, help="Horizons Sun table, required for visibility calculation")
    parser.add_argument("--latitude", type=float, default=-30, help="Observatory latitude in degrees (default: -30)")
    parser.add_argument("--min-visible-hours", type=float, default=0, help="Minimum approximate nightly visibility")
    parser.add_argument("--max-mag", type=float, default=17.5)
    parser.add_argument("--min-elongation", type=float, default=120)
    parser.add_argument("--min-moon-separation", type=float, default=45)
    parser.add_argument("--max-moon-illumination", type=float, default=60)
    parser.add_argument("--max-plane-angle", type=float, default=2)
    parser.add_argument("--plots", action="store_true", default=True, help="PNG analysis figures are written by default")
    parser.add_argument("--figures-only", action="store_true", help="Write only PNG analysis figures; do not create window CSV or report")
    parser.add_argument("--orbit-animations", action="store_true", help="Also write heliocentric 2D/3D orbit GIFs and MP4s when ffmpeg is available")
    parser.add_argument("--gault-figures", action="store_true", help="One-command preset: Gault, 2026-08-01 to 2027-11-15, figures only, output ./Gault")
    parser.add_argument("--output", type=Path, default=Path("observing_window_output"))
    args = parser.parse_args()
    if args.gault_figures:
        args.target, args.start, args.stop, args.figures_only, args.orbit_animations = "Gault", "2026-08-01", "2027-11-15", True, True
        if args.output == Path("observing_window_output"):
            args.output = Path("Gault")
    if args.target:
        if not args.start or not args.stop:
            parser.error("--target requires --start and --stop")
        label, rows = horizons_api(args.target, args.start, args.stop)
        print(f"Downloaded {len(rows)} daily entries for {label} from JPL Horizons")
        if args.min_visible_hours > 0 or args.plots or args.figures_only:
            _, sun_rows = horizons_api("10", args.start, args.stop)
            sun = {str(row["date"]): row for row in sun_rows}
            for row in rows:
                if str(row["date"]) in sun:
                    row["sun_ra"] = sun[str(row["date"])]["ra"]
                    row["sun_dec"] = sun[str(row["date"])]["dec"]
                    row["visible_hours"] = visible_hours(row, sun[str(row["date"])], args.latitude)
    elif args.input:
        rows = load_horizons(args.input) if args.input.suffix.lower() == ".txt" else load_csv(args.input)
    else:
        parser.error("provide an input file or --target with --start and --stop")
    if args.orbit_animations and not args.target:
        parser.error("--orbit-animations requires --target, --start and --stop")
    if args.sun:
        sun = {str(row["date"]): row for row in load_sun(args.sun)}
        for row in rows:
            if str(row["date"]) in sun:
                solar = sun[str(row["date"])]
                row["sun_ra"] = solar["ra"]
                row["sun_dec"] = solar["dec"]
                row["visible_hours"] = visible_hours(row, solar, args.latitude)
    write_outputs(rows, args)
    if args.orbit_animations:
        _, target_vectors = horizons_vectors_api(args.target, args.start, args.stop)
        _, earth_vectors = horizons_vectors_api("399", args.start, args.stop)
        write_orbit_products(rows, target_vectors, earth_vectors, args.output)
        print(args.output / "07_heliocentric_orbits.png")
        print(args.output / "08_heliocentric_orbit_2d.gif")
        print(args.output / "09_heliocentric_orbit_3d.gif")


if __name__ == "__main__":
    main()
