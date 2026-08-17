#!/usr/bin/env python3
"""Verify_2 CRHM @ Belly River near Mountain View (HYDAT 05AD005).
Runs the tuned .prj via the real CRHM binary, sums hourly basinflow to daily
m3/s, scores vs the obs txt. Resumable: reuses model output if present."""
import os, sys, subprocess, json
import numpy as np, pandas as pd

sys.path.insert(0, "KISSPATH_KI_ROOT")
from ki_tools_common.metrics import all_metrics

BASE = "KISSPATH_KI_ROOT/CRHM/knowledge_infrastructure/outputs/belly_verify/crhm"
PRJ  = os.path.join(BASE, "belly_tuned.prj")
CRHM = "KISSPATH_KI_ROOT/CRHM/bin/crhm"
OUT  = os.path.join(BASE, "output_verify2.txt")
OBS  = "KISSPATH_OBS/belly_river/observed_05AD005.txt"
STATE = "KISSPATH_KI_ROOT/CRHM/detached/verify_2"
os.makedirs(STATE, exist_ok=True)

# 1. run model (resumable)
if not (os.path.exists(OUT) and os.path.getsize(OUT) > 1_000_000):
    subprocess.run([CRHM, PRJ, "-o", OUT], check=True, cwd=BASE)

# 2. parse sim: hourly basinflow(1) m3/int -> daily mean m3/s
df = pd.read_csv(OUT, sep="\t", skiprows=[1])
df = df[df["time"].astype(str).str.match(r"\d{4}-\d{2}-\d{2}T", na=False)].copy()
df["dt"] = pd.to_datetime(df["time"])
df["bf"] = pd.to_numeric(df["basinflow(1)"], errors="coerce")
sim_d = (df.set_index("dt")["bf"].resample("D").sum() / 86400.0).rename("sim")

# 3. obs daily Q
obs = pd.read_csv(OBS, sep="\t")
obs_d = pd.Series(obs["Q"].astype(float).values,
                  index=pd.to_datetime(obs["dates"]), name="obs").sort_index()

# 4. align, spinup 2005 dropped
def score(lo, hi):
    m = pd.concat([obs_d, sim_d], axis=1).dropna()
    m = m[(m.index >= lo) & (m.index <= hi)]
    return m, all_metrics(m["obs"].values, m["sim"].values)

full_m, full = score("2006-01-01", "2015-12-31")
_, cal = score("2006-01-01", "2010-12-31")
_, val = score("2011-01-01", "2015-12-31")

# 5. water balance (mm over record, basin 319 km2)
area_km2 = 319.0
fc = pd.read_csv(os.path.join(BASE, "belly.obs"), sep=r"\s+", skiprows=8, header=None)
P_mm = float(fc[6].sum()) * 0.72                # hourly p summed * ClimChng_precip (model-effective)
hru_area = {"hru_actet(1)": 95.7, "hru_actet(2)": 159.5, "hru_actet(3)": 63.8}
ET_mm = sum(pd.to_numeric(df[c], errors="coerce").sum() * (a/area_km2)
            for c, a in hru_area.items() if c in df.columns)
Q_mm = float(df["bf"].sum()) / (area_km2*1e6) * 1000.0
resid_pct = 100.0 * (P_mm - ET_mm - Q_mm) / P_mm
wb_status = "PASS" if abs(resid_pct) < 5 else ("WARN" if abs(resid_pct) < 15 else "FAIL")

result = {
    "model_id": "CRHM",
    "this_location": "Belly River near Mountain View",
    "obs_source": "Belly River near Mountain View",
    "status": "completed",
    "tools_used": ["run_crhm(binary)", "parse_crhm_output", "ki_tools_common.metrics.all_metrics"],
    "tools_failed": [],
    "metrics": {
        "nse": round(float(full["NSE"]), 4),
        "kge": round(float(full["KGE"]), 4),
        "pbias": round(float(full["PBIAS"]), 4),
        "r": round(float(full["r"]), 4),
        "period": f"2006-01-01..2015-12-31 (n={len(full_m)}d, daily, spinup 2005 dropped)",
    },
    "metrics_cal": {k.lower(): round(float(cal[k]), 4) for k in ("NSE", "KGE", "PBIAS", "r")},
    "metrics_val": {k.lower(): round(float(val[k]), 4) for k in ("NSE", "KGE", "PBIAS", "r")},
    "water_balance": {"status": wb_status, "residual_pct": round(float(resid_pct), 2),
                      "P_mm": round(P_mm, 1), "ET_mm": round(float(ET_mm), 1), "Q_mm": round(Q_mm, 1)},
    "notes": (f"CRHM 4.7_16 real binary, 13-module mountain chain (basin>global>obs>calcsun>"
              f"intcp>pbsm>albedo>ebsm>netall>crack>evap>Soil>Netroute), tuned home-basin "
              f"belly_tuned.prj, NASA POWER hourly 2005-2015. Daily-summed basinflow(1)/86400 "
              f"vs obs daily Q, n={len(full_m)}d. FULL NSE {full['NSE']:.3f}/KGE {full['KGE']:.3f}/"
              f"PBIAS {full['PBIAS']:.1f}/r {full['r']:.3f}; CAL NSE {cal['NSE']:.3f}; VAL NSE "
              f"{val['NSE']:.3f}. WB resid {resid_pct:.1f}% (decadal Netroute routing-store artifact).")
}
with open(os.path.join(STATE, "result.json"), "w") as f:
    json.dump(result, f, indent=2)
print(json.dumps(result, indent=2))
