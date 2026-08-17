#!/usr/bin/env python3
"""
preflight_check.py -- Verify the HEC-RAS environment before running the KI.

Checks (in order):
  * wine present and runnable
  * RasSteady.exe (and the other solvers) staged under WINE
  * Python deps: h5py, numpy, matplotlib, ki_tools_common
  * the bundled template project exists with a run file + geometry HDF

Exit 0 if all REQUIRED checks pass, 1 otherwise. Prints a fix hint per failure
and points to diagnostics/triplets.yaml for recovery.
"""
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "tools"))

PASS = 0
FAIL = 0
WARN = 0


def ok(msg):
    global PASS
    PASS += 1
    print(f"  [PASS] {msg}")


def bad(msg, fix):
    global FAIL
    FAIL += 1
    print(f"  [FAIL] {msg}\n         fix: {fix}")


def warn(msg, note):
    global WARN
    WARN += 1
    print(f"  [WARN] {msg}\n         note: {note}")


print("HEC-RAS preflight check")
print("=" * 60)

# 1. wine ------------------------------------------------------------------
print("\n[1] WINE runtime")
wine = shutil.which("wine")
if wine:
    try:
        env = dict(os.environ)
        env.pop("LD_PRELOAD", None)
        env["WINEDEBUG"] = "-all"
        out = subprocess.run([wine, "--version"], capture_output=True, text=True,
                             env=env, timeout=30)
        ver = (out.stdout or out.stderr).strip().splitlines()[-1]
        ok(f"wine available: {ver}")
    except Exception as e:  # noqa
        warn(f"wine present but --version failed: {e}",
             "should still run solvers; strip LD_PRELOAD (triplet wine_ld_preload)")
else:
    bad("wine not found on PATH",
        "install wine (>=6); HEC-RAS solvers are Windows binaries (triplet wine_mono_missing)")

# 2. binaries --------------------------------------------------------------
print("\n[2] HEC-RAS solvers")
try:
    from _hecras_env import BINARIES, TEMPLATE_DIR, TEMPLATE_PRJ
    for kind, path in BINARIES.items():
        if os.path.isfile(path):
            ok(f"{kind}: {os.path.basename(path)}")
        else:
            if kind == "steady":
                bad(f"REQUIRED solver missing: {path}",
                    "verify the WINE-staged HEC-RAS 6.7 Beta 5 install")
            else:
                warn(f"{kind} solver missing: {os.path.basename(path)}",
                     "only steady is required for the validated pipeline")
except Exception as e:  # noqa
    bad(f"could not import tools/_hecras_env.py: {e}", "check the tools/ directory")

# 3. python deps -----------------------------------------------------------
print("\n[3] Python dependencies")
for mod, hint in [("h5py", "pip install h5py"),
                  ("numpy", "pip install numpy"),
                  ("matplotlib", "pip install matplotlib")]:
    try:
        __import__(mod)
        ok(f"import {mod}")
    except Exception:  # noqa
        bad(f"cannot import {mod}", hint)

try:
    import ki_tools_common  # noqa
    from ki_tools_common.metrics import all_metrics  # noqa
    ok("import ki_tools_common (metrics)")
except Exception as e:  # noqa
    warn(f"ki_tools_common import issue: {e}",
         "validate_hecras falls back to a built-in metrics calc")

# 4. template project ------------------------------------------------------
print("\n[4] Bundled template project")
try:
    from _hecras_env import TEMPLATE_DIR, TEMPLATE_PRJ
    need = [f"{TEMPLATE_PRJ}.r01", f"{TEMPLATE_PRJ}.g01.hdf",
            f"{TEMPLATE_PRJ}.f01", f"{TEMPLATE_PRJ}.PRJ"]
    miss = [n for n in need if not os.path.isfile(os.path.join(TEMPLATE_DIR, n))]
    if miss:
        bad(f"template incomplete, missing: {miss}",
            "restore examples/MixedFlowSteady/ from the HEC-RAS example library")
    else:
        ok(f"template OK: {TEMPLATE_DIR}")
except Exception as e:  # noqa
    bad(f"template check failed: {e}", "check examples/MixedFlowSteady/")

# 5. new-river authoring path (optional; needed ONLY for brand-new geometry) ---
# The validated steady pipeline (run on the bundled template / any project that
# already ships a .gNN.hdf + .rNN) does NOT need this. It is required only to
# AUTHOR a new river's cross-section geometry from a DEM (SKILL.md §10/§11
# routing recipe). Surfaced as WARN so agents know up-front whether the
# new-basin path is executable here.
print("\n[5] New-river authoring path (optional — only for brand-new geometry)")
try:
    import ras_commander  # noqa
    ok(f"ras_commander available (v{getattr(ras_commander, '__version__', '?')})")
except Exception:  # noqa
    # FALSE-NEGATIVE GUARD (2026-06-04): ras_commander 0.93.0 ships in the
    # python_env venv, whose site-packages is NOT on /usr/bin/python3's path.
    import sys as _sys
    _sp = "KISSPATH_PYTHON_ENV/lib/python3.12/site-packages"
    if _sp not in _sys.path:
        _sys.path.insert(0, _sp)
    try:
        import ras_commander  # noqa
        ok(f"ras_commander available (v{getattr(ras_commander, '__version__', '?')}) "
           "via python_env; invoke authoring tools with "
           "KISSPATH_PYTHON_ENV/bin/python3")
    except Exception:  # noqa
        warn("ras_commander NOT importable from /usr/bin/python3 OR python_env",
             "new-river authoring would be non-executable; steady runs on EXISTING "
             "geometry are unaffected.")

# summary ------------------------------------------------------------------
print("\n" + "=" * 60)
print(f"PASS={PASS}  WARN={WARN}  FAIL={FAIL}")
if FAIL:
    print("Preflight FAILED. See diagnostics/triplets.yaml for recovery.")
    sys.exit(1)
print("Preflight OK. Run: python3 tools/run_hecras.py --out /tmp/out")
sys.exit(0)
