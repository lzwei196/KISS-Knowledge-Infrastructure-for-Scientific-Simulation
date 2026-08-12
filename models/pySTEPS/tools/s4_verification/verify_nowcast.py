#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      verify_nowcast
Stage:        s4_verification
Description:  Verify nowcast against observed radar frames using standard skill scores.

CRITICAL:
  - Nowcast and observation must have the same shape (n_leadtimes, ny, nx).
  - Threshold for categorical scores must be in mm/h (same unit as data).
  - For ensemble: compute scores per member and average, or use probabilistic scores.

Inputs:
  --nowcast_dir:    Directory with nowcast.npz (from s3)
  --obs_dir:        Directory with observed frames (radar_frames.npz from s1, future frames)
  --thresholds:     Rainfall thresholds in mm/h for categorical scores (default: 0.1,1.0,5.0)
  --fss_scales:     FSS spatial scales in pixels (default: 1,5,10,20)
  --output_dir:     Output directory

Outputs:
  - verification_scores.json:  Per-leadtime and mean scores (CSI, POD, FAR, HSS, FSS, RMSE, NSE, r)
  - verification_summary.json: Summary with best/worst lead times

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
    if not (Path(args.nowcast_dir) / 'nowcast.npz').exists():
        errors.append(f"nowcast.npz not found in {args.nowcast_dir}. Run s3 first.")
    if not (Path(args.obs_dir) / 'radar_frames.npz').exists():
        errors.append(f"Observed radar_frames.npz not found in {args.obs_dir}")
    return errors


def compute_contingency(forecast, observed, threshold):
    """Compute contingency table counts."""
    f_above = forecast >= threshold
    o_above = observed >= threshold
    hits = np.sum(f_above & o_above)
    misses = np.sum(~f_above & o_above)
    false_alarms = np.sum(f_above & ~o_above)
    correct_negatives = np.sum(~f_above & ~o_above)
    return int(hits), int(misses), int(false_alarms), int(correct_negatives)


def compute_categorical_scores(hits, misses, false_alarms, correct_negatives):
    """Compute categorical verification scores from contingency table."""
    scores = {}
    total = hits + misses + false_alarms + correct_negatives

    # CSI (Critical Success Index / Threat Score)
    denom = hits + misses + false_alarms
    scores['CSI'] = hits / denom if denom > 0 else float('nan')

    # POD (Probability of Detection / Hit Rate)
    denom = hits + misses
    scores['POD'] = hits / denom if denom > 0 else float('nan')

    # FAR (False Alarm Ratio)
    denom = hits + false_alarms
    scores['FAR'] = false_alarms / denom if denom > 0 else float('nan')

    # HSS (Heidke Skill Score)
    expected = ((hits + misses) * (hits + false_alarms) +
                (correct_negatives + misses) * (correct_negatives + false_alarms)) / total if total > 0 else 0
    scores['HSS'] = (hits + correct_negatives - expected) / (total - expected) if (total - expected) != 0 else float('nan')

    return scores


def compute_fss(forecast, observed, threshold, scale):
    """Compute Fractions Skill Score at a given scale."""
    from scipy.ndimage import uniform_filter

    f_binary = (forecast >= threshold).astype(float)
    o_binary = (observed >= threshold).astype(float)

    f_frac = uniform_filter(f_binary, size=scale, mode='constant')
    o_frac = uniform_filter(o_binary, size=scale, mode='constant')

    mse = np.mean((f_frac - o_frac) ** 2)
    ref = np.mean(f_frac ** 2) + np.mean(o_frac ** 2)

    return 1.0 - mse / ref if ref > 0 else float('nan')


def compute_continuous_scores(forecast, observed):
    """Compute continuous verification scores: RMSE, MAE, NSE, r."""
    scores = {}
    mask = np.isfinite(forecast) & np.isfinite(observed)
    f = forecast[mask]
    o = observed[mask]

    if len(f) == 0:
        return {'RMSE': float('nan'), 'MAE': float('nan'), 'NSE': float('nan'), 'r': float('nan')}

    scores['RMSE'] = float(np.sqrt(np.mean((f - o) ** 2)))
    scores['MAE'] = float(np.mean(np.abs(f - o)))

    # NSE
    ss_res = np.sum((f - o) ** 2)
    ss_tot = np.sum((o - np.mean(o)) ** 2)
    scores['NSE'] = float(1.0 - ss_res / ss_tot) if ss_tot > 0 else float('nan')

    # Pearson r
    if np.std(f) > 0 and np.std(o) > 0:
        scores['r'] = float(np.corrcoef(f, o)[0, 1])
    else:
        scores['r'] = float('nan')

    return scores


def run(args):
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load nowcast
    nowcast_data = np.load(Path(args.nowcast_dir) / 'nowcast.npz')['forecast']
    obs_data = np.load(Path(args.obs_dir) / 'radar_frames.npz')['data']

    # Handle ensemble: use ensemble mean for deterministic scores
    is_ensemble = nowcast_data.ndim == 4
    if is_ensemble:
        n_ens = nowcast_data.shape[0]
        logger.info(f"Ensemble nowcast with {n_ens} members — using mean for deterministic scores")
        nowcast_mean = np.mean(nowcast_data, axis=0)
    else:
        nowcast_mean = nowcast_data
        n_ens = 1

    n_leadtimes = nowcast_mean.shape[0]
    n_obs = obs_data.shape[0]

    # Match lead times to observation frames
    n_compare = min(n_leadtimes, n_obs)
    if n_compare < n_leadtimes:
        logger.warning(f"Only {n_obs} observation frames available for {n_leadtimes} lead times")

    logger.info(f"Verifying {n_compare} lead times, grid: {nowcast_mean.shape[1]}x{nowcast_mean.shape[2]}")

    # Parse thresholds and scales
    thresholds = [float(t) for t in args.thresholds.split(',')]
    fss_scales = [int(s) for s in args.fss_scales.split(',')]

    # Compute scores per lead time
    results = {'per_leadtime': [], 'mean_scores': {}, 'parameters': {}}

    for lt in range(n_compare):
        fc = nowcast_mean[lt]
        ob = obs_data[lt]

        lt_scores = {'leadtime': lt + 1}

        # Continuous scores
        cont = compute_continuous_scores(fc, ob)
        lt_scores.update(cont)

        # Categorical scores per threshold
        for thr in thresholds:
            h, m, fa, cn = compute_contingency(fc, ob, thr)
            cat = compute_categorical_scores(h, m, fa, cn)
            for k, v in cat.items():
                lt_scores[f'{k}_thr{thr}'] = round(v, 6) if not np.isnan(v) else None

        # FSS per scale (using first threshold)
        for scale in fss_scales:
            try:
                fss_val = compute_fss(fc, ob, thresholds[0], scale)
                lt_scores[f'FSS_scale{scale}'] = round(fss_val, 6) if not np.isnan(fss_val) else None
            except Exception as e:
                lt_scores[f'FSS_scale{scale}'] = None
                logger.warning(f"FSS scale={scale} failed at lt={lt}: {e}")

        results['per_leadtime'].append(lt_scores)

    # Compute mean scores across lead times
    score_keys = [k for k in results['per_leadtime'][0] if k != 'leadtime']
    for k in score_keys:
        vals = [lt[k] for lt in results['per_leadtime'] if lt[k] is not None]
        results['mean_scores'][k] = round(float(np.mean(vals)), 6) if vals else None

    results['parameters'] = {
        'n_leadtimes_verified': n_compare,
        'n_ens_members': n_ens,
        'thresholds_mmh': thresholds,
        'fss_scales_px': fss_scales,
        'grid_shape': [int(nowcast_mean.shape[1]), int(nowcast_mean.shape[2])],
    }

    # Save
    (output_dir / 'verification_scores.json').write_text(
        json.dumps(results, indent=2, default=str))

    # Summary
    mean = results['mean_scores']
    summary = {
        'mean_NSE': mean.get('NSE'),
        'mean_r': mean.get('r'),
        'mean_RMSE': mean.get('RMSE'),
        'mean_CSI': mean.get(f'CSI_thr{thresholds[0]}'),
        'mean_FSS': mean.get(f'FSS_scale{fss_scales[-1]}'),
        'best_leadtime': None,
        'worst_leadtime': None,
    }

    # Find best/worst lead time by NSE
    nse_vals = [(lt['leadtime'], lt['NSE']) for lt in results['per_leadtime']
                if lt['NSE'] is not None]
    if nse_vals:
        summary['best_leadtime'] = max(nse_vals, key=lambda x: x[1])[0]
        summary['worst_leadtime'] = min(nse_vals, key=lambda x: x[1])[0]

    (output_dir / 'verification_summary.json').write_text(json.dumps(summary, indent=2))

    logger.info(f"Verification complete: mean NSE={mean.get('NSE')}, "
                f"mean CSI(>{thresholds[0]})={mean.get(f'CSI_thr{thresholds[0]}')}, "
                f"mean r={mean.get('r')}")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Verify pySTEPS nowcast against observations")
    parser.add_argument('--nowcast_dir', required=True, help="Directory with nowcast.npz")
    parser.add_argument('--obs_dir', required=True, help="Directory with observed radar_frames.npz")
    parser.add_argument('--thresholds', default='0.1,1.0,5.0',
                        help="Rainfall thresholds in mm/h (comma-separated)")
    parser.add_argument('--fss_scales', default='1,5,10,20',
                        help="FSS scales in pixels (comma-separated)")
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
