#!/usr/bin/env python3
"""Preflight check for the Ribasim Knowledge Infrastructure."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


MODEL_ID = "Ribasim"
KI_DIR = Path(__file__).resolve().parent
HYDRO_PYTHON = Path("KISSPATH_PYTHON_ENV/bin/python")
JULIA_BIN = Path("KISSPATH_HOME/.juliaup/bin/julia")
DIAGNOSTICS = KI_DIR / "diagnostics" / "triplets.yaml"
DECLARED_BINARY = KI_DIR / "tools" / "run_ribasim.py"


def recovery_hint(detail: str) -> str:
    return f"{detail}; then check {DIAGNOSTICS} for matching recovery triplets"


def emit_report(model_id: str, checks: list[dict]) -> None:
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}, sort_keys=True))
    ok = all(c["status"] == "pass" or not c.get("critical") for c in checks)
    sys.exit(0 if ok else 1)


def add_check(
    checks: list[dict],
    *,
    kind: str,
    subject: str,
    critical: bool,
    passed: bool,
    fix: str = "",
) -> bool:
    status = "pass" if passed else "fail"
    checks.append(
        {
            "kind": kind,
            "subject": subject,
            "critical": critical,
            "status": status,
            "fix": "" if passed else fix,
        }
    )
    label = "OK" if passed else ("FAIL" if critical else "WARN")
    print(f"  {label:<5} {kind}: {subject}")
    if not passed and fix:
        print(f"        Fix: {fix}")
    return passed


def run_command(cmd: list[str], *, timeout: int = 10, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=str(cwd or KI_DIR),
        text=True,
        capture_output=True,
        timeout=timeout,
    )


def check_file(
    checks: list[dict],
    path: Path,
    label: str,
    *,
    critical: bool,
    executable: bool = False,
    kind: str = "data",
) -> bool:
    subject = str(path)
    if not path.is_file():
        return add_check(
            checks,
            kind=kind,
            subject=subject,
            critical=critical,
            passed=False,
            fix=recovery_hint(f"restore required file {label} at {path}"),
        )
    if executable and not os.access(path, os.X_OK):
        return add_check(
            checks,
            kind=kind,
            subject=subject,
            critical=critical,
            passed=False,
            fix=recovery_hint(f"make {label} executable with: chmod +x {path}"),
        )
    return add_check(checks, kind=kind, subject=subject, critical=critical, passed=True)


def check_python_import(checks: list[dict], module: str, *, critical: bool = True) -> bool:
    subject = f"{HYDRO_PYTHON}: import {module}"
    if not HYDRO_PYTHON.is_file():
        return add_check(
            checks,
            kind="import",
            subject=subject,
            critical=critical,
            passed=False,
            fix=recovery_hint(f"restore HydroCraft Python interpreter at {HYDRO_PYTHON}"),
        )
    try:
        result = run_command(
            [str(HYDRO_PYTHON), "-c", f"import {module}; print('ok')"],
            timeout=15,
        )
        passed = result.returncode == 0
        detail = (result.stderr or result.stdout).strip().splitlines()
        reason = detail[-1] if detail else f"cannot import {module}"
    except Exception as exc:  # timeout and OS errors both become preflight failures
        passed = False
        reason = f"{type(exc).__name__}: {exc}"
    return add_check(
        checks,
        kind="import",
        subject=subject,
        critical=critical,
        passed=passed,
        fix=recovery_hint(f"install/fix Python package '{module.split('.')[0]}' in {HYDRO_PYTHON}: {reason}"),
    )


def check_tool_starts(checks: list[dict], path: Path) -> bool:
    realpath = os.path.realpath(path)
    if not check_file(checks, path, path.name, critical=True, executable=True, kind="binary"):
        return False
    try:
        result = run_command([str(HYDRO_PYTHON), str(path), "--help"], timeout=15)
        passed = result.returncode == 0 and "usage:" in result.stdout.lower()
        reason = (result.stderr or result.stdout).strip().splitlines()
        reason_text = reason[-1] if reason else "wrapper did not print argparse help"
    except Exception as exc:
        passed = False
        reason_text = f"{type(exc).__name__}: {exc}"
    return add_check(
        checks,
        kind="run",
        subject=realpath,
        critical=True,
        passed=passed,
        fix=recovery_hint(f"fix declared Ribasim wrapper startup ({path} --help): {reason_text}"),
    )


def known_ribasim_binary_candidates() -> list[Path]:
    candidates: list[Path] = []
    for env_name in ("RIBASIM_BIN",):
        value = os.environ.get(env_name)
        if value:
            candidates.append(Path(value))

    ribasim_home = os.environ.get("RIBASIM_HOME")
    if ribasim_home:
        home = Path(ribasim_home)
        candidates.extend([home / "bin" / "ribasim", home / "ribasim"])

    which = shutil.which("ribasim")
    if which:
        candidates.append(Path(which))

    model_dir = KI_DIR.parent
    candidates.extend(
        [
            KI_DIR / "ribasim",
            KI_DIR / "ribasim_bin" / "bin" / "ribasim",
            model_dir / "ribasim",
            model_dir / "bin" / "ribasim",
            model_dir / "ribasim_bin" / "bin" / "ribasim",
        ]
    )

    seen: set[str] = set()
    unique: list[Path] = []
    for candidate in candidates:
        key = str(candidate)
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def check_ribasim_runtime(checks: list[dict]) -> bool:
    runtime_ok = False

    found_binary: Path | None = None
    for candidate in known_ribasim_binary_candidates():
        if candidate.is_file() and os.access(candidate, os.X_OK):
            found_binary = candidate
            break

    if found_binary:
        try:
            # The CLI wrapper starts a Julia session (`using Ribasim`); on a cold
            # page cache that takes well over 20 s (observed ~7 s warm, >20 s cold),
            # so a short timeout false-fails a working binary.
            result = run_command([str(found_binary), "--version"], timeout=240)
            cli_ok = result.returncode == 0
            reason = (result.stderr or result.stdout).strip().splitlines()
            reason_text = reason[-1] if reason else "ribasim --version produced no output"
        except Exception as exc:
            cli_ok = False
            reason_text = f"{type(exc).__name__}: {exc}"
        runtime_ok = add_check(
            checks,
            kind="binary",
            subject=os.path.realpath(found_binary),
            critical=False,
            passed=cli_ok,
            fix=recovery_hint(f"fix Ribasim CLI startup: {reason_text}"),
        ) or runtime_ok
    else:
        add_check(
            checks,
            kind="binary",
            subject="ribasim CLI in RIBASIM_BIN, RIBASIM_HOME, PATH, or model directory",
            critical=False,
            passed=False,
            fix=recovery_hint("install Ribasim CLI or set RIBASIM_BIN/RIBASIM_HOME to the executable"),
        )

    python_api_ok = check_python_import(checks, "ribasim", critical=False)
    runtime_ok = python_api_ok or runtime_ok

    if JULIA_BIN.is_file():
        try:
            result = run_command(
                [str(JULIA_BIN), "-e", "using Ribasim; println(\"Ribasim.jl import ok\")"],
                timeout=30,
            )
            julia_pkg_ok = result.returncode == 0
            reason = (result.stderr or result.stdout).strip().splitlines()
            reason_text = reason[-1] if reason else "Julia could not import Ribasim"
        except Exception as exc:
            julia_pkg_ok = False
            reason_text = f"{type(exc).__name__}: {exc}"
        runtime_ok = add_check(
            checks,
            kind="import",
            subject=f"{JULIA_BIN}: using Ribasim",
            critical=False,
            passed=julia_pkg_ok,
            fix=recovery_hint(f"install/activate the Ribasim.jl Julia package: {reason_text}"),
        ) or runtime_ok

    return add_check(
        checks,
        kind="run",
        subject="Ribasim executable runtime (CLI, Python API, or Julia package)",
        critical=True,
        passed=runtime_ok,
        fix=recovery_hint("install the Ribasim CLI, install Python package 'ribasim' in the HydroCraft Python env, or activate Ribasim.jl for Julia"),
    )


def main() -> None:
    checks: list[dict] = []

    print(f"{' PREFLIGHT: Ribasim ':=^60}")
    print(f"KI directory: {KI_DIR}")

    check_file(checks, KI_DIR / "SKILL.md", "SKILL.md", critical=True)
    check_file(checks, KI_DIR / "knowledge_infrastructure.yaml", "knowledge_infrastructure.yaml", critical=True)
    check_file(checks, KI_DIR / "dag.yaml", "dag.yaml", critical=True)
    check_file(checks, DIAGNOSTICS, "diagnostics/triplets.yaml", critical=True)
    check_file(checks, KI_DIR / "docs" / "format_spec.yaml", "docs/format_spec.yaml", critical=False)

    add_check(
        checks,
        kind="import",
        subject=str(HYDRO_PYTHON),
        critical=True,
        passed=HYDRO_PYTHON.is_file() and os.access(HYDRO_PYTHON, os.X_OK),
        fix=recovery_hint(f"restore executable HydroCraft Python interpreter at {HYDRO_PYTHON}"),
    )

    for module in ("numpy", "pandas", "geopandas", "shapely", "pyogrio", "pyarrow", "xarray"):
        check_python_import(checks, module, critical=True)

    for tool in (
        KI_DIR / "tools" / "build_network.py",
        KI_DIR / "tools" / "convert_basin_params.py",
        KI_DIR / "tools" / "parse_ribasim_output.py",
        DECLARED_BINARY,
    ):
        check_file(checks, tool, tool.name, critical=True)
        try:
            result = run_command([str(HYDRO_PYTHON), "-m", "py_compile", str(tool)], timeout=15)
            passed = result.returncode == 0
            reason = (result.stderr or result.stdout).strip().splitlines()
            reason_text = reason[-1] if reason else "py_compile failed"
        except Exception as exc:
            passed = False
            reason_text = f"{type(exc).__name__}: {exc}"
        add_check(
            checks,
            kind="import",
            subject=f"{HYDRO_PYTHON}: py_compile {tool}",
            critical=True,
            passed=passed,
            fix=recovery_hint(f"fix syntax/import-time compile problem in {tool}: {reason_text}"),
        )

    check_tool_starts(checks, DECLARED_BINARY)

    if JULIA_BIN.is_file() and os.access(JULIA_BIN, os.X_OK):
        try:
            result = run_command([str(JULIA_BIN), "--version"], timeout=15)
            julia_ok = result.returncode == 0
            reason = (result.stderr or result.stdout).strip().splitlines()
            reason_text = reason[-1] if reason else "julia --version produced no output"
        except Exception as exc:
            julia_ok = False
            reason_text = f"{type(exc).__name__}: {exc}"
    else:
        julia_ok = False
        reason_text = "Julia executable is missing or not executable"
    add_check(
        checks,
        kind="binary",
        subject=os.path.realpath(JULIA_BIN),
        critical=True,
        passed=julia_ok,
        fix=recovery_hint(f"install/fix Julia runtime at {JULIA_BIN}: {reason_text}"),
    )

    check_ribasim_runtime(checks)

    failed_critical = [c for c in checks if c["critical"] and c["status"] == "fail"]
    print(f"\nResults: {len(checks) - len([c for c in checks if c['status'] == 'fail'])} passed, {len([c for c in checks if c['status'] == 'fail'])} failed")
    if failed_critical:
        print("STATUS: PREFLIGHT FAILED - fix critical blockers before running Ribasim.")
        for check in failed_critical:
            print(f"  - {check['subject']}: {check['fix']}")
    else:
        print("STATUS: PREFLIGHT PASSED - safe to proceed with Ribasim execution.")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
