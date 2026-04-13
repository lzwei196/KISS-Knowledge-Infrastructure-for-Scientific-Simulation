#!/usr/bin/env python3
"""
elevation_source_adapter.py
===========================
Retrieve elevation for a lat/lon point from various sources.

Sources:
    - cmfd_elev: CMFD elevation NetCDF (0.1 degree, China coverage)
    - srtm_api:  USGS SRTM 30m DEM via Open Elevation API
    - manual:    User-provided elevation value
    - flat:      Returns 0.0 (for flat agricultural plains)

Inputs:
    lat         - Latitude in decimal degrees
    lon         - Longitude in decimal degrees
    source      - One of: "cmfd_elev", "srtm_api", "manual", "flat"
    source_path - Path to local elevation data (for cmfd_elev)
    manual_elev - Manual elevation value (for source="manual")

Exit codes:
    0 - Success
    1 - Input validation error
    2 - Processing error
    3 - Output validation error
"""

import sys
import os
import json

# ---------------------------------------------------------------------------
# INPUTS
# ---------------------------------------------------------------------------
LAT = ""            # Latitude in decimal degrees
LON = ""            # Longitude in decimal degrees
SOURCE = "flat"     # Elevation source
SOURCE_PATH = ""    # Path to local elevation data
MANUAL_ELEV = ""    # Manual elevation value


def validate_inputs(lat_raw, lon_raw, source, source_path, manual_elev_raw):
    """Validate inputs."""
    errors = []

    lat = None
    lon = None
    try:
        lat = float(lat_raw) if lat_raw else None
        if lat is None:
            errors.append("LAT is required.")
        elif not -90 <= lat <= 90:
            errors.append(f"LAT={lat} outside [-90, 90].")
    except ValueError:
        errors.append(f"LAT must be numeric, got: {lat_raw}")

    try:
        lon = float(lon_raw) if lon_raw else None
        if lon is None:
            errors.append("LON is required.")
        elif not -180 <= lon <= 180:
            errors.append(f"LON={lon} outside [-180, 180].")
    except ValueError:
        errors.append(f"LON must be numeric, got: {lon_raw}")

    source = source.strip().lower() if source else 'flat'
    valid_sources = ['cmfd_elev', 'srtm_api', 'manual', 'flat']
    if source not in valid_sources:
        errors.append(f"SOURCE must be one of {valid_sources}, got: {source}")

    if source == 'cmfd_elev' and source_path and not os.path.isfile(source_path):
        errors.append(f"SOURCE_PATH does not exist: {source_path}")

    manual_elev = None
    if source == 'manual':
        if not manual_elev_raw:
            errors.append("MANUAL_ELEV is required when SOURCE='manual'.")
        else:
            try:
                manual_elev = float(manual_elev_raw)
            except ValueError:
                errors.append(f"MANUAL_ELEV must be numeric, got: {manual_elev_raw}")

    if errors:
        return False, "; ".join(errors), None

    return True, "", {
        'lat': lat, 'lon': lon,
        'source': source,
        'source_path': source_path,
        'manual_elev': manual_elev,
    }


def process(args):
    """
    Retrieve elevation from the specified source.
    Returns (success, error_msg, result).
    """
    lat = args['lat']
    lon = args['lon']
    source = args['source']

    try:
        elevation = 0.0

        if source == 'flat':
            elevation = 0.0

        elif source == 'manual':
            elevation = args['manual_elev']

        elif source == 'cmfd_elev':
            source_path = args['source_path']
            if not source_path:
                # Try default CMFD elevation path
                candidates = [
                    os.path.join(os.path.expanduser('~'), 'Hydrocraft', 'Hydrocraft', 'data', 'elev', 'elev_CMFD_V0200_B-00_fx_010deg.nc'),
                ]
                for c in candidates:
                    if os.path.isfile(c):
                        source_path = c
                        break

            if not source_path or not os.path.isfile(source_path):
                return False, "CMFD elevation file not found. Provide SOURCE_PATH.", None

            try:
                import xarray as xr
                ds = xr.open_dataset(source_path)
                # Find the elevation variable (first non-coordinate variable)
                var_name = [v for v in ds.data_vars][0]
                elev_val = ds[var_name].sel(
                    lat=lat, lon=lon, method='nearest'
                ).values.item()
                elevation = float(elev_val)
                ds.close()
            except ImportError:
                return False, "xarray not installed. Cannot read NetCDF elevation data.", None

        elif source == 'srtm_api':
            try:
                import urllib.request
                url = f"https://api.open-elevation.com/api/v1/lookup?locations={lat},{lon}"
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read().decode())
                    elevation = float(data['results'][0]['elevation'])
            except Exception as e:
                return False, f"SRTM API request failed: {e}", None

        result = {
            'elevation_m': round(elevation, 1),
            'source': source,
            'lat': lat,
            'lon': lon,
        }

        return True, "", result

    except Exception as e:
        return False, f"Processing error: {e}", None


def validate_outputs(result):
    """Check elevation is reasonable."""
    elev = result.get('elevation_m', 0)
    if elev < -500 or elev > 9000:
        return False, f"Elevation {elev}m outside reasonable range [-500, 9000]."
    return True, ""


def main():
    lat_raw = sys.argv[1] if len(sys.argv) > 1 else LAT
    lon_raw = sys.argv[2] if len(sys.argv) > 2 else LON
    source = sys.argv[3] if len(sys.argv) > 3 else SOURCE
    source_path = sys.argv[4] if len(sys.argv) > 4 else SOURCE_PATH
    manual_elev_raw = sys.argv[5] if len(sys.argv) > 5 else MANUAL_ELEV

    valid, err, args = validate_inputs(lat_raw, lon_raw, source, source_path, manual_elev_raw)
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
        "message": f"Elevation at ({lat_raw}, {lon_raw}): {result['elevation_m']}m (source: {source})."
    }))
    sys.exit(0)


if __name__ == '__main__':
    main()
