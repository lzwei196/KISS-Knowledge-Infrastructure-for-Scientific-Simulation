#!/usr/bin/env python3
"""Preflight check for the Elmer/Ice KI.

This script verifies the executable, Python tool dependencies, KI support files,
and bundled example mesh before model execution.
"""

import importlib.util
import json
import os
import subprocess
import sys


MODEL_ID = "Elmer-Ice"
KI_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_ROOT = os.path.dirname(KI_DIR)
DIAGNOSTICS = os.path.join(KI_DIR, "diagnostics", "triplets.yaml")
PYTHON_ENV_SITE = "KISSPATH_PYTHON_ENV/lib/python3.12/site-packages"

SOLVER = os.path.join(MODEL_ROOT, "bin", "bin", "ElmerSolver")
ELMERGRID = os.path.join(MODEL_ROOT, "bin", "bin", "ElmerGrid")

# Keep the previous KDT/models-DB install path checked as a real executable
# mirror. The KI-local install above is the preferred path for new runs.
LEGACY_SOLVER = (
    "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/"
    "Elmer_Ice/install/bin/ElmerSolver"
)


def add_check(checks, kind, subject, critical, status, fix=""):
    checks.append(
        {
            "kind": kind,
            "subject": subject,
            "critical": bool(critical),
            "status": status,
            "fix": fix,
        }
    )
    label = "OK" if status == "pass" else "FAIL"
    print(f"  {label:<5} {kind}: {subject}")
    if status != "pass" and fix:
        print(f"        Fix: {fix}")


def recovery_hint(action):
    return f"{action}; then check {DIAGNOSTICS} for matching recovery triplets."


def real_subject(path):
    return os.path.realpath(path) if os.path.exists(path) else path


def check_file(checks, path, label, critical=True, executable=False):
    subject = real_subject(path)
    if not os.path.isfile(path):
        add_check(
            checks,
            "data",
            subject,
            critical,
            "fail",
            recovery_hint(f"Restore missing {label}: {path}"),
        )
        return False
    if executable and not os.access(path, os.X_OK):
        add_check(
            checks,
            "binary",
            subject,
            critical,
            "fail",
            recovery_hint(f"Make {label} executable: chmod +x {path}"),
        )
        return False
    add_check(checks, "binary" if executable else "data", subject, critical, "pass")
    return True


def check_dir(checks, path, label, critical=True, expected_files=None):
    subject = real_subject(path)
    if not os.path.isdir(path):
        add_check(
            checks,
            "data",
            subject,
            critical,
            "fail",
            recovery_hint(f"Restore missing {label}: {path}"),
        )
        return False

    missing = [
        rel for rel in (expected_files or [])
        if not os.path.isfile(os.path.join(path, rel))
    ]
    if missing:
        add_check(
            checks,
            "data",
            subject,
            critical,
            "fail",
            recovery_hint(f"Restore {label}; missing files: {', '.join(missing)}"),
        )
        return False

    suffix = f" ({len(os.listdir(path))} items)"
    add_check(checks, "data", subject + suffix, critical, "pass")
    return True


def check_import(checks, module, critical=True):
    if PYTHON_ENV_SITE not in sys.path and os.path.isdir(PYTHON_ENV_SITE):
        sys.path.insert(0, PYTHON_ENV_SITE)

    if importlib.util.find_spec(module) is None:
        add_check(
            checks,
            "import",
            f"{sys.executable}: import {module}",
            critical,
            "fail",
            recovery_hint(
                f"Install {module.split('.')[0]} for this interpreter "
                f"({sys.executable}) or HydroCraft python_env"
            ),
        )
        return False

    add_check(checks, "import", f"{sys.executable}: import {module}", critical, "pass")
    return True


def check_binary_starts(checks, binary):
    subject = real_subject(binary)
    if not os.path.isfile(binary) or not os.access(binary, os.X_OK):
        add_check(
            checks,
            "run",
            subject,
            True,
            "fail",
            recovery_hint(f"Restore executable before startup test: {binary}"),
        )
        return False

    env = os.environ.copy()
    libdir = os.path.join(MODEL_ROOT, "bin", "lib", "elmersolver")
    env["LD_LIBRARY_PATH"] = (
        libdir + os.pathsep + env["LD_LIBRARY_PATH"]
        if env.get("LD_LIBRARY_PATH")
        else libdir
    )

    try:
        result = subprocess.run(
            [binary, "-h"],
            cwd=KI_DIR,
            env=env,
            text=True,
            capture_output=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        add_check(
            checks,
            "run",
            subject + " -h",
            True,
            "fail",
            recovery_hint("ElmerSolver startup timed out"),
        )
        return False
    except OSError as exc:
        add_check(
            checks,
            "run",
            subject + " -h",
            True,
            "fail",
            recovery_hint(f"ElmerSolver could not start: {exc}"),
        )
        return False

    combined = (result.stdout or "") + (result.stderr or "")
    if "ELMER SOLVER" in combined or "ElmerSolver finite element" in combined:
        add_check(checks, "run", subject + " -h", True, "pass")
        return True

    add_check(
        checks,
        "run",
        subject + " -h",
        True,
        "fail",
        recovery_hint(
            "ElmerSolver executed but did not print the expected startup banner"
        ),
    )
    return False


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}))
    has_failed_critical = any(
        c["status"] != "pass" and c.get("critical") for c in checks
    )
    sys.exit(1 if has_failed_critical else 0)


def main():
    checks = []

    print(f"{' PREFLIGHT: Elmer/Ice ':=^60}")
    print()

    check_dir(
        checks,
        os.path.join(KI_DIR, "tools"),
        "KI tools directory",
        critical=True,
        expected_files=[
            "convert_geometry.py",
            "convert_forcing.py",
            "generate_sif.py",
            "run_elmerice.py",
            "parse_vtu_output.py",
        ],
    )
    check_file(checks, os.path.join(KI_DIR, "SKILL.md"), "SKILL.md", critical=True)
    check_file(
        checks,
        os.path.join(KI_DIR, "knowledge_infrastructure.yaml"),
        "knowledge_infrastructure.yaml",
        critical=True,
    )
    check_file(checks, os.path.join(KI_DIR, "dag.yaml"), "dag.yaml", critical=True)
    check_file(checks, DIAGNOSTICS, "diagnostic triplets", critical=True)

    check_file(checks, SOLVER, "KI-local ElmerSolver", critical=True, executable=True)
    check_binary_starts(checks, SOLVER)
    check_file(checks, ELMERGRID, "ElmerGrid mesh generator", critical=True, executable=True)
    check_file(
        checks,
        LEGACY_SOLVER,
        "models-DB ElmerSolver mirror",
        critical=False,
        executable=True,
    )

    check_import(checks, "numpy", critical=True)
    check_import(checks, "scipy", critical=False)
    check_import(checks, "netCDF4", critical=False)

    check_dir(
        checks,
        os.path.join(MODEL_ROOT, "example_Density", "mesh"),
        "bundled example mesh",
        critical=False,
        expected_files=[
            "mesh.header",
            "mesh.nodes",
            "mesh.elements",
            "mesh.boundary",
        ],
    )
    check_file(
        checks,
        os.path.join(MODEL_ROOT, "example_Density", "density.sif"),
        "bundled density SIF",
        critical=False,
    )

    passed = sum(1 for c in checks if c["status"] == "pass")
    failed = len(checks) - passed
    print(f"\n  Results: {passed} passed, {failed} failed")
    if any(c["status"] != "pass" and c.get("critical") for c in checks):
        print(f"  STATUS: PREFLIGHT FAILED; check {DIAGNOSTICS} for recovery.")
    else:
        print("  STATUS: PREFLIGHT PASSED; ready for model execution.")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
