#!/usr/bin/env python3
"""Preflight check for the PRMS knowledge infrastructure.

This script validates the executable, Python dependencies, KI files, and tool
syntax before a PRMS run. It always finishes by printing one
PREFLIGHT_REPORT=<json> line for the KDT gate.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


MODEL_ID = "PRMS"
KI_DIR = Path(__file__).resolve().parent
MODEL_ROOT = KI_DIR.parent
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"
PYTHON_ENV = Path("KISSPATH_PYTHON_ENV/bin/python")
PRMS_BINARY = (MODEL_ROOT / "source" / "repo" / "prms" / "prms_hpc").resolve()


def fix_hint(text: str) -> str:
    return f"{text}; then check {TRIPLETS} for matching recovery triplets"


def emit_report(model_id: str, checks: list[dict]) -> None:
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}, sort_keys=True))
    sys.exit(0 if all(c["status"] == "pass" or not c.get("critical") for c in checks) else 1)


def record(
    checks: list[dict],
    kind: str,
    subject: str | Path,
    critical: bool,
    ok: bool,
    fix: str = "",
    detail: str = "",
) -> None:
    status = "pass" if ok else "fail"
    subject_text = str(subject)
    checks.append(
        {
            "kind": kind,
            "subject": subject_text,
            "critical": bool(critical),
            "status": status,
            "fix": "" if ok else fix,
        }
    )
    label = "OK" if ok else ("FAIL" if critical else "WARN")
    print(f"  {label:<5} {kind}: {subject_text}")
    if detail:
        print(f"        {detail}")
    if not ok:
        print(f"        Fix: {fix}")


def check_file(checks: list[dict], path: Path, label: str, critical: bool = True, executable: bool = False) -> None:
    subject = path.resolve() if path.exists() else path
    if not path.is_file():
        record(checks, "data", subject, critical, False, fix_hint(f"restore missing {label}: {path}"))
        return
    if executable and not os.access(path, os.X_OK):
        record(checks, "binary", subject, critical, False, fix_hint(f"make {label} executable with chmod +x {path}"))
        return
    record(checks, "binary" if executable else "data", subject, critical, True)


def check_dir(checks: list[dict], path: Path, label: str, critical: bool = True) -> None:
    subject = path.resolve() if path.exists() else path
    if not path.is_dir():
        record(checks, "data", subject, critical, False, fix_hint(f"restore missing {label} directory: {path}"))
        return
    entries = [p.name for p in path.iterdir()]
    record(checks, "data", subject, critical, bool(entries), fix_hint(f"populate empty {label} directory: {path}"), f"{len(entries)} entries")


def run_checked(cmd: list[str], timeout: int = 10, cwd: Path | None = None) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(cmd, cwd=str(cwd or KI_DIR), capture_output=True, text=True, timeout=timeout)
    except Exception as exc:
        return subprocess.CompletedProcess(cmd, returncode=999, stdout="", stderr=f"{type(exc).__name__}: {exc}")


def check_python_import(checks: list[dict], module: str, critical: bool = True) -> None:
    subject = f"{PYTHON_ENV} -c import {module}"
    if not PYTHON_ENV.is_file():
        record(
            checks,
            "import",
            subject,
            True,
            False,
            fix_hint(f"restore HydroCraft Python interpreter at {PYTHON_ENV}"),
        )
        return

    proc = run_checked([str(PYTHON_ENV), "-c", f"import {module}"], timeout=15)
    ok = proc is not None and proc.returncode == 0
    detail = "" if ok else ((proc.stderr or proc.stdout).strip().splitlines()[-1] if proc else "import subprocess failed")
    record(
        checks,
        "import",
        subject,
        critical,
        ok,
        fix_hint(f"install Python dependency '{module.split('.')[0]}' in KISSPATH_PYTHON_ENV"),
        detail,
    )


def check_tool_compile(checks: list[dict], tool: Path) -> None:
    subject = tool.resolve() if tool.exists() else tool
    if not tool.is_file():
        record(checks, "data", subject, True, False, fix_hint(f"restore missing KI tool {tool}"))
        return
    proc = run_checked([str(PYTHON_ENV), "-m", "py_compile", str(tool)], timeout=15)
    ok = proc is not None and proc.returncode == 0
    detail = "" if ok else ((proc.stderr or proc.stdout).strip().splitlines()[-1] if proc else "py_compile subprocess failed")
    record(checks, "import", subject, True, ok, fix_hint(f"fix Python syntax/import path in {tool}"), detail)


def check_binary_starts(checks: list[dict]) -> None:
    subject = PRMS_BINARY.resolve() if PRMS_BINARY.exists() else PRMS_BINARY
    if not PRMS_BINARY.is_file() or not os.access(PRMS_BINARY, os.X_OK):
        record(checks, "run", subject, True, False, fix_hint(f"restore executable PRMS binary at {PRMS_BINARY}"))
        return

    proc = run_checked([str(PRMS_BINARY)], timeout=5)
    combined = ((proc.stdout if proc else "") + (proc.stderr if proc else "")).strip()
    # PRMS without a control file exits nonzero but has started correctly when
    # it reaches its control-file reader and reports the missing control.
    ok = proc is not None and proc.returncode in (0, 1) and "Couldn't open control" in combined
    detail = combined.splitlines()[0] if combined else f"returncode={proc.returncode if proc else 'none'}"
    record(checks, "run", subject, True, ok, fix_hint(f"rebuild PRMS from {MODEL_ROOT / 'source' / 'repo'} and inspect dynamic libraries"), detail)


def check_shared_libraries(checks: list[dict]) -> None:
    subject = f"ldd {PRMS_BINARY}"
    proc = run_checked(["ldd", str(PRMS_BINARY)], timeout=10)
    if proc is None:
        record(checks, "binary", subject, False, False, fix_hint("run ldd manually to inspect PRMS shared libraries"))
        return
    output = (proc.stdout or "") + (proc.stderr or "")
    missing = [line.strip() for line in output.splitlines() if "not found" in line]
    record(
        checks,
        "binary",
        subject,
        True,
        proc.returncode == 0 and not missing,
        fix_hint("install missing PRMS runtime libraries such as libgfortran, libnetcdf, libnetcdff, or HDF5"),
        "all linked libraries resolved" if not missing else "; ".join(missing),
    )


def main() -> None:
    checks: list[dict] = []

    print(f"{' PREFLIGHT: PRMS ':=^60}")
    print(f"KI directory: {KI_DIR}")
    print(f"Diagnostics: {TRIPLETS}")
    print()

    check_file(checks, PRMS_BINARY, "PRMS binary", critical=True, executable=True)
    check_binary_starts(checks)
    check_shared_libraries(checks)

    for required in ["SKILL.md", "knowledge_infrastructure.yaml", "dag.yaml", "diagnostics/triplets.yaml"]:
        check_file(checks, KI_DIR / required, required, critical=True)

    check_dir(checks, KI_DIR / "tools", "KI tools", critical=True)
    for tool_name in [
        "convert_forcing_to_prms.py",
        "convert_params_to_prms.py",
        "generate_control_file.py",
        "run_prms.py",
        "parse_prms_output.py",
    ]:
        check_tool_compile(checks, KI_DIR / "tools" / tool_name)

    check_file(checks, PYTHON_ENV, "HydroCraft Python interpreter", critical=True, executable=True)
    for module in ["numpy", "pandas", "xarray"]:
        check_python_import(checks, module, critical=True)
    check_python_import(checks, "matplotlib", critical=False)
    check_python_import(checks, "geopandas", critical=False)

    failed = [c for c in checks if c["status"] == "fail"]
    critical_failed = [c for c in failed if c["critical"]]
    print()
    print(f"Results: {len(checks) - len(failed)} passed, {len(failed)} failed, {len(critical_failed)} critical failed")
    if critical_failed:
        print(f"STATUS: PREFLIGHT FAILED - fix blockers above; recovery hints are in {TRIPLETS}")
    else:
        print("STATUS: PREFLIGHT PASSED - PRMS is ready for model execution")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
