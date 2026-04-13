#!/usr/bin/env python3
"""
Calibrate Mass Balance — OGGM Knowledge Infrastructure

Calibrate OGGM's mass balance model against geodetic mass balance
observations from Hugonnet et al. (2021).

Usage:
    python calibrate_mass_balance.py \
        --working_dir outputs/oggm/working_dir
"""

import argparse
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="Calibrate OGGM mass balance model against geodetic observations"
    )
    parser.add_argument("--working_dir", required=True,
                        help="OGGM working directory with climate-equipped GDirs")
    parser.add_argument("--ref_period", default="2000/01/01-2020/01/01",
                        help="Reference period (default 2000/01/01-2020/01/01)")
    parser.add_argument("--inform_ref_mb", default="true",
                        help="Use Hugonnet 2021 data: true/false (default true)")
    args = parser.parse_args()

    working_dir = Path(args.working_dir)
    use_geodetic = args.inform_ref_mb.lower() == 'true'

    try:
        from oggm import cfg, workflow, tasks, utils

        if not cfg.PATHS.get('working_dir'):
            cfg.initialize(logging_level='WARNING')
            cfg.PATHS['working_dir'] = str(working_dir)

        # Load GDirs
        per_glacier = working_dir / 'per_glacier'
        rgi_ids = []
        if per_glacier.exists():
            for region_dir in per_glacier.iterdir():
                if region_dir.is_dir():
                    for gdir in region_dir.iterdir():
                        if gdir.is_dir():
                            rgi_ids.append(gdir.name)

        if not rgi_ids:
            print("ERROR: No glacier directories found")
            sys.exit(1)

        gdirs = workflow.init_glacier_directories(rgi_ids, reset=False)
        print(f"Calibrating mass balance for {len(gdirs)} glaciers...")
        print(f"Reference period: {args.ref_period}")
        print(f"Using Hugonnet 2021 geodetic MB: {use_geodetic}")

        # Run calibration
        if use_geodetic:
            print("Running geodetic MB calibration (Hugonnet 2021)...")
            workflow.execute_entity_task(
                tasks.mb_calibration_from_geodetic_mb, gdirs,
                informed_ref_mb=True,
                ref_period=args.ref_period
            )
        else:
            print("Running standard MB calibration...")
            workflow.execute_entity_task(
                tasks.mb_calibration_from_geodetic_mb, gdirs,
                informed_ref_mb=False,
                ref_period=args.ref_period
            )

        # Check results
        calibrated = 0
        failed = 0
        failed_ids = []
        mu_stars = []
        pcfs = []

        import pickle

        for gdir in gdirs:
            climate_info_path = Path(gdir.dir) / 'climate_info.pkl'
            if climate_info_path.exists():
                try:
                    with open(climate_info_path, 'rb') as f:
                        ci = pickle.load(f)
                    mu_star = ci.get('mu_star', None)
                    if mu_star is not None:
                        mu_stars.append(mu_star)
                        pcf = ci.get('prcp_fac', ci.get('pcf', 1.0))
                        pcfs.append(pcf)
                        calibrated += 1

                        # Check for boundary values
                        if mu_star <= 0 or mu_star >= 1000:
                            failed_ids.append(f"{gdir.rgi_id} (mu_star={mu_star})")
                    else:
                        failed += 1
                        failed_ids.append(gdir.rgi_id)
                except Exception as e:
                    failed += 1
                    failed_ids.append(f"{gdir.rgi_id} ({str(e)[:30]})")
            else:
                failed += 1
                failed_ids.append(gdir.rgi_id)

        # Compute statistics
        import numpy as np
        result = {
            'status': 'success' if failed == 0 else 'partial',
            'glaciers_calibrated': calibrated,
            'glaciers_failed': failed,
            'ref_period': args.ref_period,
            'geodetic_mb_used': use_geodetic
        }

        if mu_stars:
            result['mu_star_mean'] = round(float(np.mean(mu_stars)), 1)
            result['mu_star_median'] = round(float(np.median(mu_stars)), 1)
            result['mu_star_std'] = round(float(np.std(mu_stars)), 1)
            result['mu_star_range'] = [round(float(np.min(mu_stars)), 1),
                                       round(float(np.max(mu_stars)), 1)]
        if pcfs:
            result['pcf_mean'] = round(float(np.mean(pcfs)), 2)

        if failed_ids:
            result['failed_rgi_ids'] = failed_ids[:20]

        print(f"\nCalibration complete: {calibrated}/{len(gdirs)} glaciers")
        if mu_stars:
            print(f"mu_star: mean={np.mean(mu_stars):.1f}, "
                  f"median={np.median(mu_stars):.1f}, "
                  f"range=[{np.min(mu_stars):.1f}, {np.max(mu_stars):.1f}]")
        if failed > 0:
            print(f"WARNING: {failed} glaciers failed calibration")

    except ImportError:
        print("ERROR: OGGM not installed. Run: conda install -c conda-forge oggm")
        result = {'status': 'error', 'message': 'OGGM not installed'}

    except Exception as e:
        print(f"ERROR: {e}")
        result = {'status': 'error', 'message': str(e)}

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
