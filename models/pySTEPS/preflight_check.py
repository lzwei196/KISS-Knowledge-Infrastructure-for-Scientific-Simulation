#!/usr/bin/env python3
"""
Preflight check for the pySTEPS Knowledge Infrastructure.

This script verifies the package interpreter, imports, KI entry point, and
diagnostic files before model execution. It always ends with a
PREFLIGHT_REPORT= JSON line for the KDT gate.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


MODEL_ID = "pySTEPS"
EXPECTED_PYSTEPS_VERSION = "1.20.0"
KI_DIR = Path(__file__).resolve().parent
PYTHON_ENV = Path("KISSPATH_PYTHON_ENV/bin/python")
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"
BINARY_PATH = KI_DIR / "tools" / "s3_nowcast" / "run_nowcast.py"
DIAGNOSTIC_RUNNER = KI_DIR / "diagnostics" / "run_synthetic_advection.py"
SITE_PACKAGES = Path("KISSPATH_PYTHON_ENV/lib/python3.12/site-packages")


checks: list[dict[str, object]] = []


def recovery_fix(message: str) -> str:
    return f"{message}; then check {TRIPLETS} for known recovery steps"


def add_check(kind: str, subject: str, critical: bool, ok: bool, fix: str = "") -> None:
    status = "pass" if ok else "fail"
    checks.append(
        {
            "kind": kind,
            "subject": subject,
            "critical": bool(critical),
            "status": status,
            "fix": "" if ok else fix,
        }
    )
    label = "OK" if ok else "FAIL"
    print(f"  {label:<5} {kind}: {subject}")
    if not ok and fix:
        print(f"        Fix: {fix}")


def emit_report() -> None:
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": MODEL_ID, "checks": checks}))
    has_critical_failure = any(
        check["status"] == "fail" and check.get("critical") for check in checks
    )
    sys.exit(1 if has_critical_failure else 0)


def subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONNOUSERSITE"] = "1"
    return env


def check_file(path: Path, label: str, *, critical: bool = True) -> None:
    add_check(
        "data",
        str(path),
        critical,
        path.is_file(),
        recovery_fix(f"{label} is missing at {path}"),
    )


def check_python_env() -> None:
    ok = PYTHON_ENV.is_file() and os.access(PYTHON_ENV, os.X_OK)
    add_check(
        "run",
        str(PYTHON_ENV.resolve() if PYTHON_ENV.exists() else PYTHON_ENV),
        True,
        ok,
        recovery_fix(f"HydroCraft Python interpreter is missing or not executable at {PYTHON_ENV}"),
    )


def check_import(module: str, label: str, *, critical: bool = True) -> None:
    subject = f"{PYTHON_ENV} import {module}"
    if not PYTHON_ENV.is_file():
        add_check(
            "import",
            subject,
            critical,
            False,
            recovery_fix(f"Cannot import {module}: interpreter is missing at {PYTHON_ENV}"),
        )
        return

    code = (
        "import importlib.util, json, sys; "
        f"spec = importlib.util.find_spec({module!r}); "
        "print(json.dumps({'origin': spec.origin if spec else None, "
        "'executable': sys.executable})); "
        "raise SystemExit(0 if spec else 1)"
    )
    proc = subprocess.run(
        [str(PYTHON_ENV), "-c", code],
        text=True,
        capture_output=True,
        timeout=20,
        env=subprocess_env(),
    )
    ok = proc.returncode == 0
    detail = ""
    if ok:
        try:
            origin = json.loads(proc.stdout.strip() or "{}").get("origin")
            detail = f" ({origin})" if origin else ""
        except json.JSONDecodeError:
            detail = ""
    add_check(
        "import",
        subject + detail,
        critical,
        ok,
        recovery_fix(
            f"{label} import failed under {PYTHON_ENV}: {(proc.stderr or proc.stdout).strip()}"
        ),
    )


def check_pysteps_version() -> None:
    subject = f"{PYTHON_ENV} importlib.metadata version pysteps"
    code = (
        "import importlib.metadata as ilm; "
        "print(ilm.version('pysteps'))"
    )
    proc = subprocess.run(
        [str(PYTHON_ENV), "-c", code],
        text=True,
        capture_output=True,
        timeout=20,
        env=subprocess_env(),
    )
    version = proc.stdout.strip()
    ok = proc.returncode == 0 and version == EXPECTED_PYSTEPS_VERSION
    add_check(
        "import",
        f"{subject} == {EXPECTED_PYSTEPS_VERSION} (found {version or 'unavailable'})",
        True,
        ok,
        recovery_fix(
            f"Install pysteps {EXPECTED_PYSTEPS_VERSION} into {SITE_PACKAGES}; current result: "
            f"{(proc.stderr or proc.stdout).strip() or 'no version'}"
        ),
    )


def check_entrypoint() -> None:
    realpath = BINARY_PATH.resolve()
    exists = BINARY_PATH.is_file()
    add_check(
        "binary",
        str(realpath),
        True,
        exists,
        recovery_fix(f"Manifest entry point is missing at {BINARY_PATH}"),
    )
    if not exists or not PYTHON_ENV.is_file():
        return

    proc = subprocess.run(
        [str(PYTHON_ENV), str(BINARY_PATH), "--help"],
        text=True,
        capture_output=True,
        timeout=20,
        env=subprocess_env(),
    )
    add_check(
        "run",
        f"{realpath} --help via {PYTHON_ENV}",
        True,
        proc.returncode == 0 and "Run pySTEPS precipitation nowcast" in proc.stdout,
        recovery_fix(
            "pySTEPS nowcast entry point did not start cleanly: "
            f"{(proc.stderr or proc.stdout).strip()}"
        ),
    )


def check_method_registry() -> None:
    subject = f"{PYTHON_ENV} pysteps method registry"
    code = """
from pysteps import motion, nowcasts
from pysteps.verification import det_cat_fct, fss
motion.get_method("proesmans")
nowcasts.get_method("extrapolation")
print("registry-ok")
"""
    proc = subprocess.run(
        [str(PYTHON_ENV), "-c", code],
        text=True,
        capture_output=True,
        timeout=30,
        env=subprocess_env(),
    )
    add_check(
        "run",
        subject,
        True,
        proc.returncode == 0 and "registry-ok" in proc.stdout,
        recovery_fix(
            "Required pySTEPS runtime methods are unavailable: "
            f"{(proc.stderr or proc.stdout).strip()}"
        ),
    )


def main() -> None:
    print("=" * 60)
    print(f"  PREFLIGHT CHECK: {MODEL_ID}")
    print("=" * 60)

    try:
        check_python_env()
        check_import("numpy", "NumPy")
        check_import("pysteps", "pySTEPS core")
        check_import("pysteps.motion", "pySTEPS motion estimation")
        check_import("pysteps.nowcasts", "pySTEPS nowcasting methods")
        check_import("pysteps.verification", "pySTEPS verification scores")
        check_pysteps_version()
        check_entrypoint()
        check_file(DIAGNOSTIC_RUNNER, "Synthetic advection diagnostic")
        check_file(TRIPLETS, "Diagnostic triplets")
        check_method_registry()
    except Exception as exc:
        add_check(
            "run",
            "preflight_check.py internal execution",
            True,
            False,
            recovery_fix(f"Preflight crashed unexpectedly: {exc!r}"),
        )
    finally:
        emit_report()


if __name__ == "__main__":
    main()
