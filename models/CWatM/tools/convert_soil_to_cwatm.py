#!/usr/bin/env python3
"""
convert_soil_to_cwatm.py — Convert HWSD / SoilGrids soil data to CWatM soil parameter NetCDFs.

CWatM requires the following soil hydraulic parameters for 3 layers:
  - KSat1, KSat2, KSat3: Saturated hydraulic conductivity [cm/day]
  - alpha1, alpha2, alpha3: van Genuchten alpha [1/cm]
  - lambda1, lambda2, lambda3: van Genuchten lambda (pore-size index) [-]
  - thetas1, thetas2, thetas3: Saturated water content [-]
  - thetar1, thetar2, thetar3: Residual water content [-]
  - percolationImp: Fraction of impermeable area [-]

CRITICAL UNIT CONVERSIONS:
  - KSat from HWSD: already in cm/day (no conversion needed)
  - KSat from SoilGrids: mm/hr → cm/day = × 2.4
  - alpha from HWSD: already in 1/cm
  - alpha from SoilGrids: 1/kPa → 1/cm ≈ ÷ 10 (approximate)
  - thetas/thetar: volumetric fraction (0-1), same in all sources

Usage:
    python convert_soil_to_cwatm.py \\
        --source hwsd \\
        --input_dir /path/to/hwsd/ \\
        --bbox 45.0 50.0 5.0 15.0 \\
        --resolution 0.5 \\
        --output_dir /path/to/cwatm_soil/

    python convert_soil_to_cwatm.py \\
        --source soilgrids \\
        --input_dir /path/to/soilgrids/ \\
        --bbox 45.0 50.0 5.0 15.0 \\
        --resolution 0.083333 \\
        --output_dir /path/to/cwatm_soil/
"""

import argparse
import json
import os
import sys
from datetime import datetime

import numpy as np

try:
    import netCDF4 as nc
except ImportError:
    nc = None


# ---------------------------------------------------------------------------
# Van Genuchten pedotransfer functions (Wosten et al. 1999)
# ---------------------------------------------------------------------------

# USDA texture class to van Genuchten parameters (Schaap et al. 2001, Rosetta)
# Format: {texture_class: (thetar, thetas, alpha_1_cm, lambda, Ksat_cm_day)}
VAN_GENUCHTEN_PARAMS = {
    "Sand":         (0.045, 0.430, 0.145, 2.68, 712.8),
    "Loamy Sand":   (0.057, 0.410, 0.124, 2.28, 350.2),
    "Sandy Loam":   (0.065, 0.410, 0.075, 1.89, 106.1),
    "Loam":         (0.078, 0.430, 0.036, 1.56,  25.0),
    "Silt Loam":    (0.067, 0.450, 0.020, 1.41,  10.8),
    "Silt":         (0.034, 0.460, 0.016, 1.37,   6.0),
    "Sandy Clay Loam": (0.100, 0.390, 0.059, 1.48,  31.4),
    "Clay Loam":    (0.095, 0.410, 0.019, 1.31,   6.2),
    "Silty Clay Loam": (0.089, 0.430, 0.010, 1.23,   1.7),
    "Sandy Clay":   (0.100, 0.380, 0.027, 1.23,   2.9),
    "Silty Clay":   (0.070, 0.360, 0.005, 1.09,   0.5),
    "Clay":         (0.068, 0.380, 0.008, 1.09,   4.8),
}

# HWSD texture code mapping (MU_GLOBAL texture classes)
HWSD_TEXTURE_MAP = {
    1: "Sand", 2: "Loamy Sand", 3: "Sandy Loam", 4: "Loam",
    5: "Silt Loam", 6: "Silt", 7: "Sandy Clay Loam", 8: "Clay Loam",
    9: "Silty Clay Loam", 10: "Sandy Clay", 11: "Silty Clay", 12: "Clay",
    13: "Loam",  # Organic soils default to Loam
}


def validate_inputs(args):
    """Validate all input arguments before processing."""
    errors = []

    if args.source not in ("hwsd", "soilgrids"):
        errors.append(f"Unknown source: {args.source}. Supported: hwsd, soilgrids")

    if not os.path.isdir(args.input_dir):
        errors.append(f"Input directory not found: {args.input_dir}")

    if len(args.bbox) != 4:
        errors.append("--bbox requires 4 values: lat_min lat_max lon_min lon_max")
    else:
        lat_min, lat_max, lon_min, lon_max = args.bbox
        if lat_min >= lat_max:
            errors.append(f"lat_min ({lat_min}) must be < lat_max ({lat_max})")
        if lon_min >= lon_max:
            errors.append(f"lon_min ({lon_min}) must be < lon_max ({lon_max})")

    if args.resolution <= 0:
        errors.append(f"Resolution must be positive, got {args.resolution}")

    if nc is None:
        errors.append("netCDF4 package not installed. Install with: pip install netCDF4")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}, indent=2))
        sys.exit(1)


def read_hwsd_data(input_dir, bbox):
    """
    Read HWSD soil data and extract texture classes.

    Returns
    -------
    texture_top : np.ndarray (lat, lon)
        USDA texture class code for topsoil (0-30 cm)
    texture_sub : np.ndarray (lat, lon)
        USDA texture class code for subsoil (30-100 cm)
    lats, lons : np.ndarray
    """
    import glob

    lat_min, lat_max, lon_min, lon_max = bbox

    # Try to find HWSD NetCDF file
    hwsd_files = glob.glob(os.path.join(input_dir, "*HWSD*.nc")) + \
                 glob.glob(os.path.join(input_dir, "*hwsd*.nc"))

    if not hwsd_files:
        # Try GeoTIFF
        tif_files = glob.glob(os.path.join(input_dir, "*texture*.tif"))
        if tif_files and gdal is not None:
            return _read_hwsd_tif(tif_files, bbox)
        raise FileNotFoundError(
            f"No HWSD NetCDF or GeoTIFF files found in {input_dir}"
        )

    ds = nc.Dataset(hwsd_files[0])

    # Find coordinate and data variables
    lats = ds.variables.get("lat", ds.variables.get("latitude"))
    lons = ds.variables.get("lon", ds.variables.get("longitude"))

    if lats is None or lons is None:
        ds.close()
        raise ValueError("Cannot find lat/lon variables in HWSD file")

    lats = lats[:]
    lons = lons[:]

    lat_mask = (lats >= lat_min) & (lats <= lat_max)
    lon_mask = (lons >= lon_min) & (lons <= lon_max)

    # Try common variable names for texture class
    for vname in ["T_TEXTURE", "texture_top", "TEXTURE", "T_USDA_TEX_CLASS"]:
        if vname in ds.variables:
            texture_top = ds.variables[vname][lat_mask][:, lon_mask]
            break
    else:
        texture_top = np.full((lat_mask.sum(), lon_mask.sum()), 4)  # Default: Loam

    for vname in ["S_TEXTURE", "texture_sub", "S_USDA_TEX_CLASS"]:
        if vname in ds.variables:
            texture_sub = ds.variables[vname][lat_mask][:, lon_mask]
            break
    else:
        texture_sub = texture_top.copy()

    ds.close()
    return texture_top, texture_sub, lats[lat_mask], lons[lon_mask]


def texture_to_vg_params(texture_array):
    """
    Convert USDA texture class codes to van Genuchten parameters.

    Returns dict with keys: thetar, thetas, alpha, lam, ksat
    Each value is an array matching the shape of texture_array.
    """
    thetar = np.full_like(texture_array, 0.078, dtype=np.float32)
    thetas = np.full_like(texture_array, 0.430, dtype=np.float32)
    alpha = np.full_like(texture_array, 0.036, dtype=np.float32)
    lam = np.full_like(texture_array, 1.56, dtype=np.float32)
    ksat = np.full_like(texture_array, 25.0, dtype=np.float32)

    for code, tex_name in HWSD_TEXTURE_MAP.items():
        if tex_name in VAN_GENUCHTEN_PARAMS:
            mask = texture_array == code
            params = VAN_GENUCHTEN_PARAMS[tex_name]
            thetar[mask] = params[0]
            thetas[mask] = params[1]
            alpha[mask] = params[2]
            lam[mask] = params[3]
            ksat[mask] = params[4]

    return {
        "thetar": thetar,
        "thetas": thetas,
        "alpha": alpha,
        "lam": lam,
        "ksat": ksat,
    }


def write_soil_netcdf(output_dir, var_name, data, lats, lons, units, long_name):
    """Write a single soil parameter to CWatM-compatible NetCDF."""
    output_path = os.path.join(output_dir, f"{var_name}.nc")
    ds = nc.Dataset(output_path, "w", format="NETCDF4")

    ds.createDimension("lat", len(lats))
    ds.createDimension("lon", len(lons))

    lat_var = ds.createVariable("lat", "f8", ("lat",))
    lat_var.units = "degrees_north"
    lat_var.standard_name = "latitude"
    lat_var[:] = lats

    lon_var = ds.createVariable("lon", "f8", ("lon",))
    lon_var.units = "degrees_east"
    lon_var.standard_name = "longitude"
    lon_var[:] = lons

    data_var = ds.createVariable(
        var_name, "f4", ("lat", "lon"),
        fill_value=-9999.0, zlib=True,
    )
    data_var.units = units
    data_var.long_name = long_name
    data_var[:] = data

    ds.Conventions = "CF-1.6"
    ds.title = f"CWatM soil parameter: {var_name}"
    ds.history = f"Created {datetime.now().isoformat()}"
    ds.close()

    return output_path


def validate_outputs(params_dict, layer_name):
    """Validate converted soil parameters for physical consistency."""
    warnings = []

    ksat = params_dict["ksat"]
    thetas = params_dict["thetas"]
    thetar = params_dict["thetar"]
    alpha = params_dict["alpha"]
    lam = params_dict["lam"]

    # KSat sanity checks (cm/day)
    if np.nanmax(ksat) > 5000:
        warnings.append(
            f"UNIT TRAP ({layer_name}): KSat max={np.nanmax(ksat):.1f} cm/day. "
            f"If > 5000, units may be wrong (mm/hr?). Convert: cm/day = mm/hr × 2.4"
        )
    if np.nanmin(ksat[ksat > 0]) < 0.001:
        warnings.append(
            f"WARNING ({layer_name}): KSat min={np.nanmin(ksat[ksat > 0]):.4f} cm/day. "
            f"Very low — check if units are m/s (convert: cm/day = m/s × 8640000)"
        )

    # Porosity checks
    if np.any(thetas > 0.95):
        warnings.append(f"WARNING ({layer_name}): thetas > 0.95 found — unrealistic porosity")
    if np.any(thetar >= thetas):
        warnings.append(f"ERROR ({layer_name}): thetar >= thetas — physically impossible")
    if np.any(thetar < 0):
        warnings.append(f"ERROR ({layer_name}): negative thetar values")

    # van Genuchten alpha (1/cm)
    if np.nanmax(alpha) > 1.0:
        warnings.append(
            f"UNIT TRAP ({layer_name}): alpha max={np.nanmax(alpha):.3f}. "
            f"If > 1.0 1/cm, units may be 1/m — divide by 100."
        )

    # Lambda
    if np.any(lam < 1.0):
        warnings.append(
            f"WARNING ({layer_name}): lambda < 1.0 found. "
            f"CWatM uses genuM = lambda/(1+lambda), check consistency."
        )

    return warnings


def convert_soil(args):
    """Main conversion pipeline: validate → process → validate."""
    os.makedirs(args.output_dir, exist_ok=True)
    results = {"status": "success", "files_created": [], "warnings": []}

    if args.source == "hwsd":
        texture_top, texture_sub, lats, lons = read_hwsd_data(args.input_dir, args.bbox)

        # Layer 1: Topsoil (0-5 cm) — same as topsoil texture
        # Layer 2: Topsoil (5-30 cm) — same as topsoil texture
        # Layer 3: Subsoil (30-100 cm) — subsoil texture
        layer_textures = {
            "1": texture_top,
            "2": texture_top,
            "3": texture_sub,
        }

        for layer_num, texture in layer_textures.items():
            params = texture_to_vg_params(texture)
            layer_name = f"Layer {layer_num}"

            # Validate
            layer_warnings = validate_outputs(params, layer_name)
            results["warnings"].extend(layer_warnings)

            # Write each parameter
            param_specs = [
                ("KSat", params["ksat"], "cm/day", "Saturated hydraulic conductivity"),
                ("alpha", params["alpha"], "1/cm", "van Genuchten alpha"),
                ("lambda", params["lam"], "-", "van Genuchten pore-size index lambda"),
                ("thetas", params["thetas"], "-", "Saturated water content"),
                ("thetar", params["thetar"], "-", "Residual water content"),
            ]

            for pname, pdata, punits, plong in param_specs:
                var_name = f"{pname}{layer_num}"
                fpath = write_soil_netcdf(
                    args.output_dir, var_name, pdata, lats, lons, punits, plong
                )
                results["files_created"].append({
                    "variable": var_name,
                    "file": fpath,
                    "min": float(np.nanmin(pdata)),
                    "max": float(np.nanmax(pdata)),
                    "mean": float(np.nanmean(pdata)),
                })

        # Percolation impermeability (default 0.1 for clay-rich, 0.01 otherwise)
        perc_imp = np.where(texture_sub >= 11, 0.1, 0.01).astype(np.float32)
        fpath = write_soil_netcdf(
            args.output_dir, "percolationImp", perc_imp, lats, lons,
            "-", "Fraction of impermeable area",
        )
        results["files_created"].append({
            "variable": "percolationImp",
            "file": fpath,
            "min": float(np.nanmin(perc_imp)),
            "max": float(np.nanmax(perc_imp)),
        })

    elif args.source == "soilgrids":
        results["warnings"].append(
            "SoilGrids conversion not yet fully implemented. "
            "Use HWSD source or provide pre-converted NetCDFs."
        )

    print(json.dumps(results, indent=2))
    return results


def main():
    parser = argparse.ArgumentParser(
        description="Convert soil data to CWatM parameter NetCDFs"
    )
    parser.add_argument("--source", required=True, choices=["hwsd", "soilgrids"])
    parser.add_argument("--input_dir", required=True, help="Soil data directory")
    parser.add_argument(
        "--bbox", type=float, nargs=4, required=True,
        metavar=("LAT_MIN", "LAT_MAX", "LON_MIN", "LON_MAX"),
    )
    parser.add_argument("--resolution", type=float, default=0.5, help="Grid resolution in degrees")
    parser.add_argument("--output_dir", required=True, help="Output directory")

    args = parser.parse_args()

    print("=== CWatM Soil Parameter Converter ===")
    validate_inputs(args)
    convert_soil(args)


if __name__ == "__main__":
    main()
