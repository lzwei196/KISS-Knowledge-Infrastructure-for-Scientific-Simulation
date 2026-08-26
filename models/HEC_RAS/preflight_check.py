#!/usr/bin/env python3
"""
preflight_check.py -- Verify the HEC-RAS environment before running the KI.

Checks everything needed before model execution:
  * WINE is present and runnable
  * the real HEC-RAS steady solver exists, is executable, and starts cheaply
  * supporting HEC-RAS solver binaries are staged under WINE
  * required Python imports are available
  * the bundled MixedFlowSteady template project is complete

The final output line is the gate contract:
PREFLIGHT_REPORT=<json>
"""
import importlib
import json
import os
import shutil
import subprocess
import sys

MODEL_ID = "HEC-RAS"
HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS_DIR = os.path.join(HERE, "tools")
PYTHON_ENV = "KISSPATH_PYTHON_ENV/bin/python3"
TRIPLETS = os.path.join(HERE, "diagnostics", "triplets.yaml")

sys.path.insert(0, TOOLS_DIR)

PASS = 0
FAIL = 0
WARN = 0
CHECKS = []


def add_check(kind, subject, critical, status, fix=""):
    CHECKS.append({
        "kind": kind,
        "subject": os.path.realpath(subject) if kind == "binary" and os.path.exists(subject) else subject,
        "critical": bool(critical),
        "status": status,
        "fix": fix,
    })


def ok(msg, kind, subject, critical=True):
    global PASS
    PASS += 1
    print(f"  [PASS] {msg}")
    add_check(kind, subject, critical, "pass")


def bad(msg, fix, kind, subject, critical=True):
    global FAIL
    FAIL += 1
    print(f"  [FAIL] {msg}\n         fix: {fix}")
    add_check(kind, subject, critical, "fail", fix)


def warn(msg, note, kind, subject):
    global WARN
    WARN += 1
    print(f"  [WARN] {msg}\n         note: {note}")
    add_check(kind, subject, False, "fail", note)


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}, sort_keys=True))
    critical_failed = any(c["critical"] and c["status"] != "pass" for c in checks)
    sys.exit(1 if critical_failed else 0)


def clean_wine_env():
    env = dict(os.environ)
    env.pop("LD_PRELOAD", None)
    env["WINEPREFIX"] = env.get("WINEPREFIX", "KISSPATH_HOME/.wine")
    env["WINEDEBUG"] = "-all"
    return env


def check_import(module, hint, critical=True):
    try:
        importlib.import_module(module)
        ok(f"import {module}", "import", module, critical)
    except Exception as exc:  # noqa: BLE001
        if critical:
            bad(f"cannot import {module}: {exc}", hint, "import", module, True)
        else:
            warn(f"cannot import {module}: {exc}", hint, "import", module)


def check_import_with_interpreter(interpreter, module, hint, critical=False):
    subject = f"{interpreter} -c import {module}"
    if not os.path.isfile(interpreter):
        warn(f"{module} interpreter missing: {interpreter}", hint, "import", subject)
        return
    code = (
        "import warnings; warnings.simplefilter('ignore'); "
        f"import {module}; "
        f"print(getattr({module}, '__version__', '?'))"
    )
    try:
        proc = subprocess.run(
            [interpreter, "-c", code],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception as exc:  # noqa: BLE001
        if critical:
            bad(f"cannot import {module} with {interpreter}: {exc}", hint, "import", subject, True)
        else:
            warn(f"{module} import check failed with {interpreter}: {exc}", hint, "import", subject)
        return

    if proc.returncode == 0:
        version = (proc.stdout or "?").strip().splitlines()[-1]
        ok(f"{module} available via python_env (v{version})", "import", subject, critical)
    elif critical:
        err = (proc.stderr or proc.stdout or "").strip()
        bad(f"cannot import {module} with {interpreter}: {err}", hint, "import", subject, True)
    else:
        err = (proc.stderr or proc.stdout or "").strip()
        warn(f"{module} NOT importable with python_env: {err}", hint, "import", subject)


def check_file(path, label, critical=True, executable=False):
    if not os.path.isfile(path):
        fix = "restore the WINE-staged HEC-RAS 6.7 Beta 5 install; see diagnostics/triplets.yaml"
        if critical:
            bad(f"{label} missing: {path}", fix, "binary", path, True)
        else:
            warn(f"{label} missing: {path}", fix, "binary", path)
        return False
    if executable and not os.access(path, os.X_OK):
        fix = f"chmod +x {path}; see diagnostics/triplets.yaml"
        if critical:
            bad(f"{label} exists but is not executable: {path}", fix, "binary", path, True)
        else:
            warn(f"{label} exists but is not executable: {path}", fix, "binary", path)
        return False
    ok(f"{label}: {os.path.basename(path)}", "binary", path, critical)
    return True


def check_data_file(path, label, critical=True):
    if os.path.isfile(path):
        ok(f"{label}: {path}", "data", path, critical)
    else:
        fix = "restore examples/MixedFlowSteady/ from the HEC-RAS example library; see diagnostics/triplets.yaml"
        if critical:
            bad(f"{label} missing: {path}", fix, "data", path, True)
        else:
            warn(f"{label} missing: {path}", fix, "data", path)


def main():
    print("HEC-RAS preflight check")
    print("=" * 60)

    print("\n[1] WINE runtime")
    wine = shutil.which("wine")
    if wine:
        wine_real = os.path.realpath(wine)
        try:
            proc = subprocess.run(
                [wine, "--version"],
                capture_output=True,
                text=True,
                env=clean_wine_env(),
                timeout=30,
            )
            if proc.returncode == 0:
                ver = (proc.stdout or proc.stderr).strip().splitlines()[-1]
                ok(f"wine available: {ver}", "binary", wine_real, True)
            else:
                bad(
                    f"wine --version failed with exit {proc.returncode}",
                    "repair WINE install; strip LD_PRELOAD; see diagnostics/triplets.yaml",
                    "binary",
                    wine_real,
                    True,
                )
        except Exception as exc:  # noqa: BLE001
            bad(
                f"wine present but --version failed: {exc}",
                "repair WINE install; strip LD_PRELOAD; see diagnostics/triplets.yaml",
                "binary",
                wine_real,
                True,
            )
    else:
        bad(
            "wine not found on PATH",
            "install wine (>=6); HEC-RAS solvers are Windows binaries; see diagnostics/triplets.yaml",
            "binary",
            "wine",
            True,
        )

    print("\n[2] HEC-RAS solvers")
    env_imported = False
    binaries = {}
    template_dir = None
    template_prj = None
    try:
        from _hecras_env import BINARIES, TEMPLATE_DIR, TEMPLATE_PRJ

        binaries = BINARIES
        template_dir = TEMPLATE_DIR
        template_prj = TEMPLATE_PRJ
        env_imported = True
        ok("import tools/_hecras_env.py", "import", "_hecras_env", True)
    except Exception as exc:  # noqa: BLE001
        bad(
            f"could not import tools/_hecras_env.py: {exc}",
            "check the tools/ directory; see diagnostics/triplets.yaml",
            "import",
            "_hecras_env",
            True,
        )

    steady_path = binaries.get("steady")
    steady_ready = False
    if steady_path:
        steady_ready = check_file(steady_path, "steady solver", True, executable=True)
    elif env_imported:
        bad(
            "steady solver path missing from BINARIES",
            "restore tools/_hecras_env.py BINARIES['steady']; see diagnostics/triplets.yaml",
            "binary",
            "BINARIES['steady']",
            True,
        )

    for kind, path in sorted(binaries.items()):
        if kind == "steady":
            continue
        check_file(path, f"{kind} solver", False, executable=True)

    if wine and steady_ready:
        subject = os.path.realpath(steady_path)
        try:
            proc = subprocess.run(
                [wine, steady_path],
                capture_output=True,
                text=True,
                env=clean_wine_env(),
                timeout=20,
            )
            output = (proc.stdout or proc.stderr or "").strip()
            if proc.returncode == 0:
                ok("RasSteady.exe starts under WINE", "run", subject, True)
            else:
                bad(
                    f"RasSteady.exe launch returned {proc.returncode}: {output[:300]}",
                    "repair the WINE-staged HEC-RAS install; see diagnostics/triplets.yaml",
                    "run",
                    subject,
                    True,
                )
        except subprocess.TimeoutExpired:
            bad(
                "RasSteady.exe launch timed out",
                "inspect WINE/HEC-RAS startup; see diagnostics/triplets.yaml",
                "run",
                subject,
                True,
            )
        except Exception as exc:  # noqa: BLE001
            bad(
                f"RasSteady.exe launch failed: {exc}",
                "repair WINE/HEC-RAS environment; see diagnostics/triplets.yaml",
                "run",
                subject,
                True,
            )

    print("\n[3] Python dependencies")
    check_import("h5py", "pip install h5py; see diagnostics/triplets.yaml", True)
    check_import("numpy", "pip install numpy; see diagnostics/triplets.yaml", True)
    check_import("matplotlib", "pip install matplotlib; see diagnostics/triplets.yaml", True)
    check_import("ki_tools_common", "install/restore ki_tools_common; see diagnostics/triplets.yaml", False)
    check_import("ki_tools_common.metrics", "install/restore ki_tools_common metrics; see diagnostics/triplets.yaml", False)

    print("\n[4] Bundled template project")
    if template_dir and template_prj:
        required = [
            f"{template_prj}.r01",
            f"{template_prj}.g01.hdf",
            f"{template_prj}.f01",
            f"{template_prj}.PRJ",
        ]
        for name in required:
            check_data_file(os.path.join(template_dir, name), f"template {name}", True)
    elif env_imported:
        bad(
            "template project constants missing from _hecras_env.py",
            "restore TEMPLATE_DIR and TEMPLATE_PRJ in tools/_hecras_env.py; see diagnostics/triplets.yaml",
            "data",
            "TEMPLATE_DIR/TEMPLATE_PRJ",
            True,
        )

    print("\n[5] Diagnostics")
    check_data_file(TRIPLETS, "diagnostic triplets", False)

    print("\n[6] New-river authoring path (optional; only for brand-new geometry)")
    check_import_with_interpreter(
        PYTHON_ENV,
        "ras_commander",
        "new-river authoring would be unavailable; install ras_commander in python_env; steady runs on existing geometry are unaffected; see diagnostics/triplets.yaml",
        False,
    )

    print("\n" + "=" * 60)
    print(f"PASS={PASS}  WARN={WARN}  FAIL={FAIL}")
    if any(c["critical"] and c["status"] != "pass" for c in CHECKS):
        print("Preflight FAILED. See diagnostics/triplets.yaml for recovery.")
    else:
        print("Preflight OK. Run: python3 tools/run_hecras.py --out /tmp/out")
    emit_report(MODEL_ID, CHECKS)


if __name__ == "__main__":
    main()
