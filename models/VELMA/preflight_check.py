#!/usr/bin/env python3
"""Preflight check for the VELMA Knowledge Infrastructure."""

import json
import os
import subprocess
import sys


MODEL_ID = "VELMA"
KI_DIR = os.path.dirname(os.path.abspath(__file__))
TOOLS_DIR = os.path.join(KI_DIR, "tools")
RUN_VELMA = os.path.join(TOOLS_DIR, "run_velma.py")
TRIPLETS = os.path.join(KI_DIR, "diagnostics", "triplets.yaml")
PYTHON_ENV = "KISSPATH_PYTHON_ENV/bin/python3"
PYTHON = PYTHON_ENV if os.path.exists(PYTHON_ENV) else sys.executable
CHECKS = []


def recovery_hint(fix):
    return f"{fix}; see {TRIPLETS} for recovery."


def add_check(kind, subject, critical, status, fix=""):
    CHECKS.append(
        {
            "kind": kind,
            "subject": subject,
            "critical": bool(critical),
            "status": status,
            "fix": fix,
        }
    )


def line(status, label, detail):
    print(f"  {status:<5} {label}: {detail}")


def check_file(path, label, critical=True, executable=False):
    subject = os.path.realpath(path)
    if not os.path.isfile(path):
        fix = recovery_hint(f"Restore required file at {path}")
        line("FAIL", label, f"NOT FOUND at {path}")
        add_check("binary" if executable else "data", subject, critical, "fail", fix)
        return False
    if executable and not os.access(path, os.X_OK):
        fix = recovery_hint(f"Run: chmod +x {path}")
        line("FAIL", label, f"exists but is not executable: {path}")
        add_check("binary", subject, critical, "fail", fix)
        return False
    line("OK", label, subject)
    add_check("binary" if executable else "data", subject, critical, "pass", "")
    return True


def check_dir(path, label, critical=True):
    subject = os.path.realpath(path)
    if os.path.isdir(path):
        n_items = len(os.listdir(path))
        line("OK", label, f"{subject} ({n_items} items)")
        add_check("data", subject, critical, "pass", "")
        return True
    fix = recovery_hint(f"Restore required directory at {path}")
    line("FAIL", label, f"directory NOT FOUND at {path}")
    add_check("data", subject, critical, "fail", fix)
    return False


def check_import(module, label, critical=True):
    subject = f"{os.path.realpath(PYTHON)}:import:{module}"
    code = f"import importlib; importlib.import_module({module!r})"
    try:
        subprocess.run(
            [PYTHON, "-c", code],
            cwd=KI_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15,
            check=True,
        )
    except (subprocess.CalledProcessError, OSError, subprocess.TimeoutExpired) as exc:
        detail = str(exc)
        if isinstance(exc, subprocess.CalledProcessError):
            detail = (exc.stderr or exc.stdout or str(exc)).strip()
        fix = recovery_hint(
            f"Install {module.split('.')[0]} for {PYTHON} or restore the HydroCraft python_env"
        )
        line("FAIL", label, f"import {module} failed: {detail}")
        add_check("import", subject, critical, "fail", fix)
        return False
    line("OK", label, f"{subject}")
    add_check("import", subject, critical, "pass", "")
    return True


def check_help_start(path, label, critical=True):
    subject = os.path.realpath(path)
    try:
        result = subprocess.run(
            [subject, "--help"],
            cwd=KI_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        fix = recovery_hint(f"Verify the shebang and executable permissions for {path}")
        line("FAIL", label, f"could not start: {exc}")
        add_check("run", subject, critical, "fail", fix)
        return False
    if result.returncode != 0 or "Run VELMA" not in result.stdout:
        fix = recovery_hint(f"Run {path} --help and repair its imports/CLI")
        detail = (result.stderr or result.stdout or "").strip()
        line("FAIL", label, f"--help exited {result.returncode}: {detail}")
        add_check("run", subject, critical, "fail", fix)
        return False
    line("OK", label, "--help starts and reports the VELMA CLI")
    add_check("run", subject, critical, "pass", "")
    return True


def emit_report():
    print(
        "PREFLIGHT_REPORT="
        + json.dumps({"model_id": MODEL_ID, "checks": CHECKS}, sort_keys=True)
    )
    critical_failed = any(c["critical"] and c["status"] != "pass" for c in CHECKS)
    sys.exit(1 if critical_failed else 0)


def main():
    print(f"{' PREFLIGHT: VELMA ':=^60}")
    print(f"  Python for import checks: {PYTHON}")
    print()

    check_dir(TOOLS_DIR, "KI tools directory", critical=True)
    check_file(RUN_VELMA, "VELMA executable", critical=True, executable=True)
    check_help_start(RUN_VELMA, "VELMA CLI startup", critical=True)

    for rel_path in (
        "knowledge_infrastructure.yaml",
        "dag.yaml",
        "SKILL.md",
        "docs/format_spec.yaml",
        "diagnostics/triplets.yaml",
        "tools/convert_forcing_to_velma.py",
        "tools/convert_soil_to_velma.py",
        "tools/parse_output_velma.py",
    ):
        check_file(os.path.join(KI_DIR, rel_path), rel_path, critical=True)

    for module in (
        "numpy",
        "pandas",
        "scipy",
        "xarray",
        "geopandas",
        "shapely",
        "netCDF4",
    ):
        check_import(module, module, critical=True)
    check_import("matplotlib", "matplotlib", critical=False)

    passed = sum(1 for c in CHECKS if c["status"] == "pass")
    failed = len(CHECKS) - passed
    print()
    print(f"  Results: {passed} passed, {failed} failed")
    if failed:
        print(f"  STATUS: PREFLIGHT FAILED; fixes point to {TRIPLETS}")
    else:
        print("  STATUS: PREFLIGHT PASSED")
    emit_report()


if __name__ == "__main__":
    main()
