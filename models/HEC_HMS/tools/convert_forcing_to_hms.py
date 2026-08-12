#!/usr/bin/env python3
"""
Convert CMFD/MSWX forcing data to HEC-HMS input format.

Reads NetCDF forcing files (precipitation, temperature, radiation) and produces
basin-averaged daily CSV suitable for HEC-HMS SCS-CN continuous simulation.

Unit conversions applied:
  - Precipitation: CMFD mm/day → mm/day (no conversion needed for daily)
  - Temperature: CMFD Kelvin → Celsius (subtract 273.15)
  - Radiation: CMFD W/m² → MJ/m²/day (multiply by 0.0864)
  - PET: Computed via Hargreaves equation from Tmin, Tmax, radiation

Usage:
  python3 convert_forcing_to_hms.py \
    --forcing_dir /path/to/cmfd/ \
    --basin_shp /path/to/basin.shp \
    --start_date 1980-01-01 --end_date 1990-12-31 \
    --output_dir ./forcing_out/
"""

import argparse
import json
import os
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=RuntimeWarning)


# ---------------------------------------------------------------------------
# Validate inputs
# ---------------------------------------------------------------------------
def validate_inputs(args):
    """Check all input paths and parameters exist and are valid."""
    errors = []

    if not os.path.isdir(args.forcing_dir):
        errors.append(f"Forcing directory not found: {args.forcing_dir}")

    if not os.path.isfile(args.basin_shp):
        errors.append(f"Basin shapefile not found: {args.basin_shp}")

    try:
        pd.Timestamp(args.start_date)
        pd.Timestamp(args.end_date)
    except Exception as e:
        errors.append(f"Invalid date format: {e}")

    if pd.Timestamp(args.start_date) >= pd.Timestamp(args.end_date):
        errors.append("start_date must be before end_date")

    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"[validate_inputs] All inputs valid.")
    print(f"  Forcing dir: {args.forcing_dir}")
    print(f"  Basin shp:   {args.basin_shp}")
    print(f"  Period:       {args.start_date} to {args.end_date}")


# ---------------------------------------------------------------------------
# Read basin geometry
# ---------------------------------------------------------------------------
def read_basin_mask(basin_shp, resolution=0.25):
    """Read basin shapefile and create a spatial mask at given resolution."""
    import geopandas as gpd
    from shapely.geometry import box

    gdf = gpd.read_file(basin_shp)
    gdf = gdf.to_crs(epsg=4326)

    bounds = gdf.total_bounds  # minx, miny, maxx, maxy
    print(f"[read_basin_mask] Basin bounds: {bounds}")

    # Compute basin area in km²
    gdf_proj = gdf.to_crs(epsg=6933)  # Equal-area projection
    area_km2 = gdf_proj.area.sum() / 1e6
    print(f"[read_basin_mask] Basin area: {area_km2:.1f} km²")

    return gdf, bounds, area_km2


# ---------------------------------------------------------------------------
# Read CMFD NetCDF forcing
# ---------------------------------------------------------------------------
def read_cmfd_forcing(forcing_dir, bounds, start_date, end_date):
    """
    Read CMFD daily forcing NetCDF files and extract basin-average time series.

    CMFD file naming: {var}_CMFD_V0106_B-01_01dy_025deg_{yyyy}.nc
    Variables: prec (mm/day), temp (K), srad (W/m²)
    """
    import xarray as xr

    start_year = pd.Timestamp(start_date).year
    end_year = pd.Timestamp(end_date).year

    minx, miny, maxx, maxy = bounds
    # Add buffer for cell centers
    buf = 0.25
    lon_slice = slice(minx - buf, maxx + buf)
    lat_slice = slice(miny - buf, maxy + buf)

    var_map = {
        "prec": "prec",
        "temp": "temp",
        "srad": "srad",
    }

    all_data = {v: [] for v in var_map}

    forcing_dir = Path(forcing_dir)
    for year in range(start_year, end_year + 1):
        for var_key, var_name in var_map.items():
            # Try multiple naming patterns
            patterns = [
                f"{var_key}_CMFD_*_025deg_{year}.nc",
                f"{var_key}*{year}*.nc",
                f"{var_name}*{year}*.nc",
            ]
            nc_file = None
            for pat in patterns:
                matches = list(forcing_dir.glob(pat))
                if matches:
                    nc_file = matches[0]
                    break

            if nc_file is None:
                print(f"  WARNING: No {var_key} file for {year}, skipping")
                continue

            try:
                try:
                    ds = xr.open_dataset(nc_file, engine="h5netcdf")
                except Exception:
                    ds = xr.open_dataset(nc_file)
                # Handle different coordinate names
                lon_name = "lon" if "lon" in ds.dims else "longitude"
                lat_name = "lat" if "lat" in ds.dims else "latitude"

                # Select spatial subset
                ds_sub = ds.sel(
                    **{lon_name: lon_slice, lat_name: lat_slice}
                )

                # Get the data variable (first non-coordinate variable)
                data_vars = [v for v in ds_sub.data_vars]
                if data_vars:
                    da = ds_sub[data_vars[0]]
                    # Basin average (simple mean over spatial dims)
                    basin_avg = da.mean(dim=[lon_name, lat_name])
                    all_data[var_key].append(basin_avg)

                ds.close()
            except Exception as e:
                print(f"  WARNING: Error reading {nc_file}: {e}")

    # Concatenate along time
    result = {}
    for var_key, da_list in all_data.items():
        if da_list:
            combined = xr.concat(da_list, dim="time")
            result[var_key] = combined

    return result


# ---------------------------------------------------------------------------
# Unit conversions
# ---------------------------------------------------------------------------
def convert_units(data_dict):
    """
    Apply unit conversions:
      prec: mm/day (CMFD) → mm/day (no change)
      temp: K (CMFD) → °C (subtract 273.15)
      srad: W/m² (CMFD) → MJ/m²/day (multiply 0.0864)
    """
    converted = {}

    if "prec" in data_dict:
        prec = data_dict["prec"].values.copy()
        prec = np.maximum(prec, 0.0)  # No negative precipitation
        # dt_101: actual CMFD NetCDF precip is a RATE in kg/m2/s (= mm/s),
        # NOT mm/day as some docs state. Detect by magnitude and convert.
        if np.nanmean(prec) < 0.1:
            prec = prec * 86400.0
            print("[convert_units] Precip rate kg/m2/s detected -> x86400 to mm/day")
        converted["prec_mm"] = prec
        print(f"[convert_units] Precip: mean={np.nanmean(prec):.2f} mm/day, "
              f"max={np.nanmax(prec):.1f} mm/day")

    if "temp" in data_dict:
        temp_k = data_dict["temp"].values.copy()
        # CRITICAL: Convert Kelvin to Celsius (dt_102)
        if np.nanmean(temp_k) > 100:
            temp_c = temp_k - 273.15
            print(f"[convert_units] Temperature: Kelvin detected (mean={np.nanmean(temp_k):.1f}K), "
                  f"converting to Celsius (mean={np.nanmean(temp_c):.1f}°C)")
        else:
            temp_c = temp_k
            print(f"[convert_units] Temperature: already Celsius (mean={np.nanmean(temp_c):.1f}°C)")
        converted["temp_c"] = temp_c

    if "srad" in data_dict:
        srad = data_dict["srad"].values.copy()
        srad = np.maximum(srad, 0.0)
        # Convert W/m² → MJ/m²/day (dt_110)
        srad_mj = srad * 0.0864
        converted["srad_mj"] = srad_mj
        print(f"[convert_units] Radiation: {np.nanmean(srad):.1f} W/m² → "
              f"{np.nanmean(srad_mj):.2f} MJ/m²/day")

    return converted


# ---------------------------------------------------------------------------
# PET computation (Hargreaves)
# ---------------------------------------------------------------------------
def compute_pet_hargreaves(temp_c, srad_mj, lat_deg=33.0):
    """
    Compute potential evapotranspiration using Hargreaves equation.

    PET = 0.0023 * (T_mean + 17.8) * (T_max - T_min)^0.5 * Ra
    Simplified for daily mean temperature (assume Trange ~ 10°C):
    PET = 0.0023 * (T + 17.8) * 10^0.5 * Ra
    Where Ra is extraterrestrial radiation ≈ srad_mj / 0.5 (rough approximation)
    """
    t_range = 10.0  # Assumed daily temperature range (°C)
    # Hargreaves equation
    pet = 0.0023 * (temp_c + 17.8) * np.sqrt(t_range) * srad_mj
    pet = np.maximum(pet, 0.0)

    # Clip unrealistic values (dt_118)
    pet = np.minimum(pet, 15.0)  # Max ~15 mm/day

    print(f"[compute_pet] PET: mean={np.nanmean(pet):.2f} mm/day, "
          f"max={np.nanmax(pet):.1f} mm/day")
    return pet


# ---------------------------------------------------------------------------
# Build output DataFrame
# ---------------------------------------------------------------------------
def build_forcing_csv(data_dict, converted, pet, start_date, end_date):
    """Build daily forcing CSV with columns: date, precip_mm, temp_c, pet_mm."""
    time_index = pd.date_range(start_date, end_date, freq="D")

    # Handle length mismatch
    n = min(len(time_index), len(converted.get("prec_mm", [])))
    if n == 0:
        print("ERROR: No forcing data available for the specified period", file=sys.stderr)
        sys.exit(1)

    df = pd.DataFrame(index=time_index[:n])
    df.index.name = "date"

    if "prec_mm" in converted:
        df["precip_mm"] = converted["prec_mm"][:n]
    if "temp_c" in converted:
        df["temp_c"] = converted["temp_c"][:n]
    if pet is not None:
        df["pet_mm"] = pet[:n]

    # Fill NaN with 0 for precip, interpolate for temp/pet
    if "precip_mm" in df.columns:
        df["precip_mm"] = df["precip_mm"].fillna(0.0)
    if "temp_c" in df.columns:
        df["temp_c"] = df["temp_c"].interpolate(method="linear").fillna(method="bfill").fillna(method="ffill")
    if "pet_mm" in df.columns:
        df["pet_mm"] = df["pet_mm"].interpolate(method="linear").fillna(method="bfill").fillna(method="ffill")

    return df


# ---------------------------------------------------------------------------
# Validate outputs
# ---------------------------------------------------------------------------
def validate_outputs(df, output_dir):
    """Check output CSV for unrealistic values."""
    warnings_list = []

    if "precip_mm" in df.columns:
        annual_precip = df["precip_mm"].sum() / (len(df) / 365.25)
        if annual_precip < 100:
            warnings_list.append(f"Annual precip very low: {annual_precip:.0f} mm/yr (expected 400-2000)")
        if annual_precip > 5000:
            warnings_list.append(f"Annual precip very high: {annual_precip:.0f} mm/yr (check units!)")
        if df["precip_mm"].max() > 500:
            warnings_list.append(f"Max daily precip = {df['precip_mm'].max():.0f} mm (>500 is extreme)")
        print(f"[validate_outputs] Annual precipitation: {annual_precip:.0f} mm/yr")

    if "temp_c" in df.columns:
        t_mean = df["temp_c"].mean()
        if t_mean > 50 or t_mean < -30:
            warnings_list.append(f"Mean temperature {t_mean:.1f}°C is unrealistic — check Kelvin conversion!")
        print(f"[validate_outputs] Mean temperature: {t_mean:.1f}°C")

    if "pet_mm" in df.columns:
        annual_pet = df["pet_mm"].sum() / (len(df) / 365.25)
        print(f"[validate_outputs] Annual PET: {annual_pet:.0f} mm/yr")
        if annual_pet > 3000:
            warnings_list.append(f"Annual PET very high: {annual_pet:.0f} mm/yr")

    for w in warnings_list:
        print(f"  WARNING: {w}")

    # Check for gaps
    n_missing = df.isna().sum().sum()
    if n_missing > 0:
        warnings_list.append(f"{n_missing} missing values remain after filling")

    return warnings_list


# ---------------------------------------------------------------------------
# Process
# ---------------------------------------------------------------------------
def process(args):
    """Main processing workflow."""
    print("=" * 60)
    print("HEC-HMS Forcing Converter (CMFD → HEC-HMS)")
    print("=" * 60)

    # 1. Read basin mask
    gdf, bounds, area_km2 = read_basin_mask(args.basin_shp)

    # 2. Read CMFD forcing
    print("\n[read_cmfd] Reading CMFD forcing files...")
    data_dict = read_cmfd_forcing(args.forcing_dir, bounds, args.start_date, args.end_date)

    if not data_dict:
        print("ERROR: No forcing data found!", file=sys.stderr)
        sys.exit(1)

    # 3. Convert units
    print("\n[convert_units] Applying unit conversions...")
    converted = convert_units(data_dict)

    # 4. Compute PET
    print("\n[compute_pet] Computing Hargreaves PET...")
    pet = None
    if "temp_c" in converted and "srad_mj" in converted:
        pet = compute_pet_hargreaves(converted["temp_c"], converted["srad_mj"])
    elif "temp_c" in converted:
        # Estimate PET from temperature only (simplified Hargreaves)
        pet = 0.0023 * (converted["temp_c"] + 17.8) * np.sqrt(10.0) * 15.0  # assume 15 MJ/m²/day
        pet = np.maximum(pet, 0.0)
        pet = np.minimum(pet, 15.0)
        print(f"[compute_pet] PET estimated from temperature only: "
              f"mean={np.nanmean(pet):.2f} mm/day")

    # 5. Build CSV
    print("\n[build_csv] Building forcing CSV...")
    df = build_forcing_csv(data_dict, converted, pet, args.start_date, args.end_date)

    # 6. Write output
    os.makedirs(args.output_dir, exist_ok=True)
    out_csv = os.path.join(args.output_dir, "basin_avg_forcing.csv")
    df.to_csv(out_csv)
    print(f"\n[write] Forcing CSV: {out_csv}")
    print(f"  Rows: {len(df)}, Columns: {list(df.columns)}")

    # Write area info
    area_json = os.path.join(args.output_dir, "basin_info.json")
    with open(area_json, "w") as f:
        json.dump({"area_km2": area_km2, "bounds": list(bounds)}, f, indent=2)
    print(f"  Basin info: {area_json}")

    # 7. Validate
    print("\n[validate_outputs] Checking output...")
    warnings_list = validate_outputs(df, args.output_dir)

    result = {
        "status": "success",
        "output_csv": out_csv,
        "n_days": len(df),
        "area_km2": area_km2,
        "warnings": warnings_list,
    }
    print(f"\n{json.dumps(result, indent=2)}")
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Convert CMFD forcing to HEC-HMS format")
    parser.add_argument("--forcing_dir", required=True, help="CMFD forcing directory")
    parser.add_argument("--basin_shp", required=True, help="Basin shapefile path")
    parser.add_argument("--start_date", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end_date", required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument("--output_dir", required=True, help="Output directory")
    args = parser.parse_args()

    validate_inputs(args)
    process(args)


if __name__ == "__main__":
    main()
