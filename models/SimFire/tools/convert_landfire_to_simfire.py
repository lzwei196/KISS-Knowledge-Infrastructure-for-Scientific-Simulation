#!/usr/bin/env python3
"""
convert_landfire_to_simfire.py — Convert LandFire GeoTIFF fuel/elevation to SimFire format.

Downloads or reads LandFire FBFM-13 fuel model and elevation rasters for a given
geographic bounding box, then converts them to SimFire-compatible numpy arrays.

CRITICAL UNIT CONVERSIONS:
  - Elevation: LandFire provides meters. SimFire expects feet. Multiply by 3.28084.
  - Fuel models: LandFire uses integer codes (1-13, 91-99). SimFire maps these to
    Fuel dataclass objects with (w_0, delta, M_x, sigma) in lb/ft², ft, -, ft²/ft³.
  - Area: Config specifies height/width in meters, resolution in meters (30m).

Output:
  - fuel_array.npy: int array of FBFM-13 codes, shape (H, W)
  - elevation_array.npy: float array of elevation in FEET, shape (H, W)
  - metadata.json: bounding box, CRS, resolution, conversion notes

Usage:
    python convert_landfire_to_simfire.py \\
        --latitude 38.422 --longitude -118.266 \\
        --height 2000 --width 2000 \\
        --resolution 30 --year 2020 \\
        --output-dir ./simfire_terrain/

    python convert_landfire_to_simfire.py \\
        --fuel-tif fuel.tif --elev-tif elev.tif \\
        --output-dir ./simfire_terrain/
"""

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np

# FBFM-13 fuel model code mapping
# Non-burnable codes map to 0 (w_0=0)
FBFM13_VALID_CODES = set(range(1, 14))  # 1-13 burnable
FBFM13_NONBURNABLE = {91, 92, 93, 98, 99, -32768, -9999, 0}

# Fuel parameters: (w_0 [lb/ft²], delta [ft], M_x [-], sigma [ft²/ft³])
FUEL_PARAMS = {
    1:  (0.0340, 1.000, 0.12, 3500),
    2:  (0.0918, 1.000, 0.15, 2784),
    3:  (0.1377, 2.500, 0.25, 1500),
    4:  (0.2296, 6.000, 0.20, 1739),
    5:  (0.0459, 2.000, 0.20, 1683),
    6:  (0.0688, 2.500, 0.25, 1564),
    7:  (0.0459, 2.500, 0.40, 1552),
    8:  (0.0688, 0.200, 0.30, 1889),
    9:  (0.1331, 0.200, 0.25, 2484),
    10: (0.1377, 1.000, 0.25, 1764),
    11: (0.0688, 1.000, 0.15, 1182),
    12: (0.1836, 2.300, 0.20, 1145),
    13: (0.3214, 3.000, 0.25, 1159),
}

METERS_TO_FEET = 3.28084


def validate_inputs(args):
    """Validate command-line arguments before processing.

    Checks geographic bounds, resolution, file existence.
    Exits with JSON error if validation fails.
    """
    errors = []

    if args.fuel_tif and args.elev_tif:
        # File mode: check files exist
        if not os.path.isfile(args.fuel_tif):
            errors.append(f"Fuel GeoTIFF not found: {args.fuel_tif}")
        if not os.path.isfile(args.elev_tif):
            errors.append(f"Elevation GeoTIFF not found: {args.elev_tif}")
    else:
        # Download mode: check coordinates
        if args.latitude is None or args.longitude is None:
            errors.append("Must provide --latitude and --longitude, or --fuel-tif and --elev-tif")
        if args.latitude is not None and not (-90 <= args.latitude <= 90):
            errors.append(f"Latitude {args.latitude} out of range [-90, 90]")
        if args.longitude is not None and not (-180 <= args.longitude <= 180):
            errors.append(f"Longitude {args.longitude} out of range [-180, 180]")
        if args.height <= 0 or args.width <= 0:
            errors.append(f"Height ({args.height}) and width ({args.width}) must be positive meters")
        if args.resolution != 30:
            errors.append(f"Resolution must be 30m (LandFire native), got {args.resolution}")
        if args.year not in (2019, 2020, 2022):
            errors.append(f"LandFire year must be 2019, 2020, or 2022, got {args.year}")

    if errors:
        print(json.dumps({"status": "error", "stage": "validate_inputs", "errors": errors}))
        sys.exit(1)


def read_geotiff(filepath):
    """Read a GeoTIFF file and return (data_array, metadata_dict).

    Uses geotiff or rasterio depending on availability.
    """
    try:
        from geotiff import GeoTiff
        geo = GeoTiff(str(filepath))
        data = np.array(geo.read())
        meta = {
            "crs": str(geo.crs_code),
            "bbox": geo.tif_bBox,
            "shape": list(data.shape),
        }
        return data, meta
    except ImportError:
        pass

    try:
        import rasterio
        with rasterio.open(str(filepath)) as src:
            data = src.read(1)
            meta = {
                "crs": str(src.crs),
                "bbox": list(src.bounds),
                "shape": list(data.shape),
                "transform": list(src.transform)[:6],
            }
            return data, meta
    except ImportError:
        print(json.dumps({
            "status": "error",
            "errors": ["Neither geotiff nor rasterio installed. pip install geotiff rasterio"]
        }))
        sys.exit(1)


def download_landfire(latitude, longitude, height, width, resolution, year, output_dir):
    """Download LandFire fuel and elevation data using the landfire package.

    Returns paths to downloaded GeoTIFF files.
    """
    try:
        from landfire import Landfire
    except ImportError:
        print(json.dumps({
            "status": "error",
            "errors": ["landfire package not installed. pip install landfire"]
        }))
        sys.exit(1)

    # Compute bounding box from top-left + dimensions
    # LandFire bbox: (west, south, east, north)
    from geopy.distance import geodesic

    south_point = geodesic(meters=height).destination((latitude, longitude), 180)
    east_point = geodesic(meters=width).destination((latitude, longitude), 90)

    bbox = (longitude, south_point.latitude, east_point.longitude, latitude)

    lf = Landfire(bbox, output_crs="EPSG:4326")

    fuel_path = os.path.join(output_dir, "landfire_fuel.tif")
    elev_path = os.path.join(output_dir, "landfire_elev.tif")

    # Download FBFM-13 fuel model
    lf.request_data(
        layers=["FBFM13"],
        output_path=fuel_path,
        resolution=resolution,
        year=year,
    )

    # Download elevation
    lf.request_data(
        layers=["ELEV"],
        output_path=elev_path,
        resolution=resolution,
        year=year,
    )

    return fuel_path, elev_path


def convert_fuel_array(fuel_raw):
    """Convert raw LandFire FBFM codes to clean integer array.

    Maps non-burnable codes (91, 92, 93, 98, 99, nodata) to 0.
    Validates all codes are in expected range.

    Returns:
        fuel_clean: int array with values in {0, 1, 2, ..., 13}
        stats: dict with code distribution
    """
    fuel_clean = fuel_raw.copy().astype(int)

    # Map non-burnable and nodata to 0
    for code in FBFM13_NONBURNABLE:
        fuel_clean[fuel_raw == code] = 0

    # Check for unexpected codes
    unique_codes = set(np.unique(fuel_clean))
    expected = FBFM13_VALID_CODES | {0}
    unexpected = unique_codes - expected
    if unexpected:
        print(json.dumps({
            "status": "warning",
            "message": f"Unexpected fuel codes found: {unexpected}. Mapping to non-burnable (0)."
        }), file=sys.stderr)
        for code in unexpected:
            fuel_clean[fuel_clean == code] = 0

    stats = {}
    for code in sorted(expected):
        count = int(np.sum(fuel_clean == code))
        if count > 0:
            stats[str(code)] = count

    return fuel_clean, stats


def convert_elevation_array(elev_raw):
    """Convert elevation from meters (LandFire) to feet (SimFire).

    CRITICAL: SimFire Rothermel model expects elevation in FEET.
    LandFire provides elevation in METERS.
    Conversion: feet = meters × 3.28084

    Returns:
        elev_feet: float array in feet
        stats: dict with min, max, mean elevation
    """
    # Handle nodata values
    nodata_mask = (elev_raw < -1000) | (elev_raw > 30000)
    elev_clean = elev_raw.astype(float)
    elev_clean[nodata_mask] = 0.0

    # CRITICAL CONVERSION: meters → feet
    elev_feet = elev_clean * METERS_TO_FEET

    stats = {
        "min_ft": float(np.min(elev_feet[~nodata_mask])) if not nodata_mask.all() else 0.0,
        "max_ft": float(np.max(elev_feet[~nodata_mask])) if not nodata_mask.all() else 0.0,
        "mean_ft": float(np.mean(elev_feet[~nodata_mask])) if not nodata_mask.all() else 0.0,
        "nodata_pixels": int(np.sum(nodata_mask)),
    }

    return elev_feet, stats


def validate_outputs(fuel_array, elev_array, output_dir):
    """Post-processing validation of converted arrays.

    Checks:
    - Arrays have same shape
    - Fuel codes are valid
    - Elevation values are in reasonable range (feet)
    - At least some burnable pixels exist
    """
    errors = []

    if fuel_array.shape != elev_array.shape:
        errors.append(
            f"Shape mismatch: fuel {fuel_array.shape} vs elevation {elev_array.shape}"
        )

    burnable = np.sum((fuel_array >= 1) & (fuel_array <= 13))
    if burnable == 0:
        errors.append("No burnable pixels found. Check fuel model data or bounding box.")

    elev_min = np.min(elev_array)
    elev_max = np.max(elev_array)
    if elev_max > 30000:  # ~30000 ft = Mt. Everest
        errors.append(
            f"Elevation max {elev_max:.0f} ft seems too high. "
            "Check if data is in meters (should be feet)."
        )
    if elev_min < -2000:  # Below Death Valley
        errors.append(
            f"Elevation min {elev_min:.0f} ft seems too low. Check nodata handling."
        )

    if errors:
        print(json.dumps({"status": "error", "stage": "validate_outputs", "errors": errors}))
        sys.exit(1)

    return {
        "shape": list(fuel_array.shape),
        "burnable_pixels": int(burnable),
        "total_pixels": int(fuel_array.size),
        "burnable_fraction": float(burnable / fuel_array.size),
        "elevation_range_ft": [float(elev_min), float(elev_max)],
    }


def process(args):
    """Main processing pipeline: download/read → convert → validate → save."""
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: Acquire data
    if args.fuel_tif and args.elev_tif:
        fuel_raw, fuel_meta = read_geotiff(args.fuel_tif)
        elev_raw, elev_meta = read_geotiff(args.elev_tif)
    else:
        fuel_path, elev_path = download_landfire(
            args.latitude, args.longitude,
            args.height, args.width,
            args.resolution, args.year,
            str(output_dir),
        )
        fuel_raw, fuel_meta = read_geotiff(fuel_path)
        elev_raw, elev_meta = read_geotiff(elev_path)

    # Step 2: Convert
    fuel_array, fuel_stats = convert_fuel_array(fuel_raw)
    elev_array, elev_stats = convert_elevation_array(elev_raw)

    # Step 3: Validate outputs
    validation = validate_outputs(fuel_array, elev_array, str(output_dir))

    # Step 4: Save
    fuel_path = output_dir / "fuel_array.npy"
    elev_path = output_dir / "elevation_array.npy"
    meta_path = output_dir / "metadata.json"

    np.save(str(fuel_path), fuel_array)
    np.save(str(elev_path), elev_array)

    metadata = {
        "source": "LandFire FBFM-13 + ELEV",
        "fuel_stats": fuel_stats,
        "elevation_stats": elev_stats,
        "validation": validation,
        "fuel_meta": fuel_meta if 'fuel_meta' in dir() else {},
        "elev_meta": elev_meta if 'elev_meta' in dir() else {},
        "unit_conversions": {
            "elevation": "meters → feet (×3.28084)",
            "fuel_codes": "FBFM-13 integer codes (1-13 burnable, 0 non-burnable)",
        },
    }
    with open(str(meta_path), "w") as f:
        json.dump(metadata, f, indent=2, default=str)

    return {
        "fuel_array": str(fuel_path),
        "elevation_array": str(elev_path),
        "metadata": str(meta_path),
        "validation": validation,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Convert LandFire GeoTIFF fuel/elevation to SimFire format"
    )
    # Download mode arguments
    parser.add_argument("--latitude", type=float, default=None,
                        help="Top-left latitude (decimal degrees)")
    parser.add_argument("--longitude", type=float, default=None,
                        help="Top-left longitude (decimal degrees)")
    parser.add_argument("--height", type=float, default=2000,
                        help="Area height in meters")
    parser.add_argument("--width", type=float, default=2000,
                        help="Area width in meters")
    parser.add_argument("--resolution", type=int, default=30,
                        help="Resolution in meters (must be 30)")
    parser.add_argument("--year", type=int, default=2020,
                        help="LandFire year (2019, 2020, 2022)")

    # File mode arguments
    parser.add_argument("--fuel-tif", type=str, default=None,
                        help="Path to fuel model GeoTIFF")
    parser.add_argument("--elev-tif", type=str, default=None,
                        help="Path to elevation GeoTIFF")

    parser.add_argument("--output-dir", type=str, required=True,
                        help="Output directory for converted arrays")

    args = parser.parse_args()
    validate_inputs(args)
    result = process(args)

    print(json.dumps({"status": "success", "output": result}, indent=2, default=str))


if __name__ == "__main__":
    main()
