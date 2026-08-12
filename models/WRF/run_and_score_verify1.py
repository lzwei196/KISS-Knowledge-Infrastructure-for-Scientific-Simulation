#!/usr/bin/env python3
"""
WRF VERIFIER (verify_1) runner + scorer (detached, resumable).

Same proven WPS->WRF chain (geogrid -> ungrib -> metgrid -> real -> wrf) and same
KI tools as the Real-case, but at a DIFFERENT location: a Yangtze-delta gridded
domain (ref 31.0N, 119.0E) instead of the North China Plain (37.0N, 115.0E).
Driven by the SAME cached GFS 0.25deg forcing (2026-03-25..27, box 28-40N/110-125E,
which fully contains the new domain), then scores the domain-mean 2-m air
temperature (T2) spatial field against ERA5-Land monthly March climatology
(2015-2022) over the new domain's bbox -> spatial_field_comparison (metric CSI +
NSE/KGE/PBIAS/r).

Resumable: every stage skips if its output already exists.
Writes the verifier result object to detached/verify_1/result.json.
"""
import os, sys, json, glob, subprocess
from pathlib import Path
from datetime import datetime, timedelta
import numpy as np

# ---------------------------------------------------------------- paths
WORK      = "/home/server/knowledge-dissection-toolkit/auto_dissect/_work/WRF"
KI        = "/mnt/disk1/Hydrocraft_server/models/WRF/knowledge_infrastructure"
TOOLS     = os.path.join(KI, "tools")
DETACHED  = "/mnt/disk1/Hydrocraft_server/models/WRF/detached/verify_1"
RUN       = os.path.join(DETACHED, "run")
TEMPLATE  = os.path.join(WORK, "run_chaohe")           # proven link-farm to clone
GFS_DIR   = os.path.join(WORK, "gfs_data")
GEOG_REAL = os.path.join(WORK, "WPS_GEOG_LOW_RES")
GEOG      = "/tmp/GEOG"                                 # short symlink (WPS 128-char buffer)
ERA5_ZIP  = "/mnt/disk1/Hydrocraft_server/data/obs/era5_land/era5land_monthly_china_2015_2022.nc"
ERA5_NC   = "/tmp/era5land/data_stream-moda.nc"
RESULT    = os.path.join(DETACHED, "result.json")

sys.path.insert(0, "/mnt/disk1/Hydrocraft_server/models/ki_tools_common")
sys.path.insert(0, "/mnt/disk1/Hydrocraft_server/python_env/lib/python3.12/site-packages")

# ---------------------------------------------------------------- domain / time (NEW location)
REF_LAT, REF_LON = 31.0, 119.0            # Yangtze delta (distinct from 37.0N/115.0E NCP)
E_WE, E_SN, DX   = 37, 37, 12000          # 37x37 @12km ~ 4deg span, fits inside GFS box
TRUELAT1, TRUELAT2, STAND_LON = 30.0, 60.0, 119.0
START = datetime(2026, 3, 25, 0)
END   = datetime(2026, 3, 27, 0)          # 48 h; same cached GFS window
INTERVAL = 21600                          # 6-hourly GFS
CLIM_MONTH = 3                            # March climatology
LOCATION = "yangtze_delta_gridded_domain(31.0N,119.0E)"
OBS_SOURCE = "ERA5-Land Monthly Means (China: SWE/ET/soil moisture/temp/runoff, 2015-2022)"

def log(m): print(f"[verify1] {m}", flush=True)

# ---------------------------------------------------------------- stage 0: link farm
def setup_run_dir():
    os.makedirs(RUN, exist_ok=True)
    if not (os.path.islink(GEOG) or os.path.exists(GEOG)):
        os.symlink(GEOG_REAL, GEOG)
    marker = os.path.join(RUN, ".linkfarm_done")
    if os.path.exists(marker):
        return
    log("Cloning proven link farm from run_chaohe (preserving symlinks)")
    for name in os.listdir(TEMPLATE):
        src = os.path.join(TEMPLATE, name)
        dst = os.path.join(RUN, name)
        if name.startswith(("geo_em", "met_em.", "FILE:", "GRIBFILE.",
                            "wrfout", "wrfinput", "wrfbdy", "namelist",
                            "rsl.", "wrf_full.log", "geogrid.log",
                            "ungrib.log", "metgrid.log")):
            continue
        if os.path.islink(src):
            tgt = os.readlink(src)
            if os.path.lexists(dst):
                continue
            os.symlink(tgt, dst)
    Path(marker).touch()

# ---------------------------------------------------------------- stage 1: geogrid
def write_namelist_wps():
    txt = f"""&share
 wrf_core = 'ARW',
 max_dom = 1,
 start_date = '{START:%Y-%m-%d_%H:%M:%S}',
 end_date   = '{END:%Y-%m-%d_%H:%M:%S}',
 interval_seconds = {INTERVAL},
/

&geogrid
 parent_id         =   1,
 parent_grid_ratio =   1,
 i_parent_start    =   1,
 j_parent_start    =   1,
 e_we              =  {E_WE},
 e_sn              =  {E_SN},
 geog_data_res     = 'lowres+default',
 dx = {DX},
 dy = {DX},
 map_proj = 'lambert',
 ref_lat   =  {REF_LAT},
 ref_lon   = {REF_LON},
 truelat1  =  {TRUELAT1},
 truelat2  =  {TRUELAT2},
 stand_lon = {STAND_LON},
 geog_data_path = '{GEOG}',
/

&ungrib
 out_format = 'WPS',
 prefix = 'FILE',
/

&metgrid
 fg_name = 'FILE',
 io_form_metgrid = 2,
/
"""
    with open(os.path.join(RUN, "namelist.wps"), "w") as f:
        f.write(txt)

def run_exe(exe, logf, timeout):
    log(f"running {exe}")
    with open(os.path.join(RUN, logf), "w") as lf:
        p = subprocess.run([os.path.join(RUN, exe)], cwd=RUN,
                           stdout=lf, stderr=subprocess.STDOUT, timeout=timeout)
    return p.returncode

def stage_geogrid():
    if glob.glob(os.path.join(RUN, "geo_em.d01.nc")):
        log("geo_em exists -> skip geogrid"); return
    write_namelist_wps()
    run_exe("geogrid.exe", "geogrid.log", 1800)
    tail = open(os.path.join(RUN, "geogrid.log")).read()[-400:]
    if not glob.glob(os.path.join(RUN, "geo_em.d01.nc")):
        raise RuntimeError("geogrid produced no geo_em. tail:\n" + tail)
    log("geogrid OK")

# ---------------------------------------------------------------- stage 2: ungrib
def stage_ungrib():
    if glob.glob(os.path.join(RUN, "FILE:*")):
        log("FILE:* exist -> skip ungrib"); return
    gribs = []
    t = START
    while t <= END:
        f = os.path.join(GFS_DIR, f"gfs_{t:%Y%m%d_%H}.grb2")
        if os.path.exists(f): gribs.append(f)
        t += timedelta(seconds=INTERVAL)
    if not gribs:
        raise RuntimeError("no GFS grib files for run window")
    def suffix(i):
        a = i // (26*26); b = (i // 26) % 26; c = i % 26
        return chr(65+a)+chr(65+b)+chr(65+c)
    for i, g in enumerate(gribs):
        link = os.path.join(RUN, f"GRIBFILE.{suffix(i)}")
        if os.path.lexists(link): os.remove(link)
        os.symlink(g, link)
    log(f"linked {len(gribs)} GRIBFILE.* ; running ungrib")
    run_exe("ungrib.exe", "ungrib.log", 1200)
    if not glob.glob(os.path.join(RUN, "FILE:*")):
        raise RuntimeError("ungrib produced no FILE:*. tail:\n" +
                           open(os.path.join(RUN, "ungrib.log")).read()[-600:])
    log("ungrib OK")

# ---------------------------------------------------------------- stage 3: metgrid
def stage_metgrid():
    if glob.glob(os.path.join(RUN, "met_em.d01.*")):
        log("met_em exist -> skip metgrid"); return
    run_exe("metgrid.exe", "metgrid.log", 1800)
    mets = glob.glob(os.path.join(RUN, "met_em.d01.*"))
    if not mets:
        raise RuntimeError("metgrid produced no met_em. tail:\n" +
                           open(os.path.join(RUN, "metgrid.log")).read()[-600:])
    log(f"metgrid OK ({len(mets)} files)")

# ---------------------------------------------------------------- stage 4-5: namelist.input
def write_namelist_input():
    rd = (END - START).days
    rh = int(((END - START).seconds) // 3600)
    txt = f""" &time_control
 run_days                            = {rd},
 run_hours                           = {rh},
 run_minutes                         = 0,
 run_seconds                         = 0,
 start_year                          = {START.year},
 start_month                         = {START.month:02d},
 start_day                           = {START.day:02d},
 start_hour                          = {START.hour:02d},
 end_year                            = {END.year},
 end_month                           = {END.month:02d},
 end_day                             = {END.day:02d},
 end_hour                            = {END.hour:02d},
 interval_seconds                    = {INTERVAL},
 input_from_file                     = .true.,
 history_interval                    = 180,
 frames_per_outfile                  = 1000,
 restart                             = .false.,
 restart_interval                    = 5000,
 io_form_history                     = 2,
 io_form_restart                     = 2,
 io_form_input                       = 2,
 io_form_boundary                    = 2,
 /

 &domains
 time_step                           = 60,
 time_step_fract_num                 = 0,
 time_step_fract_den                 = 1,
 max_dom                             = 1,
 e_we                                = {E_WE},
 e_sn                                = {E_SN},
 e_vert                              = 45,
 dzstretch_s                         = 1.1,
 p_top_requested                     = 5000,
 num_metgrid_levels                  = 24,
 num_metgrid_soil_levels             = 4,
 dx                                  = {DX},
 dy                                  = {DX},
 grid_id                             = 1,
 parent_id                           = 0,
 i_parent_start                      = 1,
 j_parent_start                      = 1,
 parent_grid_ratio                   = 1,
 parent_time_step_ratio              = 1,
 feedback                            = 1,
 smooth_option                       = 0,
 /

 &physics
 mp_physics                          = 6,
 ra_lw_physics                       = 1,
 ra_sw_physics                       = 1,
 radt                                = 12,
 sf_sfclay_physics                   = 1,
 sf_surface_physics                  = 2,
 bl_pbl_physics                      = 1,
 bldt                                = 0,
 cu_physics                          = 1,
 cudt                                = 5,
 surface_input_source                = 3,
 num_soil_layers                     = 4,
 num_land_cat                        = 21,
 sf_urban_physics                    = 0,
 /

 &fdda
 /

 &dynamics
 hybrid_opt                          = 2,
 w_damping                           = 1,
 diff_opt                            = 2,
 km_opt                              = 4,
 diff_6th_opt                        = 0,
 diff_6th_factor                     = 0.12,
 base_temp                           = 290.,
 damp_opt                            = 3,
 zdamp                               = 5000.,
 dampcoef                            = 0.2,
 khdif                               = 0,
 kvdif                               = 0,
 non_hydrostatic                     = .true.,
 moist_adv_opt                       = 1,
 scalar_adv_opt                      = 1,
 gwd_opt                             = 0,
 /

 &bdy_control
 spec_bdy_width                      = 5,
 specified                           = .true.,
 /

 &grib2
 /

 &namelist_quilt
 nio_tasks_per_group                 = 0,
 nio_groups                          = 1,
 /
"""
    with open(os.path.join(RUN, "namelist.input"), "w") as f:
        f.write(txt)

# ---------------------------------------------------------------- stage 6: real + wrf (KI tool)
def stage_run_wrf():
    outs = glob.glob(os.path.join(RUN, "wrfout_d01_*"))
    if outs:
        log(f"wrfout exists ({outs[0]}) -> skip real/wrf"); return
    write_namelist_input()
    cmd = [sys.executable, os.path.join(TOOLS, "run_wrf.py"),
           "--wrf-dir", RUN, "--np", "1", "--timeout", "5400"]
    log("stage6: " + " ".join(cmd))
    p = subprocess.run(cmd)
    outs = glob.glob(os.path.join(RUN, "wrfout_d01_*"))
    if not outs:
        raise RuntimeError("run_wrf.py produced no wrfout (rc=%s)" % p.returncode)
    log(f"wrf OK -> {outs[0]}")

# ---------------------------------------------------------------- scoring
def load_wrf_t2():
    import netCDF4 as nc
    f = sorted(glob.glob(os.path.join(RUN, "wrfout_d01_*")))[0]
    d = nc.Dataset(f)
    t2 = np.asarray(d.variables["T2"][:])          # (t, sn, we) K
    lat = np.asarray(d.variables["XLAT"][0])
    lon = np.asarray(d.variables["XLONG"][0])
    d.close()
    return t2.mean(axis=0), lat, lon, f, t2.shape[0]

def load_era5_march_clim(bbox):
    import netCDF4 as nc
    if not os.path.exists(ERA5_NC):
        os.makedirs(os.path.dirname(ERA5_NC), exist_ok=True)
        subprocess.run(["unzip", "-o", ERA5_ZIP, "-d", os.path.dirname(ERA5_NC)],
                       check=True, stdout=subprocess.DEVNULL)
    d = nc.Dataset(ERA5_NC)
    lat = np.asarray(d.variables["latitude"][:])
    lon = np.asarray(d.variables["longitude"][:])
    vt  = np.asarray(d.variables["valid_time"][:])
    months = np.array([datetime.utcfromtimestamp(int(s)).month for s in vt])
    sel = np.where(months == CLIM_MONTH)[0]
    t2m = d.variables["t2m"]
    stack = np.ma.stack([np.ma.masked_invalid(t2m[i]) for i in sel])
    clim = stack.mean(axis=0)
    d.close()
    la0, la1, lo0, lo1 = bbox
    li = np.where((lat >= la0) & (lat <= la1))[0]
    lj = np.where((lon >= lo0) & (lon <= lo1))[0]
    sub = clim[np.ix_(li, lj)]
    return lat[li], lon[lj], sub

def csi(obs, sim, thr):
    eo = obs > thr; es = sim > thr
    tp = int(np.sum(eo & es)); fp = int(np.sum(es & ~eo)); fn = int(np.sum(~es & eo))
    return (tp / (tp + fp + fn)) if (tp + fp + fn) > 0 else float("nan"), tp, fp, fn

def score():
    from scipy.interpolate import griddata
    from ki_tools_common.metrics import all_metrics

    t2mean, wlat, wlon, wfile, ntimes = load_wrf_t2()
    bbox = (float(wlat.min()), float(wlat.max()), float(wlon.min()), float(wlon.max()))
    log(f"WRF domain bbox {bbox}, ntimes={ntimes}, T2mean {t2mean.min():.1f}-{t2mean.max():.1f}K")

    elat, elon, eclim = load_era5_march_clim(bbox)
    LON, LAT = np.meshgrid(elon, elat)

    pts = np.column_stack([wlon.ravel(), wlat.ravel()])
    sim = griddata(pts, t2mean.ravel(), (LON, LAT), method="linear")

    obs = np.ma.filled(eclim.astype(float), np.nan)
    mask = np.isfinite(obs) & np.isfinite(sim)
    o = obs[mask]; s = sim[mask]
    log(f"paired spatial cells: {o.size} (ERA5-Land 0.1deg, ocean/NaN dropped)")

    m = all_metrics(o.tolist(), s.tolist())
    nse = float(m["NSE"]); kge = float(m["KGE"]); pbias = float(m["PBIAS"])
    r = float(m["r"]); rmse = float(m["RMSE"])
    thr = float(np.median(o))
    csi_val, tp, fp, fn = csi(o, s, thr)
    bias = float(np.mean(s - o))
    log(f"CSI(thr={thr:.2f}K)={csi_val:.3f} tp={tp} fp={fp} fn={fn}")
    log(f"spatial r={r:.3f} RMSE={rmse:.2f}K bias={bias:+.2f}K NSE={nse:.2f} KGE={kge:.2f} PBIAS={pbias:+.1f}%")

    period = f"March climatology 2015-2022 (spatial field, {o.size} land cells)"
    result = {
        "model_id": "WRF",
        "this_location": LOCATION,
        "obs_source": OBS_SOURCE,
        "status": "completed",
        "tools_used": ["run_wrf.py", "geogrid.exe", "ungrib.exe", "metgrid.exe",
                       "ki_tools_common.metrics.all_metrics"],
        "tools_failed": [],
        "variable": "T2",
        "obs_shape": "spatial_time_series",
        "comparison_mode": "spatial_field_comparison",
        "determining_metric": "csi",
        "csi": round(csi_val, 4),
        "csi_threshold_K": round(thr, 3),
        "spatial_r": round(r, 4),
        "rmse_K": round(rmse, 3),
        "bias_K": round(bias, 3),
        "metrics": {
            "nse": round(nse, 4), "kge": round(kge, 4), "pbias": round(pbias, 4),
            "r": round(r, 4), "rmse": round(rmse, 4), "csi": round(csi_val, 4),
            "spatial_r": round(r, 4),
            "period": period,
        },
        "water_balance": {"status": "N/A", "residual_pct": None},
        "notes": (
            f"VERIFIER: same WPS->WRF chain + same KI tools as Real-case, run at a DIFFERENT "
            f"location -- Yangtze-delta domain ref 31.0N/119.0E ({E_WE}x{E_SN}@{DX//1000}km, 45 eta "
            f"levels) vs Real-case North China Plain 37.0N/115.0E. Same cached GFS 0.25deg forcing "
            f"({START:%Y-%m-%d}..{END:%m-%d}, 48h, {ntimes} frames; GFS box 28-40N/110-125E contains "
            f"both domains). Domain-mean T2 interpolated to ERA5-Land 0.1deg; spatial_field_comparison "
            f"vs ERA5-Land March climatology (2015-2022), {o.size} land cells. CSI={csi_val:.3f} "
            f"(median thr), spatial r={r:.3f}, RMSE={rmse:.2f}K, bias={bias:+.2f}K, NSE={nse:.2f}, "
            f"KGE={kge:.2f}, PBIAS={pbias:+.1f}%. Year mismatch (WRF Mar-2026 vs Mar climatology) is "
            f"inherent to spatial climatology comparison of a limited-area model; T2 pattern is "
            f"elevation/latitude-dominated so CSI/spatial-r robust."
        ),
    }
    return result

# ---------------------------------------------------------------- main
def main():
    os.makedirs(DETACHED, exist_ok=True)
    try:
        setup_run_dir()
        stage_geogrid()
        stage_ungrib()
        stage_metgrid()
        stage_run_wrf()
        result = score()
    except Exception as e:
        import traceback
        result = {
            "model_id": "WRF", "this_location": LOCATION, "obs_source": OBS_SOURCE,
            "status": "failed", "tools_used": [], "tools_failed": [],
            "metrics": {"nse": None, "kge": None, "pbias": None, "r": None, "period": None},
            "water_balance": {"status": "N/A", "residual_pct": None},
            "error": f"{type(e).__name__}: {e}",
            "traceback": traceback.format_exc()[-2000:],
            "notes": "verify_1 run_and_score failed; see traceback.",
        }
    with open(RESULT, "w") as f:
        json.dump(result, f, indent=2)
    log(f"wrote {RESULT} (status={result.get('status')})")

if __name__ == "__main__":
    main()
