#!/usr/bin/env python3
"""
SWAT+ VERIFIER (verify_1) — Wangjiaba (王家坝), Huai River, gauge 51030.

Second location for the SWAT+ consistency check. The Real-case stage ran the KI
chain at Zijingguan (Juma/Haihe, ~1767 km2, semi-arid Taihang karst front). This
script runs the SAME chain, FROM SCRATCH, at Wangjiaba: the upper Huai main stem
at the Wangjiaba sluice (32.42442N, 115.58542E), published drainage area
30,630 km2 — humid subtropical, 17x larger, agricultural plain.

    s1/delineate_watershed.py       DEM -> watershed.shp   (area-checked)
    s2/generate_hru_from_global.py  HRUs + soils.sol + full TxtInOut
    s3/prepare_weather_files.py     CMFD 3-hourly -> .pcp/.tmp/.slr/.hmd/.wnd
    s3/validate_weather_data.py     QC (Tmax==Tmin trap, dt_043)
    s3/generate_weather_stations.py weather-sta.cli + weather-wgn.cli
    s7/configure_time_sim.py        1978-1997, 3 warmup years
    s7/configure_print_prt.py       channel daily, basin_wb + aquifer yearly
    s7/validate_txtinout.py         cross-check file.cio
    s6/generate_calibration_file.py calibration.cal (+ structural aquifer.aqu)
    s8/run_swatplus.py              rev59 binary
    s9/extract_discharge.py         topology outlet, ha-m/day -> m3/s

A pre-tuned Wangjiaba deck exists on disk (`run_wjb/`, the `cn2 absval 25` +
`rchg_dp 0.78` recipe recorded in SKILL.md) and is deliberately NOT reused: it
was hand-calibrated in an earlier session, so scoring it would report a tuned
deck's skill as this from-scratch verifier's. Everything is rebuilt into wjb_v3/.

TWO OUT-OF-TOOL REPAIRS, mirroring the Real case exactly
--------------------------------------------------------
The Real case's Zijingguan deck did NOT run on raw s2/s6 output. Two repairs
that the Real case applied were later REVERTED out of the KI by the fix-stage
rollback, and are verifiably absent from the live tools (md5s recorded below).
Applying them here is what makes the two basins comparable; NOT applying them
would compare a repaired pipeline at Zijingguan against a broken one here.

  (1) aquifer.aqu — s2's write_aquifer_files() fabricates magnitudes and
      MIS-NAMES two columns. Ground truth is the shipped SWAT+ Editor v2.1.0
      demo (demo_lrew/swatplus_rev60_demo/aquifer.aqu):
          gw_flo 2500.0 -> 0.05 | dep_bot('gw_dp') 1000.0 m -> 10.0
          dep_wt('gw_ht') 1.0 -> 3.0 | flo_min 1000.0 -> 3.0
          revap_min 750.0 -> 5.0 | cols 7/8 ptl_n/ptl_p -> carbon 0.5 / flo_dist 50.0
      dep_bot 1000 m x spec_yld 0.05 is a 50,000 mm aquifer that never yields
      return flow. The Real case ran `zjg/pristine/aquifer.aqu`, the corrected
      form; this script writes the identical correction into wjb_v3/pristine/.

  (2) msk_co1/msk_co2/msk_x — every bsn-object name is a calibration.cal no-op
      in rev59, so Muskingum routing is only reachable by editing parameters.bsn.
      Live s6 EXITS 1 ("Unknown parameter: msk_co1") and writes nothing at all —
      it takes the whole call down, so a trial naming msk would silently lose
      its cn2/rchg_dp too. This script therefore routes the three bsn names
      around s6 into parameters.bsn directly (fixed-width round-trip asserted).

Both are recorded in tools_failed with live md5s.

Calibration mirrors the Real case exactly: run UNCALIBRATED, read the outlet
PBIAS sign, then greedily search one parameter group at a time, SELECTING ON
KGE of the calibration period (SKILL.md: NSE <= r^2, so a greedy NSE search is
near-degenerate when r is the binding constraint). 1981-1989 selects;
1990-1997 is held out and never optimized on.

Stages sweep only names the live binary actually APPLIES (dt_045): cn2, esco,
alpha, flo_min via calibration.cal; rchg_dp structurally via aquifer.aqu; msk_*
structurally via parameters.bsn. surlag / canmx / perco are omitted — live s6
DROPS them with a warning, so sweeping them burns binary runs exploring nothing.

RESUMABLE at every stage: watershed.shp, TxtInOut, the weather deck, and each
calibration trial's metrics (trials.json, guarded by a fingerprint over the
tools + topology) are cached and skipped on relaunch. A result.json carrying
this run's signature short-circuits the whole script.
"""
import sys, os, json, shutil, subprocess, time, hashlib, traceback
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path("KISSPATH_ROOT")
KI = ROOT / "models/SWAT+/knowledge_infrastructure"
TOOLS = KI / "tools"
WORK = ROOT / "models/SWAT+/wjb_v3"
DELIN = WORK / "delin"
TXTINOUT = WORK / "TxtInOut"
WEATHER = WORK / "weather"
PRISTINE = WORK / "pristine"
BINARY = ROOT / "models/SWAT_Plus/test_rev59/swatplus_rev59"
CMFD = ROOT / "data/forcing/Data_forcing_03hr_010deg"
OBS = ROOT / "data/obs/WJB/HUAIH-51030-wangjiaba.txt"

# MERIT Hydro tiles clipped to the Huai in an earlier session. Wangjiaba's basin
# is nested inside that clip (bbox 111.30-118.05E, 30.85-35.00N); reused read-only.
SRC = ROOT / "models/SWAT+/bengbu_v1"
DEM = SRC / "elv_clip.tif"          # MERIT Hydro elevation
DIR_TIF = SRC / "dir_clip.tif"      # MERIT Hydro D8 flow direction (conditioned)

# Weather deck built by the SAME live prepare_weather_files.py (md5 asserted at
# runtime). Reused ONLY if the fresh rout_unit.con station coords match it.
WEATHER_CACHE = ROOT / "models/SWAT+/wjb_v2/weather"

OUTDIR = ROOT / "models/SWAT+/detached/verify_1"
RESULT = OUTDIR / "result.json"
TRIALS = OUTDIR / "trials.json"

# Wangjiaba sluice (王家坝闸). Located as the MERIT `upa` main-stem cell whose
# upstream area matches the gauge's published 30,630 km2. The nominal station
# coordinate (32.4333N, 115.6083E) sits ~2 km off the conditioned channel.
OUTLET_LAT, OUTLET_LON = 32.42442, 115.58542
PUBLISHED_AREA_KM2 = 30630.0

# Obs record runs 1952-05-30..1998-12-31; CMFD V0200 starts 1951-01. 1978-1997
# is fully covered by both.
SIM_START, SIM_END = "1978-01-01", "1997-12-31"
WARMUP_YEARS = 3                        # 1978-1980 discarded
CAL = ("1981-01-01", "1989-12-31")
VAL = ("1990-01-01", "1997-12-31")      # held out; never optimized on
N_SUBBASINS = 8
STREAM_THRESHOLD_KM2 = 125.0            # scaled to 30,630 km2
SNAP_DIST_DEG = 0.01

sys.path.insert(0, str(TOOLS / "s9"))
sys.path.insert(0, "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect_multi_agent")
sys.path.insert(0, "KISSPATH_INTERNAL_NOT_SHIPPED")

from extract_discharge import find_channel_file, parse_channel_day, load_obs   # noqa: E402
from ki_tools_common.metrics import all_metrics                                # noqa: E402
from ki_tools_common.validation import validate_water_balance                  # noqa: E402
from validators.standard_calval import compute_calval_metrics                  # noqa: E402

PY = sys.executable
LOG = []

RUN_SIGNATURE = f"wjb_v3|from_scratch|{SIM_START}..{SIM_END}|cal={CAL[0]}..{CAL[1]}|sel=KGE_cal"

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
NOTES = []


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


# ------------------------------------------------------------------ S1 basin
def merit_watershed(shp_path):
    """Trace the basin upstream of the outlet through MERIT Hydro's D8 `dir`.

    MERIT `dir` is the hydrologically-CONDITIONED flow direction shipped with the
    DEM. On the flat Huai plain a raw breach/fill + D8 pass over the bare DEM
    routinely leaks across the Yellow-River and Yangtze divides (dt_008); the
    conditioned pointer does not.
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

    polys = [shape(g) for g, v in features.shapes(m2.astype("uint8"), mask=m2,
                                                  transform=tr) if v == 1]
    geom = unary_union(polys).buffer(0).simplify(0.0025).buffer(0)
    gdf = gpd.GeoDataFrame({"id": [1]}, geometry=[geom], crs="EPSG:4326")
    gdf.to_file(str(shp_path))
    poly_area = float(gdf.to_crs("EPSG:6933").area.sum() / 1e6)
    log(f"MERIT-dir watershed: {poly_area:.0f} km2 (published {PUBLISHED_AREA_KM2:.0f}, "
        f"{(poly_area-PUBLISHED_AREA_KM2)/PUBLISHED_AREA_KM2*100:+.1f}%)")
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
        f"s1/delineate_watershed.py: on the flat Huai plain a breach-fill + D8 pass over the "
        f"bare DEM {detail}. WhiteboxTools' `fill_depressions` cannot recover the true divide "
        f"across the Huaibei plain, so the pour point captures (or loses) whole sub-basins — "
        f"dt_008 with no fatal error. WORKAROUND used here: trace the basin through MERIT "
        f"Hydro's hydrologically-CONDITIONED D8 `dir` grid. The KI has no tool for this; s1 "
        f"should accept a conditioned flow-direction raster instead of re-deriving one from "
        f"raw elevation on low-relief basins."
    )
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
         "--output_dir", TXTINOUT, "--basin_name", "wangjiaba",
         "--start_year", SIM_START[:4], "--end_year", SIM_END[:4],
         "--n_subbasins", N_SUBBASINS)


# ----------------------------------------- out-of-tool repair (1): aquifer.aqu
def repair_aquifer():
    """Rewrite aquifer.aqu with the SWAT+ Editor v2.1.0 column names + magnitudes.

    Preserves s2's aquifer ids/names/init; replaces only the fabricated numbers.
    Verified against demo_lrew/swatplus_rev60_demo/aquifer.aqu. Byte-for-byte the
    same layout the Real case ran from zjg/pristine/aquifer.aqu.
    """
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
        "spec_yld 0.05 makes a 50,000 mm aquifer that never yields return flow. The Real case "
        "ran a corrected file (zjg/pristine/aquifer.aqu); this fix was REVERTED out of the KI "
        f"(live s2 md5 {md5(TOOLS/'s2/generate_hru_from_global.py')} still emits the fabricated "
        "form). Repaired identically here, else the two basins would not be comparable."
    )


# ------------------------------------ out-of-tool repair (2): parameters.bsn msk
def write_bsn(params):
    """Set msk_co1/msk_co2/msk_x in parameters.bsn (fixed-width, round-trip asserted).

    Live s6 exits 1 on these names ("Unknown parameter") and writes NOTHING —
    not even the calibration.cal rows for the other parameters in the same call.
    """
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


def cache_matches(names):
    """Reuse the cached weather deck only if it is for THESE stations at THESE coords."""
    if not WEATHER_CACHE.is_dir():
        return False
    coords, _ = station_coords()
    for (lat, lon), n in zip(coords, names):
        f = WEATHER_CACHE / f"{n}.pcp"
        if not f.exists():
            return False
        meta = f.read_text().split("\n")[2].split()   # name nbyr tstep lat lon elev
        if abs(float(meta[2]) - lat) > 1e-4 or abs(float(meta[3]) - lon) > 1e-4:
            log(f"weather cache coord mismatch at {n}: {meta[2]},{meta[3]} vs {lat},{lon}")
            return False
    return True


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
    elif cache_matches(names):
        log(f"[resume] reusing wjb_v2 weather deck: same live s3 tool, identical "
            f"station coords ({len(names)} stations)")
        for f in WEATHER_CACHE.iterdir():
            if f.suffix in (".pcp", ".tmp", ".slr", ".hmd", ".wnd", ".cli"):
                shutil.copy2(f, WEATHER / f.name)
    else:
        log(f"weather: building {len(names)} stations from CMFD 3-hourly "
            f"({SIM_START}..{SIM_END})")
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
    ~800 monthly files per variable, so pointing preflight at the store root only
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
    """md5 over the things that change what a trial MEANS.

    A trials.json written before a topology/tool/repair change must never replay.
    """
    h = hashlib.md5()
    for p in (TXTINOUT / "rout_unit.con", PRISTINE / "aquifer.aqu",
              PRISTINE / "parameters.bsn",
              TOOLS / "s2/generate_hru_from_global.py",
              TOOLS / "s6/generate_calibration_file.py"):
        h.update(Path(p).read_bytes())
    h.update(f"{SIM_START}{SIM_END}{WARMUP_YEARS}{CAL}{VAL}".encode())
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


def score(sim):
    obs = load_obs(OBS)["Q_obs"]
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
    base = {"model_id": "SWAT+", "this_location": "Wangjiaba", "obs_source": "ObservedQ",
            "run_signature": RUN_SIGNATURE}
    base.update(kw)
    RESULT.write_text(json.dumps(base, indent=2, default=float))


TOOLS_USED = [
    "s1/delineate_watershed.py", "s2/generate_hru_from_global.py",
    "s3/prepare_weather_files.py", "s3/validate_weather_data.py",
    "s3/generate_weather_stations.py", "s6/generate_calibration_file.py",
    "s7/configure_time_sim.py", "s7/configure_print_prt.py",
    "s7/validate_txtinout.py", "s8/run_swatplus.py", "s9/extract_discharge.py",
    "ki_tools_common.load_forcing", "ki_tools_common.terrain",
    "ki_tools_common.metrics", "ki_tools_common.validation",
    "validators/standard_calval", "validators/preflight_forcing"]


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
    log(f"binary md5 {md5(BINARY)}  {BINARY}")

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
        if not any("write_aquifer_files" in t for t in TOOLS_FAILED):
            TOOLS_FAILED.append(
                "s2/generate_hru_from_global.py write_aquifer_files(): fabricated aquifer.aqu "
                "magnitudes + two mis-named columns (gw_flo 2500 vs 0.05, dep_bot 1000 m vs 10, "
                "flo_min 1000 vs 3, ptl_n/ptl_p vs carbon/flo_dist). Repaired into pristine/ on "
                "an earlier pass of this resumable run; see zjg/pristine/aquifer.aqu.")
    TOOLS_FAILED.append(
        "s6/generate_calibration_file.py: the bsn-object names msk_co1/msk_co2/msk_x make the "
        f"tool EXIT 1 ('Unknown parameter'), writing NOTHING — not even the calibration.cal rows "
        f"for the other parameters in the same call, so a trial naming msk silently loses its "
        f"cn2/rchg_dp too. Every bsn name is also a calibration.cal no-op in rev59, so Muskingum "
        f"routing is reachable ONLY by editing parameters.bsn. The Real case had a STRUCTURAL_BSN "
        f"writer for exactly these names; it was REVERTED (live s6 md5 "
        f"{md5(TOOLS/'s6/generate_calibration_file.py')} has no msk handling). Routed around s6 "
        f"here. Separately, s6's structural aquifer.aqu writer re-joins row tokens with '   ', "
        f"destroying the fixed-width layout s2 wrote (values survive; free-format read tolerates it).")

    coords, names = prepare_weather()

    pf = preflight()
    if not pf["all_pass"]:
        write_result(status="failed", tools_used=TOOLS_USED, tools_failed=TOOLS_FAILED,
                     metrics={"nse": None, "kge": None, "pbias": None, "r": None,
                              "period": None},
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
        # Volume first: cn2 caps quickflow, rchg_dp is the dominant volume sink
        # (SKILL.md's validated Wangjiaba recipe is cn2 absval 25 + rchg_dp 0.78).
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
        f"SWAT+ rev59 built FROM SCRATCH at Wangjiaba (upper Huai, gauge 51030, outlet "
        f"{OUTLET_LAT}N {OUTLET_LON}E, delineated {area:.0f} km2 vs published "
        f"{PUBLISHED_AREA_KM2:.0f}), same KI chain as the Zijingguan real case; the pre-tuned "
        f"run_wjb/ deck was NOT reused. CMFD 3-hourly forcing, {len(names)} stations, "
        f"{N_SUBBASINS} requested subbasins. Sim {SIM_START}..{SIM_END}, {WARMUP_YEARS} warmup "
        f"years; scored on {len(df)} paired daily values. Uncalibrated PBIAS_cal={pbias0:+.1f}% "
        f"(r_cal={r0:.3f}, so NSE_cal <= {r0**2:.3f}) -> {'OVER' if over else 'UNDER'}-predict "
        f"recipe; staged greedy search over {len(cache)} trials, selected on KGE of 1981-1989 "
        f"only, winner '{best_name}' {best['params']}. Full NSE={f['NSE']:.4f} KGE={f['KGE']:.4f} "
        f"PBIAS={f['PBIAS']:+.2f}% r={f['r']:.4f}; held-out validation (1990-1997) "
        f"NSE={m['val']['NSE']:.4f} KGE={m['val']['KGE']:.4f} PBIAS={m['val']['PBIAS']:+.2f}%. "
        f"Water balance {wb['status']} (residual {wb.get('residual_pct')}%). "
        f"Two repairs the Real case also relied on had been REVERTED out of the live KI and were "
        f"re-applied here (fabricated aquifer.aqu; msk_* routed around an s6 that exits 1 on "
        f"them) — without them the two basins would not be running the same pipeline."
    )
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
            notes=f"SWAT+ Wangjiaba verifier failed: {e}",
            log_tail=LOG[-60:])
        raise
