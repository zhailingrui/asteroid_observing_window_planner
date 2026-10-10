# Observing-window planner

This package provides the same proposal-window screening in two forms:

- `gault_window.py`: a dependency-free command-line tool that writes a candidate-night CSV and a concise Markdown shortlist.
- `dist/index.html`: a private browser tool. It starts with the Gault ephemeris and can load another compatible CSV locally; no uploaded data leaves the browser.

## Command line

Run from this directory:

```bash
python3 proposal_window_tool/gault_window.py gault_proposal_ephemeris_2026-2028.csv \
  --output observing_window_output
```

To add the seasonal, latitude-only visibility estimate, give the original target and Sun Horizons tables:

```bash
python3 proposal_window_tool/gault_window.py gault_horizons_2026-09-22_2028-04-01.txt \
  --sun sun_horizons_2026-09-22_2028-04-01.txt --latitude -30 \
  --min-visible-hours 2 --output observing_window_output
```

The approximate visibility calculation uses target altitude ≥30° and Sun altitude ≤−18°. It is appropriate for proposal-season planning, not a replacement for a topocentric schedule at a real observatory.

## Browser CSV columns

`date, mag, elong, moon_sep, moon_illum, plane` are required. The included compact export has additional columns such as `ra`, `dec`, and `rate` for display.
