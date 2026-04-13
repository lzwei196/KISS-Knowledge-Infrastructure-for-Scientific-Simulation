#!/usr/bin/env python3
"""
convert_soil_to_classic.py — Build CLASSIC initialization netCDF from soil/veg data.

Creates a single-point initialization file for CLASSIC with:
  - Soil texture (SAND, CLAY, ORGM as percentages)
  - Soil depth and layer configuration
  - Vegetation parameters (PFT fractions, LAI, albedo, etc.)
  - Prognostic variable initialization (temperature, moisture, carbon pools)

CRITICAL UNIT CONVERSIONS:
  - Soil texture: HWSD gives 0-1 fraction, CLASSIC expects 0-100 percent
  - Soil depth (SDEP): Often in cm, CLASSIC expects meters
  - Layer thickness (DELZ): Often in cm, CLASSIC expects meters
  - Rooting depth (ROOT): Often in cm, CLASSIC expects meters
  - Carbon pools: Often in gC/m2, CLASSIC expects kgC/m2
  - Temperature (TBAR): CLASSIC expects Kelvin in init file

Usage:
    python convert_soil_to_classic.py \\
        --lat 40.48 --lon 116.97 \\
        --sand "80,75,70,65,60,60,55,55,50,50,50,50,50,50,50,50,50,50,50,50" \\
        --clay "5,8,10,12,15,15,18,18,20,20,20,20,20,20,20,20,20,20,20,20" \\
        --orgm "5,3,2,1,1,0.5,0.5,0.5,0,0,0,0,0,0,0,0,0,0,0,0" \\
        --sdep 4.1 \\
        --pft_fracs "0.3,0.2,0.0,0.0,0.1,0.0,0.1,0.1,0.2" \\
        --output init_file.nc
"""

import argparse
import json
import os
import sys

import numpy as np

try:
    import netCDF4 as nc
except ImportError:
    print(json.dumps({"status": "error", "errors": ["netCDF4 not installed"]}))
    sys.exit(1)


# Default 20-layer configuration (standard CLASSIC)
DEFAULT_DELZ = [0.10, 0.10, 0.10, 0.10, 0.10,
                0.20, 0.20, 0.20, 0.20, 0.20,
                0.30, 0.50, 0.50, 0.50, 0.50,
                0.50, 0.50, 0.50, 0.50, 0.50]  # total = 6.1 m

# Default CLASS PFT parameters (4 CLASS PFTs + urban)
DEFAULT_CLASS_PARAMS = {
    # NdlTr, BdlTr, Crops, Grass, Urban
    "ALVC": [0.03, 0.06, 0.06, 0.06, 0.10],
    "ALIC": [0.19, 0.28, 0.34, 0.34, 0.30],
    "LNZ0": [1.83, 2.08, -0.29, -1.20, -0.59],
    "PAMX": [5.0, 6.0, 4.5, 3.5, 0.0],
    "PAMN": [3.0, 1.0, 0.0, 3.5, 0.0],
    "CMAS": [25.0, 25.0, 3.0, 2.5, 0.0],
    "ROOT": [1.0, 2.0, 0.8, 0.5, 0.0],
}

# CTEM PFT names (9 standard PFTs)
CTEM_PFT_NAMES = [
    "NdlEvgTr", "NdlDcdTr",  # Needleleaf: evergreen, deciduous
    "BdlEvgTr", "BdlDCoTr", "BdlDDrTr",  # Broadleaf: evergreen, cold-dec, drought-dec
    "CropC3", "CropC4",  # Crops: C3, C4
    "GrassC3", "GrassC4",  # Grass: C3, C4
]


def validate_inputs(args):
    """Validate input arguments."""
    errors = []

    if args.lat < -90 or args.lat > 90:
        errors.append(f"--lat must be between -90 and 90, got {args.lat}")
    if args.lon < -180 or args.lon > 360:
        errors.append(f"--lon must be between -180 and 360, got {args.lon}")

    sand_vals = [float(x) for x in args.sand.split(",")]
    clay_vals = [float(x) for x in args.clay.split(",")]
    orgm_vals = [float(x) for x in args.orgm.split(",")]

    n_layers = len(DEFAULT_DELZ)
    if len(sand_vals) != n_layers:
        errors.append(f"SAND needs {n_layers} values, got {len(sand_vals)}")
    if len(clay_vals) != n_layers:
        errors.append(f"CLAY needs {n_layers} values, got {len(clay_vals)}")
    if len(orgm_vals) != n_layers:
        errors.append(f"ORGM needs {n_layers} values, got {len(orgm_vals)}")

    # Check soil texture is in percentage (0-100), not fraction (0-1)
    for name, vals in [("SAND", sand_vals), ("CLAY", clay_vals)]:
        valid = [v for v in vals if v >= 0]  # skip flag values
        if valid and max(valid) <= 1.0:
            errors.append(
                f"CRITICAL: {name} values appear to be fractions (0-1). "
                f"CLASSIC expects percentages (0-100). Multiply by 100!"
            )

    pft_fracs = [float(x) for x in args.pft_fracs.split(",")]
    if len(pft_fracs) != 9:
        errors.append(f"--pft_fracs needs 9 CTEM PFT fractions, got {len(pft_fracs)}")
    if sum(pft_fracs) > 1.01:
        errors.append(f"Sum of PFT fractions ({sum(pft_fracs):.3f}) exceeds 1.0")

    if args.sdep <= 0:
        errors.append(f"--sdep must be > 0, got {args.sdep}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)


def create_init_file(lat, lon, sand, clay, orgm, sdep, pft_fracs,
                     output_path, init_temp_c=10.0, init_moisture=0.3):
    """
    Create a CLASSIC initialization netCDF file for a single point.

    Parameters
    ----------
    lat, lon : float
        Location coordinates
    sand, clay, orgm : list of float
        Soil texture percentages per layer
    sdep : float
        Soil permeable depth in meters
    pft_fracs : list of float
        CTEM PFT fractions (9 values)
    output_path : str
        Output file path
    init_temp_c : float
        Initial soil temperature in Celsius (stored as K in file but note
        the init file uses C for TBAR according to ncdump examples)
    init_moisture : float
        Initial volumetric liquid water content (m3/m3)
    """
    n_layers = len(DEFAULT_DELZ)
    n_ic = 4  # CLASS PFTs
    n_icc = 9  # CTEM PFTs
    n_icp1 = n_ic + 1  # CLASS PFTs + urban
    n_iccp1 = n_icc + 1  # CTEM PFTs + bareground
    n_iccp2 = n_icc + 2  # CTEM PFTs + bareground + LUC

    ds = nc.Dataset(output_path, "w", format="NETCDF4")

    # --- Dimensions ---
    ds.createDimension("tile", 1)
    ds.createDimension("lat", 1)
    ds.createDimension("lon", 1)
    ds.createDimension("layer", n_layers)
    ds.createDimension("ic", n_ic)
    ds.createDimension("icc", n_icc)
    ds.createDimension("icp1", n_icp1)
    ds.createDimension("iccp1", n_iccp1)
    ds.createDimension("iccp2", n_iccp2)
    ds.createDimension("months", 12)
    ds.createDimension("slope", 8)

    # --- Coordinate variables ---
    v = ds.createVariable("lat", "f8", ("lat",))
    v.units = "degrees_north"
    v.standard_name = "latitude"
    v[:] = [lat]

    v = ds.createVariable("lon", "f8", ("lon",))
    v.units = "degrees_east"
    v.standard_name = "longitude"
    v[:] = [lon]

    v = ds.createVariable("tile", "f8", ("tile",))
    v.long_name = "tiles"
    v[:] = [1.0]

    v = ds.createVariable("layer", "f8", ("layer",))
    v.long_name = "ground column layers"
    v[:] = np.arange(1, n_layers + 1, dtype=float)

    v = ds.createVariable("ic", "f8", ("ic",))
    v.long_name = "CLASS PFTs"
    v[:] = np.arange(1, n_ic + 1, dtype=float)

    v = ds.createVariable("icc", "f8", ("icc",))
    v.long_name = "CTEM PFTs"
    v[:] = np.arange(1, n_icc + 1, dtype=float)

    v = ds.createVariable("icp1", "f8", ("icp1",))
    v.long_name = "CLASS PFTs + bareground"
    v[:] = np.arange(1, n_icp1 + 1, dtype=float)

    v = ds.createVariable("iccp1", "f8", ("iccp1",))
    v.long_name = "CTEM PFTs + bareground"
    v[:] = np.arange(1, n_iccp1 + 1, dtype=float)

    v = ds.createVariable("iccp2", "f8", ("iccp2",))
    v.long_name = "CTEM PFTs + bareground + LUC"
    v[:] = np.arange(1, n_iccp2 + 1, dtype=float)

    v = ds.createVariable("months", "f8", ("months",))
    v.long_name = "Months"
    v[:] = np.arange(1, 13, dtype=float)

    v = ds.createVariable("slope", "f8", ("slope",))
    v.long_name = "slope fractions"
    v[:] = np.arange(1, 9, dtype=float)

    # --- Helper to create fill-value variables ---
    def make_var(name, dims, units, long_name, data, dtype="f4", fill=-999.0):
        var = ds.createVariable(name, dtype, dims, fill_value=fill)
        var.units = units
        var.long_name = long_name
        var[:] = data
        return var

    # --- Soil texture ---
    make_var("SAND", ("tile", "layer", "lat", "lon"), "%",
             "Percentage sand content",
             np.array(sand).reshape(1, n_layers, 1, 1))
    make_var("CLAY", ("tile", "layer", "lat", "lon"), "%",
             "Percentage clay content",
             np.array(clay).reshape(1, n_layers, 1, 1))
    make_var("ORGM", ("tile", "layer", "lat", "lon"), "%",
             "Percentage organic matter content",
             np.array(orgm).reshape(1, n_layers, 1, 1))

    # --- Layer thickness ---
    make_var("DELZ", ("layer",), "m", "Ground layer thickness",
             np.array(DEFAULT_DELZ))

    # --- Soil surface parameters ---
    make_var("SDEP", ("tile", "lat", "lon"), "m",
             "Soil permeable depth", np.array([[[sdep]]]))
    make_var("DRN", ("tile", "lat", "lon"), "-",
             "Soil drainage index", np.array([[[0.005]]]))
    make_var("SOCI", ("tile", "lat", "lon"), "index",
             "Soil colour index", np.array([[[10]]]), dtype="i4", fill=-999)
    make_var("FARE", ("tile", "lat", "lon"), "fraction",
             "Tile fractional area", np.array([[[1.0]]]))
    make_var("MID", ("tile", "lat", "lon"), "-",
             "Mosaic tile type (1=land, 0=lake)",
             np.array([[[1]]]), dtype="i4", fill=-999)
    make_var("GC", ("lat", "lon"), "-",
             "GCM surface descriptor", np.array([[-1]]), dtype="i4", fill=-999)
    make_var("grclarea", ("lat", "lon"), "km2",
             "Area of grid cell", np.array([[100.0]]))

    # --- Vegetation parameters (CLASS PFTs + urban) ---
    # Map CTEM fracs to CLASS PFTs
    # NdlTr = NdlEvg + NdlDcd, BdlTr = BdlEvg + BdlDCo + BdlDDr
    # Crops = CropC3 + CropC4, Grass = GrassC3 + GrassC4
    class_fracs = [
        pft_fracs[0] + pft_fracs[1],       # NdlTr
        pft_fracs[2] + pft_fracs[3] + pft_fracs[4],  # BdlTr
        pft_fracs[5] + pft_fracs[6],       # Crops
        pft_fracs[7] + pft_fracs[8],       # Grass
        0.0,  # Urban
    ]

    fcan = np.array(class_fracs).reshape(1, n_icp1, 1, 1)
    make_var("FCAN", ("tile", "icp1", "lat", "lon"), "-",
             "Annual maximum fractional coverage", fcan)

    for param_name, vals in DEFAULT_CLASS_PARAMS.items():
        data = np.array(vals).reshape(1, n_icp1, 1, 1)
        if param_name in ["PAMX", "PAMN", "CMAS", "ROOT"]:
            make_var(param_name, ("tile", "ic", "lat", "lon"),
                     "-" if param_name in ["PAMX", "PAMN"] else "m",
                     param_name,
                     np.array(vals[:n_ic]).reshape(1, n_ic, 1, 1))
        else:
            make_var(param_name, ("tile", "icp1", "lat", "lon"), "-",
                     param_name, data)

    # --- CTEM vegetation ---
    make_var("fcancmx", ("tile", "icc", "lat", "lon"), "-",
             "PFT fractional coverage",
             np.array(pft_fracs).reshape(1, n_icc, 1, 1))

    # --- Prognostic: soil temperature and moisture ---
    tbar = np.full((1, n_layers, 1, 1), init_temp_c, dtype=np.float32)
    make_var("TBAR", ("tile", "layer", "lat", "lon"), "C",
             "Temperature of soil layers", tbar)

    thlq = np.full((1, n_layers, 1, 1), init_moisture, dtype=np.float32)
    make_var("THLQ", ("tile", "layer", "lat", "lon"), "m3/m3",
             "Volumetric liquid water content", thlq)

    thic = np.zeros((1, n_layers, 1, 1), dtype=np.float32)
    make_var("THIC", ("tile", "layer", "lat", "lon"), "m3/m3",
             "Volumetric frozen water content", thic)

    # --- Prognostic: snow (initialize to zero = snow-free) ---
    for var_name, long_name, units in [
        ("SNO", "Mass of snow pack", "kg/m2"),
        ("TSNO", "Snowpack temperature", "C"),
        ("ALBS", "Snow albedo", "-"),
        ("RHOS", "Density of snow", "kg/m3"),
    ]:
        make_var(var_name, ("tile", "lat", "lon"), units, long_name,
                 np.zeros((1, 1, 1), dtype=np.float32))

    # --- Prognostic: canopy ---
    make_var("TCAN", ("tile", "lat", "lon"), "C",
             "Vegetation canopy temperature",
             np.array([[[init_temp_c]]]))
    make_var("RCAN", ("tile", "lat", "lon"), "kg/m2",
             "Intercepted liquid water on canopy",
             np.zeros((1, 1, 1), dtype=np.float32))
    make_var("SCAN", ("tile", "lat", "lon"), "kg/m2",
             "Intercepted frozen water on canopy",
             np.zeros((1, 1, 1), dtype=np.float32))
    make_var("GRO", ("tile", "lat", "lon"), "-",
             "Vegetation growth index",
             np.array([[[1.0]]]))

    # --- Prognostic: ponded water ---
    make_var("TPND", ("tile", "lat", "lon"), "C",
             "Temperature of ponded water",
             np.zeros((1, 1, 1), dtype=np.float32))
    make_var("ZPND", ("tile", "lat", "lon"), "m",
             "Depth of ponded water",
             np.zeros((1, 1, 1), dtype=np.float32))

    # --- CTEM prognostic: carbon pools (initialize to small values) ---
    make_var("gleafmas", ("tile", "icc", "lat", "lon"), "kgC/m2",
             "Green leaf mass",
             np.where(np.array(pft_fracs) > 0, 0.1, 0.0).reshape(1, n_icc, 1, 1))
    make_var("bleafmas", ("tile", "icc", "lat", "lon"), "kgC/m2",
             "Brown leaf mass",
             np.zeros((1, n_icc, 1, 1), dtype=np.float32))
    make_var("stemmass", ("tile", "icc", "lat", "lon"), "kgC/m2",
             "Stem mass",
             np.where(np.array(pft_fracs[:5]) > 0, 1.0, 0.0).tolist()
             + [0.0, 0.0, 0.0, 0.0])  # trees only
    ds.variables["stemmass"][:] = np.array(
        [max(pft_fracs[i], 0) * (5.0 if i < 5 else 0.0) for i in range(n_icc)]
    ).reshape(1, n_icc, 1, 1)

    make_var("rootmass", ("tile", "icc", "lat", "lon"), "kgC/m2",
             "Root mass",
             np.where(np.array(pft_fracs) > 0, 0.5, 0.0).reshape(1, n_icc, 1, 1))

    # Litter and soil C: iccp2 = icc+2 (includes bareground + LUC pool)
    make_var("litrmass", ("tile", "iccp2", "lat", "lon"), "kgC/m2",
             "Litter mass",
             np.full((1, n_iccp2, 1, 1), 0.1, dtype=np.float64), dtype="f8")
    make_var("soilcmas", ("tile", "iccp2", "lat", "lon"), "kgC/m2",
             "Soil C mass",
             np.full((1, n_iccp2, 1, 1), 1.0, dtype=np.float64), dtype="f8")

    # Phenology
    make_var("lfstatus", ("tile", "icc", "lat", "lon"), "-",
             "Leaf phenological status",
             np.where(np.array(pft_fracs) > 0, 2.0, 4.0).reshape(1, n_icc, 1, 1))
    make_var("pandays", ("tile", "icc", "lat", "lon"), "-",
             "Days with positive net photosynthesis",
             np.where(np.array(pft_fracs) > 0, 7.0, 0.0).reshape(1, n_icc, 1, 1))

    # Peatland (off)
    make_var("ipeatland", ("tile", "lat", "lon"), "-",
             "Peatland flag", np.zeros((1, 1, 1), dtype=np.float32))

    # Number of tiles
    make_var("nmtest", ("lat", "lon"), "-",
             "Number of tiles per grid cell",
             np.array([[1]]), dtype="i4", fill=-999)

    # Slope fractions (for dynamic wetlands)
    make_var("slopefrac", ("tile", "slope", "lat", "lon"), "-",
             "Slope-based fraction for dynamic wetlands",
             np.zeros((1, 8, 1, 1), dtype=np.float32))

    # Competition variables
    for var_name in ["anndefct", "annsrpls", "annpcp"]:
        make_var(var_name, ("lat", "lon"), "mm", var_name,
                 np.zeros((1, 1), dtype=np.float32))
    make_var("aridity", ("lat", "lon"), "-", "Aridity index",
             np.array([[1.0]]))
    for var_name in ["defctmon", "srplsmon"]:
        make_var(var_name, ("lat", "lon"), "months", var_name,
                 np.zeros((1, 1), dtype=np.float32))
    make_var("dry_season_length", ("lat", "lon"), "months",
             "Dry season length", np.zeros((1, 1), dtype=np.float32))
    make_var("gdd5", ("lat", "lon"), "days",
             "Growing degree days above 5C", np.zeros((1, 1), dtype=np.float32))
    make_var("tcoldm", ("lat", "lon"), "C",
             "Temperature of coldest month", np.array([[-10.0]]))
    make_var("twarmm", ("lat", "lon"), "C",
             "Temperature of warmest month", np.array([[25.0]]))

    # Growth efficiency
    make_var("grwtheff", ("tile", "icc", "lat", "lon"), "(kgC/m2)/(m2/m2)",
             "Growth efficiency",
             np.zeros((1, n_icc, 1, 1), dtype=np.float64), dtype="f8")

    # Moss/peatland (zero)
    for var_name, units in [("Cmossmas", "kgC/m2"), ("litrmsmoss", "kgC/m2"),
                            ("dmoss", "m")]:
        make_var(var_name, ("tile", "lat", "lon"), units, var_name,
                 np.zeros((1, 1, 1), dtype=np.float32))

    make_var("maxAnnualActLyr", ("tile", "lat", "lon"), "m",
             "Max annual active layer thickness",
             np.array([[[2.0]]]), dtype="f8")

    ds.close()

    # Validate output
    result = {"status": "success", "file": output_path, "warnings": []}
    print(json.dumps(result, indent=2))
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Build CLASSIC initialization netCDF from soil/veg data"
    )
    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--lon", type=float, required=True)
    parser.add_argument("--sand", required=True,
                        help="Comma-separated sand %% per layer (20 values)")
    parser.add_argument("--clay", required=True,
                        help="Comma-separated clay %% per layer (20 values)")
    parser.add_argument("--orgm", required=True,
                        help="Comma-separated organic matter %% per layer (20 values)")
    parser.add_argument("--sdep", type=float, required=True,
                        help="Soil permeable depth in meters")
    parser.add_argument("--pft_fracs", required=True,
                        help="Comma-separated CTEM PFT fractions (9 values)")
    parser.add_argument("--output", required=True,
                        help="Output initialization netCDF path")
    parser.add_argument("--init_temp", type=float, default=10.0,
                        help="Initial soil temperature (deg C)")
    parser.add_argument("--init_moisture", type=float, default=0.3,
                        help="Initial soil moisture (m3/m3)")

    args = parser.parse_args()
    validate_inputs(args)

    sand = [float(x) for x in args.sand.split(",")]
    clay = [float(x) for x in args.clay.split(",")]
    orgm = [float(x) for x in args.orgm.split(",")]
    pft_fracs = [float(x) for x in args.pft_fracs.split(",")]

    create_init_file(args.lat, args.lon, sand, clay, orgm, args.sdep,
                     pft_fracs, args.output, args.init_temp, args.init_moisture)


if __name__ == "__main__":
    main()
