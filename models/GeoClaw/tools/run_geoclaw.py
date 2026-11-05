#!/usr/bin/env python3
"""
run_geoclaw.py — Compile and execute a GeoClaw simulation with error checking.

Handles the full execution pipeline:
  1. Generate .data files from setrun.py
  2. Compile Fortran sources via Makefile (if needed)
  3. Run the xgeoclaw executable
  4. Verify output files were produced

CRITICAL REQUIREMENTS:
  - CLAW environment variable must be set to clawpack root
  - A Fortran compiler (gfortran) must be available
  - setrun.py must exist in the run directory
  - Topography files referenced in setrun.py must exist

Pattern: validate_inputs → process → validate_outputs
"""

import argparse
import json
import os
import subprocess
import sys
import time
import glob
import shutil


# ---------------------------------------------------------------------------
# Clawpack engine lookup. GeoClaw is the Clawpack Fortran source tree ($CLAW), compiled per
# case by `make .exe` with $FC, plus the Clawpack Python that runs setrun.py. None of it is in
# the HydroCraft python_env that SKILL.md uses to start this tool, so the tool finds it itself
# (same env vars and server defaults as preflight_check.py and the tree's setup_env.sh):
#   Clawpack python: --claw-python -> $CLAW_PYTHON -> server default
#                    -> this python (only if it imports clawpack.geoclaw / clawpack.clawutil)
#   Clawpack source: --claw-dir -> $CLAW -> server default
#   Fortran compiler: --fc -> $FC -> gfortran
# An explicit value is used as given; if it does not work the run fails (no fallback).
# ---------------------------------------------------------------------------
GEOCLAW_WORK = "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/GeoClaw"
CLAW_PYTHON_DEFAULT = GEOCLAW_WORK + "/venv/bin/python"
CLAW_DIR_DEFAULT = GEOCLAW_WORK + "/clawpack"
CLAW_IMPORT_CHECK = "import clawpack.geoclaw, clawpack.clawutil"

# Files xgeoclaw writes into the output folder (removed before a fresh run with --overwrite)
OUTPUT_PATTERNS = ["fort.*", "gauge[0-9]*.txt", "gauge[0-9]*.bin*", "fgmax[0-9]*.txt",
                   "fgout[0-9]*.[qtb][0-9]*"]


def _pick(cli_value, option, env_name, default=None):
    """CLI value -> environment variable -> default; returns (value, source)."""
    if cli_value is not None:
        return cli_value, option
    if os.environ.get(env_name) is not None:
        return os.environ[env_name], "$" + env_name
    return default, "default"


def resolve_engine(args):
    """Return ({"claw_python", "claw_dir", "fc"} with sources, errors)."""
    errors = []
    eng = {}

    py, src = _pick(args.claw_python, "--claw-python", "CLAW_PYTHON")
    if py is None:
        if os.path.isfile(CLAW_PYTHON_DEFAULT):
            py, src = CLAW_PYTHON_DEFAULT, "server default"
        elif subprocess.run([sys.executable, "-c", CLAW_IMPORT_CHECK],
                            capture_output=True).returncode == 0:
            py, src = sys.executable, "running python (imports clawpack)"
    if not py or not (os.path.isfile(py) and os.access(py, os.X_OK)):
        errors.append(f"Clawpack python not found or not executable: {py!r} ({src}); set "
                      f"--claw-python / CLAW_PYTHON (server default {CLAW_PYTHON_DEFAULT})")
    else:
        py = os.path.abspath(py)  # not realpath: a venv python must keep its own path
        try:
            ok = subprocess.run([py, "-c", CLAW_IMPORT_CHECK], capture_output=True,
                                timeout=300).returncode == 0
        except (OSError, subprocess.TimeoutExpired) as e:
            ok = False
            src += f"; {e}"
        if not ok:
            errors.append(f"{py} ({src}) cannot import clawpack.geoclaw / clawpack.clawutil")
    eng["claw_python"], eng["claw_python_source"] = py, src

    claw, src = _pick(args.claw_dir, "--claw-dir", "CLAW")
    if claw is None and os.path.isdir(CLAW_DIR_DEFAULT):
        claw, src = CLAW_DIR_DEFAULT, "server default"
    if claw is not None and claw != "":
        claw = os.path.abspath(claw)
    eng["claw_dir"], eng["claw_dir_source"] = claw, src
    if args.use_makefile and not (claw and os.path.isfile(
            os.path.join(claw, "clawutil", "src", "Makefile.common"))):
        errors.append(f"Clawpack source tree not usable: {claw!r} ({src}); set --claw-dir / CLAW "
                      f"(server default {CLAW_DIR_DEFAULT}, see its setup_env.sh)")

    fc, src = _pick(args.fc, "--fc", "FC", "gfortran")
    if fc and os.sep in fc:  # a path (not a bare command name): make runs in run_dir
        fc = os.path.abspath(fc)
    eng["fc"], eng["fc_source"] = fc, src
    return eng, errors


def engine_env(eng):
    """Environment for setrun.py, make and xgeoclaw (as clawpack/setup_env.sh sets it)."""
    env = dict(os.environ)
    env["CLAW_PYTHON"] = eng["claw_python"]
    env["FC"] = eng["fc"]
    if eng.get("claw_dir"):
        env["CLAW"] = eng["claw_dir"]
    env["PATH"] = os.path.dirname(eng["claw_python"]) + os.pathsep + env.get("PATH", "")
    return env


def _claw_data_value(run_dir, key):
    """Value of '<value> =: <key>' in run_dir/claw.data (None if absent)."""
    path = os.path.join(run_dir, "claw.data")
    if not os.path.isfile(path):
        return None
    with open(path) as f:
        for line in f:
            if "=:" in line and line.split("=:", 1)[1].split()[:1] == [key]:
                return line.split("=:", 1)[0].strip()
    return None


def validate_inputs(args):
    """Phase 1: Validate environment and input files. Returns (engine, errors, warnings)."""
    errors = []
    warnings = []

    # Check run directory
    if not os.path.isdir(args.run_dir):
        errors.append(f"Run directory not found: {args.run_dir}")

    # Check setrun.py
    setrun_path = os.path.join(args.run_dir, "setrun.py")
    if not os.path.isfile(setrun_path):
        errors.append(f"setrun.py not found in {args.run_dir}")

    # Check Makefile
    makefile_path = os.path.join(args.run_dir, "Makefile")
    if not os.path.isfile(makefile_path):
        if args.use_makefile:
            errors.append(f"Makefile not found in {args.run_dir} (required when --use-makefile)")
        else:
            warnings.append("No Makefile found — will attempt direct execution")

    # Clawpack python / source tree / compiler
    eng, eng_errors = resolve_engine(args)
    errors.extend(eng_errors)

    # Check Fortran compiler
    if args.use_makefile:
        fc = eng["fc"]
        try:
            subprocess.run([fc, "--version"], capture_output=True, timeout=10)
        except (FileNotFoundError, PermissionError, subprocess.TimeoutExpired):
            errors.append(
                f"Fortran compiler '{fc}' ({eng['fc_source']}) not found. "
                "Install gfortran: sudo apt install gfortran"
            )

    return eng, errors, warnings


def process(args, input_warnings):
    """Phase 2: Compile and run GeoClaw."""
    warnings = list(input_warnings)
    run_dir = args.run_dir
    start_time = time.time()

    result = {
        "status": "running",
        "run_dir": run_dir,
        "warnings": warnings,
        "steps": [],
    }

    env = engine_env(args.engine)
    result["engine"] = {k: v for k, v in args.engine.items()}

    # Step 1: Generate .data files from setrun.py
    step_result = _run_setrun(run_dir, args.timeout, args.engine["claw_python"], env)
    result["steps"].append(step_result)
    if step_result["status"] != "success":
        result["status"] = "error"
        result["error"] = "Failed to generate .data files from setrun.py"
        return result

    # Step 2: Compile (if using Makefile)
    if args.use_makefile:
        step_result = _compile(run_dir, args.timeout, env)
        result["steps"].append(step_result)
        if step_result["status"] != "success":
            result["status"] = "error"
            result["error"] = "Compilation failed"
            return result

    # Step 3: Run the executable in run_dir/_output (as clawutil's runclaw / `make .output`)
    step_result = _run_executable(run_dir, args.executable, args.timeout, env, args.overwrite)
    result["steps"].append(step_result)
    if step_result["status"] != "success":
        result["status"] = "error"
        result["error"] = "Simulation failed"
        return result

    elapsed = time.time() - start_time
    result["status"] = "success"
    result["elapsed_seconds"] = round(elapsed, 2)
    result["warnings"] = warnings

    return result


def _run_setrun(run_dir, timeout, claw_python, env):
    """Generate .data files by running setrun.py with the Clawpack python."""
    try:
        proc = subprocess.run(
            [claw_python, "setrun.py"],
            cwd=run_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        return {
            "step": "generate_data_files",
            "status": "success" if proc.returncode == 0 else "error",
            "returncode": proc.returncode,
            "stdout": proc.stdout[-500:] if proc.stdout else "",
            "stderr": proc.stderr[-500:] if proc.stderr else "",
        }
    except subprocess.TimeoutExpired:
        return {"step": "generate_data_files", "status": "error",
                "error": f"Timeout after {timeout}s"}
    except Exception as e:
        return {"step": "generate_data_files", "status": "error", "error": str(e)}


def _compile(run_dir, timeout, env):
    """Compile Fortran sources using Makefile."""
    try:
        proc = subprocess.run(
            ["make", ".exe"],
            cwd=run_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        return {
            "step": "compile",
            "status": "success" if proc.returncode == 0 else "error",
            "returncode": proc.returncode,
            "stdout": proc.stdout[-500:] if proc.stdout else "",
            "stderr": proc.stderr[-500:] if proc.stderr else "",
        }
    except subprocess.TimeoutExpired:
        return {"step": "compile", "status": "error",
                "error": f"Compilation timeout after {timeout}s"}
    except Exception as e:
        return {"step": "compile", "status": "error", "error": str(e)}


def _run_executable(run_dir, executable, timeout, env, overwrite=False):
    """Run the GeoClaw executable in run_dir/_output, like clawutil's runclaw.

    The *.data files written by setrun.py are copied into _output and the executable runs
    there, so fort.q*/fort.t*/gauge*.txt/fgmax*.txt land in _output. Old output files are
    removed first with --overwrite (a fresh run refuses to mix with them otherwise); a
    restart run (claw.data restart = T) keeps them, as runclaw does.
    """
    output_dir = os.path.join(run_dir, "_output")
    try:
        os.makedirs(output_dir, exist_ok=True)
    except OSError as e:
        return {"step": "run_simulation", "status": "error",
                "error": f"could not create {output_dir}: {e}"}

    # Find executable
    exe_path = None
    candidates = ["xgeoclaw", "xgeo", "xclaw"]
    if executable:
        exe_path = os.path.abspath(executable)
    else:
        # Look for common GeoClaw executable names
        for cand in candidates:
            p = os.path.join(run_dir, cand)
            if os.path.isfile(p) and os.access(p, os.X_OK):
                exe_path = p
                break

    if not exe_path or not os.path.isfile(exe_path):
        return {
            "step": "run_simulation",
            "status": "error",
            "error": f"Executable not found. Looked for: {exe_path or candidates}",
        }

    restart = (_claw_data_value(run_dir, "restart") or "F").upper() in ("T", "TRUE", ".TRUE.")
    amr = os.path.join(output_dir, "fort.amr")
    try:
        old = sorted({f for pat in OUTPUT_PATTERNS
                      for f in glob.glob(os.path.join(output_dir, pat)) if os.path.isfile(f)})
        if old and not restart:
            if not overwrite:
                return {
                    "step": "run_simulation",
                    "status": "error",
                    "error": f"{output_dir} already has {len(old)} output files from an earlier "
                             "run (fort.*, gauge*, fgmax*, fgout*); use --overwrite to replace them",
                }
            for f in old:
                os.remove(f)
        for f in glob.glob(os.path.join(run_dir, "*.data")):
            shutil.copy(f, os.path.join(output_dir, os.path.basename(f)))
        # a restart appends to fort.amr: only text written by this run counts
        amr_offset = os.path.getsize(amr) if os.path.isfile(amr) else 0
    except OSError as e:
        return {"step": "run_simulation", "status": "error",
                "error": f"could not prepare {output_dir}: {e}"}

    try:
        proc = subprocess.run(
            [exe_path],
            cwd=output_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        status = "success" if proc.returncode == 0 else "error"
        out = {
            "step": "run_simulation",
            "status": status,
            "returncode": proc.returncode,
            "executable": exe_path,
            "output_dir": output_dir,
            "restart": restart,
            "stdout_tail": proc.stdout[-1000:] if proc.stdout else "",
            "stderr_tail": proc.stderr[-1000:] if proc.stderr else "",
        }
        # A Fortran STOP can end the run with return code 0; AMRClaw writes this line to
        # fort.amr only when the integration really finished.
        finished = False
        if os.path.isfile(amr):
            with open(amr, errors="replace") as f:
                if os.path.getsize(amr) >= amr_offset:
                    f.seek(amr_offset)
                finished = "end of AMRCLAW integration" in f.read()
        if status == "success" and not finished:
            out["status"] = "error"
            out["error"] = (f"{os.path.basename(exe_path)} returned 0 but {amr} has no "
                            "'end of AMRCLAW integration' line: the run did not finish")
        return out
    except subprocess.TimeoutExpired:
        return {
            "step": "run_simulation",
            "status": "error",
            "error": f"Simulation timeout after {timeout}s",
        }
    except Exception as e:
        return {"step": "run_simulation", "status": "error", "error": str(e)}


def validate_outputs(result):
    """Phase 3: Validate simulation outputs."""
    if result["status"] != "success":
        return result

    warnings = result.get("warnings", [])
    run_dir = result["run_dir"]
    output_dir = os.path.join(run_dir, "_output")

    # Check output directory exists
    if not os.path.isdir(output_dir):
        warnings.append("CRITICAL: _output directory was not created")
        result["warnings"] = warnings
        return result

    # Count output files
    q_files = sorted(glob.glob(os.path.join(output_dir, "fort.q*")))
    t_files = sorted(glob.glob(os.path.join(output_dir, "fort.t*")))
    a_files = sorted(glob.glob(os.path.join(output_dir, "fort.a[0-9]*")))  # not fort.amr
    gauge_file = os.path.join(output_dir, "fort.gauge")
    gauge_txt = glob.glob(os.path.join(output_dir, "gauge[0-9]*.txt"))

    result["output_files"] = {
        "fort_q": len(q_files),
        "fort_t": len(t_files),
        "fort_a": len(a_files),
        "gauge": os.path.isfile(gauge_file) or bool(gauge_txt),
    }

    # Frames the run must write (clawutil ClawRunData output styles): output_t0 = T, or
    # style 1 with num_output_times > 0, or style 2 (a non-empty list of output_times),
    # or style 3 with output_step_interval > 0 and total_steps >= output_step_interval
    def _int(key):
        try:
            return int(float(_claw_data_value(run_dir, key) or 0))
        except ValueError:
            return 0
    t0 = (_claw_data_value(run_dir, "output_t0") or "F").upper() in ("T", "TRUE")
    style = _claw_data_value(run_dir, "output_style")
    frames_expected = (
        (style in ("1", "3") and t0)
        or (style == "1" and _int("num_output_times") > 0)
        or (style == "2" and _int("num_output_times") > 0)
        or (style == "3" and _int("output_step_interval") > 0
            and _int("total_steps") >= _int("output_step_interval"))
    )

    if len(q_files) == 0:
        if frames_expected:
            result["status"] = "error"
            result["error"] = (f"No fort.q files in {output_dir}, although claw.data asks "
                               "for output frames")
        warnings.append("CRITICAL: No fort.q files produced — simulation may have failed")
    elif len(q_files) == 1:
        warnings.append("WARNING: Only 1 fort.q file — only initial condition was written")

    # Check for NaN in last output
    if q_files:
        last_q = q_files[-1]
        try:
            with open(last_q, "r") as f:
                content = f.read(10000)
                if "nan" in content.lower() or "inf" in content.lower():
                    warnings.append(
                        "CRITICAL: NaN or Inf detected in final output. "
                        "Likely numerical instability — reduce CFL or increase resolution."
                    )
        except Exception:
            pass

    # Check total output size
    total_size = sum(
        os.path.getsize(f) for f in q_files + t_files + a_files
        if os.path.isfile(f)
    )
    result["total_output_size_mb"] = round(total_size / 1e6, 2)

    result["warnings"] = warnings
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Compile and run a GeoClaw simulation"
    )
    parser.add_argument("--run-dir", required=True,
                        help="Directory containing setrun.py and Makefile")
    parser.add_argument("--use-makefile", action="store_true",
                        help="Use Makefile to compile (requires gfortran)")
    parser.add_argument("--executable", default=None,
                        help="Path to pre-compiled executable")
    parser.add_argument("--overwrite", action="store_true",
                        help="Overwrite existing output")
    parser.add_argument("--timeout", type=int, default=3600,
                        help="Max runtime in seconds (default: 3600)")
    parser.add_argument("--json-output", default=None,
                        help="Write result JSON to this file")
    parser.add_argument("--claw-python", default=None,
                        help="Python with clawpack, runs setrun.py (default: $CLAW_PYTHON, else "
                             f"{CLAW_PYTHON_DEFAULT}, else this python if it imports clawpack)")
    parser.add_argument("--claw-dir", default=None,
                        help=f"Clawpack source tree for make (default: $CLAW, else {CLAW_DIR_DEFAULT})")
    parser.add_argument("--fc", default=None,
                        help="Fortran compiler for make (default: $FC, else gfortran)")

    args = parser.parse_args()
    args.run_dir = os.path.abspath(args.run_dir)

    # Phase 1: Validate inputs
    engine, errors, input_warnings = validate_inputs(args)
    for key in ("claw_python", "claw_dir", "fc"):
        print(f"[run_geoclaw.py] {key}: {engine[key]} ({engine[key + '_source']})",
              file=sys.stderr)

    if errors:
        result = {"status": "error", "errors": errors, "warnings": input_warnings,
                  "run_dir": args.run_dir}
    else:
        args.engine = engine
        # Phase 2: Process
        result = process(args, input_warnings)
        # Phase 3: Validate outputs
        result = validate_outputs(result)

    # Write JSON result
    if args.json_output:
        with open(args.json_output, "w") as f:
            json.dump(result, f, indent=2)
    else:
        print(json.dumps(result, indent=2))

    sys.exit(0 if result.get("status") == "success" else 1)


if __name__ == "__main__":
    main()
