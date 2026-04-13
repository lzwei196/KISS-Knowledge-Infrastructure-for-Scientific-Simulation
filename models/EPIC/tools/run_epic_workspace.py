#!/usr/bin/env python3
"""
Execute EPIC model for one or more sites within a Geo-EPIC workspace.

Pipeline: validate workspace → configure runs → execute binary → collect outputs
Pattern:  validate inputs → process → validate outputs

This wrapper handles:
  - Workspace directory structure validation
  - EPICCONT.DAT configuration (start date, duration)
  - EPICRUN.DAT generation per site
  - PRNT1102.DAT output type toggling
  - Binary execution with timeout
  - Output collection
"""

import os
import sys
import json
import shutil
import argparse
import subprocess
import tempfile
import getpass
from pathlib import Path
from datetime import datetime

try:
    import pandas as pd
    import yaml
except ImportError:
    pd = None
    yaml = None


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
REQUIRED_MODEL_FILES = [
    "EPIC1102.exe", "EPICCONT.DAT", "EPICFILE.DAT",
    "CROPCOM.DAT", "PARM.DAT", "PRNT1102.DAT"
]

VALID_OUTPUT_TYPES = [
    "OUT", "ACM", "SUM", "DHY", "DPS", "MFS", "MPS", "ANN",
    "SOT", "DTP", "MCM", "DCS", "SCO", "ACN", "DCN", "SCN",
    "DGN", "DWT", "ACY", "ACO", "DSL", "MWC", "ABR", "ATG",
    "MSW", "APS", "DWC", "DHS", "DGZ", "ERX", "DNC", "ASL", "DDN"
]


def validate_workspace(workspace_dir: str) -> list:
    """Validate workspace structure and required files."""
    errors = []
    ws = Path(workspace_dir)

    # Check config.yml
    config_path = ws / "config.yml"
    if not config_path.exists():
        errors.append(f"ERROR: config.yml not found in {workspace_dir}")
        return errors

    # Check model directory
    model_dir = ws / "model"
    if not model_dir.exists():
        errors.append("ERROR: model/ directory not found")
        return errors

    for f in REQUIRED_MODEL_FILES:
        if not (model_dir / f).exists():
            errors.append(f"ERROR: Required model file missing: model/{f}")

    # Check input directories
    for d in ["weather", "soil", "sites", "opc"]:
        if not (ws / d).exists():
            errors.append(f"WARNING: {d}/ directory not found")

    # Check info.csv
    info_path = ws / "info.csv"
    if not info_path.exists():
        errors.append("ERROR: info.csv not found")
    elif pd is not None:
        info = pd.read_csv(info_path)
        required_cols = {"SiteID", "soil", "dly", "opc"}
        missing = required_cols - set(info.columns)
        if missing:
            errors.append(f"ERROR: info.csv missing columns: {missing}")

    return errors


def configure_epiccont(model_dir: str, start_date: str, duration: int):
    """
    Update EPICCONT.DAT with simulation start date and duration.

    Line 1 format: [duration:4][year:4][month:4][day:4][rest of line]
    """
    epiccont_path = os.path.join(model_dir, "EPICCONT.DAT")
    with open(epiccont_path, "r") as f:
        lines = f.readlines()

    dt = datetime.strptime(start_date, "%Y-%m-%d")
    # Overwrite first 16 characters of line 1
    old_line = lines[0]
    new_prefix = f"{duration:4d}{dt.year:4d}{dt.month:4d}{dt.day:4d}"
    lines[0] = new_prefix + old_line[16:]

    with open(epiccont_path, "w") as f:
        f.writelines(lines)

    print(f"EPICCONT.DAT: duration={duration}yr, start={start_date}")


def configure_output_types(model_dir: str, output_types: list):
    """
    Toggle output types in PRNT1102.DAT.

    Lines -2 and -1 contain extension names.
    Lines 15 and 16 (0-indexed 14,15) contain toggle switches.
    """
    prnt_path = os.path.join(model_dir, "PRNT1102.DAT")
    with open(prnt_path, "r") as f:
        lines = f.readlines()

    # Read extension names from last two lines
    ext_line1 = lines[-2].split()
    ext_line2 = lines[-1].split()

    # Build toggle arrays
    toggle1 = []
    for ext in ext_line1:
        toggle1.append("1" if ext.upper() in [t.upper() for t in output_types] else "0")

    toggle2 = []
    for ext in ext_line2:
        toggle2.append("1" if ext.upper() in [t.upper() for t in output_types] else "0")

    # Write toggles to lines 14 and 15
    if len(lines) > 15:
        lines[14] = "  ".join(toggle1) + "\n"
        lines[15] = "  ".join(toggle2) + "\n"

    with open(prnt_path, "w") as f:
        f.writelines(lines)

    print(f"PRNT1102.DAT: enabled {output_types}")


def write_epicrun(model_dir: str, site_id: str):
    """Write EPICRUN.DAT for a single site."""
    epicrun_path = os.path.join(model_dir, "EPICRUN.DAT")
    # Format: site_id padded to 9 chars, then flags
    content = f"{site_id:>9s} 1  0  0  0  1  1  1/\n"
    with open(epicrun_path, "w") as f:
        f.write(content)


def setup_run_directory(workspace_dir: str, site_id: str,
                        soil_file: str, dly_file: str, opc_file: str,
                        lat: float, lon: float, elev: float) -> str:
    """
    Create a temporary run directory with all required files.

    Returns path to run directory.
    """
    ws = Path(workspace_dir)
    user = getpass.getuser()

    # Use RAM-backed temp dir if available
    cache_base = f"/dev/shm/geo_epic_{user}"
    if not os.path.exists("/dev/shm"):
        cache_base = os.path.join(workspace_dir, ".cache", f"geo_epic_{user}")

    os.makedirs(cache_base, exist_ok=True)
    run_dir = tempfile.mkdtemp(dir=cache_base, prefix=f"{site_id}_")

    # Copy model directory
    model_src = ws / "model"
    for f in model_src.iterdir():
        shutil.copy2(f, run_dir)

    # Copy weather files as 1.DLY
    dly_src = ws / "weather" / dly_file
    if dly_src.exists():
        shutil.copy2(dly_src, os.path.join(run_dir, "1.DLY"))

    # Copy soil file
    sol_src = ws / "soil" / soil_file
    if sol_src.exists():
        shutil.copy2(sol_src, run_dir)

    # Copy SIT file
    sit_name = soil_file.replace(".SOL", ".SIT").replace(".sol", ".sit")
    sit_src = ws / "sites" / sit_name
    if sit_src.exists():
        shutil.copy2(sit_src, run_dir)

    # Copy OPC file
    opc_src = ws / "opc" / opc_file
    if opc_src.exists():
        shutil.copy2(opc_src, run_dir)

    # Write file reference files
    # WDLSTCOM.DAT → references 1.DLY
    wdlst_path = os.path.join(run_dir, "WDLSTCOM.DAT")
    with open(wdlst_path, "w") as f:
        f.write(f"1.DLY\n")

    # WPM1USEL.DAT → references 1.WP1 with lat/lon/elev
    wpm1_path = os.path.join(run_dir, "WPM1USEL.DAT")
    with open(wpm1_path, "w") as f:
        f.write(f"1.WP1{lat:8.3f}{lon:9.3f}{elev:8.1f}\n")

    # SITECOM.DAT → references SIT file
    sitecom_path = os.path.join(run_dir, "SITECOM.DAT")
    with open(sitecom_path, "w") as f:
        f.write(f"{sit_name}\n")

    # SOILCOM.DAT → references SOL file
    soilcom_path = os.path.join(run_dir, "SOILCOM.DAT")
    with open(soilcom_path, "w") as f:
        f.write(f"{soil_file}\n")

    # OPSCCOM.DAT → references OPC file
    opsccom_path = os.path.join(run_dir, "OPSCCOM.DAT")
    with open(opsccom_path, "w") as f:
        f.write(f"{opc_file}\n")

    # Write EPICRUN.DAT
    write_epicrun(run_dir, site_id)

    return run_dir


def run_epic_binary(run_dir: str, site_id: str, timeout: int = 30) -> dict:
    """
    Execute the EPIC binary in run_dir.

    Returns dict with status, stdout, stderr, return_code.
    """
    # Find executable
    exe_candidates = list(Path(run_dir).glob("EPIC*.exe")) + \
                     list(Path(run_dir).glob("EPIC*"))
    exe_path = None
    for c in exe_candidates:
        if c.is_file() and not c.name.endswith(".DAT"):
            exe_path = c
            break

    if exe_path is None:
        return {
            "status": "error",
            "message": "EPIC executable not found in run directory",
            "return_code": -1
        }

    # Make executable on Unix
    os.chmod(exe_path, 0o755)

    result = {"status": "unknown", "return_code": -1}

    try:
        proc = subprocess.run(
            [str(exe_path)],
            cwd=run_dir,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            input=b"\n" * 10  # Handle interactive prompts
        )
        result["return_code"] = proc.returncode
        result["stdout"] = proc.stdout.decode("utf-8", errors="replace")[:2000]
        result["stderr"] = proc.stderr.decode("utf-8", errors="replace")[:2000]
        result["status"] = "completed" if proc.returncode == 0 else "error"

    except subprocess.TimeoutExpired:
        result["status"] = "timeout"
        result["message"] = f"EPIC timed out after {timeout}s"

    except PermissionError:
        result["status"] = "error"
        result["message"] = "Permission denied — may need Wine for Windows .exe on Linux"

    except Exception as e:
        result["status"] = "error"
        result["message"] = str(e)

    return result


def collect_outputs(run_dir: str, output_dir: str, site_id: str,
                    output_types: list) -> list:
    """Collect output files from run directory to output directory."""
    os.makedirs(output_dir, exist_ok=True)
    collected = []

    for ext in output_types:
        src = os.path.join(run_dir, f"{site_id}.{ext}")
        if os.path.exists(src):
            dst = os.path.join(output_dir, f"{site_id}.{ext}")
            shutil.copy2(src, dst)
            collected.append(dst)

    # Also check for generic output files
    for f in Path(run_dir).glob(f"{site_id}.*"):
        if f.suffix[1:].upper() in VALID_OUTPUT_TYPES:
            dst = os.path.join(output_dir, f.name)
            if not os.path.exists(dst):
                shutil.copy2(f, dst)
                collected.append(dst)

    return collected


def validate_outputs(output_dir: str, site_id: str,
                     output_types: list) -> list:
    """Validate that expected output files were produced."""
    errors = []

    for ext in output_types:
        out_path = os.path.join(output_dir, f"{site_id}.{ext}")
        if not os.path.exists(out_path):
            errors.append(f"WARNING: Expected output {site_id}.{ext} not found")
        elif os.path.getsize(out_path) == 0:
            errors.append(f"WARNING: Output {site_id}.{ext} is empty (0 bytes)")

    return errors


def main():
    parser = argparse.ArgumentParser(
        description="Run EPIC model for workspace sites"
    )
    parser.add_argument("--workspace", required=True,
                        help="Path to Geo-EPIC workspace directory")
    parser.add_argument("--site-id", default=None,
                        help="Run specific site (default: all from info.csv)")
    parser.add_argument("--timeout", type=int, default=30,
                        help="Per-site timeout in seconds")

    args = parser.parse_args()

    # Step 1: Validate workspace
    ws_errors = validate_workspace(args.workspace)
    for e in ws_errors:
        print(e)
    if any("ERROR" in e for e in ws_errors):
        sys.exit(1)

    # Step 2: Read config
    config_path = os.path.join(args.workspace, "config.yml")
    if yaml is not None:
        with open(config_path) as f:
            config = yaml.safe_load(f)
    else:
        config = {
            "start_date": "2000-01-01",
            "duration": 6,
            "output_types": ["ACY", "DGN"],
            "output_dir": "./output"
        }

    # Step 3: Configure model
    model_dir = os.path.join(args.workspace, "model")
    configure_epiccont(model_dir, config["start_date"], config["duration"])
    configure_output_types(model_dir, config.get("output_types", ["ACY", "DGN"]))

    # Step 4: Read site list
    if pd is not None:
        info = pd.read_csv(os.path.join(args.workspace, "info.csv"))
    else:
        print("ERROR: pandas not available")
        sys.exit(1)

    if args.site_id:
        info = info[info["SiteID"] == args.site_id]

    output_dir = os.path.join(args.workspace,
                              config.get("output_dir", "./output"))

    # Step 5: Run each site
    results = {}
    for _, row in info.iterrows():
        sid = str(row["SiteID"])
        print(f"\n--- Running site: {sid} ---")

        run_dir = setup_run_directory(
            args.workspace, sid,
            str(row["soil"]), str(row["dly"]), str(row["opc"]),
            float(row.get("lat", 0)), float(row.get("lon", 0)),
            float(row.get("elev", 100))
        )

        result = run_epic_binary(run_dir, sid, timeout=args.timeout)
        print(f"  Status: {result['status']}")

        if result["status"] == "completed":
            collected = collect_outputs(
                run_dir, output_dir, sid,
                config.get("output_types", ["ACY", "DGN"])
            )
            print(f"  Collected {len(collected)} output files")

            out_errors = validate_outputs(
                output_dir, sid,
                config.get("output_types", ["ACY", "DGN"])
            )
            for e in out_errors:
                print(f"  {e}")

        results[sid] = result

        # Cleanup run directory
        shutil.rmtree(run_dir, ignore_errors=True)

    # Summary
    print(f"\n=== Summary ===")
    completed = sum(1 for r in results.values() if r["status"] == "completed")
    print(f"Completed: {completed}/{len(results)}")

    return results


if __name__ == "__main__":
    main()
