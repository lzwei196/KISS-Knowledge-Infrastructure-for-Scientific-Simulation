#!/usr/bin/env python3
"""
convert_forcing.py — Convert forcing data to SuperflexPy input format.

Reads CSV/space-separated forcing files (precipitation, PET, temperature)
and outputs numpy-compatible arrays in mm/d with unit validation.

Supports common global datasets (ERA5, GSWP3, station data) and converts
units automatically. Outputs JSON with arrays or saves .npy files.

Two input formats:
  --format text     (default) column-oriented CSV / space-separated text
  --format caravan  a Caravan / GRDC-Caravan per-gauge netCDF file, which already
                    carries basin-averaged ERA5-Land forcing AND the gauge's
                    observed streamflow on the same daily axis.

Usage:
    python convert_forcing.py --input forcing.csv --output forcing.json
    python convert_forcing.py --input forcing.csv --output forcing.json --p-col 6 --pet-col 7 --q-col 8
    python convert_forcing.py --input forcing.csv --output forcing.json --p-unit mm/h --pet-unit mm/month --timestep 1.0
    python convert_forcing.py --format caravan --input GRDC_6503201.nc \
        --start 1979-01-01 --end 1990-12-31 --area 1517.1 --output forcing.json
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np

# Unit conversion factors to mm/d
PRECIP_CONVERSIONS = {
    "mm/d": 1.0,
    "mm/day": 1.0,
    "mm/h": 24.0,
    "mm/hr": 24.0,
    "mm/month": 1.0 / 30.4375,
    "m/d": 1000.0,
    "m/day": 1000.0,
    "m/s": 86400000.0,
    "kg/m2/s": 86400.0,
    "in/d": 25.4,
    "in/day": 25.4,
}

PET_CONVERSIONS = {
    "mm/d": 1.0,
    "mm/day": 1.0,
    "mm/h": 24.0,
    "mm/hr": 24.0,
    "mm/month": 1.0 / 30.4375,
    "W/m2": 0.0353,  # approx: 1 W/m2 ~ 0.0353 mm/d latent heat
    "MJ/m2/d": 0.408,  # Penman conversion
    "m/d": 1000.0,
}

Q_CONVERSIONS = {
    "mm/d": 1.0,
    "mm/day": 1.0,
    "m3/s": None,  # Requires catchment area
    "cms": None,
    "l/s": None,
}

# ---------------------------------------------------------------------------
# Caravan / GRDC-Caravan per-gauge netCDF contract.
#
# TRAP (verified 2026-08-21 on GRDC-Caravan-extension-nc): the per-gauge netCDF
# files carry NO `units` attribute on ANY variable. The file-level `Units`
# global attribute documents the ERA5-Land meteorology but says NOTHING about
# `streamflow`. Do not guess m3/s: Caravan distributes `streamflow` already
# converted to BASIN-AVERAGED mm/day, i.e. the same unit as SuperflexPy's
# Q_sim, so NO area conversion is needed (and applying one is a silent
# area-squared error). Verified against GRDC_1159100 (Orange R. at Vioolsdrif,
# 786,038 km2): mean 0.0248 mm/d -> 225 m3/s, matching the published GRDC mean.
#
# `potential_evaporation_sum` is ALREADY sign-flipped to positive demand by the
# Caravan producers (raw ERA5-Land potential_evaporation is negative-downward).
# Verified: min 1.77, max 14.87 mm/d. If a future Caravan release ships it
# negative, --pet-sign flip is the lever; the reader hard-fails on all-negative
# PET rather than silently running a model with zero evaporative demand.
# ---------------------------------------------------------------------------
CARAVAN_VARS = {
    "P": "total_precipitation_sum",     # mm/d, basin mean
    "PET": "potential_evaporation_sum",  # mm/d, basin mean, positive = demand
    "Q": "streamflow",                   # mm/d, basin-averaged  <-- NOT m3/s
    "T": "temperature_2m_mean",          # degC
}
CARAVAN_TIME_DIM = "date"


def validate_inputs(args):
    """Validate command-line arguments and input file."""
    errors = []

    input_path = Path(args.input)
    if not input_path.exists():
        errors.append(f"Input file not found: {args.input}")
    if args.format == "caravan":
        if input_path.suffix not in (".nc", ".nc4", ".netcdf"):
            errors.append(
                f"--format caravan expects a netCDF file, got {input_path.suffix}. "
                "Expected .nc, .nc4, or .netcdf"
            )
    elif not input_path.suffix in (".csv", ".dat", ".txt", ".tsv"):
        errors.append(
            f"Unsupported file format: {input_path.suffix}. "
            "Expected .csv, .dat, .txt, or .tsv"
        )

    if args.p_unit not in PRECIP_CONVERSIONS:
        errors.append(
            f"Unknown precipitation unit: {args.p_unit}. "
            f"Supported: {list(PRECIP_CONVERSIONS.keys())}"
        )

    if args.pet_unit not in PET_CONVERSIONS:
        errors.append(
            f"Unknown PET unit: {args.pet_unit}. "
            f"Supported: {list(PET_CONVERSIONS.keys())}"
        )

    if args.timestep <= 0:
        errors.append(f"Timestep must be positive, got {args.timestep}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)


def _open_any_netcdf(path):
    """Open a netCDF file, trying every engine this machine actually has.

    TRAP (verified 2026-08-21): the shared HydroCraft python_env ships
    netCDF4 1.7.4 / HDF5 1.14.6, which raises
    `OSError: [Errno -101] NetCDF: HDF error` on every Caravan .nc file.
    The SuperflexPy work venv's netCDF4 reads them fine. Rather than pin an
    interpreter, try engines in order and report ALL failures if none works.
    """
    import xarray as xr

    errors = []
    for engine in ("netcdf4", "h5netcdf", None):
        try:
            if engine is None:
                return xr.open_dataset(path)
            return xr.open_dataset(path, engine=engine)
        except Exception as exc:  # noqa: BLE001 - we want the full engine report
            errors.append(f"{engine or 'default'}: {type(exc).__name__}: {exc}")
    raise RuntimeError(
        "Could not open netCDF with any engine. Tried -> " + " | ".join(errors)
    )


def process_caravan(args):
    """Read a Caravan / GRDC-Caravan per-gauge netCDF into the forcing contract.

    Caravan bundles basin-AVERAGED ERA5-Land forcing with the gauge's observed
    streamflow on one daily axis, which is exactly the lumped-conceptual-model
    input SuperflexPy needs. All three series are already mm/d (see the
    CARAVAN_VARS note above), so no unit factor is applied and none must be.
    """
    input_path = Path(args.input)

    try:
        ds = _open_any_netcdf(str(input_path))
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "errors": [str(exc)]}

    missing = [v for v in (CARAVAN_VARS["P"], CARAVAN_VARS["PET"]) if v not in ds.variables]
    if missing:
        return {
            "status": "error",
            "errors": [
                f"Caravan file is missing required variable(s): {missing}. "
                f"Present: {sorted(ds.data_vars)[:10]}..."
            ],
        }
    if CARAVAN_TIME_DIM not in ds.coords:
        return {
            "status": "error",
            "errors": [f"Caravan file has no '{CARAVAN_TIME_DIM}' coordinate"],
        }

    if args.start or args.end:
        ds = ds.sel({CARAVAN_TIME_DIM: slice(args.start, args.end)})
    n_rows = ds.sizes[CARAVAN_TIME_DIM]
    if n_rows == 0:
        return {
            "status": "error",
            "errors": [
                f"No timesteps in requested window {args.start}..{args.end}"
            ],
        }

    P = np.asarray(ds[CARAVAN_VARS["P"]].values, dtype=float)
    PET = np.asarray(ds[CARAVAN_VARS["PET"]].values, dtype=float)

    # Caravan ships PET as positive demand. If a release ever ships the raw
    # negative-downward ERA5-Land sign, running as-is would give the model zero
    # evaporative demand and a runoff ratio near 1 with NO error. Fail loudly.
    finite_pet = PET[np.isfinite(PET)]
    if finite_pet.size and np.nanmax(finite_pet) <= 0:
        if args.pet_sign == "flip":
            PET = -PET
        else:
            return {
                "status": "error",
                "errors": [
                    "Caravan PET is all <= 0 (raw ERA5-Land downward-positive sign). "
                    "Re-run with --pet-sign flip, or the model runs with zero "
                    "evaporative demand and silently over-predicts runoff (dt_002)."
                ],
            }

    # Reanalysis daily PET goes slightly NEGATIVE on condensation days (34/4383
    # days in Ireland, min -0.45 mm/d). Negative PET is not "less demand": in
    # GR4J's InterceptionFilter, remove = min(PET, P) becomes negative, so
    # P - remove ADDS water that never fell, and the ProductionStore's
    # evaporation term reverses sign. Floor it. --pet-min 0 is the correct
    # setting for every reanalysis PET product; None keeps the raw values.
    n_neg_pet = int(np.sum(PET < 0))
    if args.pet_min is not None:
        PET = np.maximum(PET, float(args.pet_min))

    Q_obs = None
    if CARAVAN_VARS["Q"] in ds.variables:
        Q_obs = np.asarray(ds[CARAVAN_VARS["Q"]].values, dtype=float)

    T = None
    if CARAVAN_VARS["T"] in ds.variables:
        T = np.asarray(ds[CARAVAN_VARS["T"]].values, dtype=float)

    times = ds[CARAVAN_TIME_DIM].values
    dates = [str(np.datetime_as_string(t, unit="D")) for t in times]
    ds.close()

    # A single NaN in P or PET poisons the whole downstream ODE solution: the
    # implicit solver propagates NaN into the storage state and EVERY later
    # timestep of Q_sim is NaN, with exit code 0. Refuse to emit such forcing.
    for name, arr in (("P", P), ("PET", PET)):
        n_bad = int(np.sum(~np.isfinite(arr)))
        if n_bad:
            if args.fill_forcing_gaps:
                idx = np.arange(len(arr))
                good = np.isfinite(arr)
                arr[~good] = np.interp(idx[~good], idx[good], arr[good])
            else:
                return {
                    "status": "error",
                    "errors": [
                        f"{name} has {n_bad}/{len(arr)} non-finite values in the "
                        "requested window. A single NaN makes EVERY subsequent "
                        "Q_sim NaN with exit code 0. Re-run with "
                        "--fill-forcing-gaps to linearly interpolate, or narrow "
                        "the window."
                    ],
                }

    result = {
        "status": "success",
        "source_format": "caravan",
        "source_file": str(input_path),
        "gauge_id": input_path.stem,
        "n_timesteps": int(n_rows),
        "timestep_d": args.timestep,
        "units": {"P": "mm/d", "PET": "mm/d", "Q_obs": "mm/d"},
        "conversions_applied": {
            "P": "Caravan total_precipitation_sum is mm/d basin mean -> mm/d (factor=1.0)",
            "PET": "Caravan potential_evaporation_sum is mm/d basin mean, positive demand -> mm/d (factor=1.0)",
            "Q_obs": "Caravan streamflow is BASIN-AVERAGED mm/d (NOT m3/s) -> mm/d (factor=1.0, no area conversion)",
            "PET_floor": (
                f"floored at {args.pet_min} mm/d ({n_neg_pet} negative days clipped)"
                if args.pet_min is not None
                else f"NOT floored ({n_neg_pet} negative days left as-is)"
            ),
        },
        "statistics": {
            "P_mean": float(np.nanmean(P)),
            "P_max": float(np.nanmax(P)),
            "P_total": float(np.nansum(P)),
            "PET_mean": float(np.nanmean(PET)),
            "PET_max": float(np.nanmax(PET)),
        },
        "P": P.tolist(),
        "PET": PET.tolist(),
        "dates": dates,
    }
    if args.area is not None:
        result["area_km2"] = float(args.area)
    if Q_obs is not None:
        result["Q_obs"] = Q_obs.tolist()
        result["statistics"]["Q_obs_mean"] = float(np.nanmean(Q_obs))
        result["statistics"]["Q_obs_nan_frac"] = float(np.mean(~np.isfinite(Q_obs)))
    if T is not None:
        result["T"] = T.tolist()
        result["units"]["T"] = "degC"
    return result


def process(args):
    """Read forcing file and convert to SuperflexPy format."""

    if args.format == "caravan":
        return process_caravan(args)

    input_path = Path(args.input)

    # Detect separator
    with open(input_path, "r") as f:
        # Skip header lines
        for _ in range(args.header_lines):
            f.readline()
        sample_line = f.readline()

    if "," in sample_line:
        sep = ","
    else:
        sep = r"\s+"

    # Read data, skipping header
    try:
        data = np.genfromtxt(
            str(input_path),
            skip_header=args.header_lines,
            delimiter="," if sep == "," else None,
            filling_values=np.nan,
        )
    except Exception as e:
        return {"status": "error", "errors": [f"Failed to read data: {str(e)}"]}

    if data.ndim == 1:
        return {"status": "error", "errors": ["Data appears to have only one column"]}

    n_cols = data.shape[1]
    n_rows = data.shape[0]

    # Extract columns (0-indexed)
    p_col = args.p_col
    pet_col = args.pet_col
    q_col = args.q_col

    if p_col >= n_cols:
        return {
            "status": "error",
            "errors": [f"P column index {p_col} >= number of columns {n_cols}"],
        }

    # Extract precipitation
    P = data[:, p_col].copy()
    P_factor = PRECIP_CONVERSIONS[args.p_unit]
    P *= P_factor

    # Extract PET
    if pet_col is not None and pet_col < n_cols:
        PET = data[:, pet_col].copy()
        PET_factor = PET_CONVERSIONS[args.pet_unit]
        PET *= PET_factor
    else:
        PET = np.zeros(n_rows)
        print("WARNING: No PET column specified, using zeros", file=sys.stderr)

    # Extract observed Q if available
    Q_obs = None
    if q_col is not None and q_col < n_cols:
        Q_obs = data[:, q_col].copy()
        if args.q_unit in Q_CONVERSIONS and Q_CONVERSIONS[args.q_unit] is not None:
            Q_obs *= Q_CONVERSIONS[args.q_unit]
        elif args.q_unit in ("m3/s", "cms") and args.area is not None:
            # Convert m3/s to mm/d: Q * 86400 / (area_km2 * 1e6) * 1000
            Q_obs = Q_obs * 86400.0 / (args.area * 1e6) * 1000.0
        elif args.q_unit in ("l/s",) and args.area is not None:
            Q_obs = Q_obs * 86.4 / (args.area * 1e6) * 1000.0

    # Extract dates if available
    dates = None
    if args.year_col is not None and args.month_col is not None and args.day_col is not None:
        years = data[:, args.year_col].astype(int)
        months = data[:, args.month_col].astype(int)
        days = data[:, args.day_col].astype(int)
        dates = [f"{y:04d}-{m:02d}-{d:02d}" for y, m, d in zip(years, months, days)]

    result = {
        "status": "success",
        "n_timesteps": int(n_rows),
        "timestep_d": args.timestep,
        "units": {"P": "mm/d", "PET": "mm/d", "Q_obs": "mm/d"},
        "conversions_applied": {
            "P": f"{args.p_unit} -> mm/d (factor={P_factor})",
            "PET": f"{args.pet_unit} -> mm/d (factor={PET_CONVERSIONS[args.pet_unit]})",
        },
        "statistics": {
            "P_mean": float(np.nanmean(P)),
            "P_max": float(np.nanmax(P)),
            "P_total": float(np.nansum(P)),
            "PET_mean": float(np.nanmean(PET)),
            "PET_max": float(np.nanmax(PET)),
        },
        "P": P.tolist(),
        "PET": PET.tolist(),
    }

    if Q_obs is not None:
        result["Q_obs"] = Q_obs.tolist()
        result["statistics"]["Q_obs_mean"] = float(np.nanmean(Q_obs))

    if dates is not None:
        result["dates"] = dates

    return result


def validate_outputs(result):
    """Check output arrays for common silent errors."""
    if result["status"] != "success":
        return result

    warnings = []

    P = np.array(result["P"])
    PET = np.array(result["PET"])

    # Check for negative values
    if np.any(P < 0):
        warnings.append("WARNING: Negative precipitation values detected — check units")

    if np.any(PET < 0):
        warnings.append("WARNING: Negative PET values detected — check units")

    # Check for suspiciously large values (dt_001)
    if np.nanmax(P) > 500:
        warnings.append(
            f"WARNING: Max P = {np.nanmax(P):.1f} mm/d seems very high — "
            "verify unit conversion (dt_001)"
        )

    if np.nanmean(P) > 50:
        warnings.append(
            f"WARNING: Mean P = {np.nanmean(P):.1f} mm/d — "
            "likely wrong units (expected daily, got monthly?)"
        )

    # Check PET magnitude (dt_002)
    if np.nanmax(PET) > 30:
        warnings.append(
            f"WARNING: Max PET = {np.nanmax(PET):.1f} mm/d seems high — "
            "verify PET units (dt_002)"
        )

    # Check for all-zero arrays
    if np.all(P == 0):
        warnings.append("WARNING: All precipitation values are zero")

    # Check NaN fraction
    nan_frac = np.sum(np.isnan(P)) / len(P)
    if nan_frac > 0.1:
        warnings.append(f"WARNING: {nan_frac*100:.1f}% of P values are NaN")

    if warnings:
        result["warnings"] = warnings
        for w in warnings:
            print(w, file=sys.stderr)

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Convert forcing data to SuperflexPy input format"
    )
    parser.add_argument("--input", type=str, required=True, help="Input forcing file path")
    parser.add_argument("--output", type=str, default=None, help="Output JSON path (default: stdout)")
    parser.add_argument(
        "--format",
        type=str,
        default="text",
        choices=("text", "caravan"),
        help="Input layout: 'text' (columnar CSV/DAT, default) or 'caravan' (Caravan per-gauge netCDF)",
    )
    parser.add_argument("--start", type=str, default=None, help="First date to keep, YYYY-MM-DD (caravan)")
    parser.add_argument("--end", type=str, default=None, help="Last date to keep, YYYY-MM-DD (caravan)")
    parser.add_argument(
        "--pet-sign",
        type=str,
        default="asis",
        choices=("asis", "flip"),
        help="'flip' negates PET (use only if the source ships downward-positive ERA5 sign)",
    )
    parser.add_argument(
        "--pet-min",
        type=float,
        default=None,
        help="Floor PET at this value (use 0 for reanalysis PET: negative condensation "
             "days make GR4J's interception filter ADD water)",
    )
    parser.add_argument(
        "--fill-forcing-gaps",
        action="store_true",
        help="Linearly interpolate non-finite P/PET instead of refusing to emit NaN-poisoned forcing",
    )
    parser.add_argument("--header-lines", type=int, default=7, help="Number of header lines to skip (default: 7)")
    parser.add_argument("--p-col", type=int, default=6, help="Precipitation column index (0-based, default: 6)")
    parser.add_argument("--pet-col", type=int, default=7, help="PET column index (0-based, default: 7)")
    parser.add_argument("--q-col", type=int, default=8, help="Observed Q column index (0-based, default: 8)")
    parser.add_argument("--year-col", type=int, default=0, help="Year column index")
    parser.add_argument("--month-col", type=int, default=1, help="Month column index")
    parser.add_argument("--day-col", type=int, default=2, help="Day column index")
    parser.add_argument("--p-unit", type=str, default="mm/d", help="Precipitation units")
    parser.add_argument("--pet-unit", type=str, default="mm/d", help="PET units")
    parser.add_argument("--q-unit", type=str, default="mm/d", help="Observed Q units")
    parser.add_argument("--timestep", type=float, default=1.0, help="Timestep in days (default: 1.0)")
    parser.add_argument("--area", type=float, default=None, help="Catchment area in km² (for Q unit conversion)")

    args = parser.parse_args()

    validate_inputs(args)
    result = process(args)
    result = validate_outputs(result)

    output_json = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        with open(args.output, "w") as f:
            f.write(output_json)
        print(f"Results written to {args.output}", file=sys.stderr)
    else:
        print(output_json)


if __name__ == "__main__":
    main()
