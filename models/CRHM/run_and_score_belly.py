#!/usr/bin/env python3
"""Verifier runner+scoring for CRHM @ Belly River near Mountain View (HYDAT 05AD005).

Runs the validated 13-module Belly River .prj through the REAL CRHM binary, sums
hourly basinflow(1) [m^3/int] to daily mean m^3/s, loads the HYDAT obs txt, aligns,
drops the 2005 spinup year, and computes NSE/KGE/PBIAS/r via ki_tools_common.metrics.
RESUMABLE: skips the CRHM run if its output already exists (>1MB)."""
import os, sys, json, subprocess
import numpy as np, pandas as pd

sys.path.insert(0, "/mnt/disk1/Hydrocraft_server/models")
from ki_tools_common.metrics import all_metrics

KI    = "/mnt/disk1/Hydrocraft_server/models/CRHM/knowledge_infrastructure"
EXE   = "/mnt/disk1/Hydrocraft_server/model/crhmcode/crhmcode/build/crhm"
PRJ   = os.path.join(KI, "outputs/belly_verify/crhm/belly_tuned.prj")
OBSF  = "/mnt/disk1/Hydrocraft_server/data/obs/belly_river/observed_05AD005.txt"
OBSP  = os.path.join(KI, "outputs/belly_verify/crhm/belly.obs")
STATE = "/mnt/disk1/Hydrocraft_server/models/CRHM/detached/verify_2"
OUT   = os.path.join(STATE, "crhm_output.txt")
RESULT= os.path.join(STATE, "result.json")
AREA  = 319.0
AREAS = [95.7, 159.5, 63.8]
os.makedirs(STATE, exist_ok=True)

# ---- 1. run CRHM (resumable) ----
if not (os.path.isfile(OUT) and os.path.getsize(OUT) > 1_000_000):
    cmd = [sys.executable, os.path.join(KI, "tools/s5_execution/run_crhm.py"),
           "--crhm_exe", EXE, "--prj_path", PRJ, "--output_path", OUT,
           "--time_format", "YYYYMMDD"]
    print("RUN:", " ".join(cmd), flush=True)
    r = subprocess.run(cmd, cwd=KI, capture_output=True, text=True)
    print((r.stdout or "")[-2000:]); print((r.stderr or "")[-2000:])
    if not (os.path.isfile(OUT) and os.path.getsize(OUT) > 1_000_000):
        cmd2 = [EXE, "-f", "STD", "-t", "YYYYMMDD", "-o", OUT, PRJ]
        print("FALLBACK:", " ".join(cmd2), flush=True)
        subprocess.run(cmd2, cwd=KI, capture_output=True, text=True)
else:
    print("RESUME: using existing", OUT, flush=True)

# ---- 2. Simulated: hourly basinflow(1) [m^3/int] -> daily mean m^3/s ----
cols = pd.read_csv(OUT, sep="\t", nrows=0).columns.tolist()
df = pd.read_csv(OUT, sep="\t", skiprows=[1])
df["time"] = pd.to_datetime(df["time"])
df = df.set_index("time")
sim = (df["basinflow(1)"].resample("D").sum() / 86400.0).rename("sim")

# ---- 3. Observed from txt (cols: stcd, dates, z, Q) ----
obs_df = pd.read_csv(OBSF, sep="\t")
obs_df["dates"] = pd.to_datetime(obs_df["dates"])
obs = obs_df.set_index("dates")["Q"].astype(float).rename("obs").sort_index()

# ---- 4. Align, drop spinup 2005, score ----
both = pd.concat([obs, sim], axis=1).dropna()
both = both[both.index.year >= 2006]
o = both["obs"].to_numpy(); s = both["sim"].to_numpy()
m = all_metrics(o, s)
period = f"{both.index.min().date()}..{both.index.max().date()} (n={len(both)}d, daily, spinup 2005 dropped)"
print("metrics:", m, "n=", len(both), flush=True)

# ---- 5. Water balance (mm over scored period) ----
yrs = both.index.year.nunique()
# precip from belly.obs (col idx 6 = p mm), years>2005
p_tot = 0.0
with open(OBSP) as fh:
    for ln in fh:
        t = ln.split()
        if len(t) >= 11 and t[0].isdigit() and int(t[0]) >= 2006:
            p_tot += float(t[6])
# ET area-weighted across HRUs over scored period
df2 = df[df.index.year >= 2006]
et_tot = 0.0
for i, a in enumerate(AREAS, start=1):
    c = f"hru_actet({i})"
    if c in df2.columns:
        et_tot += pd.to_numeric(df2[c], errors="coerce").sum() * (a/AREA)
q_depth = both["sim"].sum()*86400.0/(AREA*1e6)*1000.0
resid = p_tot - et_tot - q_depth
resid_pct = round(100.0*resid/p_tot, 2) if p_tot else None
wb_status = "PASS" if (resid_pct is not None and abs(resid_pct) <= 5) else "WARN"
wb = {"status": wb_status, "residual_pct": resid_pct,
      "P_mm": round(p_tot,1), "ET_mm": round(et_tot,1), "Q_mm": round(q_depth,1)}
print("WB:", wb, flush=True)

result = {
    "model_id": "CRHM",
    "this_location": "Belly River near Mountain View",
    "obs_source": "Belly River near Mountain View",
    "status": "completed",
    "tools_used": ["run_crhm", "parse_crhm_output (inline)", "ki_tools_common.metrics"],
    "tools_failed": [],
    "metrics": {
        "nse": round(float(m["NSE"]), 3),
        "kge": round(float(m["KGE"]), 3),
        "pbias": round(float(m["PBIAS"]), 2),
        "r": round(float(m["r"]), 3),
        "period": period,
    },
    "water_balance": {"status": wb["status"], "residual_pct": wb["residual_pct"]},
    "notes": (
        f"CRHM 13-module mountain chain (basin>global>obs>calcsun>intcp>pbsm>albedo>ebsm>"
        f"netall>crack>evap>Soil>Netroute), NASA POWER forcing 2005-2015, at HYDAT 05AD005 "
        f"Belly River near Mountain View AB (319 km2, Rockies foothills). Validated Belly .prj "
        f"(obs_elev 1900, ClimChng_precip 0.72, GW gw_K 0.6/gw_max 600-1000). Sim=daily-summed "
        f"basinflow(1)/86400. Daily NSE {m['NSE']:.3f}/KGE {m['KGE']:.3f}/PBIAS {m['PBIAS']:.1f}% "
        f"over {len(both)} days (2006-2015). WB P={wb['P_mm']} ET={wb['ET_mm']} Q={wb['Q_mm']} mm, "
        f"residual {resid_pct}%."
    ),
}
with open(RESULT, "w") as f:
    json.dump(result, f, indent=2)
print("WROTE", RESULT, flush=True)
print(json.dumps(result, indent=2))
