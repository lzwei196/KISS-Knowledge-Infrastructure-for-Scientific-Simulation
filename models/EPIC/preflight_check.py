#!/usr/bin/env python3
"""Preflight check for the EPIC 1102 KI."""
import os
import sys
import shutil

PASS = 0
FAIL = 0
MODEL_NAME = "EPIC 1102 (v2025-05-25)"


def check_file(path, label, executable=False):
    global PASS, FAIL
    if os.path.isfile(path):
        if executable and not os.access(path, os.X_OK):
            print(f"  WARN  {label}: exists but not executable: {path}")
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


def check_binary_in_path(name, label):
    global PASS, FAIL
    found = shutil.which(name)
    if found:
        print(f"  OK    {label}: {found}")
        PASS += 1
    else:
        print(f"  FAIL  {label}: '{name}' not on PATH")
        print(f"         Fix: install via 'sudo apt install wine'")
        FAIL += 1


def check_import(module, label, fix=None):
    global PASS, FAIL
    try:
        __import__(module)
        print(f"  OK    {label}: import {module} succeeded")
        PASS += 1
    except ImportError as e:
        print(f"  WARN  {label}: import {module} failed: {e}")
        if fix:
            print(f"         Fix: {fix}")
        FAIL += 1


def main():
    global PASS, FAIL
    print("=" * 60)
    print(f"  PREFLIGHT CHECK: {MODEL_NAME}")
    print("=" * 60)

    ki_dir = os.path.dirname(os.path.abspath(__file__))
    templates_dir = os.path.join(ki_dir, "templates")

    # Resolve through the same helper the tools use, so preflight and
    # run_epic.py can never disagree about where the binary lives.
    sys.path.insert(0, os.path.join(ki_dir, "tools"))
    try:
        from _common import resolve_binary
        binary = resolve_binary()
    except Exception:
        binary = os.environ.get(
            "EPIC_BINARY",
            os.path.join(os.path.dirname(ki_dir), "bin",
                         "epic1102-official_release.exe"),
        )
    check_file(binary, "EPIC 1102 binary")
    check_binary_in_path("wine", "Wine runtime")
    check_dir(templates_dir, "templates/")
    for fn in ("EPICRUN.DAT", "EPICCONT.DAT", "EPICFILE.DAT",
               "CROPCOM.DAT", "FERT2012.DAT", "PARM1102.DAT",
               "umstead.SIT", "umstead.SOL", "umstead.OPC",
               "NCRDU.DLY", "NCCLAYTO.WP1", "NCCLAYTO.WND"):
        check_file(os.path.join(templates_dir, fn), f"template {fn}")

    check_dir(os.path.join(ki_dir, "tools"), "tools/")

    print()
    print("  Optional dependencies:")
    for cand in (
        "/home/server/knowledge-dissection-toolkit/ki_tools_common",
        "/home/server/knowledge-dissection-toolkit/kdt-release/ki_tools_common",
    ):
        if os.path.isdir(cand):
            sys.path.insert(0, os.path.dirname(cand))
            break
    check_import("ki_tools_common", "ki_tools_common")
    check_import("ki_tools_common.load_forcing", "load_forcing helper")

    print()
    triplets = os.path.join(ki_dir, "diagnostics", "triplets.yaml")
    if os.path.isfile(triplets):
        print(f"  INFO  Diagnostic triplets: {triplets}")

    print()
    print(f"  Results: {PASS} passed, {FAIL} failed")
    if FAIL > 0:
        print("  STATUS: PREFLIGHT FAILED")
        sys.exit(1)
    print("  STATUS: PREFLIGHT PASSED")
    sys.exit(0)


if __name__ == "__main__":
    main()
