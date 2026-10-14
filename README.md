# Observing-window planner

`gault_window.py` is a local command-line tool. It queries JPL Horizons directly,
then writes a candidate-night CSV, a concise Markdown shortlist, and (optionally)
proposal-style PNG figures.

## Command line

### One-command Gault figures

No ephemeris file or filtering parameters are needed for the standard Gault
figure set:

```bash
.venv/bin/python gault_window.py --gault-figures
```

This queries Gault from 2026-08-01 to 2027-11-15 and writes the PNG files to
`./Gault`, including the 2D and 3D orbit animations. Use `--output another_folder`
to choose another destination.

For a different target or date range, use `--target`, `--start`, `--stop`, and
`--figures-only`. The figure mode queries the Sun automatically and produces:

- `01_brightness_distance.png` — predicted V magnitude and heliocentric/geocentric distance.
- `02_observing_geometry.png` — solar elongation, phase angle, and Moon separation.
- `03_radec_track.png` — sky track with date annotations.
- `04_visibility_latitude.png` — latitude versus nightly dark-time visibility heatmap.
- `05_tracking_plane.png` — sky motion and orbital-plane angle.
- `06_galactic_plane_track.png` — target track in Galactic coordinates, relative to the Galactic plane.

### Heliocentric orbit animations

For any target supplied with `--target`, add `--orbit-animations` to fetch
heliocentric ecliptic vectors for the target and Earth from Horizons. It writes:

- `07_heliocentric_orbits.png` — 2D ecliptic-plane and 3D static overview at the brightest predicted date.
- `08_heliocentric_orbit_2d.gif` — animated top-down and side-on Earth–Sun–target geometry.
- `09_heliocentric_orbit_3d.gif` — fixed-camera 3D animation with the ecliptic plane.

MP4 versions are also written when `ffmpeg` is available. The GIFs use ten-day
frames, so this option takes longer than the standard static figures.

The normal mode writes these figures by default, together with the candidate-night
CSV and report. If you only want the figures and will judge the observing window
yourself, add `--figures-only`. This does not create `candidate_nights.csv` or
`observing_window_report.md`, and the numerical filter options are then ignored.

Add `--min-visible-hours 2 --latitude -30` to filter the shortlist using the
latitude-only seasonal visibility estimate as well.

Run from this directory:

```bash
.venv/bin/python proposal_window_tool/gault_window.py gault_proposal_ephemeris_2026-2028.csv \
  --output observing_window_output
```

To add the seasonal, latitude-only visibility estimate, give the original target and Sun Horizons tables:

```bash
.venv/bin/python proposal_window_tool/gault_window.py gault_horizons_2026-09-22_2028-04-01.txt \
  --sun sun_horizons_2026-09-22_2028-04-01.txt --latitude -30 \
  --min-visible-hours 2 --output observing_window_output
```

The approximate visibility calculation uses target altitude ≥30° and Sun altitude ≤−18°. It is appropriate for proposal-season planning, not a replacement for a topocentric schedule at a real observatory.

## Browser CSV columns

`date, mag, elong, moon_sep, moon_illum, plane` are required. The included compact export has additional columns such as `ra`, `dec`, and `rate` for display.
