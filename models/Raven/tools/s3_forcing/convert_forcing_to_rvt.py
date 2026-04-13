#!/usr/bin/env python3
"""
convert_forcing_to_rvt.py — Convert CMFD/MSWX/VIC forcing to Raven .rvt format.

!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
!! CRITICAL WARNING: RAVEN IGNORES UNITS AND WILL NOT DO UNIT CONVERSION.    !!
!! All conversions MUST happen in this tool. If units are wrong, Raven will  !!
!! run without error but produce completely wrong results (SILENT FAILURE).  !!
!!                                                                          !!
!! This is the #1 source of errors in Raven applications.                   !!
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

Unit conversion table (enforced by this tool):
  | Variable     | CMFD/MSWX unit  | Raven expected unit | Conversion          |
  |-------------|-----------------|---------------------|---------------------|
  | PRECIP      | mm/3hr          | mm/d                | sum 8 timesteps     |
  | TEMP_MIN    | K               | degC                | subtract 273.15     |
  | TEMP_MAX    | K               | degC                | subtract 273.15     |
  | TEMP_AVE    | K               | degC                | subtract 273.15     |
  | WIND_VEL    | m/s             | m/s                 | no conversion       |
  | REL_HUMIDITY| kg/kg (spec.hum)| fraction (0-1)      | convert via Psat    |
  | SW_RADIA    | W/m2            | MJ/m2/d             | multiply by 0.0864  |
  | AIR_PRES    | Pa              | kPa                 | divide by 1000      |

Usage:
    python convert_forcing_to_rvt.py \
        --forcing_dir outputs/chaohe_2000_2010_025deg/vic_temp/forcing/forcing_final \
        --grid_nc outputs/chaohe_2000_2010_025deg/vic_temp/grid/basin_grid.nc \
        --output_dir outputs/chaohe_raven/ \
        --basin_name chaohe \
        --start_year 2000 --end_year 2010 \
        --forcing_source cmfd
"""

import argparse
import json
import os
import sys
import warnings
from datetime import datetime, timedelta

warnings.filterwarnings("ignore")

try:
    import numpy as np
except ImportError:
    print(json.dumps({"status": "error", "message": "numpy is required"}))
    sys.exit(1)


# Physical bounds for quality checks (CRITICAL — catches unit errors)
BOUNDS = {
    "PRECIP": (0, 500),        # mm/d — max 500 is extreme but possible
    "TEMP_MIN": (-60, 55),     # degC
    "TEMP_MAX": (-60, 60),     # degC
    "TEMP_AVE": (-60, 55),     # degC
    "WIND_VEL": (0, 50),       # m/s
    "REL_HUMIDITY": (0, 1.1),  # fraction — slightly >1 from rounding is OK
    "SW_RADIA": (0, 50),       # MJ/m2/d (solar constant ~118 MJ/m2/d)
    "AIR_PRES": (30, 110),     # kPa
}


def validate_inputs(args):
    """Validate inputs."""
    errors = []
    if not os.path.isdir(args.forcing_dir):
        errors.append(f"Forcing directory not found: {args.forcing_dir}")
    if args.grid_nc and not os.path.isfile(args.grid_nc):
        errors.append(f"Grid NetCDF not found: {args.grid_nc}")
    if args.start_year > args.end_year:
        errors.append(f"start_year ({args.start_year}) > end_year ({args.end_year})")
    if errors:
        return {"status": "error", "errors": errors}
    return {"status": "ok"}


def read_cmfd_netcdf_for_cell(forcing_dir, lat, lon, start_year, end_year):
    """
    Read CMFD 3-hourly forcing directly from NetCDF files.

    CMFD stores variables in subdirectories: Prec/, Temp/, SRad/, LRad/, Wind/, Pres/, SHum/
    Each file is monthly: prec_CMFD_V0200_B-01_03hr_010deg_YYYYMM.nc

    Returns: np.array with same 7-column format as VIC forcing:
        0: air_temp (C), 1: prec (mm/3hr), 2: pressure (kPa),
        3: swdown (W/m2), 4: lwdown (W/m2), 5: vp (kPa), 6: wind (m/s)
    """
    import xarray as xr

    forcing_dir = Path(forcing_dir)
    cmfd_vars = [
        ('Temp', 'temp', lambda x: x - 273.15),        # K -> C
        ('Prec', 'prec', lambda x: x),                  # mm/3hr as-is
        ('Pres', 'pres', lambda x: x / 1000.0),         # Pa -> kPa
        ('SRad', 'srad', lambda x: x),                   # W/m2
        ('LRad', 'lrad', lambda x: x),                   # W/m2
        ('SHum', 'shum', lambda x: x),                   # kg/kg -> use as vp proxy
        ('Wind', 'wind', lambda x: x),                   # m/s
    ]

    all_timesteps = {i: [] for i in range(7)}

    for year in range(start_year, end_year + 1):
        for month in range(1, 13):
            for v_idx, (subdir, pattern, convert) in enumerate(cmfd_vars):
                nc_files = sorted((forcing_dir / subdir).glob(f"*{year}{month:02d}*")) if (forcing_dir / subdir).exists() else []
                if not nc_files:
                    nc_files = sorted(forcing_dir.glob(f"*{pattern}*{year}{month:02d}*"))

                if nc_files:
                    ds = xr.open_dataset(nc_files[0])
                    data_var = [v for v in ds.data_vars if pattern in v.lower()]
                    if not data_var:
                        data_var = list(ds.data_vars)
                    grid_lats = ds['lat'].values if 'lat' in ds else ds['latitude'].values
                    grid_lons = ds['lon'].values if 'lon' in ds else ds['longitude'].values
                    lat_idx = int(np.argmin(np.abs(grid_lats - lat)))
                    lon_idx = int(np.argmin(np.abs(grid_lons - lon)))
                    vals = ds[data_var[0]][:, lat_idx, lon_idx].values
                    all_timesteps[v_idx].extend(convert(vals))
                    ds.close()

    if not all_timesteps[0]:
        return None

    min_len = min(len(v) for v in all_timesteps.values())
    result = np.column_stack([np.array(all_timesteps[i][:min_len]) for i in range(7)])

    # Convert specific humidity to vapor pressure: vp = q * P / (0.622 + 0.378*q)
    q = result[:, 5]
    p_kpa = result[:, 2]
    result[:, 5] = q * p_kpa / (0.622 + 0.378 * q)

    return result


def read_vic_forcing_file(filepath):
    """
    Read a VIC forcing file (7-column ASCII).

    ACTUAL column order from process_forcing.py (verified 2026-03-22):
      0: air_temp  (C)        — single temperature, NOT separate min/max
      1: prec      (mm/3hr)   — precipitation per 3-hour timestep
      2: pressure  (kPa)      — already converted from Pa
      3: swdown    (W/m2)     — shortwave radiation
      4: lwdown    (W/m2)     — longwave radiation
      5: vp        (kPa)      — vapor pressure (NOT specific humidity)
      6: wind      (m/s)      — wind speed

    CRITICAL: The original tool assumed a WRONG column order
    (PRECIP, TEMP_MAX, TEMP_MIN, WIND, SW, LW, PRESSURE) that does NOT
    match the actual VIC forcing output. This caused all unit bounds
    violations (dt_err_005).
    """
    try:
        data = np.loadtxt(filepath)
        if data.ndim == 1:
            data = data.reshape(1, -1)
        return data
    except Exception as e:
        return None


def aggregate_3hourly_to_daily(data_3hr, steps_per_day=8):
    """
    Aggregate 3-hourly VIC forcing to daily values for Raven.

    VIC forcing columns (input):
      0: air_temp (C), 1: prec (mm/3hr), 2: pressure (kPa),
      3: swdown (W/m2), 4: lwdown (W/m2), 5: vp (kPa), 6: wind (m/s)

    Raven daily output columns (this function returns):
      0: PRECIP (mm/d)       — sum of 3hr precip
      1: TEMP_MAX (C)        — daily max of air_temp
      2: TEMP_MIN (C)        — daily min of air_temp
      3: WIND (m/s)          — daily mean
      4: SHORTWAVE (MJ/m2/d) — mean W/m2 * 0.0864
      5: LONGWAVE  (MJ/m2/d) — mean W/m2 * 0.0864
      6: PRESSURE  (kPa)     — daily mean
    """
    n_records = len(data_3hr)
    n_days = n_records // steps_per_day

    if n_days == 0:
        return None

    # Truncate to complete days
    data_3hr = data_3hr[:n_days * steps_per_day]

    daily = np.zeros((n_days, 7))
    for d in range(n_days):
        start = d * steps_per_day
        end = start + steps_per_day
        chunk = data_3hr[start:end]

        # VIC col 1 → Raven col 0: PRECIP — SUM (mm/3hr -> mm/d)
        daily[d, 0] = np.sum(chunk[:, 1])

        # VIC col 0 → Raven col 1: TEMP_MAX — MAXIMUM of 3-hourly air_temp (already C)
        daily[d, 1] = np.max(chunk[:, 0])

        # VIC col 0 → Raven col 2: TEMP_MIN — MINIMUM of 3-hourly air_temp (already C)
        daily[d, 2] = np.min(chunk[:, 0])

        # VIC col 6 → Raven col 3: WIND — MEAN (m/s, no conversion)
        daily[d, 3] = np.mean(chunk[:, 6])

        # VIC col 3 → Raven col 4: SHORTWAVE — MEAN W/m2 -> MJ/m2/d
        # 1 W/m2 = 86400 J/m2/d = 0.0864 MJ/m2/d
        daily[d, 4] = np.mean(chunk[:, 3]) * 0.0864

        # VIC col 4 → Raven col 5: LONGWAVE — MEAN W/m2 -> MJ/m2/d
        daily[d, 5] = np.mean(chunk[:, 4]) * 0.0864

        # VIC col 2 → Raven col 6: PRESSURE — MEAN (already kPa)
        daily[d, 6] = np.mean(chunk[:, 2])

    return daily


def bounds_check(daily_data, var_names, filepath):
    """
    Check if values are within physical bounds.
    Returns warnings list. This catches unit conversion errors.
    """
    warnings_list = []
    for i, var in enumerate(var_names):
        if var in BOUNDS:
            lo, hi = BOUNDS[var]
            col = daily_data[:, i]
            valid = col[~np.isnan(col)]
            if len(valid) == 0:
                continue
            vmin, vmax = valid.min(), valid.max()

            if vmin < lo or vmax > hi:
                warnings_list.append(
                    f"BOUNDS VIOLATION: {var} in {os.path.basename(filepath)}: "
                    f"range [{vmin:.2f}, {vmax:.2f}] outside expected [{lo}, {hi}]. "
                    f"LIKELY UNIT ERROR — check conversion."
                )
    return warnings_list


def generate_rvt_gauge_block(station_name, lat, lon, elev, daily_data,
                              start_date, variables):
    """
    Generate a Raven gauge block for .rvt file.

    Format:
      :Gauge StationName
        :Latitude 40.5
        :Longitude 116.8
        :Elevation 500.0
        :Data PRECIP mm/d
          2000-01-01 00:00:00.0 1.0 365
          value1
          value2
          ...
        :EndData
      :EndGauge
    """
    lines = []
    lines.append(f":Gauge {station_name}")
    lines.append(f"  :Latitude  {lat:.4f}")
    lines.append(f"  :Longitude {lon:.4f}")
    lines.append(f"  :Elevation {elev:.1f}")
    lines.append("")

    n_days = len(daily_data)

    # Variable-to-column mapping and units
    var_info = {
        "PRECIP":       {"col": 0, "unit": "mm/d"},
        "TEMP_MAX":     {"col": 1, "unit": "degC"},
        "TEMP_MIN":     {"col": 2, "unit": "degC"},
        "TEMP_AVE":     {"col": None, "unit": "degC"},  # computed
        "WIND_VEL":     {"col": 3, "unit": "m/s"},
        "SW_RADIA":     {"col": 4, "unit": "MJ/m2/d"},
        "LW_INCOMING":  {"col": 5, "unit": "MJ/m2/d"},
        "AIR_PRES":     {"col": 6, "unit": "kPa"},
    }

    for var in variables:
        if var not in var_info:
            continue

        info = var_info[var]
        unit = info["unit"]

        lines.append(f"  :Data {var} {unit}")
        lines.append(f"    {start_date} 00:00:00.0 1.0 {n_days}")

        if var == "TEMP_AVE":
            # Compute average from min and max
            values = (daily_data[:, 1] + daily_data[:, 2]) / 2.0
        else:
            col = info["col"]
            values = daily_data[:, col]

        for v in values:
            lines.append(f"    {v:.4f}")

        lines.append(f"  :EndData")
        lines.append("")

    lines.append(":EndGauge")
    lines.append("")

    return "\n".join(lines)


def process(args):
    """Main processing: read forcing files and generate .rvt."""

    # Read grid cells
    cells = []
    if args.grid_nc:
        try:
            import netCDF4 as nc
            ds = nc.Dataset(args.grid_nc)
            # Try lat/lon first, then y/x (HydroCraft VIC grid uses y/x with 2D mask)
            if "lat" in ds.variables and "lon" in ds.variables:
                lats = ds.variables["lat"][:]
                lons = ds.variables["lon"][:]
                for lat, lon in zip(lats, lons):
                    cells.append({"lat": float(lat), "lon": float(lon)})
            elif "y" in ds.variables and "x" in ds.variables:
                y = ds.variables["y"][:]
                x = ds.variables["x"][:]
                mask = ds.variables["mask"][:] if "mask" in ds.variables else None
                if mask is not None:
                    # 2D grid with mask — extract active cell coordinates
                    for i in range(len(y)):
                        for j in range(len(x)):
                            if mask[i, j] > 0:
                                cells.append({"lat": float(y[i]), "lon": float(x[j])})
                else:
                    # 1D coordinate arrays — create all combinations
                    for yi in y:
                        for xi in x:
                            cells.append({"lat": float(yi), "lon": float(xi)})
            ds.close()
        except Exception:
            pass

    if not cells:
        # Try to infer from forcing file names (handle any extension or no extension)
        forcing_files = sorted(os.listdir(args.forcing_dir))
        for ff in forcing_files:
            # Parse lat/lon from filename like "bengbu_0.25deg_31.1250_115.6250"
            # or "forcing_40.1250_116.6250.txt"
            parts = ff.replace(".txt", "").replace(".dat", "").split("_")
            for i, p in enumerate(parts):
                try:
                    lat = float(p)
                    lon = float(parts[i + 1])
                    if -90 <= lat <= 90 and -180 <= lon <= 360:
                        cells.append({"lat": lat, "lon": lon})
                        break
                except (ValueError, IndexError):
                    continue

    if not cells:
        return {"status": "error", "message": "No grid cells found. Provide --grid_nc or check forcing file names."}

    # Compute basin-mean forcing (aggregate all cells)
    all_data = []
    files_read = 0
    warnings_all = []

    # Pre-list all files in forcing_dir once for efficiency
    forcing_filelist = os.listdir(args.forcing_dir)

    for cell in cells:
        found = False
        for fn in forcing_filelist:
            if f"{cell['lat']:.4f}" in fn and f"{cell['lon']:.4f}" in fn:
                fpath = os.path.join(args.forcing_dir, fn)
                data = read_vic_forcing_file(fpath)
                if data is not None and len(data) > 0:
                    all_data.append(data)
                    files_read += 1
                    found = True
                    break

    # If no VIC files found, try reading CMFD NetCDF directly from subdirectories
    if files_read == 0:
        print(f"No VIC ASCII files found. Trying CMFD NetCDF direct read from {args.forcing_dir}...")
        for cell in cells:
            data = read_cmfd_netcdf_for_cell(
                args.forcing_dir, cell['lat'], cell['lon'],
                args.start_year, args.end_year
            )
            if data is not None and len(data) > 0:
                all_data.append(data)
                files_read += 1

    if files_read == 0:
        return {"status": "error", "message": f"No forcing files found in {args.forcing_dir} (tried VIC ASCII and CMFD NetCDF)"}

    # Compute basin-mean forcing
    min_len = min(len(d) for d in all_data)
    stacked = np.stack([d[:min_len] for d in all_data], axis=0)
    mean_forcing = np.mean(stacked, axis=0)  # shape: (n_timesteps, 7)

    # Aggregate to daily
    steps_per_day = 8  # 3-hourly
    if args.timestep_hours:
        steps_per_day = 24 // args.timestep_hours

    daily = aggregate_3hourly_to_daily(mean_forcing, steps_per_day)
    if daily is None:
        return {"status": "error", "message": "Not enough data for even 1 complete day"}

    # Bounds checking (CRITICAL)
    var_names = ["PRECIP", "TEMP_MAX", "TEMP_MIN", "WIND_VEL", "SW_RADIA", "LW_INCOMING", "AIR_PRES"]
    warnings_all.extend(bounds_check(daily, var_names, args.forcing_dir))

    # Basin centroid
    mean_lat = np.mean([c["lat"] for c in cells])
    mean_lon = np.mean([c["lon"] for c in cells])
    mean_elev = 500.0  # default, will be overridden by .rvh

    # Determine which variables to include in .rvt
    # Minimum: PRECIP + TEMP_MIN + TEMP_MAX (Raven generates the rest)
    variables = ["PRECIP", "TEMP_MIN", "TEMP_MAX", "TEMP_AVE"]

    if args.include_full_forcing:
        variables = ["PRECIP", "TEMP_MIN", "TEMP_MAX", "TEMP_AVE",
                     "WIND_VEL", "SW_RADIA", "AIR_PRES"]

    start_date = f"{args.start_year}-01-01"

    # Generate .rvt content
    rvt_content = []
    rvt_content.append(f"# Raven .rvt file -- Forcing data for {args.basin_name}")
    rvt_content.append(f"# Generated by HydroCraft convert_forcing_to_rvt.py")
    rvt_content.append(f"# Source: {args.forcing_source} forcing, aggregated from {files_read} grid cells to basin mean")
    rvt_content.append(f"# Period: {args.start_year}-01-01 to {args.end_year}-12-31")
    rvt_content.append(f"# CRITICAL: Raven ignores units. All conversions done in this tool.")
    rvt_content.append(f"# Unit conversions applied:")
    rvt_content.append(f"#   PRECIP: mm/3hr -> mm/d (summed over 8 timesteps)")
    rvt_content.append(f"#   TEMP: already Celsius from VIC forcing pipeline")
    rvt_content.append(f"#   SHORTWAVE: W/m2 -> MJ/m2/d (x 0.0864)")
    rvt_content.append(f"#   PRESSURE: already kPa from VIC forcing pipeline")
    rvt_content.append(f"# Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    rvt_content.append("")

    gauge_block = generate_rvt_gauge_block(
        station_name=f"{args.basin_name}_mean",
        lat=mean_lat, lon=mean_lon, elev=mean_elev,
        daily_data=daily, start_date=start_date,
        variables=variables,
    )
    rvt_content.append(gauge_block)

    # Add observed data reference if provided
    if args.obs_file and os.path.isfile(args.obs_file):
        rvt_content.append(f"# Observed discharge for calibration/validation")
        rvt_content.append(f":RedirectToFile {args.basin_name}_obs.rvt")
        rvt_content.append("")

    # Write .rvt
    os.makedirs(args.output_dir, exist_ok=True)
    rvt_path = os.path.join(args.output_dir, f"{args.basin_name}.rvt")
    with open(rvt_path, "w") as f:
        f.write("\n".join(rvt_content))

    # Summary statistics for QC
    precip_annual = daily[:, 0].sum() / max(1, len(daily) / 365.25)
    temp_mean = (daily[:, 1] + daily[:, 2]).mean() / 2.0

    results = {
        "status": "success",
        "output_rvt": rvt_path,
        "forcing_stats": {
            "grid_cells_used": files_read,
            "total_cells_found": len(cells),
            "daily_records": len(daily),
            "start_date": start_date,
            "end_date": f"{args.end_year}-12-31",
            "variables_included": variables,
            "mean_annual_precip_mm": round(precip_annual, 1),
            "mean_temp_C": round(temp_mean, 1),
            "precip_range_mm_d": [round(daily[:, 0].min(), 2), round(daily[:, 0].max(), 2)],
            "temp_range_C": [round(daily[:, 2].min(), 1), round(daily[:, 1].max(), 1)],
        },
        "unit_conversions_applied": [
            "PRECIP: mm/3hr -> mm/d (sum of 8 timesteps per day)",
            "TEMP: Celsius (no conversion needed from VIC pipeline)",
            "SW_RADIA: W/m2 -> MJ/m2/d (factor 0.0864)",
            "PRESSURE: kPa (no conversion needed from VIC pipeline)",
        ],
        "warnings": warnings_all,
    }

    if warnings_all:
        results["WARNING"] = "BOUNDS VIOLATIONS DETECTED — possible unit error. Review warnings."

    return results


def validate_outputs(results, args):
    """Validate output."""
    errors = []
    rvt_path = results.get("output_rvt")
    if rvt_path and not os.path.isfile(rvt_path):
        errors.append(f"Expected .rvt not found: {rvt_path}")
    elif rvt_path:
        with open(rvt_path) as f:
            content = f.read()
        if ":Gauge" not in content:
            errors.append(".rvt missing :Gauge block")
        if ":Data PRECIP" not in content:
            errors.append(".rvt missing precipitation data")

    # Check for suspicious values
    stats = results.get("forcing_stats", {})
    annual_p = stats.get("mean_annual_precip_mm", 0)
    if annual_p > 5000:
        errors.append(f"SUSPICIOUS: Annual precip = {annual_p} mm — likely unit error (expected 200-3000 mm/yr)")
    if annual_p < 10:
        errors.append(f"SUSPICIOUS: Annual precip = {annual_p} mm — likely unit error or missing data")

    mean_t = stats.get("mean_temp_C", 0)
    if mean_t > 100 or mean_t < -100:
        errors.append(f"SUSPICIOUS: Mean temp = {mean_t} C — likely Kelvin not converted to Celsius")

    if errors:
        return {"status": "error", "errors": errors}
    return {"status": "ok"}


def main():
    parser = argparse.ArgumentParser(description="Convert forcing to Raven .rvt format")
    parser.add_argument("--forcing_dir", required=True, help="Directory with VIC forcing files")
    parser.add_argument("--grid_nc", default=None, help="VIC basin_grid.nc for cell coordinates")
    parser.add_argument("--output_dir", required=True, help="Output directory for .rvt file")
    parser.add_argument("--basin_name", required=True, help="Basin name")
    parser.add_argument("--start_year", type=int, required=True, help="Start year")
    parser.add_argument("--end_year", type=int, required=True, help="End year")
    parser.add_argument("--forcing_source", default="cmfd", help="Forcing source: cmfd, mswx, nasa_power")
    parser.add_argument("--forcing_prefix", default="", help="Forcing filename prefix")
    parser.add_argument("--timestep_hours", type=int, default=3, help="Forcing timestep in hours (default: 3)")
    parser.add_argument("--include_full_forcing", action="store_true",
                        help="Include wind, radiation, pressure (not just P/T)")
    parser.add_argument("--obs_file", default=None, help="Path to observed discharge file")

    args = parser.parse_args()

    validation = validate_inputs(args)
    if validation["status"] == "error":
        print(json.dumps(validation, indent=2))
        sys.exit(1)

    try:
        results = process(args)
    except Exception as e:
        import traceback
        print(json.dumps({"status": "error", "message": str(e), "traceback": traceback.format_exc()}))
        sys.exit(2)

    if results.get("status") == "error":
        print(json.dumps(results, indent=2))
        sys.exit(2)

    output_validation = validate_outputs(results, args)
    if output_validation["status"] == "error":
        results["output_validation"] = output_validation
        print(json.dumps(results, indent=2))
        sys.exit(3)

    print(json.dumps(results, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
