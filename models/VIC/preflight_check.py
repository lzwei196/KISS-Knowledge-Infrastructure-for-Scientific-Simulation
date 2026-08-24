#!/usr/bin/env python3
"""
Software preflight for VIC + CaMa-Flood.

This check answers one question: is the scientific software installed on this
machine?  Input data belongs to an individual GeoForge project and is checked
in that chat's dynamic data panel, not while installing the shared software.

Usage:
    python preflight_check.py

Exit codes:
    0 — all checks passed, safe to proceed
    1 — one or more checks failed, fix before proceeding
"""

import os
import sys
import shutil
import subprocess

PASS = 0
FAIL = 0


def check_file(path, label, executable=False):
    global PASS, FAIL
    if os.path.isfile(path):
        if executable and not os.access(path, os.X_OK):
            print(f"  WARN  {label}: exists but not executable: {path}")
            print(f"         Fix: chmod +x {path}")
            FAIL += 1
        else:
            print(f"  OK    {label}: {path}")
            PASS += 1
    else:
        print(f"  FAIL  {label}: NOT FOUND at {path}")
        FAIL += 1


def report_project_data(path, label):
    """Report reusable reference data without making it an install blocker."""
    if os.path.isdir(path):
        n = len(os.listdir(path))
        print(f"  INFO  Project data already available — {label}: {path} ({n} items)")
    else:
        print(f"  INFO  Project data not installed globally — {label}")
        print(f"        GeoForge will prepare or request it inside the active chat.")


def check_import(module, label):
    # Also search HydroCraft python_env for packages
    import sys
    _penv = "KISSPATH_PYTHON_ENV/lib/python3.12/site-packages"
    if _penv not in sys.path:
        sys.path.insert(0, _penv)
    global PASS, FAIL
    try:
        __import__(module)
        print(f"  OK    {label}: import {module} succeeded")
        PASS += 1
    except ImportError as e:
        print(f"  FAIL  {label}: import {module} failed: {e}")
        print(f"         Fix: pip install {module.split('.')[0]}")
        FAIL += 1


def check_binary_search(name, label):
    global PASS, FAIL
    found = shutil.which(name)
    if found:
        print(f"  OK    {label}: {found}")
        PASS += 1
        return
    # Search common locations
    search_dirs = [
        "KISSPATH_BINARIES",
        "KISSPATH_HOME",
        "/usr/local/bin",
    ]
    for d in search_dirs:
        if not os.path.isdir(d):
            continue
        for root, dirs, files in os.walk(d):
            for f in files:
                if name.lower() in f.lower() and os.access(os.path.join(root, f), os.X_OK):
                    print(f"  OK    {label}: {os.path.join(root, f)}")
                    PASS += 1
                    return
            if root.count(os.sep) - d.count(os.sep) > 3:
                dirs.clear()  # limit depth
    print(f"  FAIL  {label}: binary '{name}' not found in PATH or common locations")
    print(f"         Check SKILL.md for the correct binary path")
    FAIL += 1


def check_common_data():
    """Check common HydroCraft data paths."""
    global PASS, FAIL
    common = [
        ("KISSPATH_OBS", "Observation data"),
        ("KISSPATH_FORCING", "Forcing data"),
        ("KISSPATH_STATIC", "DEM data"),
        ("KISSPATH_STATIC", "Soil data"),
    ]
    for path, label in common:
        if os.path.isdir(path):
            PASS += 1
        else:
            print(f"  WARN  {label}: {path} not found (may not be needed)")


def main():
    global PASS, FAIL
    print(f"=" * 60)
    print(f"  SOFTWARE PREFLIGHT: VIC + CaMa-Flood")
    print(f"=" * 60)
    print()

    # Model-specific checks
    # Binary: VIC 5.1.0 classic driver
    check_file("KISSPATH_BINARIES/VIC-5.1.0/vic/drivers/classic/vic_classic.exe", "VIC 5.1.0 classic driver", executable=True)
    # Binary: CaMa-Flood 4.20
    check_file("KISSPATH_BINARIES/cmf_v420_pkg/src/MAIN_cmf", "CaMa-Flood 4.20", executable=True)
    # These are project inputs, not software installation requirements.  Keep
    # the familiar reference paths visible for existing users, but do not make
    # every new Mac download a China-wide archive before VIC can be verified.
    report_project_data("KISSPATH_FORCING/huai/Data_forcing_01dy_025deg", "CMFD daily forcing")
    report_project_data("KISSPATH_STATIC/china_dem_90m", "DEM 90m")

    print()

    # Common data checks
    check_common_data()

    # Diagnostics available?
    ki_dir = os.path.dirname(os.path.abspath(__file__))
    triplets = os.path.join(ki_dir, "diagnostics", "triplets.yaml")
    if os.path.isfile(triplets):
        print(f"  INFO  Diagnostic triplets available at: {triplets}")
        print(f"         If the model fails, check triplets FIRST for known fixes.")

    print()
    print(f"  Results: {PASS} passed, {FAIL} failed")
    if FAIL > 0:
        print(f"  STATUS: PREFLIGHT FAILED — fix the issues above before running")
        sys.exit(1)
    else:
        print(f"  STATUS: SOFTWARE PREFLIGHT PASSED")
        print(f"          Project inputs will be checked before a model run.")
        sys.exit(0)


if __name__ == "__main__":
    main()
