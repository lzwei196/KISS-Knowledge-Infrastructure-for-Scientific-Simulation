#!/usr/bin/env python3
"""
Build subsurface property fields for ParFlow from HWSD soil data.

Maps soil texture to van Genuchten parameters (alpha, n, Sres, Ssat) and
hydraulic conductivity (K) using Rosetta pedotransfer functions.

**CRITICAL UNIT: ParFlow K is in m/hr** (NOT m/day = 24x error, NOT m/s = 3600x error)
**CRITICAL UNIT: van Genuchten alpha is 1/m** (NOT 1/cm = 100x error)

Uses the shared HydroCraft HWSD adapter for soil property extraction.

Usage:
    python build_subsurface_properties.py \
        --domain_json outputs/parflow_run/domain/domain_definition.json \
        --mask_npy outputs/parflow_run/domain/domain_mask.npy \
        --output_dir outputs/parflow_run/subsurface/

Author: Jianyun Zhang Research Group, Hohai University
"""

import argparse
import json
import os
import sys

import numpy as np

try:
    import rasterio
    from pyproj import CRS, Transformer
except ImportError as e:
    print(json.dumps({"status": "error", "message": f"Missing dependency: {e}"}))
    sys.exit(1)

# ========================== CONFIGURATION ==========================
HYDROCRAFT_ROOT = "KISSPATH_ROOT"
HWSD_RASTER = os.path.join(HYDROCRAFT_ROOT, "data/soil/HWSD_RASTER/hwsd.bil")

# Rosetta v3 pedotransfer: soil texture class -> van Genuchten parameters
# Source: Schaap et al. (2001), converted to ParFlow units
# alpha: 1/m (NOT 1/cm), n: dimensionless, Sres: fraction, Ssat: fraction
# Ksat: m/hr (NOT m/day or m/s)
ROSETTA_VAN_GENUCHTEN = {
    # texture_class: (alpha_1_per_m, n, theta_r, theta_s, Ksat_m_per_hr)
    "sand":         (14.50, 2.680, 0.045, 0.430, 2.953e-02),
    "loamy_sand":   (12.40, 2.280, 0.057, 0.410, 1.452e-02),
    "sandy_loam":   ( 7.50, 1.890, 0.065, 0.410, 4.420e-03),
    "loam":         ( 3.60, 1.560, 0.078, 0.430, 1.040e-03),
    "silt_loam":    ( 2.00, 1.410, 0.067, 0.450, 4.500e-04),
    "silt":         ( 1.60, 1.370, 0.034, 0.460, 2.500e-04),
    "sandy_clay_loam": (5.90, 1.480, 0.100, 0.390, 1.310e-03),
    "clay_loam":    ( 1.90, 1.310, 0.095, 0.410, 2.600e-04),
    "silty_clay_loam": (1.00, 1.230, 0.089, 0.430, 1.700e-04),
    "sandy_clay":   ( 2.70, 1.230, 0.100, 0.380, 2.170e-04),
    "silty_clay":   ( 0.50, 1.090, 0.070, 0.360, 1.000e-04),
    "clay":         ( 0.80, 1.090, 0.068, 0.380, 8.333e-05),
}

# Specific storage (1/m) by texture class
SPECIFIC_STORAGE = {
    "sand": 5.0e-5, "loamy_sand": 5.0e-5, "sandy_loam": 1.0e-4,
    "loam": 1.0e-4, "silt_loam": 1.5e-4, "silt": 1.5e-4,
    "sandy_clay_loam": 1.0e-4, "clay_loam": 1.5e-4,
    "silty_clay_loam": 2.0e-4, "sandy_clay": 1.5e-4,
    "silty_clay": 2.0e-4, "clay": 2.5e-4,
}

# Default fallback
DEFAULT_TEXTURE = "loam"
# ===================================================================


def classify_soil_texture(sand, silt, clay):
    """
    USDA soil texture triangle classification.
    sand, silt, clay in percentage (0-100).
    """
    if sand + 0.5 * silt >= 70:
        if sand >= 85:
            return "sand"
        elif sand >= 70:
            return "loamy_sand"
        else:
            return "sandy_loam"
    elif clay >= 40:
        if silt >= 40:
            return "silty_clay"
        elif sand >= 45:
            return "sandy_clay"
        else:
            return "clay"
    elif clay >= 27:
        if sand >= 20 and sand < 45:
            return "clay_loam"
        elif sand < 20:
            return "silty_clay_loam"
        else:
            return "sandy_clay_loam"
    elif silt >= 50:
        if clay >= 12:
            return "silt_loam"
        else:
            return "silt"
    elif clay >= 7 and clay < 27 and sand < 52:
        return "loam"
    else:
        return "sandy_loam"


def validate_inputs(domain_json, mask_npy):
    errors = []
    if not os.path.exists(domain_json):
        errors.append(f"Domain definition not found: {domain_json}")
    if not os.path.exists(mask_npy):
        errors.append(f"Mask file not found: {mask_npy}")
    if not os.path.exists(HWSD_RASTER):
        errors.append(f"HWSD raster not found: {HWSD_RASTER}")
    return errors


def process(domain_json, mask_npy, output_dir, k_anisotropy_ratio=0.1):
    """
    Build subsurface properties from HWSD.

    Parameters
    ----------
    domain_json : str
        Path to domain definition JSON.
    mask_npy : str
        Path to 3D domain mask numpy file.
    output_dir : str
        Output directory for property arrays.
    k_anisotropy_ratio : float
        Kz/Kx ratio (typically 0.1 for layered sediments, 1.0 for isotropic).
    """
    os.makedirs(output_dir, exist_ok=True)

    # Load HWSD soil database for texture lookup
    import pandas as pd
    hwsd_csv = os.path.join(HYDROCRAFT_ROOT, "data/soil/HWSD_DATA.csv")
    if os.path.exists(hwsd_csv):
        process._hwsd_df = pd.read_csv(hwsd_csv, low_memory=False)
        print(f"Loaded HWSD database: {len(process._hwsd_df)} records")
    else:
        process._hwsd_df = None
        print(f"WARNING: HWSD_DATA.csv not found at {hwsd_csv}, using default loam texture")

    with open(domain_json) as f:
        domain = json.load(f)

    mask_3d = np.load(mask_npy)
    grid = domain["grid"]
    nx, ny, nz = grid["nx"], grid["ny"], grid["nz"]
    dx, dy = grid["dx"], grid["dy"]
    origin_x = domain["origin"]["x"]
    origin_y = domain["origin"]["y"]
    utm_epsg = domain["crs"]["epsg"]

    # Initialize property arrays (nz, ny, nx)
    perm_x = np.zeros((nz, ny, nx), dtype=np.float64)
    perm_y = np.zeros((nz, ny, nx), dtype=np.float64)
    perm_z = np.zeros((nz, ny, nx), dtype=np.float64)
    porosity = np.zeros((nz, ny, nx), dtype=np.float64)
    alpha = np.zeros((nz, ny, nx), dtype=np.float64)
    vg_n = np.zeros((nz, ny, nx), dtype=np.float64)
    s_res = np.zeros((nz, ny, nx), dtype=np.float64)
    s_sat = np.ones((nz, ny, nx), dtype=np.float64)
    spec_storage = np.zeros((nz, ny, nx), dtype=np.float64)

    # Create coordinate transformer UTM -> WGS84
    transformer = Transformer.from_crs(
        f"EPSG:{utm_epsg}", "EPSG:4326", always_xy=True
    )

    # For each active surface cell, sample HWSD
    texture_counts = {}
    with rasterio.open(HWSD_RASTER) as hwsd_src:
        for j in range(ny):
            for i in range(nx):
                if mask_3d[0, j, i] == 0:
                    continue

                # Cell center in UTM
                cx = origin_x + (i + 0.5) * dx
                cy = origin_y + (j + 0.5) * dy

                # Convert to WGS84
                lon, lat = transformer.transform(cx, cy)

                # Sample HWSD
                try:
                    row, col = hwsd_src.index(lon, lat)
                    mu_id = hwsd_src.read(1, window=rasterio.windows.Window(col, row, 1, 1))[0, 0]
                except Exception:
                    mu_id = 0

                # Look up sand/silt/clay from HWSD CSV database
                texture = DEFAULT_TEXTURE
                if mu_id > 0 and hasattr(process, '_hwsd_df'):
                    row_match = process._hwsd_df[process._hwsd_df['MU_GLOBAL'] == mu_id]
                    if len(row_match) > 0:
                        r = row_match.iloc[0]
                        t_sand = r.get('T_SAND', 0)
                        t_silt = r.get('T_SILT', 0)
                        t_clay = r.get('T_CLAY', 0)
                        if t_sand > 0 or t_silt > 0 or t_clay > 0:
                            texture = classify_soil_texture(
                                float(t_sand), float(t_silt), float(t_clay)
                            )

                texture_counts[texture] = texture_counts.get(texture, 0) + 1

                # Get van Genuchten parameters
                params = ROSETTA_VAN_GENUCHTEN.get(texture, ROSETTA_VAN_GENUCHTEN[DEFAULT_TEXTURE])
                a, n_vg, tr, ts, ks = params
                ss = SPECIFIC_STORAGE.get(texture, 1.0e-4)

                # Assign to all layers
                # NOTE: In a more sophisticated setup, deeper layers would use
                # GLHYMPS properties instead of HWSD (which is top 0-2m only)
                for k in range(nz):
                    perm_x[k, j, i] = ks
                    perm_y[k, j, i] = ks
                    perm_z[k, j, i] = ks * k_anisotropy_ratio
                    porosity[k, j, i] = ts
                    alpha[k, j, i] = a
                    vg_n[k, j, i] = n_vg
                    s_res[k, j, i] = tr
                    s_sat[k, j, i] = ts  # ParFlow Ssat = porosity
                    spec_storage[k, j, i] = ss

    # Save all arrays
    outputs = {}
    for name, arr in [
        ("permeability_x", perm_x),
        ("permeability_y", perm_y),
        ("permeability_z", perm_z),
        ("porosity", porosity),
        ("vangenuchten_alpha", alpha),
        ("vangenuchten_n", vg_n),
        ("residual_saturation", s_res),
        ("saturation_at_saturation", s_sat),
        ("specific_storage", spec_storage),
    ]:
        path = os.path.join(output_dir, f"{name}.npy")
        np.save(path, arr)
        outputs[name] = path

        # Also try PFB
        try:
            from parflow.tools.io import write_pfb
            pfb_path = os.path.join(output_dir, f"{name}.pfb")
            write_pfb(pfb_path, arr, dx=dx, dy=dy, dz=1.0,
                      x=origin_x, y=origin_y, z=0.0)
            outputs[f"{name}_pfb"] = pfb_path
        except ImportError:
            pass

    # Statistics
    active_mask = mask_3d > 0
    stats = {}
    for name, arr in [("K_m_hr", perm_x), ("porosity", porosity),
                       ("alpha_1_m", alpha), ("vg_n", vg_n)]:
        valid = arr[active_mask]
        if len(valid) > 0:
            stats[name] = {
                "min": float(np.min(valid)),
                "max": float(np.max(valid)),
                "mean": float(np.mean(valid)),
            }

    result = {
        "status": "success",
        "output_files": outputs,
        "texture_distribution": texture_counts,
        "k_anisotropy_ratio": k_anisotropy_ratio,
        "stats": stats,
        "unit_warnings": [
            "K is in m/hr (ParFlow default). NOT m/day (MODFLOW) or m/s (SI).",
            "Alpha is in 1/m (ParFlow). NOT 1/cm (Rosetta raw output -- divide by 100).",
            "Pressure head is in meters of water. NOT Pa or kPa.",
        ],
    }
    return result


def validate_outputs(result):
    warnings = []
    stats = result.get("stats", {})
    k_stats = stats.get("K_m_hr", {})
    if k_stats:
        if k_stats["max"] > 1.0:
            warnings.append(
                f"Max K = {k_stats['max']:.4f} m/hr is very high -- "
                "verify units (should be m/hr, not m/s)"
            )
        if k_stats["min"] < 1e-8:
            warnings.append(
                f"Min K = {k_stats['min']:.2e} m/hr is extremely low -- "
                "may cause solver convergence issues"
            )
    alpha_stats = stats.get("alpha_1_m", {})
    if alpha_stats:
        if alpha_stats["max"] > 50:
            warnings.append(
                f"Max alpha = {alpha_stats['max']:.1f} 1/m seems high -- "
                "verify units (should be 1/m, not 1/cm)"
            )
    return warnings


def main():
    parser = argparse.ArgumentParser(
        description="Build ParFlow subsurface properties from HWSD"
    )
    parser.add_argument("--domain_json", required=True)
    parser.add_argument("--mask_npy", required=True)
    parser.add_argument("--output_dir", required=True)
    parser.add_argument("--k_anisotropy", type=float, default=0.1,
                        help="Kz/Kx ratio (default 0.1)")
    args = parser.parse_args()

    errs = validate_inputs(args.domain_json, args.mask_npy)
    if errs:
        print(json.dumps({"status": "error", "errors": errs}))
        sys.exit(1)

    result = process(args.domain_json, args.mask_npy, args.output_dir,
                     args.k_anisotropy)

    warnings = validate_outputs(result)
    if warnings:
        result["warnings"] = warnings

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
