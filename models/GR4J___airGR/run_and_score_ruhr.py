#!/usr/bin/env python3
"""
GR4J/airGR verifier runner — GRDC-Caravan Extension gauge GRDC_6335030
RUHR, HATTINGEN, Germany (51.398N, 7.165E, 4098 km2). Humid temperate lowland
basin, runoff ratio ~0.48. Uses the KI Caravan chain end-to-end:
  convert_forcing_to_gr4j.py --source caravan (ERA5-Land P + Oudin PE, streamflow mm/d)
  -> run_gr4j.py (plain GR4J, NSE calibration) -> all_metrics.
Bundled ERA5-Land forcing + streamflow are the canonical Caravan inputs; no
external forcing fetch is required. RESUMABLE: each stage skips if output exists.
"""
import os, sys, json, subprocess
import numpy as np, pandas as pd

KI = 'KISSPATH_KI_ROOT/GR4J___airGR/knowledge_infrastructure'
TOOLS = KI + '/tools'
sys.path.insert(0, TOOLS)
sys.path.insert(0, 'KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect_multi_agent')
from ki_tools_common.metrics import all_metrics
from ki_tools_common.validation import validate_water_balance

WD = 'KISSPATH_OUTPUTS/gr4j_grdc6335030'
OUT = 'KISSPATH_KI_ROOT/GR4J___airGR/detached/verify_1'
os.makedirs(WD, exist_ok=True); os.makedirs(OUT, exist_ok=True)

GAUGE = 'GRDC_6335030'
LAT, LON, AREA = 51.3979, 7.1646, 4097.883
NC = ('KISSPATH_DATA/observed_data/dischargeandwatershed/GRDC-Caravan-extension-nc/'
      'timeseries/netcdf/grdc/' + GAUGE + '.nc')
# streamflow fully valid 1981-2020; use 1980 as warmup year for forcing.
FORC_START, FORC_END = '1980-01-01', '2020-12-31'
CAL = ('1981-01-01', '2000-12-31'); VAL = ('2001-01-01', '2020-12-31')
EVAL_START, EVAL_END = '1981-01-01', '2020-12-31'
PY = sys.executable


def sh(cmd):
    print('+', ' '.join(cmd), flush=True)
    subprocess.run(cmd, check=True)


# --- Stage 1: Caravan NetCDF -> airGR forcing (ERA5-Land P, Oudin PE, streamflow mm/d) ---
forcing = WD + '/forcing_gr4j.csv'
if not os.path.exists(forcing):
    sh([PY, TOOLS + '/convert_forcing_to_gr4j.py', '--source', 'caravan',
        '--caravan-nc', NC, '--lat', str(LAT), '--area-km2', str(AREA),
        '--start-date', FORC_START, '--end-date', FORC_END,
        '--pe-method', 'oudin', '--output', forcing])

# --- Stage 2: calibration (plain GR4J, NSE) on CAL window ---
meta_cal = WD + '/meta_cal.json'
sim_cal = WD + '/sim_cal.csv'
if not os.path.exists(meta_cal):
    sh([PY, TOOLS + '/run_gr4j.py', '--forcing', forcing, '--output', sim_cal,
        '--mode', 'calibration', '--start', CAL[0], '--end', CAL[1],
        '--warmup', '1', '--criterion', 'NSE', '--meta-json', meta_cal])
params = json.load(open(meta_cal))['param']
print('Calibrated params (X1-X4):', params, flush=True)

# --- Stage 3: simulation over full eval period 1981-2020 (warmup 1980) ---
sim_full = WD + '/sim_full.csv'
if not os.path.exists(sim_full):
    sh([PY, TOOLS + '/run_gr4j.py', '--forcing', forcing, '--output', sim_full,
        '--mode', 'simulation', '--start', EVAL_START, '--end', EVAL_END,
        '--warmup', '1',
        '--x1', str(params[0]), '--x2', str(params[1]),
        '--x3', str(params[2]), '--x4', str(params[3])])

# --- Stage 4: metrics ---
sim = pd.read_csv(sim_full, parse_dates=['Date'])
forc = pd.read_csv(forcing, parse_dates=['Date'])
m = sim.merge(forc[['Date', 'Qobs_mm', 'Precip_mm', 'PotEvap_mm']], on='Date', how='left')
m['yr'] = m.Date.dt.year


def metrics_for(sub, label="headline", period_role="full"):
    d = sub.dropna(subset=['Qobs_mm', 'Qsim_mm'])
    if len(d) < 2:
        return None
    # dated + labelled capture via the shared scorer (step 5) — see run_and_score_hydat_08MH001.py
    return all_metrics(d.Qobs_mm.values, d.Qsim_mm.values,
                       dates=d.Date.values, label=label,
                       meta={"period_role": period_role, "unit": "mm/d"})


cal = metrics_for(m[(m.yr >= 1981) & (m.yr <= 2000)], label="cal", period_role="cal")
val = metrics_for(m[(m.yr >= 2001) & (m.yr <= 2020)], label="val", period_role="val")
full = metrics_for(m, label="headline", period_role="full")
print('CAL', cal, flush=True); print('VAL', val, flush=True); print('FULL', full, flush=True)

# --- Water balance closure ---
P = m.Precip_mm.sum(); AE = sim['AE'].sum(); Q = sim['Qsim_mm'].sum()
dS = (sim[['Prod', 'Rout']].iloc[-1].sum() - sim[['Prod', 'Rout']].iloc[0].sum())
wb = validate_water_balance(precip_mm=P, et_mm=AE, runoff_mm=Q,
                            delta_storage_mm=dS, period_days=len(m))

result = {
    "model_id": "GR4J___airGR",
    "this_location": "GRDC-Caravan Extension (5,357 global gauges + basin shapes)",
    "obs_source": "GRDC",
    "status": "completed",
    "tools_used": ["convert_forcing_to_gr4j.py (--source caravan)", "run_gr4j.py",
                   "ki_tools_common.metrics.all_metrics",
                   "ki_tools_common.validation.validate_water_balance"],
    "tools_failed": [],
    "variable": "Qsim", "obs_shape": "point_time_series",
    "metrics": {
        "nse": full['NSE'], "kge": full['KGE'], "pbias": full['PBIAS'], "r": full['r'],
        "nse_cal": cal['NSE'], "kge_cal": cal['KGE'],
        "nse_val": val['NSE'], "kge_val": val['KGE'], "pbias_val": val['PBIAS'],
        "period": EVAL_START + ".." + EVAL_END,
        "period_calibration": CAL[0] + ".." + CAL[1],
        "period_validation": VAL[0] + ".." + VAL[1],
    },
    "water_balance": {"status": wb['status'], "residual_mm": wb['residual_mm'],
                      "residual_pct": wb['residual_pct'],
                      "diagnostics": wb.get('diagnostics', [])},
    "calibrated_params_x1_x4": params,
    "gauge": GAUGE,
    "location": "GRDC_6335030 RUHR, HATTINGEN, Germany (humid temperate lowland, 4098 km2)",
    "notes": ("Plain GR4J/airGR at RUHR/Hattingen via KI Caravan chain "
              "(convert_forcing_to_gr4j --source caravan: ERA5-Land P + Oudin PE, "
              "streamflow mm/d). cal/val/full NSE %.3f/%.3f/%.3f, KGE_val %.3f, "
              "PBIAS_val %.1f%%. Cal 1981-2000 / Val 2001-2020, warmup 1980. "
              "X1-X4=%s. WB %s residual %.1f%% (X2 GW-exchange open-boundary "
              "artifact if FAIL, not a unit error)."
              % (cal['NSE'], val['NSE'], full['NSE'], val['KGE'], val['PBIAS'],
                 [round(p, 3) for p in params], wb['status'], wb['residual_pct'])),
}
json.dump(result, open(OUT + '/result.json', 'w'), indent=1, default=str)
print('WROTE', OUT + '/result.json', flush=True)
print(json.dumps(result['metrics'], indent=1), flush=True)
