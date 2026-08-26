#!/usr/bin/env python3
"""Preflight check for the PISM Knowledge Infrastructure."""

import json
import os
import subprocess
import sys
from pathlib import Path


MODEL_ID = "PISM"
KI_DIR = Path(__file__).resolve().parent
PISM_BIN = Path("KISSPATH_KI_ROOT/PISM/build/pism")
PYTHON_ENV = Path("KISSPATH_PYTHON_ENV/bin/python")
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"


def make_check(kind, subject, critical, passed, fix):
    """Create one KDT preflight report check and print the user-facing status."""
    status = "pass" if passed else "fail"
    prefix = "OK  " if passed else "FAIL"
    print(f"  {prefix}  {kind}: {subject}")
    if not passed and fix:
        print(f"        Fix: {fix}")
    return {
        "kind": kind,
        "subject": str(subject),
        "critical": bool(critical),
        "status": status,
        "fix": "" if passed else fix,
    }


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}))
    has_critical_failure = any(c["status"] != "pass" and c.get("critical") for c in checks)
    sys.exit(1 if has_critical_failure else 0)


def check_file(path, label, critical=True, executable=False):
    if not path.exists():
        return make_check(
            "binary" if executable else "data",
            str(path),
            critical,
            False,
            f"{label} is missing. Check {TRIPLETS} for recovery steps.",
        )
    if not path.is_file():
        return make_check(
            "binary" if executable else "data",
            str(path),
            critical,
            False,
            f"{label} must be a file. Check {TRIPLETS} for recovery steps.",
        )
    if executable and not os.access(path, os.X_OK):
        return make_check(
            "binary",
            str(path.resolve()),
            critical,
            False,
            f"Run: chmod +x {path}. Then rerun this preflight; see {TRIPLETS}.",
        )
    return make_check(
        "binary" if executable else "data",
        str(path.resolve() if executable else path),
        critical,
        True,
        "",
    )


def check_dir(path, label, critical=True, must_contain=None):
    if not path.is_dir():
        return make_check(
            "data",
            str(path),
            critical,
            False,
            f"{label} directory is missing. Check {TRIPLETS} for recovery steps.",
        )
    missing = [name for name in (must_contain or []) if not (path / name).is_file()]
    if missing:
        return make_check(
            "data",
            str(path),
            critical,
            False,
            f"{label} is missing required files: {', '.join(missing)}. Check {TRIPLETS}.",
        )
    return make_check("data", str(path), critical, True, "")


def check_python_import(module, critical=True):
    if not PYTHON_ENV.is_file():
        return make_check(
            "import",
            f"{module} via {PYTHON_ENV}",
            critical,
            False,
            f"HydroCraft Python interpreter not found at {PYTHON_ENV}. Check {TRIPLETS}.",
        )
    proc = subprocess.run(
        [str(PYTHON_ENV), "-c", f"import {module}"],
        text=True,
        capture_output=True,
        timeout=20,
    )
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip().splitlines()[-1:]
        suffix = f" ({detail[0]})" if detail else ""
        return make_check(
            "import",
            f"{module} via {PYTHON_ENV}",
            critical,
            False,
            f"Install {module.split('.')[0]} in KISSPATH_PYTHON_ENV{suffix}. Check {TRIPLETS}.",
        )
    return make_check("import", f"{module} via {PYTHON_ENV}", critical, True, "")


def check_pism_starts():
    subject = str(PISM_BIN.resolve()) if PISM_BIN.exists() else str(PISM_BIN)
    if not PISM_BIN.is_file() or not os.access(PISM_BIN, os.X_OK):
        return make_check(
            "run",
            subject,
            True,
            False,
            f"PISM binary cannot be started until the executable check passes. Check {TRIPLETS}.",
        )

    env = dict(os.environ)
    env.setdefault("HDF5_DISABLE_VERSION_CHECK", "2")
    try:
        proc = subprocess.run(
            [str(PISM_BIN), "-version"],
            text=True,
            capture_output=True,
            timeout=20,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return make_check(
            "run",
            subject,
            True,
            False,
            f"{PISM_BIN} -version timed out. Check runtime libraries and {TRIPLETS}.",
        )
    except OSError as exc:
        return make_check(
            "run",
            subject,
            True,
            False,
            f"Failed to execute PISM: {exc}. Check {TRIPLETS}.",
        )

    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout).strip().splitlines()[-1:]
        detail = f" Last output: {tail[0]}" if tail else ""
        return make_check(
            "run",
            subject,
            True,
            False,
            f"{PISM_BIN} -version exited {proc.returncode}.{detail} Check {TRIPLETS}.",
        )

    first_line = (proc.stdout or proc.stderr).strip().splitlines()
    if first_line:
        print(f"        Started: {first_line[0]}")
    return make_check("run", subject, True, True, "")


def main():
    print(f"{' PREFLIGHT: PISM ':=^60}")
    print()

    checks = [
        check_dir(
            KI_DIR / "tools",
            "KI tools",
            critical=True,
            must_contain=[
                "convert_climate_forcing.py",
                "convert_geometry.py",
                "parse_output.py",
                "run_pism.py",
            ],
        ),
        check_file(PISM_BIN, "PISM binary", critical=True, executable=True),
        check_pism_starts(),
        check_file(KI_DIR / "knowledge_infrastructure.yaml", "KI manifest", critical=True),
        check_file(KI_DIR / "dag.yaml", "DAG", critical=True),
        check_file(KI_DIR / "docs" / "format_spec.yaml", "format specification", critical=False),
        check_file(TRIPLETS, "diagnostic triplets", critical=False),
        check_file(PYTHON_ENV, "HydroCraft Python interpreter", critical=True, executable=True),
        check_python_import("numpy", critical=True),
        check_python_import("netCDF4", critical=True),
    ]

    passed = sum(1 for check in checks if check["status"] == "pass")
    failed = len(checks) - passed
    print(f"\n  Results: {passed} passed, {failed} failed")
    if failed:
        print(f"  STATUS: PREFLIGHT FAILED. Check fixes above and {TRIPLETS}.")
    else:
        print("  STATUS: PREFLIGHT PASSED. PISM is ready for model execution.")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
