#!/usr/bin/env python3
"""
WRF-Hydro v5.2.0 standalone -- VERIFIER run at Berounka @ Beroun (GRDC_6140250).

Third location for the WRF-Hydro KI consistency check. Companions:
  * real-case : 紫荆关 Zijingguan (Juma R., Haihe, regulated arid N-China)  -> failed
  * verify_1  : Bengbu (Huai R., China, CMFD forcing)
  * verify_2  : THIS -- Berounka @ Beroun, Czech Republic, GRDC-Caravan Extension

Why Berounka: a clean, humid-continental, essentially unregulated central-European
basin (~8,300 km2). This is a genuine generalization test for the KI OUTSIDE China
and away from the regulated-arid failure mode -- comparable in scale/climate to the
KI's own validated global cases (Kettle River, Balsas, Clutha, Spain GRDC).

Gauge   : GRDC_6140250, 49.9604N 14.0854E, Caravan area 8295.554 km2.
Obs     : GRDC-Caravan Extension NetCDF, variable `streamflow` in Caravan units of
          mm/day. Converted to m3/s by  Q = streamflow_mm_day * area_km2 / 86.4
          (inverting Caravan's own area normalization; area = Caravan attribute area).
Basin   : polygon GRDC_6140250 from grdc_basin_shapes.shp -> berounka_basin.shp
          (delineated 8323 km2, matches Caravan 8296 km2).
Forcing : NASA POWER hourly (global, 2001-present) -> hourly LDASIN on the LCC grid
          via the KI tool tools/s8_forcing/nasa_power_to_ldasin.py (cached per
          point/year -> resumable).
DEM     : SRTM GL1 auto-merged for the domain (20 tiles) via the KI's
          run_wrfhydro_full_pipeline.auto_merge_srtm_dem().
Domain  : rebuilt from scratch by KI tools s1..s6, 18x18 LSM @10 km, 72x72 routing
          @2.5 km (aggfactrt=4), stand_lon=basin centre.
Physics : the KI's stock generate_namelists.py defaults, which ARE "Config A"
          (RUNOFF_OPTION=3 Schaake96, channel_option=3 diffusive-wave gridded,
          GWBASESWCRT=1 exp bucket, UDMP_OPT=0, rst_typ=0). The tool exposes NO
          physics CLI flags, so this is an UNCALIBRATED stock-parameter run -- the
          same treatment the Zijingguan real-case and the Bengbu verifier received.

Period  : 2009-07-01 .. 2013-12-31 (cold start in July -> avoids the Jan frozen-soil
          crash dt_v023).
          spinup      2009-07-01 .. 2009-12-31 (discarded)
          calibration 2010-01-01 .. 2011-12-31 (reported, NOT optimised on)
          validation  2012-01-01 .. 2013-12-31 (held out)
          Nothing is calibrated; the cal/val split is reported only for comparability
          with the other two locations.

KI_DEFECTS worked around (identical to the Bengbu verifier -- all recorded in result):
  D1 end-of-forcing off-by-one: generate_namelists.compute_khour() = (end-start+1day)
     in hours; WRF-Hydro reads forcing at t=0..KHOUR *inclusive*, so it needs an
     LDASIN file at hour KHOUR -- one hour past what the forcing tool writes for the
     same [start,end]. Fix: generate NASA POWER forcing through END + 1 day.
  D2 SKILL.md documents extract_discharge.py --gauge_lat/--gauge_lon/--min_order and
     a find_gauge_feature(); none exist on disk (only find_outlet_feature() = argmax
     streamflow). Gauge matching is done here and cross-checked against that argmax.
  D3 hydro.namelist hard-codes CHRTOUT_GRID=1 / RTOUT_DOMAIN=1 with no flag; patched
     off after generation (pure I/O reduction; no physics touched).

Resumable at stage level:
  * DEM      -- skipped when dem_srtm_merged.tif already exists
  * domain   -- skipped when all 8 DOMAIN files exist
  * forcing  -- NASA POWER tool caches per point/year; skipped when the hour-KHOUR
                file and the full LDASIN count are already present
  * model    -- skipped only when wrfhydro_run_gate says the run is finished (completion
                banner in a current diag_hydro.* AND run_inputs.json, written at launch,
                matching the current namelists/DOMAIN/FORCING/dates); else old outputs
                are moved aside (kept) and the model runs from scratch
  * scoring  -- always recomputed (cheap)
Final action: writes the complete verifier result object to
  KISSPATH_KI_ROOT/WRF_Hydro/detached/verify_1/result.json
"""
import os
import sys
import json
import glob
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

sys.path.insert(0, str(TOOLS))            # for run_wrfhydro_full_pipeline.auto_merge_srtm_dem
sys.path.insert(0, str(TOOLS / "s11_output"))
sys.path.insert(0, str(VALID))
# wrfhydro_run_gate / wrfhydro_domain_edits ship inside the KI, in tools/ next to this file
sys.path.insert(0, str(Path(__file__).resolve().parent / "tools"))
import wrfhydro_run_gate as gate
import wrfhydro_domain_edits as de

STATE_DIR = ROOT / "models/WRF_Hydro/detached/verify_1"
RUN = ROOT / "outputs/berounka_wrfhydro_verify1"
DOMAIN = RUN / "DOMAIN"
FORCING = RUN / "FORCING"

# ---- obs / gauge / basin --------------------------------------------------
OBS_NC = Path("KISSPATH_DATA/observed_data/dischargeandwatershed/"
              "GRDC-Caravan-extension-nc/timeseries/netcdf/grdc/GRDC_6140250.nc")
GAUGE_LAT, GAUGE_LON = 49.9604, 14.0854
CARAVAN_AREA_KM2 = 8295.554               # inverts Caravan mm/day -> m3/s
BASIN_SHP = RUN / "berounka_basin.shp"
GRDC_ALLSHP = Path("KISSPATH_DATA/observed_data/dischargeandwatershed/"
                   "GRDC-Caravan-extension-nc/shapefiles/grdc/grdc_basin_shapes.shp")

# ---- global static inputs -------------------------------------------------
LANDCOVER = ROOT / "data/landcover/AVHRR_1km_LANDCOVER_1981_1994.GLOBAL.tif"
HWSD_RASTER = ROOT / "data/soil/HWSD_RASTER/hwsd.bil"
HWSD_MDB = ROOT / "data/forcing/huaihe_raw/soil/HWSD.mdb"
TBL_DIR = ROOT / "model/wrf_hydro/source/trunk/NDHMS/Run"
SOILPARM = TBL_DIR / "SOILPARM.TBL"
MPTABLE = TBL_DIR / "MPTABLE.TBL"
HYDROTBL = TBL_DIR / "HYDRO.TBL"
SRTM_DIR = "KISSPATH_DATA/SRTMGL1"
DEM = RUN / "dem_srtm_merged.tif"

# ---- domain params --------------------------------------------------------
DX = 10000.0
TRUELAT1, TRUELAT2 = 30.0, 60.0
STAND_LON = 14.0854
BUFFER_CELLS = 3
AGGFACTRT = 4
STREAM_THRESHOLD = 100
CELL_AREA_KM2 = (DX / 1000.0) ** 2        # 100 km2 per LSM cell

# ---- period ---------------------------------------------------------------
START, END = _dt.date(2009, 7, 1), _dt.date(2013, 12, 31)
# REFKDT for s5 build_soil_properties.py: an explicit choice of THIS runner
# (the tool has no default since 2026-10-05). 0.8 is the value this runner
# effectively used before (the tool's old built-in value), kept unchanged.
REFKDT = 0.8
SCORE_START = "2010-01-01"                # 2009 H2 = spinup, discarded
CAL = ("2010-01-01", "2011-12-31")
VAL = ("2012-01-01", "2013-12-31")

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


# Domain stand-in edits: OFF unless --fix-domain-gaps (see __main__); every
# edit recorded (wrfhydro_domain_edits; soil gaps filled from neighbours).
EDITS = de.DomainEdits(fix=False, soilparm_tbl=ROOT / "model/wrf_hydro/source/trunk/NDHMS/Run/SOILPARM.TBL", log=log)
DOMAIN_EDIT_REC = {}


def sh(cmd, cwd=None, timeout=None):
    log("RUN: " + " ".join(str(c) for c in cmd))
    r = subprocess.run([str(c) for c in cmd], cwd=cwd,
                       capture_output=True, text=True, timeout=timeout)
    if r.stdout:
        log("  stdout tail: " + r.stdout[-1500:])
    if r.returncode != 0:
        log("  stderr tail: " + (r.stderr or "")[-3000:])
        raise RuntimeError(f"command failed rc={r.returncode}: "
                           f"{cmd[1] if len(cmd) > 1 else cmd}")
    return r


def month_iter(start, end):
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        yield y, m
        m += 1
        if m == 13:
            y, m = y + 1, 1


# ------------------------------------------------------------------ basin shp
def ensure_basin_shp():
    if BASIN_SHP.exists():
        return
    import geopandas as gpd
    g = gpd.read_file(str(GRDC_ALLSHP))
    row = g[g["gauge_id"].astype(str) == "GRDC_6140250"].iloc[[0]]
    row.to_file(str(BASIN_SHP))
    log(f"  extracted basin polygon GRDC_6140250 -> {BASIN_SHP.name}")


# ------------------------------------------------------------------ DEM
def ensure_dem(ddef):
    if DEM.exists():
        log(f"  DEM present: {DEM.name}")
        return
    from run_wrfhydro_full_pipeline import auto_merge_srtm_dem
    log("  merging SRTM GL1 tiles for domain ...")
    p = auto_merge_srtm_dem(str(ddef), str(RUN), SRTM_DIR)
    if Path(p) != DEM:
        os.replace(p, DEM)
    log(f"  DEM merged -> {DEM.name}")


# ------------------------------------------------------------------ stages 1-6
def build_domain():
    DOMAIN.mkdir(parents=True, exist_ok=True)
    ddef = RUN / "domain_def.json"

    if not ddef.exists():
        sh([PY, TOOLS / "s1_domain/define_lambert_domain.py",
            "--basin_shp", BASIN_SHP, "--dx", DX,
            "--truelat1", TRUELAT1, "--truelat2", TRUELAT2,
            "--stand_lon", STAND_LON, "--buffer_cells", BUFFER_CELLS,
            "--output", ddef])
    TOOLS_USED.append("s1_domain/define_lambert_domain.py")

    ensure_dem(ddef)

    have = [f for f in DOMAIN_FILES if (DOMAIN / f).exists()]
    if len(have) == len(DOMAIN_FILES) and not de.rebuild_incomplete(DOMAIN):
        log(f"  domain: all {len(DOMAIN_FILES)} files present, skip rebuild")
        TOOLS_USED.extend(["s2_geo_em/build_geo_em.py",
                           "s3_wrfinput/build_wrfinput.py",
                           "s4_fulldom/build_fulldom_hires.py",
                           "s5_soil_properties/build_soil_properties.py",
                           "s6_groundwater/build_groundwater.py"])
        return
    log(f"  domain: {len(have)}/{len(DOMAIN_FILES)} present"
        f"{' (earlier rebuild did not finish)' if de.rebuild_incomplete(DOMAIN) else ''} -> rebuilding s1..s6")
    # Rebuild into a FRESH DOMAIN: the old one (files + edit record) is moved aside
    # whole, so no old, already-edited file can mix with new ones; the mark stays
    # until every file is built (an interrupted rebuild is rebuilt again).
    de.start_rebuild(DOMAIN, log)

    sh([PY, TOOLS / "s2_geo_em/build_geo_em.py",
        "--domain_json", ddef, "--dem_path", DEM,
        "--landcover_path", LANDCOVER, "--hwsd_raster", HWSD_RASTER,
        "--hwsd_mdb", HWSD_MDB, "--basin_shp", BASIN_SHP,
        "--output", DOMAIN / "geo_em.d01.nc"] + EDITS.tool_flags(), timeout=7200)
    TOOLS_USED.append("s2_geo_em/build_geo_em.py")

    geo = DOMAIN / "geo_em.d01.nc"
    sh([PY, TOOLS / "s3_wrfinput/build_wrfinput.py",
        "--geo_em", geo, "--output_path", DOMAIN / "wrfinput_d01.nc",
        "--start_month", START.month, "--soilparm_tbl", SOILPARM] + EDITS.tool_flags())
    TOOLS_USED.append("s3_wrfinput/build_wrfinput.py")

    sh([PY, TOOLS / "s4_fulldom/build_fulldom_hires.py",
        "--geo_em", geo, "--domain_json", ddef, "--dem_path", DEM,
        "--basin_shp", BASIN_SHP, "--output_path", DOMAIN / "Fulldom_hires.nc",
        "--aggfactrt", AGGFACTRT, "--stream_threshold", STREAM_THRESHOLD] + EDITS.tool_flags(),
       timeout=7200)
    TOOLS_USED.append("s4_fulldom/build_fulldom_hires.py")

    sh([PY, TOOLS / "s5_soil_properties/build_soil_properties.py", "--refkdt", REFKDT,
        "--geo_em", geo, "--output_path", DOMAIN / "soil_properties.nc",
        "--soilparm_tbl", SOILPARM, "--mptable_tbl", MPTABLE] + EDITS.tool_flags())
    TOOLS_USED.append("s5_soil_properties/build_soil_properties.py")

    sh([PY, TOOLS / "s6_groundwater/build_groundwater.py",
        "--geo_em", geo, "--domain_json", ddef, "--basin_shp", BASIN_SHP,
        "--output_dir", DOMAIN, "--hydro_tbl", HYDROTBL] + EDITS.tool_flags())
    TOOLS_USED.append("s6_groundwater/build_groundwater.py")

    missing = [f for f in DOMAIN_FILES if not (DOMAIN / f).exists()]
    if missing:
        raise RuntimeError(f"domain rebuild left files missing: {missing}")
    de.finish_rebuild(DOMAIN)
    log("  domain: rebuilt all 8 files")


# ------------------------------------------------------------------ stage 8
def expected_ldasin(force_end):
    return (force_end - START).days * 24 + 1     # t=0 .. hour KHOUR inclusive


ELEV_CORRECTION = "barometric-estimate"          # SKILL section 9 (dt_v008)


def _forcing_reusable(force_end, need):
    """Existing FORCING may be reused only if the strict converter wrote it for
    exactly this period, with the same elevation choice and zero filled values
    (its forcing_provenance.json). Counting files is not enough: FORCING built
    by the old converter (gap filling, fixed 45-degree wind split) has the same
    file names."""
    prov = FORCING / "forcing_provenance.json"
    if not prov.is_file():
        return False, "no forcing_provenance.json (built by the old converter)"
    try:
        p = json.loads(prov.read_text())
    except Exception as e:
        return False, f"unreadable forcing_provenance.json: {e}"
    want = {"start": START.isoformat(), "end": force_end.isoformat(), "filled_values": 0}
    for k, v in want.items():
        if p.get(k) != v:
            return False, f"provenance {k}={p.get(k)!r}, need {v!r}"
    if str(p.get("elevation_correction", "")).startswith("none"):
        return False, "provenance says no elevation correction; this run uses it"
    # The forcing was interpolated (and elevation-corrected) for one geo_em; a
    # rebuilt domain needs new forcing.
    geo = DOMAIN / "geo_em.d01.nc"
    want_geo = p.get("target_geo_em_sha256")
    if not want_geo:
        return False, "provenance has no target_geo_em_sha256 (cannot show it is for this domain)"
    if not geo.is_file():
        return False, f"{geo} missing"
    import hashlib
    h = hashlib.sha256()
    with open(geo, "rb") as fh:
        for b in iter(lambda: fh.read(1 << 20), b""):
            h.update(b)
    if h.hexdigest() != want_geo:
        return False, "forcing was built for another geo_em (target_geo_em_sha256 differs)"
    have = len(glob.glob(str(FORCING / "*.LDASIN_DOMAIN1")))
    if have < need:
        return False, f"{have}/{need} LDASIN files"
    return True, f"{have}/{need} LDASIN files, provenance matches"


def build_forcing():
    """NASA POWER -> hourly LDASIN. Series must extend one day past END so the
    hour-KHOUR file exists (KI defect D1)."""
    force_end = END + _dt.timedelta(days=1)      # 2014-01-01 supplies hour KHOUR
    khour_file = FORCING / f"{force_end:%Y%m%d}00.LDASIN_DOMAIN1"
    need = expected_ldasin(force_end)

    if FORCING.exists():
        ok, why = _forcing_reusable(force_end, need)
        if ok and khour_file.exists():
            log(f"  forcing: reuse ({why})")
            TOOLS_USED.append("s8_forcing/nasa_power_to_ldasin.py")
            return len(glob.glob(str(FORCING / "*.LDASIN_DOMAIN1")))
        # The converter publishes a NEW folder and refuses an existing one, so
        # an old or unverifiable FORCING is moved aside (kept, never deleted).
        aside = FORCING.with_name(f"FORCING.unverified_{_dt.datetime.now():%Y%m%dT%H%M%S}")
        FORCING.rename(aside)
        log(f"  forcing: existing FORCING not reusable ({why}); moved to {aside.name}")

    FORCING.parent.mkdir(parents=True, exist_ok=True)
    log(f"  forcing: build NASA POWER {START}..{force_end} "
        f"(elevation correction: {ELEV_CORRECTION})")
    sh([PY, TOOLS / "s8_forcing/nasa_power_to_ldasin.py",
        "--geo_em", DOMAIN / "geo_em.d01.nc",
        "--output_dir", FORCING,
        "--start_date", START.isoformat(),
        "--end_date", force_end.isoformat(),
        "--elev-correction", ELEV_CORRECTION], timeout=200000)
    TOOLS_USED.append("s8_forcing/nasa_power_to_ldasin.py")

    have = len(glob.glob(str(FORCING / "*.LDASIN_DOMAIN1")))
    if not khour_file.exists():
        raise RuntimeError(
            f"forcing at hour KHOUR missing ({khour_file.name}); the run would "
            "abort in read_hydro_forcing_mpp1() (KI defect D1)")
    log(f"  FORCING total: {have} LDASIN files; hour-KHOUR file present")
    return have


# ------------------------------------------------------------------ stage 9+10
def expected_days():
    return (END - START).days + 1


def patch_hydro_namelist():
    """KI defect D3: turn off gridded CHRTOUT/RTOUT (pure I/O reduction)."""
    p = RUN / "hydro.namelist"
    txt = p.read_text()
    txt = txt.replace("CHRTOUT_GRID   = 1", "CHRTOUT_GRID   = 0")
    txt = txt.replace("RTOUT_DOMAIN   = 1", "RTOUT_DOMAIN   = 0")
    p.write_text(txt)
    log("  hydro.namelist: CHRTOUT_GRID=0, RTOUT_DOMAIN=0")


SUCCESS_BANNER = "The model finished successfully"   # as tools/s10_execution/run_wrfhydro.py


def _run_state(need):
    """(complete, why). Complete only if every daily CHRTOUT exists, a diag file
    has WRF-Hydro's success banner, none reports a FATAL ERROR, and the run is
    newer than the forcing it should have read (forcing_provenance.json). A file
    count alone accepted runs that aborted, or that used forcing since replaced."""
    n = len(glob.glob(str(RUN / "*.CHRTOUT_DOMAIN1")))
    diags = sorted(RUN.glob("diag_hydro.*"))
    text = "".join(d.read_text(errors="replace") for d in diags)
    if "FATAL ERROR" in text:
        return False, f"diag_hydro reports FATAL ERROR ({n}/{need} CHRTOUT)"
    if SUCCESS_BANNER not in text:
        return False, f"no success banner in diag_hydro ({n}/{need} CHRTOUT)"
    days = [START + _dt.timedelta(days=i) for i in range((END - START).days + 1)]
    lost = [d for d in days if not (RUN / f"{d:%Y%m%d}0000.CHRTOUT_DOMAIN1").exists()]
    if lost:
        return False, f"{len(lost)} of {len(days)} daily CHRTOUT missing (first {lost[0]})"
    prov = FORCING / "forcing_provenance.json"
    if not prov.is_file() or min(d.stat().st_mtime for d in diags) < prov.stat().st_mtime:
        return False, "model outputs are older than the current forcing"
    return True, f"{n}/{need} CHRTOUT, finished successfully"


def run_model():
    need = expected_days()
    n_chrt = len(glob.glob(str(RUN / "*.CHRTOUT_DOMAIN1")))
    # Namelists (deterministic) are written first so the finished check compares
    # against the namelists this code would run now.
    sh([PY, TOOLS / "s9_namelists/generate_namelists.py",
        "--domain_dir", DOMAIN, "--forcing_dir", FORCING,
        "--output_dir", RUN,
        "--start_date", START.isoformat(), "--end_date", END.isoformat(),
        "--nproc", NPROC, "--output_timestep", 86400, "--restart_freq", -9999])
    TOOLS_USED.append("s9_namelists/generate_namelists.py")
    patch_hydro_namelist()

    gate.require_forcing_source(RUN, FORCING)
    ok, gwhy = gate.check_finished(RUN, START.isoformat(), END.isoformat(), tables=True, exe=TBL_DIR / "wrf_hydro.exe", tbl_dir=TBL_DIR)
    done, why = _run_state(need)     # earlier checks (FATAL, every day, forcing age) still apply
    if ok and not done:
        ok, gwhy = False, why
    if ok:
        log(f"  model: finished earlier ({gwhy}; {n_chrt}/{need} CHRTOUT), skipping run")
        TOOLS_USED.append("s10_execution/run_wrfhydro.py")
        return
    log(f"  model: not finished ({gwhy}; {n_chrt}/{need} CHRTOUT) -> running WRF-Hydro from scratch")
    aside, n_aside = gate.move_outputs_aside(RUN)
    if aside:
        log(f"  old outputs ({n_aside} files) moved to {aside.name} (kept)")
    # launch-time only: the run folder gets the install tables; a run-local table
    # that differs is moved aside (kept), never deleted. Checks only read them.
    _staged, _kept = gate.stage_tables(RUN, TBL_DIR, keep_dir=(aside / "tables") if aside else None)
    if _kept:
        log(f"  run-local parameter tables that differed from the install kept in {_kept}")
    gate.write_run_inputs(RUN, START.isoformat(), END.isoformat(), tables=True, exe=TBL_DIR / "wrf_hydro.exe", tbl_dir=TBL_DIR)

    sh([PY, TOOLS / "s10_execution/run_wrfhydro.py",
        "--run_dir", RUN, "--tbl_dir", TBL_DIR, "--exe", TBL_DIR / "wrf_hydro.exe", "--nproc", NPROC, "--timeout", 400000],
       timeout=420000)
    TOOLS_USED.append("s10_execution/run_wrfhydro.py")

    gwhy = gate.require_finished_after_run(RUN, START.isoformat(), END.isoformat(), tables=True, exe=TBL_DIR / "wrf_hydro.exe", tbl_dir=TBL_DIR)
    n_chrt = len(glob.glob(str(RUN / "*.CHRTOUT_DOMAIN1")))
    log(f"  model finished: {n_chrt} CHRTOUT files ({gwhy})")
    done, why = _run_state(need)
    log(f"  model finished: {why}")
    if not done:
        raise RuntimeError(f"WRF-Hydro run did not complete: {why}")


# ------------------------------------------------------------------ stage 11
def pick_outlet():
    """Gauge-matched outlet (KI defect D2: extract_discharge.py has only
    find_outlet_feature()=argmax, no gauge matching). Select the feature nearest
    the gauge among the top Strahler orders; cross-check against the KI argmax."""
    from extract_discharge import find_outlet_feature

    files = sorted(RUN.glob("*.CHRTOUT_DOMAIN1"))
    sample = files[len(files) // 3::max(1, len(files) // 24)][:24]
    qsum = None
    for f in sample:
        ds = nc.Dataset(str(f))
        q = np.asarray(ds["streamflow"][:], dtype="f8")
        ds.close()
        qsum = q if qsum is None else qsum + q
    qmean = qsum / len(sample)

    ds = nc.Dataset(str(files[0]))
    lat = np.asarray(ds["latitude"][:]); lon = np.asarray(ds["longitude"][:])
    order = np.asarray(ds["order"][:]); fid = np.asarray(ds["feature_id"][:])
    ds.close()

    # candidates: features in the top two Strahler orders (main stem near outlet)
    omax = int(order.max())
    cand = np.where(order >= max(1, omax - 1))[0]
    dist_all = np.hypot((lat - GAUGE_LAT) * 111.0,
                        (lon - GAUGE_LON) * 111.0 * np.cos(np.radians(GAUGE_LAT)))
    idx = int(cand[np.argmin(dist_all[cand])])

    ki_idx = int(find_outlet_feature(RUN))
    TOOLS_USED.append("s11_output/extract_discharge.py")
    info = {"feature_idx": idx, "feature_id": int(fid[idx]),
            "lat": float(lat[idx]), "lon": float(lon[idx]),
            "strahler_order": int(order[idx]), "max_order": omax,
            "mean_Q_m3s": round(float(qmean[idx]), 2),
            "dist_to_gauge_km": round(float(dist_all[idx]), 2),
            "ki_argmax_idx": ki_idx,
            "ki_argmax_dist_km": round(float(dist_all[ki_idx]), 2),
            "agrees_with_ki_argmax": bool(ki_idx == idx)}
    log(f"  outlet: {info}")
    if ki_idx != idx:
        NOTES_EXTRA.append(
            f"gauge-matched outlet idx={idx} ({info['dist_to_gauge_km']} km from "
            f"gauge) differs from the KI argmax idx={ki_idx} "
            f"({info['ki_argmax_dist_km']} km)")
    return idx, info


def load_obs_m3s():
    ds = nc.Dataset(str(OBS_NC))
    q = np.asarray(ds["streamflow"][:], dtype="f8")            # mm/day (Caravan)
    tvar = ds.variables["date"]
    dates = nc.num2date(tvar[:], tvar.units,
                        only_use_cftime_datetimes=False)
    ds.close()
    idx = pd.to_datetime([pd.Timestamp(str(d)) for d in dates]).normalize()
    s = pd.Series(q * CARAVAN_AREA_KM2 / 86.4, index=idx, name="Q_obs")  # -> m3/s
    s = s[(s.notna()) & (s >= 0)]
    return s


def extract_and_score(idx):
    from extract_discharge import extract_daily_discharge
    from ki_tools_common.metrics import all_metrics
    from validators.standard_calval import compute_calval_metrics

    sim = extract_daily_discharge(RUN, idx)          # DataFrame index=date, Q_sim
    sim.to_csv(STATE_DIR / "discharge_sim_full.csv")
    sim.index = pd.to_datetime(sim.index).normalize()

    obs = load_obs_m3s()
    merged = pd.concat([obs, sim["Q_sim"]], axis=1, join="inner").dropna()
    # END cut too: the run writes one more daily CHRTOUT, stamped END+1 00:00
    merged = merged[(merged.index >= pd.Timestamp(SCORE_START)) &
                    (merged.index <= pd.Timestamp(END))]
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
    log(f"  FULL NSE={m['NSE']:.4f} r={m['r']:.4f} KGE={m['KGE']:.4f} "
        f"PBIAS={m['PBIAS']:.2f}")
    log(f"  CAL {cv['calibration']}")
    log(f"  VAL {cv['validation']}")
    return (m, cv), merged


# ------------------------------------------------------------------ water balance
def water_balance():
    from ki_tools_common.validation import validate_water_balance
    TOOLS_USED.append("ki_tools_common.validation.validate_water_balance")

    gwb = nc.Dataset(str(DOMAIN / "GWBASINS.nc"))
    mask = np.asarray(gwb["BASIN"][:]).squeeze() > 0
    gwb.close()
    area_km2 = float(mask.sum()) * CELL_AREA_KM2
    log(f"  water balance: {int(mask.sum())} basin LSM cells "
        f"(~{area_km2:.0f} km2)")

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
    q_mm = float(sim["Q_sim"].sum() * 86400.0 / (area_km2 * 1e6) * 1000.0)

    ds_tot = d_soil + d_snow + d_gw
    wb = validate_water_balance(precip_mm=p_tot, et_mm=et, runoff_mm=q_mm,
                                delta_storage_mm=ds_tot, period_days=ndays)
    comp = {"precip_mm": round(p_tot, 1), "et_mm": round(et, 1),
            "runoff_mm": round(q_mm, 2), "d_soil_mm": round(d_soil, 1),
            "d_snow_mm": round(d_snow, 2), "d_gwbucket_mm": round(d_gw, 2),
            "delta_storage_mm": round(ds_tot, 1), "period_days": ndays,
            "basin_area_km2": round(area_km2, 1)}
    log(f"  WB {comp} -> {wb.get('status')}")
    return wb, comp


# ------------------------------------------------------------------ main
def main():
    result = {
        "model_id": "WRF_Hydro",
        "this_location": "GRDC-Caravan Extension (5,357 global gauges + basin shapes)",
        "obs_source": "GRDC",
        "status": "failed",
        "tools_used": [],
        "tools_failed": [],
        "metrics": {"nse": None, "kge": None, "pbias": None, "r": None,
                    "period": None},
        "water_balance": {"status": "N/A", "residual_pct": None},
        "notes": "",
    }
    try:
        log("=== basin polygon ===")
        ensure_basin_shp()

        log("=== stage 1-6: domain (+SRTM DEM) ===")
        build_domain()
        DOMAIN_EDIT_REC.clear(); DOMAIN_EDIT_REC.update(de.ensure_domain_record(DOMAIN, EDITS, STATE_DIR, log))

        log("=== stage 8: NASA POWER forcing ===")
        nforce = build_forcing()

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
            # no metrics = failed (JSON status and exit code agree)
            result["status"] = "failed"
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
                "period": (f"{merged.index.min():%Y-%m-%d}.."
                           f"{merged.index.max():%Y-%m-%d} "
                           f"({len(merged)} paired daily values; "
                           f"2009-H2 discarded as spinup)"),
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
        result["caravan_area_km2"] = CARAVAN_AREA_KM2
        result["domain_rebuilt"] = True

        result["notes"] = (
            "WRF-Hydro v5.2.0 standalone (NoahMP + gridded diffusive-wave routing) "
            "verifier at Berounka @ Beroun (GRDC_6140250, Czech Republic, Caravan "
            "area 8,296 km2) -- the third KI location and the first genuinely "
            "OUT-OF-CHINA, unregulated humid-continental test, complementing the "
            "Zijingguan real-case (regulated arid N-China, failed) and the Bengbu "
            "verifier. DOMAIN rebuilt from scratch by KI tools s1-s6 on an 18x18 LSM "
            "grid @10 km with a 4x routing grid @2.5 km; DEM auto-merged from 20 SRTM "
            "GL1 tiles; forcing is NASA POWER hourly -> LDASIN via "
            "nasa_power_to_ldasin.py. Physics is the KI's stock generate_namelists.py "
            "default = Config A (RUNOFF_OPTION=3 Schaake96, channel_option=3 diffusive "
            "wave, GWBASESWCRT=1, UDMP_OPT=0); the tool exposes no physics flags, so "
            "this is an UNCALIBRATED stock-parameter run, the same treatment the "
            "other two locations received. Cold start in July avoids the January "
            "frozen-soil crash (dt_v023); 2009-H2 is spinup and discarded; the "
            "cal/val split (cal 2010-2011, val 2012-2013) is reported for "
            "comparability only -- nothing was optimised. Obs is GRDC-Caravan "
            "`streamflow` (mm/day) converted to m3/s via area/86.4. Discharge is "
            "taken from CHRTOUT at the gauge-matched max-order feature (dt_v009 -- "
            "NOT basin-mean LDASOUT SFCRNOFF). THREE KI DEFECTS were worked around, "
            "identical to the Bengbu verifier: (D1) generate_namelists KHOUR "
            "off-by-one vs the forcing span -> the stock pair aborts in "
            "read_hydro_forcing_mpp1() one hour past the last LDASIN; fixed by "
            "generating forcing through END+1 day. (D2) SKILL.md documents "
            "extract_discharge --gauge_lat/--gauge_lon/--min_order and "
            "find_gauge_feature(); neither exists (only argmax find_outlet_feature); "
            "gauge matching done here and cross-checked. (D3) hydro.namelist "
            "hard-codes CHRTOUT_GRID=1/RTOUT_DOMAIN=1; patched off (I/O only). "
            + (" ".join(NOTES_EXTRA) if NOTES_EXTRA else "")
        )
    except Exception as e:  # noqa: BLE001
        import traceback
        log("FAILED: " + repr(e))
        log(traceback.format_exc())
        result["status"] = "failed"
        result["notes"] = f"runner exception: {e!r}"
        TOOLS_FAILED.append(f"run_and_score.py: {e!r}")

    seen = set()
    result["tools_used"] = [t for t in TOOLS_USED
                            if not (t in seen or seen.add(t))]
    result["tools_failed"] = TOOLS_FAILED
    result["ki_defects_worked_around"] = [
        "D1 generate_namelists.compute_khour() off-by-one vs forcing span -> "
        "read_hydro_forcing_mpp1() abort at the final step",
        "D2 SKILL.md documents extract_discharge --gauge_lat/--gauge_lon/--min_order "
        "and find_gauge_feature(); none exist on disk",
        "D3 hydro.namelist template hard-codes CHRTOUT_GRID=1 / RTOUT_DOMAIN=1",
    ]

    if DOMAIN_EDIT_REC:
        result["domain_edits"] = de.summary_for_result(DOMAIN_EDIT_REC)
        result["notes"] = ((result.get("notes") or "") + " " + de.summary_sentence(DOMAIN_EDIT_REC)).strip()
    out = STATE_DIR / "result.json"
    with open(out, "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    log(f"WROTE {out}")


if __name__ == "__main__":
    import argparse as _ap
    _args = de.add_cli(_ap.ArgumentParser(description="WRF-Hydro runner")).parse_args()
    EDITS = de.DomainEdits(fix=_args.fix_domain_gaps, smois_floor=_args.smois_floor,
                           tslb_floor=_args.tslb_floor, accept_unknown_history=_args.accept_unknown_domain_history, soilparm_tbl=ROOT / "model/wrf_hydro/source/trunk/NDHMS/Run/SOILPARM.TBL", log=log)
    import time as _time
    _t0 = _time.time()
    main()
    # a failed/partial run, or one without metrics, must not exit 0
    gate.exit_by_result(STATE_DIR / "result.json", _t0, key="status")
