#!/usr/bin/env python3
"""
run_telemac.py - Execution wrapper for TELEMAC-MASCARET simulations.

Sets up the runtime environment (HOMETEL, PATH, LD_LIBRARY_PATH), validates
the steering file (.cas), and invokes the appropriate module runner script
(telemac2d.py, telemac3d.py, tomawac.py, etc.).

Usage:
    python run_telemac.py --cas simulation.cas --module telemac2d \
        --hometel /path/to/telemac

    python run_telemac.py --cas simulation.cas --module telemac3d \
        --hometel /path/to/telemac --nproc 8

    python run_telemac.py --cas coupled.cas --module telemac2d \
        --hometel /path/to/telemac --options "--ncsize 4"

Follows validate -> process -> validate pattern.
"""

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time
import uuid


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
VALID_MODULES = [
    "telemac2d", "telemac3d", "tomawac", "artemis",
    "gaia", "mascaret", "khione", "waqtel",
    "postel3d", "stbtel",
]

RUNNER_SCRIPTS = {
    "telemac2d": "telemac2d.py",
    "telemac3d": "telemac3d.py",
    "tomawac": "tomawac.py",
    "artemis": "artemis.py",
    "mascaret": "mascaret.py",
    "postel3d": "postel3d.py",
    "stbtel": "stbtel.py",
    "gaia": "telemac2d.py",  # gaia coupled with t2d
    "khione": "telemac2d.py",  # khione coupled with t2d
    "waqtel": "telemac2d.py",  # waqtel coupled with t2d
}


# Server defaults (same as preflight_check.py): TELEMAC tree and build.
SERVER_HOMETEL = ("KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/"
                  "TELEMAC_MASCARET/source/repo")
DEFAULT_BUILD_NAME = "main_gfortran_release"

TAIL_CHARS = 4000  # characters of stdout/stderr returned on failure


# ---------------------------------------------------------------------------
# Launch helpers (environment, build dir, work dir for user Fortran)
# ---------------------------------------------------------------------------
def parse_runner_options(hometel, runner, cas_path, nproc, extra_options):
    """Parse --options with TELEMAC's OWN runner grammar (runcode.add_runcode_argument).

    The command the runner will see ([cas] [--ncsize n] <options>) is parsed with the
    parser TELEMAC builds itself, so abbreviations (--workdir, --buildd), short-option
    clusters (-stw DIR) and last-occurrence rules match the real runner exactly.
    Returns (tokens, namespace) or raises ValueError for options the runner rejects.
    """
    tokens = shlex.split(extra_options) if extra_options else []
    scripts_dir = os.path.join(hometel, "scripts", "python3")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    from runcode import add_runcode_argument  # TELEMAC's own option grammar

    module = os.path.splitext(os.path.basename(runner))[0]
    parser = argparse.ArgumentParser(add_help=False)
    parser.set_defaults(module=module)
    parser = add_runcode_argument(parser, module=module)
    parser.add_argument("args", nargs="+")
    argv = [cas_path] + (["--ncsize", str(nproc)] if nproc and nproc > 1 else []) + tokens

    def _fail(message):
        raise ValueError(message)
    parser.error = _fail  # report instead of exiting
    return tokens, parser.parse_args(argv)


def resolve_build_dir(hometel, cli_build_dir, opt_build_dir):
    """Build dir: --options -d > --build-dir > $BUILD_DIR > <hometel> (if it has bin/,
    TELEMAC's own rule) > <hometel>/builds/main_gfortran_release (server default)."""
    for cand in (opt_build_dir, cli_build_dir, os.environ.get("BUILD_DIR")):
        if cand:
            return os.path.abspath(cand)
    if os.path.isdir(os.path.join(hometel, "bin")):
        return os.path.abspath(hometel)
    return os.path.join(os.path.abspath(hometel), "builds", DEFAULT_BUILD_NAME)


def dependency_dirs(build_dir):
    """Relative folders named by -Wl,--dependency-file=... in build_commands.json.

    This build's user-Fortran link lines (library and executable) carry CMake's
    --dependency-file=CMakeFiles/<target>.dir/link.d; ld stops if that folder does not
    exist in the folder where TELEMAC links (<work dir>/user_fortran).
    """
    path = os.path.join(build_dir, "build_commands.json")
    if not os.path.isfile(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    dirs = set()
    for dep in re.findall(r"--dependency-file=([^\s\"]+)", text):
        d = os.path.dirname(dep)
        if not d or os.path.isabs(d) or ".." in d.replace("\\", "/").split("/"):
            continue
        dirs.add(d)
    return sorted(dirs)


def prepare_work_dir(cas_path, tokens, known, build_dir):
    """Make sure TELEMAC runs in a known work dir and pre-create the link.d folders.

    Returns (tokens, work_dir). If the caller gave -w (as parsed by TELEMAC's grammar),
    it is kept (relative paths are joined to the case dir, as TELEMAC does). Otherwise a
    unique work dir next to the .cas is passed with -w (TELEMAC still deletes it at the
    end unless -t is given). For staged runs (--split/--run/--merge/-x) without -w
    nothing is added: TELEMAC itself requires the caller's -w there.
    """
    cas_dir = os.path.dirname(cas_path)
    if known.w_dir:
        wd = os.path.join(cas_dir, known.w_dir)
    elif known.split or known.run or known.merge or known.compileonly:
        return tokens, None
    else:
        stamp = time.strftime("%Y-%m-%d-%Hh%Mmin%Ss")
        wd = os.path.join(cas_dir, f"{os.path.basename(cas_path)}_{stamp}_{uuid.uuid4().hex[:8]}")
        tokens = tokens + ["-w", wd]
    fdir = os.path.join(wd, "user_fortran")
    for d in dependency_dirs(build_dir):
        os.makedirs(os.path.join(fdir, d), exist_ok=True)
    return tokens, wd


def known_error_hints(text):
    hints = []
    if "cannot open shared object file" in text:
        hints.append("A TELEMAC shared library was not found: check the build dir "
                     "(--build-dir / BUILD_DIR) and that <build>/lib exists.")
    if "dependency file" in text and "link.d" in text:
        hints.append("ld could not write CMake's link.d during the user Fortran link "
                     "(see build_commands.json --dependency-file).")
    if "Could not compile your Fortran" in text or "Could not link your" in text:
        hints.append("The case's user Fortran (FORTRAN FILE) failed to compile/link.")
    return hints


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------
def validate_inputs(args):
    """Check steering file, module, and environment."""
    errors = []

    # Check steering file
    if not os.path.isfile(args.cas):
        errors.append(f"Steering file not found: {args.cas}")

    # Check module
    if args.module not in VALID_MODULES:
        errors.append(f"Unknown module '{args.module}'. Valid: {VALID_MODULES}")

    # Check HOMETEL
    hometel = args.hometel or os.environ.get("HOMETEL", "") or SERVER_HOMETEL
    if not hometel:
        errors.append("HOMETEL not set. Use --hometel or set HOMETEL env var")
    elif not os.path.isdir(hometel):
        errors.append(f"HOMETEL directory does not exist: {hometel}")

    # Check runner script
    if hometel and os.path.isdir(hometel):
        runner = os.path.join(hometel, "scripts", "python3", RUNNER_SCRIPTS.get(args.module, ""))
        if not os.path.isfile(runner):
            errors.append(f"Runner script not found: {runner}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)

    return os.path.abspath(hometel)


def validate_cas_file(cas_path):
    """Parse and validate critical keywords in the steering file."""
    warnings = []
    keywords = {}

    with open(cas_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("/"):
                continue
            if "=" in line or ":" in line:
                sep = "=" if "=" in line else ":"
                parts = line.split(sep, 1)
                key = parts[0].strip().upper()
                val = parts[1].strip().rstrip("/").strip()
                # Remove inline comments
                val = val.split("/")[0].strip()
                keywords[key] = val

    # Check required files
    for required in ["GEOMETRY FILE", "BOUNDARY CONDITIONS FILE"]:
        if required not in keywords:
            warnings.append(f"Missing keyword: {required}")
        else:
            fpath = keywords[required].strip("'\"")
            cas_dir = os.path.dirname(os.path.abspath(cas_path))
            full_path = os.path.join(cas_dir, fpath)
            if not os.path.isfile(full_path):
                warnings.append(f"{required} not found: {full_path}")

    # Check time parameters
    if "TIME STEP" in keywords:
        try:
            dt = float(keywords["TIME STEP"])
            if dt <= 0:
                warnings.append(f"TIME STEP must be positive, got {dt}")
            elif dt > 3600:
                warnings.append(f"TIME STEP = {dt}s seems very large (> 1 hour)")
        except ValueError:
            warnings.append(f"Cannot parse TIME STEP: {keywords['TIME STEP']}")

    # Check friction consistency
    friction_law = keywords.get("LAW OF BOTTOM FRICTION", "")
    friction_coeff = keywords.get("FRICTION COEFFICIENT", "")
    if friction_law and friction_coeff:
        try:
            law = int(friction_law)
            coeff = float(friction_coeff)
            if law == 4 and coeff > 1.0:  # Manning
                warnings.append(
                    f"Manning friction (law=4) with coefficient={coeff}. "
                    f"Manning n is typically 0.01-0.10. Did you mean Strickler (law=3)?")
            if law == 3 and coeff < 1.0:  # Strickler
                warnings.append(
                    f"Strickler friction (law=3) with coefficient={coeff}. "
                    f"Strickler K is typically 10-90. Did you mean Manning (law=4)?")
        except ValueError:
            pass

    return keywords, warnings


def validate_output(cas_path, keywords, run_dir):
    """Check that the results file was produced."""
    results_file = keywords.get("RESULTS FILE", "").strip("'\"")
    if results_file:
        # Results are written to the run directory
        expected = os.path.join(run_dir, results_file)
        if os.path.isfile(expected):
            size_mb = os.path.getsize(expected) / (1024 * 1024)
            return {"status": "success", "results_file": expected,
                    "size_mb": round(size_mb, 2)}
        else:
            # Check in cas directory
            cas_dir = os.path.dirname(os.path.abspath(cas_path))
            alt = os.path.join(cas_dir, results_file)
            if os.path.isfile(alt):
                size_mb = os.path.getsize(alt) / (1024 * 1024)
                return {"status": "success", "results_file": alt,
                        "size_mb": round(size_mb, 2)}
    return {"status": "warning", "message": "Results file not found after run"}


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------
def run_simulation(hometel, module, cas_path, nproc, extra_options, build_dir=None):
    """Execute the TELEMAC simulation."""
    scripts_dir = os.path.join(hometel, "scripts", "python3")
    runner = os.path.join(scripts_dir, RUNNER_SCRIPTS[module])
    cas_path = os.path.abspath(cas_path)

    try:
        tokens, known = parse_runner_options(hometel, runner, cas_path, nproc, extra_options)
    except Exception as exc:  # parse error or TELEMAC scripts not importable
        return {"returncode": 2, "stdout": "", "elapsed_s": 0.0,
                "stderr": f"Could not read --options with TELEMAC's runner grammar: {exc}"}
    cas_dir = os.path.dirname(cas_path)
    # Relative -r/-d are seen by TELEMAC from the case dir (its cwd): resolve them there
    # and forward the absolute paths last (argparse: last occurrence wins).
    if known.root_dir:
        root_abs = os.path.normpath(os.path.join(cas_dir, known.root_dir))
        if root_abs != os.path.normpath(hometel):
            return {"returncode": 2, "stdout": "", "elapsed_s": 0.0,
                    "stderr": f"--options rootdir {known.root_dir} ({root_abs}) conflicts "
                              f"with HOMETEL {hometel}"}
        tokens = tokens + ["-r", root_abs]
    opt_build = os.path.join(cas_dir, known.build_dir) if known.build_dir else ""
    build = resolve_build_dir(hometel, build_dir, opt_build)
    if known.build_dir:
        tokens = tokens + ["-d", build]
    lib_dir = os.path.join(build, "lib")
    if not os.path.isdir(lib_dir):
        return {"returncode": 2, "stdout": "", "elapsed_s": 0.0,
                "stderr": f"TELEMAC build lib dir not found: {lib_dir} "
                          f"(set --build-dir or BUILD_DIR)"}
    try:
        tokens, work_dir = prepare_work_dir(cas_path, tokens, known, build)
    except OSError as exc:
        return {"returncode": 2, "stdout": "", "elapsed_s": 0.0,
                "stderr": f"Could not prepare TELEMAC work dir: {exc}"}

    # Build environment
    env = os.environ.copy()
    env["HOMETEL"] = hometel
    env["BUILD_DIR"] = build
    env["PATH"] = scripts_dir + ":" + env.get("PATH", "")
    env["LD_LIBRARY_PATH"] = lib_dir + (":" + env["LD_LIBRARY_PATH"]
                                        if env.get("LD_LIBRARY_PATH") else "")

    # Build command
    cmd = [sys.executable, runner, cas_path]
    if nproc and nproc > 1:
        cmd.extend(["--ncsize", str(nproc)])
    cmd.extend(tokens)

    print(f"Running: {' '.join(cmd)}", file=sys.stderr)
    print(f"Working directory: {os.path.dirname(cas_path)}", file=sys.stderr)
    print(f"Build dir: {build}  (LD_LIBRARY_PATH += {lib_dir})", file=sys.stderr)
    if work_dir:
        print(f"TELEMAC work dir: {work_dir}", file=sys.stderr)

    start_time = time.time()
    try:
        result = subprocess.run(
            cmd,
            cwd=os.path.dirname(cas_path),
            env=env,
            capture_output=True,
            text=True,
            timeout=7200,  # 2 hour timeout
        )
        rc, out, err = result.returncode, result.stdout or "", result.stderr or ""
    except subprocess.TimeoutExpired as exc:
        rc = 124
        out = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        err = (exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")) \
            + "\nTimed out after 7200 s"
    except OSError as exc:
        rc, out, err = 127, "", f"Could not start {runner}: {exc}"
    elapsed = time.time() - start_time

    return {
        "returncode": rc,
        "stdout": out[-TAIL_CHARS:],
        "stderr": err[-TAIL_CHARS:],
        "hints": known_error_hints(out + "\n" + err),
        "elapsed_s": round(elapsed, 2),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Run TELEMAC-MASCARET simulation")
    parser.add_argument("--cas", required=True, help="Steering file (.cas)")
    parser.add_argument("--module", required=True, choices=VALID_MODULES,
                        help="TELEMAC module to run")
    parser.add_argument("--hometel", default=None, help="TELEMAC root directory")
    parser.add_argument("--nproc", type=int, default=1, help="Number of MPI processes")
    parser.add_argument("--options", default="", help="Extra options for runner script")
    parser.add_argument("--build-dir", default=None,
                        help="TELEMAC build dir (default: $BUILD_DIR, else "
                             "<hometel>/builds/main_gfortran_release); <build>/lib is "
                             "added to LD_LIBRARY_PATH")
    parser.add_argument("--dry-run", action="store_true", help="Validate only, do not run")
    args = parser.parse_args()

    # Step 1: Validate inputs
    hometel = validate_inputs(args)

    # Step 2: Validate steering file
    keywords, warnings = validate_cas_file(args.cas)
    if warnings:
        for w in warnings:
            print(f"WARNING: {w}", file=sys.stderr)

    if args.dry_run:
        print(json.dumps({
            "status": "validated",
            "module": args.module,
            "cas": args.cas,
            "keywords_found": len(keywords),
            "warnings": warnings,
        }))
        return

    # Step 3: Run simulation
    run_result = run_simulation(hometel, args.module, args.cas, args.nproc, args.options,
                                build_dir=args.build_dir)

    if run_result["returncode"] != 0:
        print(json.dumps({
            "status": "error",
            "returncode": run_result["returncode"],
            "elapsed_s": run_result["elapsed_s"],
            "stderr_tail": run_result["stderr"],
            "stdout_tail": run_result["stdout"],
            "hints": run_result.get("hints", []),
        }))
        sys.exit(1)

    # Step 4: Validate output
    run_dir = os.path.dirname(os.path.abspath(args.cas))
    output_check = validate_output(args.cas, keywords, run_dir)
    output_check["elapsed_s"] = run_result["elapsed_s"]
    output_check["module"] = args.module
    print(json.dumps(output_check))


if __name__ == "__main__":
    main()
