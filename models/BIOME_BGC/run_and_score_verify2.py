#!/usr/bin/env python3
"""
BIOME-BGC VERIFIER (verify_2) — US-Me2 (Metolius mature ponderosa pine, Oregon, ENF).
Runs the SAME KI tools end-to-end as the NL-Loo real-case, scores daily GPP vs FLUXNET2015.
Resumable: skips spinup/normal stages whose outputs already exist.
"""
import os, sys, subprocess, json
import numpy as np
import pandas as pd

ROOT = "/mnt/disk1/Hydrocraft_server/models/BIOME_BGC"
KI = f"{ROOT}/knowledge_infrastructure"
TOOLS = f"{KI}/tools"
BGC = "/mnt/disk1/Hydrocraft_server/model/biome-bgc/bgc-src/bgc"
WORK = f"{ROOT}/detached/verify_2"
SITE = "DE-Tha"
FLUX = f"/mnt/disk1/Hydrocraft_server/data/obs/fluxnet/sites/{SITE}/FULLSET_DD.csv"

# DE-Tha site constants (Tharandt, Germany — Norway spruce, temperate ENF)
LAT, LON, ELEV = 50.9636, 13.5669, 385.0
SOIL_DEPTH = 1.0
Y0, Y1 = 1996, 2014
NYEARS = Y1 - Y0 + 1
PFT = "ENF"

sys.path.insert(0, f"{ROOT}/models" if os.path.isdir(f"{ROOT}/models") else ROOT)
from ki_tools_common.metrics import all_metrics
from ki_tools_common.soil_utils import lookup_hwsd

soil = lookup_hwsd(LAT, LON)
SAND, SILT, CLAY = soil["sand"], soil["silt"], soil["clay"]

def sh(cmd):
    print(">>", " ".join(cmd), flush=True)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout); print(r.stderr)
        raise SystemExit(f"FAILED rc={r.returncode}: {' '.join(cmd)}")
    return r.stdout

for d in ["epc", "metdata", "restart", "outputs"]:
    os.makedirs(f"{WORK}/{d}", exist_ok=True)

EPC = f"{WORK}/epc/site.epc"
MET = f"{WORK}/metdata/site.mtc43"
SPIN_INI = f"{WORK}/spinup.ini"
NORM_INI = f"{WORK}/normal.ini"
ENDPOINT = f"{WORK}/restart/site.endpoint"
DAYOUT = f"{WORK}/outputs/normal.dayout.ascii"

# S2 ecophysiology
if not os.path.exists(EPC):
    sh(["python3", f"{TOOLS}/select_ecophysiology.py", "--pft", PFT, "--output", EPC])

# S3 forcing (KI tool reads FLUXNET FULLSET_DD directly; leap-day drop in tool)
if not os.path.exists(MET):
    sh(["python3", f"{TOOLS}/convert_forcing_to_bgc.py",
        "--forcing_file", FLUX, "--source", "fluxnet", "--lat", str(LAT),
        "--start_year", str(Y0), "--end_year", str(Y1), "--output", MET])

ny = pd.read_csv(MET, skiprows=4, sep=r"\s+", header=None)[0].value_counts()
assert (ny == 365).all(), f"met not 365/yr: {ny.to_dict()}"

common = ["--met_file", MET, "--epc_file", EPC, "--lat", str(LAT),
          "--elevation", str(ELEV), "--soil_depth", str(SOIL_DEPTH),
          "--sand", str(SAND), "--silt", str(SILT), "--clay", str(CLAY),
          "--start_year", str(Y0), "--n_met_years", str(NYEARS)]

# S5 spinup
if not os.path.exists(ENDPOINT):
    sh(["python3", f"{TOOLS}/generate_site_ini.py", *common,
        "--output_prefix", f"{WORK}/outputs/spinup", "--mode", "spinup",
        "--restart_file", ENDPOINT, "--write_restart", "--output", SPIN_INI])
    sh(["python3", f"{TOOLS}/run_bgc_spinup.py", "--bgc_binary", BGC, "--ini_file", SPIN_INI])

# S6 normal
if not os.path.exists(DAYOUT):
    sh(["python3", f"{TOOLS}/generate_site_ini.py", *common,
        "--output_prefix", f"{WORK}/outputs/normal", "--mode", "normal",
        "--restart_file", ENDPOINT, "--read_restart", "--output", NORM_INI])
    sh(["python3", f"{TOOLS}/run_bgc.py", "--bgc_binary", BGC, "--ini_file", NORM_INI])

# S7 extract sim daily GPP (col index 7, kgC/m2/d -> gC/m2/d)
day = pd.read_csv(DAYOUT, sep=r"\s+", header=None)
sim_gpp = day[7].values * 1000.0
dates = pd.date_range(f"{Y0}-01-01", f"{Y1}-12-31", freq="D")
dates = dates[~((dates.month == 2) & (dates.day == 29))]
assert len(dates) == len(sim_gpp), f"{len(dates)} vs {len(sim_gpp)}"
sim = pd.Series(sim_gpp, index=dates)

# obs daily GPP_NT_VUT_REF
obs = pd.read_csv(FLUX)
obs = obs.replace(-9999.0, np.nan)
obs["date"] = pd.to_datetime(obs["TIMESTAMP"], format="%Y%m%d")
obs = obs.set_index("date")["GPP_NT_VUT_REF"]
obs = obs[~((obs.index.month == 2) & (obs.index.day == 29))]

df = pd.DataFrame({"sim": sim, "obs": obs}).dropna()
print(f"paired days: {len(df)}  obs mean {df.obs.mean():.2f}  sim mean {df.sim.mean():.2f}")

m = all_metrics(df["obs"].values, df["sim"].values)
yrs = sorted(df.index.year.unique())
split = yrs[int(len(yrs)*0.6)]
cal = df[df.index.year < split]; val = df[df.index.year >= split]
mc = all_metrics(cal["obs"].values, cal["sim"].values)
mv = all_metrics(val["obs"].values, val["sim"].values)

result = {
    "model_id": "BIOME_BGC",
    "this_location": "FLUXNET2015 Global Flux Tower Network (192 sites)",
    "obs_source": "FLUXNET2015 Global Flux Tower Network (192 sites)",
    "status": "completed",
    "tools_used": ["select_ecophysiology.py", "convert_forcing_to_bgc.py",
                   "generate_site_ini.py", "run_bgc_spinup.py", "run_bgc.py",
                   "ki_tools_common.soil_utils.lookup_hwsd",
                   "ki_tools_common.metrics.all_metrics"],
    "tools_failed": [],
    "metrics": {
        "nse": round(m["NSE"],4), "kge": round(m["KGE"],4),
        "pbias": round(m["PBIAS"],4), "r": round(m["r"],4),
        "rmse": round(m["RMSE"],4),
        "nse_cal": round(mc["NSE"],4), "kge_cal": round(mc["KGE"],4),
        "nse_val": round(mv["NSE"],4), "kge_val": round(mv["KGE"],4),
        "pbias_val": round(mv["PBIAS"],4),
        "period": f"{yrs[0]}-{yrs[-1]}",
        "period_calibration": f"{yrs[0]}-{split-1}",
        "period_validation": f"{split}-{yrs[-1]}",
    },
    "water_balance": {"status": "N/A", "residual_pct": None},
    "notes": (f"BIOME-BGC 4.2 ENF (default params, NO calib) at temperate-maritime ENF site "
              f"DE-Tha (Tharandt Norway spruce, Germany, 50.96N 13.57E, 385m) — close analog "
              f"of the NL-Loo temperate-ENF real-case. "
              f"Daily GPP NSE {m['NSE']:.3f}/KGE {m['KGE']:.3f}/r {m['r']:.3f}/"
              f"PBIAS {m['PBIAS']:.1f}% (val NSE {mv['NSE']:.3f}, cal {mc['NSE']:.3f}). "
              f"sim mean {df.sim.mean():.2f} vs obs {df.obs.mean():.2f} gC/m2/d, n={len(df)}d, "
              f"soil loam sand{SAND}/silt{SILT}/clay{CLAY} via lookup_hwsd. "
              f"Same pipeline/leap-day-fix as NL-Loo real-case.")
}
os.makedirs(WORK, exist_ok=True)
with open(f"{WORK}/result.json", "w") as f:
    json.dump(result, f, indent=2)
print(json.dumps(result["metrics"], indent=2))
print("WROTE", f"{WORK}/result.json")
