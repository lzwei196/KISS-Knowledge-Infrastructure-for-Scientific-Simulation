#!/usr/bin/env python3
"""Preflight check for the PIHM knowledge infrastructure."""

import json
import os
import subprocess
import sys
from pathlib import Path


MODEL_ID = "PIHM"
KI_DIR = Path(__file__).resolve().parent
MODEL_ROOT = KI_DIR.parent
REPO_DIR = MODEL_ROOT / "source" / "repo"
PIHM_BINARY = REPO_DIR / "flux-pihm"
HYDRO_PYTHON = Path("KISSPATH_PYTHON_ENV/bin/python")
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"

CRITICAL_INPUT_EXTENSIONS = [
    ".mesh",
    ".att",
    ".soil",
    ".meteo",
    ".riv",
    ".para",
    ".calib",
]


def make_check(kind, subject, critical, ok, fix):
    return {
        "kind": kind,
        "subject": str(subject),
        "critical": bool(critical),
        "status": "pass" if ok else "fail",
        "fix": "" if ok else fix,
    }


def add_file_check(checks, path, label, critical=True, executable=False):
    path = Path(path)
    ok = path.is_file()
    if ok and executable:
        ok = os.access(path, os.X_OK)
    subject = path.resolve() if path.exists() else path
    if ok:
        print(f"  OK    {label}: {subject}")
    else:
        reason = "missing"
        if path.exists() and executable:
            reason = "not executable"
        print(f"  FAIL  {label}: {subject} ({reason})")
    fix = (
        f"Restore/build {path}; check {TRIPLETS} for known PIHM recovery steps."
        if not executable
        else f"Build PIHM/Flux-PIHM or chmod +x {path}; check {TRIPLETS}."
    )
    checks.append(make_check("binary" if executable else "data", subject, critical, ok, fix))
    return ok


def add_dir_check(checks, path, label, critical=True, nonempty=False):
    path = Path(path)
    ok = path.is_dir() and (not nonempty or any(path.iterdir()))
    subject = path.resolve() if path.exists() else path
    if ok:
        count = len(list(path.iterdir()))
        print(f"  OK    {label}: {subject} ({count} items)")
    else:
        print(f"  FAIL  {label}: {subject} (missing or empty)")
    fix = f"Restore {path}; check {TRIPLETS} for the expected KI/model layout."
    checks.append(make_check("data", subject, critical, ok, fix))
    return ok


def add_python_import_check(checks, module, critical=True):
    subject = f"{HYDRO_PYTHON} import {module}"
    if not HYDRO_PYTHON.is_file():
        print(f"  FAIL  Python import {module}: interpreter missing at {HYDRO_PYTHON}")
        checks.append(
            make_check(
                "import",
                subject,
                critical,
                False,
                f"Restore HydroCraft Python environment at {HYDRO_PYTHON}; check {TRIPLETS}.",
            )
        )
        return False

    result = subprocess.run(
        [str(HYDRO_PYTHON), "-c", f"import {module}"],
        cwd=str(KI_DIR),
        text=True,
        capture_output=True,
        timeout=20,
    )
    ok = result.returncode == 0
    if ok:
        print(f"  OK    Python import: {module}")
    else:
        detail = (result.stderr or result.stdout).strip().splitlines()
        tail = detail[-1] if detail else f"exit {result.returncode}"
        print(f"  FAIL  Python import {module}: {tail}")
    fix = (
        f"Install/repair {module.split('.')[0]} in {HYDRO_PYTHON}; check {TRIPLETS}."
    )
    checks.append(make_check("import", subject, critical, ok, fix))
    return ok


def add_binary_start_check(checks, binary):
    binary = Path(binary)
    subject = binary.resolve() if binary.exists() else binary
    if not (binary.is_file() and os.access(binary, os.X_OK)):
        checks.append(
            make_check(
                "run",
                f"{subject} startup probe",
                True,
                False,
                f"Build or restore executable {binary}; check {TRIPLETS}.",
            )
        )
        return False

    result = subprocess.run(
        [str(subject)],
        cwd=str(REPO_DIR),
        text=True,
        capture_output=True,
        timeout=5,
    )
    output = result.stdout + result.stderr
    ok = (
        result.returncode != 127
        and result.returncode != 126
        and ("Usage:" in output or "project" in output or "ParseCmdLineParam" in output)
    )
    if ok:
        print(f"  OK    PIHM binary starts and prints usage: {subject}")
    else:
        print(f"  FAIL  PIHM binary startup probe failed: {subject}")
    fix = f"Rebuild Flux-PIHM in {REPO_DIR} and check {TRIPLETS} for loader/runtime errors."
    checks.append(make_check("run", f"{subject} startup probe", True, ok, fix))
    return ok


def add_shalehills_input_checks(checks):
    input_dir = REPO_DIR / "input" / "ShaleHills"
    add_dir_check(checks, input_dir, "ShaleHills example input directory", critical=True, nonempty=True)
    for ext in CRITICAL_INPUT_EXTENSIONS:
        add_file_check(
            checks,
            input_dir / f"ShaleHills{ext}",
            f"ShaleHills required input {ext}",
            critical=True,
        )


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}, sort_keys=True))
    failed_critical = any(c["status"] != "pass" and c.get("critical") for c in checks)
    sys.exit(1 if failed_critical else 0)


def main():
    checks = []

    print("=" * 60)
    print(f"  PREFLIGHT CHECK: {MODEL_ID}")
    print("=" * 60)

    add_dir_check(checks, KI_DIR / "tools", "KI tools directory", critical=True, nonempty=True)
    add_file_check(checks, TRIPLETS, "diagnostic triplets", critical=True)
    add_file_check(checks, KI_DIR / "knowledge_infrastructure.yaml", "KI manifest", critical=True)
    add_file_check(checks, KI_DIR / "dag.yaml", "DAG contract", critical=True)
    add_file_check(checks, KI_DIR / "docs" / "format_spec.yaml", "I/O format specification", critical=False)

    add_dir_check(checks, REPO_DIR, "MM-PIHM source repository", critical=True, nonempty=True)
    add_file_check(checks, PIHM_BINARY, "Flux-PIHM executable", critical=True, executable=True)
    add_binary_start_check(checks, PIHM_BINARY)

    for tool in [
        "config_writer.py",
        "forcing_converter.py",
        "mesh_builder.py",
        "output_parser.py",
        "run_pihm.py",
        "soil_converter.py",
    ]:
        add_file_check(checks, KI_DIR / "tools" / tool, f"KI tool {tool}", critical=True)

    for module in ["numpy", "rasterio", "shapely", "ki_tools_common.terrain_ops"]:
        add_python_import_check(checks, module, critical=True)

    add_shalehills_input_checks(checks)

    passed = sum(c["status"] == "pass" for c in checks)
    failed = len(checks) - passed
    print()
    print(f"  Results: {passed} passed, {failed} failed")
    if failed:
        print(f"  STATUS: PREFLIGHT FAILED - check fixes above and {TRIPLETS}")
    else:
        print("  STATUS: PREFLIGHT PASSED - model execution prerequisites are available")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
