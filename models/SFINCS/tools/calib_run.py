#!/usr/bin/env python3
"""
SFINCS calibration driver — RUNNER-mode run+score for ONE candidate parameter vector.

TARGET CASE (pinned; this driver scores nothing else)
-----------------------------------------------------
    case_id     HYDAT:08MF035
    gauge/obs   HYDAT 08MF035 "FRASER RIVER NEAR AGASSIZ" daily water level (DLY_LEVELS,
                metres in HYDAT DATUM_ID 35 "GEODETIC SURVEY OF CANADA DATUM"),
                read READ-ONLY out of /mnt/disk4/Hydat_sqlite3_20260116/Hydat.sqlite3
    quantity    water surface elevation at the SFINCS observation point (his `point_zs`)
    metric      PBIAS (magnitude_accuracy); nse / kge / r / rmse also emitted
    provenance  SFINCS_20260805T020658Z_648666 — the validated coupling reproduced here
                (holdout pbias -0.6652085, nse 0.9744295, kge 0.8701747, r 0.9968597).

This is NOT the Huai/Wangjiaba, Kangerlussuaq or Zijingguan SFINCS showcase; the KI's
other run scripts target those. The gauge is a MODULE CONSTANT — it is never taken from
an env var or a CLI flag, and `__kdt__.case_id` / `__kdt__.scored_obs` are BUILT from the
HYDAT station row that actually opened the observations, so a wrong-gauge run cannot be
mislabelled as this one.

WHAT ONE EVAL DOES
------------------
  1. read the candidate vector from $KDT_CALIB_PARAMS (runner mode: the kit writes
     nothing into the inputs — see calibration.yaml `injection.mode: runner`);
  2. stage the VALIDATED run's static inputs (domain sfincs.dep/.msk/.ind/.man and the
     per-year sfincs.precip/.src/.dis/.obs) into a FRESH per-candidate directory — they
     are built ONCE by ensure_base() and reused, nothing is downloaded per eval;
  3. INJECT the candidate the model's own way, AFTER staging so nothing overwrites it:
       manning_water_n / manning_land_mult -> sfincs.man   (compressed float32 map)
       q_mult                              -> sfincs.dis   (ASCII discharge table)
       precip_mult                         -> sfincs.precip(ASCII rainfall table)
       qinf / advection                    -> sfincs.inp   (written by the KI's
                                              s6_config/generate_sfincs_inp.py, then the
                                              qinf line re-written at full precision
                                              because the generator formats it "%.2f")
  4. READ every value BACK out of the artifact SFINCS actually opens and fail closed
     (nonzero exit, NO metrics file) if any read-back disagrees with the request;
  5. run the binary through the KI's own s7_execution/run_sfincs.py;
  6. gate on run health (run_summary.json status, "Simulation finished" in sfincs.log,
     no CRITICAL preflight warning, finite un-filled point_zs) — a REQUIRED diagnostic
     that is missing or None fails the eval closed, it is never defaulted to a pass;
  7. score daily-mean point_zs against the HYDAT observations for the requested split,
     after adding the FIXED vertical registration constant DATUM_OFFSET_M;
  8. write metrics + the reserved `__kdt__` block via a staged temp file + os.replace.

VERTICAL DATUM — WHY THE OFFSET IS A CONSTANT, NOT A PARAMETER
--------------------------------------------------------------
The DEM is Copernicus GLO-30 (EGM2008-referenced, and over water it reports the river
surface at acquisition) while the gauge is CGVD28-family, so SFINCS `zs` and HYDAT stage
live on different vertical data. The validated run fitted ONE constant offset on the
2021 calibration year and applied it unchanged to 2022. That constant is PINNED here
(DATUM_OFFSET_M below) and is identical for every candidate: re-fitting it per candidate
would force PBIAS to zero by construction on the calibration split and leave the
sensitivity screen with no signal at all. Because the constant was fitted with the
DEFAULT vector, PBIAS on the calibration split starts at ~0 and every parameter move is
visible against it; the holdout split starts at the validated -0.665%.

USAGE
-----
    python calib_run.py --workdir <wd> --out <metrics.json>
    env  KDT_CALIB_PARAMS  path to {"name": value, ...}   (REQUIRED — runner mode)
    env  KDT_CALIB_SPLIT   "calibration" | "holdout"      (unset/blank/"full" -> both)

Exit codes: 0 = metrics written; non-zero = NO metrics file (the kit scores +inf).
"""

from __future__ import annotations

import argparse
import datetime as dtm
import hashlib
import importlib.util
import json
import math
import os
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------- pinned case
KI = Path(__file__).resolve().parent.parent
TOOLS = KI / "tools"

CASE_ID = "HYDAT:08MF035"                 # the TARGET CASE; asserted against the resolved station
OBS_NETWORK = "HYDAT"
OBS_STATION = "08MF035"                   # scored gauge — Fraser River near Agassiz
OBS_STATION_NAME = "FRASER RIVER NEAR AGASSIZ"
OBS_LAT = 49.20368957519531
OBS_LON = -121.7758331298828
OBS_AREA_KM2 = 218000.0
OBS_DATUM_ID = 35
OBS_DATUM_NAME = "GEODETIC SURVEY OF CANADA DATUM"
OBS_TABLE = "DLY_LEVELS"
OBS_UNIT = "m"

FLOW_STATION = "08MF005"                  # inflow BC — Fraser River at Hope (a DIFFERENT gauge)
FLOW_STATION_NAME = "FRASER RIVER AT HOPE"

HYDAT_DB = "/mnt/disk4/Hydat_sqlite3_20260116/Hydat.sqlite3"
HYDAT_VERSION = "Hydat_sqlite3_20260116"

DEM = ("/mnt/disk1/Hydrocraft_server/data/dem/dem_tiles_cache/"
       "Copernicus_DSM_COG_10_N49_00_W122_00_DEM.tif")
LULC = ("/mnt/disk1/Hydrocraft_server/data/landcover/"
        "AVHRR_1km_LANDCOVER_1981_1994.GLOBAL.tif")
MSWX = "/mnt/disk3/msxw/"
SFINCS_BIN = "/mnt/disk1/Hydrocraft_server/model/sfincs/bin/sfincs"

# The validated run's staged tree (domain + per-year forcing). Rebuilt by ensure_base()
# with the KI's own s1-s4 tools if it is absent; never rebuilt per eval.
BASE = Path("/mnt/disk1/Hydrocraft_server/outputs/sfincs_fraser_agassiz")

# Domain / run recipe — verbatim from the validated run (run_and_score_hydat_fraser.py).
BBOX = "-121.90,49.15,-121.42,49.40"
RES = 100.0
MAX_ELEV = 80.0
N_SRC = 25
SRC_SEARCH_M = 2500.0
OMP_THREADS = 8                            # as validated; fixed so results are reproducible
SFINCS_TIMEOUT_S = 360000

SPINUP_START = "{y}-02-15"
RUN_END = "{y}-08-31"
SCORE_START = "{y}-03-01"

# Vertical registration: ONE constant, fitted on the 2021 calibration year with the
# DEFAULT parameter vector in provenance run SFINCS_20260805T020658Z_648666 and applied
# unchanged to every candidate and every split (see the module docstring).
DATUM_OFFSET_M = -1.4035284032929418

# --------------------------------------------------------------------------- splits
CAL_YEAR, HOLDOUT_YEAR = 2021, 2022
SPLIT_YEARS = {"calibration": (CAL_YEAR,), "holdout": (HOLDOUT_YEAR,),
               "full": (CAL_YEAR, HOLDOUT_YEAR)}

# --------------------------------------------------------------------------- obs contract
# The observation envelope this driver ENFORCES before any metric is computed. Every
# field is read out of HYDAT and asserted; a mismatch exits nonzero with NO metrics file,
# so a changed or corrupted series for the SAME station can never be silently scored.
# Kept in sync with calibration.yaml `obs_contract`.
OBS_ENVELOPE = {
    2021: {"start": "2021-03-01", "end": "2021-08-24", "n_days": 177,
           "obs_min": 12.095000267028809, "obs_max": 16.482000350952148,
           "obs_mean": 13.986016930833374},
    2022: {"start": "2022-03-01", "end": "2022-08-08", "n_days": 161,
           "obs_min": 12.065999984741213, "obs_max": 16.799999237060547,
           "obs_mean": 14.245608643715427},
}
OBS_TOL_M = 1e-6            # HYDAT levels are float32-derived; 1e-6 m is far below a gauge count
OBS_MIN_LEVEL_M, OBS_MAX_LEVEL_M = 5.0, 30.0     # structural plausibility band for this reach

# --------------------------------------------------------------------------- parameters
# name -> (default, lo, hi). MUST stay in sync with calibration.yaml `parameters`.
PARAM_SPEC = {
    "manning_water_n":   (0.025, 0.018, 0.055),
    "manning_land_mult": (1.0,   0.75,  1.40),
    "q_mult":            (1.0,   0.90,  1.10),
    "precip_mult":       (1.0,   0.70,  1.30),
    "qinf":              (1.0,   0.10,  5.00),
    "advection":         (0,     0,     1),
}
INT_PARAMS = {"advection"}

# Manning class split. The LULC-derived sfincs.man carries exactly five discrete values
# (0.025 water / 0.030 / 0.035 / 0.040 / 0.100). Cells at the water value are the
# low-roughness conveyance class driven by `manning_water_n`; every other active cell is
# scaled by `manning_land_mult`. Masks are ALWAYS taken from the pristine BASE map, never
# from an already-injected one.
WATER_N_THRESHOLD = 0.0255

# Our own read-back gate, stricter than the kit's 1e-6 but above the float32 storage
# resolution of sfincs.man (~6e-8 relative), which is the binding term. Measured worst
# case across all 12 range bounds + the default and perturbed vectors: 4.3e-8.
READBACK_RTOL = 5e-7


# =========================================================================== helpers
class Fail(Exception):
    """Any condition that must produce NO metrics file and a non-zero exit."""


def log(msg):
    print(f"[calib_run] {msg}", flush=True)


def _load_ki_module(rel_path, name):
    p = TOOLS / rel_path
    if not p.is_file():
        raise Fail(f"KI tool missing: {p}")
    spec = importlib.util.spec_from_file_location(name, str(p))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_tool(script, args):
    cmd = [sys.executable, str(TOOLS / script)] + [str(a) for a in args]
    log("RUN " + " ".join(cmd))
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        tail = (p.stdout or "")[-1500:] + (p.stderr or "")[-3000:]
        raise Fail(f"{script} exited {p.returncode}\n{tail}")
    return p.stdout


# =========================================================================== observations
def _hydat():
    """HYDAT opened READ-ONLY through the KI's own connector (mode=ro&immutable=1), so
    scoring works on a read-only mount and can never write to the obs catalog."""
    m = _load_ki_module("s4_forcing/hydat_to_sfincs_boundary.py", "kdt_hydat_bc")
    return m, m.connect_hydat(HYDAT_DB)


def resolve_station(con, mod):
    """Resolve the SCORED station from HYDAT and assert its identity. Everything the
    declaration (`case_id` / `scored_obs`) later reports is derived from THIS row."""
    info = mod.station_info(con, OBS_STATION)
    if not info:
        raise Fail(f"HYDAT has no STATIONS row for {OBS_STATION}")
    checks = [
        ("station_id", info.get("station_id"), OBS_STATION, None),
        ("station_name", info.get("station_name"), OBS_STATION_NAME, None),
        ("lat", info.get("lat"), OBS_LAT, 1e-6),
        ("lon", info.get("lon"), OBS_LON, 1e-6),
        ("drainage_area_km2", info.get("drainage_area_km2"), OBS_AREA_KM2, 1e-6),
        ("datum_id", info.get("datum_id"), OBS_DATUM_ID, None),
        ("datum_name", info.get("datum_name"), OBS_DATUM_NAME, None),
    ]
    for field, got, want, tol in checks:
        if got is None:
            raise Fail(f"obs contract: STATIONS.{field} is None for {OBS_STATION}")
        if tol is None:
            if str(got) != str(want):
                raise Fail(f"obs contract: STATIONS.{field} = {got!r}, expected {want!r}")
        elif not math.isclose(float(got), float(want), rel_tol=0.0, abs_tol=tol):
            raise Fail(f"obs contract: STATIONS.{field} = {got!r}, expected {want!r}")
    resolved_case = f"{OBS_NETWORK}:{info['station_id']}"
    if resolved_case != CASE_ID:
        raise Fail(f"resolved case {resolved_case} != pinned TARGET CASE {CASE_ID}")
    return info, resolved_case


def load_obs_year(con, mod, year):
    """Daily observed stage for `year`'s scored window, with the full declared envelope
    ASSERTED (exact contiguous date set, count, min/max/mean, plausibility band)."""
    env = OBS_ENVELOPE.get(year)
    if env is None:
        raise Fail(f"no declared obs envelope for year {year}")
    d0 = dtm.datetime.strptime(env["start"], "%Y-%m-%d")
    d1 = dtm.datetime.strptime(env["end"], "%Y-%m-%d")
    raw = mod.daily_series(con, OBS_TABLE, "LEVEL", OBS_STATION, d0, d1)
    if not raw:
        raise Fail(f"HYDAT {OBS_TABLE} empty for {OBS_STATION} {env['start']}..{env['end']}")
    s = pd.Series(raw).sort_index()
    s.index = pd.DatetimeIndex(s.index)

    want_idx = pd.date_range(env["start"], env["end"], freq="D")
    if len(s) != env["n_days"] or len(want_idx) != env["n_days"]:
        raise Fail(f"obs contract {year}: {len(s)} observed days, declared {env['n_days']}")
    if not s.index.equals(want_idx):
        raise Fail(f"obs contract {year}: observed date set is not the declared gap-free "
                   f"daily index {env['start']}..{env['end']}")
    if not np.isfinite(s.values).all():
        raise Fail(f"obs contract {year}: non-finite observed level")
    if s.min() < OBS_MIN_LEVEL_M or s.max() > OBS_MAX_LEVEL_M:
        raise Fail(f"obs contract {year}: level outside the plausible band "
                   f"[{OBS_MIN_LEVEL_M}, {OBS_MAX_LEVEL_M}] m "
                   f"(got {s.min():.3f}..{s.max():.3f}) — a sentinel or a unit change")
    for field, got in (("obs_min", float(s.min())), ("obs_max", float(s.max())),
                       ("obs_mean", float(s.mean()))):
        want = env[field]
        if not math.isclose(got, want, rel_tol=0.0, abs_tol=OBS_TOL_M):
            raise Fail(f"obs contract {year}: {field} = {got!r}, declared {want!r}")
    return s


# =========================================================================== base inputs
BASE_STATIC = ("sfincs.dep", "sfincs.msk", "sfincs.ind", "sfincs.man")
BASE_PER_YEAR = ("sfincs.precip", "sfincs.src", "sfincs.dis", "sfincs.obs")


def _base_complete():
    if not (BASE / "domain" / "grid_info.json").is_file():
        return False
    for f in BASE_STATIC:
        if not (BASE / "domain" / f).is_file():
            return False
    for y in (CAL_YEAR, HOLDOUT_YEAR):
        for f in BASE_PER_YEAR:
            if not (BASE / f"run_{y}" / f).is_file():
                return False
    return True


def ensure_base():
    """ONE-TIME prepare: the domain and per-year forcing of the validated run. Reused by
    every eval; nothing here runs per candidate. A lock file makes concurrent evals safe."""
    if _base_complete():
        return BASE / "domain" / "grid_info.json"
    BASE.mkdir(parents=True, exist_ok=True)
    lock = BASE / ".calib_prepare.lock"
    for _ in range(3600):
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            break
        except FileExistsError:
            if _base_complete():
                return BASE / "domain" / "grid_info.json"
            time.sleep(5)
    else:
        raise Fail(f"timed out waiting for the prepare lock {lock}")
    try:
        for label, path in (("hydat", HYDAT_DB), ("dem", DEM), ("sfincs_binary", SFINCS_BIN),
                            ("mswx", MSWX), ("lulc", LULC)):
            if not Path(path).exists():
                raise Fail(f"required input unreachable: {label} = {path}")
        dom = BASE / "domain"
        dom.mkdir(parents=True, exist_ok=True)
        gi = dom / "grid_info.json"
        if not gi.is_file():
            run_tool("s1_domain/setup_sfincs_domain.py",
                     [f"--bbox={BBOX}", "--resolution", RES, "--buffer_m", 0,
                      "--output_dir", dom])
        if not (dom / "sfincs.dep").is_file():
            run_tool("s2_topobathy/build_sfincs_topobathy.py",
                     ["--grid_info", gi, "--dem_path", DEM, "--max_elev", MAX_ELEV,
                      "--outflow_value", 3, "--outflow_edges", "w", "--output_dir", dom])
        if not (dom / "sfincs.man").is_file():
            run_tool("s3_roughness/build_sfincs_roughness.py",
                     ["--grid_info", gi, "--lulc_path", LULC,
                      "--index_file", dom / "sfincs.ind", "--output_dir", dom])
        for y in (CAL_YEAR, HOLDOUT_YEAR):
            rd = BASE / f"run_{y}"
            rd.mkdir(parents=True, exist_ok=True)
            t0, t1 = SPINUP_START.format(y=y), RUN_END.format(y=y)
            if not (rd / "sfincs.precip").is_file():
                run_tool("s4_forcing/prepare_sfincs_rainfall.py",
                         ["--forcing_dir", MSWX, "--grid_info", gi, "--source", "mswx",
                          "--start_date", t0, "--end_date", t1, "--output_dir", rd])
            if not (rd / "sfincs.dis").is_file():
                for f in BASE_STATIC:
                    shutil.copy2(dom / f, rd / f)
                run_tool("s4_forcing/hydat_to_sfincs_boundary.py",
                         ["--hydat_db", HYDAT_DB, "--grid_info", gi,
                          "--flow_station", FLOW_STATION, "--obs_stations", OBS_STATION,
                          "--start_date", t0, "--end_date", t1, "--tref", t0,
                          "--topobathy_dir", rd, "--n_src", N_SRC,
                          "--src_search_m", SRC_SEARCH_M, "--output_dir", rd])
        if not _base_complete():
            raise Fail("prepare finished but the base tree is still incomplete")
        return BASE / "domain" / "grid_info.json"
    finally:
        try:
            os.unlink(lock)
        except OSError:
            pass


# =========================================================================== injection
def _read_f32(path):
    a = np.fromfile(str(path), dtype="<f4")
    if a.size == 0:
        raise Fail(f"empty binary map {path}")
    return a


def _read_table(path):
    a = np.loadtxt(str(path), dtype=np.float64, ndmin=2)
    if a.size == 0:
        raise Fail(f"empty table {path}")
    return a


def inject_manning(rd, base_man, water, water_n, land_mult):
    new = base_man.astype(np.float64)
    new[water] = float(water_n)
    new[~water] = new[~water] * float(land_mult)
    if not np.isfinite(new).all() or (new <= 0).any():
        raise Fail("injected Manning map has non-finite or non-positive values")
    new.astype("<f4").tofile(str(rd / "sfincs.man"))


def readback_manning(rd, base_man, water):
    got = _read_f32(rd / "sfincs.man").astype(np.float64)
    if got.size != base_man.size:
        raise Fail(f"sfincs.man read back {got.size} cells, expected {base_man.size}")
    uniq = np.unique(got[water])
    if uniq.size != 1:
        raise Fail(f"sfincs.man: water class carries {uniq.size} distinct values, expected 1")
    land_base = base_man[~water].astype(np.float64).sum()
    if land_base <= 0:
        raise Fail("sfincs.man: base land-class Manning sum is not positive")
    return float(uniq[0]), float(got[~water].sum() / land_base)


def inject_table(src_path, dst_path, mult, value_cols, value_fmt, time_fmt):
    base = _read_table(src_path)
    new = base.copy()
    new[:, value_cols] = base[:, value_cols] * float(mult)
    if not np.isfinite(new).all():
        raise Fail(f"injected table {dst_path.name} has non-finite values")
    with open(dst_path, "w") as fh:
        for row in new:
            fh.write(time_fmt % row[0] + " "
                     + " ".join(value_fmt % v for v in row[1:]) + "\n")


def readback_table_mult(base_path, run_path, value_cols):
    base = _read_table(base_path)
    got = _read_table(run_path)
    if got.shape != base.shape:
        raise Fail(f"{run_path.name} read back shape {got.shape}, expected {base.shape}")
    if not np.allclose(got[:, 0], base[:, 0], rtol=0.0, atol=1e-6):
        raise Fail(f"{run_path.name}: time column changed during injection")
    denom = float(base[:, value_cols].sum())
    if denom <= 0:
        raise Fail(f"{base_path.name}: base value sum is not positive — no scalable signal")
    return float(got[:, value_cols].sum()) / denom


def write_inp(rd, gi, year, qinf, advection):
    t0, t1 = SPINUP_START.format(y=year), RUN_END.format(y=year)
    run_tool("s6_config/generate_sfincs_inp.py",
             ["--grid_info", gi, "--topobathy_dir", rd,
              "--start_date", t0, "--end_date", t1,
              "--manning_file", rd / "sfincs.man",
              "--precip_file", rd / "sfincs.precip",
              "--src_file", rd / "sfincs.src",
              "--dis_file", rd / "sfincs.dis",
              "--obs_file", rd / "sfincs.obs",
              "--dtout", 86400, "--dthisout", 3600, "--dtmaxout", 0,
              "--zsini", 0.0, "--qinf", qinf, "--advection", int(advection),
              "--output_dir", rd])
    # The generator formats qinf as "%.2f", which would quantize the candidate. Re-write
    # the line at full float precision AFTER generation so nothing overwrites it.
    inp = rd / "sfincs.inp"
    lines = inp.read_text().splitlines()
    out, seen = [], False
    for ln in lines:
        if ln.split("=")[0].strip() == "qinf":
            out.append(f"qinf           = {float(qinf)!r}")
            seen = True
        else:
            out.append(ln)
    if not seen:
        raise Fail("generate_sfincs_inp.py wrote no qinf key — cannot inject infiltration")
    inp.write_text("\n".join(out) + "\n")


def read_inp(rd):
    keys = {}
    for ln in (rd / "sfincs.inp").read_text().splitlines():
        ln = ln.split("!")[0].strip()
        if "=" in ln:
            k, _, v = ln.partition("=")
            keys[k.strip()] = v.strip()
    return keys


# =========================================================================== run + score
def run_year(rd, gi, year, p, base_man, water):
    """Stage -> inject -> read back -> run -> health-gate one simulation year."""
    dom, src = BASE / "domain", BASE / f"run_{year}"
    rd.mkdir(parents=True, exist_ok=True)
    for f in ("sfincs.dep", "sfincs.msk", "sfincs.ind"):
        shutil.copy2(dom / f, rd / f)
    # sfincs.src carries the 25 snapped channel source POINTS that sfincs.dis feeds.
    # Omitting it makes SFINCS drop the entire fluvial boundary WITHOUT any error and
    # still exit 0 (commissioning 2026-08-09) — hence the copy AND the log gate below.
    for f in ("sfincs.obs", "sfincs.src"):
        shutil.copy2(src / f, rd / f)
    n_src = len([ln for ln in (rd / "sfincs.src").read_text().splitlines() if ln.strip()])
    if n_src != N_SRC:
        raise Fail(f"sfincs.src carries {n_src} source points, expected {N_SRC}")

    inject_manning(rd, base_man, water, p["manning_water_n"], p["manning_land_mult"])
    inject_table(src / "sfincs.dis", rd / "sfincs.dis", p["q_mult"],
                 slice(1, None), "%.10g", "%.0f")
    inject_table(src / "sfincs.precip", rd / "sfincs.precip", p["precip_mult"],
                 slice(1, None), "%.9f", "%.1f")
    write_inp(rd, gi, year, p["qinf"], p["advection"])

    water_n, land_mult = readback_manning(rd, base_man, water)
    q_mult = readback_table_mult(src / "sfincs.dis", rd / "sfincs.dis", slice(1, None))
    pr_mult = readback_table_mult(src / "sfincs.precip", rd / "sfincs.precip", slice(1, None))
    inp = read_inp(rd)
    if "qinf" not in inp or "advection" not in inp:
        raise Fail("sfincs.inp is missing qinf/advection after injection")
    for key, want in (("manningfile", "sfincs.man"), ("srcfile", "sfincs.src"),
                      ("disfile", "sfincs.dis"), ("precipfile", "sfincs.precip"),
                      ("obsfile", "sfincs.obs")):
        if inp.get(key) != want:
            raise Fail(f"sfincs.inp {key} = {inp.get(key)!r}, expected {want!r}; the "
                       "injected input is not the one SFINCS will read")
        if not (rd / want).is_file():
            raise Fail(f"sfincs.inp references {want} but it is not in the run directory "
                       "— SFINCS drops that forcing silently and still exits 0")
    applied = {"manning_water_n": water_n, "manning_land_mult": land_mult,
               "q_mult": q_mult, "precip_mult": pr_mult,
               "qinf": float(inp["qinf"]), "advection": int(float(inp["advection"]))}

    os.environ["OMP_NUM_THREADS"] = str(OMP_THREADS)
    run_tool("s7_execution/run_sfincs.py",
             ["--run_dir", rd, "--sfincs_binary", SFINCS_BIN,
              "--omp_threads", OMP_THREADS, "--timeout", SFINCS_TIMEOUT_S])

    health = gate_run_health(rd)
    try:
        (rd / "sfincs_map.nc").unlink()      # 13 MB per eval and never scored
    except OSError:
        pass
    return applied, health


def gate_run_health(rd):
    """FAIL-CLOSED. Every diagnostic below is one SFINCS/run_sfincs.py actually produces;
    a missing or None value raises instead of defaulting to a passing value."""
    summary_path = rd / "run_summary.json"
    if not summary_path.is_file():
        raise Fail("run health: run_summary.json was not written")
    summary = json.loads(summary_path.read_text())
    status = summary.get("status")
    if status is None:
        raise Fail("run health: run_summary.json has no `status`")
    if status != "success":
        raise Fail(f"run health: run_summary.json status = {status!r}")
    exit_code = summary.get("exit_code")
    if exit_code is None:
        raise Fail("run health: run_summary.json has no `exit_code`")
    warnings = summary.get("preflight_warnings")
    if warnings is None:
        raise Fail("run health: run_summary.json has no `preflight_warnings`")
    critical = [w for w in warnings if "CRITICAL" in str(w)]
    if critical:
        raise Fail(f"run health: CRITICAL preflight warning(s): {critical}")
    elapsed = summary.get("elapsed_seconds")
    if elapsed is None or not math.isfinite(float(elapsed)):
        raise Fail("run health: run_summary.json has no finite `elapsed_seconds`")

    log_path = rd / "sfincs.log"
    if not log_path.is_file():
        raise Fail("run health: sfincs.log was not written")
    log_txt = log_path.read_text(errors="replace")
    if "Simulation finished" not in log_txt:
        raise Fail("run health: sfincs.log does not report 'Simulation finished' "
                   "— the solver did not reach tstop")
    # SFINCS prints NaN only when the solver has blown up; a healthy log has no such token.
    if "nan" in log_txt.lower():
        raise Fail("run health: sfincs.log reports NaN — the solver went unstable")
    # SILENT-FORCING-LOSS GATE. SFINCS reports which forcings it actually switched on and
    # times them in the closing block. A missing srcfile drops the ENTIRE fluvial boundary
    # with no error and exit code 0 (commissioning 2026-08-09: stage bias went to -16 %
    # while every metric stayed finite). Each forcing this configuration declares must
    # therefore be confirmed present in the log, not assumed.
    for token, what in (("reading discharges", "the fluvial discharge boundary "
                                               "(sfincs.src/.dis)"),
                        ("Time in discharges", "the fluvial discharge boundary "
                                               "(no time was spent in it)"),
                        ("turning on precipitation", "precipitation forcing (sfincs.precip)"),
                        ("turning on spatially-uniform constant infiltration",
                         "constant infiltration (qinf)"),
                        ("reading observation points", "the his observation point (sfincs.obs)")):
        if token not in log_txt:
            raise Fail(f"run health: sfincs.log never reports {token!r} — {what} was not "
                       "active in the run that produced these results")
    if not (rd / "sfincs_his.nc").is_file():
        raise Fail("run health: sfincs_his.nc was not written")
    return {"exit_code": int(exit_code), "elapsed_seconds": float(elapsed),
            "simulation_finished": True, "preflight_warnings": list(warnings)}


def sim_daily_stage(rd):
    """Daily-mean simulated water surface elevation at the observation point, read with
    the KI's own his-file opener (h5netcdf fallback — dt_v016)."""
    p = str(TOOLS / "s8_postprocess")
    if p not in sys.path:
        sys.path.insert(0, p)
    from extract_sfincs_results import open_sfincs_nc

    ds = open_sfincs_nc(str(rd / "sfincs_his.nc"))
    try:
        var = next((c for c in ("point_zs", "zs", "point_zsm") if c in ds.variables), None)
        if var is None:
            raise Fail(f"no point_zs in sfincs_his.nc; vars={list(ds.variables)}")
        arr = np.asarray(ds[var].values, dtype=float)
        if arr.ndim > 1:
            arr = arr.reshape(arr.shape[0], -1)[:, 0]
        times = pd.to_datetime(np.asarray(ds["time"].values))
    finally:
        ds.close()
    s = pd.Series(arr, index=times)
    if not np.isfinite(s.values).all():
        raise Fail("run health: simulated point_zs contains non-finite values")
    if (np.abs(s.values) >= 9998).any():
        raise Fail("run health: simulated point_zs contains SFINCS fill values (>=9998) "
                   "— the observation point went dry or fell outside the active mask")
    out = s.resample("D").mean().dropna()
    if out.empty:
        raise Fail("run health: no daily-mean simulated stage could be formed")
    return out


# =========================================================================== main
def parse_params():
    pf = os.environ.get("KDT_CALIB_PARAMS")
    if not pf:
        raise Fail("KDT_CALIB_PARAMS is not set — this KI is runner-mode "
                   "(injection.mode: runner) and refuses to score an un-injected run")
    p = Path(pf)
    if not p.is_file():
        raise Fail(f"KDT_CALIB_PARAMS points at a missing file: {pf}")
    handed = json.loads(p.read_text())
    if not isinstance(handed, dict) or not handed:
        raise Fail("KDT_CALIB_PARAMS is not a non-empty JSON object")
    unknown = sorted(set(handed) - set(PARAM_SPEC))
    if unknown:
        raise Fail(f"unknown parameter name(s) {unknown}; this contract declares "
                   f"{sorted(PARAM_SPEC)}")
    values = {}
    for name, (default, lo, hi) in PARAM_SPEC.items():
        v = handed.get(name, default)          # a staged round may freeze a param out
        try:
            fv = float(v)
        except (TypeError, ValueError):
            raise Fail(f"parameter {name} = {v!r} is not numeric")
        if not math.isfinite(fv):
            raise Fail(f"parameter {name} = {v!r} is not finite")
        if fv < lo - 1e-12 or fv > hi + 1e-12:
            raise Fail(f"parameter {name} = {fv!r} is outside its declared range [{lo}, {hi}]")
        values[name] = int(round(fv)) if name in INT_PARAMS else fv
    return handed, values


def resolve_split():
    raw = os.environ.get("KDT_CALIB_SPLIT")
    s = (raw or "").strip().lower()
    if s in ("", "none", "full"):
        return "full"
    if s not in SPLIT_YEARS:
        raise Fail(f"unknown KDT_CALIB_SPLIT {raw!r}; expected calibration|holdout|full")
    return s


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    handed, p = parse_params()
    split = resolve_split()
    years = SPLIT_YEARS[split]
    log(f"split={split} years={list(years)} params={p}")

    gi = ensure_base()
    base_man = _read_f32(BASE / "domain" / "sfincs.man").astype(np.float64)
    water = base_man <= WATER_N_THRESHOLD
    if not water.any() or water.all():
        raise Fail("the base Manning map has no water/land split — the roughness "
                   "parameters would be unidentifiable")

    key = hashlib.sha1(json.dumps({k: f"{v:.12g}" for k, v in sorted(p.items())},
                                  sort_keys=True).encode()).hexdigest()[:12]
    eval_root = Path(args.workdir) / "_sfincs_evals" / f"{split}_{key}"
    shutil.rmtree(eval_root, ignore_errors=True)
    eval_root.mkdir(parents=True, exist_ok=True)

    mod, con = _hydat()
    try:
        station, resolved_case = resolve_station(con, mod)
        applied_all, health_all, frames = [], {}, []
        for y in years:
            rd = eval_root / f"run_{y}"
            applied, health = run_year(rd, gi, y, p, base_man, water)
            applied_all.append(applied)
            health_all[str(y)] = health

            sim = sim_daily_stage(rd)
            obs = load_obs_year(con, mod, y)
            idx = obs.index.intersection(sim.index)
            df = pd.DataFrame({"obs": obs.reindex(idx), "sim": sim.reindex(idx)}).dropna()
            env = OBS_ENVELOPE[y]
            if len(df) != env["n_days"]:
                raise Fail(f"{y}: {len(df)} paired days, declared {env['n_days']} — the "
                           "simulated record does not cover the whole scored window")
            df = df.assign(sim=df["sim"] + DATUM_OFFSET_M)
            df.rename_axis("date").reset_index().to_csv(
                eval_root / f"scored_{y}.csv", index=False, float_format="%.6f")
            frames.append(df)
    finally:
        con.close()

    # every year must have applied the SAME vector — otherwise the declaration is a fiction
    applied = applied_all[0]
    for other in applied_all[1:]:
        for k in applied:
            if not math.isclose(float(applied[k]), float(other[k]),
                                rel_tol=READBACK_RTOL, abs_tol=0.0) \
                    and float(applied[k]) != float(other[k]):
                raise Fail(f"parameter {k} differs between simulated years "
                           f"({applied[k]} vs {other[k]})")
    for name, want in p.items():
        got = applied[name]
        if name in INT_PARAMS:
            if int(got) != int(want):
                raise Fail(f"read-back {name}: applied {got} != requested {want}")
            continue
        if want == 0.0:
            if got != 0.0:
                raise Fail(f"read-back {name}: applied {got} != requested {want}")
        elif not math.isclose(float(got), float(want), rel_tol=READBACK_RTOL, abs_tol=0.0):
            raise Fail(f"read-back {name}: applied {got!r} != requested {want!r} "
                       f"(rel_tol {READBACK_RTOL}) — the value SFINCS reads is not the "
                       "one that was requested")

    paired = pd.concat(frames).sort_index()
    if len(paired) < 30:
        raise Fail(f"only {len(paired)} paired days — refusing to score")

    sys.path.insert(0, "/mnt/disk1/Hydrocraft_server/models/ki_tools_common")
    from ki_tools_common.metrics import all_metrics
    m = all_metrics(paired["obs"], paired["sim"], label=split,
                    meta={"unit": OBS_UNIT, "period_role": split,
                          "obs_source": f"HYDAT {OBS_STATION} {OBS_TABLE}"})
    for k in ("NSE", "KGE", "PBIAS", "r", "RMSE"):
        v = m.get(k)
        if v is None or not math.isfinite(float(v)):
            raise Fail(f"metric {k} is missing or non-finite ({v!r})")

    peak_bias = float((paired["sim"].max() - paired["obs"].max())
                      / paired["obs"].max() * 100.0)
    scored_obs = (f"{OBS_NETWORK} {station['station_id']} {station['station_name']} "
                  f"{OBS_TABLE} [{OBS_UNIT}] @ lat {station['lat']:.5f} "
                  f"lon {station['lon']:.5f} "
                  f"({station['datum_name']}) from {HYDAT_DB} "
                  f"[{HYDAT_VERSION}] — split={split}, years={list(years)}, "
                  f"{paired.index.min().date()}..{paired.index.max().date()}, "
                  f"n={len(paired)}")

    out = {
        "nse": float(m["NSE"]), "kge": float(m["KGE"]), "pbias": float(m["PBIAS"]),
        "r": float(m["r"]), "rmse": float(m["RMSE"]),
        # zsmax / point_snapshot reading of the same pairing: bias of the peak stage
        "pbias_peak_stage": peak_bias,
        "n_paired": int(len(paired)),
        "split": split,
        "__kdt__": {
            # EVERY key we were handed is echoed, including any a staged round froze at
            # its default; `all_applied_params` additionally reports the untouched rest.
            "applied_params": {k: applied[k] for k in handed},
            "case_id": resolved_case,
            "scored_obs": scored_obs,
            "all_applied_params": applied,
            "datum_offset_m": DATUM_OFFSET_M,
            "datum_offset_source": ("constant fitted on the 2021 calibration year with the "
                                    "DEFAULT vector in provenance run "
                                    "SFINCS_20260805T020658Z_648666; PINNED, never refit"),
            "obs_contract": "pinned",
            "obs_source_path": HYDAT_DB,
            "obs_station": {k: station[k] for k in sorted(station)},
            "sim_source_paths": [str(eval_root / f"run_{y}" / "sfincs_his.nc") for y in years],
            "scored_series_paths": [str(eval_root / f"scored_{y}.csv") for y in years],
            "years": [int(y) for y in years],
            "period": [str(paired.index.min().date()), str(paired.index.max().date())],
            "run_health": health_all,
            "eval_dir": str(eval_root),
        },
    }
    tmp = Path(str(args.out) + ".tmp")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(json.dumps(out, indent=2, default=str))
    os.replace(str(tmp), str(args.out))
    log(f"wrote {args.out}: pbias={out['pbias']:.6f} nse={out['nse']:.6f} "
        f"kge={out['kge']:.6f} n={out['n_paired']} split={split}")


if __name__ == "__main__":
    try:
        main()
    except Fail as exc:
        print(f"[calib_run] FAIL: {exc}", file=sys.stderr, flush=True)
        sys.exit(1)
    except Exception:                                    # noqa: BLE001
        traceback.print_exc()
        sys.exit(2)
