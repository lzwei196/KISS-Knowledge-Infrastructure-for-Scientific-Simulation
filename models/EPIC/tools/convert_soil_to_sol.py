#!/usr/bin/env python3
"""
Convert HWSD / SoilGrids soil data to EPIC .SOL and .SIT file formats.

Pipeline: HWSD raster or SoilGrids CSV → layer interpolation → .SOL + .SIT
Pattern:  validate inputs → process → validate outputs

Supports:
  - HWSD (Harmonized World Soil Database) raster
  - SoilGrids CSV exports (from ISRIC)
  - Generic CSV with soil layer properties
"""

import os
import sys
import argparse
import numpy as np
import pandas as pd
from pathlib import Path


# ---------------------------------------------------------------------------
# EPIC SOL format specification
# ---------------------------------------------------------------------------
SOL_PROPERTIES = [
    "Layer_depth",         # cm
    "Bulk_Density",        # g/cm3
    "Wilting_capacity",    # fraction (m3/m3)
    "Field_Capacity",      # fraction (m3/m3)
    "Sand_content",        # %
    "Silt_content",        # %
    "N_concen",            # mg/kg (ppm)
    "pH",                  # pH units
    "Sum_Bases",           # meq/100g
    "Organic_Carbon",      # %
    "Calcium_Carbonate",   # %
    "Cation_exchange",     # meq/100g
    "Coarse_Fragment",     # %
    "Sat_conductivity",    # mm/hr
    "pkrz",                # linear parameter
    "rsd",                 # residual water content
    "BD_dry",              # g/cm3
    "psp",                 # pore size parameter
    "Ksat_2",              # mm/hr (duplicate)
]

# Hydrological group mapping
HYDGRP_MAP = {"A": 1.0, "B": 2.0, "C": 3.0, "D": 4.0,
              "A/D": 1.0, "B/D": 2.0, "C/D": 3.0}

# Default layer depths for EPIC (10 layers, cm)
DEFAULT_LAYERS_CM = [18, 28, 52, 77, 101, 126, 152, 178, 203, 229]

SOL_FMT = "%8.3f"


def validate_inputs(soil_data: pd.DataFrame, source: str) -> list:
    """Validate raw soil input data."""
    errors = []

    if soil_data.empty:
        errors.append("ERROR: Soil data is empty")
        return errors

    # Check for physically unreasonable values
    if "Bulk_Density" in soil_data.columns:
        bd = soil_data["Bulk_Density"]
        if bd.min() < 0.5 or bd.max() > 2.5:
            errors.append(
                f"WARNING: Bulk density range [{bd.min():.2f}, {bd.max():.2f}] "
                f"outside normal range [0.5, 2.5] g/cm3"
            )

    if "Sand_content" in soil_data.columns and "Silt_content" in soil_data.columns:
        total = soil_data["Sand_content"] + soil_data["Silt_content"]
        if total.max() > 105:  # allow small tolerance
            errors.append(
                f"WARNING: Sand + Silt = {total.max():.1f}% > 100% in some layers"
            )

    if "pH" in soil_data.columns:
        ph = soil_data["pH"]
        if ph.min() < 3.0 or ph.max() > 10.0:
            errors.append(
                f"WARNING: pH range [{ph.min():.1f}, {ph.max():.1f}] "
                f"outside normal range [3, 10]"
            )

    return errors


def convert_hwsd_to_layers(hwsd_record: dict) -> pd.DataFrame:
    """
    Convert a single HWSD grid cell record to EPIC soil layers.

    HWSD provides topsoil (0-30 cm) and subsoil (30-100 cm) properties.
    We interpolate to 10 EPIC layers.

    HWSD units → EPIC units:
      T_BULK_DENSITY: kg/dm3 = g/cm3 (same)
      T_SAND, T_SILT, T_CLAY: % (same)
      T_PH_H2O: pH (same)
      T_OC: % (same)
      T_CEC_SOIL: cmol(+)/kg = meq/100g (same)
      T_GRAVEL: % vol (same)
      T_REF_BULK_DENSITY: kg/dm3 = g/cm3 (same)

    CRITICAL: HWSD gives Organic Carbon directly as %, NOT Organic Matter.
    If source gives OM%, convert: OC% = OM% / 1.724 (Van Bemmelen factor)
    """
    layers = []
    for i, depth in enumerate(DEFAULT_LAYERS_CM):
        # Determine if topsoil (< 30 cm) or subsoil
        prefix = "T_" if depth <= 30 else "S_"

        layer = {
            "Layer_depth": depth,
            "Bulk_Density": hwsd_record.get(f"{prefix}BULK_DENSITY", 1.40),
            "Sand_content": hwsd_record.get(f"{prefix}SAND", 40.0),
            "Silt_content": hwsd_record.get(f"{prefix}SILT", 30.0),
            "pH": hwsd_record.get(f"{prefix}PH_H2O", 6.5),
            "Organic_Carbon": hwsd_record.get(f"{prefix}OC", 1.0),
            "Cation_exchange": hwsd_record.get(f"{prefix}CEC_SOIL", 15.0),
            "Coarse_Fragment": hwsd_record.get(f"{prefix}GRAVEL", 5.0),
            "BD_dry": hwsd_record.get(f"{prefix}REF_BULK_DENSITY", 1.35),
        }

        # Estimate missing properties using pedotransfer functions
        sand = layer["Sand_content"]
        clay = 100 - sand - layer["Silt_content"]

        # Wilting point (Saxton & Rawls, 2006)
        layer["Wilting_capacity"] = max(0.04, 0.09878 + 0.002135 * clay
                                        - 0.0004434 * sand)

        # Field capacity
        layer["Field_Capacity"] = max(
            layer["Wilting_capacity"] + 0.05,
            0.2576 - 0.002 * sand + 0.0036 * clay
        )

        # Saturated hydraulic conductivity (mm/hr) from sand content
        # Cosby et al. (1984): log10(Ksat) = -0.6 + 0.0126*sand - 0.0064*clay
        log_ksat = -0.6 + 0.0126 * sand - 0.0064 * clay
        layer["Sat_conductivity"] = 10 ** log_ksat * 25.4  # in/hr to mm/hr
        layer["Ksat_2"] = layer["Sat_conductivity"]

        # Defaults for less common properties
        layer["N_concen"] = max(50, layer["Organic_Carbon"] * 800)
        layer["Sum_Bases"] = max(0, layer["Cation_exchange"] * 0.6)
        layer["Calcium_Carbonate"] = hwsd_record.get(f"{prefix}CACO3", 0.0)
        layer["pkrz"] = 0.0
        layer["rsd"] = max(0.01, layer["Wilting_capacity"] * 0.5)
        layer["psp"] = 0.0

        layers.append(layer)

    return pd.DataFrame(layers)


def convert_soilgrids_csv(csv_path: str) -> pd.DataFrame:
    """
    Convert SoilGrids CSV export to EPIC soil layers.

    SoilGrids units → EPIC units:
      bdod: cg/cm3 → g/cm3: divide by 100
      sand, silt, clay: g/kg → %: divide by 10
      phh2o: pH*10 → pH: divide by 10
      soc: dg/kg → %: divide by 100 (dg/kg = 0.1 g/kg)
      cec: mmol(c)/kg → meq/100g: divide by 10
      cfvo: cm3/dm3 → %: divide by 10
    """
    df = pd.read_csv(csv_path)

    # SoilGrids depths: 0-5, 5-15, 15-30, 30-60, 60-100, 100-200 cm
    sg_depths = [5, 15, 30, 60, 100, 200]

    layers = []
    for i, depth in enumerate(DEFAULT_LAYERS_CM):
        # Find closest SoilGrids layer
        sg_idx = min(range(len(sg_depths)),
                     key=lambda j: abs(sg_depths[j] - depth))
        row = df.iloc[sg_idx] if sg_idx < len(df) else df.iloc[-1]

        # UNIT CONVERSIONS — critical!
        layer = {
            "Layer_depth": depth,
            "Bulk_Density": row.get("bdod", 140) / 100.0,    # cg/cm3 → g/cm3
            "Sand_content": row.get("sand", 400) / 10.0,     # g/kg → %
            "Silt_content": row.get("silt", 300) / 10.0,     # g/kg → %
            "pH": row.get("phh2o", 65) / 10.0,               # pH*10 → pH
            "Organic_Carbon": row.get("soc", 100) / 100.0,   # dg/kg → %
            "Cation_exchange": row.get("cec", 150) / 10.0,   # mmol/kg → meq/100g
            "Coarse_Fragment": row.get("cfvo", 50) / 10.0,   # cm3/dm3 → %
        }

        sand = layer["Sand_content"]
        clay = 100 - sand - layer["Silt_content"]

        layer["Wilting_capacity"] = max(0.04, 0.09878 + 0.002135 * clay
                                        - 0.0004434 * sand)
        layer["Field_Capacity"] = max(
            layer["Wilting_capacity"] + 0.05,
            0.2576 - 0.002 * sand + 0.0036 * clay
        )
        log_ksat = -0.6 + 0.0126 * sand - 0.0064 * clay
        layer["Sat_conductivity"] = 10 ** log_ksat * 25.4
        layer["Ksat_2"] = layer["Sat_conductivity"]
        layer["N_concen"] = max(50, layer["Organic_Carbon"] * 800)
        layer["Sum_Bases"] = max(0, layer["Cation_exchange"] * 0.6)
        layer["Calcium_Carbonate"] = 0.0
        layer["BD_dry"] = layer["Bulk_Density"] * 0.95
        layer["pkrz"] = 0.0
        layer["rsd"] = max(0.01, layer["Wilting_capacity"] * 0.5)
        layer["psp"] = 0.0

        layers.append(layer)

    return pd.DataFrame(layers)


def validate_outputs(layers: pd.DataFrame) -> list:
    """Validate soil layers before writing SOL file."""
    errors = []

    # Layer depths must be monotonically increasing
    depths = layers["Layer_depth"].values
    if not all(depths[i] < depths[i + 1] for i in range(len(depths) - 1)):
        errors.append("ERROR: Layer depths must be monotonically increasing")

    # Bulk density range
    bd = layers["Bulk_Density"]
    if bd.min() < 0.3 or bd.max() > 2.65:
        errors.append(
            f"WARNING: Bulk density [{bd.min():.2f}, {bd.max():.2f}] "
            f"outside physical range. Check units (must be g/cm3, not kg/m3)."
        )

    # Wilting < Field Capacity < 1.0
    if (layers["Wilting_capacity"] >= layers["Field_Capacity"]).any():
        errors.append("ERROR: Wilting capacity >= Field capacity in some layers")

    # Sand + Silt <= 100
    total = layers["Sand_content"] + layers["Silt_content"]
    if total.max() > 100.5:
        errors.append(f"ERROR: Sand + Silt = {total.max():.1f}% > 100%")

    # Ksat > 0
    if (layers["Sat_conductivity"] <= 0).any():
        errors.append("WARNING: Saturated conductivity <= 0 in some layers")

    return errors


def write_sol(layers: pd.DataFrame, output_path: str,
              soil_id: str = "SOIL001",
              albedo: float = 0.13, hydgrp: str = "B"):
    """Write EPIC .SOL file in fixed-width format."""
    num_layers = len(layers)
    hydgrp_code = HYDGRP_MAP.get(hydgrp.upper(), 2.0)

    lines = []

    # Line 1: Soil ID
    lines.append(f"ID: {soil_id}")

    # Line 2: Albedo and hydrological group
    line2 = f"{albedo:8.3f}{hydgrp_code:8.3f}"
    line2 += " " * (80 - len(line2))
    lines.append(line2)

    # Line 3: Number of layers
    line3 = f"{num_layers:8.3f}"
    line3 += " " * (80 - len(line3))
    lines.append(line3)

    # Lines 4-22: Property rows (19 properties, each row has num_layers columns)
    for prop in SOL_PROPERTIES:
        row_values = layers[prop].values
        line = "".join(f"{v:8.3f}" for v in row_values)
        lines.append(line)

    # Pad to at least 42 lines
    while len(lines) < 42:
        lines.append(" " * 80)

    with open(output_path, "w") as f:
        f.write("\n".join(lines) + "\n")

    print(f"Wrote {num_layers}-layer SOL to {output_path}")


def write_sit(output_path: str, site_id: str = "SITE001",
              lat: float = 35.0, lon: float = -78.0, elev: float = 100.0,
              slope_length: float = 50.0, slope_steepness: float = 0.01,
              description: str = "EPIC simulation site"):
    """Write EPIC .SIT file."""
    lines = []

    # Line 1: Description
    lines.append(f"{description:<80s}")

    # Line 2: Prototype
    lines.append(f"{site_id}.SIT" + " " * (80 - len(f"{site_id}.SIT")))

    # Line 3: Site ID
    lines.append(f"ID: {site_id}" + " " * (80 - len(f"ID: {site_id}")))

    # Line 4: Lat, Lon, Elevation, other params
    line4 = (f"{lat:8.2f}{lon:8.2f}{elev:8.2f}"
             f"{'':8s}{'':8s}{'':8s}{'':8s}{'':8s}{'':8s}{'':8s}{'':8s}")
    lines.append(line4)

    # Line 5: Slope parameters
    line5 = " " * 48 + f"{slope_length:8.1f}{slope_steepness:8.2f}"
    lines.append(line5)

    # Line 6: Empty
    lines.append(" " * 80)

    # Line 7: Flags
    lines.append("   0   0   0   0   0  21   0  10  22   0   0")

    with open(output_path, "w") as f:
        f.write("\n".join(lines) + "\n")

    print(f"Wrote SIT to {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Convert soil data to EPIC .SOL and .SIT formats"
    )
    parser.add_argument("--source", choices=["hwsd", "soilgrids", "csv"],
                        required=True, help="Soil data source")
    parser.add_argument("--input", required=True,
                        help="Input file path")
    parser.add_argument("--output-dir", required=True,
                        help="Output directory for .SOL and .SIT files")
    parser.add_argument("--site-id", default="SITE001",
                        help="Site identifier (max 9 chars)")
    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--lon", type=float, required=True)
    parser.add_argument("--elev", type=float, default=100.0,
                        help="Elevation in meters")
    parser.add_argument("--hydgrp", default="B",
                        help="Hydrological group (A/B/C/D)")

    args = parser.parse_args()
    os.makedirs(args.output_dir, exist_ok=True)

    # Step 1: Convert to layers
    if args.source == "hwsd":
        # Read HWSD record (simplified — in practice use rasterio)
        import json
        with open(args.input) as f:
            record = json.load(f)
        layers = convert_hwsd_to_layers(record)
    elif args.source == "soilgrids":
        layers = convert_soilgrids_csv(args.input)
    elif args.source == "csv":
        layers = pd.read_csv(args.input)

    # Step 2: Validate inputs
    input_errors = validate_inputs(layers, args.source)
    for e in input_errors:
        print(e)

    # Step 3: Validate outputs
    output_errors = validate_outputs(layers)
    for e in output_errors:
        print(e)

    if any("ERROR" in e for e in output_errors):
        print("FATAL: Soil validation failed.")
        sys.exit(1)

    # Step 4: Write files
    sol_path = os.path.join(args.output_dir, f"{args.site_id}.SOL")
    sit_path = os.path.join(args.output_dir, f"{args.site_id}.SIT")

    write_sol(layers, sol_path, soil_id=args.site_id, hydgrp=args.hydgrp)
    write_sit(sit_path, site_id=args.site_id,
              lat=args.lat, lon=args.lon, elev=args.elev)


if __name__ == "__main__":
    main()
