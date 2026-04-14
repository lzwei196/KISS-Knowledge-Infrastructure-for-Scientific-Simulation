#!/usr/bin/env python3
"""
EPIC0810 pre-flight check.

Verifies binary, template files, Python dependencies, and shared utilities
BEFORE attempting a real run. Exits 0 on success, 1 on any failure.

Each failure prints a specific fix instruction. Errors that are documented in
diagnostics/triplets.yaml include the triplet ID.
"""

import os
import sys

EPIC_BINARY = "/home/server/knowledge-dissection-toolkit/auto_dissect_multi_agent/_work_v2/EPIC/source/repo/epic0810.x"
EXAMPLE_DIR = "/home/server/knowledge-dissection-toolkit/auto_dissect_multi_agent/_work_v2/EPIC/source/repo/epic1102_example_files_20221002"

REQUIRED_TEMPLATE_FILES = [
    "EPICCONT.DAT", "EPICFILE.DAT", "EPICRUN.DAT",
    "PARM1102.DAT", "PRNT1102.DAT",
    "CROPCOM.DAT", "TILLCOM.DAT", "PESTCOM.DAT", "FERT2012.DAT",
    "SOIL35K.DAT",
    "SITECOM.DAT", "SOILCOM.DAT", "OPSCCOM.DAT", "WDLSTCOM.DAT",
    "umstead.SIT", "umstead.SOL", "umstead.OPC",
    "NCRDU.DLY",
]

REQUIRED_PY_PACKAGES = ["numpy", "pandas", "yaml"]


def check(label, ok, fix_instruction):
    mark = "✓" if ok else "✗"
    print(f"  {mark} {label}")
    if not ok:
        print(f"      FIX: {fix_instruction}")
    return ok


def main() -> int:
    print("EPIC0810 preflight check")
    print("=" * 50)
    failures = 0

    print("\n[1/4] Binary")
    ok = os.path.exists(EPIC_BINARY)
    if not check(f"binary at {EPIC_BINARY}", ok,
                 f"Re-extract the EPIC tarball into {os.path.dirname(EPIC_BINARY)}"):
        failures += 1
    if ok and not os.access(EPIC_BINARY, os.X_OK):
        if not check("binary is executable", False,
                     f"chmod +x {EPIC_BINARY}"):
            failures += 1

    print("\n[2/4] Template files")
    for f in REQUIRED_TEMPLATE_FILES:
        path = os.path.join(EXAMPLE_DIR, f)
        if not check(f, os.path.exists(path),
                     f"Restore {path} from the EPIC1102 example bundle"):
            failures += 1

    print("\n[3/4] Python dependencies")
    for pkg in REQUIRED_PY_PACKAGES:
        try:
            __import__(pkg)
            check(pkg, True, "")
        except ImportError:
            check(pkg, False, f"pip install {pkg}")
            failures += 1

    print("\n[4/4] Shared utilities (ki_tools_common)")
    try:
        from ki_tools_common.load_forcing import load_daily_forcing  # noqa
        check("ki_tools_common.load_forcing", True, "")
    except ImportError:
        check("ki_tools_common.load_forcing", False,
              "Add /home/server/knowledge-dissection-toolkit to PYTHONPATH "
              "or install kdt-release")
        failures += 1
    try:
        from ki_tools_common.soil_utils import lookup_hwsd  # noqa
        check("ki_tools_common.soil_utils", True, "")
    except ImportError:
        check("ki_tools_common.soil_utils", False,
              "Add /home/server/knowledge-dissection-toolkit to PYTHONPATH")
        failures += 1
    try:
        from ki_tools_common.metrics import all_metrics  # noqa
        check("ki_tools_common.metrics", True, "")
    except ImportError:
        check("ki_tools_common.metrics", False,
              "Add /home/server/knowledge-dissection-toolkit to PYTHONPATH")
        failures += 1

    print("\n" + "=" * 50)
    if failures:
        print(f"FAIL: {failures} preflight checks failed")
        print("See diagnostics/triplets.yaml for documented error patterns.")
        return 1
    print("OK: all preflight checks passed")
    print("Next: python tools/run_epic_workspace.py --workspace /tmp/epic_run1")
    return 0


if __name__ == "__main__":
    sys.exit(main())
