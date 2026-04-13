#!/usr/bin/env python3
"""
Generate Cell2Fire fuel lookup tables and convert landscape rasters.

Produces:
  - spain_lookup_table.csv (for Scott & Burgan / --sim S)
  - fbp_lookup_table.csv (for Canadian FBP / --sim C)

Also converts fuel rasters between different classification systems
and prepares landscape ASC files (fuels, elevation, slope, aspect).

Usage:
  python convert_fuel_params.py --model S --output-dir ./instance_folder
  python convert_fuel_params.py --model C --output-dir ./instance_folder --custom-fuels custom.csv
"""

import argparse
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd


# ── Validation ──────────────────────────────────────────────────────────────

def validate_inputs(model: str, fuel_raster_path: str = None, custom_fuels: str = None) -> list:
    """Validate input parameters. Returns list of warnings."""
    warnings = []

    if model not in ("S", "C", "K", "P"):
        raise ValueError(f"Unknown model: {model}. Use S, C, K, or P.")

    if fuel_raster_path and not os.path.exists(fuel_raster_path):
        raise FileNotFoundError(f"Fuel raster not found: {fuel_raster_path}")

    if custom_fuels and not os.path.exists(custom_fuels):
        raise FileNotFoundError(f"Custom fuel table not found: {custom_fuels}")

    return warnings


def validate_fuel_raster(fuel_data: np.ndarray, model: str) -> list:
    """Validate fuel raster values against expected fuel codes."""
    warnings = []
    unique_codes = np.unique(fuel_data[fuel_data != -9999])

    if model == "S":
        valid_ranges = set(range(0, 1)) | set(range(91, 100)) | set(range(101, 109)) | \
                       set(range(121, 125)) | set(range(141, 150)) | set(range(161, 166)) | \
                       set(range(181, 190)) | set(range(201, 205))
        invalid = [c for c in unique_codes if int(c) not in valid_ranges]
        if invalid:
            warnings.append(
                f"WARNING: Found fuel codes not in standard S&B range: {invalid[:10]}. "
                "Ensure your spain_lookup_table.csv maps these codes."
            )
    elif model == "C":
        valid_codes = {0, 1, 2, 3, 4, 5, 6, 7, 11, 12, 13, 14, 16, 17, 18, 19, 20}
        invalid = [c for c in unique_codes if int(c) not in valid_codes]
        if invalid:
            warnings.append(
                f"WARNING: Found fuel codes not in standard FBP range: {invalid[:10]}. "
                "Ensure your fbp_lookup_table.csv maps these codes."
            )

    return warnings


def validate_outputs(lookup_path: str) -> list:
    """Validate the generated lookup table."""
    warnings = []

    if not os.path.exists(lookup_path):
        raise FileNotFoundError(f"Lookup table was not created: {lookup_path}")

    df = pd.read_csv(lookup_path)
    if len(df) == 0:
        warnings.append("WARNING: Lookup table is empty")

    if "grid_value" not in df.columns and "grid_value" not in [c.strip() for c in df.columns]:
        warnings.append("WARNING: Lookup table missing 'grid_value' column")

    return warnings


# ── Default lookup tables ───────────────────────────────────────────────────

# Standard Scott & Burgan fuel model lookup
SB_LOOKUP = """grid_value,export_value,descriptive_name,fuel_type, r, g, b, h, s, l
0,0,Non-burnable,NB,0,0,0,0,0,0
91,91,Urban/Developed NB1,NB1,100,100,100,0,0,100
92,92,Snow/Ice NB2,NB2,200,200,255,170,255,228
93,93,Agriculture NB3,NB3,255,255,200,42,255,228
99,99,Water NB9,NB9,0,0,200,170,255,100
101,101,Short sparse grass GR1,GR1,209,255,115,57,255,185
102,102,Low load dry climate grass GR2,GR2,209,255,115,57,255,185
103,103,Low load humid climate grass GR3,GR3,34,102,51,95,128,68
104,104,Moderate load dry climate grass GR4,GR4,131,199,149,96,96,165
105,105,Low load humid climate grass GR5,GR5,112,168,0,57,255,84
106,106,Moderate load humid climate grass GR6,GR6,223,184,230,206,122,207
107,107,High load dry climate grass GR7,GR7,172,102,237,192,201,170
108,108,High load very coarse humid climate grass GR8,GR8,112,12,242,188,231,127
109,109,Very high load humid climate grass GR9,GR9,80,10,200,180,220,105
121,121,Low load dry climate grass-shrub GS1,GS1,196,189,151,35,70,174
122,122,Moderate load dry climate grass-shrub GS2,GS2,137,112,68,27,86,103
123,123,Moderate load humid climate grass-shrub GS3,GS3,196,189,151,35,70,174
124,124,High load humid climate grass-shrub GS4,GS4,251,190,185,3,227,218
141,141,Low load dry climate shrub SH1,SH1,150,100,50,25,128,100
142,142,Moderate load dry climate shrub SH2,SH2,247,104,161,272,229,176
143,143,Moderate load humid climate shrub SH3,SH3,174,1,126,285,252,88
144,144,Low load humid climate timber-shrub SH4,SH4,255,255,190,42,255,223
145,145,High load dry climate shrub SH5,SH5,230,230,0,42,255,115
146,146,Low load humid climate shrub SH6,SH6,255,211,127,28,255,191
147,147,Very high load dry climate shrub SH7,SH7,255,170,0,28,255,128
148,148,High load humid climate shrub SH8,SH8,255,211,127,28,255,191
149,149,Very high load humid climate shrub SH9,SH9,200,150,50,28,200,125
161,161,Low load dry climate timber-grass-shrub TU1,TU1,200,120,80,15,150,140
162,162,Moderate load humid climate timber-shrub TU2,TU2,180,140,100,20,100,140
163,163,Moderate load humid climate timber-grass-shrub TU3,TU3,160,120,80,15,100,120
164,164,Dwarf conifer with understory TU4,TU4,140,100,60,15,133,100
165,165,Very high load dry climate timber-shrub TU5,TU5,120,80,40,15,128,80
181,181,Low load compact conifer litter TL1,TL1,100,80,50,20,100,75
182,182,Low load broadleaf litter TL2,TL2,120,100,60,20,100,90
183,183,Moderate load conifer litter TL3,TL3,90,70,40,20,128,65
184,184,Small downed logs TL4,TL4,80,60,30,20,167,55
185,185,High load conifer litter TL5,TL5,110,90,50,20,120,80
186,186,Moderate load broadleaf litter TL6,TL6,130,110,70,20,86,100
187,187,Large downed logs TL7,TL7,70,50,20,20,175,45
188,188,Long-needle litter TL8,TL8,140,120,80,20,75,110
189,189,Very high load broadleaf litter TL9,TL9,150,130,90,20,67,120
201,201,Low load activity fuel SB1,SB1,200,150,100,20,100,150
202,202,Moderate load activity fuel or low load blowdown SB2,SB2,180,130,80,15,125,130
203,203,High load activity fuel or moderate load blowdown SB3,SB3,160,110,60,15,167,110
204,204,High load blowdown SB4,SB4,140,90,40,15,175,90"""

# Standard Canadian FBP fuel type lookup
FBP_LOOKUP = """grid_value, export_value, descriptive_name, fuel_type, r, g, b, h, s, l
1,1,Spruce-Lichen Woodland,C-1,209,255,115,57,255,185
2,2,Boreal Spruce,C-2,34,102,51,95,128,68
3,3,Mature Jack or Lodgepole Pine,C-3,131,199,149,96,96,165
4,4,Immature Jack or Lodgepole Pine,C-4,112,168,0,57,255,84
5,5,Red and White Pine,C-5,223,184,230,206,122,207
6,6,Conifer Plantation,C-6,172,102,237,192,201,170
7,7,Ponderosa Pine Douglas-Fir,C-7,112,12,242,188,231,127
11,11,Leafless Aspen,D-1,196,189,151,35,70,174
12,12,Green Aspen with BUI Thresholding,D-2,137,112,68,27,86,103
13,13,Boreal Mixedwood Leafless,M-1,196,189,151,35,70,174
14,14,Boreal Mixedwood Green,M-2,251,190,185,3,227,218
16,16,Matted Grass,O-1a,255,255,190,42,255,223
17,17,Standing Grass,O-1b,230,230,0,42,255,115
18,18,Jack or Lodgepole Pine Slash,S-1,255,211,127,28,255,191
19,19,White Spruce Balsam Slash,S-2,255,170,0,28,255,128
20,20,Coastal Cedar Hemlock Douglas-Fir Slash,S-3,255,211,127,28,255,191"""


# ── ASC raster utilities ────────────────────────────────────────────────────

def read_asc(filepath: str) -> tuple:
    """Read an ESRI ASCII grid file. Returns (header_dict, data_array)."""
    header = {}
    header_lines = 0
    with open(filepath, "r") as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) == 2 and parts[0].lower() in (
                "ncols", "nrows", "xllcorner", "yllcorner", "cellsize", "nodata_value"
            ):
                key = parts[0].lower()
                try:
                    header[key] = int(parts[1])
                except ValueError:
                    header[key] = float(parts[1])
                header_lines += 1
            else:
                break

    data = np.loadtxt(filepath, skiprows=header_lines)
    return header, data


def write_asc(filepath: str, header: dict, data: np.ndarray):
    """Write an ESRI ASCII grid file."""
    with open(filepath, "w") as f:
        f.write(f"ncols {header['ncols']}\n")
        f.write(f"nrows {header['nrows']}\n")
        f.write(f"xllcorner {header['xllcorner']}\n")
        f.write(f"yllcorner {header['yllcorner']}\n")
        f.write(f"cellsize {header['cellsize']}\n")
        f.write(f"NODATA_value {header.get('nodata_value', -9999)}\n")
        for row in data:
            f.write(" ".join(str(int(v)) if v == int(v) else f"{v:.4f}" for v in row) + "\n")


def compute_slope_aspect(elevation_path: str, output_dir: str) -> tuple:
    """
    Compute slope (degrees) and aspect (degrees, compass) from elevation raster.
    Returns paths to (slope.asc, saz.asc).
    """
    header, elev = read_asc(elevation_path)
    cellsize = header["cellsize"]
    nodata = header.get("nodata_value", -9999)

    nrows, ncols = elev.shape
    slope = np.full_like(elev, nodata, dtype=float)
    aspect = np.full_like(elev, nodata, dtype=float)

    for i in range(1, nrows - 1):
        for j in range(1, ncols - 1):
            if elev[i, j] == nodata:
                continue
            # Compute gradient using 3x3 kernel (Horn's method)
            dz_dx = (
                (elev[i-1, j+1] + 2*elev[i, j+1] + elev[i+1, j+1]) -
                (elev[i-1, j-1] + 2*elev[i, j-1] + elev[i+1, j-1])
            ) / (8 * cellsize)
            dz_dy = (
                (elev[i+1, j-1] + 2*elev[i+1, j] + elev[i+1, j+1]) -
                (elev[i-1, j-1] + 2*elev[i-1, j] + elev[i-1, j+1])
            ) / (8 * cellsize)

            slope_rad = np.arctan(np.sqrt(dz_dx**2 + dz_dy**2))
            slope[i, j] = np.degrees(slope_rad)

            if dz_dx == 0 and dz_dy == 0:
                aspect[i, j] = 0  # Flat
            else:
                asp_rad = np.arctan2(-dz_dy, dz_dx)
                asp_deg = np.degrees(asp_rad)
                # Convert from math convention to compass (north=0, clockwise)
                asp_compass = (90 - asp_deg) % 360
                aspect[i, j] = asp_compass

    slope_path = os.path.join(output_dir, "slope.asc")
    saz_path = os.path.join(output_dir, "saz.asc")
    write_asc(slope_path, header, slope)
    write_asc(saz_path, header, aspect)

    return slope_path, saz_path


# ── Main generation ─────────────────────────────────────────────────────────

def generate_lookup_table(
    model: str,
    output_dir: str,
    custom_fuels: str = None,
) -> dict:
    """
    Generate the appropriate fuel lookup table for Cell2Fire.

    Parameters
    ----------
    model : str
        Fire model: S, C, K, P
    output_dir : str
        Directory to write the lookup table.
    custom_fuels : str, optional
        Path to custom fuel table CSV to merge/replace defaults.

    Returns
    -------
    dict with keys: lookup_path, n_fuel_types, warnings
    """
    validate_inputs(model)
    os.makedirs(output_dir, exist_ok=True)

    if model in ("S", "K", "P"):
        lookup_name = "spain_lookup_table.csv"
        default_data = SB_LOOKUP
    elif model == "C":
        lookup_name = "fbp_lookup_table.csv"
        default_data = FBP_LOOKUP
    else:
        raise ValueError(f"Unknown model: {model}")

    lookup_path = os.path.join(output_dir, lookup_name)

    if custom_fuels:
        # Use custom fuel table, merging with defaults
        custom_df = pd.read_csv(custom_fuels)
        default_df = pd.read_csv(pd.io.common.StringIO(default_data))
        # Custom overrides default for matching grid_values
        merged = pd.concat([default_df, custom_df]).drop_duplicates(
            subset=["grid_value"], keep="last"
        ).sort_values("grid_value")
        merged.to_csv(lookup_path, index=False)
        n_types = len(merged)
    else:
        with open(lookup_path, "w") as f:
            f.write(default_data)
        n_types = len(default_data.strip().split("\n")) - 1

    warnings = validate_outputs(lookup_path)
    for w in warnings:
        print(w, file=sys.stderr)

    return {
        "lookup_path": lookup_path,
        "n_fuel_types": n_types,
        "warnings": warnings,
    }


# ── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Generate Cell2Fire fuel lookup tables")
    parser.add_argument("--model", required=True, choices=["S", "C", "K", "P"],
                        help="Fire model")
    parser.add_argument("--output-dir", required=True, help="Instance folder path")
    parser.add_argument("--custom-fuels", default=None,
                        help="Custom fuel table CSV to merge with defaults")
    parser.add_argument("--elevation", default=None,
                        help="Elevation ASC to compute slope/aspect from")

    args = parser.parse_args()

    result = generate_lookup_table(args.model, args.output_dir, args.custom_fuels)
    print(f"Generated {result['lookup_path']} with {result['n_fuel_types']} fuel types")

    if args.elevation:
        slope_path, saz_path = compute_slope_aspect(args.elevation, args.output_dir)
        print(f"Computed slope: {slope_path}")
        print(f"Computed aspect: {saz_path}")


if __name__ == "__main__":
    main()
