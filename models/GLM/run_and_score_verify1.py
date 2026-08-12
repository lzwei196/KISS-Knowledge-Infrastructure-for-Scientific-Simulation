#!/usr/bin/env python3
"""
GLM-AED2 verifier (verify_1): surface dissolved oxygen at a CHINESE deep
reservoir, matching the real-case variable (OXY_oxy) at a NEW location.

Location : Qiandao Lake / Xin'anjiang Reservoir (千岛湖), station 三潭岛
           (China National Surface-Water Quality Auto-Monitoring, guokongzhan)
           ~118.969E, 29.546N — deep, strongly stratified reservoir (ideal GLM).
Variable : OXY_oxy surface dissolved oxygen (mg/L), point_time_series (dag).
Forcing  : NASA POWER daily (SKILL-endorsed point forcing).
Period   : obs natural period intersected with forcing (2021-01-01..2024-12-31).

RESUMABLE: skips GLM run if output/output.nc already exists; caches obs parquet.
Scoring  : sim TOP active layer DO (surface point) vs daily-mean station DO,
           via ki_tools_common.metrics.all_metrics. Surface DO is the
           dag-compliant primary support (dt_035). Nutrient (NH3-N/TN/TP)
           magnitudes reported as secondary context only.
"""
import os, sys, json, glob, re, subprocess
import numpy as np, pandas as pd

KI   = "/mnt/disk1/Hydrocraft_server/models/GLM/knowledge_infrastructure"
TOOLS= os.path.join(KI, "tools")
GLM  = "/mnt/disk1/Hydrocraft_server/model/glm/bin/glm"
RUN  = "/mnt/disk1/Hydrocraft_server/outputs/glm_qiandao_do_china"
CHINA= "/mnt/disk1/Hydrocraft_server/data/china_data/2021-2025 国控站水质数据(excel)"
DEGRAY_AED = "/mnt/disk1/Hydrocraft_server/outputs/glm_degray_do_wqp/aed2.nml"
OUT_RESULT_DIR = "/mnt/disk1/Hydrocraft_server/models/GLM/detached/verify_1"

STATION = "三潭岛"
LAT, LON = 29.546429, 118.968529
LAKE = "QiandaoLake"
AREA_KM2, DMAX, DAVG, ELEV = 580.0, 100.0, 30.0, 108.0
START, STOP = "2021-01-01", "2024-12-31"
TIMEZONE = 8

sys.path.insert(0, "/mnt/disk1/Hydrocraft_server/models/ki_tools_common")
from ki_tools_common.metrics import all_metrics


def sh(cmd):
    print("[cmd]", " ".join(cmd), flush=True)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    print(r.stdout[-800:]);
    if r.returncode != 0:
        print("STDERR:", r.stderr[-1500:])
        raise RuntimeError("command failed: " + " ".join(cmd))
    return r


# ---------------------------------------------------------------- obs
def load_obs():
    cache = os.path.join(RUN, "obs_station.parquet")
    if os.path.exists(cache):
        return pd.read_parquet(cache)
    rows = []
    files = sorted(glob.glob(os.path.join(CHINA, "20*", "*.csv")))
    print(f"[obs] scanning {len(files)} csv files for station {STATION}", flush=True)
    for f in files:
        try:
            df = pd.read_csv(f, encoding="gb18030")
        except Exception:
            continue
        if "断面名称" not in df.columns:
            continue
        sub = df[df["断面名称"] == STATION]
        if len(sub) == 0:
            continue
        yr = re.match(r"(\d{4})", os.path.basename(f)).group(1)
        for _, r in sub.iterrows():
            rows.append({
                "yr": yr, "time": str(r["监测时间"]),
                "DO": r.get("溶解氧(mg/L)"), "wt": r.get("水温(℃)"),
                "NH3": r.get("氨氮(mg/L)"), "TP": r.get("总磷(mg/L)"),
                "TN": r.get("总氮(mg/L)"),
            })
    d = pd.DataFrame(rows)
    if len(d) == 0:
        raise RuntimeError(f"no obs found for station {STATION}")
    # parse "MM-DD HH:MM" with year from filename
    dt = pd.to_datetime(d["yr"] + "-" + d["time"].str.strip(),
                        format="%Y-%m-%d %H:%M", errors="coerce")
    d["datetime"] = dt
    d = d.dropna(subset=["datetime"])
    for c in ["DO", "wt", "NH3", "TP", "TN"]:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d["date"] = d["datetime"].dt.normalize()
    os.makedirs(RUN, exist_ok=True)
    d.to_parquet(cache)
    return d


def obs_daily(d):
    g = d.dropna(subset=["DO"]).groupby("date")["DO"]
    obs = pd.DataFrame({"obs_DO": g.mean(), "obs_n": g.size()})
    obs = obs.loc[(obs.index >= START) & (obs.index <= STOP)]
    return obs


# ---------------------------------------------------------------- setup
def build_inputs():
    os.makedirs(os.path.join(RUN, "bcs"), exist_ok=True)
    morph = os.path.join(RUN, "morphometry.json")
    if not os.path.exists(morph):
        sh([sys.executable, os.path.join(TOOLS, "s1_lake_identification/build_morphometry.py"),
            "--area_km2", str(AREA_KM2), "--depth_max", str(DMAX), "--depth_avg", str(DAVG),
            "--elevation", str(ELEV), "--lat", str(LAT), "--lon", str(LON),
            "--name", LAKE, "--output", morph])
    met = os.path.join(RUN, "bcs/met_daily.csv")
    if not os.path.exists(met):
        sh([sys.executable, os.path.join(TOOLS, "s2_met_forcing/convert_met_to_glm.py"),
            "--forcing_source", "nasa_power", "--lat", str(LAT), "--lon", str(LON),
            "--start_date", START, "--end_date", STOP, "--output", met])
    init = os.path.join(RUN, "init_profiles.json")
    if not os.path.exists(init):
        sh([sys.executable, os.path.join(TOOLS, "s5_init_profiles/build_init_profiles.py"),
            "--strategy", "uniform", "--temp", "10", "--depth", str(DMAX), "--output", init])
    aed = os.path.join(RUN, "aed2.nml")
    if not os.path.exists(aed):
        # core-nutrient AED2 set (per dt_032 phyto/silica disabled). Reuse the
        # validated DeGray aed2.nml (Fsed_oxy=-12, Ksed_oxy=50 SOD lever).
        with open(DEGRAY_AED) as fa:
            txt = fa.read()
        with open(aed, "w") as fo:
            fo.write(txt)


def write_nml():
    """Assemble glm3.nml from validated DeGray template (generate_glm_nml.py does
    NOT wire AED2 per dt_033) with Qiandao-specific morphometry/dates/limnology."""
    morph = json.load(open(os.path.join(RUN, "morphometry.json")))
    H = morph["H"]; A = morph["A"]
    Hs = ", ".join(f"{h:.3f}" for h in H)
    As = ", ".join(f"{a:.1f}" for a in A)
    nlev = len(H)
    crest = H[-1]
    nml = f"""
&glm_setup
   sim_name = '{LAKE}'
   max_layers = 500
   min_layer_vol = 0.5
   min_layer_thick = 0.15
   max_layer_thick = 0.5
   density_model = 1
   non_avg = .true.
/

&wq_setup
   wq_lib = 'aed2'
   wq_nml_file = 'aed2.nml'
   ode_method = 1
   split_factor = 1
   bioshade_feedback = .true.
   repair_state = .true.
/

&mixing
   surface_mixing = 1
   coef_mix_conv = 0.2
   coef_wind_stir = 0.402
   coef_mix_shear = 0.2
   coef_mix_turb = 0.51
   coef_mix_KH = 0.3
   deep_mixing = 2
   coef_mix_hyp = 0.5
   diff = 0.0
/

&morphometry
   lake_name = '{LAKE}'
   latitude = {LAT}
   longitude = {LON}
   bsn_len = 24000.0
   bsn_wid = 24000.0
   crest_elev = {crest:.2f}
   bsn_vals = {nlev}
   H = {Hs}
   A = {As}
/

&time
   timefmt = 2
   start = '{START} 00:00:00'
   stop = '{STOP} 23:00:00'
   dt = 3600
   timezone = {TIMEZONE}
/

&output
   out_dir = 'output'
   out_fn = 'output'
   nsave = 24
   csv_lake_fname = 'lake'
   csv_point_nlevs = 4
   csv_point_frombot = .false.
   csv_point_fname = 'WQ'
   csv_point_at = 0.5, 10.0, 30.0, 60.0
   csv_point_nvars = 3
   csv_point_vars = 'temp','salt','OXY_oxy'
   csv_outlet_allinone = .false.
   csv_outlet_fname = 'outlet_'
   csv_outlet_nvars = 3
   csv_outlet_vars = 'flow','temp','salt'
   csv_ovrflw_fname = 'overflow'
/

&init_profiles
   lake_depth = {DMAX}
   num_depths = 3
   the_depths = 0.0, {DMAX/2:.1f}, {DMAX:.1f}
   the_temps = 10.0, 9.0, 8.0
   the_sals = 0.0, 0.0, 0.0
   num_wq_vars = 10
   wq_names = 'OXY_oxy','NIT_amm','NIT_nit','PHS_frp','OGM_doc','OGM_poc','OGM_don','OGM_pon','OGM_dop','OGM_pop'
   wq_init_vals = 320.0, 320.0, 320.0,
                  2.0, 2.0, 2.0,
                  5.0, 5.0, 5.0,
                  0.1, 0.1, 0.1,
                  50.0, 50.0, 50.0,
                  10.0, 10.0, 10.0,
                  4.0, 4.0, 4.0,
                  1.0, 1.0, 1.0,
                  0.1, 0.1, 0.1,
                  0.05, 0.05, 0.05
/

&meteorology
   met_sw = .true.
   lw_type = 'LW_IN'
   rain_sw = .false.
   atm_stab = 0
   catchrain = .false.
   rad_mode = 1
   albedo_mode = 1
   cloud_mode = 4
   fetch_mode = 0
   subdaily = .false.
   meteo_fl = 'bcs/met_daily.csv'
   wind_factor = 1.0
   sw_factor = 1.0
   lw_factor = 1.0
   at_factor = 1.0
   rh_factor = 1.0
   rain_factor = 1.0
   ce = 0.0013
   ch = 0.0014
   cd = 0.0013
   rain_threshold = 0.01
   runoff_coef = 0.3
/

&bird_model
   AP = 973
   Oz = 0.279
   WatVap = 1.1
   AOD500 = 0.033
   AOD380 = 0.038
   Albedo = 0.2
/

&light
   light_mode = 0
   n_bands = 4
   light_extc = 1.0, 0.5, 2.0, 4.0
   energy_frac = 0.51, 0.45, 0.035, 0.005
   Benthic_Imin = 10
   Kw = 0.4
/

&inflow
   num_inflows = 0
/

&outflow
   num_outlet = 0
   flt_off_sw = .false.
   outl_elvs = {crest-5:.1f}
   bsn_len_outl = 100
   bsn_wid_outl = 50
   outflow_fl = ''
   outflow_factor = 1.0
   crest_width = 100.0
   crest_factor = 0.61
/

&sediment
   sed_heat_Ksoil = 2.0
   sed_temp_depth = 0.2
   sed_temp_mean = 17.0
   sed_temp_amplitude = 8.0
   sed_temp_peak_doy = 242
   benthic_mode = 2
   n_zones = 1
   zone_heights = {crest-2:.1f}
   sed_reflectivity = 0.1
   sed_roughness = 0.01
/

&snowice
   snow_albedo_factor = 1.0
   snow_rho_max = 500
   snow_rho_min = 100
   dt_iceon_avg = 0.02
   min_ice_thickness = 0.001
/
"""
    with open(os.path.join(RUN, "glm3.nml"), "w") as f:
        f.write(nml)


def ensure_run():
    nc = os.path.join(RUN, "output", "output.nc")
    if os.path.exists(nc) and os.path.getsize(nc) > 1_000_000:
        print("[resume] output.nc exists -> skip GLM run", flush=True)
        return
    r = subprocess.run([sys.executable,
                        os.path.join(TOOLS, "s8_execution/run_glm.py"), "--run_dir", RUN],
                       capture_output=True, text=True, timeout=7200)
    print(r.stdout[-1500:])
    if r.returncode != 0:
        print("STDERR", r.stderr[-2000:])
    if not os.path.exists(nc):
        raise RuntimeError("GLM did not produce output.nc")


# ---------------------------------------------------------------- sim
def sim_surface_do(need_dates):
    """Per-day surface (top active layer) DO in mg/L. Reads output.nc ONE
    timestep at a time (bulk [:] read of padded z=500 var segfaults libnetcdf)."""
    import netCDF4 as ncmod
    ds = ncmod.Dataset(os.path.join(RUN, "output", "output.nc"))
    t = ds.variables["time"]
    times = pd.to_datetime(ncmod.num2date(np.asarray(t[:]), t.units,
                           only_use_cftime_datetimes=False)).normalize()
    date_to_idx = {}
    for i, dd in enumerate(times):
        date_to_idx.setdefault(pd.Timestamp(dd), i)
    oxyv = ds.variables["OXY_oxy"]; NSv = ds.variables["NS"]
    rows = []
    for d in need_dates:
        d = pd.Timestamp(d)
        if d not in date_to_idx:
            continue
        i = date_to_idx[d]
        n = int(np.asarray(NSv[i]))
        if n < 1:
            continue
        o = np.squeeze(np.asarray(oxyv[i]))[:n] * 32.0 / 1000.0
        o = np.where(np.abs(o) < 1e8, o, np.nan)
        if not np.isfinite(o[n-1]):
            continue
        rows.append({"date": d, "sim_surf": float(o[n-1])})
    ds.close()
    return pd.DataFrame(rows).set_index("date")


def main():
    os.makedirs(RUN, exist_ok=True)
    raw = load_obs()
    build_inputs()
    write_nml()
    ensure_run()

    obs = obs_daily(raw)
    print(f"[obs] {len(obs)} daily-mean DO dates in {START}..{STOP}", flush=True)
    sim = sim_surface_do(list(obs.index))
    print(f"[sim] {len(sim)} matching sim dates", flush=True)
    m = obs.join(sim, how="inner").dropna(subset=["obs_DO", "sim_surf"])
    m = m.loc[(m.index >= START) & (m.index <= STOP)]

    primary = all_metrics(m["obs_DO"].values, m["sim_surf"].values)

    # monthly aggregate (secondary, smooths diel/synoptic noise)
    mm = m.copy(); mm["ym"] = mm.index.to_period("M")
    mon = mm.groupby("ym").agg(obs=("obs_DO", "mean"), sim=("sim_surf", "mean"))
    monthly = all_metrics(mon["obs"].values, mon["sim"].values) if len(mon) >= 3 else {}

    # nutrient magnitude context (NOT primary; GLM nutrients are uncalibrated)
    nut = {}
    for col, label in [("NH3", "NH3_N"), ("TN", "total_nitrogen"), ("TP", "total_phosphorus")]:
        v = pd.to_numeric(raw[col], errors="coerce").dropna()
        if len(v):
            nut[label + "_obs_mean_mgL"] = round(float(v.mean()), 4)

    res = {
        "model_id": "GLM",
        "this_location": "Qiandao Lake / Xin'anjiang Reservoir (千岛湖), station 三潭岛 — China guokongzhan",
        "obs_source": "China National Surface-Water Quality Auto-Monitoring 2021-2025 (guokongzhan)",
        "status": "completed",
        "variable": "OXY_oxy (surface dissolved oxygen, mg/L)",
        "obs_shape": "point_time_series",
        "tools_used": [
            "s1_lake_identification/build_morphometry.py",
            "s2_met_forcing/convert_met_to_glm.py (nasa_power)",
            "s5_init_profiles/build_init_profiles.py",
            "s7_aed_config core-nutrient aed2.nml",
            "s8_execution/run_glm.py",
            "ki_tools_common.metrics.all_metrics",
        ],
        "tools_failed": [],
        "n_paired_dates": int(len(m)),
        "metrics": {
            "nse": round(primary["NSE"], 4), "kge": round(primary["KGE"], 4),
            "pbias": round(primary["PBIAS"], 4), "r": round(primary["r"], 4),
            "rmse": round(primary["RMSE"], 4),
            "period": f"{START} to {STOP} (surface DO, uncalibrated)",
        },
        "secondary_metrics": {
            "monthly_surface_DO": {k: round(v, 4) for k, v in monthly.items()},
        },
        "obs_DO_mean_mgL": round(float(m["obs_DO"].mean()), 3),
        "sim_DO_mean_mgL": round(float(m["sim_surf"].mean()), 3),
        "nutrient_context": nut,
        "water_balance": {"status": "N/A", "residual_pct": None},
        "notes": (
            "GLM-AED2 surface DO at Qiandao Lake (千岛湖), the dag-compliant "
            "OXY_oxy point_time_series, matching the DeGray real-case variable. "
            "NASA POWER forcing, uncalibrated (Miyun/DeGray defaults). Nutrients "
            "(NH3-N/TN/TP) available at this station but GLM nutrient loading is "
            "uncalibrated (no catchment inflow WQ) and structurally weak per "
            "dt_032/Qionghai/Erhai — reported as magnitude context only."
        ),
    }
    os.makedirs(OUT_RESULT_DIR, exist_ok=True)
    with open(os.path.join(OUT_RESULT_DIR, "result.json"), "w") as f:
        json.dump(res, f, indent=2, ensure_ascii=False)
    print(json.dumps(res, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
