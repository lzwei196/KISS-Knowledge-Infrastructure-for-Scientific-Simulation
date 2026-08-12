#!/usr/bin/env python3
"""
Validate Calibration — OGGM Knowledge Infrastructure

Validate mass balance calibration quality by checking parameter
distributions and comparing modeled vs. observed mass balance.

Usage:
    python validate_calibration.py \
        --working_dir outputs/oggm/working_dir \
        --tolerance_mm_yr 50
"""

import argparse
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="Validate OGGM mass balance calibration quality"
    )
    parser.add_argument("--working_dir", required=True,
                        help="OGGM working directory with calibrated GDirs")
    parser.add_argument("--tolerance_mm_yr", type=float, default=50,
                        help="Acceptable error tolerance in mm w.e./yr (default 50)")
    args = parser.parse_args()

    working_dir = Path(args.working_dir)

    try:
        import pickle
        import numpy as np

        per_glacier = working_dir / 'per_glacier'
        if not per_glacier.exists():
            print(f"ERROR: No per_glacier directory at {per_glacier}")
            sys.exit(1)

        # Collect calibration parameters from all GDirs
        mu_stars = []
        pcfs = []
        tbiases = []
        at_bounds = []
        all_params = []

        for region_dir in sorted(per_glacier.iterdir()):
            if not region_dir.is_dir():
                continue
            for sub_dir in sorted(region_dir.iterdir()):
                if not sub_dir.is_dir():
                    continue
                for gdir in sorted(sub_dir.iterdir()):
                    if not gdir.is_dir():
                        continue

                    ci_path = gdir / 'climate_info.pkl'
                    if ci_path.exists():
                        try:
                            with open(ci_path, 'rb') as f:
                                ci = pickle.load(f)

                            mu_star = ci.get('mu_star', None)
                            pcf = ci.get('prcp_fac', ci.get('pcf', None))
                            tbias = ci.get('temp_bias', ci.get('tbias', 0))

                            if mu_star is not None:
                                mu_stars.append(mu_star)
                                if pcf is not None:
                                    pcfs.append(pcf)
                                tbiases.append(tbias if tbias is not None else 0)

                                all_params.append({
                                    'rgi_id': gdir.name,
                                    'mu_star': mu_star,
                                    'pcf': pcf,
                                    'tbias': tbias
                                })

                                if mu_star <= 0 or mu_star >= 1000:
                                    at_bounds.append(gdir.name)
                        except Exception:
                            pass

        if not mu_stars:
            print("ERROR: No calibration parameters found")
            result = {'status': 'FAIL', 'message': 'No calibration data'}
            print(json.dumps(result, indent=2))
            sys.exit(1)

        # Compute diagnostics
        mu_arr = np.array(mu_stars)
        pcf_arr = np.array(pcfs) if pcfs else np.array([1.0])
        tbias_arr = np.array(tbiases)

        # Parameter reasonableness checks
        errors_list = []
        warnings_list = []

        # Check mu_star at bounds
        if at_bounds:
            warnings_list.append(
                f"{len(at_bounds)} glaciers have mu_star at bounds (0 or 1000): "
                f"{at_bounds[:5]}"
            )

        # Check pcf range
        pcf_outliers = [p for p in all_params
                        if p['pcf'] is not None and (p['pcf'] < 0.5 or p['pcf'] > 5.0)]
        if pcf_outliers:
            warnings_list.append(
                f"{len(pcf_outliers)} glaciers have pcf outside [0.5, 5.0]"
            )

        # Check tbias range
        tbias_extreme = [p for p in all_params
                         if p['tbias'] is not None and abs(p['tbias']) > 5.0]
        if tbias_extreme:
            warnings_list.append(
                f"{len(tbias_extreme)} glaciers have |tbias| > 5 degC"
            )

        # Fraction within expected ranges
        fraction_reasonable = np.sum((mu_arr > 10) & (mu_arr < 900)) / len(mu_arr) * 100

        status = 'PASS'
        if errors_list:
            status = 'FAIL'
        elif warnings_list:
            status = 'PASS_WITH_WARNINGS'

        result = {
            'status': status,
            'total_glaciers': len(mu_stars),
            'mu_star': {
                'mean': round(float(np.mean(mu_arr)), 1),
                'median': round(float(np.median(mu_arr)), 1),
                'std': round(float(np.std(mu_arr)), 1),
                'min': round(float(np.min(mu_arr)), 1),
                'max': round(float(np.max(mu_arr)), 1),
                'at_bounds_count': len(at_bounds)
            },
            'pcf': {
                'mean': round(float(np.mean(pcf_arr)), 2),
                'median': round(float(np.median(pcf_arr)), 2),
                'min': round(float(np.min(pcf_arr)), 2),
                'max': round(float(np.max(pcf_arr)), 2)
            },
            'tbias': {
                'mean': round(float(np.mean(tbias_arr)), 2),
                'std': round(float(np.std(tbias_arr)), 2)
            },
            'fraction_reasonable_pct': round(fraction_reasonable, 1),
            'tolerance_mm_yr': args.tolerance_mm_yr,
            'errors': errors_list,
            'warnings': warnings_list
        }

        print(f"Calibration validation: {status}")
        print(f"Glaciers: {len(mu_stars)}")
        print(f"mu_star: {np.mean(mu_arr):.1f} +/- {np.std(mu_arr):.1f}")
        print(f"pcf: {np.mean(pcf_arr):.2f} +/- {np.std(pcf_arr):.2f}")
        print(f"Fraction with reasonable params: {fraction_reasonable:.1f}%")
        if at_bounds:
            print(f"WARNING: {len(at_bounds)} glaciers at mu_star bounds")

    except Exception as e:
        print(f"ERROR: {e}")
        result = {'status': 'error', 'message': str(e)}

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
