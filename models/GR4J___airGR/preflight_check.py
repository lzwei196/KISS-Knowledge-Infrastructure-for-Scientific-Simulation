#!/usr/bin/env python3
"""Preflight check for GR4J___airGR."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


MODEL_ID = "GR4J___airGR"
KI_DIR = Path(__file__).resolve().parent
TOOLS_DIR = KI_DIR / "tools"
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"

HYDROCRAFT_PYTHON = Path("KISSPATH_PYTHON_ENV/bin/python")
PYTHON = HYDROCRAFT_PYTHON if HYDROCRAFT_PYTHON.is_file() else Path(sys.executable)
RSCRIPT = Path(shutil.which("Rscript") or "/usr/bin/Rscript")
AIRGR_SO = Path("KISSPATH_HOME/R/library/airGR/libs/airGR.so")


def make_check(kind, subject, critical, status, fix):
    return {
        "kind": kind,
        "subject": str(subject),
        "critical": bool(critical),
        "status": status,
        "fix": fix,
    }


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}))
    failed_critical = any(
        c["status"] != "pass" and c.get("critical") for c in checks
    )
    sys.exit(1 if failed_critical else 0)


def add_file_check(checks, path, label, kind="data", critical=True, executable=False):
    subject = Path(path)
    fix = ""
    status = "pass"
    display_path = subject

    if not subject.is_file():
        status = "fail"
        fix = (
            f"Restore {label} at {subject}; see {TRIPLETS} for recovery guidance."
        )
    elif executable and not os.access(subject, os.X_OK):
        status = "fail"
        fix = f"chmod +x {subject}; see {TRIPLETS} if execution still fails."

    if status == "pass":
        if executable:
            display_path = subject.resolve()
        print(f"  OK    {label}: {display_path}")
    else:
        print(f"  FAIL  {label}: {fix}")

    checks.append(
        make_check(kind, display_path, critical, status, fix)
    )


def add_dir_check(checks, path, label, critical=True):
    subject = Path(path)
    fix = ""
    status = "pass"

    if not subject.is_dir():
        status = "fail"
        fix = f"Restore {label} at {subject}; see {TRIPLETS} for recovery guidance."
    elif not any(subject.iterdir()):
        status = "fail"
        fix = f"Populate {label} at {subject}; see {TRIPLETS} for recovery guidance."

    if status == "pass":
        print(f"  OK    {label}: {subject} ({len(list(subject.iterdir()))} items)")
    else:
        print(f"  FAIL  {label}: {fix}")

    checks.append(make_check("data", subject, critical, status, fix))


def run_command_check(checks, cmd, label, kind, subject, critical=True, fix=None,
                      timeout=20, env=None):
    fix = fix or f"Repair {label}; see {TRIPLETS} for recovery guidance."
    try:
        proc = subprocess.run(
            cmd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"  FAIL  {label}: {exc}")
        checks.append(make_check(kind, subject, critical, "fail", fix))
        return

    if proc.returncode == 0:
        first_line = (proc.stdout or proc.stderr).strip().splitlines()
        detail = f": {first_line[0]}" if first_line else ""
        print(f"  OK    {label}{detail}")
        checks.append(make_check(kind, subject, critical, "pass", ""))
    else:
        detail = (proc.stderr or proc.stdout).strip().splitlines()
        suffix = f": {detail[0]}" if detail else ""
        print(f"  FAIL  {label}{suffix}")
        print(f"         Fix: {fix}")
        checks.append(make_check(kind, subject, critical, "fail", fix))


def add_python_import_check(checks, module, critical=True):
    subject = f"{PYTHON}:{module}"
    cmd = [
        str(PYTHON),
        "-c",
        f"import {module}; print(getattr({module}, '__file__', '{module}'))",
    ]
    run_command_check(
        checks,
        cmd,
        f"HydroCraft Python import {module}",
        "import",
        subject,
        critical=critical,
        fix=(
            f"Install {module.split('.')[0]} into {PYTHON}; see {TRIPLETS} for "
            "known environment fixes."
        ),
    )


def add_tool_import_check(checks, tool_name):
    env = os.environ.copy()
    env["PYTHONPATH"] = str(KI_DIR)
    subject = f"{PYTHON}:tools.{tool_name}"
    run_command_check(
        checks,
        [str(PYTHON), "-c", f"import tools.{tool_name}; print('imported')"],
        f"KI tool import tools.{tool_name}",
        "import",
        subject,
        critical=True,
        fix=(
            f"Fix syntax/import errors in tools/{tool_name}.py or install its "
            f"dependencies into {PYTHON}; see {TRIPLETS}."
        ),
        env=env,
    )


def main():
    checks = []
    print(f"{' PREFLIGHT: GR4J___airGR ':=^60}")
    print()

    # Existing real checks, now represented in the required JSON report.
    add_dir_check(checks, TOOLS_DIR, "KI tools directory", critical=True)
    add_file_check(
        checks,
        AIRGR_SO,
        "airGR compiled shared object",
        kind="binary",
        critical=True,
        executable=True,
    )
    add_file_check(
        checks,
        TRIPLETS,
        "diagnostics/triplets.yaml",
        kind="data",
        critical=False,
    )

    # Cheap startup checks for the actual runtime used by tools/run_gr4j.py.
    add_file_check(
        checks,
        RSCRIPT,
        "Rscript executable",
        kind="binary",
        critical=True,
        executable=True,
    )
    run_command_check(
        checks,
        [str(RSCRIPT), "--version"],
        "Rscript starts",
        "run",
        str(RSCRIPT.resolve()) if RSCRIPT.exists() else str(RSCRIPT),
        critical=True,
        fix=f"Install or repair Rscript; see {TRIPLETS} for recovery guidance.",
        timeout=10,
    )
    run_command_check(
        checks,
        [
            str(RSCRIPT),
            "--vanilla",
            "-e",
            (
                '.libPaths(c("KISSPATH_HOME/R/library", .libPaths())); '
                'library(airGR); '
                'stopifnot(file.exists(system.file("libs", "airGR.so", '
                'package="airGR"))); '
                'cat(as.character(packageVersion("airGR")), "\\n")'
            ),
        ],
        "airGR package loads in R",
        "run",
        str(AIRGR_SO.resolve()) if AIRGR_SO.exists() else str(AIRGR_SO),
        critical=True,
        fix=(
            'Install/load airGR in KISSPATH_HOME/R/library; in R run '
            'install.packages("airGR", lib="KISSPATH_HOME/R/library"). '
            f"Then check {TRIPLETS}."
        ),
    )

    add_file_check(
        checks,
        PYTHON,
        "HydroCraft Python interpreter",
        kind="binary",
        critical=True,
        executable=True,
    )
    for module in ("numpy", "pandas"):
        add_python_import_check(checks, module, critical=True)
    for module in ("matplotlib", "xarray"):
        add_python_import_check(checks, module, critical=False)

    for tool_name in (
        "convert_catchment_params",
        "convert_forcing_to_gr4j",
        "run_gr4j",
        "parse_gr4j_output",
    ):
        add_tool_import_check(checks, tool_name)

    print()
    passed = sum(c["status"] == "pass" for c in checks)
    failed = len(checks) - passed
    print(f"  Results: {passed} passed, {failed} failed")
    if failed:
        print(f"  STATUS: PREFLIGHT FAILED - check fixes above and {TRIPLETS}")
    else:
        print("  STATUS: PREFLIGHT PASSED - safe to proceed with model execution")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
