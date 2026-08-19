#!/usr/bin/env python3
"""
calib_run.py — programmatic run+score of ONE Noah-MP candidate parameter vector.

    python3 calib_run.py --workdir <wd> --out <metrics.json>

TARGET CASE (PINNED — this driver scores this gauge and no other)
-----------------------------------------------------------------
    case_id        SITE:US-Ne1
    obs            FLUXNET2015 tower US-Ne1 — Mead, Nebraska, UNL ARDC,
                   irrigated continuous maize.  FULLSET_DD daily LE_F_MDS
                   [W m-2], QC fraction >= 0.8.
    dag var        LH  (obs_shape point_time_series, target quantity ET)
    metric         nse  (determining), plus kge / pbias / rmse / r

The site identity, its coordinates, the obs file and the scored period are
module CONSTANTS.  Nothing about *what is scored* is read from the environment:
`KDT_CALIB_PARAMS` (the candidate vector) and `KDT_CALIB_SPLIT`
("calibration" | "holdout") are the only environment inputs, and the split only
selects a contiguous sub-window of the SAME station's series.  The `case_id` /
`scored_obs` fields written into `__kdt__` are DERIVED from the obs path/site id
that was actually opened and from the period/rows that were actually scored, and
are then cross-checked against the target-case constants — so the declaration
cannot diverge from what was scored.

INJECTION MODE: runner
----------------------
The KI regenerates every model input on each run (setup NetCDF, agdata NetCDF,
namelist, parameter table), so the kit cannot pre-write parameter values.  This
driver reads the candidate vector from the JSON at `KDT_CALIB_PARAMS`, injects
it into a PER-EVAL COPY of `NoahmpTable.TBL` (the artifact hrldas.exe reads from
its run directory), reads every value BACK out of that written table, and fails
closed (nonzero exit, no metrics file) if any value cannot be written+read.
Every key handed in `KDT_CALIB_PARAMS` is echoed in `__kdt__.applied_params`,
including parameters frozen at their default by a staged round.

The model itself is ALWAYS run through the KI's own stage tools:
    s2  tools/convert_soil_to_noahmp.py      (+ ki_tools_common.soil_utils)
    s4  tools/convert_forcing_to_noahmp.py   (+ validators/preflight_forcing.py)
    s1  tools/build_hrldas_setup.py
    s6  tools/run_noahmp.py                  -> hrldas.exe
    s8  ki_tools_common.metrics.all_metrics
        ki_tools_common.validation.validate_water_balance
s2/s4 are ONE-TIME prepare steps cached in --prep-dir; only s1/s6/s7/s8 run per
candidate.

CANDIDATE ISOLATION + STALE-OUTPUT SAFETY
-----------------------------------------
The model runs ONLY inside the `--workdir` the kit hands this candidate:
`<workdir>/run` is WIPED AND REBUILT at the start of every evaluation, and
`<workdir>` is held under an exclusive non-blocking lock for the whole run, so no
concurrent or retried candidate can share a run directory or read another
candidate's inputs/outputs.  The shared `--prep-dir` cache is serialised under its
own blocking lock and published with atomic replaces.  `--out` is deleted as the
FIRST action of main(), before the workdir is created or locked, and again on
EVERY failure path — so even lock contention (which raises before the model runs)
cannot leave a stale metrics file.  The metrics JSON is only ever created by a
completed, fully validated evaluation (tmp + os.replace); a failed run leaves
NOTHING behind, so the kit reads +inf instead of a stale success.

Commissioning helper (NOT used by the kit; never emits metrics):
    python3 calib_run.py --readback-probe --workdir <wd> --set NAME=VALUE ...
runs a short model window at the requested vector and writes a probe JSON with
`__kdt__.applied_params`, so each range bound can be shown to apply EXACTLY and
to leave the model numerically stable.
"""

import argparse
import errno
import fcntl
import glob
import json
import math
import os
import re
import shutil
import subprocess
import sys
import traceback
from datetime import datetime, timedelta

import numpy as np

# --------------------------------------------------------------------------
# KI wiring (identical to the validated real-case runner run_and_score_usne1.py)
# --------------------------------------------------------------------------
KI = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(KI, "tools")
ROOT = os.path.dirname(KI)
BIN = "KISSPATH_BINARIES/Noah_MP/source/hrldas/hrldas/run/hrldas.exe"
SRCDIR = "KISSPATH_BINARIES/Noah_MP/source/repo"
TBL_SRC = "KISSPATH_BINARIES/Noah_MP/source/hrldas/hrldas/run/NoahmpTable.TBL"
KDT = "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect_multi_agent"
PREFLIGHT = os.path.join(KDT, "validators", "preflight_forcing.py")

sys.path.insert(0, KDT)
sys.path.insert(0, TOOLS)

DEFAULT_PREP_DIR = "/mnt/extreme_ssd1/hc_detached/Noah_MP/calib_prep_usne1"

# --------------------------------------------------------------------------
# TARGET CASE — pinned constants
# --------------------------------------------------------------------------
TARGET_CASE_ID = "SITE:US-Ne1"
TARGET_SITE_ID = "US-Ne1"
TARGET_NETWORK = "FLUXNET2015"
SITE_DIR = "KISSPATH_OBS/fluxnet/sites/US-Ne1"
SITE_NAME = "Mead, Nebraska - irrigated continuous maize (UNL ARDC)"
SITE_LAT, SITE_LON = 41.16506, -96.47664       # BADM LOCATION_LAT / LOCATION_LONG
SITE_ELEV = 361.0                              # BADM LOCATION_ELEV [m]
UTC_OFFSET = -6.0                              # BADM UTC_OFFSET [h], no DST
ZLVL = 6.2                                     # VAR_INFO_HEIGHT of USTAR [m]
IGBP = "CRO"
IVGTYP = 12                                    # MODIS-IGBP croplands
EXPECTED_ISLTYP = 6                            # HWSD loam at the tower

DAG_VAR = "LH"
OBS_SHAPE = "point_time_series"
OBS_SOURCE = "fluxnet2015"
OBS_FILE_NAME = "FULLSET_DD.csv"
OBS_COL = "LE_F_MDS"
OBS_QC_COL = "LE_F_MDS_QC"
OBS_QC_MIN = 0.8
OBS_UNIT = "W m-2"
DETERMINING_METRIC = "nse"

# Period: 2004-2012 record, 5-yr calibration / 4-yr held-out validation, exactly
# as in the validated real case (run_and_score_usne1.py).
FORCE_START_DATE = "2004-01-01"
FORCE_END_DATE = "2013-01-02"
SPLIT_WINDOWS = {
    "full":        ("2004-01-01", "2012-12-31"),
    "calibration": ("2004-01-01", "2008-12-31"),
    "holdout":     ("2009-01-01", "2012-12-31"),
}
SPINUP_LOOPS = 3
N_LDASIN_EXPECTED = 78937
KHOUR = N_LDASIN_EXPECTED - 2                  # 78935; forcing read at t=0..KHOUR

# The headline (site-valid) configuration selected by the validated real case on
# calibration-period NSE.  Calibration reproduces this configuration EXACTLY and
# varies only the parameter vector.
CONFIG = dict(crop=0, dveg=3, irr=3, irrm=1, btr=2, opt_run=1, opt_runsub=1)

# --------------------------------------------------------------------------
# OBS CONTRACT — every field asserted before a metric is computed.
# Derived from FULLSET_DD.csv itself; a changed/corrupted series for the SAME
# station therefore fails closed instead of being silently scored.
# --------------------------------------------------------------------------
OBS_CONTRACT = {
    "full": dict(start="2004-01-01", end="2012-12-31", rows=3288, n_qc=3271,
                 mean=52.828716, min=-6.2203, max=275.5560, std=51.647000,
                 precip_mm=7531.231),
    "calibration": dict(start="2004-01-01", end="2008-12-31", rows=1827, n_qc=1821,
                        mean=52.344279, min=-6.2203, max=275.5560, std=51.250724,
                        precip_mm=4462.911),
    "holdout": dict(start="2009-01-01", end="2012-12-31", rows=1461, n_qc=1450,
                    mean=53.437102, min=-5.1784, max=248.2010, std=52.151742,
                    precip_mm=3068.320),
}

SOIL_DZ_MM = np.array([100.0, 300.0, 600.0, 1000.0])

# --------------------------------------------------------------------------
# PARAMETER POOL — see calibration.yaml for ranges + literature provenance.
# `section` is the NoahmpTable.TBL Fortran namelist group; `column` is
#   "veg"  -> MODIS-IGBP land category index (IVGTYP = 12, croplands)
#   "soil" -> STAS soil category index (ISLTYP = 6, loam)
#   None   -> single global scalar
# --------------------------------------------------------------------------
VEG_SECTION = "noahmp_modis_parameters"
SOIL_SECTION = "noahmp_soil_stas_parameters"
GLOBAL_SECTION = "noahmp_global_parameters"
LAI_MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
              "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]

PARAMS = {
    # --- canopy / photosynthesis (MODIS croplands column) ---
    "VCMX25":    dict(section=VEG_SECTION, row="VCMX25", column="veg"),
    "MP":        dict(section=VEG_SECTION, row="MP", column="veg"),
    "CH2OP":     dict(section=VEG_SECTION, row="CH2OP", column="veg"),
    "CWPVT":     dict(section=VEG_SECTION, row="CWPVT", column="veg"),
    # synthetic multiplier applied to the 12 MODIS monthly LAI rows
    "LAI_SCALE": dict(kind="lai_scale", section=VEG_SECTION, column="veg"),
    # --- global scalars ---
    "RSURF_EXP": dict(section=GLOBAL_SECTION, row="RSURF_EXP", column=None),
    "PSIWLT":    dict(section=GLOBAL_SECTION, row="PSIWLT", column=None),
    "FSATMX":    dict(section=GLOBAL_SECTION, row="FSATMX", column=None),
    "TIMEAN":    dict(section=GLOBAL_SECTION, row="TIMEAN", column=None),
    # --- soil (STAS soil category column) ---
    "MAXSMC":    dict(section=SOIL_SECTION, row="MAXSMC", column="soil"),
    "WLTSMC":    dict(section=SOIL_SECTION, row="WLTSMC", column="soil"),
    "BB":        dict(section=SOIL_SECTION, row="BB", column="soil"),
    "SATDK":     dict(section=SOIL_SECTION, row="SATDK", column="soil"),
    "SATPSI":    dict(section=SOIL_SECTION, row="SATPSI", column="soil"),
}

# read-back tolerance: the table is written with %.10g, so a round trip is exact
# to ~10 significant digits.
READBACK_RTOL = 1e-8
READBACK_ATOL = 1e-12

NML = """&NOAHLSM_OFFLINE
 HRLDAS_SETUP_FILE = "{setup}"
 AGDATA_FLNM = "{agdata}"
 INDIR = "{indir}"
 OUTDIR = "{outdir}"
 START_YEAR={sy}
 START_MONTH={sm}
 START_DAY={sd}
 START_HOUR={sh}
 START_MIN=00
 KHOUR={khour}
 SPINUP_LOOPS={spin}
 FORCING_NAME_T="T2D"
 FORCING_NAME_Q="Q2D"
 FORCING_NAME_U="U2D"
 FORCING_NAME_V="V2D"
 FORCING_NAME_P="PSFC"
 FORCING_NAME_LW="LWDOWN"
 FORCING_NAME_SW="SWDOWN"
 FORCING_NAME_PR="RAINRATE"
 DYNAMIC_VEG_OPTION={dveg}
 CANOPY_STOMATAL_RESISTANCE_OPTION=1
 BTR_OPTION={btr}
 SURFACE_RUNOFF_OPTION={opt_run}
 SUBSURFACE_RUNOFF_OPTION={opt_runsub}
 DVIC_INFILTRATION_OPTION=1
 SURFACE_DRAG_OPTION=1
 FROZEN_SOIL_OPTION=1
 SUPERCOOLED_WATER_OPTION=1
 RADIATIVE_TRANSFER_OPTION=3
 SNOW_ALBEDO_OPTION=1
 SNOW_COMPACTION_OPTION=2
 SNOW_COVER_OPTION=1
 PCP_PARTITION_OPTION=1
 SNOW_THERMAL_CONDUCTIVITY=1
 TBOT_OPTION=2
 TEMP_TIME_SCHEME_OPTION=3
 GLACIER_OPTION=1
 SURFACE_RESISTANCE_OPTION=4
 SOIL_DATA_OPTION=1
 PEDOTRANSFER_OPTION=1
 CROP_OPTION={crop}
 IRRIGATION_OPTION={irr}
 IRRIGATION_METHOD={irrm}
 TILE_DRAINAGE_OPTION=0
 WETLAND_OPTION=0
 FORCING_TIMESTEP=3600
 NOAH_TIMESTEP=1800
 OUTPUT_TIMESTEP=3600
 SPLIT_OUTPUT_COUNT={split_count}
 SKIP_FIRST_OUTPUT=.true.
 RESTART_FREQUENCY_HOURS=0
 NSOIL=4
 soil_thick_input(1)=0.10
 soil_thick_input(2)=0.30
 soil_thick_input(3)=0.60
 soil_thick_input(4)=1.00
 ZLVL={zlvl}
 SF_URBAN_PHYSICS=0
 USE_WUDAPT_LCZ=0
/
"""


class Fail(Exception):
    """Any condition that must produce NO metrics file and a nonzero exit."""


def log(*a):
    print(*a, flush=True)


# ==========================================================================
# CANDIDATE ISOLATION + STALE-OUTPUT SAFETY
# ==========================================================================
# The kit hands every candidate a `--workdir` and reads `--out`.  Three rules
# make an evaluation's score provably its own:
#   1. the model runs ONLY inside `<workdir>/run`, which is REBUILT FROM SCRATCH
#      at the start of every evaluation (reset_rundir), so no artifact of a
#      previous or concurrent candidate can be read as this one's output;
#   2. `<workdir>` is held under an EXCLUSIVE non-blocking lock for the whole
#      evaluation, so two processes can never share one run directory (a retry
#      that collides fails closed instead of interleaving into it);
#   3. `--out` (and its .tmp) is deleted as the FIRST action of main() — before
#      the workdir is created or locked, so the lock itself is inside the guarded
#      region — and again on EVERY failure path, so a failed run leaves NOTHING
#      behind and the kit reads +inf rather than a previous candidate's metrics.
# --------------------------------------------------------------------------
_LOCKS = []                    # keep lock file objects alive for the process


def _lock_dir(path, blocking, what):
    """flock `path`/.kdt_calib.lock.  Non-blocking -> Fail on contention."""
    os.makedirs(path, exist_ok=True)
    fh = open(os.path.join(path, ".kdt_calib.lock"), "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        fh.close()
        if exc.errno in (errno.EACCES, errno.EAGAIN):
            raise Fail(f"{what} {path} is already in use by another calib_run.py "
                       "process — refusing to share a run directory")
        raise
    _LOCKS.append(fh)
    return fh


def clear_metrics(out_path):
    """Remove the metrics artifact (and its temp) — a failed eval writes NOTHING."""
    if not out_path:
        return
    for p in (out_path, out_path + ".tmp"):
        try:
            os.unlink(p)
        except OSError:
            pass


def reset_rundir(rundir):
    """Fresh, empty `<workdir>/run` for THIS candidate.

    Every file the model reads (NoahmpTable.TBL, hrldas_setup.nc, agdata.nc,
    namelist.hrldas) and everything it writes (LDASOUT, RESTART, result JSON) is
    regenerated per evaluation, so wiping the directory can only remove another
    evaluation's state.  Without this a run that died mid-way leaves LDASOUT
    files behind and the NEXT candidate in the same workdir either trips
    final_loop_file() or scores stale output.
    """
    rundir = os.path.abspath(rundir)
    if os.path.dirname(rundir) == rundir or os.path.basename(rundir) != "run":
        raise Fail(f"refusing to reset an unexpected run directory: {rundir}")
    shutil.rmtree(rundir, ignore_errors=True)
    os.makedirs(rundir, exist_ok=True)


# ==========================================================================
# NoahmpTable.TBL editing  (the artifact hrldas.exe reads from its run dir)
# ==========================================================================
def _section_bounds(lines, section):
    start = None
    for i, ln in enumerate(lines):
        if ln.strip().lower().startswith("&" + section.lower()):
            start = i + 1
            break
    if start is None:
        raise Fail(f"section &{section} not found in parameter table")
    for j in range(start, len(lines)):
        if lines[j].strip() == "/":
            return start, j
    raise Fail(f"section &{section} is not terminated in parameter table")


_ROW_RE_CACHE = {}


def _row_index(lines, lo, hi, row):
    rx = _ROW_RE_CACHE.setdefault(row, re.compile(r"^\s*" + re.escape(row) + r"\s*="))
    for i in range(lo, hi):
        if rx.match(lines[i]):
            return i
    raise Fail(f"row {row} not found in the requested parameter-table section")


def _split_row(line):
    """-> (prefix 'NAME = ', value tokens, trailing comment incl. leading '!')."""
    head, _, rest = line.partition("=")
    prefix = head + "="
    comment = ""
    k = rest.find("!")
    if k >= 0:
        comment = rest[k:]
        rest = rest[:k]
    return prefix, rest.split(","), comment


def _fmt(v):
    # repr() is the shortest decimal string that round-trips a double exactly, so
    # every value read back out of the written table is BIT-identical to the one
    # requested (the kit compares requested vs applied on every eval).
    return repr(float(v))


def _row_get(lines, lo, hi, row, col):
    i = _row_index(lines, lo, hi, row)
    _, toks, _ = _split_row(lines[i])
    if col is None:
        vals = [t for t in toks if t.strip()]
        if not vals:
            raise Fail(f"row {row} carries no value")
        return float(vals[0])
    if col < 1 or col > len(toks) or not toks[col - 1].strip():
        raise Fail(f"row {row} has no column {col}")
    return float(toks[col - 1])


def _row_set(lines, lo, hi, row, col, value):
    i = _row_index(lines, lo, hi, row)
    prefix, toks, comment = _split_row(lines[i])
    if col is None:
        nonblank = [k for k, t in enumerate(toks) if t.strip()]
        if not nonblank:
            raise Fail(f"row {row} carries no value")
        toks[nonblank[0]] = " " + _fmt(value)
    else:
        if col < 1 or col > len(toks) or not toks[col - 1].strip():
            raise Fail(f"row {row} has no column {col}")
        toks[col - 1] = " " + _fmt(value)
    lines[i] = prefix + ",".join(toks) + comment


def _lai_months(lines, col):
    """The 12 MODIS monthly LAI values of one land category, in month order."""
    lo, hi = _section_bounds(lines, VEG_SECTION)
    return [_row_get(lines, lo, hi, "LAI_" + m, col) for m in LAI_MONTHS]


# LAI_SCALE is recovered from the ONE month whose shipped table value is exactly
# 1.0 (MODIS croplands: LAI_MAY), so `written / base` returns the requested
# multiplier BIT-exactly for any double.  The rule is fixed in advance, and every
# other month is separately verified to carry the same factor.
_LAI_ANCHOR_BASE = 1.0
_LAI_SCALE_RTOL = 1e-9


def _lai_anchor(base_months):
    for i, v in enumerate(base_months):
        if v == _LAI_ANCHOR_BASE:
            return i
    raise Fail("no MODIS monthly LAI of exactly 1.0 to anchor LAI_SCALE on for "
               "this land category")


def inject_table(dest, requested, veg_col, soil_col):
    """Write the per-eval NoahmpTable.TBL, then read every value back out of it.

    Returns (applied, defaults).  Raises Fail if any handed parameter is unknown
    or does not read back equal to what was requested (a value the model would
    have CLAMPED or an edit that missed its token can never be trusted).
    """
    with open(TBL_SRC, "r") as fh:
        base_lines = fh.read().split("\n")
    lines = list(base_lines)

    unknown = sorted(set(requested) - set(PARAMS))
    if unknown:
        raise Fail(f"unknown parameter(s) in KDT_CALIB_PARAMS: {unknown}")

    def col_of(spec):
        c = spec.get("column")
        return veg_col if c == "veg" else (soil_col if c == "soil" else None)

    # ---- defaults (what the shipped table says), for provenance ----
    defaults = {}
    for name, spec in PARAMS.items():
        if spec.get("kind") == "lai_scale":
            defaults[name] = 1.0
            continue
        lo, hi = _section_bounds(base_lines, spec["section"])
        defaults[name] = _row_get(base_lines, lo, hi, spec["row"], col_of(spec))

    # ---- write ----
    lai_base = _lai_months(base_lines, veg_col)
    anchor = _lai_anchor(lai_base)
    for name, value in requested.items():
        spec = PARAMS[name]
        value = float(value)
        if not math.isfinite(value):
            raise Fail(f"{name}: non-finite requested value {value!r}")
        if spec.get("kind") == "lai_scale":
            lo, hi = _section_bounds(lines, VEG_SECTION)
            for m, base in zip(LAI_MONTHS, lai_base):
                _row_set(lines, lo, hi, "LAI_" + m, veg_col, base * value)
            lines.insert(_section_bounds(lines, VEG_SECTION)[0],
                         " ! KDT_LAI_SCALE = %s" % _fmt(value))
        else:
            lo, hi = _section_bounds(lines, spec["section"])
            _row_set(lines, lo, hi, spec["row"], col_of(spec), value)

    os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
    with open(dest, "w") as fh:
        fh.write("\n".join(lines))

    # ---- read every handed key BACK out of the written file ----
    with open(dest, "r") as fh:
        out_lines = fh.read().split("\n")
    applied = {}
    for name in requested:
        spec = PARAMS[name]
        if spec.get("kind") == "lai_scale":
            written = _lai_months(out_lines, veg_col)
            applied[name] = written[anchor] / lai_base[anchor]
            off = [LAI_MONTHS[i] for i, (w, b) in enumerate(zip(written, lai_base))
                   if not math.isclose(w, b * applied[name],
                                       rel_tol=_LAI_SCALE_RTOL, abs_tol=1e-12)]
            if off:
                raise Fail("LAI_SCALE did not apply uniformly across the monthly "
                           f"climatology; off months: {off}")
        else:
            lo, hi = _section_bounds(out_lines, spec["section"])
            applied[name] = _row_get(out_lines, lo, hi, spec["row"], col_of(spec))

    bad = []
    for name, want in requested.items():
        got = applied[name]
        if not math.isclose(got, float(want), rel_tol=READBACK_RTOL, abs_tol=READBACK_ATOL):
            bad.append(f"{name}: requested {want!r} but the table reads back {got!r}")
    if bad:
        raise Fail("parameter read-back mismatch (value did not apply exactly): "
                   + "; ".join(bad))
    return applied, defaults


# ==========================================================================
# One-time preparation (KI stages s4 + s2) — cached, never per-eval
# ==========================================================================
def _ldasin(fdir):
    return sorted(glob.glob(os.path.join(fdir, "*.LDASIN_DOMAIN1")))


def _check_forcing_provenance(fdir, n_sample=24):
    """Tie the LDASIN forcing to the SAME tower whose LE we score.

    Re-derives T2D for a sample of hours straight from US-Ne1's own
    FULLSET_HR.csv (TA_F, local standard time) and compares.  A forcing
    directory built from any other site/product cannot pass.
    """
    import netCDF4 as nc
    import pandas as pd

    # read-only: the tower record is an immutable obs source
    with open(os.path.join(SITE_DIR, "FULLSET_HR.csv"), "r") as fh:
        hr = pd.read_csv(fh, usecols=["TIMESTAMP_START", "TA_F"])
    hr = hr.replace(-9999.0, np.nan).dropna(subset=["TA_F"])
    hr["dt_local"] = pd.to_datetime(hr["TIMESTAMP_START"].astype("int64").astype(str),
                                    format="%Y%m%d%H%M")
    hr = hr.set_index("dt_local")["TA_F"]

    files = _ldasin(fdir)
    if not files:
        raise Fail(f"no LDASIN files in {fdir}")
    step = max(len(files) // n_sample, 1)
    dmax, n = 0.0, 0
    for f in files[::step][:n_sample]:
        stamp = os.path.basename(f)[:10]
        t_utc = datetime.strptime(stamp, "%Y%m%d%H")
        t_loc = t_utc + timedelta(hours=UTC_OFFSET)
        if t_loc not in hr.index:
            continue
        with nc.Dataset(f, "r") as ds:      # read-only: forcing is an input
            t2d = float(np.asarray(ds["T2D"][:]).ravel()[0])
        dmax = max(dmax, abs(t2d - (float(hr.loc[t_loc]) + 273.15)))
        n += 1
    if n < 5:
        raise Fail("could not match enough LDASIN hours to the US-Ne1 tower record")
    if dmax > 0.05:
        raise Fail(f"forcing does not match the US-Ne1 tower: max |dT| = {dmax:.4f} K "
                   f"over {n} sampled hours")
    return {"checked_hours": n, "max_abs_dT_K": dmax}


def prepare(prep_dir):
    """Idempotent: forcing (s4) + preflight + soil (s2) + forcing-mean air T.

    CONCURRENCY: candidates run in their own --workdir but SHARE this prep cache,
    so the whole body is serialised under a BLOCKING lock on prep_dir and every
    artifact is published with an atomic os.replace.  A second candidate that
    arrives while the first is preparing waits, then reads the finished JSON —
    it can never observe a half-written cache or race the forcing build.
    """
    import netCDF4 as nc

    os.makedirs(prep_dir, exist_ok=True)
    prep_json = os.path.join(prep_dir, "calib_prep.json")
    fdir = os.path.join(prep_dir, "forcing")

    def _cached():
        try:
            with open(prep_json) as fh:
                prep = json.load(fh)
        except (OSError, ValueError):
            return None
        if prep.get("version") == 3 and os.path.isdir(prep.get("forcing_dir", "")) \
                and len(_ldasin(prep["forcing_dir"])) == N_LDASIN_EXPECTED:
            return prep
        return None

    hit = _cached()
    if hit is not None:
        return hit
    _lock_dir(prep_dir, blocking=True, what="preparation cache")
    hit = _cached()                     # another process may have just built it
    if hit is not None:
        return hit

    # ---- s4 forcing (reuse if the validated real case already built it) ----
    if len(_ldasin(fdir)) != N_LDASIN_EXPECTED:
        staged = "/mnt/extreme_ssd1/hc_detached/Noah_MP/real_case_usne1/cell/forcing"
        if (not os.path.exists(fdir)) and len(_ldasin(staged)) == N_LDASIN_EXPECTED:
            os.symlink(staged, fdir)
        else:
            os.makedirs(fdir, exist_ok=True)
            r = subprocess.run(
                [sys.executable, os.path.join(TOOLS, "convert_forcing_to_noahmp.py"),
                 "--input_dir", SITE_DIR, "--output_dir", fdir,
                 "--lat", str(SITE_LAT), "--lon", str(SITE_LON),
                 "--start_date", FORCE_START_DATE, "--end_date", FORCE_END_DATE,
                 "--timestep", "3600", "--source", "fluxnet",
                 "--utc_offset", str(UTC_OFFSET)],
                capture_output=True, text=True)
            log(r.stdout[-1500:])
            if r.returncode != 0:
                log("STDERR:", r.stderr[-1500:])
    n_for = len(_ldasin(fdir))
    if n_for != N_LDASIN_EXPECTED:
        raise Fail(f"forcing has {n_for} LDASIN files, expected {N_LDASIN_EXPECTED}")

    provenance = _check_forcing_provenance(fdir)

    # ---- mandatory forcing preflight (the KI's own validator) ----
    r = subprocess.run([sys.executable, PREFLIGHT, fdir, "--source", "auto", "--json"],
                       capture_output=True, text=True)
    txt = r.stdout.strip()
    i = txt.find("{")
    if i < 0:
        raise Fail("forcing preflight produced no JSON")
    pf = json.loads(txt[i:txt.rfind("}") + 1])
    if pf.get("n_fail"):
        raise Fail(f"forcing preflight FAILED: {pf.get('errors')}")

    # ---- s2 soil ----
    from ki_tools_common.soil_utils import lookup_hwsd
    p = lookup_hwsd(SITE_LAT, SITE_LON)
    sand, clay = float(p["sand"]), float(p["clay"])
    soil_json = os.path.join(prep_dir, "soil.json")
    soil_tmp = "%s.%d.tmp" % (soil_json, os.getpid())
    r = subprocess.run([sys.executable, os.path.join(TOOLS, "convert_soil_to_noahmp.py"),
                        "--lat", str(SITE_LAT), "--lon", str(SITE_LON),
                        "--sand", str(sand), "--clay", str(clay),
                        "--output", soil_tmp], capture_output=True, text=True)
    if r.returncode != 0:
        raise Fail(f"convert_soil_to_noahmp failed: {r.stderr[-800:]}")
    with open(soil_tmp) as fh:
        isltyp = int(json.load(fh)["noahmp_isltyp"])
    os.replace(soil_tmp, soil_json)     # published only once complete
    if isltyp != EXPECTED_ISLTYP:
        raise Fail(f"resolved ISLTYP {isltyp} != the target case's {EXPECTED_ISLTYP}")

    # ---- forcing-mean air temperature (TMN / TSK / TSLB initialisation) ----
    tsum, n = 0.0, 0
    for f in _ldasin(fdir):
        with nc.Dataset(f, "r") as ds:      # read-only: forcing is an input
            tsum += float(np.asarray(ds["T2D"][:]).ravel()[0])
        n += 1
    tmean = tsum / max(n, 1)

    prep = {"version": 3, "site_id": TARGET_SITE_ID, "forcing_dir": fdir,
            "n_forcing": n_for, "isltyp": isltyp, "sand": sand, "clay": clay,
            "tmean": tmean, "forcing_provenance": provenance,
            "preflight": {"all_pass": pf.get("all_pass"), "n_fail": pf.get("n_fail"),
                          "n_warn": pf.get("n_warn"), "source": pf.get("source")}}
    prep_tmp = "%s.%d.tmp" % (prep_json, os.getpid())
    with open(prep_tmp, "w") as fh:
        json.dump(prep, fh, indent=2)
    os.replace(prep_tmp, prep_json)     # the cache appears only once complete
    return prep


# ==========================================================================
# Model run (KI stage s1 + s6) and output read (s7)
# ==========================================================================
def build_and_run(rundir, prep, requested, khour, spinup, timeout, start_stamp=None):
    from build_hrldas_setup import build_setup_file, build_agdata_file, \
        table_gvf, validate_setup_file

    reset_rundir(rundir)      # candidate isolation: no artifact of any other eval
    tbl = os.path.join(rundir, "NoahmpTable.TBL")
    applied, defaults = inject_table(tbl, requested, IVGTYP, prep["isltyp"])

    # SHDMAX/SHDMIN/LAI_init come from the INJECTED table so the canopy fraction
    # stays consistent with whatever LAI_SCALE did.
    shdmax, shdmin, laimax = table_gvf(tbl, IVGTYP)
    setup = os.path.join(rundir, "hrldas_setup.nc")
    agdata = os.path.join(rundir, "agdata.nc")
    build_setup_file(setup, SITE_LAT, SITE_LON, SITE_ELEV, IVGTYP, prep["isltyp"],
                     prep["tmean"], 0.30, shdmax, shdmin, laimax,
                     title="HYDROCRAFT NOAHMP %s CALIB" % TARGET_SITE_ID)
    problems = validate_setup_file(setup)
    if problems:
        raise Fail(f"setup file validation failed: {problems}")
    build_agdata_file(agdata, irfract=1.0, sifract=1.0, mifract=0.0, fifract=0.0)

    f0 = start_stamp or os.path.basename(_ldasin(prep["forcing_dir"])[0])
    if not os.path.isfile(os.path.join(prep["forcing_dir"], f0[:10] + ".LDASIN_DOMAIN1")):
        raise Fail(f"no LDASIN forcing at the requested start {f0[:10]}")
    nml = os.path.join(rundir, "namelist.hrldas")
    with open(nml, "w") as fh:
        fh.write(NML.format(setup=setup, agdata=agdata, indir=prep["forcing_dir"],
                            outdir=rundir + "/", sy=int(f0[0:4]), sm=int(f0[4:6]),
                            sd=int(f0[6:8]), sh=int(f0[8:10]), khour=khour,
                            spin=spinup, split_count=khour, zlvl=ZLVL, **CONFIG))

    res_json = os.path.join(rundir, "run_noahmp_result.json")
    subprocess.run([sys.executable, os.path.join(TOOLS, "run_noahmp.py"),
                    "--source_dir", SRCDIR, "--run_dir", rundir,
                    "--namelist", nml, "--binary", BIN, "--skip_compile",
                    "--timeout", str(timeout), "--output_json", res_json],
                   capture_output=True, text=True)

    # ---- FAIL-CLOSED run health: a missing/None diagnostic is never a pass ----
    if not os.path.isfile(res_json):
        raise Fail("run_noahmp.py wrote no result JSON")
    with open(res_json, "r") as fh:
        rr = json.load(fh)
    status, rc = rr.get("status"), rr.get("return_code")
    if status is None or rc is None:
        raise Fail(f"run_noahmp.py reported status={status!r} return_code={rc!r}")
    if status != "completed" or int(rc) != 0:
        raise Fail(f"hrldas.exe did not terminate normally (status={status}, rc={rc})")
    # run_noahmp.py ALWAYS reports n_output_files, and this driver republishes it in
    # __kdt__.run_health — so a missing/None value is a claimed diagnostic that went
    # absent and must fail the eval closed, never be defaulted to something passing.
    n_out = rr.get("n_output_files")
    if n_out is None:
        raise Fail("run_noahmp.py reported no n_output_files — a run-health "
                   "diagnostic this driver republishes cannot be absent")
    if int(n_out) < 1:
        raise Fail(f"hrldas.exe wrote {n_out} LDASOUT files")

    return tbl, applied, defaults, rr, dict(shdmax=shdmax, shdmin=shdmin, lai_init=laimax)


def final_loop_file(rundir):
    """Only the LAST spin-up loop is the scored simulation (`.loopNNNN`)."""
    allf = glob.glob(os.path.join(rundir, "*.LDASOUT_DOMAIN1.loop*"))
    if allf:
        idx = {}
        for f in allf:
            m = re.search(r"\.loop(\d+)$", f)
            if m:
                idx.setdefault(int(m.group(1)), []).append(f)
        if not idx:
            raise Fail("LDASOUT loop files carry no loop index")
        files = sorted(idx[max(idx)])
    else:
        files = sorted(glob.glob(os.path.join(rundir, "*.LDASOUT_DOMAIN1")))
    if len(files) != 1:
        raise Fail(f"expected exactly one final-loop LDASOUT file, found {len(files)}")
    return files[0]


def read_series(ds, name):
    """Time series at the single column, dimension order read from the variable's
    OWN dimension names (mirrors parse_noahmp_output.extract_point, but over the
    whole Time axis instead of one record).  Returns (ntime,) or (ntime, nlayer).
    """
    import parse_noahmp_output as P
    if name not in ds.variables:
        return None
    var = ds.variables[name]
    dims = [d.lower() for d in var.dimensions]
    idx, layer_axis, time_axis = [], None, None
    for a, dname in enumerate(dims):
        if dname == "time":
            time_axis = a
            idx.append(slice(None))
        elif dname in ("south_north", "south_north_stag", "y", "lat"):
            idx.append(0)
        elif dname in ("west_east", "west_east_stag", "x", "lon"):
            idx.append(0)
        elif dname in P._LAYER_DIMS or "layer" in dname or "level" in dname:
            layer_axis = a
            idx.append(slice(None))
        else:
            idx.append(0)
    if time_axis is None:
        return None
    arr = np.asarray(var[tuple(idx)], dtype=float)
    if layer_axis is not None and arr.ndim == 2 and time_axis > layer_axis:
        arr = arr.T
    return np.where(arr <= P.LDASOUT_FILL, np.nan, arr)


def read_output(rundir, khour):
    import netCDF4 as nc
    import pandas as pd
    import parse_noahmp_output as P

    path = final_loop_file(rundir)
    with nc.Dataset(path, "r") as ds:
        times = ds.variables["Times"][:]
        stamps = ["".join(
            [c.decode() if isinstance(c, bytes) else str(c) for c in row]).strip()
            for row in np.asarray(times)]
        out = {v: read_series(ds, v) for v in
               ("LH", "ECAN", "EDIR", "ETRAN", "SFCRNOFF", "UGDRNOFF",
                "SNEQV", "WA", "LAI", "FVEG", "SOIL_M", "IRSIVOL", "IRELOSS")}
        # cross-check the vectorised reader against the KI's own single-record
        # extractor, so this fast path cannot silently disagree with stage s7.
        ref = P.extract_point(ds, "LH", 0, 0)
        if ref is not None and not math.isclose(float(ref), float(out["LH"][0]),
                                                rel_tol=1e-9, abs_tol=1e-9):
            raise Fail("vectorised LDASOUT read disagrees with "
                       "parse_noahmp_output.extract_point")

    nt = len(stamps)
    if nt != khour:
        raise Fail(f"final-loop LDASOUT holds {nt} output times, expected {khour}")
    if out["LH"] is None:
        raise Fail("LDASOUT carries no LH")
    if not np.isfinite(out["LH"]).all():
        raise Fail(f"{int((~np.isfinite(out['LH'])).sum())} non-finite LH values in "
                   f"the scored simulation")

    dt_utc = pd.to_datetime(pd.Series(stamps), format="%Y-%m-%d_%H:%M:%S")
    df = pd.DataFrame({"dt_utc": dt_utc, "LH": out["LH"]})
    for v in ("ECAN", "EDIR", "ETRAN", "SFCRNOFF", "UGDRNOFF", "SNEQV", "WA",
              "LAI", "FVEG", "IRSIVOL", "IRELOSS"):
        df[v] = out[v] if out[v] is not None else np.nan
    soil = out["SOIL_M"]
    for k in range(4):
        df[f"soil{k}"] = soil[:, k] if soil is not None else np.nan
    df["dt_local"] = df["dt_utc"] + timedelta(hours=UTC_OFFSET)
    df["date"] = df["dt_local"].dt.normalize()
    return df, nt


# ==========================================================================
# Observations
# ==========================================================================
def resolve_site():
    """Derive the station identity from the obs location actually used."""
    site_dir = os.path.abspath(SITE_DIR)
    site_id = os.path.basename(site_dir)
    obs_path = os.path.join(site_dir, OBS_FILE_NAME)
    if site_id != TARGET_SITE_ID:
        raise Fail(f"resolved station {site_id!r} is not the target case "
                   f"{TARGET_SITE_ID!r}")
    if not os.path.isfile(obs_path):
        raise Fail(f"obs file not found: {obs_path}")
    return site_id, obs_path


def load_obs(obs_path, split):
    """Read + ASSERT the whole declared obs envelope for this split."""
    import pandas as pd

    # read-only: an immutable obs source must never be opened for writing
    with open(obs_path, "r") as fh:
        d = pd.read_csv(fh, usecols=lambda c: c in (
            "TIMESTAMP", OBS_COL, OBS_QC_COL, "LE_CORR", "P_F"))
    for c in ("TIMESTAMP", OBS_COL, OBS_QC_COL, "P_F"):
        if c not in d.columns:
            raise Fail(f"obs file {obs_path} is missing required column {c}")
    d = d.replace(-9999.0, np.nan)
    d["date"] = pd.to_datetime(d["TIMESTAMP"].astype("int64").astype(str),
                               format="%Y%m%d")

    start, end = SPLIT_WINDOWS[split]
    want = OBS_CONTRACT[split]
    if (want["start"], want["end"]) != (start, end):
        raise Fail("obs contract window disagrees with the split window")

    w = d[(d.date >= start) & (d.date <= end)].sort_values("date").reset_index(drop=True)
    q = w[(w[OBS_QC_COL].isna()) | (w[OBS_QC_COL] >= OBS_QC_MIN)]
    q = q.dropna(subset=[OBS_COL]).reset_index(drop=True)

    # --- the exact date set: one row per calendar day, no gaps, no duplicates
    cal = pd.date_range(start, end, freq="D")
    if len(w) != len(cal) or not (w.date.values == cal.values).all():
        raise Fail(f"obs date set for split {split!r} is not the contiguous daily "
                   f"calendar {start}..{end} ({len(w)} rows vs {len(cal)} days)")

    checks = {
        "rows": (len(w), want["rows"], 0),
        "n_qc": (len(q), want["n_qc"], 0),
        "mean": (float(q[OBS_COL].mean()), want["mean"], 1e-4),
        "min": (float(q[OBS_COL].min()), want["min"], 1e-4),
        "max": (float(q[OBS_COL].max()), want["max"], 1e-4),
        "std": (float(q[OBS_COL].std()), want["std"], 1e-4),
        "precip_mm": (float(w["P_F"].sum()), want["precip_mm"], 1e-3),
    }
    bad = [f"{k}: got {got!r}, contract says {exp!r}"
           for k, (got, exp, tol) in checks.items() if abs(got - exp) > tol]
    if bad:
        raise Fail(f"obs contract violated for split {split!r}: " + "; ".join(bad))

    return d, w, q, {k: v[0] for k, v in checks.items()}


# ==========================================================================
# Eval
# ==========================================================================
def evaluate(args, requested, split):
    import pandas as pd
    from ki_tools_common.metrics import all_metrics
    from ki_tools_common.validation import validate_water_balance

    # The obs envelope is asserted BEFORE the (10-minute) model run, so a changed
    # or corrupted series fails the eval closed without burning a simulation.
    site_id, obs_path = resolve_site()
    obs_all, obs_win, obs_qc, obs_checked = load_obs(obs_path, split)

    prep = prepare(args.prep_dir)
    rundir = os.path.join(args.workdir, "run")

    tbl, applied, defaults, rr, veg = build_and_run(
        rundir, prep, requested, args.khour, args.spinup, args.timeout)
    sim, nt = read_output(rundir, args.khour)

    daily = sim.groupby("date").agg(
        sim_LE=("LH", "mean"), n_hr=("LH", "size"),
        ECAN=("ECAN", "mean"), EDIR=("EDIR", "mean"), ETRAN=("ETRAN", "mean"),
        SFCRNOFF=("SFCRNOFF", "last"), UGDRNOFF=("UGDRNOFF", "last"),
        IRSIVOL=("IRSIVOL", "last"), IRELOSS=("IRELOSS", "last"),
        SNEQV=("SNEQV", "last"), WA=("WA", "last"),
        LAI=("LAI", "mean"), FVEG=("FVEG", "mean"),
        s0=("soil0", "last"), s1=("soil1", "last"),
        s2=("soil2", "last"), s3=("soil3", "last")).reset_index()
    daily = daily[daily.n_hr == 24].reset_index(drop=True)

    m = daily.merge(obs_qc[["date", OBS_COL]], on="date", how="inner")
    m = m.dropna(subset=["sim_LE", OBS_COL]).reset_index(drop=True)
    if len(m) < 200:
        raise Fail(f"only {len(m)} paired daily records for split {split!r}")

    idx = pd.DatetimeIndex(m.date)
    raw = all_metrics(pd.Series(m[OBS_COL].values.astype(float), index=idx),
                      pd.Series(m.sim_LE.values.astype(float), index=idx),
                      label="calib")
    metrics = {}
    for k in ("NSE", "KGE", "PBIAS", "RMSE", "R"):
        v = raw.get(k, raw.get(k.lower()))
        if v is None or not np.isfinite(float(v)):
            raise Fail(f"metric {k} is {v!r} — refusing to report a partial score")
        metrics[k.lower()] = float(v)

    # ---- water balance over the WHOLE simulated record (soft dag diagnostic,
    #      but a missing/None value fails the eval closed) ----
    fs, fe = SPLIT_WINDOWS["full"]
    sc = daily[(daily.date >= fs) & (daily.date <= fe)].reset_index(drop=True)
    if len(sc) < 3000:
        raise Fail(f"only {len(sc)} complete simulated days over {fs}..{fe}")
    hourly = sim[(sim.date >= fs) & (sim.date <= fe)].reset_index(drop=True)
    et_mm = float(np.nansum((hourly.ECAN + hourly.EDIR + hourly.ETRAN) * 3600.0))

    def acc(col):
        """Period total of an LDASOUT running accumulator [mm]."""
        v = hourly[col].values.astype(float)
        return float(np.nan_to_num(v[-1] - v[0]))

    irr_mm, irr_loss = acc("IRSIVOL"), acc("IRELOSS")
    ro_mm = acc("SFCRNOFF") + acc("UGDRNOFF")
    dS = float(np.sum((np.array([hourly[f"soil{k}"].values[-1] for k in range(4)]) -
                       np.array([hourly[f"soil{k}"].values[0] for k in range(4)])) * SOIL_DZ_MM)) \
        + float(hourly.SNEQV.values[-1] - hourly.SNEQV.values[0]) \
        + float(hourly.WA.values[-1] - hourly.WA.values[0])
    p_mm = float(obs_all[(obs_all.date >= fs) & (obs_all.date <= fe)].P_F.sum())
    wb = validate_water_balance(precip_mm=p_mm + irr_mm, et_mm=et_mm + irr_loss,
                                runoff_mm=ro_mm, delta_storage_mm=dS,
                                period_days=int(len(sc)))
    wb_status, wb_pct = wb.get("status"), wb.get("residual_pct")
    if wb_status is None or wb_pct is None or not np.isfinite(float(wb_pct)):
        raise Fail(f"water-balance diagnostic missing (status={wb_status!r}, "
                   f"residual_pct={wb_pct!r})")
    if wb_status == "FAIL":
        raise Fail(f"water balance FAILED closure: residual {wb.get('residual_mm')} mm "
                   f"({wb_pct:.2f}% of P) — the run is not scorable")

    period = (str(m.date.min().date()), str(m.date.max().date()))
    scored_obs = (f"{OBS_SOURCE}:{site_id}:{OBS_COL} [{OBS_UNIT}] {obs_path} "
                  f"{period[0]}..{period[1]} n={len(m)} split={split}")
    case_id = "SITE:" + site_id
    if case_id != TARGET_CASE_ID:
        raise Fail(f"derived case_id {case_id!r} != target {TARGET_CASE_ID!r}")

    out = dict(metrics)
    out["__kdt__"] = {
        "applied_params": applied,
        "case_id": case_id,
        "scored_obs": scored_obs,
        "station_id": site_id,
        "network": TARGET_NETWORK,
        "station_lat": SITE_LAT,
        "station_lon": SITE_LON,
        "station_elev_m": SITE_ELEV,
        "dag_var": DAG_VAR,
        "obs_shape": OBS_SHAPE,
        "determining_metric": DETERMINING_METRIC,
        "obs_file": obs_path,
        "obs_column": OBS_COL,
        "obs_unit": OBS_UNIT,
        "obs_qc_min": OBS_QC_MIN,
        "split": split,
        "scored_period": list(period),
        "n_paired": int(len(m)),
        "obs_contract_checked": obs_checked,
        "parameter_defaults": defaults,
        "parameter_table": tbl,
        "run_health": {
            "hrldas_status": rr.get("status"),
            "hrldas_return_code": rr.get("return_code"),
            "n_output_files": rr.get("n_output_files"),
            "n_output_times": int(nt),
            "n_nonfinite_LH": 0,
            "water_balance_status": wb_status,
            "water_balance_residual_pct": float(wb_pct),
        },
        "water_balance": {"precip_mm": p_mm, "irrigation_mm": irr_mm,
                          "et_mm": et_mm, "irrigation_evap_loss_mm": irr_loss,
                          "runoff_mm": ro_mm, "dStorage_mm": dS},
        "configuration": dict(CONFIG, spinup_loops=args.spinup, khour=args.khour,
                              zlvl=ZLVL, ivgtyp=IVGTYP, isltyp=prep["isltyp"],
                              shdmax_pct=veg["shdmax"], lai_init=veg["lai_init"]),
        "sim_mean_LE_Wm2": float(m.sim_LE.mean()),
        "obs_mean_LE_Wm2": float(m[OBS_COL].mean()),
        "sim_max_LAI": float(daily.LAI.max()),
    }
    return out, rundir


def cleanup(rundir):
    for pat in ("*.LDASOUT_DOMAIN1*", "RESTART.*"):
        for f in glob.glob(os.path.join(rundir, pat)):
            try:
                os.remove(f)
            except OSError:
                pass


# ==========================================================================
def read_requested(args):
    """The candidate vector, from KDT_CALIB_PARAMS (the kit's runner contract).

    `--set` is accepted ONLY together with `--readback-probe`, which never emits
    metrics; a scoring evaluation always takes its vector from KDT_CALIB_PARAMS
    so the kit's requested-vs-applied diff cannot be bypassed.
    """
    if args.set:
        if not args.readback_probe:
            raise Fail("--set is a commissioning flag and is only accepted with "
                       "--readback-probe; a scored evaluation must take its "
                       "vector from KDT_CALIB_PARAMS")
        return {k: float(v) for k, v in (s.split("=", 1) for s in args.set)}
    path = os.environ.get("KDT_CALIB_PARAMS", "")
    if not path:
        return {}
    if not os.path.isfile(path):
        raise Fail(f"KDT_CALIB_PARAMS points at a missing file: {path}")
    with open(path, "r") as fh:
        vec = json.load(fh)
    if not isinstance(vec, dict):
        raise Fail("KDT_CALIB_PARAMS must hold a JSON object {name: value}")
    return {k: float(v) for k, v in vec.items()}


def resolve_split():
    s = os.environ.get("KDT_CALIB_SPLIT", "").strip().lower()
    if s in ("", "both", "all"):
        return "full"
    if s not in SPLIT_WINDOWS:
        raise Fail(f"KDT_CALIB_SPLIT={s!r} is not one of "
                   f"{sorted(SPLIT_WINDOWS)} — refusing to guess a scoring window")
    return s


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--out", default=None)
    ap.add_argument("--prep-dir", default=DEFAULT_PREP_DIR,
                    help="cache for the one-time forcing/soil preparation")
    ap.add_argument("--timeout", type=int, default=10800)
    ap.add_argument("--keep-output", action="store_true")
    ap.add_argument("--set", action="append", default=[],
                    help="NAME=VALUE (commissioning only; overrides KDT_CALIB_PARAMS)")
    ap.add_argument("--readback-probe", action="store_true",
                    help="commissioning only: short run, writes a probe JSON with "
                         "__kdt__.applied_params and NO metrics")
    a = ap.parse_args()
    a.khour = KHOUR
    a.spinup = SPINUP_LOOPS

    # STALE-OUTPUT SAFETY: the metrics artifact is removed BEFORE ANY other work —
    # before the workdir is even created or locked.  EVERY exit path below is
    # therefore covered, INCLUDING lock contention (which raises before the model
    # ever runs): the kit reads +inf, never a previous candidate's metrics.
    clear_metrics(a.out)
    try:
        os.makedirs(a.workdir, exist_ok=True)
        # CANDIDATE ISOLATION: this process owns <workdir> (and therefore
        # <workdir>/run) exclusively for the whole evaluation.  Concurrent
        # candidates get DIFFERENT workdirs from the kit and so never contend; a
        # retry that reuses a workdir still in flight fails closed instead of
        # writing into a live run directory.
        _lock_dir(a.workdir, blocking=False, what="workdir")
        return _run(a)
    except BaseException:
        clear_metrics(a.out)             # never leave a previous candidate's metrics
        if not a.keep_output:
            cleanup(os.path.join(a.workdir, "run"))
        raise


def _run(a):
    requested = read_requested(a)

    if a.readback_probe:
        # 60 simulated days across the PEAK GROWING SEASON (2004-06-01 ..
        # 2004-07-31), no spin-up: long enough to prove the value applies
        # EXACTLY and that the canopy/soil physics stays numerically stable at
        # that bound, cheap enough to probe every bound of every parameter.
        a.khour, a.spinup = 1440, 0
        prep = prepare(a.prep_dir)
        rundir = os.path.join(a.workdir, "run")
        tbl, applied, defaults, rr, veg = build_and_run(
            rundir, prep, requested, a.khour, a.spinup, a.timeout,
            start_stamp="2004060100")
        sim, nt = read_output(rundir, a.khour)
        probe = {"probe": True, "__kdt__": {
            "applied_params": applied, "requested_params": requested,
            "case_id": TARGET_CASE_ID, "station_id": TARGET_SITE_ID,
            "run_health": {"hrldas_status": rr.get("status"),
                           "hrldas_return_code": rr.get("return_code"),
                           "n_output_times": int(nt),
                           "n_nonfinite_LH": 0},
            "lh_mean_Wm2": float(np.mean(sim.LH.values)),
            "lai_max": float(np.nanmax(sim.LAI.values)),
            "parameter_table": tbl}}
        cleanup(rundir)
        if a.out:
            with open(a.out + ".tmp", "w") as fh:
                json.dump(probe, fh, indent=2)
            os.replace(a.out + ".tmp", a.out)
        log(json.dumps(probe["__kdt__"]["applied_params"], indent=2))
        return 0

    if not a.out:
        raise Fail("--out is required")
    split = resolve_split()
    out, rundir = evaluate(a, requested, split)
    if not a.keep_output:
        cleanup(rundir)
    tmp = a.out + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(out, fh, indent=2)
    os.replace(tmp, a.out)          # the metrics file appears only once complete
    log(json.dumps({k: v for k, v in out.items() if k != "__kdt__"}, indent=2))
    log("applied_params: " + json.dumps(out["__kdt__"]["applied_params"]))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:                                   # noqa: BLE001
        print("CALIB_RUN FAILED: %s" % exc, file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)
