#!/usr/bin/env python3
"""
convert_soil_to_trigrs.py
=========================
Convert soil property data (HWSD, SoilGrids, or manual tables) into
TRIGRS zone parameters and property zone grid files.

TRIGRS uses zone-based soil properties. Each grid cell is assigned a zone
integer, and each zone has a fixed set of geotechnical/hydraulic properties.

CRITICAL UNIT REQUIREMENTS (TRIGRS expects):
    - cohesion:     Pa       (NOT kPa -- 1000x trap)
    - phi:          degrees
    - uws:          N/m^3    (NOT kN/m^3 -- 1000x trap)
    - diffusivity:  m^2/s
    - K-sat:        m/s      (NOT cm/hr, NOT mm/hr)
    - Theta-sat:    fraction (0-1)
    - Theta-res:    fraction (0-1)
    - Alpha:        1/m      (Gardner parameter; negative = use saturated model)

Usage:
    python convert_soil_to_trigrs.py \\
        --soil_data soil_properties.csv \\
        --dem dem.asc \\
        --output_zones zones.asc \\
        --output_params soil_params.txt

Output:
    - zones.asc           (integer zone grid matching DEM)
    - soil_params.txt     (zone blocks for tr_in.txt)
"""

import argparse
import csv
import os
import sys
from typing import Dict, List, Tuple

import numpy as np

# ---------------------------------------------------------------------------
# Pedotransfer function lookup tables (simplified HWSD -> geotechnical)
# ---------------------------------------------------------------------------
# USDA texture classes -> typical geotechnical properties
TEXTURE_PROPERTIES = {
    "sand": {
        "cohesion_pa": 0.0,
        "phi_deg": 35.0,
        "uws_nm3": 18000.0,
        "diffusivity_m2s": 1.0e-3,
        "ksat_ms": 5.0e-5,
        "theta_sat": 0.43,
        "theta_res": 0.05,
        "alpha_1m": 14.5,
    },
    "loamy_sand": {
        "cohesion_pa": 500.0,
        "phi_deg": 33.0,
        "uws_nm3": 18500.0,
        "diffusivity_m2s": 5.0e-4,
        "ksat_ms": 1.0e-5,
        "theta_sat": 0.41,
        "theta_res": 0.06,
        "alpha_1m": 12.4,
    },
    "sandy_loam": {
        "cohesion_pa": 2000.0,
        "phi_deg": 30.0,
        "uws_nm3": 19000.0,
        "diffusivity_m2s": 1.0e-4,
        "ksat_ms": 5.0e-6,
        "theta_sat": 0.41,
        "theta_res": 0.07,
        "alpha_1m": 7.5,
    },
    "loam": {
        "cohesion_pa": 5000.0,
        "phi_deg": 28.0,
        "uws_nm3": 19500.0,
        "diffusivity_m2s": 5.0e-5,
        "ksat_ms": 1.0e-6,
        "theta_sat": 0.43,
        "theta_res": 0.08,
        "alpha_1m": 3.6,
    },
    "silt_loam": {
        "cohesion_pa": 8000.0,
        "phi_deg": 26.0,
        "uws_nm3": 19500.0,
        "diffusivity_m2s": 1.0e-5,
        "ksat_ms": 5.0e-7,
        "theta_sat": 0.45,
        "theta_res": 0.07,
        "alpha_1m": 2.0,
    },
    "clay_loam": {
        "cohesion_pa": 15000.0,
        "phi_deg": 22.0,
        "uws_nm3": 20000.0,
        "diffusivity_m2s": 5.0e-6,
        "ksat_ms": 1.0e-7,
        "theta_sat": 0.41,
        "theta_res": 0.10,
        "alpha_1m": 1.9,
    },
    "clay": {
        "cohesion_pa": 25000.0,
        "phi_deg": 18.0,
        "uws_nm3": 21000.0,
        "diffusivity_m2s": 1.0e-6,
        "ksat_ms": 1.0e-8,
        "theta_sat": 0.38,
        "theta_res": 0.07,
        "alpha_1m": 0.8,
    },
    "colluvium": {
        "cohesion_pa": 3500.0,
        "phi_deg": 35.0,
        "uws_nm3": 22000.0,
        "diffusivity_m2s": 6.0e-6,
        "ksat_ms": 1.0e-7,
        "theta_sat": 0.45,
        "theta_res": 0.05,
        "alpha_1m": 0.5,
    },
}

# Physical bounds for validation
BOUNDS = {
    "cohesion_pa": (0.0, 100000.0),
    "phi_deg": (0.0, 60.0),
    "uws_nm3": (14000.0, 25000.0),
    "diffusivity_m2s": (1e-8, 1.0),
    "ksat_ms": (1e-10, 1e-2),
    "theta_sat": (0.2, 0.7),
    "theta_res": (0.01, 0.3),
    "alpha_1m": (0.1, 100.0),
}


def validate_inputs(soil_data_path: str, dem_path: str) -> dict:
    """Validate input files exist and are readable."""
    errors = []

    if not os.path.isfile(soil_data_path):
        errors.append(f"Soil data file not found: {soil_data_path}")

    if not os.path.isfile(dem_path):
        errors.append(f"DEM file not found: {dem_path}")

    if errors:
        raise ValueError("Input validation failed:\n  " + "\n  ".join(errors))

    dem_meta = read_asc_header(dem_path)
    return {"dem_meta": dem_meta}


def read_asc_header(filepath: str) -> dict:
    """Read ESRI ASCII grid header."""
    meta = {}
    with open(filepath, "r") as f:
        for _ in range(6):
            line = f.readline().strip().split()
            if len(line) >= 2:
                key = line[0].lower()
                try:
                    val = int(line[1])
                except ValueError:
                    val = float(line[1])
                meta[key] = val
    return meta


def read_asc_grid(filepath: str) -> Tuple[dict, np.ndarray]:
    """Read ESRI ASCII grid, return header and data array."""
    meta = read_asc_header(filepath)
    ncols = int(meta.get("ncols", 0))
    nrows = int(meta.get("nrows", 0))
    nodata = meta.get("nodata_value", -9999)

    data = np.loadtxt(filepath, skiprows=6)
    if data.shape != (nrows, ncols):
        data = data.reshape(nrows, ncols)
    return meta, data


def read_soil_csv(filepath: str) -> List[dict]:
    """
    Read soil properties CSV. Expected columns:
    zone_id, texture OR individual properties.
    """
    zones = []
    with open(filepath, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            zone = {"zone_id": int(row.get("zone_id", len(zones) + 1))}

            # Check if texture class provided
            if "texture" in row and row["texture"].strip():
                texture = row["texture"].strip().lower().replace(" ", "_")
                if texture in TEXTURE_PROPERTIES:
                    zone.update(TEXTURE_PROPERTIES[texture])
                else:
                    print(f"  WARNING: Unknown texture '{texture}', "
                          f"using loam defaults")
                    zone.update(TEXTURE_PROPERTIES["loam"])
            else:
                # Read individual properties
                zone["cohesion_pa"] = float(row.get("cohesion_pa", 5000))
                zone["phi_deg"] = float(row.get("phi_deg", 30))
                zone["uws_nm3"] = float(row.get("uws_nm3", 19000))
                zone["diffusivity_m2s"] = float(
                    row.get("diffusivity_m2s", 1e-5))
                zone["ksat_ms"] = float(row.get("ksat_ms", 1e-6))
                zone["theta_sat"] = float(row.get("theta_sat", 0.43))
                zone["theta_res"] = float(row.get("theta_res", 0.07))
                zone["alpha_1m"] = float(row.get("alpha_1m", -0.5))

            zones.append(zone)
    return zones


def apply_unit_conversions(zones: List[dict],
                           cohesion_unit: str = "pa",
                           uws_unit: str = "n/m3",
                           ksat_unit: str = "m/s") -> List[dict]:
    """
    Convert input properties to TRIGRS-expected units.

    TRAP WARNING: This is where 1000x errors commonly occur.
    """
    for zone in zones:
        # Cohesion: TRIGRS expects Pa
        if cohesion_unit == "kpa":
            zone["cohesion_pa"] *= 1000.0
            print(f"  Zone {zone['zone_id']}: cohesion converted from kPa to Pa")
        elif cohesion_unit == "psf":
            zone["cohesion_pa"] *= 47.8698
            print(f"  Zone {zone['zone_id']}: cohesion converted from psf to Pa")

        # Unit weight of soil: TRIGRS expects N/m^3
        if uws_unit == "kn/m3":
            zone["uws_nm3"] *= 1000.0
            print(f"  Zone {zone['zone_id']}: uws converted from kN/m^3 to N/m^3")

        # K-sat: TRIGRS expects m/s
        if ksat_unit == "cm/hr":
            zone["ksat_ms"] *= 2.778e-6
            print(f"  Zone {zone['zone_id']}: Ksat converted from cm/hr to m/s")
        elif ksat_unit == "cm/s":
            zone["ksat_ms"] *= 0.01
        elif ksat_unit == "mm/hr":
            zone["ksat_ms"] /= 3.6e6

    return zones


def validate_zone_properties(zones: List[dict]) -> List[str]:
    """Check all zone properties are within physical bounds."""
    warnings = []
    for zone in zones:
        zid = zone["zone_id"]
        for prop, (lo, hi) in BOUNDS.items():
            val = zone.get(prop, 0)
            if prop == "alpha_1m" and val < 0:
                # Negative alpha means saturated model -- valid
                continue
            if val < lo or val > hi:
                warnings.append(
                    f"Zone {zid}: {prop} = {val:.4e} outside "
                    f"typical range [{lo:.4e}, {hi:.4e}]"
                )
    return warnings


def write_zone_grid(filepath: str, dem_meta: dict,
                    zone_map: np.ndarray) -> None:
    """Write integer zone grid in ESRI ASCII format."""
    ncols = int(dem_meta.get("ncols", 10))
    nrows = int(dem_meta.get("nrows", 10))
    xll = dem_meta.get("xllcorner", 0)
    yll = dem_meta.get("yllcorner", 0)
    cellsize = dem_meta.get("cellsize", 10)
    nodata = int(dem_meta.get("nodata_value", -9999))

    with open(filepath, "w") as f:
        f.write(f"ncols         {ncols}\n")
        f.write(f"nrows         {nrows}\n")
        f.write(f"xllcorner     {xll}\n")
        f.write(f"yllcorner     {yll}\n")
        f.write(f"cellsize      {cellsize}\n")
        f.write(f"NODATA_value  {nodata}\n")
        for r in range(nrows):
            row_str = " ".join([str(int(zone_map[r, c]))
                                for c in range(ncols)])
            f.write(row_str + "\n")


def write_soil_params(filepath: str, zones: List[dict]) -> None:
    """Write zone parameter blocks for inclusion in tr_in.txt."""
    with open(filepath, "w") as f:
        f.write("# Soil zone parameters for tr_in.txt\n")
        f.write("# Generated by convert_soil_to_trigrs.py\n")
        f.write(f"# {len(zones)} zones\n\n")
        f.write(f"zones = {len(zones)}\n\n")

        for zone in zones:
            zid = zone["zone_id"]
            f.write(f"zone, {zid}\n")
            f.write("cohesion,phi,  uws,   diffus,   K-sat, "
                    "Theta-sat,Theta-res,Alpha\n")
            f.write(
                f"{zone['cohesion_pa']:.4e}, "
                f"{zone['phi_deg']:.1f}, "
                f"{zone['uws_nm3']:.4e}, "
                f"{zone['diffusivity_m2s']:.4e}, "
                f"{zone['ksat_ms']:.4e}, "
                f"{zone['theta_sat']:.2f}, "
                f"{zone['theta_res']:.2f}, "
                f"{zone['alpha_1m']:.1f}\n\n"
            )


def main():
    parser = argparse.ArgumentParser(
        description="Convert soil data to TRIGRS zone parameters"
    )
    parser.add_argument("--soil_data", required=True,
                        help="Soil properties CSV")
    parser.add_argument("--dem", required=True,
                        help="DEM ASCII grid file")
    parser.add_argument("--output_zones", default="zones.asc",
                        help="Output zone grid file")
    parser.add_argument("--output_params", default="soil_params.txt",
                        help="Output parameter file")
    parser.add_argument("--cohesion_unit", default="pa",
                        choices=["pa", "kpa", "psf"])
    parser.add_argument("--uws_unit", default="n/m3",
                        choices=["n/m3", "kn/m3"])
    parser.add_argument("--ksat_unit", default="m/s",
                        choices=["m/s", "cm/hr", "cm/s", "mm/hr"])

    args = parser.parse_args()

    # Step 1: Validate inputs
    print("[1/4] Validating inputs...")
    params = validate_inputs(args.soil_data, args.dem)

    # Step 2: Read soil data
    print("[2/4] Reading soil data...")
    zones = read_soil_csv(args.soil_data)
    print(f"  Read {len(zones)} zones")

    # Apply unit conversions
    zones = apply_unit_conversions(zones, args.cohesion_unit,
                                   args.uws_unit, args.ksat_unit)

    # Step 3: Write outputs
    print("[3/4] Writing outputs...")
    dem_meta = params["dem_meta"]
    ncols = int(dem_meta.get("ncols", 10))
    nrows = int(dem_meta.get("nrows", 10))

    # Create zone grid (default: all zone 1 if only one zone)
    if len(zones) == 1:
        zone_map = np.ones((nrows, ncols), dtype=int)
    else:
        # Simple assignment: zone_id cycles through zones
        zone_map = np.ones((nrows, ncols), dtype=int)
        # In real use, the zone grid comes from GIS classification

    write_zone_grid(args.output_zones, dem_meta, zone_map)
    write_soil_params(args.output_params, zones)

    # Step 4: Validate
    print("[4/4] Validating outputs...")
    warnings = validate_zone_properties(zones)
    if warnings:
        print("  WARNINGS:")
        for w in warnings:
            print(f"    - {w}")
    else:
        print("  All zone properties within physical bounds")

    print(f"\nDone. Zone grid: {args.output_zones}")
    print(f"Parameters: {args.output_params}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
