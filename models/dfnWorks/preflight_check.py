#!/usr/bin/env python3
"""Preflight check for the dfnWorks Knowledge Infrastructure."""

from __future__ import annotations

import json
import os
import py_compile
import subprocess
import sys
from pathlib import Path


MODEL_ID = "dfnWorks"
KI_DIR = Path(__file__).resolve().parent
HYDROCRAFT_PYTHON = Path("KISSPATH_PYTHON_ENV/bin/python")
DFNGEN = Path(
    "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/dfnWorks/source/repo/DFNGen/DFNGen"
)
DFNWORKSRC = Path.home() / ".dfnworksrc"
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"

DIAG_FIX = f"Check {TRIPLETS.relative_to(KI_DIR)} for the matching recovery triplet."


def emit_report(model_id: str, checks: list[dict[str, object]]) -> None:
    """Emit the KDT preflight report as the final output line."""
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}, sort_keys=True))
    failed = [c for c in checks if c["status"] == "fail" and c.get("critical")]
    sys.exit(1 if failed else 0)


def add_check(
    checks: list[dict[str, object]],
    *,
    kind: str,
    subject: str,
    critical: bool,
    status: bool,
    fix: str,
    detail: str = "",
) -> None:
    check = {
        "kind": kind,
        "subject": subject,
        "critical": critical,
        "status": "pass" if status else "fail",
        "fix": "" if status else fix,
    }
    checks.append(check)

    label = "OK" if status else ("FAIL" if critical else "WARN")
    print(f"  {label:<5} {kind}: {subject}")
    if detail:
        print(f"        {detail}")
    if not status:
        print(f"        Fix: {fix}")


def real_subject(path: Path) -> str:
    return os.path.realpath(path) if path.exists() else str(path)


def check_file(
    checks: list[dict[str, object]],
    path: Path,
    label: str,
    *,
    kind: str = "data",
    critical: bool = True,
    executable: bool = False,
) -> None:
    exists = path.is_file()
    executable_ok = (not executable) or os.access(path, os.X_OK)
    status = exists and executable_ok
    fix = f"Restore {path}; {DIAG_FIX}"
    if executable and exists:
        fix = f"Run chmod +x {path} or rebuild the executable; {DIAG_FIX}"
    detail = label
    add_check(
        checks,
        kind=kind,
        subject=real_subject(path),
        critical=critical,
        status=status,
        fix=fix,
        detail=detail,
    )


def check_dir(checks: list[dict[str, object]], path: Path, label: str, *, critical: bool = True) -> None:
    status = path.is_dir() and any(path.iterdir())
    detail = f"{label}; {len(list(path.iterdir())) if path.is_dir() else 0} item(s)"
    add_check(
        checks,
        kind="data",
        subject=str(path),
        critical=critical,
        status=status,
        fix=f"Restore the KI directory contents at {path}; {DIAG_FIX}",
        detail=detail,
    )


def run_probe(argv: list[str], timeout: int = 10) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, text=True, capture_output=True, timeout=timeout, check=False)


def check_python_starts(checks: list[dict[str, object]]) -> None:
    subject = real_subject(HYDROCRAFT_PYTHON)
    ok = HYDROCRAFT_PYTHON.is_file() and os.access(HYDROCRAFT_PYTHON, os.X_OK)
    detail = "HydroCraft Python interpreter for KI imports"
    if ok:
        try:
            proc = run_probe([str(HYDROCRAFT_PYTHON), "-c", "import sys; print(sys.executable)"])
            ok = proc.returncode == 0
            if proc.stdout.strip():
                detail += f"; starts as {proc.stdout.strip()}"
            elif proc.stderr.strip():
                detail += f"; stderr: {proc.stderr.strip()[:200]}"
        except Exception as exc:  # pragma: no cover - preflight diagnostic path
            ok = False
            detail += f"; start probe failed: {exc}"

    add_check(
        checks,
        kind="binary",
        subject=subject,
        critical=True,
        status=ok,
        fix=f"Restore KISSPATH_PYTHON_ENV/bin/python; {DIAG_FIX}",
        detail=detail,
    )


def check_dfngen_starts(checks: list[dict[str, object]]) -> None:
    subject = real_subject(DFNGEN)
    ok = DFNGEN.is_file() and os.access(DFNGEN, os.X_OK)
    detail = "DFNGen executable used by pydfnworks create_network()"
    if ok:
        try:
            proc = run_probe([str(DFNGEN), "--help"])
            combined = (proc.stdout + proc.stderr).strip()
            ok = "Starting DFNGen" in combined or proc.returncode == 0
            if combined:
                detail += f"; probe output: {combined.splitlines()[0][:200]}"
        except Exception as exc:  # pragma: no cover - preflight diagnostic path
            ok = False
            detail += f"; start probe failed: {exc}"

    add_check(
        checks,
        kind="binary",
        subject=subject,
        critical=True,
        status=ok,
        fix=f"Rebuild DFNGen from the dfnWorks source repo; see diagnostics/triplets.yaml dt_009 and dt_010.",
        detail=detail,
    )


def check_import(checks: list[dict[str, object]], module: str, *, critical: bool = True) -> None:
    code = (
        "import importlib.util, sys\n"
        f"spec = importlib.util.find_spec({module!r})\n"
        "assert spec is not None\n"
        f"__import__({module!r})\n"
        "print(spec.origin or 'built-in')\n"
    )
    ok = False
    detail = f"import {module} using {HYDROCRAFT_PYTHON}"
    try:
        proc = run_probe([str(HYDROCRAFT_PYTHON), "-c", code])
        ok = proc.returncode == 0
        output = (proc.stdout or proc.stderr).strip()
        if output:
            detail += f"; {output.splitlines()[-1][:240]}"
    except Exception as exc:  # pragma: no cover - preflight diagnostic path
        detail += f"; import probe failed: {exc}"

    add_check(
        checks,
        kind="import",
        subject=module,
        critical=critical,
        status=ok,
        fix=f"Install or repair {module} in KISSPATH_PYTHON_ENV; {DIAG_FIX}",
        detail=detail,
    )


def check_tool_syntax(checks: list[dict[str, object]], path: Path) -> None:
    ok = path.is_file()
    detail = "Python syntax compile"
    if ok:
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as exc:
            ok = False
            detail += f"; {exc.msg.splitlines()[-1][:240]}"

    add_check(
        checks,
        kind="data",
        subject=str(path.relative_to(KI_DIR)),
        critical=True,
        status=ok,
        fix=f"Repair {path.relative_to(KI_DIR)}; {DIAG_FIX}",
        detail=detail,
    )


def check_dfnworksrc(checks: list[dict[str, object]]) -> None:
    ok = DFNWORKSRC.is_file()
    detail = "dfnWorks path configuration"
    fix = f"Create or repair {DFNWORKSRC}; see diagnostics/triplets.yaml dt_010."
    if ok:
        try:
            data = json.loads(DFNWORKSRC.read_text())
            dfnworks_path = data.get("dfnworks_PATH")
            ok = bool(dfnworks_path and Path(dfnworks_path).is_dir())
            detail += f"; dfnworks_PATH={dfnworks_path}"
        except Exception as exc:
            ok = False
            detail += f"; invalid JSON: {exc}"

    add_check(
        checks,
        kind="data",
        subject=str(DFNWORKSRC),
        critical=True,
        status=ok,
        fix=fix,
        detail=detail,
    )


def main() -> None:
    checks: list[dict[str, object]] = []

    print(f"{' PREFLIGHT: dfnWorks ':=^60}")
    print()

    check_dir(checks, KI_DIR / "tools", "KI tools directory")
    check_file(checks, KI_DIR / "knowledge_infrastructure.yaml", "KI manifest")
    check_file(checks, KI_DIR / "dag.yaml", "DAG contract")
    check_file(checks, TRIPLETS, "diagnostic triplets for recovery")
    check_dfnworksrc(checks)

    check_python_starts(checks)
    check_dfngen_starts(checks)

    check_import(checks, "numpy")
    check_import(checks, "pydfnworks")
    check_import(checks, "h5py", critical=False)
    check_import(checks, "networkx", critical=False)

    for tool in [
        "convert_fracture_input.py",
        "convert_hydraulic_params.py",
        "parse_dfnworks_output.py",
        "run_dfnworks.py",
    ]:
        check_tool_syntax(checks, KI_DIR / "tools" / tool)

    passed = sum(1 for check in checks if check["status"] == "pass")
    failed = len(checks) - passed
    print()
    print(f"  Results: {passed} passed, {failed} failed")
    if failed:
        print(f"  Blockers: check {TRIPLETS.relative_to(KI_DIR)} for recovery guidance.")
    else:
        print("  STATUS: PREFLIGHT PASSED")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
