#!/usr/bin/env python3
"""
crop_calendar_lookup.py
=======================
Look up planting and harvest dates (as day-of-year) for a given crop at a
given lat/lon, combining a global crop calendar (Sacks dataset, 0.5-degree
NetCDF) with a higher-resolution China Crop Phenology dataset (1 km GeoTIFF).

Data sources
------------
1. **Global Crop Calendar (Sacks)**
   - Directory: ALL_CROPS_netCDF_0.5deg_filled/
   - Files: gzipped NetCDF, e.g. ``Maize.crop.calendar.fill.nc.gz``
   - Grid: 0.5-degree global (360 x 720), latitude from 89.75 to -89.75,
     longitude from -179.75 to 179.75
   - Variables: ``plant`` (planting DOY midpoint), ``harvest`` (harvest DOY
     midpoint), ``tot.days`` (season length in days)

2. **China Override: China Crop Phenology (1 km)**
   - Directory: 8313530/
   - Files: GeoTIFF, ``CHN_{CropPrefix}_{Phase}_{Year}.tif``
   - CRS: ESRI:102025 (Asia North Albers Equal Area Conic)
   - Resolution: 1 km, grid 4335 x 4372
   - Nodata: -3.4028e+38 (float32) or 255 (uint8)

Inputs:
    lat                    - latitude in decimal degrees (required)
    lon                    - longitude in decimal degrees (required)
    crop_name              - crop name string (required)
    year                   - year for China phenology lookup (default: 2019)
    calendar_dir           - path to ALL_CROPS_netCDF_0.5deg_filled/
    china_pheno_dir        - path to 8313530/
    prefer_china_phenology - use China data when available (default: True)

Exit codes:
    0 - Success
    1 - Input validation error
    2 - Processing error
    3 - Output validation error
"""

import sys
import os
import json
import gzip
import math
import tempfile
import numpy as np

# Optional heavy dependencies -- fall back to global calendar if missing
try:
    import rasterio
    HAS_RASTERIO = True
except ImportError:
    HAS_RASTERIO = False

try:
    from pyproj import Transformer
    HAS_PYPROJ = True
except ImportError:
    HAS_PYPROJ = False

# Harmonizer lives in the same package
from crop_name_harmonizer import harmonize, CHINA_PHENOLOGY_PHASES

# ---------------------------------------------------------------------------
# INPUTS (module-level defaults, overridden by CLI args or direct call)
# ---------------------------------------------------------------------------
LAT = ""
LON = ""
CROP_NAME = ""
YEAR = "2019"
CALENDAR_DIR = "/home/server/Crop_model_dataset/ALL_CROPS_netCDF_0.5deg_filled"
CHINA_PHENO_DIR = "/home/server/Crop_model_dataset/8313530"
PREFER_CHINA_PHENOLOGY = "True"

# ---------------------------------------------------------------------------
# China bounding box (approximate geographic extent)
# ---------------------------------------------------------------------------
CHINA_LAT_MIN = 18.0
CHINA_LAT_MAX = 54.0
CHINA_LON_MIN = 73.0
CHINA_LON_MAX = 135.0

# ESRI:102025 -- Asia North Albers Equal Area Conic
_CHINA_CRS = "ESRI:102025"
_WGS84_CRS = "EPSG:4326"

# Nodata sentinel for the China phenology float32 GeoTIFFs
_CHINA_NODATA_FLOAT = -3.4028230607370965e+38


# ===================================================================
# validate_inputs
# ===================================================================
def validate_inputs(lat, lon, crop_name, year, calendar_dir,
                    china_pheno_dir, prefer_china_phenology):
    """Validate and normalise all inputs.

    Returns (ok, error_message, args_dict).
    """
    errors = []

    # --- lat / lon ---
    try:
        lat = float(lat)
    except (TypeError, ValueError):
        errors.append(f"lat must be a number, got: {lat!r}")
        lat = None
    if lat is not None and not (-90.0 <= lat <= 90.0):
        errors.append(f"lat out of range [-90, 90]: {lat}")

    try:
        lon = float(lon)
    except (TypeError, ValueError):
        errors.append(f"lon must be a number, got: {lon!r}")
        lon = None
    if lon is not None and not (-180.0 <= lon <= 180.0):
        errors.append(f"lon out of range [-180, 180]: {lon}")

    # --- crop_name ---
    if not crop_name:
        errors.append("crop_name is required.")
    else:
        try:
            crop_info = harmonize(crop_name)
        except ValueError as exc:
            errors.append(str(exc))
            crop_info = None

    # --- year ---
    try:
        year = int(year)
    except (TypeError, ValueError):
        errors.append(f"year must be an integer, got: {year!r}")
        year = 2019

    # --- directories ---
    if not calendar_dir:
        calendar_dir = CALENDAR_DIR
    if not os.path.isdir(calendar_dir):
        errors.append(f"calendar_dir does not exist: {calendar_dir}")

    if not china_pheno_dir:
        china_pheno_dir = CHINA_PHENO_DIR
    # china_pheno_dir is only required when we actually try China path; do
    # not treat a missing directory as a hard error here.

    # --- prefer_china_phenology ---
    if isinstance(prefer_china_phenology, str):
        prefer_china_phenology = prefer_china_phenology.strip().lower() in (
            "true", "1", "yes"
        )
    else:
        prefer_china_phenology = bool(prefer_china_phenology)

    if errors:
        return False, "; ".join(errors), None

    return True, "", {
        "lat": lat,
        "lon": lon,
        "crop_info": crop_info,
        "year": year,
        "calendar_dir": calendar_dir,
        "china_pheno_dir": china_pheno_dir,
        "prefer_china_phenology": prefer_china_phenology,
    }


# ===================================================================
# Internal helpers
# ===================================================================

def _read_global_calendar(calendar_dir, crop_calendar_file, lat, lon):
    """Read planting / harvest DOY from the Sacks global crop calendar.

    Returns (planting_doy, harvest_doy, season_length, source_file) or raises.
    """
    import xarray as xr

    nc_gz_path = os.path.join(calendar_dir, crop_calendar_file)
    if not os.path.isfile(nc_gz_path):
        raise FileNotFoundError(f"Crop calendar file not found: {nc_gz_path}")

    tmp_path = None
    try:
        # Decompress gzipped NetCDF into a temporary file
        with gzip.open(nc_gz_path, "rb") as gz_in:
            tmp_fd, tmp_path = tempfile.mkstemp(suffix=".nc")
            with os.fdopen(tmp_fd, "wb") as tmp_out:
                # Read in chunks to keep memory reasonable
                while True:
                    chunk = gz_in.read(1 << 20)  # 1 MiB
                    if not chunk:
                        break
                    tmp_out.write(chunk)

        ds = xr.open_dataset(tmp_path, decode_timedelta=False)

        # Select nearest grid cell
        plant_val = float(
            ds["plant"].sel(latitude=lat, longitude=lon, method="nearest").values
        )
        harvest_val = float(
            ds["harvest"].sel(latitude=lat, longitude=lon, method="nearest").values
        )
        tot_days_val = float(
            ds["tot.days"].sel(latitude=lat, longitude=lon, method="nearest").values
        )
        ds.close()

        if math.isnan(plant_val) or math.isnan(harvest_val):
            raise ValueError(
                f"No crop calendar data at lat={lat}, lon={lon} "
                f"in {crop_calendar_file}"
            )

        planting_doy = int(round(plant_val))
        harvest_doy = int(round(harvest_val))
        season_length = int(round(tot_days_val)) if not math.isnan(tot_days_val) else None

        # Compute season length if tot.days was NaN but we have both DOYs
        if season_length is None:
            if harvest_doy >= planting_doy:
                season_length = harvest_doy - planting_doy
            else:
                # Cross-year (winter crop)
                season_length = (365 - planting_doy) + harvest_doy

        return planting_doy, harvest_doy, season_length, nc_gz_path

    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _is_nodata(value, nodata):
    """Check whether a raster sample value is nodata.

    DOY values must be in [1, 366]; anything outside that range is treated
    as nodata.  Explicit nodata sentinels (255 for uint8, -3.4e38 for
    float32) are also caught.
    """
    if value is None:
        return True
    try:
        fval = float(value)
    except (TypeError, ValueError):
        return True
    if math.isnan(fval) or math.isinf(fval):
        return True
    # Check explicit nodata sentinel from the raster metadata
    if nodata is not None:
        try:
            if abs(fval - float(nodata)) < 1.0:
                return True
        except (TypeError, ValueError, OverflowError):
            pass
    # DOY must be in [1, 366]; anything else is invalid / nodata
    if fval < 1 or fval > 366:
        return True
    return False


def _sample_china_tif(tif_path, lat, lon):
    """Sample a single China Phenology GeoTIFF at the given WGS-84 lat/lon.

    Returns the pixel value (float) or None if nodata / out-of-bounds.
    """
    if not HAS_RASTERIO or not HAS_PYPROJ:
        return None

    if not os.path.isfile(tif_path):
        return None

    transformer = Transformer.from_crs(_WGS84_CRS, _CHINA_CRS, always_xy=True)
    x, y = transformer.transform(lon, lat)  # lon first for always_xy

    with rasterio.open(tif_path) as src:
        nodata = src.nodata
        # Check if projected point falls inside the raster bounds
        if not (src.bounds.left <= x <= src.bounds.right and
                src.bounds.bottom <= y <= src.bounds.top):
            return None

        row, col = src.index(x, y)
        # Bounds check on array indices
        if row < 0 or row >= src.height or col < 0 or col >= src.width:
            return None

        val = src.read(1)[row, col]
        if _is_nodata(val, nodata):
            return None
        return float(val)


def _read_china_phenology(china_pheno_dir, china_prefix, year, lat, lon):
    """Read planting and harvest DOY from the China Phenology GeoTIFFs.

    Returns (planting_doy, harvest_doy, season_length, source_file) or raises.
    """
    phases = CHINA_PHENOLOGY_PHASES.get(china_prefix)
    if phases is None:
        raise ValueError(f"No China phenology phase mapping for prefix: {china_prefix}")

    plant_phase = phases["planting"]
    harvest_phase = phases["harvest"]

    plant_file = f"CHN_{china_prefix}_{plant_phase}_{year}.tif"
    harvest_file = f"CHN_{china_prefix}_{harvest_phase}_{year}.tif"

    plant_path = os.path.join(china_pheno_dir, plant_file)
    harvest_path = os.path.join(china_pheno_dir, harvest_file)

    plant_val = _sample_china_tif(plant_path, lat, lon)
    if plant_val is None:
        raise ValueError(
            f"No China phenology planting data at lat={lat}, lon={lon} "
            f"(file: {plant_file})"
        )

    harvest_val = _sample_china_tif(harvest_path, lat, lon)
    if harvest_val is None:
        raise ValueError(
            f"No China phenology harvest data at lat={lat}, lon={lon} "
            f"(file: {harvest_file})"
        )

    planting_doy = int(round(plant_val))
    harvest_doy = int(round(harvest_val))

    # Season length
    if harvest_doy >= planting_doy:
        season_length = harvest_doy - planting_doy
    else:
        # Cross-year season (e.g. winter wheat)
        season_length = (365 - planting_doy) + harvest_doy

    source_file = f"{plant_path}; {harvest_path}"
    return planting_doy, harvest_doy, season_length, source_file


# ===================================================================
# process
# ===================================================================
def process(args):
    """Main processing: decide source, read data, return result dict.

    Returns (success, error_message, result_dict).
    """
    lat = args["lat"]
    lon = args["lon"]
    crop_info = args["crop_info"]
    year = args["year"]
    calendar_dir = args["calendar_dir"]
    china_pheno_dir = args["china_pheno_dir"]
    prefer_china = args["prefer_china_phenology"]

    china_prefix = crop_info.china_pheno_prefix
    crop_calendar_file = crop_info.crop_calendar_file

    try:
        # ------------------------------------------------------------------
        # Attempt China Phenology path
        # ------------------------------------------------------------------
        used_china = False
        if (prefer_china
                and HAS_RASTERIO
                and HAS_PYPROJ
                and china_prefix is not None
                and CHINA_LAT_MIN <= lat <= CHINA_LAT_MAX
                and CHINA_LON_MIN <= lon <= CHINA_LON_MAX):
            try:
                planting_doy, harvest_doy, season_length, source_file = (
                    _read_china_phenology(china_pheno_dir, china_prefix,
                                          year, lat, lon)
                )
                used_china = True
            except (ValueError, FileNotFoundError, OSError) as exc:
                # Fall back to global calendar
                used_china = False

        # ------------------------------------------------------------------
        # Global Crop Calendar path (primary or fallback)
        # ------------------------------------------------------------------
        if not used_china:
            if crop_calendar_file is None:
                return False, (
                    f"No global crop calendar file mapped for crop "
                    f"'{crop_info.canonical_name}'. Cannot determine calendar."
                ), None
            planting_doy, harvest_doy, season_length, source_file = (
                _read_global_calendar(calendar_dir, crop_calendar_file,
                                      lat, lon)
            )

        source = "china_phenology" if used_china else "global_crop_calendar"

        result = {
            "planting_doy": planting_doy,
            "harvest_doy": harvest_doy,
            "season_length_days": season_length,
            "source": source,
            "source_file": source_file,
            "crop_name": crop_info.canonical_name,
        }
        return True, "", result

    except Exception as exc:
        return False, f"Processing error: {exc}", None


# ===================================================================
# validate_outputs
# ===================================================================
def validate_outputs(result):
    """Validate the result dictionary.

    Returns (ok, error_message).
    """
    if not result:
        return False, "No result produced."

    planting = result.get("planting_doy")
    harvest = result.get("harvest_doy")
    season = result.get("season_length_days")

    if planting is None or harvest is None:
        return False, "planting_doy and harvest_doy must be present."

    if not (1 <= planting <= 366):
        return False, f"planting_doy out of range [1, 366]: {planting}"
    if not (1 <= harvest <= 366):
        return False, f"harvest_doy out of range [1, 366]: {harvest}"

    if season is not None and season < 0:
        return False, f"season_length_days is negative: {season}"

    return True, ""


# ===================================================================
# main
# ===================================================================
def main():
    """CLI entry point -- follows validate_inputs / process / validate_outputs
    pattern."""
    lat = sys.argv[1] if len(sys.argv) > 1 else LAT
    lon = sys.argv[2] if len(sys.argv) > 2 else LON
    crop_name = sys.argv[3] if len(sys.argv) > 3 else CROP_NAME
    year = sys.argv[4] if len(sys.argv) > 4 else YEAR
    calendar_dir = sys.argv[5] if len(sys.argv) > 5 else CALENDAR_DIR
    china_pheno_dir = sys.argv[6] if len(sys.argv) > 6 else CHINA_PHENO_DIR
    prefer_china = sys.argv[7] if len(sys.argv) > 7 else PREFER_CHINA_PHENOLOGY

    # Step 1: validate inputs
    valid, err, args = validate_inputs(
        lat, lon, crop_name, year, calendar_dir, china_pheno_dir, prefer_china
    )
    if not valid:
        print(json.dumps({"status": "INPUT_ERROR", "message": err}))
        sys.exit(1)

    # Step 2: process
    success, err, result = process(args)
    if not success:
        print(json.dumps({"status": "PROCESSING_ERROR", "message": err}))
        sys.exit(2)

    # Step 3: validate outputs
    valid, err = validate_outputs(result)
    if not valid:
        print(json.dumps({"status": "OUTPUT_ERROR", "message": err}))
        sys.exit(3)

    # Cross-year note for the message
    cross_year = result["harvest_doy"] < result["planting_doy"]
    note = " (cross-year winter crop season)" if cross_year else ""

    print(json.dumps({
        "status": "SUCCESS",
        "result": result,
        "message": (
            f"Crop '{result['crop_name']}' at ({args['lat']}, {args['lon']}): "
            f"plant DOY {result['planting_doy']}, harvest DOY {result['harvest_doy']}, "
            f"{result['season_length_days']} days{note}. "
            f"Source: {result['source']}."
        ),
    }))
    sys.exit(0)


if __name__ == "__main__":
    main()
