#!/usr/bin/env python3
"""
fertilizer_rate_lookup.py
=========================
Look up N, P2O5, and K2O fertilizer application rates from the NPKGRIDS v1.08
dataset for a specific crop at a given lat/lon, then split the total N into
RZWQM2 fertilizer application events.

Data source: NPKGRIDS v1.08 (global 0.05-degree gridded NPK rates)
    Zip file contains NetCDF files named ``NPKGRIDSv1.08_{crop_name}.nc``
    with variables Nrate, P2O5rate, K2Orate (kg/ha) and quality indicators
    Nqual, P2O5qual, K2Oqual.  Special value -1 = ocean / no data.

Inputs:
    lat               - latitude in decimal degrees (required)
    lon               - longitude in decimal degrees (required)
    crop_name         - crop name string (required)
    npkgrids_zip_path - path to NPKGRIDSv1.08_NC.zip
                        (default: /home/server/Crop_model_dataset/24616050/NPKGRIDSv1.08_NC.zip)
    split_strategy    - "single", "two_split", "three_split" (default: "two_split")

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
import io
import math

import numpy as np
import xarray as xr

# Allow imports from the same directory
sys.path.insert(0, os.path.dirname(__file__))
from crop_name_harmonizer import harmonize

# ---------------------------------------------------------------------------
# INPUTS
# ---------------------------------------------------------------------------
LAT = ""
LON = ""
CROP_NAME = ""
NPKGRIDS_ZIP_PATH = "/home/server/Crop_model_dataset/24616050/NPKGRIDSv1.08_NC.zip"
SPLIT_STRATEGY = "two_split"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_P2O5_TO_P = 0.436   # elemental P fraction in P2O5
_VALID_STRATEGIES = {"single", "two_split", "three_split"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_application(plant_ref=1, timing=1, offset_days=14, method=2,
                      no3_kg_ha=0.0, nh4_kg_ha=0.0, urea_kg_ha=0.0,
                      p_mass_kg_ha=0.0):
    """Build a single RZWQM2 fertilizer application dictionary."""
    return {
        "plant_ref": plant_ref,
        "timing": timing,
        "offset_days": offset_days,
        "method": method,
        "no3_kg_ha": round(no3_kg_ha, 2),
        "nh4_kg_ha": round(nh4_kg_ha, 2),
        "urea_kg_ha": round(urea_kg_ha, 2),
        "bmp_chem": 1,
        "bmp_method": 1,
        "split_min_days": 0,
        "split_starter_frac": 0.0,
        "split_max_n": 0.0,
        "p_mass_kg_ha": round(p_mass_kg_ha, 2),
    }


def _split_n(total_n, p_kg_ha, strategy):
    """
    Split total N (kg/ha) into RZWQM2 fertilizer application events.

    Parameters
    ----------
    total_n : float
        Total N rate in kg-N/ha.
    p_kg_ha : float
        Elemental P to attach to the first application.
    strategy : str
        One of "single", "two_split", "three_split".

    Returns
    -------
    list[dict]
        List of RZWQM2 fertilizer application dicts.
    """
    applications = []

    if strategy == "single":
        # 1 application: all N as NO3, preplant, 14 days before planting
        applications.append(_make_application(
            timing=1,
            offset_days=14,
            no3_kg_ha=total_n,
            p_mass_kg_ha=p_kg_ha,
        ))

    elif strategy == "two_split":
        # 2 applications:
        #   1) 1/3 as NH4, preplant (timing=1), offset=14 days before planting
        #   2) 2/3 as urea, postemergence (timing=3), offset=30 days after emergence
        n_first = total_n / 3.0
        n_second = total_n * 2.0 / 3.0
        applications.append(_make_application(
            timing=1,
            offset_days=14,
            nh4_kg_ha=n_first,
            p_mass_kg_ha=p_kg_ha,
        ))
        applications.append(_make_application(
            timing=3,
            offset_days=30,
            urea_kg_ha=n_second,
        ))

    elif strategy == "three_split":
        # 3 applications:
        #   1) 1/4 NH4 preplant (timing=1, offset=14)
        #   2) 1/2 urea postemergence (timing=3, offset=30)
        #   3) 1/4 urea postemergence (timing=3, offset=60)
        n_first = total_n / 4.0
        n_second = total_n / 2.0
        n_third = total_n / 4.0
        applications.append(_make_application(
            timing=1,
            offset_days=14,
            nh4_kg_ha=n_first,
            p_mass_kg_ha=p_kg_ha,
        ))
        applications.append(_make_application(
            timing=3,
            offset_days=30,
            urea_kg_ha=n_second,
        ))
        applications.append(_make_application(
            timing=3,
            offset_days=60,
            urea_kg_ha=n_third,
        ))

    return applications


# ---------------------------------------------------------------------------
# validate_inputs / process / validate_outputs / main
# ---------------------------------------------------------------------------

def validate_inputs(lat, lon, crop_name, npkgrids_zip_path, split_strategy):
    """Validate all inputs and return resolved parameters."""
    errors = []

    # --- lat / lon ---
    if lat == "" or lat is None:
        errors.append("LAT is required.")
    if lon == "" or lon is None:
        errors.append("LON is required.")

    lat_f, lon_f = None, None
    if lat != "" and lat is not None:
        try:
            lat_f = float(lat)
            if lat_f < -90 or lat_f > 90:
                errors.append(f"LAT={lat_f} out of range [-90, 90].")
        except (ValueError, TypeError):
            errors.append(f"LAT must be numeric, got: {lat}")

    if lon != "" and lon is not None:
        try:
            lon_f = float(lon)
            if lon_f < -180 or lon_f > 180:
                errors.append(f"LON={lon_f} out of range [-180, 180].")
        except (ValueError, TypeError):
            errors.append(f"LON must be numeric, got: {lon}")

    # --- crop_name ---
    if not crop_name:
        errors.append("CROP_NAME is required.")

    cropgrids_name = None
    if crop_name:
        try:
            harmonized = harmonize(crop_name)
            cropgrids_name = harmonized.cropgrids_name
        except ValueError as e:
            errors.append(str(e))

    # --- zip path ---
    if not npkgrids_zip_path:
        npkgrids_zip_path = NPKGRIDS_ZIP_PATH

    if not os.path.isfile(npkgrids_zip_path):
        errors.append(f"NPKGRIDS zip file not found: {npkgrids_zip_path}")

    # --- split strategy ---
    if not split_strategy:
        split_strategy = SPLIT_STRATEGY

    split_strategy = split_strategy.strip().lower()
    if split_strategy not in _VALID_STRATEGIES:
        errors.append(
            f"Invalid split_strategy: '{split_strategy}'. "
            f"Must be one of {sorted(_VALID_STRATEGIES)}."
        )

    if errors:
        return False, "; ".join(errors), None

    return True, "", {
        "lat": lat_f,
        "lon": lon_f,
        "crop_name": crop_name,
        "cropgrids_name": cropgrids_name,
        "npkgrids_zip_path": npkgrids_zip_path,
        "split_strategy": split_strategy,
    }


def process(args):
    """
    Read NPKGRIDS data for the resolved crop at the given location and build
    fertilizer application events.

    Returns (success, error_msg, result).
    """
    lat = args["lat"]
    lon = args["lon"]
    cropgrids_name = args["cropgrids_name"]
    zip_path = args["npkgrids_zip_path"]
    split_strategy = args["split_strategy"]

    nc_filename = f"NPKGRIDSv1.08_{cropgrids_name}.nc"

    try:
        # ------ read NetCDF from zip ------
        with zipfile.ZipFile(zip_path, "r") as zf:
            if nc_filename not in zf.namelist():
                return False, (
                    f"NetCDF file '{nc_filename}' not found in zip. "
                    f"Crop '{cropgrids_name}' may not be available in NPKGRIDS."
                ), None
            nc_bytes = zf.read(nc_filename)

        ds = xr.open_dataset(io.BytesIO(nc_bytes))

        # ------ sample at nearest pixel ------
        try:
            n_rate = float(ds["Nrate"].sel(lat=lat, lon=lon, method="nearest").values)
            p2o5_rate = float(ds["P2O5rate"].sel(lat=lat, lon=lon, method="nearest").values)
            k2o_rate = float(ds["K2Orate"].sel(lat=lat, lon=lon, method="nearest").values)
        except KeyError as e:
            return False, f"Expected variable not found in NetCDF: {e}", None

        # Quality indicators (optional, may not exist for all crops)
        n_qual = None
        try:
            n_qual = float(ds["Nqual"].sel(lat=lat, lon=lon, method="nearest").values)
        except (KeyError, Exception):
            pass

        ds.close()

        # ------ check for no-data ------
        if n_rate == -1 or math.isnan(n_rate):
            return False, (
                f"No NPKGRIDS data at lat={lat}, lon={lon} for crop '{cropgrids_name}' "
                f"(Nrate={n_rate}).  Location may be ocean or outside crop area."
            ), None

        if p2o5_rate == -1 or math.isnan(p2o5_rate):
            p2o5_rate = 0.0

        if k2o_rate == -1 or math.isnan(k2o_rate):
            k2o_rate = 0.0

        # ------ conversions ------
        p_kg_ha = p2o5_rate * _P2O5_TO_P

        # ------ split N into application events ------
        applications = _split_n(n_rate, p_kg_ha, split_strategy)

        result = {
            "n_rate_kg_ha": round(n_rate, 2),
            "p2o5_rate_kg_ha": round(p2o5_rate, 2),
            "k2o_rate_kg_ha": round(k2o_rate, 2),
            "p_rate_kg_ha": round(p_kg_ha, 2),
            "n_quality": n_qual,
            "source": "npkgrids_v1.08",
            "applications": applications,
        }

        return True, "", result

    except zipfile.BadZipFile:
        return False, f"Bad zip file: {zip_path}", None
    except Exception as e:
        return False, f"Processing error: {e}", None


def validate_outputs(result):
    """Verify critical fields in the output."""
    if not result:
        return False, "No result produced."

    if result.get("n_rate_kg_ha") is None:
        return False, "Missing n_rate_kg_ha in result."

    apps = result.get("applications")
    if not apps or not isinstance(apps, list):
        return False, "No fertilizer applications generated."

    # Verify total N across applications matches the rate (within rounding)
    total_applied = sum(
        a.get("no3_kg_ha", 0) + a.get("nh4_kg_ha", 0) + a.get("urea_kg_ha", 0)
        for a in apps
    )
    if abs(total_applied - result["n_rate_kg_ha"]) > 0.1:
        return False, (
            f"N balance mismatch: total applied={total_applied:.2f} vs "
            f"rate={result['n_rate_kg_ha']:.2f}"
        )

    return True, ""


def main():
    lat = sys.argv[1] if len(sys.argv) > 1 else LAT
    lon = sys.argv[2] if len(sys.argv) > 2 else LON
    crop_name = sys.argv[3] if len(sys.argv) > 3 else CROP_NAME
    npkgrids_zip_path = sys.argv[4] if len(sys.argv) > 4 else NPKGRIDS_ZIP_PATH
    split_strategy = sys.argv[5] if len(sys.argv) > 5 else SPLIT_STRATEGY

    valid, err, args = validate_inputs(
        lat, lon, crop_name, npkgrids_zip_path, split_strategy
    )
    if not valid:
        print(json.dumps({"status": "INPUT_ERROR", "message": err}))
        sys.exit(1)

    success, err, result = process(args)
    if not success:
        print(json.dumps({"status": "PROCESSING_ERROR", "message": err}))
        sys.exit(2)

    valid, err = validate_outputs(result)
    if not valid:
        print(json.dumps({"status": "OUTPUT_ERROR", "message": err}))
        sys.exit(3)

    print(json.dumps({
        "status": "SUCCESS",
        "result": result,
        "message": (
            f"NPKGRIDS lookup for '{args['cropgrids_name']}' at "
            f"({args['lat']}, {args['lon']}): "
            f"N={result['n_rate_kg_ha']} kg/ha, "
            f"P2O5={result['p2o5_rate_kg_ha']} kg/ha, "
            f"K2O={result['k2o_rate_kg_ha']} kg/ha. "
            f"{len(result['applications'])} fertilizer application(s) generated "
            f"({args['split_strategy']})."
        ),
    }))
    sys.exit(0)


if __name__ == "__main__":
    main()
