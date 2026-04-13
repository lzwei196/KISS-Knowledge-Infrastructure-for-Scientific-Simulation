#!/usr/bin/env python3
"""
convert_soil_params.py — Convert external soil data to CLM5 surface dataset format.

Maps soil properties from HWSD (Harmonized World Soil Database), SoilGrids, or
custom datasets to CLM5's 25-layer soil column structure.

CLM5 SOIL LAYER STRUCTURE (25 layers):
  Layer  1: 0.000 - 0.018 m  (dz = 0.0175 m)
  Layer  2: 0.018 - 0.045 m  (dz = 0.0276 m)
  Layer  3: 0.045 - 0.091 m  (dz = 0.0455 m)
  Layer  4: 0.091 - 0.166 m  (dz = 0.0750 m)
  Layer  5: 0.166 - 0.289 m  (dz = 0.1236 m)
  Layer  6: 0.289 - 0.493 m  (dz = 0.2038 m)
  Layer  7: 0.493 - 0.829 m  (dz = 0.3360 m)
  Layer  8: 0.829 - 1.383 m  (dz = 0.5539 m)
  Layer  9: 1.383 - 2.296 m  (dz = 0.9133 m)
  Layer 10: 2.296 - 3.802 m  (dz = 1.5058 m)
  ...continuing to ~8.5 m total

CRITICAL:
  - HWSD provides 6 layers to ~2m; extrapolation needed for deep layers
  - Sand + clay must sum to <= 100%; silt = 100 - sand - clay
  - Organic matter density: SoilGrids provides g/kg; CLM5 uses kg/m3
  - Soil depth from HWSD in cm; CLM5 uses m

Usage:
    python convert_soil_params.py --source hwsd --input soil_data.csv \\
        --lat 40.0 --lon 116.0 --output clm_soil.json
    python convert_soil_params.py --source soilgrids --input soilgrids.nc \\
        --output clm_soil.json
"""

import argparse
import json
import os
import sys

import numpy as np

try:
    import pandas as pd
except ImportError:
    pd = None


# ---------------------------------------------------------------------------
# CLM5 soil layer structure
# ---------------------------------------------------------------------------
# Node depths (m) for CLM5 25-layer configuration
# From clm_varpar: zsoi (node depth) and dzsoi (layer thickness)
CLM5_LAYER_NODES = np.array([
    0.0071, 0.0279, 0.0623, 0.1189, 0.2122, 0.3661, 0.6199,
    1.0380, 1.7276, 2.8647, 4.7394, 7.8299, 12.9253, 21.3264,
    # Bedrock layers (15-25) — typically rock, but soil properties needed
    35.1776, 58.0400, 95.7953, 158.1170, 260.9596, 430.4720,
    710.1313, 1171.9306, 1933.4087, 3190.7765, 5265.6953
])

CLM5_LAYER_INTERFACES = np.array([
    0.0000, 0.0175, 0.0451, 0.0906, 0.1656, 0.2891, 0.4929,
    0.8289, 1.3828, 2.2961, 3.8019, 6.2841, 10.3747, 17.1257,
    28.2517, 46.6134, 76.9254, 126.9467, 209.4834, 345.7034,
    570.4568, 941.3284, 1553.5413, 2563.4340, 4231.4805, 6984.0996
])

N_SOIL_LAYERS = 25
MAX_SOIL_DEPTH = 8.5  # meters, practical soil column


def validate_inputs(args):
    """Validate input arguments."""
    errors = []

    if not os.path.exists(args.input):
        errors.append(f"Input file does not exist: {args.input}")

    if args.source not in ("hwsd", "soilgrids", "csv"):
        errors.append(f"Unknown source: {args.source}. Use hwsd, soilgrids, or csv")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)


def read_hwsd(filepath, lat=None, lon=None):
    """Read HWSD data and extract soil properties.

    HWSD typically provides:
      - T_SAND, T_CLAY, T_SILT (topsoil %, 0-30 cm)
      - S_SAND, S_CLAY, S_SILT (subsoil %, 30-100 cm)
      - T_OC, S_OC (organic carbon %, weight)
      - T_BULK_DENSITY, S_BULK_DENSITY (kg/dm3)
      - T_GRAVEL, S_GRAVEL (% volume)
    """
    df = pd.read_csv(filepath)

    # Extract topsoil and subsoil properties
    soil = {
        "top_sand": _get_col(df, ["T_SAND", "sand_top", "sand_0_30"]),
        "top_clay": _get_col(df, ["T_CLAY", "clay_top", "clay_0_30"]),
        "top_oc": _get_col(df, ["T_OC", "oc_top", "soc_0_30"]),
        "top_bd": _get_col(df, ["T_BULK_DENSITY", "bd_top", "bulk_density_0_30"]),
        "sub_sand": _get_col(df, ["S_SAND", "sand_sub", "sand_30_100"]),
        "sub_clay": _get_col(df, ["S_CLAY", "clay_sub", "clay_30_100"]),
        "sub_oc": _get_col(df, ["S_OC", "oc_sub", "soc_30_100"]),
        "sub_bd": _get_col(df, ["S_BULK_DENSITY", "bd_sub", "bulk_density_30_100"]),
    }

    # If lat/lon provided, try to select nearest point
    if lat is not None and lon is not None:
        for key in ("lat", "latitude", "LAT"):
            if key in df.columns:
                lat_col = key
                break
        else:
            lat_col = None
        for key in ("lon", "longitude", "LON"):
            if key in df.columns:
                lon_col = key
                break
        else:
            lon_col = None

        if lat_col and lon_col:
            dist = np.sqrt(
                (df[lat_col] - lat)**2 + (df[lon_col] - lon)**2
            )
            idx = dist.idxmin()
            for k in soil:
                if soil[k] is not None and hasattr(soil[k], '__len__'):
                    soil[k] = float(soil[k].iloc[idx] if hasattr(soil[k], 'iloc') else soil[k][idx])

    return soil


def _get_col(df, candidates):
    """Try multiple column name candidates; return first match or None."""
    for name in candidates:
        if name in df.columns:
            return df[name]
    return None


def read_soilgrids(filepath, lat=None, lon=None):
    """Read SoilGrids data (typically NetCDF or CSV).

    SoilGrids provides data at standard depths:
      0-5 cm, 5-15 cm, 15-30 cm, 30-60 cm, 60-100 cm, 100-200 cm

    Variables: sand (g/kg), clay (g/kg), soc (dg/kg), bdod (cg/cm3)
    """
    if filepath.endswith(".nc"):
        try:
            import xarray as xr
            ds = xr.open_dataset(filepath)
            soil = {
                "depths_cm": [5, 15, 30, 60, 100, 200],
                "sand_pct": [],
                "clay_pct": [],
                "soc_gkg": [],
                "bd_kgm3": [],
            }
            for depth_label in ["0-5cm", "5-15cm", "15-30cm", "30-60cm",
                                "60-100cm", "100-200cm"]:
                for var, key in [("sand", "sand_pct"), ("clay", "clay_pct"),
                                 ("soc", "soc_gkg"), ("bdod", "bd_kgm3")]:
                    vname = f"{var}_{depth_label}_mean"
                    if vname in ds:
                        val = float(ds[vname].values.mean())
                        if var in ("sand", "clay"):
                            val = val / 10.0  # g/kg → %
                        elif var == "bdod":
                            val = val * 10.0  # cg/cm3 → kg/m3
                        soil[key].append(val)
            ds.close()
            return soil
        except Exception as e:
            print(json.dumps({
                "status": "error",
                "errors": [f"Failed to read SoilGrids NetCDF: {e}"]
            }))
            sys.exit(1)
    else:
        # CSV fallback
        df = pd.read_csv(filepath)
        return {
            "top_sand": _get_col(df, ["sand"]),
            "top_clay": _get_col(df, ["clay"]),
            "top_oc": _get_col(df, ["soc", "organic_carbon"]),
            "top_bd": _get_col(df, ["bulk_density", "bd"]),
            "sub_sand": None,
            "sub_clay": None,
            "sub_oc": None,
            "sub_bd": None,
        }


def interpolate_to_clm_layers(soil, source):
    """Interpolate soil properties to CLM5 25-layer structure.

    For HWSD (2 layers: 0-30cm, 30-100cm):
      - Layers 1-5 (~0-29cm) use topsoil values
      - Layers 6-9 (~29-230cm) use subsoil values
      - Layers 10+ use deepest available with organic matter decay

    For SoilGrids (6 layers to 200cm):
      - Linear interpolation to CLM layer midpoints
      - Extrapolation below 200cm with exponential decay for organic matter
    """
    sand_profile = np.zeros(N_SOIL_LAYERS)
    clay_profile = np.zeros(N_SOIL_LAYERS)
    organic_profile = np.zeros(N_SOIL_LAYERS)

    if source == "hwsd":
        top_sand = _to_float(soil.get("top_sand"), 50.0)
        top_clay = _to_float(soil.get("top_clay"), 20.0)
        top_oc = _to_float(soil.get("top_oc"), 1.0)
        sub_sand = _to_float(soil.get("sub_sand"), top_sand)
        sub_clay = _to_float(soil.get("sub_clay"), top_clay)
        sub_oc = _to_float(soil.get("sub_oc"), top_oc * 0.5)

        for i in range(N_SOIL_LAYERS):
            depth_m = CLM5_LAYER_NODES[i]
            if depth_m < 0.30:
                sand_profile[i] = top_sand
                clay_profile[i] = top_clay
                organic_profile[i] = top_oc
            elif depth_m < 1.00:
                sand_profile[i] = sub_sand
                clay_profile[i] = sub_clay
                organic_profile[i] = sub_oc
            else:
                # Extrapolate: texture constant, OC decays exponentially
                sand_profile[i] = sub_sand
                clay_profile[i] = sub_clay
                decay = np.exp(-0.5 * (depth_m - 1.0))
                organic_profile[i] = sub_oc * decay

    elif source == "soilgrids" and "depths_cm" in soil:
        depths_cm = np.array(soil["depths_cm"])
        depths_m = depths_cm / 100.0

        sand_vals = np.array(soil.get("sand_pct", [50]*6))
        clay_vals = np.array(soil.get("clay_pct", [20]*6))
        soc_vals = np.array(soil.get("soc_gkg", [10]*6))

        for i in range(N_SOIL_LAYERS):
            d = CLM5_LAYER_NODES[i]
            if d <= depths_m[-1]:
                sand_profile[i] = np.interp(d, depths_m, sand_vals)
                clay_profile[i] = np.interp(d, depths_m, clay_vals)
                organic_profile[i] = np.interp(d, depths_m, soc_vals)
            else:
                sand_profile[i] = sand_vals[-1]
                clay_profile[i] = clay_vals[-1]
                decay = np.exp(-0.5 * (d - depths_m[-1]))
                organic_profile[i] = soc_vals[-1] * decay

    else:
        # Constant profile fallback
        sand_profile[:] = _to_float(soil.get("top_sand"), 50.0)
        clay_profile[:] = _to_float(soil.get("top_clay"), 20.0)
        organic_profile[:] = _to_float(soil.get("top_oc"), 1.0)

    # Ensure sand + clay <= 100
    total = sand_profile + clay_profile
    excess = np.maximum(total - 100.0, 0.0)
    if np.any(excess > 0):
        scale = 100.0 / np.maximum(total, 1e-6)
        sand_profile *= np.where(excess > 0, scale, 1.0)
        clay_profile *= np.where(excess > 0, scale, 1.0)

    silt_profile = 100.0 - sand_profile - clay_profile

    return {
        "sand_pct": sand_profile.tolist(),
        "clay_pct": clay_profile.tolist(),
        "silt_pct": silt_profile.tolist(),
        "organic_matter": organic_profile.tolist(),
        "n_layers": N_SOIL_LAYERS,
        "layer_depths_m": CLM5_LAYER_NODES[:N_SOIL_LAYERS].tolist(),
    }


def _to_float(val, default):
    """Convert value to float, handling Series/array/None."""
    if val is None:
        return default
    if hasattr(val, 'mean'):
        v = float(val.mean())
    else:
        v = float(val)
    return v if np.isfinite(v) else default


def validate_outputs(result):
    """Validate soil profiles for physical consistency."""
    warnings_list = []

    sand = np.array(result["sand_pct"])
    clay = np.array(result["clay_pct"])
    silt = np.array(result["silt_pct"])

    total = sand + clay + silt
    if not np.allclose(total, 100.0, atol=0.1):
        warnings_list.append(
            f"Sand+clay+silt != 100% at some layers. "
            f"Range: {total.min():.1f}-{total.max():.1f}%"
        )

    if np.any(sand < 0) or np.any(clay < 0) or np.any(silt < 0):
        warnings_list.append("Negative texture fraction detected")

    if np.any(sand > 100) or np.any(clay > 100):
        warnings_list.append("Texture fraction > 100% detected")

    om = np.array(result["organic_matter"])
    if np.any(om < 0):
        warnings_list.append("Negative organic matter detected")

    # Check that organic matter decays with depth
    if len(om) > 5 and om[0] < om[-1]:
        warnings_list.append(
            "Organic matter increases with depth — verify data"
        )

    result["warnings"] = warnings_list
    return result


def process(args):
    """Main processing pipeline."""
    if args.source == "hwsd":
        soil = read_hwsd(args.input, lat=args.lat, lon=args.lon)
    elif args.source == "soilgrids":
        soil = read_soilgrids(args.input, lat=args.lat, lon=args.lon)
    elif args.source == "csv":
        soil = read_hwsd(args.input, lat=args.lat, lon=args.lon)
    else:
        print(json.dumps({
            "status": "error",
            "errors": [f"Unknown source: {args.source}"]
        }))
        sys.exit(1)

    profiles = interpolate_to_clm_layers(soil, args.source)
    return profiles


def main():
    parser = argparse.ArgumentParser(
        description="Convert soil data to CLM5 25-layer format"
    )
    parser.add_argument(
        "--source", type=str, required=True,
        choices=["hwsd", "soilgrids", "csv"],
        help="Soil data source type"
    )
    parser.add_argument(
        "--input", type=str, required=True,
        help="Input soil data file (CSV or NetCDF)"
    )
    parser.add_argument("--lat", type=float, default=None)
    parser.add_argument("--lon", type=float, default=None)
    parser.add_argument(
        "--output", type=str, default=None,
        help="Output JSON file path"
    )

    args = parser.parse_args()

    validate_inputs(args)
    profiles = process(args)
    profiles = validate_outputs(profiles)

    profiles["status"] = "success"
    profiles["source"] = args.source

    output_json = json.dumps(profiles, indent=2)

    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            f.write(output_json)
        print(f"Output written to {args.output}", file=sys.stderr)
    else:
        print(output_json)


if __name__ == "__main__":
    main()
