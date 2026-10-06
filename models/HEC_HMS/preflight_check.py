#!/usr/bin/env python3
"""Preflight check for the HEC-HMS Knowledge Infrastructure."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


MODEL_ID = "HEC-HMS"
KI_DIR = Path(__file__).resolve().parent
TOOLS_DIR = KI_DIR / "tools"
DIAGNOSTICS = KI_DIR / "diagnostics" / "triplets.yaml"
PYTHON_ENV = Path(os.environ.get("KI_PYTHON", sys.executable))
# The REAL engine: official USACE HEC-HMS 4.14 Linux build, headless launcher.
# Same default as tools/run_hms_engine.py; override with env HMS_ENGINE.
# Made absolute here: the smoke run below is launched with cwd = a temp folder.
ENGINE = Path(os.path.abspath(os.environ.get("HMS_ENGINE", "KISSPATH_HOME/engine_builds_20261006/HEC_HMS/run_hms_headless.sh")))
ENGINE_TOOL = TOOLS_DIR / "run_hms_engine.py"
JYTHON_SMOKE = "from hms.model import Project\nfrom hms import Hms\nprint('HMS_JYTHON_OK')\nHms.shutdownEngine()\n"


def fix_text(action):
    return f"{action}; then check {DIAGNOSTICS} for matching recovery triplets."


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}, sort_keys=True))
    failed_critical = any(c["status"] == "fail" and c.get("critical") for c in checks)
    sys.exit(1 if failed_critical else 0)


def add_check(checks, kind, subject, critical, ok, fix):
    status = "pass" if ok else "fail"
    checks.append({
        "kind": kind,
        "subject": str(subject),
        "critical": bool(critical),
        "status": status,
        "fix": "" if ok else fix,
    })
    label = "OK" if ok else ("FAIL" if critical else "WARN")
    print(f"  {label:<5} {kind}: {subject}")
    if not ok:
        print(f"        Fix: {fix}")
    return ok


def check_file(checks, path, label, critical=True, executable=False):
    path = Path(path)
    ok = path.is_file()
    if ok and executable:
        ok = os.access(path, os.X_OK)
    if executable:
        action = f"ensure {label} exists and is executable: chmod +x {path}"
    else:
        action = f"restore required file for {label}: {path}"
    return add_check(checks, "data", path.resolve() if path.exists() else path, critical, ok, fix_text(action))


def check_dir(checks, path, label, critical=True, non_empty=True):
    path = Path(path)
    ok = path.is_dir() and (not non_empty or any(path.iterdir()))
    action = f"restore required directory for {label}: {path}"
    return add_check(checks, "data", path.resolve() if path.exists() else path, critical, ok, fix_text(action))


def check_python_import(checks, module, critical=True):
    cmd = [str(PYTHON_ENV), "-c", f"import {module}"]
    try:
        proc = subprocess.run(cmd, cwd=KI_DIR, text=True, capture_output=True, timeout=20)
        ok = proc.returncode == 0
        detail = (proc.stderr or proc.stdout).strip().splitlines()
        extra = f" ({detail[-1]})" if detail and not ok else ""
    except Exception as exc:
        ok = False
        extra = f" ({exc})"
    fix = fix_text(f"install/repair Python dependency '{module}' in {PYTHON_ENV}")
    return add_check(checks, "import", f"{module} via {PYTHON_ENV}{extra}", critical, ok, fix)


def check_command(checks, subject, cmd, critical=True, timeout=20):
    try:
        proc = subprocess.run(cmd, cwd=KI_DIR, text=True, capture_output=True, timeout=timeout)
        ok = proc.returncode == 0
        detail = (proc.stderr or proc.stdout).strip().splitlines()
        extra = f" ({detail[-1][:180]})" if detail and not ok else ""
    except Exception as exc:
        ok = False
        extra = f" ({exc})"
    fix = fix_text(f"make this command start successfully: {' '.join(map(str, cmd))}")
    return add_check(checks, "run", f"{subject}{extra}", critical, ok, fix)


def main():
    checks = []

    print("=" * 60)
    print(f"  PREFLIGHT CHECK: {MODEL_ID}")
    print("=" * 60)

    python_ok = PYTHON_ENV.is_file() and os.access(PYTHON_ENV, os.X_OK)
    add_check(
        checks,
        "data",
        PYTHON_ENV,
        True,
        python_ok,
        fix_text(f"restore executable HydroCraft Python interpreter: {PYTHON_ENV}"),
    )

    # The REAL engine. Subjects are the launcher realpath so the gate can
    # compare it with the models DB binary_path.
    eng_real = os.path.realpath(ENGINE)
    eng_ok = ENGINE.is_file() and os.access(ENGINE, os.X_OK)
    add_check(checks, "binary", eng_real, True, eng_ok,
              fix_text(f"restore the headless HEC-HMS launcher {ENGINE} (see its BUILD_LOG.md) or set HMS_ENGINE"))
    hms_home = Path(eng_real).parent / "HEC-HMS-4.14"
    for rel in ("hms.jar", "jre/bin/java", "bin/javaHeclib"):
        add_check(checks, "data", hms_home / rel, True, (hms_home / rel).exists(),
                  fix_text(f"HEC-HMS install is incomplete ({hms_home / rel} missing); re-extract the official 4.14 tarball"))
    # Run the engine: a Jython script that imports the HMS API. The JVM exits 0
    # even when a script fails, so the marker line is the pass condition.
    marker_ok, extra = False, ""
    if eng_ok:
        with tempfile.TemporaryDirectory() as td:
            sp = Path(td) / "smoke.py"
            sp.write_text(JYTHON_SMOKE)
            env = dict(os.environ)
            env.pop("DISPLAY", None)
            try:
                proc = subprocess.run([str(ENGINE), "-script", str(sp)], cwd=td, env=env,
                                      text=True, capture_output=True, timeout=90)
                marker_ok = proc.returncode == 0 and "HMS_JYTHON_OK" in proc.stdout
                if not marker_ok:
                    extra = f" (rc={proc.returncode}; {(proc.stderr or proc.stdout).strip()[-160:]})"
            except Exception as exc:
                extra = f" ({exc})"
    add_check(checks, "run", eng_real + extra, True, marker_ok,
              fix_text(f"make the headless engine run a Jython script: env -u DISPLAY {ENGINE} -script smoke.py"))
    check_command(checks, f"{ENGINE_TOOL.name} --help",
                  [str(PYTHON_ENV), str(ENGINE_TOOL), "--help"], critical=True)

    # tools/run_hec_hms.py (checked below) is the Python SURROGATE: it is kept
    # for the legacy calibration loop and is never the model of record.

    for module in ("numpy", "pandas"):
        check_python_import(checks, module, critical=True)

    # These are required for the documented HydroCraft data-prep/validation tools.
    for module in ("xarray", "geopandas", "shapely", "rasterio", "matplotlib", "scipy"):
        check_python_import(checks, module, critical=True)

    for rel in (
        "tools/run_hms_engine.py",
        "tools/run_hec_hms.py",
        "tools/convert_forcing_to_hms.py",
        "tools/convert_soil_to_hms.py",
        "tools/parse_hms_output.py",
        "tools/validate_hms.py",
        "tools/calibrate_hms.py",
    ):
        check_file(checks, KI_DIR / rel, rel, critical=True)

    check_dir(checks, TOOLS_DIR, "KI tools", critical=True, non_empty=True)
    check_file(checks, KI_DIR / "SKILL.md", "KI instructions", critical=True)
    check_file(checks, KI_DIR / "knowledge_infrastructure.yaml", "KI manifest", critical=True)
    check_file(checks, KI_DIR / "dag.yaml", "KDT DAG", critical=True)
    check_file(checks, KI_DIR / "docs" / "format_spec.yaml", "I/O format specification", critical=True)
    check_file(checks, DIAGNOSTICS, "diagnostic recovery triplets", critical=True)

    check_command(
        checks,
        "compile all HEC-HMS tool scripts",
        [str(PYTHON_ENV), "-m", "py_compile"] + [str(p) for p in sorted(TOOLS_DIR.glob("*.py"))],
        critical=True,
        timeout=30,
    )

    passed = sum(1 for c in checks if c["status"] == "pass")
    failed = len(checks) - passed
    print()
    print(f"  Results: {passed} passed, {failed} failed")
    if failed:
        print(f"  STATUS: PREFLIGHT FAILED - check {DIAGNOSTICS} and fix blockers above")
    else:
        print("  STATUS: PREFLIGHT PASSED - safe to proceed with HEC-HMS execution")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
