#!/usr/bin/env python3
"""
Validate Preprocessing — OGGM Knowledge Infrastructure

Validate that all glacier directories are properly initialized with
flowlines, DEM, and ice thickness data.

Usage:
    python validate_preprocessing.py \
        --working_dir outputs/oggm/working_dir
"""

import argparse
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="Validate OGGM glacier directory preprocessing"
    )
    parser.add_argument("--working_dir", required=True,
                        help="OGGM working directory")
    args = parser.parse_args()

    working_dir = Path(args.working_dir)
    per_glacier = working_dir / 'per_glacier'

    if not per_glacier.exists():
        print(f"ERROR: No per_glacier directory found at {per_glacier}")
        result = {'status': 'error', 'message': 'per_glacier directory not found'}
        print(json.dumps(result, indent=2))
        sys.exit(1)

    try:
        from oggm import cfg, workflow, utils
        import pickle

        if not cfg.PATHS.get('working_dir'):
            cfg.initialize(logging_level='WARNING')
            cfg.PATHS['working_dir'] = str(working_dir)

        # Find all glacier directories
        gdir_paths = []
        for region_dir in per_glacier.iterdir():
            if region_dir.is_dir():
                for glacier_dir in region_dir.iterdir():
                    if glacier_dir.is_dir():
                        gdir_paths.append(glacier_dir)

        total = len(gdir_paths)
        valid = 0
        failed = 0
        issues = []
        total_volume = 0.0
        total_area = 0.0

        for gdir_path in gdir_paths:
            glacier_name = gdir_path.name
            glacier_issues = []

            # Check for flowlines
            flowlines_path = gdir_path / 'model_flowlines.pkl'
            if not flowlines_path.exists():
                glacier_issues.append('missing model_flowlines.pkl')

            # Check for inversion flowlines
            inv_path = gdir_path / 'inversion_flowlines.pkl'
            if not inv_path.exists():
                glacier_issues.append('missing inversion_flowlines.pkl')

            # Check for DEM
            dem_path = gdir_path / 'dem.tif'
            if not dem_path.exists():
                glacier_issues.append('missing dem.tif')

            # Try to read volume from diagnostics
            diag_path = gdir_path / 'model_diagnostics.nc'
            if flowlines_path.exists():
                try:
                    with open(flowlines_path, 'rb') as f:
                        flowlines = pickle.load(f)
                    if flowlines:
                        vol = sum(fl.volume_km3 for fl in flowlines
                                  if hasattr(fl, 'volume_km3'))
                        area = sum(fl.area_km2 for fl in flowlines
                                   if hasattr(fl, 'area_km2'))
                        total_volume += vol
                        total_area += area
                        if vol <= 0:
                            glacier_issues.append('zero or negative volume')
                    else:
                        glacier_issues.append('empty flowlines')
                except Exception as e:
                    glacier_issues.append(f'flowline read error: {str(e)[:50]}')

            if glacier_issues:
                failed += 1
                issues.append({
                    'glacier': glacier_name,
                    'issues': glacier_issues
                })
            else:
                valid += 1

        result = {
            'status': 'PASS' if failed == 0 else 'PASS_WITH_WARNINGS' if valid > 0 else 'FAIL',
            'total_glaciers': total,
            'valid_count': valid,
            'failed_count': failed,
            'total_volume_km3': round(total_volume, 4),
            'total_area_km2': round(total_area, 2),
            'issues': issues[:20]  # Limit to first 20
        }

        if failed > 20:
            result['note'] = f'Showing first 20 of {failed} failed glaciers'

        print(f"Validation complete: {valid}/{total} glaciers OK")
        if failed > 0:
            print(f"WARNING: {failed} glaciers have issues")
        print(f"Total estimated volume: {total_volume:.4f} km3")
        print(f"Total area: {total_area:.2f} km2")

    except ImportError:
        # Fallback: check file existence without OGGM
        print("OGGM not available — performing basic file existence checks")

        total = len(gdir_paths)
        valid = 0
        failed = 0
        issues = []

        for gdir_path in gdir_paths:
            has_flowlines = (gdir_path / 'model_flowlines.pkl').exists()
            has_dem = (gdir_path / 'dem.tif').exists()

            if has_flowlines and has_dem:
                valid += 1
            else:
                failed += 1
                issues.append({
                    'glacier': gdir_path.name,
                    'has_flowlines': has_flowlines,
                    'has_dem': has_dem
                })

        result = {
            'status': 'PASS' if failed == 0 else 'DEGRADED',
            'total_glaciers': total,
            'valid_count': valid,
            'failed_count': failed,
            'issues': issues[:20],
            'note': 'Basic file check only (OGGM not installed)'
        }

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
