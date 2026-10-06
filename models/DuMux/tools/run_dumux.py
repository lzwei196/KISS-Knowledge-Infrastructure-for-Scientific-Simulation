#!/usr/bin/env python3
"""
run_dumux.py — Build and execute a DuMux simulation.

Pipeline stage: s4 (Build & Execute)
Pattern: validate → process → validate

Handles:
  1. Building the DuMux executable with CMake/Make
  2. Running the simulation with parameter file
  3. Monitoring output and capturing results
  4. Post-run validation of output files

Usage:
    python run_dumux.py \\
        --source_dir /path/to/dumux/source \\
        --build_dir /path/to/build \\
        --target example_1ptracer \\
        --params params.input \\
        --overrides "Problem.Name=myrun TimeLoop.TEnd=10000"
"""

import argparse
import json
import os
import subprocess
import sys
import time
import glob
from pathlib import Path

# ─── Constants ────────────────────────────────────────────────────────────────
DEFAULT_BUILD_TYPE = "Release"
DEFAULT_CXX_FLAGS = "-O3 -DNDEBUG"
DEFAULT_TIMEOUT = 600  # seconds (10 minutes)
# DuMux/DUNE builds with OpenMP start one thread per core when no limit is set
# (192 on the GeoForge server). For the official 1ptracer example, 4 threads and
# all threads gave byte-identical output files.
DEFAULT_THREADS = 4

# Server builds of example_1ptracer (2026-10-06):
#  - clean official build (DuMux releases/3.10 3e151aeb, no local edits), the server default:
CLEAN_1PTRACER_BIN = ("KISSPATH_HOME/engine_builds_20261006/dumux/src/build-cmake/dumux/"
                      "examples/1ptracer/example_1ptracer")
CLEAN_1PTRACER_SHA256 = {"c1a81191f542afc19a5d46faaaf7df6777e6c31ed5997fe7afa341a473ad741c"}
#  - older build of a KI-edited problem_1p.hh (before 2026-10-06 the server default). Its
#    default Problem.FlowDirection=0 is a left-right flow, not the official bottom-top flow;
#    runs made with it are reproduced only with it (pass it with --binary):
EDITED_1PTRACER_BIN = ("KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/DuMux/"
                       "dumux/dumux/build-cmake/examples/1ptracer/example_1ptracer")
# Keys read ONLY by the KI-edited build. The clean build would ignore them without an error.
EDITED_ONLY_KEYS = ("Problem.FlowDirection", "Problem.PressureLeft", "Problem.PressureRight")


def _sha256(path: str) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _ini_keys(path: str) -> set:
    """Full key names in a DUNE INI file, read the way Dune::ParameterTreeParser::readINITree
    does (dune-common 2.10): '#' lines skipped; '[x]' sets the prefix (text after ']'
    ignored); '#' ends a key line; key = prefix + text before '='; a value starting with
    ' or \" runs over the following lines until the closing quote."""
    keys, prefix = set(), ""
    with open(path, errors="replace") as fh:
        lines = fh.read().split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].lstrip()
        i += 1
        if not line or line[0] == "#":
            continue
        if line[0] == "[":
            pos = line.find("]")
            if pos != -1:
                prefix = line[1:pos].strip()
                prefix = prefix + "." if prefix else ""
            continue
        line = line.split("#", 1)[0]
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        keys.add(prefix + key.strip())
        value = value.lstrip()
        if value and value[0] in "'\"":
            quote, value = value[0], value[1:]
            while not value.rstrip().endswith(quote) and i < len(lines):
                value += "\n" + lines[i]
                i += 1
    return keys


def _resolve_exe(binary_path: str, work_dir: str):
    """Absolute path of the program subprocess will start (relative paths are taken from
    work_dir, as subprocess does with cwd=work_dir; bare names from PATH); None if not found."""
    import shutil
    if os.path.isabs(binary_path):
        exe = binary_path
    elif os.sep in binary_path:
        exe = os.path.join(work_dir or os.getcwd(), binary_path)
    else:
        exe = shutil.which(binary_path)
    return os.path.abspath(exe) if exe and os.path.isfile(exe) else None


def edited_only_keys_used(exe: str, params_file: str, work_dir: str,
                          overrides: dict = None) -> list:
    """Edited-build-only keys that a run asks for while the program is the clean build.

    exe must be the absolute program path that will run. The parameter file is found the way
    DuMux 3.10 Parameters::init does: -ParameterFile override, else the first argument, else
    '<program>.input', else 'params.input' (relative names from work_dir). Returns [] when the
    program is not the known clean example_1ptracer build or no such key is used. Raises
    OSError/ValueError when the program or parameter file cannot be read.
    """
    if _sha256(exe) not in CLEAN_1PTRACER_SHA256:
        return []
    overrides = overrides or {}
    used = set(overrides)
    wd = work_dir or os.getcwd()
    pf = overrides.get("ParameterFile") or params_file
    if pf:
        pf = pf if os.path.isabs(pf) else os.path.join(wd, pf)
        if not os.path.isfile(pf):
            raise ValueError(f"parameter file not found: {pf}")
    else:
        for cand in (exe + ".input", os.path.join(wd, "params.input")):
            if os.path.isfile(cand):
                pf = cand
                break
    if pf:
        used |= _ini_keys(pf)
    return sorted(k for k in EDITED_ONLY_KEYS if k in used)


def _thread_env(threads=None) -> dict:
    """Environment for the engine with one OpenMP/DuMux thread limit.

    Precedence: threads argument (--threads), then $DUMUX_NUM_THREADS, then
    $OMP_NUM_THREADS, then DEFAULT_THREADS. Both variables are set to the chosen
    value. Raises ValueError for a value that is not a positive integer.
    """
    env = dict(os.environ)
    for label, val in (("--threads", threads),
                       ("$DUMUX_NUM_THREADS", env.get("DUMUX_NUM_THREADS")),
                       ("$OMP_NUM_THREADS", env.get("OMP_NUM_THREADS")),
                       ("default", DEFAULT_THREADS)):
        if val is None or str(val).strip() == "":
            continue
        try:
            n = int(str(val).strip())
        except ValueError:
            n = 0
        if n < 1:
            raise ValueError(f"thread count from {label} must be a positive integer, got {val!r}")
        env["OMP_NUM_THREADS"] = env["DUMUX_NUM_THREADS"] = str(n)
        return env
    return env


def validate_inputs(
    source_dir: str,
    build_dir: str,
    target: str,
    params_file: str,
) -> dict:
    """Validate build environment and input files.

    Returns:
        dict with valid, errors, warnings, metadata
    """
    result = {"valid": True, "errors": [], "warnings": [], "metadata": {}}

    # Check source directory
    if not os.path.isdir(source_dir):
        result["valid"] = False
        result["errors"].append(f"Source directory not found: {source_dir}")
        return result

    # Check for CMakeLists.txt
    cmake_file = os.path.join(source_dir, "CMakeLists.txt")
    if not os.path.isfile(cmake_file):
        result["valid"] = False
        result["errors"].append(f"CMakeLists.txt not found in {source_dir}")

    # Check for dune.module (DuMux-specific)
    dune_module = os.path.join(source_dir, "dune.module")
    if os.path.isfile(dune_module):
        result["metadata"]["has_dune_module"] = True
        with open(dune_module) as f:
            for line in f:
                if line.startswith("Version:"):
                    result["metadata"]["version"] = line.split(":")[1].strip()
                if line.startswith("Module:"):
                    result["metadata"]["module"] = line.split(":")[1].strip()
    else:
        result["warnings"].append("No dune.module found — may not be a DUNE/DuMux project")

    # Check parameter file
    if params_file and not os.path.isfile(params_file):
        # Params file might be relative to build target directory
        result["warnings"].append(
            f"Parameter file '{params_file}' not found at current path. "
            "Will search in build/example directories."
        )

    # Check for required tools
    for tool in ["cmake", "make"]:
        try:
            subprocess.run([tool, "--version"], capture_output=True, timeout=10)
        except FileNotFoundError:
            result["valid"] = False
            result["errors"].append(f"Required tool '{tool}' not found in PATH")
        except Exception:
            pass

    return result


def validate_build(build_dir: str, target: str) -> dict:
    """Validate build succeeded."""
    result = {"valid": True, "errors": [], "warnings": []}

    # Check build directory exists
    if not os.path.isdir(build_dir):
        result["valid"] = False
        result["errors"].append(f"Build directory not found: {build_dir}")
        return result

    # Search for the built binary
    binary_paths = []
    for root, dirs, files in os.walk(build_dir):
        for f in files:
            if f == target and os.access(os.path.join(root, f), os.X_OK):
                binary_paths.append(os.path.join(root, f))

    if not binary_paths:
        result["valid"] = False
        result["errors"].append(
            f"Binary '{target}' not found in {build_dir}. Build may have failed."
        )
    elif len(binary_paths) > 1:
        result["valid"] = False
        result["errors"].append(
            f"Several executables named '{target}' in {build_dir}: {binary_paths}. "
            "Pass the one to run with --binary."
        )
    else:
        result["binary_path"] = binary_paths[0]

    return result


def _file_state(folder: str) -> dict:
    """{path: (mtime_ns, size)} of the files directly in folder."""
    state = {}
    if os.path.isdir(folder):
        for name in os.listdir(folder):
            path = os.path.normpath(os.path.join(folder, name))
            if os.path.isfile(path):
                st = os.stat(path)
                state[path] = (st.st_mtime_ns, st.st_size)
    return state


def validate_output(work_dir: str, problem_name: str, before: dict = None) -> dict:
    """Validate simulation produced expected output files.

    before: _file_state(work_dir) taken just before the run; files that were
    already there unchanged (left from an earlier run) do not count.
    """
    result = {"valid": True, "errors": [], "warnings": [], "metadata": {}}

    # Check for VTK output files
    vtu_files = glob.glob(os.path.join(work_dir, f"{problem_name}*.vtu"))
    vtk_files = glob.glob(os.path.join(work_dir, f"{problem_name}*.vtk"))
    pvd_files = glob.glob(os.path.join(work_dir, f"{problem_name}*.pvd"))

    def fresh(fs):
        if before is None:
            return fs
        out = []
        for f in fs:
            st = os.stat(f)
            if before.get(os.path.normpath(f)) != (st.st_mtime_ns, st.st_size):
                out.append(f)
        return out

    data_files = fresh(vtu_files + vtk_files)
    new_pvd = fresh(pvd_files)
    stale = len(vtu_files + vtk_files) - len(data_files)
    all_vtk = data_files + new_pvd
    result["metadata"]["vtk_files"] = len(all_vtk)
    result["metadata"]["vtu_files"] = data_files[:5]  # first 5
    if stale:
        result["warnings"].append(f"{stale} older '{problem_name}*' data files ignored "
                                  "(not written by this run)")

    if len(data_files) == 0:
        result["valid"] = False
        result["errors"].append(
            f"No VTK data files (.vtu/.vtk) matching '{problem_name}*' written by this run in "
            f"{work_dir}. Check Problem.Name parameter and output directory."
        )
    else:
        empty = [f for f in data_files if os.path.getsize(f) == 0]
        total_size = sum(os.path.getsize(f) for f in all_vtk)
        result["metadata"]["total_output_size_bytes"] = total_size

        if empty:
            result["valid"] = False
            result["errors"].append(f"Empty VTK output files (0 bytes): {empty[:5]}")
        elif total_size < 100:
            result["warnings"].append(
                f"VTK output very small ({total_size} bytes). May contain no data."
            )

    # Every file listed in a .pvd written by this run must exist and not be empty
    import xml.etree.ElementTree as ET
    for pvd in new_pvd:
        try:
            refs = [d.get("file", "") for d in ET.parse(pvd).getroot().iter("DataSet")]
        except ET.ParseError as exc:
            result["valid"] = False
            result["errors"].append(f"Cannot read {pvd}: {exc}")
            continue
        bad, old, outside = [], [], []
        for r in refs:
            ref = os.path.normpath(os.path.join(os.path.dirname(pvd), r))
            if not os.path.isfile(ref) or os.path.getsize(ref) == 0:
                bad.append(r)
            elif before is not None and os.path.dirname(ref) != os.path.normpath(work_dir):
                # the pre-run state covers only files directly in work_dir
                outside.append(r)
            elif not fresh([ref]):
                old.append(r)
        if outside:
            result["valid"] = False
            result["errors"].append(f"{pvd} lists files outside {work_dir}; cannot check that this "
                                    f"run wrote them: {outside[:5]}")
        if bad:
            result["valid"] = False
            result["errors"].append(f"{pvd} lists missing or empty files: {bad[:5]}")
        if old:
            result["valid"] = False
            result["errors"].append(f"{pvd} lists files not written by this run: {old[:5]}")

    return result


# ─── Build Functions ─────────────────────────────────────────────────────────

def configure_cmake(
    source_dir: str,
    build_dir: str,
    build_type: str = DEFAULT_BUILD_TYPE,
    extra_cmake_args: list = None,
) -> dict:
    """Run cmake configuration step."""
    os.makedirs(build_dir, exist_ok=True)

    cmd = [
        "cmake",
        source_dir,
        f"-DCMAKE_BUILD_TYPE={build_type}",
    ]
    if extra_cmake_args:
        cmd.extend(extra_cmake_args)

    print(f"  CMake command: {' '.join(cmd)}")
    print(f"  Build directory: {build_dir}")

    try:
        proc = subprocess.run(
            cmd,
            cwd=build_dir,
            capture_output=True,
            text=True,
            timeout=300,
        )
        return {
            "success": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": proc.stdout[-2000:] if proc.stdout else "",
            "stderr": proc.stderr[-2000:] if proc.stderr else "",
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "returncode": -1, "stderr": "CMake timed out (300s)"}
    except Exception as e:
        return {"success": False, "returncode": -1, "stderr": str(e)}


def build_target(build_dir: str, target: str, n_jobs: int = 4) -> dict:
    """Build a specific target with make."""
    cmd = ["make", "-j", str(n_jobs), target]
    print(f"  Make command: {' '.join(cmd)}")

    try:
        proc = subprocess.run(
            cmd,
            cwd=build_dir,
            capture_output=True,
            text=True,
            timeout=600,
        )
        return {
            "success": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": proc.stdout[-2000:] if proc.stdout else "",
            "stderr": proc.stderr[-2000:] if proc.stderr else "",
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "returncode": -1, "stderr": "Build timed out (600s)"}
    except Exception as e:
        return {"success": False, "returncode": -1, "stderr": str(e)}


# ─── Run Functions ───────────────────────────────────────────────────────────

def run_simulation(
    binary_path: str,
    params_file: str,
    work_dir: str,
    overrides: dict = None,
    timeout: int = DEFAULT_TIMEOUT,
    threads: int = None,
) -> dict:
    """Run DuMux simulation.

    Args:
        binary_path: Path to compiled executable
        params_file: Path to .input parameter file
        work_dir: Working directory for execution
        overrides: Dict of param overrides {Section.Key: value}
        timeout: Maximum runtime in seconds
        threads: OpenMP/DuMux thread limit (default: env, else DEFAULT_THREADS)

    Returns:
        dict with success, returncode, stdout, stderr, runtime_s
    """
    exe = _resolve_exe(binary_path, work_dir)
    if exe is None:
        msg = f"program not found: {binary_path} (work dir {work_dir}). Not run."
        print(f"  ERROR: {msg}")
        return {"success": False, "returncode": -1, "stderr": msg, "runtime_s": 0.0}
    try:
        bad = edited_only_keys_used(exe, params_file, work_dir, overrides)
    except (OSError, ValueError) as exc:
        msg = f"could not check the run's parameters: {exc}. Not run."
        print(f"  ERROR: {msg}")
        return {"success": False, "returncode": -1, "stderr": msg, "runtime_s": 0.0}
    if bad:
        msg = (f"{', '.join(bad)} set, but {exe} is the clean official DuMux build, "
               f"which ignores these keys (it always runs the official bottom-top flow). These "
               f"keys need the older KI-edited build: pass --binary {EDITED_1PTRACER_BIN} "
               f"(or set DUMUX_BIN to it). Not run.")
        print(f"  ERROR: {msg}")
        return {"success": False, "returncode": -1, "stderr": msg, "runtime_s": 0.0}

    cmd = [exe]
    if params_file:
        cmd.append(params_file)

    # Add parameter overrides
    if overrides:
        for key, value in overrides.items():
            cmd.extend([f"-{key}", str(value)])

    env = _thread_env(threads)
    print(f"  Run command: {' '.join(cmd)}")
    print(f"  Work dir: {work_dir}")
    print(f"  Threads: OMP_NUM_THREADS={env['OMP_NUM_THREADS']} DUMUX_NUM_THREADS={env['DUMUX_NUM_THREADS']}")

    start_time = time.time()
    try:
        proc = subprocess.run(
            cmd,
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        elapsed = time.time() - start_time

        return {
            "success": proc.returncode == 0,
            "returncode": proc.returncode,
            "newton_info": parse_newton_output(proc.stdout or ""),  # from the full stdout
            "stdout": proc.stdout[-3000:] if proc.stdout else "",
            "stderr": proc.stderr[-2000:] if proc.stderr else "",
            "runtime_s": elapsed,
        }
    except subprocess.TimeoutExpired:
        elapsed = time.time() - start_time
        return {
            "success": False,
            "returncode": -1,
            "stderr": f"Simulation timed out after {timeout}s",
            "runtime_s": elapsed,
        }
    except Exception as e:
        elapsed = time.time() - start_time
        return {
            "success": False,
            "returncode": -1,
            "stderr": str(e),
            "runtime_s": elapsed,
        }


def parse_newton_output(stdout: str) -> dict:
    """Parse DuMux Newton solver output for convergence info."""
    info = {
        "time_steps": 0,
        "newton_iterations_total": 0,
        "convergence_failures": 0,
        "final_time": None,
    }

    for line in stdout.split("\n"):
        line_stripped = line.strip()
        if "Time step" in line_stripped:
            info["time_steps"] += 1
        if "Newton iteration" in line_stripped:
            info["newton_iterations_total"] += 1
        if "convergence" in line_stripped.lower() and "fail" in line_stripped.lower():
            info["convergence_failures"] += 1

    return info


# ─── Main Pipeline ───────────────────────────────────────────────────────────

def process(
    source_dir: str,
    build_dir: str,
    target: str,
    params_file: str,
    overrides_str: str = "",
    build_type: str = DEFAULT_BUILD_TYPE,
    skip_build: bool = False,
    timeout: int = DEFAULT_TIMEOUT,
    work_dir: str = None,
    threads: int = None,
    binary: str = None,
) -> dict:
    """Full build-and-run pipeline: validate → build → run → validate.

    The simulation runs in work_dir (default: the current directory), never in
    the build tree, so outputs do not mix with build files.
    """
    summary = {
        "status": "failed",
        "source_dir": source_dir,
        "build_dir": build_dir,
        "target": target,
    }

    # ── Validate inputs ──
    print("=== Validating inputs ===")
    input_val = validate_inputs(source_dir, build_dir, target, params_file)
    for w in input_val["warnings"]:
        print(f"  WARNING: {w}")
    if not input_val["valid"]:
        for e in input_val["errors"]:
            print(f"  ERROR: {e}")
        summary["errors"] = input_val["errors"]
        return summary
    summary["metadata"] = input_val["metadata"]

    if not skip_build:
        # ── Configure ──
        print("\n=== Configuring with CMake ===")
        cmake_result = configure_cmake(source_dir, build_dir, build_type)
        if not cmake_result["success"]:
            print(f"  CMake FAILED (rc={cmake_result['returncode']})")
            print(f"  stderr: {cmake_result['stderr'][:500]}")
            summary["cmake_error"] = cmake_result["stderr"][:1000]
            summary["status"] = "cmake_failed"
            return summary
        print("  CMake configuration: OK")

        # ── Build ──
        print("\n=== Building target ===")
        build_result = build_target(build_dir, target)
        if not build_result["success"]:
            print(f"  Build FAILED (rc={build_result['returncode']})")
            print(f"  stderr: {build_result['stderr'][:500]}")
            summary["build_error"] = build_result["stderr"][:1000]
            summary["status"] = "build_failed"
            return summary
        print("  Build: OK")

    # ── Locate binary ──
    # Order: --binary, then $DUMUX_BIN, then the one executable named --target
    # inside --build_dir. An explicit choice that is not
    # an executable file is an error; there is no fallback to another program.
    binary_path = None
    env_bin = os.environ.get("DUMUX_BIN")
    if binary:
        source = "--binary"
        binary_path = binary
    elif env_bin:
        source = "$DUMUX_BIN"
        binary_path = env_bin
    if binary_path is not None:
        if not (os.path.isfile(binary_path) and os.access(binary_path, os.X_OK)):
            msg = f"{source} {binary_path} is not an executable file"
            print(f"  ERROR: {msg}")
            summary["errors"] = [msg]
            summary["status"] = "binary_not_found"
            return summary
        binary_path = os.path.abspath(binary_path)
    else:
        build_val = validate_build(build_dir, target)
        if not build_val["valid"]:
            for e in build_val["errors"]:
                print(f"  ERROR: {e}")
            summary["errors"] = build_val["errors"]
            summary["status"] = "binary_not_found"
            return summary
        binary_path = os.path.abspath(build_val["binary_path"])
        source = "--build_dir"

    summary["binary_path"] = binary_path
    print(f"  Binary found ({source}): {binary_path}")

    # Resolve params file path: as given (relative to the current directory),
    # else next to the binary (where the DuMux build copies an example's
    # params file). Nothing else: a params file of another problem is never used.
    binary_dir = os.path.dirname(binary_path)
    if params_file:
        if os.path.isfile(params_file):
            params_file = os.path.abspath(params_file)
        elif os.path.isfile(os.path.join(binary_dir, params_file)):
            params_file = os.path.abspath(os.path.join(binary_dir, params_file))
            print(f"  Params file taken from the binary folder: {params_file}")
        else:
            msg = (f"Parameter file not found: '{params_file}' (looked in the current "
                   f"directory and in {binary_dir})")
            print(f"  ERROR: {msg}")
            summary["errors"] = [msg]
            summary["status"] = "params_not_found"
            return summary

    # Parse overrides
    overrides = {}
    if overrides_str:
        for pair in overrides_str.split():
            if "=" in pair and pair.split("=", 1)[0]:
                k, v = pair.split("=", 1)
                overrides[k] = v
            else:
                msg = f"Malformed override '{pair}' (expected Key=value)"
                print(f"  ERROR: {msg}")
                summary["errors"] = [msg]
                summary["status"] = "bad_overrides"
                return summary

    # ── Run simulation ──
    print("\n=== Running simulation ===")
    work_dir = os.path.abspath(work_dir or os.getcwd())
    os.makedirs(work_dir, exist_ok=True)
    summary["work_dir"] = work_dir
    try:
        _thread_env(threads)
    except ValueError as exc:
        print(f"  ERROR: {exc}")
        summary["errors"] = [str(exc)]
        summary["status"] = "bad_threads"
        return summary
    state_before = _file_state(work_dir)
    run_result = run_simulation(
        binary_path, params_file, work_dir, overrides, timeout, threads=threads
    )

    summary["runtime_s"] = run_result["runtime_s"]
    summary["test_command"] = f"{binary_path} {params_file}"

    if not run_result["success"]:
        print(f"  Simulation FAILED (rc={run_result['returncode']})")
        print(f"  stderr: {run_result['stderr'][:500]}")
        summary["run_error"] = run_result["stderr"][:1000]
        summary["test_output"] = run_result["stderr"][:500]
        summary["status"] = "run_failed"
        return summary

    print(f"  Simulation completed in {run_result['runtime_s']:.1f}s")
    summary["test_output"] = run_result["stdout"][:500]

    # Parse Newton info (counted on the full stdout in run_simulation)
    newton_info = run_result.get("newton_info") or parse_newton_output(run_result["stdout"])
    summary["newton_info"] = newton_info
    print(f"  Time steps: {newton_info['time_steps']}")
    print(f"  Newton iterations: {newton_info['newton_iterations_total']}")

    # ── Validate output ──
    print("\n=== Validating output ===")
    problem_name = overrides.get("Problem.Name", "")
    if not problem_name and params_file:
        # Problem.Name from the params file: "[Problem]" + "Name = x" or a root-level
        # "Problem.Name = x" (DUNE INI form; '#' comments and quotes removed)
        try:
            section = ""
            with open(params_file) as f:
                for line in f:
                    line = line.split("#", 1)[0].strip()
                    if line.startswith("[") and line.endswith("]"):
                        section = line[1:-1].strip()
                    elif "=" in line:
                        k, v = line.split("=", 1)
                        full = f"{section}.{k.strip()}" if section else k.strip()
                        if full == "Problem.Name":
                            problem_name = v.strip().strip('"').strip("'")
                            break
        except Exception:
            pass
    if not problem_name:
        problem_name = target

    output_val = validate_output(work_dir, problem_name, before=state_before)
    for w in output_val["warnings"]:
        print(f"  WARNING: {w}")
    summary["output_metadata"] = output_val["metadata"]

    if output_val["valid"]:
        summary["status"] = "completed"
        print("  Output validation: OK")
    else:
        for e in output_val["errors"]:
            print(f"  ERROR: {e}")
        summary["status"] = "output_invalid"

    return summary


def main():
    parser = argparse.ArgumentParser(
        description="Build and run a DuMux simulation"
    )
    parser.add_argument("--source_dir", required=True, help="DuMux source directory")
    parser.add_argument("--build_dir", required=True, help="Build directory")
    parser.add_argument("--target", required=True, help="Build target name")
    parser.add_argument("--params", default="", help="Parameter .input file")
    parser.add_argument("--overrides", default="", help="Parameter overrides: Key=val ...")
    parser.add_argument("--build_type", default=DEFAULT_BUILD_TYPE)
    parser.add_argument("--skip_build", action="store_true", help="Skip build step")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    parser.add_argument("--work_dir", default=None,
                        help="Folder to run in and write outputs to (default: current directory; "
                             "never the build tree)")
    parser.add_argument("--binary", default=None,
                        help="Prebuilt program to run (else $DUMUX_BIN, else the one "
                             "executable named --target in --build_dir)")
    parser.add_argument("--threads", type=int, default=None,
                        help=f"OpenMP/DuMux thread limit (default: $DUMUX_NUM_THREADS, then "
                             f"$OMP_NUM_THREADS, else {DEFAULT_THREADS})")
    args = parser.parse_args()

    result = process(
        source_dir=args.source_dir,
        build_dir=args.build_dir,
        target=args.target,
        params_file=args.params,
        overrides_str=args.overrides,
        build_type=args.build_type,
        skip_build=args.skip_build,
        timeout=args.timeout,
        work_dir=args.work_dir,
        threads=args.threads,
        binary=args.binary,
    )

    print(f"\n{'='*60}")
    print(f"Status: {result['status']}")
    if result.get("binary_path"):
        print(f"Binary: {result['binary_path']}")
    if result.get("work_dir"):
        print(f"Work dir: {result['work_dir']}")
    if result.get("runtime_s"):
        print(f"Runtime: {result['runtime_s']:.1f}s")

    if result["status"] != "completed":
        sys.exit(1)


if __name__ == "__main__":
    main()
