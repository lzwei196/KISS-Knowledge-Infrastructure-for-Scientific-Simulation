#!/usr/bin/env python3
"""
run_epanet.py — Execute EPANET with preflight checks and output validation.

Wraps the runepanet CLI binary with:
- Preflight validation of .inp file (required sections, syntax checks)
- Binary discovery (build dir, system PATH, user-specified)
- Execution with timeout and progress monitoring
- Post-run output validation (report file checks, error detection)

Usage:
    python run_epanet.py \
        --inp network.inp \
        --rpt network.rpt \
        --out network.out \
        --binary /path/to/runepanet \
        --timeout 300

Pattern: validate → process → validate
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path


# ── Required sections in a valid .inp file ────────────────────────────────────
REQUIRED_SECTIONS = {"[JUNCTIONS]", "[OPTIONS]", "[TIMES]"}
RECOMMENDED_SECTIONS = {"[TITLE]", "[PIPES]", "[REPORT]", "[END]"}

# ── Known error codes ─────────────────────────────────────────────────────────
ERROR_CATEGORIES = {
    range(1, 100): "warning",
    range(100, 200): "syntax_error",
    range(200, 300): "data_error",
    range(300, 400): "file_error",
}


def find_binary(user_path=None):
    """Locate the runepanet binary.

    Search order:
    1. User-specified path
    2. Common build directories relative to source
    3. System PATH
    """
    candidates = []

    if user_path:
        candidates.append(user_path)

    # Common build locations
    script_dir = Path(__file__).resolve().parent
    for rel in [
        "../../source/repo/SRC_engines/build/src/run/runepanet",
        "../source/repo/SRC_engines/build/src/run/runepanet",
        "../../build/src/run/runepanet",
        "../build/src/run/runepanet",
        "./runepanet",
    ]:
        candidates.append(str(script_dir / rel))

    # Check work directory patterns
    work_dir = Path(os.getcwd())
    for rel in [
        "source/repo/SRC_engines/build/src/run/runepanet",
        "SRC_engines/build/src/run/runepanet",
        "build/src/run/runepanet",
    ]:
        candidates.append(str(work_dir / rel))

    # System PATH
    system_binary = shutil.which("runepanet")
    if system_binary:
        candidates.append(system_binary)

    for c in candidates:
        p = Path(c).resolve()
        if p.is_file() and os.access(str(p), os.X_OK):
            return str(p)

    return None


def validate_inp_file(inp_path):
    """Preflight validation of the .inp file.

    Checks:
    - File exists and is readable
    - Required sections present
    - No obvious syntax errors
    - Node/link counts are reasonable
    """
    errors = []
    warnings = []

    if not os.path.isfile(inp_path):
        errors.append(f"Input file not found: {inp_path}")
        return errors, warnings

    with open(inp_path, "r") as f:
        content = f.read()

    # Check for required sections
    found_sections = set(re.findall(r'\[([A-Z_]+)\]', content))
    found_sections_bracketed = {f"[{s}]" for s in found_sections}

    missing_required = REQUIRED_SECTIONS - found_sections_bracketed
    if missing_required:
        errors.append(f"Missing required sections: {missing_required}")

    missing_recommended = RECOMMENDED_SECTIONS - found_sections_bracketed
    if missing_recommended:
        warnings.append(f"Missing recommended sections: {missing_recommended}")

    # Count junctions
    junction_section = re.search(
        r'\[JUNCTIONS\](.*?)(?=\[|\Z)', content, re.DOTALL
    )
    if junction_section:
        junction_lines = [
            line.strip() for line in junction_section.group(1).split('\n')
            if line.strip() and not line.strip().startswith(';')
        ]
        n_junctions = len(junction_lines)
        if n_junctions == 0:
            errors.append("No junctions defined in [JUNCTIONS] section")
        else:
            print(f"  Junctions: {n_junctions}")

    # Check OPTIONS section for units
    options_section = re.search(
        r'\[OPTIONS\](.*?)(?=\[|\Z)', content, re.DOTALL
    )
    if options_section:
        opts = options_section.group(1)
        units_match = re.search(r'Units\s+(\S+)', opts, re.IGNORECASE)
        if units_match:
            print(f"  Flow units: {units_match.group(1)}")
        headloss_match = re.search(r'Headloss\s+(\S+)', opts, re.IGNORECASE)
        if headloss_match:
            print(f"  Headloss: {headloss_match.group(1)}")

    # Check TIMES section
    times_section = re.search(
        r'\[TIMES\](.*?)(?=\[|\Z)', content, re.DOTALL
    )
    if times_section:
        duration_match = re.search(
            r'Duration\s+(\S+)', times_section.group(1), re.IGNORECASE
        )
        if duration_match:
            print(f"  Duration: {duration_match.group(1)}")

    # Check file size
    fsize = os.path.getsize(inp_path)
    if fsize > 100_000_000:  # 100 MB
        warnings.append(f"Large input file ({fsize / 1e6:.1f} MB) — may be slow")

    return errors, warnings


def validate_output(rpt_path, out_path=None):
    """Post-run validation of output files.

    Checks:
    - Report file exists and contains results
    - No fatal error messages in report
    - Binary output file exists if requested
    """
    errors = []
    warnings = []

    # Check report file
    if not os.path.isfile(rpt_path):
        errors.append(f"Report file not created: {rpt_path}")
        return errors, warnings

    with open(rpt_path, "r") as f:
        content = f.read()

    # Check for error messages
    error_matches = re.findall(r'(Error|ERROR)\s+(\d+)', content)
    for match in error_matches:
        code = int(match[1])
        errors.append(f"EPANET Error {code} in report file")

    # Check for warning messages
    warning_matches = re.findall(r'(Warning|WARNING)', content)
    if warning_matches:
        warnings.append(f"{len(warning_matches)} warnings in report file")

    # Check for results
    if "Node Results" in content:
        print(f"  [OK] Node results found in report")
    else:
        warnings.append("No node results found in report")

    if "Link Results" in content:
        print(f"  [OK] Link results found in report")
    else:
        warnings.append("No link results found in report")

    # Check binary output
    if out_path and out_path.strip():
        if os.path.isfile(out_path):
            out_size = os.path.getsize(out_path)
            print(f"  [OK] Binary output: {out_path} ({out_size} bytes)")

            # Validate magic number
            with open(out_path, "rb") as f:
                import struct
                magic = struct.unpack('i', f.read(4))[0]
                if magic != 516114521:
                    errors.append(
                        f"Invalid binary output magic number: {magic} "
                        f"(expected 516114521)"
                    )
        else:
            warnings.append(f"Binary output file not created: {out_path}")

    return errors, warnings


def run_epanet(binary_path, inp_path, rpt_path, out_path=None, timeout=300):
    """Execute EPANET and return exit code and output."""
    cmd = [binary_path, inp_path, rpt_path]
    if out_path and out_path.strip():
        cmd.append(out_path)

    print(f"\n[EXEC] {' '.join(cmd)}")
    start_time = time.time()

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=os.path.dirname(os.path.abspath(inp_path)) or ".",
        )
        elapsed = time.time() - start_time

        print(f"\n[OUTPUT] (exit code: {result.returncode}, {elapsed:.1f}s)")
        if result.stdout:
            print(result.stdout[:2000])
        if result.stderr:
            print(f"[STDERR] {result.stderr[:1000]}")

        return result.returncode, result.stdout, result.stderr, elapsed

    except subprocess.TimeoutExpired:
        elapsed = time.time() - start_time
        print(f"\n[TIMEOUT] EPANET exceeded {timeout}s timeout")
        return -1, "", f"Timeout after {timeout}s", elapsed

    except FileNotFoundError:
        print(f"\n[ERROR] Binary not found: {binary_path}")
        return -2, "", f"Binary not found: {binary_path}", 0


def main():
    parser = argparse.ArgumentParser(
        description="Run EPANET with preflight checks and output validation"
    )
    parser.add_argument("--inp", required=True, help="Input .inp file")
    parser.add_argument("--rpt", required=True, help="Output report .rpt file")
    parser.add_argument("--out", default="", help="Binary output .out file (optional)")
    parser.add_argument("--binary", default=None,
                        help="Path to runepanet binary (auto-detected if omitted)")
    parser.add_argument("--timeout", type=int, default=300,
                        help="Execution timeout in seconds (default: 300)")
    parser.add_argument("--skip-preflight", action="store_true",
                        help="Skip input file validation")

    args = parser.parse_args()

    # ── Step 1: Find binary ───────────────────────────────────────────────────
    print("=" * 60)
    print("EPANET Execution Wrapper")
    print("=" * 60)

    binary = find_binary(args.binary)
    if not binary:
        print("[ERROR] Could not find runepanet binary")
        print("  Searched: user path, build directories, system PATH")
        print("  Use --binary /path/to/runepanet to specify manually")
        sys.exit(1)
    print(f"\n[OK] Binary: {binary}")

    # ── Step 2: Preflight validation ──────────────────────────────────────────
    if not args.skip_preflight:
        print(f"\n[PREFLIGHT] Validating: {args.inp}")
        errors, warnings = validate_inp_file(args.inp)

        for w in warnings:
            print(f"  [WARN] {w}")
        for e in errors:
            print(f"  [ERR]  {e}")

        if errors:
            print("\n[ABORT] Preflight validation failed")
            sys.exit(1)

        print("  [OK] Preflight passed")

    # ── Step 3: Set LD_LIBRARY_PATH for shared library ────────────────────────
    binary_dir = os.path.dirname(binary)
    solver_dir = os.path.join(os.path.dirname(binary_dir), "solver")
    if os.path.isdir(solver_dir):
        ld_path = os.environ.get("LD_LIBRARY_PATH", "")
        os.environ["LD_LIBRARY_PATH"] = f"{solver_dir}:{ld_path}"
        print(f"  [OK] LD_LIBRARY_PATH includes: {solver_dir}")

    # ── Step 4: Run EPANET ────────────────────────────────────────────────────
    exit_code, stdout, stderr, elapsed = run_epanet(
        binary, args.inp, args.rpt, args.out, args.timeout
    )

    # ── Step 5: Post-run validation ───────────────────────────────────────────
    print(f"\n[POST-RUN] Validating outputs")
    errors, warnings = validate_output(args.rpt, args.out)

    for w in warnings:
        print(f"  [WARN] {w}")
    for e in errors:
        print(f"  [ERR]  {e}")

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{'=' * 60}")
    if exit_code == 0 and not errors:
        print(f"[SUCCESS] EPANET completed in {elapsed:.1f}s")
        print(f"  Report: {args.rpt}")
        if args.out:
            print(f"  Binary: {args.out}")
        sys.exit(0)
    elif exit_code < 100 and not errors:
        print(f"[WARNING] EPANET completed with warnings in {elapsed:.1f}s")
        sys.exit(0)
    else:
        print(f"[FAILED] EPANET exit code: {exit_code}")
        sys.exit(exit_code if exit_code > 0 else 1)


if __name__ == "__main__":
    main()
