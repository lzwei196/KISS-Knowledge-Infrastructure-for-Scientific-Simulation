#!/usr/bin/env python3
"""
Preflight check for SWAT+ — verifies environment before simulation.

Run this BEFORE attempting any model execution. It checks that all required
binaries, packages, and data paths are available.

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


def check_dir(path, label):
    global PASS, FAIL
    if os.path.isdir(path):
        n = len(os.listdir(path))
        print(f"  OK    {label}: {path} ({n} items)")
        PASS += 1
    else:
        print(f"  FAIL  {label}: directory NOT FOUND at {path}")
        FAIL += 1


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
    print(f"  PREFLIGHT CHECK: SWAT+")
    print(f"=" * 60)
    print()

    # Model-specific checks
    # Binary: SWAT+ Rev 59.3 (5.6MB, Jul 2019). HydroCraft projects use
    # sd_channel_control3, which the post-2023 recompile crashes on
    # (SIGSEGV in ch_initial_ -> proc_cha_; `ch` array allocated size 0).
    # See diagnostics/triplets.yaml (pattern "SIGSEGV in ch_initial_").
    # DO NOT use .../wangjiaba/run/swatplus — that is the broken 6.5MB recompile
    # ("Revision unknown", GNU 13.3.0) that segfaults on channel init.
    REV59_CANDIDATES = [
        "KISSPATH_KI_ROOT/SWAT_Plus/test_rev59/swatplus_rev59",
        "KISSPATH_OUTPUTS/chaohe_2000_2010_025deg/swatplus_cn2_test/swatplus_rev59",
    ]
    rev59 = next((p for p in REV59_CANDIDATES if os.path.isfile(p)), None)
    if rev59:
        check_file(rev59, "SWAT+ Rev 59.3 binary (5.6MB, Jul 2019)", executable=True)
        print(f"  INFO  Run with: python tools/s8/run_swatplus.py {rev59} <TxtInOut>")
    else:
        check_file(REV59_CANDIDATES[0], "SWAT+ Rev 59.3 binary (5.6MB, Jul 2019)", executable=True)

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
        print(f"  STATUS: PREFLIGHT PASSED — safe to proceed with model execution")
        sys.exit(0)


if __name__ == "__main__":
    main()
