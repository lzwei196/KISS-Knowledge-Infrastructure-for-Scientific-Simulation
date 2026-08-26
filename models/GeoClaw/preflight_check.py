#!/usr/bin/env python3
"""Preflight check for the GeoClaw KI."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


MODEL_ID = "GeoClaw"
KI_DIR = Path(__file__).resolve().parent
HYDROCRAFT_PYTHON = Path("KISSPATH_PYTHON_ENV/bin/python")
DIAGNOSTICS = KI_DIR / "diagnostics" / "triplets.yaml"
DEFAULT_BINARY = Path(
    "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/GeoClaw/source/repo/"
    "examples/tsunami/chile2010/xgeoclaw"
)


def fix_text(message: str) -> str:
    return f"{message}; recovery details: {DIAGNOSTICS}"


def emit_report(model_id: str, checks: list[dict[str, object]]) -> None:
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}, sort_keys=True))
    has_failed_critical = any(c["status"] == "fail" and c.get("critical") for c in checks)
    sys.exit(1 if has_failed_critical else 0)


def make_check(kind: str, subject: str, critical: bool, ok: bool, fix: str = "") -> dict[str, object]:
    return {
        "kind": kind,
        "subject": subject,
        "critical": critical,
        "status": "pass" if ok else "fail",
        "fix": "" if ok else fix,
    }


def read_manifest_binary() -> Path:
    manifest = KI_DIR / "knowledge_infrastructure.yaml"
    if not manifest.is_file():
        return DEFAULT_BINARY

    in_binary = False
    for raw_line in manifest.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if stripped == "binary:":
            in_binary = True
            continue
        if in_binary and stripped.startswith("path:"):
            value = stripped.split(":", 1)[1].strip().strip("'\"")
            return Path(value)
        if in_binary and raw_line and not raw_line.startswith(" "):
            break
    return DEFAULT_BINARY


def check_file(path: Path, label: str, critical: bool = True, executable: bool = False) -> dict[str, object]:
    real_subject = os.path.realpath(path)
    if not path.is_file():
        print(f"  FAIL  {label}: not found at {path}")
        return make_check(
            "binary" if executable else "data",
            real_subject,
            critical,
            False,
            fix_text(f"Restore or update required path: {path}"),
        )
    if executable and not os.access(path, os.X_OK):
        print(f"  FAIL  {label}: exists but is not executable: {path}")
        return make_check(
            "binary",
            real_subject,
            critical,
            False,
            fix_text(f"Run chmod +x {path} or rebuild the GeoClaw executable"),
        )

    print(f"  OK    {label}: {real_subject}")
    return make_check("binary" if executable else "data", real_subject, critical, True)


def check_python_import(module: str, critical: bool = True) -> dict[str, object]:
    subject = f"{os.path.realpath(HYDROCRAFT_PYTHON)} import {module}"
    if not HYDROCRAFT_PYTHON.is_file() or not os.access(HYDROCRAFT_PYTHON, os.X_OK):
        print(f"  FAIL  Python interpreter: {HYDROCRAFT_PYTHON} missing or not executable")
        return make_check(
            "import",
            subject,
            critical,
            False,
            fix_text(f"Restore executable Python interpreter at {HYDROCRAFT_PYTHON}"),
        )

    proc = subprocess.run(
        [str(HYDROCRAFT_PYTHON), "-c", f"import {module}"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if proc.returncode == 0:
        print(f"  OK    HydroCraft import: {module}")
        return make_check("import", subject, critical, True)

    err = (proc.stderr or proc.stdout or "").strip().splitlines()
    detail = err[-1] if err else f"return code {proc.returncode}"
    print(f"  FAIL  HydroCraft import: {module}: {detail}")
    package = module.split(".", 1)[0]
    return make_check(
        "import",
        subject,
        critical,
        False,
        fix_text(f"Install {package} into {HYDROCRAFT_PYTHON}: {HYDROCRAFT_PYTHON} -m pip install {package}"),
    )


def check_binary_starts(binary: Path) -> dict[str, object]:
    subject = os.path.realpath(binary)
    if not binary.is_file() or not os.access(binary, os.X_OK):
        return make_check(
            "run",
            subject,
            True,
            False,
            fix_text(f"Restore executable GeoClaw binary before start probe: {binary}"),
        )

    try:
        with tempfile.TemporaryDirectory(prefix="geoclaw_preflight_") as run_dir:
            proc = subprocess.run(
                [str(binary)],
                cwd=run_dir,
                capture_output=True,
                text=True,
                timeout=5,
            )
    except subprocess.TimeoutExpired:
        print(f"  FAIL  GeoClaw start probe: timed out for {binary}")
        return make_check(
            "run",
            subject,
            True,
            False,
            fix_text("GeoClaw executable did not return promptly when started without case data"),
        )
    except OSError as exc:
        print(f"  FAIL  GeoClaw start probe: {exc}")
        return make_check("run", subject, True, False, fix_text(f"Rebuild or relink GeoClaw binary: {exc}"))

    combined = f"{proc.stdout}\n{proc.stderr}".lower()
    loader_failed = (
        proc.returncode == 127
        or "error while loading shared libraries" in combined
        or "cannot open shared object file" in combined
    )
    if loader_failed:
        print(f"  FAIL  GeoClaw start probe: dynamic loader failure for {binary}")
        return make_check(
            "run",
            subject,
            True,
            False,
            fix_text("Rebuild GeoClaw or repair missing runtime libraries"),
        )

    print(f"  OK    GeoClaw start probe: process launched and returned rc={proc.returncode}")
    return make_check("run", subject, True, True)


def check_tool_import(script: Path) -> dict[str, object]:
    subject = str(script.resolve())
    module_name = f"tools.{script.stem}"
    proc = subprocess.run(
        [sys.executable, "-c", f"import {module_name}"],
        cwd=KI_DIR,
        capture_output=True,
        text=True,
        timeout=15,
    )
    if proc.returncode == 0:
        print(f"  OK    KI tool import: {script}")
        return make_check("import", subject, True, True)

    err = (proc.stderr or proc.stdout or "").strip().splitlines()
    detail = err[-1] if err else f"return code {proc.returncode}"
    print(f"  FAIL  KI tool import: {script}: {detail}")
    return make_check(
        "import",
        subject,
        True,
        False,
        fix_text(f"Fix import/runtime dependencies for {script}"),
    )


def check_command(name: str, critical: bool, fix: str) -> dict[str, object]:
    found = shutil.which(name)
    if found:
        real = os.path.realpath(found)
        print(f"  OK    Command: {name}: {real}")
        return make_check("binary", real, critical, True)
    print(f"  FAIL  Command: {name}: not found on PATH")
    return make_check("binary", name, critical, False, fix_text(fix))


def main() -> None:
    print(f"{' PREFLIGHT: GeoClaw ':=^60}")
    checks: list[dict[str, object]] = []

    binary = read_manifest_binary()
    checks.append(check_file(binary, "GeoClaw binary from knowledge_infrastructure.yaml", critical=True, executable=True))
    checks.append(check_binary_starts(binary))

    checks.append(check_file(HYDROCRAFT_PYTHON, "HydroCraft Python interpreter", critical=True, executable=True))
    for module in ("clawpack", "clawpack.geoclaw", "clawpack.clawutil", "numpy"):
        checks.append(check_python_import(module, critical=True))

    required_files = [
        KI_DIR / "SKILL.md",
        KI_DIR / "knowledge_infrastructure.yaml",
        KI_DIR / "dag.yaml",
        DIAGNOSTICS,
        KI_DIR / "docs" / "format_spec.yaml",
    ]
    for path in required_files:
        checks.append(check_file(path, f"Required KI file {path.relative_to(KI_DIR)}", critical=True))

    for script_name in (
        "convert_bathymetry.py",
        "generate_setrun.py",
        "run_geoclaw.py",
        "parse_geoclaw_output.py",
    ):
        script = KI_DIR / "tools" / script_name
        checks.append(check_file(script, f"KI tool {script_name}", critical=True))
        checks.append(check_tool_import(script))

    checks.append(check_command("gfortran", True, "Install gfortran and set FC=gfortran"))

    passed = sum(1 for check in checks if check["status"] == "pass")
    failed = len(checks) - passed
    print(f"\n  Results: {passed} passed, {failed} failed")
    if failed:
        print(f"  STATUS: PREFLIGHT FAILED - fix blockers above; check {DIAGNOSTICS} first.")
    else:
        print("  STATUS: PREFLIGHT PASSED - safe to proceed with model execution.")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
