#!/usr/bin/env python3
"""
calib_run.py -- programmatic run+score of ONE WRF-Hydro parameter candidate.

TARGET CASE (pinned, NOT overridable from the environment):
    case_id      SITE:wangjiaba
    obs          china_gaugeflux -> KISSPATH_DATA/china_water_level/淮河txt/王家坝.txt
                 (stcd 50101100 == gauge 51030, Huai River main stem, ~30,630 km2)
    gauge        32.4275 N / 115.595 E, matched to a CHRTOUT channel feature with
                 Strahler order >= 2 (real_case WRF_Hydro_20260719T082141Z_172227)
    target       streamflow -> point_time_series, determining metric NSE

Usage
-----
    python calib_run.py --workdir <wd> --out <metrics.json>

injection.mode = runner.  The kit writes the candidate vector to the JSON at
$KDT_CALIB_PARAMS; this script injects every value into the artifacts WRF-Hydro
actually consumes (soil_properties.nc, GWBUCKPARM.nc, Fulldom_hires.nc,
CHANPARM.TBL), reads each one BACK out of that artifact, runs the model through
the KI's own run tool, extracts discharge through the KI's own extraction tool,
and scores against the pinned Wangjiaba obs.

Failure policy: any staging / injection / read-back / run / extraction problem
exits non-zero having written NO metrics file (the kit scores that as +inf).

Cost control: the model is warm-started from the completed reference run's
monthly RESTART + HYDRO_RST pair six months ahead of the scoring window, FORCING
is symlinked rather than copied, and the LDASOUT / RTOUT / CHRTOUT_GRID / GWOUT
output streams are switched off (only CHRTOUT is scored).  That turns the 11-year
cold-start reference run (2 h, ~300 MB of unused output) into a 42-month eval of
~40-65 min.  Nothing is downloaded or rebuilt per eval.
"""

import argparse
import json
import os
import shutil
import sys
import traceback
from pathlib import Path

import numpy as np

# --------------------------------------------------------------------------
# TARGET CASE — pinned constants.  Deliberately NOT read from the environment:
# an env-overridable gauge would let a mis-set variable score a different site
# while still self-declaring this one.
# --------------------------------------------------------------------------
CASE_ID = "SITE:wangjiaba"
OBS_DATASET = "china_gaugeflux"
OBS_FILE = Path("KISSPATH_DATA/china_water_level/淮河txt/王家坝.txt")
GAUGE_STCD = "50101100"
GAUGE_NAME = "王家坝 Wangjiaba"
GAUGE_LAT = 32.4275
GAUGE_LON = 115.595
MIN_ORDER = 2

# The channel feature the validated run scored (real_case_20260719T082156Z:
# idx=31, order 2, 32.511 N / 115.808 E, 22 km from the gauge = one coarse cell).
# Guard only: if a candidate's flow guard picks a different cell the eval is not
# comparable to the baseline, so it fails closed rather than silently rescoring
# somewhere else.
REF_CELL_LAT = 32.511
REF_CELL_LON = 115.808
REF_CELL_TOL_DEG = 0.05

# Completed reference run supplying DOMAIN, FORCING and the warm-start restarts.
REF_RUN = Path("KISSPATH_OUTPUTS/bengbu_wrfhydro_025deg_1980_1990")

KI_ROOT = Path(__file__).resolve().parent.parent
TOOLS = KI_ROOT / "tools"

# Blocked-temporal split.  Each split warm-starts 6 months before its scoring
# window so the conceptual GW bucket (which cold-starts at Zinit, GW_RESTART=0)
# and the soil column equilibrate under the CANDIDATE's parameters before any
# scored day.
# The holdout stops at 1988 because every 1989 day in the obs file is the -99
# missing marker (0 of 365 valid), so a 1989 model year would cost ~8 min per
# evaluation and contribute no scoreable day.
SPLITS = {
    "calibration": {"restart": "1980-07-01", "start": "1981-01-01", "end": "1983-12-31"},
    "holdout":     {"restart": "1986-07-01", "start": "1987-01-01", "end": "1988-12-31"},
}

# Read-back tolerance.  All of these fields are float32 on disk, so a requested
# float64 never round-trips bit-exactly; 1e-5 relative is ~80x float32 epsilon.
RTOL = 1e-5
ATOL = 1e-8


def die(msg):
    print(f"FATAL: {msg}", file=sys.stderr)
    sys.exit(1)


# --------------------------------------------------------------------------
# KI tool imports (reuse — the model is never reimplemented here)
# --------------------------------------------------------------------------
def load_ki_tools():
    sys.path.insert(0, str(TOOLS / "s10_execution"))
    sys.path.insert(0, str(TOOLS / "s11_output"))
    import run_wrfhydro
    import extract_discharge
    return run_wrfhydro, extract_discharge


def load_all_metrics():
    """Shared metric implementation; prefer the canonical package over the
    kdt-release copy, which has been observed stale and shadowing it."""
    for p in ("KISSPATH_KI_TOOLS_COMMON",
              "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect_multi_agent"):
        if Path(p, "ki_tools_common").is_dir():
            sys.path.insert(0, p)
            break
    from ki_tools_common.metrics import all_metrics
    return all_metrics


# --------------------------------------------------------------------------
# Parameter registry.  Each entry knows how to APPLY a value into the artifact
# WRF-Hydro consumes and how to READ IT BACK out of that same artifact.
# --------------------------------------------------------------------------
PARAMS = {
    # --- SOIL PARAMETERS: table addresses (dt_v043, 2026-09-12) --------------
    # This build was compiled WITHOUT -DSPATIAL_SOIL, so DOMAIN/soil_properties.nc is NEVER
    # OPENED by the model (the only READ_3D_SOIL call sits inside that #ifdef). Noah-MP reads
    # REFKDT/SLOPE from GENPARM.TBL and SMCMAX from SOILPARM.TBL (module_sf_noahmpdrv.F:1177-1197).
    # The earlier addresses here pointed at the NetCDF — a file the KI's own build tool CREATES by
    # copying values out of SOILPARM.TBL, which is why it looked right and never was: we were
    # calibrating the copy while the model read the original. Read-back passed; output never moved.
    # The tables are COPIED into the run dir by run_wrfhydro.setup_symlinks (containment fix), so
    # writing them here can no longer touch the shared source tree.
    "refkdt":       {"file": "GENPARM.TBL", "kind": "genparm_scalar", "var": "REFKDT_DATA",
                     "default": 3.0},
    # SLOPE_DATA is a 9-entry table indexed by SLOPETYP. The driver sets SLOPETYP=2 at
    # module_NoahMP_hrldas_driver.F:1106, but the physics loop overrides it to 1 at
    # module_sf_noahmpdrv.F:~634 before TRANSFER_MP_PARAMETERS, so index 1 is the live one.
    "slope":        {"file": "GENPARM.TBL", "kind": "genparm_slope", "var": "SLOPE_DATA",
                     "default": 0.1, "index": 1},
    # smcmax_mult (dt_v045, F2+F3): scales the WHOLE retention set — DRYSMC, WLTSMC, REFSMC, MAXSMC —
    # by one factor, in BOTH places the model reads porosity: SOILPARM.TBL (land model) and
    # hydro2dtbl.nc SMCMAX1/SMCREF1/SMCWLT1 (routing). Scaling porosity alone left field
    # capacity ABOVE porosity below x0.88, and scaling the land model alone desynchronised it
    # from the routing so +10% porosity RAISED the flood peak (2416->5392 m3/s; both scaled: it
    # correctly fell to 2279). Proportional scaling preserves the ordering by construction.
    # WATER (14) and land-ice (16) classes are never scaled.
    "smcmax_mult":  {"file": "SOILPARM.TBL", "kind": "soilparm_retention_scale",
                     "cols": ("DRYSMC", "WLTSMC", "REFSMC", "MAXSMC"), "skip_classes": (14, 16),
                     "also_nc": {"file": "hydro2dtbl.nc", "vars": ("SMCMAX1", "SMCREF1", "SMCWLT1"),
                                 "skip_above": 0.9},
                     "default": 1.0},
    # --- GWBUCKPARM.nc ------------------------------------------------------
    "gw_coeff":     {"file": "GWBUCKPARM.nc", "kind": "nc_uniform", "var": "Coeff",
                     "default": 44.84479904174805},
    "gw_expon":     {"file": "GWBUCKPARM.nc", "kind": "nc_uniform", "var": "Expon",
                     "default": 3.0},
    "gw_zmax":      {"file": "GWBUCKPARM.nc", "kind": "nc_uniform", "var": "Zmax",
                     "default": 250.0},
    "gw_zinit":     {"file": "GWBUCKPARM.nc", "kind": "nc_uniform", "var": "Zinit",
                     "default": 25.0},
    # --- Fulldom_hires.nc ---------------------------------------------------
    "ovroughrtfac": {"file": "Fulldom_hires.nc", "kind": "nc_uniform", "var": "OVROUGHRTFAC",
                     "default": 1.0},
    "retdeprtfac":  {"file": "Fulldom_hires.nc", "kind": "nc_uniform", "var": "RETDEPRTFAC",
                     "default": 1.0},
    "lksatfac":     {"file": "Fulldom_hires.nc", "kind": "nc_uniform", "var": "LKSATFAC",
                     "default": 1000.0},
    # --- CHANPARM.TBL -------------------------------------------------------
    "mann_n_mult":  {"file": "CHANPARM.TBL", "kind": "chanparm_scale", "var": "MannN",
                     "default": 1.0},
}

# Files copied (not symlinked) into the eval workdir because they are written to.
MUTABLE_DOMAIN = ["soil_properties.nc", "GWBUCKPARM.nc", "Fulldom_hires.nc", "hydro2dtbl.nc"]
LINKED_DOMAIN = ["geo_em.d01.nc", "wrfinput_d01.nc", "GWBASINS.nc",
                 "GEOGRID_LDASOUT_Spatial_Metadata.nc"]


# --------------------------------------------------------------------------
# Staging
# --------------------------------------------------------------------------
def stage_workdir(wd, split):
    wd.mkdir(parents=True, exist_ok=True)
    dom = wd / "DOMAIN"
    dom.mkdir(exist_ok=True)

    for f in LINKED_DOMAIN:
        src = REF_RUN / "DOMAIN" / f
        if not src.exists():
            die(f"reference DOMAIN file missing: {src}")
        dst = dom / f
        if not dst.exists():
            dst.symlink_to(src)
    for f in MUTABLE_DOMAIN:
        src = REF_RUN / "DOMAIN" / f
        if not src.exists():
            die(f"reference DOMAIN file missing: {src}")
        shutil.copy2(src, dom / f)

    forcing = wd / "FORCING"
    if not forcing.exists():
        if not (REF_RUN / "FORCING").is_dir():
            die(f"reference FORCING missing: {REF_RUN/'FORCING'}")
        forcing.symlink_to(REF_RUN / "FORCING")

    # Warm-start pair.  Copied, never symlinked: the model writes restarts into
    # the run dir and must not be able to touch the reference run's files.
    rdate = split["restart"]
    lsm_src = REF_RUN / f"RESTART.{rdate.replace('-','')}00_DOMAIN1"
    hyd_src = REF_RUN / f"HYDRO_RST.{rdate}_00:00_DOMAIN1"
    for src in (lsm_src, hyd_src):
        if not src.exists():
            die(f"warm-start restart missing: {src}")
        shutil.copy2(src, wd / src.name)
    return lsm_src.name, hyd_src.name


def hours_between(start, end):
    """Inclusive-of-end-day run length in hours, from restart date to end date."""
    import datetime as dt
    a = dt.date.fromisoformat(start)
    b = dt.date.fromisoformat(end)
    return int((b - a).days + 1) * 24


def write_namelists(wd, split, lsm_rst, hyd_rst):
    import datetime as dt
    r = dt.date.fromisoformat(split["restart"])
    khour = hours_between(split["restart"], split["end"])

    src_h = (REF_RUN / "namelist.hrldas").read_text()
    out = []
    for line in src_h.splitlines():
        s = line.strip()
        if s.startswith("START_YEAR"):
            out.append(f"START_YEAR  = {r.year}")
        elif s.startswith("START_MONTH"):
            out.append(f"START_MONTH = {r.month:02d}")
        elif s.startswith("START_DAY"):
            out.append(f"START_DAY   = {r.day:02d}")
        elif s.startswith("KHOUR"):
            out.append(f"KHOUR = {khour}")
        elif s.startswith("OUTPUT_TIMESTEP"):
            # Suppress per-day LDASOUT: it is ~270 MB per eval and calibration
            # scores CHRTOUT only.  A timestep longer than the run leaves just
            # the t0 file.
            out.append(f"OUTPUT_TIMESTEP  = {khour * 3600}")
        elif s.startswith("HRLDAS_SETUP_FILE"):
            out.append(line)
            out.append(f'RESTART_FILENAME_REQUESTED = "./{lsm_rst}"')
        else:
            out.append(line)
    (wd / "namelist.hrldas").write_text("\n".join(out) + "\n")

    src_y = (REF_RUN / "hydro.namelist").read_text()
    out = []
    for line in src_y.splitlines():
        s = line.strip()
        if s.startswith("RESTART_FILE"):
            out.append(f'RESTART_FILE = "./{hyd_rst}"')
        elif s.startswith("CHRTOUT_GRID"):
            out.append("CHRTOUT_GRID   = 0")
        elif s.startswith("RTOUT_DOMAIN"):
            out.append("RTOUT_DOMAIN   = 0")
        elif s.startswith("output_gw"):
            out.append("output_gw      = 0")
        elif s.startswith("rst_typ"):
            # KI FIX 2026-09-08 (ticket: rst_typ hard-coded 0 for every basin). rst_typ=0 does NOT
            # restore the fine-grid subsurface state from HYDRO_RST, so a chained/warm-started run
            # cannot reproduce a continuous one: measured 738 differing hours, max|dQ| 3.92 m3/s at
            # rst_typ=0 vs 744 h / max|dQ| 0.0 at rst_typ=1 (System 1 H03 discriminator; receipts in
            # outputs/system1_common_theta_work/h03_agent/rst_typ_test.json). SKILL.md's own humid
            # guidance is 1; the 0 was an arid-basin (dt_v036) workaround applied universally.
            # Declared per-case via env, humid default 1; the arid exception stays available.
            _rt = os.environ.get("KDT_WRFHYDRO_RST_TYP", "1").strip()
            if _rt not in ("0", "1"):
                die(f"KDT_WRFHYDRO_RST_TYP={_rt!r} must be 0 or 1 (1 = restore fine-grid state, "
                    "the humid default; 0 = the arid dt_v036 workaround)")
            out.append(f"rst_typ = {_rt}")
        elif s.startswith("GW_RESTART"):
            # 0 = bucket cold-starts at the candidate's Zinit, which is what
            # makes gw_zinit a real (screenable) parameter.  The 6-month spinup
            # ahead of every scoring window absorbs the transient.
            out.append("GW_RESTART = 0")
        else:
            out.append(line)
    (wd / "hydro.namelist").write_text("\n".join(out) + "\n")


# --------------------------------------------------------------------------
# Injection + read-back
# --------------------------------------------------------------------------
def _nc_open(path):
    import netCDF4 as nc
    return nc.Dataset(str(path), "r+")


def apply_params(wd, values):
    """Write every parameter into the artifact the model consumes.

    CHANPARM.TBL is NOT written here: run_wrfhydro.setup_symlinks() replaces
    every *.TBL in the run dir with a symlink to the shared model Run/ table,
    which would silently discard the injection.  It is written after that step
    (see main), and the shared table is never modified.
    """
    dom = wd / "DOMAIN"
    base = {}
    by_file = {}
    for name, val in values.items():
        spec = PARAMS[name]
        by_file.setdefault(spec["file"], []).append((name, val, spec))

    for fname, items in by_file.items():
        if fname.endswith(".TBL"):
            # Tables are written by write_tables() AFTER setup_symlinks copies them in —
            # anything written here would be overwritten from the source tree.
            for name, val, spec in items:
                nc_side = spec.get("also_nc")
                if nc_side:                      # F2: the routing's copy of the same soil
                    ds2 = _nc_open(dom / nc_side["file"])
                    try:
                        for var in nc_side["vars"]:
                            v2 = ds2.variables[var]
                            ref = np.asarray(_read_original(nc_side["file"], var), dtype=np.float64)
                            mask = (ref > 0) & (ref < nc_side["skip_above"])   # land, non-zero
                            base[(name, var)] = (ref, mask)
                            v2[:] = np.where(mask, ref * float(val), ref)
                    finally:
                        ds2.close()
            continue
        ds = _nc_open(dom / fname)
        try:
            for name, val, spec in items:
                v = ds.variables[spec["var"]]
                arr = np.asarray(v[:], dtype=np.float64)
                if spec["kind"] == "nc_uniform":
                    arr[...] = float(val)
                elif spec["kind"] == "nc_scale":
                    ref = np.asarray(
                        _read_original(fname, spec["var"]), dtype=np.float64)
                    mask = ref < spec["skip_above"]
                    base[name] = (ref, mask)
                    arr = np.where(mask, ref * float(val), ref)
                else:
                    die(f"unknown kind for {name}")
                v[:] = arr
        finally:
            ds.close()
    return base


_ORIG_CACHE = {}


def _read_original(fname, var):
    """Pristine field from the reference DOMAIN — the denominator for
    multiplier-style parameters, so scaling is never applied twice."""
    key = (fname, var)
    if key not in _ORIG_CACHE:
        import netCDF4 as nc
        ds = nc.Dataset(str(REF_RUN / "DOMAIN" / fname), "r")
        _ORIG_CACHE[key] = np.asarray(ds.variables[var][:], dtype=np.float64)
        ds.close()
    return _ORIG_CACHE[key]


def parse_chanparm(path):
    """Return (header_lines, rows) where rows are [order, Bw, HLINK, ChSSlp, MannN]."""
    lines = Path(path).read_text().splitlines()
    header, rows = [], []
    for ln in lines:
        parts = [p.strip() for p in ln.split(",")]
        if len(parts) == 5 and parts[0].lstrip("-").isdigit():
            try:
                rows.append([int(parts[0])] + [float(x) for x in parts[1:]])
                continue
            except ValueError:
                pass
        header.append(ln)
    if not rows:
        die(f"could not parse any channel rows from {path}")
    return header, rows


def write_chanparm(dst, mult):
    """Scale MannN on every Strahler order by `mult`, relative to the shared
    model table (never modified in place)."""
    src = Path(os.environ.get("WRFHYDRO_TBL_DIR", DEFAULT_TBL_DIR)) / "CHANPARM.TBL"
    header, rows = parse_chanparm(src)
    out = list(header)
    for r in rows:
        out.append(f"{r[0]},{r[1]:.6f},{r[2]:.6f},{r[3]:.6f},{r[4]*mult:.8f}")
    Path(dst).write_text("\n".join(out) + "\n")


# --------------------------------------------------------------------------
# Table writers (dt_v043 / dt_v045). MUST run after run_wrfhydro.setup_symlinks(), which copies
# the tables into the run dir; before it, there is nothing here to write (and previously, a
# symlink to the SHARED source tree, which a write would have corrupted for every concurrent
# evaluation). The ordering is enforced by _assert_run_dir_table(), not by a comment.
# --------------------------------------------------------------------------
_SOILPARM_COLS = ["BB", "DRYSMC", "F11", "MAXSMC", "REFSMC", "SATPSI", "SATDK", "SATDW", "WLTSMC", "QTZ"]


def _assert_run_dir_table(path):
    p = Path(path)
    if not p.exists():
        die(f"{p.name}: not present in the run dir — write_tables() was called before "
            f"setup_symlinks() copied it in")
    if p.is_symlink():
        die(f"{p.name}: is a SYMLINK to {p.resolve()} — writing it would corrupt the shared "
            f"source tree for every concurrent evaluation (dt_v043 containment)")


def parse_genparm(path):
    """GENPARM.TBL is NAME_DATA lines each followed by one value, except SLOPE_DATA which is
    followed by a count line and that many values. Returns (lines, {name: [line indices]})."""
    lines = Path(path).read_text().splitlines()
    idx = {}
    i = 0
    while i < len(lines):
        tok = lines[i].strip()
        if tok.endswith("_DATA"):
            if tok == "SLOPE_DATA":
                n = int(lines[i + 1].strip())
                idx[tok] = list(range(i + 2, i + 2 + n))
                i += 2 + n
                continue
            idx[tok] = [i + 1]
            i += 2
            continue
        i += 1
    return lines, idx


def write_genparm(path, values):
    """Write REFKDT_DATA and SLOPE_DATA[index] into the RUN-DIR GENPARM.TBL."""
    _assert_run_dir_table(path)
    lines, idx = parse_genparm(path)
    for name, val in values.items():
        spec = PARAMS[name]
        if spec["file"] != "GENPARM.TBL":
            continue
        if spec["kind"] == "genparm_scalar":
            lines[idx[spec["var"]][0]] = f"{float(val):.6g}"
        elif spec["kind"] == "genparm_slope":
            lines[idx[spec["var"]][spec["index"] - 1]] = f"{float(val):.6g}"
    Path(path).write_text("\n".join(lines) + "\n")


def parse_soilparm(path):
    """Return (lines, rows) where rows = [(line_no, class_id, [10 floats], name)] for every
    data row in every block (STAS and STAS-RUC both get scaled — the model reads whichever
    block matches SOIL_DATA)."""
    lines = Path(path).read_text().splitlines()
    rows = []
    for k, ln in enumerate(lines):
        parts = [x.strip() for x in ln.split(",")]
        if len(parts) >= 12 and parts[0].isdigit() and "'" in ln:
            try:
                rows.append((k, int(parts[0]), [float(x) for x in parts[1:11]], parts[-1]))
            except ValueError:
                continue
    return lines, rows


def write_soilparm(path, values):
    """Scale the retention set proportionally in the RUN-DIR SOILPARM.TBL (F2/F3)."""
    _assert_run_dir_table(path)
    lines, rows = parse_soilparm(path)
    src_lines, src_rows = parse_soilparm(
        Path(os.environ.get("WRFHYDRO_TBL_DIR", DEFAULT_TBL_DIR)) / "SOILPARM.TBL")
    src = {(k, cid): vals for k, cid, vals, _ in src_rows}
    for name, val in values.items():
        spec = PARAMS[name]
        if spec.get("kind") != "soilparm_retention_scale":
            continue
        m = float(val)
        for k, cid, vals, nm in rows:
            if cid in spec["skip_classes"]:
                continue
            orig = src.get((k, cid), vals)             # scale from the PRISTINE table, never twice
            new = list(orig)
            for col in spec["cols"]:
                j = _SOILPARM_COLS.index(col)
                new[j] = orig[j] * m
            # Scaled retention columns are written at 6 significant figures: the source table
            # keeps DRYSMC at 3 dp, so 0.006 x 0.9 = 0.0054 would round to 0.005 and read back
            # as x0.833 — the driver's own read-back caught this. Fortran list-directed input
            # does not care how many decimals we give it.
            lines[k] = (f"{cid},  {new[0]:.2f},  {new[1]:.6g},  {new[2]:.3f},  {new[3]:.6g},  "
                        f"{new[4]:.6g},  {new[5]:.3f},  {new[6]:.2E},  {new[7]:.2E},  "
                        f"{new[8]:.6g},  {new[9]:.2f},  {nm}")
    Path(path).write_text("\n".join(lines) + "\n")


def write_tables(wd, values):
    write_genparm(wd / "GENPARM.TBL", values)
    write_soilparm(wd / "SOILPARM.TBL", values)


def validate_soil_physics(wd, present_classes=None):
    """F3: after EVERY write, the soil must still make physical sense — cell-wise, at the
    address the model reads. Fails the run; never a warning. Checks:
      SOILPARM.TBL  DRYSMC <= WLTSMC <= REFSMC < MAXSMC for every class present in the domain
      hydro2dtbl.nc SMCWLT1 <= SMCREF1 < SMCMAX1 for every land cell
    A range that was 'checked' on whole-map maxima passed while 10.5% of cells were impossible;
    only a per-element check can see that."""
    bad = []
    _, rows = parse_soilparm(wd / "SOILPARM.TBL")
    for k, cid, v, nm in rows:
        if present_classes is not None and cid not in present_classes:
            continue
        if cid in (14, 16):
            continue
        dry, mx, ref, wlt = v[1], v[3], v[4], v[8]
        if not (dry <= wlt <= ref < mx):
            bad.append(f"SOILPARM.TBL class {cid} {nm}: DRY {dry} WLT {wlt} REF {ref} MAX {mx}")
    import netCDF4 as nc
    ds = nc.Dataset(str(wd / "DOMAIN" / "hydro2dtbl.nc"), "r")
    try:
        mx = np.asarray(ds.variables["SMCMAX1"][:], dtype=np.float64)
        ref = np.asarray(ds.variables["SMCREF1"][:], dtype=np.float64)
        wlt = np.asarray(ds.variables["SMCWLT1"][:], dtype=np.float64)
    finally:
        ds.close()
    land = mx < 0.9
    viol = land & ~((wlt <= ref) & (ref < mx))
    if viol.any():
        n = int(viol.sum())
        bad.append(f"hydro2dtbl.nc: {n}/{int(land.sum())} land cells violate WLT<=REF<MAX "
                   f"(worst REF {ref[viol].max():.4f} vs MAX {mx[viol].min():.4f})")
    if bad:
        die("soil physics violated after apply_params (dt_v045):\n  " + "\n  ".join(bad))
    return True


def domain_soil_classes(wd):
    """ISLTYP classes actually present, so the table check is scoped to what the run uses."""
    import netCDF4 as nc
    ds = nc.Dataset(str(wd / "DOMAIN" / "wrfinput_d01.nc"), "r")
    try:
        a = np.asarray(ds.variables["ISLTYP"][:]).astype(int).ravel()
    finally:
        ds.close()
    return set(int(x) for x in np.unique(a))


def read_back(wd, values, base):
    """Read each applied value back out of the artifact the model consumes."""
    dom = wd / "DOMAIN"
    applied = {}
    import netCDF4 as nc
    for name, val in values.items():
        spec = PARAMS[name]
        if spec["file"] == "CHANPARM.TBL":
            _, rows = parse_chanparm(wd / "CHANPARM.TBL")
            _, orows = parse_chanparm(
                Path(os.environ.get("WRFHYDRO_TBL_DIR", DEFAULT_TBL_DIR)) / "CHANPARM.TBL")
            ratios = [r[4] / o[4] for r, o in zip(rows, orows) if o[4] != 0]
            if not ratios:
                die("CHANPARM read-back found no usable MannN rows")
            if max(ratios) - min(ratios) > 1e-6:
                die(f"CHANPARM MannN scaled inconsistently across orders: {ratios}")
            applied[name] = float(np.mean(ratios))
            continue

        if spec["file"] == "GENPARM.TBL":
            lines, idx = parse_genparm(wd / "GENPARM.TBL")
            k = idx[spec["var"]][spec.get("index", 1) - 1]
            applied[name] = float(lines[k].strip())
            continue
        if spec.get("kind") == "soilparm_retention_scale":
            _, rows = parse_soilparm(wd / "SOILPARM.TBL")
            _, orows = parse_soilparm(
                Path(os.environ.get("WRFHYDRO_TBL_DIR", DEFAULT_TBL_DIR)) / "SOILPARM.TBL")
            src = {(k, cid): v for k, cid, v, _ in orows}
            ratios = []
            for k, cid, v, _ in rows:
                if cid in spec["skip_classes"] or (k, cid) not in src:
                    continue
                for col in spec["cols"]:
                    j = _SOILPARM_COLS.index(col)
                    if src[(k, cid)][j] != 0:
                        ratios.append(v[j] / src[(k, cid)][j])
            if not ratios:
                die(f"{name}: SOILPARM read-back found no usable rows")
            if max(ratios) - min(ratios) > 1e-3:      # table rows are printed to 4 dp
                die(f"{name}: SOILPARM retention scaled inconsistently: {min(ratios):.4f}..{max(ratios):.4f}")
            tbl = float(np.mean(ratios))
            # and the routing-side copy must carry the SAME factor (F2)
            nc_side = spec["also_nc"]
            ds2 = nc.Dataset(str(dom / nc_side["file"]), "r")
            try:
                r2 = []
                for var in nc_side["vars"]:
                    ref, mask = base[(name, var)]
                    arr = np.asarray(ds2.variables[var][:], dtype=np.float64)
                    r2.append(arr[mask] / ref[mask])
            finally:
                ds2.close()
            r2 = np.concatenate([x.ravel() for x in r2])
            if float(r2.max() - r2.min()) > 1e-4:
                die(f"{name}: hydro2dtbl retention scaled inconsistently")
            if abs(float(r2.mean()) - tbl) > 1e-3:
                die(f"{name}: land model ({tbl:.4f}) and routing ({float(r2.mean()):.4f}) disagree "
                    f"about the porosity factor — the F2 desync this fix exists to prevent")
            applied[name] = tbl
            continue

        ds = nc.Dataset(str(dom / spec["file"]), "r")
        try:
            arr = np.asarray(ds.variables[spec["var"]][:], dtype=np.float64)
        finally:
            ds.close()

        if spec["kind"] == "nc_uniform":
            u = np.unique(arr)
            if u.size != 1:
                die(f"{name}: expected a uniform field, found {u.size} distinct values")
            applied[name] = float(u[0])
        elif spec["kind"] == "nc_scale":
            ref, mask = base[name]
            if not mask.any():
                die(f"{name}: no cells eligible for scaling")
            ratios = arr[mask] / ref[mask]
            if float(ratios.max() - ratios.min()) > 1e-4:
                die(f"{name}: inconsistent scaling ratio across cells")
            applied[name] = float(np.mean(ratios))
    return applied


def verify(requested, applied):
    bad = []
    for k, want in requested.items():
        got = applied.get(k)
        if got is None:
            bad.append(f"{k}: not read back")
        elif not np.isclose(got, float(want), rtol=RTOL, atol=ATOL):
            bad.append(f"{k}: requested {want!r} but artifact holds {got!r}")
    if bad:
        die("parameter read-back mismatch (injection did not reach the model):\n  "
            + "\n  ".join(bad))


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------
def load_obs():
    """china_gaugeflux tab-separated gauge file.  -99 is the missing marker;
    Q == 0 is a REAL low-flow value on this intermittent gauge, so the filter is
    > -90, not > 0."""
    import pandas as pd
    if not OBS_FILE.exists():
        die(f"obs file missing: {OBS_FILE}")
    df = pd.read_csv(OBS_FILE, sep="\t", encoding="utf-8", encoding_errors="replace")
    stcds = set(str(int(s)) for s in df["stcd"].dropna().unique())
    if GAUGE_STCD not in stcds:
        die(f"{OBS_FILE} does not contain the target gauge stcd {GAUGE_STCD} "
            f"(found {sorted(stcds)})")
    df = df[df["stcd"].astype("Int64").astype(str) == GAUGE_STCD]
    df["date"] = pd.to_datetime(df["dates"])
    df = df.set_index("date")[["Q"]].astype(float)
    df = df[df["Q"] > -90.0]
    return df.rename(columns={"Q": "Q_obs"})


def score(wd, split, extract_discharge, all_metrics):
    """Extract at the gauge-matched feature through the KI tool, then score."""
    idx = extract_discharge.find_gauge_feature(
        wd, GAUGE_LAT, GAUGE_LON, min_order=MIN_ORDER)

    import netCDF4 as nc
    files = sorted(Path(wd).glob("*.CHRTOUT_DOMAIN1"))
    if not files:
        die("no CHRTOUT_DOMAIN1 produced by the run")
    ds = nc.Dataset(str(files[len(files) // 2]), "r")
    cell_lat = float(np.asarray(ds.variables["latitude"][:]).ravel()[idx])
    cell_lon = float(np.asarray(ds.variables["longitude"][:]).ravel()[idx])
    cell_order = int(np.asarray(ds.variables["order"][:]).ravel()[idx])
    ds.close()

    # Guard: the scored cell must be the one the validated run scored.  If a
    # candidate's parameters dried the channel and the flow guard moved the
    # match elsewhere, the eval is not comparable -> fail closed.
    if (abs(cell_lat - REF_CELL_LAT) > REF_CELL_TOL_DEG
            or abs(cell_lon - REF_CELL_LON) > REF_CELL_TOL_DEG):
        die(f"gauge match moved to {cell_lat:.4f}N/{cell_lon:.4f}E, expected "
            f"{REF_CELL_LAT}N/{REF_CELL_LON}E — not the validated Wangjiaba cell")

    daily = extract_discharge.extract_daily_discharge(wd, idx)
    obs = load_obs()
    merged = obs.join(daily, how="inner").dropna()
    merged = merged.loc[split["start"]:split["end"]]
    if len(merged) < 365:
        die(f"only {len(merged)} scoreable days in "
            f"{split['start']}..{split['end']} — refusing to score")

    m = all_metrics(merged["Q_obs"].values, merged["Q_sim"].values)
    if not np.isfinite(m.get("NSE", np.nan)):
        die("NSE is not finite")

    scored_obs = (f"{OBS_DATASET}:{GAUGE_STCD} ({GAUGE_NAME}) "
                  f"{OBS_FILE} @ {GAUGE_LAT}N/{GAUGE_LON}E -> CHRTOUT feature "
                  f"idx={idx} order={cell_order} {cell_lat:.4f}N/{cell_lon:.4f}E; "
                  f"{split['start']}..{split['end']} n={len(merged)}")
    return m, scored_obs, len(merged), merged, idx


def check_build_matches_registry(exe):
    """PARAMS writes the soil parameters (REFKDT, SLOPE, SMCMAX ...) into the
    TABLES, the live address only on a build WITHOUT -DSPATIAL_SOIL. A build
    with SPATIAL_SOIL reads them from soil_properties.nc instead, so a table
    write would be read back fine and never used. Stop before staging unless the
    selected executable's sha256 is in wrfhydro_builds.json with spatial_soil
    false (unknown -> stop too)."""
    import importlib.util as _ilu
    _spec = _ilu.spec_from_file_location(
        "_calibrate_wrfhydro", TOOLS / "s10_execution" / "calibrate_wrfhydro.py")
    _cw = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_cw)
    spatial = _cw.spatial_soil_compiled(exe)
    if spatial is not False:
        die(f"WRFHYDRO_EXE={exe}: "
            + ("built WITH -DSPATIAL_SOIL" if spatial else
               "it has no entry in the build record, so its SPATIAL_SOIL setting is unknown. "
               + _cw.build_record_help())
            + "; this driver writes REFKDT/SLOPE/SMCMAX to GENPARM.TBL/SOILPARM.TBL, which such a "
              "build does not read for these parameters. Use a build without SPATIAL_SOIL, or "
              "calibrate through soil_properties.nc addresses (not supported here)")


def load_target_proof():
    """ki_tools_common.kdt_proof.target_proof, or stop. Called once BEFORE the model
    is launched, so a missing shared module fails fast instead of after a full
    simulation, when the metrics could no longer be written."""
    try:
        from ki_tools_common.kdt_proof import target_proof as _tp
    except ImportError as exc:
        die(f"ki_tools_common.kdt_proof.target_proof is not importable ({exc}); the "
            f"calibration result needs it, so the model is not launched")
    return _tp


def target_proof(merged, split_name, split, feature_idx):
    """kdt-target-proof/1 via the SHARED implementation (ki_tools_common.kdt_proof) — the raw
    scored series, so the kit can prove consumption without the rounded metrics. One
    implementation for every KI; this driver was the reference port (2026-09-14)."""
    _tp = load_target_proof()
    return _tp(merged["Q_sim"].values, merged.index, target="streamflow", unit="m3/s",
               split=split_name, window=(split["start"], split["end"]),
               source=(f"CHRTOUT feature idx={feature_idx}, extract_discharge.extract_daily_discharge, "
                       f"inner-joined to obs, sliced to the split window"))


# --------------------------------------------------------------------------
DEFAULT_TBL_DIR = os.path.join(
    os.environ.get("HYDROCRAFT_ROOT", "KISSPATH_ROOT"),
    "model/wrf_hydro/source/trunk/NDHMS/Run")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--nproc", type=int,
                    default=int(os.environ.get("KDT_CALIB_NPROC", "8")))
    ap.add_argument("--timeout", type=int,
                    default=int(os.environ.get("KDT_CALIB_TIMEOUT", "7200")))
    args = ap.parse_args()

    wd = Path(args.workdir).resolve()
    out = Path(args.out)

    split_name = os.environ.get("KDT_CALIB_SPLIT", "calibration").strip().lower()
    if split_name not in SPLITS:
        die(f"KDT_CALIB_SPLIT={split_name!r} is not one of {sorted(SPLITS)}")
    split = SPLITS[split_name]

    # ---- candidate vector -------------------------------------------------
    requested = {}
    pfile = os.environ.get("KDT_CALIB_PARAMS")
    if pfile:
        if not Path(pfile).exists():
            die(f"KDT_CALIB_PARAMS points at a missing file: {pfile}")
        requested = json.loads(Path(pfile).read_text())
    unknown = set(requested) - set(PARAMS)
    if unknown:
        die(f"unknown parameter(s) in KDT_CALIB_PARAMS: {sorted(unknown)}")

    # Every registered parameter is applied, so the run is fully determined;
    # frozen/absent ones take their default.
    values = {k: float(requested.get(k, PARAMS[k]["default"])) for k in PARAMS}

    run_wrfhydro, extract_discharge = load_ki_tools()
    all_metrics = load_all_metrics()
    load_target_proof()          # fail before the model run, not after it
    check_build_matches_registry(os.environ.get("WRFHYDRO_EXE", str(run_wrfhydro.DEFAULT_WRF_HYDRO_EXE)))

    # ---- stage + inject ---------------------------------------------------
    lsm_rst, hyd_rst = stage_workdir(wd, split)
    write_namelists(wd, split, lsm_rst, hyd_rst)
    base = apply_params(wd, values)

    ok, msgs = run_wrfhydro.preflight_check(wd)
    if not ok:
        die("run_wrfhydro preflight failed:\n  " + "\n  ".join(msgs))

    # setup_symlinks re-links every *.TBL, so CHANPARM.TBL must be written after
    # it, and run_model() invoked directly rather than re-entering the CLI.
    tbl_dir = os.environ.get("WRFHYDRO_TBL_DIR", DEFAULT_TBL_DIR)
    exe = os.environ.get("WRFHYDRO_EXE", str(run_wrfhydro.DEFAULT_WRF_HYDRO_EXE))
    mpirun = os.environ.get("WRFHYDRO_MPIRUN", str(run_wrfhydro.DEFAULT_MPIRUN))
    run_wrfhydro.setup_symlinks(wd, exe, tbl_dir)

    chanparm = wd / "CHANPARM.TBL"
    if chanparm.is_symlink():
        chanparm.unlink()
    write_chanparm(chanparm, values["mann_n_mult"])
    # dt_v043: GENPARM/SOILPARM are the LIVE soil addresses on this build. Written here, after
    # setup_symlinks has copied real files in; _assert_run_dir_table() dies if that order is wrong.
    write_tables(wd, values)

    # ---- read back BEFORE running; a value that did not land never runs ----
    applied = read_back(wd, values, base)
    verify(values, applied)
    # ---- dt_v045: and the soil must still be PHYSICAL, cell-wise, at the live address ----
    validate_soil_physics(wd, present_classes=domain_soil_classes(wd))

    # ---- run --------------------------------------------------------------
    res = run_wrfhydro.run_model(wd, mpirun, args.nproc, args.timeout)
    if not res.get("success"):
        die(f"WRF-Hydro did not finish (rc={res.get('returncode')}, "
            f"{res.get('elapsed_s')}s): {res.get('diag_last_lines')}")

    # ---- score ------------------------------------------------------------
    m, scored_obs, n, merged, feat_idx = score(wd, split, extract_discharge, all_metrics)

    payload = {
        "nse": float(m["NSE"]),
        "kge": float(m["KGE"]),
        "pbias": float(m["PBIAS"]),
        "r": float(m["r"]),
        "rmse": float(m["RMSE"]),
        "__kdt__": {
            # Echo EVERY key handed to us (including any frozen at default in a
            # staged round), reporting the value actually read back out of the
            # model's own inputs.
            "applied_params": {k: applied[k] for k in requested} if requested
                              else {k: applied[k] for k in PARAMS},
            "case_id": CASE_ID,
            # Derived from the same variables used to read the obs and pick the
            # model cell, so the declaration cannot diverge from what was scored.
            "scored_obs": scored_obs,
            "split": split_name,
            "n_days": n,
            "elapsed_s": res.get("elapsed_s"),
            # kit gap fix: the raw scored series, one record per target
            "target_proofs": [target_proof(merged, split_name, split, feat_idx)],
        },
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2))
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        sys.exit(1)
