#!/usr/bin/env python3
"""
GR4J/airGR verifier runner — HYDAT gauge 08MH001
CHILLIWACK RIVER AT VEDDER CROSSING, BC, Canada (49.097N, -121.967E, 1230 km2).
RHBN reference basin, unregulated (STN_REGULATION REGULATED=0), daily-flow record
99.2% complete 1988-2020. Snow-influenced Cascade mountain basin -> uses --snow
(CemaNeige+GR4J), per the KI's documented HYDAT cold-basin protocol.

KI chain end-to-end, all LOCAL inputs (no network fetch):
  MSWX 0.1deg 3-hourly (P mm/3hr, Tair degC) -> daily catchment CSV (via
    ki_tools_common.load_forcing.load_daily_forcing, nearest point at gauge)
  -> convert_forcing_to_gr4j.py --source cmfd (daily P sum, Oudin PE, HYDAT Qobs
     m3/s -> mm/d) -> run_gr4j.py --snow (NSE calibration + simulation) -> all_metrics.

RESUMABLE: MSWX cached per-year; forcing/qobs CSVs, calibration meta, and the
simulation CSV each skip if their output already exists. Relaunch resumes.
"""
import os, sys, json, subprocess, sqlite3, calendar
import numpy as np, pandas as pd
from datetime import datetime

KI = 'KISSPATH_KI_ROOT/GR4J___airGR/knowledge_infrastructure'
TOOLS = KI + '/tools'
COMMON = 'KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect_multi_agent'
sys.path.insert(0, TOOLS)
sys.path.insert(0, COMMON)
from ki_tools_common.metrics import all_metrics
from ki_tools_common.validation import validate_water_balance
from ki_tools_common.load_forcing import load_daily_forcing

WD = 'KISSPATH_OUTPUTS/gr4j_hydat_08MH001'
OUT = 'KISSPATH_KI_ROOT/GR4J___airGR/detached/verify_2'
MSWX_CACHE = WD + '/mswx_years'
os.makedirs(WD, exist_ok=True); os.makedirs(OUT, exist_ok=True)
os.makedirs(MSWX_CACHE, exist_ok=True)

# --- Station / period configuration ---
STN = '08MH001'
LAT, LON, AREA = 49.09738, -121.96748, 1230.0
HYDAT = ('KISSPATH_DATA/observed_data/dischargeandwatershed/'
         'National Water Data Archive HYDAT/Hydat.sqlite3')
FORC_SY, FORC_EY = 1989, 2020           # 1989 = warmup year
EVAL_START, EVAL_END = '1990-01-01', '2020-12-31'
CAL = ('1990-01-01', '2005-12-31')
VAL = ('2006-01-01', '2020-12-31')
PY = sys.executable


def sh(cmd):
    print('+', ' '.join(str(c) for c in cmd), flush=True)
    subprocess.run(cmd, check=True)


# --- Input availability record (all local) ---
ia = {"all_required_reachable": True, "required": [], "optional": [],
      "unreachable_required": []}
for p in [HYDAT, 'KISSPATH_FORCING/P', 'KISSPATH_FORCING/Tair']:
    ia["required"].append({"path": p, "reachable": os.path.exists(p)})
if not all(r["reachable"] for r in ia["required"]):
    ia["all_required_reachable"] = False
    ia["unreachable_required"] = [r["path"] for r in ia["required"] if not r["reachable"]]
json.dump(ia, open(OUT + '/input_availability.json', 'w'), indent=1)

# --- Stage 0: HYDAT daily discharge (m3/s) -> qobs CSV ---
qobs_csv = WD + '/qobs_m3s.csv'
if not os.path.exists(qobs_csv):
    con = sqlite3.connect(HYDAT)
    rows = []
    q = ("SELECT YEAR,MONTH," + ",".join(f"FLOW{i}" for i in range(1, 32)) +
         " FROM DLY_FLOWS WHERE STATION_NUMBER=? AND YEAR BETWEEN ? AND ?")
    for r in con.execute(q, (STN, FORC_SY, FORC_EY)):
        yr, mo = r[0], r[1]
        flows = r[2:]
        ndays = calendar.monthrange(yr, mo)[1]
        for d in range(ndays):
            v = flows[d]
            rows.append((f"{yr:04d}-{mo:02d}-{d+1:02d}", v))
    con.close()
    dq = pd.DataFrame(rows, columns=['date', 'Q_m3s']).sort_values('date')
    dq.to_csv(qobs_csv, index=False)
    print(f'[qobs] wrote {len(dq)} rows, valid={dq.Q_m3s.notna().sum()}', flush=True)

# --- Stage 1: MSWX daily forcing (per-year cache) -> combined CMFD-style CSV ---
cmfd_csv = WD + '/mswx_daily.csv'
if not os.path.exists(cmfd_csv):
    frames = []
    for yr in range(FORC_SY, FORC_EY + 1):
        yc = MSWX_CACHE + f'/mswx_{yr}.csv'
        if not os.path.exists(yc):
            print(f'[mswx] loading {yr} ...', flush=True)
            f = load_daily_forcing('mswx', LAT, LON, yr, yr)
            dfy = pd.DataFrame({
                'date': pd.to_datetime(f['dates']),
                'prec': f['precip_mm'],          # mm/day (already daily sum)
                'temp': f['temp_mean_c'],        # degC
            })
            dfy.to_csv(yc, index=False)
        frames.append(pd.read_csv(yc, parse_dates=['date']))
    allf = pd.concat(frames).sort_values('date').reset_index(drop=True)
    allf.to_csv(cmfd_csv, index=False)
    print(f'[mswx] combined {len(allf)} days, P_mean={allf.prec.mean():.2f} mm/d, '
          f'T_mean={allf.temp.mean():.1f} C', flush=True)

# --- Stage 2: airGR forcing (Precip_mm, Oudin PE, TempMean_degC, Qobs_mm) ---
forcing = WD + '/forcing_gr4j.csv'
if not os.path.exists(forcing):
    sh([PY, TOOLS + '/convert_forcing_to_gr4j.py', '--source', 'cmfd',
        '--cmfd-csv', cmfd_csv, '--lat', str(LAT), '--area-km2', str(AREA),
        '--qobs-csv', qobs_csv, '--output', forcing])

# --- Stage 3: calibration (CemaNeige-GR4J, NSE) on CAL window ---
meta_cal = WD + '/meta_cal.json'
sim_cal = WD + '/sim_cal.csv'
if not os.path.exists(meta_cal):
    sh([PY, TOOLS + '/run_gr4j.py', '--forcing', forcing, '--output', sim_cal,
        '--mode', 'calibration', '--snow', '--start', CAL[0], '--end', CAL[1],
        '--warmup', '1', '--criterion', 'NSE', '--meta-json', meta_cal])
params = json.load(open(meta_cal))['param']
print('Calibrated params:', params, flush=True)

# --- Stage 4: simulation over full eval period 1990-2020 (warmup 1989) ---
sim_full = WD + '/sim_full.csv'
if not os.path.exists(sim_full):
    cmd = [PY, TOOLS + '/run_gr4j.py', '--forcing', forcing, '--output', sim_full,
           '--mode', 'simulation', '--snow', '--start', EVAL_START, '--end', EVAL_END,
           '--warmup', '1',
           '--x1', str(params[0]), '--x2', str(params[1]),
           '--x3', str(params[2]), '--x4', str(params[3])]
    if len(params) >= 6:
        cmd += ['--x5', str(params[4]), '--x6', str(params[5])]
    sh(cmd)

# --- Stage 5: metrics ---
sim = pd.read_csv(sim_full, parse_dates=['Date'])
forc = pd.read_csv(forcing, parse_dates=['Date'])
m = sim.merge(forc[['Date', 'Qobs_mm', 'Precip_mm', 'PotEvap_mm']], on='Date', how='left')
m['yr'] = m.Date.dt.year


def metrics_for(sub, label="headline", period_role="full"):
    d = sub.dropna(subset=['Qobs_mm', 'Qsim_mm'])
    if len(d) < 2:
        return None
    # pass dates + label so the shared scorer captures a DATED, labelled series (step 5): dateless
    # capture would cap a temporal metric at series_only and it could never be trusted.
    return all_metrics(d.Qobs_mm.values, d.Qsim_mm.values,
                       dates=d.Date.values, label=label,
                       meta={"period_role": period_role, "unit": "mm/d"})


cal = metrics_for(m[(m.yr >= 1990) & (m.yr <= 2005)], label="cal", period_role="cal")
val = metrics_for(m[(m.yr >= 2006) & (m.yr <= 2020)], label="val", period_role="val")
full = metrics_for(m, label="headline", period_role="full")
print('CAL', cal, flush=True); print('VAL', val, flush=True); print('FULL', full, flush=True)

# --- Water balance closure (snowpack storage not in Prod/Rout -> residual noted) ---
P = m.Precip_mm.sum(); AE = sim['AE'].sum(); Q = sim['Qsim_mm'].sum()
dS = (sim[['Prod', 'Rout']].iloc[-1].sum() - sim[['Prod', 'Rout']].iloc[0].sum())
wb = validate_water_balance(precip_mm=P, et_mm=AE, runoff_mm=Q,
                            delta_storage_mm=dS, period_days=len(m))

result = {
    "model_id": "GR4J___airGR",
    "this_location": "HYDAT - Canada National Water Data Archive (~8,000 stations, 1850s-present)",
    "obs_source": "HYDAT",
    "status": "completed",
    "tools_used": ["ki_tools_common.load_forcing.load_daily_forcing (mswx)",
                   "convert_forcing_to_gr4j.py (--source cmfd)",
                   "run_gr4j.py (--snow, calibration+simulation)",
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
    "water_balance": {"status": wb['status'], "residual_mm": wb.get('residual_mm'),
                      "residual_pct": wb.get('residual_pct'),
                      "diagnostics": wb.get('diagnostics', [])},
    "calibrated_params": params,
    "gauge": STN,
    "location": ("HYDAT 08MH001 CHILLIWACK RIVER AT VEDDER CROSSING, BC "
                 "(RHBN, unregulated, snow-influenced Cascade, 1230 km2)"),
    "input_availability": ia,
    "notes": ("CemaNeige-GR4J/airGR at HYDAT 08MH001 (Chilliwack R.) via KI chain "
              "(MSWX->convert_forcing_to_gr4j --source cmfd->run_gr4j --snow). "
              "cal/val/full NSE %.3f/%.3f/%.3f, KGE_val %.3f, PBIAS_val %.1f%%. "
              "Cal 1990-2005 / Val 2006-2020, warmup 1989. --snow used per KI "
              "cold-HYDAT-basin protocol. WB %s (snowpack storage excluded from "
              "Prod/Rout closure -> residual expected)."
              % (cal['NSE'], val['NSE'], full['NSE'], val['KGE'], val['PBIAS'],
                 wb['status'])),
}
json.dump(result, open(OUT + '/result.json', 'w'), indent=1, default=str)
print('WROTE', OUT + '/result.json', flush=True)
print(json.dumps(result['metrics'], indent=1), flush=True)
