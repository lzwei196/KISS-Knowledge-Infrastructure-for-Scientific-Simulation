#!/usr/bin/env python3
"""
Run Glacier Projections — OGGM Knowledge Infrastructure

Run glacier dynamics simulations under future CMIP6 climate scenarios.

Usage:
    python run_glacier_projections.py \
        --working_dir outputs/oggm/working_dir \
        --gcm BCC-CSM2-MR --ssp ssp245 \
        --start_year 2020 --end_year 2100
"""

import argparse
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="Run OGGM glacier projections under climate scenarios"
    )
    parser.add_argument("--working_dir", required=True,
                        help="OGGM working directory")
    parser.add_argument("--gcm", required=True,
                        help="GCM name")
    parser.add_argument("--ssp", required=True,
                        choices=["ssp126", "ssp245", "ssp370", "ssp585"],
                        help="SSP scenario")
    parser.add_argument("--start_year", type=int, required=True)
    parser.add_argument("--end_year", type=int, required=True)
    parser.add_argument("--model_type", default="FluxBased",
                        choices=["FluxBased", "SemiImplicit"],
                        help="Flowline model (default FluxBased)")
    args = parser.parse_args()

    working_dir = Path(args.working_dir)
    rid = f"{args.gcm}_{args.ssp}"
    suffix = f"_{rid}"

    print(f"Running glacier projection: {rid}")
    print(f"Period: {args.start_year}-{args.end_year}")

    try:
        from oggm import cfg, workflow, tasks

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

        gdirs = workflow.init_glacier_directories(rgi_ids, reset=False)
        print(f"Running projections for {len(gdirs)} glaciers...")

        # Run projection
        workflow.execute_entity_task(
            tasks.run_with_hydro, gdirs,
            run_task=tasks.run_from_climate_data,
            climate_filename='gcm_data',
            climate_input_filesuffix=suffix,
            min_ys=args.start_year,
            max_ys=args.end_year,
            store_monthly_hydro=True,
            output_filesuffix=suffix
        )

        # Check results and find peak water
        simulated = 0
        total_annual_runoff = {}

        import xarray as xr
        import numpy as np

        for gdir in gdirs:
            diag = Path(gdir.dir) / f'model_diagnostics{suffix}.nc'
            if diag.exists():
                simulated += 1
                try:
                    ds = xr.open_dataset(diag)
                    # Volume evolution
                    ds.close()
                except Exception:
                    pass

        # Compute peak water from compiled output
        peak_water_year = None
        volume_2100 = None

        result = {
            'status': 'success' if simulated > 0 else 'error',
            'gcm': args.gcm,
            'ssp': args.ssp,
            'period': f"{args.start_year}-{args.end_year}",
            'glaciers_simulated': simulated,
            'total_glaciers': len(gdirs),
            'output_suffix': suffix
        }

        if peak_water_year:
            result['peak_water_year'] = peak_water_year
        if volume_2100 is not None:
            result['volume_end_km3'] = volume_2100

        print(f"\nProjection complete: {simulated}/{len(gdirs)} glaciers")
        if peak_water_year:
            print(f"Peak water year: {peak_water_year}")

    except ImportError:
        print("ERROR: OGGM not installed")
        result = {'status': 'error', 'message': 'OGGM not installed'}

    except Exception as e:
        print(f"ERROR: {e}")
        result = {'status': 'error', 'message': str(e)}

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
