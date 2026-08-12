#!/usr/bin/env python3
"""
Knowledge Infrastructure — Calibration Runner (programmatic, NOT an agent)
=========================================================================
Tool ID:      calib_run
Model:        SWAT+ (binding swatplus_rev59)
Contract:     <ki>/calibration.yaml   (injection.mode: runner)

    python calib_run.py --workdir <wd> --out <metrics.json>

Runs ONE calibration candidate for the pinned TARGET CASE and writes the
dag-gate-valid metrics as JSON. Called hundreds of times, so it does no
downloading, no delineation and no forcing generation: it rebuilds the deck from
a pristine snapshot of the ALREADY-VALIDATED Xixian TxtInOut, injects the
candidate parameters, runs the real binary through the KI's own s8 tool, and
scores the outlet series against the Xixian gauge with the KI's s9 tool.

TARGET CASE (pinned — see PIN below, and __kdt__.case_id in the output):
    case_id     SITE:xixian
    gauge       xixian_50225601 息县, upper Huai River (china_gaugeflux stcd 50225601)
    obs         /mnt/datasets/china_water_level/淮河txt/息县.txt
    quantity    discharge  ->  dag var "streamflow at channel outlet (flo_out)"
    metric      nse (dag determining_metric for point_time_series)
    provenance  SWAT+_20260719T235310Z_630596   (validated NSE 0.6417)

SKILL.md's worked example is BENGBU. This runner is NOT Bengbu. Nothing here
reads a gauge, obs path, lat/lon or basin from the environment; the case is a
module constant, every identity fact in __kdt__ is derived from the artifacts
this run actually read, and the deck is verified to be the Xixian delineation
before the binary is allowed to run.

INJECTION (runner mode — the kit does NOT write the inputs):
  The candidate vector arrives as JSON at $KDT_CALIB_PARAMS. The 12 parameters
  reach the model through FOUR different mechanisms, because SWAT+ silently
  IGNORES a calibration.cal row whose name is absent from the project's own
  cal_parms.cal — and, as commissioning showed, sometimes even one that IS
  present (awc, surlag; see their notes below):
    (a) calibration.cal rows  ->  KI tool s6/generate_calibration_file.py
        (owns name validation, the alpha_bf->alpha rev59 aliasing, and the
        count-line format SWAT+ requires): cn2, k, esco, alpha_bf, revap_co
    (b) aquifer.aqu columns   ->  same KI tool (STRUCTURAL_AQU path):
        rchg_dp, spec_yld
    (c) free-format column tables -> direct edit, the same mechanism the KI tool
        itself uses for aquifer.aqu: hydrology.hyd (perco, cn3_swf),
        hydrology.cha (chn_mann), parameters.bsn (surlag)
    (d) soils.sol layer rows scaled uniformly: awc
  After the tool runs, every injected number is REWRITTEN at full precision
  (the tool formats calibration.cal at %.3f and aquifer.aqu at %.5f, which is
  coarser than the kit's applied-vs-requested tolerance of rel_tol 1e-6), then
  read BACK out of the effective artifact. Any parameter that cannot be written
  and read back exactly aborts the eval with NO metrics file.

Exit codes: 0=success (metrics written), 1=input/contract error, 2=run failure,
            3=scoring failure, 4=injection read-back mismatch.
Any nonzero exit leaves no metrics file, which the kit scores as +inf.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

# ===========================================================================
# PIN — the target case. Module constants, never environment-derived.
# ===========================================================================
CASE_ID = "SITE:xixian"
GAUGE_ID = "xixian_50225601"
GAUGE_NAME = "息县"
OBS_STCD = "50225601"
OBS_FILE = Path("/mnt/datasets/china_water_level/淮河txt/息县.txt")
OBS_SOURCE = "china_gaugeflux"
TARGET_VAR = "streamflow at channel outlet (flo_out)"

KI = Path(__file__).resolve().parent.parent
TOOLS = KI / "tools"
BIN = Path("/mnt/disk1/Hydrocraft_server/models/SWAT+/bin/swatplus_rev59")

# The validated Xixian deck (33-station CMFD forcing, 78 HRUs, 33 channels).
CASE_ROOT = Path("/mnt/disk1/Hydrocraft_server/outputs/swatplus_xixian_multista")
BASE_DECK = CASE_ROOT / "TxtInOut"
PRISTINE_ROOT = CASE_ROOT / "_calib_pristine"
PRISTINE_DECK = PRISTINE_ROOT / "TxtInOut"

# Deck-identity guard: the Xixian delineation's channel.con bounding box. The
# validated deck's 33 channels span lat 31.63319..32.61514, lon 113.37643..
# 114.66357 (the ~10190 km2 upper-Huai catchment above 息县); the box below adds
# a small margin. A deck outside it is NOT Xixian and must never be scored
# against the Xixian gauge.
BASIN_BBOX = (31.3, 32.8, 113.2, 114.9)          # lat_min, lat_max, lon_min, lon_max
EXPECT_N_CHANNELS = 33

# Scoring windows — identical to the validated run (time.sim 1979-1990,
# print.prt nyskip 2 => printed record starts 1981).
SPLITS = {
    "calibration": ("1981-01-01", "1985-12-31"),
    "holdout":     ("1986-01-01", "1990-12-31"),
    "full":        ("1981-01-01", "1990-12-31"),
}
MIN_PAIRED_DAYS = 300

# ===========================================================================
# Parameter contract — MUST stay in sync with calibration.yaml.
# ===========================================================================
# (a) names the KI s6 tool writes into calibration.cal: name -> change_type
CAL_CAL_PARAMS = {
    "cn2":      "pctchg",
    "k":        "pctchg",
    "esco":     "absval",
    "alpha_bf": "absval",     # tool aliases -> row name "alpha"  (rev59 cal_parms)
    "revap_co": "absval",
}
CAL_CAL_ROW_ALIAS = {"alpha_bf": "alpha"}

# (b) names the KI s6 tool writes into aquifer.aqu columns (STRUCTURAL_AQU)
AQU_PARAMS = {"rchg_dp": "rchg_dp", "spec_yld": "spec_yld"}   # param -> aquifer.aqu header name

# (c) names written directly into free-format column tables
HYD_HYD_PARAMS = {"perco": "perco", "cn3_swf": "cn3_swf"}     # param -> hydrology.hyd header name
HYD_CHA_PARAMS = {"chn_mann": "mann"}                         # param -> hydrology.cha header name
BSN_PARAMS = {"surlag": "surq_lag"}                           # param -> parameters.bsn header name

# (d) percent change applied to every soil layer's awc in soils.sol.
#     COMMISSIONING FINDING: a calibration.cal `awc` row is written and accepted
#     by rev59 but has NO effect — bit-identical NSE/PBIAS at pctchg -90 and +49,
#     i.e. across the whole cal_parms box. (`k`, also obj_typ sol, DOES take
#     effect through calibration.cal, so this is specific to awc: SWAT+ derives
#     the per-layer storage terms from awc during soil initialisation and the
#     calibration update does not recompute them.) Editing soils.sol directly is
#     the effective artifact — awc x1.5 moves basin mean Q +15.6 m3/s, x0.5
#     moves it -5.8 m3/s. Same dt_013 failure class the KI documents for
#     perco / cn3_swf / rchg_dp.
SOL_AWC_PARAM = "awc"
SOL_AWC_LAYER_FIELDS = 14        # a soils.sol layer row carries the last 14 header fields
SOL_AWC_PHYS_RANGE = (0.01, 1.0) # cal_parms.cal awc obj_typ sol absmin/absmax (mm_H2O/mm)

DEFAULTS = {
    "cn2": -50.0, "cn3_swf": 0.0, "surlag": 4.0, "esco": 0.15,
    "awc": 0.0, "k": 0.0, "perco": 0.75, "rchg_dp": 0.78, "spec_yld": 0.05,
    "alpha_bf": 0.05, "revap_co": 0.02, "chn_mann": 0.05,
}
ALL_PARAMS = tuple(DEFAULTS)

# Read-back agreement. The kit compares applied vs requested at rel_tol 1e-6, so
# we write 12 significant digits and require agreement two orders tighter.
FMT = "{:.12g}"
READBACK_RTOL = 1e-9
READBACK_ATOL = 1e-12

# Files SWAT+ produces (never copied into the pristine snapshot, always cleared
# before a run so a previous candidate's output can never be scored).
OUTPUT_FILES = (
    "channel_day.txt", "channel_sd_day.txt", "channel_mon.txt", "channel_sd_mon.txt",
    "channel_yr.txt", "channel_sd_yr.txt", "basin_wb_day.txt", "basin_wb_mon.txt",
    "basin_wb_yr.txt", "basin_wb_aa.txt", "crop_yld_aa.out", "crop_yld_yr.out",
    "diagnostics.out", "files_out.out", "simulation.out", "area_calc.out",
    "erosion.txt", "swatplus_run.log", "checker.out", "hydrology.hyd.bak_overpredict",
)


def fail(code: int, msg: str) -> "NoReturn":         # noqa: F821
    """Abort with NO metrics file. The kit scores a missing file as +inf."""
    print(f"calib_run FAIL[{code}]: {msg}", file=sys.stderr, flush=True)
    sys.exit(code)


# ===========================================================================
# free-format column tables (aquifer.aqu / hydrology.hyd / hydrology.cha)
# ===========================================================================
# SWAT+ reads these with list-directed Fortran reads, so token width is free —
# which is exactly why the KI's own s6 tool can rewrite aquifer.aqu rows joined
# by plain spaces. Layout: line 0 = title, line 1 = header, line 2+ = data.

def _table_col_index(path: Path, header_name: str) -> int:
    try:
        header = path.read_text().splitlines()[1].split()
    except (OSError, IndexError) as e:
        fail(1, f"cannot read header of {path}: {e}")
    if header_name not in header:
        fail(1, f"column {header_name!r} not present in {path.name} header {header}")
    return header.index(header_name)


def _table_set(path: Path, header_name: str, value: float) -> None:
    """Set one column to `value` in EVERY data row, at full precision."""
    col = _table_col_index(path, header_name)
    lines = path.read_text().splitlines()
    out, touched = lines[:2], 0
    for ln in lines[2:]:
        toks = ln.split()
        if len(toks) <= col:
            out.append(ln)
            continue
        toks[col] = FMT.format(float(value))
        out.append("   ".join(toks))
        touched += 1
    if touched == 0:
        fail(1, f"{path.name}: no data row wide enough to hold column {header_name!r}")
    path.write_text("\n".join(out) + "\n")


def _table_get(path: Path, header_name: str) -> float:
    """Read the column back; every data row must agree (they are written tied)."""
    col = _table_col_index(path, header_name)
    vals = []
    for ln in path.read_text().splitlines()[2:]:
        toks = ln.split()
        if len(toks) <= col:
            continue
        try:
            vals.append(float(toks[col]))
        except ValueError:
            fail(4, f"{path.name}: column {header_name!r} holds a non-numeric token {toks[col]!r}")
    if not vals:
        fail(4, f"{path.name}: column {header_name!r} has no readable data row")
    if max(vals) - min(vals) > 0.0:
        fail(4, f"{path.name}: column {header_name!r} is not uniform across rows "
                f"({min(vals)}..{max(vals)}) — a tied global parameter was written per-row")
    return vals[0]


def _sol_awc_index(path: Path) -> int:
    """Column of `awc` within a soils.sol LAYER row.

    soils.sol interleaves soil-header rows (7 fields) with per-layer rows that
    carry the last SOL_AWC_LAYER_FIELDS names of the file header, so the layer
    index is the header index minus that offset.
    """
    header = path.read_text().splitlines()[1].split()
    if "awc" not in header:
        fail(1, f"soils.sol header has no awc column: {header}")
    idx = header.index("awc") - (len(header) - SOL_AWC_LAYER_FIELDS)
    if not 0 <= idx < SOL_AWC_LAYER_FIELDS:
        fail(1, f"soils.sol layout unrecognised (awc resolves to layer index {idx})")
    return idx


def _sol_awc_values(path: Path) -> list:
    idx = _sol_awc_index(path)
    vals = []
    for ln in path.read_text().splitlines()[2:]:
        toks = ln.split()
        if len(toks) != SOL_AWC_LAYER_FIELDS:      # soil-header row, not a layer
            continue
        try:
            vals.append(float(toks[idx]))
        except ValueError:
            fail(4, f"soils.sol layer row holds a non-numeric awc {toks[idx]!r}")
    if not vals:
        fail(1, "soils.sol has no parseable layer rows")
    return vals


def _sol_awc_apply(deck: Path, pct: float) -> None:
    """Scale every layer's awc by (1 + pct/100), preserving spatial variability."""
    path, idx = deck / "soils.sol", _sol_awc_index(deck / "soils.sol")
    factor = 1.0 + float(pct) / 100.0
    lines = path.read_text().splitlines()
    out = lines[:2]
    for ln in lines[2:]:
        toks = ln.split()
        if len(toks) != SOL_AWC_LAYER_FIELDS:
            out.append(ln)
            continue
        new = float(toks[idx]) * factor
        lo, hi = SOL_AWC_PHYS_RANGE
        if not (lo <= new <= hi):
            fail(4, f"awc pctchg {pct} drives a layer to {new:g} mm/mm, outside the "
                    f"model's documented valid band {SOL_AWC_PHYS_RANGE} — the range "
                    f"is wrong, not the value")
        toks[idx] = FMT.format(new)
        out.append("      " + "   ".join(toks))
    path.write_text("\n".join(out) + "\n")


def _sol_awc_readback(deck: Path) -> float:
    """Recover the achieved percent change by comparing against the pristine deck.

    Every layer is scaled by the same factor, so the ratio of the totals is that
    factor exactly (to ~1e-12 with 12-significant-digit writes).
    """
    now = _sol_awc_values(deck / "soils.sol")
    ref = _sol_awc_values(PRISTINE_DECK / "soils.sol")
    if len(now) != len(ref):
        fail(4, f"soils.sol layer count changed ({len(ref)} -> {len(now)})")
    tot_ref = sum(ref)
    if tot_ref <= 0.0:
        fail(1, "pristine soils.sol has non-positive total awc")
    return (sum(now) / tot_ref - 1.0) * 100.0


# ===========================================================================
# deck preparation
# ===========================================================================
def _ignore_outputs(_dirname, names):
    drop = set()
    for n in names:
        if n in OUTPUT_FILES or n.endswith((".out", ".log")) or ".bak" in n:
            drop.add(n)
    return drop


def ensure_pristine() -> None:
    """One-time: snapshot the validated deck minus every output file.

    Built into a temp dir and moved into place atomically, so concurrent evals
    can race safely and a half-built snapshot is never visible.
    """
    marker = PRISTINE_ROOT / ".ready"
    if marker.exists():
        return
    if not BASE_DECK.is_dir():
        fail(1, f"validated Xixian deck missing: {BASE_DECK}")
    PRISTINE_ROOT.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="_pristine_", dir=str(PRISTINE_ROOT)))
    try:
        shutil.copytree(BASE_DECK, tmp / "TxtInOut", ignore=_ignore_outputs)
        try:
            os.rename(tmp / "TxtInOut", PRISTINE_DECK)
        except OSError:
            if not PRISTINE_DECK.is_dir():
                raise                       # a real failure, not a lost race
        marker.write_text(f"from {BASE_DECK}\n")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    # Wait out a concurrent builder that won the rename but hasn't marked yet.
    for _ in range(120):
        if (PRISTINE_DECK / "file.cio").is_file():
            return
        time.sleep(0.5)
    fail(1, f"pristine snapshot never became usable: {PRISTINE_DECK}")


def build_eval_deck(workdir: Path) -> Path:
    """Rebuild a clean deck for THIS candidate.

    One directory per process (evals are sequential within a worker), rebuilt
    from scratch every call: aquifer.aqu / hydrology.* edits are in-place, so a
    reused deck would accumulate the previous candidate's values.
    """
    tag = os.environ.get("KDT_CALIB_EVAL_ID") or str(os.getpid())
    deck = workdir / "calib_evals" / f"eval_{tag}" / "TxtInOut"
    if deck.parent.exists():
        shutil.rmtree(deck.parent, ignore_errors=True)
    deck.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(PRISTINE_DECK, deck, ignore=_ignore_outputs)
    for name in OUTPUT_FILES:                    # belt and braces
        (deck / name).unlink(missing_ok=True)
    return deck


def verify_deck_is_target_case(deck: Path) -> dict:
    """Refuse to run unless this deck really is the Xixian delineation.

    Guards the other half of "did we score the right site": a correct obs file
    paired with somebody else's basin would still be the wrong answer.
    """
    con = deck / "channel.con"
    if not con.is_file():
        fail(1, f"deck has no channel.con: {deck}")
    lats, lons = [], []
    for ln in con.read_text().splitlines()[2:]:
        p = ln.split()
        if len(p) < 6:
            continue
        try:
            lats.append(float(p[4])); lons.append(float(p[5]))
        except ValueError:
            continue
    if not lats:
        fail(1, "channel.con carries no parseable channel coordinates")
    lo_lat, hi_lat, lo_lon, hi_lon = BASIN_BBOX
    if not (lo_lat <= min(lats) and max(lats) <= hi_lat
            and lo_lon <= min(lons) and max(lons) <= hi_lon):
        fail(1, f"deck bbox lat {min(lats):.4f}..{max(lats):.4f} lon "
                f"{min(lons):.4f}..{max(lons):.4f} is OUTSIDE the {CASE_ID} basin box "
                f"{BASIN_BBOX} — this is not the Xixian delineation, refusing to score it")
    if len(lats) != EXPECT_N_CHANNELS:
        fail(1, f"deck has {len(lats)} channels, expected {EXPECT_N_CHANNELS} for {CASE_ID}")
    return {"n_channels": len(lats),
            "bbox": [min(lats), max(lats), min(lons), max(lons)]}


# ===========================================================================
# parameter injection
# ===========================================================================
def load_requested() -> tuple[dict, list]:
    """Read the candidate vector. Returns (full vector, names actually handed).

    Unhanded parameters fall back to their calibration.yaml default so the deck
    is always in a fully-specified state; the handed names are tracked because
    the kit requires EVERY handed key to be echoed back.
    """
    handed = {}
    pf = os.environ.get("KDT_CALIB_PARAMS")
    if pf:
        try:
            raw = json.loads(Path(pf).read_text())
        except (OSError, ValueError) as e:
            fail(1, f"cannot read KDT_CALIB_PARAMS at {pf}: {e}")
        if not isinstance(raw, dict):
            fail(1, f"KDT_CALIB_PARAMS is {type(raw).__name__}, expected an object")
        unknown = sorted(set(raw) - set(ALL_PARAMS))
        if unknown:
            fail(1, f"KDT_CALIB_PARAMS carries parameter(s) this contract does not "
                    f"declare: {unknown}")
        for k, v in raw.items():
            try:
                fv = float(v)
            except (TypeError, ValueError):
                fail(1, f"parameter {k} has non-numeric value {v!r}")
            if not math.isfinite(fv):
                fail(1, f"parameter {k} is non-finite ({v!r})")
            handed[k] = fv
    vec = dict(DEFAULTS)
    vec.update(handed)
    return vec, sorted(handed)


def run_ki_tool(script: Path, args: list, cwd: Path | None = None) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(script)] + [str(a) for a in args]
    return subprocess.run(cmd, cwd=str(cwd) if cwd else None,
                          capture_output=True, text=True)


def inject(deck: Path, vec: dict) -> None:
    """Write the candidate into the artifacts the binary actually consumes."""

    # ---- (a)+(b): calibration.cal rows and aquifer.aqu columns, via the KI tool.
    tool = TOOLS / "s6" / "generate_calibration_file.py"
    if not tool.is_file():
        fail(1, f"KI tool missing: {tool}")
    payload = {name: {"change_type": CAL_CAL_PARAMS[name], "value": vec[name]}
               for name in CAL_CAL_PARAMS}
    payload.update({name: {"change_type": "absval", "value": vec[name]}
                    for name in AQU_PARAMS})
    p = run_ki_tool(tool, [json.dumps(payload), str(deck)])
    if p.returncode != 0:
        fail(2, f"s6/generate_calibration_file.py rc={p.returncode}: "
                f"{(p.stderr or '')[-600:]}")

    # The tool formats calibration.cal at %.3f and aquifer.aqu at %.5f — coarser
    # than the kit's rel_tol 1e-6 applied-vs-requested check. Rewrite the exact
    # values at full precision, keeping the tool's structure/validation.
    _rewrite_cal_cal_precision(deck / "calibration.cal", vec)
    for name, col in AQU_PARAMS.items():
        _table_set(deck / "aquifer.aqu", col, vec[name])

    # ---- (c): free-format column tables, unreachable from calibration.cal.
    for name, col in HYD_HYD_PARAMS.items():
        _table_set(deck / "hydrology.hyd", col, vec[name])
    for name, col in HYD_CHA_PARAMS.items():
        _table_set(deck / "hydrology.cha", col, vec[name])
    for name, col in BSN_PARAMS.items():
        _table_set(deck / "parameters.bsn", col, vec[name])

    # ---- (d): per-layer soil awc in soils.sol.
    _sol_awc_apply(deck, vec[SOL_AWC_PARAM])


def _rewrite_cal_cal_precision(path: Path, vec: dict) -> None:
    """Replace each calibration.cal VAL field with the full-precision request."""
    if not path.is_file():
        fail(2, "s6 tool did not produce calibration.cal")
    want = {CAL_CAL_ROW_ALIAS.get(n, n): vec[n] for n in CAL_CAL_PARAMS}
    lines = path.read_text().splitlines()
    if len(lines) < 3:
        fail(2, f"calibration.cal is malformed ({len(lines)} lines)")
    out, seen = lines[:3], set()
    for ln in lines[3:]:
        toks = ln.split()
        if len(toks) < 3 or toks[0] not in want:
            out.append(ln)
            continue
        toks[2] = FMT.format(float(want[toks[0]]))
        seen.add(toks[0])
        out.append("   ".join(toks))
    missing = sorted(set(want) - seen)
    if missing:
        # The tool DROPS any name absent from the deck's cal_parms.cal — SWAT+
        # would have silently ignored the row. Never optimize a dead parameter.
        fail(4, f"calibration.cal has no row for {missing} — the KI tool dropped "
                f"them as absent from cal_parms.cal, so they would be silently "
                f"ignored by SWAT+")
    path.write_text("\n".join(out) + "\n")


def read_back(deck: Path) -> dict:
    """Read every parameter out of the artifact the binary consumes."""
    applied = {}

    cal = (deck / "calibration.cal").read_text().splitlines()
    rows = {}
    for ln in cal[3:]:
        toks = ln.split()
        if len(toks) >= 3:
            try:
                rows[toks[0]] = float(toks[2])
            except ValueError:
                fail(4, f"calibration.cal row {toks[0]!r} has non-numeric VAL {toks[2]!r}")
    for name in CAL_CAL_PARAMS:
        row = CAL_CAL_ROW_ALIAS.get(name, name)
        if row not in rows:
            fail(4, f"calibration.cal lost the row for {name} (as {row!r})")
        applied[name] = rows[row]

    for name, col in AQU_PARAMS.items():
        applied[name] = _table_get(deck / "aquifer.aqu", col)
    for name, col in HYD_HYD_PARAMS.items():
        applied[name] = _table_get(deck / "hydrology.hyd", col)
    for name, col in HYD_CHA_PARAMS.items():
        applied[name] = _table_get(deck / "hydrology.cha", col)
    for name, col in BSN_PARAMS.items():
        applied[name] = _table_get(deck / "parameters.bsn", col)
    applied[SOL_AWC_PARAM] = _sol_awc_readback(deck)
    return applied


def verify_injection(vec: dict, applied: dict) -> None:
    """Fail closed unless every parameter reads back exactly as requested."""
    bad = []
    for name in ALL_PARAMS:
        if name not in applied:
            bad.append(f"{name}: not readable from any artifact")
            continue
        want, got = float(vec[name]), float(applied[name])
        if not math.isfinite(got):
            bad.append(f"{name}: applied non-finite {got!r}")
        elif want != 0.0 and got == 0.0:
            bad.append(f"{name}: requested {want} but the model input holds 0 (clamped)")
        elif not math.isclose(got, want, rel_tol=READBACK_RTOL, abs_tol=READBACK_ATOL):
            bad.append(f"{name}: requested {want!r}, input holds {got!r} (clamped or lossy)")
    if bad:
        fail(4, "parameter read-back mismatch — the model would not have run the "
                "requested vector: " + "; ".join(bad))


# ===========================================================================
# run + score
# ===========================================================================
def execute(deck: Path) -> Path:
    """Run the binary and extract the outlet series, both via KI tools."""
    for name in OUTPUT_FILES:
        (deck / name).unlink(missing_ok=True)
    if not BIN.is_file():
        fail(1, f"SWAT+ binary missing: {BIN}")

    p = run_ki_tool(TOOLS / "s8" / "run_swatplus.py", [str(BIN), str(deck)])
    if p.returncode != 0:
        fail(2, f"s8/run_swatplus.py rc={p.returncode}: {(p.stderr or '')[-800:]}")
    if not (deck / "channel_day.txt").is_file():
        fail(2, "SWAT+ produced no channel_day.txt")

    sim_csv = deck.parent / "sim.csv"
    sim_csv.unlink(missing_ok=True)
    p = run_ki_tool(TOOLS / "s9" / "extract_discharge.py",
                    ["--txtinout_dir", str(deck), "--output_csv", str(sim_csv)])
    if p.returncode != 0 or not sim_csv.is_file():
        fail(2, f"s9/extract_discharge.py rc={p.returncode}: {(p.stderr or '')[-800:]}")
    return sim_csv


def load_sim(sim_csv: Path):
    d, q = [], []
    for ln in sim_csv.read_text().splitlines()[1:]:
        parts = ln.strip().split(",")
        if len(parts) < 2:
            continue
        try:
            d.append(np.datetime64(parts[0])); q.append(float(parts[1]))
        except ValueError:
            continue
    if not d:
        fail(3, f"simulated series is empty: {sim_csv}")
    return np.array(d), np.array(q, dtype=float)


def load_obs():
    """息县.txt — tab separated, cols stcd/dates/z/Q/name, -99 = missing.

    Returns (dates, discharge, resolved_identity). The identity is built from
    what was ACTUALLY parsed, so __kdt__.scored_obs cannot drift from the series
    that was scored. Rows carrying any other station code — or a station name
    that is not the pinned gauge — abort the eval.

    Encoding: the file is UTF-8 (verified: the name column holds e6 81 af e5 8e
    bf = 息县). The validated runner decoded it as GBK with errors="replace",
    which parsed the ASCII numeric columns fine but mangled the name; decoding
    UTF-8 first makes the station name usable as an identity check, with a GBK
    fallback for any sibling file that really is GBK.
    """
    if not OBS_FILE.is_file():
        fail(1, f"target-case obs file missing: {OBS_FILE}")
    blob = OBS_FILE.read_bytes()
    try:
        raw = blob.decode("utf-8")
    except UnicodeDecodeError:
        raw = blob.decode("gbk", errors="replace")
    dates, q, codes, names = [], [], set(), set()
    for ln in raw.splitlines()[1:]:
        parts = ln.split("\t")
        if len(parts) < 4:
            continue
        try:
            y, m, dd = (int(x) for x in parts[1].split("-"))
            val = float(parts[3])
        except (ValueError, IndexError):
            continue
        codes.add(parts[0].strip())
        if len(parts) >= 5:
            names.add(parts[4].strip())
        if val <= -99:
            continue
        dates.append(np.datetime64(f"{y:04d}-{m:02d}-{dd:02d}"))
        q.append(val)
    if not dates:
        fail(3, f"no usable observations parsed from {OBS_FILE}")
    if codes != {OBS_STCD}:
        fail(1, f"{OBS_FILE.name} carries station code(s) {sorted(codes)}; the "
                f"{CASE_ID} target gauge is stcd {OBS_STCD} — refusing to score a "
                f"series that is not the target gauge")
    if names and names != {GAUGE_NAME}:
        fail(1, f"{OBS_FILE.name} names station(s) {sorted(names)}; the {CASE_ID} "
                f"target gauge is {GAUGE_NAME} — refusing to score a series that "
                f"is not the target gauge")
    identity = {
        "stcd": sorted(codes)[0],
        "station_names": sorted(names),
        "file": str(OBS_FILE),
        "source": OBS_SOURCE,
    }
    return np.array(dates), np.array(q, dtype=float), identity


def pair_and_window(obs_d, obs_q, sim_d, sim_q, split: str):
    lo, hi = (np.datetime64(x) for x in SPLITS[split])
    common = np.intersect1d(obs_d, sim_d)
    common = common[(common >= lo) & (common <= hi)]
    if common.size == 0:
        fail(3, f"no overlapping days between obs and sim in the {split} window")
    oi = {d: i for i, d in enumerate(obs_d)}
    si = {d: i for i, d in enumerate(sim_d)}
    o = np.array([obs_q[oi[d]] for d in common])
    s = np.array([sim_q[si[d]] for d in common])
    good = np.isfinite(o) & np.isfinite(s)
    return common[good], o[good], s[good]


def score(o, s) -> dict:
    """dag-gate-valid metrics via the shared implementation."""
    try:
        from ki_tools_common.metrics import all_metrics
    except ImportError as e:
        fail(3, f"ki_tools_common.metrics unavailable: {e}")
    m = all_metrics(o, s)
    out = {}
    for k, v in m.items():
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if math.isfinite(fv):
            out[k.lower()] = fv
    for required in ("nse", "pbias"):
        if required not in out:
            fail(3, f"metric {required!r} is missing or non-finite — refusing to "
                    f"report a partial score")
    return out


# ===========================================================================
def main() -> None:
    ap = argparse.ArgumentParser(description=f"SWAT+ calibration eval — {CASE_ID}")
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    workdir = Path(args.workdir).resolve()
    out_path = Path(args.out).resolve()
    workdir.mkdir(parents=True, exist_ok=True)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.unlink(missing_ok=True)          # never leave a stale score readable

    split = (os.environ.get("KDT_CALIB_SPLIT") or "").strip().lower()
    if split not in SPLITS:
        split = "full"                        # unset/garbage -> score the whole record

    vec, handed = load_requested()

    ensure_pristine()
    deck = build_eval_deck(workdir)
    deck_identity = verify_deck_is_target_case(deck)

    inject(deck, vec)
    applied = read_back(deck)
    verify_injection(vec, applied)

    sim_csv = execute(deck)
    sim_d, sim_q = load_sim(sim_csv)
    obs_d, obs_q, obs_identity = load_obs()
    dates, o, s = pair_and_window(obs_d, obs_q, sim_d, sim_q, split)
    if o.size < MIN_PAIRED_DAYS:
        fail(3, f"only {o.size} paired days in the {split} window (min {MIN_PAIRED_DAYS})")

    metrics = score(o, s)

    # scored_obs is assembled from the SAME variables the scoring used — the obs
    # identity resolved while reading the file, and the window actually paired —
    # so the declaration cannot diverge from what was scored.
    scored_obs = (f"{GAUGE_ID} {obs_identity['station_names'][0] if obs_identity['station_names'] else GAUGE_NAME} "
                  f":: {obs_identity['source']} stcd {obs_identity['stcd']} "
                  f":: {obs_identity['file']} "
                  f":: split={split} {np.datetime_as_string(dates.min(), unit='D')}"
                  f"..{np.datetime_as_string(dates.max(), unit='D')} n={o.size}")

    payload = dict(metrics)
    payload["n"] = int(o.size)
    payload["__kdt__"] = {
        "applied_params": {k: float(applied[k]) for k in ALL_PARAMS},
        "requested_params": {k: float(vec[k]) for k in ALL_PARAMS},
        "handed_params": handed,
        "case_id": CASE_ID,
        "scored_obs": scored_obs,
        "target_var": TARGET_VAR,
        "determining_metric": "nse",
        "split": split,
        "period": [np.datetime_as_string(dates.min(), unit="D"),
                   np.datetime_as_string(dates.max(), unit="D")],
        "obs_identity": obs_identity,
        "deck": {"path": str(deck), "pristine_from": str(BASE_DECK), **deck_identity},
        "binary": str(BIN),
        "ki_tools_used": ["s6/generate_calibration_file.py", "s8/run_swatplus.py",
                          "s9/extract_discharge.py"],
    }

    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    os.replace(tmp, out_path)                 # atomic: a partial file is never read
    print(json.dumps({k: payload[k] for k in payload if k != "__kdt__"}), flush=True)


if __name__ == "__main__":
    main()
