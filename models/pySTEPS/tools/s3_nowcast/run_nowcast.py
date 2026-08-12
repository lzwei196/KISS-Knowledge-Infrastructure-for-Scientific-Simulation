#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      run_nowcast
Stage:        s3_nowcast
Description:  Run pySTEPS deterministic or ensemble nowcast using motion field and radar data.

CRITICAL:
  - Input data must be in mm/h, NOT dBZ.
  - For STEPS ensemble: n_ens_members >= 20 for stable probabilities.
  - Memory scales as O(n_ens * n_cascade * ny * nx). Monitor RAM for large domains.
  - STEPS works in log (dBR) space internally — output is converted back to mm/h.

Inputs:
  --input_dir:       Directory with radar_frames.npz and metadata.json (from s1)
  --motion_dir:      Directory with motion_field.npz (from s2)
  --method:          Nowcast method: extrapolation, steps, anvil (default: steps)
  --n_leadtimes:     Number of forecast time steps (default: 12)
  --n_ens_members:   Ensemble members for STEPS (default: 24, min 20 for probabilities)
  --n_cascade_levels: Cascade levels for STEPS (default: 6)
  --noise_method:    Noise method: nonparametric, parametric, None (default: nonparametric)
  --seed:            Random seed for reproducibility (default: None for random)
  --output_dir:      Output directory

Outputs:
  - nowcast.npz:        Forecast array (n_ens, n_leadtimes, ny, nx) or (n_leadtimes, ny, nx)
  - nowcast_summary.json: Summary with timing, method, parameters
  - exceedance_prob.npz: Probability of exceedance maps (if ensemble)

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
        errors.append(f"radar_frames.npz not found in {input_dir}")
    motion_dir = Path(args.motion_dir)
    if not (motion_dir / 'motion_field.npz').exists():
        errors.append(f"motion_field.npz not found in {motion_dir}. Run s2 first.")
    if args.method not in ['extrapolation', 'steps', 'anvil']:
        errors.append(f"Unknown method: {args.method}. Use extrapolation, steps, or anvil")
    if args.method == 'steps' and args.n_ens_members < 2:
        errors.append("STEPS requires n_ens_members >= 2 (recommend >= 20)")
    if args.n_leadtimes < 1:
        errors.append("n_leadtimes must be >= 1")
    return errors


def estimate_memory_gb(method, n_ens, n_cascade, ny, nx):
    """Estimate peak memory usage in GB."""
    if method == 'extrapolation':
        return ny * nx * 8 * 10 / 1e9  # Modest
    # STEPS: cascade decomposition + noise + ensemble
    return n_ens * n_cascade * 2 * ny * nx * 8 / 1e9


def run(args):
    import pysteps
    from pysteps import nowcasts
    from pysteps.utils import conversion, transformation
    import time as _time

    input_dir = Path(args.input_dir)
    motion_dir = Path(args.motion_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load data
    frames = np.load(input_dir / 'radar_frames.npz')['data']
    meta = json.loads((input_dir / 'metadata.json').read_text())
    V = np.load(motion_dir / 'motion_field.npz')['V']

    ny, nx = frames.shape[1], frames.shape[2]
    logger.info(f"Loaded {frames.shape[0]} frames ({ny}x{nx}), motion field ready")

    # Memory check
    mem_gb = estimate_memory_gb(args.method, args.n_ens_members,
                                 args.n_cascade_levels, ny, nx)
    logger.info(f"Estimated peak memory: {mem_gb:.1f} GB")
    if mem_gb > 16:
        logger.warning(f"Memory estimate ({mem_gb:.1f} GB) exceeds 16 GB. "
                        "Consider reducing n_ens_members or domain size.")

    # Get nowcast method
    method = args.method
    logger.info(f"Running {method} nowcast: {args.n_leadtimes} lead times")

    t0 = _time.time()

    if method == 'extrapolation':
        extrapolator = nowcasts.get_method('extrapolation')
        forecast = extrapolator(frames[-1], V, args.n_leadtimes)
        # Shape: (n_leadtimes, ny, nx)

    elif method == 'steps':
        # STEPS requires log-transformed input
        R = frames.copy()
        R[R < 0.1] = 0.0  # Threshold

        # Transform to dBR for STEPS
        R_dbr = np.zeros_like(R)
        mask = R > 0
        R_dbr[mask] = 10.0 * np.log10(R[mask])
        R_dbr[~mask] = -15.0  # Below threshold value

        steps_nowcast = nowcasts.get_method('steps')

        seed = args.seed if args.seed is not None else None

        forecast_dbr = steps_nowcast(
            R_dbr, V, args.n_leadtimes,
            n_ens_members=args.n_ens_members,
            n_cascade_levels=args.n_cascade_levels,
            noise_method=args.noise_method if args.noise_method != 'None' else None,
            R_thr=-10.0,
            kmperpixel=meta.get('xpixelsize', 1.0),
            timestep=meta.get('accutime', 5),
            seed=seed,
        )
        # Shape: (n_ens, n_leadtimes, ny, nx) in dBR

        # Convert back to mm/h
        forecast = 10.0 ** (forecast_dbr / 10.0)
        forecast[forecast_dbr < -10.0] = 0.0
        forecast = np.clip(forecast, 0, None)

    elif method == 'anvil':
        anvil_nowcast = nowcasts.get_method('anvil')
        forecast = anvil_nowcast(
            frames, V, args.n_leadtimes,
            n_cascade_levels=args.n_cascade_levels,
        )

    elapsed = _time.time() - t0
    logger.info(f"Nowcast completed in {elapsed:.2f}s")

    # Clip negative values (numerical artifacts)
    forecast = np.clip(forecast, 0, None)

    # Save forecast
    np.savez_compressed(output_dir / 'nowcast.npz', forecast=forecast)

    # Exceedance probabilities for ensemble
    if method == 'steps' and forecast.ndim == 4:
        thresholds = [0.1, 1.0, 5.0, 10.0, 20.0]
        prob_maps = {}
        for thr in thresholds:
            prob = np.mean(forecast > thr, axis=0)  # Average over ensemble
            prob_maps[f'prob_gt_{thr}'] = prob
        np.savez_compressed(output_dir / 'exceedance_prob.npz', **prob_maps)
        logger.info(f"Exceedance probability maps saved for thresholds: {thresholds}")

    # Summary
    summary = {
        'method': method,
        'n_leadtimes': args.n_leadtimes,
        'n_ens_members': args.n_ens_members if method == 'steps' else 1,
        'n_cascade_levels': args.n_cascade_levels,
        'noise_method': args.noise_method,
        'grid_shape': [ny, nx],
        'forecast_shape': list(forecast.shape),
        'elapsed_s': round(elapsed, 3),
        'forecast_range': {
            'min': float(np.nanmin(forecast)),
            'max': float(np.nanmax(forecast)),
            'mean': float(np.nanmean(forecast)),
        },
        'timestep_min': meta.get('accutime', 5),
        'forecast_horizon_min': args.n_leadtimes * meta.get('accutime', 5),
        'unit': 'mm/h',
        'estimated_memory_gb': round(mem_gb, 2),
    }
    (output_dir / 'nowcast_summary.json').write_text(json.dumps(summary, indent=2))

    logger.info(f"Forecast saved to {output_dir}: shape={forecast.shape}, "
                f"horizon={summary['forecast_horizon_min']} min")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Run pySTEPS precipitation nowcast")
    parser.add_argument('--input_dir', required=True, help="Directory with radar_frames.npz")
    parser.add_argument('--motion_dir', required=True, help="Directory with motion_field.npz")
    parser.add_argument('--method', default='steps',
                        help="Nowcast method: extrapolation, steps, anvil")
    parser.add_argument('--n_leadtimes', type=int, default=12, help="Forecast time steps")
    parser.add_argument('--n_ens_members', type=int, default=24, help="Ensemble members (STEPS)")
    parser.add_argument('--n_cascade_levels', type=int, default=6, help="Cascade levels (STEPS)")
    parser.add_argument('--noise_method', default='nonparametric',
                        help="Noise method: nonparametric, parametric, None")
    parser.add_argument('--seed', type=int, default=None, help="Random seed")
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
