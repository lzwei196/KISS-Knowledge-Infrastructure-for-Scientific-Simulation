#!/usr/bin/env python3
"""Preflight check for the LPJmL knowledge infrastructure."""

import json
import os
import subprocess
import sys
from pathlib import Path


MODEL_ID = "LPJmL"
KI_DIR = Path(__file__).resolve().parent
DIAGNOSTICS = KI_DIR / "diagnostics" / "triplets.yaml"
HYDROCRAFT_PYTHON = Path("KISSPATH_PYTHON_ENV/bin/python")
LPJML_BINARY = Path(
    "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/LPJmL/source/repo/bin/lpjml"
)
LPJROOT = LPJML_BINARY.parent.parent


def make_check(kind, subject, critical, status, fix=""):
    check = {
        "kind": kind,
        "subject": str(subject),
        "critical": bool(critical),
        "status": status,
        "fix": fix,
    }
    if status == "fail" and not fix:
        check["fix"] = f"Check {DIAGNOSTICS} for recovery steps."
    return check


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}))
    sys.exit(0 if all(c["status"] == "pass" or not c.get("critical") for c in checks) else 1)


def add_file_check(checks, path, label, critical=True, executable=False, kind="data"):
    path = Path(path)
    subject = path.resolve() if path.exists() else path
    if not path.is_file():
        fix = f"Restore {label} at {path}; check {DIAGNOSTICS} for recovery steps."
        print(f"  FAIL  {label}: missing file {path}")
        checks.append(make_check(kind, subject, critical, "fail", fix))
        return False
    if executable and not os.access(path, os.X_OK):
        fix = f"Run chmod +x {path}; check {DIAGNOSTICS} if execution still fails."
        print(f"  FAIL  {label}: not executable {path}")
        checks.append(make_check(kind, path.resolve(), critical, "fail", fix))
        return False
    print(f"  OK    {label}: {path.resolve()}")
    checks.append(make_check(kind, path.resolve(), critical, "pass"))
    return True


def add_dir_check(checks, path, label, critical=True, non_empty=False):
    path = Path(path)
    subject = path.resolve() if path.exists() else path
    if not path.is_dir():
        fix = f"Restore {label} at {path}; check {DIAGNOSTICS} for recovery steps."
        print(f"  FAIL  {label}: missing directory {path}")
        checks.append(make_check("data", subject, critical, "fail", fix))
        return False
    count = len(list(path.iterdir()))
    if non_empty and count == 0:
        fix = f"Populate {label} at {path}; check {DIAGNOSTICS} for recovery steps."
        print(f"  FAIL  {label}: empty directory {path}")
        checks.append(make_check("data", path.resolve(), critical, "fail", fix))
        return False
    print(f"  OK    {label}: {path.resolve()} ({count} items)")
    checks.append(make_check("data", path.resolve(), critical, "pass"))
    return True


def add_binary_start_check(checks, binary):
    binary = Path(binary)
    subject = binary.resolve() if binary.exists() else binary
    if not binary.is_file() or not os.access(binary, os.X_OK):
        fix = f"Build LPJmL so bin/lpjml exists and is executable; check {DIAGNOSTICS}."
        print(f"  FAIL  LPJmL startup: executable unavailable at {binary}")
        checks.append(make_check("run", subject, True, "fail", fix))
        return False

    try:
        result = subprocess.run(
            [str(binary), "-h"],
            cwd=str(binary.parent.parent),
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
    except subprocess.TimeoutExpired:
        fix = f"LPJmL help command timed out; inspect binary dependencies and {DIAGNOSTICS}."
        print(f"  FAIL  LPJmL startup: timed out running {binary} -h")
        checks.append(make_check("run", binary.resolve(), True, "fail", fix))
        return False
    except OSError as exc:
        fix = f"Fix LPJmL executable/dependencies for {binary}; check {DIAGNOSTICS}. Error: {exc}"
        print(f"  FAIL  LPJmL startup: {exc}")
        checks.append(make_check("run", binary.resolve(), True, "fail", fix))
        return False

    output = (result.stdout + result.stderr).strip()
    if result.returncode == 0 and "LPJmL" in output and "Usage:" in output:
        print("  OK    LPJmL startup: help command completed")
        checks.append(make_check("run", binary.resolve(), True, "pass"))
        return True

    fix = (
        f"Run {binary} -h manually and check {DIAGNOSTICS}; "
        f"exit={result.returncode}, output={output[:300]!r}"
    )
    print(f"  FAIL  LPJmL startup: unexpected help output or exit {result.returncode}")
    checks.append(make_check("run", binary.resolve(), True, "fail", fix))
    return False


def add_import_check(checks, module, critical=True):
    subject = f"{HYDROCRAFT_PYTHON} -c import {module}"
    if not HYDROCRAFT_PYTHON.is_file() or not os.access(HYDROCRAFT_PYTHON, os.X_OK):
        fix = f"Restore executable HydroCraft Python at {HYDROCRAFT_PYTHON}; check {DIAGNOSTICS}."
        print(f"  FAIL  import {module}: HydroCraft Python not executable")
        checks.append(make_check("import", subject, critical, "fail", fix))
        return False

    code = f"import {module}"
    try:
        result = subprocess.run(
            [str(HYDROCRAFT_PYTHON), "-c", code],
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
    except subprocess.TimeoutExpired:
        fix = f"Import {module} timed out in {HYDROCRAFT_PYTHON}; check {DIAGNOSTICS}."
        print(f"  FAIL  import {module}: timed out")
        checks.append(make_check("import", subject, critical, "fail", fix))
        return False
    except OSError as exc:
        fix = f"Fix HydroCraft Python at {HYDROCRAFT_PYTHON}; check {DIAGNOSTICS}. Error: {exc}"
        print(f"  FAIL  import {module}: {exc}")
        checks.append(make_check("import", subject, critical, "fail", fix))
        return False
    if result.returncode == 0:
        print(f"  OK    import {module}: via {HYDROCRAFT_PYTHON}")
        checks.append(make_check("import", subject, critical, "pass"))
        return True

    fix = (
        f"Install {module.split('.')[0]} into {HYDROCRAFT_PYTHON}; "
        f"check {DIAGNOSTICS}. Error: {(result.stderr or result.stdout).strip()[:300]}"
    )
    print(f"  FAIL  import {module}: {(result.stderr or result.stdout).strip()}")
    checks.append(make_check("import", subject, critical, "fail", fix))
    return False


def add_py_compile_check(checks):
    tools = sorted((KI_DIR / "tools").glob("*.py"))
    subject = f"{HYDROCRAFT_PYTHON} -m py_compile " + " ".join(str(p) for p in tools)
    if not HYDROCRAFT_PYTHON.is_file() or not os.access(HYDROCRAFT_PYTHON, os.X_OK):
        fix = f"Restore executable HydroCraft Python at {HYDROCRAFT_PYTHON}; check {DIAGNOSTICS}."
        print("  FAIL  KI tool syntax: HydroCraft Python not executable")
        checks.append(make_check("run", subject, True, "fail", fix))
        return False
    if not tools:
        fix = f"Restore KI tool scripts under {KI_DIR / 'tools'}; check {DIAGNOSTICS}."
        print("  FAIL  KI tool syntax: no Python tools found")
        checks.append(make_check("run", subject, True, "fail", fix))
        return False

    try:
        result = subprocess.run(
            [str(HYDROCRAFT_PYTHON), "-m", "py_compile", *map(str, tools)],
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
    except subprocess.TimeoutExpired:
        fix = f"Python tool compilation timed out; check {DIAGNOSTICS}."
        print("  FAIL  KI tool syntax: timed out")
        checks.append(make_check("run", subject, True, "fail", fix))
        return False
    except OSError as exc:
        fix = f"Fix HydroCraft Python/tool execution; check {DIAGNOSTICS}. Error: {exc}"
        print(f"  FAIL  KI tool syntax: {exc}")
        checks.append(make_check("run", subject, True, "fail", fix))
        return False
    if result.returncode == 0:
        print(f"  OK    KI tool syntax: {len(tools)} Python tools compile")
        checks.append(make_check("run", subject, True, "pass"))
        return True

    fix = f"Fix Python syntax/import-time compile errors in tools; check {DIAGNOSTICS}. {result.stderr[:300]}"
    print(f"  FAIL  KI tool syntax: {result.stderr.strip()}")
    checks.append(make_check("run", subject, True, "fail", fix))
    return False


def main():
    checks = []
    print(f"{' PREFLIGHT: LPJmL ':=^60}")
    print()

    add_dir_check(checks, KI_DIR / "tools", "KI tools directory", critical=True, non_empty=True)
    add_file_check(checks, DIAGNOSTICS, "diagnostics triplets", critical=True)
    add_file_check(checks, KI_DIR / "SKILL.md", "KI SKILL.md", critical=True)
    add_file_check(checks, KI_DIR / "knowledge_infrastructure.yaml", "KI manifest", critical=True)
    add_file_check(checks, KI_DIR / "dag.yaml", "KI DAG", critical=True)

    add_file_check(checks, LPJML_BINARY, "LPJmL binary", critical=True, executable=True, kind="binary")
    add_binary_start_check(checks, LPJML_BINARY)
    add_dir_check(checks, LPJROOT / "par", "LPJmL parameter directory", critical=True, non_empty=True)
    add_file_check(checks, LPJROOT / "lpjml_config.cjson", "LPJmL example configuration", critical=True)
    add_file_check(checks, LPJROOT / "input.cjson", "LPJmL input include", critical=True)

    add_file_check(
        checks,
        HYDROCRAFT_PYTHON,
        "HydroCraft Python interpreter",
        critical=True,
        executable=True,
        kind="run",
    )
    for module in ("numpy", "netCDF4", "xarray"):
        add_import_check(checks, module, critical=True)
    add_py_compile_check(checks)

    failures = [c for c in checks if c["status"] == "fail"]
    print()
    print(f"  Results: {len(checks) - len(failures)} passed, {len(failures)} failed")
    if failures:
        print(f"  STATUS: PREFLIGHT FAILED. See fixes above and {DIAGNOSTICS}.")
    else:
        print("  STATUS: PREFLIGHT PASSED. Model execution prerequisites are available.")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
