#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Programmatic run+score of ONE CRHM calibration candidate.  NOT an agent.

    python tools/calib_run.py --workdir <wd> --out <metrics.json>

TARGET CASE (pinned — this file scores THIS region/obs and no other)
------------------------------------------------------------------------------
    case_id      GEO:49.4,120.4
    obs          ESA Snow_cci MERGED SWE v2.0 (GENUINE SWE, mm), clipped and
                 area-averaged over the Hulunbuir open-steppe region polygon
                 120.0-120.8 E / 49.1-49.7 N (48 cells at 0.1 deg)
                 source granules  KISSPATH_DATA/benchmarks/snowcci_swe
                 region-mean cache outputs/hulunbuir_steppe/obs_snowcci_region_mean.csv
    quantity     SWE (dag var SWE, obs_shape regional_aggregate_time_series,
                 determining metric NSE, gate-valid families
                 magnitude_accuracy + temporal_pattern_match)
    provenance   CRHM_20260726T164031Z_286796  (held-out monthly-mean
                 NSE -0.41821090337699984 / KGE 0.1026 / r 0.8233 / PBIAS +57.00,
                 n = 47 months, PBSM activity gate FAIL frac_subl 0.0305)

This is a SNOW-WATER-EQUIVALENT case.  It is NOT discharge, it is NOT the
Yingluoxia / upper Heihe streamflow case, and it is NOT the Bow/Marmot mountain
worked examples that SKILL.md also documents.

The scored obs is NOT configurable.  There is no environment variable that can
redirect scoring to another site: the Snow_cci directory, the region bounding
box, the region-mean CSV and the screen JSON are module constants, and the
``case_id`` echoed in ``__kdt__`` is DERIVED from the latitude/longitude and
``region_bbox`` recorded in the prepared hru_config.json — the very file whose
HRU areas weight the simulated SWE — then checked against the pinned target.  If
that file ever described a different domain, the derived case_id would stop
matching and this script exits nonzero instead of quietly scoring elsewhere.
``scored_obs`` is likewise assembled from the obs path, the bbox and the record
count actually read, so the declaration cannot diverge from what was scored.

Contract (calibration_kit/CALIBRATION_YAML_SCHEMA.md, injection.mode: runner)
------------------------------------------------------------------------------
CRHM consumes a single monolithic ``.prj`` deck whose per-HRU parameter blocks
are whitespace-separated value rows under ``<module> <param> <min to max>``
headers, and the KI REGENERATES that deck from hru_config + modules.json +
derived_params on every run (tools/s4_parameter_config/create_prj_file.py).  A
value written into basin.prj before the run would be overwritten by the
regeneration, and no generic address kind points at "the 3rd, 8th, 11th and 14th
field of the row under `pbsm Ht`".  => runner mode.  The kit does NOT touch the
inputs; this script:

  1. reads the candidate vector from the JSON at env ``KDT_CALIB_PARAMS``;
  2. INJECTS it the model's own way — expands each zone-scoped parameter to the
     per-HRU vector CRHM needs and hands it to the KI's OWN create_prj_file.py
     via ``--param_overrides``, i.e. AFTER (in fact, as part of) the deck
     regeneration, so nothing can overwrite it;
  3. READS every value BACK out of the generated basin.prj — the exact file the
     CRHM binary opens — and re-collapses the per-HRU rows to the zone-scoped
     names; any write/read disagreement => exit nonzero with NO metrics file;
  4. runs the REAL model — the CRHM binary via the KI's run_crhm.py — over the
     same domain, forcing and period the validated run used, and parses it with
     the KI's parse_crhm_output.py.  The model is never reimplemented here;
  5. scores area-weighted region-mean SWE against the Snow_cci region mean with
     ki_tools_common.metrics.all_metrics (the scorer the dag gates on), at the
     aggregation screen_swe_obs.py rules admissible;
  6. emits ``{"nse":..,"kge":..,"pbias":..,"r":..,"__kdt__":{...}}``, echoing
     EVERY key it was handed (staged-frozen ones included).

Any failure at any stage: write nothing, exit nonzero.  A missing metrics file is
scored +inf by the kit — never a fake pass.  ``--out`` is deleted before any work
begins, so a failed candidate can never be read as a stale success, and the final
write is atomic (tmp + os.replace) so a kill cannot leave a truncated JSON.

WHAT IS *NOT* CALIBRATABLE HERE (SKILL.md HARD RULE, enforced below)
------------------------------------------------------------------------------
``obs ClimChng_precip`` and ``obs obs_elev`` are LOCKED at 1.0 and at the CMFD
source-cell elevation (663 m).  SWE is the scored MASS STATE, so those two knobs
write the answer directly — tuning them against SWE is fabrication, and it is the
'compensating-errors calibration' hazard dag.yaml already names.  They are held
at the validated values in ``FIXED_OVERRIDES`` and are refused as candidate
parameter names by the unknown-parameter guard; ``assert_forcing_knobs_locked()``
re-reads them out of the generated deck every eval and aborts if either moved.

OBS ENVELOPE ENFORCEMENT
------------------------------------------------------------------------------
Everything calibration.yaml's ``identity.obs_envelope`` declares is READ and
ASSERTED before a metric is computed: the CSV columns, the exact record count and
first/last date, the mean / p95 / max / min / sum of the series, the all-cells-
valid retrieval fraction, the 48-cell 0.1 deg region grid, a live spot-check of
three dates straight out of the Snow_cci granules, and the screen_swe_obs.py
verdict (mass_inconsistent_pct, threshold, daily admissibility, knob lock) that
decides the scoring aggregation.  A changed or corrupted series for the SAME
region therefore cannot be silently scored.

Splits (env ``KDT_CALIB_SPLIT``)
--------------------------------
CRHM is deterministic given a parameter vector, so every split simulates the SAME
window (2002-01-01..2014-12-31 with 2002 as spin-up) and differs ONLY in which
dates are scored — the calibration score is never confounded by a shorter warm-up:

  calibration : score 2003-01-01..2008-12-31   (6 yr)
  holdout     : score 2009-01-01..2014-12-31   (6 yr, never seen by the optimizer)
  (unset)     : score 2003-01-01..2014-12-31   (both)

Periods are inherited verbatim from the validated run (CAL / VAL in
run_and_score_hulunbuir_pbsm.py); the held-out block is the one whose monthly
NSE -0.4182 is the prior validated metric.

Cost
----
~11-13 s wall per eval (CRHM binary ~6.5 s for 13 yr x 3-hourly x 15 HRUs, parse
~2 s, deck build + score ~2 s).  Domain delineation, module selection, derived
parameters, the 13-year CMFD .obs and the Snow_cci region-mean cache are one-time
PREPARE steps done by the validated run; this script never rebuilds them.
"""
from __future__ import annotations

# dt_v010: netCDF4's bundled libhdf5 MUST initialise before h5py's (which pandas/
# xarray pull in through their entrypoint scan) or every nc_open in this process
# dies with OSError -101.  This import stays FIRST, above pandas.
import netCDF4  # noqa: E402  (import order is load-bearing)

import argparse  # noqa: E402
import glob  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

os.environ.setdefault("HDF5_USE_FILE_LOCKING", "FALSE")

# ---------------------------------------------------------------------------
# Paths.  The KI's OWN tools are reused verbatim; the model is never
# reimplemented.  ki_tools_common is pinned to its CANONICAL checkout: a stale
# copy shipped under a kdt-release tree has shadowed it before, and a different
# all_metrics is a different number.
# ---------------------------------------------------------------------------
KI = Path("KISSPATH_KI_ROOT/CRHM/knowledge_infrastructure")
TOOLS = KI / "tools"
WORK = KI / "outputs" / "hulunbuir_steppe"
CRHM_EXE = Path("KISSPATH_KI_ROOT/CRHM/bin/crhm")
KI_TOOLS_COMMON_ROOT = "KISSPATH_KI_TOOLS_COMMON"

sys.path.insert(0, KI_TOOLS_COMMON_ROOT)

# ---------------------------------------------------------------------------
# TARGET CASE — pinned constants.  Nothing below is read from the environment.
# ---------------------------------------------------------------------------
TARGET_CASE_ID = "GEO:49.4,120.4"
TARGET_LAT, TARGET_LON = 49.4, 120.4
BBOX = (120.0, 49.1, 120.8, 49.7)          # lon_min, lat_min, lon_max, lat_max
SNOWCCI_DIR = Path("KISSPATH_DATA/benchmarks/snowcci_swe")
OBS_CSV = WORK / "obs_snowcci_region_mean.csv"
SCREEN_JSON = WORK / "swe_obs_screen.json"
OBS_ID = "snowcci_swe"
OBS_UNIT = "mm"

# Prepared, read-only artifacts of the validated Hulunbuir run.  NONE is rebuilt.
HRU_CONFIG = WORK / "crhm" / "hru" / "hru_config.json"
MODULES_JSON = WORK / "crhm" / "modules.json"
DERIVED_JSON = WORK / "crhm" / "derived_params.json"
BASIN_OBS = WORK / "crhm" / "basin.obs"

# ---------------------------------------------------------------------------
# obs_envelope — every field calibration.yaml declares, asserted below.
# Measured 2026-08-03 from the prepared cache and re-derived live from the
# Snow_cci granules for the three SPOT_CHECK dates.
# ---------------------------------------------------------------------------
OBS_ENVELOPE = {
    "columns": ["date", "obs_swe_mm", "valid_frac"],
    "n_records": 2580,
    "n_valid": 2580,
    "first_date": "2003-01-01",
    "last_date": "2014-12-31",
    "mean_mm": 12.283955,
    "p95_mm": 30.544792,
    "max_mm": 42.020833,
    "min_mm": 0.0,
    "sum_mm": 31692.604167,
    "min_valid_frac": 1.0,
    "region_cells": 48,               # 6 lat x 8 lon at 0.1 deg over BBOX
}
OBS_STAT_RTOL = 1e-6
SPOT_CHECK = {                        # date -> region-mean SWE (mm) in the cache
    "20030115": 16.458333333333332,
    "20091220": 17.937500000000000,
    "20140301": 28.770833333333330,
}

# screen_swe_obs.py verdict that decides the scoring aggregation and the knob lock.
SCREEN_ENVELOPE = {
    "mass_inconsistent_pct": 4.32,
    "threshold_pct": 2.0,
    "daily_scoring_admissible": False,
    "forcing_knobs_locked": True,
    "shallow_snow_regime": True,
}

# ---------------------------------------------------------------------------
# Domain / deck constants, inherited verbatim from the validated run.
# ---------------------------------------------------------------------------
NHRU = 15
START_YEAR, END_YEAR = 2002, 2014     # 2002 = spin-up, never scored
SPLITS = {
    "calibration": ("2003-01-01", "2008-12-31"),
    "holdout":     ("2009-01-01", "2014-12-31"),
    "_both":       ("2003-01-01", "2014-12-31"),
}
MIN_DAYS_PER_MONTH = 10               # a month must be observed to be scored
LOCKED_OBS_ELEV = 663                 # CMFD source-cell elevation; SKILL.md HARD RULE
LOCKED_CLIMCHNG_PRECIP = 1.0          # SWE is the scored mass state -> LOCKED at 1.0
FOREST_FETCH_M = 300.0                # inert (inhibit_bs = 1) but written for completeness
FOREST_HT_M = 15.0                    # RULE 2: canopy HRUs keep their canopy height
CANOPY_HT_MIN_M = 2.0                 # >= this => canopy HRU => inhibit_bs = 1

# Zone -> 1-based HRU ids.  ASSERTED against hru_config.json every eval, so a
# rebuilt domain with different land cover cannot be silently calibrated.
ZONES = {
    "crop_stubble":     [1, 6, 9, 12],
    "open_prairie":     [3, 8, 11, 14],
    "bare_ground":      [4, 5],
    "deciduous_forest": [2, 7, 10, 13, 15],
}
BLOWING_SNOW_ZONES = ("crop_stubble", "open_prairie", "bare_ground")

# ---------------------------------------------------------------------------
# name -> default.  MUST stay in sync with the `parameters:` block of
# calibration.yaml: a name present there and absent here (or vice-versa) makes
# EVERY eval — the default vector included — die in the unknown-parameter guard,
# which the kit reads as a screen with no finite losses at all.
#
# The defaults ARE the validated configuration: fetch/Ht reproduce
# derive_parameters.py + the SKILL.md PBSM RULE-1 winter heights, and N_S / A_S /
# Qe_subl_from_SWE are CRHM's own declared defaults (Classpbsm.cpp:122-124,
# Classebsm.cpp:81), which the validated deck left unwritten.  Writing them
# explicitly at their default therefore reproduces that run bit-for-bit, so a
# staged round that freezes a parameter holds it at a physical, in-range value.
# ---------------------------------------------------------------------------
DEFAULTS = {
    "fetch_stubble":     1000.0,
    "fetch_open_short":  2000.0,
    "Ht_stubble":        0.10,
    "Ht_grass":          0.05,
    "Ht_bare":           0.01,
    "N_S":               320.0,
    "A_S":               0.003,
    "Qe_subl_from_SWE":  0,
}
INTEGER_PARAMS = {"Qe_subl_from_SWE"}

# Parameters that are LOCKED by the SKILL.md HARD RULE and may never be handed in.
FORBIDDEN_PARAMS = {"ClimChng_precip", "obs_elev", "ClimChng_t", "catchadjust",
                    "precip_elev_adj", "lapse_rate"}

RTOL = 1e-9        # our own write->read agreement; the kit re-checks at its own rtol

# Display_Variable set: SWE (the scored state) plus the PBSM sink terms and the
# snowfall denominator the dag's "sublimation 15-40% of snowfall in prairie"
# activity gate needs.  Display_Variable selects OUTPUT ONLY and cannot change the
# physics; the reduced set exists purely to keep the per-eval parse cheap, and the
# default vector is verified to reproduce the validated metric exactly.
OUTPUT_GROUPS = [("pbsm", "SWE"), ("pbsm", "cumSubl"), ("pbsm", "cumDrift"),
                 ("pbsm", "cumDriftIn"), ("obs", "cumhru_snow")]


class Fail(Exception):
    """Anything that must produce NO metrics file."""


def die(msg: str, code: int = 1):
    print(f"[calib_run] FAIL: {msg}", file=sys.stderr, flush=True)
    sys.exit(code)


def _close(a, b) -> bool:
    return math.isclose(float(a), float(b), rel_tol=RTOL, abs_tol=1e-12)


def _rel_ok(got, want, rtol=OBS_STAT_RTOL) -> bool:
    return math.isclose(float(got), float(want), rel_tol=rtol, abs_tol=1e-9)


def run_tool(script: Path, args, cwd: Path) -> str:
    """Invoke a KI tool as a subprocess and fail LOUDLY (never fail-open)."""
    cmd = [sys.executable, str(script)] + [str(a) for a in args]
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=str(cwd))
    if p.returncode != 0:
        raise Fail(f"{script.name} rc={p.returncode}\n"
                   f"STDOUT:\n{p.stdout[-3000:]}\nSTDERR:\n{p.stderr[-3000:]}")
    return p.stdout


# ---------------------------------------------------------------------------
# 0.  prepared artifacts + case identity
# ---------------------------------------------------------------------------
def check_prepared():
    required = [HRU_CONFIG, MODULES_JSON, DERIVED_JSON, BASIN_OBS, OBS_CSV,
                SCREEN_JSON, CRHM_EXE, SNOWCCI_DIR]
    missing = [str(p) for p in required if not p.exists()]
    if missing:
        raise Fail(
            f"prepared artifact(s) absent: {missing}.  Rebuild them ONCE with the "
            f"KI's prepare steps (create_hru_config -> select_modules -> "
            f"derive_parameters -> convert_vic_to_obs -> screen_swe_obs); "
            f"calib_run.py never rebuilds inputs per eval.")
    if not os.access(CRHM_EXE, os.X_OK):
        raise Fail(f"CRHM binary {CRHM_EXE} is not executable")


def resolve_case() -> tuple[str, dict]:
    """Read the domain THIS eval actually weights its SWE with, out of the prepared
    hru_config.json, and DERIVE the case_id from it — so the ``__kdt__.case_id``
    declaration cannot diverge from the domain that was scored.  The derived id is
    then checked against the pinned TARGET_CASE_ID; a mismatch aborts."""
    with open(HRU_CONFIG, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
    lat, lon = float(cfg["latitude"]), float(cfg["longitude"])
    case_id = f"GEO:{lat:g},{lon:g}"
    if case_id != TARGET_CASE_ID:
        raise Fail(f"{HRU_CONFIG} describes {case_id}, not the target case "
                   f"{TARGET_CASE_ID}; refusing to score a different site")
    bbox = tuple(round(float(v), 6) for v in cfg["region_bbox"])
    if bbox != BBOX:
        raise Fail(f"{HRU_CONFIG} region_bbox {bbox} != the target region {BBOX}; "
                   f"the obs polygon and the model domain would not be the same area")
    if int(cfg["nhru"]) != NHRU:
        raise Fail(f"{HRU_CONFIG} has nhru={cfg['nhru']}, expected {NHRU}")
    # zone map must be exactly the validated land-cover layout
    zones: dict[str, list[int]] = {}
    for h in cfg["hrus"]:
        zones.setdefault(str(h["land_cover_name"]), []).append(int(h["hru_id"]))
    zones = {k: sorted(v) for k, v in zones.items()}
    if zones != {k: sorted(v) for k, v in ZONES.items()}:
        raise Fail(f"land-cover zone map changed: {zones} != {ZONES}; the "
                   f"zone-scoped parameters would address different HRUs")
    for h in cfg["hrus"]:
        canopy = float(h.get("veg_height_m", 0.0)) >= CANOPY_HT_MIN_M
        if canopy != (str(h["land_cover_name"]) == "deciduous_forest"):
            raise Fail(f"HRU {h['hru_id']} canopy classification changed "
                       f"(veg_height_m={h.get('veg_height_m')}, "
                       f"cover={h['land_cover_name']}); inhibit_bs would move")
    return case_id, cfg


def load_prepared_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# 1.  the observation — read read-only, and every declared field ASSERTED
# ---------------------------------------------------------------------------
def load_screen() -> tuple[str, dict]:
    """screen_swe_obs.py's verdict.  It decides BOTH the scoring aggregation and
    whether the forcing knobs may move at all, so it is enforced, not assumed."""
    with open(SCREEN_JSON, "r", encoding="utf-8") as fh:
        s = json.load(fh)
    if os.path.abspath(str(s.get("obs_csv", ""))) != os.path.abspath(str(OBS_CSV)):
        raise Fail(f"{SCREEN_JSON} screened {s.get('obs_csv')!r}, not the scored "
                   f"series {OBS_CSV}")
    for k, want in SCREEN_ENVELOPE.items():
        got = s.get(k)
        if got is None:
            raise Fail(f"{SCREEN_JSON} is missing declared field {k!r}")
        if isinstance(want, bool):
            if bool(got) is not want:
                raise Fail(f"{SCREEN_JSON} {k}={got!r}, declared {want!r}")
        elif not _rel_ok(got, want, rtol=1e-6):
            raise Fail(f"{SCREEN_JSON} {k}={got!r}, declared {want!r}")
    # aggregation is DERIVED from the screen, not hardcoded
    agg = "daily" if bool(s["daily_scoring_admissible"]) else "monthly_mean"
    return agg, s


def load_obs() -> tuple[pd.Series, str, dict]:
    """Snow_cci region-mean daily SWE (mm).  The CSV is an immutable prepared
    artifact and is opened READ-ONLY.  Every field calibration.yaml's obs_envelope
    declares is asserted, and three dates are re-derived live from the Snow_cci
    granules so the cache cannot silently drift from its source.

    Returns the series, a scored_obs label built from what was ACTUALLY read, and
    the measured envelope."""
    with open(OBS_CSV, "r", encoding="utf-8") as fh:          # read-only
        o = pd.read_csv(fh, parse_dates=["date"])
    if list(o.columns) != OBS_ENVELOPE["columns"]:
        raise Fail(f"{OBS_CSV} columns {list(o.columns)} != declared "
                   f"{OBS_ENVELOPE['columns']}")
    if len(o) != OBS_ENVELOPE["n_records"]:
        raise Fail(f"{OBS_CSV} has {len(o)} records, declared "
                   f"{OBS_ENVELOPE['n_records']}")
    o = o.set_index("date").sort_index()
    v = o["obs_swe_mm"].dropna()
    measured = {
        "n_valid": int(len(v)),
        "first_date": str(o.index.min().date()),
        "last_date": str(o.index.max().date()),
        "mean_mm": float(v.mean()), "p95_mm": float(v.quantile(0.95)),
        "max_mm": float(v.max()), "min_mm": float(v.min()),
        "sum_mm": float(v.sum()), "min_valid_frac": float(o["valid_frac"].min()),
    }
    for k in ("first_date", "last_date"):
        if measured[k] != OBS_ENVELOPE[k]:
            raise Fail(f"{OBS_CSV} {k}={measured[k]}, declared {OBS_ENVELOPE[k]}")
    if measured["n_valid"] != OBS_ENVELOPE["n_valid"]:
        raise Fail(f"{OBS_CSV} has {measured['n_valid']} valid days, declared "
                   f"{OBS_ENVELOPE['n_valid']}")
    for k in ("mean_mm", "p95_mm", "max_mm", "sum_mm", "min_valid_frac"):
        if not _rel_ok(measured[k], OBS_ENVELOPE[k]):
            raise Fail(f"{OBS_CSV} {k}={measured[k]!r}, declared {OBS_ENVELOPE[k]!r}")
    if abs(measured["min_mm"] - OBS_ENVELOPE["min_mm"]) > 1e-9:
        raise Fail(f"{OBS_CSV} min_mm={measured['min_mm']!r}, declared "
                   f"{OBS_ENVELOPE['min_mm']!r}")

    n_cells = spot_check_snowcci()
    measured["region_cells"] = n_cells
    label = (f"{OBS_ID}:ESA Snow_cci merged SWE v2.0 ({OBS_UNIT}) region mean over "
             f"bbox {BBOX[0]}-{BBOX[2]}E / {BBOX[1]}-{BBOX[3]}N "
             f"({n_cells} cells @0.1deg), {measured['n_valid']} daily records "
             f"{measured['first_date']}..{measured['last_date']} @ {OBS_CSV} "
             f"(granules: {SNOWCCI_DIR})")
    return v, label, measured


def spot_check_snowcci() -> int:
    """Re-derive the region mean for three dates straight out of the Snow_cci
    granules and require the cache to match.  netCDF4.Dataset defaults to mode 'r'
    (read-only), so this works on a read-only mount.  Flag values -30/-20/-10/-1
    are masked; 0 is a real observation of zero SWE and is kept."""
    n_cells = None
    for stamp, want in SPOT_CHECK.items():
        files = sorted(glob.glob(str(SNOWCCI_DIR / f"{stamp}*.nc")))
        if not files:
            raise Fail(f"no Snow_cci granule for {stamp} under {SNOWCCI_DIR}")
        ds = netCDF4.Dataset(files[0], "r")            # read-only
        try:
            lat, lon = ds["lat"][:], ds["lon"][:]
            ii = np.where((lat >= BBOX[1]) & (lat <= BBOX[3]))[0]
            jj = np.where((lon >= BBOX[0]) & (lon <= BBOX[2]))[0]
            a = np.asarray(ds["swe"][0, ii.min():ii.max() + 1,
                                     jj.min():jj.max() + 1], dtype=float)
        finally:
            ds.close()
        if n_cells is None:
            n_cells = int(a.size)
            if n_cells != OBS_ENVELOPE["region_cells"]:
                raise Fail(f"Snow_cci region grid has {n_cells} cells over {BBOX}, "
                           f"declared {OBS_ENVELOPE['region_cells']}")
        ok = a >= 0
        got = float(a[ok].mean()) if ok.any() else float("nan")
        if not _rel_ok(got, want, rtol=1e-9):
            raise Fail(f"Snow_cci granule {stamp}: region mean {got!r} != cached "
                       f"{want!r}; {OBS_CSV} no longer matches its source")
    return int(n_cells)


# ---------------------------------------------------------------------------
# 2.  injection — expand zone-scoped params to the per-HRU vectors CRHM needs
# ---------------------------------------------------------------------------
def zone_vector(per_zone: dict, default=None) -> list:
    """1-based zone map -> a length-NHRU vector in HRU order."""
    v: list = [default] * NHRU
    for zone, ids in ZONES.items():
        if zone not in per_zone:
            continue
        for hid in ids:
            v[hid - 1] = per_zone[zone]
    if any(x is None for x in v):
        raise Fail("zone expansion left an HRU unset")
    return v


def build_overrides(p: dict) -> dict:
    """Every override create_prj_file.py is handed for this candidate.

    The FIXED block is copied verbatim from the validated run's make_overrides():
    the LOCKED forcing knobs (obs_elev / ClimChng_precip), the RULE-2 inhibit_bs
    mask, and the Soil/Netroute stores (which do not touch SWE and exist only so
    the water balance closes).  Only the eight calibrated names below vary."""
    fetch = zone_vector({"crop_stubble": float(p["fetch_stubble"]),
                         "open_prairie": float(p["fetch_open_short"]),
                         "bare_ground": float(p["fetch_open_short"]),
                         "deciduous_forest": FOREST_FETCH_M})
    ht = zone_vector({"crop_stubble": float(p["Ht_stubble"]),
                      "open_prairie": float(p["Ht_grass"]),
                      "bare_ground": float(p["Ht_bare"]),
                      "deciduous_forest": FOREST_HT_M})
    inhibit = zone_vector({z: (1 if z == "deciduous_forest" else 0) for z in ZONES})
    n = NHRU
    return {
        # ---- LOCKED by the SKILL.md HARD RULE (never candidate parameters) ----
        "obs obs_elev": LOCKED_OBS_ELEV,
        "obs ClimChng_flag": [1] * n,
        "obs ClimChng_precip": [LOCKED_CLIMCHNG_PRECIP] * n,
        # ---- calibrated blowing-snow parameterisation -------------------------
        "pbsm fetch": fetch,
        "pbsm Ht": ht,
        "pbsm inhibit_bs": inhibit,
        "pbsm N_S": [float(p["N_S"])] * n,
        "pbsm A_S": [float(p["A_S"])] * n,
        "ebsm Qe_subl_from_SWE": [int(round(float(p["Qe_subl_from_SWE"])))] * n,
        # ---- inert for SWE; present so the water balance closes ---------------
        "Soil gw_max": [600] * n, "Soil gw_init": [250] * n,
        "Soil gw_K": [0.6] * n, "Soil soil_gw_K": [3.0] * n,
        "Soil rechr_ssr_K": [1.0] * n, "Soil lower_ssr_K": [2.0] * n,
        "Soil soil_ssr_runoff": [1] * n,
        "Netroute Kstorage": [10.0] * n, "Netroute Lag": [24.0] * n,
        "Netroute runKstorage": [4.0] * n, "Netroute runLag": [12.0] * n,
        "Netroute ssrKstorage": [6.0] * n, "Netroute ssrLag": [24.0] * n,
        "Netroute gwKstorage": [50] * n, "Netroute gwLag": [500] * n,
    }


def build_deck(p: dict, wd: Path) -> Path:
    """Regenerate basin.prj through the KI's OWN create_prj_file.py with this
    candidate's overrides, then validate it with the KI's validate_prj.py.

    Injection happens INSIDE the regeneration, so nothing downstream can
    overwrite it.  create_prj_file.py rejects any value outside a parameter's
    declared <min to max> with a hard error rather than letting CRHM clamp it
    silently (dt_006), so an out-of-range candidate fails CLOSED here."""
    prj = wd / "basin.prj"
    ovr = wd / "param_overrides.json"
    ovr.write_text(json.dumps(build_overrides(p), indent=1))
    idx = " ".join(str(i) for i in range(1, NHRU + 1))
    output_vars = ",".join(f"{mod} {var} {idx}" for mod, var in OUTPUT_GROUPS)
    run_tool(TOOLS / "s4_parameter_config" / "create_prj_file.py",
             ["--hru_config", HRU_CONFIG, "--module_chain", MODULES_JSON,
              "--obs_path", BASIN_OBS,
              "--start_date", f"{START_YEAR} 1 1", "--end_date", f"{END_YEAR} 12 31",
              "--output_path", prj, "--output_vars", output_vars,
              "--derived_params", DERIVED_JSON, "--param_overrides", ovr], cwd=wd)
    run_tool(TOOLS / "s4_parameter_config" / "validate_prj.py",
             ["--prj_path", prj], cwd=wd)
    if not prj.exists() or prj.stat().st_size == 0:
        raise Fail("create_prj_file.py produced no deck")
    return prj


_HDR = re.compile(r"^(\S+)\s+(\S+)\s+<[^>]*>\s*$")


def read_deck_params(prj: Path) -> dict:
    """Parse the Parameters section of the deck the CRHM binary actually opens.

    Returns {"<module> <param>": [float, ...]}.  This is a read of the EFFECTIVE
    ARTIFACT, never an echo of the request."""
    out: dict[str, list[float]] = {}
    key = None
    section = None
    with open(prj, "r", encoding="utf-8", errors="replace") as fh:   # read-only
        lines = fh.read().splitlines()
    for raw in lines:
        s = raw.strip()
        if s.endswith(":") and s[:-1] in ("Parameters", "Dimensions", "Modules",
                                          "Dates", "Observations", "Macros",
                                          "Initial_State", "Final_State",
                                          "Summary_period", "Display_Variable",
                                          "Display_Observation"):
            section = s[:-1]
            key = None
            continue
        if section != "Parameters" or not s or s.startswith("#"):
            continue
        m = _HDR.match(s)
        if m:
            key = f"{m.group(1)} {m.group(2)}"
            out[key] = []
            continue
        if key is not None:
            try:
                out[key].extend(float(x) for x in s.split())
            except ValueError:
                raise Fail(f"unparsable value row under {key!r} in {prj}: {s!r}")
    if not out:
        raise Fail(f"no Parameters section parsed out of {prj}")
    return out


def read_back(prj: Path, wanted: dict) -> dict:
    """Re-collapse the per-HRU rows of the generated deck to the zone-scoped
    parameter names and return what the model will ACTUALLY use.  A zone whose
    HRUs do not all carry one value is a mis-injection and fails closed."""
    deck = read_deck_params(prj)

    def zone_value(key: str, zone: str) -> float:
        vals = deck.get(key)
        if vals is None:
            raise Fail(f"{prj} has no {key!r} block to read back")
        if len(vals) != NHRU:
            raise Fail(f"{prj} {key!r} has {len(vals)} values, expected {NHRU}")
        picked = {vals[hid - 1] for hid in ZONES[zone]}
        if len(picked) != 1:
            raise Fail(f"{prj} {key!r} is not uniform over zone {zone}: {sorted(picked)}")
        return float(picked.pop())

    def global_value(key: str) -> float:
        vals = deck.get(key)
        if vals is None:
            raise Fail(f"{prj} has no {key!r} block to read back")
        if len(vals) != NHRU:
            raise Fail(f"{prj} {key!r} has {len(vals)} values, expected {NHRU}")
        picked = set(vals)
        if len(picked) != 1:
            raise Fail(f"{prj} {key!r} is not uniform across HRUs: {sorted(picked)}")
        return float(picked.pop())

    applied = {
        "fetch_stubble":    zone_value("pbsm fetch", "crop_stubble"),
        "fetch_open_short": zone_value("pbsm fetch", "open_prairie"),
        "Ht_stubble":       zone_value("pbsm Ht", "crop_stubble"),
        "Ht_grass":         zone_value("pbsm Ht", "open_prairie"),
        "Ht_bare":          zone_value("pbsm Ht", "bare_ground"),
        "N_S":              global_value("pbsm N_S"),
        "A_S":              global_value("pbsm A_S"),
        "Qe_subl_from_SWE": global_value("ebsm Qe_subl_from_SWE"),
    }
    # bare_ground shares fetch_open_short with open_prairie -> verify, don't assume
    if not _close(zone_value("pbsm fetch", "bare_ground"), applied["fetch_open_short"]):
        raise Fail("pbsm fetch on bare_ground does not equal the open_prairie value; "
                   "fetch_open_short addresses both zones")
    if set(applied) != set(wanted):
        raise Fail(f"read-back covers {sorted(applied)}, requested {sorted(wanted)}")
    for name, want in wanted.items():
        if not _close(applied[name], want):
            raise Fail(f"{name}: requested {want!r}, deck reads back {applied[name]!r} "
                       f"-- the value did NOT apply (CRHM would run a different model)")
    return applied


def assert_deck_integrity(prj: Path):
    """Fail-closed checks on the deck the binary opens: the LOCKED forcing knobs
    must still be locked, the obs file must be this case's forcing, the dimensions
    and the simulation window must be the validated ones."""
    deck = read_deck_params(prj)
    elev = deck.get("obs obs_elev")
    if not elev or not all(_close(x, LOCKED_OBS_ELEV) for x in elev):
        raise Fail(f"obs obs_elev in {prj} is {elev!r}, not the LOCKED "
                   f"{LOCKED_OBS_ELEV} m CMFD source-cell elevation "
                   f"(SKILL.md HARD RULE: SWE is the scored mass state)")
    cp = deck.get("obs ClimChng_precip")
    if not cp or not all(_close(x, LOCKED_CLIMCHNG_PRECIP) for x in cp):
        raise Fail(f"obs ClimChng_precip in {prj} is {cp!r}, not the LOCKED "
                   f"{LOCKED_CLIMCHNG_PRECIP} (tuning it against SWE is fabrication)")
    text = prj.read_text(encoding="utf-8", errors="replace")
    if os.path.abspath(str(BASIN_OBS)) not in text:
        raise Fail(f"{prj} does not reference the prepared forcing {BASIN_OBS}")
    if f"nhru {NHRU}" not in text:
        raise Fail(f"{prj} does not declare nhru {NHRU}")
    for stamp in (f"{START_YEAR} 1 1", f"{END_YEAR} 12 31"):
        if stamp not in text:
            raise Fail(f"{prj} does not declare the simulation window token {stamp!r}")


# ---------------------------------------------------------------------------
# 3.  run the real model
# ---------------------------------------------------------------------------
def run_model(prj: Path, wd: Path) -> pd.DataFrame:
    out_txt = wd / "output.txt"
    parsed = wd / "parsed"
    run_tool(TOOLS / "s5_execution" / "run_crhm.py",
             ["--crhm_exe", CRHM_EXE, "--prj_path", prj, "--output_path", out_txt,
              "--obs_dir", str((WORK / "crhm").resolve()), "--progress", 100000],
             cwd=wd)
    run_tool(TOOLS / "s5_execution" / "parse_crhm_output.py",
             ["--output_path", out_txt, "--output_format", "csv",
              "--output_dir", parsed], cwd=wd)
    csv = parsed / "crhm_results.csv"
    if not csv.exists():
        raise Fail("parse_crhm_output.py produced no crhm_results.csv")
    df = pd.read_csv(csv, parse_dates=["datetime"]).set_index("datetime")
    return df


def run_health(df: pd.DataFrame, cfg: dict) -> dict:
    """FAIL-CLOSED run health.  Every diagnostic below is one CRHM actually
    produces; a MISSING or non-finite value fails the eval — none is defaulted to
    a passing value."""
    if df.empty:
        raise Fail("CRHM output parsed to zero rows")
    swe_cols = [f"SWE({i})" for i in range(1, NHRU + 1)]
    missing = [c for c in swe_cols if c not in df.columns]
    if missing:
        raise Fail(f"CRHM did not emit {missing}; got {list(df.columns)[:12]}")
    first, last = df.index.min(), df.index.max()
    if first > pd.Timestamp(f"{START_YEAR}-01-02"):
        raise Fail(f"CRHM output starts {first}, expected {START_YEAR}-01-01 "
                   f"(the run died early)")
    if last < pd.Timestamp(f"{END_YEAR}-12-30"):
        raise Fail(f"CRHM output ends {last}, expected {END_YEAR}-12-31 "
                   f"(the run died before the end of the record)")
    swe = df[swe_cols].apply(pd.to_numeric, errors="coerce")
    n_bad = int((~np.isfinite(swe.to_numpy())).sum())
    if n_bad:
        raise Fail(f"{n_bad} non-finite SWE values in the CRHM output")
    if float(swe.to_numpy().min()) < -1e-6:
        raise Fail(f"negative SWE in the CRHM output "
                   f"(min {float(swe.to_numpy().min())}) -- PBSM mass sink diverged")

    # PBSM activity gate (dag safety.warnings: sublimation 15-40% of snowfall in
    # prairie).  The gate is REQUIRED to be computable: a missing or non-finite
    # term fails the eval closed rather than being defaulted.
    areas = np.asarray(cfg["crhm_hru_areas_km2"], dtype=float)
    w = areas / areas.sum()

    def aw_delta(base: str) -> float:
        tot = 0.0
        for i in range(NHRU):
            col = f"{base}({i + 1})"
            if col not in df.columns:
                raise Fail(f"activity gate needs {col}; CRHM did not emit it")
            v = pd.to_numeric(df[col], errors="coerce").dropna()
            if len(v) < 2:
                raise Fail(f"activity gate column {col} carries no usable values")
            tot += w[i] * float(v.iloc[-1] - v.iloc[0])
        return tot

    cum_subl, cum_drift = aw_delta("cumSubl"), aw_delta("cumDrift")
    cum_snow = aw_delta("cumhru_snow")
    if not (math.isfinite(cum_subl) and math.isfinite(cum_drift)
            and math.isfinite(cum_snow)):
        raise Fail("PBSM activity-gate terms are not finite")
    if cum_snow <= 0.0:
        raise Fail(f"area-weighted cumulative snowfall is {cum_snow}; the snowfall "
                   f"denominator of the activity gate is unusable")
    frac_subl = cum_subl / cum_snow
    return {
        "n_rows": int(len(df)),
        "first_step": str(first), "last_step": str(last),
        "cumSubl_area_weighted_mm": cum_subl,
        "cumDrift_area_weighted_mm": cum_drift,
        "cumhru_snow_area_weighted_mm": cum_snow,
        "frac_subl": frac_subl,
        "frac_drift": cum_drift / cum_snow,
        "pbsm_band_frac_subl": [0.15, 0.40],
        "pbsm_gate_status": "PASS" if 0.15 <= frac_subl <= 0.40 else "FAIL",
    }


def sim_daily_swe(df: pd.DataFrame, cfg: dict) -> pd.Series:
    """Region SWE = AREA-WEIGHTED MEAN of the HRU SWE states, daily mean —
    the identical construction the validated run scored."""
    areas = np.asarray(cfg["crhm_hru_areas_km2"], dtype=float)
    w = areas / areas.sum()
    swe = sum(w[i] * pd.to_numeric(df[f"SWE({i + 1})"], errors="coerce")
              for i in range(NHRU))
    return swe.resample("D").mean()


def to_monthly(j: pd.DataFrame) -> pd.DataFrame:
    g = j.groupby(pd.Grouper(freq="MS"))
    n, m = g.size(), g.mean()
    m = m[n >= MIN_DAYS_PER_MONTH].dropna()
    m.index.name = "date"
    return m


# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    # ---- 0. STALE-OUTPUT SAFETY --------------------------------------------
    out_path = Path(args.out)
    try:
        out_path.unlink()
        print(f"[calib_run] removed stale metrics file {args.out!r}", flush=True)
    except FileNotFoundError:
        pass
    except OSError as e:
        raise Fail(f"cannot remove stale metrics file {args.out!r}: {e}")

    check_prepared()
    case_id, cfg = resolve_case()
    derived = load_prepared_json(DERIVED_JSON)
    # the LOCKED obs_elev must be the forcing source cell derive_parameters computed
    if not _close(round(float(derived["obs"]["obs_elev"])), LOCKED_OBS_ELEV):
        raise Fail(f"derive_parameters.py says obs_elev="
                   f"{derived['obs']['obs_elev']!r}, the lock is {LOCKED_OBS_ELEV} m")

    # ---- 1. the candidate vector -------------------------------------------
    pf = os.environ.get("KDT_CALIB_PARAMS")
    handed: dict = {}
    if pf:
        if not os.path.exists(pf):
            raise Fail(f"KDT_CALIB_PARAMS={pf!r} does not exist")
        with open(pf, "r", encoding="utf-8") as fh:
            handed = json.load(fh)
        if not isinstance(handed, dict):
            raise Fail("KDT_CALIB_PARAMS must contain a JSON object")
        forbidden = sorted(set(handed) & FORBIDDEN_PARAMS)
        if forbidden:
            raise Fail(f"parameter(s) {forbidden} are LOCKED for a SWE-scored run "
                       f"(SKILL.md HARD RULE: SWE is the scored mass state, so "
                       f"these knobs write the answer directly)")
        unknown = sorted(set(handed) - set(DEFAULTS))
        if unknown:
            raise Fail(f"handed unknown parameter(s) {unknown}")
    p = dict(DEFAULTS)
    for k, v in handed.items():
        p[k] = int(round(float(v))) if k in INTEGER_PARAMS else float(v)

    split = os.environ.get("KDT_CALIB_SPLIT") or "_both"
    if split not in SPLITS:
        raise Fail(f"unknown KDT_CALIB_SPLIT {split!r}")
    s0, s1 = SPLITS[split]

    # ---- 2. private eval workdir -------------------------------------------
    wd = Path(args.workdir).resolve() / "run"
    shutil.rmtree(wd, ignore_errors=True)
    wd.mkdir(parents=True)
    # Pin the record layer's series dumps into THIS eval's throwaway workdir.
    # ki_tools_common's resolver falls back to DIRECTORY DISCOVERY when this is
    # unset, which is how one run's all_metrics calls once appended to another
    # run's manifest.jsonl.  A calibration eval is machinery, never evidence.
    os.environ["KDT_SERIES_DUMP_DIR"] = str(wd / "_series")

    # ---- 3. obs + screen: enforce the declared envelope BEFORE any model run
    agg, screen = load_screen()
    obs, scored_obs, obs_measured = load_obs()

    # ---- 4. inject + read back from the effective artifact -------------------
    t0 = time.time()
    prj = build_deck(p, wd)
    applied = read_back(prj, p)
    assert_deck_integrity(prj)

    # ---- 5. the real model ---------------------------------------------------
    df = run_model(prj, wd)
    health = run_health(df, cfg)
    sim = sim_daily_swe(df, cfg)

    # ---- 6. score ------------------------------------------------------------
    a, b = pd.Timestamp(s0), pd.Timestamp(s1)
    o = obs[(obs.index >= a) & (obs.index <= b)]
    s = sim[(sim.index >= a) & (sim.index <= b)]
    # sort=True is today's concat default and is stated explicitly so a future
    # pandas default flip cannot silently reorder the paired frame.
    daily = pd.concat([o.rename("obs"), s.rename("sim")], axis=1, sort=True).dropna()
    daily.index.name = "date"
    j = daily if agg == "daily" else to_monthly(daily)
    if len(j) < 2:
        raise Fail(f"no paired obs/sim on split {split} ({s0}..{s1}) at {agg}")

    from ki_tools_common import metrics as _km
    if not str(Path(_km.__file__).resolve()).startswith(KI_TOOLS_COMMON_ROOT):
        raise Fail(f"ki_tools_common resolved to {_km.__file__}, not the canonical "
                   f"checkout under {KI_TOOLS_COMMON_ROOT}")
    raw = _km.all_metrics(j["obs"].to_numpy(), j["sim"].to_numpy(), dates=j.index,
                          label="calib_eval",
                          meta={"headline_candidate": False,   # machinery, not evidence
                                "unit": OBS_UNIT, "aggregation": agg,
                                "period_role": split})
    m = {str(k).lower(): float(v) for k, v in raw.items()
         if isinstance(v, (int, float))}
    for need in ("nse", "kge", "pbias"):
        if need not in m or not math.isfinite(m[need]):
            raise Fail(f"metric {need!r} missing or non-finite on split {split}")

    out = {
        "nse": m["nse"], "kge": m["kge"], "pbias": m["pbias"], "r": m.get("r"),
        "rmse": m.get("rmse"),
        "__kdt__": {
            # EVERY key handed is echoed (staged-frozen params included); with no
            # KDT_CALIB_PARAMS the full default vector is echoed.  The values are
            # the ones READ BACK out of the deck the binary opened.
            "applied_params": {k: applied[k] for k in (handed or p)},
            # Both DERIVED above from the artifacts actually used: case_id from the
            # hru_config whose areas weighted the simulated SWE, scored_obs from the
            # obs CSV + bbox + record count actually read and spot-checked against
            # the Snow_cci granules.
            "case_id": case_id,
            "scored_obs": scored_obs,
            "target_quantity": "swe",
            "split": split, "score_period": [s0, s1], "aggregation": agg,
            "n_scored": int(len(j)), "n_paired_days": int(len(daily)),
            "obs_envelope_measured": obs_measured,
            "screen": {k: screen[k] for k in SCREEN_ENVELOPE},
            "run_health": health,
            "forcing_knobs_locked": {"obs_elev": LOCKED_OBS_ELEV,
                                     "ClimChng_precip": LOCKED_CLIMCHNG_PRECIP},
            "wallclock_s": round(time.time() - t0, 2),
        },
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_out = out_path.with_suffix(out_path.suffix + f".partial.{os.getpid()}")
    tmp_out.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    os.replace(tmp_out, out_path)
    print(f"[calib_run] case={case_id} split={split} agg={agg} n={len(j)} "
          f"nse={m['nse']:.6f} kge={m['kge']:.4f} pbias={m['pbias']:+.2f}% "
          f"frac_subl={health['frac_subl']:.4f} "
          f"({out['__kdt__']['wallclock_s']}s)", flush=True)

    if os.environ.get("KDT_CRHM_KEEP_WORKDIR", "0") != "1":
        shutil.rmtree(wd, ignore_errors=True)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Fail as e:
        die(str(e))
    except Exception as e:                  # never leave a half-written metrics file
        import traceback
        traceback.print_exc()
        die(f"{type(e).__name__}: {e}", code=2)
