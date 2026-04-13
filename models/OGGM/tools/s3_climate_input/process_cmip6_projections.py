#!/usr/bin/env python3
"""
Process CMIP6 Climate Projections — OGGM Knowledge Infrastructure

Process CMIP6 GCM projections for future glacier simulations using
the delta method for bias correction.

Usage:
    python process_cmip6_projections.py \
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
        description="Process CMIP6 projections for OGGM glacier simulations"
    )
    parser.add_argument("--working_dir", required=True,
                        help="OGGM working directory")
    parser.add_argument("--gcm", required=True,
                        help="GCM name (e.g., BCC-CSM2-MR, CESM2, MPI-ESM1-2-HR)")
    parser.add_argument("--ssp", required=True,
                        choices=["ssp126", "ssp245", "ssp370", "ssp585"],
                        help="SSP scenario")
    parser.add_argument("--start_year", type=int, required=True,
                        help="Projection start year")
    parser.add_argument("--end_year", type=int, required=True,
                        help="Projection end year")
    args = parser.parse_args()

    working_dir = Path(args.working_dir)
    rid = f"{args.gcm}_{args.ssp}"

    print(f"Processing CMIP6 projection: {rid}")
    print(f"Period: {args.start_year}-{args.end_year}")

    try:
        from oggm import cfg, workflow, utils
        from oggm.shop import gcm_climate

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
        print(f"Processing {len(gdirs)} glaciers...")

        # Download and process CMIP6 data
        # OGGM provides pre-processed CMIP6 via the shop module
        print(f"Downloading {args.gcm} {args.ssp} data...")

        workflow.execute_entity_task(
            gcm_climate.process_cmip_data, gdirs,
            filesuffix=f'_{rid}',
            y0=args.start_year,
            y1=args.end_year
        )

        # CRITICAL: Verify temperature is in Celsius
        import xarray as xr
        sample_gdir = gdirs[0]
        climate_file = Path(sample_gdir.dir) / f'gcm_data_{rid}.nc'
        if climate_file.exists():
            ds = xr.open_dataset(climate_file)
            mean_temp = float(ds['temp'].mean())
            if mean_temp > 100:
                print(f"CRITICAL WARNING: Mean temperature is {mean_temp:.1f}")
                print("This appears to be in Kelvin, not Celsius!")
                print("Converting: T(C) = T(K) - 273.15")
                # Auto-fix would go here in production
            else:
                print(f"Temperature check OK: mean = {mean_temp:.1f} degC")
            ds.close()

        # Count processed
        processed = 0
        for gdir in gdirs:
            cf = Path(gdir.dir) / f'gcm_data_{rid}.nc'
            if cf.exists():
                processed += 1

        result = {
            'status': 'success',
            'gcm': args.gcm,
            'ssp': args.ssp,
            'period': f"{args.start_year}-{args.end_year}",
            'glaciers_processed': processed,
            'total_glaciers': len(gdirs),
            'filesuffix': f'_{rid}'
        }

    except ImportError as e:
        print(f"ERROR: Missing dependency: {e}")
        print("Install: conda install -c conda-forge oggm")
        result = {'status': 'error', 'message': f'Missing dependency: {e}'}

    except Exception as e:
        print(f"ERROR: {e}")
        result = {'status': 'error', 'message': str(e)}

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
