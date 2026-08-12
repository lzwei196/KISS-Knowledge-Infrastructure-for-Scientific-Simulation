#!/usr/bin/env python3
"""
parse_noahmp_output.py — Stage s7: Noah-MP Output Parser

Extracts variables from Noah-MP HRLDAS LDASOUT NetCDF files and converts
to CSV timeseries for analysis and validation.

LDASOUT file naming: YYYYMMDDHH00.LDASOUT_DOMAIN1

Key output variables:
  TSLB(ns,y,x)      — Soil temperature [K] per layer
  SMOIS(ns,y,x)     — Volumetric soil moisture [m³/m³] per layer
  SH2O(ns,y,x)      — Liquid soil moisture [m³/m³] per layer
  SNOW(y,x)          — Snow water equivalent [mm]
  SNOWH(y,x)         — Snow depth [m]
  TSK(y,x)           — Skin temperature [K]
  HFX(y,x)           — Sensible heat flux [W/m²]
  LH(y,x)            — Latent heat flux [W/m²]
  GRDFLX(y,x)        — Ground heat flux [W/m²]
  SFCRUNOFF(y,x)     — Accumulated surface runoff [m]
  UDRUNOFF(y,x)      — Accumulated subsurface runoff [m]
  ALBEDO(y,x)        — Surface albedo [-]
  EMISS(y,x)         — Surface emissivity [-]
  ACSNOM(y,x)        — Accumulated snowmelt [mm]
  LAI(y,x)           — Leaf area index [m²/m²]

Pattern: validate_inputs → process → validate_outputs
"""

import os
import sys
import json
import argparse
import glob
import re
import numpy as np
from datetime import datetime

try:
    import netCDF4 as nc
except ImportError:
    nc = None

try:
    import pandas as pd
except ImportError:
    pd = None

# Default variables to extract
# NOTE: Noah-MP v5.2 HRLDAS LDASOUT names surface/underground runoff
# SFCRNOFF / UGDRNOFF (units: mm, accumulated). Older/other drivers used
# SFCRUNOFF / UDRUNOFF (units: m). Both spellings are resolved below.
DEFAULT_VARS = [
    "TSK", "SMOIS", "TSLB", "SH2O", "SNOW", "SNOWH", "SNEQV",
    "HFX", "LH", "GRDFLX", "SFCRNOFF", "UGDRNOFF",
    "ALBEDO", "EMISS", "LAI"
]

# Runoff variable name aliases (v5.2 first, then legacy) and their unit -> mm scale.
SFC_RUNOFF_ALIASES = ["SFCRNOFF", "SFCRUNOFF"]
SUB_RUNOFF_ALIASES = ["UGDRNOFF", "UDRUNOFF"]


def resolve_runoff(ds, aliases):
    """Return (varname, scale_to_mm) for the first matching runoff alias.

    v5.2 emits these already in mm; legacy drivers emit meters. Decide the
    scale from the variable's ``units`` attribute rather than assuming.
    """
    for name in aliases:
        if name in ds.variables:
            units = getattr(ds.variables[name], "units", "").strip().lower()
            scale = 1000.0 if units in ("m", "meter", "meters") else 1.0
            return name, scale
    return None, 1.0

# Variable metadata for unit labeling
VAR_META = {
    "TSK":       {"unit": "K",     "desc": "Skin temperature"},
    "SMOIS":     {"unit": "m3/m3", "desc": "Volumetric soil moisture"},
    "TSLB":      {"unit": "K",     "desc": "Soil temperature"},
    "SH2O":      {"unit": "m3/m3", "desc": "Liquid soil moisture"},
    "SNOW":      {"unit": "mm",    "desc": "Snow water equivalent"},
    "SNOWH":     {"unit": "m",     "desc": "Snow depth"},
    "HFX":       {"unit": "W/m2",  "desc": "Sensible heat flux"},
    "LH":        {"unit": "W/m2",  "desc": "Latent heat flux"},
    "GRDFLX":    {"unit": "W/m2",  "desc": "Ground heat flux"},
    "SFCRUNOFF": {"unit": "m",     "desc": "Accumulated surface runoff"},
    "UDRUNOFF":  {"unit": "m",     "desc": "Accumulated subsurface runoff"},
    "SFCRNOFF":  {"unit": "mm",    "desc": "Accumulated surface runoff (v5.2)"},
    "UGDRNOFF":  {"unit": "mm",    "desc": "Accumulated underground runoff (v5.2)"},
    "SNEQV":     {"unit": "mm",    "desc": "Snow water equivalent (v5.2)"},
    "ALBEDO":    {"unit": "-",     "desc": "Surface albedo"},
    "EMISS":     {"unit": "-",     "desc": "Surface emissivity"},
    "LAI":       {"unit": "m2/m2", "desc": "Leaf area index"},
    "ACSNOM":    {"unit": "mm",    "desc": "Accumulated snowmelt"},
    "ACSNOW":    {"unit": "mm",    "desc": "Accumulated snowfall"},
}


def validate_inputs(args):
    """Validate input arguments."""
    errors = []

    if not os.path.isdir(args.output_dir):
        errors.append(f"Output directory not found: {args.output_dir}")

    ldasout = glob.glob(os.path.join(args.output_dir, "*LDASOUT*"))
    if len(ldasout) == 0:
        errors.append(f"No LDASOUT files found in {args.output_dir}")

    if nc is None:
        errors.append("netCDF4 package required. Install: pip install netCDF4")
    if pd is None:
        errors.append("pandas package required. Install: pip install pandas")

    if errors:
        print("INPUT VALIDATION FAILED:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(1)

    return sorted(ldasout)


def parse_timestamp_from_filename(fname):
    """Extract datetime from LDASOUT filename: YYYYMMDDHH00.LDASOUT_DOMAIN1"""
    base = os.path.basename(fname)
    m = re.match(r'(\d{10})\d*\.LDASOUT', base)
    if m:
        return datetime.strptime(m.group(1), "%Y%m%d%H")
    # Try alternative format
    m = re.match(r'(\d{4})-(\d{2})-(\d{2})_(\d{2})', base)
    if m:
        return datetime(int(m.group(1)), int(m.group(2)),
                        int(m.group(3)), int(m.group(4)))
    return None


# HRLDAS fill value written before the first physics step has run, and for
# skipped (water / sea-ice) cells.  It is NOT flagged with a _FillValue
# attribute, so a naive read folds -9999 straight into means/increments.
LDASOUT_FILL = -9990.0

# Layer/level dimension names in LDASOUT.
_LAYER_DIMS = ("soil_layers_stag", "snow_layers", "rad_num")


def _is_fill(v):
    return (v is None) or (not np.isfinite(v)) or (v <= LDASOUT_FILL)


def extract_point(ds, varname, ix=0, iy=0):
    """Extract a variable value at grid point (ix, iy).

    Dimension order is read from the variable's OWN dimension names, not from
    positional assumptions.  HRLDAS writes layered LDASOUT fields as
    ``(Time, south_north, soil_layers_stag, west_east)`` -- the layer axis sits
    BETWEEN the two horizontal axes, not before them.  The previous positional
    code did ``var[0, k, iy, ix]`` with ``k`` over ``shape[1]``, i.e. it walked
    the south_north axis and read the layer axis with ``iy``: on a 1x1 column it
    silently returned layer 1 only (layers 2..N vanished), and on a real 2-D
    domain it returned scrambled layer/row values.  SOIL_M / SOIL_T / SOIL_W are
    dag validation outputs, so this was a silent wrong-answer path.

    Fill values (-9999, e.g. the t=0 record) return None so the caller records a
    gap instead of a number.
    """
    if varname not in ds.variables:
        return None

    var = ds.variables[varname]
    dims = list(var.dimensions) if hasattr(var, "dimensions") else []

    try:
        if len(dims) == var.ndim and dims:
            idx = []
            layer_axis = None
            for a, dname in enumerate(dims):
                dl = dname.lower()
                if dl == "time":
                    idx.append(0)
                elif dl in ("south_north", "south_north_stag", "y", "lat"):
                    idx.append(iy)
                elif dl in ("west_east", "west_east_stag", "x", "lon"):
                    idx.append(ix)
                elif dl in _LAYER_DIMS or "layer" in dl or "level" in dl:
                    layer_axis = a
                    idx.append(slice(None))
                else:
                    idx.append(0)
            arr = np.asarray(var[tuple(idx)], dtype=float).ravel()
            if layer_axis is None:
                v = float(arr[0])
                return None if _is_fill(v) else v
            out = [None if _is_fill(float(v)) else float(v) for v in arr]
            return None if all(o is None for o in out) else out

        # Fallback: no usable dimension names.
        ndim = var.ndim
        if ndim == 2:
            v = float(var[iy, ix])
        elif ndim == 3 and var.shape[0] == 1:
            v = float(var[0, iy, ix])
        elif ndim == 3:
            out = [float(var[k, iy, ix]) for k in range(var.shape[0])]
            return [None if _is_fill(o) else o for o in out]
        else:
            v = float(np.asarray(var[:]).ravel()[0])
        return None if _is_fill(v) else v
    except Exception:
        return None


def compute_runoff_increment(current, previous):
    """Compute runoff increment from accumulated values."""
    if current is None or previous is None:
        return None
    inc = current - previous
    return max(0.0, inc)  # Runoff can only be positive


def process(ldasout_files, variables, ix=0, iy=0):
    """Process all LDASOUT files and extract timeseries."""
    records = []
    prev_sfcrunoff = None
    prev_udrunoff = None

    for i, fpath in enumerate(ldasout_files):
        ts = parse_timestamp_from_filename(fpath)
        if ts is None:
            continue

        record = {"datetime": ts.strftime("%Y-%m-%d %H:%M:%S")}

        try:
            with nc.Dataset(fpath, 'r') as ds:
                for varname in variables:
                    val = extract_point(ds, varname, ix, iy)
                    if val is None:
                        continue

                    if isinstance(val, list):
                        # Multi-layer variable
                        for k, v in enumerate(val):
                            record[f"{varname}_L{k+1}"] = v
                    else:
                        record[varname] = val

                # Compute incremental runoff. Resolve the actual variable
                # names (v5.2 SFCRNOFF/UGDRNOFF vs legacy SFCRUNOFF/UDRUNOFF)
                # and scale to mm using each variable's declared units.
                sfc_name, sfc_scale = resolve_runoff(ds, SFC_RUNOFF_ALIASES)
                sub_name, sub_scale = resolve_runoff(ds, SUB_RUNOFF_ALIASES)
                sfcrunoff = extract_point(ds, sfc_name, ix, iy) if sfc_name else None
                udrunoff = extract_point(ds, sub_name, ix, iy) if sub_name else None

                if sfcrunoff is not None and prev_sfcrunoff is not None:
                    record["SFCRUNOFF_INC_mm"] = compute_runoff_increment(
                        sfcrunoff, prev_sfcrunoff) * sfc_scale
                if udrunoff is not None and prev_udrunoff is not None:
                    record["UDRUNOFF_INC_mm"] = compute_runoff_increment(
                        udrunoff, prev_udrunoff) * sub_scale

                prev_sfcrunoff = sfcrunoff
                prev_udrunoff = udrunoff

        except Exception as e:
            print(f"  WARNING: Failed to read {fpath}: {e}")
            continue

        records.append(record)

        if (i + 1) % 100 == 0:
            print(f"  Processed {i+1}/{len(ldasout_files)} files...")

    return records


def compute_statistics(df):
    """Compute summary statistics from the timeseries DataFrame."""
    stats = {}
    for col in df.columns:
        if col == "datetime":
            continue
        vals = df[col].dropna()
        if len(vals) == 0:
            continue
        stats[col] = {
            "mean": float(vals.mean()),
            "min": float(vals.min()),
            "max": float(vals.max()),
            "std": float(vals.std()),
            "n": int(len(vals)),
        }

    # Domain-specific derived metrics
    if "TSK" in df.columns:
        tsk = df["TSK"].dropna()
        stats["TSK"]["mean_celsius"] = float(tsk.mean() - 273.15)
        stats["TSK"]["range_celsius"] = float(tsk.max() - tsk.min())

    if "SFCRUNOFF_INC_mm" in df.columns and "UDRUNOFF_INC_mm" in df.columns:
        total_sfc = df["SFCRUNOFF_INC_mm"].sum()
        total_sub = df["UDRUNOFF_INC_mm"].sum()
        stats["total_runoff"] = {
            "surface_mm": float(total_sfc),
            "subsurface_mm": float(total_sub),
            "total_mm": float(total_sfc + total_sub),
            "baseflow_ratio": float(total_sub / max(total_sfc + total_sub, 1e-10)),
        }

    if "SNOW" in df.columns:
        snow = df["SNOW"].dropna()
        stats["snow_summary"] = {
            "max_swe_mm": float(snow.max()),
            "mean_swe_mm": float(snow.mean()),
            "snow_days": int((snow > 1.0).sum()),
        }

    if "LH" in df.columns:
        lh = df["LH"].dropna()
        # Approximate ET: LH / Lv (2.5e6 J/kg) * 3600 s/hr -> mm/hr
        et_mmhr = lh / 2.5e6 * 3600
        stats["et_summary"] = {
            "mean_lh_wm2": float(lh.mean()),
            "mean_et_mm_hr": float(et_mmhr.mean()),
        }

    return stats


def validate_outputs(df, stats):
    """Validate output data is physically reasonable."""
    warnings = []

    if "TSK" in df.columns:
        tsk = df["TSK"].dropna()
        if tsk.min() < 180:
            warnings.append(f"TSK min={tsk.min():.1f} K — likely wrong temperature units")
        if tsk.max() > 350:
            warnings.append(f"TSK max={tsk.max():.1f} K — unrealistically high")

    if "SMOIS_L1" in df.columns:
        sm = df["SMOIS_L1"].dropna()
        if sm.max() > 0.6:
            warnings.append(f"SMOIS L1 max={sm.max():.3f} — exceeds typical porosity")
        if sm.min() < 0:
            warnings.append(f"SMOIS L1 min={sm.min():.3f} — negative soil moisture")

    if "HFX" in df.columns:
        hfx = df["HFX"].dropna()
        if abs(hfx.mean()) > 200:
            warnings.append(f"HFX mean={hfx.mean():.1f} W/m² — unusually large")

    if "LH" in df.columns:
        lh = df["LH"].dropna()
        if lh.mean() < -10:
            warnings.append(f"LH mean={lh.mean():.1f} W/m² — negative (condensation dominant)")

    if len(df) < 10:
        warnings.append(f"Only {len(df)} timesteps in output — very short simulation")

    return warnings


def main():
    parser = argparse.ArgumentParser(
        description="Parse Noah-MP LDASOUT files to CSV timeseries"
    )
    parser.add_argument("--output_dir", required=True,
                        help="Directory containing LDASOUT files")
    parser.add_argument("--variables", default=",".join(DEFAULT_VARS),
                        help="Comma-separated variable names to extract")
    parser.add_argument("--output", required=True,
                        help="Output CSV file path")
    parser.add_argument("--ix", type=int, default=0, help="Grid X index (default: 0)")
    parser.add_argument("--iy", type=int, default=0, help="Grid Y index (default: 0)")
    parser.add_argument("--stats_json", default=None,
                        help="Output statistics JSON file path")

    args = parser.parse_args()

    print("=" * 60)
    print("Noah-MP Output Parser")
    print("=" * 60)

    # Validate
    ldasout_files = validate_inputs(args)
    variables = [v.strip() for v in args.variables.split(",")]

    print(f"  Found {len(ldasout_files)} LDASOUT files")
    print(f"  Variables: {variables}")
    print(f"  Grid point: ({args.ix}, {args.iy})")

    # Process
    records = process(ldasout_files, variables, args.ix, args.iy)
    if not records:
        print("ERROR: No data extracted", file=sys.stderr)
        sys.exit(1)

    df = pd.DataFrame(records)
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.sort_values("datetime").reset_index(drop=True)

    print(f"  Extracted {len(df)} timesteps, {len(df.columns)} columns")
    print(f"  Period: {df['datetime'].iloc[0]} to {df['datetime'].iloc[-1]}")

    # Statistics
    stats = compute_statistics(df)

    # Validate
    warnings = validate_outputs(df, stats)
    for w in warnings:
        print(f"  WARNING: {w}")

    # Write CSV
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    df.to_csv(args.output, index=False)
    print(f"\n  CSV written to {args.output}")

    # Write stats JSON
    if args.stats_json:
        stats["n_timesteps"] = len(df)
        stats["period_start"] = str(df["datetime"].iloc[0])
        stats["period_end"] = str(df["datetime"].iloc[-1])
        stats["n_warnings"] = len(warnings)
        stats["warnings"] = warnings

        with open(args.stats_json, 'w') as f:
            json.dump(stats, f, indent=2, default=str)
        print(f"  Stats written to {args.stats_json}")

    print(f"\n  Validation: {'PASSED' if not warnings else f'{len(warnings)} warnings'}")

    # Print summary
    print("\n--- Summary Statistics ---")
    for var, s in stats.items():
        if isinstance(s, dict) and "mean" in s:
            meta = VAR_META.get(var, {})
            unit = meta.get("unit", "")
            print(f"  {var}: mean={s['mean']:.4f} [{s['min']:.4f}, {s['max']:.4f}] {unit}")


if __name__ == "__main__":
    main()
