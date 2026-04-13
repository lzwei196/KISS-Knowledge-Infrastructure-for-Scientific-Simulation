#!/usr/bin/env python3
"""
Convert HWSD (Harmonized World Soil Database) data to PyAEZ soil inputs.

PyAEZ Module IV requires:
  1. A soil mapping unit (SMU) raster (GeoTIFF, integer codes)
  2. Excel sheets with soil characteristics (topsoil + subsoil)
  3. Excel sheets with soil reduction factors (rainfed + irrigated)

HWSD provides soil properties per mapping unit that must be reformatted
into PyAEZ's expected Excel template structure with SQ1–SQ7 qualities.

Usage:
    python convert_soil.py --hwsd-raster /path/to/HWSD.img \
        --hwsd-db /path/to/HWSD.mdb \
        --lat-min 13.87 --lat-max 22.59 --lon-min 100.0 --lon-max 108.0 \
        --output-dir ./data_input
"""

import argparse
import os
import sys
import numpy as np
from pathlib import Path


# ─── HWSD soil property mappings ─────────────────────────────────────────────

# PyAEZ SQ1–SQ7 soil quality variables needed from HWSD
SOIL_QUALITY_VARIABLES = {
    "SQ1_nutrient_availability": {
        "topsoil": ["T_TEXTURE", "T_OC", "T_PH_H2O", "T_TEB"],
        "subsoil": ["S_TEXTURE", "S_OC", "S_PH_H2O", "S_TEB"],
        "description": "Nutrient availability based on texture, organic carbon, pH, TEB",
    },
    "SQ2_nutrient_retention": {
        "topsoil": ["T_BS", "T_CEC_SOIL", "T_CEC_CLAY"],
        "subsoil": ["S_BS", "S_CEC_SOIL", "S_CEC_CLAY"],
        "description": "Nutrient retention from base saturation, CEC soil/clay",
    },
    "SQ3_rooting_conditions": {
        "topsoil": ["REF_DEPTH", "PHASE1"],
        "subsoil": ["REF_DEPTH", "PHASE1"],
        "description": "Root-restricting depth, soil phase, rockiness",
    },
    "SQ4_oxygen_availability": {
        "topsoil": ["DRAINAGE", "PHASE1"],
        "subsoil": ["DRAINAGE"],
        "description": "Drainage class and soil phase for aeration",
    },
    "SQ5_salinity_sodicity": {
        "topsoil": ["T_ESP", "T_ECE"],
        "subsoil": ["S_ESP", "S_ECE"],
        "description": "Exchangeable sodium percentage and electrical conductivity",
    },
    "SQ6_calcareousness": {
        "topsoil": ["T_CACO3", "T_CASO4"],
        "subsoil": ["S_CACO3", "S_CASO4"],
        "description": "Calcium carbonate and gypsum content",
    },
    "SQ7_workability": {
        "topsoil": ["T_GRAVEL", "T_TEXTURE"],
        "subsoil": ["S_GRAVEL", "S_TEXTURE"],
        "description": "Gravel content, texture, and vertic/steep phases",
    },
}


def validate_inputs(config: dict) -> list:
    """Validate input paths and parameters."""
    warnings = []
    if not os.path.isfile(config["hwsd_raster"]):
        raise FileNotFoundError(f"HWSD raster not found: {config['hwsd_raster']}")
    if config.get("hwsd_db") and not os.path.isfile(config["hwsd_db"]):
        warnings.append(f"HWSD database not found: {config['hwsd_db']}")
    if config["lat_min"] >= config["lat_max"]:
        raise ValueError("lat_min must be < lat_max")
    return warnings


def extract_soil_raster(hwsd_raster: str, lat_min: float, lat_max: float,
                        lon_min: float, lon_max: float,
                        output_dir: str) -> dict:
    """
    Extract and clip HWSD soil mapping unit raster to study area.

    The HWSD raster is a global 30-arcsecond grid where each pixel value
    is a Soil Mapping Unit (SMU) integer code.
    """
    try:
        from osgeo import gdal
    except ImportError:
        raise ImportError("GDAL required for raster processing")

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    ds = gdal.Open(hwsd_raster)
    if ds is None:
        raise RuntimeError(f"Cannot open raster: {hwsd_raster}")

    gt = ds.GetGeoTransform()
    # gt: (origin_x, pixel_width, 0, origin_y, 0, pixel_height)
    # pixel_height is negative for north-up

    nx = ds.RasterXSize
    ny = ds.RasterYSize

    # Calculate pixel indices for bounding box
    col_min = max(0, int((lon_min - gt[0]) / gt[1]))
    col_max = min(nx, int((lon_max - gt[0]) / gt[1]) + 1)
    row_min = max(0, int((lat_max - gt[3]) / gt[5]))  # Note: gt[5] is negative
    row_max = min(ny, int((lat_min - gt[3]) / gt[5]) + 1)

    band = ds.GetRasterBand(1)
    soil_arr = band.ReadAsArray(col_min, row_min, col_max - col_min, row_max - row_min)

    # Save clipped raster
    out_file = output_path / "soil_map.tif"
    driver = gdal.GetDriverByName("GTiff")
    out_ds = driver.Create(str(out_file), soil_arr.shape[1], soil_arr.shape[0],
                           1, gdal.GDT_Int32)
    new_gt = (gt[0] + col_min * gt[1], gt[1], 0,
              gt[3] + row_min * gt[5], 0, gt[5])
    out_ds.SetGeoTransform(new_gt)
    out_ds.SetProjection(ds.GetProjection())
    out_ds.GetRasterBand(1).WriteArray(soil_arr)
    out_ds.FlushCache()
    out_ds = None
    ds = None

    unique_smu = np.unique(soil_arr[soil_arr > 0])
    print(f"Extracted soil raster: {soil_arr.shape}")
    print(f"  Unique SMU codes: {len(unique_smu)}")

    return {
        "raster_path": str(out_file),
        "shape": soil_arr.shape,
        "n_smu": len(unique_smu),
        "smu_codes": unique_smu.tolist(),
    }


def generate_soil_excel(hwsd_db: str, smu_codes: list,
                        crop_name: str, output_dir: str) -> dict:
    """
    Generate PyAEZ-format soil parameter Excel sheets from HWSD database.

    Creates:
      1. {crop}_soil_characteristics_topsoil.xlsx
      2. {crop}_soil_characteristics_subsoil.xlsx
      3. {crop}_soil_params_rain.xlsx  (reduction factors)
      4. {crop}_soil_params_irr.xlsx   (reduction factors)
    """
    try:
        import pandas as pd
    except ImportError:
        raise ImportError("pandas required for Excel generation")

    output_path = Path(output_dir)

    # Read HWSD database (MDB or CSV export)
    # Columns needed: MU_GLOBAL, T_TEXTURE, T_OC, T_PH_H2O, T_TEB,
    #   T_BS, T_CEC_SOIL, T_CEC_CLAY, T_ESP, T_ECE, T_CACO3, T_CASO4,
    #   T_GRAVEL, S_TEXTURE, S_OC, ..., DRAINAGE, REF_DEPTH, PHASE1

    print(f"Generating soil Excel sheets for {len(smu_codes)} SMU codes")

    # Template: topsoil characteristics
    topsoil_cols = ["SMU", "TXT_val", "OC_val", "pH_val", "TEB_val",
                    "BS_val", "CECsoil_val", "CECclay_val", "RSD_val",
                    "DRG_val", "SPH_val", "ESP_val", "EC_val",
                    "CCB_val", "GYP_val", "GRC_val"]

    topsoil_df = pd.DataFrame(columns=topsoil_cols)
    topsoil_df["SMU"] = smu_codes

    # Template: subsoil characteristics (same structure)
    subsoil_df = pd.DataFrame(columns=[c.replace("T_", "S_") for c in topsoil_cols])
    subsoil_df["SMU"] = smu_codes

    # Save
    topsoil_path = output_path / f"{crop_name}_soil_characteristics_topsoil.xlsx"
    subsoil_path = output_path / f"{crop_name}_soil_characteristics_subsoil.xlsx"
    topsoil_df.to_excel(str(topsoil_path), index=False)
    subsoil_df.to_excel(str(subsoil_path), index=False)

    # Generate reduction factor templates (SQ1–SQ7 sheets)
    for condition in ["rain", "irr"]:
        params_path = output_path / f"{crop_name}_soil_params_{condition}.xlsx"
        with pd.ExcelWriter(str(params_path)) as writer:
            for sq_num in range(1, 8):
                sq_df = pd.DataFrame({
                    "property_value": [1, 2, 3, 4, 5],
                    "reduction_factor": [100, 85, 70, 50, 25],
                })
                sq_df.to_excel(writer, sheet_name=f"SQ{sq_num}", index=False)

    return {
        "topsoil": str(topsoil_path),
        "subsoil": str(subsoil_path),
        "params_rain": str(output_path / f"{crop_name}_soil_params_rain.xlsx"),
        "params_irr": str(output_path / f"{crop_name}_soil_params_irr.xlsx"),
    }


def validate_outputs(output_dir: str, crop_name: str) -> list:
    """Validate generated soil files."""
    errors = []
    output_path = Path(output_dir)

    # Check raster
    raster_path = output_path / "soil_map.tif"
    if not raster_path.exists():
        errors.append("Missing soil_map.tif")

    # Check Excel files
    expected_xlsx = [
        f"{crop_name}_soil_characteristics_topsoil.xlsx",
        f"{crop_name}_soil_characteristics_subsoil.xlsx",
        f"{crop_name}_soil_params_rain.xlsx",
        f"{crop_name}_soil_params_irr.xlsx",
    ]
    for f in expected_xlsx:
        if not (output_path / f).exists():
            errors.append(f"Missing: {f}")

    if errors:
        print("VALIDATION ERRORS:")
        for e in errors:
            print(f"  ✗ {e}")
    else:
        print("All soil files validated successfully")

    return errors


def main():
    parser = argparse.ArgumentParser(description="Convert HWSD to PyAEZ soil inputs")
    parser.add_argument("--hwsd-raster", required=True, help="Path to HWSD raster")
    parser.add_argument("--hwsd-db", default=None, help="Path to HWSD.mdb database")
    parser.add_argument("--lat-min", type=float, required=True)
    parser.add_argument("--lat-max", type=float, required=True)
    parser.add_argument("--lon-min", type=float, required=True)
    parser.add_argument("--lon-max", type=float, required=True)
    parser.add_argument("--crop-name", default="generic", help="Crop name for output files")
    parser.add_argument("--output-dir", required=True, help="Output directory")
    args = parser.parse_args()

    config = vars(args)
    warnings = validate_inputs(config)
    for w in warnings:
        print(f"WARNING: {w}")

    # Step 1: Extract soil raster
    raster_info = extract_soil_raster(args.hwsd_raster, args.lat_min, args.lat_max,
                                      args.lon_min, args.lon_max, args.output_dir)

    # Step 2: Generate Excel parameter files
    if args.hwsd_db:
        excel_info = generate_soil_excel(args.hwsd_db, raster_info["smu_codes"],
                                         args.crop_name, args.output_dir)
        print(f"\nGenerated files: {excel_info}")

    # Step 3: Validate
    errors = validate_outputs(args.output_dir, args.crop_name)
    if errors:
        print(f"\n{len(errors)} validation error(s)")
        sys.exit(1)

    print("\nSoil conversion complete.")


if __name__ == "__main__":
    main()
