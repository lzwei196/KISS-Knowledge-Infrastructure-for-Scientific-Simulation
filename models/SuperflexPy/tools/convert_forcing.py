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


def _nonfinite_label(x):
    x = float(x)
    return "NaN" if np.isnan(x) else "+Inf" if x > 0 else "-Inf" if x < 0 else repr(x)


def _gap_policy(P, PET, dates, enabled, sources=None, transforms=None):
    """Explicit interior interpolation with a complete per-value repair record.

    `P`/`PET` are the converted series (mm/d, after any requested PET sign/floor
    step); interpolation runs on them. `sources` holds the same series exactly as
    read from the file, BEFORE unit factors and sign/floor steps, so the record
    keeps the true source value ("original") even when a transform changed it
    (e.g. --pet-sign flip turns a source -Inf into +Inf).
    """
    sources = sources or {}
    report = {"enabled": bool(enabled), "method": "linear interpolation between finite neighbours",
              "interpolated_on": "converted mm/d values after the transforms listed here",
              "transforms_before_interpolation": transforms or {},
              "counts": {}, "masks": {}, "records": []}
    for name, arr in (("P", P), ("PET", PET)):
        if arr.ndim != 1 or not arr.size:
            raise ValueError(f"{name}: a nonempty one-dimensional daily series is required")
        src = np.asarray(sources.get(name, arr), dtype=float)
        if src.shape != arr.shape:
            raise ValueError(f"{name}: source and converted series differ in length")
        good = np.isfinite(arr)
        if not np.array_equal(good, np.isfinite(src)):
            raise ValueError(f"{name}: conversion changed which values are finite")
        report["counts"][name] = int((~good).sum())
        report["masks"][name] = (~good).tolist()
        if good.all():
            continue
        if not enabled:
            i = int(np.flatnonzero(~good)[0])
            raise ValueError(f"{name}: missing/nonfinite value at {dates[i] if dates else i}; "
                             "supply complete data or explicitly request --fill-forcing-gaps")
        if not good[0] or not good[-1]:
            raise ValueError(f"{name}: gap filling needs finite observations on both sides; "
                             "edge/all-missing gaps cannot be interpolated")
        valid = np.flatnonzero(good)
        for i in np.flatnonzero(~good):
            pos = np.searchsorted(valid, i)
            left, right = int(valid[pos-1]), int(valid[pos])
            value = float(np.interp(i, valid, arr[good]))
            def neighbour(j):
                return {"index": j, "date": dates[j] if dates else None,
                        "value": float(arr[j]), "source_value": float(src[j])}
            report["records"].append({"field": name, "index": int(i),
                "date": dates[i] if dates else None,
                "original": _nonfinite_label(src[i]),
                "after_transforms": _nonfinite_label(arr[i]),
                "filled_value": value, "method": "linear", "left": neighbour(left), "right": neighbour(right)})
            arr[i] = value
    return report


def _pet_transform(PET, args, source_label, all_zero_ok=False):
    """Apply the requested PET sign and floor steps, the same way for every format.

    Returns (PET, info). A wrong sign is never guessed:
    - finite PET that has negative values and no positive value is the raw
      downward-positive sign: it stops unless --pet-sign flip is given;
    - --pet-sign flip is accepted ONLY for that case (on PET with positive
      values it would invert real demand, on all-zero PET it changes nothing
      and would record a false sign correction);
    - finite PET that is all zero is real zero demand for text input
      (all_zero_ok=True) but an empty field for Caravan basin-mean ERA5-Land
      PET, which is never zero over a whole window (all_zero_ok=False).
    """
    PET = np.asarray(PET, dtype=float).copy()
    finite = PET[np.isfinite(PET)]
    has_pos = bool(finite.size) and bool(np.any(finite > 0))
    has_neg = bool(finite.size) and bool(np.any(finite < 0))
    negative_only = has_neg and not has_pos
    all_zero = bool(finite.size) and not has_pos and not has_neg
    flipped = False
    if getattr(args, "pet_sign", "asis") == "flip":
        if not negative_only:
            raise ValueError(
                f"--pet-sign flip was requested but {source_label} PET is not negative-only "
                "(it has positive values, is all zero, or has no finite values); flipping "
                "would invert real demand or record a sign change that did nothing. "
                "Drop --pet-sign flip.")
        PET = -PET
        flipped = True
    elif negative_only:
        raise ValueError(
            f"{source_label} finite PET has negative values and is never > 0 in the window "
            "(raw ERA5-Land downward-positive sign). Re-run with --pet-sign flip, or the "
            "model runs with zero evaporative demand and silently over-predicts runoff (dt_002).")
    elif all_zero and not all_zero_ok:
        raise ValueError(
            f"{source_label} finite PET is zero on every day of the window; basin-mean "
            "ERA5-Land PET is never zero for a whole window, so this is an empty PET field.")
    # Reanalysis daily PET goes slightly NEGATIVE on condensation days (34/4383
    # days in Ireland, min -0.45 mm/d). Negative PET is not "less demand": in
    # GR4J's InterceptionFilter, remove = min(PET, P) becomes negative, so
    # P - remove ADDS water that never fell, and the ProductionStore's
    # evaporation term reverses sign. Floor it. --pet-min 0 is the correct
    # setting for every reanalysis PET product; None keeps the raw values.
    n_neg = int(np.sum(np.isfinite(PET) & (PET < 0)))
    n_floored = 0
    pet_min = getattr(args, "pet_min", None)
    if pet_min is not None:
        if not np.isfinite(pet_min):
            raise ValueError("--pet-min must be finite")
        n_floored = int(np.sum(np.isfinite(PET) & (PET < pet_min)))
        PET = np.where(np.isfinite(PET), np.maximum(PET, float(pet_min)), PET)
    info = {
        "PET_sign": "negated (--pet-sign flip)" if flipped else "as in source",
        "PET_all_zero": bool(all_zero),
        "PET_floor": (f"floored at {pet_min} mm/d ({n_floored} finite values clipped)"
                      if pet_min is not None else f"NOT floored ({n_neg} negative values left as-is)"),
    }
    return PET, info


def _check_dates(dates, n, timestep, start=None, end=None):
    if dates is None:
        return
    axis = np.asarray(dates, dtype="datetime64[D]")
    if axis.shape != (n,) or np.isnat(axis).any():
        raise ValueError("dates must have one valid daily date per forcing value")
    if timestep < 1:
        # Sub-daily rows carry only a day (no hour column): every day must be
        # there, in order, with exactly 1/timestep rows (e.g. 24 for hourly).
        per_day = round(1.0 / timestep)
        if abs(1.0 / timestep - per_day) > 1e-9:
            raise ValueError(f"--timestep {timestep} d does not divide a day")
        days, counts = np.unique(axis, return_counts=True)
        if np.any(np.diff(axis).astype(int) < 0):
            raise ValueError("dates must be in order")
        if len(days) > 1 and np.any(np.diff(days).astype(int) != 1):
            raise ValueError("days must be consecutive, without missing days")
        if np.any(counts != per_day):
            bad = days[counts != per_day][:5]
            raise ValueError(f"every day needs exactly {per_day} rows at --timestep {timestep}; "
                             f"not so on {[str(d) for d in bad]}")
    elif n > 1 and np.any(np.diff(axis).astype(int) != timestep):
        raise ValueError("dates must be ordered and consecutive, without gaps/duplicates")
    if (start and axis[0] != np.datetime64(start, 'D')) or (end and axis[-1] != np.datetime64(end, 'D')):
        raise ValueError("forcing does not cover the requested start/end dates")


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

    try:
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

        # Caravan ships PET as positive demand; the sign check and the floor are
        # shared with text input (_pet_transform) and run after the window cut.
        P_src = P.copy()
        PET_src = PET.copy()

        Q_obs = None
        if CARAVAN_VARS["Q"] in ds.variables:
            Q_obs = np.asarray(ds[CARAVAN_VARS["Q"]].values, dtype=float)

        T = None
        if CARAVAN_VARS["T"] in ds.variables:
            T = np.asarray(ds[CARAVAN_VARS["T"]].values, dtype=float)

        times = ds[CARAVAN_TIME_DIM].values
        dates = [str(np.datetime_as_string(t, unit="D")) for t in times]

    except (ValueError, KeyError, TypeError) as exc:
        return {"status": "error", "errors": [str(exc)]}
    finally:
        ds.close()

    try:
        if args.timestep != 1.:
            raise ValueError("Caravan forcing has a daily timestep; --timestep must be 1")
        if P.shape != (n_rows,) or PET.shape != (n_rows,):
            raise ValueError("Caravan P/PET must have one value per date")
        if np.any(times.astype('datetime64[s]') != times.astype('datetime64[D]')):
            raise ValueError("Caravan timestamps must be daily midnight values")
        _check_dates(dates, n_rows, 1, args.start, args.end)
        PET, pet_info = _pet_transform(PET, args, "Caravan")
        gap_filling = _gap_policy(P, PET, dates, args.fill_forcing_gaps,
                                  sources={"P": P_src, "PET": PET_src}, transforms=pet_info)
    except ValueError as exc:
        return {"status": "error", "errors": [str(exc)]}

    result = {
        "status": "success",
        "source_format": "caravan",
        "gap_filling": gap_filling,
        "source_file": str(input_path),
        "gauge_id": input_path.stem,
        "n_timesteps": int(n_rows),
        "timestep_d": args.timestep,
        "units": {"P": "mm/d", "PET": "mm/d", "Q_obs": "mm/d"},
        "conversions_applied": {
            "P": "Caravan total_precipitation_sum is mm/d basin mean -> mm/d (factor=1.0)",
            "PET": "Caravan potential_evaporation_sum is mm/d basin mean, positive demand -> mm/d (factor=1.0)",
            "Q_obs": "Caravan streamflow is BASIN-AVERAGED mm/d (NOT m3/s) -> mm/d (factor=1.0, no area conversion)",
            "PET_sign": pet_info["PET_sign"],
            "PET_floor": pet_info["PET_floor"],
        },
        "statistics": {
            "gap_filled_counts": gap_filling["counts"],
            "P_mean": float(np.nanmean(P)),
            "P_max": float(np.nanmax(P)),
            # P is a rate (mm/d); the total depth needs the step length.
            "P_total": float(np.nansum(P) * args.timestep),
            "P_total_unit": "mm",
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
            ndmin=2,  # keep a one-row file 2-D, so it is not mistaken for one column
        )
    except Exception as e:
        return {"status": "error", "errors": [f"Failed to read data: {str(e)}"]}

    if data.ndim != 2 or data.shape[0] == 0:
        return {"status": "error", "errors": ["No data rows after the header"]}
    if data.shape[1] < 2:
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
    P_src = data[:, p_col].copy()
    P = P_src.copy()
    P_factor = PRECIP_CONVERSIONS[args.p_unit]
    P *= P_factor

    # Extract PET
    if pet_col is not None and pet_col < n_cols:
        PET_src = data[:, pet_col].copy()
        PET_factor = PET_CONVERSIONS[args.pet_unit]
        PET = PET_src * PET_factor
    else:
        return {"status": "error", "errors": ["Missing required PET column; no zero substitute is used"]}

    # Extract observed Q if available
    Q_obs = None
    if q_col is not None and q_col < n_cols:
        Q_obs = data[:, q_col].copy()
        if args.q_unit not in Q_CONVERSIONS:
            return {"status": "error", "errors": [
                f"Unknown Q unit: {args.q_unit}. Supported: {list(Q_CONVERSIONS.keys())}"]}
        if Q_CONVERSIONS[args.q_unit] is not None:
            Q_obs *= Q_CONVERSIONS[args.q_unit]
            q_note = f"{args.q_unit} -> mm/d (factor={Q_CONVERSIONS[args.q_unit]})"
        else:
            # A volume flow can only become a basin depth with the basin area.
            # Never pass m3/s or l/s numbers on labelled as mm/d.
            if args.area is None or not np.isfinite(args.area) or args.area <= 0:
                return {"status": "error", "errors": [
                    f"--q-unit {args.q_unit} needs --area (catchment area in km2, > 0) "
                    "to convert observed Q to mm/d; no conversion is guessed"]}
            if args.q_unit in ("m3/s", "cms"):
                # m3/s * 86400 s/d / (area_km2 * 1e6 m2) * 1000 mm/m
                Q_obs = Q_obs * 86400.0 / (args.area * 1e6) * 1000.0
            else:  # l/s = 1e-3 m3/s
                Q_obs = Q_obs * 86.4 / (args.area * 1e6) * 1000.0
            q_note = f"{args.q_unit} -> mm/d using area {args.area} km2"

    # Extract dates if available
    dates = None
    if args.year_col is not None and args.month_col is not None and args.day_col is not None:
        years = data[:, args.year_col].astype(int)
        months = data[:, args.month_col].astype(int)
        days = data[:, args.day_col].astype(int)
        dates = [f"{y:04d}-{m:02d}-{d:02d}" for y, m, d in zip(years, months, days)]

    try:
        _check_dates(dates, n_rows, args.timestep)
        PET, pet_info = _pet_transform(PET, args, "text", all_zero_ok=True)
        gap_filling = _gap_policy(P, PET, dates, args.fill_forcing_gaps,
                                  sources={"P": P_src, "PET": PET_src}, transforms=pet_info)
    except ValueError as exc:
        return {"status": "error", "errors": [str(exc)]}

    result = {
        "status": "success",
        "gap_filling": gap_filling,
        "n_timesteps": int(n_rows),
        "timestep_d": args.timestep,
        "units": {"P": "mm/d", "PET": "mm/d", "Q_obs": "mm/d"},
        "conversions_applied": {
            "P": f"{args.p_unit} -> mm/d (factor={P_factor})",
            "PET": f"{args.pet_unit} -> mm/d (factor={PET_CONVERSIONS[args.pet_unit]})",
            "PET_sign": pet_info["PET_sign"],
            "PET_floor": pet_info["PET_floor"],
        },
        "statistics": {
            "gap_filled_counts": gap_filling["counts"],
            "P_mean": float(np.nanmean(P)),
            "P_max": float(np.nanmax(P)),
            # P is a rate (mm/d); the total depth needs the step length.
            "P_total": float(np.nansum(P) * args.timestep),
            "P_total_unit": "mm",
            "PET_mean": float(np.nanmean(PET)),
            "PET_max": float(np.nanmax(PET)),
        },
        "P": P.tolist(),
        "PET": PET.tolist(),
    }

    if Q_obs is not None:
        result["Q_obs"] = Q_obs.tolist()
        result["conversions_applied"]["Q_obs"] = q_note
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

    if not np.isfinite(P).all() or not np.isfinite(PET).all():
        return {"status": "error", "errors": ["P/PET contain nonfinite values after conversion"]}

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
        help="Interpolate interior P/PET gaps and record dates, masks, original values and neighbours; edge gaps fail",
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
    try:
        result = validate_outputs(process(args))
    except (ValueError, IndexError, OSError) as exc:
        result = {"status": "error", "errors": [str(exc)]}
    if result["status"] != "success":
        print(json.dumps(result, indent=2), file=sys.stderr)
        sys.exit(1)

    output_json = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        with open(args.output, "w") as f:
            f.write(output_json)
        print(f"Results written to {args.output}", file=sys.stderr)
    else:
        print(output_json)


if __name__ == "__main__":
    main()
