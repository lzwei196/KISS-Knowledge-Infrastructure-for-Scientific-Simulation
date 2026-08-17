#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
==========================================
Tool ID:      verify_dlbreach
Stage:        s1_installation
Description:  Verify DLBreach binary is available and functional.
              Checks for the binary (native Linux or Windows .exe via Wine),
              runs a minimal test case, and confirms output generation.

Inputs:
  --dlbreach_path: path to DLBreach binary (auto-detected if omitted)

Outputs:
  - JSON with binary_path, platform, status, test_result

Exit codes:
  0 -- success (binary found and test passed)
  1 -- input validation failed
  2 -- binary not found or not executable
  3 -- test run failed (binary found but produced no output)
"""

import sys
import os
import json
import shutil
import logging
import subprocess
import tempfile
import argparse
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path("KISSPATH_ROOT")
DEFAULT_SEARCH_PATHS = [
    PROJECT_ROOT / "model" / "dlbreach" / "bin" / "DLBreach.exe",
    PROJECT_ROOT / "model" / "dlbreach" / "bin" / "dlbreach",
    PROJECT_ROOT / "model" / "dlbreach" / "bin" / "DLBreach",
    PROJECT_ROOT / "model" / "dlbreach" / "DLBreach_Barrier" / "DLBreach.exe",
]

# Minimal test input (Teton Dam simplified case)
MINIMAL_TEST_INPUT = """Time_Step    1.0                ! in sec
Simulation_Period    0.0, 3600.0    ! 1 hour in sec
Embankment_Height    93.0           ! in m
Embankment_Crest_Width    10.0      ! in m
Embankment_Upstream_Slope    0.4    ! V/H
Embankment_Downstream_Slope    0.4  ! V/H
Embankment_Length    200.0          ! in m
Breach_Mode    1                    ! overtopping
Overtopping_Mode    1               ! surface erosion
Initial_Overtopping_Breach    0.3, 2.0    ! depth, width in m
Breach_Location    2.0              ! two-sided
Noncohesive_or_Cohesive_Sediment    1    ! noncohesive
Sediment_Diameter    0.001          ! in m
Sediment_Specific_Gravity    2.65
Sediment_Porosity    0.35
Sediment_Clay_Content    0.0
Sediment_Cohesion    0.0            ! Pa
Sediment_Internal_Friction    0.75  ! tan(phi)
Noncohesive_Sed_Adaptation_Lamda    6.0
Breach_Manning_n    0.025
Initial_Up&Downstream_WSL    90.0, 0.01    ! in m
Upstream_Reservoir    2, 3.9e9, 2.3e7, 93.0
"""

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def find_binary(user_path=None):
    """Locate DLBreach binary."""
    if user_path:
        p = Path(user_path)
        if p.exists():
            return str(p), "user_specified"
        else:
            return None, f"user path not found: {user_path}"

    # Search default paths
    for p in DEFAULT_SEARCH_PATHS:
        if p.exists():
            return str(p), "default_search"

    # Check PATH
    which_result = shutil.which("DLBreach") or shutil.which("dlbreach") or shutil.which("DLBreach.exe")
    if which_result:
        return which_result, "system_path"

    return None, "not_found"


def detect_platform(binary_path):
    """Determine if this is a native Linux binary or Windows .exe."""
    bp = Path(binary_path)
    if bp.suffix.lower() == ".exe":
        # Check if Wine is available
        wine = shutil.which("wine")
        if wine:
            return "windows_exe_wine", wine
        else:
            return "windows_exe_no_wine", None
    else:
        # Check if it's executable
        if os.access(binary_path, os.X_OK):
            return "linux_native", None
        else:
            return "linux_not_executable", None


def run_test(binary_path, platform, wine_path=None):
    """Run a minimal test case."""
    with tempfile.TemporaryDirectory(prefix="dlbreach_test_") as tmpdir:
        # Write test input
        input_file = Path(tmpdir) / "test.txt"
        input_file.write_text(MINIMAL_TEST_INPUT)

        # Build command
        if platform == "windows_exe_wine":
            cmd = [wine_path, binary_path]
        elif platform == "linux_native":
            cmd = [binary_path]
        else:
            return False, f"unsupported platform: {platform}"

        # Run DLBreach (it prompts for casename on stdin)
        try:
            proc = subprocess.run(
                cmd,
                input="test\n",
                cwd=tmpdir,
                capture_output=True,
                text=True,
                timeout=60,
            )

            output_file = Path(tmpdir) / "test.out"
            if output_file.exists() and output_file.stat().st_size > 0:
                # Verify output has 13 columns
                lines = output_file.read_text().strip().split("\n")
                data_lines = [l for l in lines if l.strip() and not l.strip().startswith("#")]
                if data_lines:
                    ncols = len(data_lines[-1].split())
                    if ncols == 13:
                        return True, f"test passed, {len(data_lines)} output lines, 13 columns"
                    else:
                        return False, f"unexpected column count: {ncols} (expected 13)"
                else:
                    return False, "output file has no data lines"
            else:
                stderr_msg = proc.stderr[:500] if proc.stderr else "no stderr"
                return False, f"no output file generated. exit_code={proc.returncode}, stderr={stderr_msg}"

        except subprocess.TimeoutExpired:
            return False, "test timed out after 60 seconds"
        except Exception as e:
            return False, f"execution error: {str(e)}"


def main():
    parser = argparse.ArgumentParser(description="Verify DLBreach installation")
    parser.add_argument("--dlbreach_path", type=str, default=None,
                        help="Path to DLBreach binary (auto-detected if omitted)")
    parser.add_argument("--json", action="store_true", help="Output JSON only")
    args = parser.parse_args()

    result = {
        "binary_path": None,
        "platform": None,
        "wine_path": None,
        "test_passed": False,
        "test_message": None,
        "status": "error",
        "errors": [],
        "recommendations": [],
    }

    # Step 1: Find binary
    binary_path, find_status = find_binary(args.dlbreach_path)

    if binary_path is None:
        result["errors"].append(f"DLBreach binary not found ({find_status})")
        result["recommendations"] = [
            "Download from https://webspace.clarkson.edu/~wwu/DLBreach.html",
            "Place DLBreach.exe in model/dlbreach/bin/",
            "For Linux: compile Fortran source with gfortran, or install Wine to run .exe",
            "Wine install: sudo apt-get install wine",
        ]
        result["status"] = "binary_not_found"
        logger.warning("DLBreach binary not found. See recommendations.")
        print(json.dumps(result, indent=2))
        sys.exit(2)

    result["binary_path"] = binary_path
    logger.info(f"Binary found: {binary_path} (via {find_status})")

    # Step 2: Detect platform
    platform, wine_path = detect_platform(binary_path)
    result["platform"] = platform
    result["wine_path"] = wine_path

    if platform == "windows_exe_no_wine":
        result["errors"].append("Windows .exe found but Wine is not installed")
        result["recommendations"] = [
            "Install Wine: sudo apt-get install wine",
            "Or compile DLBreach from Fortran source for native Linux execution",
        ]
        result["status"] = "wine_not_available"
        logger.warning("Windows .exe found but Wine not available.")
        print(json.dumps(result, indent=2))
        sys.exit(2)

    if platform == "linux_not_executable":
        result["errors"].append("Binary found but not executable")
        result["recommendations"] = [f"Run: chmod +x {binary_path}"]
        result["status"] = "not_executable"
        print(json.dumps(result, indent=2))
        sys.exit(2)

    logger.info(f"Platform: {platform}")

    # Step 3: Run test
    test_passed, test_msg = run_test(binary_path, platform, wine_path)
    result["test_passed"] = test_passed
    result["test_message"] = test_msg

    if test_passed:
        result["status"] = "success"
        logger.info(f"Test result: {test_msg}")
    else:
        result["status"] = "test_failed"
        result["errors"].append(test_msg)
        logger.warning(f"Test failed: {test_msg}")

    print(json.dumps(result, indent=2))
    sys.exit(0 if test_passed else 3)


if __name__ == "__main__":
    main()
