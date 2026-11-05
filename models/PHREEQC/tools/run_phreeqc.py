#!/usr/bin/env python3
"""
Execution wrapper for PHREEQC binary.

Performs preflight validation, runs the model, and captures exit status
and diagnostic output.

Usage:
    python3 run_phreeqc.py --binary ./phreeqc --input model.pqi \
        --output model.pqo --database phreeqc.dat

Binary lookup: --binary, else $PHREEQC_BIN, else the server default (the same
binary preflight_check.py checks). An explicit value that is not an executable
file is an error (no fallback).
File paths (--input/--output/--database/--screen-log/--json-output) are taken
relative to the directory the tool is started from.
Exit code: 0 only when PHREEQC finished without error and wrote a non-empty
output; 1 otherwise (the JSON result is still written first).
"""
import argparse
import json
import os
import subprocess
import sys
import time
import re

DEFAULT_BINARY = (
    "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/"
    "PHREEQC/source/repo/build/phreeqc"
)
# Text reads: PHREEQC databases (phreeqc.dat, pitzer.dat, Amm.dat, ...) contain
# Latin-1 bytes (e.g. 0xb0 degree sign); latin-1 never fails and keeps ASCII keywords.
TEXT_ENCODING = "latin-1"


def resolve_binary(arg_binary):
    """--binary, else $PHREEQC_BIN, else the server default. Returns (path, source)."""
    if arg_binary is not None:
        return arg_binary, "--binary"
    env_bin = os.environ.get("PHREEQC_BIN")
    if env_bin is not None:
        return env_bin, "PHREEQC_BIN"
    return DEFAULT_BINARY, "server default"


def validate_inputs(args):
    """Preflight checks before execution."""
    errors = []
    warnings = []

    # Check binary exists and is executable
    if not args.binary or not os.path.isfile(args.binary):
        errors.append(f"PHREEQC binary not found: {args.binary!r} (from {args.binary_source})")
    elif not os.access(args.binary, os.X_OK):
        errors.append(f"PHREEQC binary not executable: {args.binary} (from {args.binary_source})")

    # Check input file
    if not os.path.isfile(args.input):
        errors.append(f"Input file not found: {args.input}")
    else:
        # Quick validation of input file
        with open(args.input, "r", encoding=TEXT_ENCODING) as f:
            content = f.read()

        # Check for at least one keyword block
        keywords = ["SOLUTION", "EQUILIBRIUM_PHASES", "REACTION", "KINETICS",
                     "TRANSPORT", "MIX", "EXCHANGE", "SURFACE", "INVERSE_MODELING",
                     "GAS_PHASE", "SOLID_SOLUTION"]
        found_keywords = [kw for kw in keywords if kw in content.upper()]
        if not found_keywords:
            errors.append("Input file contains no recognized PHREEQC keywords")

        # Check for SOLUTION block (almost always required)
        if "SOLUTION" not in content.upper():
            warnings.append("No SOLUTION block found - most simulations require one")

        # Check for END keyword
        if "END" not in content.upper():
            warnings.append("No END keyword found - PHREEQC may not process all blocks")

        # Check for DATABASE keyword in input
        db_match = re.search(r'^DATABASE\s+(.+)$', content, re.MULTILINE | re.IGNORECASE)
        if db_match:
            db_in_input = db_match.group(1).strip()
            warnings.append(f"DATABASE keyword found in input file: {db_in_input}. "
                          f"This overrides the --database argument.")

    # Check database file
    if not os.path.isfile(args.database):
        errors.append(f"Database file not found: {args.database}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors, "warnings": warnings}),
              file=sys.stderr)
        sys.exit(1)

    return warnings


def _master_species(path):
    """Element names from SOLUTION_MASTER_SPECIES blocks of a database or input file."""
    elements = set()
    with open(path, "r", encoding=TEXT_ENCODING) as f:
        in_master = False
        for line in f:
            stripped = line.strip()
            if stripped.upper().startswith("SOLUTION_MASTER_SPECIES"):
                in_master = True
                continue
            if in_master:
                if stripped and not stripped.startswith("#"):
                    if stripped.upper() in ("SOLUTION_SPECIES", "PHASES", "EXCHANGE_MASTER_SPECIES",
                                            "SURFACE_MASTER_SPECIES", "END"):
                        in_master = False
                        continue
                    parts = stripped.split()
                    if parts:
                        elem = parts[0]
                        if not elem.startswith("#"):
                            elements.add(elem.split("(")[0])  # Strip redox state
    return elements


def check_element_coverage(input_file, database_file):
    """Check if all elements in SOLUTION blocks exist in the database."""
    warnings = []

    # Read master species of the database and of the input file itself
    # (an input may define new elements in its own SOLUTION_MASTER_SPECIES block)
    db_elements = set()
    for species_file in (database_file, input_file):
        db_elements |= _master_species(species_file)

    # Read input elements from SOLUTION blocks
    input_elements = set()
    with open(input_file, "r", encoding=TEXT_ENCODING) as f:
        in_solution = False
        for line in f:
            stripped = line.strip()
            # "SOLUTION n ..." only, not SOLUTION_MASTER_SPECIES / SOLUTION_SPECIES / ...
            if re.match(r"SOLUTION(\s|$)", stripped.upper()):
                in_solution = True
                continue
            if in_solution:
                if stripped.upper() in ("END", "") or any(
                    stripped.upper().startswith(kw) for kw in
                    ["EQUILIBRIUM", "EXCHANGE", "SURFACE", "KINETICS",
                     "TRANSPORT", "MIX", "REACTION", "GAS_PHASE",
                     "SOLUTION", "SELECTED_OUTPUT", "PRINT", "INVERSE",
                     "SOLID_SOLUTION", "RATES", "TITLE", "DATABASE"]
                ):
                    in_solution = False
                    continue
                parts = stripped.split()
                if parts and not parts[0].startswith("#"):
                    elem_name = parts[0]
                    if elem_name.lower() not in ("temp", "ph", "pe", "density",
                                                  "units", "redox", "water",
                                                  "-water", "-temp", "-ph", "-pe",
                                                  "-density", "-units", "-redox",
                                                  "pressure", "-pressure"):
                        input_elements.add(elem_name.split("(")[0])

    # Check coverage
    missing = input_elements - db_elements
    if missing:
        warnings.append(
            f"Elements in input but NOT in database: {sorted(missing)}. "
            f"PHREEQC will error. Switch to a database that includes these elements."
        )

    return warnings


def process(args, preflight_warnings):
    """Run PHREEQC and capture output."""
    results = {
        "status": "success",
        "warnings": preflight_warnings,
        "command": None,
        "exit_code": None,
        "runtime_seconds": None,
        "output_file": args.output,
    }

    # Check element coverage
    coverage_warnings = check_element_coverage(args.input, args.database)
    results["warnings"].extend(coverage_warnings)

    # Build command
    cmd = [args.binary, args.input, args.output, args.database]
    if args.screen_log:
        cmd.append(args.screen_log)
    results["command"] = " ".join(cmd)

    # Run
    start = time.time()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=args.timeout,
            cwd=args.workdir or os.path.dirname(args.input) or ".",
        )
        elapsed = time.time() - start
        results["exit_code"] = proc.returncode
        results["runtime_seconds"] = round(elapsed, 3)
        results["stdout"] = proc.stdout[:2000] if proc.stdout else ""
        results["stderr"] = proc.stderr[:2000] if proc.stderr else ""

        if proc.returncode != 0:
            results["status"] = "error"
            results["errors"] = [f"PHREEQC exited with code {proc.returncode}"]

            # Parse error messages from output
            if proc.stderr:
                error_lines = [l for l in proc.stderr.splitlines()
                              if "error" in l.lower() or "ERROR" in l]
                if error_lines:
                    results["error_details"] = error_lines[:10]

    except subprocess.TimeoutExpired:
        elapsed = time.time() - start
        results["status"] = "error"
        results["errors"] = [f"PHREEQC timed out after {args.timeout}s"]
        results["runtime_seconds"] = round(elapsed, 3)
    except FileNotFoundError:
        results["status"] = "error"
        results["errors"] = [f"Binary not found: {args.binary}"]

    return results


def validate_outputs(results, args):
    """Post-run validation."""
    if results["status"] != "success":
        return results

    # Check output file was created
    if not os.path.isfile(args.output):
        results["status"] = "error"
        results.setdefault("errors", []).append(
            f"Output file was not created despite exit code 0: {args.output}")
        return results

    output_size = os.path.getsize(args.output)
    results["output_size_bytes"] = output_size

    if output_size == 0:
        results["status"] = "error"
        results.setdefault("errors", []).append(f"Output file is empty: {args.output}")
        return results

    # Scan the whole output for PHREEQC's own error marker ("ERROR: ...").
    # (A plain "error" substring also matches normal lines such as
    # "Percent error, 100*(Cat-|An|)/(Cat+|An|)".)
    error_lines = []
    with open(args.output, "r", encoding=TEXT_ENCODING) as f:
        for line in f:
            if line.lstrip().startswith("ERROR:"):
                error_lines.append(line.strip())
    if error_lines:
        results["status"] = "error"
        results.setdefault("errors", []).append(
            f"PHREEQC output contains {len(error_lines)} ERROR line(s)")
        results["error_details"] = error_lines[:10]

    # Check for selected output files
    sel_files = []
    input_dir = os.path.dirname(args.input) or "."
    for f in os.listdir(input_dir):
        if f.endswith(".sel") or f.endswith(".tsv"):
            sel_files.append(f)
    if sel_files:
        results["selected_output_files"] = sel_files

    return results


def main():
    parser = argparse.ArgumentParser(description="PHREEQC execution wrapper")
    parser.add_argument("--binary", default=None,
                        help="Path to phreeqc binary (default: $PHREEQC_BIN, else the server build "
                             + DEFAULT_BINARY + ")")
    parser.add_argument("--input", required=True, help="Input file (.pqi)")
    parser.add_argument("--output", required=True, help="Output file (.pqo)")
    parser.add_argument("--database", required=True, help="Thermodynamic database (.dat)")
    parser.add_argument("--screen-log", default=None, help="Screen output log file")
    parser.add_argument("--workdir", default=None, help="Working directory for execution")
    parser.add_argument("--timeout", type=int, default=3600, help="Timeout in seconds (default 3600)")
    parser.add_argument("--json-output", default=None, help="Path for JSON result summary")

    args = parser.parse_args()
    args.binary, args.binary_source = resolve_binary(args.binary)
    # One meaning for relative paths: the directory the tool is started from
    # (validation and PHREEQC, which runs in --workdir, then see the same files).
    for name in ("binary", "input", "output", "database", "screen_log", "json_output"):
        value = getattr(args, name)
        if value:
            setattr(args, name, os.path.abspath(value))
    warnings = validate_inputs(args)
    results = process(args, warnings)
    results = validate_outputs(results, args)

    if args.json_output:
        os.makedirs(os.path.dirname(args.json_output) or ".", exist_ok=True)
        with open(args.json_output, "w") as f:
            json.dump(results, f, indent=2)
    else:
        print(json.dumps(results, indent=2))

    if results.get("status") != "success":
        print(f"PHREEQC run FAILED: {results.get('errors')}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
