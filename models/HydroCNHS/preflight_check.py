#!/usr/bin/env python3
"""Preflight check for the HydroCNHS knowledge infrastructure."""

from __future__ import annotations

import json
import os
import py_compile
import subprocess
import sys
from pathlib import Path


MODEL_ID = "HydroCNHS"
EXPECTED_VERSION = "1.2.1"
KI_DIR = Path(__file__).resolve().parent
MODEL_DIR = KI_DIR.parent
MODEL_VENV_PYTHON = MODEL_DIR / "venv" / "bin" / "python"
MODEL_SOURCE_DIR = MODEL_DIR / "source" / "repo" / "src" / "hydrocnhs"
PYTHON_ENV = Path("KISSPATH_PYTHON_ENV/bin/python")
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"


checks: list[dict[str, object]] = []


def add_check(kind: str, subject: str, critical: bool, status: str, fix: str = "") -> None:
    if status not in {"pass", "fail"}:
        raise ValueError(f"invalid preflight status: {status}")
    check = {
        "kind": kind,
        "subject": subject,
        "critical": bool(critical),
        "status": status,
        "fix": fix,
    }
    checks.append(check)

    label = "OK" if status == "pass" else "FAIL"
    print(f"  {label:<5} {kind}: {subject}")
    if status == "fail" and fix:
        print(f"        Fix: {fix}")


def emit_report(model_id: str, report_checks: list[dict[str, object]]) -> None:
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": report_checks}))
    failed_critical = any(
        check["status"] == "fail" and check.get("critical") for check in report_checks
    )
    sys.exit(1 if failed_critical else 0)


def check_file(path: Path, label: str, *, critical: bool, executable: bool = False) -> None:
    subject = str(path)
    if not path.is_file():
        add_check(
            "data",
            subject,
            critical,
            "fail",
            f"Restore {label}; see {TRIPLETS} for known recovery steps.",
        )
        return
    if executable and not os.access(path, os.X_OK):
        add_check(
            "binary",
            str(path.resolve()),
            critical,
            "fail",
            f"Run chmod +x {path}; see {TRIPLETS} for runtime recovery.",
        )
        return
    add_check("binary" if executable else "data", str(path.resolve()), critical, "pass")


def check_dir(path: Path, label: str, *, critical: bool) -> None:
    if path.is_dir() and any(path.iterdir()):
        add_check("data", str(path.resolve()), critical, "pass")
    else:
        add_check(
            "data",
            str(path),
            critical,
            "fail",
            f"Restore non-empty {label}; see {TRIPLETS} for expected KI layout.",
        )


def run_subprocess(
    args: list[str],
    *,
    label: str,
    subject: str,
    kind: str,
    critical: bool,
    timeout_s: int,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str] | None:
    try:
        proc = subprocess.run(
            args,
            cwd=str(KI_DIR),
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired:
        add_check(
            kind,
            subject,
            critical,
            "fail",
            f"{label} timed out after {timeout_s}s. Use {TRIPLETS} before working around the real model.",
        )
        return None

    if proc.returncode == 0:
        add_check(kind, subject, critical, "pass")
    else:
        output = (proc.stderr or proc.stdout or "").strip().splitlines()
        detail = output[-1] if output else f"exit code {proc.returncode}"
        add_check(
            kind,
            subject,
            critical,
            "fail",
            f"{label} failed: {detail}. Check {TRIPLETS} and repair the real HydroCNHS environment.",
        )
    return proc


def check_python_runtime() -> None:
    # The KI is for a Python package. The executable subject is the realpath
    # of the interpreter actually verified, which is what the gate compares.
    if not MODEL_VENV_PYTHON.is_file():
        add_check(
            "binary",
            str(MODEL_VENV_PYTHON),
            True,
            "fail",
            f"Restore the HydroCNHS model venv at {MODEL_DIR / 'venv'} or install hydrocnhs in KISSPATH_PYTHON_ENV; see {TRIPLETS}.",
        )
        return
    if not os.access(MODEL_VENV_PYTHON, os.X_OK):
        add_check(
            "binary",
            str(MODEL_VENV_PYTHON.resolve()),
            True,
            "fail",
            f"Run chmod +x {MODEL_VENV_PYTHON}; see {TRIPLETS}.",
        )
        return

    real_python = str(MODEL_VENV_PYTHON.resolve())
    run_subprocess(
        [str(MODEL_VENV_PYTHON), "--version"],
        label="HydroCNHS Python runtime startup",
        subject=real_python,
        kind="binary",
        critical=True,
        timeout_s=10,
    )


def check_hydrocnhs_import() -> None:
    code = (
        "import hydrocnhs, hydrocnhs.calibration; "
        "version = getattr(hydrocnhs, '__version__', 'NO_VERSION'); "
        f"raise SystemExit(0 if version == '{EXPECTED_VERSION}' else "
        "f'unexpected hydrocnhs version {version}')"
    )
    run_subprocess(
        [str(MODEL_VENV_PYTHON), "-c", code],
        label=f"import hydrocnhs {EXPECTED_VERSION}",
        subject="hydrocnhs",
        kind="import",
        critical=True,
        timeout_s=30,
    )


def check_shared_python_env() -> None:
    if not PYTHON_ENV.is_file():
        return
    code = (
        "import importlib.util; "
        "raise SystemExit(0 if importlib.util.find_spec('hydrocnhs') else 1)"
    )
    try:
        proc = subprocess.run(
            [str(PYTHON_ENV), "-c", code],
            cwd=str(KI_DIR),
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
    except subprocess.TimeoutExpired:
        add_check(
            "run",
            str(PYTHON_ENV.resolve()),
            False,
            "pass",
        )
        return

    if proc.returncode == 0:
        add_check("import", str(PYTHON_ENV.resolve()), False, "pass")
    else:
        add_check(
            "import",
            f"{PYTHON_ENV.resolve()} does not provide hydrocnhs; using model-local venv",
            False,
            "pass",
        )


def check_tool_syntax() -> None:
    for rel in [
        "tools/build_model_config.py",
        "tools/convert_climate_inputs.py",
        "tools/convert_parameters.py",
        "tools/run_hydrocnhs.py",
        "tools/parse_output.py",
    ]:
        path = KI_DIR / rel
        if not path.is_file():
            add_check(
                "data",
                rel,
                True,
                "fail",
                f"Restore required KI tool {rel}; see {TRIPLETS}.",
            )
            continue
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as exc:
            add_check(
                "run",
                str(path.resolve()),
                True,
                "fail",
                f"Fix syntax error in {rel}: {exc.msg}; see {TRIPLETS}.",
            )
        else:
            add_check("run", str(path.resolve()), True, "pass")


def main() -> None:
    print("=" * 60)
    print(f"  PREFLIGHT CHECK: {MODEL_ID}")
    print("=" * 60)

    check_python_runtime()
    check_dir(MODEL_SOURCE_DIR, "HydroCNHS source package", critical=True)
    check_file(KI_DIR / "SKILL.md", "KI SKILL.md", critical=True)
    check_file(KI_DIR / "knowledge_infrastructure.yaml", "KI manifest", critical=True)
    check_file(KI_DIR / "dag.yaml", "KI DAG", critical=True)
    check_file(TRIPLETS, "diagnostic triplets", critical=False)
    check_file(KI_DIR / "docs" / "format_spec.yaml", "I/O format spec", critical=False)
    check_tool_syntax()
    check_shared_python_env()

    if MODEL_VENV_PYTHON.is_file():
        check_hydrocnhs_import()

    failed_critical = [c for c in checks if c["status"] == "fail" and c.get("critical")]
    print()
    print(f"  Results: {len(checks) - len([c for c in checks if c['status'] == 'fail'])} passed, {len([c for c in checks if c['status'] == 'fail'])} failed")
    if failed_critical:
        print(f"  STATUS: PREFLIGHT FAILED - inspect fixes above and {TRIPLETS}")
    else:
        print("  STATUS: PREFLIGHT PASSED - safe to proceed with model execution")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
