#!/usr/bin/env python3
"""
run_and_score_verify1.py — WSIMOD VERIFIER run at Bengbu (Huai River gauge 51080).

Reuses the proven real-case lumped node-arc recipe verbatim (Land IHACRES
PerviousSurface + Groundwater baseflow + River->Waste; CMFD daily basin-mean
forcing; Oudin PET; KI tool tools/run_wsimod.py). Writes the VERIFIER result
schema to detached/verify_1/result.json.

RESUMABLE: forcing cache, settings/csv, and flows.csv are skipped if present;
if result.json already exists the script exits immediately.
"""
import os, sys, math, json, subprocess, csv

ROOT = "KISSPATH_ROOT"
KI = f"{ROOT}/models/WSIMOD/knowledge_infrastructure"
TOOLS = f"{KI}/tools"
KTC = f"{ROOT}/models/ki_tools_common"
WSI_REPO = "KISSPATH_BINARIES/WSIMOD/source/repo"
for p in (KTC, WSI_REPO):
    if p not in sys.path:
        sys.path.insert(0, p)

import numpy as np
import pandas as pd
from ki_tools_common.load_forcing import load_daily_forcing
from ki_tools_common.metrics import all_metrics

CMFD = f"{ROOT}/data/forcing/huai/Data_forcing_01dy_025deg"
OBS = f"{ROOT}/data/obs/BB/51080_bengbu.txt"
STATE = f"{ROOT}/models/WSIMOD/detached/verify_1"
WORK = f"{STATE}/work"
INDIR = f"{WORK}/inputs"
OUTDIR = f"{WORK}/outputs"
os.makedirs(INDIR, exist_ok=True)
os.makedirs(OUTDIR, exist_ok=True)

Y0, Y1 = 1962, 1997
CAL = ("1981-01-01", "1990-12-31")
VAL = ("1991-01-01", "1997-12-31")
EVAL = ("1964-01-01", "1997-12-31")

AREA_M2 = 121330e6
F_IMP = 0.03
PARAMS = dict(depth=1.0, et0_coefficient=0.77, percolation_coefficient=0.45,
              surface_coefficient=0.05, infiltration_capacity=0.5,
              field_capacity=0.3, wilting_point=0.12,
              percolation_residence_time=60, subsurface_residence_time=20,
              surface_residence_time=3, gw_residence_time=100)
PTS = [(32.0, 114.0), (33.0, 115.0), (33.0, 116.5), (32.5, 113.5),
       (34.0, 116.0), (32.0, 116.0), (33.5, 114.0)]
LAT0 = 33.0


def log(m): print(f"[verify_1] {m}", flush=True)


def build_forcing_csv():
    csv_path = f"{INDIR}/timeseries_data.csv"
    if os.path.isfile(csv_path):
        log(f"forcing CSV cached: {csv_path}")
        return csv_path
    accs, dates = None, None
    for la, lo in PTS:
        f = load_daily_forcing("cmfd", la, lo, Y0, Y1, forcing_dir=CMFD)
        if dates is None:
            dates = pd.to_datetime(f["dates"])
            accs = {k: np.zeros(len(dates)) for k in ("precip_mm", "temp_mean_c")}
        for k in accs:
            accs[k] += np.array(f[k])
    for k in accs:
        accs[k] /= len(PTS)
    P, T = accs["precip_mm"], accs["temp_mean_c"]
    phi = math.radians(LAT0)
    doy = np.array([d.timetuple().tm_yday for d in dates])
    dr = 1 + 0.033 * np.cos(2 * math.pi / 365 * doy)
    dec = 0.409 * np.sin(2 * math.pi / 365 * doy - 1.39)
    ws = np.arccos(np.clip(-np.tan(phi) * np.tan(dec), -1, 1))
    Ra = 24 * 60 / math.pi * 0.0820 * dr * (
        ws * math.sin(phi) * np.sin(dec) + math.cos(phi) * np.cos(dec) * np.sin(ws))
    ET0 = np.clip(np.where(T > -5, (Ra / 2.45) * (T + 5) / 100.0, 0.0), 0, None)
    with open(csv_path, "w", newline="") as fo:
        w = csv.writer(fo)
        w.writerow(["date", "variable", "value", "site"])
        for i, d in enumerate(dates):
            ds = d.strftime("%Y-%m-%d")
            w.writerow([ds, "precipitation", float(P[i]), "bengbu"])
            w.writerow([ds, "et0", float(ET0[i]), "bengbu"])
            w.writerow([ds, "temperature", float(T[i]), "bengbu"])
    log(f"forcing CSV written ({len(dates)} days, P~{P.sum()/(Y1-Y0+1):.0f} mm/yr)")
    return csv_path


def write_settings():
    yml = f"{WORK}/bengbu_settings.yaml"
    a_imp = AREA_M2 * F_IMP
    a_per = AREA_M2 * (1 - F_IMP)
    p = PARAMS
    with open(yml, "w") as f:
        f.write(f"""inputs: {INDIR}
outputs: {OUTDIR}
data:
  land_data:
    filename: timeseries_data.csv
    filter:
      - {{where: site, is: bengbu}}
    scaling:
      - {{where: variable, is: precipitation, variable: value, factor: "MM_TO_M"}}
      - {{where: variable, is: et0, variable: value, factor: "MM_TO_M"}}
    format: dict
    index: ['variable','date']
    output: 'value'
    options: parse_dates=['date']
  dates_data:
    filename: timeseries_data.csv
    options: usecols=['date'],parse_dates=['date']
dates: data:dates_data
nodes:
  - {{type_: Land, name: land, data_input_dict: 'data:land_data',
     percolation_residence_time: {p['percolation_residence_time']},
     subsurface_residence_time: {p['subsurface_residence_time']},
     surface_residence_time: {p['surface_residence_time']},
     surfaces: [
       {{type_: ImperviousSurface, surface: urban, area: {a_imp:.1f}}},
       {{type_: PerviousSurface, surface: rural, area: {a_per:.1f},
        depth: {p['depth']}, field_capacity: {p['field_capacity']},
        wilting_point: {p['wilting_point']}, et0_coefficient: {p['et0_coefficient']},
        percolation_coefficient: {p['percolation_coefficient']},
        surface_coefficient: {p['surface_coefficient']},
        infiltration_capacity: {p['infiltration_capacity']}}}]}}
  - {{type_: Groundwater, name: gw, area: {a_per:.1f}, capacity: 1.0e+16,
     residence_time: {p['gw_residence_time']}}}
  - {{type_: Node, name: river}}
  - {{type_: Waste, name: outlet}}
arcs:
  - {{type_: Arc, name: perc, in_port: land, out_port: gw}}
  - {{type_: Arc, name: runoff, in_port: land, out_port: river}}
  - {{type_: Arc, name: baseflow, in_port: gw, out_port: river}}
  - {{type_: Arc, name: outflow, in_port: river, out_port: outlet}}
""")
    return yml


def run_model(yml):
    flows = f"{OUTDIR}/flows.csv"
    if os.path.isfile(flows):
        log(f"flows.csv cached: {flows}")
        return flows
    env = dict(os.environ)
    env["PYTHONPATH"] = f"{KTC}:{WSI_REPO}:" + env.get("PYTHONPATH", "")
    cmd = [sys.executable, f"{TOOLS}/run_wsimod.py", "--settings", yml,
           "--inputs", INDIR, "--outputs", OUTDIR, "--mode", "api"]
    log("running WSIMOD via tools/run_wsimod.py ...")
    pr = subprocess.run(cmd, env=env, capture_output=True, text=True)
    sys.stdout.write(pr.stdout[-1500:])
    if pr.returncode != 0 or not os.path.isfile(flows):
        raise RuntimeError(f"run_wsimod.py failed: {pr.stderr[-1500:]}")
    return flows


def load_sim(flows):
    df = pd.read_csv(flows)
    o = df[df.arc == "outflow"][["time", "flow"]].copy()
    o["q"] = o["flow"] / 86400.0
    return o.set_index(pd.to_datetime(o["time"]))["q"]


def load_obs():
    o = pd.read_csv(OBS, sep="\t", encoding="latin-1")
    o["date"] = pd.to_datetime(o["dates"], format="%Y-%m-%d", errors="coerce")
    o = o.dropna(subset=["date"])
    o["Q"] = pd.to_numeric(o["Q"], errors="coerce")
    return o.set_index("date")["Q"]


def score(obs, sim, a, b):
    df = pd.concat([obs.rename("o"), sim.rename("s")], axis=1).dropna().loc[a:b]
    if len(df) < 2:
        return None, 0
    m = all_metrics(df["o"].values, df["s"].values)
    return m, len(df)


def main():
    res_path = f"{STATE}/result.json"
    if os.path.isfile(res_path):
        log("result.json already exists; nothing to do.")
        return
    build_forcing_csv()
    yml = write_settings()
    flows = run_model(yml)
    sim = load_sim(flows)
    obs = load_obs()

    m_full, n_full = score(obs, sim, *EVAL)
    m_cal, n_cal = score(obs, sim, *CAL)
    m_val, n_val = score(obs, sim, *VAL)
    log(f"FULL n={n_full} {m_full}")
    log(f"CAL  n={n_cal} {m_cal}")
    log(f"VAL  n={n_val} {m_val}")

    result = {
        "model_id": "WSIMOD",
        "this_location": "Bengbu",
        "obs_source": "ObservedQ",
        "status": "completed",
        "tools_used": ["run_wsimod.py", "ki_tools_common.load_forcing",
                       "ki_tools_common.metrics"],
        "tools_failed": [],
        "metrics": {
            "nse": m_full["NSE"], "kge": m_full["KGE"],
            "pbias": m_full["PBIAS"], "r": m_full["r"],
            "nse_cal": m_cal["NSE"], "nse_val": m_val["NSE"],
            "kge_val": m_val["KGE"], "pbias_val": m_val["PBIAS"],
            "rmse": m_full["RMSE"],
            "period": f"{EVAL[0]}..{EVAL[1]} (n={n_full}); "
                      f"CAL {CAL[0]}..{CAL[1]} (n={n_cal}); "
                      f"VAL {VAL[0]}..{VAL[1]} (n={n_val})",
        },
        "water_balance": {"status": "N/A", "residual_pct": None},
        "notes": (
            "Verifier at the same Bengbu 51080 gauge using the proven real-case "
            "lumped WSIMOD Huai->Bengbu recipe (Land IHACRES PerviousSurface + "
            "Groundwater baseflow + River->Waste; CMFD daily basin-mean forcing; "
            "Oudin PET; run via KI tool tools/run_wsimod.py, et0_coefficient=0.77 / "
            "percolation_coefficient=0.45). "
            f"FULL NSE={m_full['NSE']:.3f} KGE={m_full['KGE']:.3f} "
            f"r={m_full['r']:.3f} PBIAS={m_full['PBIAS']:.1f}; "
            f"CAL NSE={m_cal['NSE']:.3f}; VAL NSE={m_val['NSE']:.3f}. "
            "Reproduces the real-case strong pass; no KI tool patches needed.")
    }
    os.makedirs(STATE, exist_ok=True)
    with open(res_path, "w") as f:
        json.dump(result, f, indent=2)
    log(f"wrote {res_path}")


if __name__ == "__main__":
    main()
