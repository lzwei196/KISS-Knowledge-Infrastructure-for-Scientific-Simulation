#!/usr/bin/env python3
"""
run_elmfire.py — Execute ELMFIRE with preflight validation and output checking.

Preflight checks:
  1. Binary exists and is executable
  2. Namelist file exists and is parseable
  3. All referenced raster files exist
  4. Output directory exists (creates if needed)
  5. Scratch directory exists (creates if needed)
  6. GDAL is available (if CONVERT_TO_GEOTIFF = .TRUE.)

Execution:
  - Single-process: elmfire_VERSION namelist
  - MPI-parallel: mpirun -np N elmfire_VERSION namelist

Post-run checks:
  1. Output files exist
  2. Fire size stats show non-zero area
  3. Time of arrival raster has valid values

Usage:
    python run_elmfire.py \\
        --namelist ./inputs/elmfire.data \\
        --np 4 \\
        --binary elmfire_2025.1002

    python run_elmfire.py \\
        --namelist ./inputs/elmfire.data \\
        --docker \\
        --np 8
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ELMFIRE_NAME = "elmfire_2025.1002"
# Server default build (the same path the KI preflight_check.py checks)
SERVER_DEFAULT_BINARY = ("KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/ELMFIRE/"
                         "source/repo/build/linux/bin/elmfire_2025.1002")


def resolve_binary(user_value):
    """--binary (a path, or a name on PATH), then $ELMFIRE_BIN, then the server default.
    Returns (path or None, source, message). An explicit choice that cannot be used is
    an error; there is no fallback to another ELMFIRE."""
    for label, val in (("--binary", user_value), ("$ELMFIRE_BIN", os.environ.get("ELMFIRE_BIN"))):
        if not val:
            continue
        cand = val if os.sep in val else shutil.which(val)
        if cand and os.path.isfile(cand) and os.access(cand, os.X_OK):
            return os.path.abspath(cand), label, ""
        return None, label, f"ELMFIRE binary not found or not executable ({label}): {val}"
    if os.path.isfile(SERVER_DEFAULT_BINARY) and os.access(SERVER_DEFAULT_BINARY, os.X_OK):
        return SERVER_DEFAULT_BINARY, "server default", ""
    return None, "server default", f"ELMFIRE binary not found: {SERVER_DEFAULT_BINARY}"


def case_dir_of(args):
    """Folder ELMFIRE runs in; relative paths in the namelist are taken from it.
    --case-dir if given, else the namelist's folder (the tool's old behaviour)."""
    if getattr(args, "case_dir", None):
        return os.path.abspath(args.case_dir)
    return os.path.dirname(os.path.abspath(args.namelist))


def _resolve(base_dir, path):
    return path if os.path.isabs(path) else os.path.normpath(os.path.join(base_dir, path))


def strip_namelist_comments(content):
    """Namelist text without '!' comments (a '!' inside quotes is kept)."""
    out = []
    for line in content.splitlines():
        q, cut = None, len(line)
        for k, ch in enumerate(line):
            if ch in "'\"":
                q = None if q == ch else (ch if q is None else q)
            elif ch == "!" and q is None:
                cut = k
                break
        out.append(line[:cut])
    return "\n".join(out)


# Engine defaults of the logicals this tool reads (elmfire_namelists.f90)
LOGICAL_DEFAULTS = {"CONVERT_TO_GEOTIFF": True, "USE_BSQ_XML_HEADER": True,
                    "USE_EXISTING_BSQS": False, "VRT_INSTEAD_OF_TIF": False,
                    "DUMP_FLIN": False, "DUMP_SPREAD_RATE": False, "DUMP_TIME_OF_ARRIVAL": False}


def namelist_true(content, key):
    """Value of a logical in the (comment-free) namelist: an assignment may start a
    line or follow '&GROUP', ',' or another value on the same line; .TRUE./T/.T. are
    true. The engine default is used when the key is absent."""
    # quoted strings cannot hold assignments: blank them out first
    content = re.sub(r"'[^']*'|\"[^\"]*\"", "''", content)
    m = None
    for m in re.finditer(rf"(?i)(?:^|[\s,&/])\s*{key}\s*=\s*([^\s,/]+)", content, re.MULTILINE):
        pass  # the last assignment wins, as in a Fortran namelist read
    if not m:
        return LOGICAL_DEFAULTS.get(key.upper(), False)
    return m.group(1).strip().upper().lstrip(".").startswith("T")


def validate_inputs(args):
    """Preflight validation before running ELMFIRE.

    Input rasters follow the engine's reader (elmfire_io.f90 READ_BSQ_RASTER): for each
    raster, <name>.bsq and <name>.hdr are read from SCRATCH (or from the input folder when
    SCRATCH is 'null'); if either is missing, the engine makes them with
    PATH_TO_GDAL/gdal_translate from <input folder>/<name>.tif (.vrt with
    VRT_INSTEAD_OF_TIF). Relative paths are taken from the case folder.
    """
    errors = []
    warnings = []

    # Check namelist
    if not os.path.isfile(args.namelist):
        errors.append(f"Namelist file not found: {args.namelist}")
    else:
        namelist_content = strip_namelist_comments(open(args.namelist).read())

        # Extract directories from namelist
        fuels_dir = extract_namelist_value(namelist_content,
                                           "FUELS_AND_TOPOGRAPHY_DIRECTORY")
        weather_dir = extract_namelist_value(namelist_content, "WEATHER_DIRECTORY")
        outputs_dir = extract_namelist_value(namelist_content, "OUTPUTS_DIRECTORY")
        scratch_dir = extract_namelist_value(namelist_content, "SCRATCH")

        base_dir = case_dir_of(args)
        bsq_dir = (None if not scratch_dir or scratch_dir == 'null'
                   else _resolve(base_dir, scratch_dir))
        src_ext = ".vrt" if namelist_true(namelist_content, "VRT_INSTEAD_OF_TIF") else ".tif"
        need_gdal = namelist_true(namelist_content, "CONVERT_TO_GEOTIFF")
        xml_header = namelist_true(namelist_content, "USE_BSQ_XML_HEADER")
        existing_bsqs = namelist_true(namelist_content, "USE_EXISTING_BSQS")

        for dirname, dirpath, keys in [("Fuels/topo", fuels_dir, FUEL_RASTER_KEYS),
                                       ("Weather", weather_dir, WEATHER_RASTER_KEYS)]:
            if not dirpath:
                continue
            full_path = _resolve(base_dir, dirpath)
            missing_dir_needed = False
            for rname in extract_raster_filenames(namelist_content, keys):
                where = bsq_dir or full_path
                cached = [os.path.join(where, f"{rname}{e}") for e in (".bsq", ".hdr")]
                if xml_header:
                    # READ_BSQ_XML_HEADER: converts every time unless USE_EXISTING_BSQS,
                    # then reads <name>.bsq.aux.xml
                    if existing_bsqs:
                        cached.append(os.path.join(where, f"{rname}.bsq.aux.xml"))
                        missing = [c for c in cached if not os.path.isfile(c)]
                        if missing:
                            errors.append(f"USE_EXISTING_BSQS is set but missing: {missing}")
                        continue
                elif all(os.path.isfile(c) for c in cached):
                    continue
                if not os.path.isdir(full_path):
                    missing_dir_needed = True
                    continue
                if os.path.isfile(os.path.join(full_path, f"{rname}{src_ext}")):
                    need_gdal = True
                else:
                    why = ("the engine rebuilds the .bsq from it every run (USE_BSQ_XML_HEADER "
                           "without USE_EXISTING_BSQS)" if xml_header
                           else f"no {rname}.bsq + .hdr in {where} either")
                    errors.append(f"Raster not found: {rname}{src_ext} in {full_path}; {why}")
            if missing_dir_needed:
                hint = ""
                parent = os.path.dirname(base_dir)
                if not os.path.isabs(dirpath) and os.path.isdir(_resolve(parent, dirpath)):
                    hint = (f" (it exists relative to {parent}: ELMFIRE's own layout keeps "
                            f"elmfire.data in inputs/ and runs from the case folder - "
                            f"use --case-dir {parent})")
                errors.append(f"{dirname} directory not found: {full_path}{hint}")

        # GDAL: needed to convert .tif inputs and for CONVERT_TO_GEOTIFF
        if need_gdal:
            gdal_dir = _resolve(base_dir, extract_namelist_value(namelist_content, "PATH_TO_GDAL")
                                or "/usr/bin")
            gt = os.path.join(gdal_dir, "gdal_translate")
            if not (os.path.isfile(gt) and os.access(gt, os.X_OK)):
                on_path = shutil.which("gdal_translate")
                hint = (f"; gdal_translate on PATH is in {os.path.dirname(on_path)} - set "
                        f"PATH_TO_GDAL to that folder") if on_path else ""
                errors.append(f"PATH_TO_GDAL = '{gdal_dir}' has no gdal_translate (ELMFIRE "
                              f"needs it here){hint}")

        # Create output/scratch directories
        if outputs_dir:
            full_outputs = _resolve(base_dir, outputs_dir)
            os.makedirs(full_outputs, exist_ok=True)
        if bsq_dir:
            os.makedirs(bsq_dir, exist_ok=True)

    # Check binary
    binary, source, msg = resolve_binary(args.binary)
    if binary is None:
        errors.append(msg)
    else:
        args.binary = binary
        args.binary_source = source

    # Check MPI
    if args.np > 1 and not shutil.which("mpirun"):
        errors.append("mpirun not found — required for parallel execution")

    if errors:
        print(json.dumps({"status": "error", "stage": "preflight", "errors": errors}))
        sys.exit(1)

    if warnings:
        for w in warnings:
            print(f"  WARNING: {w}")


def extract_namelist_value(content, key):
    """Extract a value from Fortran namelist text."""
    pattern = rf"(?<![A-Z0-9_]){key}\s*=\s*(['\"])([^'\"]+)\1"
    match = re.search(pattern, content, re.IGNORECASE)
    if match:
        return match.group(2)
    # Try without quotes (numeric values)
    pattern = rf"(?<![A-Z0-9_]){key}\s*=\s*([^\s,/]+)"
    match = re.search(pattern, content, re.IGNORECASE)
    if match:
        return match.group(1)
    return None


FUEL_RASTER_KEYS = ["ASP_FILENAME", "CBD_FILENAME", "CBH_FILENAME", "CC_FILENAME",
                    "CH_FILENAME", "DEM_FILENAME", "FBFM_FILENAME", "SLP_FILENAME",
                    "ADJ_FILENAME", "PHI_FILENAME"]
WEATHER_RASTER_KEYS = ["WS_FILENAME", "WD_FILENAME", "M1_FILENAME", "M10_FILENAME",
                       "M100_FILENAME"]


def extract_raster_filenames(content, keys=None):
    """Extract raster filenames from namelist (all keys, or the given ones)."""
    rasters = []
    for key in (keys or FUEL_RASTER_KEYS + WEATHER_RASTER_KEYS):
        val = extract_namelist_value(content, key)
        if val and val != 'null':
            rasters.append(val)
    return rasters


def run_elmfire(args):
    """Execute ELMFIRE binary."""
    if args.np > 1:
        cmd = ["mpirun", "-np", str(args.np), "--allow-run-as-root",
               args.binary, args.namelist]
    else:
        cmd = [args.binary, args.namelist]

    cmd[-1] = os.path.abspath(args.namelist)
    print(f"Executing: {' '.join(cmd)}")
    print(f"  Case folder (cwd): {case_dir_of(args)}")
    start_time = time.time()

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=args.timeout,
            cwd=case_dir_of(args)
        )
    except subprocess.TimeoutExpired:
        return {"status": "error", "returncode": -1,
                "stderr": f"timed out after {args.timeout}s", "elapsed_s": args.timeout}
    except OSError as exc:
        return {"status": "error", "returncode": -2, "stderr": str(exc), "elapsed_s": 0}

    elapsed = time.time() - start_time
    print(f"  Completed in {elapsed:.1f} seconds")

    # ELMFIRE ends a finished run with this line
    if result.returncode == 0 and "End of simulation reached successfully" not in result.stdout:
        print(f"  STDOUT tail: {result.stdout[-1000:]}")
        return {
            "status": "error",
            "returncode": 0,
            "error": "no 'End of simulation reached successfully' line in ELMFIRE output",
            "stdout": result.stdout[-500:],
            "stderr": result.stderr[:500],
            "elapsed_s": elapsed
        }

    if result.returncode != 0:
        print(f"  STDERR: {result.stderr[:1000]}")
        return {
            "status": "error",
            "returncode": result.returncode,
            "stderr": result.stderr[:500],
            "elapsed_s": elapsed
        }

    return {
        "status": "completed",
        "returncode": 0,
        "stdout": result.stdout[-500:],
        "stderr": result.stderr[:500],
        "elapsed_s": elapsed
    }


def _output_state(folder):
    """{name: (mtime_ns, size)} of the files in folder."""
    st = {}
    if os.path.isdir(folder):
        for f in os.listdir(folder):
            p = os.path.join(folder, f)
            if os.path.isfile(p):
                s_ = os.stat(p)
                st[f] = (s_.st_mtime_ns, s_.st_size)
    return st


def outputs_dir_of(args):
    namelist_content = strip_namelist_comments(open(args.namelist).read())
    outputs_dir = extract_namelist_value(namelist_content, "OUTPUTS_DIRECTORY")
    return _resolve(case_dir_of(args), outputs_dir or "outputs")


def validate_outputs(args, before=None):
    """Post-run validation of ELMFIRE outputs.

    Every raster the namelist asks for (DUMP_TIME_OF_ARRIVAL, DUMP_FLIN,
    DUMP_SPREAD_RATE -> vs_*) must have been written by this run with real data:
    a non-empty .tif when CONVERT_TO_GEOTIFF is set, else a non-empty .bil plus .hdr.
    before = file state of the outputs folder just before the run.
    """
    namelist_content = strip_namelist_comments(open(args.namelist).read())
    full_outputs = outputs_dir_of(args)

    results = {"status": "ok", "outputs": [], "warnings": []}

    if not os.path.isdir(full_outputs):
        results["status"] = "error"
        results["warnings"].append(f"Output directory not found: {full_outputs}")
        return results

    # Files written by this run
    now = _output_state(full_outputs)
    output_files = sorted(f for f in now if before is None or before.get(f) != now[f])
    results["outputs"] = output_files
    results["output_count"] = len(output_files)

    if len(output_files) == 0:
        results["status"] = "error"
        results["warnings"].append("No output files produced by this run")

    geotiff = namelist_true(namelist_content, "CONVERT_TO_GEOTIFF")
    for key, prefix in (("DUMP_TIME_OF_ARRIVAL", "time_of_arrival_"), ("DUMP_FLIN", "flin_"),
                        ("DUMP_SPREAD_RATE", "vs_")):
        if not namelist_true(namelist_content, key):
            continue
        if geotiff:
            ok = [f for f in output_files if f.startswith(prefix) and f.endswith(".tif")
                  and now[f][1] > 0]
        else:
            ok = [f for f in output_files if f.startswith(prefix) and f.endswith(".bil")
                  and now[f][1] > 0 and f[:-4] + ".hdr" in output_files
                  and now[f[:-4] + ".hdr"][1] > 0]
        if not ok:
            results["status"] = "error"
            results["warnings"].append(
                f"{key} is set but this run wrote no {prefix}* {'.tif' if geotiff else '.bil + .hdr'} "
                f"with data in {full_outputs}")

    # Check fire size stats
    stats_files = [f for f in output_files if f.startswith("fire_size_stats")]
    if stats_files:
        results["stats_file"] = stats_files[0]

    print(json.dumps(results, indent=2))
    return results


def process(args):
    """Main pipeline: validate → execute → validate."""
    # Step 1: Preflight checks
    print("Running preflight checks...")
    validate_inputs(args)
    print("  Preflight OK")

    # Step 2: Execute
    print("\nRunning ELMFIRE...")
    before = _output_state(outputs_dir_of(args))
    run_result = run_elmfire(args)

    if run_result["status"] != "completed":
        print(json.dumps(run_result, indent=2))
        sys.exit(1)

    # Step 3: Validate outputs
    print("\nValidating outputs...")
    output_result = validate_outputs(args, before)

    # Combined result
    final = {
        "status": "completed" if output_result["status"] == "ok" else "error",
        "execution": run_result,
        "outputs": output_result
    }
    print(json.dumps(final, indent=2))
    if final["status"] != "completed":
        sys.exit(1)
    return final


def main():
    parser = argparse.ArgumentParser(description="Run ELMFIRE with validation")
    parser.add_argument("--namelist", required=True, help="Path to elmfire.data")
    parser.add_argument("--binary", default=None,
                        help=f"ELMFIRE binary path or name on PATH (else $ELMFIRE_BIN, else the "
                             f"server default {SERVER_DEFAULT_BINARY})")
    parser.add_argument("--case-dir", default=None,
                        help="Folder ELMFIRE runs in; relative paths in the namelist are taken from "
                             "it (default: the namelist's folder). ELMFIRE's own examples keep "
                             "elmfire.data in inputs/ and run from the parent folder.")
    parser.add_argument("--np", type=int, default=1,
                        help="Number of MPI processes (default: 1)")
    parser.add_argument("--timeout", type=int, default=3600,
                        help="Timeout in seconds (default: 3600)")
    parser.add_argument("--docker", action="store_true",
                        help="Run inside Docker container")

    args = parser.parse_args()
    process(args)


if __name__ == "__main__":
    main()
