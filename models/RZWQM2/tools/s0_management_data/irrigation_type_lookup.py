#!/usr/bin/env python3
"""
irrigation_type_lookup.py
=========================
Determine whether a crop at a given lat/lon is predominantly irrigated or
rainfed, using SPAM 2020 V2r0 harvested-area data.  Optionally extracts
yield for validation.

Data source
-----------
SPAM 2020 V2r0 Global CSV zip files, each containing a subdirectory with
one CSV per technology aggregation:

    spam2020V2r0_global_harvested_area.csv.zip
        -> spam2020V2r0_global_harvested_area/spam2020V2r0_global_H_TA.csv  (all tech)
        -> spam2020V2r0_global_harvested_area/spam2020V2r0_global_H_TI.csv  (irrigated)
    spam2020V2r0_global_yield.csv.zip
        -> spam2020V2r0_global_yield/spam2020V2r0_global_Y_TA.csv           (all tech)

Inputs:
    lat                 - Latitude in decimal degrees (required)
    lon                 - Longitude in decimal degrees (required)
    crop_name           - Crop name string, resolved via crop_name_harmonizer (required)
    spam_csv_dir        - Path to Global_CSV/ directory (default provided)
    irrigated_threshold - Fraction threshold for "irrigated" classification (default 0.5)
    include_yield       - Whether to also look up yield (default True)

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

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Sibling import: crop_name_harmonizer lives in the same package directory.
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.dirname(__file__))
from crop_name_harmonizer import harmonize  # noqa: E402

# ---------------------------------------------------------------------------
# INPUTS  (module-level defaults; overridden by main() / callers)
# ---------------------------------------------------------------------------
LAT = ""
LON = ""
CROP_NAME = ""
SPAM_CSV_DIR = "/home/server/Crop_model_dataset/dataverse_files/Global_CSV"
IRRIGATED_THRESHOLD = "0.5"
INCLUDE_YIELD = "True"

# ---------------------------------------------------------------------------
# Default output returned when the crop has no SPAM code.
# ---------------------------------------------------------------------------
_DEFAULT_OUTPUT = {
    "is_irrigated": False,
    "irrigated_fraction": 0.0,
    "total_area_ha": 0.0,
    "irrigated_area_ha": 0.0,
    "yield_kg_ha": None,
    "spam_crop_code": None,
    "source": "spam_2020_v2r0",
}

# ---------------------------------------------------------------------------
# Module-level cache for loaded DataFrames.
# Keys are (zip_path, csv_inner_path, crop_col) tuples; values are DataFrames
# with columns ['x', 'y', <crop_col>].
# ---------------------------------------------------------------------------
_DF_CACHE: dict = {}

# ---------------------------------------------------------------------------
# Zip / CSV layout constants
# ---------------------------------------------------------------------------
_HA_ZIP_NAME = "spam2020V2r0_global_harvested_area.csv.zip"
_HA_SUBDIR = "spam2020V2r0_global_harvested_area"
_HA_TA_CSV = f"{_HA_SUBDIR}/spam2020V2r0_global_H_TA.csv"
_HA_TI_CSV = f"{_HA_SUBDIR}/spam2020V2r0_global_H_TI.csv"

_YIELD_ZIP_NAME = "spam2020V2r0_global_yield.csv.zip"
_YIELD_SUBDIR = "spam2020V2r0_global_yield"
_YIELD_TA_CSV = f"{_YIELD_SUBDIR}/spam2020V2r0_global_Y_TA.csv"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_spam_columns(zip_path: str, csv_inner_path: str,
                       crop_col: str) -> pd.DataFrame:
    """
    Read only the x, y, and *crop_col* columns from a CSV inside a zip file.
    Results are cached in the module-level ``_DF_CACHE`` dict so that
    repeated calls (e.g., for different lat/lon but the same crop) do not
    re-read the large file.

    Parameters
    ----------
    zip_path : str
        Absolute path to the zip archive.
    csv_inner_path : str
        Path of the CSV *inside* the zip (including subdirectory).
    crop_col : str
        Name of the crop column to keep (e.g. ``MAIZ_A``).

    Returns
    -------
    pd.DataFrame
        DataFrame with columns ``['x', 'y', crop_col]``.
    """
    cache_key = (zip_path, csv_inner_path, crop_col)
    if cache_key in _DF_CACHE:
        return _DF_CACHE[cache_key]

    with zipfile.ZipFile(zip_path, "r") as zf:
        with zf.open(csv_inner_path) as f:
            df = pd.read_csv(
                f,
                usecols=["x", "y", crop_col],
                encoding="utf-8-sig",
                dtype={"x": np.float64, "y": np.float64, crop_col: np.float64},
            )

    _DF_CACHE[cache_key] = df
    return df


def _find_nearest_iloc(df: pd.DataFrame, lon: float, lat: float) -> int:
    """Return the positional (iloc) index of the row closest to (lon, lat).

    Uses squared Euclidean distance on the x/y grid -- adequate for the
    ~10 km SPAM pixels.
    """
    dist = (df["x"].values - lon) ** 2 + (df["y"].values - lat) ** 2
    return int(np.argmin(dist))


def _lookup_value_at_pixel(df: pd.DataFrame, px: float, py: float,
                           crop_col: str) -> float:
    """Find the row in *df* whose (x, y) matches the pixel at (px, py)
    within half a pixel tolerance (~0.05 deg) and return the crop column
    value.  Returns 0.0 if no matching pixel exists (e.g. TI has fewer
    rows than TA because the pixel is entirely rainfed).
    """
    dist = (df["x"].values - px) ** 2 + (df["y"].values - py) ** 2
    idx = int(np.argmin(dist))
    # SPAM resolution is 5 arc-min ≈ 0.0833 deg; half-pixel ≈ 0.042 deg.
    # Use a generous tolerance of 0.01 deg squared (≈ 0.1 deg) to account
    # for floating-point representation.
    if dist[idx] > 0.01:
        return 0.0
    return float(df.iloc[idx][crop_col])


# ---------------------------------------------------------------------------
# validate_inputs
# ---------------------------------------------------------------------------

def validate_inputs(lat_raw, lon_raw, crop_name_raw, spam_csv_dir,
                    threshold_raw, include_yield_raw):
    """Validate and parse raw inputs.

    Returns
    -------
    (ok, error_message, parsed_args_dict)
    """
    errors = []

    # -- lat --
    lat = None
    try:
        lat = float(lat_raw) if lat_raw not in (None, "") else None
        if lat is None:
            errors.append("LAT is required.")
        elif not -90 <= lat <= 90:
            errors.append(f"LAT={lat} outside [-90, 90].")
    except (ValueError, TypeError):
        errors.append(f"LAT must be numeric, got: {lat_raw}")

    # -- lon --
    lon = None
    try:
        lon = float(lon_raw) if lon_raw not in (None, "") else None
        if lon is None:
            errors.append("LON is required.")
        elif not -180 <= lon <= 180:
            errors.append(f"LON={lon} outside [-180, 180].")
    except (ValueError, TypeError):
        errors.append(f"LON must be numeric, got: {lon_raw}")

    # -- crop_name --
    crop_name = None
    spam_code = None
    if not crop_name_raw or str(crop_name_raw).strip() == "":
        errors.append("CROP_NAME is required.")
    else:
        crop_name = str(crop_name_raw).strip()
        try:
            crop_info = harmonize(crop_name)
            spam_code = crop_info.spam_code  # may be None for some crops
        except ValueError as exc:
            errors.append(str(exc))

    # -- spam_csv_dir --
    if not spam_csv_dir:
        spam_csv_dir = SPAM_CSV_DIR
    if not os.path.isdir(spam_csv_dir):
        errors.append(f"SPAM_CSV_DIR does not exist: {spam_csv_dir}")

    # -- irrigated_threshold --
    threshold = 0.5
    try:
        threshold = float(threshold_raw) if threshold_raw not in (None, "") else 0.5
        if not 0.0 <= threshold <= 1.0:
            errors.append(f"IRRIGATED_THRESHOLD={threshold} outside [0, 1].")
    except (ValueError, TypeError):
        errors.append(f"IRRIGATED_THRESHOLD must be numeric, got: {threshold_raw}")

    # -- include_yield --
    if isinstance(include_yield_raw, bool):
        include_yield = include_yield_raw
    elif isinstance(include_yield_raw, str):
        include_yield = include_yield_raw.strip().lower() not in ("false", "0", "no", "")
    else:
        include_yield = True

    if errors:
        return False, "; ".join(errors), None

    return True, "", {
        "lat": lat,
        "lon": lon,
        "crop_name": crop_name,
        "spam_code": spam_code,
        "spam_csv_dir": spam_csv_dir,
        "threshold": threshold,
        "include_yield": include_yield,
    }


# ---------------------------------------------------------------------------
# process
# ---------------------------------------------------------------------------

def process(args):
    """Look up irrigation type (and optionally yield) from SPAM data.

    Returns
    -------
    (success, error_message, result_dict)
    """
    lat = args["lat"]
    lon = args["lon"]
    spam_code = args["spam_code"]
    spam_csv_dir = args["spam_csv_dir"]
    threshold = args["threshold"]
    include_yield = args["include_yield"]

    # If the crop has no SPAM code, return defaults immediately.
    if spam_code is None:
        return True, "", dict(_DEFAULT_OUTPUT)

    try:
        ha_zip = os.path.join(spam_csv_dir, _HA_ZIP_NAME)
        if not os.path.isfile(ha_zip):
            return False, f"Harvested-area zip not found: {ha_zip}", None

        # Determine the technology suffixes for the crop columns.
        # H_TA.csv uses suffix _A; H_TI.csv uses suffix _I.
        crop_col_a = f"{spam_code}_A"
        crop_col_i = f"{spam_code}_I"

        # --- Load TA (all technologies) ---
        df_ta = _load_spam_columns(ha_zip, _HA_TA_CSV, crop_col_a)

        # --- Find nearest pixel in TA (the most complete grid) ---
        idx_ta = _find_nearest_iloc(df_ta, lon, lat)
        total_area = float(df_ta.iloc[idx_ta][crop_col_a])
        # Remember the pixel coordinates for cross-referencing TI/yield.
        px = float(df_ta.iloc[idx_ta]["x"])
        py = float(df_ta.iloc[idx_ta]["y"])

        # --- Load TI (irrigated) ---
        # The TI CSV contains only pixels with non-zero irrigated area
        # (~173 K rows vs ~962 K for TA), so we look up the same
        # physical pixel by its (x, y) coordinates.
        df_ti = _load_spam_columns(ha_zip, _HA_TI_CSV, crop_col_i)
        irrigated_area = _lookup_value_at_pixel(df_ti, px, py, crop_col_i)

        # --- Compute fraction and classification ---
        if total_area > 0:
            irrigated_fraction = irrigated_area / total_area
        else:
            irrigated_fraction = 0.0

        is_irrigated = irrigated_fraction >= threshold

        # --- Yield (optional) ---
        yield_kg_ha = None
        if include_yield:
            yield_zip = os.path.join(spam_csv_dir, _YIELD_ZIP_NAME)
            if os.path.isfile(yield_zip):
                # Yield CSV uses the _A suffix (all-tech aggregate).
                df_yield = _load_spam_columns(yield_zip, _YIELD_TA_CSV, crop_col_a)
                idx_y = _find_nearest_iloc(df_yield, lon, lat)
                yield_kg_ha = float(df_yield.iloc[idx_y][crop_col_a])
            # If yield zip is missing we silently leave yield as None.

        result = {
            "is_irrigated": bool(is_irrigated),
            "irrigated_fraction": round(irrigated_fraction, 4),
            "total_area_ha": round(total_area, 2),
            "irrigated_area_ha": round(irrigated_area, 2),
            "yield_kg_ha": round(yield_kg_ha, 2) if yield_kg_ha is not None else None,
            "spam_crop_code": spam_code,
            "source": "spam_2020_v2r0",
        }

        return True, "", result

    except Exception as exc:
        return False, f"Processing error: {exc}", None


# ---------------------------------------------------------------------------
# validate_outputs
# ---------------------------------------------------------------------------

def validate_outputs(result):
    """Sanity-check the output dictionary.

    Returns
    -------
    (ok, error_message)
    """
    if result is None:
        return False, "Result is None."

    frac = result.get("irrigated_fraction")
    if frac is not None and not (0.0 <= frac <= 1.0):
        return False, f"irrigated_fraction={frac} outside [0, 1]."

    total = result.get("total_area_ha")
    if total is not None and total < 0:
        return False, f"total_area_ha={total} is negative."

    irr = result.get("irrigated_area_ha")
    if irr is not None and irr < 0:
        return False, f"irrigated_area_ha={irr} is negative."

    y = result.get("yield_kg_ha")
    if y is not None and y < 0:
        return False, f"yield_kg_ha={y} is negative."

    return True, ""


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    """CLI entry point.

    Usage:
        python irrigation_type_lookup.py <lat> <lon> <crop_name> \
            [spam_csv_dir] [irrigated_threshold] [include_yield]
    """
    lat_raw = sys.argv[1] if len(sys.argv) > 1 else LAT
    lon_raw = sys.argv[2] if len(sys.argv) > 2 else LON
    crop_name_raw = sys.argv[3] if len(sys.argv) > 3 else CROP_NAME
    spam_csv_dir = sys.argv[4] if len(sys.argv) > 4 else SPAM_CSV_DIR
    threshold_raw = sys.argv[5] if len(sys.argv) > 5 else IRRIGATED_THRESHOLD
    include_yield_raw = sys.argv[6] if len(sys.argv) > 6 else INCLUDE_YIELD

    # -- Validate --
    valid, err, args = validate_inputs(
        lat_raw, lon_raw, crop_name_raw, spam_csv_dir,
        threshold_raw, include_yield_raw,
    )
    if not valid:
        print(json.dumps({"status": "INPUT_ERROR", "message": err}))
        sys.exit(1)

    # -- Process --
    success, err, result = process(args)
    if not success:
        print(json.dumps({"status": "PROCESSING_ERROR", "message": err}))
        sys.exit(2)

    # -- Validate outputs --
    valid, err = validate_outputs(result)
    if not valid:
        print(json.dumps({"status": "OUTPUT_ERROR", "message": err}))
        sys.exit(3)

    # -- Success --
    irr_label = "irrigated" if result["is_irrigated"] else "rainfed"
    frac_pct = result["irrigated_fraction"] * 100
    msg = (
        f"Crop '{args['crop_name']}' at ({args['lat']}, {args['lon']}) is "
        f"classified as {irr_label} ({frac_pct:.1f}% irrigated area)."
    )
    if result.get("yield_kg_ha") is not None:
        msg += f" Yield: {result['yield_kg_ha']} kg/ha."

    print(json.dumps({"status": "SUCCESS", "result": result, "message": msg}))
    sys.exit(0)


if __name__ == "__main__":
    main()
