#!/usr/bin/env python3
"""
S3b: Convert projected forcing NetCDF → VIC ASCII format.

After apply_deltas_forcing.py produces projected NC files (monthly, 3-hourly),
this tool converts them to per-grid-cell ASCII files that VIC can read directly.

Usage:
    python convert_projected_forcing.py \
        <input_dir> <output_dir> <soil_file> <forcing_prefix> <basin_tag> \
        <start_year> <end_year>

Example:
    python convert_projected_forcing.py \
        outputs/nuxia/climate_projection/forcing_ACCESS-CM2_126 \
        outputs/nuxia/climate_projection/forcing_final_ACCESS-CM2_126 \
        outputs/nuxia/vic_temp/soil/SOIL_PARAM_COMPLETE.txt \
        "nuxia_01dy_025deg_" "nuxia" 2041 2070
"""

import sys
import glob
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

warnings.filterwarnings("ignore")

# ---------------------------------------------------------------------------
# Configuration (overridden by sys.argv)
# ---------------------------------------------------------------------------
INPUT_DIR = ""
OUTPUT_DIR = ""
SOIL_FILE = ""
FORCING_PREFIX = ""
BASIN_TAG = ""
START_YEAR = 2041
END_YEAR = 2070

if len(sys.argv) >= 8:
    INPUT_DIR = sys.argv[1]
    OUTPUT_DIR = sys.argv[2]
    SOIL_FILE = sys.argv[3]
    FORCING_PREFIX = sys.argv[4]
    BASIN_TAG = sys.argv[5]
    START_YEAR = int(sys.argv[6])
    END_YEAR = int(sys.argv[7])

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    input_dir = Path(INPUT_DIR)
    output_dir = Path(OUTPUT_DIR)
    soil_file = Path(SOIL_FILE)

    if not input_dir.exists():
        print(f"ERROR: Input directory not found: {input_dir}")
        sys.exit(1)
    if not soil_file.exists():
        print(f"ERROR: Soil file not found: {soil_file}")
        sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)

    # Read grid cell coordinates from soil file
    df_soil = pd.read_csv(
        soil_file, sep=r"\s+", header=None,
        usecols=[0, 1, 2, 3],
        names=["run_cell", "grid_id", "lat", "lon"],
    )
    n_cells = len(df_soil)
    print(f"Grid cells: {n_cells}")
    print(f"Period: {START_YEAR}-{END_YEAR}")

    # Load all variables from monthly NC files
    var_names = ["prec", "temp", "pres", "srad", "lrad", "shum", "wind"]
    all_ds = []
    available_vars = []

    for var in var_names:
        var_files = sorted(glob.glob(str(input_dir / f"{var}_*_{BASIN_TAG}*.nc")))
        if not var_files:
            print(f"  WARNING: No files found for variable '{var}', will use defaults")
            continue
        print(f"  Loading {var}: {len(var_files)} files")
        ds_list = []
        for f in var_files:
            ds = xr.open_dataset(f, engine="netcdf4")
            # Drop spatial_ref if present (from rasterio-based writes)
            for drop_var in ["spatial_ref"]:
                if drop_var in ds.coords:
                    ds = ds.drop_vars(drop_var)
                if drop_var in ds.data_vars:
                    ds = ds.drop_vars(drop_var)
            ds_list.append(ds)
        ds_var = xr.concat(ds_list, dim="time")
        all_ds.append(ds_var)
        available_vars.append(var)

    if not all_ds:
        print("ERROR: No forcing variables found!")
        sys.exit(1)

    # Merge all variables and select time range
    start_date = f"{START_YEAR}-01-01"
    end_date = f"{END_YEAR}-12-31"
    ds_m = xr.merge(all_ds).sortby("time").sel(time=slice(start_date, end_date))

    # Detect coordinate dimension names
    lat_dim = "y" if "y" in ds_m.coords else "lat"
    lon_dim = "x" if "x" in ds_m.coords else "lon"

    print(f"  Time steps: {len(ds_m.time)}")
    print(f"  Variables: {available_vars}")
    print(f"  Converting to VIC ASCII...")

    # Convert each grid cell
    success = 0
    for idx, row in df_soil.iterrows():
        lat, lon = row["lat"], row["lon"]
        try:
            cell = ds_m.sel(
                {lat_dim: lat, lon_dim: lon},
                method="nearest", tolerance=0.13,
            ).compute()
            df = cell.to_dataframe()
            df_out = pd.DataFrame(index=df.index)

            # Temperature: K → C
            df_out["air_temp"] = df["temp"] - 273.15 if "temp" in df.columns else 20.0

            # Precipitation: kg/m2/s → mm/timestep (3hr = 10800s)
            df_out["prec"] = df["prec"] * 10800 if "prec" in df.columns else 0.0

            # Pressure: Pa → kPa
            df_out["pressure"] = df["pres"] / 1000.0 if "pres" in df.columns else 101.3

            # Shortwave radiation (W/m2, pass through)
            df_out["swdown"] = df["srad"] if "srad" in df.columns else 150.0

            # Longwave radiation (W/m2, pass through or estimate from T)
            if "lrad" in df.columns:
                df_out["lwdown"] = df["lrad"]
            else:
                T_k = df["temp"] if "temp" in df.columns else 293.15
                df_out["lwdown"] = 5.67e-8 * (T_k ** 4)

            # Vapor pressure from specific humidity
            if "shum" in df.columns and "pres" in df.columns:
                q, P = df["shum"], df["pres"]
                df_out["vp"] = (q * P / (0.622 + 0.378 * q)) / 1000.0
            else:
                T = df_out["air_temp"]
                df_out["vp"] = 6.1094 * np.exp(17.625 * T / (T + 243.04)) * 0.5 / 10.0

            # Wind speed (m/s, pass through)
            if "wind" in df.columns:
                df_out["wind"] = df["wind"].fillna(2.0)
            else:
                df_out["wind"] = 2.0

            # Write VIC forcing: 7 columns, no header
            vic_df = df_out[["air_temp", "prec", "pressure", "swdown", "lwdown", "vp", "wind"]].fillna(0)
            out_path = output_dir / f"{FORCING_PREFIX}{lat:.4f}_{lon:.4f}"
            vic_df.to_csv(out_path, sep="\t", header=False, index=False, float_format="%.4f")
            success += 1
        except Exception as e:
            pass

    print(f"Converted: {success}/{n_cells} cells")
    if success == 0:
        print("ERROR: No cells converted! Check coordinate alignment.")
        sys.exit(2)
    elif success < n_cells:
        print(f"WARNING: {n_cells - success} cells failed (may be outside forcing coverage)")


if __name__ == "__main__":
    main()
