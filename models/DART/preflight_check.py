#!/usr/bin/env python3
"""Preflight check for the DART Knowledge Infrastructure."""

import json
import os
import subprocess
import sys
from pathlib import Path


MODEL_ID = "DART"
KI_DIR = Path(__file__).resolve().parent
PYTHON_ENV = Path("KISSPATH_PYTHON_ENV/bin/python")

DART_FILTER_CANDIDATES = [
    Path(os.environ["DART_FILTER_BINARY"])
    if os.environ.get("DART_FILTER_BINARY")
    else None,
    KI_DIR.parent / "source" / "repo" / "models" / "lorenz_63" / "work" / "filter",
    KI_DIR.parent / "repo" / "models" / "lorenz_63" / "work" / "filter",
    KI_DIR.parent / "DART" / "models" / "lorenz_63" / "work" / "filter",
]


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}))
    failed_critical = any(
        check["status"] != "pass" and check.get("critical") for check in checks
    )
    sys.exit(1 if failed_critical else 0)


def add_check(checks, kind, subject, critical, status, fix=""):
    check = {
        "kind": kind,
        "subject": str(subject),
        "critical": bool(critical),
        "status": status,
        "fix": fix,
    }
    checks.append(check)
    label = "OK" if status == "pass" else "FAIL"
    print(f"  {label:<5} {kind}: {subject}")
    if status != "pass" and fix:
        print(f"        Fix: {fix}")


def check_file(checks, path, label, critical=True, executable=False):
    path = Path(path)
    subject = path.resolve(strict=False)
    if not path.is_file():
        add_check(
            checks,
            "data",
            subject,
            critical,
            "fail",
            f"{label} is missing. Restore it in this KI; consult diagnostics/triplets.yaml for recovery.",
        )
        return False
    if executable and not os.access(path, os.X_OK):
        add_check(
            checks,
            "binary",
            subject,
            critical,
            "fail",
            f"{label} exists but is not executable. Run: chmod +x {path}",
        )
        return False
    add_check(checks, "binary" if executable else "data", subject, critical, "pass")
    return True


def check_dir(checks, path, label, critical=True):
    path = Path(path)
    subject = path.resolve(strict=False)
    if not path.is_dir():
        add_check(
            checks,
            "data",
            subject,
            critical,
            "fail",
            f"{label} is missing. Restore the KI layout; consult diagnostics/triplets.yaml.",
        )
        return False
    if not any(path.iterdir()):
        add_check(
            checks,
            "data",
            subject,
            critical,
            "fail",
            f"{label} is empty. Restore the generated KI files.",
        )
        return False
    add_check(checks, "data", subject, critical, "pass")
    return True


def check_import(checks, module, critical=True):
    subject = f"{PYTHON_ENV}: import {module}"
    if not PYTHON_ENV.is_file():
        add_check(
            checks,
            "import",
            subject,
            critical,
            "fail",
            "HydroCraft Python environment is missing; restore KISSPATH_PYTHON_ENV.",
        )
        return False

    result = subprocess.run(
        [str(PYTHON_ENV), "-c", f"import {module}"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode == 0:
        add_check(checks, "import", subject, critical, "pass")
        return True

    detail = (result.stderr or result.stdout).strip().splitlines()
    message = detail[-1] if detail else f"import {module} failed"
    add_check(
        checks,
        "import",
        subject,
        critical,
        "fail",
        f"{message}. Install into the HydroCraft Python environment; consult diagnostics/triplets.yaml.",
    )
    return False


def find_filter_binary():
    for candidate in DART_FILTER_CANDIDATES:
        if candidate and candidate.is_file():
            return candidate
    return None


def check_dart_filter(checks):
    binary = find_filter_binary()
    searched = [
        str(path.resolve(strict=False)) for path in DART_FILTER_CANDIDATES if path is not None
    ]
    if binary is None:
        add_check(
            checks,
            "binary",
            "DART filter executable in current KI layout",
            True,
            "fail",
            "No built DART filter executable found. Build Lorenz 63 with quickbuild.sh or set DART_FILTER_BINARY to the real filter path; see diagnostics/triplets.yaml.",
        )
        add_check(
            checks,
            "data",
            "DART filter search paths: " + "; ".join(searched),
            False,
            "fail",
            "Expected a current-model-tree path for the built DART executable.",
        )
        return

    real_binary = binary.resolve(strict=True)
    if not os.access(real_binary, os.X_OK):
        add_check(
            checks,
            "binary",
            real_binary,
            True,
            "fail",
            f"DART filter is not executable. Run: chmod +x {real_binary}",
        )
        return

    add_check(checks, "binary", real_binary, True, "pass")

    try:
        result = subprocess.run(
            [str(real_binary)],
            cwd=str(real_binary.parent),
            capture_output=True,
            text=True,
            timeout=3,
        )
    except subprocess.TimeoutExpired:
        add_check(
            checks,
            "run",
            real_binary,
            True,
            "fail",
            "DART filter did not return within 3 seconds. Check whether it is an MPI build and launch through tools/run_dart.py with mpirun; see diagnostics/triplets.yaml.",
        )
        return

    output = (result.stdout + result.stderr).strip()
    status = "pass" if output or result.returncode in (0, 1, 2) else "fail"
    fix = "" if status == "pass" else "DART filter produced no output on startup; rebuild and check diagnostics/triplets.yaml."
    add_check(checks, "run", real_binary, True, status, fix)


def main():
    checks = []
    print(f"{' PREFLIGHT: DART ':=^60}")
    print(f"KI directory: {KI_DIR}")
    print()

    check_dir(checks, KI_DIR / "tools", "KI tools directory", critical=True)
    for relpath in [
        "tools/convert_obs_to_dart.py",
        "tools/generate_input_nml.py",
        "tools/parse_dart_output.py",
        "tools/run_dart.py",
        "SKILL.md",
        "knowledge_infrastructure.yaml",
        "dag.yaml",
        "docs/format_spec.yaml",
    ]:
        check_file(checks, KI_DIR / relpath, relpath, critical=True)

    check_file(
        checks,
        KI_DIR / "diagnostics" / "triplets.yaml",
        "diagnostics/triplets.yaml",
        critical=True,
    )

    for module in ["numpy", "pandas", "netCDF4", "yaml"]:
        check_import(checks, module, critical=True)

    check_dart_filter(checks)

    print()
    passed = sum(1 for check in checks if check["status"] == "pass")
    failed = len(checks) - passed
    print(f"Results: {passed} passed, {failed} failed")
    if failed:
        print("Blockers found. Start recovery with diagnostics/triplets.yaml.")
    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
