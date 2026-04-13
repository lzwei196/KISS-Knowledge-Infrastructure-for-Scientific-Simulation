#!/usr/bin/env python3
"""
vic_soil_converter.py
=====================
Convert VIC soil parameters to RZWQM2 soil configuration JSON.

Reads a VIC soil parameter file (53-column format from
global_soil_param_new.txt or basin-specific SOIL_PARAM_COMPLETE.txt),
extracts parameters for one grid cell, and converts to RZWQM2-compatible
soil horizon format.

Unit conversions (VIC -> RZWQM2):
    ksat:         mm/day  -> cm/hr     (divide by 240)
    expt:         -       -> pore_size_dist  (2 / expt)
    bulk_density: kg/m3   -> g/cm3     (divide by 1000)
                          -> ws        (1 - bd/2.65)
    Wcr_FRACT:    fraction -> fc33     (Wcr * ws)
    Wpwp_FRACT:   fraction -> fc15     (Wpwp * ws)
    depth:        m       -> cm        (multiply by 100)

Missing params (bubbling_pressure, wr, c2, N2) derived via
RZWQM2 pedotransfer functions.

Inputs:
    vic_soil_file   - Path to VIC soil parameter file
    lat             - Latitude (finds nearest grid cell)
    lon             - Longitude (finds nearest grid cell)
    grid_id         - VIC grid cell ID (alternative to lat/lon)
    output_json     - Path for output JSON (optional)

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
VIC_SOIL_FILE = ""  # Path to VIC soil parameter file
LAT = ""            # Latitude in decimal degrees
LON = ""            # Longitude in decimal degrees
GRID_ID = ""        # VIC grid cell ID (alternative to lat/lon)
OUTPUT_JSON = ""    # Output JSON path (optional)

# ---------------------------------------------------------------------------
# Add lib to path
# ---------------------------------------------------------------------------
DATA_PREP_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'lib')
sys.path.insert(0, os.path.abspath(DATA_PREP_DIR))

# VIC 53-column layout (0-indexed)
# Verified against global_soil_param_new.txt on 2026-03-17
VIC_COL = {
    'run_cell': 0, 'grid_id': 1, 'lat': 2, 'lon': 3,
    'b_infilt': 4, 'Ds': 5, 'Ds_max': 6, 'Ws': 7, 'c': 8,
    'expt': [9, 10, 11],           # 3 layers
    'ksat': [12, 13, 14],          # mm/day
    'phi_s': [15, 16, 17],
    'init_moist': [18, 19, 20],
    'elev': 21,
    'depth': [22, 23, 24],         # meters
    'avg_T': 25,
    'dp': 26,
    'bubble': 27,
    # cols 28-29 vary by file version (bubble per layer or Wpwp_FRACT offset)
    'quartz': [30, 31, 32],        # fraction (0-1)
    'bulk_density': [33, 34, 35],  # kg/m3 (verified: values ~1000-1800)
    'soil_density': [36, 37, 38],  # kg/m3 (verified: values ~2600-2700)
    'off_gmt': 39,                 # timezone offset (verified: value like -2.9)
    'Wcr_FRACT': [40, 41, 42],    # fraction (verified: values 0.1-0.5)
    'Wpwp_FRACT': [43, 44, 45],   # fraction (verified: values 0.05-0.3)
    'resid_moist': [46, 47, 48],   # residual moisture fraction
    # cols 49-52: fs_active, frost_slope, max_snow_albedo, etc.
}


def validate_inputs(vic_file, lat_raw, lon_raw, grid_id_raw, output_json):
    """Validate inputs."""
    errors = []

    if not vic_file:
        errors.append("VIC_SOIL_FILE is required.")
    elif not os.path.isfile(vic_file):
        errors.append(f"VIC_SOIL_FILE not found: {vic_file}")

    lat = lon = grid_id = None
    if grid_id_raw:
        try:
            grid_id = int(grid_id_raw)
        except ValueError:
            errors.append(f"GRID_ID must be integer: {grid_id_raw}")
    elif lat_raw and lon_raw:
        try:
            lat = float(lat_raw)
            lon = float(lon_raw)
        except ValueError:
            errors.append(f"LAT/LON must be numeric: {lat_raw}, {lon_raw}")
    else:
        errors.append("Either LAT+LON or GRID_ID is required.")

    if errors:
        return False, "; ".join(errors), None

    return True, "", {
        'vic_file': vic_file, 'lat': lat, 'lon': lon,
        'grid_id': grid_id, 'output_json': output_json,
    }


def _find_grid_cell(vic_file, lat, lon, grid_id):
    """Find the matching row in the VIC soil param file."""
    best_row = None
    best_dist = float('inf')

    with open(vic_file) as f:
        for line in f:
            parts = line.split()
            if len(parts) < 44:
                continue
            try:
                row_id = int(float(parts[VIC_COL['grid_id']]))
                row_lat = float(parts[VIC_COL['lat']])
                row_lon = float(parts[VIC_COL['lon']])

                if grid_id is not None and row_id == grid_id:
                    return [float(p) for p in parts]

                if lat is not None:
                    dist = (row_lat - lat) ** 2 + (row_lon - lon) ** 2
                    if dist < best_dist:
                        best_dist = dist
                        best_row = [float(p) for p in parts]
            except (ValueError, IndexError):
                continue

    if best_row is not None and math.sqrt(best_dist) < 1.0:
        return best_row
    return None


def process(args):
    """
    Convert VIC soil parameters to RZWQM2 format.
    Returns (success, error_msg, result).
    """
    vic_file = args['vic_file']
    lat = args['lat']
    lon = args['lon']
    grid_id = args['grid_id']

    try:
        row = _find_grid_cell(vic_file, lat, lon, grid_id)
        if row is None:
            return False, "No matching grid cell found in VIC soil parameter file.", None

        cell_lat = row[VIC_COL['lat']]
        cell_lon = row[VIC_COL['lon']]
        cell_id = int(row[VIC_COL['grid_id']])
        elevation = row[VIC_COL['elev']]

        # Try to import pedotransfer functions
        try:
            from rzwqm_file import (soil_default_setter, pore_size_distribution_estimate,
                                     B_estimate, bubbling_pressure_estimate,
                                     N2_estimate, C2_estimate, fc10_estimate)
            has_ptf = True
        except ImportError:
            has_ptf = False

        # Convert 3 VIC layers to RZWQM2 horizons
        horizons = []
        cumulative_depth = 0.0

        for layer in range(3):
            # Extract VIC values
            expt = row[VIC_COL['expt'][layer]]
            ksat_mm_day = row[VIC_COL['ksat'][layer]]
            depth_m = row[VIC_COL['depth'][layer]]
            bulk_density_kgm3 = row[VIC_COL['bulk_density'][layer]]
            wcr_fract = row[VIC_COL['Wcr_FRACT'][layer]]
            wpwp_fract = row[VIC_COL['Wpwp_FRACT'][layer]]

            # Unit conversions
            ksat_cm_hr = ksat_mm_day / 240.0
            pore_size_dist = 2.0 / expt if expt > 0 else 0.5
            bulk_density_gcc = bulk_density_kgm3 / 1000.0
            ws = 1.0 - bulk_density_gcc / 2.65
            ws = max(0.25, min(0.70, ws))  # physical clamp
            fc33 = wcr_fract * ws
            fc15 = wpwp_fract * ws

            cumulative_depth += depth_m * 100.0  # m -> cm

            # Estimate texture from bulk density + ksat heuristic
            if bulk_density_gcc > 1.55 and ksat_cm_hr < 0.3:
                texture = 'clay'
            elif bulk_density_gcc > 1.45 and ksat_cm_hr < 0.8:
                texture = 'clay loam'
            elif bulk_density_gcc < 1.3 and ksat_cm_hr > 5.0:
                texture = 'sandy loam'
            elif bulk_density_gcc < 1.2 and ksat_cm_hr > 10.0:
                texture = 'sand'
            else:
                texture = 'loam'

            # Derive missing RZWQM2 params via pedotransfer (MODE 1: measured)
            # VIC provides measured equivalents for ws (from bulk_density),
            # fc33 (from Wcr_FRACT), fc15 (from Wpwp_FRACT), ksat, and
            # pore_size_dist (from expt). Only wr needs texture defaults.
            # This matches rzwqm_scenario_mass_generation use_default_value=False
            wr = 0.05
            bp = 20.0
            fc10 = 0.35
            n2 = 12.0
            c2 = 0.0

            if has_ptf:
                defaults = soil_default_setter(texture)
                if defaults:
                    wr = defaults.get('wr', 0.05)
                    try:
                        psd = pore_size_dist
                        # Use measured fc33 + wr to estimate B
                        B = B_estimate(fc33, wr, psd)
                        # Use measured ws (from bulk_density) to estimate bubbling pressure
                        bp = bubbling_pressure_estimate(ws, psd, wr, B)
                        fc10 = fc10_estimate(ws, wr, bp, psd)
                        n2 = N2_estimate(psd)
                        # Use measured ksat for C2
                        c2 = C2_estimate(bp, psd, ksat_cm_hr, 0)
                    except Exception:
                        bp = defaults.get('bubbling_pressure', 20.0)

            horizons.append({
                'depth_cm': round(cumulative_depth),
                'ksat_cm_hr': round(ksat_cm_hr, 4),
                'pore_size_dist': round(pore_size_dist, 3),
                'ws': round(ws, 4),
                'wr': round(wr, 4),
                'fc33': round(fc33, 4),
                'fc15': round(fc15, 4),
                'fc10': round(fc10, 4),
                'bubbling_pressure': round(bp, 2),
                'N2': round(n2, 2),
                'C2': round(c2, 4),
                'bulk_density_gcc': round(bulk_density_gcc, 3),
                'texture_class': texture,
                'vic_expt': round(expt, 3),
                'vic_ksat_mm_day': round(ksat_mm_day, 2),
                'vic_layer': layer + 1,
            })

        result = {
            'source': 'vic_soil_converter',
            'vic_grid_id': cell_id,
            'lat': cell_lat,
            'lon': cell_lon,
            'elevation': round(elevation, 1),
            'horizons': horizons,
            'unit_conversions': {
                'ksat': 'mm/day / 240 = cm/hr',
                'pore_size_dist': '2 / VIC_expt',
                'ws': '1 - bulk_density(g/cm3) / 2.65',
                'fc33': 'Wcr_FRACT * ws',
                'fc15': 'Wpwp_FRACT * ws',
            }
        }

        # Optionally write to file
        if args.get('output_json'):
            with open(args['output_json'], 'w') as f:
                json.dump(result, f, indent=2)

        return True, "", result

    except Exception as e:
        return False, f"Processing error: {e}", None


def validate_outputs(result):
    """Validate converted soil parameters."""
    if not result or 'horizons' not in result:
        return False, "No horizons produced."

    for i, h in enumerate(result['horizons']):
        if h['ksat_cm_hr'] <= 0:
            return False, f"Horizon {i}: ksat_cm_hr <= 0"
        if not 0.1 < h['ws'] < 0.8:
            return False, f"Horizon {i}: ws={h['ws']} outside [0.1, 0.8]"
        if h['depth_cm'] <= 0:
            return False, f"Horizon {i}: depth_cm <= 0"

    return True, ""


def main():
    vic_file = sys.argv[1] if len(sys.argv) > 1 else VIC_SOIL_FILE
    lat_raw = sys.argv[2] if len(sys.argv) > 2 else LAT
    lon_raw = sys.argv[3] if len(sys.argv) > 3 else LON
    grid_id_raw = sys.argv[4] if len(sys.argv) > 4 else GRID_ID
    output_json = sys.argv[5] if len(sys.argv) > 5 else OUTPUT_JSON

    valid, err, args = validate_inputs(vic_file, lat_raw, lon_raw, grid_id_raw, output_json)
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
        "vic_grid_id": result['vic_grid_id'],
        "lat": result['lat'], "lon": result['lon'],
        "num_horizons": len(result['horizons']),
        "message": (
            f"Converted VIC grid cell {result['vic_grid_id']} "
            f"({result['lat']}, {result['lon']}) to {len(result['horizons'])} RZWQM2 horizons."
        )
    }))
    sys.exit(0)


if __name__ == '__main__':
    main()
