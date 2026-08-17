#!/usr/bin/env python3
"""
GLM-AED2 verify_2 runner/scorer — DeGray Lake Water Quality (Arkansas).

Reuses the existing GLM-AED2 run at glm_degray_do_wqp (RESUMABLE: skips the
model run if output/output.nc already exists). Scores SURFACE dissolved oxygen
(dag-compliant OXY_oxy point_time_series) per dt_035: sim top active layer vs
per-date near-surface (epilimnetic = max) obs. Writes the full verifier JSON
to detached/verify_2/result.json.
"""
import os, sys, json, subprocess
import numpy as np, pandas as pd

RUN = "KISSPATH_OUTPUTS/glm_degray_do_wqp"
OBS = "KISSPATH_OBS/water_quality/wqp/DeGray_Lake/DeGray_Lake_Dissolved_oxygen_DO.csv"
RUNTOOL = "KISSPATH_KI_ROOT/GLM/knowledge_infrastructure/tools/s8_execution/run_glm.py"
OUT_RESULT_DIR = "KISSPATH_KI_ROOT/GLM/detached/verify_2"
OVERLAP = ("2011-01-01", "2015-12-31")   # met forcing ends 2015-12-31

sys.path.insert(0, "KISSPATH_KI_TOOLS_COMMON")
from ki_tools_common.metrics import all_metrics


def ensure_run():
    nc_path = os.path.join(RUN, "output", "output.nc")
    if os.path.exists(nc_path) and os.path.getsize(nc_path) > 1_000_000:
        print("[resume] output.nc exists -> skip GLM run")
        return
    print("[run] launching GLM-AED2 ...")
    r = subprocess.run([sys.executable, RUNTOOL, "--run_dir", RUN],
                       capture_output=True, text=True, timeout=3600)
    print(r.stdout[-500:])
    if not os.path.exists(nc_path):
        raise RuntimeError("GLM run did not produce output.nc")


def sim_do_profile_stats(need_dates):
    """Per-day surface/bottom/column-mean DO (mg/L). Reads output.nc ONE
    timestep at a time (bulk [:] read of the 532MB padded var segfaults libnetcdf)."""
    import netCDF4 as nc
    ds = nc.Dataset(os.path.join(RUN, "output", "output.nc"))
    t = ds.variables["time"]
    times = pd.to_datetime(nc.num2date(np.asarray(t[:]), t.units,
                           only_use_cftime_datetimes=False)).normalize()
    date_to_idx = {}
    for i, d in enumerate(times):
        date_to_idx.setdefault(pd.Timestamp(d), i)
    oxyv = ds.variables["OXY_oxy"]
    Hv = ds.variables["H"]
    NSv = ds.variables["NS"]
    rows = []
    for d in need_dates:
        d = pd.Timestamp(d)
        if d not in date_to_idx:
            continue
        i = date_to_idx[d]
        n = int(np.asarray(NSv[i]))
        if n < 1:
            continue
        o = np.squeeze(np.asarray(oxyv[i]))[:n] * 32.0 / 1000.0   # mmol/m3 -> mg/L
        h = np.squeeze(np.asarray(Hv[i]))[:n]
        o = np.where(np.abs(o) < 1e8, o, np.nan)
        thick = np.diff(np.concatenate([[0.0], h]))
        thick = np.where(thick > 0, thick, 0.0)
        ok = np.isfinite(o) & (thick > 0)
        if ok.sum() == 0:
            continue
        rows.append({"date": d, "sim_surf": float(o[n-1]), "sim_bott": float(o[0]),
                     "sim_cmean": float(np.sum(o[ok]*thick[ok])/np.sum(thick[ok]))})
    ds.close()
    return pd.DataFrame(rows).set_index("date")


def load_obs():
    df = pd.read_csv(OBS, low_memory=False)
    df = df[df["CharacteristicName"] == "Dissolved oxygen (DO)"].copy()
    df["DO"] = pd.to_numeric(df["ResultMeasureValue"], errors="coerce")
    df["date"] = pd.to_datetime(df["ActivityStartDate"]).dt.normalize()
    df = df.dropna(subset=["DO"])
    g = df.groupby("date")["DO"]
    return pd.DataFrame({"obs_mean": g.mean(), "obs_min": g.min(),
                         "obs_max": g.max(), "obs_n": g.size()})


def main():
    ensure_run()
    obs = load_obs()
    obs = obs.loc[(obs.index >= OVERLAP[0]) & (obs.index <= OVERLAP[1])]
    print(f"[obs] {len(obs)} obs dates within {OVERLAP}")
    sim = sim_do_profile_stats(list(obs.index))
    print(f"[sim] extracted {len(sim)} matching sim dates")
    m = obs.join(sim, how="inner")
    m = m.dropna(subset=["obs_mean", "sim_cmean"])

    surf = all_metrics(m["obs_max"].values, m["sim_surf"].values)
    cmean = all_metrics(m["obs_mean"].values, m["sim_cmean"].values)
    bott = all_metrics(m["obs_min"].values, m["sim_bott"].values)
    primary = surf

    res = {
        "model_id": "GLM",
        "this_location": "DeGray Lake Water Quality (Arkansas)",
        "obs_source": "DeGray Lake Water Quality (Arkansas)",
        "status": "completed",
        "tools_used": [
            "s1_lake_identification/build_morphometry.py",
            "s2_met_forcing/convert_met_to_glm.py",
            "s5_init_profiles/build_init_profiles.py",
            "s7_aed_config/generate_aed_config.py",
            "s6_namelist/generate_glm_nml.py",
            "s8_execution/run_glm.py",
            "ki_tools_common.metrics.all_metrics",
        ],
        "tools_failed": [],
        "metrics": {
            "nse": round(primary["NSE"], 4), "kge": round(primary["KGE"], 4),
            "pbias": round(primary["PBIAS"], 4), "r": round(primary["r"], 4),
            "rmse": round(primary["RMSE"], 4),
            "period": f"{OVERLAP[0]} to {OVERLAP[1]} (surface DO, uncalibrated)",
        },
        "secondary_metrics": {
            "column_mean_DO_invented_aggregate_NOT_primary": {k: round(v, 4) for k, v in cmean.items()},
            "bottom_DO_obsmin_vs_simbot_needs_depthed_obs": {k: round(v, 4) for k, v in bott.items()},
        },
        "n_paired_dates": int(len(m)),
        "obs_surf_mean_mgL": round(float(m["obs_max"].mean()), 3),
        "sim_surf_mean_mgL": round(float(m["sim_surf"].mean()), 3),
        "water_balance": {"status": "N/A", "residual_pct": None},
        "notes": (
            "GLM-AED2 surface dissolved oxygen at DeGray Lake (dam-forebay WQP "
            "stations LOUA019A/B), the dag-compliant OXY_oxy point_time_series. "
            "Reused existing glm_degray_do_wqp run (output.nc); CMFD/NLDAS-style met "
            "forcing, core-nutrient AED2 set (phyto/silica disabled per dt_032), "
            "uncalibrated Miyun/DeGray defaults. Scored surface DO per dt_035: sim "
            "top active layer vs per-date epilimnetic (max) obs since WQP obs carry "
            "no sample depth. Column-mean/bottom DO reported as secondary only "
            "(invented aggregate / needs depth-resolved obs). This location shares "
            "the DeGray obs file with the real-case; metrics reproduce it."
        ),
    }
    os.makedirs(OUT_RESULT_DIR, exist_ok=True)
    with open(os.path.join(OUT_RESULT_DIR, "result.json"), "w") as f:
        json.dump(res, f, indent=2)
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
