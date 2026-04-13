#!/usr/bin/env python3
"""
convert_params_to_prms.py — Convert soil/land use data to PRMS parameter file.

Takes basin delineation (HRU shapefile or CSV), DEM-derived attributes, and soil
data (HWSD/SOILGRIDS) and produces a PRMS parameter file with proper units.

CRITICAL UNIT CONVERSIONS:
  - Area: km2 -> acres (1 km2 = 247.105 acres)
  - Elevation: meters -> feet (ft = m / 0.3048) if elev_units=0
  - Soil depth: mm -> inches (in = mm / 25.4)
  - Slope: degrees -> decimal fraction (fraction = tan(radians(degrees)))

Usage:
  python convert_params_to_prms.py \\
    --hru_file /path/to/hrus.csv \\
    --soil_file /path/to/soil.csv \\
    --output_file /path/to/prms.params \\
    --elev_units 0
"""

import argparse
import math
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
KM2_TO_ACRES = 247.10538146717  # 1 km2 = 247.105 acres
M2_TO_ACRES = KM2_TO_ACRES / 1e6
METERS_TO_FEET = 1.0 / 0.3048  # 3.28084
MM_TO_INCHES = 1.0 / 25.4  # 0.03937

# Default parameter values
DEFAULTS = {
    "hru_type": 1,           # 1=land
    "cov_type": 3,           # 3=trees
    "covden_sum": 0.5,       # summer cover density
    "covden_win": 0.2,       # winter cover density
    "hru_percent_imperv": 0.0,
    "soil_type": 2,          # 2=loam
    "soil_moist_max": 6.0,   # inches
    "soil_rechr_max": 3.0,   # inches
    "soil_rechr_max_frac": 0.5,
    "soil_moist_init_frac": 0.5,
    "soil_rechr_init_frac": 0.5,
    "ssstor_init_frac": 0.1,
    "gwflow_coef": 0.015,
    "gwstor_init": 2.0,      # inches
    "gwstor_min": 0.0,       # inches
    "gwsink_coef": 0.0,
    "ssr2gw_rate": 0.1,
    "ssr2gw_exp": 1.0,
    "slowcoef_lin": 0.015,
    "slowcoef_sq": 0.1,
    "fastcoef_lin": 0.09,
    "fastcoef_sq": 0.8,
    "smidx_coef": 0.005,
    "smidx_exp": 0.3,
    "pref_flow_den": 0.0,
    "sat_threshold": 15.0,   # inches
    "snowinfil_max": 2.0,    # inches
    "imperv_stor_max": 0.05, # inches
    "tmax_allsnow": 32.0,    # Fahrenheit
    "tmax_allrain_offset": 6.0,
    "jh_coef_hru": 13.0,
    "jh_coef": 0.014,
    "rain_cbh_adj": 1.0,
    "snow_cbh_adj": 1.0,
    "tmax_cbh_adj": 0.0,
    "tmin_cbh_adj": 0.0,
    "potet_sublim": 0.5,
    "rad_trncf": 0.5,
    "snarea_thresh": 50.0,
    "cecn_coef": 5.0,
    "freeh2o_cap": 0.05,
    "emis_noppt": 0.757,
    "potet_coef": 1.0,
}


def validate_inputs(hru_file: str, soil_file: str, output_file: str,
                    elev_units: int) -> dict:
    """Validate input files and parameters.

    Returns dict with validated parameters.
    Raises ValueError on critical errors.
    """
    issues = []

    if not Path(hru_file).exists():
        raise ValueError(f"HRU file not found: {hru_file}")

    if soil_file and not Path(soil_file).exists():
        issues.append(f"Soil file not found: {soil_file} — using defaults")

    if elev_units not in (0, 1):
        raise ValueError(f"elev_units must be 0 (feet) or 1 (meters), got {elev_units}")

    return {"issues": issues, "elev_units": elev_units}


def read_hru_data(hru_file: str) -> pd.DataFrame:
    """Read HRU attributes from CSV or shapefile.

    Expected columns (metric units):
        hru_id, area_km2, elev_m, lat, lon, slope_deg
    Optional: cov_type, imperv_frac
    """
    if hru_file.endswith((".shp", ".gpkg")):
        try:
            import geopandas as gpd
            gdf = gpd.read_file(hru_file)
            df = pd.DataFrame(gdf.drop(columns="geometry"))
        except ImportError:
            raise ImportError("geopandas required for shapefile: pip install geopandas")
    else:
        df = pd.read_csv(hru_file)

    # Standardize column names
    rename_map = {
        "area": "area_km2", "Area": "area_km2", "area_km2": "area_km2",
        "elevation": "elev_m", "elev": "elev_m", "dem": "elev_m",
        "latitude": "lat", "Latitude": "lat",
        "longitude": "lon", "Longitude": "lon",
        "slope": "slope_deg",
    }
    df = df.rename(columns={k: v for k, v in rename_map.items() if k in df.columns})

    required = ["area_km2", "elev_m", "lat"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}. "
                         f"Available: {list(df.columns)}")

    return df


def read_soil_data(soil_file: str, nhru: int) -> pd.DataFrame:
    """Read soil properties from CSV (HWSD or SOILGRIDS format).

    Expected columns:
        hru_id, clay_pct, sand_pct, silt_pct, depth_mm, porosity, ksat_mm_hr
    """
    if soil_file is None or not Path(soil_file).exists():
        print("[soil] No soil file — using defaults")
        return pd.DataFrame({
            "clay_pct": [25.0] * nhru,
            "sand_pct": [40.0] * nhru,
            "depth_mm": [1500.0] * nhru,
            "ksat_mm_hr": [10.0] * nhru,
        })

    df = pd.read_csv(soil_file)
    return df


def classify_soil_type(clay_pct: float, sand_pct: float) -> int:
    """Classify soil into PRMS soil types based on texture.

    PRMS soil_type: 1=sand, 2=loam, 3=clay
    """
    if sand_pct > 65:
        return 1  # sand
    elif clay_pct > 35:
        return 3  # clay
    else:
        return 2  # loam


def compute_soil_moist_max(depth_mm: float, porosity: float = 0.4) -> float:
    """Compute maximum soil moisture storage in inches.

    soil_moist_max = soil_depth_inches * available_water_capacity
    Typical AWC ~ 0.15 for loam, 0.08 for sand, 0.12 for clay.
    """
    depth_in = depth_mm * MM_TO_INCHES
    # Use a moderate AWC as default
    awc = 0.15
    return max(depth_in * awc, 1.0)  # minimum 1 inch


def process_parameters(hru_df: pd.DataFrame, soil_df: pd.DataFrame,
                       elev_units: int) -> dict:
    """Process HRU and soil data into PRMS parameter arrays.

    Returns dict of {param_name: (values_list, dimension, type_code)}.
    """
    nhru = len(hru_df)
    params = {}

    # --- HRU Area: km2 -> acres ---
    area_km2 = hru_df["area_km2"].values
    area_acres = area_km2 * KM2_TO_ACRES
    params["hru_area"] = (area_acres.tolist(), "nhru", 2)
    print(f"[convert] hru_area: {area_km2.min():.2f}-{area_km2.max():.2f} km2 -> "
          f"{area_acres.min():.1f}-{area_acres.max():.1f} acres")

    # --- Elevation: meters -> feet (if elev_units=0) ---
    elev_m = hru_df["elev_m"].values
    if elev_units == 0:
        elev_out = elev_m * METERS_TO_FEET
        print(f"[convert] hru_elev: {elev_m.min():.0f}-{elev_m.max():.0f} m -> "
              f"{elev_out.min():.0f}-{elev_out.max():.0f} ft")
    else:
        elev_out = elev_m.copy()
        print(f"[convert] hru_elev: {elev_m.min():.0f}-{elev_m.max():.0f} m (kept as meters)")
    params["hru_elev"] = (elev_out.tolist(), "nhru", 2)

    # --- Latitude ---
    params["hru_lat"] = (hru_df["lat"].values.tolist(), "nhru", 2)

    # --- Longitude ---
    if "lon" in hru_df.columns:
        params["hru_lon"] = (hru_df["lon"].values.tolist(), "nhru", 2)

    # --- HRU type ---
    if "hru_type" in hru_df.columns:
        params["hru_type"] = (hru_df["hru_type"].values.tolist(), "nhru", 1)
    else:
        params["hru_type"] = ([DEFAULTS["hru_type"]] * nhru, "nhru", 1)

    # --- Cover type ---
    if "cov_type" in hru_df.columns:
        params["cov_type"] = (hru_df["cov_type"].values.tolist(), "nhru", 1)
    else:
        params["cov_type"] = ([DEFAULTS["cov_type"]] * nhru, "nhru", 1)

    # --- Cover density ---
    params["covden_sum"] = ([DEFAULTS["covden_sum"]] * nhru, "nhru", 2)
    params["covden_win"] = ([DEFAULTS["covden_win"]] * nhru, "nhru", 2)

    # --- Impervious fraction ---
    if "imperv_frac" in hru_df.columns:
        params["hru_percent_imperv"] = (hru_df["imperv_frac"].values.tolist(), "nhru", 2)
    else:
        params["hru_percent_imperv"] = ([DEFAULTS["hru_percent_imperv"]] * nhru, "nhru", 2)

    # --- Soil parameters ---
    if len(soil_df) >= nhru:
        soil_data = soil_df.iloc[:nhru]
    else:
        # Repeat soil data to match nhru
        reps = nhru // len(soil_df) + 1
        soil_data = pd.concat([soil_df] * reps).iloc[:nhru]

    soil_types = []
    soil_moist_maxes = []
    for idx in range(nhru):
        row = soil_data.iloc[idx]
        clay = row.get("clay_pct", 25.0)
        sand = row.get("sand_pct", 40.0)
        depth = row.get("depth_mm", 1500.0)
        st = classify_soil_type(clay, sand)
        smm = compute_soil_moist_max(depth)
        soil_types.append(st)
        soil_moist_maxes.append(round(smm, 2))

    params["soil_type"] = (soil_types, "nhru", 1)
    params["soil_moist_max"] = (soil_moist_maxes, "nhru", 2)
    params["soil_rechr_max"] = ([round(s * 0.5, 2) for s in soil_moist_maxes], "nhru", 2)

    # --- Calibration parameters (defaults) ---
    # nhru-dimensioned calibration params
    for pname in ["slowcoef_lin", "fastcoef_lin",
                   "smidx_coef", "smidx_exp", "sat_threshold", "snowinfil_max",
                   "imperv_stor_max", "pref_flow_den", "potet_sublim", "rad_trncf",
                   "freeh2o_cap"]:
        params[pname] = ([DEFAULTS[pname]] * nhru, "nhru", 2)

    # ngw-dimensioned params (groundwater)
    params["gwflow_coef"] = ([DEFAULTS["gwflow_coef"]] * nhru, "ngw", 2)
    params["gwstor_init"] = ([DEFAULTS.get("gwstor_init", 2.0)] * nhru, "ngw", 2)
    params["gwstor_min"] = ([DEFAULTS.get("gwstor_min", 0.0)] * nhru, "ngw", 2)
    params["gwsink_coef"] = ([DEFAULTS.get("gwsink_coef", 0.0)] * nhru, "ngw", 2)

    # nssr-dimensioned params (subsurface)
    params["ssr2gw_rate"] = ([DEFAULTS["ssr2gw_rate"]] * nhru, "nssr", 2)
    params["ssr2gw_exp"] = ([DEFAULTS.get("ssr2gw_exp", 1.0)] * nhru, "nssr", 2)
    params["ssstor_init_frac"] = ([DEFAULTS.get("ssstor_init_frac", 0.1)] * nhru, "nssr", 2)

    # --- Slope ---
    if "slope_deg" in hru_df.columns:
        slope_frac = [round(math.tan(math.radians(s)), 4)
                      for s in hru_df["slope_deg"].values]
        params["hru_slope"] = (slope_frac, "nhru", 2)

    # --- Aspect ---
    if "aspect_deg" in hru_df.columns:
        params["hru_aspect"] = (hru_df["aspect_deg"].values.tolist(), "nhru", 2)
    else:
        params["hru_aspect"] = ([0.0] * nhru, "nhru", 2)

    # --- Elevation units parameter ---
    params["elev_units"] = ([elev_units], "one", 1)

    # --- Monthly parameters ---
    nmonths = 12
    for mname in ["tmax_allsnow", "adjmix_rain"]:
        if mname == "tmax_allsnow":
            params[mname] = ([DEFAULTS["tmax_allsnow"]] * nhru * nmonths, "nhru,nmonths", 2)
        elif mname == "adjmix_rain":
            params[mname] = ([1.0] * nhru * nmonths, "nhru,nmonths", 2)

    # --- Single-value parameters ---
    params["temp_units"] = ([0], "one", 1)  # 0=Fahrenheit
    params["precip_units"] = ([0], "one", 1)  # 0=inches
    params["runoff_units"] = ([0], "one", 1)  # 0=cfs

    return params


def write_parameter_file(output_file: str, params: dict, nhru: int,
                         nsegment: int = 1, nobs: int = 0) -> str:
    """Write PRMS parameter file.

    Format: dimensions section, then parameters section.
    """
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_file, "w") as f:
        f.write("Written by convert_params_to_prms.py\n")
        f.write("Version: PRMS parameter tool v1.0\n")

        # --- Dimensions ---
        # Format: ####, dimension_name, dimension_value (NO count line)
        f.write("** Dimensions **\n")
        dims = {
            "nhru": nhru,
            "nssr": nhru,
            "ngw": nhru,
            "one": 1,
            "nsegment": nsegment,
            "nobs": nobs,
            "nmonths": 12,
            "ndepl": 1,
            "ndeplval": 11,
            "nsub": 0,
        }
        for dname, dval in dims.items():
            f.write("####\n")
            f.write(f"{dname}\n")
            f.write(f"{dval}\n")

        # --- Parameters ---
        f.write("** Parameters **\n")
        for pname, (values, dim_str, type_code) in params.items():
            f.write("####\n")
            f.write(f"{pname}\n")

            # Dimension info
            dim_names = dim_str.split(",")
            f.write(f"{len(dim_names)}\n")
            for dn in dim_names:
                f.write(f"{dn}\n")

            f.write(f"{len(values)}\n")
            f.write(f"{type_code}\n")

            for v in values:
                if type_code == 1:
                    f.write(f"{int(v)}\n")
                else:
                    f.write(f"{float(v):.6f}\n")

        # --- Snow depletion curve (required) ---
        f.write("####\n")
        f.write("snarea_curve\n")
        f.write("1\n")
        f.write("ndeplval\n")
        f.write("11\n")
        f.write("2\n")
        for v in [0.05, 0.25, 0.40, 0.55, 0.65, 0.75, 0.82, 0.88, 0.93, 0.97, 1.00]:
            f.write(f"{v:.2f}\n")

    print(f"[write] Parameter file: {output_file}")
    print(f"[write] {nhru} HRUs, {len(params)} parameters")
    return output_file


def validate_outputs(params: dict, nhru: int) -> list:
    """Post-conversion validation checks."""
    warnings = []

    if "hru_area" in params:
        areas = params["hru_area"][0]
        if min(areas) <= 0:
            warnings.append("WARNING: hru_area contains zero/negative values")
        if max(areas) < 1:
            warnings.append(
                "WARNING: Max hru_area < 1 acre — did you forget km2->acres conversion?"
            )

    if "hru_elev" in params:
        elevs = params["hru_elev"][0]
        if max(elevs) < 100 and params.get("elev_units", ([0],))[0][0] == 0:
            warnings.append(
                "WARNING: Max elevation < 100 ft — did you forget m->ft conversion?"
            )

    if "soil_moist_max" in params:
        smm = params["soil_moist_max"][0]
        if max(smm) > 100:
            warnings.append(
                "WARNING: soil_moist_max > 100 inches — likely mm not converted to inches"
            )

    for w in warnings:
        print(f"  {w}")

    return warnings


def main():
    parser = argparse.ArgumentParser(
        description="Convert soil/land use data to PRMS parameter file"
    )
    parser.add_argument("--hru_file", required=True, help="HRU attributes CSV/shapefile")
    parser.add_argument("--soil_file", default=None, help="Soil data CSV")
    parser.add_argument("--output_file", required=True, help="Output parameter file path")
    parser.add_argument("--elev_units", type=int, default=0,
                        help="Elevation units in output: 0=feet, 1=meters")
    parser.add_argument("--nsegment", type=int, default=1, help="Number of stream segments")
    parser.add_argument("--nobs", type=int, default=0, help="Number of observation stations")
    args = parser.parse_args()

    print("=" * 60)
    print("PRMS Parameter Converter")
    print("=" * 60)

    # Step 1: Validate
    validated = validate_inputs(args.hru_file, args.soil_file, args.output_file,
                                args.elev_units)

    # Step 2: Read HRU data
    print("\n--- Reading HRU data ---")
    hru_df = read_hru_data(args.hru_file)
    nhru = len(hru_df)
    print(f"[read] {nhru} HRUs loaded")

    # Step 3: Read soil data
    print("\n--- Reading soil data ---")
    soil_df = read_soil_data(args.soil_file, nhru)

    # Step 4: Process (convert units + compute derived params)
    print("\n--- Processing parameters ---")
    params = process_parameters(hru_df, soil_df, args.elev_units)

    # Step 5: Validate
    print("\n--- Validating parameters ---")
    warnings = validate_outputs(params, nhru)

    # Step 6: Write
    print("\n--- Writing output ---")
    write_parameter_file(args.output_file, params, nhru,
                         args.nsegment, args.nobs)

    if warnings:
        print(f"\n*** {len(warnings)} warnings — review before running PRMS ***")
    else:
        print("\nAll checks passed.")


if __name__ == "__main__":
    main()
