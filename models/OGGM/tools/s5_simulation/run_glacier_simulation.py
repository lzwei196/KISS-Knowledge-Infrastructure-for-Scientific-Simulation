#!/usr/bin/env python3
"""
Run Glacier Simulation — OGGM Knowledge Infrastructure

Run historical glacier dynamics simulation with hydrological output.

Usage:
    python run_glacier_simulation.py \
        --working_dir outputs/oggm/working_dir \
        --start_year 2000 --end_year 2020 \
        --use_spinup true
"""

import argparse
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="Run OGGM glacier dynamics simulation"
    )
    parser.add_argument("--working_dir", required=True,
                        help="OGGM working directory with calibrated GDirs")
    parser.add_argument("--start_year", type=int, required=True,
                        help="Simulation start year")
    parser.add_argument("--end_year", type=int, required=True,
                        help="Simulation end year")
    parser.add_argument("--use_spinup", default="true",
                        help="Use dynamic spinup: true/false (default true)")
    parser.add_argument("--model_type", default="FluxBased",
                        choices=["FluxBased", "SemiImplicit"],
                        help="Flowline model type (default FluxBased)")
    parser.add_argument("--output_suffix", default="",
                        help="Suffix for output files")
    args = parser.parse_args()

    working_dir = Path(args.working_dir)
    use_spinup = args.use_spinup.lower() == 'true'
    suffix = args.output_suffix if args.output_suffix else '_historical'

    print(f"Running glacier simulation: {args.start_year}-{args.end_year}")
    print(f"Model: {args.model_type}")
    print(f"Spinup: {use_spinup}")

    try:
        from oggm import cfg, workflow, tasks, utils

        if not cfg.PATHS.get('working_dir'):
            cfg.initialize(logging_level='WARNING')
            cfg.PATHS['working_dir'] = str(working_dir)
        # Required for run_with_hydro in OGGM v1.6+
        cfg.PARAMS['store_model_geometry'] = True
        cfg.PARAMS['dl_verify'] = False

        # Load GDirs — OGGM layout nests per_glacier/RGIxx-NN/RGIxx-NN.YY/RGIxx-NN.YYZZZ/
        import re as _re
        per_glacier = working_dir / 'per_glacier'
        rgi_ids = []
        _pat = _re.compile(r'^RGI\d+-\d+\.\d{5}$')
        if per_glacier.exists():
            for p in per_glacier.rglob('*'):
                if p.is_dir() and _pat.match(p.name):
                    rgi_ids.append(p.name)

        gdirs = workflow.init_glacier_directories(rgi_ids, reset=False)
        print(f"Simulating {len(gdirs)} glaciers...")

        # Select run task based on spinup
        if use_spinup:
            run_task = tasks.run_dynamic_spinup
            print("Using dynamic spinup...")
        else:
            run_task = tasks.run_from_climate_data
            print("Starting from RGI geometry (no spinup)...")

        # Run simulation with hydro output
        print("Running dynamics with hydrological output...")
        print("(store_monthly_hydro=True for VIC coupling)")

        workflow.execute_entity_task(
            tasks.run_with_hydro, gdirs,
            run_task=run_task,
            min_ys=args.start_year,
            max_ys=args.end_year,
            store_monthly_hydro=True,
            output_filesuffix=suffix
        )

        # Check results
        simulated = 0
        failed = 0
        failed_ids = []

        for gdir in gdirs:
            diag = Path(gdir.dir) / f'model_diagnostics{suffix}.nc'
            hydro = Path(gdir.dir) / f'run_output_hydro{suffix}.nc'

            if diag.exists():
                simulated += 1
            else:
                failed += 1
                failed_ids.append(gdir.rgi_id)

        # Get volume summary from first/last glacier
        vol_start = None
        vol_end = None
        if simulated > 0:
            try:
                import xarray as xr
                total_vol_start = 0
                total_vol_end = 0
                for gdir in gdirs:
                    diag = Path(gdir.dir) / f'model_diagnostics{suffix}.nc'
                    if diag.exists():
                        ds = xr.open_dataset(diag)
                        if 'volume_m3' in ds:
                            total_vol_start += float(ds['volume_m3'].values[0])
                            total_vol_end += float(ds['volume_m3'].values[-1])
                        ds.close()
                vol_start = total_vol_start / 1e9  # m3 to km3
                vol_end = total_vol_end / 1e9
            except Exception:
                pass

        result = {
            'status': 'success' if failed == 0 else 'partial',
            'glaciers_simulated': simulated,
            'glaciers_failed': failed,
            'period': f"{args.start_year}-{args.end_year}",
            'model_type': args.model_type,
            'spinup': use_spinup,
            'output_suffix': suffix
        }

        if vol_start is not None:
            result['total_volume_start_km3'] = round(vol_start, 4)
            result['total_volume_end_km3'] = round(vol_end, 4)
            result['volume_change_pct'] = round(
                (vol_end - vol_start) / vol_start * 100 if vol_start > 0 else 0, 1
            )

        if failed_ids:
            result['failed_rgi_ids'] = failed_ids[:20]

        print(f"\nSimulation complete: {simulated}/{len(gdirs)} glaciers")
        if vol_start is not None:
            print(f"Volume: {vol_start:.4f} -> {vol_end:.4f} km3 "
                  f"({result.get('volume_change_pct', '?')}%)")

    except ImportError:
        print("ERROR: OGGM not installed. Run: conda install -c conda-forge oggm")
        result = {'status': 'error', 'message': 'OGGM not installed'}

    except Exception as e:
        print(f"ERROR: {e}")
        result = {'status': 'error', 'message': str(e)}

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
