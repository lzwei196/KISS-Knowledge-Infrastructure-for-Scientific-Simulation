#!/usr/bin/env python3
"""
crop_area_lookup.py
===================
Look up the dominant crop at a given lat/lon pixel using the CROPGRIDS v1.08
dataset (0.05-degree global harvested-area maps).

Data source
-----------
Zip file containing NetCDF maps named ``CROPGRIDSv1.08_{crop_name}.nc``.
Each file has a ``harvarea`` variable (hectares; -1 = ocean/water).

Only crops that have DSSAT mappings (via ``crop_name_harmonizer``) are scanned
(roughly 30 crops out of 173), because those are the only ones the modelling
pipeline can actually simulate.

Inputs:
    lat                - Latitude in decimal degrees  (required)
    lon                - Longitude in decimal degrees  (required)
    cropgrids_zip_path - Path to CROPGRIDSv1.08_NC_maps.zip
                         (default: KISSPATH_HOME/Crop_model_dataset/22491997/CROPGRIDSv1.08_NC_maps.zip)
    top_n              - Number of top crops to return (default: 5)

Exit codes:
    0 - Success
    1 - Input validation error
    2 - Processing error
    3 - Output validation error
"""

import sys
import os
import json
import zipfile
from io import BytesIO

import xarray as xr
import numpy as np

# Resolve import of crop_name_harmonizer from the same package directory
sys.path.insert(0, os.path.dirname(__file__))
from crop_name_harmonizer import _CROP_TABLE, harmonize  # noqa: E402

# ---------------------------------------------------------------------------
# DEFAULT INPUTS
# ---------------------------------------------------------------------------
LAT = ""
LON = ""
CROPGRIDS_ZIP_PATH = "KISSPATH_HOME/Crop_model_dataset/22491997/CROPGRIDSv1.08_NC_maps.zip"
TOP_N = "5"


def _get_unique_cropgrids_names():
    """
    Return a dict mapping unique cropgrids file-name fragments to a list of
    canonical crop names that share that fragment.

    E.g. ``{'wheat': ['wheat', 'winter_wheat'], 'maize': ['maize'], ...}``
    """
    cg_to_canonical = {}
    for canonical, entry in _CROP_TABLE.items():
        cropgrids_name = entry[1]  # index 1 is cropgrids_name
        cg_to_canonical.setdefault(cropgrids_name, []).append(canonical)
    return cg_to_canonical


def validate_inputs(lat, lon, cropgrids_zip_path, top_n):
    """Validate and parse all inputs."""
    errors = []

    # --- lat ---
    if lat == "" or lat is None:
        errors.append("LAT is required.")
    else:
        try:
            lat = float(lat)
            if lat < -90.0 or lat > 90.0:
                errors.append(f"LAT must be between -90 and 90, got {lat}.")
        except (ValueError, TypeError):
            errors.append(f"LAT must be a number, got: {lat}")

    # --- lon ---
    if lon == "" or lon is None:
        errors.append("LON is required.")
    else:
        try:
            lon = float(lon)
            if lon < -180.0 or lon > 180.0:
                errors.append(f"LON must be between -180 and 180, got {lon}.")
        except (ValueError, TypeError):
            errors.append(f"LON must be a number, got: {lon}")

    # --- zip path ---
    if not cropgrids_zip_path:
        cropgrids_zip_path = CROPGRIDS_ZIP_PATH
    if not os.path.isfile(cropgrids_zip_path):
        errors.append(f"CROPGRIDS zip file not found: {cropgrids_zip_path}")

    # --- top_n ---
    try:
        top_n = int(top_n)
        if top_n < 1:
            errors.append(f"TOP_N must be >= 1, got {top_n}.")
    except (ValueError, TypeError):
        errors.append(f"TOP_N must be an integer, got: {top_n}")

    if errors:
        return False, "; ".join(errors), None

    return True, "", {
        "lat": float(lat),
        "lon": float(lon),
        "cropgrids_zip_path": cropgrids_zip_path,
        "top_n": int(top_n),
    }


def process(args):
    """
    Open the CROPGRIDS zip, read harvested area for each DSSAT-mapped crop
    at the requested pixel, and rank by area.

    Returns (success, error_msg, result).
    """
    lat = args["lat"]
    lon = args["lon"]
    cropgrids_zip_path = args["cropgrids_zip_path"]
    top_n = args["top_n"]

    try:
        cg_name_map = _get_unique_cropgrids_names()
        crop_areas = []  # list of (canonical_name, cropgrids_name, area_ha)
        pixel_lat = None
        pixel_lon = None

        with zipfile.ZipFile(cropgrids_zip_path, "r") as zf:
            for cropgrids_name, canonical_names in cg_name_map.items():
                # Construct expected path inside zip
                nc_filename = f"CROPGRIDSv1.08_NC_maps/CROPGRIDSv1.08_{cropgrids_name}.nc"

                # Check if the file exists in the archive
                if nc_filename not in zf.namelist():
                    continue

                # Read NetCDF from zip via BytesIO
                nc_bytes = zf.read(nc_filename)
                ds = xr.open_dataset(BytesIO(nc_bytes), engine="scipy")

                try:
                    # Sample the nearest pixel
                    point = ds["harvarea"].sel(
                        lat=lat, lon=lon, method="nearest"
                    )
                    area_val = float(point.values)

                    # Record the actual pixel coordinates (same for all crops
                    # on the same grid, but capture once)
                    if pixel_lat is None:
                        pixel_lat = float(point.coords["lat"].values)
                        pixel_lon = float(point.coords["lon"].values)

                    # Only keep valid positive areas
                    if not np.isnan(area_val) and area_val > 0:
                        # Associate area with the first canonical name for
                        # this cropgrids_name (they share the same physical
                        # area; we pick the primary canonical name)
                        crop_areas.append(
                            (canonical_names[0], cropgrids_name, area_val)
                        )
                finally:
                    ds.close()

        # Sort descending by area
        crop_areas.sort(key=lambda x: x[2], reverse=True)

        # Build result
        if not crop_areas:
            result = {
                "dominant_crop": None,
                "dominant_crop_area_ha": None,
                "top_crops": [],
                "pixel_lat": pixel_lat,
                "pixel_lon": pixel_lon,
                "source": "cropgrids_v1.08",
            }
        else:
            top_list = [
                {"crop": name, "area_ha": round(area, 2)}
                for name, _cg, area in crop_areas[:top_n]
            ]
            result = {
                "dominant_crop": crop_areas[0][0],
                "dominant_crop_area_ha": round(crop_areas[0][2], 2),
                "top_crops": top_list,
                "pixel_lat": pixel_lat,
                "pixel_lon": pixel_lon,
                "source": "cropgrids_v1.08",
            }

        return True, "", result

    except Exception as e:
        return False, f"Processing error: {e}", None


def validate_outputs(result):
    """Verify the result structure is well-formed."""
    if result is None:
        return False, "Result is None."
    if "top_crops" not in result:
        return False, "Missing 'top_crops' key in result."
    if "pixel_lat" not in result or "pixel_lon" not in result:
        return False, "Missing pixel coordinate keys in result."
    return True, ""


def main():
    lat = sys.argv[1] if len(sys.argv) > 1 else LAT
    lon = sys.argv[2] if len(sys.argv) > 2 else LON
    cropgrids_zip_path = sys.argv[3] if len(sys.argv) > 3 else CROPGRIDS_ZIP_PATH
    top_n = sys.argv[4] if len(sys.argv) > 4 else TOP_N

    # --- Step 1: validate inputs ---
    valid, err, args = validate_inputs(lat, lon, cropgrids_zip_path, top_n)
    if not valid:
        print(json.dumps({"status": "INPUT_ERROR", "message": err}))
        sys.exit(1)

    # --- Step 2: process ---
    success, err, result = process(args)
    if not success:
        print(json.dumps({"status": "PROCESSING_ERROR", "message": err}))
        sys.exit(2)

    # --- Step 3: validate outputs ---
    valid, err = validate_outputs(result)
    if not valid:
        print(json.dumps({"status": "OUTPUT_ERROR", "message": err}))
        sys.exit(3)

    # --- Step 4: report ---
    if result["dominant_crop"]:
        msg = (
            f"Dominant crop at ({result['pixel_lat']}, {result['pixel_lon']}): "
            f"{result['dominant_crop']} ({result['dominant_crop_area_ha']} ha). "
            f"{len(result['top_crops'])} crops returned."
        )
    else:
        msg = (
            f"No DSSAT-mapped crops found at pixel "
            f"({result['pixel_lat']}, {result['pixel_lon']})."
        )

    print(json.dumps({"status": "SUCCESS", "result": result, "message": msg}))
    sys.exit(0)


if __name__ == "__main__":
    main()
