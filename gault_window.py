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
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path


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


def write_outputs(rows: list[dict], args: argparse.Namespace) -> None:
    args.output.mkdir(parents=True, exist_ok=True)
    candidates = [row for row in rows if qualifying(row, args)]
    columns = list(FIELDS) + (["visible_hours"] if any("visible_hours" in row for row in rows) else [])
    with (args.output / "candidate_nights.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
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
    print(f"{len(candidates)} candidate nights in {len(groups)} window(s)")
    print(args.output / "candidate_nights.csv")
    print(args.output / "observing_window_report.md")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Compact ephemeris CSV or Horizons target table")
    parser.add_argument("--sun", type=Path, help="Horizons Sun table, required for visibility calculation")
    parser.add_argument("--latitude", type=float, default=-30, help="Observatory latitude in degrees (default: -30)")
    parser.add_argument("--min-visible-hours", type=float, default=0, help="Minimum approximate nightly visibility")
    parser.add_argument("--max-mag", type=float, default=17.5)
    parser.add_argument("--min-elongation", type=float, default=120)
    parser.add_argument("--min-moon-separation", type=float, default=45)
    parser.add_argument("--max-moon-illumination", type=float, default=60)
    parser.add_argument("--max-plane-angle", type=float, default=2)
    parser.add_argument("--output", type=Path, default=Path("observing_window_output"))
    args = parser.parse_args()
    rows = load_horizons(args.input) if args.input.suffix.lower() == ".txt" else load_csv(args.input)
    if args.sun:
        sun = {str(row["date"]): row for row in load_sun(args.sun)}
        for row in rows:
            if str(row["date"]) in sun: row["visible_hours"] = visible_hours(row, sun[str(row["date"])], args.latitude)
    write_outputs(rows, args)


if __name__ == "__main__":
    main()
