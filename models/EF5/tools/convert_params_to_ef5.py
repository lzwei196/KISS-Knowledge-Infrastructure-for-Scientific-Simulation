#!/usr/bin/env python3
"""
convert_params_to_ef5.py — Convert soil/land parameters to EF5 parameter grids.

Converts HWSD (Harmonized World Soil Database), STATSGO, or SoilGrids data
into CREST or SAC-SMA parameter grids for EF5.

CREST parameters from soil:
  - WM: max soil water capacity (mm) — from porosity * depth
  - FC/Ksat: saturated hydraulic conductivity (mm/hr)
  - B: variable infiltration curve exponent — from soil texture
  - IM: impervious area ratio (0-100%) — from urban land cover

SAC-SMA parameters from soil:
  - UZTWM, UZFWM: upper zone tensions/free water max (mm)
  - LZTWM, LZFSM, LZFPM: lower zone capacities (mm)
  - UZK, LZSK, LZPK: withdrawal rates (fractional/day)

Pipeline: validate inputs → read soil data → compute parameters → write grids → validate outputs
"""

import argparse
import os
import sys
import struct
import numpy as np
from pathlib import Path

# ---------------------------------------------------------------------------
# CREST parameter derivation from soil properties
# ---------------------------------------------------------------------------

# Soil texture class -> B exponent (variable infiltration curve)
# Based on Cosby et al. (1984) and CREST literature
TEXTURE_TO_B = {
    "sand": 0.30,
    "loamy_sand": 0.35,
    "sandy_loam": 0.45,
    "silt_loam": 0.55,
    "silt": 0.50,
    "loam": 0.50,
    "sandy_clay_loam": 0.60,
    "silty_clay_loam": 0.65,
    "clay_loam": 0.60,
    "sandy_clay": 0.70,
    "silty_clay": 0.75,
    "clay": 0.80,
}

# Soil texture class -> Ksat (mm/hr), from Rawls et al. (1982)
TEXTURE_TO_KSAT = {
    "sand": 120.0,
    "loamy_sand": 60.0,
    "sandy_loam": 26.0,
    "silt_loam": 6.8,
    "silt": 3.4,
    "loam": 13.0,
    "sandy_clay_loam": 4.3,
    "silty_clay_loam": 1.5,
    "clay_loam": 2.3,
    "sandy_clay": 1.2,
    "silty_clay": 0.9,
    "clay": 0.6,
}

# Soil texture class -> porosity (fraction), from Rawls et al. (1982)
TEXTURE_TO_POROSITY = {
    "sand": 0.437,
    "loamy_sand": 0.437,
    "sandy_loam": 0.453,
    "silt_loam": 0.501,
    "silt": 0.480,
    "loam": 0.463,
    "sandy_clay_loam": 0.398,
    "silty_clay_loam": 0.471,
    "clay_loam": 0.464,
    "sandy_clay": 0.430,
    "silty_clay": 0.479,
    "clay": 0.475,
}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def validate_inputs(soil_dir, dem_path, output_dir):
    """Validate input files exist."""
    errors = []
    if soil_dir and not os.path.isdir(soil_dir):
        errors.append(f"Soil data directory not found: {soil_dir}")
    if dem_path and not os.path.isfile(dem_path):
        errors.append(f"DEM file not found: {dem_path}")
    if errors:
        for e in errors:
            print(f"[ERROR] {e}", file=sys.stderr)
        return False
    return True


def validate_param_grid(data, param_name, valid_range):
    """Validate parameter grid values are in expected range."""
    valid = data[~np.isnan(data)]
    if len(valid) == 0:
        print(f"[WARNING] {param_name}: all NaN values", file=sys.stderr)
        return False
    lo, hi = valid_range
    pct_out = np.sum((valid < lo) | (valid > hi)) / len(valid) * 100
    if pct_out > 5:
        print(f"[WARNING] {param_name}: {pct_out:.1f}% of values outside [{lo}, {hi}]", file=sys.stderr)
        print(f"  Range: [{valid.min():.3f}, {valid.max():.3f}], Mean: {valid.mean():.3f}", file=sys.stderr)
    else:
        print(f"[OK] {param_name}: range [{valid.min():.3f}, {valid.max():.3f}], mean={valid.mean():.3f}")
    return True


def validate_outputs(output_dir, model="crest"):
    """Validate all output parameter grids."""
    ranges = {
        "crest": {
            "wm": (10.0, 2000.0),
            "b": (0.01, 2.0),
            "im": (0.0, 100.0),
            "ksat": (0.01, 500.0),
        },
        "sac": {
            "uztwm": (1.0, 500.0),
            "uzfwm": (1.0, 200.0),
            "lztwm": (1.0, 1000.0),
            "lzfsm": (1.0, 500.0),
            "lzfpm": (1.0, 1000.0),
        },
    }
    model_ranges = ranges.get(model, ranges["crest"])
    for param, rng in model_ranges.items():
        fpath = os.path.join(output_dir, f"{param}.tif")
        if not os.path.exists(fpath):
            fpath = os.path.join(output_dir, f"{param}.asc")
        if os.path.exists(fpath):
            data = read_grid(fpath)
            if data is not None:
                validate_param_grid(data, param, rng)


# ---------------------------------------------------------------------------
# Grid I/O
# ---------------------------------------------------------------------------
def read_grid(filepath):
    """Read ASC or TIF grid."""
    if filepath.endswith(".asc"):
        return read_asc_grid(filepath)
    elif filepath.endswith(".tif") or filepath.endswith(".tiff"):
        return read_tif_grid(filepath)
    return None


def read_asc_grid(filepath):
    """Read ESRI ASCII grid."""
    with open(filepath, "r") as f:
        header = {}
        for _ in range(6):
            parts = f.readline().strip().split()
            if len(parts) >= 2:
                header[parts[0].lower()] = float(parts[1])
        ncols = int(header.get("ncols", 0))
        nrows = int(header.get("nrows", 0))
        nodata = header.get("nodata_value", -9999)
        data = np.loadtxt(f, dtype=np.float32).reshape(nrows, ncols)
        data[data == nodata] = np.nan
    return data


def read_tif_grid(filepath):
    """Read float32 GeoTIFF."""
    try:
        from osgeo import gdal
        ds = gdal.Open(filepath)
        if not ds:
            return None
        band = ds.GetRasterBand(1)
        data = band.ReadAsArray().astype(np.float32)
        nd = band.GetNoDataValue()
        if nd is not None:
            data[data == nd] = np.nan
        gt = ds.GetGeoTransform()
        ds = None
        return data
    except ImportError:
        try:
            import rasterio
            with rasterio.open(filepath) as src:
                data = src.read(1).astype(np.float32)
                if src.nodata is not None:
                    data[data == src.nodata] = np.nan
                return data
        except ImportError:
            print("[ERROR] GDAL or rasterio required", file=sys.stderr)
            return None


def write_tif_grid(filepath, data, geo_transform, nodata=-9999.0):
    """Write float32 GeoTIFF with given geotransform."""
    try:
        from osgeo import gdal, osr
        nrows, ncols = data.shape
        driver = gdal.GetDriverByName("GTiff")
        ds = driver.Create(filepath, ncols, nrows, 1, gdal.GDT_Float32)
        ds.SetGeoTransform(geo_transform)
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(4326)
        ds.SetProjection(srs.ExportToWkt())
        band = ds.GetRasterBand(1)
        band.SetNoDataValue(nodata)
        out = data.copy()
        out[np.isnan(out)] = nodata
        band.WriteArray(out)
        ds.FlushCache()
        ds = None
    except ImportError:
        write_asc_grid(filepath.replace(".tif", ".asc"), data, nodata=nodata)


def write_asc_grid(filepath, data, xll=0.0, yll=0.0, cellsize=0.1, nodata=-9999.0):
    """Write ESRI ASCII grid."""
    nrows, ncols = data.shape
    out = data.copy()
    out[np.isnan(out)] = nodata
    with open(filepath, "w") as f:
        f.write(f"ncols         {ncols}\n")
        f.write(f"nrows         {nrows}\n")
        f.write(f"xllcorner     {xll}\n")
        f.write(f"yllcorner     {yll}\n")
        f.write(f"cellsize      {cellsize}\n")
        f.write(f"NODATA_value  {nodata}\n")
        for row in range(nrows):
            f.write(" ".join(f"{v:.4f}" for v in out[row]) + "\n")


# ---------------------------------------------------------------------------
# Parameter derivation
# ---------------------------------------------------------------------------
def compute_crest_params(sand_pct, clay_pct, silt_pct, depth_cm, urban_pct=None):
    """
    Derive CREST parameter grids from soil texture percentages and depth.

    Parameters
    ----------
    sand_pct : ndarray — Sand percentage (0-100)
    clay_pct : ndarray — Clay percentage (0-100)
    silt_pct : ndarray — Silt percentage (0-100)
    depth_cm : ndarray or float — Soil depth in cm
    urban_pct : ndarray or None — Urban land cover percentage for IM

    Returns
    -------
    dict of parameter name -> ndarray
    """
    # Determine texture class per pixel (simplified)
    # Using Rawls pedotransfer functions
    total = sand_pct + clay_pct + silt_pct
    sand_frac = np.where(total > 0, sand_pct / total, 0.33)
    clay_frac = np.where(total > 0, clay_pct / total, 0.33)

    # Porosity from Rawls: theta_s = 0.332 - 7.251e-4*sand + 0.1276*log10(clay)
    porosity = 0.332 - 7.251e-4 * sand_pct + 0.1276 * np.log10(np.clip(clay_pct, 1, 100))
    porosity = np.clip(porosity, 0.2, 0.6)

    # WM = porosity * depth (converted to mm)
    depth_mm = np.float32(depth_cm) * 10.0 if isinstance(depth_cm, (int, float)) else depth_cm * 10.0
    wm = porosity * depth_mm
    wm = np.clip(wm, 10.0, 2000.0)

    # B exponent: Cosby (1984): B = 3.10 + 15.7*clay_frac - 0.3*sand_frac
    b = 3.10 + 15.7 * clay_frac - 0.3 * sand_frac
    b = np.clip(b, 0.01, 2.0)
    # Normalize to typical CREST range (0.1-1.5)
    b = b / 10.0  # Scale down from Cosby raw

    # Ksat from Cosby: log10(Ksat) = -0.6 + 1.26*sand_frac - 0.64*clay_frac (cm/hr)
    log_ksat = -0.6 + 1.26 * (sand_pct / 100.0) - 0.64 * (clay_pct / 100.0)
    ksat = np.power(10.0, log_ksat) * 10.0  # cm/hr -> mm/hr
    ksat = np.clip(ksat, 0.01, 500.0)

    # IM: impervious area
    if urban_pct is not None:
        im = np.clip(urban_pct, 0, 100).astype(np.float32)
    else:
        im = np.zeros_like(wm)

    return {
        "wm": wm.astype(np.float32),
        "b": b.astype(np.float32),
        "im": im.astype(np.float32),
        "ksat": ksat.astype(np.float32),
    }


def compute_sac_params(sand_pct, clay_pct, silt_pct, depth_cm):
    """
    Derive SAC-SMA parameter grids from soil texture.

    Uses Anderson (2002) pedotransfer relationships for SAC-SMA.
    """
    total = sand_pct + clay_pct + silt_pct
    sand_frac = np.where(total > 0, sand_pct / total, 0.33)
    clay_frac = np.where(total > 0, clay_pct / total, 0.33)

    porosity = 0.332 - 7.251e-4 * sand_pct + 0.1276 * np.log10(np.clip(clay_pct, 1, 100))
    porosity = np.clip(porosity, 0.2, 0.6)

    depth_mm = np.float32(depth_cm) * 10.0 if isinstance(depth_cm, (int, float)) else depth_cm * 10.0

    # Upper zone: ~top 20% of soil
    uz_depth = depth_mm * 0.2
    uztwm = porosity * uz_depth * 0.6  # tension water
    uzfwm = porosity * uz_depth * 0.3  # free water

    # Lower zone: ~bottom 80% of soil
    lz_depth = depth_mm * 0.8
    lztwm = porosity * lz_depth * 0.5
    lzfsm = porosity * lz_depth * 0.15
    lzfpm = porosity * lz_depth * 0.20

    # Withdrawal rates from texture
    uzk = np.clip(0.2 + 0.3 * sand_frac, 0.1, 0.7)
    lzsk = np.clip(0.02 + 0.1 * sand_frac, 0.01, 0.3)
    lzpk = np.clip(0.005 + 0.02 * sand_frac, 0.001, 0.05)

    return {
        "uztwm": np.clip(uztwm, 1, 500).astype(np.float32),
        "uzfwm": np.clip(uzfwm, 1, 200).astype(np.float32),
        "uzk": uzk.astype(np.float32),
        "lztwm": np.clip(lztwm, 1, 1000).astype(np.float32),
        "lzfsm": np.clip(lzfsm, 1, 500).astype(np.float32),
        "lzfpm": np.clip(lzfpm, 1, 1000).astype(np.float32),
        "lzsk": lzsk.astype(np.float32),
        "lzpk": lzpk.astype(np.float32),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def convert_params(soil_dir, output_dir, model="crest", dem_path=None, depth_cm=100):
    """
    Convert soil property grids to EF5 parameter grids.

    Parameters
    ----------
    soil_dir : str — Directory with sand.tif, clay.tif, silt.tif
    output_dir : str — Output directory for parameter grids
    model : str — "crest" or "sac"
    dem_path : str — DEM file for geo-reference
    depth_cm : float — Soil depth in cm (default 100)
    """
    if not validate_inputs(soil_dir, dem_path, output_dir):
        return False

    os.makedirs(output_dir, exist_ok=True)

    # Read soil texture grids
    sand = read_grid(os.path.join(soil_dir, "sand.tif"))
    clay = read_grid(os.path.join(soil_dir, "clay.tif"))
    silt = read_grid(os.path.join(soil_dir, "silt.tif"))

    if sand is None or clay is None:
        # Try alternative names
        for suffix in [".asc", ".tiff"]:
            sand = read_grid(os.path.join(soil_dir, f"sand{suffix}"))
            clay = read_grid(os.path.join(soil_dir, f"clay{suffix}"))
            silt = read_grid(os.path.join(soil_dir, f"silt{suffix}"))
            if sand is not None:
                break

    if sand is None or clay is None:
        print("[ERROR] Could not find sand/clay/silt grids in soil directory", file=sys.stderr)
        return False

    if silt is None:
        silt = 100.0 - sand - clay

    # Read urban cover if available
    urban = None
    for name in ["urban.tif", "urban.asc", "impervious.tif"]:
        p = os.path.join(soil_dir, name)
        if os.path.exists(p):
            urban = read_grid(p)
            break

    # Compute parameters
    if model.lower() == "crest":
        params = compute_crest_params(sand, clay, silt, depth_cm, urban)
    elif model.lower() == "sac":
        params = compute_sac_params(sand, clay, silt, depth_cm)
    else:
        print(f"[ERROR] Unknown model: {model}", file=sys.stderr)
        return False

    # Get geo-reference from DEM or sand grid
    geo_transform = [0.0, 0.1, 0, 0.0, 0, -0.1]  # default
    if dem_path:
        try:
            from osgeo import gdal
            ds = gdal.Open(dem_path)
            if ds:
                geo_transform = list(ds.GetGeoTransform())
                ds = None
        except ImportError:
            pass

    # Write parameter grids
    for pname, pdata in params.items():
        out_path = os.path.join(output_dir, f"{pname}.tif")
        write_tif_grid(out_path, pdata, geo_transform)
        print(f"[OK] Wrote {out_path}")

    # Validate
    validate_outputs(output_dir, model)
    return True


def main():
    parser = argparse.ArgumentParser(description="Convert soil data to EF5 parameter grids")
    parser.add_argument("--soil-dir", required=True, help="Directory with soil texture grids")
    parser.add_argument("--output-dir", required=True, help="Output directory")
    parser.add_argument("--model", default="crest", choices=["crest", "sac"])
    parser.add_argument("--dem", help="DEM file for geo-reference")
    parser.add_argument("--depth", type=float, default=100, help="Soil depth in cm")
    args = parser.parse_args()

    success = convert_params(args.soil_dir, args.output_dir, args.model, args.dem, args.depth)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
