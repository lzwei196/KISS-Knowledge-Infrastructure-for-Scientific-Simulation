#!/usr/bin/env python3
"""calib_run.py — programmatic run+score of ONE DSSAT candidate for the calibration kit.

TARGET CASE (pinned, never overridable from the environment)
------------------------------------------------------------
  case_id        : OBS:spam2020
  obs / gauge id : spam2020   (SPAM 2020 V2r0 maize yield, IFPRI)
  target quantity: yield  -> dag output "HWAM (harvested grain yield at maturity, dry)"
  obs_shape      : regional_aggregate_time_series  (aggregate_trend_comparison)
  determining metric: pbias   (magnitude_accuracy — the only gate-valid family this
                      single-year regional aggregate can score; trend_match is N/A)
  provenance     : DSSAT_20260630T053443Z, prior validated pbias = +8.34 %

This reproduces EXACTLY the validated coupling recorded in
``KISSPATH_KI_ROOT/DSSAT/real_case_result.json``:

  * 42 grid points = 6 lat x 7 lon on lat [35.0, 37.5] x lon [116.0, 119.0], step
    0.5 deg (endpoints inclusive) over the Shandong / North-China-Plain
    summer-maize belt;
  * DSSAT-CSM 4.8.5 (dscsm048) CERES-Maize, cultivar CN0001 "Zhengdan 958",
    soil IB00000004 (generic deep silty loam), planting 2020-06-15, rainfed,
    split N, per-cell CMFD V2.0 3-hourly 0.1deg weather;
  * obs = ki_tools_common.crop_obs.get_observed_yield(lat, lon, 'maize') at the SAME
    42 points  -> unweighted regional mean 6461.9047619047615 kg/ha (pinned below);
  * sim = unweighted regional mean of the 42 per-cell Summary.OUT HWAM values;
  * pbias = 100 * (sim_region - obs_region) / obs_region.
  At the DEFAULT split and the DEFAULT parameter vector this reproduces sim
  7001.1428571 kg/ha and pbias +8.3444 % — i.e. the validated metric, to the digit.

SPLIT SEMANTICS (KDT_CALIB_SPLIT)  — the DEFAULT is the WHOLE target case
-------------------------------------------------------------------------
  unset / "" / "full"  -> ALL 42 cells: the target case's own regional aggregate,
                          exactly as validated.  This is the default, so any caller
                          that does not ask for a split scores the DECLARED CASE.
  "calibration"        -> western block, lon <  118.5 degE  (30 of 42 cells)
  "holdout"            -> eastern block, lon >= 118.5 degE  (12 of 42 cells)
The two blocks are the MANDATORY leave-region-out holdout declared in
calibration.yaml (strategy.holdout, protocol leave_region_out, fraction 0.2857).
They are the only splits that ever score a subset, they are requested EXPLICITLY by
the kit, and every eval self-declares ``__kdt__.split`` + ``__kdt__.n_cells_scored``
alongside the derived ``case_id`` / ``scored_obs``.

INJECTION MODE: runner (calibration.yaml -> injection.mode: runner)
-------------------------------------------------------------------
The KI REGENERATES every DSSAT input from scratch on each run
(``dssat_workdir_setup.create_workdir`` rewrites FileX / DSSATPRO / DSSBatch /
SOIL.SOL and re-merges the China cultivar library into MZCER048.CUL), so anything
the kit wrote beforehand would be overwritten.  This driver therefore

  1. reads the candidate vector from the JSON at ``$KDT_CALIB_PARAMS``;
  2. calls the KI's OWN tool ``create_workdir`` for every cell (never reimplements
     DSSAT or its deck writers), passing the management levers through its documented
     ``**management_kwargs`` API, and then INJECTS the remaining levers into the
     regenerated decks the model's own fixed-width way:
        * MZCER048.CUL  — CERES-Maize cultivar record CN0001, FORTRAN format
          ``(A6,1X,A16,7X,A6,6F6.0)`` (dssat-csm-os InputModule/IPVAR.for:240);
        * SOIL.SOL      — profile IB00000004, header-delimited column windows
          (IPSOIL_Inp.for + Utilities/READS.for:PARSE_HEADERS);
        * FileX (*.MZX) — *PLANTING DETAILS / *INITIAL CONDITIONS / *FERTILIZERS,
          same header-window convention (IPEXP);
  3. READS EVERY VALUE BACK out of the effective artifacts DSSAT consumes (the
     workdir root copies that DSSATPRO.v48 points at, AND the Genotype/ + Soil/
     duplicates) and aborts with NO metrics + a non-zero exit if any value does not
     read back bit-identical to the request;
  4. emits ``__kdt__.applied_params`` (every key it was handed, incl. staged-frozen
     ones), ``__kdt__.case_id`` and ``__kdt__.scored_obs`` — both DERIVED from the
     obs record actually loaded and scored, not from a hardcoded label.

SHARED-SPEC ENFORCEMENT (interface_contracts.yaml -> shared_specs/dssat/base)
-----------------------------------------------------------------------------
Every deck this driver writes or hands to DSSAT is validated against the binding
shared spec ``models/shared_specs/dssat/base/format_spec.yaml`` BEFORE the write
(``tool_conventions.batch_file_writers.must_validate_widths_pre_write: true``):

  * ``field_widths.FILEX.record_length`` (92) — the *TREATMENTS record must fit in
    92 columns, and the DSSBatch.v48 ``@FILEX`` path field must be EXACTLY 92 wide
    with TRTNO starting at column 93.  This is the Xinjiang A96 failure the rule
    exists for (a 96-wide path field shifted TRTNO by 4 chars).
  * ``field_widths.FILEX.field_layout`` — the *TREATMENTS field windows.  They are
    reconciled against the windows DSSAT's own ``PARSE_HEADERS`` derives from the
    ``@N R O C TNAME... CU FL ... SM`` header line: the spec's declared start/end
    columns are 1 greater than the layout every shipped DSSAT deck uses (DSSAT reads
    the record as ``(I2,1X,3(I1,1X),A25,14(1X,I2))``: N at col 2, R at 4, O at 6,
    C at 8, TNAME 10-34, CU 36-37, ...).  We therefore require each spec window to
    agree with the header-derived window to within ONE column and to declare the same
    field NAMES in the same ORDER — which still catches the 4-column shift the rule
    was written for, while not rejecting decks DSSAT itself accepts.
  * ``forbidden_combinations.FILEX.harvs_m_with_harvest_details`` — HARVS=M forbids a
    *HARVEST DETAILS section.
  * ``path_constraints.FILEX`` (max_chars 95, must_be_relative_to_workdir) — the
    FILEX path recorded in DSSBatch.v48 is REWRITTEN to the workdir-relative
    basename (DSSAT runs with cwd=workdir), then re-validated and read back; it must
    be relative, resolve to the FileX we injected, and fit both the 95-char A95
    FILEX field and the 92-char batch field.
If the shared spec cannot be read, this driver FAILS CLOSED — it never silently
degrades to unvalidated writes.

EXACTNESS OF THE READ-BACK (why the parameters are integer-scaled)
------------------------------------------------------------------
Every DSSAT deck field is a fixed-width FORTRAN slot (6 chars in the .CUL, 5 chars in
the header-delimited .SOL / FileX columns), so a continuous float can NEVER round-trip:
the deck quantises it and ``applied != requested`` at the kit's rel_tol=1e-6, which
fails EVERY eval closed.  Each parameter is therefore declared as an INTEGER count of
the deck's own finest representable unit (e.g. P2 in 0.001 d/h, G3 in 0.01 mg/day,
SDUL/SLLL offsets in 0.001 cm3/cm3).  The written text is then exact, and the
read-back recovers the integer bit-for-bit at BOTH range bounds.

USAGE
-----
    python calib_run.py --workdir <wd> --out <metrics.json>

Env:
    KDT_CALIB_PARAMS  path to {"name": value, ...} for this candidate (runner mode)
    KDT_CALIB_SPLIT   "" | "full" | "calibration" | "holdout"   (see above)
    KDT_DSSAT_CALIB_CACHE  optional cache DIRECTORY (path only — it can never
                      redirect which gauge/obs is scored; the obs envelope pinned
                      below is re-asserted on every load)

On ANY failure this writes NOTHING and exits non-zero (a missing metrics file scores
+inf in the kit — never a fake pass).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

KI = Path("KISSPATH_KI_ROOT/DSSAT/knowledge_infrastructure")
sys.path.insert(0, str(KI / "tools"))
sys.path.insert(0, str(KI / "tools" / "s2_weather_prep"))
sys.path.insert(0, "KISSPATH_KI_TOOLS_COMMON")

# ===========================================================================
# TARGET CASE — pinned constants. NOT readable from the environment.
# ===========================================================================
OBS_ID = "spam2020"                     # the gauge/obs id of the TARGET CASE
CASE_ID = f"OBS:{OBS_ID}"               # -> "OBS:spam2020"
OBS_DATASET = "SPAM2020"                # crop_obs source tag every point must carry
CROP = "maize"
CROP_CODE = "MZ"
CULTIVAR = "CN0001"                     # Zhengdan 958, Huang-Huai-Hai summer maize
CUL_FILE = "MZCER048.CUL"
SOIL_ID = "IB00000004"                  # generic deep silty loam (validated run)
LAT_RANGE = (35.0, 37.5)
LON_RANGE = (116.0, 119.0)
STEP = 0.5
YEAR = 2020
PLANTING = "2020-06-15"
SIM_VAR = "HWAM"                        # dag output var scored

# --- obs envelope, pinned from the VALIDATED run (real_case_result.json,
#     provenance DSSAT_20260630T053443Z).  Every field the case declares is
#     asserted on EVERY eval; a changed/corrupted SPAM series for the same
#     region can therefore never be silently scored.
OBS_N_CELLS = 42
OBS_MEAN_KGHA = 6461.9047619047615      # == real_case_result.obs_region_kgha (6461.9)
OBS_MIN_KGHA = 1800.0
OBS_MAX_KGHA = 8400.0
OBS_SUM_KGHA = 271400.0
OBS_SHA256 = "56332d325c5629bb1706c1efafb83231521be4814a00e9bb2c074c8d18d42a80"
OBS_TOL = 1e-6                          # relative tolerance on the pinned aggregates

# --- holdout: leave-region-out spatial block on the 0.5deg grid.
#     The EASTERN block (lon >= HOLDOUT_LON_MIN) is held out: 6 lat x 2 lon = 12 of
#     42 cells = 28.6% ~ fraction 0.3.  Contiguous, so it is a genuine spatial
#     transfer test, not a random-cell shuffle.  NOTE: this split is applied ONLY
#     when the kit asks for it explicitly; the DEFAULT scores all 42 cells.
HOLDOUT_LON_MIN = 118.5

# --- binding shared spec (models/DSSAT/knowledge_infrastructure/interface_contracts.yaml
#     -> shared: shared_specs/dssat/base/format_spec.yaml)
SPEC_PATH = Path("KISSPATH_KI_ROOT/shared_specs/dssat/base/format_spec.yaml")

CACHE_DIR = Path(os.environ.get("KDT_DSSAT_CALIB_CACHE") or "/tmp/dssat_calib_cache")
WTH_DIR = CACHE_DIR / "wth"
OBS_CACHE = CACHE_DIR / "obs_spam2020.json"


class Fail(RuntimeError):
    """Any condition that must produce NO metrics and a non-zero exit."""


# ===========================================================================
# Parameter table — name -> (default, artifact, writer/reader spec)
# All values are INTEGER counts of the deck's finest representable unit.
# Keep in lockstep with calibration.yaml (same names, defaults, ranges).
# ===========================================================================
CUL_FIELDS = ["P1", "P2", "P5", "G2", "G3", "PHINT"]      # .CUL column order
CUL_COL = {n: (37 + 6 * i, 42 + 6 * i) for i, n in enumerate(CUL_FIELDS)}  # 1-indexed

# name -> (cul field, scale, format-decimals)
CUL_PARAMS = {
    "P1":        ("P1",    1,    1),   # degC.day
    "P2_MD":     ("P2",    1000, 4),   # 0.001 d/h
    "P5":        ("P5",    1,    1),   # degC.day
    "G2":        ("G2",    1,    1),   # kernels/plant
    "G3_CG":     ("G3",    100,  2),   # 0.01 mg/day
    "PHINT_DD":  ("PHINT", 10,   1),   # 0.1 degC.day
}
# name -> (.SOL profile-level header key, scale, decimals)
SOL_SCALAR_PARAMS = {
    "SLDR_MD": ("SLDR", 1000, 3),      # 0.001 (-)
    "SLPF_MD": ("SLPF", 1000, 3),      # 0.001 (-)
}
# name -> (.SOL per-layer header key, scale, decimals)  — ADDITIVE offset
SOL_LAYER_OFFSETS = {
    "SDUL_OFF": ("SDUL", 1000, 3),     # 0.001 cm3/cm3, added to every layer
    "SLLL_OFF": ("SLLL", 1000, 3),
}
# name -> (.SOL per-layer header key, scale, decimals) — MULTIPLICATIVE, in 1/1000.
# Applied as exact integer arithmetic on the deck's own milli-unit grid:
#     new_milli = (base_milli * value + 500) // 1000
# Layer 1 of IB00000004 has base SRGF = 1.000 (milli 1000), so its written value is
# the requested integer ITSELF -> the scale reads back independently and exactly.
SOL_LAYER_SCALES = {
    "SRGF_SCL": ("SRGF", 1000, 3),
}

DEFAULTS = {
    "P1": 270, "P2_MD": 450, "P5": 800, "G2": 800, "G3_CG": 690, "PHINT_DD": 375,
    "SDUL_OFF": 0, "SLLL_OFF": 0, "SRGF_SCL": 1000, "SLDR_MD": 400, "SLPF_MD": 1000,
    "FERT_N": 200, "IC_SH2O": 200, "PPOP_CG": 720,
}
PARAM_NAMES = tuple(DEFAULTS)


# ===========================================================================
# Shared-spec loading + FILEX / batch validation (must_validate_widths_pre_write)
# ===========================================================================
def load_format_spec() -> dict:
    """Load the binding DSSAT shared format spec.  FAIL CLOSED if unreadable.

    interface_contracts.yaml binds this KI to shared_specs/dssat/base/format_spec.yaml.
    This driver CLAIMS to validate FILEX widths + the FILEX path constraint before
    writing, so a missing/unparseable spec must fail the eval, never degrade to an
    unvalidated write.
    """
    try:
        import yaml
    except ImportError as exc:                      # pragma: no cover
        raise Fail(f"PyYAML unavailable — cannot load the DSSAT shared spec: {exc}")
    if not SPEC_PATH.is_file():
        raise Fail(f"binding shared spec missing: {SPEC_PATH}")
    with open(SPEC_PATH, "r") as fh:                # read-only: works on a RO mount
        spec = yaml.safe_load(fh)
    if not isinstance(spec, dict):
        raise Fail(f"{SPEC_PATH}: spec did not parse to a mapping")
    fx = ((spec.get("field_widths") or {}).get("FILEX")) or {}
    rec_len = fx.get("record_length")
    layout = fx.get("field_layout")
    pc = ((spec.get("path_constraints") or {}).get("FILEX")) or {}
    max_chars = pc.get("max_chars")
    if not isinstance(rec_len, int) or rec_len <= 0:
        raise Fail(f"{SPEC_PATH}: field_widths.FILEX.record_length missing/invalid")
    if not isinstance(layout, dict) or not layout:
        raise Fail(f"{SPEC_PATH}: field_widths.FILEX.field_layout missing/invalid")
    if not isinstance(max_chars, int) or max_chars <= 0:
        raise Fail(f"{SPEC_PATH}: path_constraints.FILEX.max_chars missing/invalid")
    return {
        "record_length": rec_len,
        "field_layout": layout,
        "max_chars": max_chars,
        "must_be_relative": bool(pc.get("must_be_relative_to_workdir")),
        "forbidden": ((spec.get("forbidden_combinations") or {}).get("FILEX")) or [],
    }


SPEC = None            # populated once in main(); every writer asserts it is loaded


def _spec() -> dict:
    if SPEC is None:
        raise Fail("shared format spec was never loaded — refusing to write a deck")
    return SPEC


# --- *TREATMENTS record ----------------------------------------------------
# The spec names TRTNO where the FILEX header names the column "N".
_SPEC_TO_HEADER = {"TRTNO": "N"}
_TREATMENT_INT_FIELDS = ("TRTNO", "R", "O", "C", "CU", "FL", "SA", "IC", "MP", "MI",
                         "MF", "MR", "MC", "MT", "ME", "MH", "SM")


def _find_treatments(lines):
    """Return (header_index, data_index) of the *TREATMENTS header + first data row."""
    for i, ln in enumerate(lines):
        if ln.startswith("*TREATMENTS"):
            for j in range(i + 1, len(lines)):
                if lines[j].startswith("@"):
                    for k in range(j + 1, len(lines)):
                        s = lines[k]
                        if not s.strip() or s.startswith("*") or s.startswith("@"):
                            break
                        return j, k
                    raise Fail("FILEX: *TREATMENTS header has no data row")
            raise Fail("FILEX: *TREATMENTS section has no '@' header line")
    raise Fail("FILEX: no *TREATMENTS section")


def validate_filex_deck(lines, where: str) -> None:
    """Validate a FILEX against the binding shared spec.  Call BEFORE writing.

    Enforces field_widths.FILEX.record_length + field_layout and the
    forbidden_combinations.FILEX.harvs_m_with_harvest_details rule.
    """
    sp = _spec()
    hdr_i, dat_i = _find_treatments(lines)
    header, data = lines[hdr_i], lines[dat_i]

    # --- record_length: the *TREATMENTS record must fit the 92-column record.
    for label, ln in (("header", header), ("record", data)):
        if len(ln.rstrip()) > sp["record_length"]:
            raise Fail(f"{where}: *TREATMENTS {label} is {len(ln.rstrip())} chars, "
                       f"spec record_length is {sp['record_length']}")

    # --- field_layout: names + order + column agreement with the header windows
    #     DSSAT's own PARSE_HEADERS derives (see the module docstring for why a
    #     one-column tolerance is the faithful reconciliation here).
    hdr_cols = parse_header_cols(header)
    spec_names = list(sp["field_layout"].keys())
    hdr_names = list(hdr_cols.keys())
    want_hdr = [_SPEC_TO_HEADER.get(n, n) for n in spec_names]
    if hdr_names != want_hdr:
        raise Fail(f"{where}: *TREATMENTS header fields {hdr_names} do not match the "
                   f"spec field_layout order {want_hdr}")
    for name in spec_names:
        win = sp["field_layout"][name]
        s_start, s_end = int(win["start"]), int(win["end"])
        h_start, h_end = hdr_cols[_SPEC_TO_HEADER.get(name, name)]
        if abs(s_start - h_start) > 1 or abs(s_end - h_end) > 1:
            raise Fail(f"{where}: *TREATMENTS field {name} sits at columns "
                       f"{h_start}-{h_end} but the spec declares {s_start}-{s_end} "
                       f"— the record is column-shifted")

    # --- the data row must actually parse in those windows.
    for name in spec_names:
        h_start, h_end = hdr_cols[_SPEC_TO_HEADER.get(name, name)]
        tok = data[h_start - 1:h_end].strip()
        if name in _TREATMENT_INT_FIELDS:
            try:
                int(tok)
            except ValueError:
                raise Fail(f"{where}: *TREATMENTS {name} = {tok!r} is not an integer "
                           f"at columns {h_start}-{h_end}")
        elif not tok:
            raise Fail(f"{where}: *TREATMENTS {name} is empty at columns "
                       f"{h_start}-{h_end}")

    # --- forbidden_combinations: HARVS=M must not carry a *HARVEST DETAILS section.
    harvs = None
    cols = {}
    for ln in lines:
        if ln.startswith("@") and "HARVS" in ln:
            cols = parse_header_cols(ln)
            continue
        if cols and "HARVS" in cols and ln.strip() and not ln.startswith(("@", "*")):
            harvs = get_field(ln, cols["HARVS"]).strip()
            cols = {}
    if harvs == "M" and any(ln.startswith("*HARVEST DETAILS") for ln in lines):
        raise Fail(f"{where}: HARVS=M with a *HARVEST DETAILS section — "
                   f"forbidden_combinations.FILEX.harvs_m_with_harvest_details")


def enforce_batch_filex_path(workdir: Path, filex: Path) -> str:
    """Make DSSBatch.v48's FILEX path spec-compliant, then verify it.

    ``path_constraints.FILEX`` requires the FILEX path to be RELATIVE to the workdir
    and <= max_chars (95); ``field_widths.FILEX.record_length`` (92) is the width of
    the batch record's FILEX field, with TRTNO immediately after it.  create_workdir
    writes an ABSOLUTE path there, so we rewrite the field to the workdir-relative
    basename (DSSAT runs with cwd=workdir), validating widths BEFORE the write and
    reading the value back afterwards.  Returns the relative path actually recorded.
    """
    sp = _spec()
    width = sp["record_length"]
    batch = workdir / "DSSBatch.v48"
    if not batch.is_file():
        raise Fail(f"{workdir}: DSSBatch.v48 missing")
    if batch.is_symlink():
        raise Fail(f"{batch}: is a symlink — refusing to write through it")

    rel = os.path.relpath(str(filex.resolve()), str(workdir.resolve()))
    if os.path.isabs(rel) or rel.startswith(os.pardir + os.sep):
        raise Fail(f"FILEX {filex} is not inside the workdir {workdir}")
    if sp["must_be_relative"] and os.path.isabs(rel):
        raise Fail(f"FILEX path {rel!r} must be relative to the workdir")
    if len(rel) > sp["max_chars"]:
        raise Fail(f"FILEX path {rel!r} is {len(rel)} chars > spec max_chars "
                   f"{sp['max_chars']} (A95 field truncates silently)")
    if len(rel) > width:
        raise Fail(f"FILEX path {rel!r} is {len(rel)} chars > the {width}-char batch "
                   f"FILEX field — TRTNO would be shifted")

    lines = batch.read_text().splitlines()
    hdr_idx = None
    for i, ln in enumerate(lines):
        if ln.startswith("@FILEX"):
            hdr_idx = i
            break
    if hdr_idx is None:
        raise Fail(f"{batch}: no @FILEX header record")
    # The header must reserve EXACTLY `width` columns for the path field, so the
    # five I6 fields TRTNO/RP/SQ/OP/CO occupy columns width+1 .. width+30.  A
    # 96-wide field here is the Xinjiang failure this rule exists for: it pushes
    # TRTNO four columns right and DSSAT reads a blank treatment number.
    trt_win = slice(width, width + 6)
    hdr = lines[hdr_idx]
    if hdr[:width].strip() != "@FILEX":
        raise Fail(f"{batch}: @FILEX header field is not {width} columns wide")
    if hdr[trt_win].strip() != "TRTNO":
        raise Fail(f"{batch}: TRTNO is not in columns {width + 1}-{width + 6} "
                   f"(found {hdr[trt_win]!r}) — the FILEX field is not {width} wide")

    n_data = 0
    for i in range(hdr_idx + 1, len(lines)):
        ln = lines[i]
        if not ln.strip():
            continue
        tail = ln[width:]
        if not tail.strip():
            raise Fail(f"{batch}: data record {i} has no TRTNO block after column {width}")
        # TRTNO RP SQ OP CO are five 6-column integer fields immediately after the
        # path field; all five must parse where the spec puts them.
        if len(tail.rstrip()) > 30:
            raise Fail(f"{batch}: record {i} has {len(tail.rstrip())} chars after "
                       f"column {width}, expected 5 x I6 = 30")
        try:
            fields = [int(tail[6 * k:6 * (k + 1)]) for k in range(5)]
        except ValueError:
            raise Fail(f"{batch}: TRTNO/RP/SQ/OP/CO not parseable as 5 x I6 at "
                       f"columns {width + 1}+ ({tail!r}) — the FILEX field is not "
                       f"{width} columns wide")
        trt = fields[0]
        if trt < 1:
            raise Fail(f"{batch}: TRTNO {trt} < 1")
        new = f"{rel:<{width}s}{tail}"
        # PRE-WRITE width validation: the rewrite may not move a single column.
        if len(new) != len(ln) or new[width:] != ln[width:]:
            raise Fail(f"{batch}: rewriting the FILEX field would shift columns")
        lines[i] = new
        n_data += 1
    if n_data == 0:
        raise Fail(f"{batch}: no data records under @FILEX")

    batch.write_text("\n".join(lines) + "\n")

    # --- read the value back out of the artifact DSSAT consumes.
    got = None
    for ln in batch.read_text().splitlines()[hdr_idx + 1:]:
        if not ln.strip():
            continue
        field = ln[:width].strip()
        if got is not None and field != got:
            raise Fail(f"{batch}: FILEX path differs between records")
        got = field
    if got != rel:
        raise Fail(f"{batch}: FILEX path read back {got!r} != {rel!r}")
    if os.path.isabs(got):
        raise Fail(f"{batch}: FILEX path {got!r} is absolute")
    resolved = (workdir / got).resolve()
    if resolved != filex.resolve():
        raise Fail(f"{batch}: FILEX path {got!r} resolves to {resolved}, not {filex}")
    return got


# ===========================================================================
# DSSAT fixed-width deck helpers
# ===========================================================================
def parse_header_cols(line: str) -> dict:
    """Column windows of a DSSAT '@' header line, 1-indexed inclusive.

    Faithful port of dssat-csm-os ``Utilities/READS.for :: PARSE_HEADERS`` — the
    routine IPSOIL_Inp.for / IPEXP use to slice every data line.  Writing back into
    exactly these windows is what makes the edit byte-safe for the FORTRAN reader.
    """
    s = line.rstrip("\n")
    length = len(s.rstrip())
    if length <= 1:
        return {}
    cols = [[1, None]]
    spaces = True
    i = 2
    while i <= length:
        ch = s[i - 1]
        if ch == "!":
            length = i - 1
            break
        if ch == " ":
            if not spaces:
                cols[-1][1] = i - 1
                cols.append([i + 1, None])
                spaces = True
        else:
            spaces = False
        i += 1
    cols[-1][1] = length
    out = {}
    for k, (c1, c2) in enumerate(cols):
        raw = s[1:c2] if k == 0 else s[c1 - 1:c2]
        name = raw.strip().rstrip(". ")
        if name:
            out[name] = (c1, c2)
    return out


def get_field(line: str, win) -> str:
    c1, c2 = win
    return line[c1 - 1:c2]


def set_field(line: str, win, text: str) -> str:
    c1, c2 = win
    width = c2 - c1 + 1
    if len(text) > width:
        raise Fail(f"value {text!r} does not fit the {width}-char DSSAT field {win}")
    padded = line.ljust(c2)
    return padded[:c1 - 1] + text.rjust(width) + padded[c2:]


def fmt_scaled(int_value: int, scale: int, decimals: int) -> str:
    """Render an integer count of 1/scale units with `decimals` decimals — exact."""
    return f"{int_value / scale:.{decimals}f}"


def read_scaled(text: str, scale: int) -> int:
    v = float(text)
    iv = int(round(v * scale))
    if abs(v * scale - iv) > 1e-6:
        raise Fail(f"field {text!r} is not on the 1/{scale} deck grid")
    return iv


def _assert_writable(path: Path) -> None:
    """Never write through a symlink into the shared read-only DSSAT install."""
    if path.is_symlink():
        raise Fail(f"{path}: is a symlink into the shared DSSAT install — refusing "
                   f"to inject (create_workdir must have replaced it with a copy)")


# ---------------------------------------------------------------------------
# .CUL — CERES-Maize cultivar record (FORMAT A6,1X,A16,7X,A6,6F6.0)
# ---------------------------------------------------------------------------
def inject_cul(path: Path, params: dict) -> None:
    _assert_writable(path)
    lines = path.read_text(errors="ignore").splitlines()
    n_hit = 0
    for idx, ln in enumerate(lines):
        if not ln.startswith(CULTIVAR):
            continue
        if len(ln) < 72:
            raise Fail(f"{path}: cultivar record for {CULTIVAR} is truncated")
        for pname, (field, scale, dec) in CUL_PARAMS.items():
            lines[idx] = set_field(lines[idx], CUL_COL[field],
                                   fmt_scaled(params[pname], scale, dec))
        n_hit += 1
    if n_hit == 0:
        raise Fail(f"{path}: cultivar {CULTIVAR} not found (China library not merged?)")
    path.write_text("\n".join(lines) + "\n")


def read_cul(path: Path) -> dict:
    """Read back every cultivar param from the record(s) DSSAT will consume."""
    got = None
    with open(path, "r", errors="ignore") as fh:
        for ln in fh:
            if not ln.startswith(CULTIVAR):
                continue
            vals = {p: read_scaled(get_field(ln, CUL_COL[f]), s)
                    for p, (f, s, _d) in CUL_PARAMS.items()}
            if got is not None and vals != got:
                raise Fail(f"{path}: duplicate {CULTIVAR} records disagree after injection")
            got = vals
    if got is None:
        raise Fail(f"{path}: cultivar {CULTIVAR} vanished after injection")
    return got


# ---------------------------------------------------------------------------
# .SOL — profile IB00000004
# ---------------------------------------------------------------------------
def _soil_block(lines):
    start = None
    for i, ln in enumerate(lines):
        if ln.startswith("*") and SOIL_ID in ln[:12]:
            start = i
            break
    if start is None:
        raise Fail(f"soil profile {SOIL_ID} not found in SOIL.SOL")
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j].startswith("*"):
            end = j
            break
    return start, end


def _scaled_layer(base_milli: int, scale_milli: int) -> int:
    """Exact integer scaling on the deck's own 1/1000 grid (round-half-up)."""
    return (base_milli * scale_milli + 500) // 1000


def inject_sol(path: Path, params: dict, base_layers: dict | None = None) -> dict:
    """Write the soil levers into profile SOIL_ID.

    `base_layers` pins the UNPERTURBED per-layer SDUL/SLLL/SRGF so the additive
    offsets and the multiplicative SRGF scale are always applied to the pristine
    profile (never compounded).  Returns the base it used so the caller can reuse it
    for the Soil/ duplicate.
    """
    _assert_writable(path)
    lines = path.read_text(errors="ignore").splitlines()
    start, end = _soil_block(lines)
    cols = {}
    layer_i = 0
    base = dict(base_layers or {})
    first_pass = base_layers is None
    for i in range(start + 1, end):
        ln = lines[i]
        if not ln.strip():
            continue
        if ln.lstrip().startswith("!"):
            continue
        if ln.startswith("@"):
            cols = parse_header_cols(ln)
            if "SLB" in cols:
                layer_i = 0
            continue
        if not cols:
            continue
        if "SLB" in cols:                                   # layer data row
            for pname, (key, scale, dec) in SOL_LAYER_OFFSETS.items():
                if key not in cols:
                    continue
                bkey = (key, layer_i)
                if first_pass:
                    base[bkey] = read_scaled(get_field(ln, cols[key]), scale)
                if bkey not in base:
                    raise Fail(f"{path}: layer {layer_i} missing base for {key}")
                ln = set_field(ln, cols[key],
                               fmt_scaled(base[bkey] + params[pname], scale, dec))
            for pname, (key, scale, dec) in SOL_LAYER_SCALES.items():
                if key not in cols:
                    continue
                bkey = (key, layer_i)
                if first_pass:
                    base[bkey] = read_scaled(get_field(ln, cols[key]), scale)
                if bkey not in base:
                    raise Fail(f"{path}: layer {layer_i} missing base for {key}")
                ln = set_field(ln, cols[key],
                               fmt_scaled(_scaled_layer(base[bkey], params[pname]),
                                          scale, dec))
            lines[i] = ln
            layer_i += 1
        else:                                               # profile-level row
            for pname, (key, scale, dec) in SOL_SCALAR_PARAMS.items():
                if key in cols:
                    ln = set_field(ln, cols[key], fmt_scaled(params[pname], scale, dec))
            lines[i] = ln
    path.write_text("\n".join(lines) + "\n")
    return base


def read_sol(path: Path, base_layers: dict) -> dict:
    """Recover the soil levers from the written profile — exact integer arithmetic.

    SDUL/SLLL offsets are recovered by differencing against the pinned base.  The
    SRGF scale is recovered INDEPENDENTLY from the layer whose base is exactly
    1.000 cm3/cm3 (layer 1 of IB00000004): its written value IS the requested
    integer.  Every other layer is then required to equal the exact scaling of its
    own base by that recovered value.
    """
    lines = path.read_text(errors="ignore").splitlines()
    start, end = _soil_block(lines)
    cols = {}
    layer_i = 0
    scalars, offsets = {}, {}
    scale_rows = {}                    # pname -> {layer_i: written milli}
    for i in range(start + 1, end):
        ln = lines[i]
        if not ln.strip() or ln.lstrip().startswith("!"):
            continue
        if ln.startswith("@"):
            cols = parse_header_cols(ln)
            if "SLB" in cols:
                layer_i = 0
            continue
        if not cols:
            continue
        if "SLB" in cols:
            for pname, (key, scale, _d) in SOL_LAYER_OFFSETS.items():
                if key not in cols:
                    continue
                off = read_scaled(get_field(ln, cols[key]), scale) - base_layers[(key, layer_i)]
                prev = offsets.setdefault(pname, off)
                if prev != off:
                    raise Fail(f"{path}: {pname} not uniform across layers "
                               f"({prev} vs {off} at layer {layer_i})")
            for pname, (key, scale, _d) in SOL_LAYER_SCALES.items():
                if key not in cols:
                    continue
                scale_rows.setdefault(pname, {})[layer_i] = read_scaled(
                    get_field(ln, cols[key]), scale)
            layer_i += 1
        else:
            for pname, (key, scale, _d) in SOL_SCALAR_PARAMS.items():
                if key in cols:
                    scalars[pname] = read_scaled(get_field(ln, cols[key]), scale)

    scales = {}
    for pname, (key, _s, _d) in SOL_LAYER_SCALES.items():
        rows = scale_rows.get(pname) or {}
        if not rows:
            raise Fail(f"{path}: {pname} column {key} absent from the layer table")
        anchors = [i for i in rows if base_layers.get((key, i)) == 1000]
        if not anchors:
            raise Fail(f"{path}: no layer with base {key} == 1.000 — {pname} cannot be "
                       f"read back independently")
        recovered = rows[anchors[0]]
        for i, milli in rows.items():
            expect = _scaled_layer(base_layers[(key, i)], recovered)
            if milli != expect:
                raise Fail(f"{path}: {pname} layer {i} is {milli} but scaling its base "
                           f"{base_layers[(key, i)]} by {recovered} gives {expect} — "
                           f"the profile is not a uniform scaling")
        scales[pname] = recovered

    missing = ((set(SOL_SCALAR_PARAMS) - set(scalars))
               | (set(SOL_LAYER_OFFSETS) - set(offsets))
               | (set(SOL_LAYER_SCALES) - set(scales)))
    if missing:
        raise Fail(f"{path}: could not read back {sorted(missing)}")
    return {**scalars, **offsets, **scales}


# ---------------------------------------------------------------------------
# FileX (*.MZX) — planting density, initial soil water, fertiliser N
# ---------------------------------------------------------------------------
def _filex_path(workdir: Path) -> Path:
    hits = sorted(workdir.glob("*.MZX"))
    if len(hits) != 1:
        raise Fail(f"{workdir}: expected exactly one FileX (*.MZX), found {len(hits)}")
    return hits[0]


def inject_filex(path: Path, params: dict) -> None:
    _assert_writable(path)
    lines = path.read_text().splitlines()
    # The deck create_workdir just regenerated must itself be spec-valid.
    validate_filex_deck(lines, f"{path} (as generated)")
    cols = {}
    for i, ln in enumerate(lines):
        if ln.startswith("*") or not ln.strip():
            cols = {}
            continue
        if ln.startswith("@"):
            cols = parse_header_cols(ln)
            continue
        if not cols:
            continue
        if "PPOP" in cols and "PDATE" in cols:
            txt = fmt_scaled(params["PPOP_CG"], 100, 2)
            ln = set_field(ln, cols["PPOP"], txt)
            if "PPOE" in cols:
                ln = set_field(ln, cols["PPOE"], txt)
            lines[i] = ln
        elif "SH2O" in cols and "ICBL" in cols:
            lines[i] = set_field(ln, cols["SH2O"],
                                 fmt_scaled(params["IC_SH2O"], 1000, 3))
    # PRE-WRITE validation of the edited deck (must_validate_widths_pre_write).
    validate_filex_deck(lines, f"{path} (post-injection)")
    path.write_text("\n".join(lines) + "\n")


def read_filex(path: Path) -> dict:
    lines = path.read_text().splitlines()
    cols = {}
    ppop, sh2o, famn = set(), set(), 0.0
    n_fert = 0
    for ln in lines:
        if ln.startswith("*") or not ln.strip():
            cols = {}
            continue
        if ln.startswith("@"):
            cols = parse_header_cols(ln)
            continue
        if not cols:
            continue
        if "PPOP" in cols and "PDATE" in cols:
            ppop.add(read_scaled(get_field(ln, cols["PPOP"]), 100))
            if "PPOE" in cols:
                ppop.add(read_scaled(get_field(ln, cols["PPOE"]), 100))
        elif "SH2O" in cols and "ICBL" in cols:
            sh2o.add(read_scaled(get_field(ln, cols["SH2O"]), 1000))
        elif "FAMN" in cols and "FDATE" in cols:
            famn += float(get_field(ln, cols["FAMN"]))
            n_fert += 1
    if len(ppop) != 1:
        raise Fail(f"{path}: PPOP/PPOE disagree or missing ({sorted(ppop)})")
    if len(sh2o) != 1:
        raise Fail(f"{path}: initial SH2O not uniform across layers ({sorted(sh2o)})")
    if n_fert == 0:
        raise Fail(f"{path}: no *FERTILIZERS rows — FERT_N never reached the deck")
    if abs(famn - round(famn)) > 1e-9:
        raise Fail(f"{path}: FAMN total {famn} is not integral")
    return {"PPOP_CG": ppop.pop(), "IC_SH2O": sh2o.pop(), "FERT_N": int(round(famn))}


# ===========================================================================
# Observations — SPAM 2020, with the full declared envelope enforced
# ===========================================================================
def _grid_points():
    lats, lons = [], []
    n_lat = int(round((LAT_RANGE[1] - LAT_RANGE[0]) / STEP)) + 1
    n_lon = int(round((LON_RANGE[1] - LON_RANGE[0]) / STEP)) + 1
    for i in range(n_lat):
        lats.append(round(LAT_RANGE[0] + i * STEP, 4))
    for j in range(n_lon):
        lons.append(round(LON_RANGE[0] + j * STEP, 4))
    return [(la, lo) for la in lats for lo in lons]


def _obs_digest(rows) -> str:
    canon = ";".join(f"{r['lat']:.4f},{r['lon']:.4f},{r['yield_kgha']:.6f}" for r in rows)
    return hashlib.sha256(canon.encode()).hexdigest()


def _build_obs():
    """Read SPAM 2020 through the KI's own obs tool (read-only zip/CSV access)."""
    from ki_tools_common.crop_obs import get_observed_yield
    rows = []
    for la, lo in _grid_points():
        rec = get_observed_yield(la, lo, CROP)
        rows.append({"lat": la, "lon": lo,
                     "yield_kgha": float(rec["yield_kgha"]),
                     "source": str(rec.get("source"))})
    return rows


def load_obs() -> list:
    """Load the pinned SPAM2020 obs record and ASSERT the whole declared envelope.

    Enforced (fail-closed, no metrics, non-zero exit on ANY mismatch):
      * dataset identity  — every point sourced from SPAM2020 (never the FAOSTAT
        national fallback that crop_obs falls through to when SPAM has no cell);
      * the EXACT grid    — 42 points, lat/lon set identical to the target case grid;
      * per-point values  — finite and strictly positive;
      * the aggregates    — n, min, max, sum and regional mean pinned from the
        validated run (real_case_result.json obs_region_kgha = 6461.9);
      * a sha256 over the canonical (lat, lon, yield) table.
    """
    rows = None
    if OBS_CACHE.is_file():
        try:
            with open(OBS_CACHE, "r") as fh:          # read-only: works on RO mounts
                rows = json.load(fh)
        except (OSError, ValueError):
            rows = None
    if rows is None:
        rows = _build_obs()
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            tmp = OBS_CACHE.with_suffix(".tmp")
            tmp.write_text(json.dumps(rows, indent=1))
            tmp.replace(OBS_CACHE)
        except OSError:
            pass                                       # read-only cache dir is fine

    want = _grid_points()
    if len(rows) != OBS_N_CELLS:
        raise Fail(f"obs contract: expected {OBS_N_CELLS} SPAM cells, got {len(rows)}")
    if [(round(float(r["lat"]), 4), round(float(r["lon"]), 4)) for r in rows] != want:
        raise Fail("obs contract: grid point set does not match the target case grid")
    vals = []
    for r in rows:
        src = str(r.get("source", ""))
        if not src.startswith(OBS_DATASET):
            raise Fail(f"obs contract: point ({r['lat']},{r['lon']}) is sourced from "
                       f"{src!r}, not {OBS_DATASET} — refusing to score a fallback series")
        v = float(r["yield_kgha"])
        if not (v == v) or v <= 0.0:
            raise Fail(f"obs contract: non-positive/NaN obs at ({r['lat']},{r['lon']})")
        vals.append(v)

    def _chk(label, got, want_v, tol=OBS_TOL):
        if abs(got - want_v) > tol * max(abs(want_v), 1.0):
            raise Fail(f"obs contract: {label} = {got!r}, pinned {want_v!r} — the SPAM "
                       f"series for this region changed; refusing to score it")

    _chk("regional mean", sum(vals) / len(vals), OBS_MEAN_KGHA)
    _chk("sum", sum(vals), OBS_SUM_KGHA)
    _chk("min", min(vals), OBS_MIN_KGHA)
    _chk("max", max(vals), OBS_MAX_KGHA)
    digest = _obs_digest(rows)
    if OBS_SHA256 and digest != OBS_SHA256:
        raise Fail(f"obs contract: sha256 {digest} != pinned {OBS_SHA256}")
    return rows


# ===========================================================================
# Weather cache — one-time CMFD -> .WTH prepare step (never per eval)
# ===========================================================================
def wth_for(idx: int) -> Path:
    return WTH_DIR / f"S{idx:03d}{YEAR % 100:02d}01.WTH"


def ensure_weather(points) -> None:
    missing = [(i, la, lo) for i, (la, lo) in enumerate(points)
               if not wth_for(i).is_file()]
    if not missing:
        return
    from datetime import datetime
    from ki_tools_common.load_forcing import load_daily_forcing_points
    from convert_cmfd_to_wth import write_wth
    WTH_DIR.mkdir(parents=True, exist_ok=True)
    fs = load_daily_forcing_points("cmfd", [(la, lo) for _i, la, lo in missing],
                                   YEAR, YEAR)
    for (i, la, lo), f in zip(missing, fs):
        daily = []
        for k, d in enumerate(f["dates"]):
            dt = d if isinstance(d, datetime) else datetime.fromisoformat(str(d)[:10])
            daily.append({"date": dt,
                          "srad": max(0.0, float(f["srad_wm2"][k]) * 0.0864),
                          "tmax": float(f["temp_max_c"][k]),
                          "tmin": float(f["temp_min_c"][k]),
                          "rain": max(0.0, float(f["precip_mm"][k])),
                          "wind": max(0.0, float(f["wind_ms"][k]) * 86.4)})
        write_wth(daily, str(wth_for(i)), f"S{i:03d}", la, lo)
    still = [i for i, _p in enumerate(points) if not wth_for(i).is_file()]
    if still:
        raise Fail(f"CMFD->WTH prepare failed for cells {still}")


# ===========================================================================
# One cell: build the deck via the KI tool, inject, verify, run, parse
# ===========================================================================
def run_cell(idx: int, lat: float, lon: float, params: dict, scratch: Path) -> float:
    import logging
    logging.disable(logging.INFO)
    from dssat_workdir_setup import create_workdir, run_dssat, parse_summary

    cell_dir = scratch / f"c{idx:02d}"
    # (1) the KI's OWN deck generator — regenerates every input from scratch.
    wd = Path(create_workdir(
        CROP_CODE, CULTIVAR, str(wth_for(idx)), SOIL_ID, None, lat, lon,
        PLANTING, YEAR, YEAR, str(cell_dir),
        fert_n=params["FERT_N"], ppop=params["PPOP_CG"] / 100.0))

    # (2) inject AFTER regeneration, into every copy DSSAT can reach.
    cul_paths = [p for p in (wd / CUL_FILE, wd / "Genotype" / CUL_FILE) if p.is_file()]
    if not cul_paths:
        raise Fail(f"{wd}: no writable {CUL_FILE} (China cultivar merge did not run)")
    for p in cul_paths:
        inject_cul(p, params)

    sol_paths = [p for p in (wd / "SOIL.SOL", wd / "Soil" / "SOIL.SOL") if p.is_file()]
    if not sol_paths:
        raise Fail(f"{wd}: SOIL.SOL missing")
    sol_base = None
    for p in sol_paths:
        sol_base = inject_sol(p, params, sol_base)

    filex = _filex_path(wd)
    inject_filex(filex, params)

    # (2b) shared-spec FILEX path contract on the deck DSSAT is actually handed.
    filex_rel = enforce_batch_filex_path(wd, filex)

    # (3) read every value back out of the artifacts the model consumes.
    applied = {}
    for p in cul_paths:
        got = read_cul(p)
        for name, (_f, _s, _d) in CUL_PARAMS.items():
            applied.setdefault(name, got[name])
            if applied[name] != got[name]:
                raise Fail(f"{p}: {name} read back {got[name]} != {applied[name]}")
    for p in sol_paths:
        got = read_sol(p, sol_base)
        for name in (list(SOL_SCALAR_PARAMS) + list(SOL_LAYER_OFFSETS)
                     + list(SOL_LAYER_SCALES)):
            applied.setdefault(name, got[name])
            if applied[name] != got[name]:
                raise Fail(f"{p}: {name} read back {got[name]} != {applied[name]}")
    applied.update(read_filex(filex))
    for name in PARAM_NAMES:
        if name not in applied:
            raise Fail(f"cell {idx}: {name} was never read back from the deck")
        if int(applied[name]) != int(params[name]):
            raise Fail(f"cell {idx}: {name} applied {applied[name]} != requested "
                       f"{params[name]} — the deck CLAMPED or rejected the value")

    # (4) run + fail-closed run health.
    res = run_dssat(str(wd), 600)
    if not isinstance(res, dict):
        raise Fail(f"cell {idx}: run_dssat returned {type(res)}")
    if res.get("success") is not True or res.get("return_code") != 0:
        raise Fail(f"cell {idx}: DSSAT exited rc={res.get('return_code')!r} "
                   f"success={res.get('success')!r}")
    if res.get("error_file"):
        raise Fail(f"cell {idx}: DSSAT wrote {res['error_file']}")
    summary_file = res.get("summary_file")
    if not summary_file or not Path(summary_file).is_file():
        raise Fail(f"cell {idx}: no Summary.OUT — the run produced no output "
                   f"(FILEX {filex_rel!r})")

    recs = parse_summary(str(wd))
    if not recs:
        raise Fail(f"cell {idx}: Summary.OUT parsed to zero records")
    hwam = recs[0].get(SIM_VAR)
    if hwam is None:
        raise Fail(f"cell {idx}: {SIM_VAR} absent from Summary.OUT")
    hwam = float(hwam)
    if hwam != hwam or hwam < 0.0:
        raise Fail(f"cell {idx}: {SIM_VAR} = {hwam!r}")
    return hwam


# ===========================================================================
# main
# ===========================================================================
def resolve_params() -> tuple:
    """Read the candidate vector.  Returns (values, handed_keys)."""
    pf = os.environ.get("KDT_CALIB_PARAMS")
    handed = {}
    if pf:
        p = Path(pf)
        if not p.is_file():
            raise Fail(f"KDT_CALIB_PARAMS points at {pf!r} which does not exist")
        with open(p, "r") as fh:
            handed = json.load(fh)
        if not isinstance(handed, dict):
            raise Fail("KDT_CALIB_PARAMS must contain a JSON object")
    values = dict(DEFAULTS)
    for k, v in handed.items():
        if k not in DEFAULTS:
            raise Fail(f"unknown parameter {k!r} in KDT_CALIB_PARAMS")
        fv = float(v)
        iv = int(round(fv))
        if abs(fv - iv) > 1e-9:
            raise Fail(f"{k} = {v!r} is not integral; every DSSAT deck lever is an "
                       f"integer count of the deck's finest representable unit")
        values[k] = iv
    return values, (set(handed) if pf else set(DEFAULTS))


def resolve_split() -> str:
    """Resolve KDT_CALIB_SPLIT.  DEFAULT = 'full' = the whole 42-cell target case."""
    raw = (os.environ.get("KDT_CALIB_SPLIT") or "").strip().lower()
    if raw in ("", "full", "all"):
        return "full"
    if raw in ("calibration", "holdout"):
        return raw
    raise Fail(f"unsupported KDT_CALIB_SPLIT {raw!r}")


def select_cells(split: str, points) -> list:
    """Cell indices for a split.  'full' is the whole declared target case."""
    if split == "full":
        idxs = list(range(len(points)))
    elif split == "holdout":
        idxs = [i for i, (_la, lo) in enumerate(points) if lo >= HOLDOUT_LON_MIN]
    else:
        idxs = [i for i, (_la, lo) in enumerate(points) if lo < HOLDOUT_LON_MIN]
    if split == "full" and len(idxs) != OBS_N_CELLS:
        raise Fail(f"full split selected {len(idxs)} cells, target case declares "
                   f"{OBS_N_CELLS}")
    if len(idxs) < 2:
        raise Fail(f"split {split!r} selected {len(idxs)} cells — not scoreable")
    return idxs


def main() -> int:
    global SPEC
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    SPEC = load_format_spec()      # fail-closed if the binding shared spec is gone
    params, handed = resolve_params()
    split = resolve_split()

    obs_rows = load_obs()
    points = [(float(r["lat"]), float(r["lon"])) for r in obs_rows]
    # Obs identity is DERIVED from the records actually loaded and scored (their
    # dataset tag), then cross-checked against the pinned target case — so the
    # __kdt__ declaration below CANNOT diverge from what was really scored.
    obs_sources = sorted({str(r["source"]) for r in obs_rows})
    tags = sorted({s.split("_", 1)[0].lower() for s in obs_sources})
    if len(tags) != 1:
        raise Fail(f"obs rows mix datasets {obs_sources} — cannot declare one scored_obs")
    resolved_obs_id = tags[0]
    if resolved_obs_id != OBS_ID:
        raise Fail(f"scored obs resolved to {resolved_obs_id!r}, target case is {OBS_ID!r}")
    resolved_case_id = f"OBS:{resolved_obs_id}"

    ensure_weather(points)
    idxs = select_cells(split, points)

    scratch = Path(tempfile.mkdtemp(prefix="dsc_", dir="/tmp"))   # short: Fortran 92-char
    try:
        sims, obss = [], []
        for i in idxs:
            la, lo = points[i]
            sims.append(run_cell(i, la, lo, params, scratch))
            obss.append(float(obs_rows[i]["yield_kgha"]))
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    sim_region = sum(sims) / len(sims)
    obs_region = sum(obss) / len(obss)
    if obs_region <= 0:
        raise Fail("obs regional mean is non-positive")
    pbias = 100.0 * (sim_region - obs_region) / obs_region
    if pbias != pbias:
        raise Fail("pbias is NaN")

    # secondary spatial-pattern diagnostics (NOT gate-determining for a
    # regional_aggregate_time_series obs_shape — kept out of the metric namespace
    # so the kit never builds an objective on them).
    diagnostics = {}
    try:
        from ki_tools_common.metrics import all_metrics
        diagnostics = {f"spatial_{k}": (None if v is None else float(v))
                       for k, v in all_metrics(obss, sims).items()}
    except Exception:
        diagnostics = {}

    payload = {
        "pbias": round(pbias, 6),
        "__kdt__": {
            "applied_params": {k: int(params[k]) for k in sorted(set(handed) | set(PARAM_NAMES))},
            "case_id": resolved_case_id,
            "scored_obs": (
                f"{resolved_obs_id} | SPAM 2020 V2r0 {CROP} yield via "
                f"ki_tools_common.crop_obs.get_observed_yield at {len(idxs)}/{OBS_N_CELLS} "
                f"grid points (lat {LAT_RANGE[0]}-{LAT_RANGE[1]}, lon {LON_RANGE[0]}-"
                f"{LON_RANGE[1]}, step {STEP}) | split={split} | sources={','.join(obs_sources)}"
                f" | cache={OBS_CACHE}"
            ),
            "split": split,
            "variable": SIM_VAR,
            "n_cells_scored": len(idxs),
            "sim_region_kgha": round(sim_region, 4),
            "obs_region_kgha": round(obs_region, 4),
            "diagnostics": diagnostics,
        },
    }
    Path(args.out).write_text(json.dumps(payload, indent=2))
    print(json.dumps({"pbias": payload["pbias"], "split": split,
                      "sim": payload["__kdt__"]["sim_region_kgha"],
                      "obs": payload["__kdt__"]["obs_region_kgha"],
                      "n": len(idxs)}))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:                      # noqa: BLE001 — fail closed, no metrics
        print(f"calib_run FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
