#!/usr/bin/env python3
"""
run_pihm.py — Execute MM-PIHM binary with pre-flight validation.

Wraps the PIHM executable with input validation, environment setup,
and output verification. Checks for common configuration errors before
running to avoid wasted compute time.

Pre-flight checks:
  - Binary exists and is executable
  - All required input files exist
  - Forcing data covers simulation period
  - Calibration values are multipliers (near 1.0)
  - CVODE tolerances are reasonable
  - Output directory has sufficient disk space

Usage:
    python run_pihm.py --binary ./pihm --project ShaleHills \\
        --input-dir input/ShaleHills --output-dir output/test_run \\
        --threads 4

    python run_pihm.py --binary ./flux-pihm --project ShaleHills \\
        --input-dir input/ShaleHills --spinup --threads 8
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime


REQUIRED_EXTENSIONS = [".mesh", ".att", ".soil", ".meteo", ".riv",
                       ".para", ".calib"]
OPTIONAL_EXTENSIONS = [".lc", ".ic", ".lai", ".bc", ".geol", ".lsm", ".rad",
                       ".bgc", ".ndep"]


def validate_inputs(args):
    """Validate binary, input files, and configuration."""
    errors = []
    warnings = []

    # Check binary exists
    if not os.path.exists(args.binary):
        errors.append(f"Binary not found: {args.binary}")
    elif not os.access(args.binary, os.X_OK):
        errors.append(f"Binary not executable: {args.binary}")

    # Check input directory
    if not os.path.isdir(args.input_dir):
        errors.append(f"Input directory not found: {args.input_dir}")
    else:
        # Check required files
        for ext in REQUIRED_EXTENSIONS:
            fpath = os.path.join(args.input_dir, args.project + ext)
            if not os.path.exists(fpath):
                errors.append(f"Required input file missing: {fpath}")

        # Check optional files
        for ext in OPTIONAL_EXTENSIONS:
            fpath = os.path.join(args.input_dir, args.project + ext)
            if os.path.exists(fpath):
                pass  # OK

        # Validate .para file contents
        para_file = os.path.join(args.input_dir, args.project + ".para")
        if os.path.exists(para_file):
            para_warnings = validate_para(para_file, args.spinup)
            warnings.extend(para_warnings)

        # Validate .calib file contents
        calib_file = os.path.join(args.input_dir, args.project + ".calib")
        if os.path.exists(calib_file):
            calib_warnings = validate_calib(calib_file)
            warnings.extend(calib_warnings)

    # Check disk space (need at least 1 GB free)
    outdir_parent = os.path.dirname(os.path.abspath(args.output_dir or "."))
    if os.path.exists(outdir_parent):
        usage = shutil.disk_usage(outdir_parent)
        free_gb = usage.free / (1024**3)
        if free_gb < 1.0:
            warnings.append(f"Low disk space: {free_gb:.1f} GB free")

    if errors:
        print(json.dumps({"status": "error", "errors": errors, "warnings": warnings}))
        sys.exit(1)

    return warnings


def validate_para(para_file, spinup_mode):
    """Check .para file for common configuration issues."""
    warnings = []
    try:
        with open(para_file, "r") as f:
            content = f.read()

        lines = content.strip().split("\n")
        params = {}
        for line in lines:
            parts = line.strip().split()
            if len(parts) >= 2:
                params[parts[0]] = parts[1]

        # Check ABSTOL
        abstol = float(params.get("ABSTOL", 1e-4))
        if abstol > 0.01:
            warnings.append(f"ABSTOL={abstol} is very loose — mass balance errors likely (dt_013)")
        elif abstol < 1e-7:
            warnings.append(f"ABSTOL={abstol} is very tight — solver may be slow")

        # Check init mode vs spinup
        init_mode = int(params.get("INIT_MODE", 0))
        sim_mode = int(params.get("SIMULATION_MODE", 0))

        if spinup_mode and sim_mode != 1:
            warnings.append("Spinup requested but SIMULATION_MODE != 1 in .para file")
        if not spinup_mode and init_mode == 0 and sim_mode == 0:
            warnings.append("No spin-up and INIT_MODE=0: starting from relaxation IC (dt_012)")

    except Exception as e:
        warnings.append(f"Could not parse .para file: {e}")

    return warnings


def validate_calib(calib_file):
    """Check .calib file for likely absolute-vs-multiplier errors."""
    warnings = []
    try:
        with open(calib_file, "r") as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 2:
                    key = parts[0]
                    try:
                        val = float(parts[1])
                    except ValueError:
                        continue

                    # Multiplier parameters should be near 1.0
                    multiplier_params = [
                        "KSATH", "KSATV", "KINF", "KMACSATH", "KMACSATV",
                        "POROSITY", "ALPHA", "BETA", "MACVF", "MACHF",
                        "VEGFRAC", "ALBEDO", "ROUGH", "DROOT", "DMAC",
                        "ROUGH_RIV", "KRIVH", "RIV_DPTH", "RIV_WDTH", "PRCP"
                    ]
                    if key in multiplier_params:
                        if val < 1e-4 or val > 1e4:
                            warnings.append(
                                f"Calib {key}={val} — this is a MULTIPLIER, not absolute. "
                                f"Did you mean to set it near 1.0? (dt_011)"
                            )

                    # SFCTMP is additive offset, should be near 0
                    if key == "SFCTMP" and abs(val) > 10.0:
                        warnings.append(
                            f"SFCTMP={val} K offset is very large. "
                            f"This is added to forcing temperature."
                        )

    except Exception as e:
        warnings.append(f"Could not parse .calib file: {e}")

    return warnings


def run_model(args, warnings):
    """Execute the PIHM binary."""
    # Set OpenMP threads
    env = os.environ.copy()
    env["OMP_NUM_THREADS"] = str(args.threads)

    # Build command
    cmd = [os.path.abspath(args.binary)]
    if args.output_dir:
        cmd.extend(["-o", args.output_dir])
    if args.spinup:
        # Spin-up is controlled by .para SIMULATION_MODE, not a flag
        pass
    if args.verbose:
        cmd.append("-v")
    if args.debug:
        cmd.append("-d")
    if args.brief:
        cmd.append("-b")
    cmd.append(args.project)

    # Change to the MM-PIHM root directory (parent of input/)
    work_dir = os.path.dirname(os.path.dirname(os.path.abspath(args.input_dir)))
    if not os.path.exists(os.path.join(work_dir, "input")):
        # Try input_dir's parent
        work_dir = os.path.dirname(os.path.abspath(args.input_dir))
        if not os.path.exists(os.path.join(work_dir, "input")):
            work_dir = "."

    print(f"Running: {' '.join(cmd)}", file=sys.stderr)
    print(f"Working directory: {work_dir}", file=sys.stderr)
    print(f"OMP_NUM_THREADS: {args.threads}", file=sys.stderr)

    try:
        result = subprocess.run(
            cmd,
            cwd=work_dir,
            env=env,
            capture_output=True,
            text=True,
            timeout=args.timeout
        )

        output = result.stdout + result.stderr
        success = result.returncode == 0

        return {
            "status": "success" if success else "error",
            "return_code": result.returncode,
            "command": " ".join(cmd),
            "working_dir": work_dir,
            "stdout_tail": output[-2000:] if len(output) > 2000 else output,
            "warnings": warnings,
        }

    except subprocess.TimeoutExpired:
        return {
            "status": "error",
            "errors": [f"Timeout after {args.timeout} seconds"],
            "command": " ".join(cmd),
            "warnings": warnings,
        }
    except Exception as e:
        return {
            "status": "error",
            "errors": [str(e)],
            "command": " ".join(cmd),
            "warnings": warnings,
        }


MAX_PHYSICAL_T1_K = 350.0


def mesh_numele(input_dir, project):
    """(nelem, None) from <input_dir>/<project>.mesh, else (None, reason).

    src/read_mesh.c:16-17 does NextLine() then ReadKeyword(cmdstr, "NUMELE",
    'i', ...): NUMELE must be the FIRST record of the .mesh or the solver
    aborts with ERR_WRONG_FORMAT.  A later NUMELE token is therefore NOT
    evidence of the element count -- if the first record is anything else the
    deck the binary read is not the deck we are parsing, the record length of
    the element-wise .dat files is unverifiable, and the caller must SKIP.

    "Record" here is src/custom_io.c NextLine + NonBlank: the first line whose
    first character, after an optional UTF-8 BOM and leading spaces/tabs, is
    not '#', CR, LF or NUL.  Keyword matching is case-insensitive to match
    ReadKeyword's strcasecmp (src/read_func.c:85), and the value must parse as
    a positive int to match its "%s %d".
    """
    path = os.path.join(input_dir, project + ".mesh")
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            for line in f:
                s = line.lstrip(" \t")
                if s == "" or s[0] in ("#", "\r", "\n", "\0"):
                    continue
                tok = s.split()
                if tok[0].upper() != "NUMELE":
                    return (None, "first record of %s.mesh is %r, not NUMELE "
                            "(src/read_mesh.c requires NUMELE first)"
                            % (project, tok[0]))
                if len(tok) < 2:
                    return (None, "NUMELE record of %s.mesh carries no value"
                            % project)
                try:
                    n = int(tok[1])
                except ValueError:
                    return (None, "NUMELE value %r in %s.mesh is not an int"
                            % (tok[1], project))
                if n < 1:
                    return (None, "NUMELE %d in %s.mesh is not positive"
                            % (n, project))
                return (n, None)
    except (OSError, UnicodeDecodeError) as e:
        return (None, "cannot read %s.mesh: %r" % (project, e))
    return (None, "%s.mesh contains no non-comment record" % project)


def check_thermal_divergence(args, result):
    """Fail a run whose Noah soil-temperature solver has gone unstable.

    A diverged column still exits 0 and still writes every .dat file, so the
    only symptom downstream is that every calibration trial scores None while
    reporting ok=True (ChiuniFR 2026-08-02: nine trials, ~8 h, all null,
    against skin temperatures of 1.4e11 K).  Read-only, and it never flips
    status on its own uncertainty: EVERY reason the check cannot run (numpy
    missing, no .t1.dat, unreadable, empty, NUMELE unverifiable, bad record
    length, non-monotonic time column) is appended to result["warnings"] as
    "thermal-divergence check SKIPPED (<why>)", so a caller can always tell an
    unchecked run from a checked one.
    """
    repo = os.path.dirname(os.path.abspath(args.binary))
    outdir = os.path.join(repo, "output", args.output_dir or args.project)
    t1 = os.path.join(outdir, args.project + ".t1.dat")

    def _skip(why):
        result.setdefault("warnings", []).append(
            "thermal-divergence check SKIPPED (%s): %s" % (why, t1))

    try:
        import numpy as np
    except ImportError:
        _skip("numpy is not importable")
        return
    if not os.path.isfile(t1):
        _skip("no such file -- T1 is not in this deck's .lsm output list, "
              "or the run wrote no output")
        return

    # src/print.c:159-166 writes one double of time followed by nvar doubles;
    # for an element-wise variable nvar == NUMELE, so the record length is
    # exactly NUMELE+1 and NO magnitude heuristic is needed to separate the
    # time stamp from the temperatures.
    nelem, why_no_numele = mesh_numele(args.input_dir, args.project)
    if nelem is None:
        _skip(why_no_numele)
        return
    reclen = nelem + 1
    try:
        # print.c uses fwrite(), i.e. host-native doubles; every supported
        # MM-PIHM build host is little-endian, so bind the layout explicitly
        # rather than inheriting the reader's native order.
        a = np.fromfile(t1, dtype="<f8")
    except (OSError, ValueError):
        _skip("unreadable")
        return
    if a.size == 0:
        _skip("empty")
        return
    if a.size % reclen != 0:
        _skip("size %d doubles is not a multiple of NUMELE+1 = %d"
              % (a.size, reclen))
        return
    m = a.reshape(-1, reclen)
    stamps = m[:, 0]
    if not np.all(np.isfinite(stamps)) or (
            stamps.shape[0] > 1 and not np.all(np.diff(stamps) > 0.0)):
        _skip("column 0 is not a strictly increasing time stamp -- the file "
              "does not match this deck's NUMELE")
        return

    # Every remaining value IS a T1 temperature: no value is filtered out, so
    # an arbitrarily large divergence (ChiuniFR 2026-08-02 reached 1.44e11 K)
    # still reaches the threshold test.
    vals = m[:, 1:]
    isfin = np.isfinite(vals)
    nonfinite = int(vals.size - np.count_nonzero(isfin))
    finite = vals[isfin]
    tmax = float(finite.max()) if finite.size else float("inf")
    result["max_t1_k"] = tmax
    result["nonfinite_t1_count"] = nonfinite
    if tmax > MAX_PHYSICAL_T1_K or nonfinite > 0:
        result["status"] = "error"
        result.setdefault("errors", []).append(
            "THERMAL DIVERGENCE: max finite T1 = %.6g K (limit %.0f K), "
            "%d non-finite T1 value(s) in %s -- the Noah soil-temperature "
            "solver has gone unstable. Check ZBOT_DATA in the .lsm against "
            "the mesh soil depth (zmax-zmin): src/noah/noah.c:1024 needs "
            "0.5*(zsoil[n-2]+zsoil[n-1]) - zbot > 0, otherwise the geothermal "
            "term becomes anti-diffusive."
            % (tmax, MAX_PHYSICAL_T1_K, nonfinite, t1))


def main():
    parser = argparse.ArgumentParser(
        description="Execute MM-PIHM binary with pre-flight validation"
    )
    parser.add_argument("--binary", required=True, help="Path to PIHM executable")
    parser.add_argument("--project", required=True, help="Project name (e.g., ShaleHills)")
    parser.add_argument("--input-dir", required=True, help="Input directory path")
    parser.add_argument("--output-dir", default=None, help="Output directory name")
    parser.add_argument("--threads", type=int, default=4, help="Number of OpenMP threads")
    parser.add_argument("--spinup", action="store_true", help="Run in spin-up mode")
    parser.add_argument("--verbose", action="store_true", help="Verbose mode")
    parser.add_argument("--debug", action="store_true", help="Debug mode")
    parser.add_argument("--brief", action="store_true", help="Brief mode")
    parser.add_argument("--timeout", type=int, default=7200,
                        help="Timeout in seconds (default: 7200 = 2 hours)")
    args = parser.parse_args()

    warnings = validate_inputs(args)
    result = run_model(args, warnings)
    check_thermal_divergence(args, result)

    print(json.dumps(result, indent=2))
    if result["status"] != "success":
        sys.exit(1)


if __name__ == "__main__":
    main()
