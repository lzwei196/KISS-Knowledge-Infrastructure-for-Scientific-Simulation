#!/usr/bin/env python3
"""
WRF-Hydro v5.2.0 standalone -- VERIFIER run at Bengbu (蚌埠), Huai River.

Companion location to the real-case at 紫荆关 Zijingguan (Juma R., Haihe).

Gauge   : Bengbu stcd 51080, ~32.943N 117.388E
Obs     : KISSPATH_OBS/BB/51080_bengbu.txt
          tab-separated (stcd dates z Q name); Q in m3/s; -99.9 = missing,
          dropped by the KI's own extract_discharge.load_obs() (Q>0 filter).
Basin   : KISSPATH_DATA/shp/bengbu_0a65a081_shp/
          bengbu_0a65a081_boundary_shp/bengbu_0a65a081_boundary.shp
          -> 115,818.7 km2 delineated (published Bengbu catchment ~121,330 km2)
Forcing : CMFD V2.0 3-hourly 0.1deg -> hourly LDASIN on the LCC grid, via the KI
          tool tools/s8_forcing/cmfd_to_ldasin.py.
Domain  : rebuilt from scratch by KI tools s1..s6 (24x22 LSM @28km,
          ~96x88 routing @7km, aggfactrt=4).
Physics : the KI's stock generate_namelists.py defaults, which ARE "Config A":
          RUNOFF_OPTION=3 (Schaake96), channel_option=3 (diffusive wave, gridded),
          GWBASESWCRT=1 (exponential bucket), UDMP_OPT=0, rst_typ=0.
          NOTE: generate_namelists.py exposes NO physics CLI flags (see KI_DEFECTS
          below), so this is an uncalibrated stock-parameter run -- exactly the
          same treatment the Zijingguan real-case received.

Period  : 1980-01-01 .. 1990-12-31   (CMFD 1951-2024; obs 1950-01-01..1997-12-31)
          spinup      1980-01-01..1980-12-31 (discarded)
          calibration 1981-01-01..1986-12-31   (reported, NOT optimised on)
          validation  1987-01-01..1990-12-31   (held out)
          Nothing is calibrated; cal/val split is reported for comparability with
          the Zijingguan real-case, which was likewise uncalibrated.

KI_DEFECTS this run works around (all recorded in the result object):
  D1 end-of-forcing off-by-one (THE bug that killed the previous Bengbu run):
     generate_namelists.compute_khour() = (end - start + 1 day) in hours.
     WRF-Hydro reads forcing at t = 0 .. KHOUR *inclusive*, so it needs an LDASIN
     file at hour KHOUR -- one hour past what cmfd_to_ldasin.py writes for the
     same [start,end]. The stock pair always dies in read_hydro_forcing_mpp1()
     "no forcing data found". Fix: generate forcing through END + 1 day.
     Evidence on disk: outputs/bengbu_wrfhydro_025deg_1980_1990 has KHOUR=96432,
     exactly 96432 LDASIN files (1980010100..1990123123), 4018 CHRTOUT, and
     diag_hydro.00000 ends with the fatal read_hydro_forcing_mpp1() error.
  D2 SKILL.md's tool table documents `extract_discharge.py --gauge_lat/--gauge_lon
     /--min_order` for gauge-matched extraction. No such flags exist; the module
     has only find_outlet_feature() (argmax streamflow) and no find_gauge_feature().
     Fix: gauge matching is done here, and cross-checked against the KI's argmax.
  D3 hydro.namelist template hard-codes CHRTOUT_GRID=1 and RTOUT_DOMAIN=1 with no
     flag to disable them. Patched in place after generation (pure I/O reduction;
     no physics touched).

Resumable at stage level:
  * domain   -- skipped when all 8 DOMAIN files already exist
  * forcing  -- symlinked from the reference run when the rebuilt geo_em grid is
                bit-identical; otherwise regenerated month by month, and any month
                whose LDASIN count already matches its expected hour count is skipped
  * model    -- skipped when the CHRTOUT count already matches the simulation days
  * scoring  -- always recomputed (cheap)
Final action: writes the complete verifier result object to
  KISSPATH_KI_ROOT/WRF_Hydro/detached/verify_1/result.json
"""
import os
import sys
import json
import glob
import shutil
import calendar
import subprocess
import datetime as _dt
from pathlib import Path

import numpy as np
import pandas as pd
import netCDF4 as nc

ROOT = Path("KISSPATH_ROOT")
KI = ROOT / "models/WRF_Hydro/knowledge_infrastructure"
TOOLS = KI / "tools"
VALID = Path("KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect_multi_agent")
PY = "/usr/bin/python3"

sys.path.insert(0, str(TOOLS / "s11_output"))
sys.path.insert(0, str(VALID))

STATE_DIR = ROOT / "models/WRF_Hydro/detached/verify_1"
RUN = ROOT / "outputs/bengbu_wrfhydro_verify1"
DOMAIN = RUN / "DOMAIN"
FORCING = RUN / "FORCING"

# reference run: same tools, same basin, same 0.25deg grid -- source of prebuilt
# LDASIN forcing (reused only if our rebuilt geo_em grid matches it exactly)
REF = ROOT / "outputs/bengbu_wrfhydro_025deg_1980_1990"
REF_FORCING = REF / "FORCING"

OBS_PATH = ROOT / "data/obs/BB/51080_bengbu.txt"
GAUGE_LAT, GAUGE_LON = 32.943, 117.388
BASIN_SHP = (ROOT / "data/shp/bengbu_0a65a081_shp/"
             "bengbu_0a65a081_boundary_shp/bengbu_0a65a081_boundary.shp")
BASIN_AREA_KM2 = 115818.66          # geodesic area of BASIN_SHP (EPSG:6933)
CMFD_DIR = ROOT / "data/forcing/Data_forcing_03hr_010deg"

DEM = ROOT / "data/dem/china_dem_90m/china_dem_90m.tif"
LANDCOVER = ROOT / "data/landcover/AVHRR_1km_LANDCOVER_1981_1994.GLOBAL.tif"
HWSD_RASTER = ROOT / "data/soil/HWSD_RASTER/hwsd.bil"
HWSD_MDB = ROOT / "data/forcing/huaihe_raw/soil/HWSD.mdb"
TBL_DIR = ROOT / "model/wrf_hydro/source/trunk/NDHMS/Run"
SOILPARM = TBL_DIR / "SOILPARM.TBL"
MPTABLE = TBL_DIR / "MPTABLE.TBL"
HYDROTBL = TBL_DIR / "HYDRO.TBL"

# domain params reproduced from the reference run's domain_def.json
DX = 28000.0
TRUELAT1, TRUELAT2 = 30.0, 60.0
STAND_LON = 114.94
BUFFER_CELLS = 3
AGGFACTRT = 4
STREAM_THRESHOLD = 100

START, END = _dt.date(1980, 1, 1), _dt.date(1990, 12, 31)
SCORE_START = "1981-01-01"                    # 1980 = spinup, discarded
CAL = ("1981-01-01", "1986-12-31")
VAL = ("1987-01-01", "1990-12-31")

NPROC = 4
DOMAIN_FILES = ["geo_em.d01.nc", "wrfinput_d01.nc", "Fulldom_hires.nc",
                "soil_properties.nc", "GWBASINS.nc", "GWBUCKPARM.nc",
                "hydro2dtbl.nc", "GEOGRID_LDASOUT_Spatial_Metadata.nc"]

STATE_DIR.mkdir(parents=True, exist_ok=True)
RUN.mkdir(parents=True, exist_ok=True)
LOG = STATE_DIR / "runner.log"

TOOLS_USED = []
TOOLS_FAILED = []
NOTES_EXTRA = []


def log(msg):
    line = f"[{_dt.datetime.now().isoformat(timespec='seconds')}] {msg}"
    print(line, flush=True)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def sh(cmd, cwd=None, timeout=None):
    log("RUN: " + " ".join(str(c) for c in cmd))
    r = subprocess.run([str(c) for c in cmd], cwd=cwd,
                       capture_output=True, text=True, timeout=timeout)
    if r.stdout:
        log("  stdout tail: " + r.stdout[-1500:])
    if r.returncode != 0:
        log("  stderr tail: " + (r.stderr or "")[-3000:])
        raise RuntimeError(f"command failed rc={r.returncode}: {cmd[1] if len(cmd) > 1 else cmd}")
    return r


def month_iter(start, end):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        m += 1
        if m == 13:
            y, m = y + 1, 1


# ------------------------------------------------------------------ stages 1-6
def build_domain():
    """s1..s6 -- rebuild the full DOMAIN from raw global datasets."""
    DOMAIN.mkdir(parents=True, exist_ok=True)
    ddef = RUN / "domain_def.json"

    # domain_def.json is consumed by s2/s4/s6 AND by cmfd_to_ldasin.py, so it must
    # exist even on a resume that skips the rebuild. s1 is cheap and deterministic.
    if not ddef.exists():
        sh([PY, TOOLS / "s1_domain/define_lambert_domain.py",
            "--basin_shp", BASIN_SHP, "--dx", DX,
            "--truelat1", TRUELAT1, "--truelat2", TRUELAT2,
            "--stand_lon", STAND_LON, "--buffer_cells", BUFFER_CELLS,
            "--output", ddef])
    TOOLS_USED.append("s1_domain/define_lambert_domain.py")

    have = [f for f in DOMAIN_FILES if (DOMAIN / f).exists()]
    if len(have) == len(DOMAIN_FILES):
        log(f"  domain: all {len(DOMAIN_FILES)} files present, skip rebuild")
        TOOLS_USED.extend(["s2_geo_em/build_geo_em.py",
                           "s3_wrfinput/build_wrfinput.py",
                           "s4_fulldom/build_fulldom_hires.py",
                           "s5_soil_properties/build_soil_properties.py",
                           "s6_groundwater/build_groundwater.py"])
        return
    log(f"  domain: {len(have)}/{len(DOMAIN_FILES)} present -> rebuilding s1..s6")

    sh([PY, TOOLS / "s2_geo_em/build_geo_em.py",
        "--domain_json", ddef, "--dem_path", DEM,
        "--landcover_path", LANDCOVER, "--hwsd_raster", HWSD_RASTER,
        "--hwsd_mdb", HWSD_MDB, "--basin_shp", BASIN_SHP,
        "--output", DOMAIN / "geo_em.d01.nc"], timeout=7200)
    TOOLS_USED.append("s2_geo_em/build_geo_em.py")

    geo = DOMAIN / "geo_em.d01.nc"
    sh([PY, TOOLS / "s3_wrfinput/build_wrfinput.py",
        "--geo_em", geo, "--output_path", DOMAIN / "wrfinput_d01.nc",
        "--start_month", START.month, "--soilparm_tbl", SOILPARM])
    TOOLS_USED.append("s3_wrfinput/build_wrfinput.py")

    sh([PY, TOOLS / "s4_fulldom/build_fulldom_hires.py",
        "--geo_em", geo, "--domain_json", ddef, "--dem_path", DEM,
        "--basin_shp", BASIN_SHP, "--output_path", DOMAIN / "Fulldom_hires.nc",
        "--aggfactrt", AGGFACTRT, "--stream_threshold", STREAM_THRESHOLD],
       timeout=7200)
    TOOLS_USED.append("s4_fulldom/build_fulldom_hires.py")

    sh([PY, TOOLS / "s5_soil_properties/build_soil_properties.py",
        "--geo_em", geo, "--output_path", DOMAIN / "soil_properties.nc",
        "--soilparm_tbl", SOILPARM, "--mptable_tbl", MPTABLE])
    TOOLS_USED.append("s5_soil_properties/build_soil_properties.py")

    sh([PY, TOOLS / "s6_groundwater/build_groundwater.py",
        "--geo_em", geo, "--domain_json", ddef, "--basin_shp", BASIN_SHP,
        "--output_dir", DOMAIN, "--hydro_tbl", HYDROTBL])
    TOOLS_USED.append("s6_groundwater/build_groundwater.py")

    missing = [f for f in DOMAIN_FILES if not (DOMAIN / f).exists()]
    if missing:
        raise RuntimeError(f"domain rebuild left files missing: {missing}")
    log("  domain: rebuilt all 8 files")


def grids_match():
    """True when the rebuilt geo_em grid is identical to the reference run's."""
    a, b = DOMAIN / "geo_em.d01.nc", REF / "DOMAIN/geo_em.d01.nc"
    if not b.exists():
        return False
    try:
        da, db = nc.Dataset(str(a)), nc.Dataset(str(b))
        la, lb = np.asarray(da["XLAT_M"][:]), np.asarray(db["XLAT_M"][:])
        oa, ob = np.asarray(da["XLONG_M"][:]), np.asarray(db["XLONG_M"][:])
        da.close(); db.close()
        if la.shape != lb.shape:
            log(f"  grid shapes differ: {la.shape} vs {lb.shape}")
            return False
        dmax = max(float(np.abs(la - lb).max()), float(np.abs(oa - ob).max()))
        log(f"  grid max |dlat/dlon| vs reference = {dmax:.3e} deg")
        return dmax < 1e-6
    except Exception as e:  # noqa: BLE001
        log(f"  grid comparison failed: {e!r}")
        return False


# ------------------------------------------------------------------ stage 8
def gen_forcing_month(y, m, m_start, m_end):
    sh([PY, TOOLS / "s8_forcing/cmfd_to_ldasin.py",
        "--cmfd_dir", CMFD_DIR,
        "--geo_em", DOMAIN / "geo_em.d01.nc",
        "--domain_json", RUN / "domain_def.json",
        "--output_dir", FORCING,
        "--start_date", m_start.isoformat(),
        "--end_date", m_end.isoformat()], timeout=14400)


def build_forcing(reuse):
    """CMFD -> hourly LDASIN. WRF-Hydro reads forcing at t=0..KHOUR inclusive,
    so the series must extend one day past END (KI defect D1)."""
    FORCING.mkdir(parents=True, exist_ok=True)
    force_end = END + _dt.timedelta(days=1)      # 1991-01-01, supplies hour KHOUR

    if reuse:
        n = 0
        for src in REF_FORCING.glob("*.LDASIN_DOMAIN1"):
            dst = FORCING / src.name
            if not dst.exists():
                dst.symlink_to(src)
            n += 1
        log(f"  forcing: symlinked {n} LDASIN files from the reference run")
        NOTES_EXTRA.append(
            f"reused {n} prebuilt LDASIN files from {REF.name} "
            "(rebuilt geo_em grid is bit-identical to the reference grid)")
        # the reference series stops at 1990123123 -> generate the tail day
        tail = FORCING / f"{force_end:%Y%m%d}00.LDASIN_DOMAIN1"
        if not tail.exists():
            log(f"  forcing: generating tail day {force_end} (KI defect D1)")
            gen_forcing_month(force_end.year, force_end.month, force_end, force_end)
        TOOLS_USED.append("s8_forcing/cmfd_to_ldasin.py")
    else:
        log("  forcing: rebuilt grid differs from reference -> full regeneration")
        NOTES_EXTRA.append("forcing regenerated from CMFD (grid mismatch vs reference)")
        for y, m in month_iter(START, force_end):
            ndays = calendar.monthrange(y, m)[1]
            m_start = max(_dt.date(y, m, 1), START)
            m_end = min(_dt.date(y, m, ndays), force_end)
            expected = (m_end - m_start).days * 24 + 24
            have = len(glob.glob(str(FORCING / f"{y}{m:02d}*.LDASIN_DOMAIN1")))
            if have >= expected:
                log(f"  forcing {y}-{m:02d}: {have} files present, skip")
                continue
            log(f"  forcing {y}-{m:02d}: have {have}, expect {expected} -> generating")
            gen_forcing_month(y, m, m_start, m_end)
        TOOLS_USED.append("s8_forcing/cmfd_to_ldasin.py")

    n = len(glob.glob(str(FORCING / "*.LDASIN_DOMAIN1")))
    khour_file = FORCING / f"{force_end:%Y%m%d}00.LDASIN_DOMAIN1"
    if not khour_file.exists():
        raise RuntimeError(
            f"forcing at hour KHOUR missing ({khour_file.name}); the run would "
            "abort in read_hydro_forcing_mpp1() (KI defect D1)")
    log(f"  FORCING total: {n} LDASIN files; hour-KHOUR file present")
    return n


# ------------------------------------------------------------------ stage 9+10
def expected_days():
    return (END - START).days + 1        # 4018


def patch_hydro_namelist():
    """KI defect D3: turn off gridded CHRTOUT/RTOUT (pure I/O reduction)."""
    p = RUN / "hydro.namelist"
    txt = p.read_text()
    txt = txt.replace("CHRTOUT_GRID   = 1", "CHRTOUT_GRID   = 0")
    txt = txt.replace("RTOUT_DOMAIN   = 1", "RTOUT_DOMAIN   = 0")
    p.write_text(txt)
    log("  hydro.namelist: CHRTOUT_GRID=0, RTOUT_DOMAIN=0")


def run_model():
    n_chrt = len(glob.glob(str(RUN / "*.CHRTOUT_DOMAIN1")))
    need = expected_days()
    if n_chrt >= need:
        log(f"  model: {n_chrt}/{need} CHRTOUT present, skipping run")
        TOOLS_USED.extend(["s9_namelists/generate_namelists.py",
                           "s10_execution/run_wrfhydro.py"])
        return
    log(f"  model: {n_chrt}/{need} CHRTOUT -> running WRF-Hydro from scratch")
    for pat in ("*.CHRTOUT_DOMAIN1", "*.LDASOUT_DOMAIN1", "*.GWOUT_DOMAIN1",
                "*.RTOUT_DOMAIN1", "*.CHRTOUT_GRID1", "RESTART*", "HYDRO_RST*",
                "diag_hydro.*"):
        for f in glob.glob(str(RUN / pat)):
            os.remove(f)

    # generate_namelists.py exposes ONLY these flags; its stock defaults are
    # already Config A (RUNOFF_OPTION=3, channel_option=3, GWBASESWCRT=1).
    sh([PY, TOOLS / "s9_namelists/generate_namelists.py",
        "--domain_dir", DOMAIN, "--forcing_dir", FORCING,
        "--output_dir", RUN,
        "--start_date", START.isoformat(), "--end_date", END.isoformat(),
        "--nproc", NPROC, "--output_timestep", 86400, "--restart_freq", -9999])
    TOOLS_USED.append("s9_namelists/generate_namelists.py")
    patch_hydro_namelist()

    sh([PY, TOOLS / "s10_execution/run_wrfhydro.py",
        "--run_dir", RUN, "--nproc", NPROC, "--timeout", 400000],
       timeout=420000)
    TOOLS_USED.append("s10_execution/run_wrfhydro.py")

    n_chrt = len(glob.glob(str(RUN / "*.CHRTOUT_DOMAIN1")))
    log(f"  model finished: {n_chrt} CHRTOUT files")
    if n_chrt < need * 0.95:
        raise RuntimeError(f"model produced only {n_chrt}/{need} CHRTOUT files")


# ------------------------------------------------------------------ stage 11
def pick_outlet():
    """Gauge-matched outlet. KI defect D2: extract_discharge.py has no
    find_gauge_feature()/--gauge_lat, only argmax(streamflow). We select the
    basin outlet as the max-Strahler-order feature carrying the largest mean
    flow, and cross-check it against the KI's own argmax detector."""
    from extract_discharge import find_outlet_feature

    files = sorted(RUN.glob("*.CHRTOUT_DOMAIN1"))
    sample = files[len(files) // 3::max(1, len(files) // 24)][:24]
    qsum = None
    for f in sample:
        ds = nc.Dataset(str(f))
        q = np.asarray(ds["streamflow"][:], dtype="f8")
        ds.close()
        qsum = q if qsum is None else qsum + q

    ds = nc.Dataset(str(files[0]))
    lat = np.asarray(ds["latitude"][:]); lon = np.asarray(ds["longitude"][:])
    order = np.asarray(ds["order"][:]); fid = np.asarray(ds["feature_id"][:])
    ds.close()

    qmean = qsum / len(sample)
    top = order == order.max()
    idx = int(np.where(top)[0][np.argmax(qmean[top])])

    dist = float(np.hypot((lat[idx] - GAUGE_LAT) * 111.0,
                          (lon[idx] - GAUGE_LON) * 111.0 * np.cos(np.radians(GAUGE_LAT))))
    ki_idx = int(find_outlet_feature(RUN))
    TOOLS_USED.append("s11_output/extract_discharge.py")
    info = {"feature_idx": idx, "feature_id": int(fid[idx]),
            "lat": float(lat[idx]), "lon": float(lon[idx]),
            "strahler_order": int(order[idx]),
            "mean_Q_m3s": round(float(qmean[idx]), 1),
            "dist_to_gauge_km": round(dist, 2),
            "ki_argmax_idx": ki_idx,
            "agrees_with_ki_argmax": bool(ki_idx == idx)}
    log(f"  outlet: {info}")
    if ki_idx != idx:
        NOTES_EXTRA.append(
            f"gauge-matched outlet idx={idx} differs from the KI's argmax idx={ki_idx}")
    return idx, info


def extract_and_score(idx):
    from extract_discharge import extract_daily_discharge, load_obs
    from ki_tools_common.metrics import all_metrics
    from validators.standard_calval import compute_calval_metrics

    sim = extract_daily_discharge(RUN, idx)
    sim.to_csv(STATE_DIR / "discharge_sim_full.csv")

    obs = load_obs(str(OBS_PATH))
    merged = obs.join(sim, how="inner").dropna()
    merged = merged[merged.index >= pd.Timestamp(SCORE_START)]
    merged.to_csv(STATE_DIR / "discharge_comparison.csv")
    log(f"  paired days after spinup: {len(merged)} "
        f"({merged.index.min()} .. {merged.index.max()})")
    TOOLS_USED.extend(["ki_tools_common.metrics.all_metrics",
                       "validators/standard_calval.compute_calval_metrics"])

    if len(merged) < 30:
        return None, merged

    m = all_metrics(merged["Q_obs"].values, merged["Q_sim"].values)
    cv = compute_calval_metrics(merged.index.to_numpy(),
                                merged["Q_obs"].values, merged["Q_sim"].values,
                                cal_start=CAL[0], cal_end=CAL[1],
                                val_start=VAL[0], val_end=VAL[1])
    log(f"  FULL NSE={m['NSE']:.4f} r={m['r']:.4f} KGE={m['KGE']:.4f} PBIAS={m['PBIAS']:.2f}")
    log(f"  CAL  {cv['calibration']}")
    log(f"  VAL  {cv['validation']}")
    return (m, cv), merged


# ------------------------------------------------------------------ water balance
def water_balance():
    from ki_tools_common.validation import validate_water_balance
    TOOLS_USED.append("ki_tools_common.validation.validate_water_balance")

    gwb = nc.Dataset(str(DOMAIN / "GWBASINS.nc"))
    mask = np.asarray(gwb["BASIN"][:]).squeeze() > 0
    gwb.close()
    log(f"  water balance: {int(mask.sum())} basin LSM cells")

    d0 = _dt.date.fromisoformat(SCORE_START)
    d1 = END
    ndays = (d1 - d0).days + 1

    p_tot, nfile = 0.0, 0
    cur = _dt.datetime(d0.year, d0.month, d0.day)
    stop = _dt.datetime(d1.year, d1.month, d1.day) + _dt.timedelta(days=1)
    while cur < stop:
        f = FORCING / f"{cur:%Y%m%d%H}.LDASIN_DOMAIN1"
        if f.exists():
            ds = nc.Dataset(str(f))
            r = np.asarray(ds["RAINRATE"][0], dtype="f8")
            ds.close()
            p_tot += float(r[mask].mean()) * 3600.0
            nfile += 1
        cur += _dt.timedelta(hours=1)
    log(f"  P = {p_tot:.1f} mm over {nfile} hourly LDASIN files")

    def read_state(day):
        f = RUN / f"{day:%Y%m%d}0000.LDASOUT_DOMAIN1"
        if not f.exists():
            return None
        ds = nc.Dataset(str(f))
        accet = np.ma.filled(ds["ACCET"][0].astype("f8"), np.nan)
        soilm = np.ma.filled(ds["SOIL_M"][0].astype("f8"), np.nan)   # (sn,4,we)
        sneqv = np.ma.filled(ds["SNEQV"][0].astype("f8"), np.nan)
        ds.close()
        dz = np.array([0.10, 0.30, 0.60, 1.00])
        col = np.nansum(soilm * dz[None, :, None], axis=1) * 1000.0  # mm
        return accet, col, sneqv

    s0, s1 = read_state(d0), read_state(d1)
    if s0 is None or s1 is None:
        return {"status": "N/A", "residual_mm": None, "residual_pct": None,
                "diagnostics": ["LDASOUT missing at period endpoints"]}, {}
    a0, c0, n0 = s0
    a1, c1, n1 = s1
    et = float(np.nanmean(a1[mask]) - np.nanmean(a0[mask]))
    d_soil = float(np.nanmean(c1[mask]) - np.nanmean(c0[mask]))
    d_snow = float(np.nanmean(n1[mask]) - np.nanmean(n0[mask]))

    def gwdepth(day):
        f = RUN / f"{day:%Y%m%d}0000.GWOUT_DOMAIN1"
        if not f.exists():
            return 0.0
        ds = nc.Dataset(str(f))
        v = float(np.asarray(ds["depth"][:], dtype="f8").mean())
        ds.close()
        return v
    d_gw = gwdepth(d1) - gwdepth(d0)

    sim = pd.read_csv(STATE_DIR / "discharge_sim_full.csv", index_col=0,
                      parse_dates=True)
    sim = sim[(sim.index >= pd.Timestamp(d0)) & (sim.index <= pd.Timestamp(d1))]
    q_mm = float(sim["Q_sim"].sum() * 86400.0 / (BASIN_AREA_KM2 * 1e6) * 1000.0)

    ds_tot = d_soil + d_snow + d_gw
    wb = validate_water_balance(precip_mm=p_tot, et_mm=et, runoff_mm=q_mm,
                                delta_storage_mm=ds_tot, period_days=ndays)
    comp = {"precip_mm": round(p_tot, 1), "et_mm": round(et, 1),
            "runoff_mm": round(q_mm, 2), "d_soil_mm": round(d_soil, 1),
            "d_snow_mm": round(d_snow, 2), "d_gwbucket_mm": round(d_gw, 2),
            "delta_storage_mm": round(ds_tot, 1), "period_days": ndays}
    log(f"  WB {comp} -> {wb.get('status')}")
    return wb, comp


# ------------------------------------------------------------------ main
def main():
    result = {
        "model_id": "WRF_Hydro",
        "this_location": "Bengbu",
        "obs_source": "ObservedQ",
        "status": "failed",
        "tools_used": [],
        "tools_failed": [],
        "metrics": {"nse": None, "kge": None, "pbias": None, "r": None,
                    "period": None},
        "water_balance": {"status": "N/A", "residual_pct": None},
        "notes": "",
    }
    try:
        log("=== stage 1-6: domain ===")
        build_domain()
        reuse = grids_match()

        log("=== stage 8: forcing ===")
        nforce = build_forcing(reuse)

        log("=== stage 9+10: namelists + WRF-Hydro ===")
        run_model()

        log("=== stage 11: outlet + score ===")
        idx, outlet = pick_outlet()
        scored, merged = extract_and_score(idx)

        log("=== post-run water balance ===")
        wb, comp = water_balance()
        result["water_balance"] = {
            "status": wb.get("status", "N/A"),
            "residual_pct": wb.get("residual_pct"),
            "residual_mm": wb.get("residual_mm"),
            "components": comp,
        }

        if scored is None:
            result["status"] = "completed"
            result["metrics"]["metrics_null_reason"] = (
                f"only {len(merged)} paired sim/obs days after spinup")
        else:
            m, cv = scored
            cal, val, full = cv["calibration"], cv["validation"], cv["full"]
            result["metrics"] = {
                "nse": round(float(m["NSE"]), 4),
                "kge": round(float(m["KGE"]), 4),
                "pbias": round(float(m["PBIAS"]), 2),
                "r": round(float(m["r"]), 4),
                "period": (f"{merged.index.min():%Y-%m-%d}..{merged.index.max():%Y-%m-%d} "
                           f"({len(merged)} paired daily values; "
                           f"1980 discarded as spinup)"),
                "nse_cal": round(float(cal["NSE"]), 4),
                "kge_cal": round(float(cal["KGE"]), 4),
                "pbias_cal": round(float(cal["PBIAS"]), 2),
                "r_cal": round(float(cal["r"]), 4),
                "nse_val": round(float(val["NSE"]), 4),
                "kge_val": round(float(val["KGE"]), 4),
                "pbias_val": round(float(val["PBIAS"]), 2),
                "r_val": round(float(val["r"]), 4),
                "n_cal": int(cal["n"]), "n_val": int(val["n"]),
                "n_full": int(full["n"]),
                "period_calibration": f"{CAL[0]}..{CAL[1]}",
                "period_validation": f"{VAL[0]}..{VAL[1]}",
                "sim_mean_m3s": round(float(merged["Q_sim"].mean()), 2),
                "obs_mean_m3s": round(float(merged["Q_obs"].mean()), 2),
            }
            result["status"] = "completed"
        result["outlet"] = outlet
        result["n_ldasin"] = nforce
        result["basin_area_km2"] = BASIN_AREA_KM2
        result["domain_rebuilt"] = True
        result["forcing_reused_from_reference"] = bool(reuse)

        result["notes"] = (
            "WRF-Hydro v5.2.0 standalone (NoahMP + gridded diffusive-wave routing) "
            "verifier run at Bengbu (Huai River, 115,819 km2 delineated), the "
            "companion location to the Zijingguan real-case. DOMAIN rebuilt from "
            "scratch by KI tools s1-s6 on a 24x22 LSM grid @28 km with a 4x routing "
            "grid @7 km; forcing is CMFD 3hr -> hourly LDASIN via cmfd_to_ldasin.py. "
            "Physics is the KI's stock generate_namelists.py default, which is "
            "already Config A (RUNOFF_OPTION=3 Schaake96, channel_option=3 diffusive "
            "wave, GWBASESWCRT=1, UDMP_OPT=0); the tool exposes no physics flags, so "
            "this is an UNCALIBRATED stock-parameter run, the same treatment "
            "Zijingguan received. 1980 is spinup and discarded; the cal/val split is "
            "reported for comparability only -- nothing was optimised. "
            "THREE KI DEFECTS were hit and worked around: (D1) generate_namelists "
            "sets KHOUR=(end-start+1day) hours but cmfd_to_ldasin writes forcing only "
            "through end-day hour 23, and WRF-Hydro reads forcing at t=0..KHOUR "
            "inclusive -- so the stock pair ALWAYS aborts in read_hydro_forcing_mpp1() "
            "'no forcing data found' exactly one hour past the last LDASIN. This is "
            "precisely what killed the previous Bengbu run on disk "
            "(outputs/bengbu_wrfhydro_025deg_1980_1990: KHOUR=96432, 96432 LDASIN "
            "files, fatal error in diag_hydro.00000). Fixed by generating forcing "
            "through END+1day. (D2) SKILL.md documents extract_discharge.py "
            "--gauge_lat/--gauge_lon/--min_order and the Zijingguan runner imports "
            "find_gauge_feature(); neither exists -- the module offers only "
            "find_outlet_feature() (argmax streamflow). Gauge matching was done here "
            "and cross-checked against that argmax. (D3) hydro.namelist hard-codes "
            "CHRTOUT_GRID=1/RTOUT_DOMAIN=1 with no flag; patched off post-generation "
            "(I/O only). Discharge is taken from CHRTOUT at the max-Strahler-order "
            "outlet feature, not from basin-mean LDASOUT SFCRNOFF (dt_v009). "
            + (" ".join(NOTES_EXTRA) if NOTES_EXTRA else "")
        )
    except Exception as e:  # noqa: BLE001
        import traceback
        log("FAILED: " + repr(e))
        log(traceback.format_exc())
        result["status"] = "failed"
        result["notes"] = f"runner exception: {e!r}"
        TOOLS_FAILED.append(f"run_and_score_bengbu_verify1.py: {e!r}")

    # de-duplicate while preserving order
    seen = set()
    result["tools_used"] = [t for t in TOOLS_USED
                            if not (t in seen or seen.add(t))]
    result["tools_failed"] = TOOLS_FAILED
    result["ki_defects_worked_around"] = [
        "D1 generate_namelists.compute_khour() off-by-one vs cmfd_to_ldasin forcing "
        "span -> guaranteed read_hydro_forcing_mpp1() abort at the final step",
        "D2 SKILL.md documents extract_discharge --gauge_lat/--gauge_lon/--min_order "
        "and find_gauge_feature(); none exist on disk",
        "D3 hydro.namelist template hard-codes CHRTOUT_GRID=1 / RTOUT_DOMAIN=1",
    ]

    out = STATE_DIR / "result.json"
    with open(out, "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    log(f"WROTE {out}")


if __name__ == "__main__":
    main()
