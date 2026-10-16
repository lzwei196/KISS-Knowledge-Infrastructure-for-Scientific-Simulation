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
import glob
import hashlib
import os
import subprocess
import sys
import time
import re
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _ttutil_swp_reader import (read_swp, SwpSyntaxError, MISSING,  # noqa: E402
                               MISSING_INT, MISSING_STR)

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

    A fatal input error (e.g. "Fatal irdat, no input date within simulation
    period") also exits with code 0, after writing only the log. So the exit
    code alone proves nothing: success is rc 0 or 100 AND SWAP's own
    ' Swap normal completion!' line on stdout (src/swap_main.f90), which is
    written only after every rerun finished. A *.ok file is not accepted as
    proof: SWAP deletes only 'Swap.ok' at start, so an old 'swap.ok' left in
    the folder by an earlier run survives a failed run.

    The line must be SWAP's own final line, exactly: swap_main.f90 writes
    ' Swap normal completion!' with format '(a)' and then calls Exit(100)
    at once, so it is the last non-blank line on stdout. A phrase found
    anywhere else is not proof: with SWSCRE = 2 SWAP echoes the PROJECT
    text to the screen, so PROJECT = 'Swap normal completion ...' followed
    by a fatal error would otherwise pass.
    """
    rc = result.get("returncode")
    if rc not in (0, 100):
        return False
    lines = [ln for ln in (result.get("stdout") or "").splitlines()
             if ln.strip()]
    return bool(lines) and lines[-1].strip() == "Swap normal completion!"


def _check_referenced_files(work_dir, keys, errors, warnings):
    """Check the met, crop and drainage files the .swp points to."""
    # Meteorological file(s). SWAP lowercases METFIL (readswap.f90 l.403).
    # A relative PATHATM is relative to work_dir (SWAP's cwd), sub-folders
    # included. Two read modes:
    #  * one file: METFIL has .met (and, after SWAP's switch overrides,
    #    no SWMETDETAIL=1 / SWRAIN=1,3).
    #    MeteoInOneFile builds fin = trim(pathatm)//trim(metfil) in a
    #    character(len=80) and opens it with a plain Fortran OPEN
    #    (readmeteo.f90 l.410/428, iReadType = 2), so PATHATM keeps its case
    #    and a name longer than 80 bytes is cut off.
    #  * yearly files trim(pathatm)//trim(metfil)//'.'//YYY (readmeteo.f90
    #    l.84-85), opened by TTUTIL RDINIT, which lowercases the whole name
    #    (swap_file_path).
    metfil = _str(keys, "metfil").rstrip(" ").translate(_UPPER_TO_LOWER)
    if metfil:
        pathatm = _str(keys, "pathatm").rstrip(" ")
        # SWAP's own switch overrides (readswap.f90 l.311-381): SWMETDETAIL
        # is read only with SWETR = 0 (with SWETR = 1 it is forced to 0);
        # SWRAIN is read only with SWMETDETAIL = 0 (else forced to 0).
        swetr = _switch(keys, "swetr", 0)
        swmetdetail = _switch(keys, "swmetdetail", 0) if swetr == 0 else 0
        swrain = _switch(keys, "swrain", 0) if swmetdetail == 0 else 0
        one_file = (".met" in metfil and swmetdetail != 1
                    and swrain not in (1, 3))
        if one_file:
            fin = pathatm + metfil
            if _nbytes(fin) > 80:
                errors.append(f"PATHATM + METFIL is {_nbytes(fin)} bytes; "
                              f"SWAP keeps only 80 (readmeteo.f90 "
                              f"MeteoInOneFile `fin`) and would open the "
                              f"wrong name: {fin!r}")
            met_path = fin if os.path.isabs(fin) else os.path.join(work_dir, fin)
            if not os.path.isfile(met_path):
                errors.append(f"Meteorological file not found: {met_path}")
        else:
            # SWAP drops a .met extension here and reads yearly files
            stem = metfil.split(".met")[0]
            met_stem = swap_file_path(work_dir, pathatm + stem)
            yearly = glob.glob(glob.escape(met_stem) + ".[0-9][0-9][0-9]")
            if not yearly:
                errors.append(f"No yearly meteorological files found: "
                              f"{met_stem}.YYY")

    # Crop files: CROPFIL column of the crop rotation table (readswap.f90
    # l.431, only when SWCROP = 1, default 1), opened as
    # trim(pathcrop)//trim(cropfil)//'.crp' through TTUTIL RDINIT
    # (readswap.f90 l.2056-2058), so the whole name is lowercased.
    if _switch(keys, "swcrop", 1) == 1:
        pathcrop = _str(keys, "pathcrop").rstrip(" ")
        cropfil = keys.get("cropfil", [])
        cropfil = cropfil if isinstance(cropfil, list) else [cropfil]
        for cf in dict.fromkeys(cropfil):
            if cf is MISSING:
                cf = MISSING_STR                 # TTUTIL's string default
            if not isinstance(cf, str):
                raise SwpSyntaxError(f"CROPFIL value {cf!r} is not a string")
            crp_path = swap_file_path(work_dir, pathcrop + cf.rstrip(" ") + ".crp")
            if not os.path.isfile(crp_path):
                warnings.append(f"Crop file not found: {crp_path}")

    # Drainage file: read only when SWDRA != 0 (readswap.f90 l.986-987),
    # opened as trim(pathdrain)//trim(drfil)//'.dra' through TTUTIL RDINIT
    # (readswap.f90 l.1766-1768), so the whole name is lowercased.
    swdra = _switch(keys, "swdra", 0)
    if swdra != 0:
        drfil = _str(keys, "drfil").rstrip(" ")
        if not drfil:
            errors.append(f"SWDRA = {swdra} but DRFIL is not set")
        else:
            pathdrain = _str(keys, "pathdrain").rstrip(" ")
            dra_path = swap_file_path(work_dir, pathdrain + drfil + ".dra")
            if not os.path.isfile(dra_path):
                errors.append(f"SWDRA = {swdra} but drainage file not found: "
                              f"{dra_path}")


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

    # SWAP lowercases the .swp name it opens on Linux (CASE.SWP -> case.swp),
    # so a name with capitals is never the file that would be read.
    if swp_file != swp_file.translate(_UPPER_TO_LOWER):
        errors.append(f"--swp-file {swp_file!r} has capital letters; SWAP on Linux "
                      f"opens the lowercase name. Rename it to "
                      f"{swp_file.translate(_UPPER_TO_LOWER)!r}")
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

    # Read the .swp with the TTUTIL-exact reader (_ttutil_swp_reader.py).
    # A file SWAP's reader would reject is a preflight error.
    try:
        keys = _read_swp_keys(swp_path)
    except SwpSyntaxError as e:
        errors.append(str(e))
        keys = None

    if keys is not None:
        try:
            _check_referenced_files(work_dir, keys, errors, warnings)
        except SwpSyntaxError as e:
            errors.append(str(e))

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


def _nbytes(name):
    """Length in bytes, as a Fortran CHARACTER(len=n) buffer counts it."""
    return len(os.fsencode(name))


def swap_argument(swp_file):
    """
    The command-line argument that makes SWAP read exactly `swp_file`.

    readswap.f90 l.40/66-80: the argument goes into character(len=32)
    swpfil; a name ending in '.swp' is used as given, any other gets '.swp'
    added, and the name is lowercased on open (TTUTIL). So the name is
    passed unchanged, and anything SWAP would read under another name is
    refused: longer than 32 bytes (cut off; Fortran counts bytes, so a
    UTF-8 name is measured with os.fsencode), not ending in '.swp'
    (SWAP would add '.swp'), or with capital letters (SWAP opens the
    lowercase name). Raises ValueError.
    """
    if _nbytes(swp_file) > 32:
        raise ValueError(f"--swp-file {swp_file!r} is {_nbytes(swp_file)} bytes; "
                         f"SWAP keeps only 32 (readswap.f90 swpfil) and would "
                         f"read another file")
    lowered = swp_file.translate(_UPPER_TO_LOWER)   # LOWERC: A-Z only
    if swp_file != lowered:
        raise ValueError(f"--swp-file {swp_file!r} has capital letters; SWAP "
                         f"opens the lowercase name {lowered!r}")
    if not swp_file.endswith(".swp") or len(swp_file) <= 4:
        raise ValueError(f"--swp-file {swp_file!r} must end in '.swp'; SWAP "
                         f"would add '.swp' and read {swp_file + '.swp'!r}")
    return swp_file


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
        # Passed unchanged; swap_argument() refuses names SWAP would read
        # as another file (see there).
        swp_arg = swap_argument(swp_file)
        # stdin is empty: on some fatal errors SWAP waits for a key press,
        # which would otherwise hang the run until the timeout.
        result = subprocess.run(
            [binary, swp_arg],
            cwd=work_dir,
            stdin=subprocess.DEVNULL,
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
            print(f"[FAIL] SWAP exited with code {result.returncode} without "
                  f"'Swap normal completion' (see the *_swap.log in the work dir)")
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


def _read_swp_keys(swp_path):
    """
    All settings of a SWAP .swp file, read with the same syntax rules as
    SWAP's TTUTIL 4.2.7 reader (see _ttutil_swp_reader.py): {lowercase name:
    value or list}. Raises SwpSyntaxError where SWAP's reader would stop.
    """
    return read_swp(swp_path)


def _str(keys, name):
    """String setting; '' when absent. A TTUTIL missing value gives TTUTIL's
    string default '- MISSING -' (what SWAP then uses). A non-string value
    is an error (SWAP's RDSCHA would stop on it)."""
    if name not in keys:
        return ""
    val = keys[name]
    if val is MISSING:
        return MISSING_STR
    if not isinstance(val, str):
        raise SwpSyntaxError(f"{name.upper()} = {val!r} is not one quoted "
                             f"string; SWAP's RDSCHA would stop")
    return val


def _switch(keys, name, default):
    """Integer switch from the .swp; `default` when the key is absent (the
    default SWAP itself uses, see src/readswap.f90). A TTUTIL missing value
    gives TTUTIL's integer default -99, which RDSINR accepts without a range
    check, so SWAP runs with switch = -99 (that is: not 1). A value that is
    not one integer is an error (SWAP's RDSINR would stop), never the
    default."""
    if name not in keys:
        return default
    val = keys[name]
    if val is MISSING:
        return MISSING_INT
    if isinstance(val, bool) or not isinstance(val, int):
        raise SwpSyntaxError(f"{name.upper()} = {val!r} is not one integer; "
                             f"SWAP's RDSINR would stop")
    return val


def expected_outputs(keys):
    """
    Output files SWAP 4.2.0 writes for these .swp settings, as
    {extension: description}. Taken from the SWAP source:

      .blc  outblc  when SWBLC = 1          (swapoutput.f90 l.24; SWBLC required)
      .bal  outbal  when SWBAL = 1          (swapoutput.f90 l.21; default 1,
                                             readswap.f90 l.243)
      .wba  outwba  when SWWBA = 1          (swapoutput.f90 l.91; default 1)
      .inc  outinc  when SWINC = 1          (swapoutput.f90 l.94; default 1)
      .vap  outvap  when SWVAP = 1          (swapoutput.f90 l.100; required)
      .sba  outsba  when SWSBA = 1, but only inside SoluteOutput, which
                    swap.f90 l.146/296 calls only when flSolute, i.e.
                    SWSOLU = 1 (timecontrol.f90 l.111-112). SWSBA default 1.
      .tem  outtem  when SWATE = 1 (read into swtem, readswap.f90 l.290),
                    but only inside TemperatureOutput, called only when
                    flTemperature, i.e. SWHEA = 1 (timecontrol.f90 l.107-108).
                    The file name ends in '.tem' (swapoutput.f90 l.2006),
                    not '.ate'.

    A required key that is missing from the file is taken as 0 here: SWAP
    stops on a missing required key before writing any output, and that
    failure is already caught by the normal-completion check.
    """
    expected = {}
    if _switch(keys, "swblc", 0) == 1:
        expected[".blc"] = "Detailed water balance"
    if _switch(keys, "swbal", 1) == 1:
        expected[".bal"] = "Yearly water balance"
    if _switch(keys, "swwba", 1) == 1:
        expected[".wba"] = "Daily water balance"
    if _switch(keys, "swinc", 1) == 1:
        expected[".inc"] = "Water balance increments"
    if _switch(keys, "swvap", 0) == 1:
        expected[".vap"] = "Soil profiles"
    if _switch(keys, "swsolu", 0) == 1 and _switch(keys, "swsba", 1) == 1:
        expected[".sba"] = "Solute balance"
    if _switch(keys, "swhea", 0) == 1 and _switch(keys, "swate", 0) == 1:
        expected[".tem"] = "Soil temperature profiles"
    return expected


_UPPER_TO_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ",
                                 "abcdefghijklmnopqrstuvwxyz")


def swap_file_path(work_dir, swap_name, lowercase=True):
    """
    The real file SWAP opens for the name string it builds.

    SWAP opens every file through TTUTIL FOPENS -> FOPENG -> FLNAME, and the
    pinned libttutil.a FLNAME is a plain tail call to LOWERC: the WHOLE name
    string (folder part included) is lowercased, ASCII A-Z only. SWAP runs
    with cwd = work_dir, so a relative result is relative to work_dir.
    """
    name = swap_name.translate(_UPPER_TO_LOWER) if lowercase else swap_name
    if os.path.isabs(name):
        return name
    return os.path.join(work_dir, name)


# Outputs SWAP opens with a plain Fortran OPEN (no TTUTIL FLNAME), so their
# name keeps its case: .tem (swapoutput.f90 l.2006-2007). Every other output
# checked here goes through `call fopens(...)` and is lowercased.
_DIRECT_OPEN_OUTPUTS = {".tem"}


def output_path(work_dir, keys, ext):
    """
    Path of the SWAP output file with extension `ext`. SWAP builds it as
    trim(pathwork)//trim(outfil)//ext (e.g. swapoutput.f90 l.2248): Fortran
    TRIM drops trailing blanks of PATHWORK and OUTFIL, the strings are joined
    with no separator, and the result goes through swap_file_path().
    """
    pathwork = _str(keys, "pathwork").rstrip(" ")
    outfil = _str(keys, "outfil").rstrip(" ")
    return swap_file_path(work_dir, pathwork + outfil + ext,
                          lowercase=ext not in _DIRECT_OPEN_OUTPUTS)


def validate_outputs(work_dir, swp_file):
    """
    Post-execution validation of SWAP output files.

    Checks:
    1. Every output file the .swp switches turn on was created, in the
       PATHWORK folder, and is not empty (missing or empty = failure)
    2. Water balance closure (from .blc file), as a warning
    3. A mass-balance deviation file (<OUTFIL>.dwb), as a warning
    """
    errors = []
    warnings = []

    swp_path = os.path.join(work_dir, swp_file)
    try:
        keys = _read_swp_keys(swp_path)
        outfil = _str(keys, "outfil").rstrip(" ")
        _str(keys, "pathwork")
        expected = expected_outputs(keys)
    except SwpSyntaxError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        print("[FAIL] Output validation failed with 1 errors")
        return False
    if not outfil:
        print(f"ERROR: OUTFIL not set in {swp_path}; cannot locate SWAP outputs",
              file=sys.stderr)
        print("[FAIL] Output validation failed with 1 errors")
        return False
    print(f"  [INFO] Looking for outputs as {output_path(work_dir, keys, '.*')}")

    if not expected:
        warnings.append("No output files are switched on in the .swp "
                        "(SWBLC/SWBAL/SWWBA/SWINC/SWVAP all 0)")

    for ext, desc in expected.items():
        fpath = output_path(work_dir, keys, ext)
        if os.path.isfile(fpath):
            size = os.path.getsize(fpath)
            if size == 0:
                errors.append(f"{fpath} is empty (0 bytes)")
            else:
                print(f"  [OK] {os.path.basename(fpath)} ({size:,} bytes) — {desc}")
        else:
            errors.append(f"Expected output not found: {fpath} ({desc})")

    # Mass-balance deviation file: SWAP writes <OUTFIL>.dwb when the water
    # balance deviation passes CritDevMasBal (checkmassbal.f90 l.155-158) and
    # keeps running, so this is a quality warning, not a failed run.
    for ext in (".dwb", ".dwb.csv"):
        dwb = output_path(work_dir, keys, ext)
        if os.path.isfile(dwb):
            warnings.append(f"Mass-balance deviation file found: {dwb} "
                            f"(SWAP passed CritDevMasBal; check it before "
                            f"using the results)")

    # Parse water balance from .blc if available
    blc_path = output_path(work_dir, keys, ".blc")
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
    try:
        swap_argument(args.swp_file)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(2)

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
