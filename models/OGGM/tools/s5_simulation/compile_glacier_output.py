#!/usr/bin/env python3
"""
Compile Glacier Output — OGGM Knowledge Infrastructure

Compile per-glacier OGGM outputs into basin-level aggregates using
OGGM's compile_run_output and compile_glacier_statistics utilities.

Usage:
    python compile_glacier_output.py \
        --working_dir outputs/oggm/working_dir \
        --output_dir outputs/oggm/compiled
"""

import argparse
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="Compile per-glacier OGGM outputs to basin-level aggregates"
    )
    parser.add_argument("--working_dir", required=True,
                        help="OGGM working directory")
    parser.add_argument("--output_dir", default=None,
                        help="Output directory (default: working_dir/compiled)")
    parser.add_argument("--output_suffix", default="_historical",
                        help="Suffix matching simulation files (default _historical)")
    args = parser.parse_args()

    working_dir = Path(args.working_dir)
    output_dir = Path(args.output_dir) if args.output_dir else working_dir / 'compiled'
    output_dir.mkdir(parents=True, exist_ok=True)

    suffix = args.output_suffix

    try:
        from oggm import cfg, workflow, utils
        import xarray as xr
        import numpy as np

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
        print(f"Compiling output for {len(gdirs)} glaciers...")

        # Compile run output (volume, area, length)
        print("Compiling run output (diagnostics)...")
        ds = utils.compile_run_output(gdirs, input_filesuffix=suffix)

        output_nc = output_dir / f'compiled_output{suffix}.nc'
        ds.to_netcdf(output_nc)
        print(f"Compiled diagnostics: {output_nc}")

        # Compile glacier statistics
        print("Compiling glacier statistics...")
        df_stats = utils.compile_glacier_statistics(gdirs)

        stats_csv = output_dir / 'glacier_statistics.csv'
        df_stats.to_csv(stats_csv)
        print(f"Glacier statistics: {stats_csv}")

        # Compute basin-level summary
        total_volume_start = float(ds['volume'].isel(time=0).sum()) / 1e9  # km3
        total_volume_end = float(ds['volume'].isel(time=-1).sum()) / 1e9
        total_area_start = float(ds['area'].isel(time=0).sum()) / 1e6  # km2
        total_area_end = float(ds['area'].isel(time=-1).sum()) / 1e6

        result = {
            'status': 'success',
            'compiled_output': str(output_nc),
            'glacier_statistics': str(stats_csv),
            'n_glaciers': len(gdirs),
            'time_range': [str(ds.time.values[0]), str(ds.time.values[-1])],
            'total_volume_start_km3': round(total_volume_start, 4),
            'total_volume_end_km3': round(total_volume_end, 4),
            'volume_change_pct': round(
                (total_volume_end - total_volume_start) / total_volume_start * 100
                if total_volume_start > 0 else 0, 1
            ),
            'total_area_start_km2': round(total_area_start, 2),
            'total_area_end_km2': round(total_area_end, 2)
        }

        print(f"\nBasin-level summary:")
        print(f"  Volume: {total_volume_start:.4f} -> {total_volume_end:.4f} km3")
        print(f"  Area: {total_area_start:.2f} -> {total_area_end:.2f} km2")

        ds.close()

    except ImportError:
        print("ERROR: OGGM not installed")
        result = {'status': 'error', 'message': 'OGGM not installed'}

    except Exception as e:
        print(f"ERROR: {e}")
        result = {'status': 'error', 'message': str(e)}

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
