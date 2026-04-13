#!/usr/bin/env python3
"""
parse_rzwqm2_output.py
======================
Extract key simulation outputs from RZWQM2 .ana files and compute calibration
metrics against observed data (yield, soil moisture).

Extracts:
    - Annual grain yield (kg/ha) — peak of column 44 per crop year
    - Daily stored soil water (cm) — column 2
    - Annual ET (cm) — sum of column 84

Returns metrics: yield_RMSE, soil_moisture_NSE, combined_score.

Usage:
    python parse_rzwqm2_output.py <scenario_dir> [--obs_yield <file>] [--obs_sm <file>]

Observed yield CSV format:  year,yield_kgha
Observed soil moisture CSV: date,sm_cm  (daily, stored water in cm)

Exit codes: 0=success, 1=input error, 2=processing error
"""
import sys
import os
import json
import csv
import math
from datetime import datetime


def parse_ana(ana_path):
    """Parse .ana file, return dict of {date: [columns]} for all data lines."""
    with open(ana_path, encoding='ISO-8859-1') as f:
        lines = f.readlines()

    # Find data start (after ===... separator)
    data_start = 0
    for i, line in enumerate(lines):
        if line.strip().startswith('===='):
            data_start = i + 1
            break

    records = []
    for line in lines[data_start:]:
        parts = line.split()
        if len(parts) < 44:
            continue
        try:
            time_str = parts[0]  # YYYY.DDD
            yr_str, doy_str = time_str.split('.')
            year = int(yr_str)
            doy = int(doy_str)
            dt = datetime.strptime(f"{year}.{doy:03d}", "%Y.%j")
            vals = [float(x) for x in parts[1:]]
            records.append((dt, year, doy, vals))
        except (ValueError, IndexError):
            continue

    return records


def extract_annual_yield(records):
    """Extract peak grain yield (col 44, index 43-1=42 in vals) per year.

    Returns dict: {year: max_yield_kgha}
    """
    yearly_max = {}
    for dt, year, doy, vals in records:
        if len(vals) > 42:
            grain = vals[42]  # column 44 = BIOMASS OF GRAIN (KG/HA)
            if year not in yearly_max or grain > yearly_max[year]:
                yearly_max[year] = grain
    return yearly_max


def extract_daily_soil_water(records):
    """Extract daily stored soil water (col 2, index 0 in vals).

    Returns dict: {date: stored_water_cm}
    """
    result = {}
    for dt, year, doy, vals in records:
        if len(vals) > 0:
            result[dt] = vals[0]  # column 2 = STORED SOIL WATER (CM)
    return result


def extract_annual_et(records):
    """Extract annual sum of actual ET (col 84, index 82 in vals).

    Returns dict: {year: total_et_cm}
    """
    yearly = {}
    for dt, year, doy, vals in records:
        if len(vals) > 82:
            et = vals[82]  # column 84 = ACTUAL ET (CM)
            yearly[year] = yearly.get(year, 0.0) + et
    return yearly


def compute_nse(obs, sim):
    """Nash-Sutcliffe Efficiency between two dicts with shared keys."""
    common = sorted(set(obs.keys()) & set(sim.keys()))
    if len(common) < 3:
        return -999.0
    obs_vals = [obs[k] for k in common]
    sim_vals = [sim[k] for k in common]
    obs_mean = sum(obs_vals) / len(obs_vals)
    ss_res = sum((s - o) ** 2 for s, o in zip(sim_vals, obs_vals))
    ss_tot = sum((o - obs_mean) ** 2 for o in obs_vals)
    if ss_tot == 0:
        return -999.0
    return 1.0 - ss_res / ss_tot


def compute_rmse(obs, sim):
    """RMSE between two dicts with shared keys."""
    common = sorted(set(obs.keys()) & set(sim.keys()))
    if len(common) < 1:
        return -999.0
    sq_err = sum((sim[k] - obs[k]) ** 2 for k in common)
    return math.sqrt(sq_err / len(common))


def compute_pbias(obs, sim):
    """Percent bias: 100 * (sum_sim - sum_obs) / sum_obs."""
    common = sorted(set(obs.keys()) & set(sim.keys()))
    if len(common) < 1:
        return -999.0
    sum_obs = sum(obs[k] for k in common)
    sum_sim = sum(sim[k] for k in common)
    if sum_obs == 0:
        return -999.0
    return 100.0 * (sum_sim - sum_obs) / sum_obs


def load_obs_yield(path):
    """Load observed yield CSV: year,yield_kgha"""
    obs = {}
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            year = int(row['year'])
            yld = float(row['yield_kgha'])
            obs[year] = yld
    return obs


def load_obs_sm(path):
    """Load observed soil moisture CSV: date,sm_cm (daily)."""
    obs = {}
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            dt = datetime.strptime(row['date'], '%Y-%m-%d')
            sm = float(row['sm_cm'])
            obs[dt] = sm
    return obs


def main():
    scenario_dir = sys.argv[1] if len(sys.argv) > 1 else ""

    obs_yield_path = None
    obs_sm_path = None
    for i, arg in enumerate(sys.argv):
        if arg == '--obs_yield' and i + 1 < len(sys.argv):
            obs_yield_path = sys.argv[i + 1]
        if arg == '--obs_sm' and i + 1 < len(sys.argv):
            obs_sm_path = sys.argv[i + 1]

    if not scenario_dir:
        print(json.dumps({"status": "INPUT_ERROR",
                          "message": "Usage: parse_rzwqm2_output.py <scenario_dir> [--obs_yield f] [--obs_sm f]"}))
        sys.exit(1)

    # Find .ana file
    ana_dir = os.path.join(os.path.dirname(scenario_dir.rstrip('/')), 'Analysis')
    station = os.path.basename(scenario_dir.rstrip('/'))
    ana_path = os.path.join(ana_dir, station + '.ana')

    # Also check inside scenario dir itself
    if not os.path.isfile(ana_path):
        for f in os.listdir(scenario_dir):
            if f.endswith('.ana'):
                ana_path = os.path.join(scenario_dir, f)
                break

    if not os.path.isfile(ana_path):
        # Check parent Analysis dir
        parent = os.path.dirname(scenario_dir.rstrip('/'))
        ana_dir2 = os.path.join(parent, 'Analysis')
        if os.path.isdir(ana_dir2):
            for f in os.listdir(ana_dir2):
                if f.endswith('.ana'):
                    ana_path = os.path.join(ana_dir2, f)
                    break

    if not os.path.isfile(ana_path):
        print(json.dumps({"status": "PROCESSING_ERROR",
                          "message": f"No .ana file found for {scenario_dir}"}))
        sys.exit(2)

    # Parse
    records = parse_ana(ana_path)
    if not records:
        print(json.dumps({"status": "PROCESSING_ERROR",
                          "message": f"No data records in {ana_path}"}))
        sys.exit(2)

    # Extract simulated values
    sim_yield = extract_annual_yield(records)
    sim_sm = extract_daily_soil_water(records)
    sim_et = extract_annual_et(records)

    # Compute summary stats
    result = {
        'ana_path': ana_path,
        'n_records': len(records),
        'sim_yield_mean': round(sum(sim_yield.values()) / len(sim_yield), 1) if sim_yield else -99,
        'sim_yield_per_year': {str(k): round(v, 1) for k, v in sorted(sim_yield.items())},
        'sim_et_mean': round(sum(sim_et.values()) / len(sim_et), 1) if sim_et else -99,
        'sim_sm_mean': round(sum(sim_sm.values()) / len(sim_sm), 2) if sim_sm else -99,
    }

    # Compute metrics against observations
    metrics = {}

    if obs_yield_path and os.path.isfile(obs_yield_path):
        obs_yield = load_obs_yield(obs_yield_path)
        metrics['yield_rmse'] = round(compute_rmse(obs_yield, sim_yield), 1)
        metrics['yield_pbias'] = round(compute_pbias(obs_yield, sim_yield), 1)
        metrics['yield_obs_mean'] = round(sum(obs_yield.values()) / len(obs_yield), 1)
        metrics['yield_sim_mean'] = result['sim_yield_mean']
        metrics['yield_n_years'] = len(set(obs_yield.keys()) & set(sim_yield.keys()))

    if obs_sm_path and os.path.isfile(obs_sm_path):
        obs_sm = load_obs_sm(obs_sm_path)
        metrics['sm_nse'] = round(compute_nse(obs_sm, sim_sm), 4)
        metrics['sm_rmse'] = round(compute_rmse(obs_sm, sim_sm), 3)
        metrics['sm_pbias'] = round(compute_pbias(obs_sm, sim_sm), 1)
        metrics['sm_n_days'] = len(set(obs_sm.keys()) & set(sim_sm.keys()))

    # Combined score (for calibration objective)
    # Lower is better: normalized yield RMSE + (1 - soil moisture NSE)
    combined = -999.0
    if 'yield_rmse' in metrics and metrics.get('yield_obs_mean', 0) > 0:
        yield_score = metrics['yield_rmse'] / metrics['yield_obs_mean']  # normalized 0-1ish
        if 'sm_nse' in metrics and metrics['sm_nse'] > -900:
            sm_score = max(0, 1.0 - metrics['sm_nse'])  # 0=perfect, 2=terrible
            combined = round(0.5 * yield_score + 0.5 * sm_score, 4)
        else:
            combined = round(yield_score, 4)
    elif 'sm_nse' in metrics and metrics['sm_nse'] > -900:
        combined = round(max(0, 1.0 - metrics['sm_nse']), 4)

    metrics['combined_score'] = combined
    result['metrics'] = metrics

    print(json.dumps({"status": "SUCCESS", "result": result}))
    sys.exit(0)


if __name__ == '__main__':
    main()
