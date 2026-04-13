#!/usr/bin/env python3
"""
Initialize Glacier Directories — OGGM Knowledge Infrastructure

Initialize OGGM Glacier Directories (GDirs) from pre-processed directories
(recommended) or from scratch. Each glacier gets its own directory with
DEM, outlines, flowlines, and derived products.

Usage:
    python init_glacier_directories.py \
        --rgi_ids outputs/oggm/glaciers_in_basin.csv \
        --working_dir outputs/oggm/working_dir \
        --prepro_level 5
"""

import argparse
import csv
import json
import sys
from pathlib import Path


def load_rgi_ids(rgi_ids_input):
    """Load RGI IDs from CSV file or comma-separated string."""
    path = Path(rgi_ids_input)
    if path.exists() and path.suffix == '.csv':
        ids = []
        with open(path, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                rgi_id = row.get('rgi_id', row.get('RGIId', ''))
                if rgi_id:
                    ids.append(rgi_id)
        return ids
    else:
        # Assume comma-separated list
        return [x.strip() for x in rgi_ids_input.split(',') if x.strip()]


def main():
    parser = argparse.ArgumentParser(
        description="Initialize OGGM Glacier Directories"
    )
    parser.add_argument("--rgi_ids", required=True,
                        help="CSV file with rgi_id column, or comma-separated RGI IDs")
    parser.add_argument("--working_dir", required=True,
                        help="OGGM working directory")
    parser.add_argument("--prepro_level", type=int, default=5,
                        help="Preprocessing level 1-5 (default 5)")
    parser.add_argument("--prepro_border", type=int, default=80,
                        help="Border for pre-processed dirs: 80 or 160 (default 80)")
    parser.add_argument("--from_prepro", default="true",
                        help="Use pre-processed directories: true/false (default true)")
    args = parser.parse_args()

    # Load RGI IDs
    rgi_ids = load_rgi_ids(args.rgi_ids)
    if not rgi_ids:
        print("ERROR: No RGI IDs found in input")
        sys.exit(1)

    print(f"Loaded {len(rgi_ids)} RGI IDs")
    print(f"First few: {rgi_ids[:5]}")

    use_prepro = args.from_prepro.lower() == 'true'

    try:
        from oggm import cfg, workflow, utils

        # Ensure configuration
        if not cfg.PATHS.get('working_dir'):
            cfg.initialize(logging_level='WARNING')
            cfg.PATHS['working_dir'] = str(Path(args.working_dir).resolve())
            cfg.PARAMS['border'] = args.prepro_border

        working_dir = Path(cfg.PATHS['working_dir'])
        working_dir.mkdir(parents=True, exist_ok=True)

        if use_prepro:
            print(f"Initializing GDirs from pre-processed level {args.prepro_level}...")
            print(f"Border: {args.prepro_border}")
            print("This downloads from the OGGM Bremen server (may take several minutes)...")

            # OGGM v1.6+ requires explicit base URL for pre-processed directories
            base_url = (
                'https://cluster.klima.uni-bremen.de/~oggm/gdirs/oggm_v1.6/'
                'L3-L5_files/2023.3/elev_bands/W5E5/'
            )

            gdirs = workflow.init_glacier_directories(
                rgi_ids,
                from_prepro_level=args.prepro_level,
                prepro_border=args.prepro_border,
                prepro_base_url=base_url,
            )
        else:
            print("Initializing GDirs from scratch...")
            print("This will download DEMs and compute flowlines (may take a long time)...")

            from oggm import tasks
            gdirs = workflow.init_glacier_directories(rgi_ids)

            # Run preprocessing tasks
            print("Step 1/6: Define glacier regions...")
            workflow.execute_entity_task(tasks.define_glacier_region, gdirs)

            print("Step 2/6: Compute glacier masks...")
            workflow.execute_entity_task(tasks.glacier_masks, gdirs)

            print("Step 3/6: Compute centerlines...")
            workflow.execute_entity_task(tasks.compute_centerlines, gdirs)

            print("Step 4/6: Initialize flowlines...")
            workflow.execute_entity_task(tasks.initialize_flowlines, gdirs)

            print("Step 5/6: Compute downstream lines...")
            workflow.execute_entity_task(tasks.compute_downstream_line, gdirs)
            workflow.execute_entity_task(tasks.compute_downstream_bedshape, gdirs)

            print("Step 6/6: Compute catchment areas...")
            workflow.execute_entity_task(tasks.catchment_area, gdirs)
            workflow.execute_entity_task(tasks.catchment_intersections, gdirs)
            workflow.execute_entity_task(tasks.catchment_width_geom, gdirs)
            workflow.execute_entity_task(tasks.catchment_width_correction, gdirs)

        # Report results
        valid_count = len(gdirs)
        failed_count = len(rgi_ids) - valid_count

        result = {
            'status': 'success',
            'total_requested': len(rgi_ids),
            'initialized': valid_count,
            'failed': failed_count,
            'prepro_level': args.prepro_level if use_prepro else 'from_scratch',
            'working_dir': str(working_dir),
            'gdirs_path': str(working_dir / 'per_glacier')
        }

        print(f"\nInitialized {valid_count} glacier directories")
        if failed_count > 0:
            print(f"WARNING: {failed_count} glaciers failed to initialize")

    except ImportError:
        print("ERROR: OGGM not installed. Run: conda install -c conda-forge oggm")
        result = {'status': 'error', 'message': 'OGGM not installed'}

    except Exception as e:
        print(f"ERROR: {e}")
        result = {'status': 'error', 'message': str(e)}

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
