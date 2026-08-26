#!/usr/bin/env python3
"""Preflight check for the openAMUNDSEN Knowledge Infrastructure.

The gate executes this script before any model run. It must perform real checks
and finish with a single PREFLIGHT_REPORT= JSON line.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


MODEL_ID = "openAMUNDSEN"
KI_ROOT = Path(__file__).resolve().parent
HYDRO_PYTHON = Path("KISSPATH_PYTHON_ENV/bin/python")
HYDRO_BIN = HYDRO_PYTHON.parent
TRIPLETS = KI_ROOT / "diagnostics" / "triplets.yaml"

CHECKS: list[dict[str, object]] = []


def add_check(
    kind: str,
    subject: str | Path,
    critical: bool,
    passed: bool,
    fix: str = "",
) -> bool:
    """Record and print one contract-shaped check."""
    subject_str = str(subject)
    status = "pass" if passed else "fail"
    check: dict[str, object] = {
        "kind": kind,
        "subject": subject_str,
        "critical": bool(critical),
        "status": status,
        "fix": "" if passed else fix,
    }
    CHECKS.append(check)

    label = "OK" if passed else "FAIL"
    crit = "critical" if critical else "noncritical"
    print(f"  {label:<5} {kind:<8} {subject_str} ({crit})")
    if not passed and fix:
        print(f"        Fix: {fix}")
    return passed


def realpath_if_exists(path: Path) -> str:
    return str(path.resolve()) if path.exists() else str(path)


def run_command(args: list[str], timeout: int = 10) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            args,
            cwd=str(KI_ROOT),
            text=True,
            capture_output=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def check_file(path: Path, kind: str, critical: bool, executable: bool = False) -> bool:
    subject = realpath_if_exists(path)
    if not path.is_file():
        return add_check(
            kind,
            subject,
            critical,
            False,
            f"Restore required KI file {path}; start with diagnostics/triplets.yaml.",
        )
    if executable and not os.access(path, os.X_OK):
        return add_check(
            kind,
            subject,
            critical,
            False,
            f"Make executable: chmod +x {path}; check diagnostics/triplets.yaml if startup still fails.",
        )
    return add_check(kind, subject, critical, True)


def check_python_starts() -> bool:
    subject = realpath_if_exists(HYDRO_PYTHON)
    proc = run_command([str(HYDRO_PYTHON), "--version"], timeout=5) if HYDRO_PYTHON.exists() else None
    if proc is not None and proc.returncode == 0:
        return add_check("run", subject, True, True)
    return add_check(
        "run",
        subject,
        True,
        False,
        "Repair KISSPATH_PYTHON_ENV/bin/python so it starts; then rerun this preflight.",
    )


def check_import(module: str, critical: bool = True, package_hint: str | None = None) -> bool:
    subject = f"{realpath_if_exists(HYDRO_PYTHON)} import {module}"
    if not HYDRO_PYTHON.is_file():
        return add_check(
            "import",
            subject,
            critical,
            False,
            "HydroCraft Python interpreter is missing; restore KISSPATH_PYTHON_ENV first.",
        )

    code = f"import {module}; print(getattr({module.split('.')[0]}, '__file__', 'built-in'))"
    proc = run_command([str(HYDRO_PYTHON), "-c", code], timeout=15)
    if proc is not None and proc.returncode == 0:
        detail = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else subject
        return add_check("import", f"{subject} -> {detail}", critical, True)

    stderr = ""
    if proc is not None:
        stderr = (proc.stderr or proc.stdout or "").strip().splitlines()[-1:]
        stderr = stderr[0] if stderr else ""
    package = package_hint or module.split(".")[0]
    return add_check(
        "import",
        subject,
        critical,
        False,
        f"Install into HydroCraft Python: {HYDRO_PYTHON} -m pip install {package}; see {TRIPLETS}. {stderr}".strip(),
    )


def check_openamundsen_cli() -> bool:
    env_path = os.pathsep.join([str(HYDRO_BIN), os.environ.get("PATH", "")])
    cli = shutil.which("openamundsen", path=env_path)
    subject = Path(cli).resolve() if cli else HYDRO_BIN / "openamundsen"
    if not cli:
        return add_check(
            "binary",
            subject,
            True,
            False,
            f"Install openAMUNDSEN into the HydroCraft environment: {HYDRO_PYTHON} -m pip install openamundsen; see {TRIPLETS}.",
        )
    if not os.access(cli, os.X_OK):
        return add_check(
            "binary",
            Path(cli).resolve(),
            True,
            False,
            f"Make CLI executable: chmod +x {cli}; see {TRIPLETS} if it still fails.",
        )

    proc = run_command([cli, "--help"], timeout=10)
    if proc is not None and proc.returncode == 0:
        return add_check("binary", Path(cli).resolve(), True, True)
    return add_check(
        "binary",
        Path(cli).resolve(),
        True,
        False,
        f"openamundsen CLI exists but does not start with --help; reinstall with {HYDRO_PYTHON} -m pip install --force-reinstall openamundsen and check {TRIPLETS}.",
    )


def check_tool_help(tool: Path) -> bool:
    subject = realpath_if_exists(tool)
    if not tool.is_file():
        return add_check(
            "data",
            subject,
            True,
            False,
            f"Restore KI tool {tool}; consult {TRIPLETS} for recovery.",
        )
    proc = run_command([str(HYDRO_PYTHON), str(tool), "--help"], timeout=15)
    if proc is not None and proc.returncode == 0:
        return add_check("run", subject, True, True)
    stderr = ""
    if proc is not None:
        stderr = (proc.stderr or proc.stdout or "").strip().splitlines()[-1:]
        stderr = stderr[0] if stderr else ""
    return add_check(
        "run",
        subject,
        True,
        False,
        f"Tool must start under HydroCraft Python; install missing dependencies or repair the tool. See {TRIPLETS}. {stderr}".strip(),
    )


def emit_report(model_id: str, checks: list[dict[str, object]]) -> None:
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}, sort_keys=True))
    critical_failed = any(c["status"] == "fail" and c.get("critical") for c in checks)
    sys.exit(1 if critical_failed else 0)


def main() -> None:
    print("=" * 60)
    print(f"  PREFLIGHT CHECK: {MODEL_ID}")
    print("=" * 60)
    print(f"  KI root: {KI_ROOT}")
    print(f"  Recovery diagnostics: {TRIPLETS}")
    print()

    check_file(HYDRO_PYTHON, "binary", True, executable=True)
    check_python_starts()
    check_openamundsen_cli()

    print("\n  Required Python imports via HydroCraft Python")
    check_import("openamundsen", True)
    for module, package in [
        ("numpy", None),
        ("pandas", None),
        ("xarray", None),
        ("netCDF4", None),
        ("rasterio", None),
        ("scipy", None),
        ("numba", None),
        ("pyproj", None),
        ("ruamel.yaml", "ruamel.yaml"),
        ("cerberus", None),
        ("munch", None),
        ("pwlf", None),
    ]:
        check_import(module, True, package)

    print("\n  KI files and recovery data")
    for path in [
        KI_ROOT / "SKILL.md",
        KI_ROOT / "knowledge_infrastructure.yaml",
        KI_ROOT / "dag.yaml",
        KI_ROOT / "docs" / "format_spec.yaml",
        TRIPLETS,
    ]:
        check_file(path, "data", True)

    print("\n  KI tool entry points")
    for tool_name in [
        "convert_meteo_forcing.py",
        "convert_soil_params.py",
        "parse_output.py",
        "run_openamundsen.py",
    ]:
        check_tool_help(KI_ROOT / "tools" / tool_name)

    failed = [c for c in CHECKS if c["status"] == "fail"]
    print()
    print(f"  Results: {len(CHECKS) - len(failed)} passed, {len(failed)} failed")
    if failed:
        print(f"  STATUS: PREFLIGHT FAILED. Fix failures above; start with {TRIPLETS}.")
    else:
        print("  STATUS: PREFLIGHT PASSED. Model environment is ready.")

    emit_report(MODEL_ID, CHECKS)


if __name__ == "__main__":
    main()
