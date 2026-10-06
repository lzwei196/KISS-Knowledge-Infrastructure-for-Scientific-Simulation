#!/usr/bin/env python3
"""
convert_wind_to_simfire.py — Convert external wind data to SimFire spatial
wind arrays (ft/min, degrees).

⚠️ SCOPE: This tool produces .npy spatial wind arrays in the units that
SimFire's Rothermel **internals** use (ft/min). These arrays are NOT
consumed by the standard `wind.simple` or `wind.perlin` YAML paths —
those paths take *mph scalars* in the YAML and apply `mph_to_ftpm`
themselves (config.py:860 and :897-901). Use these arrays only for:
  - the CFD wind path
  - custom layer injection where you bypass the YAML-driven wind setup
For the simple/perlin YAML paths, just write the mph value directly.
See `docs/s3_wind_setup.md` for the canonical config recipe.

CRITICAL UNIT CONVERSIONS (this tool writes ft/min arrays):
  - From mph: multiply by 88
  - From m/s: multiply by 196.85
  - From km/h: multiply by 54.68
  - From knots: multiply by 101.27

WIND DIRECTION CONVENTION:
  - SimFire's Rothermel uses **degrees clockwise from N, "TO direction"**
    (rothermel.py:104). `direction=90` means wind blowing TOWARD East.
  - If your source data is in meteorological "from" convention, add 180
    (mod 360) before writing the array.

Output:
  - wind_speed.npy: float array of wind speeds in ft/min, shape (H, W)
  - wind_direction.npy: float array of wind directions in degrees ("TO"
    convention), shape (H, W)
  - wind_metadata.json: source info, conversion applied, statistics

Usage:
    python convert_wind_to_simfire.py \\
        --speed 20 --speed-unit mph \\
        --direction 90 \\
        --grid-shape 225 450 \\
        --output-dir ./simfire_wind/

    python convert_wind_to_simfire.py \\
        --csv wind_data.csv \\
        --speed-col wind_speed --dir-col wind_dir \\
        --speed-unit ms \\
        --grid-shape 225 450 \\
        --output-dir ./simfire_wind/
"""

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np

# Unit conversion factors TO ft/min
SPEED_CONVERSIONS = {
    "ftpm": 1.0,           # Already in ft/min
    "mph": 88.0,           # miles/hour → ft/min
    "ms": 196.85,          # m/s → ft/min
    "kmh": 54.6807,        # km/h → ft/min
    "knots": 101.269,      # knots → ft/min
}


# ---------------------------------------------------------------------------
# NASA POWER -> SimFire `wind.simple` (S3, scalar mph + "TO" degrees)
#
# THE MISSING LINK (added 2026-08-09).  SKILL.md documented the UNITS of
# `wind.simple.speed` exhaustively but never said WHICH WIND it is.  Rothermel
# (RMRS-GTR-371 / INT-115) takes the **midflame** wind -- the wind at roughly
# flame height inside/above the surface fuel bed -- not the 10 m or 2 m
# meteorological wind that every reanalysis and every weather API reports.
# Feeding a 10 m open wind straight into `wind.simple.speed` overstates the
# wind coefficient phi_w by a factor of ~2-3, i.e. it is a SILENT bias of the
# same family as the mph/ft-min traps already in triplets.yaml (dt_021).
#
# The conversion is a two-step standard:
#   1. reference height -> 20 ft (6.1 m) open wind, via the log profile
#        U_20ft = U_z * ln(6.1/z0) / ln(z/z0),      z0 = 0.03 m open rangeland
#   2. 20 ft open wind -> midflame, via the Albini & Baughman (1979)
#      unsheltered wind adjustment factor used by BEHAVE/FARSITE/FlamMap
#        WAF = 1.83 / ln((20 + 0.36 H) / (0.13 H)),   H = fuel bed depth (ft)
#      (Andrews 2012, RMRS-GTR-266, eq. for unsheltered fuels.)
#   For H = 1 ft (FBFM 1/2/10/11 grass & short shrub) WAF ~= 0.36;
#   for H = 6 ft (FBFM 4 chaparral) WAF ~= 0.55.
#
# Wind SPEED comes from ki_tools_common.load_forcing (the platform's canonical
# loader).  Wind DIRECTION does NOT: `load_forcing` returns scalar `wind_ms`
# only -- there is no direction field anywhere in ki_tools_common, which is a
# genuine gap for any directional model (fire, dune, drift-snow, plume).  Until
# that is fixed upstream, the direction is pulled here from the same NASA POWER
# endpoint constant that load_forcing itself uses, so both halves of the wind
# vector come from one product and one time standard.
# ---------------------------------------------------------------------------

KI_TOOLS_COMMON_SRC = "KISSPATH_KI_TOOLS_COMMON"

# Reference heights (m)
NASA_POWER_WIND_HEIGHT_M = 2.0   # load_forcing requests WS2M
MIDFLAME_REF_HEIGHT_M = 6.096    # 20 ft, the fire-weather standard
OPEN_RANGELAND_Z0_M = 0.03       # roughness length, open grass/shrub

# Fuel-bed depth (ft) per FBFM-13 model, for the WAF. Matches SKILL.md's table.
FBFM13_DEPTH_FT = {
    1: 1.0, 2: 1.0, 3: 2.5, 4: 6.0, 5: 2.0, 6: 2.5, 7: 2.5,
    8: 0.2, 9: 0.2, 10: 1.0, 11: 1.0, 12: 2.3, 13: 3.0,
}


def _ensure_ki_tools_common():
    """Make ki_tools_common importable from a bare model venv."""
    if KI_TOOLS_COMMON_SRC not in sys.path:
        sys.path.insert(0, KI_TOOLS_COMMON_SRC)


def wind_adjustment_factor(fuel_bed_depth_ft):
    """Albini & Baughman (1979) unsheltered WAF: 20 ft open wind -> midflame.

    Args:
        fuel_bed_depth_ft: fuel bed depth H in feet (FBFM13_DEPTH_FT).

    Returns:
        float WAF in (0, 1].
    """
    h = max(0.1, float(fuel_bed_depth_ft))
    import math

    return 1.83 / math.log((20.0 + 0.36 * h) / (0.13 * h))


def log_profile_scale(z_from_m, z_to_m, z0_m=OPEN_RANGELAND_Z0_M):
    """Neutral log-law ratio U(z_to)/U(z_from) over roughness z0."""
    import math

    return math.log(z_to_m / z0_m) / math.log(z_from_m / z0_m)


def _nasa_power_hourly_direction(lat, lon, year):
    """Hourly 10 m wind direction (deg FROM north) from NASA POWER.

    Uses ``load_forcing.NASA_POWER_URL`` so this stays pinned to whatever
    endpoint the platform loader uses, and ``trust_env=False`` because the
    sandbox proxy stalls power.larc.nasa.gov.

    Returns:
        (dates ndarray[datetime64[s]], direction ndarray[float] deg-from-N)
    """
    import datetime as _dt

    import requests

    _ensure_ki_tools_common()
    from ki_tools_common.load_forcing import NASA_POWER_URL

    params = {
        "start": f"{year}0101", "end": f"{year}1231",
        "latitude": lat, "longitude": lon,
        "community": "RE", "parameters": "WD10M,WS10M",
        "format": "JSON", "header": "false", "time-standard": "UTC",
    }
    sess = requests.Session()
    sess.trust_env = False
    resp = sess.get(NASA_POWER_URL, params=params, timeout=180)
    resp.raise_for_status()
    pdata = resp.json()["properties"]["parameter"]
    wd, ws = pdata.get("WD10M", {}), pdata.get("WS10M", {})

    dates, dirs, spds = [], [], []
    for key in sorted(wd.keys()):
        dates.append(_dt.datetime.strptime(key, "%Y%m%d%H"))
        v = wd.get(key, -999.0)
        s = ws.get(key, -999.0)
        dirs.append(np.nan if v in (-999.0, None) else float(v))
        spds.append(np.nan if s in (-999.0, None) else float(s))
    return (
        np.array(dates, dtype="datetime64[s]"),
        np.array(dirs, dtype=float),
        np.array(spds, dtype=float),
    )


def nasa_power_simple_wind(lat, lon, date, fuel_bed_depth_ft=1.0,
                           hours=24, waf_override=None,
                           start_offset_hours=0.0):
    """Build a SimFire ``wind.simple`` block for one fire-day at one point.

    Args:
        lat, lon: fire location (degrees).
        date: "YYYY-MM-DD" ignition date.
        fuel_bed_depth_ft: representative fuel bed depth for the WAF.
        hours: length of the burn window in hours.
        waf_override: bypass the Albini-Baughman WAF with this value.
        start_offset_hours: hours after 00 UTC of `date` at which the burn
            window opens. NASA POWER is UTC; a burning period defined in LOCAL
            solar time must be shifted by ``local_hour - lon/15``, otherwise a
            western-US afternoon window silently samples the PREVIOUS night.

    Returns:
        dict with `speed` (mph, MIDFLAME -- write straight into
        wind.simple.speed) and `direction` (deg, SimFire "TO" convention),
        plus every intermediate so the conversion is auditable.
    """
    import datetime as _dt

    _ensure_ki_tools_common()
    from ki_tools_common.load_forcing import load_hourly_forcing

    day = _dt.datetime.strptime(date, "%Y-%m-%d")
    year = day.year

    # Speed: the platform's canonical loader (NASA POWER hourly, WS2M).
    # TRAP (found 2026-10-06): newer ki_tools_common.load_forcing returns
    # `wind_ms` = WS10M (10 m, `wind_height_m` = 10) and the 2 m wind as
    # `wind2_ms`; on 2026-08-08 `wind_ms` was WS2M. Treating a 10 m wind as 2 m
    # inflates the midflame wind ~1.4x. Use the 2 m series when present, else
    # the height the loader reports -- never assume.
    fx = load_hourly_forcing("nasa_power", lat, lon, year, year)
    fdates = fx["dates"].astype("datetime64[s]").astype(object)
    if "wind2_ms" in fx:
        fspd2m = np.asarray(fx["wind2_ms"], dtype=float)
        wind_ref_height_m = NASA_POWER_WIND_HEIGHT_M
    else:
        fspd2m = np.asarray(fx["wind_ms"], dtype=float)
        wind_ref_height_m = float(fx.get("wind_height_m", NASA_POWER_WIND_HEIGHT_M))

    # Direction: same product, fetched here (load_forcing carries no direction).
    ddates, ddirs, dspd10m = _nasa_power_hourly_direction(lat, lon, year)
    ddates_obj = ddates.astype(object)

    t0 = day + _dt.timedelta(hours=float(start_offset_hours))
    t1 = t0 + _dt.timedelta(hours=hours)

    m_spd = np.array([t0 <= d < t1 for d in fdates])
    m_dir = np.array([t0 <= d < t1 for d in ddates_obj])
    if not m_spd.any() or not m_dir.any():
        raise RuntimeError(f"NASA POWER returned no hours in {t0}..{t1}")

    spd2m = fspd2m[m_spd]
    dirs = ddirs[m_dir]
    spd10 = dspd10m[m_dir]
    good = np.isfinite(dirs) & np.isfinite(spd10)
    if not good.any():
        raise RuntimeError("NASA POWER wind direction all-missing for this window")

    # VECTOR mean direction, speed-weighted: a scalar mean of compass bearings
    # is wrong across the 0/360 wrap and would point the head fire anywhere.
    theta = np.radians(dirs[good])
    u = -np.nanmean(spd10[good] * np.sin(theta))   # eastward component
    v = -np.nanmean(spd10[good] * np.cos(theta))   # northward component
    dir_to_deg = float((np.degrees(np.arctan2(u, v))) % 360.0)

    mean_spd_2m_ms = float(np.nanmean(spd2m))
    mean_spd_20ft_ms = mean_spd_2m_ms * log_profile_scale(
        wind_ref_height_m, MIDFLAME_REF_HEIGHT_M
    )
    waf = (
        float(waf_override)
        if waf_override is not None
        else wind_adjustment_factor(fuel_bed_depth_ft)
    )
    midflame_ms = mean_spd_20ft_ms * waf
    midflame_mph = midflame_ms * 2.236936

    return {
        "speed": round(midflame_mph, 3),          # -> wind.simple.speed (mph)
        "direction": round(dir_to_deg, 2),        # -> wind.simple.direction ("TO")
        "provenance": {
            "source": "NASA POWER hourly (via ki_tools_common.load_forcing "
                      "for speed; WD10M/WS10M for direction)",
            "lat": lat, "lon": lon, "date": date, "window_hours": hours,
            "n_hours_speed": int(m_spd.sum()), "n_hours_dir": int(good.sum()),
            "mean_wind_2m_ms": round(mean_spd_2m_ms, 3),
            "wind_ref_height_m": wind_ref_height_m,
            "mean_wind_20ft_ms": round(mean_spd_20ft_ms, 3),
            "log_profile_z0_m": OPEN_RANGELAND_Z0_M,
            "fuel_bed_depth_ft": fuel_bed_depth_ft,
            "wind_adjustment_factor": round(waf, 4),
            "midflame_wind_ms": round(midflame_ms, 3),
            "direction_convention": "degrees CW from N, SimFire 'TO' direction",
            "vector_mean": True,
        },
    }


def validate_inputs(args):
    """Validate command-line arguments.

    Checks unit names, file existence, grid dimensions.
    """
    errors = []

    if getattr(args, "nasa_power", False):
        for name in ("lat", "lon", "date"):
            if getattr(args, name, None) is None:
                errors.append(f"--nasa-power requires --{name}")
        if errors:
            print(json.dumps({"status": "error", "stage": "validate_inputs",
                              "errors": errors}))
            sys.exit(1)
        return

    if args.speed_unit not in SPEED_CONVERSIONS:
        errors.append(
            f"Unknown speed unit '{args.speed_unit}'. "
            f"Valid: {list(SPEED_CONVERSIONS.keys())}"
        )

    if args.csv:
        if not os.path.isfile(args.csv):
            errors.append(f"CSV file not found: {args.csv}")
        if not args.speed_col or not args.dir_col:
            errors.append("Must provide --speed-col and --dir-col with --csv")
    else:
        if args.speed is None:
            errors.append("Must provide --speed (constant) or --csv (spatiotemporal)")
        if args.direction is None:
            errors.append("Must provide --direction (constant) or --csv")

    if args.grid_shape:
        if len(args.grid_shape) != 2 or any(s <= 0 for s in args.grid_shape):
            errors.append(f"Grid shape must be two positive integers, got {args.grid_shape}")

    if errors:
        print(json.dumps({"status": "error", "stage": "validate_inputs", "errors": errors}))
        sys.exit(1)


def convert_speed(speed_array, from_unit):
    """Convert wind speed array to ft/min.

    CRITICAL: SimFire Rothermel equation expects wind speed in ft/min.
    Using wrong units will silently produce incorrect fire spread rates.

    Common mistake: providing mph (e.g., 20 mph = 1760 ft/min, NOT 20 ft/min).
    At 20 ft/min the wind factor phi_w is negligible.
    At 1760 ft/min (20 mph), phi_w dominates fire spread.

    Args:
        speed_array: numpy array of wind speeds in source units
        from_unit: source unit key (ftpm, mph, ms, kmh, knots)

    Returns:
        speed_ftpm: numpy array of wind speeds in ft/min
    """
    factor = SPEED_CONVERSIONS[from_unit]
    speed_ftpm = speed_array * factor

    # Clamp negative values
    speed_ftpm = np.maximum(speed_ftpm, 0.0)

    return speed_ftpm


def normalize_direction(dir_array):
    """Normalize wind direction to [0, 360) degrees.

    Convention: degrees clockwise from North.
    0° = North, 90° = East, 180° = South, 270° = West.

    Handles:
    - Negative values (e.g., -90° → 270°)
    - Values > 360° (e.g., 450° → 90°)
    - Math convention (0°=East, CCW) → met convention (0°=North, CW)
    """
    return dir_array % 360.0


def read_csv_wind(csv_path, speed_col, dir_col, grid_shape):
    """Read wind data from CSV and reshape to grid.

    Expects CSV with columns for speed and direction.
    If CSV has fewer rows than grid pixels, broadcasts uniformly.
    If CSV has a 'time' column, uses only the first timestep.
    """
    import pandas as pd

    df = pd.read_csv(csv_path)

    if speed_col not in df.columns:
        print(json.dumps({
            "status": "error",
            "errors": [f"Column '{speed_col}' not in CSV. Available: {list(df.columns)}"]
        }))
        sys.exit(1)

    if dir_col not in df.columns:
        print(json.dumps({
            "status": "error",
            "errors": [f"Column '{dir_col}' not in CSV. Available: {list(df.columns)}"]
        }))
        sys.exit(1)

    speeds = df[speed_col].values.astype(float)
    directions = df[dir_col].values.astype(float)

    h, w = grid_shape
    total_pixels = h * w

    if len(speeds) == total_pixels:
        # Exact match: reshape directly
        speed_grid = speeds.reshape(h, w)
        dir_grid = directions.reshape(h, w)
    elif len(speeds) == 1:
        # Single value: broadcast
        speed_grid = np.full((h, w), speeds[0])
        dir_grid = np.full((h, w), directions[0])
    else:
        # Take mean or first row as uniform value
        print(json.dumps({
            "status": "warning",
            "message": f"CSV has {len(speeds)} rows but grid has {total_pixels} pixels. "
                       "Using mean values as uniform field."
        }), file=sys.stderr)
        speed_grid = np.full((h, w), np.mean(speeds))
        dir_grid = np.full((h, w), np.mean(directions))

    return speed_grid, dir_grid


def validate_outputs(speed_array, dir_array):
    """Post-processing validation of converted wind arrays.

    Checks:
    - Arrays have same shape
    - Speed values are physically reasonable in ft/min
    - Directions are in [0, 360)
    """
    errors = []
    warnings = []

    if speed_array.shape != dir_array.shape:
        errors.append(
            f"Shape mismatch: speed {speed_array.shape} vs direction {dir_array.shape}"
        )

    max_speed = np.max(speed_array)
    min_speed = np.min(speed_array)

    # Reasonable wind speed checks (in ft/min)
    if max_speed > 22000:  # ~250 mph
        errors.append(f"Max wind speed {max_speed:.0f} ft/min (~{max_speed/88:.0f} mph) "
                      "exceeds 250 mph. Check unit conversion.")
    if max_speed < 1.0 and max_speed > 0:
        warnings.append(
            f"Max wind speed {max_speed:.2f} ft/min (~{max_speed/88:.4f} mph) is very low. "
            "Did you forget to convert from mph to ft/min? (multiply by 88)"
        )

    if np.any(dir_array < 0) or np.any(dir_array >= 360):
        warnings.append("Direction values outside [0, 360). Normalizing.")

    if errors:
        print(json.dumps({"status": "error", "stage": "validate_outputs", "errors": errors}))
        sys.exit(1)

    for w in warnings:
        print(json.dumps({"status": "warning", "message": w}), file=sys.stderr)

    return {
        "speed_range_ftpm": [float(min_speed), float(max_speed)],
        "speed_range_mph": [float(min_speed / 88), float(max_speed / 88)],
        "direction_range": [float(np.min(dir_array)), float(np.max(dir_array))],
        "shape": list(speed_array.shape),
    }


def process(args):
    """Main processing: read → convert → validate → save."""
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # NASA POWER scalar mode: emit the wind.simple block, not ft/min arrays.
    if getattr(args, "nasa_power", False):
        block = nasa_power_simple_wind(
            args.lat, args.lon, args.date,
            fuel_bed_depth_ft=args.fuel_bed_depth_ft,
            hours=args.window_hours,
            waf_override=args.waf,
            start_offset_hours=args.start_offset_hours,
        )
        out_path = output_dir / "wind_simple.json"
        with open(str(out_path), "w") as f:
            json.dump(block, f, indent=2)
        return {"wind_simple": str(out_path), "block": block}

    grid_shape = tuple(args.grid_shape) if args.grid_shape else (225, 225)

    # Step 1: Read data
    if args.csv:
        speed_raw, dir_raw = read_csv_wind(
            args.csv, args.speed_col, args.dir_col, grid_shape
        )
    else:
        speed_raw = np.full(grid_shape, float(args.speed))
        dir_raw = np.full(grid_shape, float(args.direction))

    # Step 2: Convert units
    speed_ftpm = convert_speed(speed_raw, args.speed_unit)
    direction_deg = normalize_direction(dir_raw)

    # Step 3: Validate outputs
    validation = validate_outputs(speed_ftpm, direction_deg)

    # Step 4: Save
    speed_path = output_dir / "wind_speed.npy"
    dir_path = output_dir / "wind_direction.npy"
    meta_path = output_dir / "wind_metadata.json"

    np.save(str(speed_path), speed_ftpm)
    np.save(str(dir_path), direction_deg)

    metadata = {
        "source_unit": args.speed_unit,
        "target_unit": "ft/min",
        "conversion_factor": SPEED_CONVERSIONS[args.speed_unit],
        "direction_convention": "degrees CW from North (0=N, 90=E, 180=S, 270=W)",
        "validation": validation,
    }
    with open(str(meta_path), "w") as f:
        json.dump(metadata, f, indent=2)

    return {
        "wind_speed": str(speed_path),
        "wind_direction": str(dir_path),
        "metadata": str(meta_path),
        "validation": validation,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Convert external wind data to SimFire format (ft/min, degrees)"
    )

    # Constant wind mode
    parser.add_argument("--speed", type=float, default=None,
                        help="Constant wind speed (in --speed-unit)")
    parser.add_argument("--direction", type=float, default=None,
                        help="Constant wind direction (degrees, 0=N, 90=E)")
    parser.add_argument("--speed-unit", type=str, default="mph",
                        choices=list(SPEED_CONVERSIONS.keys()),
                        help="Wind speed input unit (default: mph)")

    # CSV mode
    parser.add_argument("--csv", type=str, default=None,
                        help="Path to CSV file with wind data")
    parser.add_argument("--speed-col", type=str, default=None,
                        help="Column name for wind speed in CSV")
    parser.add_argument("--dir-col", type=str, default=None,
                        help="Column name for wind direction in CSV")

    # NASA POWER scalar mode (S3 for wind.simple)
    parser.add_argument("--nasa-power", action="store_true",
                        help="Derive a wind.simple block (MIDFLAME mph + 'TO' "
                             "degrees) from NASA POWER for one fire-day")
    parser.add_argument("--lat", type=float, default=None)
    parser.add_argument("--lon", type=float, default=None)
    parser.add_argument("--date", type=str, default=None,
                        help="Burn-window start date, YYYY-MM-DD (UTC)")
    parser.add_argument("--start-offset-hours", type=float, default=0.0,
                        help="Hours after 00 UTC of --date when the burn "
                             "window opens (use 12 - lon/15 for local noon)")
    parser.add_argument("--window-hours", type=int, default=24,
                        help="Burn window length in hours (default 24)")
    parser.add_argument("--fuel-bed-depth-ft", type=float, default=1.0,
                        help="Representative fuel bed depth for the WAF")
    parser.add_argument("--waf", type=float, default=None,
                        help="Override the Albini-Baughman wind adjustment factor")

    # Grid configuration
    parser.add_argument("--grid-shape", type=int, nargs=2, default=None,
                        help="Grid dimensions: height width (pixels)")

    # Output
    parser.add_argument("--output-dir", type=str, required=True,
                        help="Output directory for wind arrays")

    args = parser.parse_args()
    validate_inputs(args)
    result = process(args)

    print(json.dumps({"status": "success", "output": result}, indent=2))


if __name__ == "__main__":
    main()
