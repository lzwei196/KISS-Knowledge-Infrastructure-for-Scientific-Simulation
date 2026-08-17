#!/usr/bin/env python3
"""
WRF-Hydro v5.2.0 standalone -- VERIFIER run #2 at LAOGUAN HE @ XIXIA (GRDC 2182250).

Fourth WRF-Hydro KI location, for the consistency check. Companions:
  * real-case : 紫荆关 Zijingguan (Juma R., Haihe, regulated arid N-China, CMFD)  -> failed
  * verify_1  : Berounka @ Beroun (Czech, humid-continental, NASA POWER)   -> Q~0, failed
  * verify_2  : THIS -- Laoguan He @ Xixia, Qinling S-slope, humid subtropical CN, CMFD

Why Laoguan He: a genuinely distinct climate from the other two -- humid
subtropical Qinling headwater of the Han/Danjiang system, moderate mountains,
3,418 km2. It lies inside the LOCAL MERIT-Hydro tiles (n30e110) and the CMFD
V2.0 window (1979-2018), so the basin can be delineated and forced entirely from
on-disk data, exactly like the Zijingguan real-case (same DEM/HWSD/CMFD path).

Gauge   : GRDC 2182250, 33.289167N 111.474444E, published catchment 3,418 km2.
          MERIT-Hydro snap upa = 3,421 km2 (0.1% of published) -> delineation is
          trustworthy; basin traced to 3,434 km2, extent 33.20-34.00N 110.83-111.83E.
Obs     : GRDC daily-discharge export file 2182250_Q_Day.Cmd.txt, `Value` column in
          m3/s directly (missing = -999). Full daily coverage 1985..1991 (1992-93
          are entirely absent, so the run stops at 1991).
Basin   : delineated here from MERIT-Hydro `dir`/`upa` (reverse-D8 trace of the
          upa-snapped gauge pixel) and polygonized -> laoguan_basin.shp. This is the
          SAME MERIT method the CWatM KI uses; the WRF-Hydro tools need a basin
          polygon and none ships for these GRDC-Asia stations (no Caravan shape).
Forcing : this basin's own CMFD V2.0 3-hourly 0.1deg -> hourly LDASIN via the KI tool
          tools/s8_forcing/cmfd_to_ldasin.py (month-by-month, cached -> resumable).
DEM     : data/dem/china_dem_90m (covers all China; no SRTM merge needed).
Physics : the KI's STOCK generate_namelists.py defaults = Config A (RUNOFF_OPTION=3
          Schaake96, channel_option=3 diffusive-wave gridded, GWBASESWCRT=1 exp
          bucket, UDMP_OPT=0, rst_typ=0). REFKDT=0.8 is already baked into
          build_soil_properties (mountain value). GW bucket params are left at the
          build_groundwater STOCK output (Coeff=1.0, Expon=3.0, Zmax=50, Zinit=10) --
          NOT tuned -- so this is an UNCALIBRATED stock-parameter run, the same
          treatment verify_1 received. (The Zijingguan real-case additionally tuned
          the GW bucket to Coeff=0.04/Zmax=120; verify_2 deliberately does not, to
          match the stock verifier convention.)

Period  : 1985-07-01 .. 1991-12-31 (July cold start avoids the Jan frozen-soil crash
          dt_v023).
          spinup      1985-07-01 .. 1985-12-31 (discarded)
          calibration 1986-01-01 .. 1988-12-31 (reported, NOT optimised on)
          validation  1989-01-01 .. 1991-12-31 (held out)
          Nothing is calibrated; the cal/val split is reported only for comparability.

KI defects worked around (same family as the other WRF-Hydro locations):
  D1 end-of-forcing off-by-one (dt_v044): WRF-Hydro reads forcing at t=0..KHOUR
     inclusive, so it needs an LDASIN file one hour past what the tool writes for
     [start,end]. Fix: generate CMFD forcing through END+1 day.
  D2 SKILL.md documents extract_discharge --gauge_lat/--gauge_lon/--min_order and a
     find_gauge_feature(); NEITHER exists on the current tool on disk (only
     find_outlet_feature()=argmax streamflow). Gauge matching is done here and
     cross-checked against that argmax.
  D3 hydro.namelist template hard-codes CHRTOUT_GRID=1 / RTOUT_DOMAIN=1; patched off
     after generation (pure I/O reduction; no physics touched).
  D4 crash-avoidance sanitation of the built DOMAIN NetCDFs (NOT calibration),
     mirroring the fixes the real-case applied at source but done here on the tool
     OUTPUTS so the KI tools are left untouched:
       - dt_v036: HWSD nodata (mu==0) on a LAND cell leaves SCT_DOM=14 (water soil
         type) -> smcmax/wlt/ref=0 -> "SMCRT fully depleted" segfault. Land cells
         with soil class 14 are reset to 6 (Loam) in geo_em BEFORE s3/s5 read it,
         and smc* floored in soil_properties.nc.
       - dt_v005: GREENFRAC==0 -> SHDFAC=0 -> bare cells reach TG=630K. GREENFRAC is
         floored to 0.01 in geo_em and SHDMAX/SHDMIN floored to 1% in wrfinput.

Resumable: DEM none needed; basin shp cached; domain skipped when all 8 files exist;
forcing cached per month; model skipped when CHRTOUT count already matches sim days;
scoring always recomputed. Final action: writes the complete verifier result object
to  KISSPATH_KI_ROOT/WRF_Hydro/detached/verify_2/result.json
"""
import os
import sys
import json
import glob
import calendar
import subprocess
import datetime as _dt
from pathlib import Path

from osgeo import gdal      # MUST precede netCDF4/numpy to avoid libstdc++ static-TLS OOM
gdal.UseExceptions()
import numpy as np
import pandas as pd
import netCDF4 as nc

ROOT = Path("KISSPATH_ROOT")
KI = ROOT / "models/WRF_Hydro/knowledge_infrastructure"
TOOLS = KI / "tools"
VALID = Path("KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect_multi_agent")
PY = "/usr/bin/python3"

sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(TOOLS / "s11_output"))
sys.path.insert(0, str(VALID))
sys.path.insert(0, str(VALID / "validators"))

STATE_DIR = ROOT / "models/WRF_Hydro/detached/verify_2"
RUN = ROOT / "outputs/laoguan_wrfhydro_verify2"
DOMAIN = RUN / "DOMAIN"
FORCING = RUN / "FORCING"

# ---- obs / gauge / basin --------------------------------------------------
OBS_TXT = ("KISSPATH_DATA/china_data/"
           "GRDC_asia_discharge_daily_20260511/2182250_Q_Day.Cmd.txt")
GAUGE_LAT, GAUGE_LON = 33.289167, 111.474444
PUBLISHED_AREA_KM2 = 3418.0
BASIN_SHP = RUN / "laoguan_basin.shp"
MERIT_DIR = ROOT / "data/merit_hydro"

# ---- global static inputs -------------------------------------------------
DEM_PATH = ROOT / "data/dem/china_dem_90m/china_dem_90m.tif"
LANDCOVER = ROOT / "data/landcover/AVHRR_1km_LANDCOVER_1981_1994.GLOBAL.tif"
HWSD_RASTER = ROOT / "data/soil/HWSD_RASTER/hwsd.bil"
HWSD_MDB = ROOT / "data/forcing/huaihe_raw/soil/HWSD.mdb"
CMFD_DIR = ROOT / "data/forcing/Data_forcing_03hr_010deg"
TBL = ROOT / "model/wrf_hydro/source/trunk/NDHMS/Run"
SOILPARM = TBL / "SOILPARM.TBL"
MPTABLE = TBL / "MPTABLE.TBL"
HYDROTBL = TBL / "HYDRO.TBL"

# ---- domain params --------------------------------------------------------
DX = 1000.0
BUFFER_CELLS = 4
AGGFACTRT = 4
STREAM_THRESHOLD = 100
CELL_AREA_KM2 = (DX / 1000.0) ** 2

# ---- period ---------------------------------------------------------------
START, END = _dt.date(1985, 7, 1), _dt.date(1991, 12, 31)
SCORE_START = "1986-01-01"                 # 1985 H2 = spinup, discarded
CAL = ("1986-01-01", "1988-12-31")
VAL = ("1989-01-01", "1991-12-31")

NPROC = 4
DOMAIN_FILES = ["geo_em.d01.nc", "wrfinput_d01.nc", "Fulldom_hires.nc",
                "soil_properties.nc", "GWBASINS.nc", "GWBUCKPARM.nc",
                "hydro2dtbl.nc", "GEOGRID_LDASOUT_Spatial_Metadata.nc"]

# MERIT D8 (ArcGIS convention, row increases south)
D8_OFFSET = {1: (0, 1), 2: (1, 1), 4: (1, 0), 8: (1, -1),
             16: (0, -1), 32: (-1, -1), 64: (-1, 0), 128: (-1, 1)}

STATE_DIR.mkdir(parents=True, exist_ok=True)
RUN.mkdir(parents=True, exist_ok=True)
LOG = STATE_DIR / "runner.log"

TOOLS_USED = []
TOOLS_FAILED = []
NOTES_EXTRA = []
SANITATION = []


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


# ------------------------------------------------------------------ MERIT delineation
def _merit_tiles(win, var):
    la0, la1, lo0, lo1 = win
    out = []
    for la in range(int(np.floor(la0 / 5) * 5), int(np.ceil(la1 / 5) * 5), 5):
        for lo in range(int(np.floor(lo0 / 5) * 5), int(np.ceil(lo1 / 5) * 5), 5):
            n = (f"{'n' if la >= 0 else 's'}{abs(la):02d}"
                 f"{'e' if lo >= 0 else 'w'}{abs(lo):03d}_{var}.tif")
            p = MERIT_DIR / n
            if p.exists():
                out.append(str(p))
    if not out:
        raise RuntimeError(f"no MERIT '{var}' tiles for {win}")
    return out


def _read_merit(var, win):
    vrt = gdal.BuildVRT("", _merit_tiles(win, var))
    gt = vrt.GetGeoTransform()
    x0 = int(np.floor((win[2] - gt[0]) / gt[1]))
    x1 = int(np.ceil((win[3] - gt[0]) / gt[1]))
    y0 = int(np.floor((win[1] - gt[3]) / gt[5]))
    y1 = int(np.ceil((win[0] - gt[3]) / gt[5]))
    x0, y0 = max(x0, 0), max(y0, 0)
    x1, y1 = min(x1, vrt.RasterXSize), min(y1, vrt.RasterYSize)
    a = vrt.ReadAsArray(x0, y0, x1 - x0, y1 - y0)
    sub_gt = (gt[0] + x0 * gt[1], gt[1], 0.0, gt[3] + y0 * gt[5], 0.0, gt[5])
    del vrt
    return a, sub_gt


def _trace_basin(dirs, oy, ox):
    ny, nx = dirs.shape
    mask = np.zeros((ny, nx), dtype=bool)
    mask[oy, ox] = True
    stack = [(oy, ox)]
    inflow = [(dy, dx, v) for v, (dy, dx) in D8_OFFSET.items()]
    while stack:
        y, x = stack.pop()
        for dy, dx, v in inflow:
            yy, xx = y - dy, x - dx
            if 0 <= yy < ny and 0 <= xx < nx and not mask[yy, xx] and dirs[yy, xx] == v:
                mask[yy, xx] = True
                stack.append((yy, xx))
    return mask


def ensure_basin_shp():
    if BASIN_SHP.exists():
        log(f"  basin shp present: {BASIN_SHP.name}")
        return
    import geopandas as gpd
    from rasterio import features
    from rasterio.transform import Affine
    from shapely.geometry import shape
    from shapely.ops import unary_union

    win = (GAUGE_LAT - 0.9, GAUGE_LAT + 0.9, GAUGE_LON - 0.9, GAUGE_LON + 0.9)
    dirs, gt = _read_merit("dir", win)
    dirs = dirs.astype(np.int16)
    upa, _ = _read_merit("upa", win)
    ny, nx = dirs.shape
    flon = gt[0] + (np.arange(nx) + 0.5) * gt[1]
    flat = gt[3] + (np.arange(ny) + 0.5) * gt[5]

    gx = int(np.argmin(np.abs(flon - GAUGE_LON)))
    gy = int(np.argmin(np.abs(flat - GAUGE_LAT)))
    w = 40
    sub = upa[gy - w:gy + w + 1, gx - w:gx + w + 1]
    dy, dx = np.unravel_index(np.nanargmax(sub), sub.shape)
    oy, ox = gy - w + dy, gx - w + dx
    upa_outlet = float(upa[oy, ox])
    log(f"  gauge ({GAUGE_LON},{GAUGE_LAT}) snapped ({flon[ox]:.4f},{flat[oy]:.4f}) "
        f"upa={upa_outlet:.0f} km2 (published {PUBLISHED_AREA_KM2})")

    basin = _trace_basin(dirs, oy, ox)
    fa = (111320.0 * abs(gt[1])) * (111320.0 * abs(gt[1]) * np.cos(np.radians(flat)))
    area_km2 = float((basin * fa[:, None]).sum() / 1e6)
    ys, xs = np.nonzero(basin)
    if ys.min() < 2 or ys.max() > ny - 3 or xs.min() < 2 or xs.max() > nx - 3:
        raise RuntimeError("basin touches MERIT window edge -- widen window")
    log(f"  traced basin {basin.sum()} px  area={area_km2:.0f} km2")

    transform = Affine(gt[1], 0, gt[0], 0, gt[5], gt[3])
    geoms = [shape(g) for g, v in features.shapes(
        basin.astype(np.uint8), mask=basin, transform=transform) if v == 1]
    poly = unary_union(geoms)
    gdf = gpd.GeoDataFrame({"gauge_id": ["GRDC_2182250"],
                            "area_km2": [round(area_km2, 1)]},
                           geometry=[poly], crs="EPSG:4326")
    gdf.to_file(str(BASIN_SHP))
    NOTES_EXTRA.append(
        f"MERIT-snapped upa={upa_outlet:.0f} km2 vs published {PUBLISHED_AREA_KM2}; "
        f"traced/polygonized area {area_km2:.0f} km2")
    log(f"  wrote {BASIN_SHP.name}")


# ------------------------------------------------------------------ crash-avoidance
def sanitize_geo():
    """dt_v036 + dt_v005 on geo_em BEFORE s3/s5 read it (crash avoidance, not calib)."""
    p = DOMAIN / "geo_em.d01.nc"
    ds = nc.Dataset(str(p), "a")
    land = np.asarray(ds["LANDMASK"][0]) > 0.5
    sct = np.asarray(ds["SCT_DOM"][0])
    scb = np.asarray(ds["SCB_DOM"][0])
    bad = land & (sct == 14)
    nbad = int(bad.sum())
    if nbad:
        ds["SCT_DOM"][0][bad] = 6.0
        top = np.asarray(ds["SOILCTOP"][0]); top[:, bad] = 0.0; top[5, bad] = 1.0
        ds["SOILCTOP"][0] = top
    badb = land & (scb == 14)
    if int(badb.sum()):
        ds["SCB_DOM"][0][badb] = 6.0
        bot = np.asarray(ds["SOILCBOT"][0]); bot[:, badb] = 0.0; bot[5, badb] = 1.0
        ds["SOILCBOT"][0] = bot
    gf = np.asarray(ds["GREENFRAC"][0])
    nlow = int((gf < 0.01).sum())
    if nlow:
        gf = np.maximum(gf, 0.01)
        ds["GREENFRAC"][0] = gf
    ds.close()
    if nbad or nlow:
        SANITATION.append(f"geo_em: {nbad} land cells water-soil->Loam(dt_v036), "
                          f"{nlow} GREENFRAC floored->0.01(dt_v005)")
    log(f"  sanitize geo_em: water-soil land cells={nbad}, GREENFRAC<0.01={nlow}")


def sanitize_wrfinput():
    p = DOMAIN / "wrfinput_d01.nc"
    ds = nc.Dataset(str(p), "a")
    for v, floor in [("SHDMAX", 1.0), ("SHDMIN", 1.0)]:
        if v in ds.variables:
            a = np.asarray(ds[v][0]); ds[v][0] = np.maximum(a, floor)
    if "SMOIS" in ds.variables:
        sm = np.asarray(ds["SMOIS"][0]); ds["SMOIS"][0] = np.where(sm <= 0.02, 0.10, sm)
    ds.close()
    log("  sanitize wrfinput: SHDMAX/SHDMIN>=1%, SMOIS>0.02")


def sanitize_soil():
    p = DOMAIN / "soil_properties.nc"
    ds = nc.Dataset(str(p), "a")
    for v, floor in [("smcmax", 0.434), ("smcwlt", 0.066), ("smcref", 0.329)]:
        if v in ds.variables:
            a = np.asarray(ds[v][:]); nfix = int((a <= 0).sum())
            if nfix:
                a[a <= 0] = floor; ds[v][:] = a
                SANITATION.append(f"soil_properties {v}: {nfix} nonpos->{floor}")
    ds.close()
    log("  sanitize soil_properties: smc* floored")


# ------------------------------------------------------------------ stages 1-6
def build_domain():
    DOMAIN.mkdir(parents=True, exist_ok=True)
    ddef = RUN / "domain_def.json"

    if not ddef.exists():
        sh([PY, TOOLS / "s1_domain/define_lambert_domain.py",
            "--basin_shp", BASIN_SHP, "--dx", DX,
            "--buffer_cells", BUFFER_CELLS, "--output", ddef])
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

    geo = DOMAIN / "geo_em.d01.nc"
    sh([PY, TOOLS / "s2_geo_em/build_geo_em.py",
        "--domain_json", ddef, "--dem_path", DEM_PATH,
        "--landcover_path", LANDCOVER, "--hwsd_raster", HWSD_RASTER,
        "--hwsd_mdb", HWSD_MDB, "--basin_shp", BASIN_SHP,
        "--output", geo], timeout=7200)
    TOOLS_USED.append("s2_geo_em/build_geo_em.py")
    sanitize_geo()                       # dt_v036 + dt_v005 before s3/s5 read geo

    sh([PY, TOOLS / "s3_wrfinput/build_wrfinput.py",
        "--geo_em", geo, "--output_path", DOMAIN / "wrfinput_d01.nc",
        "--start_month", START.month, "--soilparm_tbl", SOILPARM])
    TOOLS_USED.append("s3_wrfinput/build_wrfinput.py")
    sanitize_wrfinput()

    sh([PY, TOOLS / "s4_fulldom/build_fulldom_hires.py",
        "--geo_em", geo, "--domain_json", ddef, "--dem_path", DEM_PATH,
        "--basin_shp", BASIN_SHP, "--output_path", DOMAIN / "Fulldom_hires.nc",
        "--aggfactrt", AGGFACTRT, "--stream_threshold", STREAM_THRESHOLD],
       timeout=7200)
    TOOLS_USED.append("s4_fulldom/build_fulldom_hires.py")

    sh([PY, TOOLS / "s5_soil_properties/build_soil_properties.py",
        "--geo_em", geo, "--output_path", DOMAIN / "soil_properties.nc",
        "--soilparm_tbl", SOILPARM, "--mptable_tbl", MPTABLE])
    TOOLS_USED.append("s5_soil_properties/build_soil_properties.py")
    sanitize_soil()

    sh([PY, TOOLS / "s6_groundwater/build_groundwater.py",
        "--geo_em", geo, "--domain_json", ddef, "--basin_shp", BASIN_SHP,
        "--output_dir", DOMAIN, "--hydro_tbl", HYDROTBL])
    TOOLS_USED.append("s6_groundwater/build_groundwater.py")

    missing = [f for f in DOMAIN_FILES if not (DOMAIN / f).exists()]
    if missing:
        raise RuntimeError(f"domain rebuild left files missing: {missing}")
    log("  domain: rebuilt all 8 files")


# ------------------------------------------------------------------ stage 8
def build_forcing():
    FORCING.mkdir(parents=True, exist_ok=True)
    force_end = END + _dt.timedelta(days=1)     # dt_v044: need hour-KHOUR file
    for y, m in month_iter(START, force_end):
        ndays = calendar.monthrange(y, m)[1]
        m_start = max(_dt.date(y, m, 1), START)
        m_end = min(_dt.date(y, m, ndays), force_end)
        expected = (m_end - m_start).days * 24 + 24
        have = len(glob.glob(str(FORCING / f"{y}{m:02d}*.LDASIN_DOMAIN1")))
        if have >= expected:
            continue
        log(f"  forcing {y}-{m:02d}: have {have}, expect {expected} -> generating")
        sh([PY, TOOLS / "s8_forcing/cmfd_to_ldasin.py", "--cmfd_dir", CMFD_DIR,
            "--geo_em", DOMAIN / "geo_em.d01.nc",
            "--domain_json", RUN / "domain_def.json", "--output_dir", FORCING,
            "--start_date", m_start.isoformat(), "--end_date", m_end.isoformat()],
           timeout=100000)
    TOOLS_USED.append("s8_forcing/cmfd_to_ldasin.py")
    force_end_file = FORCING / f"{force_end:%Y%m%d}00.LDASIN_DOMAIN1"
    n = len(glob.glob(str(FORCING / "*.LDASIN_DOMAIN1")))
    if not force_end_file.exists():
        raise RuntimeError(f"hour-KHOUR forcing {force_end_file.name} missing (dt_v044)")
    log(f"  FORCING total: {n} LDASIN files; hour-KHOUR present")
    return n


# ------------------------------------------------------------------ stage 9+10
def expected_days():
    return (END - START).days + 1


def patch_hydro_namelist():
    p = RUN / "hydro.namelist"
    txt = p.read_text()
    txt = txt.replace("CHRTOUT_GRID   = 1", "CHRTOUT_GRID   = 0")
    txt = txt.replace("RTOUT_DOMAIN   = 1", "RTOUT_DOMAIN   = 0")
    p.write_text(txt)
    log("  hydro.namelist: CHRTOUT_GRID=0, RTOUT_DOMAIN=0")


def run_model():
    n_chrt = len(glob.glob(str(RUN / "*.CHRTOUT_DOMAIN1")))
    need = expected_days()
    if n_chrt >= need * 0.98:
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

    sh([PY, TOOLS / "s9_namelists/generate_namelists.py",
        "--domain_dir", DOMAIN, "--forcing_dir", FORCING, "--output_dir", RUN,
        "--start_date", START.isoformat(), "--end_date", END.isoformat(),
        "--nproc", NPROC, "--output_timestep", 86400])
    TOOLS_USED.append("s9_namelists/generate_namelists.py")
    patch_hydro_namelist()

    fl = RUN / "FORCING"
    if not fl.exists():
        os.symlink(str(FORCING), str(fl))

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
            f"gauge-matched outlet idx={idx} ({info['dist_to_gauge_km']} km) differs "
            f"from KI argmax idx={ki_idx} ({info['ki_argmax_dist_km']} km)")
    return idx, info


def load_obs_m3s():
    """Parse the GRDC daily-discharge export (';'-delimited, -999 = missing, m3/s)."""
    dates, vals = [], []
    with open(OBS_TXT, "r", encoding="latin-1") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("YYYY"):
                continue
            parts = line.split(";")
            if len(parts) < 3:
                continue
            try:
                d = pd.Timestamp(parts[0].strip())
                v = float(parts[2].strip())
            except ValueError:
                continue
            if v <= -900:
                continue
            dates.append(d)
            vals.append(v)
    s = pd.Series(vals, index=pd.DatetimeIndex(dates).normalize(), name="Q_obs")
    s = s[s >= 0]
    return s


def extract_and_score(idx):
    from extract_discharge import extract_daily_discharge
    from ki_tools_common.metrics import all_metrics
    try:
        from standard_calval import compute_calval_metrics
    except ImportError:
        from validators.standard_calval import compute_calval_metrics

    sim = extract_daily_discharge(RUN, idx)
    sim.to_csv(STATE_DIR / "discharge_sim_full.csv")
    sim.index = pd.to_datetime(sim.index).normalize()

    obs = load_obs_m3s()
    merged = pd.concat([obs, sim["Q_sim"]], axis=1, join="inner").dropna()
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
    log(f"  water balance: {int(mask.sum())} basin LSM cells (~{area_km2:.0f} km2)")

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
        soilm = np.ma.filled(ds["SOIL_M"][0].astype("f8"), np.nan)
        sneqv = np.ma.filled(ds["SNEQV"][0].astype("f8"), np.nan)
        ds.close()
        dz = np.array([0.10, 0.30, 0.60, 1.00])
        col = np.nansum(soilm * dz[None, :, None], axis=1) * 1000.0
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
        "this_location": ("GRDC Asia-Region Daily Discharge Export "
                          "(250 stations, 2026-05-11 download)"),
        "obs_source": ("GRDC Asia-Region Daily Discharge Export "
                       "(250 stations, 2026-05-11 download)"),
        "status": "failed",
        "tools_used": [],
        "tools_failed": [],
        "metrics": {"nse": None, "kge": None, "pbias": None, "r": None,
                    "period": None},
        "water_balance": {"status": "N/A", "residual_pct": None},
        "notes": "",
    }
    try:
        log("=== basin delineation (MERIT-Hydro) ===")
        ensure_basin_shp()

        log("=== stage 1-6: domain ===")
        build_domain()

        log("=== stage 8: CMFD forcing ===")
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
                "period": (f"{merged.index.min():%Y-%m-%d}.."
                           f"{merged.index.max():%Y-%m-%d} "
                           f"({len(merged)} paired daily values; "
                           f"1985-H2 discarded as spinup)"),
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
                "sim_mean_m3s": round(float(merged["Q_sim"].mean()), 3),
                "obs_mean_m3s": round(float(merged["Q_obs"].mean()), 3),
            }
            result["status"] = "completed"
        result["outlet"] = outlet
        result["n_ldasin"] = nforce
        result["published_area_km2"] = PUBLISHED_AREA_KM2
        result["gauge"] = {"grdc_no": 2182250, "river": "LAOGUAN HE",
                           "station": "XIXIA", "country": "CN",
                           "lat": GAUGE_LAT, "lon": GAUGE_LON}
        result["domain_rebuilt"] = True
        result["sanitation"] = SANITATION

        result["notes"] = (
            "WRF-Hydro v5.2.0 standalone (NoahMP + gridded diffusive-wave routing) "
            "verifier #2 at Laoguan He @ Xixia (GRDC 2182250, Qinling south slope, "
            "Han/Danjiang headwater, humid subtropical China, published 3,418 km2) -- "
            "the fourth KI location, a THIRD distinct climate complementing the "
            "regulated-arid N-China real-case (Zijingguan) and the humid-continental "
            "verify_1 (Berounka, Czech). Basin delineated from LOCAL MERIT-Hydro "
            "dir/upa (upa-snap = 3,421 km2 vs published 3,418; reverse-D8 trace "
            "polygonized to laoguan_basin.shp), the same MERIT method the CWatM KI "
            "uses, because no Caravan polygon ships for GRDC-Asia stations. DOMAIN "
            "built from scratch by KI tools s1-s6 @1 km (buffer 4) on china_dem_90m + "
            "HWSD; forcing is this basin's own CMFD V2.0 3hr->hourly LDASIN via "
            "cmfd_to_ldasin.py. Physics is the KI's STOCK generate_namelists.py "
            "default = Config A (RUNOFF_OPTION=3 Schaake96, channel_option=3 diffusive "
            "wave, GWBASESWCRT=1, UDMP_OPT=0, rst_typ=0); REFKDT=0.8 is baked into "
            "build_soil_properties and the GW bucket is left at the build_groundwater "
            "STOCK output (Coeff=1.0/Expon=3.0/Zmax=50/Zinit=10) -- NOT tuned -- so "
            "this is an UNCALIBRATED stock-parameter run, matching the verify_1 "
            "convention (the Zijingguan real-case additionally tuned the GW bucket; "
            "verify_2 does not). Cold start 1985-07 avoids the Jan frozen-soil crash "
            "(dt_v023); 1985-H2 spinup discarded; cal 1986-1988, val 1989-1991 (obs "
            "1992-93 absent) reported for comparability only -- nothing optimised. Obs "
            "is the GRDC daily export `Value` (m3/s directly, -999=missing). Discharge "
            "from CHRTOUT at the gauge-matched max-order feature (dt_v009 -- NOT "
            "basin-mean LDASOUT SFCRNOFF). FOUR KI defects worked around: D1 "
            "generate_namelists KHOUR off-by-one vs forcing span (forcing generated "
            "through END+1 day); D2 SKILL.md documents extract_discharge "
            "--gauge_lat/--min_order + find_gauge_feature(), NEITHER on disk (only "
            "argmax find_outlet_feature); D3 hydro.namelist hard-codes "
            "CHRTOUT_GRID=1/RTOUT_DOMAIN=1 (patched off, I/O only); D4 crash-avoidance "
            "sanitation of the built DOMAIN NetCDFs (dt_v036 water-soil-type on land "
            "-> Loam; dt_v005 GREENFRAC/SHDMAX floor), applied to tool OUTPUTS not the "
            "tools. " + (" ".join(NOTES_EXTRA) if NOTES_EXTRA else "")
        )
    except Exception as e:  # noqa: BLE001
        import traceback
        log("FAILED: " + repr(e))
        log(traceback.format_exc())
        result["status"] = "failed"
        result["notes"] = f"runner exception: {e!r}"
        TOOLS_FAILED.append(f"run_and_score_verify2.py: {e!r}")

    seen = set()
    result["tools_used"] = [t for t in TOOLS_USED
                            if not (t in seen or seen.add(t))]
    result["tools_failed"] = TOOLS_FAILED
    result["ki_defects_worked_around"] = [
        "D1 generate_namelists KHOUR off-by-one vs forcing span (dt_v044)",
        "D2 SKILL.md documents extract_discharge --gauge_lat/--min_order and "
        "find_gauge_feature(); neither exists on disk (only argmax find_outlet_feature)",
        "D3 hydro.namelist template hard-codes CHRTOUT_GRID=1 / RTOUT_DOMAIN=1",
        "D4 dt_v036 water-soil-type on land cells + dt_v005 GREENFRAC=0 -> "
        "crash-avoidance sanitation of the DOMAIN NetCDF outputs",
    ]

    out = STATE_DIR / "result.json"
    with open(out, "w") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
    log(f"WROTE {out}  status={result['status']}")


if __name__ == "__main__":
    main()
