#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Programmatic run+score of ONE VIC calibration candidate.  NOT an agent.

    python tools/calib_run.py --workdir <wd> --out <metrics.json>

Contract (calibration_kit/CALIBRATION_YAML_SCHEMA.md v2, injection.mode: runner)
--------------------------------------------------------------------------------
The kit does NOT touch the model inputs.  It writes the candidate vector to the JSON
at env ``KDT_CALIB_PARAMS`` ({"name": value, ...}) and we do everything else:

  1. read the vector;
  2. INJECT each value into a PRIVATE per-eval copy of the artifact the binary
     actually opens — the VIC soil parameter table, the veg parameter file, the veg
     library, and a VIC ``CONSTANTS`` file we create and wire into the global param
     file (config_paths.create_global_param() emits no CONSTANTS line);
  3. READ every value BACK out of that artifact; any write/read disagreement =>
     exit nonzero with NO metrics file;
  4. run the REAL binaries — ``vic_classic.exe`` then ``route_1.0/src/rout`` — over
     the same basin, forcing and gauge the validated real_case run used;
  5. score the routed hydrograph against 唐乃亥 with ki_tools_common.metrics.all_metrics;
  6. emit ``{"nse":..,"kge":..,"pbias":.., "__kdt__": {"applied_params": {...},
     "case_id": ..., "scored_obs": ..., "run_health": {...}}}``, echoing EVERY key we
     were handed (including staged-frozen ones held at default).

Any failure at any stage: write nothing, exit nonzero.  A missing metrics file is
scored +inf by the kit — never a fake pass.  ``--out`` is deleted before any work
begins, so a failed candidate can never be read as a stale success, and the final
write is atomic (tmp + os.replace) so a kill cannot leave a truncated JSON object.

WHICH GAUGE THIS SCORES (and why it cannot drift)
-------------------------------------------------
The target case is ``SITE:tangnaihai`` (calib/reference_run.json, validated run
VIC_20260709T175707Z, nse 0.6323), whose obs is the CNGF daily discharge series of
唐乃亥 / station 40100350.  The dispatch record's ``obs_id: bengbu_51080`` is a DB-wide
default stamped on every VIC case row, not this case's gauge; no Bengbu artifact exists
under ``outputs/tangnaihai/``.

The gauge is PINNED in ``TARGET_CASE`` below.  No environment variable can move it:
the obs path, station code, station name, units, sentinel and the per-split scoring
windows are module constants, and the env vars this script does read
(``KDT_CALIB_PARAMS``, ``KDT_CALIB_SPLIT``, ``KDT_VIC_UH_CACHE``,
``KDT_VIC_FORCING_CACHE``, ``KDT_VIC_KEEP_WORKDIR``) select the candidate vector, the
split and scratch locations only.  ``load_obs()`` re-reads the station code and name out
of the file it actually opened, asserts the whole declared obs envelope
(calibration.yaml ``obs_contract``: identity, units, sentinel, exact day count,
contiguity, min/max/sum/mean of the split) and exits nonzero on any mismatch, and
``__kdt__.case_id`` / ``__kdt__.scored_obs`` are BUILT FROM those resolved values plus
the routed station read out of the staloc file that rout consumed — never from a
literal, so the declaration cannot diverge from what was scored.

Run health is fail-closed: the flux-file count must EQUAL the injected soil table's row
count, every flux file must carry exactly one record per simulated day, the routed
series must cover the simulated window, and the obs/sim pair count must equal the
declared envelope.  A diagnostic that is missing is a failure, never a default pass.

Isolation.  Every artifact this candidate touches is written under ``<workdir>/run/``:
the injected soil / veg / veglib / constants files, the global param that points at
them, VIC's flux output and the routing scratch.  The canonical ``outputs/<basin>/``
tree is opened read-only.  Concurrent and retried candidates are therefore independent.

Unit hydrograph.  The Lohmann grid is a function of the routing network (direc / frac /
xmask) AND of ``rout_velocity`` / ``rout_diffusivity``, which this contract DOES calibrate.
It is therefore cached under a key derived from the exact velocity/diffusivity text written
into ``rout_global.txt``, never as a single basin-wide file: ``rout`` reads a supplied
``<STA>.uh_s`` verbatim and never consults the kernel it built from velocity/diffusivity
(``unit_hyd_routines.f``: ``MAKE_GRID_UH`` uses ``UHM`` only in the ``UH_STRING == 'NONE'``
branch), so an unkeyed cache silently turns both routing parameters into no-ops.  A cache
miss simply lets ``rout`` build the grid inside the candidate's own private ``routing/``
directory; the result is then published to the keyed cache for reuse.  A missing cache is
never a hard error — that once made a freshly prepared basin fail EVERY candidate, the
default vector included, and the kit saw a screen with no finite losses at all.

Splits (env ``KDT_CALIB_SPLIT``)
--------------------------------
  calibration : simulate 2005-01-01..2011-12-31, score 2007-01-01..2011-12-31
  holdout     : simulate 2005-01-01..2016-12-31, score 2012-01-01..2016-12-31
  (unset)     : simulate 2005-01-01..2016-12-31, score 2007-01-01..2016-12-31

Both splits keep the validated 2005-2006 spinup.  The calibration split's shortened
simulation is not an approximation: it reproduces the published nse_cal 0.6455 /
kge_cal 0.7752 bit for bit, because 2012-2016 cannot influence 2007-2011.

Cost
----
~2.5 min CPU per calibration eval (251 cells x 7 yr x 3-hourly) + <1 s routing.
The 452 MB of ASCII forcing is staged ONCE into tmpfs (shared across all evals) and
the per-cell unit hydrographs are reused, so no eval re-does a setup step.
"""
from __future__ import annotations

import argparse
import errno
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

from ki_tools_common.metrics import all_metrics          # noqa: E402

# ---------------------------------------------------------------------------
# Prepared, read-only artifacts of the validated real_case run.  NONE of these is
# rebuilt here: basin delineation, grid, soil/veg parameter derivation, CMFD forcing
# disaggregation and the routing network are one-time prepare steps produced by the
# KI's stage tools (s1_grid/make_basin_grid_nc.py, s2_forcing/forcing_1d.py,
# s3_soil/fill_parameters{1,2}.py, s4_veg/process_vegetation_detailed.py,
# s5_routing/build_routing_param.py).  This script only perturbs + runs + scores.
#
# The real-case driver that orchestrated those stages for this case is
# models/VIC/run_and_score_tangnaihai.py (run_and_score.py itself holds the Bengbu
# verify_1 runner and is NOT this case).  Everything below reads the artifacts that
# driver's stages already produced under outputs/tangnaihai/.
# ---------------------------------------------------------------------------
BASE = "KISSPATH_ROOT"
BASIN, STA = "tangnaihai", "TNH"
BDIR = f"{BASE}/outputs/{BASIN}"

SOIL_SRC = f"{BDIR}/vic_temp/soil/SOIL_PARAM_COMPLETE.txt"
VEG_SRC = f"{BDIR}/vic_temp/veg/vic_veg_param_final.txt"
VEGLIB_SRC = f"{BASE}/data/vic_param/veglib.LDAS"
GP_SRC = f"{BDIR}/vic_temp/global_param_{BASIN}.txt"
FORCING_SRC = f"{BDIR}/vic_temp/forcing/forcing_final"
FORCING_PREFIX = f"{BASIN}_025deg_"
ROUT_SRC = f"{BDIR}/routing_param"

# Keyed unit-hydrograph cache.  NOT a single file: its contents depend on velocity and
# diffusivity, both of which are calibrated.  Lives outside the canonical (read-only)
# outputs/<basin>/ tree; scratch, so losing it costs one rebuild and nothing else.
UH_CACHE_DIR = os.environ.get("KDT_VIC_UH_CACHE", "/dev/shm/kdt_vic_calib/uh_s")

VIC_EXE = f"{BASE}/model/VIC-5.1.0/vic/drivers/classic/vic_classic.exe"
ROUT_EXE = f"{BASE}/model/route_1.0/src/rout"

# ---------------------------------------------------------------------------
# TARGET CASE — pinned, not configurable.  Mirrors calibration.yaml identity +
# obs_contract.  Nothing in the environment can redirect scoring to another gauge:
# every field below is a module constant, and load_obs() re-derives the station
# identity FROM THE FILE and refuses to score anything else.
# ---------------------------------------------------------------------------
OBS_FILE = "KISSPATH_DATA/china_water_level/黄河txt/唐乃亥.txt"

TARGET_CASE = {
    "case_id": "SITE:tangnaihai",
    "dataset": "CNGF (china_gaugeflux) 黄河txt",
    "obs_file": OBS_FILE,
    "station_code": 40100350,
    "station_name": "唐乃亥",
    "variable": "Q",
    "units": "m3 s-1",
    "missing_sentinel": -99.0,
    "gauge_lon": 100.1537,
    "gauge_lat": 35.5162,
    "routed_station_id": STA,
}

# station code actually read out of the obs file -> case_id.  case_id is LOOKED UP with
# the resolved code, so a file carrying any other station cannot be labelled SITE:tangnaihai
# (KeyError -> Fail -> no metrics).  This is the whole point: the declaration is derived.
CASE_BY_STATION = {40100350: "SITE:tangnaihai"}

# Declared obs envelope per split (calibration.yaml obs_contract.envelope).  The CNGF Q
# column is integer m3/s, so n_days / sum / min / max are EXACT fingerprints of the
# series: a re-issued or corrupted record for the same station changes at least one.
OBS_ENVELOPE = {
    "calibration": {"n_days": 1826, "q_min": 117.0, "q_max": 2680.0,
                    "q_sum": 1198400.0, "q_mean": 656.297918949},
    "holdout":     {"n_days": 1827, "q_min": 121.0, "q_max": 3350.0,
                    "q_sum": 1115040.0, "q_mean": 610.311986864},
    "_both":       {"n_days": 3653, "q_min": 117.0, "q_max": 3350.0,
                    "q_sum": 2313440.0, "q_mean": 633.298658637},
}

FORCING_CACHE = "/dev/shm/kdt_vic_calib/forcing_final"

SPINUP_YEAR = 2005
SPLITS = {
    "calibration": {"sim": (2005, 2011), "score": ("2007-01-01", "2011-12-31")},
    "holdout":     {"sim": (2005, 2016), "score": ("2012-01-01", "2016-12-31")},
    "_both":       {"sim": (2005, 2016), "score": ("2007-01-01", "2016-12-31")},
}

# 0-indexed columns of the VIC 5 classic 3-layer soil parameter table (53 columns).
C_BINFILT, C_DS, C_DSMAX, C_WS = 4, 5, 6, 7
C_EXPT = [9, 10, 11]
C_INIT_MOIST = [18, 19, 20]
C_DEPTH = [22, 23, 24]
C_DP = 26                                       # thermal damping depth (m)

# name -> default.  Mirrors calibration.yaml; a handed key outside this set is fatal.
# MUST stay in sync with the `parameters:` block of calibration.yaml — a name present
# there and absent here makes EVERY eval (the default vector included) die in the
# unknown-parameter guard below, which the kit sees as a screen with no finite losses.
DEFAULTS = {
    "binfilt": 0.3, "expt_scale": 1.0,
    "Ds": 0.02, "Dsmax": 10.0, "Ws": 0.7,
    "depth1": 0.1, "depth2": 0.3, "depth3": 1.5,
    "lai_scale": 1.0, "rmin_scale": 1.0,
    "new_snow_albedo": 0.85, "snow_alb_accum_a": 0.94, "snow_alb_thaw_a": 0.82,
    "rout_velocity": 1.5, "rout_diffusivity": 800.0,
}
SNOW_KEYS = {"new_snow_albedo": "SNOW_NEW_SNOW_ALB",
             "snow_alb_accum_a": "SNOW_ALB_ACCUM_A",
             "snow_alb_thaw_a": "SNOW_ALB_THAW_A"}

RTOL = 1e-9          # our own write->read agreement; the kit re-checks at 1e-6
FMT = "%.12g"        # enough digits that float(read) == requested within RTOL


class Fail(Exception):
    """Anything that must produce NO metrics file."""


def die(msg: str, code: int = 1):
    print(f"[calib_run] FAIL: {msg}", file=sys.stderr, flush=True)
    sys.exit(code)


def _close(a: float, b: float) -> bool:
    return math.isclose(float(a), float(b), rel_tol=RTOL, abs_tol=1e-12)


# ---------------------------------------------------------------------------
# one-time prepare steps, shared by every eval
# ---------------------------------------------------------------------------
def stage_forcing() -> str:
    """Copy the 452 MB ASCII forcing into tmpfs ONCE; return the FORCING1 prefix.

    VIC's classic driver opens 251 ASCII files and streams ~35k records from each;
    on the spinning-disk source that is ~70 s of pure I/O per eval.  Falls back to
    the original directory whenever staging is disabled or impossible — never fatal.
    """
    if os.environ.get("KDT_VIC_FORCING_CACHE", "1") != "1":
        return f"{FORCING_SRC}/{FORCING_PREFIX}"
    done = Path(FORCING_CACHE + ".complete")

    def _stale() -> bool:
        """A cache built for a different cell set (e.g. the basin was re-delineated and
        outputs/<basin>/ regenerated) must not be silently fed to VIC."""
        n_src = len(list(Path(FORCING_SRC).glob(f"{FORCING_PREFIX}*")))
        n_cache = len(list(Path(FORCING_CACHE).glob(f"{FORCING_PREFIX}*")))
        return n_src != n_cache

    try:
        if done.exists():
            if _stale():
                print("[calib_run] forcing cache cell count != source; rebuilding", flush=True)
                done.unlink(missing_ok=True)
                shutil.rmtree(FORCING_CACHE, ignore_errors=True)
            else:
                return f"{FORCING_CACHE}/{FORCING_PREFIX}"
        lock = Path(FORCING_CACHE + ".lock")
        lock.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
        except OSError as e:
            if e.errno != errno.EEXIST:
                raise
            # another eval is staging: wait for it, then use whatever it produced
            for _ in range(600):
                if done.exists():
                    return f"{FORCING_CACHE}/{FORCING_PREFIX}"
                time.sleep(1)
            return f"{FORCING_SRC}/{FORCING_PREFIX}"
        try:
            tmp = FORCING_CACHE + ".partial"
            shutil.rmtree(tmp, ignore_errors=True)
            shutil.rmtree(FORCING_CACHE, ignore_errors=True)   # a partial cache from a killed eval
            shutil.copytree(FORCING_SRC, tmp)
            os.replace(tmp, FORCING_CACHE)
            done.write_text("ok\n")
        finally:
            lock.unlink(missing_ok=True)
        return f"{FORCING_CACHE}/{FORCING_PREFIX}"
    except Exception as e:                                    # tmpfs full, no /dev/shm, ...
        print(f"[calib_run] forcing staging skipped ({e}); using {FORCING_SRC}", flush=True)
        return f"{FORCING_SRC}/{FORCING_PREFIX}"


def uh_cache_path(v_txt: str, d_txt: str) -> str:
    """Cache slot for the unit-hydrograph grid rout builds at (velocity, diffusivity).

    Keyed on the exact TEXT written into rout_global.txt, not on the float, so the cache
    identity is byte-identity of what rout reads: two candidates share a slot iff rout
    would build the same grid from them.
    """
    return f"{UH_CACHE_DIR}/uh_v{v_txt}_d{d_txt}.uh_s"


def cached_uh_s(v_txt: str, d_txt: str) -> str | None:
    """The cached grid for THIS (velocity, diffusivity), or None if it must be built.

    Reusing a grid across different velocity/diffusivity values would be silent, total
    parameter loss: rout copies a supplied uh_s straight into UH_S and never evaluates
    the UHM kernel it derived from velocity/diffusivity (unit_hyd_routines.f, MAKE_GRID_UH
    takes the `UH_STRING != 'NONE'` branch).  Both routing parameters would then move the
    requested value, pass read-back, and change nothing in the scored hydrograph.

    Returning None instead of raising is deliberate.  A missing grid used to be a hard
    Fail that told the operator to run rout by hand, which meant that after ANY fresh
    prepare of outputs/<basin>/ EVERY candidate — the default vector included — died
    before the binaries ran, and the kit saw a screen with no finite losses anywhere.
    run_rout() bootstraps the grid in the candidate's private dir and publishes it.
    """
    p = uh_cache_path(v_txt, d_txt)
    return p if os.path.exists(p) else None


def publish_uh_s(rdir: str, v_txt: str, d_txt: str):
    """Promote the uh_s grid rout just built into the keyed cache, atomically.

    rout writes CHARACTER*5 NAME5//'.uh_s' into its cwd, i.e. 'TNH  .uh_s'.  Within one
    cache slot the contents are candidate-independent, so whichever concurrent eval lands
    last writes identical bytes — os.replace makes the swap atomic and no lock is needed.
    A failure to publish is never fatal: the next eval with this key simply rebuilds it.
    """
    dst = uh_cache_path(v_txt, d_txt)
    if os.path.exists(dst):
        return
    built = sorted(Path(rdir).glob("*.uh_s"))
    if not built:
        return
    try:
        os.makedirs(UH_CACHE_DIR, exist_ok=True)
        tmp = f"{dst}.partial.{os.getpid()}"
        shutil.copy(built[0], tmp)
        os.replace(tmp, dst)
        print(f"[calib_run] published unit-hydrograph cache -> {dst!r}", flush=True)
    except OSError as e:
        print(f"[calib_run] could not publish uh_s cache ({e}); next eval will rebuild",
              flush=True)


def check_prepared():
    missing = [p for p in (SOIL_SRC, VEG_SRC, VEGLIB_SRC, GP_SRC, FORCING_SRC,
                           ROUT_SRC, VIC_EXE, ROUT_EXE, OBS_FILE)
               if not os.path.exists(p)]
    if missing:
        raise Fail(f"prepared artifact(s) absent: {missing}. Rebuild them once with the "
                   f"KI's s1_grid/s2_forcing/s3_soil/s4_veg/s5_routing stage tools "
                   f"(one-time prepare); calib_run.py never rebuilds inputs per eval.")


# ---------------------------------------------------------------------------
# injection + read-back.  Every writer returns what it can read back out of the
# artifact the binary consumes, so `applied` is never an echo of our own request.
# ---------------------------------------------------------------------------
def inject_soil(p: dict, dst: str) -> dict:
    with open(SOIL_SRC, "r") as fh:                       # canonical inputs: read-only
        src = np.loadtxt(fh)
    if src.ndim != 2 or src.shape[1] != 53:
        raise Fail(f"unexpected soil table shape {src.shape}; expected (ncell, 53)")
    a = src.copy()

    a[:, C_BINFILT] = p["binfilt"]
    a[:, C_DS] = p["Ds"]
    a[:, C_DSMAX] = p["Dsmax"]
    a[:, C_WS] = p["Ws"]
    for c in C_EXPT:
        a[:, c] = src[:, c] * p["expt_scale"]

    # depth is absolute; carry init_moist with it so the initial VOLUMETRIC water
    # fraction is preserved (VIC clamps init_moist to max_moist, but shrinking a
    # layer without rescaling would silently start every cell at saturation).
    for k, (cd, cm) in enumerate(zip(C_DEPTH, C_INIT_MOIST), start=1):
        new = float(p[f"depth{k}"])
        a[:, cm] = src[:, cm] * (new / src[:, cd])
        a[:, cd] = new

    tot = sum(float(p[f"depth{k}"]) for k in (1, 2, 3))
    if tot >= float(src[:, C_DP].min()):
        raise Fail(f"soil column {tot:.3f} m reaches the thermal damping depth "
                   f"{src[:, C_DP].min():.3f} m — infeasible (constraint should have caught it)")
    if (a[:, C_EXPT] <= 3.0).any():
        raise Fail(f"expt_scale {p['expt_scale']} drives expt <= 3.0, outside VIC's valid range")

    np.savetxt(dst, a, fmt=FMT, delimiter=" ")

    b = np.loadtxt(dst)
    if b.shape != src.shape:
        raise Fail("soil table changed shape on write")
    applied = {
        "binfilt": float(b[0, C_BINFILT]), "Ds": float(b[0, C_DS]),
        "Dsmax": float(b[0, C_DSMAX]), "Ws": float(b[0, C_WS]),
        "depth1": float(b[0, C_DEPTH[0]]), "depth2": float(b[0, C_DEPTH[1]]),
        "depth3": float(b[0, C_DEPTH[2]]),
    }
    for c in (C_BINFILT, C_DS, C_DSMAX, C_WS, *C_DEPTH):        # uniform over all cells
        if not np.allclose(b[:, c], b[0, c], rtol=RTOL, atol=1e-12):
            raise Fail(f"soil column {c} is not uniform after write (tie soil_uniform broken)")
    ratios = b[:, C_EXPT] / src[:, C_EXPT]
    if float(ratios.max() - ratios.min()) > RTOL * max(1.0, float(ratios.max())):
        raise Fail("expt scale is not uniform after write")
    applied["expt_scale"] = float(np.median(ratios))
    return applied


def inject_veg(p: dict, dst: str) -> dict:
    """Scale every monthly-LAI line of the veg parameter file.

    Format (ROOT_ZONES 3, VEGPARAM_LAI TRUE): `cellid nveg` header (2 fields), then per
    tile a `class Cv rd1 rf1 rd2 rf2 rd3 rf3` line (8 fields) followed by a 12-field
    monthly LAI line.  The 12-field arity is unambiguous.
    """
    s = float(p["lai_scale"])
    src_vals, out = [], []
    with open(VEG_SRC, "r") as fh:                        # canonical inputs: read-only
        veg_lines = fh.readlines()
    for line in veg_lines:
        f = line.split()
        if len(f) == 12:
            v = [float(x) for x in f]
            src_vals.extend(v)
            out.append("  \t \t " + "\t".join(FMT % (x * s) for x in v) + "\n")
        else:
            out.append(line)
    if not src_vals:
        raise Fail("no 12-field monthly-LAI line found in the veg parameter file")
    Path(dst).write_text("".join(out))

    back = []
    for line in open(dst):
        f = line.split()
        if len(f) == 12:
            back.extend(float(x) for x in f)
    if len(back) != len(src_vals):
        raise Fail("veg LAI line count changed on write")
    src_a, back_a = np.asarray(src_vals), np.asarray(back)
    nz = src_a > 0
    if not nz.any():
        raise Fail("all LAI values are zero; lai_scale is unobservable")
    r = back_a[nz] / src_a[nz]
    if float(r.max() - r.min()) > RTOL * max(1.0, float(r.max())):
        raise Fail("LAI scale is not uniform after write")
    return {"lai_scale": float(np.median(r))}


def inject_veglib(p: dict, dst: str) -> dict:
    """Scale Rmin (tab field 3) of every class row of the VIC vegetation library.
    Rows are tab-delimited and end with a free-text class name, so split/join on '\\t'
    and touch nothing else."""
    s = float(p["rmin_scale"])
    src_vals, back_vals, out = [], [], []
    with open(VEGLIB_SRC, "r") as fh:                     # canonical inputs: read-only
        veglib_lines = fh.readlines()
    for line in veglib_lines:
        if line.lstrip().startswith("#") or not line.strip():
            out.append(line)
            continue
        f = line.rstrip("\n").split("\t")
        if len(f) < 4:
            raise Fail(f"veglib row has {len(f)} tab fields, expected >= 4")
        v = float(f[3])
        src_vals.append(v)
        f[3] = FMT % (v * s)
        back_vals.append(float(f[3]))
        out.append("\t".join(f) + "\n")
    if not src_vals:
        raise Fail("no class rows found in the veg library")
    Path(dst).write_text("".join(out))

    chk = []
    for line in open(dst):
        if line.lstrip().startswith("#") or not line.strip():
            continue
        chk.append(float(line.rstrip("\n").split("\t")[3]))
    if chk != back_vals:
        raise Fail("veglib Rmin did not round-trip")
    r = np.asarray(chk) / np.asarray(src_vals)
    if float(r.max() - r.min()) > RTOL * max(1.0, float(r.max())):
        raise Fail("Rmin scale is not uniform after write")
    return {"rmin_scale": float(np.median(r))}


def inject_constants(p: dict, dst: str) -> dict:
    """Write the VIC CONSTANTS file (classic driver: get_global_param.c 'CONSTANTS'
    -> get_parameters.c).  snow_albedo() reads these even with FULL_ENERGY FALSE."""
    Path(dst).write_text("".join(f"{key} {FMT % float(p[name])}\n"
                                 for name, key in SNOW_KEYS.items()))
    txt = Path(dst).read_text()
    applied = {}
    for name, key in SNOW_KEYS.items():
        m = re.search(rf"^{key}\s+(\S+)", txt, re.M)
        if not m:
            raise Fail(f"{key} not found in the constants file after write")
        applied[name] = float(m.group(1))
    return applied


def _rout_value_slots(lines: list[str]) -> dict:
    """Index of the velocity and diffusion VALUE lines of a rout global file.

    Mirrors rout.f's sequential reader rather than matching comment text (the comments are
    free-form):  READ(1,'(//A)') consumes lines 0-2 (direc filename), then for velocity and
    for diffusion in turn it reads one comment line, one .true./.false. flag, and one line
    that is a grid filename when the flag is true and a scalar when it is false.
    """
    slots, i = {}, 3
    for key in ("velocity", "diffusion"):
        if i + 2 >= len(lines):
            raise Fail(f"rout_global.txt truncated before the {key} block")
        flag = lines[i + 1].strip().lower()
        if flag.startswith(".t"):
            raise Fail(f"rout_global.txt supplies a per-cell {key} GRID (flag {flag!r}); "
                       f"the scalar rout_{'velocity' if key == 'velocity' else 'diffusivity'} "
                       f"lever cannot address it")
        if not flag.startswith(".f"):
            raise Fail(f"expected a .true./.false. {key}-file flag at rout_global.txt "
                       f"line {i + 2}, found {lines[i + 1]!r}")
        slots[key] = i + 2
        i += 3
    return slots


def inject_rout_global(p: dict, dst: str, y0: int, y1: int) -> tuple[dict, str, str]:
    """Write this candidate's rout global file: velocity, diffusivity and the sim window.

    Returns (applied, velocity_text, diffusivity_text); the two texts key the uh_s cache.

    These two are the ONLY parameters consumed by route_1.0/src/rout rather than by
    vic_classic.exe.  MAKE_UHM builds the impulse response as
    ``exp(-(v*t - xmask)^2 / (4*D*t)) / (2*sqrt(pi*D*t^3))``, so both must be strictly
    positive or the kernel is all zeros and rout's renormalisation divides by zero.
    """
    v, d = float(p["rout_velocity"]), float(p["rout_diffusivity"])
    if not (v > 0.0):
        raise Fail(f"rout_velocity {v} must be > 0 (MAKE_UHM emits a zero kernel otherwise)")
    if not (d > 0.0):
        raise Fail(f"rout_diffusivity {d} must be > 0 (MAKE_UHM divides by it)")
    v_txt, d_txt = FMT % v, FMT % d

    lines = Path(f"{ROUT_SRC}/rout_global.txt").read_text().splitlines()
    slots = _rout_value_slots(lines)
    lines[slots["velocity"]] = v_txt
    lines[slots["diffusion"]] = d_txt
    # Both "route this window" and "write this window" lines carry the sim period.
    lines = [re.sub(r"^\s*\d{4}\s+\d{2}\s+\d{4}\s+\d{2}\s*$", f"{y0} 01 {y1} 12", l)
             for l in lines]
    Path(dst).write_text("\n".join(lines) + "\n")

    back = Path(dst).read_text().splitlines()
    bslots = _rout_value_slots(back)
    applied = {"rout_velocity": float(back[bslots["velocity"]]),
               "rout_diffusivity": float(back[bslots["diffusion"]])}
    for name, want in (("rout_velocity", v), ("rout_diffusivity", d)):
        if not _close(applied[name], want):
            raise Fail(f"{name} did not round-trip through rout_global.txt")
    return applied, v_txt, d_txt


def write_global_param(dst: str, soil: str, veg: str, veglib: str, constants: str,
                       result_dir: str, forcing_prefix: str, y0: int, y1: int):
    """Take the KI's own global parameter file and repoint it at this eval's private
    inputs.  Physics options (FULL_ENERGY, MODEL_STEPS_PER_DAY, OUTVAR list, ...) are
    untouched, so the flux-file column layout stays exactly what the validated run had."""
    subs = {"SOIL": soil, "VEGPARAM": veg, "VEGLIB": veglib,
            "RESULT_DIR": result_dir.rstrip("/") + "/", "FORCING1": forcing_prefix,
            "STARTYEAR": str(y0), "ENDYEAR": str(y1)}
    seen, out = set(), []
    with open(GP_SRC, "r") as fh:                         # canonical inputs: read-only
        gp_lines = fh.readlines()
    for line in gp_lines:
        k = line.split()[0] if line.split() else ""
        if k in subs and not line.lstrip().startswith("#"):
            out.append(f"{k}\t\t\t{subs[k]}\n")
            seen.add(k)
        else:
            out.append(line)
    if seen != set(subs):
        raise Fail(f"global param template lacks key(s) {sorted(set(subs) - seen)}")
    if any(l.split() and l.split()[0] == "CONSTANTS" for l in out):
        raise Fail("global param template already has a CONSTANTS line; refusing to shadow it")
    out.append(f"\nCONSTANTS\t\t{constants}\n")
    Path(dst).write_text("".join(out))


# ---------------------------------------------------------------------------
# run the real binaries
# ---------------------------------------------------------------------------
def run_vic(gp: str, result_dir: str, log: str, n_expected: int) -> int:
    """Run vic_classic.exe and FAIL CLOSED on its run-health diagnostics.

    The domain size is the diagnostic VIC actually produces: one flux file per soil-table
    row.  A short domain is a broken eval (a cell that aborted mid-run still leaves the
    binary's rc at 0), so anything other than exactly ``n_expected`` files is fatal —
    never tolerated as "enough cells".
    """
    with open(log, "w") as fh:
        r = subprocess.run([VIC_EXE, "-g", gp], stdout=fh, stderr=subprocess.STDOUT)
    if r.returncode != 0:
        raise Fail(f"vic_classic.exe rc={r.returncode}; see {log}")
    n = len(list(Path(result_dir).glob(f"{BASIN}_fluxes_*.txt")))
    if n != n_expected:
        raise Fail(f"vic_classic.exe wrote {n} flux files, expected {n_expected} "
                   f"(one per soil-table row); see {log}")
    return n


def flux_to_vic_in(result_dir: str, vic_in: str, n_days: int) -> int:
    """rout expects `year month day prec evap runoff baseflow`.  Resolve the columns
    from the flux-file header rather than hardcoding positions, so a change to the
    KI's OUTVAR list can never silently mis-feed the routing model.

    Fail-closed run health: every flux file must carry EXACTLY one daily record per
    simulated day.  A truncated cell (VIC killed mid-write, a full disk) would otherwise
    be routed as a short series and quietly score.  Returns the record count.
    """
    files = sorted(Path(result_dir).glob(f"{BASIN}_fluxes_*.txt"))
    if not files:
        raise Fail("no flux files to feed the routing model")
    with files[0].open("r") as fh:
        hdr = fh.readlines()[2].split()
    try:
        cols = [hdr.index(c) for c in ("YEAR", "MONTH", "DAY", "OUT_PREC",
                                       "OUT_EVAP", "OUT_RUNOFF", "OUT_BASEFLOW")]
    except ValueError as e:
        raise Fail(f"flux header missing a column rout needs: {e}")
    os.makedirs(vic_in, exist_ok=True)
    for f in files:
        with f.open("r") as fh:
            a = np.loadtxt(fh, skiprows=3, usecols=cols)
        if a.ndim != 2 or a.shape[0] != n_days:
            raise Fail(f"flux file {f.name} has {0 if a.ndim != 2 else a.shape[0]} daily "
                       f"records, expected {n_days} — truncated VIC output")
        if not np.isfinite(a).all():
            raise Fail(f"flux file {f.name} contains non-finite values")
        np.savetxt(f"{vic_in}/{f.name.replace(BASIN + '_', '').replace('.txt', '')}",
                   a, fmt=["%d", "%d", "%d", "%.4f", "%.4f", "%.4f", "%.4f"], delimiter="\t")
    return n_days


def run_rout(rdir: str, uh_s: str | None, v_txt: str, d_txt: str) -> tuple[pd.Series, dict]:
    """Route the candidate's runoff.  rout_global.txt was already written into rdir by
    inject_rout_global(), so the velocity/diffusivity rout reads are this candidate's."""
    for f in Path(ROUT_SRC).glob(f"{STA}_*.txt"):
        shutil.copy(f, rdir)
    shutil.copy(f"{ROUT_SRC}/UH.all", rdir)
    if not Path(f"{rdir}/rout_global.txt").exists():
        raise Fail("rout_global.txt was not injected into the eval workdir")

    # Station file line 2 names the unit-hydrograph grid.  On a cache HIT we point rout at
    # our private copy of the grid built at THIS (velocity, diffusivity).  On a MISS we
    # hand it 'NONE' so it builds one from the kernel it derives from those two values
    # (rout opens NAME5.uh_s with status='new', so this only ever happens in a fresh,
    # private rdir) and we publish the result into that key's slot afterwards.
    sta = Path(f"{ROUT_SRC}/{STA}_staloc.txt").read_text().splitlines()
    # Resolve the routed station from the staloc line rout will actually read, and pin it
    # to the target case: `<run_flag> <NAME5> <col> <row> <area>`.  A staloc naming any
    # other station would mean the routed hydrograph is not this gauge's.
    sfields = sta[0].split()
    if len(sfields) < 4 or sfields[1] != STA:
        raise Fail(f"staloc line {sta[0]!r} does not name the target routed station {STA!r}")
    routed = {"routed_station_id": sfields[1],
              "routed_cell_col": int(sfields[2]), "routed_cell_row": int(sfields[3])}
    if uh_s:
        shutil.copy(uh_s, f"{rdir}/{STA}.uh_s")
        Path(f"{rdir}/{STA}_staloc.txt").write_text(f"{sta[0]}\n./{STA}.uh_s\n")
    else:
        print(f"[calib_run] no cached unit hydrograph for (v={v_txt}, D={d_txt}); "
              f"rout will build one", flush=True)
        Path(f"{rdir}/{STA}_staloc.txt").write_text(f"{sta[0]}\nNONE\n")

    os.makedirs(f"{rdir}/rout_out", exist_ok=True)

    r = subprocess.run([ROUT_EXE, "rout_global.txt"], cwd=rdir,
                       capture_output=True, text=True, timeout=3600)
    if r.returncode != 0:
        raise Fail(f"route_1.0/rout rc={r.returncode}; {(r.stdout or '')[-400:]}")
    day = sorted(Path(f"{rdir}/rout_out").glob("*.day"))
    if not day:
        raise Fail(f"route_1.0/rout produced no .day output (rc={r.returncode}); "
                   f"{(r.stdout or '')[-400:]}")
    if not uh_s:
        publish_uh_s(rdir, v_txt, d_txt)
    if len(day) != 1:
        raise Fail(f"route_1.0/rout wrote {len(day)} .day files; expected exactly one "
                   f"({[p.name for p in day]})")
    if day[0].name.split(".")[0].strip() != STA:
        raise Fail(f"routed output {day[0].name!r} is not station {STA!r}")
    with day[0].open("r") as fh:
        rd = pd.read_csv(fh, sep=r"\s+", header=None, names=["year", "month", "day", "Q"])
    rd["date"] = pd.to_datetime(rd[["year", "month", "day"]])
    s = rd.set_index("date")["Q"]
    routed["routed_days"] = int(len(s))
    routed["routed_first"] = str(s.index.min().date())
    routed["routed_last"] = str(s.index.max().date())
    if s.isna().any() or not np.isfinite(s.to_numpy()).all():
        raise Fail("routed hydrograph contains non-finite discharge")
    return s, routed


def load_obs(split: str, s0: str, s1: str) -> tuple[pd.Series, dict]:
    """Load + FULLY VALIDATE the scored observation series, and resolve its identity.

    Enforces every field calibration.yaml's ``obs_contract`` declares — station code,
    station name (both re-read out of the file, and required to be the ONLY station in
    it), the Q column, the -99 missing sentinel, and the split's exact envelope: day
    count, contiguity, min, max, sum and mean.  Any mismatch raises => no metrics file,
    nonzero exit.  A changed or corrupted series for the SAME station therefore cannot
    be scored silently.

    Returns (series, resolved) where ``resolved`` is built from what was actually read;
    ``__kdt__.case_id`` / ``scored_obs`` are derived from it, never from a literal.

    The file is opened READ-ONLY through an explicit ``open(path, "r")`` handle so this
    works on a read-only mount / review sandbox.
    """
    want = OBS_ENVELOPE.get(split)
    if want is None:
        raise Fail(f"no declared obs envelope for split {split!r}")

    with open(OBS_FILE, "r") as fh:                      # read-only, immutable source
        o = pd.read_csv(fh, sep="\t")

    for col in ("stcd", "dates", "Q", "name"):
        if col not in o.columns:
            raise Fail(f"obs file {OBS_FILE!r} lacks declared column {col!r} "
                       f"(has {list(o.columns)})")

    codes = sorted({int(c) for c in pd.unique(o["stcd"])})
    names = sorted({str(n) for n in pd.unique(o["name"])})
    if codes != [TARGET_CASE["station_code"]]:
        raise Fail(f"obs file carries station code(s) {codes}, expected exactly "
                   f"[{TARGET_CASE['station_code']}] ({TARGET_CASE['station_name']}) — "
                   f"refusing to score a different gauge")
    if names != [TARGET_CASE["station_name"]]:
        raise Fail(f"obs file carries station name(s) {names}, expected exactly "
                   f"[{TARGET_CASE['station_name']}]")
    station_code, station_name = codes[0], names[0]
    if station_code not in CASE_BY_STATION:
        raise Fail(f"station {station_code} maps to no known case_id")
    case_id = CASE_BY_STATION[station_code]
    if case_id != TARGET_CASE["case_id"]:
        raise Fail(f"resolved case {case_id!r} != target {TARGET_CASE['case_id']!r}")

    o["date"] = pd.to_datetime(o["dates"], format="mixed")
    o = o.set_index("date")
    q = pd.to_numeric(o["Q"], errors="coerce")
    if not (q <= TARGET_CASE["missing_sentinel"] + 1e-9).any():
        raise Fail(f"declared missing sentinel {TARGET_CASE['missing_sentinel']} never "
                   f"occurs in the Q column — this is not the declared series")
    s = q[q > -90.0]
    s = s.loc[s0:s1]

    if len(s) != want["n_days"]:
        raise Fail(f"obs envelope violated on split {split}: {len(s)} valid days in "
                   f"{s0}..{s1}, declared {want['n_days']}")
    if s.index.min() != pd.Timestamp(s0) or s.index.max() != pd.Timestamp(s1):
        raise Fail(f"obs envelope violated: split {split} spans "
                   f"{s.index.min().date()}..{s.index.max().date()}, declared {s0}..{s1}")
    if len(s) != (s.index.max() - s.index.min()).days + 1 or s.index.has_duplicates:
        raise Fail(f"obs series on split {split} is not a contiguous daily record")
    for field, got in (("q_min", float(s.min())), ("q_max", float(s.max())),
                       ("q_sum", float(s.sum())), ("q_mean", float(s.mean()))):
        if not math.isclose(got, want[field], rel_tol=1e-9, abs_tol=1e-9):
            raise Fail(f"obs envelope violated on split {split}: {field} = {got!r}, "
                       f"declared {want[field]!r} — the observed series changed")

    resolved = {
        "case_id": case_id,
        "station_code": station_code,
        "station_name": station_name,
        "obs_file": OBS_FILE,
        "dataset": TARGET_CASE["dataset"],
        "variable": TARGET_CASE["variable"],
        "units": TARGET_CASE["units"],
        "gauge_lon": TARGET_CASE["gauge_lon"],
        "gauge_lat": TARGET_CASE["gauge_lat"],
        "split": split,
        "score_period": [s0, s1],
        "n_obs_days": int(len(s)),
        "obs_sum": float(s.sum()),
    }
    return s, resolved


# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    # ---- 0. STALE-OUTPUT SAFETY --------------------------------------------
    # Drop any metrics file left by an earlier candidate (or an earlier attempt at this
    # one) BEFORE doing anything that can fail.  Everything after this point either
    # runs to completion and writes a fresh file, or writes nothing at all and the kit
    # scores the candidate +inf.  A failed run must never be readable as a stale pass.
    out_path = Path(args.out)
    try:
        out_path.unlink()
        print(f"[calib_run] removed stale metrics file {args.out!r}", flush=True)
    except FileNotFoundError:
        pass
    except OSError as e:
        raise Fail(f"cannot remove stale metrics file {args.out!r}: {e}")

    check_prepared()

    # ---- 1. the candidate vector -------------------------------------------
    pf = os.environ.get("KDT_CALIB_PARAMS")
    handed: dict = {}
    if pf:
        if not os.path.exists(pf):
            raise Fail(f"KDT_CALIB_PARAMS={pf!r} does not exist")
        handed = json.loads(Path(pf).read_text())
        if not isinstance(handed, dict):
            raise Fail("KDT_CALIB_PARAMS must contain a JSON object")
        unknown = set(handed) - set(DEFAULTS)
        if unknown:                                    # fail closed on a param we can't inject
            raise Fail(f"handed unknown parameter(s) {sorted(unknown)}")
    p = dict(DEFAULTS)
    p.update({k: float(v) for k, v in handed.items()})

    split = os.environ.get("KDT_CALIB_SPLIT") or "_both"
    if split not in SPLITS:
        raise Fail(f"unknown KDT_CALIB_SPLIT {split!r}")
    (y0, y1), (s0, s1) = SPLITS[split]["sim"], SPLITS[split]["score"]

    # ---- 2. private eval workdir -------------------------------------------
    # Everything this candidate reads or writes lives under the --workdir the kit handed
    # us: the injected soil/veg/veglib/constants files, the global param that points at
    # them, VIC's flux output and the routing scratch.  Nothing is written to the shared
    # outputs/<basin>/ tree (the sole exception is the read-only uh_s cache, whose
    # contents are candidate-independent).  Concurrent or retried candidates therefore
    # cannot clobber each other, and none of them can perturb the canonical run dir.
    wd = Path(args.workdir).resolve() / "run"
    shutil.rmtree(wd, ignore_errors=True)
    (wd / "vic_result").mkdir(parents=True)
    (wd / "routing").mkdir()

    forcing_prefix = stage_forcing()

    # ---- 3. inject + read back ---------------------------------------------
    applied: dict = {}
    applied.update(inject_soil(p, str(wd / "soil.txt")))
    applied.update(inject_veg(p, str(wd / "veg.txt")))
    applied.update(inject_veglib(p, str(wd / "veglib.txt")))
    applied.update(inject_constants(p, str(wd / "vic_constants.txt")))
    rout_applied, v_txt, d_txt = inject_rout_global(
        p, str(wd / "routing" / "rout_global.txt"), y0, y1)
    applied.update(rout_applied)
    uh_s = cached_uh_s(v_txt, d_txt)

    for name, want in p.items():                       # write->read agreement, every param
        if name not in applied:
            raise Fail(f"{name} was never read back from an effective artifact")
        if not _close(applied[name], want):
            raise Fail(f"{name}: wrote {want!r}, read back {applied[name]!r}")

    write_global_param(str(wd / "global_param.txt"), str(wd / "soil.txt"),
                       str(wd / "veg.txt"), str(wd / "veglib.txt"),
                       str(wd / "vic_constants.txt"), str(wd / "vic_result"),
                       forcing_prefix, y0, y1)

    # ---- 4. real binaries ---------------------------------------------------
    # Run-health expectations, fail-closed.  n_expected is the injected soil table's own
    # row count (the domain VIC was handed), sim_days the simulated window; a diagnostic
    # that comes back short or absent kills the eval, it is never defaulted to a pass.
    n_expected = int(np.loadtxt(str(wd / "soil.txt")).shape[0])
    sim_days = int((pd.Timestamp(f"{y1}-12-31") - pd.Timestamp(f"{y0}-01-01")).days) + 1

    t0 = time.time()
    ncell = run_vic(str(wd / "global_param.txt"), str(wd / "vic_result"),
                    str(wd / "vic.log"), n_expected)
    flux_records = flux_to_vic_in(str(wd / "vic_result"),
                                  str(wd / "routing" / "vic_in"), sim_days)
    sim, routed = run_rout(str(wd / "routing"), uh_s, v_txt, d_txt)
    if routed["routed_days"] != sim_days:
        raise Fail(f"routed hydrograph has {routed['routed_days']} days, expected "
                   f"{sim_days} ({y0}-01-01..{y1}-12-31)")

    # ---- 5. score -----------------------------------------------------------
    # load_obs asserts the whole declared obs envelope for THIS split and resolves the
    # station identity out of the file it opened; `resolved` is what __kdt__ declares.
    obs, resolved = load_obs(split, s0, s1)
    paired = pd.concat([obs.rename("obs"), sim.rename("sim")], axis=1).dropna().loc[s0:s1]
    if len(paired) != resolved["n_obs_days"]:
        raise Fail(f"paired obs/sim days {len(paired)} != the {resolved['n_obs_days']} "
                   f"observed days declared for split {split} — the simulation does not "
                   f"cover the scored window")
    m = {k.lower(): float(v) for k, v in
         all_metrics(paired["obs"].to_numpy(), paired["sim"].to_numpy()).items()}
    if not math.isfinite(m["nse"]):
        raise Fail(f"non-finite NSE on split {split}")

    # scored_obs / case_id are BUILT from the resolved gauge above + the routed station
    # read out of the staloc rout consumed.  No literal: if either resolution had named a
    # different site, load_obs()/run_rout() would already have exited nonzero.
    scored_obs = (f"{resolved['dataset']} station {resolved['station_code']} "
                  f"{resolved['station_name']} ({resolved['variable']}, {resolved['units']}) "
                  f"@ {resolved['obs_file']} :: routed station {routed['routed_station_id']} "
                  f"cell(col={routed['routed_cell_col']},row={routed['routed_cell_row']}) "
                  f"@ {resolved['gauge_lon']}E,{resolved['gauge_lat']}N :: split={split} "
                  f"{s0}..{s1} n={len(paired)}")

    out = {
        "nse": m["nse"], "kge": m["kge"], "pbias": m["pbias"],
        "r": m["r"], "rmse": m["rmse"],
        "__kdt__": {
            "applied_params": {k: applied[k] for k in (handed or p)},
            "case_id": resolved["case_id"],
            "scored_obs": scored_obs,
            "obs_resolved": resolved,
            "split": split, "score_period": [s0, s1], "sim_period": [f"{y0}-01-01", f"{y1}-12-31"],
            "n_paired_days": int(len(paired)), "n_cells": int(ncell),
            "run_health": {
                "n_cells": int(ncell), "n_cells_expected": n_expected,
                "flux_records": int(flux_records), "flux_records_expected": sim_days,
                "routed_days": int(routed["routed_days"]), "routed_days_expected": sim_days,
                "paired_days": int(len(paired)),
                "paired_days_expected": int(resolved["n_obs_days"]),
                "routed_station_id": routed["routed_station_id"],
                "obs_envelope_verified": True,
            },
            "wallclock_s": round(time.time() - t0, 1),
        },
    }
    # Atomic: a kill between open() and the last write must not leave a truncated JSON
    # object that the kit could parse as a (bad but finite) result.
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_out = out_path.with_suffix(out_path.suffix + f".partial.{os.getpid()}")
    tmp_out.write_text(json.dumps(out, indent=2))
    os.replace(tmp_out, out_path)
    print(f"[calib_run] case={resolved['case_id']} obs={resolved['station_code']}"
          f"/{resolved['station_name']}", flush=True)
    print(f"[calib_run] split={split} n={len(paired)} nse={m['nse']:.4f} kge={m['kge']:.4f} "
          f"pbias={m['pbias']:+.2f}% ({out['__kdt__']['wallclock_s']}s)", flush=True)

    if os.environ.get("KDT_VIC_KEEP_WORKDIR", "0") != "1":
        shutil.rmtree(wd, ignore_errors=True)          # ~200 MB of flux files per eval
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Fail as e:
        die(str(e))
    except Exception as e:                             # never leave a half-written metrics file
        die(f"{type(e).__name__}: {e}", code=2)
