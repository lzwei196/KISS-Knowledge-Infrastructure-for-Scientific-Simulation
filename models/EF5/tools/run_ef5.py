#!/usr/bin/env python3
"""
run_ef5.py — Execute EF5 with preflight validation and output checking.

Wraps the EF5 binary with:
  1. Pre-flight validation of control file, grids, and forcing data
  2. Execution with timeout and output capture
  3. Post-run validation of output files

Pipeline: validate config → check grids → check forcing → run binary → validate output
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration parser (lightweight)
# ---------------------------------------------------------------------------
def parse_control_file(control_path):
    """
    Parse EF5 control.txt into a dict of sections.

    Returns dict: {section_type: {section_name: {key: value}}}
    """
    sections = {}
    current_section = None
    current_name = None

    with open(control_path, "r") as f:
        for line in f:
            line = line.strip()
            # Skip comments
            if not line or line.startswith("#") or line.startswith("//"):
                continue
            # Remove inline comments
            for comment_start in ["#", "//"]:
                idx = line.find(comment_start)
                if idx >= 0:
                    line = line[:idx].strip()
            # Remove C-style block comments (simplistic)
            if "/*" in line:
                line = line[:line.find("/*")].strip()

            if not line:
                continue

            # Section header
            match = re.match(r"\[(\w+)(?:\s+(.+))?\]", line)
            if match:
                current_section = match.group(1).lower()
                current_name = match.group(2) if match.group(2) else ""
                current_name = current_name.strip()
                key = f"{current_section}:{current_name}"
                sections[key] = {"_type": current_section, "_name": current_name}
                continue

            # Key=value
            if "=" in line and current_section:
                parts = line.split("=", 1)
                k = parts[0].strip().lower()
                v = parts[1].strip()
                key = f"{current_section}:{current_name}"
                sections[key][k] = v

    return sections


# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------
def preflight_check(control_path, binary_path):
    """
    Validate configuration and data files before running EF5.

    Returns (ok: bool, messages: list[str])
    """
    messages = []
    errors = []

    # Check binary
    if not os.path.isfile(binary_path):
        errors.append(f"EF5 binary not found: {binary_path}")
    elif not os.access(binary_path, os.X_OK):
        errors.append(f"EF5 binary not executable: {binary_path}")

    # Check control file
    if not os.path.isfile(control_path):
        errors.append(f"Control file not found: {control_path}")
        return False, errors

    sections = parse_control_file(control_path)

    # Check [Basic] section
    basic_key = None
    for k in sections:
        if k.startswith("basic:"):
            basic_key = k
            break

    if not basic_key:
        errors.append("Missing [Basic] section in control file")
    else:
        basic = sections[basic_key]
        for grid in ["dem", "ddm", "fam"]:
            path = basic.get(grid, "")
            if not path:
                errors.append(f"Missing {grid.upper()} path in [Basic]")
            elif not os.path.isfile(path):
                errors.append(f"{grid.upper()} file not found: {path}")
            else:
                messages.append(f"[OK] {grid.upper()}: {path}")

        proj = basic.get("proj", "").lower()
        if proj not in ["geographic", "laea", ""]:
            errors.append(f"Unknown projection: {proj}. Use 'geographic' or 'laea'")

        esri_ddm = basic.get("esriddm", "").lower()
        if esri_ddm and esri_ddm not in ["true", "false"]:
            errors.append(f"ESRIDDM must be true or false, got: {esri_ddm}")

    # Check forcing sections
    for key, sec in sections.items():
        sec_type = sec.get("_type", "")
        if sec_type in ["precipforcing", "petforcing", "tempforcing"]:
            loc = sec.get("loc", "")
            if loc and not os.path.isdir(loc):
                errors.append(f"Forcing directory not found: {loc} (section {key})")
            elif loc:
                messages.append(f"[OK] {sec_type} dir: {loc}")

            unit = sec.get("unit", "")
            if unit:
                messages.append(f"  Unit: {unit}")
                # Check for common unit traps
                if sec_type == "precipforcing" and unit.lower() == "mm/m":
                    errors.append(
                        f"UNIT=mm/m means mm/month — did you mean mm/h (mm per hour)? "
                        f"'m' = month, 'u' = minute in EF5 time units!"
                    )

    # Check gauge sections
    gauge_count = 0
    for key, sec in sections.items():
        if sec.get("_type") == "gauge":
            gauge_count += 1
            lon = sec.get("lon")
            lat = sec.get("lat")
            if lon and lat:
                try:
                    lon_f = float(lon)
                    lat_f = float(lat)
                    if abs(lat_f) > 90:
                        errors.append(f"Gauge {sec['_name']}: LAT={lat_f} out of range [-90,90]")
                    if abs(lon_f) > 180:
                        errors.append(f"Gauge {sec['_name']}: LON={lon_f} out of range [-180,180]")
                except ValueError:
                    errors.append(f"Gauge {sec['_name']}: invalid LON/LAT")

    if gauge_count == 0:
        errors.append("No [Gauge] sections found in control file")
    else:
        messages.append(f"[OK] {gauge_count} gauge(s) defined")

    # Check task sections
    task_count = 0
    for key, sec in sections.items():
        if sec.get("_type") == "task":
            task_count += 1
            style = sec.get("style", "").upper()
            model = sec.get("model", "").upper()
            routing = sec.get("routing", "").upper()

            valid_styles = ["SIMU", "SIMU_RP", "CALI_DREAM", "CALI_ARS", "CLIP_BASIN", "CLIP_GAUGE", "BASIN_AVG"]
            if style and style not in valid_styles:
                errors.append(f"Task {sec['_name']}: unknown STYLE={style}")

            valid_models = ["CREST", "SAC", "HYMOD", "HP"]
            if model and model not in valid_models:
                errors.append(f"Task {sec['_name']}: unknown MODEL={model}")

            valid_routes = ["KW", "LR", ""]
            if routing and routing not in valid_routes:
                errors.append(f"Task {sec['_name']}: unknown ROUTING={routing}")

            # Check time format
            for tkey in ["time_begin", "time_end"]:
                tval = sec.get(tkey, "")
                if tval and len(tval) < 12:
                    errors.append(
                        f"Task {sec['_name']}: {tkey}={tval} too short. "
                        f"Format is YYYYMMDDHHUUSS (at least YYYYMMDDHHMM)"
                    )

            # Check timestep unit
            ts = sec.get("timestep", "")
            if ts:
                unit_char = ts[-1] if ts else ""
                if unit_char == "m":
                    messages.append(
                        f"[WARNING] Task {sec['_name']}: TIMESTEP={ts} — 'm' means MONTHS. "
                        f"For minutes use 'u' (e.g. 5u = 5 minutes)"
                    )

            output_dir = sec.get("output", "")
            if output_dir:
                os.makedirs(output_dir, exist_ok=True)
                messages.append(f"[OK] Output dir: {output_dir}")

    # Check [Execute] section
    has_execute = any(sec.get("_type") == "execute" for sec in sections.values())
    if not has_execute:
        errors.append("Missing [Execute] section — EF5 won't know which tasks to run")

    if errors:
        for e in errors:
            print(f"[ERROR] {e}", file=sys.stderr)
    for m in messages:
        print(m)

    return len(errors) == 0, errors + messages


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------
def resolve_shared_libs(binary_path):
    """Find directories that satisfy ef5's 'not found' shared libraries.

    The ef5 binary is linked against libtiff/libgeotiff/libproj that live in
    conda envs on this server, not on the default loader path — a fresh shell
    gets `error while loading shared libraries: libproj.so.25` (exit 127).
    We parse `ldd` for unresolved libs, then search a set of known conda-env
    lib dirs (and any dir already supplying a *resolved* ef5 dependency) for a
    file of that soname, and return the dirs to prepend to LD_LIBRARY_PATH.
    """
    try:
        ldd = subprocess.run(["ldd", binary_path], capture_output=True, text=True, timeout=30)
    except Exception:
        return []
    missing, known_dirs = [], set()
    for line in ldd.stdout.splitlines():
        line = line.strip()
        if "=> not found" in line:
            missing.append(line.split("=>")[0].strip())
        elif "=> /" in line:  # an already-resolved dep tells us a good lib dir
            known_dirs.add(os.path.dirname(line.split("=>")[1].strip().split(" (")[0]))
    if not missing:
        return []
    search = list(known_dirs) + [
        "/home/server/knowledge-dissection-toolkit/auto_dissect/_work/PCR_GLOBWB_2/miniconda/envs/pcrglobwb_python3/lib",
    ]
    # Add all conda env lib dirs as a last resort
    import glob
    search += sorted(glob.glob("/home/server/miniconda3/envs/*/lib"))
    found = []
    for soname in missing:
        for d in search:
            if os.path.exists(os.path.join(d, soname)):
                if d not in found:
                    found.append(d)
                break
    return found


def run_ef5(binary_path, control_path, timeout=3600, cwd=None):
    """
    Run EF5 binary and capture output.

    Returns (returncode, stdout, stderr, elapsed_seconds)
    """
    if cwd is None:
        cwd = os.path.dirname(os.path.abspath(control_path))

    cmd = [binary_path, control_path]
    print(f"Running: {' '.join(cmd)}")
    print(f"Working directory: {cwd}")

    env = os.environ.copy()
    lib_dirs = resolve_shared_libs(binary_path)
    if lib_dirs:
        existing = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = ":".join(lib_dirs + ([existing] if existing else []))
        print(f"[run_ef5] LD_LIBRARY_PATH += {':'.join(lib_dirs)}")

    start = time.time()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            env=env,
        )
        elapsed = time.time() - start
        return result.returncode, result.stdout, result.stderr, elapsed
    except subprocess.TimeoutExpired:
        elapsed = time.time() - start
        return -1, "", f"Timeout after {timeout}s", elapsed
    except FileNotFoundError:
        return -2, "", f"Binary not found: {binary_path}", 0


# ---------------------------------------------------------------------------
# Post-run validation
# ---------------------------------------------------------------------------
def validate_output(control_path, stdout, stderr, returncode):
    """Validate EF5 output after run."""
    messages = []

    if returncode != 0:
        messages.append(f"[ERROR] EF5 exited with code {returncode}")
        if "Segmentation fault" in stderr or "SIGSEGV" in stderr:
            messages.append("[ERROR] Segmentation fault — check grid dimensions and memory")
        if "No execute section" in stderr or "No execute section" in stdout:
            messages.append("[ERROR] Missing [Execute] section in control file")

    # Check for output files
    sections = parse_control_file(control_path)
    for key, sec in sections.items():
        if sec.get("_type") == "task":
            output_dir = sec.get("output", "")
            if output_dir and os.path.isdir(output_dir):
                files = list(Path(output_dir).glob("*"))
                if files:
                    messages.append(f"[OK] {len(files)} output files in {output_dir}")
                else:
                    messages.append(f"[WARNING] No output files in {output_dir}")

    # Check for gauge time series output
    for line in stdout.split("\n"):
        if "time series" in line.lower() or "output" in line.lower():
            messages.append(f"  EF5: {line.strip()}")

    # Check for common warnings in stdout
    warning_patterns = [
        ("Node Soil Moisture", "Initial soil moisture issues — check IWU parameter"),
        ("not found", "Missing file — check paths in control file"),
        ("Impervious Area", "IM parameter out of range"),
    ]
    for pattern, explanation in warning_patterns:
        count = stdout.count(pattern)
        if count > 0:
            messages.append(f"[WARNING] '{pattern}' appeared {count} times — {explanation}")

    return messages


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Run EF5 with preflight and post-run validation")
    parser.add_argument("--binary", required=True, help="Path to ef5 binary")
    parser.add_argument("--control", required=True, help="Path to control.txt")
    parser.add_argument("--timeout", type=int, default=3600, help="Timeout in seconds")
    parser.add_argument("--skip-preflight", action="store_true", help="Skip preflight checks")
    parser.add_argument("--log", help="Log file path for output")
    args = parser.parse_args()

    # Pre-flight
    if not args.skip_preflight:
        print("=" * 60)
        print("PREFLIGHT CHECKS")
        print("=" * 60)
        ok, msgs = preflight_check(args.control, args.binary)
        if not ok:
            print("\n[ABORT] Preflight checks failed. Fix errors above before running.")
            sys.exit(1)
        print("\n[OK] All preflight checks passed\n")

    # Execute
    print("=" * 60)
    print("EXECUTING EF5")
    print("=" * 60)
    returncode, stdout, stderr, elapsed = run_ef5(args.binary, args.control, args.timeout)

    print(f"\nEF5 completed in {elapsed:.1f}s with exit code {returncode}")
    if stdout:
        print("\n--- STDOUT ---")
        print(stdout[:5000])
    if stderr:
        print("\n--- STDERR ---")
        print(stderr[:2000])

    # Post-run validation
    print("\n" + "=" * 60)
    print("POST-RUN VALIDATION")
    print("=" * 60)
    msgs = validate_output(args.control, stdout, stderr, returncode)
    for m in msgs:
        print(m)

    # Write log
    if args.log:
        log_data = {
            "binary": args.binary,
            "control": args.control,
            "returncode": returncode,
            "elapsed_s": elapsed,
            "stdout_head": stdout[:2000],
            "stderr_head": stderr[:1000],
        }
        with open(args.log, "w") as f:
            json.dump(log_data, f, indent=2)
        print(f"\n[OK] Log written to {args.log}")

    sys.exit(0 if returncode == 0 else 1)


if __name__ == "__main__":
    main()
