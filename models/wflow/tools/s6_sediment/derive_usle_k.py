#!/usr/bin/env python3
"""
derive_usle_k.py -- Derive USLE K-factor (soil erodibility) from HWSD soil
texture data for wflow_sediment staticmaps.

Computes USLE K using the Wischmeier & Smith (1978) nomograph equation:

    K = [2.1e-4 * M^1.14 * (12 - OM) + 3.25*(s-2) + 2.5*(p-3)] / 100

Where:
    M  = (% silt + 0.2 * % sand) * (100 - % clay)
    OM = organic matter (%) = OC * 1.724 (Van Bemmelen factor)
    s  = soil structure code (1-4, default 2 = medium granular)
    p  = permeability class (1-6, default 3 = slow-to-moderate)

K is in SI units: t*ha*h/(ha*MJ*mm)

Supports two modes:
  1. Grid mode: reads an existing wflow staticmaps.nc, extracts lat/lon grid,
     looks up HWSD for every active cell, computes K, and writes USLE_K into
     a new or patched NetCDF.
  2. Point mode: computes K for a single lat/lon (for testing/verification).

Data source: HWSD v1.2 via ki_tools_common.soil_utils.lookup_hwsd

Usage:
    # Grid mode (main use case):
    python derive_usle_k.py --staticmaps /path/to/staticmaps.nc \
        --output /path/to/usle_k.nc

    # Grid mode with patch (writes USLE_K directly into staticmaps_sediment.nc):
    python derive_usle_k.py --staticmaps /path/to/staticmaps.nc \
        --patch_nc /path/to/staticmaps_sediment.nc

    # Point mode (verification):
    python derive_usle_k.py --lat 32.93 --lon 117.36

    # Use SoilGrids instead of HWSD (Bengbu region only):
    python derive_usle_k.py --staticmaps /path/to/staticmaps.nc \
        --output /path/to/usle_k.nc --soil_source soilgrids
"""

import argparse
import json
import os
import sys

import numpy as np

sys.path.insert(0, "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect")

# ---------------------------------------------------------------------------
# USLE K computation (Wischmeier & Smith 1978)
# ---------------------------------------------------------------------------

# Soil structure codes (Wischmeier & Smith, 1978, Table 2):
#   1 = very fine granular     (clayey, well-aggregated)
#   2 = fine granular          (medium structure, most common)
#   3 = medium/coarse granular (moderate aggregation)
#   4 = blocky/platy/massive   (poor structure)
STRUCTURE_CODE_DEFAULT = 2

# Permeability classes (Wischmeier & Smith, 1978, Table 3):
#   1 = rapid           (sand, loamy sand)
#   2 = moderate-rapid  (sandy loam)
#   3 = moderate        (loam, silt loam)
#   4 = slow-moderate   (clay loam)
#   5 = slow            (silty clay loam)
#   6 = very slow       (clay)
PERMEABILITY_CLASS_DEFAULT = 3


def permeability_class_from_texture(sand, clay):
    """Estimate USDA permeability class from texture percentages.

    Parameters
    ----------
    sand, clay : float or ndarray -- percentages (0-100)

    Returns
    -------
    perm_class : int or ndarray -- permeability class (1-6)
    """
    sand = np.asarray(sand, dtype=np.float64)
    clay = np.asarray(clay, dtype=np.float64)

    perm = np.full_like(sand, 3, dtype=np.int32)  # default moderate
    perm = np.where(sand >= 85, 1, perm)           # rapid (sand)
    perm = np.where((sand >= 65) & (sand < 85) & (clay < 15), 2, perm)  # mod-rapid
    perm = np.where((clay >= 27) & (clay < 40), 4, perm)   # slow-moderate
    perm = np.where((clay >= 40) & (clay < 55), 5, perm)   # slow
    perm = np.where(clay >= 55, 6, perm)                   # very slow

    return perm


def structure_code_from_texture(sand, clay, om_pct):
    """Estimate soil structure code from texture and organic matter.

    Parameters
    ----------
    sand, clay : float or ndarray -- percentages (0-100)
    om_pct : float or ndarray -- organic matter percentage

    Returns
    -------
    struct_code : int or ndarray -- structure code (1-4)
    """
    sand = np.asarray(sand, dtype=np.float64)
    clay = np.asarray(clay, dtype=np.float64)
    om_pct = np.asarray(om_pct, dtype=np.float64)

    # Default: medium granular (2)
    sc = np.full_like(sand, 2, dtype=np.int32)

    # High clay + high OM -> very fine granular (1)
    sc = np.where((clay >= 35) & (om_pct >= 3.0), 1, sc)

    # Low OM + high sand -> coarse (3)
    sc = np.where((om_pct < 1.0) & (sand >= 50), 3, sc)

    # Very low OM and high clay -> blocky/massive (4)
    sc = np.where((om_pct < 0.5) & (clay >= 40), 4, sc)

    return sc


def compute_usle_k(sand_pct, silt_pct, clay_pct, oc_pct=1.0,
                   struct_code=None, perm_class=None):
    """Compute USLE K-factor using Wischmeier & Smith (1978) nomograph.

    Parameters
    ----------
    sand_pct : float or ndarray -- sand content (%)
    silt_pct : float or ndarray -- silt content (%)
    clay_pct : float or ndarray -- clay content (%)
    oc_pct : float or ndarray -- organic carbon (%), converted to OM internally
    struct_code : int or ndarray or None -- soil structure code (1-4)
    perm_class : int or ndarray or None -- permeability class (1-6)

    Returns
    -------
    K : float or ndarray -- USLE K factor in SI units (t*ha*h/(ha*MJ*mm))
        Typical range: 0.001 - 0.1
    """
    sand = np.asarray(sand_pct, dtype=np.float64)
    silt = np.asarray(silt_pct, dtype=np.float64)
    clay = np.asarray(clay_pct, dtype=np.float64)
    oc = np.asarray(oc_pct, dtype=np.float64)

    # Convert organic carbon to organic matter (Van Bemmelen factor)
    om = oc * 1.724
    # Cap OM at 4% for the Wischmeier equation (above 4% the linear
    # approximation overestimates the OM reduction effect)
    om = np.clip(om, 0.0, 4.0)

    # Modified silt factor M
    M = (silt + 0.2 * sand) * (100.0 - clay)

    # Estimate structure and permeability codes from texture if not provided
    if struct_code is None:
        s = structure_code_from_texture(sand, clay, om)
    else:
        s = np.asarray(struct_code, dtype=np.float64)

    if perm_class is None:
        p = permeability_class_from_texture(sand, clay)
    else:
        p = np.asarray(perm_class, dtype=np.float64)

    # Wischmeier & Smith (1978) nomograph equation
    # This gives K in US customary units (ton*acre*h / (100*acre*ft-tonf*in))
    K_us = (
        2.1e-4 * np.power(M, 1.14) * (12.0 - om)
        + 3.25 * (s - 2.0)
        + 2.5 * (p - 3.0)
    ) / 100.0

    # Convert to SI: t*ha*h/(ha*MJ*mm)
    # Conversion factor: 1 US K unit = 0.1317 SI K unit
    # Reference: Foster et al. (1981); Renard et al. (1997) RUSLE handbook
    K = K_us * 0.1317

    # Clamp to physically reasonable range (SI)
    # Typical: 0.001 (clay, resistant) to 0.070 (silt, very erodible)
    K = np.clip(K, 0.001, 0.070)

    return K


# ---------------------------------------------------------------------------
# Grid mode: derive K for every cell in a wflow staticmaps.nc
# ---------------------------------------------------------------------------

def derive_k_grid(staticmaps_path, soil_source="hwsd"):
    """Derive USLE K factor for every active cell in a wflow staticmaps.nc.

    Parameters
    ----------
    staticmaps_path : str -- path to wflow staticmaps.nc
    soil_source : str -- "hwsd" or "soilgrids"

    Returns
    -------
    dict with keys: K_array (2D ndarray), lats, lons, mask, stats
    """
    import xarray as xr

    ds = xr.open_dataset(staticmaps_path)

    # Get coordinate arrays
    if "lat" in ds.coords:
        lats = ds["lat"].values
        lons = ds["lon"].values
    elif "y" in ds.coords:
        lats = ds["y"].values
        lons = ds["x"].values
    else:
        raise ValueError("Cannot find lat/lon or y/x coordinates in staticmaps")

    # Get basin mask
    if "wflow_subcatch" in ds:
        mask = ds["wflow_subcatch"].values > 0
    else:
        first_var = list(ds.data_vars)[0]
        mask = np.isfinite(ds[first_var].values) & (ds[first_var].values != 0)

    ny, nx = mask.shape
    print(f"  Grid: {nx} x {ny}, active cells: {mask.sum()}", file=sys.stderr)

    # Initialize output arrays
    K_array = np.full((ny, nx), np.nan, dtype=np.float32)
    sand_array = np.full((ny, nx), np.nan, dtype=np.float32)
    silt_array = np.full((ny, nx), np.nan, dtype=np.float32)
    clay_array = np.full((ny, nx), np.nan, dtype=np.float32)
    oc_array = np.full((ny, nx), np.nan, dtype=np.float32)

    if soil_source == "hwsd":
        from ki_tools_common.soil_utils import lookup_hwsd

        n_active = int(mask.sum())
        n_done = 0
        n_water = 0

        for i in range(ny):
            for j in range(nx):
                if not mask[i, j]:
                    continue

                lat = float(lats[i])
                lon = float(lons[j])

                props = lookup_hwsd(lat, lon)

                if props["mu_id"] == 0:
                    # Water/ice/rock: use moderate default
                    sand_array[i, j] = 40.0
                    silt_array[i, j] = 40.0
                    clay_array[i, j] = 20.0
                    oc_array[i, j] = 1.5
                    n_water += 1
                else:
                    sand_array[i, j] = props["sand"]
                    silt_array[i, j] = props["silt"]
                    clay_array[i, j] = props["clay"]
                    oc_array[i, j] = props["oc"]

                n_done += 1
                if n_done % 50 == 0:
                    print(f"  HWSD lookup: {n_done}/{n_active} cells done",
                          file=sys.stderr)

        if n_water > 0:
            print(f"  WARNING: {n_water} cells had MU_GLOBAL=0 (water/ice/rock), "
                  f"using default texture (loam)", file=sys.stderr)

    elif soil_source == "soilgrids":
        # SoilGrids 250m (Bengbu region only: 113-118E, 31-35N)
        _derive_k_from_soilgrids(lats, lons, mask, sand_array, silt_array,
                                  clay_array, oc_array)
    else:
        raise ValueError(f"Unknown soil_source: {soil_source}. Use 'hwsd' or 'soilgrids'.")

    # Compute K for all active cells at once (vectorized)
    active_sand = np.where(mask, np.nan_to_num(sand_array, nan=40.0), 0.0)
    active_silt = np.where(mask, np.nan_to_num(silt_array, nan=40.0), 0.0)
    active_clay = np.where(mask, np.nan_to_num(clay_array, nan=20.0), 0.0)
    active_oc = np.where(mask, np.nan_to_num(oc_array, nan=1.5), 0.0)

    K_values = compute_usle_k(active_sand, active_silt, active_clay, active_oc)
    K_array = np.where(mask, K_values.astype(np.float32), np.nan)

    # Statistics
    valid_K = K_array[mask]
    stats = {
        "mean_K": round(float(np.nanmean(valid_K)), 5),
        "min_K": round(float(np.nanmin(valid_K)), 5),
        "max_K": round(float(np.nanmax(valid_K)), 5),
        "std_K": round(float(np.nanstd(valid_K)), 5),
        "n_cells": int(mask.sum()),
        "soil_source": soil_source,
    }

    ds.close()

    return {
        "K_array": K_array,
        "sand_array": sand_array,
        "silt_array": silt_array,
        "clay_array": clay_array,
        "oc_array": oc_array,
        "lats": lats,
        "lons": lons,
        "mask": mask,
        "stats": stats,
    }


def _derive_k_from_soilgrids(lats, lons, mask, sand_array, silt_array,
                               clay_array, oc_array):
    """Fill texture arrays from SoilGrids GeoTIFFs (Bengbu region only)."""
    try:
        import rasterio
    except ImportError:
        print("ERROR: rasterio required for SoilGrids. "
              "Install with: pip install rasterio", file=sys.stderr)
        sys.exit(1)

    soilgrids_dir = "KISSPATH_HOME/Crop_model_dataset/SoilGrids_Bengbu"
    depth = "0-5cm"  # topsoil for USLE

    files = {
        "sand": os.path.join(soilgrids_dir, f"sand_{depth}_mean.tif"),
        "silt": os.path.join(soilgrids_dir, f"silt_{depth}_mean.tif"),
        "clay": os.path.join(soilgrids_dir, f"clay_{depth}_mean.tif"),
        "soc": os.path.join(soilgrids_dir, f"soc_{depth}_mean.tif"),
    }

    for name, path in files.items():
        if not os.path.exists(path):
            print(f"WARNING: SoilGrids file not found: {path}. "
                  f"Falling back to defaults.", file=sys.stderr)
            return

    ny, nx = mask.shape

    for name, path in files.items():
        with rasterio.open(path) as src:
            for i in range(ny):
                for j in range(nx):
                    if not mask[i, j]:
                        continue
                    lat = float(lats[i])
                    lon = float(lons[j])

                    try:
                        row, col = src.index(lon, lat)
                        val = int(src.read(1, window=rasterio.windows.Window(
                            col, row, 1, 1))[0, 0])
                    except Exception:
                        val = -32768

                    if val == -32768:
                        continue

                    # SoilGrids units: sand/silt/clay in g/kg -> % (/10)
                    # SOC in dg/kg -> % (/100, since OC% = g/kg / 10)
                    if name == "sand":
                        sand_array[i, j] = val / 10.0
                    elif name == "silt":
                        silt_array[i, j] = val / 10.0
                    elif name == "clay":
                        clay_array[i, j] = val / 10.0
                    elif name == "soc":
                        # dg/kg -> g/kg: /10, then g/kg -> %: /10 => /100
                        oc_array[i, j] = val / 100.0

    print(f"  SoilGrids lookup complete (depth={depth})", file=sys.stderr)


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def write_output(result, output_path, staticmaps_path):
    """Write USLE_K as a standalone NetCDF file."""
    import xarray as xr

    ds_ref = xr.open_dataset(staticmaps_path)

    # Determine coordinate names
    if "lat" in ds_ref.coords:
        y_name, x_name = "lat", "lon"
    else:
        y_name, x_name = "y", "x"

    coords = {
        y_name: result["lats"],
        x_name: result["lons"],
    }

    ds_out = xr.Dataset(
        {
            "USLE_K": ([y_name, x_name], result["K_array"],
                       {"long_name": "USLE K factor (soil erodibility)",
                        "units": "t*ha*h/(ha*MJ*mm)",
                        "source": f"Wischmeier-Smith 1978, soil={result['stats']['soil_source']}",
                        "valid_range": [0.001, 0.070]}),
        },
        coords=coords,
    )

    ds_out.attrs["title"] = "USLE K-factor derived from soil texture"
    ds_out.attrs["method"] = "Wischmeier-Smith (1978) nomograph equation"
    ds_out.attrs["tool"] = "derive_usle_k.py (wflow KI)"

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    ds_out.to_netcdf(output_path)
    ds_ref.close()

    print(f"  Written USLE_K to {output_path}", file=sys.stderr)


def patch_netcdf(result, patch_nc_path):
    """Write USLE_K into an existing staticmaps_sediment.nc."""
    import xarray as xr

    ds = xr.open_dataset(patch_nc_path)

    # Determine coordinate names
    if "lat" in ds.coords:
        y_name, x_name = "lat", "lon"
    else:
        y_name, x_name = "y", "x"

    ds["USLE_K"] = xr.DataArray(
        result["K_array"],
        dims=[y_name, x_name],
        attrs={
            "long_name": "USLE K factor (soil erodibility)",
            "units": "t*ha*h/(ha*MJ*mm)",
            "source": f"Wischmeier-Smith 1978, soil={result['stats']['soil_source']}",
        },
    )

    ds.to_netcdf(patch_nc_path + ".tmp")
    ds.close()

    os.replace(patch_nc_path + ".tmp", patch_nc_path)
    print(f"  Patched USLE_K into {patch_nc_path}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Point mode
# ---------------------------------------------------------------------------

def point_mode(lat, lon, soil_source="hwsd"):
    """Compute USLE K for a single point (verification mode)."""
    if soil_source == "hwsd":
        from ki_tools_common.soil_utils import lookup_hwsd
        props = lookup_hwsd(lat, lon)
        sand, silt, clay = props["sand"], props["silt"], props["clay"]
        oc = props["oc"]
        texture = props["texture"]
        mu_id = props["mu_id"]
    else:
        raise ValueError("Point mode only supports 'hwsd' soil source")

    om = oc * 1.724
    K = float(compute_usle_k(sand, silt, clay, oc))

    result = {
        "lat": lat,
        "lon": lon,
        "soil_source": soil_source,
        "mu_id": mu_id,
        "sand_pct": round(sand, 1),
        "silt_pct": round(silt, 1),
        "clay_pct": round(clay, 1),
        "oc_pct": round(oc, 2),
        "om_pct": round(min(om, 4.0), 2),
        "texture": texture,
        "USLE_K": round(K, 5),
        "K_interpretation": _interpret_k(K),
    }
    return result


def _interpret_k(K):
    """Interpret K factor value."""
    if K < 0.01:
        return "very low erodibility (resistant soil)"
    elif K < 0.025:
        return "low erodibility"
    elif K < 0.04:
        return "moderate erodibility"
    elif K < 0.06:
        return "high erodibility"
    else:
        return "very high erodibility (silt-rich soil)"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Derive USLE K-factor from soil texture (HWSD or SoilGrids) "
                    "for wflow_sediment.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Grid mode: derive K for all cells
    python derive_usle_k.py --staticmaps staticmaps.nc --output usle_k.nc

    # Grid mode: patch into existing sediment staticmaps
    python derive_usle_k.py --staticmaps staticmaps.nc \\
        --patch_nc staticmaps_sediment.nc

    # Point mode: check single location
    python derive_usle_k.py --lat 32.93 --lon 117.36

    # Use SoilGrids (Bengbu only, 250m resolution)
    python derive_usle_k.py --staticmaps staticmaps.nc --output usle_k.nc \\
        --soil_source soilgrids

Method:
    Wischmeier & Smith (1978) nomograph equation:
    K = [2.1e-4 * M^1.14 * (12-OM) + 3.25*(s-2) + 2.5*(p-3)] / 100

    Where M = (%silt + 0.2*%sand) * (100 - %clay)
    OM = organic matter (%), s = structure code (1-4), p = permeability (1-6)

    Output range: 0.001 - 0.070 t*ha*h/(ha*MJ*mm) (SI units)

Reference:
    Wischmeier, W.H. and Smith, D.D. (1978). Predicting Rainfall Erosion
    Losses. Agriculture Handbook No. 537, USDA.
        """,
    )
    parser.add_argument("--staticmaps", type=str,
                        help="Path to wflow staticmaps.nc (grid mode)")
    parser.add_argument("--output", type=str,
                        help="Output NetCDF file for USLE_K (grid mode)")
    parser.add_argument("--patch_nc", type=str,
                        help="Existing staticmaps_sediment.nc to patch with USLE_K")
    parser.add_argument("--lat", type=float,
                        help="Latitude for point mode")
    parser.add_argument("--lon", type=float,
                        help="Longitude for point mode")
    parser.add_argument("--soil_source", type=str, default="hwsd",
                        choices=["hwsd", "soilgrids"],
                        help="Soil data source (default: hwsd)")

    args = parser.parse_args()

    # --- Point mode ---
    if args.lat is not None and args.lon is not None:
        result = point_mode(args.lat, args.lon, args.soil_source)
        print(json.dumps(result, indent=2))
        return

    # --- Grid mode ---
    if not args.staticmaps:
        parser.error("Provide --staticmaps (grid mode) or --lat/--lon (point mode)")
    if not args.output and not args.patch_nc:
        parser.error("Provide --output or --patch_nc for grid mode")

    if not os.path.exists(args.staticmaps):
        print(f"ERROR: staticmaps not found: {args.staticmaps}", file=sys.stderr)
        sys.exit(1)

    print(f"Deriving USLE K-factor from {args.soil_source.upper()}...",
          file=sys.stderr)

    result = derive_k_grid(args.staticmaps, args.soil_source)
    stats = result["stats"]

    if args.output:
        write_output(result, args.output, args.staticmaps)

    if args.patch_nc:
        if not os.path.exists(args.patch_nc):
            print(f"ERROR: patch target not found: {args.patch_nc}", file=sys.stderr)
            sys.exit(1)
        patch_netcdf(result, args.patch_nc)

    # Print summary
    output = {
        "status": "success",
        "soil_source": args.soil_source,
        "stats": stats,
    }
    if args.output:
        output["output_file"] = args.output
    if args.patch_nc:
        output["patched_file"] = args.patch_nc

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
