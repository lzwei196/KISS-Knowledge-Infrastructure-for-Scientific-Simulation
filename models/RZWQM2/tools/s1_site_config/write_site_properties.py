#!/usr/bin/env python3
"""
write_site_properties.py
========================
Write geographic/site properties to the grid_general_property section of
RZWQM.dat.

Properties written (in RZWQM.dat column order):
  area, elevation, aspect, center_lat, slope, center_lon, rainfall_zone, ambient_co2

Uses grid_general_property class and write_soil_general_properties_to_dat()
from rzwqm_file.py.

CRITICAL: Latitude and longitude must be in RADIANS, not degrees.
          Convert with: rad = deg * pi / 180

Inputs:
    project_path    - RZWQM2 project root path
    station_id      - Station or grid identifier
    lat             - Latitude in radians
    lon             - Longitude in radians
    elevation       - Elevation in meters
    slope           - Slope as fraction (0.0-1.0)
    area            - Grid cell area in m^2 (default 10000)
    aspect          - Aspect clockwise from north in degrees (default 0)
    ambient_co2     - Ambient CO2 in ppm (default 400)
    rainfall_zone   - Rainfall zone identifier (default 1)

Exit codes:
    0 - Success
    1 - Input validation error
    2 - Processing error
    3 - Output validation error
"""

import sys
import os
import json
import math

# ---------------------------------------------------------------------------
# INPUTS
# ---------------------------------------------------------------------------
PROJECT_PATH = ""       # RZWQM2 project root path
STATION_ID = ""         # Station or grid identifier
LAT = ""                # Latitude in RADIANS
LON = ""                # Longitude in RADIANS
ELEVATION = ""          # Elevation in meters
SLOPE = ""              # Slope as fraction
AREA = "10000"          # Grid cell area in m^2
ASPECT = "0"            # Aspect clockwise from north (degrees)
AMBIENT_CO2 = "400"     # Ambient CO2 concentration (ppm)
RAINFALL_ZONE = "1"     # Rainfall zone identifier

# ---------------------------------------------------------------------------
# Add lib to path
# ---------------------------------------------------------------------------
DATA_PREP_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'lib')
sys.path.insert(0, os.path.abspath(DATA_PREP_DIR))


def validate_inputs(project_path, station_id, lat, lon, elevation, slope,
                    area, aspect, ambient_co2, rainfall_zone):
    """Validate inputs. Returns (valid, error_msg, parsed_args)."""
    errors = []

    if not project_path:
        errors.append("PROJECT_PATH is required.")
    elif not os.path.isdir(project_path):
        errors.append(f"PROJECT_PATH does not exist: {project_path}")

    if not station_id:
        errors.append("STATION_ID is required.")

    # Parse numeric inputs
    parsed = {}
    for name, val, required in [
        ('lat', lat, True), ('lon', lon, True),
        ('elevation', elevation, True), ('slope', slope, True),
        ('area', area, False), ('aspect', aspect, False),
        ('ambient_co2', ambient_co2, False), ('rainfall_zone', rainfall_zone, False)
    ]:
        if not val and required:
            errors.append(f"{name.upper()} is required.")
        elif val:
            try:
                parsed[name] = float(val)
            except ValueError:
                errors.append(f"{name.upper()} must be numeric, got: {val}")

    if errors:
        return False, "; ".join(errors), None

    # Domain checks
    if 'lat' in parsed:
        if abs(parsed['lat']) > math.pi / 2:
            errors.append(
                f"LAT={parsed['lat']:.4f} is outside radian range [-pi/2, pi/2]. "
                f"Did you pass degrees instead of radians? "
                f"Convert: rad = deg * pi / 180"
            )
    if 'lon' in parsed:
        if abs(parsed['lon']) > math.pi:
            errors.append(
                f"LON={parsed['lon']:.4f} is outside radian range [-pi, pi]. "
                f"Did you pass degrees instead of radians?"
            )
    if 'slope' in parsed:
        if not 0.0 <= parsed['slope'] <= 1.0:
            errors.append(f"SLOPE must be between 0 and 1, got: {parsed['slope']}")
    if 'elevation' in parsed:
        if not -500 <= parsed['elevation'] <= 9000:
            errors.append(f"ELEVATION={parsed['elevation']} outside reasonable range [-500, 9000] m.")

    # Check RZWQM.dat exists
    if project_path and station_id:
        dat_path = os.path.join(project_path, station_id, 'RZWQM.dat')
        if not os.path.isfile(dat_path):
            # Try case-insensitive
            alt_path = os.path.join(project_path, station_id, 'rzwqm.dat')
            if os.path.isfile(alt_path):
                dat_path = alt_path
            else:
                errors.append(f"RZWQM.dat not found: {dat_path}")

    if errors:
        return False, "; ".join(errors), None

    return True, "", {
        'project_path': project_path,
        'station_id': station_id,
        'lat': parsed['lat'],
        'lon': parsed['lon'],
        'elevation': parsed['elevation'],
        'slope': parsed['slope'],
        'area': parsed.get('area', 10000.0),
        'aspect': parsed.get('aspect', 0.0),
        'ambient_co2': parsed.get('ambient_co2', 400.0),
        'rainfall_zone': int(parsed.get('rainfall_zone', 1)),
        'dat_path': dat_path
    }


def process(args):
    """
    Write site properties to RZWQM.dat.
    Returns (success, error_msg, summary).
    """
    from rzwqm_file import RZWQM, grid_general_property

    project_path = args['project_path']
    station_id = args['station_id']

    try:
        site_props = grid_general_property(
            area=args['area'],
            elevation=args['elevation'],
            aspect_measured_clockwise=args['aspect'],
            center_lat=args['lat'],
            center_lon=args['lon'],
            slope=args['slope'],
            rainfall_zone=args['rainfall_zone'],
            ambient_co2=args['ambient_co2']
        )

        rz = RZWQM(project_path, station_id)
        rz.write_soil_general_properties_to_dat(site_props)

        summary = {
            'lat_rad': args['lat'],
            'lon_rad': args['lon'],
            'lat_deg': round(args['lat'] * 180 / math.pi, 4),
            'lon_deg': round(args['lon'] * 180 / math.pi, 4),
            'elevation': args['elevation'],
            'slope': args['slope'],
            'area': args['area'],
            'ambient_co2': args['ambient_co2']
        }

        return True, "", summary

    except Exception as e:
        return False, f"Processing error: {e}", None


def validate_outputs(args):
    """Verify that site properties were written correctly."""
    from rzwqm_file import RZWQM

    errors = []

    try:
        rz = RZWQM(args['project_path'], args['station_id'])
        props = rz.return_soil_general_properties()

        if float(props.center_lat) == 0.0 and float(props.center_lon) == 0.0:
            errors.append("Lat and lon are both 0.0 after write — values may not have been written.")

        # Check that written values are close to input values
        written_lat = float(props.center_lat)
        if abs(written_lat - args['lat']) > 0.001:
            errors.append(
                f"Written lat ({written_lat}) differs from input ({args['lat']})."
            )

    except Exception as e:
        errors.append(f"Could not verify outputs: {e}")

    if errors:
        return False, "; ".join(errors)
    return True, ""


def main():
    project_path = sys.argv[1] if len(sys.argv) > 1 else PROJECT_PATH
    station_id = sys.argv[2] if len(sys.argv) > 2 else STATION_ID
    lat = sys.argv[3] if len(sys.argv) > 3 else LAT
    lon = sys.argv[4] if len(sys.argv) > 4 else LON
    elevation = sys.argv[5] if len(sys.argv) > 5 else ELEVATION
    slope = sys.argv[6] if len(sys.argv) > 6 else SLOPE
    area = sys.argv[7] if len(sys.argv) > 7 else AREA
    aspect = sys.argv[8] if len(sys.argv) > 8 else ASPECT
    ambient_co2 = sys.argv[9] if len(sys.argv) > 9 else AMBIENT_CO2
    rainfall_zone = sys.argv[10] if len(sys.argv) > 10 else RAINFALL_ZONE

    # Ensure project_path ends with separator for RZWQM class compatibility
    if project_path and not project_path.endswith(('/', '\\')):
        project_path = project_path + '/'

    # --- Step 1: Validate inputs ---
    valid, err, args = validate_inputs(
        project_path, station_id, lat, lon, elevation, slope,
        area, aspect, ambient_co2, rainfall_zone
    )
    if not valid:
        print(json.dumps({"status": "INPUT_ERROR", "message": err}))
        sys.exit(1)

    # --- Step 2: Process ---
    success, err, summary = process(args)
    if not success:
        print(json.dumps({"status": "PROCESSING_ERROR", "message": err}))
        sys.exit(2)

    # --- Step 3: Validate outputs ---
    valid, err = validate_outputs(args)
    if not valid:
        print(json.dumps({"status": "OUTPUT_ERROR", "message": err}))
        sys.exit(3)

    print(json.dumps({
        "status": "SUCCESS",
        "dat_file": args['dat_path'],
        "summary": summary,
        "message": (
            f"Site properties written. "
            f"Lat={summary['lat_deg']}deg ({summary['lat_rad']:.4f} rad), "
            f"Lon={summary['lon_deg']}deg ({summary['lon_rad']:.4f} rad), "
            f"Elev={summary['elevation']}m."
        )
    }))
    sys.exit(0)


if __name__ == '__main__':
    main()
