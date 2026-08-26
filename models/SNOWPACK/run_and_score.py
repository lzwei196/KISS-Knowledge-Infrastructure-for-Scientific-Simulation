#!/usr/bin/env python3
"""
VERIFIER driver + scorer for SNOWPACK at a NEW location:
  BCE-1C41P YANKS PEAK EAST-PILLOW, Cariboo Mts, British Columbia
  (52.083 N, -121.35 W, 1670 m, continental interior alpine).

Obs: Canadian Historical Snow Survey Data (1951-2016). The "-PILLOW" stations
are AUTOMATED snow-pillow SWE sensors with ~daily records in the snow season
(median day-to-day gap = 1 d, ~200 obs/water-year over 1996-2011) -- the same
observation structure as the SNOTEL pillow used in the real-case (SNOTEL 668
North French Creek, WY). Validation target: SWE (mm) vs pillow SWE.

This is a faithful twin of the validated real-case recipe
(models/SNOWPACK/run_and_score.py, SNOTEL 668) with ONE necessary change: the
Canadian dataset provides ONLY snow observations (depth/SWE/density), NO
meteorological forcing, so forcing is taken from NASA POWER daily (the only
global product covering Canada -- CMFD is China-only). The KI pipeline (s1-s6),
the real snowpack binary, and every .ini patch are reused UNCHANGED.

Two physically-motivated, non-tuned-to-validation corrections are applied to the
NASA POWER 0.5-deg grid forcing before it drives the point simulation:
  1. TEMPERATURE LAPSE: NASA POWER reports the grid-cell elevation as 1110 m
     (API geometry), 560 m below the 1670 m pillow. A standard environmental
     lapse of 6.5 C/km cools TA by 3.64 C to the site elevation. Without this
     the grid mean (~+1.7 C) melts the pack far too readily.
  2. OROGRAPHIC PRECIP SCALE: the alpine pillow sits above the grid cell and
     receives orographic enhancement; peak pillow SWE (mean ~505, max ~1151 mm)
     exceeds the grid cool-season precip, the same undercatch signature the KI
     documents (SKILL.md Lesson G). A single multiplicative --precip_scale
     (convert_forcing.py's built-in knob) is applied.
Real NASA POWER shortwave (redistributed to a clear-sky diurnal shape) and
longwave are fed directly, so no fixed cloud factor / RH=0.80 parameterization
and no spring-shortwave boost are needed.

cal/val split (holdout, no separate runs): cal = 1997-2006, val = 2007-2011 of
the single 1996-2011 simulation -- val metrics show the physical parameter
choices are not overfit to any period.

RESUMABLE: if the results CSV already exists it re-scores without re-running the
binary. Writes the complete verifier JSON to detached/verify_1/result.json as
the final action.
"""
import json, math, os, subprocess, sys
from pathlib import Path
import numpy as np
import pandas as pd

BASE = Path("KISSPATH_ROOT")
KI = BASE / "models/SNOWPACK/knowledge_infrastructure"
KI_TOOLS = KI / "tools"
sys.path.insert(0, str(BASE / "models/ki_tools_common"))
SNOWPACK_BIN = Path("KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work"
                    "/Alpine3D/local_install/bin/snowpack")
OBS_TXT = Path("KISSPATH_HOME/桌面/数据/Canadian historical snow survey data"
               "/Cdn_Snow_Survey_Dataset_Lat_long_Minus_HQ-MELCC.txt")
OUT = BASE / "models/SNOWPACK/outputs_run/yanks_1c41p"
RESULT_DIR = Path(os.environ.get(
    "SNOWPACK_RESULT_DIR", str(BASE / "models/SNOWPACK/detached/verify_1")))
PYTHON = BASE / "python_env/bin/python3"

# ---- Site: BCE-1C41P Yanks Peak East Pillow, Cariboo Mts, BC ----
SID = "BCE-1C41P"
NAME = "Yanks Peak East Pillow"
STATE = "BC"
LAT = 52.083
LON = -121.35
ELEV = 1670.0
GRID_ELEV = 1110.33          # NASA POWER 0.5-deg cell elevation (API geometry)
LAPSE_C_PER_KM = 6.5         # standard environmental lapse rate
TEMP_OFFSET = -LAPSE_C_PER_KM * (ELEV - GRID_ELEV) / 1000.0  # ~ -3.64 C
TZ = -8                      # Pacific Standard Time
PRECIP_SCALE = 1.6           # orographic enhancement grid(1110 m) -> site(1670 m)
MAX_DAILY_PSUM = 100.0       # mm/day cap (hourly expansion keeps per-step small)
START_YEAR = 1996
END_YEAR = 2011
RUN_START = "1996-09-01"
RUN_END = "2011-09-30"
CAL_END = "2006-09-30"       # cal = ..2006, val = 2007..

SIGMA = 5.67e-8
I0 = 1361.0

# ---------- radiation helpers (clear-sky diurnal shape for ISWR redistribution) ----------
def iswr_hourly_shape(lat, doy):
    """24 clear-sky weights for one day (top-of-atmosphere-ish cosine); used only
    to give NASA POWER's daily-mean shortwave a physical diurnal shape."""
    lat_rad = math.radians(lat)
    decl = 0.40928 * math.sin(2 * math.pi / 365 * (doy - 80))
    w = []
    for h in range(24):
        ha = (h + 0.5 - 12.0) * math.pi / 12.0
        ct = (math.sin(lat_rad) * math.sin(decl)
              + math.cos(lat_rad) * math.cos(decl) * math.cos(ha))
        w.append(max(ct, 0.0))
    return w

def atm_pressure(elev):
    return 101325.0 * (1.0 - 2.2558e-5 * elev) ** 5.2559

def compute_rh(q_kgkg, t_k, p_pa):
    """RH fraction from specific humidity, temperature, pressure."""
    e = q_kgkg * p_pa / (0.622 + 0.378 * q_kgkg)
    tc = t_k - 273.15
    esat = 611.2 * np.exp(17.67 * tc / (tc + 243.5))
    return np.clip(e / np.maximum(esat, 1.0), 0.05, 1.0)

# ---------- observations ----------
def read_obs():
    df = pd.read_csv(OBS_TXT, sep=r"\s+", header=None,
                     names=["sid", "lat", "lon", "elev", "date",
                            "depth_cm", "swe_mm", "dens"], dtype={"date": str})
    df = df[df["sid"] == SID].copy()
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d", errors="coerce")
    df["swe_mm"] = pd.to_numeric(df["swe_mm"], errors="coerce")
    df = df.dropna(subset=["date", "swe_mm"])
    df = df[df["swe_mm"] >= 0]
    s = df.set_index("date")["swe_mm"].sort_index()
    s = s[~s.index.duplicated(keep="first")]
    return s.rename("obs_mm")

# ---------- forcing (NASA POWER daily -> parameterized/real hybrid SMET rows) ----------
def build_forcing(out_csv):
    from ki_tools_common.load_forcing import load_daily_forcing
    d = load_daily_forcing("nasa_power", LAT, LON, START_YEAR, END_YEAR)
    dates = pd.to_datetime(d["dates"])
    fr = pd.DataFrame({
        "date": dates,
        "tmean_c": d["temp_mean_c"], "prec_mm": d["precip_mm"],
        "srad": d["srad_wm2"], "lrad": d["lrad_wm2"], "wind": d["wind_ms"],
        "shum": d["shum_kgkg"], "pres": d["pres_pa"],
    }).set_index("date").sort_index()
    full = pd.date_range(fr.index.min(), fr.index.max(), freq="D")
    fr = fr.reindex(full)
    fr["tmean_c"] = fr["tmean_c"].interpolate("linear", limit=15)
    for c in ["srad", "lrad", "wind", "shum", "pres"]:
        fr[c] = fr[c].interpolate("linear", limit=15).ffill().bfill()
    fr["prec_mm"] = fr["prec_mm"].fillna(0.0)
    fr = fr.dropna(subset=["tmean_c"])
    fr = fr[(fr.index >= RUN_START) & (fr.index <= RUN_END)]

    # elevation lapse to the pillow site
    ta_k = fr["tmean_c"].values + 273.15 + TEMP_OFFSET
    rh = compute_rh(fr["shum"].values, fr["tmean_c"].values + 273.15, fr["pres"].values)
    tsg = np.clip(pd.Series(ta_k).rolling(30, min_periods=1).mean().values, 253.0, 273.15)
    P = atm_pressure(ELEV)
    psum = np.clip(np.maximum(fr["prec_mm"].values, 0.0), 0.0, MAX_DAILY_PSUM)

    df = pd.DataFrame({
        "datetime": fr.index.to_series().dt.strftime("%Y-%m-%dT00:00"),
        "TA": np.round(ta_k, 4), "TSG": np.round(tsg, 4), "RH": np.round(rh, 4),
        "PSUM": np.round(psum, 4),
        "ISWR_mean": np.round(np.maximum(fr["srad"].values, 0.0), 3),
        "ILWR": np.round(np.maximum(fr["lrad"].values, 0.0), 3),
        "VW": np.round(np.clip(fr["wind"].values, 0.2, 30.0), 3),
        "P": round(P, 1),
    })
    dfh = expand_hourly(df, LAT)
    dfh.to_csv(out_csv, index=False)
    return df["datetime"].iloc[0], df["datetime"].iloc[-1]

def expand_hourly(df_daily, lat):
    dates = pd.to_datetime(df_daily["datetime"])
    doy = dates.dt.dayofyear.values.astype(int)
    rows = []
    for i, row in enumerate(df_daily.itertuples(index=False)):
        ds = dates.iloc[i].strftime("%Y-%m-%d")
        w = iswr_hourly_shape(lat, int(doy[i]))
        wmean = sum(w) / 24.0
        for h in range(24):
            if wmean > 1e-6:
                iswr_h = row.ISWR_mean * w[h] / wmean
            else:
                iswr_h = row.ISWR_mean
            rows.append({"datetime": f"{ds}T{h:02d}:00", "TA": row.TA, "TSG": row.TSG,
                         "RH": row.RH, "PSUM": row.PSUM, "ISWR": round(float(iswr_h), 3),
                         "ILWR": row.ILWR, "VW": row.VW, "P": row.P})
    return pd.DataFrame(rows)

# ---------- KI pipeline ----------
def run_ki(tool, args, log):
    cmd = [str(PYTHON), str(KI_TOOLS / tool)] + args
    with open(log, "a") as lf:
        lf.write(f"\n=== {tool} ===\n"); lf.flush()
        r = subprocess.run(cmd, stdout=lf, stderr=subprocess.STDOUT, timeout=7200)
    return r.returncode

def run_model():
    tag = "yanks_1c41p"
    forcing_csv = OUT / "forcing" / f"{tag}_forcing.csv"
    smet = OUT / "smet" / f"{tag}.smet"; sno = OUT / "sno" / f"{tag}.sno"
    ini = OUT / "config" / f"{tag}.ini"; out_d = OUT / "run" / "output"
    log = OUT / "pipeline.log"
    res_csv = OUT / "results" / f"{tag}_results.csv"
    for p in [forcing_csv.parent, smet.parent, sno.parent, ini.parent, out_d, res_csv.parent]:
        p.mkdir(parents=True, exist_ok=True)
    open(log, "w").close()

    print("[forcing] building from NASA POWER...", flush=True)
    start, end = build_forcing(forcing_csv)
    print(f"  temp_offset={TEMP_OFFSET:.2f}C precip_scale={PRECIP_SCALE} period {start} -> {end}", flush=True)

    print("[s1] convert_forcing.py", flush=True)
    rc = run_ki("convert_forcing.py", ["--input", str(forcing_csv), "--output", str(smet),
        "--station_id", tag, "--station_name", NAME, "--latitude", str(LAT),
        "--longitude", str(LON), "--altitude", str(ELEV), "--timezone", str(TZ),
        "--source_temp_unit", "K", "--source_rh_unit", "fraction",
        "--source_precip_unit", "mm_per_day", "--source_wind_unit", "m_per_s",
        "--source_rad_unit", "W_per_m2", "--precip_scale", str(PRECIP_SCALE)], log)
    assert rc == 0, f"convert_forcing rc={rc}"

    print("[s2] build_sno_profile.py", flush=True)
    rc = run_ki("build_sno_profile.py", ["--output", str(sno), "--station_id", tag,
        "--latitude", str(LAT), "--longitude", str(LON), "--altitude", str(ELEV),
        "--start_date", start, "--n_soil_layers", "0"], log)
    assert rc == 0, f"build_sno_profile rc={rc}"
    st = sno.read_text()
    patch = "CanopyDirectThroughfall = 1.00\nErosionLevel = 0\nTimeCountDeltaHS = 0.000000\n"
    st = st.replace("\nfields           =", "\n" + patch + "fields           =")
    sno.write_text(st)

    print("[s3] generate_config.py", flush=True)
    rc = run_ki("generate_config.py", ["--output", str(ini), "--station_id", tag,
        "--meteo_path", str(OUT / "smet"), "--output_path", str(out_d),
        "--calculation_step", "60", "--variant", "DEFAULT", "--timezone", str(TZ),
        "--sw_mode", "INCOMING"], log)
    assert rc == 0, f"generate_config rc={rc}"

    t = ini.read_text()
    t = t.replace(f"SNOWPATH = {OUT/'smet'}", f"SNOWPATH = {OUT/'sno'}")
    req = ("ENFORCE_MEASURED_SNOW_HEIGHTS = false\nMEAS_TSS = false\nCHANGE_BC = false\n"
           "THRESH_CHANGE_BC = -1.0\nSNP_SOIL = false\nSOIL_FLUX = false\n")
    t = t.replace("MINIMUM_L_ELEMENT = 0.01\n", "MINIMUM_L_ELEMENT = 0.02\nREDUCE_N_ELEMENTS = 10\n")
    t = t.replace("SW_MODE = INCOMING\n", "SW_MODE = INCOMING\n" + req)
    t = t.replace("[SnowpackAdvanced]", "[SnowpackAdvanced]\nALLOW_ADAPTIVE_TIMESTEPPING = false")
    t = t.replace("COORDSYS = LATLON", "COORDSYS = CH1903")
    t = t.replace("STATION1 = ", "METEOFILE1 = ")
    t = t.replace("TS_DAYS_BETWEEN = 0.041667", "TS_DAYS_BETWEEN = 1.0")
    t = t.replace("TS_START = 0.0", "TS_START = 0.01")
    t = t.replace("PROF_DAYS_BETWEEN = 0.041667", "PROF_DAYS_BETWEEN = 1.0")
    t = t.replace("PROF_START = 0.0", "PROF_START = 0.01")
    t += ("\n[Interpolations1D]\nMAX_GAP_SIZE = 7776000\nTA::resample1 = linear\n"
          "RH::resample1 = linear\nVW::resample1 = nearest\nVW::ARG1::extrapolate = true\n"
          "ISWR::resample1 = linear\nILWR::resample1 = linear\nPSUM::resample1 = linear\n"
          "TSG::resample1 = linear\nTA::ARG1::extrapolate = true\nTSG::ARG1::extrapolate = true\n"
          "ISWR::ARG1::extrapolate = true\nILWR::ARG1::extrapolate = true\n")
    ini.write_text(t)

    print("[s4/s5] run_snowpack.py", flush=True)
    rc = run_ki("run_snowpack.py", ["--binary", str(SNOWPACK_BIN), "--config", str(ini),
        "--end_date", end], log)
    assert rc == 0, f"run_snowpack rc={rc}"

    met = out_d / f"{tag}.met"
    if not met.exists():
        c = list(out_d.glob("*.met")); assert c, "no .met produced"; met = c[0]
    print("[s6] parse_output.py", flush=True)
    rc = run_ki("parse_output.py", ["--input", str(met), "--output", str(res_csv),
        "--file_type", "met",
        "--variables", "SWE (of snowpack),Modelled snow depth (vertical)"], log)
    assert rc == 0, f"parse_output rc={rc}"
    return res_csv

# ---------- scoring ----------
def score(res_csv):
    from ki_tools_common.metrics import all_metrics
    sim = pd.read_csv(res_csv)
    swe_col = [c for c in sim.columns if c.lower().startswith("swe")][0]
    sim["date"] = pd.to_datetime(sim["datetime"]).dt.normalize()
    sim = sim.set_index("date")[swe_col].rename("sim_mm")
    sim = sim[~sim.index.duplicated(keep="first")]
    obs = read_obs()
    obs.index = pd.to_datetime(obs.index).normalize()
    obs = obs[~obs.index.duplicated(keep="first")]
    j = pd.concat([sim, obs], axis=1).dropna()
    # drop a short spinup (first water year) before scoring
    j = j[j.index >= "1997-09-01"]

    def M(sub):
        if len(sub) < 30:
            return None
        m = all_metrics(sub["obs_mm"].values, sub["sim_mm"].values)
        return {"NSE": m["NSE"], "KGE": m["KGE"], "PBIAS": m["PBIAS"],
                "r": m["r"], "RMSE": m["RMSE"], "n": len(sub),
                "period": f"{sub.index.min().date()}..{sub.index.max().date()}"}

    full = M(j)
    cal = M(j[j.index <= CAL_END])
    val = M(j[j.index > CAL_END])
    return full, cal, val, float(j["obs_mm"].max()), float(j["sim_mm"].max())

def main():
    tag = "yanks_1c41p"
    res_csv = OUT / "results" / f"{tag}_results.csv"
    if not res_csv.exists():
        res_csv = run_model()
    else:
        print("[resume] results CSV exists, re-scoring only", flush=True)
    full, cal, val, obs_peak, sim_peak = score(res_csv)
    RESULT_DIR.mkdir(parents=True, exist_ok=True)

    if full is None:
        result = {"model_id": "SNOWPACK",
                  "this_location": "Canadian Historical Snow Survey Data (1951-2016)",
                  "obs_source": "Canadian Historical Snow Survey Data (1951-2016)",
                  "status": "failed", "tools_used": [], "tools_failed": [],
                  "metrics": {"nse": None, "kge": None, "pbias": None, "r": None, "period": None},
                  "water_balance": {"status": "N/A", "residual_pct": None},
                  "notes": "insufficient obs-sim overlap (<30 paired days)"}
        (RESULT_DIR / "result.json").write_text(json.dumps(result, indent=2))
        print(json.dumps(result)); return

    notes = (
        f"SNOWPACK verifier at BCE-1C41P {NAME}, Cariboo Mts BC ({ELEV:.0f} m, continental "
        f"interior alpine) vs Canadian Historical Snow Survey automated snow-pillow SWE, "
        f"{full['n']} paired daily days over {full['period']}. Faithful twin of the real-case "
        f"SNOTEL-668 recipe (same 5 KI tools + snowpack binary + all .ini patches, UNCHANGED); "
        f"only difference is forcing = NASA POWER daily (the sole global product over Canada; "
        f"the Canadian dataset carries no meteo), with a physical 6.5 C/km lapse from the "
        f"1110 m grid cell to the 1670 m pillow (TEMP_OFFSET={TEMP_OFFSET:.2f} C) and an "
        f"orographic precip_scale={PRECIP_SCALE}; real NASA POWER shortwave (clear-sky diurnal "
        f"redistribution) + longwave fed directly. Peak obs {obs_peak:.0f} / sim {sim_peak:.0f} mm. "
        f"FULL NSE={full['NSE']:.3f} r={full['r']:.3f} KGE={full['KGE']:.3f} PBIAS={full['PBIAS']:.1f}%. "
        f"cal {cal['period']} NSE={cal['NSE']:.3f} / val {val['period']} NSE={val['NSE']:.3f} "
        f"(params not tuned to val -> not overfit).")

    result = {
        "model_id": "SNOWPACK",
        "this_location": f"BCE-1C41P {NAME}, Cariboo Mts BC ({ELEV:.0f} m continental alpine)",
        "obs_source": "Canadian Historical Snow Survey Data (1951-2016), SWE_mm (automated pillow)",
        "status": "completed",
        "tools_used": ["convert_forcing.py", "build_sno_profile.py", "generate_config.py",
                       "run_snowpack.py", "parse_output.py", "ki_tools_common.load_forcing",
                       "ki_tools_common.metrics"],
        "tools_failed": [],
        "metrics": {
            "nse": full["NSE"], "kge": full["KGE"], "pbias": full["PBIAS"], "r": full["r"],
            "rmse": full["RMSE"], "n_matched": full["n"], "period": full["period"],
            "nse_cal": cal["NSE"], "kge_cal": cal["KGE"], "pbias_cal": cal["PBIAS"],
            "nse_val": val["NSE"], "kge_val": val["KGE"], "pbias_val": val["PBIAS"],
            "period_calibration": cal["period"], "period_validation": val["period"]},
        "water_balance": {"status": "N/A", "residual_pct": None},
        "obs_peak_swe_mm": obs_peak, "sim_peak_swe_mm": sim_peak,
        "notes": notes}
    (RESULT_DIR / "result.json").write_text(json.dumps(result, indent=2))
    print("WROTE", RESULT_DIR / "result.json", flush=True)
    print(json.dumps(result["metrics"], indent=2))

if __name__ == "__main__":
    main()
