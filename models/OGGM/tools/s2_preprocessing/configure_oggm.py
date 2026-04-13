#!/usr/bin/env python3
"""
Configure OGGM — OGGM Knowledge Infrastructure

Initialize OGGM configuration with working directory, DEM source,
multiprocessing settings, and download verification.

Usage:
    python configure_oggm.py \
        --working_dir outputs/oggm/working_dir \
        --border 80 --multiprocessing true
"""

import argparse
import json
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(
        description="Initialize OGGM configuration"
    )
    parser.add_argument("--working_dir", required=True,
                        help="OGGM working directory for glacier data")
    parser.add_argument("--border", type=int, default=80,
                        help="DEM border pixels (default 80)")
    parser.add_argument("--multiprocessing", default="true",
                        help="Enable multiprocessing: true/false (default true)")
    parser.add_argument("--dl_verify", default="true",
                        help="Verify downloads: true/false (default true)")
    parser.add_argument("--dem_source", default=None,
                        help="DEM source: COPDEM, SRTM, NASADEM, AW3D30")
    args = parser.parse_args()

    working_dir = Path(args.working_dir)
    working_dir.mkdir(parents=True, exist_ok=True)

    use_mp = args.multiprocessing.lower() == 'true'
    verify = args.dl_verify.lower() == 'true'

    try:
        import oggm
        from oggm import cfg

        # Initialize with default parameters
        cfg.initialize(logging_level='WARNING')

        # Set working directory
        cfg.PATHS['working_dir'] = str(working_dir)

        # Set parameters
        cfg.PARAMS['border'] = args.border
        cfg.PARAMS['use_multiprocessing'] = use_mp
        cfg.PARAMS['dl_verify'] = verify

        if args.dem_source:
            cfg.PARAMS['dem_source'] = args.dem_source

        # Set matplotlib to non-interactive backend for headless servers
        import matplotlib
        matplotlib.use('Agg')

        result = {
            'status': 'success',
            'working_dir': str(working_dir),
            'border': args.border,
            'multiprocessing': use_mp,
            'dl_verify': verify,
            'dem_source': args.dem_source or 'auto',
            'oggm_version': oggm.__version__,
            'base_url': cfg.PARAMS.get('dl_base_url', 'default')
        }

        print(f"OGGM v{oggm.__version__} configured successfully")
        print(f"Working directory: {working_dir}")
        print(f"Border: {args.border} pixels")
        print(f"Multiprocessing: {use_mp}")

    except ImportError:
        print("ERROR: OGGM not installed.")
        print("Install: conda install -c conda-forge oggm")
        print("Or: pip install oggm")
        result = {
            'status': 'error',
            'message': 'OGGM not installed',
            'install_cmd': 'conda install -c conda-forge oggm'
        }

    except Exception as e:
        print(f"ERROR: OGGM configuration failed: {e}")
        result = {
            'status': 'error',
            'message': str(e)
        }

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
