#!/usr/bin/env python3
"""
derive_usle_c.py -- Derive USLE C-factor (cover management) from AVHRR land
cover classification for wflow_sediment staticmaps.

The USLE C-factor quantifies the effect of vegetation and land management on
erosion relative to bare soil (C=1.0). Values range from 0.001 (dense forest)
to 1.0 (bare soil).

Lookup table maps UMD 17-class land cover scheme to C-factor values based on
published USLE tables (Wischmeier & Smith 1978; Morgan 2005; Panagos et al. 2015).

Two UMD numbering conventions exist in HydroCraft:
  - "SKILL.md" convention (used in build_sediment_model.py): class 11=Wetland,
    12=Cropland, 16=Barren
  - "reclassify.py" convention (used in extract_landcover.py): class 11=Cropland,
    12=Bare Ground, 14=Wetland

This tool uses the reclassify.py convention (matching the actual AVHRR GeoTIFF)
and also supports a --class_scheme flag to select either convention.

Supports two modes:
  1. Grid mode: reads an existing wflow staticmaps.nc, extracts the extent,
     samples the AVHRR raster for every active cell, maps to C-factor.
  2. Point mode: returns the C-factor for a single lat/lon.

Data source: AVHRR 1km UMD Global Land Cover
    /mnt/disk1/Hydrocraft_server/data/landcover/AVHRR_1km_LANDCOVER_1981_1994.GLOBAL.tif

Usage:
    # Grid mode (main use case):
    python derive_usle_c.py --staticmaps /path/to/staticmaps.nc \
        --output /path/to/usle_c.nc

    # Grid mode: patch into existing sediment staticmaps
    python derive_usle_c.py --staticmaps /path/to/staticmaps.nc \
        --patch_nc /path/to/staticmaps_sediment.nc

    # Point mode (verification):
    python derive_usle_c.py --lat 32.93 --lon 117.36

    # Use the SKILL.md class numbering convention:
    python derive_usle_c.py --staticmaps staticmaps.nc --output usle_c.nc \
        --class_scheme skillmd
"""

import argparse
import json
import os
import sys

import numpy as np

# ---------------------------------------------------------------------------
# AVHRR Data
# ---------------------------------------------------------------------------

AVHRR_TIF = "/mnt/disk1/Hydrocraft_server/data/landcover/AVHRR_1km_LANDCOVER_1981_1994.GLOBAL.tif"

# ---------------------------------------------------------------------------
# USLE C-factor lookup tables for UMD land cover classes
# ---------------------------------------------------------------------------

# Convention 1: "reclassify.py" / actual AVHRR GeoTIFF (DEFAULT)
# This matches the pixel values in the AVHRR GeoTIFF file
USLE_C_AVHRR = {
    0:  0.0,     # Water -- no erosion
    1:  0.003,   # Evergreen Needleleaf Forest
    2:  0.003,   # Evergreen Broadleaf Forest
    3:  0.005,   # Deciduous Needleleaf Forest
    4:  0.005,   # Deciduous Broadleaf Forest
    5:  0.004,   # Mixed Forest
    6:  0.008,   # Woodland (closed canopy, some understory)
    7:  0.03,    # Wooded Grassland
    8:  0.015,   # Closed Shrubland
    9:  0.05,    # Open Shrubland
    10: 0.03,    # Grassland (perennial cover)
    11: 0.30,    # Cropland (annual crops, seasonal exposure)
    12: 0.90,    # Bare Ground (near bare-soil reference)
    13: 0.01,    # Urban (impervious surfaces, low splash erosion)
    14: 0.0,     # Permanent Wetlands -- no overland erosion
    15: 0.0,     # Snow and Ice -- no erosion
    16: 0.45,    # Barren or Sparsely Vegetated
}

# Convention 2: "SKILL.md" / build_sediment_model.py convention
# Different numbering (class 11=Wetland, 12=Cropland)
USLE_C_SKILLMD = {
    0:  0.0,     # Water
    1:  0.003,   # Evergreen Needleleaf Forest
    2:  0.003,   # Evergreen Broadleaf Forest
    3:  0.005,   # Deciduous Needleleaf Forest
    4:  0.005,   # Deciduous Broadleaf Forest
    5:  0.004,   # Mixed Forest
    6:  0.015,   # Closed Shrubland
    7:  0.05,    # Open Shrubland
    8:  0.008,   # Woody Savanna
    9:  0.05,    # Savanna
    10: 0.03,    # Grassland
    11: 0.0,     # Wetland
    12: 0.30,    # Cropland
    13: 0.01,    # Urban
    14: 0.15,    # Cropland/Natural Mosaic
    15: 0.0,     # Snow/Ice
    16: 0.45,    # Barren/Sparse
    17: 0.0,     # Unclassified
}

CLASS_NAMES_AVHRR = {
    0: "Water", 1: "Evergreen Needleleaf Forest",
    2: "Evergreen Broadleaf Forest", 3: "Deciduous Needleleaf Forest",
    4: "Deciduous Broadleaf Forest", 5: "Mixed Forest",
    6: "Woodland", 7: "Wooded Grassland",
    8: "Closed Shrubland", 9: "Open Shrubland",
    10: "Grassland", 11: "Cropland",
    12: "Bare Ground", 13: "Urban",
    14: "Permanent Wetlands", 15: "Snow and Ice",
    16: "Barren",
}

CLASS_NAMES_SKILLMD = {
    0: "Water", 1: "Evergreen Needleleaf Forest",
    2: "Evergreen Broadleaf Forest", 3: "Deciduous Needleleaf Forest",
    4: "Deciduous Broadleaf Forest", 5: "Mixed Forest",
    6: "Closed Shrubland", 7: "Open Shrubland",
    8: "Woody Savanna", 9: "Savanna",
    10: "Grassland", 11: "Wetland",
    12: "Cropland", 13: "Urban",
    14: "Cropland/Natural Mosaic", 15: "Snow/Ice",
    16: "Barren/Sparse", 17: "Unclassified",
}


def get_c_lookup(class_scheme="avhrr"):
    """Get the appropriate C-factor lookup table.

    Parameters
    ----------
    class_scheme : str -- "avhrr" (default) or "skillmd"

    Returns
    -------
    c_lookup : dict -- {class_code: C_factor}
    class_names : dict -- {class_code: class_name}
    """
    if class_scheme == "avhrr":
        return USLE_C_AVHRR, CLASS_NAMES_AVHRR
    elif class_scheme == "skillmd":
        return USLE_C_SKILLMD, CLASS_NAMES_SKILLMD
    else:
        raise ValueError(f"Unknown class_scheme: {class_scheme}. "
                         f"Use 'avhrr' or 'skillmd'.")


def landcover_to_c_factor(lc_array, c_lookup):
    """Convert a 2D land cover class array to USLE C-factor array.

    Parameters
    ----------
    lc_array : ndarray (2D, uint8) -- land cover class codes
    c_lookup : dict -- {class_code: C_factor}

    Returns
    -------
    c_array : ndarray (2D, float32) -- USLE C-factor values
    """
    c_array = np.full_like(lc_array, np.nan, dtype=np.float32)

    for code, c_val in c_lookup.items():
        c_array[lc_array == code] = c_val

    # Any unmapped codes (e.g., 255 nodata) remain NaN
    return c_array


# ---------------------------------------------------------------------------
# Grid mode
# ---------------------------------------------------------------------------

def derive_c_grid(staticmaps_path, avhrr_tif=None, class_scheme="avhrr"):
    """Derive USLE C-factor for every active cell in wflow staticmaps.nc.

    For each grid cell center, sample the AVHRR 1km land cover raster,
    then map the UMD class code to a C-factor value.

    Parameters
    ----------
    staticmaps_path : str -- path to wflow staticmaps.nc
    avhrr_tif : str or None -- path to AVHRR GeoTIFF (default: server path)
    class_scheme : str -- "avhrr" or "skillmd"

    Returns
    -------
    dict with keys: C_array, LC_array, lats, lons, mask, stats
    """
    import xarray as xr

    try:
        import rasterio
    except ImportError:
        print("ERROR: rasterio required. Install with: pip install rasterio",
              file=sys.stderr)
        sys.exit(1)

    avhrr_path = avhrr_tif or AVHRR_TIF
    if not os.path.exists(avhrr_path):
        print(f"ERROR: AVHRR raster not found: {avhrr_path}", file=sys.stderr)
        sys.exit(1)

    c_lookup, class_names = get_c_lookup(class_scheme)

    ds = xr.open_dataset(staticmaps_path)

    # Get coordinates
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

    # Initialize arrays
    LC_array = np.full((ny, nx), 255, dtype=np.uint8)  # 255 = nodata
    C_array = np.full((ny, nx), np.nan, dtype=np.float32)

    # Open AVHRR raster and sample at each cell center
    n_active = int(mask.sum())
    n_done = 0
    n_nodata = 0
    class_counts = {}

    with rasterio.open(avhrr_path) as src:
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
                    val = 255

                if val == 255:
                    n_nodata += 1
                    # Use moderate default (grassland)
                    LC_array[i, j] = 10
                    C_array[i, j] = c_lookup.get(10, 0.03)
                else:
                    LC_array[i, j] = val
                    C_array[i, j] = c_lookup.get(val, 0.15)
                    class_counts[val] = class_counts.get(val, 0) + 1

                n_done += 1
                if n_done % 50 == 0:
                    print(f"  AVHRR sampling: {n_done}/{n_active} cells done",
                          file=sys.stderr)

    if n_nodata > 0:
        print(f"  WARNING: {n_nodata} cells had AVHRR nodata (255), "
              f"using grassland default (C=0.03)", file=sys.stderr)

    # Statistics
    valid_C = C_array[mask]

    # Dominant class
    if class_counts:
        dominant_code = max(class_counts, key=class_counts.get)
        dominant_name = class_names.get(dominant_code, f"Unknown ({dominant_code})")
        dominant_frac = class_counts[dominant_code] / n_active
    else:
        dominant_code, dominant_name, dominant_frac = -1, "N/A", 0.0

    # Class distribution
    class_distribution = {}
    for code, count in sorted(class_counts.items()):
        name = class_names.get(code, f"Unknown ({code})")
        c_val = c_lookup.get(code, 0.15)
        class_distribution[name] = {
            "code": code,
            "count": count,
            "fraction": round(count / n_active, 4),
            "C_factor": c_val,
        }

    stats = {
        "mean_C": round(float(np.nanmean(valid_C)), 5),
        "min_C": round(float(np.nanmin(valid_C)), 5),
        "max_C": round(float(np.nanmax(valid_C)), 5),
        "std_C": round(float(np.nanstd(valid_C)), 5),
        "n_cells": n_active,
        "n_nodata_cells": n_nodata,
        "dominant_class": f"{dominant_code} ({dominant_name})",
        "dominant_fraction": round(dominant_frac, 4),
        "class_scheme": class_scheme,
        "class_distribution": class_distribution,
    }

    ds.close()

    return {
        "C_array": C_array,
        "LC_array": LC_array,
        "lats": lats,
        "lons": lons,
        "mask": mask,
        "stats": stats,
    }


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def write_output(result, output_path, staticmaps_path):
    """Write USLE_C as a standalone NetCDF file."""
    import xarray as xr

    ds_ref = xr.open_dataset(staticmaps_path)

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
            "USLE_C": ([y_name, x_name], result["C_array"],
                       {"long_name": "USLE C factor (cover management)",
                        "units": "-",
                        "source": "AVHRR 1km UMD land cover -> USLE C lookup",
                        "valid_range": [0.0, 1.0]}),
            "landcover": ([y_name, x_name], result["LC_array"].astype(np.int16),
                          {"long_name": "UMD land cover class",
                           "units": "-",
                           "source": "AVHRR 1km UMD Global Land Cover"}),
        },
        coords=coords,
    )

    ds_out.attrs["title"] = "USLE C-factor derived from AVHRR land cover"
    ds_out.attrs["method"] = "UMD land cover class -> C-factor lookup table"
    ds_out.attrs["tool"] = "derive_usle_c.py (wflow KI)"

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    ds_out.to_netcdf(output_path)
    ds_ref.close()

    print(f"  Written USLE_C to {output_path}", file=sys.stderr)


def patch_netcdf(result, patch_nc_path):
    """Write USLE_C into an existing staticmaps_sediment.nc."""
    import xarray as xr

    ds = xr.open_dataset(patch_nc_path)

    if "lat" in ds.coords:
        y_name, x_name = "lat", "lon"
    else:
        y_name, x_name = "y", "x"

    ds["USLE_C"] = xr.DataArray(
        result["C_array"],
        dims=[y_name, x_name],
        attrs={
            "long_name": "USLE C factor (cover management)",
            "units": "-",
            "source": "AVHRR 1km UMD land cover -> USLE C lookup",
        },
    )

    ds.to_netcdf(patch_nc_path + ".tmp")
    ds.close()

    os.replace(patch_nc_path + ".tmp", patch_nc_path)
    print(f"  Patched USLE_C into {patch_nc_path}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Point mode
# ---------------------------------------------------------------------------

def point_mode(lat, lon, avhrr_tif=None, class_scheme="avhrr"):
    """Get USLE C-factor for a single point."""
    try:
        import rasterio
    except ImportError:
        print("ERROR: rasterio required. Install with: pip install rasterio",
              file=sys.stderr)
        sys.exit(1)

    avhrr_path = avhrr_tif or AVHRR_TIF
    c_lookup, class_names = get_c_lookup(class_scheme)

    with rasterio.open(avhrr_path) as src:
        try:
            row, col = src.index(lon, lat)
            lc_code = int(src.read(1, window=rasterio.windows.Window(
                col, row, 1, 1))[0, 0])
        except Exception as e:
            print(f"ERROR: Failed to sample AVHRR at ({lat}, {lon}): {e}",
                  file=sys.stderr)
            sys.exit(1)

    # If pixel is Water (0) or NoData (255), search 8 neighbors at ~1km offsets
    if lc_code in (0, 255):
        original_code = lc_code
        offset_deg = 0.01  # ~1km
        neighbor_codes = []
        for dlat in [-offset_deg, 0, offset_deg]:
            for dlon in [-offset_deg, 0, offset_deg]:
                if dlat == 0 and dlon == 0:
                    continue
                try:
                    with rasterio.open(avhrr_path) as src2:
                        r2, c2 = src2.index(lon + dlon, lat + dlat)
                        nc = int(src2.read(1, window=rasterio.windows.Window(
                            c2, r2, 1, 1))[0, 0])
                        if nc not in (0, 255):
                            neighbor_codes.append(nc)
                except Exception:
                    continue
        if neighbor_codes:
            # Use most common non-water neighbor
            from collections import Counter
            lc_code = Counter(neighbor_codes).most_common(1)[0][0]
            print(f"NOTE: Exact coordinate hit {'Water' if original_code == 0 else 'NoData'} pixel. "
                  f"Using dominant neighbor landcover (code={lc_code}).", file=sys.stderr)

    if lc_code == 255:
        lc_code = -1
        lc_name = "NoData"
        c_factor = None
    elif lc_code == 0:
        lc_name = "Water"
        c_factor = 0.0
    else:
        lc_name = class_names.get(lc_code, f"Unknown ({lc_code})")
        c_factor = c_lookup.get(lc_code, 0.15)

    result = {
        "lat": lat,
        "lon": lon,
        "class_scheme": class_scheme,
        "landcover_code": lc_code,
        "landcover_name": lc_name,
        "USLE_C": c_factor,
        "C_interpretation": _interpret_c(c_factor) if c_factor is not None else "no data",
    }
    return result


def _interpret_c(C):
    """Interpret C-factor value."""
    if C == 0.0:
        return "no erosion (water/ice/wetland/urban)"
    elif C <= 0.01:
        return "very low erosion potential (dense forest)"
    elif C <= 0.05:
        return "low erosion potential (shrubland/grassland)"
    elif C <= 0.15:
        return "moderate erosion potential (mixed vegetation)"
    elif C <= 0.35:
        return "high erosion potential (cropland)"
    elif C <= 0.60:
        return "very high erosion potential (sparse vegetation)"
    else:
        return "extreme erosion potential (bare soil)"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Derive USLE C-factor from AVHRR land cover for wflow_sediment.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Grid mode: derive C for all cells
    python derive_usle_c.py --staticmaps staticmaps.nc --output usle_c.nc

    # Grid mode: patch into existing sediment staticmaps
    python derive_usle_c.py --staticmaps staticmaps.nc \\
        --patch_nc staticmaps_sediment.nc

    # Point mode: check single location
    python derive_usle_c.py --lat 32.93 --lon 117.36

C-factor lookup (AVHRR UMD classes):
    0  Water                    -> C = 0.000
    1  Evergreen Needleleaf     -> C = 0.003
    2  Evergreen Broadleaf      -> C = 0.003
    3  Deciduous Needleleaf     -> C = 0.005
    4  Deciduous Broadleaf      -> C = 0.005
    5  Mixed Forest             -> C = 0.004
    6  Woodland                 -> C = 0.008
    7  Wooded Grassland         -> C = 0.030
    8  Closed Shrubland         -> C = 0.015
    9  Open Shrubland           -> C = 0.050
    10 Grassland                -> C = 0.030
    11 Cropland                 -> C = 0.300
    12 Bare Ground              -> C = 0.900
    13 Urban                    -> C = 0.010
    14 Permanent Wetlands       -> C = 0.000
    15 Snow and Ice             -> C = 0.000
    16 Barren                   -> C = 0.450

Reference:
    Morgan, R.P.C. (2005). Soil Erosion and Conservation. Blackwell.
    Panagos, P. et al. (2015). Estimating the soil erosion cover-management
    factor at the European scale. Land Use Policy 48, 38-50.
        """,
    )
    parser.add_argument("--staticmaps", type=str,
                        help="Path to wflow staticmaps.nc (grid mode)")
    parser.add_argument("--output", type=str,
                        help="Output NetCDF file for USLE_C (grid mode)")
    parser.add_argument("--patch_nc", type=str,
                        help="Existing staticmaps_sediment.nc to patch with USLE_C")
    parser.add_argument("--lat", type=float,
                        help="Latitude for point mode")
    parser.add_argument("--lon", type=float,
                        help="Longitude for point mode")
    parser.add_argument("--avhrr_tif", type=str, default=None,
                        help=f"Path to AVHRR GeoTIFF (default: {AVHRR_TIF})")
    parser.add_argument("--class_scheme", type=str, default="avhrr",
                        choices=["avhrr", "skillmd"],
                        help="UMD class numbering scheme (default: avhrr)")

    args = parser.parse_args()

    # --- Point mode ---
    if args.lat is not None and args.lon is not None:
        result = point_mode(args.lat, args.lon, args.avhrr_tif, args.class_scheme)
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

    print(f"Deriving USLE C-factor from AVHRR land cover...", file=sys.stderr)

    result = derive_c_grid(args.staticmaps, args.avhrr_tif, args.class_scheme)
    stats = result["stats"]

    if args.output:
        write_output(result, args.output, args.staticmaps)

    if args.patch_nc:
        if not os.path.exists(args.patch_nc):
            print(f"ERROR: patch target not found: {args.patch_nc}", file=sys.stderr)
            sys.exit(1)
        patch_netcdf(result, args.patch_nc)

    # Print summary (strip class_distribution for cleaner output)
    output_stats = {k: v for k, v in stats.items() if k != "class_distribution"}
    output = {
        "status": "success",
        "stats": output_stats,
        "class_distribution": stats.get("class_distribution", {}),
    }
    if args.output:
        output["output_file"] = args.output
    if args.patch_nc:
        output["patched_file"] = args.patch_nc

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
