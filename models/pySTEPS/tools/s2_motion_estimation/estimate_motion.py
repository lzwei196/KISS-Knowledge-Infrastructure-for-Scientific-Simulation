#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      estimate_motion
Stage:        s2_motion_estimation
Description:  Estimate precipitation motion field from radar frame sequence using optical flow.

CRITICAL:
  - Input must be in mm/h (NOT dBZ). Convert first using s1_data_import.
  - At least 2 consecutive frames required.
  - Lucas-Kanade is robust for most cases. Use Proesmans for uniform translation.
  - VET/DARTS handle rotational/divergent flow but are slower.

Inputs:
  --input_dir:     Directory with radar_frames.npz and metadata.json from s1
  --method:        Motion method: LK, VET, proesmans, DARTS (default: LK)
  --max_corners:   Max features for Lucas-Kanade (default: 500)
  --quality_level: Feature quality threshold for LK (default: 0.1)
  --win_size:      LK window size in pixels (default: 50)
  --output_dir:    Output directory

Outputs:
  - motion_field.npz:  NumPy archive with 'V' (2, ny, nx) motion vectors in px/frame
  - motion_summary.json: Summary with method, mean velocity, max velocity

Exit codes:
  0 — success, 1 — input error, 2 — processing error, 3 — output error
"""

import sys
import os
import json
import logging
import argparse
import numpy as np
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def validate_inputs(args):
    errors = []
    input_dir = Path(args.input_dir)
    if not (input_dir / 'radar_frames.npz').exists():
        errors.append(f"radar_frames.npz not found in {input_dir}. Run s1_data_import first.")
    if args.method not in ['LK', 'VET', 'proesmans', 'DARTS']:
        errors.append(f"Unknown method: {args.method}. Use LK, VET, proesmans, or DARTS")
    if args.max_corners < 10:
        errors.append("max_corners must be >= 10")
    return errors


def run(args):
    import pysteps
    from pysteps import motion

    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load data
    frames = np.load(input_dir / 'radar_frames.npz')['data']
    meta = json.loads((input_dir / 'metadata.json').read_text())

    logger.info(f"Loaded {frames.shape[0]} frames ({frames.shape[1]}x{frames.shape[2]})")

    # Verify units
    unit = meta.get('unit', 'unknown')
    if unit == 'dBZ':
        logger.error("Input is in dBZ — must convert to mm/h first (run s1 with --convert_to_mmh)")
        return 1

    if frames.shape[0] < 2:
        logger.error("Need at least 2 frames for motion estimation")
        return 1

    # Get motion estimator
    method = args.method
    logger.info(f"Estimating motion field using {method}")

    oflow = motion.get_method(method)

    # Configure method-specific kwargs
    kwargs = {}
    if method == 'LK':
        kwargs['fd_method'] = 'shitomasi'
        kwargs['fd_kwargs'] = {
            'maxCorners': args.max_corners,
            'qualityLevel': args.quality_level,
        }
        kwargs['lk_kwargs'] = {
            # pysteps.tracking.lucaskanade.track_features takes `winsize`
            # (lowercase s), NOT OpenCV's camelCase `winSize`. Passing winSize
            # made the DEFAULT method (LK) die with
            # "track_features() got an unexpected keyword argument 'winSize'"
            # on pysteps 1.20.0 (found 2026-08-11).
            'winsize': (args.win_size, args.win_size),
        }
    elif method == 'VET':
        kwargs['n_iter'] = 5

    # Estimate motion
    import time as _time
    t0 = _time.time()
    V = oflow(frames, **kwargs)
    elapsed = _time.time() - t0

    logger.info(f"Motion estimation completed in {elapsed:.2f}s")

    # Validate motion field
    if np.all(V == 0):
        logger.warning("Motion field is all zero — no movement detected. "
                        "Try increasing maxCorners or decreasing qualityLevel.")
    if np.any(np.isnan(V)):
        nan_frac = np.isnan(V).mean()
        logger.warning(f"Motion field has {nan_frac:.1%} NaN values")
        V = np.nan_to_num(V, nan=0.0)

    # Compute statistics
    speed = np.sqrt(V[0] ** 2 + V[1] ** 2)
    mean_speed = float(np.mean(speed[speed > 0])) if np.any(speed > 0) else 0.0
    max_speed = float(np.max(speed))

    # Convert to km/h for reporting
    pixel_size_km = meta.get('xpixelsize', 1.0) / 1000.0 if meta.get('xpixelsize', 1.0) > 100 else meta.get('xpixelsize', 1.0)
    timestep_h = meta.get('accutime', 5) / 60.0
    mean_speed_kmh = mean_speed * pixel_size_km / timestep_h if timestep_h > 0 else 0.0
    max_speed_kmh = max_speed * pixel_size_km / timestep_h if timestep_h > 0 else 0.0

    logger.info(f"Mean motion: {mean_speed:.2f} px/frame ({mean_speed_kmh:.1f} km/h)")
    logger.info(f"Max motion:  {max_speed:.2f} px/frame ({max_speed_kmh:.1f} km/h)")

    # Save
    np.savez_compressed(output_dir / 'motion_field.npz', V=V)

    summary = {
        'method': method,
        'n_input_frames': int(frames.shape[0]),
        'grid_shape': [int(frames.shape[1]), int(frames.shape[2])],
        'mean_speed_px_per_frame': round(mean_speed, 3),
        'max_speed_px_per_frame': round(max_speed, 3),
        'mean_speed_kmh': round(mean_speed_kmh, 1),
        'max_speed_kmh': round(max_speed_kmh, 1),
        'elapsed_s': round(elapsed, 3),
        'method_kwargs': {k: str(v) for k, v in kwargs.items()},
    }
    (output_dir / 'motion_summary.json').write_text(json.dumps(summary, indent=2))

    logger.info(f"Motion field saved to {output_dir}")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Estimate precipitation motion field")
    parser.add_argument('--input_dir', required=True, help="Directory with radar_frames.npz")
    parser.add_argument('--method', default='LK', help="Motion method: LK, VET, proesmans, DARTS")
    parser.add_argument('--max_corners', type=int, default=500, help="Max features for LK")
    parser.add_argument('--quality_level', type=float, default=0.1, help="Feature quality for LK")
    parser.add_argument('--win_size', type=int, default=50, help="LK window size in pixels")
    parser.add_argument('--output_dir', required=True, help="Output directory")
    args = parser.parse_args()

    errors = validate_inputs(args)
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)

    try:
        sys.exit(run(args))
    except Exception as e:
        logger.error(f"Processing error: {e}")
        sys.exit(2)


if __name__ == '__main__':
    main()
