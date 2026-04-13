#!/usr/bin/env python3
"""
Validate Glacier Selection — OGGM Knowledge Infrastructure

Validate the selected glacier inventory for a basin simulation.
Checks for duplicates, area thresholds, and computes glacier fraction.

Usage:
    python validate_glacier_selection.py \
        --glacier_csv outputs/oggm/glaciers_in_basin.csv \
        --basin_area_km2 208091
"""

import argparse
import csv
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="Validate glacier selection for basin simulation"
    )
    parser.add_argument("--glacier_csv", required=True, help="Glacier inventory CSV")
    parser.add_argument("--basin_area_km2", type=float, required=True,
                        help="Total basin area in km2")
    args = parser.parse_args()

    csv_path = Path(args.glacier_csv)
    if not csv_path.exists():
        print(f"ERROR: Glacier CSV not found: {csv_path}")
        sys.exit(1)

    # Read glacier data
    glaciers = []
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            glaciers.append(row)

    errors = []
    warnings = []
    info = []

    # Check 1: Non-empty
    if len(glaciers) == 0:
        errors.append("No glaciers in CSV file")
        result = {
            'status': 'FAIL',
            'n_glaciers': 0,
            'errors': errors,
            'warnings': warnings
        }
        print(json.dumps(result, indent=2))
        return

    info.append(f"Total glaciers: {len(glaciers)}")

    # Check 2: No duplicate RGI IDs
    rgi_ids = [g.get('rgi_id', '') for g in glaciers]
    duplicates = set([x for x in rgi_ids if rgi_ids.count(x) > 1])
    if duplicates:
        errors.append(f"Duplicate RGI IDs found: {duplicates}")

    # Check 3: Valid RGI ID format (RGI60-XX.XXXXX)
    import re
    rgi_pattern = re.compile(r'^RGI\d{2}-\d{2}\.\d{5}$')
    invalid_ids = [rid for rid in rgi_ids if rid and not rgi_pattern.match(rid)]
    if invalid_ids:
        warnings.append(f"Non-standard RGI ID format ({len(invalid_ids)} glaciers): {invalid_ids[:5]}...")

    # Check 4: Areas > 0
    areas = []
    for g in glaciers:
        try:
            area = float(g.get('area_km2', 0))
            areas.append(area)
            if area <= 0:
                errors.append(f"Glacier {g.get('rgi_id', '?')} has non-positive area: {area}")
        except (ValueError, TypeError):
            errors.append(f"Glacier {g.get('rgi_id', '?')} has invalid area: {g.get('area_km2')}")
            areas.append(0)

    # Check 5: Glacier fraction
    total_glacier_area = sum(areas)
    glacier_fraction = total_glacier_area / args.basin_area_km2 * 100 if args.basin_area_km2 > 0 else 0

    if glacier_fraction < 0.1:
        warnings.append(
            f"Glacier fraction is very small ({glacier_fraction:.3f}%). "
            "Consider skipping OGGM — glacier contribution to discharge is negligible."
        )
    elif glacier_fraction > 50:
        warnings.append(
            f"Glacier fraction is very large ({glacier_fraction:.1f}%). "
            "Extra care needed for double-counting correction with VIC."
        )

    info.append(f"Total glacier area: {total_glacier_area:.2f} km2")
    info.append(f"Basin area: {args.basin_area_km2:.1f} km2")
    info.append(f"Glacier fraction: {glacier_fraction:.3f}%")

    # Check 6: Elevation statistics
    elevations = []
    for g in glaciers:
        try:
            max_elev = float(g.get('max_elev', -999))
            min_elev = float(g.get('min_elev', -999))
            if max_elev > 0:
                elevations.append(max_elev)
        except (ValueError, TypeError):
            pass

    if elevations:
        info.append(f"Elevation range: {min(elevations):.0f} - {max(elevations):.0f} m")
        area_weighted_elev = sum(
            float(g.get('max_elev', 0)) * float(g.get('area_km2', 0))
            for g in glaciers
            if float(g.get('max_elev', -999)) > 0
        ) / total_glacier_area if total_glacier_area > 0 else 0
        info.append(f"Area-weighted mean max elevation: {area_weighted_elev:.0f} m")

    # Check 7: Problematic glaciers
    debris_count = sum(1 for g in glaciers if str(g.get('debris_flag', '0')) not in ('0', ''))
    if debris_count > 0:
        info.append(
            f"Debris-covered glaciers: {debris_count} "
            "(OGGM does not model debris cover explicitly)"
        )

    # Area distribution
    if areas:
        areas_sorted = sorted(areas, reverse=True)
        info.append(f"Largest glacier: {areas_sorted[0]:.2f} km2")
        info.append(f"Smallest glacier: {areas_sorted[-1]:.4f} km2")
        info.append(f"Median glacier area: {areas_sorted[len(areas_sorted)//2]:.4f} km2")

    # Overall status
    status = 'PASS' if not errors else 'FAIL'
    if warnings and not errors:
        status = 'PASS_WITH_WARNINGS'

    result = {
        'status': status,
        'n_glaciers': len(glaciers),
        'total_glacier_area_km2': round(total_glacier_area, 2),
        'basin_area_km2': args.basin_area_km2,
        'glacier_fraction_pct': round(glacier_fraction, 3),
        'errors': errors,
        'warnings': warnings,
        'info': info,
        'recommendation': (
            'SKIP OGGM' if glacier_fraction < 0.1
            else 'OPTIONAL' if glacier_fraction < 1
            else 'RECOMMENDED' if glacier_fraction < 10
            else 'REQUIRED'
        )
    }

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
