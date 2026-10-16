#!/usr/bin/env python3
"""
Build subsurface property fields for ParFlow from HWSD soil data.

Maps soil texture to van Genuchten parameters (alpha, n, Sres, Ssat) and
hydraulic conductivity (K) using Rosetta pedotransfer functions.

**CRITICAL UNIT: ParFlow K is in m/hr** (NOT m/day = 24x error, NOT m/s = 3600x error)
**CRITICAL UNIT: van Genuchten alpha is 1/m** (NOT 1/cm = 100x error)

Reads HWSD directly (not ki_tools_common lookup_hwsd): the hwsd.bil raster gives
the mapping unit at each cell centre, and the dominant row of HWSD_DATA.csv
(largest SHARE; ties -> lowest SEQ) gives topsoil T_SAND/T_SILT/T_CLAY -> USDA
texture class.

Every cell of the rectangular grid gets its own HWSD texture, inside AND outside
the basin mask: the s7 run script uses Box geometry (no SolidFile mask;
pfmask-to-pfsol is not installed), so ParFlow simulates every cell of the
rectangle. There is no default and no fill texture: if any cell has no HWSD
texture (raster read fails, no mapping unit such as water, unit not in the CSV,
or no topsoil sand/silt/clay) the tool stops and lists the first 10 failing
cells (with inside/outside mask) and the count.

Saturation exports are ParFlow saturation FRACTIONS: residual_saturation =
theta_r / theta_s and saturation_at_saturation = 1.0 (same as the s7 generator).

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

# There is NO default texture: every cell's texture must come from HWSD
# (raster mapping unit -> dominant HWSD_DATA row -> topsoil sand/silt/clay),
# otherwise the tool stops and lists the failing cells.
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


def dominant_hwsd_rows(df):
    """One row per MU_GLOBAL: the component with the largest SHARE (percent of
    the mapping unit). Ties (and rows with no SHARE) are broken by lowest SEQ.
    HWSD SEQ is NOT a reliable share order (e.g. unit 2: SEQ 1 = 25 %,
    SEQ 3 = 30 %)."""
    share = df["SHARE"] if "SHARE" in df.columns else None
    if share is None:
        raise ValueError("HWSD_DATA.csv has no SHARE column; cannot pick the dominant component")
    tmp = df.assign(_share=share.astype(float))
    return (tmp.sort_values(["MU_GLOBAL", "_share", "SEQ"], ascending=[True, False, True],
                            na_position="last", kind="mergesort")
            .drop_duplicates("MU_GLOBAL", keep="first").drop(columns="_share")
            .set_index("MU_GLOBAL"))


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
    if not os.path.exists(hwsd_csv):
        # No silent all-loam fallback: that would be a silent-substitution bug
        raise FileNotFoundError(f"HWSD_DATA.csv not found at {hwsd_csv}")
    process._hwsd_df = pd.read_csv(hwsd_csv, low_memory=False)
    print(f"Loaded HWSD database: {len(process._hwsd_df)} records")

    with open(domain_json) as f:
        domain = json.load(f)

    mask_3d = np.load(mask_npy)
    grid = domain["grid"]
    nx, ny, nz = grid["nx"], grid["ny"], grid["nz"]
    dx, dy = grid["dx"], grid["dy"]
    origin_x = domain["origin"]["x"]
    origin_y = domain["origin"]["y"]
    utm_epsg = domain["crs"]["epsg"]
    if mask_3d.shape != (nz, ny, nx):
        raise ValueError(f"mask shape {mask_3d.shape} does not match grid ({nz}, {ny}, {nx})")
    if not np.any(mask_3d[0] != 0):
        raise ValueError("domain mask has no active surface cell; nothing to build")

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

    # For EVERY surface cell, sample HWSD. The run script's geometry is the
    # full Box, so cells outside the basin mask are simulated too and need
    # their own soil (no fill class, no default).
    texture_counts = {}
    texture_names = list(ROSETTA_VAN_GENUCHTEN.keys())  # stable class codes
    tex_code_2d = np.zeros((ny, nx), dtype=np.int32)
    failures = []  # (i, j, lon, lat, in_mask, reason) for cells with no HWSD texture
    hwsd_dom = dominant_hwsd_rows(process._hwsd_df)
    with rasterio.open(HWSD_RASTER) as hwsd_src:
        for j in range(ny):
            for i in range(nx):
                in_mask = bool(mask_3d[0, j, i] != 0)
                # Cell center in UTM
                cx = origin_x + (i + 0.5) * dx
                cy = origin_y + (j + 0.5) * dy

                # Convert to WGS84
                lon, lat = transformer.transform(cx, cy)

                # Sample HWSD. Any failure is recorded for this cell; the
                # tool stops after the loop (no stand-in texture).
                try:
                    row, col = hwsd_src.index(lon, lat)
                    if not (0 <= row < hwsd_src.height and 0 <= col < hwsd_src.width):
                        raise ValueError(f"outside the HWSD raster (row {row}, col {col})")
                    mu_id = int(hwsd_src.read(1, window=rasterio.windows.Window(col, row, 1, 1))[0, 0])
                except Exception as exc:
                    failures.append((i, j, lon, lat, in_mask, f"raster sampling failed: {exc}"))
                    continue
                if mu_id <= 0 or (hwsd_src.nodata is not None and mu_id == hwsd_src.nodata):
                    failures.append((i, j, lon, lat, in_mask, f"no HWSD mapping unit (value {mu_id})"))
                    continue
                if mu_id not in hwsd_dom.index:
                    failures.append((i, j, lon, lat, in_mask, f"MU_GLOBAL {mu_id} not in HWSD_DATA.csv"))
                    continue
                r = hwsd_dom.loc[mu_id]
                fr = {k: r.get(k) for k in ("T_SAND", "T_SILT", "T_CLAY")}
                try:
                    vals = {k: float(v) for k, v in fr.items()}
                except (TypeError, ValueError):
                    vals = None
                if (vals is None or not all(np.isfinite(v) for v in vals.values())
                        or sum(vals.values()) <= 0):
                    failures.append((i, j, lon, lat, in_mask,
                                     f"MU_GLOBAL {mu_id} dominant row (SEQ {r.get('SEQ')}, "
                                     f"ISSOIL {r.get('ISSOIL')}) has no topsoil texture {fr}"))
                    continue
                texture = classify_soil_texture(vals["T_SAND"], vals["T_SILT"], vals["T_CLAY"])

                texture_counts[texture] = texture_counts.get(texture, 0) + 1
                tex_code_2d[j, i] = texture_names.index(texture) + 1

                # Get van Genuchten parameters (every class has an entry)
                a, n_vg, tr, ts, ks = ROSETTA_VAN_GENUCHTEN[texture]
                ss = SPECIFIC_STORAGE[texture]

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
                    # ParFlow VanGenuchten SRes/SSat are saturation
                    # FRACTIONS (0-1), not water contents: SRes = theta_r /
                    # theta_s, SSat = 1.0 (as the s7 generator writes them).
                    s_res[k, j, i] = round(tr / ts, 4)
                    s_sat[k, j, i] = 1.0
                    spec_storage[k, j, i] = ss

    # IndicatorField for the run script (washita LW_Test.py pattern): integer
    # texture class per cell, replicated over all layers, plus the class->
    # parameter table the s7 script generator consumes.
    if failures:
        n_out = sum(1 for f in failures if not f[4])
        lines = [f"  cell (i={i}, j={j}) lon={lon:.5f} lat={lat:.5f} "
                 f"{'inside' if m else 'OUTSIDE'} basin mask: {why}"
                 for i, j, lon, lat, m, why in failures[:10]]
        raise ValueError(
            f"HWSD gave no soil texture for {len(failures)} cell(s) ({n_out} outside the "
            f"basin mask); no default or fill texture is used. The run script uses Box "
            f"geometry, so every cell of the rectangle is simulated and needs real soil: "
            f"shrink/move the domain rectangle or fix the soil source. "
            f"First {len(lines)}:\n" + "\n".join(lines))
    if np.any(tex_code_2d == 0):
        raise RuntimeError("internal error: a cell has no texture class after sampling")
    tex_code_3d = np.repeat(tex_code_2d[np.newaxis, :, :], nz, axis=0)
    tex_params = {}
    for code in np.unique(tex_code_3d):
        name = texture_names[int(code) - 1]
        a, n_vg, tr, ts, ks = ROSETTA_VAN_GENUCHTEN[name]
        tex_params[int(code)] = {
            "name": name, "ks_m_hr": ks, "porosity": ts,
            "alpha_1m": a, "n": n_vg, "sres": tr,
            "ss_1m": SPECIFIC_STORAGE[name],
        }

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
        ("texture_indicator", tex_code_3d.astype(np.float64)),
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

    # Statistics over every simulated cell (the whole Box)
    active_mask = np.ones((nz, ny, nx), dtype=bool)
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

    params_path = os.path.join(output_dir, "texture_params.json")
    with open(params_path, "w") as f:
        json.dump(tex_params, f, indent=2)
    outputs["texture_params_json"] = params_path

    result = {
        "status": "success",
        "output_files": outputs,
        "texture_distribution": texture_counts,
        "texture_source": ("HWSD dominant component (largest SHARE, ties -> lowest SEQ) "
                           "topsoil T_SAND/T_SILT/T_CLAY; no default"),
        "texture_cells": ("every cell of the rectangular grid (s7 uses Box geometry, so "
                          "cells outside the basin mask are simulated with their own HWSD soil)"),
        "cells_outside_mask": int(np.sum(mask_3d[0] == 0)),
        "saturation_fields": "residual_saturation = theta_r/theta_s, saturation_at_saturation = 1.0 (fractions)",
        "k_anisotropy_ratio": k_anisotropy_ratio,
        "stats": stats,
        "unit_warnings": [
            "K is in m/hr (ParFlow default). NOT m/day (MODFLOW) or m/s (SI).",
            "Alpha is in 1/m (ParFlow). NOT 1/cm (Rosetta raw output -- multiply 1/cm by 100 to get 1/m, e.g. 0.036/cm = 3.6/m).",
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

    try:
        result = process(args.domain_json, args.mask_npy, args.output_dir,
                         args.k_anisotropy)
    except (ValueError, FileNotFoundError) as exc:
        print(json.dumps({"status": "error", "errors": [str(exc)]}, indent=2))
        sys.exit(1)

    warnings = validate_outputs(result)
    if warnings:
        result["warnings"] = warnings

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
