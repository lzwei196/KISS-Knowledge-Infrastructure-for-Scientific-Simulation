#!/usr/bin/env python3
"""
Verifier run_and_score for BIOME-BGC at FLUXNET2015 US-MMS (Morgan Monroe State
Forest, Indiana, temperate Deciduous Broadleaf Forest, 39.32N -86.41W).

Contrasts the Real-case boreal ENF FI-Hyy site with a temperate DBF site to
test cross-biome consistency. Uses the KI tools end-to-end:
  convert_forcing_to_bgc -> generate_site_ini (spinup) -> run_bgc_spinup ->
  generate_site_ini (normal) -> run_bgc -> parse daily GPP.

RESUMABLE: skips spinup/normal runs whose output files already exist.

Obs: FLUXNET2015 US-MMS FULLSET_DD GPP_NT_VUT_REF (gC/m2/d).
Sim: BIOME-BGC summary.daily_gpp (kgC/m2/d) * 1000.
"""
import os, sys, json, subprocess, calendar
from datetime import date

KI = "KISSPATH_KI_ROOT/BIOME_BGC/knowledge_infrastructure"
BGC = "KISSPATH_BINARIES/biome-bgc/bgc-src/bgc"
TOOLS = os.path.join(KI, "tools")
OBS = "KISSPATH_OBS/fluxnet/sites/US-MMS/FULLSET_DD.csv"
OUT = "KISSPATH_KI_ROOT/BIOME_BGC/detached/verify_1"
RESULT = os.path.join(OUT, "result.json")

# --- Site ---
SITE = "usmms"
LAT, LON, ELEV = 39.3232, -86.4131, 275.0
PFT = "DBF"
START, END = 1999, 2014
NYEARS = END - START + 1
CO2_PPM = 385.0     # ~1999-2014 mean; constant, matching Real-case no-calib approach
CAL_END = 2009      # cal 1999-2009, val 2010-2014

sys.path.insert(0, KI)
sys.path.insert(0, os.path.join(KI, "lib"))
from ki_tools_common.metrics import all_metrics
from ki_tools_common.soil_utils import lookup_hwsd


def run(cmd):
    print(">>", " ".join(cmd), flush=True)
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        print(p.stdout); print(p.stderr)
        raise RuntimeError(f"FAILED ({p.returncode}): {' '.join(cmd)}")
    return p.stdout


def main():
    os.makedirs(OUT, exist_ok=True)
    for sub in ("metdata", "epc", "outputs", "restart"):
        os.makedirs(os.path.join(OUT, sub), exist_ok=True)

    soil = lookup_hwsd(LAT, LON)
    sand, silt, clay = soil["sand"], soil["silt"], soil["clay"]
    # renormalize to 100
    tot = sand + silt + clay
    sand, silt, clay = [round(x * 100.0 / tot, 1) for x in (sand, silt, clay)]
    print(f"Soil HWSD: sand={sand} silt={silt} clay={clay} ({soil['texture']})", flush=True)

    epc = os.path.join(OUT, "epc", f"{SITE}.epc")
    met = os.path.join(OUT, "metdata", f"{SITE}.mtc43")
    spin_ini = os.path.join(OUT, "spinup.ini")
    norm_ini = os.path.join(OUT, "normal.ini")
    spin_prefix = os.path.join(OUT, "outputs", "spinup")
    norm_prefix = os.path.join(OUT, "outputs", "normal")
    restart = os.path.join(OUT, "restart", f"{SITE}.endpoint")
    dayout = norm_prefix + ".dayout.ascii"

    # S2 ecophysiology
    run([sys.executable, os.path.join(TOOLS, "select_ecophysiology.py"),
         "--pft", PFT, "--output", epc])

    # S3 forcing (KI tool) then drop leap Feb-29 lines so each year has 365
    run([sys.executable, os.path.join(TOOLS, "convert_forcing_to_bgc.py"),
         "--forcing_file", OBS, "--source", "fluxnet",
         "--lat", str(LAT), "--start_year", str(START), "--end_year", str(END),
         "--output", met])
    with open(met) as f:
        lines = f.readlines()
    header, body = lines[:4], lines[4:]
    kept = []
    for ln in body:
        parts = ln.split()
        if not parts:
            continue
        yr, yday = int(parts[0]), int(parts[1])
        if calendar.isleap(yr) and yday == 60:   # Feb-29 -> drop
            continue
        kept.append(ln)
    with open(met, "w") as f:
        f.writelines(header + kept)
    # sanity: 365/year
    per = {}
    for ln in kept:
        per[int(ln.split()[0])] = per.get(int(ln.split()[0]), 0) + 1
    assert all(v == 365 for v in per.values()), per
    print(f"met file: {len(kept)} lines = {len(per)} yrs x 365", flush=True)

    common = ["--met_file", met, "--epc_file", epc, "--lat", str(LAT),
              "--elevation", str(ELEV), "--soil_depth", "1.0",
              "--sand", str(sand), "--silt", str(silt), "--clay", str(clay),
              "--start_year", str(START), "--n_met_years", str(NYEARS),
              "--co2_ppm", str(CO2_PPM)]

    # S5 spinup
    if not os.path.exists(restart):
        run([sys.executable, os.path.join(TOOLS, "generate_site_ini.py"),
             *common, "--output_prefix", spin_prefix, "--mode", "spinup",
             "--max_spinup_years", "6000", "--restart_file", restart,
             "--write_restart", "--output", spin_ini])
        run([sys.executable, os.path.join(TOOLS, "run_bgc_spinup.py"),
             "--bgc_binary", BGC, "--ini_file", spin_ini, "--timeout", "1200"])
    else:
        print("spinup restart exists, skipping", flush=True)

    # S6 normal
    if not os.path.exists(dayout):
        run([sys.executable, os.path.join(TOOLS, "generate_site_ini.py"),
             *common, "--output_prefix", norm_prefix, "--mode", "normal",
             "--restart_file", restart, "--read_restart", "--output", norm_ini])
        run([sys.executable, os.path.join(TOOLS, "run_bgc.py"),
             "--bgc_binary", BGC, "--ini_file", norm_ini, "--ascii",
             "--timeout", "600"])
    else:
        print("dayout exists, skipping normal run", flush=True)

    # --- Parse sim daily GPP (col index 7 -> kgC/m2/d) and build dates ---
    GPP_COL = 7
    sim_vals = []
    with open(dayout) as f:
        for ln in f:
            p = ln.split()
            if len(p) >= 23:
                sim_vals.append(float(p[GPP_COL]) * 1000.0)  # kgC->gC
    # build sim dates: chronological, 365/yr, Feb-29 removed
    sim_dates = []
    for yr in range(START, END + 1):
        d = date(yr, 1, 1)
        while d.year == yr:
            if not (calendar.isleap(yr) and d.month == 2 and d.day == 29):
                sim_dates.append(d)
            d = date.fromordinal(d.toordinal() + 1)
    assert len(sim_dates) == len(sim_vals), (len(sim_dates), len(sim_vals))
    sim = dict(zip(sim_dates, sim_vals))

    # --- Obs ---
    import csv
    obs = {}
    with open(OBS) as f:
        r = csv.DictReader(f)
        for row in r:
            ts = row["TIMESTAMP"]
            y = int(ts[:4])
            if y < START or y > END:
                continue
            g = float(row["GPP_NT_VUT_REF"])
            if g <= -9990:
                continue
            obs[date(y, int(ts[4:6]), int(ts[6:8]))] = g

    def metrics_for(d0, d1):
        o, s = [], []
        for dt in sorted(set(sim) & set(obs)):
            if d0 <= dt.year <= d1:
                o.append(obs[dt]); s.append(sim[dt])
        m = all_metrics(o, s)
        return m, len(o)

    m_all, n_all = metrics_for(START, END)
    m_cal, n_cal = metrics_for(START, CAL_END)
    m_val, n_val = metrics_for(CAL_END + 1, END)

    mean_sim = sum(sim.values()) / len(sim)
    mean_obs = sum(obs.values()) / len(obs)

    out = {
        "model_id": "BIOME_BGC",
        "this_location": "FLUXNET2015 (192 sites)",
        "obs_source": "FLUXNET2015 US-MMS GPP_NT_VUT_REF",
        "status": "completed",
        "tools_used": ["select_ecophysiology.py", "convert_forcing_to_bgc.py",
                       "generate_site_ini.py", "run_bgc_spinup.py", "run_bgc.py",
                       "ki_tools_common.soil_utils.lookup_hwsd",
                       "ki_tools_common.metrics.all_metrics"],
        "tools_failed": [],
        "metrics": {
            "nse": round(m_all["NSE"], 4), "kge": round(m_all["KGE"], 4),
            "pbias": round(m_all["PBIAS"], 3), "r": round(m_all["r"], 4),
            "rmse": round(m_all["RMSE"], 4),
            "nse_cal": round(m_cal["NSE"], 4), "kge_cal": round(m_cal["KGE"], 4),
            "nse_val": round(m_val["NSE"], 4), "kge_val": round(m_val["KGE"], 4),
            "pbias_val": round(m_val["PBIAS"], 3),
            "n_days": n_all, "n_cal": n_cal, "n_val": n_val,
            "mean_sim_gC_m2_d": round(mean_sim, 3),
            "mean_obs_gC_m2_d": round(mean_obs, 3),
            "period": f"{START}-{END}",
            "period_calibration": f"{START}-{CAL_END}",
            "period_validation": f"{CAL_END+1}-{END}",
        },
        "water_balance": {"status": "N/A", "residual_pct": None},
        "location": "FLUXNET2015 US-MMS (Morgan Monroe, Indiana, temperate DBF, 39.32N -86.41W)",
        "notes": (f"BIOME-BGC 4.2 DBF (default ecophysiology, no calibration) at temperate "
                  f"deciduous broadleaf US-MMS. Daily GPP {START}-{END}: NSE {m_all['NSE']:.3f}/"
                  f"KGE {m_all['KGE']:.3f}/r {m_all['r']:.3f}/PBIAS {m_all['PBIAS']:.1f}% "
                  f"(val NSE {m_val['NSE']:.3f}). Mean GPP sim {mean_sim:.2f} vs obs {mean_obs:.2f} "
                  f"gC/m2/d. HWSD {soil['texture']}. Leap Feb-29 dropped from met (365/yr per "
                  f"metarr_init.c). Same KI tools as Real-case FI-Hyy.")
    }
    with open(RESULT, "w") as f:
        json.dump(out, f, indent=2)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
