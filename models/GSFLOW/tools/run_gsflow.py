#!/usr/bin/env python3
"""
Execute the GSFLOW model binary with pre/post validation.

Usage:
    python run_gsflow.py \
        --executable /path/to/gsflow \
        --control-file /path/to/gsflow.control \
        --timeout 7200

Pipeline Stage: s6 (Model Execution)
Follows: validate → process → validate pattern

Checks:
    Pre-run:  control file exists, the input files this run reads exist, binary is executable
    Run:      executes gsflow with control file, captures stdout/stderr
    Post-run: GSFLOW error lines (GSFLOW often exits 0 after an error), end-of-run
              line, and the output files the control file switches on

Control-file rules follow the GSFLOW 2.4.0 source (prms/sm_read_control_file.f90,
gsflow/gsflow_prms.f90, gsflow/gsflow_sum.f90, gsflow/gsflow_modflow.f).
"""

import os
import sys
import argparse
import subprocess
import time
import re

# Server default build (the same path the KI preflight_check.py checks)
SERVER_DEFAULT_EXECUTABLE = ("KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/"
                             "GSFLOW/source/repo/autotest/gsflow")

# Engine defaults for control parameters this tool uses (sm_read_control_file.f90)
CONTROL_DEFAULTS = {
    "model_mode": "GSFLOW5", "data_file": "prms.data", "param_file": "prms.params",
    "model_output_file": "prms.out", "csv_output_file": "prms_summary.csv",
    "gsflow_output_file": "gsflow.out", "stat_var_file": "statvar.out",
    "var_save_file": "prms_ic.out", "var_init_file": "prms_ic.in",
    "modflow_name": "modflow.nam",
    "print_debug": 0, "csvON_OFF": 0, "gsf_rpt": 1, "statsON_OFF": 0,
    "save_vars_to_file": 0, "init_vars_from_file": 0,
}


def resolve_executable(user_path):
    """--executable, then $GSFLOW_BIN, then the server default. Returns (path, source).
    An explicit choice is used as given (and fails in validate_inputs if bad)."""
    for label, val in (("--executable", user_path), ("$GSFLOW_BIN", os.environ.get("GSFLOW_BIN"))):
        if val:
            return val, label
    return SERVER_DEFAULT_EXECUTABLE, "server default"


def read_control(control_file):
    """GSFLOW/PRMS control file -> {name: [values as text]}, read like the engine
    (prms/sm_read_control_file.f90): a block starts at a line whose first four
    characters are '####', then the name, the number of values (>= 1), the type
    (1 integer, 2 real, 4 text); text values are one per line; numbers are read
    list-directed (separated by blanks or commas, may span lines, r*v = r copies of v).
    Raises ValueError for a malformed or incomplete block."""
    with open(control_file) as f:
        lines = [l.rstrip("\n") for l in f]
    params = {}
    i = 0
    while i < len(lines):
        if lines[i][:4] != "####":
            i += 1
            continue
        start = i + 1
        try:
            name = lines[i + 1].strip()
            n = int(lines[i + 2].replace(",", " ").split()[0])
            ptype = int(lines[i + 3].replace(",", " ").split()[0])
        except (IndexError, ValueError):
            raise ValueError(f"{control_file}: malformed block at line {start}")
        if not name or n < 1 or ptype not in (1, 2, 4):
            raise ValueError(f"{control_file}: malformed block '{name}' at line {start} "
                             f"(number of values {n}, type {ptype})")
        i += 4
        if ptype == 4:
            vals = [l.strip() for l in lines[i:i + n]]
            if len(vals) < n or any(v[:4] == "####" for v in vals):
                raise ValueError(f"{control_file}: block '{name}' has fewer than {n} text values")
            i += n
        else:
            vals = []
            while len(vals) < n:
                if i >= len(lines) or lines[i][:4] == "####":
                    raise ValueError(f"{control_file}: block '{name}' has fewer than {n} values")
                # list-directed read: '!' starts a comment
                for tok in lines[i].split("!", 1)[0].replace(",", " ").split():
                    if len(vals) >= n:
                        break  # the read is complete; the rest of the line is ignored
                    if "*" in tok:
                        rep, _, v = tok.partition("*")
                        try:
                            vals.extend([v] * min(int(rep), n - len(vals)))
                        except ValueError:
                            raise ValueError(f"{control_file}: bad value '{tok}' in block '{name}'")
                    else:
                        vals.append(tok)
                i += 1
            for v in vals[:n]:
                try:
                    int(v) if ptype == 1 else float(v.replace("d", "e").replace("D", "e"))
                except ValueError:
                    raise ValueError(f"{control_file}: bad value '{v}' in block '{name}'")
            vals = vals[:n]
        params[name] = vals
    return params


def model_kind(params):
    """Model dispatch as in gsflow/gsflow_prms.f90:
    'prms_only' (PRMS*, DAILY: full PRMS run, PRMS_only active),
    'prms_pre' (FROST, CLIMATE, WRITE_CLIMATE, POTET, TRANSPIRE, CONVERT: PRMS_only
               pre-process modes that return before the PRMS summary),
    'modsim_prms' (MODSIM-PRMS, MODSIM-PRMS-LOOSE: PRMS runs, PRMS_only off),
    'coupled' (GSFLOW*, MODSIM-GSFLOW), 'modflow' (MODFLOW*, MODSIM-MODFLOW, MODSIM)."""
    vals = params.get("model_mode") or ["GSFLOW5"]
    mode = vals[0]
    if mode[:4] == "    " or not mode.strip():
        mode = "GSFLOW5"
    up = mode.strip()
    if up[:4] in ("PRMS", "prms") or up[:5] == "DAILY":
        return "prms_only"
    if up[:6] in ("GSFLOW", "gsflow") or up[:13] == "MODSIM-GSFLOW":
        return "coupled"
    if up[:7] in ("MODFLOW", "modflow") or up[:14] == "MODSIM-MODFLOW":
        return "modflow"
    if up[:11] == "MODSIM-PRMS":
        return "modsim_prms"
    if up[:6] == "MODSIM":
        return "modflow"
    return "prms_pre"


def control_flag(params, name, default):
    """Integer control value; the engine default only when the entry is absent.
    A present but unreadable value is an error (never a silent default)."""
    vals = params.get(name)
    if not vals:
        return default
    try:
        return int(vals[0])
    except ValueError:
        raise ValueError(f"control parameter {name}: not an integer: {vals[0]!r}")


def enabled_outputs(params):
    """Output files this run writes, by the engine's switches and defaults
    (sm_read_control_file.f90, gsflow_prms.f90, gsflow_sum.f90):
    [(param, file name as in the control file or the engine default)]."""
    defaults = {"model_output_file": "prms.out", "csv_output_file": "prms_summary.csv",
                "gsflow_output_file": "gsflow.out", "stat_var_file": "statvar.out",
                "var_save_file": "prms_ic.out"}
    kind = model_kind(params)
    prms_runs = kind in ("prms_only", "modsim_prms", "coupled")
    names = []
    if kind == "coupled":
        names.append("gsflow_output_file")
        if control_flag(params, "gsf_rpt", 1) == 1:
            names.append("csv_output_file")
    if kind == "prms_only" and control_flag(params, "csvON_OFF", 0) > 0:
        names.append("csv_output_file")
    if kind == "prms_pre":
        # CLIMATE, TRANSPIRE and POTET call summary_output (statvar); the others write
        # no summary file this tool can check
        mode = (params.get("model_mode") or [""])[0].strip().upper()
        if (mode.startswith(("CLIMATE", "TRANSPIRE", "POTET"))
                and control_flag(params, "statsON_OFF", 0) == 1):
            names.append("stat_var_file")
    if prms_runs:
        if control_flag(params, "print_debug", 0) > -2:
            names.append("model_output_file")
        if control_flag(params, "statsON_OFF", 0) == 1:
            names.append("stat_var_file")
        if control_flag(params, "save_vars_to_file", 0) == 1:
            names.append("var_save_file")
    return [(n, (params.get(n) or [defaults[n]])[0]) for n in names]


def _value(params, name):
    """First value of a control parameter as text, else the engine default."""
    vals = params.get(name)
    if vals:
        return vals[0]
    return str(CONTROL_DEFAULTS.get(name, ""))


def _flag(params, name):
    return control_flag(params, name, int(CONTROL_DEFAULTS.get(name, 0)))


def control_path(base_dir, fpath):
    """Path of a control-file entry, as GSFLOW opens it (relative to the run folder)."""
    return os.path.join(base_dir, fpath) if not os.path.isabs(fpath) else fpath


def run_dir_of(control_file, working_dir=None):
    """Folder GSFLOW runs in; relative paths in the control file are taken from it."""
    return os.path.abspath(working_dir or os.path.dirname(os.path.abspath(control_file)))


def validate_inputs(executable, control_file, source="--executable", working_dir=None):
    """Validate executable and control file before running."""
    errors = []

    if not os.path.isfile(executable):
        errors.append(f"GSFLOW executable not found ({source}): {executable}")
    elif not os.access(executable, os.X_OK):
        errors.append(f"GSFLOW binary not executable ({source}): {executable} (run: chmod +x)")

    if not os.path.isfile(control_file):
        errors.append(f"Control file not found: {control_file}")
        if errors:
            for e in errors:
                print(f"ERROR: {e}", file=sys.stderr)
            return False
        return True

    # Parse control file to check referenced files
    base_dir = run_dir_of(control_file, working_dir)
    try:
        referenced_files = parse_control_file_paths(control_file, base_dir)
        outputs = _output_files(control_file, base_dir)
    except ValueError as exc:
        errors.append(str(exc))
        referenced_files, outputs = [], []

    for fpath, param_name in referenced_files:
        if os.sep == "/" and "\\" in fpath:
            errors.append(f"Windows path in the control file: {fpath} (param: {param_name}); "
                          "GSFLOW on Linux cannot open it - rerun with --convert-windows-paths "
                          "(changes \\ to / in the control file and the MODFLOW name file, as "
                          "the official GSFLOW autotest does)")
        elif not os.path.isfile(fpath):
            errors.append(f"Referenced file missing: {fpath} (param: {param_name})")
    for param_name, fpath in outputs:
        if os.sep == "/" and "\\" in fpath:
            errors.append(f"Windows path in the control file: {fpath} (output param: {param_name}); "
                          "rerun with --convert-windows-paths")

    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        return False

    print(f"  Pre-run validation PASSED ({len(referenced_files)} referenced files verified)")
    return True


def parse_control_file_paths(control_file, base_dir):
    """
    Parse control file to extract the INPUT files this run reads.
    Returns list of (absolute_path, parameter_name) tuples.

    Output files (var_save_file, stat_var_file, *_output_file) are never inputs.
    PRMS inputs (data_file, param_file) only when PRMS runs; var_init_file only if
    init_vars_from_file > 0; tmax/tmin/precip/swrad/potet *_day files only if their
    module is climate_hru; modflow_name only when MODFLOW runs. Engine defaults are
    used for entries the control file leaves out.
    """
    params = read_control(control_file)
    kind = model_kind(params)
    referenced = []

    def add(name):
        vals = params.get(name) or [str(CONTROL_DEFAULTS[name])]
        for fpath in vals:
            if fpath:
                referenced.append((control_path(base_dir, fpath), name))

    if kind in ("prms_only", "modsim_prms", "coupled"):
        add("data_file")
        add("param_file")
        if _flag(params, "init_vars_from_file") > 0:
            add("var_init_file")
        day_files = {"tmax_day": "temp_module", "tmin_day": "temp_module",
                     "precip_day": "precip_module", "swrad_day": "solrad_module",
                     "potet_day": "et_module"}
        for name, module in day_files.items():
            if name in params and _value(params, module).strip() == "climate_hru":
                add(name)
    if kind in ("coupled", "modflow"):
        add("modflow_name")

    return referenced


def convert_windows_paths(control_file, base_dir):
    """Change '\\' to '/' in the control file and the MODFLOW name file it lists, in
    place, as the official GSFLOW autotest (t001_test.py) does on Linux. The first
    time, each original is kept byte for byte as <file>.winpaths.orig.
    Returns the files changed."""
    changed = []
    params = read_control(control_file)
    targets = [control_file]
    if model_kind(params) in ("coupled", "modflow"):
        targets.append(control_path(base_dir, _value(params, "modflow_name").replace("\\", "/")))
    for t in targets:
        if not os.path.isfile(t):
            raise ValueError(f"cannot convert, file not found: {t}")
        with open(t, "rb") as f:
            raw = f.read()
        if b"\\" not in raw:
            continue
        backup = t + ".winpaths.orig"
        if not os.path.exists(backup):
            with open(backup, "wb") as f:
                f.write(raw)
        with open(t, "wb") as f:
            f.write(raw.replace(b"\\", b"/"))
        changed.append(t)
    return changed


def run_model(executable, control_file, timeout=7200, working_dir=None):
    """
    Execute GSFLOW binary.

    Args:
        executable: path to gsflow binary
        control_file: path to control file
        timeout: max runtime in seconds (default 2 hours)
        working_dir: directory to run from (default: control file's directory)

    Returns:
        (return_code, stdout, stderr, elapsed_seconds)
    """
    if working_dir is None:
        working_dir = os.path.dirname(os.path.abspath(control_file))

    cmd = [os.path.abspath(executable), os.path.abspath(control_file)]
    print(f"  Running: {' '.join(cmd)}")
    print(f"  Working dir: {working_dir}")
    print(f"  Timeout: {timeout}s")

    start_time = time.time()
    try:
        result = subprocess.run(
            cmd,
            cwd=working_dir,
            capture_output=True,
            text=True,
            timeout=timeout
        )
        elapsed = time.time() - start_time
        return result.returncode, result.stdout, result.stderr, elapsed
    except subprocess.TimeoutExpired:
        elapsed = time.time() - start_time
        return -1, "", f"TIMEOUT after {timeout}s", elapsed
    except Exception as e:
        elapsed = time.time() - start_time
        return -2, "", str(e), elapsed


def _output_files(control_file, base_dir):
    """[(param, absolute path)] of the output files this run must write (engine
    switches and defaults, see enabled_outputs)."""
    params = read_control(control_file)
    return [(n, control_path(base_dir, f)) for n, f in enabled_outputs(params)]


def file_state(paths):
    """{path: (mtime_ns, size)} for the paths that exist now."""
    st = {}
    for p in paths:
        if os.path.isfile(p):
            s_ = os.stat(p)
            st[p] = (s_.st_mtime_ns, s_.st_size)
    return st


# GSFLOW error messages that do not stop the program with a non-zero code
_FATAL_PATTERNS = [r"^\s*ERROR\b", r"\*\*FIX input errors"]


def validate_outputs(control_file, stdout, stderr, return_code, before=None, working_dir=None):
    """
    Validate model run by checking:
    1. Return code
    2. GSFLOW's own error lines (GSFLOW often exits 0 after an error:
       "ERROR opening input file ...", "**FIX input errors in your Control/Parameter
       File to continue**"); the line "Please give careful consideration to fixing all
       ERROR and WARNING messages", printed in every run, is not an error
    3. End of run: MODFLOW modes "Normal termination of simulation" or the final
       "FAILED TO MEET SOLVER CONVERGENCE CRITERIA" summary (warning); PRMS-only
       "Normal completion of GSFLOW" or "Execution elapsed time" in the PRMS report
    4. Output files the control file switches on were written by this run
       (before = file_state() just before the run)
    """
    errors = []
    warnings = []
    stdout = stdout or ""

    # Check return code
    if return_code != 0:
        if return_code == -1:
            errors.append("Model run TIMED OUT")
        elif return_code == -2:
            errors.append(f"Model run FAILED: {stderr}")
        else:
            errors.append(f"Non-zero return code: {return_code}")

    # Check stderr for fatal errors
    if stderr:
        for line in stderr.split("\n"):
            if "error" in line.lower() or "fatal" in line.lower():
                errors.append(f"STDERR: {line.strip()}")

    error_lines = [l.strip() for l in stdout.split("\n")
                   if any(re.search(p, l, re.IGNORECASE) for p in _FATAL_PATTERNS)]
    for el in error_lines[:5]:
        errors.append(f"STDOUT error: {el}")

    base_dir = run_dir_of(control_file, working_dir)
    params = read_control(control_file)
    kind = model_kind(params)
    outputs = _output_files(control_file, base_dir)

    fresh = {}
    for param, abs_path in outputs:
        if not os.path.isfile(abs_path):
            errors.append(f"Expected output not written: {abs_path} ({param})")
            continue
        st = os.stat(abs_path)
        if before is not None and before.get(abs_path) == (st.st_mtime_ns, st.st_size):
            errors.append(f"Output not written by this run (unchanged): {abs_path} ({param})")
            continue
        fresh[param] = abs_path
        print(f"  Output file: {abs_path} ({st.st_size} bytes)")

    if return_code == 0 and not error_lines:
        if kind in ("coupled", "modflow"):
            nonconv = re.search(r"FAILED TO MEET SOLVER CONVERGENCE CRITERIA\s+\d+\s+TIME", stdout)
            if nonconv:
                warnings.append("MODFLOW solver failed to converge in some time steps "
                                f"({nonconv.group(0).strip()})")
            elif "Normal termination of simulation" not in stdout:
                errors.append("No 'Normal termination of simulation' line in GSFLOW output")
        elif kind == "prms_pre":
            # pre-process modes print no end-of-run line
            warnings.append("pre-process model_mode: no end-of-run line to check; "
                            "judged by return code, error lines and output files only")
        else:
            done = "Normal completion of GSFLOW" in stdout
            if not done and "model_output_file" in fresh:
                with open(fresh["model_output_file"], errors="replace") as fh:
                    done = "Execution elapsed time" in fh.read()
            quiet = _flag(params, "print_debug") <= -2
            if not done and quiet:
                # print_debug <= -2 writes neither marker: a summary file written by
                # this run is the evidence; with none switched on it cannot be checked
                if fresh:
                    done = True
                elif not outputs:
                    done = True
                    warnings.append("print_debug <= -2 and no summary output switched on: "
                                    "end of run cannot be confirmed")
            if not done:
                errors.append("No end-of-run evidence ('Normal completion of GSFLOW' on screen or "
                              "'Execution elapsed time' in the PRMS report)")

    # Report
    if warnings:
        for w in warnings:
            print(f"WARNING: {w}", file=sys.stderr)

    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        return False

    print("  Post-run validation PASSED")
    return True


def main():
    parser = argparse.ArgumentParser(description="Run GSFLOW model with validation")
    parser.add_argument("--executable", default=None,
                        help="Path to gsflow binary (else $GSFLOW_BIN, else the server default "
                             f"{SERVER_DEFAULT_EXECUTABLE})")
    parser.add_argument("--control-file", required=True, help="Path to control file")
    parser.add_argument("--timeout", type=int, default=7200, help="Max runtime seconds")
    parser.add_argument("--working-dir", default=None, help="Working directory")
    parser.add_argument("--convert-windows-paths", action="store_true",
                        help="Change \\ to / in the control file and the MODFLOW name file "
                             "(in place; originals kept as *.winpaths.orig), as the official "
                             "GSFLOW autotest does on Linux")
    args = parser.parse_args()

    executable, source = resolve_executable(args.executable)
    run_dir = run_dir_of(args.control_file, args.working_dir)

    print("=" * 60)
    print("GSFLOW Execution Wrapper")
    print("=" * 60)

    if args.convert_windows_paths:
        if not (os.path.isfile(executable) and os.access(executable, os.X_OK)):
            print(f"ERROR: GSFLOW executable not usable ({source}): {executable}", file=sys.stderr)
            sys.exit(1)
        try:
            for f in convert_windows_paths(args.control_file, run_dir):
                print(f"  Converted Windows paths: {f} (original: {f}.winpaths.orig)")
        except (OSError, ValueError) as exc:
            print(f"ERROR: Windows path conversion failed: {exc}", file=sys.stderr)
            sys.exit(1)

    # ── Step 1: Pre-run validation ──
    print(f"\n[1/3] Validating inputs")
    if not validate_inputs(executable, args.control_file, source, args.working_dir):
        sys.exit(1)
    print(f"  Executable ({source}): {executable}")

    # ── Step 2: Run model ──
    print(f"\n[2/3] Running GSFLOW")
    before = file_state([p for _, p in _output_files(args.control_file, run_dir)])
    rc, stdout, stderr, elapsed = run_model(
        executable, args.control_file, args.timeout, run_dir
    )
    print(f"  Completed in {elapsed:.1f}s (return code: {rc})")

    if stdout:
        # Print last 20 lines of stdout
        last_lines = stdout.strip().split("\n")[-20:]
        print("\n  --- Last 20 lines of stdout ---")
        for line in last_lines:
            print(f"  {line}")

    if stderr and rc != 0:
        print(f"\n  --- stderr ---")
        print(f"  {stderr[:500]}")

    # ── Step 3: Post-run validation ──
    print(f"\n[3/3] Validating outputs")
    success = validate_outputs(args.control_file, stdout, stderr, rc, before, args.working_dir)

    if success:
        print(f"\nGSFLOW run completed successfully in {elapsed:.1f}s")
    else:
        print(f"\nGSFLOW run completed with errors (elapsed: {elapsed:.1f}s)")
        sys.exit(1)


if __name__ == "__main__":
    main()
