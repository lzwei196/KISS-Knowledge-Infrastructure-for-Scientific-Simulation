#!/usr/bin/env python3
"""Preflight check for the APSIM Knowledge Infrastructure.

This script verifies the model runtime and KI support tooling before any APSIM
simulation is attempted. It always terminates by emitting the KDT
PREFLIGHT_REPORT= JSON line required by the gate.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


MODEL_ID = "APSIM"
KI_DIR = Path(__file__).resolve().parent
PYTHON_ENV = Path("KISSPATH_PYTHON_ENV/bin/python")
DOTNET_ROOT = Path("KISSPATH_HOME/.dotnet")
APSIM_BINARY = Path(
    "KISSPATH_KI_ROOT/APSIM/source/repo/bin/Release/net8.0/apsim"
).resolve()

TOOLS = [
    "tools/build_apsimx.py",
    "tools/convert_met.py",
    "tools/convert_soil.py",
    "tools/parse_output.py",
    "tools/run_apsim.py",
]

IMPORTS = [
    ("numpy", True, "Install numpy in KISSPATH_PYTHON_ENV."),
    ("pandas", True, "Install pandas in KISSPATH_PYTHON_ENV."),
    ("xarray", True, "Install xarray/netCDF4 in KISSPATH_PYTHON_ENV."),
    (
        "ki_tools_common.humidity",
        True,
        "Restore KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/ki_tools_common; see diagnostics/triplets.yaml.",
    ),
    (
        "ki_tools_common.units",
        True,
        "Restore KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/ki_tools_common; see diagnostics/triplets.yaml.",
    ),
    (
        "ki_tools_common.load_forcing",
        True,
        "Restore KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/ki_tools_common; see diagnostics/triplets.yaml.",
    ),
]


checks: list[dict[str, object]] = []


def add_check(kind: str, subject: str, critical: bool, passed: bool, fix: str = "") -> None:
    check = {
        "kind": kind,
        "subject": subject,
        "critical": critical,
        "status": "pass" if passed else "fail",
        "fix": "" if passed else fix,
    }
    checks.append(check)

    label = "OK" if passed else ("FAIL" if critical else "WARN")
    print(f"  {label:<5} {kind}: {subject}")
    if not passed and fix:
        print(f"        Fix: {fix}")


def run_command(
    cmd: list[str],
    *,
    timeout: int = 20,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            cmd,
            cwd=str(cwd or KI_DIR),
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(cmd, returncode=124, stdout="", stderr=str(exc))


def check_file(path: Path, label: str, *, critical: bool = True, executable: bool = False) -> None:
    subject = str(path)
    if not path.is_file():
        add_check(
            "data",
            subject,
            critical,
            False,
            f"Restore {label}; check diagnostics/triplets.yaml for the APSIM recovery path.",
        )
        return

    if executable and not os.access(path, os.X_OK):
        add_check(
            "binary",
            subject,
            critical,
            False,
            f"Make {label} executable: chmod +x {path}; see diagnostics/triplets.yaml.",
        )
        return

    add_check("binary" if executable else "data", subject, critical, True)


def check_dir(path: Path, label: str, *, critical: bool = True) -> None:
    if path.is_dir() and any(path.iterdir()):
        add_check("data", str(path), critical, True)
    else:
        add_check(
            "data",
            str(path),
            critical,
            False,
            f"Restore non-empty {label}; see diagnostics/triplets.yaml.",
        )


def check_python_import(module: str, critical: bool, fix: str) -> None:
    if not PYTHON_ENV.is_file():
        add_check(
            "import",
            f"{module} via {PYTHON_ENV}",
            critical,
            False,
            "Restore KISSPATH_PYTHON_ENV and rerun preflight; see diagnostics/triplets.yaml.",
        )
        return

    code = f"import {module}"
    env = dict(os.environ)
    env["PYTHONPATH"] = "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect:" + env.get(
        "PYTHONPATH", ""
    )
    proc = run_command([str(PYTHON_ENV), "-c", code], timeout=20, env=env)
    passed = proc is not None and proc.returncode == 0
    detail = f"{module} via {PYTHON_ENV}"
    add_check("import", detail, critical, passed, fix)


def check_tool_syntax(tool_relpath: str) -> None:
    tool = KI_DIR / tool_relpath
    check_file(tool, f"KI tool {tool_relpath}", critical=True, executable=False)
    if not tool.is_file() or not PYTHON_ENV.is_file():
        return

    proc = run_command([str(PYTHON_ENV), "-m", "py_compile", str(tool)], timeout=20)
    add_check(
        "import",
        f"py_compile {tool}",
        True,
        proc is not None and proc.returncode == 0,
        f"Fix syntax/import-time errors in {tool_relpath}; see diagnostics/triplets.yaml.",
    )


def check_dotnet_runtime() -> None:
    dotnet = DOTNET_ROOT / "dotnet"
    if not dotnet.is_file():
        add_check(
            "binary",
            str(dotnet),
            True,
            False,
            "Install .NET 8.0 runtime/SDK or restore KISSPATH_HOME/.dotnet; see diagnostics/triplets.yaml dt_012.",
        )
        return

    env = dict(os.environ, DOTNET_ROOT=str(DOTNET_ROOT), PATH=f"{DOTNET_ROOT}:{os.environ.get('PATH', '')}")
    proc = run_command([str(dotnet), "--list-runtimes"], timeout=20, env=env)
    passed = proc is not None and proc.returncode == 0 and "Microsoft.NETCore.App 8." in proc.stdout
    add_check(
        "binary",
        str(dotnet.resolve()),
        True,
        passed,
        "Install .NET 8.0 runtime/SDK or restore KISSPATH_HOME/.dotnet; see diagnostics/triplets.yaml dt_012.",
    )


def check_apsim_binary() -> None:
    subject = str(APSIM_BINARY)
    check_file(APSIM_BINARY, "APSIM binary", critical=True, executable=True)
    if not APSIM_BINARY.is_file() or not os.access(APSIM_BINARY, os.X_OK):
        return

    env = dict(os.environ, DOTNET_ROOT=str(DOTNET_ROOT), PATH=f"{DOTNET_ROOT}:{os.environ.get('PATH', '')}")
    proc = run_command([subject, "--help"], timeout=20, env=env)
    passed = (
        proc is not None
        and proc.returncode == 0
        and "run" in proc.stdout.lower()
        and "apsim" in proc.stdout.lower()
    )
    add_check(
        "run",
        subject,
        True,
        passed,
        "APSIM exists but does not start. Set DOTNET_ROOT=KISSPATH_HOME/.dotnet or rebuild APSIM/.NET 8; see diagnostics/triplets.yaml dt_012.",
    )


def emit_report(model_id: str, report_checks: list[dict[str, object]]) -> None:
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": report_checks}, sort_keys=True))
    sys.exit(0 if all(c["status"] == "pass" or not c.get("critical") for c in report_checks) else 1)


def main() -> None:
    print("=" * 60)
    print(f"  PREFLIGHT CHECK: {MODEL_ID}")
    print("=" * 60)

    check_dir(KI_DIR / "tools", "KI tools directory")
    check_file(KI_DIR / "SKILL.md", "SKILL.md", critical=True)
    check_file(KI_DIR / "knowledge_infrastructure.yaml", "knowledge_infrastructure.yaml", critical=True)
    check_file(KI_DIR / "dag.yaml", "dag.yaml", critical=True)
    check_file(KI_DIR / "diagnostics" / "triplets.yaml", "diagnostic triplets", critical=True)

    check_file(PYTHON_ENV, "HydroCraft Python interpreter", critical=True, executable=True)
    for module, critical, fix in IMPORTS:
        check_python_import(module, critical, fix)

    for tool in TOOLS:
        check_tool_syntax(tool)

    check_dotnet_runtime()
    check_apsim_binary()

    failed = [c for c in checks if c["status"] == "fail"]
    if failed:
        print(f"\n  Results: {len(checks) - len(failed)} passed, {len(failed)} failed")
        print("  STATUS: PREFLIGHT FAILED. Fix failures above; start with diagnostics/triplets.yaml.")
    else:
        print(f"\n  Results: {len(checks)} passed, 0 failed")
        print("  STATUS: PREFLIGHT PASSED.")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
