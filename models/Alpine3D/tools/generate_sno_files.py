#!/usr/bin/env python3
"""
generate_sno_files.py — Generate initial snow/soil profiles (.sno) for Alpine3D.

Reads a DEM (ARC ASCII grid) and generates one .sno file per grid cell. Each file
contains the initial soil stratigraphy and (optionally) snow layers for the simulation
start date.

CRITICAL UNITS:
  - Layer thickness (Layer_Thick): meters
  - Temperature (T): Kelvin
  - Vol_Frac_I/W/V/S: volumetric fractions (sum must = 1.0)
  - Rho_S (soil density): kg/m³ (NOT g/cm³, multiply by 1000 if needed)
  - Conduc_S (soil conductivity): W/(m·K)
  - HeatCapac_S (soil heat capacity): J/(kg·K)
  - rg (grain radius): mm (NOT µm, divide by 1000 if needed)
  - rb (bond radius): mm
  - dd (dendricity): 0–1
  - sp (sphericity): 0–1

Usage:
    python generate_sno_files.py \\
        --dem ./input/surface-grids/dem.asc \\
        --output ./input/snowfiles/ \\
        --date 2014-10-01T00:00 \\
        --n-soil-layers 3 \\
        --soil-type mineral

    python generate_sno_files.py \\
        --dem ./input/surface-grids/dem.asc \\
        --output ./input/snowfiles/ \\
        --date 2014-10-01T00:00 \\
        --n-soil-layers 5 \\
        --soil-density 1800 --soil-conductivity 1.5 --soil-heat-capacity 900 \\
        --soil-water-fraction 0.20
"""

import argparse
import json
import os
import sys
from datetime import datetime


# Predefined soil types with typical properties
SOIL_TYPES = {
    "mineral": {
        "density": 1800.0,        # kg/m³
        "conductivity": 1.5,      # W/(m·K)
        "heat_capacity": 900.0,   # J/(kg·K)
        "water_fraction": 0.20,   # volumetric
        "soil_fraction": 0.50,    # volumetric
    },
    "organic": {
        "density": 1200.0,
        "conductivity": 0.5,
        "heat_capacity": 1400.0,
        "water_fraction": 0.35,
        "soil_fraction": 0.30,
    },
    "sandy": {
        "density": 1600.0,
        "conductivity": 1.8,
        "heat_capacity": 800.0,
        "water_fraction": 0.10,
        "soil_fraction": 0.55,
    },
    "clay": {
        "density": 2000.0,
        "conductivity": 1.2,
        "heat_capacity": 1000.0,
        "water_fraction": 0.30,
        "soil_fraction": 0.45,
    },
    "rock": {
        "density": 2600.0,
        "conductivity": 3.0,
        "heat_capacity": 750.0,
        "water_fraction": 0.02,
        "soil_fraction": 0.85,
    },
}

# Default soil layer thicknesses (m), listed SURFACE -> BOTTOM (thin at the
# surface where the diurnal wave lives, thick at depth).
#
# NOTE: SNOWPACK reads .sno layers BOTTOM -> TOP (SmetIO.cc: "Layer %d from
# bottom"), so process() reverses this list before writing. Emitting it in
# surface-first order — as this tool used to — put the 5 cm skin layer at the
# bottom of the column and the 85 cm layer at the soil surface, which
# destroys the near-surface ground heat flux the snow energy balance needs.
DEFAULT_LAYER_THICKNESSES = {
    1: [2.0],
    2: [0.5, 1.5],
    3: [0.3, 0.5, 1.2],
    4: [0.1, 0.3, 0.5, 1.1],
    5: [0.05, 0.15, 0.3, 0.5, 1.0],
    6: [0.05, 0.1, 0.2, 0.3, 0.5, 0.85],
}


def validate_inputs(args):
    """Validate command-line arguments."""
    errors = []

    if not os.path.exists(args.dem):
        errors.append(f"DEM file not found: {args.dem}")

    if args.n_soil_layers < 1 or args.n_soil_layers > 20:
        errors.append(f"n_soil_layers must be 1–20, got {args.n_soil_layers}")

    if args.soil_type and args.soil_type not in SOIL_TYPES:
        errors.append(f"Unknown soil type: {args.soil_type}. "
                      f"Available: {', '.join(SOIL_TYPES.keys())}")

    if args.soil_density is not None and args.soil_density < 100:
        errors.append(f"Soil density {args.soil_density} kg/m³ seems too low. "
                      f"Did you use g/cm³? Multiply by 1000.")

    if args.soil_density is not None and args.soil_density > 5000:
        errors.append(f"Soil density {args.soil_density} kg/m³ seems too high.")

    # Validate date format
    try:
        datetime.strptime(args.date, "%Y-%m-%dT%H:%M")
    except ValueError:
        try:
            datetime.strptime(args.date, "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            errors.append(f"Date format must be YYYY-MM-DDTHH:MM, got: {args.date}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)


def read_arc_grid(filepath):
    """Read an ARC ASCII grid file. Returns header dict and 2D data list."""
    header = {}
    data_rows = []

    with open(filepath, "r") as f:
        # Read header (6 lines)
        for _ in range(6):
            line = f.readline().strip()
            parts = line.split()
            if len(parts) >= 2:
                key = parts[0].lower()
                try:
                    val = int(parts[1])
                except ValueError:
                    val = float(parts[1])
                header[key] = val

        # Read data
        for line in f:
            row = [float(x) for x in line.strip().split()]
            if row:
                data_rows.append(row)

    return header, data_rows


def estimate_soil_temperature(altitude, month):
    """Estimate initial soil temperature based on altitude and month.

    Uses a simple lapse rate model:
      T_soil ≈ mean_annual_T + seasonal_amplitude * cos(2π*(month-1)/12)
      mean_annual_T ≈ 15 - 0.006 * altitude (in K above 273.15)

    Returns temperature in Kelvin.
    """
    import math
    mean_annual_C = 15.0 - 0.006 * altitude
    seasonal_amp = 5.0  # °C amplitude
    seasonal_offset = math.cos(2.0 * math.pi * (month - 1) / 12.0)
    t_celsius = mean_annual_C + seasonal_amp * seasonal_offset
    # Soil temperature is damped relative to air
    t_soil_celsius = mean_annual_C + 0.5 * seasonal_amp * seasonal_offset
    return t_soil_celsius + 273.15


def write_sno_file(filepath, station_id, latitude, longitude, altitude,
                   profile_date, soil_layers, snow_layers=None, soil_albedo=0.2,
                   bare_soil_z0=0.02, easting=None, northing=None, epsg=None):
    """Write a single .sno file in SMET format.

    Args:
        soil_layers: list of dicts with keys:
            thickness, temperature, vol_frac_ice, vol_frac_water,
            vol_frac_voids, vol_frac_soil, rho_s, conduc_s, heat_capac_s
        snow_layers: optional list of dicts with snow layer properties
        easting/northing/epsg: if all given, the projected-coordinate SMET
            location keys are written instead of latitude/longitude. SMET
            accepts either pair; writing PROJECTED metres into `latitude`
            and `longitude` (which the tool used to do) makes MeteoIO reject
            the profile with "invalid latitude".

    FIELD LAYOUT IS POSITIONAL. SNOWPACK's SmetIO::readSnowCover parses the
    layer columns by index (see snowpack/plugins/SmetIO.cc ~line 417-457):
      hl tl phiIce phiWater phiVoids phiSoil SoilRho SoilK SoilC
      rg rb dd sp mk hr ne CDot metamo                    -> 18 numeric columns
    The canonical header (SmetIO.cc line 121 / 723) names them
      "... rg rb dd sp mk mass_hoar ne CDot metamo".
    The previous version of this tool emitted "... mk hr CDot metamo" — it
    both used the wrong name for mass_hoar AND omitted `ne` (number of
    finite elements per layer), so every subsequent column was read one
    position early: CDot was read as `ne`, giving ne=0 elements and a
    degenerate/unusable initial profile.
    """
    n_snow = len(snow_layers) if snow_layers else 0
    n_soil = len(soil_layers)

    fields = ("timestamp Layer_Thick T Vol_Frac_I Vol_Frac_W Vol_Frac_V "
              "Vol_Frac_S Rho_S Conduc_S HeatCapac_S rg rb dd sp mk "
              "mass_hoar ne CDot metamo")

    use_proj = easting is not None and northing is not None and epsg is not None

    with open(filepath, "w") as f:
        f.write("SMET 1.1 ASCII\n")
        f.write("[HEADER]\n")
        f.write(f"station_id       = {station_id}\n")
        if use_proj:
            f.write(f"easting          = {easting:.2f}\n")
            f.write(f"northing         = {northing:.2f}\n")
            f.write(f"epsg             = {int(epsg)}\n")
        else:
            f.write(f"latitude         = {latitude:.6f}\n")
            f.write(f"longitude        = {longitude:.6f}\n")
        f.write(f"altitude         = {altitude:.1f}\n")
        f.write(f"nodata           = -999\n")
        f.write(f"ProfileDate      = {profile_date}\n")
        f.write(f"HS_Last          = 0.000000\n")
        f.write(f"SlopeAngle       = 0.00\n")
        f.write(f"SlopeAzi         = 0.00\n")
        f.write(f"nSoilLayerData   = {n_soil}\n")
        f.write(f"nSnowLayerData   = {n_snow}\n")
        # Key names below MUST match SmetIO::get_doubleval lookups exactly
        # ("SoilAlbedo", "CanopyLeafAreaIndex") — the short forms "SoilAlb"
        # and "CanopyLAI" this tool used to write are not recognised.
        f.write(f"SoilAlbedo       = {soil_albedo}\n")
        f.write(f"BareSoil_z0      = {bare_soil_z0}\n")
        f.write(f"CanopyHeight     = 0.00\n")
        f.write(f"CanopyLeafAreaIndex = 0.00\n")
        f.write(f"CanopyDirectThroughfall = 1.00\n")
        f.write(f"WindScalingFactor = 1.00\n")
        f.write(f"ErosionLevel     = 0\n")
        f.write(f"TimeCountDeltaHS = 0.000000\n")
        f.write(f"fields           = {fields}\n")
        f.write("[DATA]\n")

        # Write soil layers (bottom to top)
        for layer in soil_layers:
            vals = [
                profile_date,
                f"{layer['thickness']:.6f}",
                f"{layer['temperature']:.2f}",
                f"{layer['vol_frac_ice']:.4f}",
                f"{layer['vol_frac_water']:.4f}",
                f"{layer['vol_frac_voids']:.4f}",
                f"{layer['vol_frac_soil']:.4f}",
                f"{layer['rho_s']:.1f}",
                f"{layer['conduc_s']:.4f}",
                f"{layer['heat_capac_s']:.1f}",
                f"{layer.get('rg', 0.3):.4f}",
                f"{layer.get('rb', 0.2):.4f}",
                f"{layer.get('dd', 0.0):.4f}",
                f"{layer.get('sp', 1.0):.4f}",
                f"{layer.get('mk', 0)}",
                f"{layer.get('mass_hoar', layer.get('hr', 0.0)):.6f}",
                f"{layer.get('ne', 1)}",
                f"{layer.get('CDot', 0.0):.6f}",
                f"{layer.get('metamo', 0.0):.6f}",
            ]
            f.write(" ".join(vals) + "\n")

        # Write snow layers if any
        if snow_layers:
            for layer in snow_layers:
                vals = [
                    layer.get("deposition_date", profile_date),
                    f"{layer['thickness']:.6f}",
                    f"{layer['temperature']:.2f}",
                    f"{layer['vol_frac_ice']:.4f}",
                    f"{layer['vol_frac_water']:.4f}",
                    f"{layer['vol_frac_voids']:.4f}",
                    "0.0000",  # vol_frac_soil = 0 for snow
                    "0.0",     # rho_s = 0 for snow
                    "0.0000",  # conduc_s = 0 for snow
                    "0.0",     # heat_capac_s = 0 for snow
                    f"{layer.get('rg', 0.15):.4f}",
                    f"{layer.get('rb', 0.1):.4f}",
                    f"{layer.get('dd', 0.5):.4f}",
                    f"{layer.get('sp', 0.5):.4f}",
                    f"{layer.get('mk', 0)}",
                    f"{layer.get('mass_hoar', layer.get('hr', 0.0)):.6f}",
                    f"{layer.get('ne', 1)}",
                    f"{layer.get('CDot', 0.0):.6f}",
                    f"{layer.get('metamo', 0.0):.6f}",
                ]
                f.write(" ".join(vals) + "\n")


def validate_sno_file(filepath):
    """Validate a generated .sno file for consistency."""
    warnings = []

    with open(filepath, "r") as f:
        content = f.read()

    if "SMET 1.1 ASCII" not in content:
        warnings.append("Missing SMET header")

    if "ProfileDate" not in content:
        warnings.append("Missing ProfileDate")

    if "nSoilLayerData" not in content:
        warnings.append("Missing nSoilLayerData")

    return warnings


def process(args):
    """Main processing: read DEM, generate .sno files for each valid pixel."""
    header, dem_data = read_arc_grid(args.dem)

    ncols = int(header.get("ncols", 0))
    nrows = int(header.get("nrows", 0))
    xll = float(header.get("xllcorner", 0))
    yll = float(header.get("yllcorner", 0))
    cellsize = float(header.get("cellsize", 0))
    nodata = float(header.get("nodata_value", -9999))

    # Get soil properties
    if args.soil_type:
        soil_props = SOIL_TYPES[args.soil_type]
    else:
        soil_props = {
            "density": args.soil_density or 1800.0,
            "conductivity": args.soil_conductivity or 1.5,
            "heat_capacity": args.soil_heat_capacity or 900.0,
            "water_fraction": args.soil_water_fraction or 0.20,
            "soil_fraction": args.soil_solid_fraction or 0.50,
        }

    # Validate soil properties
    if soil_props["density"] < 100:
        print("WARNING: Soil density < 100 kg/m³ — did you use g/cm³?", file=sys.stderr)
        soil_props["density"] *= 1000

    # Layer thicknesses. DEFAULT_LAYER_THICKNESSES is surface->bottom; SNOWPACK
    # reads .sno layers bottom->top, so reverse before writing.
    n_layers = args.n_soil_layers
    if n_layers in DEFAULT_LAYER_THICKNESSES:
        thicknesses = list(reversed(DEFAULT_LAYER_THICKNESSES[n_layers]))
    else:
        # Equal thickness layers
        total_depth = 2.0  # m
        thicknesses = [total_depth / n_layers] * n_layers

    # Optional projected-coordinate metadata for the SMET location keys.
    epsg = args.epsg

    os.makedirs(args.output, exist_ok=True)

    # Parse profile date
    profile_date = args.date
    month = int(profile_date[5:7])

    n_written = 0
    n_skipped = 0

    for row in range(nrows):
        for col in range(ncols):
            if row >= len(dem_data) or col >= len(dem_data[row]):
                n_skipped += 1
                continue

            altitude = dem_data[row][col]
            if altitude == nodata or altitude < -500:
                n_skipped += 1
                continue

            # Compute pixel center coordinates
            easting = xll + (col + 0.5) * cellsize
            northing = yll + (nrows - row - 0.5) * cellsize

            # --- .sno FILE NAME (Alpine3D convention, NOT free-form) --------
            # Alpine3D builds the name it looks for in SnowpackInterface.cc:
            #   per-pixel  GRID_sno = <ix>_<iy>_<EXPERIMENT>      (line ~1260)
            #   per-class  LUS_sno  = <EXPERIMENT>_<landuse_code> (line ~1259)
            # where ix is the COLUMN and iy the ROW COUNTED FROM THE BOTTOM
            # (MeteoIO grids are south-up), and EXPERIMENT is [Output]::
            # EXPERIMENT. The old `<row>_<col>.sno` name matched neither, so
            # Alpine3D found no initial profile and aborted.
            iy = nrows - 1 - row          # row index from the bottom
            if args.naming == "landuse":
                station_id = f"{args.experiment}_{args.landuse_code}"
            else:
                station_id = f"{col}_{iy}_{args.experiment}"

            # Estimate soil temperature
            t_soil = estimate_soil_temperature(altitude, month)

            # Build soil layers (bottom -> top, matching `thicknesses`)
            soil_layers = []
            n_thick = len(thicknesses)
            for i, thick in enumerate(thicknesses):
                # Warmer at depth: i=0 is the DEEPEST layer.
                layer_t = t_soil + 0.5 * (n_thick - i)

                water_frac = soil_props["water_fraction"]
                soil_frac = soil_props["soil_fraction"]
                void_frac = 1.0 - water_frac - soil_frac
                if void_frac < 0:
                    void_frac = 0.01
                    soil_frac = 1.0 - water_frac - void_frac

                soil_layers.append({
                    "thickness": thick,
                    "temperature": layer_t,
                    "vol_frac_ice": 0.0,
                    "vol_frac_water": water_frac,
                    "vol_frac_voids": void_frac,
                    "vol_frac_soil": soil_frac,
                    "rho_s": soil_props["density"],
                    "conduc_s": soil_props["conductivity"],
                    "heat_capac_s": soil_props["heat_capacity"],
                })

            filepath = os.path.join(args.output, f"{station_id}.sno")
            if os.path.exists(filepath) and args.naming == "landuse":
                # landuse naming yields ONE profile per class, not per pixel
                n_skipped += 1
                continue
            write_sno_file(
                filepath=filepath,
                station_id=station_id,
                # Projected DEM coordinates go in easting/northing/epsg — they
                # are NOT latitude/longitude (see write_sno_file docstring).
                latitude=args.latitude,
                longitude=args.longitude,
                altitude=altitude,
                profile_date=profile_date,
                soil_layers=soil_layers,
                easting=easting if epsg else None,
                northing=northing if epsg else None,
                epsg=epsg,
            )

            n_written += 1

    return {
        "status": "success",
        "n_pixels_written": n_written,
        "n_pixels_skipped": n_skipped,
        "n_soil_layers": n_layers,
        "output_dir": args.output,
        "soil_type": args.soil_type or "custom",
    }


def main():
    parser = argparse.ArgumentParser(
        description="Generate initial snow/soil profile (.sno) files for Alpine3D",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--dem", required=True, help="Path to ARC ASCII DEM file")
    parser.add_argument("--output", required=True, help="Output directory for .sno files")
    parser.add_argument("--date", required=True,
                        help="Profile date (YYYY-MM-DDTHH:MM)")
    parser.add_argument("--n-soil-layers", type=int, default=3,
                        help="Number of soil layers (default: 3)")
    parser.add_argument("--soil-type", default="mineral",
                        choices=list(SOIL_TYPES.keys()),
                        help="Predefined soil type (default: mineral)")
    parser.add_argument("--soil-density", type=float, default=None,
                        help="Custom soil density (kg/m³)")
    parser.add_argument("--soil-conductivity", type=float, default=None,
                        help="Custom soil thermal conductivity (W/(m·K))")
    parser.add_argument("--soil-heat-capacity", type=float, default=None,
                        help="Custom soil heat capacity (J/(kg·K))")
    parser.add_argument("--soil-water-fraction", type=float, default=None,
                        help="Custom soil volumetric water content (0–1)")
    parser.add_argument("--soil-solid-fraction", type=float, default=None,
                        help="Custom soil solid fraction (0–1)")

    # --- Alpine3D .sno naming (see process() for the convention) -----------
    parser.add_argument("--experiment", default="sim",
                        help="[Output]::EXPERIMENT from io.ini. Alpine3D looks for "
                             "'<col>_<row_from_bottom>_<EXPERIMENT>.sno' (pixel) or "
                             "'<EXPERIMENT>_<landuse_code>.sno' (landuse).")
    parser.add_argument("--naming", default="pixel", choices=["pixel", "landuse"],
                        help="pixel: one .sno per grid cell named <ix>_<iy>_<EXPERIMENT>. "
                             "landuse: a single .sno per land-use class named "
                             "<EXPERIMENT>_<code> (default Alpine3D fallback). "
                             "(default: pixel)")
    parser.add_argument("--landuse-code", type=int, default=10851,
                        help="Land-use (PREVAH) code used by --naming landuse "
                             "(default: 10851 = alpine grassland/tundra)")
    # SMET location keys
    parser.add_argument("--epsg", type=int, default=None,
                        help="EPSG code of the DEM's projected CRS. When given, "
                             "each .sno carries easting/northing/epsg (correct for a "
                             "projected DEM) instead of latitude/longitude.")
    parser.add_argument("--latitude", type=float, default=0.0,
                        help="Site latitude (WGS84), used only when --epsg is absent")
    parser.add_argument("--longitude", type=float, default=0.0,
                        help="Site longitude (WGS84), used only when --epsg is absent")

    args = parser.parse_args()

    validate_inputs(args)
    result = process(args)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
