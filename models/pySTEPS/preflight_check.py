#!/usr/bin/env python3
"""
Preflight check for pySTEPS — verifies environment before nowcasting.

Run this BEFORE attempting any model execution. It checks that all required
packages and data paths are available.

Usage:
    python preflight_check.py

Exit codes:
    0 — all checks passed, safe to proceed
    1 — one or more checks failed, fix before proceeding
"""

import os
import sys
import shutil

PASS = 0
FAIL = 0
MODEL_NAME = "pySTEPS"


def check_file(path, label, executable=False):
    """Check that a file exists (and is executable if required)."""
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
    """Check that a directory exists and is non-empty."""
    global PASS, FAIL
    if os.path.isdir(path):
        n = len(os.listdir(path))
        print(f"  OK    {label}: {path} ({n} items)")
        PASS += 1
    else:
        print(f"  FAIL  {label}: directory NOT FOUND at {path}")
        FAIL += 1


def check_import(module, label):
    """Check that a Python package can be imported."""
    global PASS, FAIL
    _penv = "KISSPATH_PYTHON_ENV/lib/python3.12/site-packages"
    if _penv not in sys.path:
        sys.path.insert(0, _penv)
    try:
        __import__(module)
        print(f"  OK    {label}: import {module} succeeded")
        PASS += 1
    except ImportError as e:
        print(f"  FAIL  {label}: import {module} failed: {e}")
        print(f"         Fix: pip install {module.split('.')[0]}")
        FAIL += 1


def main():
    global PASS, FAIL
    print(f"{'=' * 60}")
    print(f"  PREFLIGHT CHECK: {MODEL_NAME}")
    print(f"{'=' * 60}")
    print()

    # Core package
    check_import("pysteps", "pySTEPS core")

    # Key submodules exercised by the diagnostic runner
    check_import("pysteps.motion", "pySTEPS motion estimation")
    check_import("pysteps.nowcasts", "pySTEPS nowcasting methods")
    check_import("pysteps.verification", "pySTEPS verification scores")

    # Runtime dependency
    check_import("numpy", "NumPy")

    # Diagnostic runner
    ki_dir = os.path.dirname(os.path.abspath(__file__))
    check_file(
        os.path.join(ki_dir, "diagnostics", "run_synthetic_advection.py"),
        "Synthetic advection diagnostic",
    )

    print()

    # Diagnostics available?
    triplets = os.path.join(ki_dir, "diagnostics", "triplets.yaml")
    if os.path.isfile(triplets):
        print(f"  INFO  Diagnostic triplets available at: {triplets}")
        print(f"         If the model fails, check triplets FIRST for known fixes.")

    # Version info
    try:
        import importlib.metadata as ilm
        ver = ilm.version("pysteps")
        print(f"  INFO  pySTEPS version: {ver}")
    except Exception:
        pass

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
