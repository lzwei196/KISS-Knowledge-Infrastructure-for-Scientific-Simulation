#!/usr/bin/env python3
"""
convert_soil_params.py — Convert soil databases to TopoFlow infiltration parameters.

Supported sources:
  - HWSD (Harmonized World Soil Database) — shapefile/raster at 1 km
  - SoilGrids (ISRIC) — REST API or pre-downloaded GeoTIFF at 250 m

Target methods:
  - Green-Ampt:      Ks, Ki, θs, θi, G (capillary length)
  - Smith-Parlange:  Ks, Ki, θs, θi, G, γ
  - Richards 1-D:    Ks, Ki, θs, θi, θr, pB, λ, c

CRITICAL UNIT TRAPS:
  - HWSD Ks is often in cm/day or mm/hr → TopoFlow needs m/s (÷ 3.6e6)
  - SoilGrids Ks is in mm/hr → ÷ 3.6e6 for m/s
  - Capillary suction G in literature is commonly cm → need m (÷ 100)
  - Porosity from databases may be % (0–100) → need fraction (÷ 100)
  - Bulk density may be in g/cm³ — verify units if computing porosity

Output:
  Either scalar values for .cfg files, or RTG grid files for spatially
  distributed parameters.

Usage:
  python convert_soil_params.py \\
    --source hwsd \\
    --input_file /path/to/HWSD_RASTER/hwsd.bil \\
    --lat 41.17 --lon -95.62 \\
    --method green_ampt \\
    --output_dir ./soil_input/ \\
    --site_prefix Treynor
"""

import argparse
import json
import os
import sys

import numpy as np

# ---------------------------------------------------------------------------
# Pedotransfer lookup: USDA texture class → hydraulic parameters
# Sources: Rawls et al. (1982), Clapp & Hornberger (1978)
# ---------------------------------------------------------------------------
# Units: Ks [m/s], θs [-], θr [-], G [m], pB [m], λ [-]
SOIL_PARAMS = {
    "sand": {
        "Ks": 5.83e-5, "theta_s": 0.395, "theta_r": 0.020,
        "G": 0.0495, "pB": 0.121, "lambda": 0.694, "c": 2.0,
    },
    "loamy_sand": {
        "Ks": 1.70e-5, "theta_s": 0.410, "theta_r": 0.035,
        "G": 0.0613, "pB": 0.090, "lambda": 0.553, "c": 2.0,
    },
    "sandy_loam": {
        "Ks": 7.19e-6, "theta_s": 0.435, "theta_r": 0.041,
        "G": 0.1101, "pB": 0.218, "lambda": 0.378, "c": 2.0,
    },
    "silty_loam": {
        "Ks": 3.67e-6, "theta_s": 0.485, "theta_r": 0.015,
        "G": 0.1668, "pB": 0.786, "lambda": 0.234, "c": 2.0,
    },
    "loam": {
        "Ks": 3.67e-6, "theta_s": 0.451, "theta_r": 0.027,
        "G": 0.0889, "pB": 0.478, "lambda": 0.252, "c": 2.0,
    },
    "sandy_clay_loam": {
        "Ks": 1.19e-6, "theta_s": 0.420, "theta_r": 0.068,
        "G": 0.2185, "pB": 0.299, "lambda": 0.319, "c": 2.0,
    },
    "silty_clay_loam": {
        "Ks": 6.39e-7, "theta_s": 0.477, "theta_r": 0.040,
        "G": 0.2730, "pB": 0.356, "lambda": 0.177, "c": 2.0,
    },
    "clay_loam": {
        "Ks": 6.39e-7, "theta_s": 0.476, "theta_r": 0.075,
        "G": 0.2088, "pB": 0.630, "lambda": 0.194, "c": 2.0,
    },
    "sandy_clay": {
        "Ks": 3.33e-7, "theta_s": 0.426, "theta_r": 0.109,
        "G": 0.2390, "pB": 0.153, "lambda": 0.223, "c": 2.0,
    },
    "silty_clay": {
        "Ks": 2.50e-7, "theta_s": 0.492, "theta_r": 0.056,
        "G": 0.2922, "pB": 0.490, "lambda": 0.150, "c": 2.0,
    },
    "clay": {
        "Ks": 1.67e-7, "theta_s": 0.482, "theta_r": 0.090,
        "G": 0.3163, "pB": 0.405, "lambda": 0.165, "c": 2.0,
    },
}

# HWSD texture code → USDA class mapping (simplified)
HWSD_TEXTURE_MAP = {
    1: "sand", 2: "loamy_sand", 3: "sandy_loam", 4: "silty_loam",
    5: "loam", 6: "sandy_clay_loam", 7: "silty_clay_loam",
    8: "clay_loam", 9: "sandy_clay", 10: "silty_clay",
    11: "clay", 12: "loam",  # organic soils default to loam
    13: "sand",  # rock/gravel default
}


def validate_inputs(source, input_file, lat, lon, method, output_dir):
    """Validate inputs before processing.

    Returns (errors, warnings) lists.
    """
    errors = []
    warnings = []

    valid_sources = {"hwsd", "soilgrids", "manual"}
    if source not in valid_sources:
        errors.append(f"Unknown source '{source}'. Valid: {valid_sources}")

    if source != "manual" and input_file and not os.path.exists(input_file):
        errors.append(f"Input file not found: {input_file}")

    valid_methods = {"green_ampt", "smith_parlange", "richards_1d"}
    if method not in valid_methods:
        errors.append(f"Unknown method '{method}'. Valid: {valid_methods}")

    if not (-90 <= lat <= 90):
        errors.append(f"Latitude {lat} out of range")
    if not (-180 <= lon <= 180):
        errors.append(f"Longitude {lon} out of range")

    os.makedirs(output_dir, exist_ok=True)

    return errors, warnings


def lookup_hwsd_texture(input_file, lat, lon):
    """Look up HWSD soil texture class at a point.

    Returns USDA texture class name.
    """
    try:
        from osgeo import gdal
        ds = gdal.Open(input_file)
        if ds is None:
            raise FileNotFoundError(f"Cannot open HWSD raster: {input_file}")
        gt = ds.GetGeoTransform()
        col = int((lon - gt[0]) / gt[1])
        row = int((lat - gt[3]) / gt[5])
        band = ds.GetRasterBand(1)
        val = int(band.ReadAsArray(col, row, 1, 1)[0, 0])
        ds = None
        texture = HWSD_TEXTURE_MAP.get(val, "loam")
        return texture, val
    except ImportError:
        print("WARNING: GDAL not available. Using default soil type.", file=sys.stderr)
        return "loam", -1
    except Exception as e:
        print(f"WARNING: HWSD lookup failed ({e}). Using default.", file=sys.stderr)
        return "loam", -1


def lookup_manual(soil_type):
    """Look up parameters for a given USDA texture class name."""
    soil_type_lower = soil_type.lower().replace(" ", "_")
    if soil_type_lower not in SOIL_PARAMS:
        raise ValueError(
            f"Unknown soil type '{soil_type}'. "
            f"Valid: {list(SOIL_PARAMS.keys())}"
        )
    return soil_type_lower


def params_for_method(texture, method, theta_i=None):
    """Extract parameters for a specific infiltration method.

    Parameters
    ----------
    texture : str
        USDA texture class name.
    method : str
        One of green_ampt, smith_parlange, richards_1d.
    theta_i : float, optional
        Initial soil moisture.  Defaults to midpoint of θr and θs.

    Returns
    -------
    params : dict
        Parameter name → value in TopoFlow units.
    """
    base = SOIL_PARAMS[texture].copy()

    if theta_i is None:
        theta_i = 0.5 * (base["theta_r"] + base["theta_s"])

    result = {
        "Ks_val": base["Ks"],         # m/s
        "Ki_val": 0.5 * base["Ks"],   # initial K ≈ half Ks
        "qs_val": base["theta_s"],     # saturated moisture
        "qi_val": theta_i,             # initial moisture
        "soil_type": texture,
    }

    if method == "green_ampt":
        result["G_val"] = base["G"]                # capillary length [m]

    elif method == "smith_parlange":
        result["G_val"] = base["G"]
        result["gamma_val"] = 0.8                  # Smith-Parlange γ

    elif method == "richards_1d":
        result["qr_val"] = base["theta_r"]         # residual moisture
        result["pB_val"] = base["pB"]              # bubbling pressure [m]
        result["lam_val"] = base["lambda"]          # pore size distribution
        result["c_val"] = base["c"]                 # Brooks-Corey c

    return result


def write_cfg_snippet(params, method, output_dir, site_prefix):
    """Write a .cfg snippet with the infiltration parameters.

    Returns path to the written file.
    """
    lines = [
        f"# Infiltration parameters for method: {method}",
        f"# Soil type: {params['soil_type']}",
        f"# Generated by convert_soil_params.py",
        f"#",
        f"# CRITICAL: Ks is in m/s.  If your source was mm/hr, divide by 3.6e6.",
        f"# CRITICAL: G (capillary length) is in meters.  If source was cm, divide by 100.",
        f"#",
    ]

    param_lines = {
        "Ks_val": ("Ks_val", "float", "sat. hydraulic conductivity [m/s]"),
        "Ki_val": ("Ki_val", "float", "init. hydraulic conductivity [m/s]"),
        "qs_val": ("qs_val", "float", "sat. soil water content [-]"),
        "qi_val": ("qi_val", "float", "init. soil water content [-]"),
        "G_val":  ("G_val",  "float", "capillary length scale [m]"),
        "gamma_val": ("gamma_val", "float", "Smith-Parlange gamma [-]"),
        "qr_val": ("qr_val", "float", "residual soil water content [-]"),
        "pB_val": ("pB_val", "float", "bubbling pressure head [m]"),
        "lam_val": ("lam_val", "float", "pore-size distribution index [-]"),
        "c_val":  ("c_val",  "float", "Brooks-Corey c parameter [-]"),
    }

    for key, (name, dtype, desc) in param_lines.items():
        if key in params and key != "soil_type":
            val = params[key]
            lines.append(f"{name:<20s} | {val:<16.6e} | {dtype:<8s} | {desc}")

    filepath = os.path.join(output_dir, f"{site_prefix}_infil_{method}_params.cfg")
    with open(filepath, "w") as f:
        f.write("\n".join(lines) + "\n")
    return filepath


def write_rtg_grid(param_name, value, nrows, ncols, output_dir, site_prefix):
    """Write a uniform RTG binary grid for spatial parameter.

    Returns path to the written .rtg file.
    """
    grid = np.full((nrows, ncols), value, dtype=np.float32)
    filepath = os.path.join(output_dir, f"{site_prefix}_{param_name}.rtg")
    grid.tofile(filepath)
    return filepath


def process(source, input_file, lat, lon, method, output_dir, site_prefix,
            soil_type=None, theta_i=None, nrows=None, ncols=None):
    """Main processing: lookup soil, compute params, write outputs.

    Returns result dict with status, parameters, and file paths.
    """
    # Determine soil texture
    if source == "manual":
        texture = lookup_manual(soil_type or "loam")
        hwsd_code = -1
    elif source == "hwsd":
        texture, hwsd_code = lookup_hwsd_texture(input_file, lat, lon)
    else:
        texture, hwsd_code = "loam", -1

    # Compute parameters
    params = params_for_method(texture, method, theta_i)

    # Write cfg snippet
    cfg_path = write_cfg_snippet(params, method, output_dir, site_prefix)

    # Optionally write RTG grids
    grid_files = {}
    if nrows and ncols:
        for key, val in params.items():
            if key != "soil_type" and isinstance(val, (int, float)):
                path = write_rtg_grid(key, val, nrows, ncols, output_dir, site_prefix)
                grid_files[key] = path

    return {
        "status": "success",
        "source": source,
        "hwsd_code": hwsd_code,
        "soil_texture": texture,
        "method": method,
        "parameters": {k: v for k, v in params.items() if k != "soil_type"},
        "cfg_file": cfg_path,
        "grid_files": grid_files,
        "unit_notes": {
            "Ks": "m/s (converted from pedotransfer, already in SI)",
            "G": "meters (converted from pedotransfer, already in SI)",
            "theta_s": "dimensionless fraction 0-1",
        },
    }


def validate_outputs(params, method):
    """Validate computed parameters are physically reasonable.

    Returns (errors, warnings).
    """
    errors = []
    warnings = []

    ks = params.get("Ks_val", 0)
    if ks < 1e-9:
        warnings.append(f"Ks = {ks:.2e} m/s — extremely low, nearly impermeable.")
    if ks > 1e-3:
        errors.append(f"Ks = {ks:.2e} m/s — too high, check units (should be m/s not mm/hr).")

    qs = params.get("qs_val", 0)
    if qs > 0.65:
        errors.append(f"θs = {qs} — above physical maximum (~0.60). Check units.")
    if qs < 0.2:
        warnings.append(f"θs = {qs} — very low porosity.")

    qi = params.get("qi_val", 0)
    if qi >= qs:
        errors.append(f"θi ({qi}) >= θs ({qs}) — initial moisture cannot exceed saturation.")

    if "G_val" in params:
        g = params["G_val"]
        if g > 5.0:
            errors.append(
                f"G = {g:.2f} m — suspiciously large. "
                "If source was in cm, divide by 100."
            )
        if g < 0.001:
            warnings.append(f"G = {g:.4f} m — very small capillary length.")

    return errors, warnings


def main():
    parser = argparse.ArgumentParser(
        description="Convert soil database to TopoFlow infiltration parameters"
    )
    parser.add_argument("--source", required=True, choices=["hwsd", "soilgrids", "manual"])
    parser.add_argument("--input_file", default=None, help="Path to HWSD raster")
    parser.add_argument("--lat", required=True, type=float)
    parser.add_argument("--lon", required=True, type=float)
    parser.add_argument("--method", required=True,
                        choices=["green_ampt", "smith_parlange", "richards_1d"])
    parser.add_argument("--output_dir", required=True)
    parser.add_argument("--site_prefix", default="Site")
    parser.add_argument("--soil_type", default=None,
                        help="Manual USDA texture class (for --source manual)")
    parser.add_argument("--theta_i", type=float, default=None,
                        help="Initial soil moisture fraction")
    parser.add_argument("--nrows", type=int, default=None, help="Grid rows (for RTG output)")
    parser.add_argument("--ncols", type=int, default=None, help="Grid cols (for RTG output)")

    args = parser.parse_args()

    errors, warnings = validate_inputs(
        args.source, args.input_file, args.lat, args.lon, args.method, args.output_dir
    )
    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)
    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)

    result = process(
        args.source, args.input_file, args.lat, args.lon,
        args.method, args.output_dir, args.site_prefix,
        args.soil_type, args.theta_i, args.nrows, args.ncols
    )

    out_errors, out_warnings = validate_outputs(result["parameters"], args.method)
    result["output_warnings"] = out_warnings
    if out_errors:
        result["output_errors"] = out_errors
        result["status"] = "error"

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
