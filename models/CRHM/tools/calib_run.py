#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Calibration Runner (programmatic, NOT an agent)
==========================================================================
Tool ID:      calib_run
Stage:        calibration
Description:  Run + score ONE CRHM candidate parameter vector at the calibration
              TARGET CASE and write the gate-valid metrics as JSON.

TARGET CASE (PINNED -- this runner scores THIS gauge and no other)
------------------------------------------------------------------
  case_id      OBS:hydat
  site         Dore River near McBride, Cariboo Mountains, BC, Canada
               (53.309 N, -120.249 W); deck basin_area 406.52 km2 vs the
               published HYDAT gross drainage area 409 km2 (-0.6%); 3
               equal-area elevation HRUs (Alpine 2294 / Forest 1912 /
               Valley 1430 m, Copernicus GLO-30 terciles).
  gauge / obs  HYDAT 08KA001 (Canada National Water Data Archive), daily
               discharge m3/s, staged at
               KISSPATH_OUTPUTS/crhm_08ka001_dore/obs_08KA001.csv
  quantity     discharge -- dag var `basinflow_s`, obs_shape point_time_series,
               determining_metric NSE
  provenance   real_case CRHM_20260629T124938Z -- model-dir run_and_score.py,
               best grid member obs_elev=2100 / ClimChng_precip=1.45, FULL
               2006-2015 NSE 0.7086 (cal 2006-2010 NSE 0.7000, val 2011-2015
               NSE 0.7116, PBIAS -6.48%, n=3652).

  The gauge, its file, its coordinates, its published area and the scoring
  windows are MODULE CONSTANTS. Nothing here reads a site, gauge id, lat/lon,
  area or obs path from the environment, so no env can redirect scoring to a
  different station. `__kdt__.case_id` / `__kdt__.scored_obs` are DERIVED from
  the very identity fields the obs loader read and asserted (the station id is
  extracted from the filename of the file actually opened), so the declaration
  cannot diverge from what was actually scored.

INJECTION MODE: runner  (calibration.yaml `injection.mode: runner`)
-------------------------------------------------------------------
This case's validated recipe (model-dir run_and_score.py) REGENERATES the whole
.prj deck from a template on every run -- there is no stable parameter file a
generic applicator could edit, and several calibrated levers are per-HRU
elevation TRIPLETS that must move together. The kit therefore hands the
candidate vector in the JSON at $KDT_CALIB_PARAMS and THIS script injects it
the model's own way: it rewrites the parameter value rows of a byte-pinned COPY
of the validated best deck (dore_oe2100_p145.prj, sha256-asserted), validates
every written value against the deck's own declared `<lo to hi>` window (CRHM
hard-errors rather than clamps, so an out-of-window value must never be
written), and then reads every value BACK out of the generated .prj -- the file
the CRHM binary actually parses -- before the model is allowed to run.

The model is executed ONLY through the KI tools and the real binary:
    s5_execution/run_crhm.py                 (the real CRHM binary)
    s5_execution/parse_crhm_output.py        (STD -> csv)
    ki_tools_common.metrics.all_metrics      (NSE / KGE / PBIAS / RMSE / r)
Nothing about the model is reimplemented here.

The expensive one-time preparation (GLO-30 DEM mosaic, delineation, HRU
terciles, the 11-year hourly NASA POWER dore.obs and the HYDAT obs CSV) is
ALREADY STAGED under outputs/crhm_08ka001_dore/ by the validated real_case run
and is reused read-only by every eval. One eval = write .prj + one CRHM run +
parse + score (~2 s).

USAGE
    python3 calib_run.py --workdir <fresh_dir> --out <metrics.json>

ENV
    KDT_CALIB_PARAMS   path to {"name": value, ...} (required in runner mode)
    KDT_CALIB_SPLIT    "calibration" | "holdout"  (unset -> full 2006-2015
                       record, the validated run's own headline window)

FAIL-CLOSED CONTRACT
    Any failure -- missing/altered staged input, unknown parameter name, a
    value outside the deck's declared window, a value that does not read back
    out of the generated .prj, a CRHM error, a truncated simulation, a
    non-finite metric, or an observation series that does not match the
    declared obs contract -- exits NONZERO and writes NO metrics file. A
    missing metrics file is scored +inf by the kit; a fake pass is impossible.

Exit codes:
  0 -- success, metrics written
  1 -- input / contract / injection failure (no metrics written)
  2 -- model execution failure (no metrics written)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# ki_tools_common must win over any same-named PyPI package (insert(0), never
# append -- the HBV Bengbu lesson).
sys.path.insert(0, "KISSPATH_KI_TOOLS_COMMON")

# --------------------------------------------------------------------------- #
# PINNED PATHS -- the KI, its tools, the staged case inputs and the CRHM binary
# --------------------------------------------------------------------------- #
KI = Path(__file__).resolve().parent.parent
TOOLS = KI / "tools"
STAGE = Path("KISSPATH_OUTPUTS/crhm_08ka001_dore")
TEMPLATE_PRJ = STAGE / "crhm" / "dore_oe2100_p145.prj"   # the validated best deck
OBS_FORC = STAGE / "crhm" / "dore.obs"                   # 11-yr hourly NASA POWER
OBS_CSV = STAGE / "obs_08KA001.csv"                      # HYDAT daily discharge
CRHM_EXE = Path("KISSPATH_BINARIES/crhmcode/crhmcode/build/crhm")

# Byte-pins on the staged artifacts every eval reuses. A swapped deck (another
# site's domain) or a swapped forcing file cannot be scored silently.
TEMPLATE_SHA256 = "fb520544c09cb72d96a7699dbe1acccb4cbf2d2594a96abf17a98b60832dfef5"
FORCING_SHA256 = "912e2a2517c11cfd3f64bf411e64b32189e899e66cc6c176ed8c1bc163b8aa44"

# --------------------------------------------------------------------------- #
# PINNED TARGET CASE -- the ONLY gauge this runner may score
# --------------------------------------------------------------------------- #
CASE_ID = "OBS:hydat"
OBS_NETWORK = "hydat"
OBS_STATION = "08KA001"
OBS_SITE_NAME = "Dore River near McBride"
OBS_UNIT = "m3/s"
GAUGE_LAT, GAUGE_LON = 53.309, -120.249
GAUGE_AREA_KM2 = 409.0          # published HYDAT gross drainage area
DECK_AREA_KM2 = 406.52          # what the validated deck carries (-0.6%)
AREA_TOL_PCT = 5.0

# Simulation window carried by the pinned deck (2005 is spin-up, never scored).
SIM_START = (2005, 1, 1)
SIM_END = (2015, 12, 31)

# Scoring windows -- IDENTICAL to the validated real_case, so a calibrated
# result is directly comparable to the prior metric (FULL NSE 0.7086).
CAL_WINDOW = ("2006-01-01", "2010-12-31")
VAL_WINDOW = ("2011-01-01", "2015-12-31")
FULL_WINDOW = ("2006-01-01", "2015-12-31")

# --------------------------------------------------------------------------- #
# OBS CONTRACT -- every field declared here is READ and ASSERTED before scoring.
# A changed / corrupted / re-issued series for the SAME station cannot be
# scored silently: any mismatch exits nonzero with no metrics file.
# Values transcribed from the series the validated real_case scored.
# --------------------------------------------------------------------------- #
OBS_CONTRACT = {
    "columns": ["date", "discharge_m3s"],
    "file_sha256": "1f5dc60f435bbafee263827bbe1fd64d0efb1b003f24cf9c97f491f92c64733b",
    "date_format": "%Y-%m-%d",
    "unit": OBS_UNIT,
    "record": {"first": "2005-01-01", "last": "2015-12-31", "n_rows": 4017,
               "calendar_gaps": 0, "duplicates": 0, "nan": 0, "negative": 0},
    "splits": {
        "calibration": {
            "window": CAL_WINDOW,
            "n_valid_days": 1826,
            "first_valid": "2006-01-01",
            "last_valid": "2010-12-31",
            "min": 1.2899999618530273,
            "max": 92.30000305175781,
            "mean": 12.849978105523109,
            "missing_dates": [],
            "series_sha256":
                "a7f823a7fc05c967d30ed85ace3d61697a3290b3d6b6db9414add4dd791dca3b",
        },
        "holdout": {
            "window": VAL_WINDOW,
            "n_valid_days": 1826,
            "first_valid": "2011-01-01",
            "last_valid": "2015-12-31",
            "min": 1.0299999713897705,
            "max": 132.0,
            "mean": 15.554370188373595,
            "missing_dates": [],
            "series_sha256":
                "11aa381366085db9b3cafdd74f23341c84743555339fa44e10b68014a34bdd59",
        },
        "full": {
            "window": FULL_WINDOW,
            "n_valid_days": 3652,
            "first_valid": "2006-01-01",
            "last_valid": "2015-12-31",
            "min": 1.0299999713897705,
            "max": 132.0,
            "mean": 14.202174146948352,
            "missing_dates": [],
            "series_sha256":
                "60aabcc4116cf9644fb527dfb81ef5264666b8124c21cd0f556c76bf331736bb",
        },
    },
}
_STAT_RTOL = 1e-8   # float-summation slack; the sha256 above is the exact check

NHRU = 3

# Deck fields that pin the DOMAIN identity (asserted in the template before any
# injection -- a rebuilt/other-site deck fails closed even if the sha ever gets
# re-pinned carelessly).
DECK_IDENTITY = {
    "Shared basin_area": [DECK_AREA_KM2],
    "Shared hru_area": [135.51, 135.51, 135.51],
    "Shared hru_elev": [2294.0, 1912.0, 1430.0],
    "Shared hru_lat": [GAUGE_LAT] * 3,
    # gw routing topology: HRU1/2 gw cascades to HRU3, HRU3 exits via basingw.
    "Netroute gwwhereto": [3.0, 3.0, 0.0],
    "Netroute whereto": [3.0, 3.0, 0.0],
}

# --------------------------------------------------------------------------- #
# PARAMETER SPEC -- must stay in lockstep with calibration.yaml `parameters`.
#
#   key      : "<Module> <param>" exactly as declared in the pinned deck
#              (soil_rechr_max and Sdmax are declared under `Shared`, not
#              `Soil`, in this deck -- transcribed, not assumed).
#   shape    : how one calibrated scalar becomes the per-HRU value row
#              "all"     -> every value in every row of the block (obs_elev's
#                           3x3 block)
#              "uniform" -> the same value on all 3 HRUs
#              a list    -> an elevation PROFILE multiplied by the scalar; the
#                           profile is 1.0 at index `read_idx`, so the
#                           calibrated scalar appears VERBATIM in the .prj and
#                           reads back exactly (other entries rounded to 6 dp,
#                           which reproduces the validated deck bit-for-bit at
#                           the default vector).
#   read_idx : which value on the .prj row carries the calibrated scalar.
#   integer  : write/compare as an int.
# --------------------------------------------------------------------------- #
PARAM_SPEC = {
    # ---- forcing translation: temperature / precipitation at the HRUs --------
    "obs_elev":                {"key": "obs obs_elev",            "shape": "all",     "read_idx": 0},
    "lapse_rate":              {"key": "obs lapse_rate",          "shape": "uniform", "read_idx": 0},
    "ClimChng_precip":         {"key": "obs ClimChng_precip",     "shape": "uniform", "read_idx": 0},
    "precip_elev_adj":         {"key": "obs precip_elev_adj",     "shape": [1.0, 0.6, 0.0], "read_idx": 0},
    "tmax_allrain":            {"key": "obs tmax_allrain",        "shape": "uniform", "read_idx": 0},
    "tmax_allsnow":            {"key": "obs tmax_allsnow",        "shape": "uniform", "read_idx": 0},
    "snow_rain_determination": {"key": "obs snow_rain_determination", "shape": "uniform",
                                "read_idx": 0, "integer": True},
    # ---- snowmelt energy ----------------------------------------------------
    "Albedo_snow":             {"key": "albedo Albedo_snow", "shape": [1.0, 0.8 / 0.85, 1.0], "read_idx": 0},
    # ---- blowing snow (measured INERT at this site; kept for the dag edge) ---
    "pbsm_fetch":              {"key": "pbsm fetch",              "shape": [0.75, 0.25, 1.0], "read_idx": 2},
    # ---- frozen-soil infiltration ------------------------------------------
    "crack_fallstat":          {"key": "crack fallstat",          "shape": [0.2, 0.6, 1.0], "read_idx": 2},
    "crack_Major":             {"key": "crack Major",             "shape": "uniform", "read_idx": 0},
    # ---- evaporation --------------------------------------------------------
    "evap_F_Qg":               {"key": "evap F_Qg",               "shape": "uniform", "read_idx": 0},
    # ---- soil / groundwater stores (volume levers) --------------------------
    "Sdmax":                   {"key": "Shared Sdmax",            "shape": [0.25, 0.5, 1.0], "read_idx": 2},
    "soil_moist_max":          {"key": "Soil soil_moist_max",     "shape": [0.4, 0.8, 1.0], "read_idx": 2},
    "soil_rechr_max":          {"key": "Shared soil_rechr_max",   "shape": [0.375, 0.75, 1.0], "read_idx": 2},
    "rechr_ssr_K":             {"key": "Soil rechr_ssr_K",        "shape": "uniform", "read_idx": 0},
    "lower_ssr_K":             {"key": "Soil lower_ssr_K",        "shape": "uniform", "read_idx": 0},
    "soil_gw_K":               {"key": "Soil soil_gw_K",          "shape": "uniform", "read_idx": 0},
    "gw_max":                  {"key": "Soil gw_max",   "shape": [5.0 / 6.0, 1.0, 7.0 / 6.0], "read_idx": 1},
    "gw_K":                    {"key": "Soil gw_K",               "shape": "uniform", "read_idx": 0},
    # ---- routing storage (recession shape / timing) -------------------------
    "Kstorage":                {"key": "Netroute Kstorage", "shape": [2.0 / 3.0, 1.0, 5.0 / 12.0], "read_idx": 1},
    "Lag":                     {"key": "Netroute Lag",     "shape": [2.0 / 3.0, 1.0, 1.0 / 3.0], "read_idx": 1},
    "runKstorage":             {"key": "Netroute runKstorage",    "shape": "uniform", "read_idx": 0},
    "ssrKstorage":             {"key": "Netroute ssrKstorage",    "shape": "uniform", "read_idx": 0},
    "gwKstorage":              {"key": "Netroute gwKstorage",     "shape": "uniform", "read_idx": 0},
    "gwLag":                   {"key": "Netroute gwLag",          "shape": "uniform", "read_idx": 0},
}

# Defaults == the validated best grid member (obs_elev 2100 / ClimChng_precip
# 1.45 over the Canoe-derived large GW store and light Kstorage recipe), so the
# default vector reproduces the validated run and a staged round that freezes a
# parameter holds it at the validated value.
PARAM_DEFAULTS = {
    "obs_elev": 2100.0,
    "lapse_rate": 0.75,
    "ClimChng_precip": 1.45,
    "precip_elev_adj": 0.0005,
    "tmax_allrain": 2.0,
    "tmax_allsnow": 0.0,
    "snow_rain_determination": 0,
    "Albedo_snow": 0.85,
    "pbsm_fetch": 2000.0,
    "crack_fallstat": 50.0,
    "crack_Major": 5.0,
    "evap_F_Qg": 0.05,
    "Sdmax": 20.0,
    "soil_moist_max": 250.0,
    "soil_rechr_max": 80.0,
    "rechr_ssr_K": 0.01,
    "lower_ssr_K": 0.001,
    "soil_gw_K": 6.0,
    "gw_max": 1800.0,
    "gw_K": 1.0,
    "Kstorage": 24.0,
    "Lag": 72.0,
    "runKstorage": 0.0,
    "ssrKstorage": 0.0,
    "gwKstorage": 50.0,
    "gwLag": 500.0,
}

# gw_init is NOT calibrated: it is written every run as 0.5 x the per-HRU
# gw_max (exactly the validated deck's 750/900/1050 for gw_max 1500/1800/2100),
# so the store can never be initialised above its own capacity and CRHM's
# "Initial value of gw storage is greater than the maximum value" hard error is
# unreachable by construction.
GW_INIT_FRACTION = 0.5

READBACK_RTOL = 1e-9


class Fail(Exception):
    """Any condition that must abort the eval with NO metrics written."""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:                     # read-only, binary
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# --------------------------------------------------------------------------- #
# KI tool invocation
# --------------------------------------------------------------------------- #
def run_tool(script: Path, args, label=None):
    cmd = [sys.executable, str(script)] + [str(a) for a in args]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise Fail(f"{label or script.name} rc={p.returncode}\n"
                   f"STDOUT:\n{p.stdout[-3000:]}\nSTDERR:\n{p.stderr[-3000:]}")
    return p.stdout + "\n" + p.stderr


# --------------------------------------------------------------------------- #
# candidate vector
# --------------------------------------------------------------------------- #
def load_requested():
    """Read the candidate vector. Unknown / non-finite names fail closed."""
    pf = os.environ.get("KDT_CALIB_PARAMS")
    if not pf:
        # No vector handed => the DEFAULT vector (commissioning / kit baseline).
        return dict(PARAM_DEFAULTS), False
    p = Path(pf)
    if not p.is_file():
        raise Fail(f"KDT_CALIB_PARAMS points at a missing file: {pf}")
    with open(p, "r") as fh:                          # read-only
        raw = json.load(fh)
    if not isinstance(raw, dict):
        raise Fail("KDT_CALIB_PARAMS JSON must be an object {name: value}")
    unknown = sorted(set(raw) - set(PARAM_SPEC))
    if unknown:
        raise Fail(f"unknown calibration parameter(s): {unknown}; "
                   f"known: {sorted(PARAM_SPEC)}")
    vec = dict(PARAM_DEFAULTS)
    for k, v in raw.items():
        try:
            fv = float(v)
        except (TypeError, ValueError):
            raise Fail(f"parameter {k!r} is not numeric: {v!r}")
        if not math.isfinite(fv):
            raise Fail(f"parameter {k!r} is not finite: {v!r}")
        vec[k] = int(round(fv)) if PARAM_SPEC[k].get("integer") else fv
    # Echo EVERY key we were handed (incl. frozen ones) -- the kit fails an
    # eval that omits a handed key. `applied_params` below carries the whole
    # pool, a superset of the handed keys.
    return vec, True


def _fmt_num(v: float) -> str:
    """Deterministic token that float()-round-trips exactly."""
    if float(v) == int(v) and abs(v) < 1e15:
        return str(int(v))
    return repr(float(v))


def hru_values(name: str, scalar) -> list:
    """One calibrated scalar -> the per-HRU value list for the .prj row."""
    spec = PARAM_SPEC[name]
    shape = spec["shape"]
    if spec.get("integer"):
        scalar = int(round(scalar))
    if shape == "all" or shape == "uniform":
        return [scalar] * NHRU
    prof = shape
    if prof[spec["read_idx"]] != 1.0:
        raise Fail(f"profile for {name} must be 1.0 at read_idx")
    vals = []
    for i, f in enumerate(prof):
        if i == spec["read_idx"]:
            vals.append(float(scalar))
        else:
            vals.append(round(float(scalar) * float(f), 6))
    return vals


# --------------------------------------------------------------------------- #
# deck (.prj) surgery -- inject into a COPY of the pinned validated deck
# --------------------------------------------------------------------------- #
_DECL_RANGE = re.compile(r"^(\S+)\s+(\S+)\s+<([^>]*)>\s*$")


def _parse_decl_range(spec_text: str):
    m = re.match(r"\s*(\S+)\s+to\s+(\S+)\s*$", spec_text)
    if not m:
        raise Fail(f"unparseable declared range <{spec_text}>")
    return float(m.group(1)), float(m.group(2))


def _is_numeric_row(line: str) -> bool:
    toks = line.split()
    if not toks:
        return False
    try:
        [float(t) for t in toks]
        return True
    except ValueError:
        return False


def parse_deck(text: str):
    """The Parameters block as {key: {"lo","hi","rows":[row_line_indices]}}."""
    lines = text.split("\n")
    table = {}
    in_block = False
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if s == "Parameters:":
            in_block = True
            i += 1
            continue
        if in_block and (s.startswith("Initial_State") or s.startswith("Final_State")):
            break
        if in_block:
            m = _DECL_RANGE.match(s)
            if m:
                key = f"{m.group(1)} {m.group(2)}"
                lo, hi = _parse_decl_range(m.group(3))
                rows = []
                j = i + 1
                while j < len(lines) and _is_numeric_row(lines[j].strip()):
                    rows.append(j)
                    j += 1
                table[key] = {"lo": lo, "hi": hi, "rows": rows}
                i = j
                continue
        i += 1
    return table, lines


def deck_values(text: str, key: str):
    """All numeric values carried by `key` in deck order (flattened)."""
    table, lines = parse_deck(text)
    if key not in table:
        raise Fail(f"deck has no parameter '{key}'")
    out = []
    for j in table[key]["rows"]:
        out.extend(float(t) for t in lines[j].split())
    return out


def assert_template_identity(text: str):
    """The pinned deck must be THIS gauge's validated domain."""
    for key, want in DECK_IDENTITY.items():
        got = deck_values(text, key)
        if len(got) != len(want) or any(
                not math.isclose(g, w, rel_tol=1e-9, abs_tol=1e-9)
                for g, w in zip(got, want)):
            raise Fail(f"template deck identity mismatch on '{key}': "
                       f"{got} != expected {want} -- wrong/rebuilt domain")
    if "dore.obs" not in text:
        raise Fail("template deck does not reference dore.obs")
    for token in ("2005 1 1", "2015 12 31"):
        if token not in text:
            raise Fail(f"template deck lost its simulation window ({token})")
    area = deck_values(text, "Shared basin_area")[0]
    err = 100.0 * (area - GAUGE_AREA_KM2) / GAUGE_AREA_KM2
    if abs(err) > AREA_TOL_PCT:
        raise Fail(f"deck area {area} km2 is {err:+.1f}% off the published "
                   f"HYDAT {OBS_STATION} area {GAUGE_AREA_KM2} km2")


def inject(text: str, vec) -> str:
    """Rewrite the value rows for every calibrated key (+ derived gw_init).

    Every written value is validated against the deck's OWN declared
    `<lo to hi>` window first -- CRHM hard-errors rather than clamps, and a
    clamp-free contract means an out-of-window value must never be written.
    """
    table, lines = parse_deck(text)
    writes = {}
    for name, spec in PARAM_SPEC.items():
        writes[spec["key"]] = hru_values(name, vec[name])
    # derived: gw_init = GW_INIT_FRACTION x per-HRU gw_max (never calibrated)
    writes["Soil gw_init"] = [round(GW_INIT_FRACTION * v, 6)
                              for v in writes["Soil gw_max"]]
    for key, vals in writes.items():
        if key not in table:
            raise Fail(f"deck has no parameter '{key}' to inject")
        ent = table[key]
        if not ent["rows"]:
            raise Fail(f"deck parameter '{key}' has no value rows")
        for v in vals:
            if not (ent["lo"] <= float(v) <= ent["hi"]):
                raise Fail(f"{key}={v} is outside the deck's declared window "
                           f"<{ent['lo']} to {ent['hi']}> -- CRHM would "
                           f"hard-error; the calibration range must stay "
                           f"inside the declared window")
        row_txt = " ".join(_fmt_num(v) for v in vals)
        for j in ent["rows"]:
            lines[j] = row_txt
    return "\n".join(lines)


def read_back(prj_path: Path, vec):
    """Read every calibrated value out of the .prj CRHM will parse."""
    text = prj_path.read_text()
    applied, problems = {}, []
    for name, spec in PARAM_SPEC.items():
        try:
            vals = deck_values(text, spec["key"])
        except Fail as e:
            problems.append(str(e))
            continue
        idx = spec["read_idx"]
        if idx >= len(vals):
            problems.append(f"{name}: '{spec['key']}' has {len(vals)} "
                            f"value(s), need index {idx}")
            continue
        got = vals[idx]
        want = float(int(round(vec[name])) if spec.get("integer") else vec[name])
        if spec.get("integer"):
            got_cmp, ok = int(round(got)), int(round(got)) == int(round(want))
        else:
            got_cmp = got
            ok = math.isclose(got, want, rel_tol=READBACK_RTOL, abs_tol=1e-12)
        if not ok:
            problems.append(f"{name}: requested {want!r} but the .prj carries "
                            f"{got!r} (CRHM would run a different model)")
        applied[name] = got_cmp
    # the derived initial condition must also hold in the parsed artifact
    gw_max_vals = deck_values(text, "Soil gw_max")
    gw_init_vals = deck_values(text, "Soil gw_init")
    for gm, gi in zip(gw_max_vals, gw_init_vals):
        if not math.isclose(gi, round(GW_INIT_FRACTION * gm, 6),
                            rel_tol=1e-9, abs_tol=1e-9):
            problems.append(f"derived gw_init {gi} != {GW_INIT_FRACTION} x "
                            f"gw_max {gm}")
    if problems:
        raise Fail("parameter read-back FAILED (injection did not reach the "
                   "model input):\n  " + "\n  ".join(problems))
    return applied


# --------------------------------------------------------------------------- #
# observations -- contract-enforced
# --------------------------------------------------------------------------- #
def load_obs():
    """Load + ASSERT the declared obs envelope. Returns (series, identity)."""
    if not OBS_CSV.is_file():
        raise Fail(f"observation file missing: {OBS_CSV}")
    digest = sha256_file(OBS_CSV)
    if digest != OBS_CONTRACT["file_sha256"]:
        raise Fail(f"obs file sha256 {digest} != declared "
                   f"{OBS_CONTRACT['file_sha256']} -- the {OBS_STATION} "
                   f"series changed / was replaced")
    # The station identity is carried by the file NAME of the file we actually
    # open -- derive it, then assert it is the target-case gauge.
    m = re.match(r"^obs_(\w+)\.csv$", OBS_CSV.name)
    if not m or m.group(1) != OBS_STATION:
        raise Fail(f"obs file {OBS_CSV.name} does not carry the target-case "
                   f"station id {OBS_STATION}")
    station_id = m.group(1)

    with open(OBS_CSV, "r") as fh:                    # read-only
        df = pd.read_csv(fh, dtype=str)
    if list(df.columns) != OBS_CONTRACT["columns"]:
        raise Fail(f"obs columns {list(df.columns)} != declared "
                   f"{OBS_CONTRACT['columns']}")
    dt = pd.to_datetime(df["date"], format=OBS_CONTRACT["date_format"],
                        errors="coerce")
    if int(dt.isna().sum()):
        raise Fail(f"{int(dt.isna().sum())} unparseable dates in {OBS_CSV}")
    q = pd.to_numeric(df["discharge_m3s"], errors="coerce")
    s = pd.Series(q.to_numpy(dtype=float), index=pd.DatetimeIndex(dt)).sort_index()

    rec = OBS_CONTRACT["record"]
    if len(s) != rec["n_rows"]:
        raise Fail(f"obs rows {len(s)} != declared {rec['n_rows']}")
    if int(s.index.duplicated().sum()) != rec["duplicates"]:
        raise Fail("obs carries duplicated dates")
    if int(s.isna().sum()) != rec["nan"]:
        raise Fail("obs carries NaN discharge values")
    if int((s < 0).sum()) != rec["negative"]:
        raise Fail("obs carries negative discharge values")
    if str(s.index.min().date()) != rec["first"] or \
            str(s.index.max().date()) != rec["last"]:
        raise Fail(f"obs record span {s.index.min().date()}..{s.index.max().date()} "
                   f"!= declared {rec['first']}..{rec['last']}")
    gaps = pd.date_range(rec["first"], rec["last"], freq="D").difference(s.index)
    if len(gaps) != rec["calendar_gaps"]:
        raise Fail(f"obs has {len(gaps)} missing calendar days, declared "
                   f"{rec['calendar_gaps']}")

    for split, dec in OBS_CONTRACT["splits"].items():
        a, b = dec["window"]
        w = s[(s.index >= pd.Timestamp(a)) & (s.index <= pd.Timestamp(b))].dropna()
        if len(w) != dec["n_valid_days"]:
            raise Fail(f"obs split {split}: {len(w)} valid days, declared "
                       f"{dec['n_valid_days']}")
        if str(w.index.min().date()) != dec["first_valid"]:
            raise Fail(f"obs split {split}: first valid {w.index.min().date()} "
                       f"!= declared {dec['first_valid']}")
        if str(w.index.max().date()) != dec["last_valid"]:
            raise Fail(f"obs split {split}: last valid {w.index.max().date()} "
                       f"!= declared {dec['last_valid']}")
        for stat, got in (("min", float(w.min())), ("max", float(w.max())),
                          ("mean", float(w.mean()))):
            if not math.isclose(got, float(dec[stat]), rel_tol=_STAT_RTOL,
                                abs_tol=1e-9):
                raise Fail(f"obs split {split}: {stat} {got!r} != declared "
                           f"{dec[stat]!r} -- the series changed")
        rng_got = float(w.max()) - float(w.min())
        rng_dec = float(dec["max"]) - float(dec["min"])
        if not math.isclose(rng_got, rng_dec, rel_tol=_STAT_RTOL, abs_tol=1e-9):
            raise Fail(f"obs split {split}: range {rng_got} != {rng_dec}")
        missing = sorted(str(d.date()) for d in
                         pd.date_range(a, b, freq="D").difference(w.index))
        if missing != list(dec["missing_dates"]):
            raise Fail(f"obs split {split}: missing dates {missing[:5]}... != "
                       f"declared {dec['missing_dates']}")
        digest = hashlib.sha256(
            "|".join(f"{d.date()}:{v:.6f}" for d, v in w.items()).encode()
        ).hexdigest()
        if digest != dec["series_sha256"]:
            raise Fail(f"obs split {split}: scored series sha256 {digest} != "
                       f"declared {dec['series_sha256']} -- the observations "
                       f"for {station_id} changed")

    identity = {
        "network": OBS_NETWORK,
        "station_id": station_id,
        "station_name": OBS_SITE_NAME,
        "lat": GAUGE_LAT,
        "lon": GAUGE_LON,
        "drainage_area_km2": GAUGE_AREA_KM2,
        "unit": OBS_UNIT,
        "file": str(OBS_CSV),
    }
    return s, identity


# --------------------------------------------------------------------------- #
# run-health -- diagnostics CRHM / the KI tools actually produce.
# A required diagnostic that is MISSING fails the eval closed; nothing defaults
# to a passing value.
# --------------------------------------------------------------------------- #
def check_run_health(tool_log: str, out_txt: Path, df: pd.DataFrame):
    health = {}

    # (1) run_crhm.py escalates CRHM stderr error lines to [ERROR] log lines
    if tool_log is None:
        raise Fail("run-health: run_crhm produced no captured log")
    bad = [l for l in tool_log.splitlines() if "[ERROR]" in l]
    health["crhm_error_lines"] = len(bad)
    if bad:
        raise Fail("run-health: CRHM reported errors:\n  " + "\n  ".join(bad[:10]))

    # (2) the raw STD output must exist and be non-trivial
    if not out_txt.is_file() or out_txt.stat().st_size == 0:
        raise Fail("run-health: CRHM produced no output file")
    health["output_bytes"] = int(out_txt.stat().st_size)

    # (3) every scored/diagnostic variable must be present
    need = ["basinflow(1)", "basingw(1)"] \
        + [f"SWE({i})" for i in range(1, NHRU + 1)] \
        + [f"soil_moist({i})" for i in range(1, NHRU + 1)] \
        + [f"hru_actet({i})" for i in range(1, NHRU + 1)]
    missing = [c for c in need if c not in df.columns]
    if missing:
        raise Fail(f"run-health: parsed output is missing {missing}")

    # (4) the simulation must COVER the whole window at the full hourly step --
    #     a run that died early would otherwise be scored on its prefix.
    first, last = df.index.min(), df.index.max()
    health["sim_first"], health["sim_last"] = str(first), str(last)
    if first > pd.Timestamp(*SIM_START) + pd.Timedelta(hours=1):
        raise Fail(f"run-health: simulation starts {first}, expected "
                   f"{pd.Timestamp(*SIM_START)}")
    if last < pd.Timestamp(*SIM_END):
        raise Fail(f"run-health: simulation ends {last}, expected "
                   f"{pd.Timestamp(*SIM_END)} -- TRUNCATED run")
    per_day = df.resample("D").size()
    interior = pd.date_range(FULL_WINDOW[0], FULL_WINDOW[1], freq="D")[:-1]
    short = per_day.reindex(interior)
    n_bad = int((short != 24).sum() + short.isna().sum())
    health["incomplete_days"] = n_bad
    if n_bad:
        raise Fail(f"run-health: {n_bad} scored day(s) do not carry the full "
                   f"24 hourly steps -- incomplete simulation")

    # (5) no non-finite discharge anywhere in the scored span
    q = df.loc[FULL_WINDOW[0]:FULL_WINDOW[1], "basinflow(1)"]
    n_nf = int((~np.isfinite(q.to_numpy(dtype=float))).sum())
    health["nonfinite_basinflow_steps"] = n_nf
    if n_nf:
        raise Fail(f"run-health: {n_nf} non-finite basinflow steps")
    return health


# --------------------------------------------------------------------------- #
# scoring
# --------------------------------------------------------------------------- #
def sim_daily_q(df):
    """basinflow(1) is m3 per hourly interval -> daily total / 86400 s = m3/s
    (identical to the validated run_and_score.py aggregation)."""
    return df["basinflow(1)"].resample("D").sum() / 86400.0


def score(obs_s, sim_s, window, label):
    from ki_tools_common.metrics import all_metrics
    a, b = pd.Timestamp(window[0]), pd.Timestamp(window[1])
    o = obs_s[(obs_s.index >= a) & (obs_s.index <= b)]
    s = sim_s[(sim_s.index >= a) & (sim_s.index <= b)]
    j = pd.concat([o.rename("obs"), s.rename("sim")], axis=1).dropna()
    if len(j) < 2:
        raise Fail(f"no paired obs/sim in {label} window {window}")
    m = all_metrics(j["obs"], j["sim"], dates=j.index, label=label,
                    meta={"unit": OBS_UNIT, "obs_source": str(OBS_CSV)})
    out = {"nse": float(m["NSE"]), "kge": float(m["KGE"]),
           "pbias": float(m["PBIAS"]), "rmse": float(m["RMSE"]),
           "r": float(m["r"]), "n_paired": int(len(j))}
    for k, v in out.items():
        if isinstance(v, float) and not math.isfinite(v):
            raise Fail(f"{label}: metric {k} is not finite ({v})")
    return out


# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(
        description="CRHM calibration runner (Dore River 08KA001, OBS:hydat)")
    ap.add_argument("--workdir", required=True,
                    help="fresh per-candidate working directory")
    ap.add_argument("--out", required=True, help="metrics JSON to write")
    args = ap.parse_args()

    wd = Path(args.workdir).resolve()
    wd.mkdir(parents=True, exist_ok=True)
    out_path = Path(args.out).resolve()
    if out_path.exists():
        out_path.unlink()                      # never leave a stale pass behind

    # Pin the evidence-capture dir to THIS eval so ki_tools_common's series
    # resolver can never fall back to directory discovery and mix evals
    # (the KI's own record-defect lesson).
    os.environ["KDT_SERIES_DUMP_DIR"] = str(wd / "_series")

    # CRHM appends crhmRun.log to the PROCESS working directory. All paths here
    # are absolute, so run from the eval workdir and everything the binary
    # drops stays inside this candidate's dir.
    os.chdir(wd)

    # ---- staged inputs, byte-pinned ----
    for p in (TEMPLATE_PRJ, OBS_FORC, OBS_CSV, CRHM_EXE):
        if not Path(p).exists():
            raise Fail(f"staged case input missing: {p}")
    t_sha = sha256_file(TEMPLATE_PRJ)
    if t_sha != TEMPLATE_SHA256:
        raise Fail(f"template deck sha256 {t_sha} != pinned {TEMPLATE_SHA256} "
                   f"-- the validated Dore deck changed / was replaced")
    f_sha = sha256_file(OBS_FORC)
    if f_sha != FORCING_SHA256:
        raise Fail(f"forcing sha256 {f_sha} != pinned {FORCING_SHA256} "
                   f"-- the staged NASA POWER dore.obs changed")
    template = TEMPLATE_PRJ.read_text()
    assert_template_identity(template)

    # ---- candidate vector ----
    vec, injected = load_requested()

    # ---- inject into a copy of the pinned deck; read back what CRHM parses --
    prj = wd / "basin.prj"
    prj.write_text(inject(template, vec))
    applied = read_back(prj, vec)

    # ---- run the real binary via the KI tool ----
    out_txt = wd / "output.txt"
    tool_log = run_tool(TOOLS / "s5_execution" / "run_crhm.py",
                        ["--crhm_exe", CRHM_EXE, "--prj_path", prj,
                         "--output_path", out_txt,
                         "--obs_dir", str((STAGE / "crhm").resolve()) + "/"],
                        label="run_crhm")
    run_tool(TOOLS / "s5_execution" / "parse_crhm_output.py",
             ["--output_path", out_txt, "--output_format", "csv",
              "--output_dir", wd / "parsed"], label="parse_crhm_output")
    csv = wd / "parsed" / "crhm_results.csv"
    if not csv.is_file():
        raise Fail(f"parse_crhm_output produced no {csv}")
    df = pd.read_csv(csv, parse_dates=["datetime"]).set_index("datetime")

    health = check_run_health(tool_log, out_txt, df)

    # ---- observations (contract-enforced) + scoring ----
    obs_s, obs_identity = load_obs()
    sim = sim_daily_q(df)

    split = (os.environ.get("KDT_CALIB_SPLIT") or "").strip().lower()
    m_cal = score(obs_s, sim, CAL_WINDOW, "cal")
    m_val = score(obs_s, sim, VAL_WINDOW, "val")
    m_full = score(obs_s, sim, FULL_WINDOW, "headline")
    if split == "calibration":
        head, scored_window, scored_split = m_cal, CAL_WINDOW, "calibration"
    elif split == "holdout":
        head, scored_window, scored_split = m_val, VAL_WINDOW, "holdout"
    elif split == "":
        # no split declared -> the FULL 2006-2015 record, the exact window the
        # validated real_case's prior metric (NSE 0.7086) was computed on.
        head, scored_window, scored_split = m_full, FULL_WINDOW, "full"
    else:
        raise Fail(f"unrecognised KDT_CALIB_SPLIT={split!r}")

    # `scored_obs` / `case_id` are built from the identity the loader ASSERTED
    # (station id from the filename actually opened) and the window actually
    # scored -- they cannot diverge from the scoring.
    scored_obs = (f"{obs_identity['network'].upper()}:{obs_identity['station_id']} "
                  f"({obs_identity['station_name']}, "
                  f"lat={obs_identity['lat']} lon={obs_identity['lon']}) "
                  f"[{obs_identity['unit']}] {obs_identity['file']} "
                  f"| split={scored_split} {scored_window[0]}..{scored_window[1]} "
                  f"n={head['n_paired']}")

    metrics = {
        "nse": head["nse"], "kge": head["kge"], "pbias": head["pbias"],
        "rmse": head["rmse"], "r": head["r"], "n_paired": head["n_paired"],
        "nse_cal": m_cal["nse"], "kge_cal": m_cal["kge"], "pbias_cal": m_cal["pbias"],
        "nse_val": m_val["nse"], "kge_val": m_val["kge"], "pbias_val": m_val["pbias"],
        "nse_full": m_full["nse"], "kge_full": m_full["kge"], "pbias_full": m_full["pbias"],
        "scored_split": scored_split,
        "scored_period": f"{scored_window[0]}..{scored_window[1]}",
        "run_health": health,
        "__kdt__": {
            "applied_params": applied,
            "case_id": CASE_ID,
            "scored_obs": scored_obs,
            "injection_mode": "runner",
            "params_injected_from_env": injected,
            "target_var": "basinflow_s",
            "obs_shape": "point_time_series",
            "deck_area_km2": DECK_AREA_KM2,
            "prj": str(prj),
        },
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=1))
    print(json.dumps({k: v for k, v in metrics.items() if k != "run_health"},
                     ensure_ascii=False)[:2000])
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Fail as exc:
        print(f"CALIB_RUN FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception:
        import traceback
        traceback.print_exc()
        sys.exit(2)
