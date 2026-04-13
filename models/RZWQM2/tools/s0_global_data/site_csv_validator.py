#!/usr/bin/env python3
"""
site_csv_validator.py
=====================
Validate an input CSV of sites for mass RZWQM2 project generation.

Required CSV columns:
    site_id, lat, lon, start_date, end_date, crop_name

Optional CSV columns:
    elevation, slope, soil_source, forcing_source, soil_source_path,
    forcing_source_path, state_code, warmup_years, vic_grid_id,
    vic_soil_param_file, vic_forcing_dir

Validation checks:
    - All required columns present
    - lat in [-90, 90], lon in [-180, 180]
    - start_date < end_date, parseable as YYYY-MM-DD
    - crop_name is recognized
    - No duplicate site_ids

Inputs:
    sites_csv   - Path to the input CSV file

Exit codes:
    0 - Success (all sites valid)
    1 - Input validation error (file issues)
    2 - Processing error (data issues found)
    3 - Output validation error
"""

import sys
import os
import csv
import json
from datetime import datetime

# ---------------------------------------------------------------------------
# INPUTS
# ---------------------------------------------------------------------------
SITES_CSV = ""  # Path to input CSV file

REQUIRED_COLUMNS = ['site_id', 'lat', 'lon', 'start_date', 'end_date', 'crop_name']

OPTIONAL_COLUMNS = [
    'elevation', 'slope', 'soil_source', 'forcing_source',
    'soil_source_path', 'forcing_source_path', 'state_code',
    'warmup_years', 'vic_grid_id', 'vic_soil_param_file', 'vic_forcing_dir'
]

KNOWN_CROPS = [
    'barley', 'maize', 'corn', 'wheat', 'rice', 'sorghum', 'millet',
    'soybean', 'peanut', 'cotton', 'potato', 'tomato', 'bean', 'dry_bean',
    'chickpea', 'cowpea', 'pepper', 'sunflower', 'sugarcane', 'alfalfa',
    'cabbage', 'faba_bean', 'velvetbean', 'triticale', 'canola',
    'bermudagrass', 'foxtail_millet', 'proso_millet', 'beet_sugar',
]

VALID_SOIL_SOURCES = ['vic_global', 'soilgrids', 'canada_shapefile', 'gssurgo', 'hwsd']
VALID_FORCING_SOURCES = ['cmfd', 'era5_api', 'vic_forcing', 'csv']


def validate_inputs(sites_csv):
    """Validate that the CSV file exists and is readable."""
    errors = []

    if not sites_csv:
        errors.append("SITES_CSV is required.")
    elif not os.path.isfile(sites_csv):
        errors.append(f"SITES_CSV does not exist: {sites_csv}")

    if errors:
        return False, "; ".join(errors), None

    return True, "", {'sites_csv': sites_csv}


def process(args):
    """
    Validate all rows in the CSV.
    Returns (success, error_msg, result).
    """
    sites_csv = args['sites_csv']
    errors = []
    warnings = []
    valid_sites = []

    try:
        with open(sites_csv, 'r', newline='', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            columns = reader.fieldnames

            # Check required columns
            missing = [c for c in REQUIRED_COLUMNS if c not in columns]
            if missing:
                return False, f"Missing required columns: {missing}", None

            seen_ids = set()
            for row_num, row in enumerate(reader, start=2):
                row_errors = []

                # site_id
                site_id = row.get('site_id', '').strip()
                if not site_id:
                    row_errors.append("site_id is empty")
                elif site_id in seen_ids:
                    row_errors.append(f"duplicate site_id: {site_id}")
                else:
                    seen_ids.add(site_id)

                # lat
                try:
                    lat = float(row['lat'])
                    if not -90 <= lat <= 90:
                        row_errors.append(f"lat={lat} outside [-90, 90]")
                except (ValueError, KeyError):
                    row_errors.append(f"invalid lat: {row.get('lat')}")

                # lon
                try:
                    lon = float(row['lon'])
                    if not -180 <= lon <= 180:
                        row_errors.append(f"lon={lon} outside [-180, 180]")
                except (ValueError, KeyError):
                    row_errors.append(f"invalid lon: {row.get('lon')}")

                # dates
                start_date = None
                end_date = None
                try:
                    start_date = datetime.strptime(row['start_date'].strip(), '%Y-%m-%d')
                except (ValueError, KeyError):
                    row_errors.append(f"invalid start_date: {row.get('start_date')} (expected YYYY-MM-DD)")
                try:
                    end_date = datetime.strptime(row['end_date'].strip(), '%Y-%m-%d')
                except (ValueError, KeyError):
                    row_errors.append(f"invalid end_date: {row.get('end_date')} (expected YYYY-MM-DD)")

                if start_date and end_date and start_date >= end_date:
                    row_errors.append(f"start_date >= end_date ({row['start_date']} >= {row['end_date']})")

                # crop_name
                crop = row.get('crop_name', '').strip().lower()
                if not crop:
                    row_errors.append("crop_name is empty")
                elif crop not in KNOWN_CROPS:
                    warnings.append(f"row {row_num}: crop '{crop}' not in known list (may still work)")

                # optional: soil_source
                soil_src = row.get('soil_source', '').strip().lower()
                if soil_src and soil_src not in VALID_SOIL_SOURCES:
                    row_errors.append(f"unknown soil_source: {soil_src}")

                # optional: forcing_source
                forcing_src = row.get('forcing_source', '').strip().lower()
                if forcing_src and forcing_src not in VALID_FORCING_SOURCES:
                    row_errors.append(f"unknown forcing_source: {forcing_src}")

                # optional: elevation
                elev = row.get('elevation', '').strip()
                if elev:
                    try:
                        e = float(elev)
                        if not -500 <= e <= 9000:
                            warnings.append(f"row {row_num}: elevation={e} outside [-500, 9000]")
                    except ValueError:
                        row_errors.append(f"invalid elevation: {elev}")

                # optional: slope
                slope = row.get('slope', '').strip()
                if slope:
                    try:
                        s = float(slope)
                        if not 0 <= s <= 1:
                            row_errors.append(f"slope={s} outside [0, 1]")
                    except ValueError:
                        row_errors.append(f"invalid slope: {slope}")

                if row_errors:
                    errors.append(f"row {row_num} (site_id={site_id}): {'; '.join(row_errors)}")
                else:
                    valid_sites.append({
                        'site_id': site_id,
                        'lat': float(row['lat']),
                        'lon': float(row['lon']),
                        'start_date': row['start_date'].strip(),
                        'end_date': row['end_date'].strip(),
                        'crop_name': crop,
                        'elevation': float(row.get('elevation', 0) or 0),
                        'slope': float(row.get('slope', 0.02) or 0.02),
                        'soil_source': row.get('soil_source', '').strip().lower() or None,
                        'forcing_source': row.get('forcing_source', '').strip().lower() or None,
                        'soil_source_path': row.get('soil_source_path', '').strip() or None,
                        'forcing_source_path': row.get('forcing_source_path', '').strip() or None,
                        'state_code': row.get('state_code', '').strip() or None,
                        'warmup_years': int(row.get('warmup_years', 0) or 0),
                        'vic_grid_id': row.get('vic_grid_id', '').strip() or None,
                        'vic_soil_param_file': row.get('vic_soil_param_file', '').strip() or None,
                        'vic_forcing_dir': row.get('vic_forcing_dir', '').strip() or None,
                    })

        if errors:
            return False, f"{len(errors)} validation error(s): " + "; ".join(errors[:5]), None

        summary = {
            'total_sites': len(valid_sites),
            'valid_sites': len(valid_sites),
            'warnings': warnings[:10],
            'crops': list(set(s['crop_name'] for s in valid_sites)),
            'lat_range': [min(s['lat'] for s in valid_sites), max(s['lat'] for s in valid_sites)],
            'lon_range': [min(s['lon'] for s in valid_sites), max(s['lon'] for s in valid_sites)],
            'sites': valid_sites
        }

        return True, "", summary

    except Exception as e:
        return False, f"Processing error: {e}", None


def validate_outputs(summary):
    """Check that at least one valid site was produced."""
    if not summary or summary['total_sites'] == 0:
        return False, "No valid sites found in CSV."
    return True, ""


def main():
    sites_csv = sys.argv[1] if len(sys.argv) > 1 else SITES_CSV

    valid, err, args = validate_inputs(sites_csv)
    if not valid:
        print(json.dumps({"status": "INPUT_ERROR", "message": err}))
        sys.exit(1)

    success, err, summary = process(args)
    if not success:
        print(json.dumps({"status": "PROCESSING_ERROR", "message": err}))
        sys.exit(2)

    valid, err = validate_outputs(summary)
    if not valid:
        print(json.dumps({"status": "OUTPUT_ERROR", "message": err}))
        sys.exit(3)

    print(json.dumps({
        "status": "SUCCESS",
        "total_sites": summary['total_sites'],
        "crops": summary['crops'],
        "lat_range": summary['lat_range'],
        "lon_range": summary['lon_range'],
        "warnings": summary['warnings'],
        "message": f"Validated {summary['total_sites']} sites across {len(summary['crops'])} crop types."
    }))
    sys.exit(0)


if __name__ == '__main__':
    main()
