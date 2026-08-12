#!/usr/bin/env python3
"""
config_writer.py — S5 + S6: write PIHM `.para`, `.calib`, `.lsm` and `.lai`.

SKILL.md lists S5 (parameter configuration) and S6 (initial conditions) as
"Manual / PIHMgis", i.e. with no headless tool. This module closes that gap so
the whole S1..S8 chain can run without the GUI, and encodes the reader
conventions that MM-PIHM enforces:

* `.para`  — SIMULATION_MODE 1 = spin-up, 0 = normal; INIT_MODE 1 consumes the
  `.ic` written by a previous run (WRITE_IC 1). Output intervals are keywords
  (YEARLY/MONTHLY/DAILY/HOURLY) or positive seconds; 0 disables (dt_014).
* `.calib` — every entry is a MULTIPLIER on the corresponding soil/river/veg
  property, NOT an absolute value (dt_011). PRCP is a multiplier and SFCTMP is
  an OFFSET in K.
* `.lsm`   — Flux-PIHM (Noah) needs LATITUDE/LONGITUDE and NSOIL soil layer
  thicknesses; SLDPTH_DATA must have exactly NSOIL entries.
* `.lai`   — `LAI_TS <index>` block plus a TIME/LAI header, monthly series.
  Column layout is dictated by this tree's `src/read_lai.c`, NOT by the older
  PIHM v2.x manuals — see write_lai() for the reader trace and for the opt-in
  legacy RL column.

Every block written here is re-read before the tool reports success
(verify_lai below), because the MM-PIHM readers abort with ERR_WRONG_FORMAT
rather than warn: a bad header costs a whole model launch to discover.

Usage:
    python config_writer.py --out-dir input/Chiuni --project Chiuni \\
        --lat 42.177 --lon 8.612 --start 2015-01-01 --end 2021-08-01 \\
        --mode normal --lai-monthly 1.4,1.5,1.9,2.3,2.5,2.4,2.1,1.9,1.9,1.8,1.6,1.4
"""

import argparse
import io
import json
import os
from datetime import datetime

# Order matters: MM-PIHM's ReadCalib matches keywords, but keeping the shipped
# ShaleHills ordering makes diffs against the reference deck readable.
CALIB_KEYS = [
    "KSATH", "KSATV", "KINF", "KMACSATH", "KMACSATV", "DROOT", "DMAC",
    "POROSITY", "ALPHA", "BETA", "MACVF", "MACHF", "VEGFRAC", "ALBEDO",
    "ROUGH", "ROUGH_RIV", "KRIVH", "RIV_DPTH", "RIV_WDTH",
]
LSM_CALIB = {"DRIP": 1.0, "CMCMAX": 1.0, "RS": 1.0, "CZIL": 1.0, "FXEXP": 1.0,
             "CFACTR": 1.0, "RGL": 1.0, "HS": 1.0, "REFSMC": 0.95,
             "WLTSMC": 1.0}
OUTPUT_VARS = ["SURF", "UNSAT", "GW", "RIVSTG", "SNOW", "CMC", "INFIL",
               "RECHARGE", "EC", "ETT", "EDIR", "RIVFLX0", "RIVFLX1",
               "RIVFLX2", "RIVFLX3", "RIVFLX4", "RIVFLX5", "SUBFLX",
               "SURFFLX"]
# Noah 10-layer thicknesses used by the shipped ShaleHills/Chimborazo decks
SLDPTH_10 = [0.107, 0.123, 0.142, 0.165, 0.192, 0.223, 0.260, 0.301, 0.350,
             0.377]


def write_para(path, start, end, mode="normal", interval="DAILY",
               model_stepsize=60, lsm_step=900, abstol=1e-4, reltol=1e-3,
               max_spinup_year=50, write_ic=1, init_mode=0):
    sim_mode = 1 if mode == "spinup" else 0
    with open(path, "w") as f:
        f.write("SIMULATION_MODE\t%d\t\t# 1 = spinup, 0 = normal\n" % sim_mode)
        f.write("INIT_MODE\t%d\t\t# 0 = relaxation, 1 = use .ic file\n" % init_mode)
        f.write("ASCII_OUTPUT\t0\n")
        f.write("WATBAL_OUTPUT\t1\n")
        f.write("WRITE_IC\t%d\n" % write_ic)
        f.write("START\t\t%s\n" % start)
        f.write("END\t\t%s\n" % end)
        f.write("MAX_SPINUP_YEAR\t%d\n" % max_spinup_year)
        f.write("MODEL_STEPSIZE\t%d\n" % model_stepsize)
        f.write("LSM_STEP\t%d\n" % lsm_step)
        f.write("ABSTOL\t\t%g\n" % abstol)
        f.write("RELTOL\t\t%g\n" % reltol)
        f.write("INIT_SOLVER_STEP\t5E-5\n")
        f.write("NUM_NONCOV_FAIL\t0.0\n")
        f.write("MAX_NONLIN_ITER\t3.0\n")
        f.write("MIN_NONLIN_ITER\t1.0\n")
        f.write("DECR_FACTOR\t1.2\n")
        f.write("INCR_FACTOR\t1.2\n")
        f.write("MIN_MAXSTEP\t1.0\n")
        for v in OUTPUT_VARS:
            f.write("%s\t\t%s\n" % (v, interval))
        f.write("IC\t\tMONTHLY\n")


def write_calib(path, overrides=None, prcp=1.0, sfctmp=0.0):
    """All values are MULTIPLIERS (dt_011); SFCTMP is an offset in K."""
    vals = {k: 1.0 for k in CALIB_KEYS}
    vals.update({k.upper(): float(v) for k, v in (overrides or {}).items()
                 if k.upper() in vals})
    lsm = dict(LSM_CALIB)
    lsm.update({k.upper(): float(v) for k, v in (overrides or {}).items()
                if k.upper() in lsm})
    with open(path, "w") as f:
        for k in CALIB_KEYS:
            f.write("%s\t%g\n" % (k, vals[k]))
        f.write("\nLSM_CALIBRATION\n")
        for k, v in lsm.items():
            f.write("%s\t%g\n" % (k, v))
        f.write("\nBGC_CALIBRATION\nMORTALITY\t9.0\nSLA\t1.0\n")
        f.write("\nSCENARIO\n")
        f.write("PRCP\t%g\t# precipitation multiplier\n" % prcp)
        f.write("SFCTMP\t%g\t# temperature offset (K)\n" % sfctmp)


def mesh_max_soil_depth(mesh_path):
    """Max element soil-column depth (m) in a PIHM .mesh, or None.

    src/init_topo.c:26-27 sets topo.zmin/topo.zmax to the MEAN of the three
    node values, so the per-element depth the solver sees is
    mean(ZMAX) - mean(ZMIN), not a per-node difference.  That element depth is
    handed to DefineSoilDepths() (src/noah/lsm_func.c:79), which appends an
    extra Noah layer whenever it exceeds sum(SLDPTH_DATA).  ZBOT must sit below
    the resulting column -- see write_lsm().
    """
    try:
        lines = io.open(mesh_path, encoding='utf-8').read().split('\n')
    except (IOError, OSError):
        return None

    def _rows(start, n, ncol):
        out, k = [], start
        while len(out) < n and k < len(lines):
            tok = lines[k].split()
            k += 1
            if not tok or tok[0].lstrip('-').startswith('#'):
                continue
            try:
                vals = [float(t) for t in tok[:ncol]]
            except ValueError:
                continue
            if len(vals) == ncol:
                out.append(vals)
        return out

    try:
        nelem = int(lines[0].split()[1])
    except (IndexError, ValueError):
        return None
    elems = _rows(1, nelem, 4)
    j = 1 + nelem
    while j < len(lines) and 'NUMNODE' not in lines[j].upper():
        j += 1
    if j >= len(lines):
        return None
    try:
        nnode = int(lines[j].split()[1])
    except (IndexError, ValueError):
        return None
    nodes = _rows(j + 1, nnode, 5)
    if len(elems) != nelem or len(nodes) != nnode:
        return None

    zmin = [r[3] for r in nodes]
    zmax = [r[4] for r in nodes]
    best = None
    for e in elems:
        idx = [int(e[1]) - 1, int(e[2]) - 1, int(e[3]) - 1]
        if min(idx) < 0 or max(idx) >= nnode:
            return None
        d = (sum(zmax[i] for i in idx) - sum(zmin[i] for i in idx)) / 3.0
        if best is None or d > best:
            best = d
    return best


def zbot_for_depth(max_soil_depth_m):
    """Noah lower thermal boundary (m, negative) for a given soil-column depth.

    src/noah/noah.c:1024 computes the bottom-layer gradient denominator as
        denom = 0.5 * (zsoil[n-2] + zsoil[n-1]) - zbot
    so |zbot| MUST exceed the mid-depth of the bottom layer, otherwise denom
    goes negative, dtsdz2 flips sign and the geothermal term becomes an
    anti-diffusive source -- the soil column then diverges exponentially
    (ChiuniFR 2026-08-02: 15 m aquifer against a fixed -8.0 m ZBOT gave
    denom = -0.620 m and stc0 -> 1.05e15 K).  TBnd (src/noah/noah.c:2047)
    inverts for the same reason.  Placing the boundary a half-column below the
    deepest layer keeps denom positive and preserves the ~3.5x column-to-
    boundary ratio of the shipped ShaleHills deck (2.240 m column, -8.0 m).
    """
    if not max_soil_depth_m or max_soil_depth_m <= 0:
        return -8.0
    return -round(max(8.0, 1.5 * float(max_soil_depth_m)), 1)


def write_lsm(path, lat, lon, tbot_k=288.15, interval="DAILY",
              sldpth=None, max_soil_depth_m=None, zbot=None):
    sldpth = sldpth or SLDPTH_10
    if zbot is None:
        zbot = zbot_for_depth(max_soil_depth_m)
    with open(path, "w") as f:
        f.write("LATITUDE\t%.5f\n" % lat)
        f.write("LONGITUDE\t%.5f\n" % lon)
        f.write("NSOIL\t\t%d\n" % len(sldpth))
        f.write("SLDPTH_DATA\t" + "\t".join("%.3f" % d for d in sldpth) + "\n")
        f.write("RAD_MODE_DATA\t0\n")
        f.write("SBETA_DATA\t-2.0\nFXEXP_DATA\t2.0\nCSOIL_DATA\t2E6\n")
        f.write("SALP_DATA\t2.6\nFRZK_DATA\t0.15\n")
        f.write("ZBOT_DATA\t%.1f\n" % zbot)
        f.write("TBOT_DATA\t%.2f\n" % tbot_k)
        f.write("CZIL_DATA\t0.05\nLVCOEF_DATA\t0.5\n")
        for v in ["T1", "STC", "SMC", "SH2O", "SNOWH", "ALBEDO", "LE", "SH",
                  "G", "ETP", "ESNOW", "ROOTW", "SOILM", "SOLAR", "CH"]:
            f.write("%s\t\t%s\n" % (v, interval))


def verify_lai(path):
    """Re-read an emitted `.lai` the way src/read_lai.c does, and raise on any
    mismatch.

    ReadLai() calls pihm_error(ERROR, ERR_WRONG_FORMAT) — it aborts the run, it
    does not warn — so a malformed block is only discovered after a full model
    launch. The checks below mirror the reader step for step:

      FindLine(BOF); CountOccurr(fp, "LAI_TS")        -> >= 1 block
      ReadKeyword(cmdstr, "LAI_TS", 'i', ...)         -> integer index
      if (i != index - 1) -> ERR_WRONG_FORMAT         -> blocks numbered 1..n
      CheckHeader(cmdstr, 2, "TIME", "LAI")           -> first 2 tokens
      ReadTs(cmdstr, 1, &ftime, &data[0])             -> "date time" + 1 float

    Blank lines and lines whose first non-space character is '#' are invisible
    to the reader (NonBlank/NextLine in src/custom_io.c), so they are dropped
    here too — that is what makes the `#TS  m2/m2` unit line legal.
    """
    with open(path) as f:
        lines = [ln.strip() for ln in f]
    lines = [ln for ln in lines if ln and not ln.lstrip().startswith("#")]
    if not lines:
        raise ValueError("%s: no LAI_TS block (ReadLai would find nlai=0)" % path)

    blocks = [i for i, ln in enumerate(lines) if ln.split()[0].upper() == "LAI_TS"]
    if not blocks:
        raise ValueError("%s: missing 'LAI_TS <index>' keyword line" % path)

    for n, i in enumerate(blocks):
        tok = lines[i].split()
        if len(tok) < 2 or not tok[1].lstrip("+-").isdigit():
            raise ValueError("%s: 'LAI_TS' line %r has no integer index" % (path, lines[i]))
        if int(tok[1]) != n + 1:
            raise ValueError("%s: LAI_TS index %s out of order; ReadLai requires "
                             "1..n in order" % (path, tok[1]))
        if i + 1 >= len(lines):
            raise ValueError("%s: LAI_TS %d has no header line" % (path, n + 1))
        head = lines[i + 1].split()
        # CheckHeader compares only the first nvar tokens (src/read_func.c), so
        # trailing columns are tolerated but the first two are mandatory.
        if [t.upper() for t in head[:2]] != ["TIME", "LAI"]:
            raise ValueError("%s: header %r; ReadLai's CheckHeader(2, TIME, LAI) "
                             "would abort with ERR_WRONG_FORMAT" % (path, lines[i + 1]))
        end = blocks[n + 1] if n + 1 < len(blocks) else len(lines)
        rows = lines[i + 2:end]
        if not rows:
            raise ValueError("%s: LAI_TS %d has no data rows" % (path, n + 1))
        prev = None
        for row in rows:
            tok = row.split()
            # ReadTs: sscanf("%s %s") for the timestamp, then nvrbl=1 float.
            if len(tok) < 3:
                raise ValueError("%s: row %r is not 'YYYY-MM-DD HH:MM <LAI>'" % (path, row))
            try:
                t = datetime.strptime(tok[0] + " " + tok[1], "%Y-%m-%d %H:%M")
                float(tok[2])
            except ValueError:
                raise ValueError("%s: row %r fails ReadTs (StrTime + 1 value)" % (path, row))
            # IntrplForcing (src/forcing.c) binary-searches ftime[] and divides
            # by (ftime[m] - ftime[m-1]), so equal or decreasing timestamps give
            # a divide-by-zero or a silently wrong bracket, not an error.
            if prev is not None and t <= prev:
                raise ValueError("%s: timestamp %s does not increase; "
                                 "IntrplForcing needs a strictly increasing "
                                 "series" % (path, tok[0] + " " + tok[1]))
            prev = t
    return True


def write_lai(path, start_year, end_year, monthly, rl=None):
    """Write the `.lai` forcing block for LAI_TS index 1.

    Column layout comes from this tree's reader, src/read_lai.c:

        CheckHeader(cmdstr, 2, "TIME", "LAI");            // 2 columns
        ReadTs(cmdstr, 1, &forc->lai[i].ftime[j], &forc->lai[i].data[j][0]);

    i.e. MM-PIHM consumes exactly TIME and LAI. There is no RL (roughness
    length) column anywhere in this source tree — surface roughness reaches the
    elements through ROUGH in `.lc` (ReadLc, CheckHeader 16) scaled by the
    ROUGH multiplier in `.calib` — and all three shipped reference decks
    (input/ShaleHills, input/Chimborazo, input/Bengbu) are 2-column. So
    2 columns is the default and is what matches the shipped decks byte for
    byte.

    PIHM v2.x-era decks did carry a third RL column. Because CheckHeader
    compares only the first `nvar` tokens and ReadTs stops after `nvrbl`
    values, such a row is still read correctly by MM-PIHM (the RL value is
    simply ignored). `rl` therefore emits the legacy 3-column layout on
    request, for engines that require it, without changing the default.
    """
    if len(monthly) != 12:
        raise ValueError("monthly LAI must have 12 values")
    for m, v in enumerate(monthly):
        if not 0.0 <= float(v) <= 20.0:
            raise ValueError("monthly LAI[%d]=%r outside 0..20 m2/m2" % (m + 1, v))
    if end_year < start_year:
        raise ValueError("end_year %d precedes start_year %d" % (end_year, start_year))
    with open(path, "w") as f:
        f.write("LAI_TS\t\t1\n")
        if rl is None:
            f.write("TIME\t\t\tLAI\n")
            f.write("#TS\t\t\tm2/m2\n")
        else:
            f.write("TIME\t\t\tLAI\t\tRL\n")
            f.write("#TS\t\t\tm2/m2\t\tm\n")
        for y in range(start_year, end_year + 1):
            for m in range(12):
                f.write("%04d-%02d-01 00:00\t%.4f" % (y, m + 1, monthly[m]))
                f.write("\t%.4f\n" % rl if rl is not None else "\n")
    verify_lai(path)


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out-dir", required=True)
    p.add_argument("--project", required=True)
    p.add_argument("--lat", type=float, required=True)
    p.add_argument("--lon", type=float, required=True)
    p.add_argument("--start", required=True, help="YYYY-MM-DD")
    p.add_argument("--end", required=True, help="YYYY-MM-DD")
    p.add_argument("--mode", default="normal", choices=["normal", "spinup"])
    p.add_argument("--init-mode", type=int, default=0)
    p.add_argument("--interval", default="DAILY")
    p.add_argument("--abstol", type=float, default=1e-4)
    p.add_argument("--reltol", type=float, default=1e-3)
    p.add_argument("--max-spinup-year", type=int, default=50)
    p.add_argument("--tbot-k", type=float, default=288.15)
    p.add_argument("--zbot", type=float, default=None,
                   help="Noah lower thermal boundary (m, negative). "
                        "Default: derived from the .mesh soil depth "
                        "as -max(8.0, 1.5*depth); see zbot_for_depth().")
    p.add_argument("--lai-monthly", default="0.5,0.6,1.0,2.0,3.0,3.2,3.0,2.8,2.4,1.8,1.2,0.7")
    p.add_argument("--lai-rl", type=float, default=None,
                   help="Emit the legacy PIHM v2.x 'TIME LAI RL' layout with "
                        "this roughness length (m). Omit for the 2-column "
                        "'TIME LAI' block that src/read_lai.c defines and that "
                        "the shipped ShaleHills/Chimborazo/Bengbu decks use.")
    p.add_argument("--calib-json", default=None,
                   help="JSON dict of calibration multiplier overrides")
    p.add_argument("--prcp-mult", type=float, default=1.0)
    p.add_argument("--sfctmp-offset", type=float, default=0.0)
    a = p.parse_args()

    os.makedirs(a.out_dir, exist_ok=True)
    base = os.path.join(a.out_dir, a.project)
    s = datetime.strptime(a.start, "%Y-%m-%d")
    e = datetime.strptime(a.end, "%Y-%m-%d")
    ov = json.loads(a.calib_json) if a.calib_json else {}

    write_para(base + ".para", s.strftime("%Y-%m-%d %H:%M"),
               e.strftime("%Y-%m-%d %H:%M"), mode=a.mode,
               interval=a.interval, abstol=a.abstol, reltol=a.reltol,
               max_spinup_year=a.max_spinup_year, init_mode=a.init_mode)
    write_calib(base + ".calib", ov, a.prcp_mult, a.sfctmp_offset)
    max_depth = mesh_max_soil_depth(base + ".mesh")
    zbot = a.zbot if a.zbot is not None else zbot_for_depth(max_depth)
    write_lsm(base + ".lsm", a.lat, a.lon, a.tbot_k, a.interval,
              max_soil_depth_m=max_depth, zbot=zbot)
    # One year of padding on each side: IntrplForcing exits the run outright
    # when t falls outside [ftime[0], ftime[length-1]], and the monthly stamps
    # sit on the 1st, so an unpadded series cannot bracket the whole run.
    write_lai(base + ".lai", s.year - 1, e.year + 1,
              [float(x) for x in a.lai_monthly.split(",")], rl=a.lai_rl)
    print(json.dumps({"status": "success",
                      "files": [base + ext for ext in
                                (".para", ".calib", ".lsm", ".lai")],
                      "lai_columns": ["TIME", "LAI"] if a.lai_rl is None
                                     else ["TIME", "LAI", "RL"],
                      "lai_verified_against": "src/read_lai.c ReadLai()",
                      "max_soil_depth_m": max_depth,
                      "zbot_m": zbot},
                     indent=2))


if __name__ == "__main__":
    main()
