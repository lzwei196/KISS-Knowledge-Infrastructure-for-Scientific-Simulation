#!/usr/bin/env python3
"""
SWAT+ VERIFIER (verify_2) — XIXIA (西峡), Laoguan He (老灌河), GRDC 2182250.

Third location for the SWAT+ consistency check.
  Real case : Zijingguan (Juma / Haihe,   ~1,931 km2, semi-arid Taihang front)
  verify_1  : Wangjiaba  (Huai,          ~30,630 km2, humid subtropical plain)
  verify_2  : Xixia      (Laoguan/Han/Yangtze, 3,418 km2, Qinling mountains)  <- HERE

Xixia is drawn from the assigned obs source: the GRDC Asia-Region Daily
Discharge Export (250 stations, downloaded 2026-05-11). It was selected from
the 38 Chinese stations in that export by three hard criteria, all verified
on disk before this script was written:

  1. MERIT Hydro tiles must cover the WHOLE upstream basin. Only 90-100E x
     30-40N and 110-115E/115-120E x 30-35N are on disk. That removes MINHE
     (102.8E, no n35e100 tile) and most of the export.
  2. The published drainage area must be independently reproducible from MERIT
     `upa`. The GRDC coordinate itself reads upa = 0.0 km2 at EVERY candidate
     station -- the published lat/lon is systematically off-channel -- so the
     outlet is the nearby channel cell whose upstream area matches the
     published one. At Xixia that cell carries 3,420.4 km2 vs the published
     3,418.0 km2 (+0.07%), 3.3 km from the GRDC coordinate. ZHIMENDA fails
     this test outright (best cell within 0.05 deg carries 2,557 km2 against a
     published 137,704 -- the GRDC coordinate is nowhere near the Tongtian He
     main stem); GAOLIN fails too (61.9 vs 552).
  3. A long, near-complete daily record. Xixia has 7,305 daily values
     (1977-01-01..1996-12-31); only 1992 and 1993 are wholly missing (-999).

Xixia is also the most INDEPENDENT basin available: the Laoguan He drains to
the Dan -> Han -> Yangtze, so it shares no river system with either the Haihe
real case or the Huai verifier, and its area sits between theirs. (CHANGTAIGUAN
also passes the area test but lies on the Huai directly upstream of Wangjiaba,
so it would not be an independent check.)

Chain -- the SAME KI tools as the real case, run from scratch:

    s1/delineate_watershed.py       DEM -> watershed.shp   (area-checked)
    s2/generate_hru_from_global.py  HRUs + soils.sol + full TxtInOut
    s3/prepare_weather_files.py     CMFD 3-hourly -> .pcp/.tmp/.slr/.hmd/.wnd
    s3/validate_weather_data.py     QC (Tmax==Tmin trap, dt_043)
    s3/generate_weather_stations.py weather-sta.cli + weather-wgn.cli
    s7/configure_time_sim.py        1977-1996, 3 warmup years
    s7/configure_print_prt.py       channel daily, basin_wb + aquifer yearly
    s7/validate_txtinout.py         cross-check file.cio
    s6/generate_calibration_file.py calibration.cal (+ structural aquifer.aqu)
    s8/run_swatplus.py              rev59 binary
    s9/extract_discharge.py         topology outlet, ha-m/day -> m3/s

TWO OUT-OF-TOOL REPAIRS, mirroring the real case and verify_1 EXACTLY
---------------------------------------------------------------------
Both defects were re-confirmed LIVE before this script was written; the tool
md5s are byte-identical to the ones verify_1 recorded, i.e. neither fix ever
landed in the KI:
    s2/generate_hru_from_global.py  e84bec4046490347e0c250577e86bf63
    s6/generate_calibration_file.py 80ebc8a1fa0d2331a36b1e24cd21ea06

  (1) aquifer.aqu -- s2's write_aquifer_files() fabricates magnitudes and
      MIS-NAMES two columns. Ground truth is the shipped SWAT+ Editor v2.1.0
      demo (demo_lrew/swatplus_rev60_demo/aquifer.aqu):
          gw_flo 2500.0 -> 0.05 | dep_bot('gw_dp') 1000.0 m -> 10.0
          dep_wt('gw_ht') 1.0 -> 3.0 | flo_min 1000.0 -> 3.0
          revap_min 750.0 -> 5.0 | cols 7/8 ptl_n/ptl_p -> carbon 0.5 / flo_dist 50.0
      dep_bot 1000 m x spec_yld 0.05 is a 50,000 mm aquifer that never yields
      return flow. Still emitted by the live tool (see md5 above).

  (2) msk_co1/msk_co2/msk_x -- every bsn-object name is a calibration.cal no-op
      in rev59, so Muskingum routing is only reachable by editing parameters.bsn.
      Live s6 EXITS 1 ("Unknown parameter: msk_co1") and writes NOTHING at all --
      it takes the whole call down, so a trial naming msk would silently lose
      its cn2/rchg_dp too. Routed around s6 into parameters.bsn directly
      (fixed-width round-trip asserted).

Applying them here is what makes the three basins comparable; NOT applying them
would score a repaired pipeline at Zijingguan against a broken one here. Both
are recorded in tools_failed with the live md5s.

Calibration mirrors the real case exactly: run UNCALIBRATED, read the outlet
PBIAS sign, then greedily search one parameter group at a time, SELECTING ON
KGE of the calibration period (SKILL.md: NSE <= r^2, so a greedy NSE search is
near-degenerate when r is the binding constraint). 1980-1987 selects; 1988-1996
is held out and never optimized on. Stages sweep only names the live binary
actually APPLIES (dt_045): cn2, esco, alpha, flo_min via calibration.cal;
rchg_dp structurally via aquifer.aqu; msk_* structurally via parameters.bsn.

RESUMABLE at every stage: the DEM clip, watershed.shp, TxtInOut, the weather
deck, and each calibration trial's metrics (trials.json, guarded by a
fingerprint over the tools + topology) are cached and skipped on relaunch. A
result.json carrying this run's signature short-circuits the whole script.
"""
import sys, os, json, shutil, subprocess, time, hashlib, math, traceback
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("KISSPATH_ROOT")
KI = ROOT / "models/SWAT+/knowledge_infrastructure"
TOOLS = KI / "tools"
WORK = ROOT / "models/SWAT+/xixia_v1"
DELIN = WORK / "delin"
TXTINOUT = WORK / "TxtInOut"
WEATHER = WORK / "weather"
PRISTINE = WORK / "pristine"
BINARY = ROOT / "models/SWAT_Plus/test_rev59/swatplus_rev59"
CMFD = ROOT / "data/forcing/Data_forcing_03hr_010deg"

MERIT = ROOT / "data/merit_hydro"
MERIT_TILE = "n30e110"                      # 110-115E, 30-35N; contains the whole basin
DEM = WORK / "elv_clip.tif"                 # MERIT Hydro elevation, clipped
DIR_TIF = WORK / "dir_clip.tif"             # MERIT Hydro conditioned D8 flow direction

# GRDC Asia-Region Daily Discharge Export (250 stations, 2026-05-11 download).
OBS = ROOT / ("data/china_data/GRDC_asia_discharge_daily_20260511/"
              "2182250_Q_Day.Cmd.txt")
GRDC_NO = "2182250"

OUTDIR = ROOT / "models/SWAT+/detached/verify_2"
RESULT = OUTDIR / "result.json"
TRIALS = OUTDIR / "trials.json"

# Xixia gauge. The GRDC coordinate (33.289167N, 111.474444E) reads upa = 0.0 km2
# -- it is off-channel. The outlet is the MERIT `upa` cell whose upstream area
# matches the published 3,418 km2: 3,420.4 km2 (+0.07%), 3.3 km to the SSW.
OUTLET_LAT, OUTLET_LON = 33.26000, 111.47917
GRDC_LAT, GRDC_LON = 33.289167, 111.474444
PUBLISHED_AREA_KM2 = 3418.0

# Basin traced through MERIT `dir` spans 110.826-111.830E, 33.195-33.995N.
# Clip with ~0.07 deg margin; stays well inside the n30e110 tile.
CLIP_BBOX = (110.75, 33.13, 111.90, 34.07)   # (lon_w, lat_s, lon_e, lat_n)

# Obs record 1977-01-01..1996-12-31 (1992+1993 wholly missing). CMFD V0200
# covers 1951-01..2024-12, so the whole record is forced.
SIM_START, SIM_END = "1977-01-01", "1996-12-31"
WARMUP_YEARS = 3                        # 1977-1979 discarded
CAL = ("1980-01-01", "1987-12-31")
VAL = ("1988-01-01", "1996-12-31")      # held out; never optimized on
N_SUBBASINS = 8
STREAM_THRESHOLD_KM2 = 25.0             # scaled to 3,418 km2 (as at Zijingguan)
SNAP_DIST_DEG = 0.01

sys.path.insert(0, str(TOOLS / "s9"))
sys.path.insert(0, "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect_multi_agent")
sys.path.insert(0, "KISSPATH_INTERNAL_NOT_SHIPPED")

from extract_discharge import find_channel_file, parse_channel_day        # noqa: E402
from ki_tools_common.metrics import all_metrics                           # noqa: E402
from ki_tools_common.validation import validate_water_balance             # noqa: E402
from validators.standard_calval import compute_calval_metrics             # noqa: E402

PY = sys.executable
LOG = []

RUN_SIGNATURE = (f"xixia_v1|grdc{GRDC_NO}|from_scratch|{SIM_START}..{SIM_END}"
                 f"|cal={CAL[0]}..{CAL[1]}|sel=KGE_cal")

# Structural files s6 edits IN PLACE. Restored from PRISTINE before every trial,
# otherwise a trial that omits rchg_dp silently inherits the last value tried.
STRUCT_FILES = ("aquifer.aqu", "hydrology.hyd", "soils.sol", "topography.hyd",
                "parameters.bsn")

# bsn-object names: calibration.cal no-ops in rev59, and live s6 exits 1 on them.
BSN_NAMES = ("msk_co1", "msk_co2", "msk_x")

# Ground-truth aquifer row (SWAT+ Editor v2.1.0 demo). Values s2 fabricates.
AQU_HDR = ("      id  name                init        gw_flo       dep_bot"
           "        dep_wt         no3_n         sol_p        carbon      flo_dist"
           "        bf_max      alpha_bf         revap       rchg_dp      spec_yld"
           "       hl_no3n       flo_min     revap_min  ")
AQU_VALS = (0.05, 10.0, 3.0, 0.0, 0.0, 0.5, 50.0, 1.0, 0.05, 0.02, 0.05, 0.05,
            0.0, 3.0, 5.0)

TOOLS_FAILED = []


def log(msg):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    LOG.append(msg)


def md5(p):
    return hashlib.md5(Path(p).read_bytes()).hexdigest()


def tool(script, *args, cwd=None, timeout=172800):
    cmd = [PY, str(TOOLS / script)] + [str(a) for a in args]
    log(f"TOOL {script} {' '.join(str(a)[:60] for a in args)}")
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=timeout)
    if r.returncode != 0:
        log(r.stdout[-1500:])
        log(r.stderr[-1500:])
        raise RuntimeError(f"{script} exited {r.returncode}")
    return r.stdout


# ------------------------------------------------------------------- obs (GRDC)
def load_obs_grdc(path):
    """Parse a GRDC `*_Q_Day.Cmd.txt` export -> DataFrame[Q_obs], m3/s.

    Format: '#'-commented header, then 'YYYY-MM-DD;hh:mm; Value', ';'-delimited,
    missing = -999.000. The KI's extract_discharge.load_obs() reads the
    HydroCraft tab format ('dates'/'Q' columns) and cannot read this; that is a
    data-format difference, not a tool defect, so it is handled here rather than
    reported in tools_failed.
    """
    rows = []
    with open(path, encoding="latin-1") as fh:
        for line in fh:
            if line.startswith("#") or line.startswith("YYYY"):
                continue
            p = line.strip().split(";")
            if len(p) < 3:
                continue
            try:
                rows.append((pd.Timestamp(p[0]), float(p[2])))
            except ValueError:
                continue
    df = pd.DataFrame(rows, columns=["date", "Q_obs"]).set_index("date")
    n_raw = len(df)
    df.loc[df["Q_obs"] <= -999.0, "Q_obs"] = np.nan
    df = df.dropna()
    log(f"obs GRDC {GRDC_NO}: {n_raw} rows, {n_raw-len(df)} missing -> {len(df)} valid "
        f"({df.index.min().date()}..{df.index.max().date()}), "
        f"mean {df['Q_obs'].mean():.2f} m3/s")
    return df


# --------------------------------------------------------------------- DEM clip
def clip_merit():
    """Clip MERIT elv + dir to the basin bbox (resumable).

    The window MUST be snapped to integer pixel offsets before it is used. On
    this bbox `from_bounds` yields col_off=900.4999.., row_off=1115.5: `read()`
    rounds those to whole pixels but `window_transform()` does NOT, so the clip
    would be georeferenced half a pixel off its own data. Nothing errors — but
    rowcol(outlet) then lands on the neighbouring HILLSLOPE cell (dir 32 rather
    than the true dir 4), the upstream trace terminates after one cell, and the
    basin silently comes out as 0 km2. The same shifted grid would have gone to
    s1/delineate_watershed.py. Round once, use the identical window for both.
    """
    import rasterio
    from rasterio.windows import from_bounds

    if DEM.exists() and DIR_TIF.exists():
        log("[resume] elv_clip.tif + dir_clip.tif present -> skip clip")
        return
    WORK.mkdir(parents=True, exist_ok=True)
    ref = {}
    for var, dst in (("elv", DEM), ("dir", DIR_TIF)):
        src_p = MERIT / f"{MERIT_TILE}_{var}.tif"
        assert src_p.exists(), f"missing MERIT tile {src_p}"
        with rasterio.open(src_p) as r:
            win = (from_bounds(*CLIP_BBOX, transform=r.transform)
                   .round_offsets(op="floor").round_lengths(op="ceil"))
            data = r.read(1, window=win)
            prof = r.profile
            prof.update(height=data.shape[0], width=data.shape[1],
                        transform=r.window_transform(win), compress="deflate")
            # full-tile truth at the outlet, to prove the clip stayed aligned
            fr, fc = rasterio.transform.rowcol(r.transform, OUTLET_LON, OUTLET_LAT)
            ref[var] = r.read(1)[fr, fc]
        with rasterio.open(dst, "w", **prof) as o:
            o.write(data, 1)

        # read-back: the clip must resolve the outlet to the SAME cell value
        with rasterio.open(dst) as c:
            cr, cc = rasterio.transform.rowcol(c.transform, OUTLET_LON, OUTLET_LAT)
            assert 0 <= cr < c.height and 0 <= cc < c.width, \
                f"{dst.name}: outlet falls outside the clip"
            got = c.read(1)[cr, cc]
            assert got == ref[var], (
                f"{dst.name} MISALIGNED: {var} at the outlet reads {got}, "
                f"full tile reads {ref[var]} — the clip transform does not match its data")
        log(f"clipped {src_p.name} -> {dst.name} {data.shape}, "
            f"{var}@outlet={got} (matches full tile)")


# ------------------------------------------------------------------ S1 basin
def merit_watershed(shp_path):
    """Trace the basin upstream of the outlet through MERIT Hydro's D8 `dir`.

    MERIT `dir` is the hydrologically-CONDITIONED flow direction shipped with the
    DEM; a raw breach/fill + D8 pass over the bare DEM can leak across divides
    (dt_008). Same fallback verify_1 used on the Huai plain.
    """
    import rasterio
    from rasterio import features
    import geopandas as gpd
    from shapely.geometry import shape
    from shapely.ops import unary_union

    with rasterio.open(DIR_TIF) as r:
        d = r.read(1)
        tr = r.transform
    H, W = d.shape
    dy = {1: 0, 2: 1, 4: 1, 8: 1, 16: 0, 32: -1, 64: -1, 128: -1}
    dx = {1: 1, 2: 1, 4: 0, 8: -1, 16: -1, 32: -1, 64: 0, 128: 1}
    ds = np.full(H * W, -1, np.int64)
    idx = np.arange(H * W, dtype=np.int64)
    yy, xx, flat = idx // W, idx % W, d.ravel()
    for c in (1, 2, 4, 8, 16, 32, 64, 128):
        m = flat == c
        ny, nx = yy[m] + dy[c], xx[m] + dx[c]
        ok = (ny >= 0) & (ny < H) & (nx >= 0) & (nx < W)
        ds[idx[m][ok]] = ny[ok] * W + nx[ok]

    oy, ox = rasterio.transform.rowcol(tr, OUTLET_LON, OUTLET_LAT)
    out = oy * W + ox
    valid = ds >= 0
    o = np.argsort(ds[valid], kind="stable")
    dst_s, src_s = ds[valid][o], idx[valid][o]
    ar = np.arange(H * W)
    starts = np.searchsorted(dst_s, ar, "left")
    ends = np.searchsorted(dst_s, ar, "right")
    mask = np.zeros(H * W, bool)
    stack = [out]
    mask[out] = True
    while stack:
        c = stack.pop()
        for u in src_s[starts[c]:ends[c]]:
            if not mask[u]:
                mask[u] = True
                stack.append(u)
    m2 = mask.reshape(H, W)

    n_cells = int(m2.sum())
    log(f"MERIT-dir upstream trace: {n_cells} cells from outlet px ({oy},{ox}) dir={d[oy,ox]}")
    # Fail closed. A half-pixel grid shift puts the outlet on a hillslope and the
    # trace terminates immediately; simplify() then collapses the 1-cell polygon
    # and the basin reports 0 km2 with no error anywhere. Never let that through.
    assert n_cells > 1000, (
        f"upstream trace found only {n_cells} cells — the outlet "
        f"({OUTLET_LAT},{OUTLET_LON}) is not on a channel in {DIR_TIF.name}")

    polys = [shape(g) for g, v in features.shapes(m2.astype("uint8"), mask=m2,
                                                  transform=tr) if v == 1]
    geom = unary_union(polys).buffer(0).simplify(0.0025).buffer(0)
    gdf = gpd.GeoDataFrame({"id": [1]}, geometry=[geom], crs="EPSG:4326")
    gdf.to_file(str(shp_path))
    poly_area = float(gdf.to_crs("EPSG:6933").area.sum() / 1e6)
    err = (poly_area - PUBLISHED_AREA_KM2) / PUBLISHED_AREA_KM2
    log(f"MERIT-dir watershed: {poly_area:.0f} km2 (published {PUBLISHED_AREA_KM2:.0f}, "
        f"{err*100:+.1f}%)")
    assert abs(err) <= 0.10, (
        f"traced basin {poly_area:.0f} km2 is {err*100:+.1f}% off the published "
        f"{PUBLISHED_AREA_KM2:.0f} km2 — refusing to build a deck on the wrong basin")
    return poly_area


def shp_area(shp):
    import geopandas as gpd
    return float(gpd.read_file(str(shp)).to_crs("EPSG:6933").area.sum() / 1e6)


def build_basin():
    shp = DELIN / "watershed.shp"
    if shp.exists():
        a = shp_area(shp)
        log(f"[resume] watershed.shp present ({a:.0f} km2) -> skip S1")
        return shp, a

    DELIN.mkdir(parents=True, exist_ok=True)
    s1_area = None
    try:
        out = tool("s1/delineate_watershed.py", DEM, OUTLET_LAT, OUTLET_LON,
                   DELIN, STREAM_THRESHOLD_KM2, SNAP_DIST_DEG)
        rep = json.loads(out[out.find("{"):out.rfind("}") + 1])
        s1_area = rep.get("delineated_area_km2")
        log(f"S1 delineated_area_km2 = {s1_area}")
    except Exception as e:
        log(f"S1 delineate_watershed.py FAILED: {e}")

    err = abs(s1_area - PUBLISHED_AREA_KM2) / PUBLISHED_AREA_KM2 if s1_area else None
    if err is not None and err <= 0.10 and shp.exists():
        log(f"S1 area within {err*100:.1f}% of published -> using its watershed.shp")
        return shp, shp_area(shp)

    detail = (f"delineated {s1_area:.0f} km2 vs published {PUBLISHED_AREA_KM2:.0f} "
              f"({err*100:+.1f}%)" if s1_area else "produced no usable watershed")
    TOOLS_FAILED.append(
        f"s1/delineate_watershed.py: {detail}. Fell back to tracing MERIT Hydro's "
        f"hydrologically-CONDITIONED D8 `dir` grid from the area-matched outlet cell. "
        f"The KI has no tool for this; s1 should accept a conditioned flow-direction "
        f"raster instead of always re-deriving one from raw elevation (dt_008).")
    for ext in (".shp", ".shx", ".dbf", ".prj", ".cpg"):
        p = shp.with_suffix(ext)
        if p.exists():
            p.unlink()
    return shp, merit_watershed(shp)


# --------------------------------------------------------------------- S2 HRU
def build_txtinout(basin_shp):
    if (TXTINOUT / "hru.con").exists() and (TXTINOUT / "soils.sol").exists():
        log("[resume] TxtInOut present -> skip S2")
        return
    tool("s2/generate_hru_from_global.py",
         "--basin_shp", basin_shp, "--dem_path", DEM,
         "--output_dir", TXTINOUT, "--basin_name", "xixia",
         "--start_year", SIM_START[:4], "--end_year", SIM_END[:4],
         "--n_subbasins", N_SUBBASINS)


# ----------------------------------------- out-of-tool repair (1): aquifer.aqu
def repair_aquifer():
    """Rewrite aquifer.aqu with the SWAT+ Editor v2.1.0 column names + magnitudes."""
    aqu = TXTINOUT / "aquifer.aqu"
    lines = aqu.read_text().rstrip("\n").split("\n")
    hdr_before = lines[1].split()
    rows = [l.split() for l in lines[2:] if l.strip()]

    out = [lines[0], AQU_HDR]
    for r in rows:
        aid, name, init = int(r[0]), r[1], r[2]
        out.append(f"{aid:>8}  {name:<12}{init:>12}"
                   + "".join(f"{v:>14.5f}" for v in AQU_VALS) + "  ")
    aqu.write_text("\n".join(out) + "\n")

    # read-back proof
    L = aqu.read_text().rstrip("\n").split("\n")
    h = L[1].split()
    chk = L[2].split()
    assert len(chk) == len(h) == 18, f"aquifer.aqu repair produced {len(chk)} tokens"
    assert float(chk[h.index("dep_bot")]) == 10.0
    assert float(chk[h.index("gw_flo")]) == 0.05
    assert float(chk[h.index("flo_min")]) == 3.0
    log(f"repair_aquifer: {len(rows)} aquifers; cols {hdr_before[3:9]} -> {h[3:9]}")
    TOOLS_FAILED.append(
        "s2/generate_hru_from_global.py write_aquifer_files(): aquifer.aqu is written with "
        "FABRICATED magnitudes and two MIS-NAMED columns, checked against the only ground "
        "truth on disk (demo_lrew/swatplus_rev60_demo/aquifer.aqu, SWAT+ Editor v2.1.0). "
        "gw_flo 2500.0 vs 0.05; dep_bot ('gw_dp') 1000.0 m vs 10.0 m; dep_wt ('gw_ht') 1.0 "
        "vs 3.0; flo_min 1000.0 vs 3.0; revap_min 750.0 vs 5.0; columns 7/8 named ptl_n/ptl_p "
        "(hence 0.0) where SWAT+ expects carbon=0.5 and flo_dist=50.0. dep_bot 1000 m x "
        "spec_yld 0.05 makes a 50,000 mm aquifer that never yields return flow. The real case "
        "ran a corrected file (zjg/pristine/aquifer.aqu) and verify_1 repaired it identically; "
        f"the fix has never landed in the KI (live s2 md5 {md5(TOOLS/'s2/generate_hru_from_global.py')} "
        "still emits the fabricated form). Repaired identically here, else the basins would "
        "not be comparable.")


# ------------------------------------ out-of-tool repair (2): parameters.bsn msk
def write_bsn(params):
    """Set msk_co1/msk_co2/msk_x in parameters.bsn (fixed-width, round-trip asserted)."""
    if not params:
        return {}
    p = TXTINOUT / "parameters.bsn"
    lines = p.read_text().rstrip("\n").split("\n")
    hdr, vals = lines[1].split(), lines[2].split()

    def emit(v):
        return "".join(f"{float(x):>14.5f}" for x in v[:-1]) + f"{int(v[-1]):>14d}" + "  "

    assert emit(vals) == lines[2], "parameters.bsn fixed-width round-trip failed"
    applied = {}
    for name, spec in params.items():
        assert spec["change_type"] == "absval", f"{name}: only absval supported"
        vals[hdr.index(name)] = f"{float(spec['value']):.5f}"
        applied[name] = float(spec["value"])
    lines[2] = emit(vals)
    p.write_text("\n".join(lines) + "\n")

    back = p.read_text().rstrip("\n").split("\n")[2].split()
    for name, v in applied.items():
        assert abs(float(back[hdr.index(name)]) - v) < 1e-9, f"{name} read-back failed"
    return applied


# ----------------------------------------------------------------- S3 weather
def station_coords():
    # rout_unit.con columns: id name gis_id area lat lon elev rtu wst ...
    rows = [l.split() for l in (TXTINOUT / "rout_unit.con").read_text().split("\n")[2:]
            if l.strip()]
    return [[float(r[4]), float(r[5])] for r in rows], [r[8] for r in rows]


def weather_ready(names, n_days):
    for n in names:
        for ext in ("pcp", "tmp", "slr", "hmd", "wnd"):
            f = WEATHER / f"{n}.{ext}"
            if not f.exists() or len(f.read_text().strip().split("\n")) < n_days + 3:
                return False
    return all((WEATHER / f"{v}.cli").exists() for v in ("pcp", "tmp", "slr", "hmd", "wnd"))


def prepare_weather():
    coords, names = station_coords()
    n_days = (pd.Timestamp(SIM_END) - pd.Timestamp(SIM_START)).days + 1
    WEATHER.mkdir(parents=True, exist_ok=True)

    if weather_ready(names, n_days):
        log(f"[resume] weather: {len(names)} stations complete -> skip")
    else:
        log(f"weather: building {len(names)} stations from CMFD 3-hourly "
            f"({SIM_START}..{SIM_END}) — the long pole, ~1 read of each monthly slab")
        tool("s3/prepare_weather_files.py", "cmfd", CMFD, json.dumps(coords),
             SIM_START, SIM_END, WEATHER, json.dumps(names))

    tool("s3/validate_weather_data.py", WEATHER)
    for f in WEATHER.iterdir():
        if f.suffix in (".pcp", ".tmp", ".slr", ".hmd", ".wnd", ".cli"):
            shutil.copy2(f, TXTINOUT / f.name)
    tool("s3/generate_weather_stations.py", TXTINOUT / "pcp.cli",
         json.dumps(coords), json.dumps(coords), TXTINOUT)
    return coords, names


CMFD_PREFLIGHT_VARS = ("Prec", "Temp", "SRad", "RHum", "Wind")


def preflight():
    """Validate the RAW gridded forcing store, one variable subdir at a time.

    _find_nc_files() sorts then truncates at 500 files and the 03hr store keeps
    ~888 monthly files per variable, so pointing preflight at the store root only
    ever samples the alphabetically-first variable (LRad).
    """
    script = ("KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect_multi_agent/"
              "validators/preflight_forcing.py")
    failures, warnings, tails = [], [], []
    for var in CMFD_PREFLIGHT_VARS:
        vdir = CMFD / var
        if not vdir.is_dir():
            failures.append(f"FAIL: CMFD variable dir missing: {vdir}")
            continue
        r = subprocess.run([PY, script, str(vdir), "--source", "cmfd", "--json"],
                           capture_output=True, text=True, timeout=7200)
        tails.append(f"[{var}] " + ((r.stdout or "") + (r.stderr or ""))[-300:])
        try:
            rep = json.loads(r.stdout)
        except Exception as e:
            failures.append(f"FAIL: {var}: preflight_forcing emitted no JSON: {e}")
            continue
        for c in rep.get("checks", []):
            msg = f"{var}/{c.get('variable','?')}: {c.get('detail','')}"
            if c.get("status") == "FAIL":
                failures.append("FAIL: " + msg)
            elif c.get("status") == "WARN":
                warnings.append("WARN: " + msg)
        if not rep.get("checks"):
            warnings.append(f"WARN: {var}: no known variable mapping, not range-checked")
    log("preflight_forcing:\n" + "\n".join(tails)[-1200:])
    return {"all_pass": not failures, "source": "cmfd_3hr_raw_store",
            "failures": failures, "warnings": warnings}


# ------------------------------------------------------------------ run/score
def build_fingerprint():
    """md5 over the things that change what a trial MEANS."""
    h = hashlib.md5()
    for p in (TXTINOUT / "rout_unit.con", PRISTINE / "aquifer.aqu",
              PRISTINE / "parameters.bsn",
              TOOLS / "s2/generate_hru_from_global.py",
              TOOLS / "s6/generate_calibration_file.py"):
        h.update(Path(p).read_bytes())
    h.update(f"{SIM_START}{SIM_END}{WARMUP_YEARS}{CAL}{VAL}{OUTLET_LAT}{OUTLET_LON}".encode())
    return h.hexdigest()


def restore_pristine():
    for f in STRUCT_FILES:
        shutil.copy2(PRISTINE / f, TXTINOUT / f)


def run_model():
    for n in ("channel_sd_day.txt", "channel_day.txt"):
        p = TXTINOUT / n
        if p.exists():
            p.unlink()
    t0 = time.time()
    tool("s8/run_swatplus.py", BINARY.resolve(), TXTINOUT)
    log(f"  binary finished in {time.time()-t0:.1f}s")


def sim_series():
    return parse_channel_day(find_channel_file(TXTINOUT), txtinout_dir=TXTINOUT)["Q_sim"]


_OBS_CACHE = {}


def score(sim):
    if "df" not in _OBS_CACHE:
        _OBS_CACHE["df"] = load_obs_grdc(OBS)
    obs = _OBS_CACHE["df"]["Q_obs"]
    df = pd.concat([obs, sim], axis=1, join="inner").dropna()
    df = df[df.index >= pd.Timestamp(CAL[0])]
    if len(df) < 2:
        return None, df
    m_full = all_metrics(df["Q_obs"].values, df["Q_sim"].values)
    cv = compute_calval_metrics(df.index.to_pydatetime(), df["Q_obs"].values,
                                df["Q_sim"].values,
                                cal_start=CAL[0], cal_end=CAL[1],
                                val_start=VAL[0], val_end=VAL[1])
    return {"full": m_full, "cal": cv["calibration"], "val": cv["validation"]}, df


def apply_params(params):
    """Restore pristine, then split params between s6 and the parameters.bsn shim."""
    restore_pristine()
    cal = TXTINOUT / "calibration.cal"
    if cal.exists():
        cal.unlink()
    if not params:
        return {}
    bsn = {k: v for k, v in params.items() if k in BSN_NAMES}
    s6p = {k: v for k, v in params.items() if k not in BSN_NAMES}
    applied = {"structural_bsn": write_bsn(bsn)}
    if s6p:
        out = tool("s6/generate_calibration_file.py", json.dumps(s6p), TXTINOUT)
        try:
            applied.update(json.loads(out[out.find("{"):out.rfind("}") + 1]))
        except Exception:
            pass
    return applied


def trial(name, params, cache):
    if name in cache:
        c = cache[name]
        log(f"[resume] trial {name}: cached KGE_cal={c['cal']['KGE']:.4f} "
            f"NSE_cal={c['cal']['NSE']:.4f}")
        return c
    apply_params(params)
    run_model()
    m, _ = score(sim_series())
    if m is None:
        raise RuntimeError(f"trial {name}: no sim/obs overlap")
    m["params"] = params
    cache[name] = m
    TRIALS.write_text(json.dumps({"_fingerprint": build_fingerprint(),
                                  **{k: v for k, v in cache.items()
                                     if not k.startswith("_")}}, indent=2, default=float))
    log(f"trial {name}: KGE_cal={m['cal']['KGE']:.4f} NSE_cal={m['cal']['NSE']:.4f} "
        f"PBIAS_cal={m['cal']['PBIAS']:+.1f}% r_cal={m['cal']['r']:.3f} "
        f"| NSE_val={m['val']['NSE']:.4f} KGE_val={m['val']['KGE']:.4f}")
    return m


# ------------------------------------------------------- water balance / closure
def _yearly(fname, years):
    lines = (TXTINOUT / fname).read_text().strip().split("\n")
    cols = lines[1].split()
    rows = [dict(zip(cols, l.split())) for l in lines[3:] if len(l.split()) >= len(cols)]
    df = pd.DataFrame(rows).apply(pd.to_numeric, errors="coerce")
    return df[df["yr"].between(*years)]


def aquifer_budget(years):
    """Area-weighted aquifer fluxes (mm/yr) from aquifer_yr.txt."""
    hdr = "jday mon day yr unit gis_id name flo dep_wt stor rchrg seep revap".split()
    rows = [l.split()[:13] for l in (TXTINOUT / "aquifer_yr.txt").read_text().split("\n")[3:]
            if len(l.split()) > 12]
    df = pd.DataFrame(rows, columns=hdr)
    for c in hdr:
        if c != "name":
            df[c] = pd.to_numeric(df[c], errors="coerce")
    acon = [l.split() for l in (TXTINOUT / "aquifer.con").read_text().split("\n")[2:]
            if l.strip()]
    area = {int(r[0]): float(r[3]) for r in acon}
    tot = sum(area.values())
    d = df[df["yr"].between(*years)]
    nyr = d["yr"].nunique()
    aw = lambda c: sum(d[d.gis_id == i][c].sum() * area[i] for i in area) / tot / nyr
    return {"rchrg": aw("rchrg"), "flo": aw("flo"), "seep": aw("seep"),
            "revap": aw("revap"), "dep_wt": aw("dep_wt"), "stor": aw("stor")}


def water_balance(years, sim, area_km2):
    """Closure + the two invariants that actually catch a routing bug (dt_046).

    `outlet / wateryld` is NOT a mass-balance test: basin_wb's `wateryld` is
    surq_gen + latq only and EXCLUDES aquifer return flow.
    """
    wb = _yearly("basin_wb_yr.txt", years)
    nyr = wb["yr"].nunique()
    P, ET = float(wb["precip"].sum()), float(wb["et"].sum())
    WY, perc = float(wb["wateryld"].sum()), float(wb["perc"].sum())
    ndays = int((pd.Timestamp(f"{years[1]}-12-31") - pd.Timestamp(f"{years[0]}-01-01")).days) + 1

    diagnostics, aq = [], None
    try:
        aq = aquifer_budget(years)
        pm = perc / nyr
        diagnostics.append(
            f"aquifer rchrg {aq['rchrg']:.2f} vs basin perc {pm:.2f} mm/yr "
            f"({abs(aq['rchrg']-pm)/max(pm,1e-9)*100:.1f}% — must match; if it instead "
            f"matches wateryld, rout_unit.con is sending `tot` to the aquifer)")
        s = sim.loc[f"{years[0]}":f"{years[1]}"]
        outlet_mm = float(s.sum() * 86400.0 / (area_km2 * 1e6) * 1000.0) / nyr
        pred = WY / nyr + aq["flo"]
        diagnostics.append(
            f"outlet {outlet_mm:.2f} vs wateryld({WY/nyr:.2f}) + aqu_flo({aq['flo']:.2f}) "
            f"= {pred:.2f} mm/yr ({abs(outlet_mm-pred)/max(pred,1e-9)*100:.1f}%)")
        diagnostics.append(f"deep export (aquifer seep) = {aq['seep']:.2f} mm/yr "
                           f"= {aq['seep']/(P/nyr)*100:.1f}% of P")
    except Exception as e:
        diagnostics.append(f"aquifer invariants unavailable: {e}")

    # Percolation reaching the deep aquifer leaves the local balance (rchg_dp);
    # count it as storage change, not as an unexplained residual.
    out = validate_water_balance(precip_mm=P, et_mm=ET, runoff_mm=WY,
                                 delta_storage_mm=perc, period_days=ndays)
    out["diagnostics"] = diagnostics
    out["_totals"] = {"P_mm": P, "ET_mm": ET, "WY_mm": WY, "perc_mm": perc}
    if aq:
        out["aquifer_mm_yr"] = aq
    return out


def write_result(**kw):
    OUTDIR.mkdir(parents=True, exist_ok=True)
    base = {"model_id": "SWAT+",
            "this_location": ("Xixia (西峡), Laoguan He, Han/Yangtze basin, 3418 km2 "
                              "— GRDC 2182250"),
            "obs_source": ("GRDC Asia-Region Daily Discharge Export (250 stations, "
                           "2026-05-11 download)"),
            "run_signature": RUN_SIGNATURE}
    base.update(kw)
    RESULT.write_text(json.dumps(base, indent=2, default=float, ensure_ascii=False))


TOOLS_USED = [
    "s1/delineate_watershed.py", "s2/generate_hru_from_global.py",
    "s3/prepare_weather_files.py", "s3/validate_weather_data.py",
    "s3/generate_weather_stations.py", "s6/generate_calibration_file.py",
    "s7/configure_time_sim.py", "s7/configure_print_prt.py",
    "s7/validate_txtinout.py", "s8/run_swatplus.py", "s9/extract_discharge.py",
    "ki_tools_common.load_forcing", "ki_tools_common.terrain",
    "ki_tools_common.metrics", "ki_tools_common.validation",
    "validators/standard_calval", "validators/preflight_forcing"]

NULL_METRICS = {"nse": None, "kge": None, "pbias": None, "r": None, "period": None}


# ---------------------------------------------------------------------- main
def main():
    OUTDIR.mkdir(parents=True, exist_ok=True)
    if RESULT.exists():
        sig = None
        try:
            r = json.loads(RESULT.read_text())
            sig = r.get("run_signature")
            if sig == RUN_SIGNATURE and r.get("status") == "completed" \
                    and (r.get("metrics") or {}).get("nse") is not None:
                log("[resume] result.json for THIS run already complete -> exit")
                return
        except Exception:
            pass
        log(f"result.json exists but signature={sig!r} != {RUN_SIGNATURE!r} -> regenerating")
        RESULT.unlink()

    assert BINARY.exists(), f"missing binary {BINARY}"
    assert OBS.exists(), f"missing obs {OBS}"
    log(f"binary md5 {md5(BINARY)}  {BINARY}")
    log(f"live tool md5s: s2={md5(TOOLS/'s2/generate_hru_from_global.py')} "
        f"s6={md5(TOOLS/'s6/generate_calibration_file.py')}")

    clip_merit()
    basin_shp, area = build_basin()
    build_txtinout(basin_shp)

    # Structural repairs + pristine reference (before any trial).
    if not (PRISTINE / "aquifer.aqu").exists():
        repair_aquifer()
        PRISTINE.mkdir(parents=True, exist_ok=True)
        for f in STRUCT_FILES:
            shutil.copy2(TXTINOUT / f, PRISTINE / f)
        log(f"pristine/ built from repaired TxtInOut ({', '.join(STRUCT_FILES)})")
    else:
        log("[resume] pristine/ present -> skip aquifer repair")
        TOOLS_FAILED.append(
            "s2/generate_hru_from_global.py write_aquifer_files(): fabricated aquifer.aqu "
            "magnitudes + two mis-named columns (gw_flo 2500 vs 0.05, dep_bot 1000 m vs 10, "
            "flo_min 1000 vs 3, ptl_n/ptl_p vs carbon/flo_dist). Repaired into pristine/ on "
            "an earlier pass of this resumable run; see zjg/pristine/aquifer.aqu.")
    TOOLS_FAILED.append(
        "s6/generate_calibration_file.py: the bsn-object names msk_co1/msk_co2/msk_x make the "
        "tool EXIT 1 ('Unknown parameter'), writing NOTHING — not even the calibration.cal rows "
        "for the other parameters in the same call, so a trial naming msk silently loses its "
        "cn2/rchg_dp too. Every bsn name is also a calibration.cal no-op in rev59, so Muskingum "
        "routing is reachable ONLY by editing parameters.bsn. The real case had a STRUCTURAL_BSN "
        f"writer for exactly these names; it was REVERTED (live s6 md5 "
        f"{md5(TOOLS/'s6/generate_calibration_file.py')} has no msk handling). Routed around s6 "
        "here, exactly as verify_1 did. Separately, s6's structural aquifer.aqu writer re-joins "
        "row tokens with '   ', destroying the fixed-width layout s2 wrote (values survive; "
        "free-format read tolerates it).")

    coords, names = prepare_weather()

    pf = preflight()
    if not pf["all_pass"]:
        write_result(status="failed", tools_used=TOOLS_USED, tools_failed=TOOLS_FAILED,
                     metrics=NULL_METRICS,
                     water_balance={"status": "N/A", "residual_pct": None},
                     forcing_preflight=pf,
                     metrics_null_reason="forcing preflight FAILED before the model ran",
                     notes="Forcing preflight FAILED; stopped before running the model.")
        return

    tool("s7/configure_time_sim.py", SIM_START, SIM_END, TXTINOUT, WARMUP_YEARS)
    tool("s7/configure_print_prt.py",
         json.dumps({"channel": {"daily": True}, "basin_wb": {"yearly": True},
                     "aquifer": {"yearly": True}}), TXTINOUT, WARMUP_YEARS)
    tool("s7/validate_txtinout.py", TXTINOUT)

    cache = {}
    if TRIALS.exists():
        c = json.loads(TRIALS.read_text())
        if c.get("_fingerprint") == build_fingerprint():
            cache = {k: v for k, v in c.items() if not k.startswith("_")}
            log(f"[resume] trials.json fingerprint matches -> {len(cache)} cached trials")
        else:
            log("trials.json fingerprint STALE (tools/topology changed) -> discarding")

    # ---- Stage 0: UNCALIBRATED. The PBIAS sign selects the recipe direction.
    base = trial("uncalibrated", {}, cache)
    pbias0, r0 = base["cal"]["PBIAS"], base["cal"]["r"]
    over = pbias0 > 0
    log(f"UNCALIBRATED PBIAS_cal={pbias0:+.1f}% r_cal={r0:.3f} (NSE ceiling r^2="
        f"{r0**2:.3f}) -> basin {'OVER' if over else 'UNDER'}-predicts")

    best_name, best = "uncalibrated", base
    params = {}
    SEL = lambda m: m["cal"]["KGE"]      # NSE <= r^2; select on KGE, report NSE

    def stage(label, options):
        nonlocal best, best_name, params
        for tag, extra in options:
            m = trial(f"{label}:{tag}", dict(params, **extra), cache)
            if SEL(m) > SEL(best):
                best, best_name = m, f"{label}:{tag}"
        if best_name.startswith(label + ":"):
            params = dict(best["params"])
        log(f"  after {label}: best={best_name} KGE_cal={SEL(best):.4f} "
            f"NSE_cal={best['cal']['NSE']:.4f} NSE_val={best['val']['NSE']:.4f}")

    if over:
        stage("cn2", [("pct-20", {"cn2": {"change_type": "pctchg", "value": -20}}),
                      ("pct-35", {"cn2": {"change_type": "pctchg", "value": -35}}),
                      ("pct-50", {"cn2": {"change_type": "pctchg", "value": -50}}),
                      ("abs25", {"cn2": {"change_type": "absval", "value": 25}})])
        stage("esco", [(f"{v}", {"esco": {"change_type": "absval", "value": v}})
                       for v in (0.15, 0.50, 0.95)])
        stage("rchg_dp", [(f"{v}", {"rchg_dp": {"change_type": "absval", "value": v}})
                          for v in (0.30, 0.60, 0.78, 0.90)])
    else:
        stage("cn2", [(f"pct{v}", {"cn2": {"change_type": "pctchg", "value": v}})
                      for v in (5, 20, 35)])
        stage("esco", [(f"{v}", {"esco": {"change_type": "absval", "value": v}})
                       for v in (0.85, 0.50)])
        stage("rchg_dp", [(f"{v}", {"rchg_dp": {"change_type": "absval", "value": v}})
                          for v in (0.0, 0.05)])

    stage("alpha", [(f"{v}", {"alpha": {"change_type": "absval", "value": v}})
                    for v in (0.02, 0.05, 0.30)])
    stage("flo_min", [(f"{v}", {"flo_min": {"change_type": "absval", "value": v}})
                      for v in (3.0, 10.0, 50.0)])
    # Muskingum: only the msk_co1:msk_co2 RATIO matters (SWAT+ normalises them).
    stage("msk", [(f"{a}/{b}", {"msk_co1": {"change_type": "absval", "value": a},
                                "msk_co2": {"change_type": "absval", "value": b}})
                  for a, b in ((1.0, 1.0), (3.0, 1.0))])
    stage("msk_x", [(f"{v}", {"msk_x": {"change_type": "absval", "value": v}})
                    for v in (0.1, 0.3)])

    # ---- Re-run the winner so TxtInOut on disk matches the reported numbers
    log(f"FINAL: re-running winner {best_name} -> {best['params']}")
    applied = apply_params(best["params"])
    run_model()
    m, df = score(sim_series())
    df.to_csv(OUTDIR / "discharge_comparison.csv")
    wb = water_balance((int(CAL[0][:4]), int(VAL[1][:4])), df["Q_sim"], area)

    f = m["full"]
    notes = (
        f"SWAT+ rev59 built FROM SCRATCH at Xixia (西峡), Laoguan He, GRDC 2182250 — a "
        f"Qinling-mountain headwater of the Dan/Han/Yangtze, hydrologically independent of "
        f"both the Zijingguan real case (Haihe) and the Wangjiaba verifier (Huai). Selected "
        f"from the 38 Chinese stations in the assigned GRDC export as the only one that is "
        f"(a) fully inside the MERIT tiles on disk, (b) area-reproducible, and (c) long. The "
        f"GRDC coordinate ({GRDC_LAT}N {GRDC_LON}E) reads upa=0.0 km2 — off-channel — so the "
        f"outlet was moved to the area-matched channel cell {OUTLET_LAT}N {OUTLET_LON}E "
        f"(upa 3420.4 km2 vs published {PUBLISHED_AREA_KM2:.0f}, +0.07%); delineated "
        f"{area:.0f} km2. CMFD 3-hourly forcing, {len(names)} stations, {N_SUBBASINS} "
        f"requested subbasins. Sim {SIM_START}..{SIM_END}, {WARMUP_YEARS} warmup years; "
        f"scored on {len(df)} paired daily values (1992-93 absent from the GRDC record). "
        f"Uncalibrated PBIAS_cal={pbias0:+.1f}% (r_cal={r0:.3f}, so NSE_cal <= {r0**2:.3f}) "
        f"-> {'OVER' if over else 'UNDER'}-predict recipe; staged greedy search over "
        f"{len(cache)} trials, selected on KGE of {CAL[0]}..{CAL[1]} only, winner "
        f"'{best_name}' {best['params']}. Full NSE={f['NSE']:.4f} KGE={f['KGE']:.4f} "
        f"PBIAS={f['PBIAS']:+.2f}% r={f['r']:.4f}; held-out validation ({VAL[0]}..{VAL[1]}) "
        f"NSE={m['val']['NSE']:.4f} KGE={m['val']['KGE']:.4f} PBIAS={m['val']['PBIAS']:+.2f}%. "
        f"Water balance {wb['status']} (residual {wb.get('residual_pct')}%). "
        f"The same two repairs the real case and verify_1 relied on are STILL absent from the "
        f"live KI (tool md5s unchanged) and were re-applied here: the fabricated aquifer.aqu, "
        f"and msk_* routed around an s6 that exits 1 on them.")
    if TOOLS_FAILED:
        notes += f" {len(TOOLS_FAILED)} KI tool defect(s) hit — see tools_failed."

    write_result(
        status="completed",
        tools_used=TOOLS_USED,
        tools_failed=TOOLS_FAILED,
        variable="flo_out",
        obs_shape="point_time_series",
        metrics={
            "nse": f["NSE"], "kge": f["KGE"], "pbias": f["PBIAS"], "r": f["r"],
            "rmse": f.get("RMSE"),
            "period": f"{CAL[0]}..{VAL[1]} daily",
            "nse_cal": m["cal"]["NSE"], "kge_cal": m["cal"]["KGE"],
            "pbias_cal": m["cal"]["PBIAS"], "r_cal": m["cal"]["r"],
            "nse_val": m["val"]["NSE"], "kge_val": m["val"]["KGE"],
            "pbias_val": m["val"]["PBIAS"], "r_val": m["val"]["r"],
            "nse_val_ceiling_r2": m["val"]["r"] ** 2,
            "period_calibration": f"{CAL[0]}..{CAL[1]}",
            "period_validation": f"{VAL[0]}..{VAL[1]}",
            "n_paired_days": int(len(df))},
        water_balance={"status": wb["status"], "residual_pct": wb.get("residual_pct"),
                       "residual_mm": wb.get("residual_mm"),
                       "diagnostics": wb.get("diagnostics"), "totals": wb["_totals"],
                       "aquifer_mm_yr": wb.get("aquifer_mm_yr")},
        forcing_preflight=pf,
        basin={"area_km2": area, "published_gauge_area_km2": PUBLISHED_AREA_KM2,
               "outlet_lat": OUTLET_LAT, "outlet_lon": OUTLET_LON,
               "grdc_lat": GRDC_LAT, "grdc_lon": GRDC_LON,
               "merit_upa_at_outlet_km2": 3420.4,
               "merit_upa_at_grdc_coord_km2": 0.0,
               "n_subbasins_requested": N_SUBBASINS, "n_weather_stations": len(names)},
        calibration={"selected": best_name, "params": best["params"],
                     "structural_applied": applied,
                     "uncalibrated_pbias_cal": pbias0, "n_trials": len(cache),
                     "selection_metric": "KGE_cal",
                     "selection_period": f"{CAL[0]}..{CAL[1]}"},
        notes=notes,
        log_tail=LOG[-40:])
    log(f"WROTE {RESULT}: NSE={f['NSE']:.4f} NSE_val={m['val']['NSE']:.4f} "
        f"PBIAS={f['PBIAS']:+.2f}%")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        write_result(
            status="failed", tools_used=TOOLS_USED, tools_failed=TOOLS_FAILED,
            metrics={"nse": None, "kge": None, "pbias": None, "r": None,
                     "period": f"{CAL[0]}..{VAL[1]} daily"},
            water_balance={"status": "N/A", "residual_pct": None},
            metrics_null_reason=f"run failed before scoring: {e}",
            error=str(e), traceback=traceback.format_exc()[-3000:],
            notes=f"SWAT+ Xixia (GRDC 2182250) verifier failed: {e}",
            log_tail=LOG[-60:])
        raise
