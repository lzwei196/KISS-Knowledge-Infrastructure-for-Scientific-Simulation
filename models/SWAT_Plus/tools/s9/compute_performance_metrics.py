#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
Tool ID:      compute_performance_metrics
Stage:        s9_output_parsing
Description:  Compute NSE, PBIAS, KGE, R2, RMSE between simulated and observed discharge.

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys, os, logging, json, math
from pathlib import Path

SIMULATED = ""  # JSON array or CSV path
OBSERVED = ""   # JSON array or CSV path

if len(sys.argv) >= 3:
    SIMULATED = sys.argv[1]
    OBSERVED = sys.argv[2]

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def validate_inputs():
    errors = []
    if not SIMULATED:
        errors.append("Simulated data not provided")
    if not OBSERVED:
        errors.append("Observed data not provided")
    if errors:
        for e in errors: logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")

def compute_nse(sim, obs):
    """Nash-Sutcliffe Efficiency."""
    obs_mean = sum(obs) / len(obs)
    numerator = sum((o - s) ** 2 for o, s in zip(obs, sim))
    denominator = sum((o - obs_mean) ** 2 for o in obs)
    return 1 - numerator / denominator if denominator > 0 else float('-inf')

def compute_pbias(sim, obs):
    """Percent Bias."""
    return 100 * sum(o - s for o, s in zip(obs, sim)) / sum(obs) if sum(obs) != 0 else float('inf')

def compute_kge(sim, obs):
    """Kling-Gupta Efficiency."""
    n = len(sim)
    sim_mean = sum(sim) / n
    obs_mean = sum(obs) / n
    sim_std = math.sqrt(sum((s - sim_mean) ** 2 for s in sim) / n)
    obs_std = math.sqrt(sum((o - obs_mean) ** 2 for o in obs) / n)

    if obs_std == 0 or sim_std == 0:
        return float('-inf')

    r = sum((s - sim_mean) * (o - obs_mean) for s, o in zip(sim, obs)) / (n * sim_std * obs_std)
    beta = sim_mean / obs_mean if obs_mean != 0 else float('inf')
    gamma = (sim_std / sim_mean) / (obs_std / obs_mean) if sim_mean != 0 and obs_mean != 0 else float('inf')

    return 1 - math.sqrt((r - 1) ** 2 + (beta - 1) ** 2 + (gamma - 1) ** 2)

def compute_rmse(sim, obs):
    """Root Mean Square Error."""
    return math.sqrt(sum((o - s) ** 2 for o, s in zip(obs, sim)) / len(obs))

def compute_r2(sim, obs):
    """Coefficient of determination."""
    n = len(sim)
    sim_mean = sum(sim) / n
    obs_mean = sum(obs) / n
    sim_std = math.sqrt(sum((s - sim_mean) ** 2 for s in sim) / n)
    obs_std = math.sqrt(sum((o - obs_mean) ** 2 for o in obs) / n)
    if sim_std == 0 or obs_std == 0:
        return 0.0
    r = sum((s - sim_mean) * (o - obs_mean) for s, o in zip(sim, obs)) / (n * sim_std * obs_std)
    return r ** 2

def rate_performance(nse, pbias):
    """Moriasi et al. (2007) performance ratings."""
    if nse > 0.75 and abs(pbias) < 10:
        return "Very Good"
    elif nse > 0.65 and abs(pbias) < 15:
        return "Good"
    elif nse > 0.50 and abs(pbias) < 25:
        return "Satisfactory"
    else:
        return "Unsatisfactory"

def process():
    # Parse inputs (support JSON arrays or CSV files)
    if Path(SIMULATED).exists():
        # CSV file
        sim_data = []
        for line in Path(SIMULATED).read_text().strip().split('\n')[1:]:
            parts = line.split(',')
            if len(parts) >= 2:
                sim_data.append(float(parts[1]))
    else:
        sim_data = json.loads(SIMULATED)

    if Path(OBSERVED).exists():
        obs_data = []
        for line in Path(OBSERVED).read_text().strip().split('\n')[1:]:
            parts = line.split(',')
            if len(parts) >= 2:
                obs_data.append(float(parts[1]))
    else:
        obs_data = json.loads(OBSERVED)

    # Ensure same length
    n = min(len(sim_data), len(obs_data))
    sim = sim_data[:n]
    obs = obs_data[:n]

    if n < 30:
        logger.warning(f"Only {n} data points — metrics may be unreliable")

    nse = compute_nse(sim, obs)
    pbias = compute_pbias(sim, obs)
    kge = compute_kge(sim, obs)
    rmse = compute_rmse(sim, obs)
    r2 = compute_r2(sim, obs)
    rating = rate_performance(nse, pbias)

    logger.info(f"NSE={nse:.3f}, PBIAS={pbias:.1f}%, KGE={kge:.3f}, RMSE={rmse:.2f}, R2={r2:.3f} [{rating}]")

    return {
        "status": "success",
        "n_points": n,
        "metrics": {
            "NSE": round(nse, 4),
            "PBIAS": round(pbias, 2),
            "KGE": round(kge, 4),
            "R2": round(r2, 4),
            "RMSE": round(rmse, 3)
        },
        "rating": rating
    }

def validate_outputs(result):
    logger.info(f"Performance rating: {result['rating']}")

if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try: result = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}"); sys.exit(2)
    validate_outputs(result)
    print(json.dumps(result, indent=2)); sys.exit(0)
