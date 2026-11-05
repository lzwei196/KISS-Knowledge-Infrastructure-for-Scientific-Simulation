#!/usr/bin/env python3
"""SURROGATE -- NOT EPA VELMA. This converter writes the surrogate's Kelvin forcing JSON (not an EPA VELMA input).
It belongs to the Python lumped 4-layer stand-in (tools/run_velma.py), a HydroCraft
re-implementation; its numbers are never VELMA results. The real model is EPA VELMA 2.1
(JVelma.jar), run by tools/run_velma_engine.py with weather drivers from
tools/build_velma_weather_from_source.py (P mm/day, T deg C).
The surrogate's full I/O contract is docs/surrogate_velma_4layer_dag.yaml.

Strict daily forcing preparation for the legacy Python VELMA adapter.

JSON uses P in mm/day, temperature in Kelvin and solar in W/m2.
EPA's original Java model uses Celsius weather files, not this JSON schema.
Explicit --solar-mode unused omits solar for native Java P/T preparation;
it must not be used with the Python runner. No values or dates are filled.
Only already-daily NetCDF sources are supported; subdaily inputs must be
validated and aggregated upstream. All requested years must be complete.
"""

import argparse
import json
import os
import sys
from datetime import datetime

import numpy as np

try:
    import pandas as pd
except ImportError:
    pd = None

try:
    import xarray as xr
except ImportError:
    xr = None

try:
    import geopandas as gpd
    from shapely.geometry import Point
except ImportError:
    gpd = None


# ---- Unit conversion constants ------------------------------------------------
# Each constant converts FROM the source unit TO the model's expected unit.
# Variable names encode the conversion: SOURCE_TO_TARGET.

# Precipitation: CMFD is kg/m2/s = mm/s.  Model needs mm/d.
CMFD_PRECIP_KGM2S_TO_MMDAY = 86400.0   # kg/m2/s -> mm/d  (1 kg/m2/s = 1 mm/s * 86400 s/d)
M_D_TO_MM_D = 1000.0                    # m/d -> mm/d

# Temperature: VELMA expects Kelvin internally.
# If source is Celsius, ADD 273.15.  If source is already K, no conversion.
C_TO_K = 273.15                          # deg C -> K  (add this offset)
F_TO_C_SCALE = 5.0 / 9.0                # (F - 32) * 5/9 = C, then + 273.15 = K
F_TO_C_OFFSET = -32.0

# Solar radiation: VELMA expects W/m2.
MJ_M2_D_TO_W_M2 = 1.0 / 0.0864         # MJ/m2/d -> W/m2  (~11.574)
KJ_M2_D_TO_W_M2 = 1.0 / 86.4           # kJ/m2/d -> W/m2  (~0.01157)


def validate_inputs(args):
    """Validate all inputs before processing. Returns list of errors."""
    errors = []

    if not os.path.isdir(args.forcing_dir):
        errors.append(f"Forcing directory does not exist: {args.forcing_dir}")

    if not os.path.isfile(args.shapefile):
        errors.append(f"Shapefile does not exist: {args.shapefile}")

    # Parse year range
    try:
        parts = args.years.split("-")
        y_start, y_end = int(parts[0]), int(parts[1])
        if y_start > y_end:
            errors.append(f"Start year {y_start} > end year {y_end}")
        if y_start < 1900 or y_end > 2100:
            errors.append(f"Year range {y_start}-{y_end} looks implausible")
    except (ValueError, IndexError):
        errors.append(f"Cannot parse year range '{args.years}'. Use YYYY-YYYY format.")

    valid_prec_units = ["kg/m2/s", "mm/d", "m/d"]
    if args.prec_unit not in valid_prec_units:
        errors.append(
            f"Invalid prec unit '{args.prec_unit}'. Must be one of {valid_prec_units}")

    valid_temp_units = ["K", "C", "F"]
    if args.temp_unit not in valid_temp_units:
        errors.append(
            f"Invalid temp unit '{args.temp_unit}'. Must be one of {valid_temp_units}")

    valid_srad_units = ["W/m2", "MJ/m2/d", "kJ/m2/d"]
    if args.srad_unit not in valid_srad_units:
        errors.append(
            f"Invalid srad unit '{args.srad_unit}'. Must be one of {valid_srad_units}")

    if xr is None:
        errors.append("xarray is required but not installed. Run: pip install xarray")

    if gpd is None:
        errors.append("geopandas is required but not installed. Run: pip install geopandas")

    if pd is None:
        errors.append("pandas is required but not installed. Run: pip install pandas")

    return errors


def convert_precipitation(values, from_unit):
    """Convert precipitation to mm/d.

    CRITICAL: Getting this wrong causes discharge to be off by orders of
    magnitude. The model runs without error -- only the results are wrong.

    Conversion factors:
      kg/m2/s -> mm/d:  multiply by CMFD_PRECIP_KGM2S_TO_MMDAY (86400)
      m/d     -> mm/d:  multiply by 1000
      mm/d    -> mm/d:  no conversion
      mm/3h is rejected: validate and aggregate subdaily data upstream.
    """
    if from_unit == "mm/d":
        return values
    elif from_unit == "kg/m2/s":
        return values * CMFD_PRECIP_KGM2S_TO_MMDAY
    elif from_unit == "m/d":
        return values * M_D_TO_MM_D
    elif from_unit == "mm/3h":
        raise ValueError("mm/3h is subdaily. Validate all eight steps and aggregate upstream; supply daily totals as mm/d")
    else:
        raise ValueError(f"Unknown precipitation unit: {from_unit}")


def convert_temperature(values, from_unit):
    """Convert temperature to Kelvin.

    CRITICAL: The legacy Python adapter expects Kelvin. The model subtracts 273.15 internally.
    Pre-converting to Celsius causes the model to compute T_C = C - 273.15,
    giving values like -258 C, which makes PET = 0 and ET = 0 (dt_004).
    """
    if from_unit == "K":
        return values
    elif from_unit == "C":
        return values + C_TO_K   # i.e., values + 273.15
    elif from_unit == "F":
        t_c = (values + F_TO_C_OFFSET) * F_TO_C_SCALE
        return t_c + C_TO_K
    else:
        raise ValueError(f"Unknown temperature unit: {from_unit}")


def convert_solar_radiation(values, from_unit):
    """Convert solar radiation to W/m2.

    CRITICAL: Wrong srad units make PET off by ~10x (dt_006, dt_007).
    CMFD srad is already in W/m2. Other sources may be in MJ/m2/d or kJ/m2/d.
    """
    if from_unit == "W/m2":
        return values
    elif from_unit == "MJ/m2/d":
        return values * MJ_M2_D_TO_W_M2
    elif from_unit == "kJ/m2/d":
        return values * KJ_M2_D_TO_W_M2
    else:
        raise ValueError(f"Unknown solar radiation unit: {from_unit}")


def _daily_index(index, years, label):
    dates = pd.DatetimeIndex(index)
    expected = pd.date_range(f"{years[0]}-01-01", f"{years[-1]}-12-31")
    if dates.tz is not None or dates.hasnans or not dates.normalize().equals(expected):
        raise ValueError(f"{label}: require exactly one ordered record per requested day, including leap days; no duplicate, missing or extra dates")
    return dates.normalize()


def load_and_mask_cmfd(forcing_dir, shapefile, years, prec_var, temp_var,
                       srad_var, file_pattern, log, source_units=None):
    """Read complete daily fields. Never reduce over missing active cells.

    Cell centres covered by the union of all basin polygons receive equal
    weight, preserving the existing arithmetic spatial-mean convention.
    A field with no selected centre is an error, not a bounding-box fallback.
    Passing srad_var=None explicitly omits the unused solar field.
    """
    gdf = gpd.read_file(shapefile)
    if gdf.crs is None or gdf.empty or gdf.geometry.is_empty.any() or not gdf.geometry.is_valid.all():
        raise ValueError("Basin polygons require an explicit CRS and valid nonempty geometry")
    gdf = gdf.to_crs("EPSG:4326")
    basin = gdf.geometry.union_all()
    bounds = basin.bounds
    result = []
    for var in (prec_var, temp_var, srad_var):
        if var is None:
            result.append(None)
            continue
        chunks = []
        for year in years:
            path = os.path.join(forcing_dir, file_pattern.format(var=var, year=year))
            if not os.path.isfile(path):
                raise FileNotFoundError(f"Required {var} source is missing: {path}")
            with xr.open_dataset(path) as ds:
                if var not in ds:
                    raise ValueError(f"Requested variable {var!r} not in {path}")
                field = ds[var]
                pair = next(((lat, lon) for lat, lon in
                             (("lat", "lon"), ("latitude", "longitude"), ("y", "x"))
                             if lat in field.dims and lon in field.dims), None)
                if pair is None or set(field.dims) != {"time", *pair}:
                    raise ValueError(f"{var}: expected time and two geographic coordinate dimensions")
                lat, lon = pair
                for coord, limit in ((lat, 90), (lon, 180)):
                    axis = ds[coord]
                    values = np.asarray(axis.values, dtype=float)
                    if axis.ndim != 1 or not np.isfinite(values).all() or np.any(np.abs(values) > limit) or len(np.unique(values)) != len(values):
                        raise ValueError(f"{var}: invalid geographic {coord} coordinates")
                    unit = str(axis.attrs.get("units", "")).lower()
                    if unit and unit not in ("degree", "degrees", "degrees_north", "degrees_east", "degree_north", "degree_east"):
                        raise ValueError(f"{var}: {coord} must be geographic degrees, found {unit}")
                mapping = field.attrs.get("grid_mapping")
                if mapping and mapping in ds and ds[mapping].attrs.get("grid_mapping_name", "latitude_longitude") != "latitude_longitude":
                    raise ValueError(f"{var}: projected grids require explicit geographic reprojection first")
                sub = field.isel({lon: (ds[lon] >= bounds[0]) & (ds[lon] <= bounds[2]),
                                  lat: (ds[lat] >= bounds[1]) & (ds[lat] <= bounds[3])}).transpose("time", lat, lon)
                xx, yy = np.meshgrid(sub[lon].values, sub[lat].values)
                mask = np.array([basin.covers(Point(x, y)) for x, y in zip(xx.ravel(), yy.ravel())], dtype=bool).reshape(xx.shape)
                if not mask.any():
                    raise ValueError(f"{var}: no grid cell centres covered by basin polygon; supply suitable resolution")
                dates = _daily_index(sub.time.values, [year], var)
                active = np.asarray(sub.values[:, mask], dtype=float)
                if not np.isfinite(active).all():
                    raise ValueError(f"{var}: missing or infinite value in an active grid cell; repair source data explicitly")
                if source_units:
                    if var == prec_var:
                        checked = convert_precipitation(active, source_units['prec'])
                        validate_outputs(checked, None, None, log)
                    elif var == temp_var:
                        validate_outputs(None, convert_temperature(active, source_units['temp']), None, log)
                    else:
                        validate_outputs(None, None, convert_solar_radiation(active, source_units['srad']), log)
                chunks.append(pd.Series(active.mean(axis=1), index=dates, name=var))
                log.append(f"{path}: {len(dates)} complete days; {int(mask.sum())} active cells; equal-weight mean")
        series = pd.concat(chunks)
        _daily_index(series.index, years, var)
        result.append(series)
    return tuple(result)


def validate_outputs(prec_mm_d, temp_K, srad_Wm2, log):
    """Enforce per-value finite/physical checks, allowing real zero rain/solar."""
    for name, values in (("precipitation", prec_mm_d), ("temperature", temp_K), ("solar radiation", srad_Wm2)):
        if values is None:
            continue
        values = np.asarray(values, dtype=float)
        if not values.size or not np.isfinite(values).all():
            raise ValueError(f"{name}: all required values must be finite")
        if name == "temperature":
            if np.any((values < 173.15) | (values > 343.15)):
                raise ValueError("temperature outside [-100, 70] Celsius; verify explicitly declared units")
        elif np.any(values < 0):
            raise ValueError(f"{name}: negative values are invalid")
    return True


def process(args, log):
    start, end = map(int, args.years.split("-"))
    if start > end:
        raise ValueError("Start year exceeds end year")
    years = list(range(start, end + 1))
    solar_mode = getattr(args, "solar_mode", "required")
    if solar_mode not in ("required", "unused"):
        raise ValueError("solar_mode must be required or unused")
    source_units = {'prec': args.prec_unit, 'temp': args.temp_unit, 'srad': args.srad_unit}
    raw = load_and_mask_cmfd(args.forcing_dir, args.shapefile, years,
                            args.prec_var, args.temp_var,
                            args.srad_var if solar_mode == "required" else None,
                            args.file_pattern, log, source_units=source_units)
    for name, series in zip(("precipitation", "temperature", "solar radiation"), raw[:3 if solar_mode == "required" else 2]):
        if series is None:
            raise ValueError(f"Missing required {name} source; no replacement is permitted")
        _daily_index(series.index, years, name)
        if not np.isfinite(np.asarray(series.values, dtype=float)).all():
            raise ValueError(f"{name}: missing or infinite daily values")
    prec = convert_precipitation(np.asarray(raw[0].values, dtype=float), args.prec_unit)
    temp = convert_temperature(np.asarray(raw[1].values, dtype=float), args.temp_unit)
    solar = convert_solar_radiation(np.asarray(raw[2].values, dtype=float), args.srad_unit) if solar_mode == "required" else None
    validate_outputs(prec, temp, solar, log)
    dates = _daily_index(raw[0].index, years, "precipitation")
    sources = []
    for var in (args.prec_var, args.temp_var, args.srad_var if solar_mode == 'required' else None):
        if var is None:
            continue
        for year in years:
            path = os.path.join(args.forcing_dir, args.file_pattern.format(var=var, year=year))
            # Files exist for the real loader; unit tests may inject series.
            if os.path.isfile(path):
                import hashlib
                with open(path, "rb") as handle:
                    digest = hashlib.file_digest(handle, "sha256").hexdigest()
                sources.append({'path': os.path.abspath(path), 'sha256': digest, 'variable': var, 'year': year})
    output = {
        "dates": dates.strftime("%Y-%m-%d").tolist(),
        "prec_mm_d": prec.tolist(), "temp_K": temp.tolist(),
        "n_days": len(dates), "year_range": args.years,
        "filled_values": 0, "solar_mode": solar_mode,
        "source_units": {key: value for key, value in source_units.items() if key != 'srad' or solar is not None},
        "target_units": {"prec": "mm/d", "temp": "K"},
        "sources": sources,
        "spatial_method": "equal-weight mean of all finite polygon-covered cell centres; no partial-cell or missing-cell renormalization",
        "runtime_contract": "Legacy Python JSON uses Kelvin. EPA Java weather files require Celsius; subtract 273.15 exactly once when exporting.",
        "statistics": {
            "prec_mean_mm_d": float(prec.mean()), "prec_max_mm_d": float(prec.max()),
            "prec_total_mm": float(prec.sum()), "temp_mean_K": float(temp.mean()),
            "temp_min_K": float(temp.min()), "temp_max_K": float(temp.max()),
        },
    }
    if solar is not None:
        output['srad_Wm2'] = solar.tolist()
        output['target_units']['srad'] = 'W/m2'
        output['statistics']['srad_mean_Wm2'] = float(solar.mean())
    return {"status": "success", "output": output, "log": log}


def main():
    parser = argparse.ArgumentParser(
        description="SURROGATE input only (NOT EPA VELMA): convert CMFD/ERA5 NetCDF forcing to the Python stand-in's Kelvin JSON. For the real engine use build_velma_weather_from_source.py.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
CRITICAL UNIT TRAPS:
  dt_001: CMFD precip is kg/m2/s. Multiply by 86400 for mm/d.
  Legacy Python JSON uses Kelvin; EPA Java weather files require Celsius.
  dt_006: Solar radiation must be in W/m2 (CMFD default). If MJ/m2/d, divide by 0.0864.
""")
    parser.add_argument("--forcing-dir", required=True,
                        help="Directory containing CMFD/ERA5 NetCDF files")
    parser.add_argument("--shapefile", required=True,
                        help="Path to basin boundary shapefile")
    parser.add_argument("--years", required=True,
                        help="Year range YYYY-YYYY (e.g. 1980-1990)")
    parser.add_argument("--prec-var", default="prec",
                        help="Precipitation variable name in filenames (default: prec)")
    parser.add_argument("--temp-var", default="temp",
                        help="Temperature variable name in filenames (default: temp)")
    parser.add_argument("--srad-var", default="srad",
                        help="Solar radiation variable name in filenames (default: srad)")
    parser.add_argument("--prec-unit", default="kg/m2/s",
                        choices=["kg/m2/s", "mm/d", "m/d"],
                        help="Precipitation unit in source data (default: kg/m2/s)")
    parser.add_argument("--temp-unit", default="K",
                        choices=["K", "C", "F"],
                        help="Temperature unit in source data (default: K)")
    parser.add_argument("--srad-unit", default="W/m2",
                        choices=["W/m2", "MJ/m2/d", "kJ/m2/d"],
                        help="Solar radiation unit in source data (default: W/m2)")
    parser.add_argument("--solar-mode", choices=["required", "unused"], default="required",
                        help="required for legacy Python runner; unused omits solar for native Java P/T preparation")
    parser.add_argument("--file-pattern", default="{var}_ITPCAS-CMFD_V0200_B-01_01dy_025deg_{year}01-{year}12.nc",
                        help="Filename pattern with {var} and {year} placeholders")
    parser.add_argument("--output", required=True,
                        help="Output JSON file path")

    args = parser.parse_args()

    # Validate inputs
    errors = validate_inputs(args)
    if errors:
        result = {"status": "error", "errors": errors, "log": []}
        json.dump(result, sys.stdout, indent=2)
        sys.exit(1)

    # Process
    log = []
    try:
        result = process(args, log)
    except (ValueError, OSError, KeyError) as exc:
        print(json.dumps({"status": "error", "errors": [str(exc)], "log": log}), file=sys.stderr)
        return 1

    # Write output
    output_dir = os.path.dirname(args.output)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    with open(args.output, "w") as f:
        json.dump(result, f, indent=2, allow_nan=False)

    status = result["status"]
    print(f"\n[convert_forcing_to_velma] Status: {status}")
    print(f"  Output: {args.output}")
    if status == "success":
        n = result["output"]["n_days"]
        stats = result["output"]["statistics"]
        print(f"  Days: {n}")
        print(f"  Mean precip: {stats['prec_mean_mm_d']} mm/d")
        print(f"  Mean temp: {stats['temp_mean_K']} K "
              f"({stats['temp_mean_K'] - 273.15:.1f} C)")
        if 'srad_mean_Wm2' in stats:
            print(f"  Mean srad: {stats['srad_mean_Wm2']} W/m2")
    for entry in log:
        if "[CRITICAL]" in entry or "[WARN]" in entry:
            print(f"  {entry}")


if __name__ == "__main__":
    sys.exit(main())
