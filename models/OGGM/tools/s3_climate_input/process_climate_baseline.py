#!/usr/bin/env python3
"""
Process Baseline Climate Data — OGGM Knowledge Infrastructure

Process standard climate datasets (W5E5, CRU, ERA5) for glacier mass
balance computation and attach to glacier directories.

Usage:
    python process_climate_baseline.py \
        --working_dir outputs/oggm/working_dir \
        --source W5E5
"""

import argparse
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="Process baseline climate data for OGGM"
    )
    parser.add_argument("--working_dir", required=True,
                        help="OGGM working directory with initialized GDirs")
    parser.add_argument("--source", default="W5E5",
                        choices=["W5E5", "CRU", "ERA5"],
                        help="Climate data source (default W5E5)")
    parser.add_argument("--ref_period", default="2000-2020",
                        help="Reference period YYYY-YYYY (default 2000-2020)")
    args = parser.parse_args()

    working_dir = Path(args.working_dir)

    try:
        from oggm import cfg, workflow, tasks, utils

        if not cfg.PATHS.get('working_dir'):
            cfg.initialize(logging_level='WARNING')
            cfg.PATHS['working_dir'] = str(working_dir)

        # Load glacier directories
        gdirs = workflow.init_glacier_directories(
            utils.get_rgi_glacier_entities(str(working_dir)),
            reset=False, force=False
        )

        if not gdirs:
            # Try alternative: read from per_glacier directory
            per_glacier = working_dir / 'per_glacier'
            if per_glacier.exists():
                rgi_ids = []
                for region_dir in per_glacier.iterdir():
                    if region_dir.is_dir():
                        for gdir in region_dir.iterdir():
                            if gdir.is_dir():
                                rgi_ids.append(gdir.name)
                gdirs = workflow.init_glacier_directories(rgi_ids, reset=False)

        print(f"Processing {args.source} climate for {len(gdirs)} glaciers...")

        # Process climate based on source
        if args.source == 'W5E5':
            print("Downloading W5E5 data (first time may take several minutes)...")
            workflow.execute_entity_task(tasks.process_w5e5_data, gdirs)
        elif args.source == 'CRU':
            print("Downloading CRU TS data...")
            workflow.execute_entity_task(tasks.process_cru_data, gdirs)
        elif args.source == 'ERA5':
            print("Processing ERA5 data (requires CDS API key in ~/.cdsapirc)...")
            workflow.execute_entity_task(tasks.process_era5_daily_data, gdirs)

        # Verify climate files exist
        processed = 0
        missing = []
        for gdir in gdirs:
            climate_file = Path(gdir.dir) / 'climate_historical.nc'
            if climate_file.exists():
                processed += 1
            else:
                missing.append(gdir.rgi_id)

        result = {
            'status': 'success' if not missing else 'partial',
            'source': args.source,
            'ref_period': args.ref_period,
            'glaciers_processed': processed,
            'glaciers_missing': len(missing),
            'missing_rgi_ids': missing[:10]
        }

        print(f"Climate processed for {processed}/{len(gdirs)} glaciers")
        if missing:
            print(f"WARNING: {len(missing)} glaciers missing climate data")

    except ImportError:
        print("ERROR: OGGM not installed. Run: conda install -c conda-forge oggm")
        result = {'status': 'error', 'message': 'OGGM not installed'}

    except Exception as e:
        print(f"ERROR: {e}")
        result = {'status': 'error', 'message': str(e)}

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
