#!/usr/bin/env python3
"""
SWAP model execution wrapper with preflight checks and output validation.

Runs the SWAP binary in the specified working directory, validates that
required input files exist, and checks output files for completeness.

Usage:
    python run_swap.py \\
        --binary /path/to/swap \\
        --work-dir /path/to/case/ \\
        --swp-file swap.swp
"""

import argparse
import hashlib
import os
import subprocess
import sys
import time
import re
from pathlib import Path

# The SWAP executable this KI is validated against: the Meson build of the
# pinned v4.2.0 source tree. Recorded so a run's evidence is attributable.
PINNED_SWAP_BINARY = ("KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/"
                      "_work/SWAP/source/repo/builddir/swap")
PINNED_SWAP_SHA256 = \
    "a696efc5344daa53b3ddeebd3664656d0822959a5b2f4f863efc710469f1cf97"


def resolve_binary(requested=None, allow_unpinned=False):
    """
    Resolve the SWAP executable, FAILING LOUDLY rather than substituting.

    Rules:
      * default is the pinned build (PINNED_SWAP_BINARY);
      * any other --binary needs an explicit --allow-unpinned-binary;
      * $PATH is NEVER searched and no fallback is ever chosen — a stray
        `swap` on PATH could be any program, and a metric produced by an
        unidentified binary is unattributable evidence;
      * missing / non-executable / non-ELF aborts with exit status 2;
      * the sha256 actually executed is printed every run, and a mismatch
        against the recorded pin is reported as a loud WARNING (a legitimate
        rebuild changes the hash — a silent swap must still be visible).
    """
    path = os.path.abspath(requested or PINNED_SWAP_BINARY)
    pinned = os.path.abspath(PINNED_SWAP_BINARY)

    if path != pinned and not allow_unpinned:
        print(f"ERROR: --binary is not the pinned SWAP build.\n"
              f"       requested: {path}\n"
              f"       pinned:    {pinned}\n"
              f"       Pass --allow-unpinned-binary to run a different build "
              f"deliberately.", file=sys.stderr)
        sys.exit(2)

    if not os.path.isfile(path):
        print(f"ERROR: SWAP binary not found: {path}\n"
              f"       This wrapper never searches $PATH and never substitutes "
              f"another executable.\n"
              f"       Build the pinned source first:\n"
              f"         meson setup builddir && meson compile -C builddir\n"
              f"       (SWAP v4.2.0, github.com/SWAP-model/swap)",
              file=sys.stderr)
        sys.exit(2)
    if not os.access(path, os.X_OK):
        print(f"ERROR: SWAP binary is not executable: {path}", file=sys.stderr)
        sys.exit(2)

    with open(path, "rb") as f:
        magic = f.read(4)
        f.seek(0)
        digest = hashlib.sha256(f.read()).hexdigest()
    if magic != b"\x7fELF":
        print(f"ERROR: {path} is not an ELF executable (magic "
              f"{magic!r}) — refusing to run it as SWAP", file=sys.stderr)
        sys.exit(2)

    tag = "PINNED" if path == pinned else "UNPINNED (--allow-unpinned-binary)"
    print(f"[OK] SWAP binary [{tag}]: {path}")
    print(f"     sha256 {digest}")
    if digest != PINNED_SWAP_SHA256:
        print(f"WARNING: this binary's sha256 differs from the recorded pin "
              f"{PINNED_SWAP_SHA256} — it is a different build than the one "
              f"the KI's validated numbers came from")
    return path


def swap_run_succeeded(result, work_dir):
    """
    Decide whether a SWAP invocation actually succeeded.

    SWAP 4.2.0 signals NORMAL COMPLETION with exit code 100
    (src/swap_main.f90 `Call Exit(100)`), so a plain `returncode == 0` test
    reports every successful run as a failure and skips output validation
    entirely (dt_018 / CDK #9).

    Success is rc == 0, or rc == 100 confirmed by either 'normal completion'
    on stdout or a *.ok file written into the work directory.
    """
    rc = result.get("returncode")
    if rc == 0:
        return True
    if rc != 100:
        return False

    stdout = (result.get("stdout") or "").lower()
    if "normal completion" in stdout:
        return True
    try:
        for f_name in os.listdir(work_dir):
            if f_name.lower().endswith(".ok"):
                return True
    except OSError:
        pass
    return False


def validate_inputs(binary, work_dir, swp_file):
    """
    Pre-flight checks before running SWAP.

    Verifies:
    1. Binary exists and is executable
    2. Working directory exists
    3. Main .swp file exists
    4. Referenced input files (.met, .crp, .dra, .bbc) exist
    5. All filenames are lowercase (Linux requirement)
    """
    errors = []
    warnings = []

    # Check binary
    if not os.path.isfile(binary):
        errors.append(f"SWAP binary not found: {binary}")
    elif not os.access(binary, os.X_OK):
        errors.append(f"SWAP binary not executable: {binary}")

    # Check work directory
    if not os.path.isdir(work_dir):
        errors.append(f"Working directory not found: {work_dir}")
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        return False

    # Check .swp file
    swp_path = os.path.join(work_dir, swp_file)
    if not os.path.isfile(swp_path):
        errors.append(f"Main input file not found: {swp_path}")
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        return False

    # Parse .swp file for referenced files
    with open(swp_path, "r") as f:
        content = f.read()

    # Extract METFIL
    met_match = re.search(r"METFIL\s*=\s*'([^']+)'", content)
    if met_match:
        met_file = met_match.group(1)
        # Check in PATHATM or work_dir
        pathatm_match = re.search(r"PATHATM\s*=\s*'([^']+)'", content)
        pathatm = pathatm_match.group(1) if pathatm_match else "./"
        if pathatm.startswith("./"):
            pathatm = work_dir

        met_path = os.path.join(pathatm, met_file)
        if not os.path.isfile(met_path):
            # Try without explicit extension — SWAP may append year extension
            found = False
            for ext in [".met", ""]:
                test = met_path + ext
                if os.path.isfile(test):
                    found = True
                    break
            if not found:
                errors.append(f"Meteorological file not found: {met_path}")

    # Extract crop files
    crop_matches = re.findall(r"CROPFIL\s*=\s*'([^']+)'", content)
    # Also from table format
    crop_table = re.findall(r"'(\w+)'\s+\d+\s*$", content, re.MULTILINE)
    for cf in set(crop_matches + crop_table):
        crp_path = os.path.join(work_dir, cf + ".crp")
        if not os.path.isfile(crp_path):
            pathcrop_match = re.search(r"PATHCROP\s*=\s*'([^']+)'", content)
            pathcrop = pathcrop_match.group(1).replace("./", work_dir + "/") if pathcrop_match else work_dir
            crp_path = os.path.join(pathcrop, cf + ".crp")
            if not os.path.isfile(crp_path):
                warnings.append(f"Crop file not found: {cf}.crp")

    # Extract drainage file — only relevant when drainage is switched on.
    # SWAP never opens DRFIL when SWDRA = 0, so warning about a missing .dra
    # there is pure noise.
    swdra_match = re.search(r"^[ \t]*SWDRA[ \t]*=[ \t]*(\d+)", content, re.MULTILINE)
    swdra = int(swdra_match.group(1)) if swdra_match else 0
    dra_match = re.search(r"DRFIL\s*=\s*'([^']+)'", content)
    if swdra != 0 and dra_match:
        dra_file = dra_match.group(1) + ".dra"
        dra_path = os.path.join(work_dir, dra_file)
        if not os.path.isfile(dra_path):
            errors.append(f"SWDRA = {swdra} but drainage file not found: {dra_file}")

    # Check for uppercase filenames (Linux trap)
    for f_name in os.listdir(work_dir):
        if f_name != f_name.lower() and not f_name.startswith("."):
            warnings.append(f"Uppercase filename detected (Linux issue): {f_name}")

    for w in warnings:
        print(f"WARNING: {w}")
    for e in errors:
        print(f"ERROR: {e}", file=sys.stderr)

    if errors:
        print(f"[FAIL] Preflight check failed with {len(errors)} errors")
        return False
    print(f"[OK] Preflight checks passed ({len(warnings)} warnings)")
    return True


def run_swap(binary, work_dir, swp_file, timeout=300):
    """
    Execute SWAP binary.

    Parameters
    ----------
    binary : str
        Path to SWAP executable
    work_dir : str
        Working directory containing input files
    swp_file : str
        Name of main .swp input file
    timeout : int
        Maximum runtime in seconds

    Returns
    -------
    dict : Execution result with returncode, stdout, stderr, elapsed
    """
    print(f"[RUN] Starting SWAP: {binary}")
    print(f"      Working dir: {work_dir}")
    print(f"      Config file: {swp_file}")

    start_time = time.time()

    try:
        result = subprocess.run(
            [binary],
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        elapsed = time.time() - start_time

        output = {
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "elapsed_seconds": round(elapsed, 2),
        }

        if swap_run_succeeded(output, work_dir):
            print(f"[OK] SWAP completed successfully in {elapsed:.1f}s "
                  f"(exit code {result.returncode})")
        else:
            print(f"[FAIL] SWAP exited with code {result.returncode}")
            if result.stderr:
                print(f"STDERR: {result.stderr[:500]}")
            if result.stdout:
                print(f"STDOUT: {result.stdout[:500]}")

        return output

    except subprocess.TimeoutExpired:
        elapsed = time.time() - start_time
        print(f"[FAIL] SWAP timed out after {timeout}s")
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": f"Timeout after {timeout}s",
            "elapsed_seconds": round(elapsed, 2),
        }
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"[FAIL] SWAP execution error: {e}")
        return {
            "returncode": -2,
            "stdout": "",
            "stderr": str(e),
            "elapsed_seconds": round(elapsed, 2),
        }


def validate_outputs(work_dir, swp_file):
    """
    Post-execution validation of SWAP output files.

    Checks:
    1. Output files were created (.blc, .inc, .vap, etc.)
    2. Water balance closure (from .blc file)
    3. No error files (.dwb.csv)
    """
    errors = []
    warnings = []

    # Parse OUTFIL from .swp
    swp_path = os.path.join(work_dir, swp_file)
    outfil = "result"
    with open(swp_path, "r") as f:
        for line in f:
            m = re.search(r"OUTFIL\s*=\s*'([^']+)'", line)
            if m:
                outfil = m.group(1)
                break

    # Check expected output files
    expected = {
        ".blc": "Detailed water balance",
        ".inc": "Water balance increments",
    }

    # Also check optional files based on switches
    with open(swp_path, "r") as f:
        content = f.read()

    switch_file_map = {
        "SWVAP = 1": (".vap", "Soil profiles"),
        "SWBAL = 1": (".bal", "Yearly water balance"),
        "SWWBA = 1": (".wba", "Daily water balance"),
        "SWSBA = 1": (".sba", "Solute balance"),
        "SWATE = 1": (".ate", "Temperature profiles"),
    }

    for switch, (ext, desc) in switch_file_map.items():
        if switch.replace(" ", "") in content.replace(" ", ""):
            expected[ext] = desc

    for ext, desc in expected.items():
        fpath = os.path.join(work_dir, outfil + ext)
        if os.path.isfile(fpath):
            size = os.path.getsize(fpath)
            if size == 0:
                warnings.append(f"{outfil}{ext} is empty (0 bytes)")
            else:
                print(f"  [OK] {outfil}{ext} ({size:,} bytes) — {desc}")
        else:
            warnings.append(f"Expected output not found: {outfil}{ext} ({desc})")

    # Check for error files
    for f_name in os.listdir(work_dir):
        if f_name.lower().endswith(".dwb.csv"):
            errors.append(f"Water balance error file found: {f_name}")

    # Parse water balance from .blc if available
    blc_path = os.path.join(work_dir, outfil + ".blc")
    if os.path.isfile(blc_path):
        try:
            with open(blc_path, "r") as f:
                blc_content = f.read()
            # Look for Sum lines
            sum_in = re.findall(r"Sum\s*:\s*([\d.]+)", blc_content)
            if len(sum_in) >= 2:
                s_in = float(sum_in[0])
                s_out = float(sum_in[1])
                diff = abs(s_in - s_out)
                print(f"  [INFO] Water balance: In={s_in:.2f} cm, Out={s_out:.2f} cm, "
                      f"Diff={diff:.2f} cm")
                if diff > 1.0:
                    warnings.append(
                        f"Large water balance discrepancy: {diff:.2f} cm "
                        f"(check storage change)"
                    )
        except Exception as e:
            warnings.append(f"Could not parse .blc file: {e}")

    for w in warnings:
        print(f"WARNING: {w}")
    for e in errors:
        print(f"ERROR: {e}", file=sys.stderr)

    if errors:
        print(f"[FAIL] Output validation failed with {len(errors)} errors")
        return False
    print(f"[OK] Output validation passed ({len(warnings)} warnings)")
    return True


def main():
    parser = argparse.ArgumentParser(description="Run SWAP model with validation")
    parser.add_argument("--binary", type=str, default=None,
                        help="Path to the SWAP executable (default: the pinned "
                             "build, see PINNED_SWAP_BINARY)")
    parser.add_argument("--allow-unpinned-binary", action="store_true",
                        help="Permit a --binary other than the pinned build; "
                             "the substitution is reported on stdout")
    parser.add_argument("--work-dir", type=str, required=True,
                        help="Working directory with input files")
    parser.add_argument("--swp-file", type=str, default="swap.swp",
                        help="Name of main .swp configuration file")
    parser.add_argument("--timeout", type=int, default=300,
                        help="Maximum runtime in seconds")
    parser.add_argument("--skip-preflight", action="store_true",
                        help="Skip preflight validation")
    args = parser.parse_args()

    # Binary resolution happens FIRST, before --skip-preflight can skip
    # anything: an unidentified or absent executable must never reach
    # subprocess.run().
    binary = resolve_binary(args.binary,
                            allow_unpinned=args.allow_unpinned_binary)

    # Preflight
    if not args.skip_preflight:
        if not validate_inputs(binary, args.work_dir, args.swp_file):
            sys.exit(1)

    # Execute
    result = run_swap(binary, args.work_dir, args.swp_file, args.timeout)

    if not swap_run_succeeded(result, args.work_dir):
        sys.exit(1)

    # Validate outputs
    if not validate_outputs(args.work_dir, args.swp_file):
        sys.exit(1)


if __name__ == "__main__":
    main()
