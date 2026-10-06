#!/usr/bin/env python3
"""
run_lpjguess_engine.py -- drive the REAL LPJ-GUESS 4.1.1 engine (`guess`)
headless. (tools/run_lpjguess.py is a Python SURROGATE, not this engine.)

Two modes, both COPY the shipped instruction files (src/data/ins/*.ins) into
a fresh workspace and only edit specific values -- nothing is generated from
scratch:

  example  Official demo: global_demo.ins, `-input demo`, 13 cells of the
           shipped Cramer-Leemans climate + LPJ soil codes. The output is
           compared number-by-number with the reference run made at build time
           (default <engine>/run_global_demo, 19 .out files). The reference
           must be COMPLETE: the directory must exist and hold every annual
           table the demo writes, and the run and the reference must have the
           SAME set of .out files; otherwise exit 5. Any value difference above
           --tolerance -> exit 5. Only `--reference_dir ''` skips the check, and
           then the JSON says "reproduced": false (an install check, not a
           reproduction).

  cf       Site / grid run with `-input cf`: copies global_cf.ins to
           site_cf.ins, points its file_* params at the NetCDF files listed in
           forcing_meta.json (tools/build_lpjguess_cf_forcing.py), the CO2 file
           (tools/build_lpjguess_co2_file.py) and the soil-code file, then
           appends override lines (later lines win in an .ins file):
           firemodel, nyear_spinup, npatch, monthly output files, --set lines.
           The soil-code file is copied and ONE line is added for the exact
           site coordinate, with the code of the 0.5-degree cell that holds it:
           4.1.1 has no working soil search for -input cf (setting
           searchradius_soil segfaults: CFInput() builds a throw-away local
           SoilInput that registers the parameter), so it is refused here.

Success = ALL of: exit code 0; guess.log has a "Finished" line and no line
starting "Error"; every expected .out file exists with rows; the last
simulated year is the same in all of them (cf: equals the forcing end year).
The engine's own fail() exits 99 and logs the reason in guess.log.

Exit codes: 0 ok, 2 bad input, 3 engine failed (rc != 0, timeout, no
"Finished", or an Error line), 4 outputs missing/incomplete, 5 example output
differs from the reference run.
The last stdout line is a JSON summary.

Usage:
  python run_lpjguess_engine.py example --out_dir /tmp/lpj_demo
  python run_lpjguess_engine.py cf --forcing_meta forcing/forcing_meta.json \
      --co2_file co2_1901_2014.txt --out_dir run_detha [--nyear_spinup 500]
"""
import argparse
import glob
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time

ENGINE_ROOT = os.environ.get("LPJGUESS_ENGINE_ROOT",
                             "KISSPATH_HOME/engine_builds_20261006/LPJ_GUESS")
BIN = os.environ.get("LPJGUESS_BIN", os.path.join(ENGINE_ROOT, "build", "guess"))
INS_DIR = os.path.join(ENGINE_ROOT, "src", "data", "ins")
ENV_DIR = os.path.join(ENGINE_ROOT, "src", "data", "env")
GRID_DIR = os.path.join(ENGINE_ROOT, "src", "data", "gridlist")
REF_DEMO = os.path.join(ENGINE_ROOT, "run_global_demo")

# Annual tables global.ins always writes (file_* set there).
ANNUAL_OUT = ["cmass.out", "anpp.out", "agpp.out", "fpc.out", "aaet.out", "lai.out",
              "cflux.out", "dens.out", "tot_runoff.out", "cpool.out"]
# Monthly tables the cf mode switches on (empty by default in global.ins).
MONTHLY_OUT = {"file_mgpp": "mgpp.out", "file_mnpp": "mnpp.out", "file_mra": "mra.out",
               "file_mrh": "mrh.out", "file_mnee": "mnee.out", "file_maet": "maet.out",
               "file_mevap": "mevap.out", "file_mintercep": "mintercep.out",
               "file_mrunoff": "mrunoff.out", "file_mlai": "mlai.out",
               "file_mpet": "mpet.out"}


def fail(msg, code, **extra):
    print(f"ERROR: {msg}", file=sys.stderr)
    print(json.dumps({"status": "failed", "exit_code": code, "error": msg, **extra}))
    return code


def new_workspace(out_dir, overwrite):
    run = os.path.join(os.path.abspath(out_dir), "run")
    if os.path.islink(out_dir) or os.path.islink(run):
        raise ValueError(f"refusing a symlinked run dir: {run}")
    if os.path.exists(run):
        if not overwrite:
            raise ValueError(f"{run} exists; pass --overwrite to replace it")
        shutil.rmtree(run)
    os.makedirs(run)
    for f in glob.glob(os.path.join(INS_DIR, "*.ins")):
        shutil.copy2(f, run)
    return run


def set_str_param(text, name, value):
    """Replace the value of an active (not `!`-commented) `param "<name>" (str "...")`
    line -- must match exactly once."""
    pat = re.compile(r'^(\s*param\s+"%s"\s+\(str\s+")[^"]*("\))' % re.escape(name), re.M)
    new, n = pat.subn(lambda m: m.group(1) + value + m.group(2), text)
    if n != 1:
        raise ValueError(f'param "{name}" found {n} times in the template (expected 1)')
    return new


def read_table(path):
    """LPJ-GUESS .out table -> (header list, list of row lists of str)."""
    with open(path) as f:
        lines = [ln.split() for ln in f if ln.strip()]
    return (lines[0], lines[1:]) if lines else ([], [])


def site_soil_file(src, run, lon, lat):
    """Copy the LPJ soil-code map and add the site's exact (lon, lat) with the code
    of the 0.5-degree cell holding it (the engine's own cell-centre rule)."""
    clon, clat = (int(lon * 2 // 1) / 2 + 0.25), (int(lat * 2 // 1) / 2 + 0.25)
    code = None
    with open(src) as f:
        lines = f.readlines()
    for ln in lines:
        s = ln.split()
        if len(s) == 3 and abs(float(s[0]) - clon) < 1e-6 and abs(float(s[1]) - clat) < 1e-6:
            code = s[2]
    if code is None:
        raise ValueError(f"cell ({clon}, {clat}) holding the site is not in {src}")
    dst = os.path.join(run, "soils_site.dat")
    with open(dst, "w") as f:
        f.writelines(lines)
        f.write(f"{lon!r} {lat!r} {code}\n")
    return dst, {"cell": [clon, clat], "soil_code": int(code)}


def run_engine(run, ins, module, timeout):
    t0 = time.time()
    try:
        p = subprocess.run([BIN, "-input", module, ins], cwd=run, capture_output=True,
                           text=True, timeout=timeout)
        rc, out = p.returncode, p.stdout + p.stderr
    except subprocess.TimeoutExpired as e:
        so = e.stdout or ""
        rc, out = -9, so.decode(errors="replace") if isinstance(so, bytes) else so
    with open(os.path.join(run, "guess_stdout.log"), "w") as f:
        f.write(out)
    return rc, round(time.time() - t0, 1)


def check_run(run, rc, expected_files, expected_last_year=None):
    """Return (exit_code, checks dict)."""
    log = os.path.join(run, "guess.log")
    text = open(log, errors="replace").read() if os.path.isfile(log) else ""
    errors = [ln.strip() for ln in text.splitlines() if ln.strip().startswith("Error")]
    checks = {"rc": rc, "finished_line": bool(re.search(r"^Finished\s*$", text, re.M)),
              "error_lines": errors[:5]}
    if rc != 0 or not checks["finished_line"] or errors:
        checks["log_tail"] = text.strip().splitlines()[-8:]
        return 3, checks
    last_years, missing = {}, []
    for fn in expected_files:
        p = os.path.join(run, fn)
        hdr, rows = read_table(p) if os.path.isfile(p) else ([], [])
        if not rows or "Year" not in hdr:
            missing.append(fn)
            continue
        yi = hdr.index("Year")
        last_years[fn] = max(int(r[yi]) for r in rows)
    checks.update(missing_or_empty=missing, last_year=sorted(set(last_years.values())))
    if missing or len(set(last_years.values())) != 1:
        return 4, checks
    if expected_last_year is not None and checks["last_year"][0] != expected_last_year:
        checks["expected_last_year"] = expected_last_year
        return 4, checks
    return 0, checks


def _cell_diff(a, b):
    """abs difference of two table cells. Non-numeric cells must match exactly; a numeric
    cell that is not finite (nan, inf) on either side is a failure (inf), never 0."""
    try:
        x, y = float(a), float(b)
    except ValueError:
        return 0.0 if a == b else float("inf")
    if not (math.isfinite(x) and math.isfinite(y)):
        return float("inf")
    return abs(x - y)


def compare_with_reference(run, ref):
    """Number-by-number comparison of the run's .out files with a COMPLETE reference set.
    Returns (worst, per-file result, problems); any problem means 'not reproduced'."""
    problems = []
    if not ref or not os.path.isdir(ref):
        return float("inf"), {}, [f"reference dir not found: {ref!r}"]
    ref_files = {os.path.basename(p) for p in glob.glob(os.path.join(ref, "*.out"))}
    run_files = {os.path.basename(p) for p in glob.glob(os.path.join(run, "*.out"))}
    if not ref_files:
        return float("inf"), {}, [f"reference dir has no .out files: {ref}"]
    lacking = sorted(set(ANNUAL_OUT) - ref_files)
    if lacking:
        problems.append(f"reference set incomplete, lacks {lacking}")
    if ref_files - run_files:
        problems.append(f"run lacks {sorted(ref_files - run_files)}")
    if run_files - ref_files:
        problems.append(f"reference lacks {sorted(run_files - ref_files)}")
    res, worst = {}, 0.0
    for fn in sorted(ref_files & run_files):
        p, q = os.path.join(ref, fn), os.path.join(run, fn)
        h1, r1 = read_table(p)
        h2, r2 = read_table(q)
        if not r1:
            res[fn] = "reference table empty"
            worst = float("inf")
            continue
        if h1 != h2 or len(r1) != len(r2) or any(len(x) != len(y) for x, y in zip(r1, r2)):
            res[fn] = f"shape differs ({len(r1)} vs {len(r2)} rows)"
            worst = float("inf")
            continue
        d = max((_cell_diff(a, b) for x, y in zip(r1, r2) for a, b in zip(x, y)), default=0.0)
        res[fn] = "identical" if open(p, "rb").read() == open(q, "rb").read() else f"max_abs_diff={d:g}"
        worst = max(worst, d)
    if problems:
        worst = float("inf")
    return worst, res, problems


def mode_example(a):
    run = new_workspace(a.out_dir, a.overwrite)
    for f in glob.glob(os.path.join(ENV_DIR, "*.grd")) + [os.path.join(ENV_DIR, "soils_lpj.dat")]:
        shutil.copy2(f, run)
    shutil.copy2(os.path.join(GRID_DIR, "gridlist_global.txt"), os.path.join(run, "gridlist.txt"))
    rc, wall = run_engine(run, "global_demo.ins", "demo", a.timeout)
    code, checks = check_run(run, rc, ANNUAL_OUT)
    summary = {"mode": "example", "run_dir": run, "binary": os.path.realpath(BIN),
               "wall_s": wall, "checks": checks}
    if code:
        return fail("engine run did not pass the success checks", code, **summary)
    if a.reference_dir:
        worst, res, problems = compare_with_reference(run, a.reference_dir)
        n_ident = sum(v == "identical" for v in res.values())
        summary.update(reference_dir=a.reference_dir, comparison=res,
                       files_compared=len(res), files_identical=n_ident,
                       max_abs_diff=None if worst == float("inf") else worst,
                       reference_problems=problems)
        if problems:
            return fail("reference comparison not possible: " + "; ".join(problems), 5,
                        reproduced=False, **summary)
        if worst > a.tolerance:
            return fail(f"output differs from reference (max abs diff {worst})", 5,
                        reproduced=False, **summary)
        summary["reproduced"] = True
    else:
        summary.update(reproduced=False,
                       comparison="skipped (--reference_dir ''): install check only, NOT a reproduction")
    print(json.dumps({"status": "success", "exit_code": 0, **summary}))
    return 0


def mode_cf(a):
    try:
        with open(a.forcing_meta) as f:
            meta = json.load(f)
        paths = [a.co2_file, a.soil_file, meta["gridlist"]] + \
            [v["file"] for v in meta["files"].values()]
        float(meta["lon"]), float(meta["lat"]), int(meta["end_year"])
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
        return fail(f"forcing_meta unreadable or incomplete ({a.forcing_meta}): {e!r}", 2)
    for p in paths:
        if not os.path.isfile(p):
            return fail(f"input file not found: {p}", 2)
    if any("searchradius_soil" in x for x in (a.set or [])):
        return fail("searchradius_soil crashes LPJ-GUESS 4.1.1 with -input cf (see triplets)", 2)
    run = new_workspace(a.out_dir, a.overwrite)
    soil, soil_info = site_soil_file(a.soil_file, run, float(meta["lon"]), float(meta["lat"]))
    text = open(os.path.join(run, "global_cf.ins")).read()
    files = meta["files"]
    try:
        text = set_str_param(text, "file_gridlist_cf", meta["gridlist"])
        text = set_str_param(text, "file_co2", os.path.abspath(a.co2_file))
        text = set_str_param(text, "file_ndep", a.ndep_file or "")
        text = set_str_param(text, "file_soildata", soil)
        text = set_str_param(text, "file_simfire", a.simfire_file or "")
        for v in ["temp", "prec", "insol", "wind", "relhum", "min_temp", "max_temp"]:
            text = set_str_param(text, f"file_{v}", files[v]["file"] if v in files else "")
            text = set_str_param(text, f"variable_{v}", files[v]["variable"] if v in files else "")
        for v in ["pres", "specifichum", "wetdays"]:   # daily input: not used
            text = set_str_param(text, f"file_{v}", "")
            text = set_str_param(text, f"variable_{v}", "")
    except (KeyError, ValueError) as e:
        return fail(f"could not edit global_cf.ins: {e}", 2)
    over = ["", "! ---- run_lpjguess_engine.py overrides (later lines win) ----",
            f'firemodel "{a.firemodel}"', f"nyear_spinup {a.nyear_spinup}"]
    if a.npatch:
        over.append(f"npatch {a.npatch}")
    over += [f'{k} "{v}"' for k, v in MONTHLY_OUT.items()]
    over += list(a.set or [])
    with open(os.path.join(run, "site_cf.ins"), "w") as f:
        f.write(text.rstrip("\n") + "\n" + "\n".join(over) + "\n")
    rc, wall = run_engine(run, "site_cf.ins", "cf", a.timeout)
    code, checks = check_run(run, rc, ANNUAL_OUT + list(MONTHLY_OUT.values()),
                             expected_last_year=int(meta["end_year"]))
    summary = {"mode": "cf", "run_dir": run, "binary": os.path.realpath(BIN), "wall_s": wall,
               "site": meta.get("site"), "forcing_source": meta.get("source"),
               "firemodel": a.firemodel, "nyear_spinup": a.nyear_spinup, "soil": soil_info,
               "checks": checks}
    if code:
        return fail("engine run did not pass the success checks", code, **summary)
    print(json.dumps({"status": "success", "exit_code": 0, **summary}))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="mode", required=True)
    for name in ("example", "cf"):
        s = sub.add_parser(name)
        s.add_argument("--out_dir", required=True)
        s.add_argument("--overwrite", action="store_true")
        s.add_argument("--timeout", type=int, default=7200, help="seconds")
    ex = sub.choices["example"]
    ex.add_argument("--reference_dir", default=REF_DEMO,
                    help="build-time demo run to compare against; must exist and be complete "
                         "(exit 5 otherwise). '' = skip, reported as reproduced=false")
    ex.add_argument("--tolerance", type=float, default=0.0,
                    help="max abs difference allowed in any .out value")
    cf = sub.choices["cf"]
    cf.add_argument("--forcing_meta", required=True)
    cf.add_argument("--co2_file", required=True)
    cf.add_argument("--soil_file", default=os.path.join(ENV_DIR, "soils_lpj.dat"),
                    help="LPJ soil-code file (lon lat code); default = shipped 0.5 deg map")
    cf.add_argument("--ndep_file", default="", help="Lamarque .bin; '' = constant pre-industrial")
    cf.add_argument("--simfire_file", default="", help="SimfireInput.bin, needed only for BLAZE")
    cf.add_argument("--firemodel", default="GLOBFIRM", choices=["GLOBFIRM", "BLAZE", "NOFIRE"])
    cf.add_argument("--nyear_spinup", type=int, default=500)
    cf.add_argument("--npatch", type=int, default=None)
    cf.add_argument("--set", action="append", help="extra raw .ins line, e.g. 'npatch 25'")
    a = ap.parse_args()

    if not (os.path.isfile(BIN) and os.access(BIN, os.X_OK)):
        return fail(f"engine binary not executable: {BIN} (see triplets)", 2)
    if a.mode == "cf" and a.firemodel == "BLAZE" and not a.simfire_file:
        return fail("BLAZE needs --simfire_file (SimfireInput.bin, not shipped)", 2)
    try:
        return mode_example(a) if a.mode == "example" else mode_cf(a)
    except ValueError as e:
        return fail(str(e), 2)


if __name__ == "__main__":
    sys.exit(main())
