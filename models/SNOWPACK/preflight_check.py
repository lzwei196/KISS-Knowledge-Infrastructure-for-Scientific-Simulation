#!/usr/bin/env python3
"""Preflight check for the SNOWPACK Knowledge Infrastructure."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path


MODEL_ID = "SNOWPACK"
KI_DIR = Path(__file__).resolve().parent
DIAGNOSTICS = KI_DIR / "diagnostics" / "triplets.yaml"
PYTHON = Path("KISSPATH_PYTHON_ENV/bin/python3")
SNOWPACK_BIN = Path(
    "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/"
    "Alpine3D/local_install/bin/snowpack"
)

TOOL_FILES = [
    KI_DIR / "tools" / "build_sno_profile.py",
    KI_DIR / "tools" / "convert_forcing.py",
    KI_DIR / "tools" / "generate_config.py",
    KI_DIR / "tools" / "parse_output.py",
    KI_DIR / "tools" / "run_snowpack.py",
]

REQUIRED_FILES = [
    KI_DIR / "SKILL.md",
    KI_DIR / "knowledge_infrastructure.yaml",
    KI_DIR / "dag.yaml",
    KI_DIR / "docs" / "format_spec.yaml",
    DIAGNOSTICS,
]


def fix(message):
    return f"{message}; check {DIAGNOSTICS} for known SNOWPACK recovery steps."


def add_check(checks, kind, subject, critical, passed, fix_text=""):
    checks.append(
        {
            "kind": kind,
            "subject": str(subject),
            "critical": bool(critical),
            "status": "pass" if passed else "fail",
            "fix": "" if passed else fix_text,
        }
    )


def check_file(checks, path, label, critical=True, executable=False):
    path = Path(path)
    subject = path.resolve(strict=False)
    if not path.is_file():
        print(f"  FAIL  {label}: not found at {path}")
        add_check(checks, "data", subject, critical, False, fix(f"Restore required file {path}"))
        return False
    if executable and not os.access(path, os.X_OK):
        print(f"  FAIL  {label}: exists but is not executable: {path}")
        add_check(checks, "binary", subject, critical, False, fix(f"Run chmod +x {path}"))
        return False
    print(f"  OK    {label}: {path}")
    add_check(checks, "data", subject, critical, True)
    return True


def check_dir(checks, path, label, critical=True):
    path = Path(path)
    subject = path.resolve(strict=False)
    if not path.is_dir():
        print(f"  FAIL  {label}: not found at {path}")
        add_check(checks, "data", subject, critical, False, fix(f"Restore required directory {path}"))
        return False
    print(f"  OK    {label}: {path} ({len(list(path.iterdir()))} items)")
    add_check(checks, "data", subject, critical, True)
    return True


def check_python(checks):
    subject = PYTHON.resolve(strict=False)
    if not PYTHON.is_file() or not os.access(PYTHON, os.X_OK):
        print(f"  FAIL  HydroCraft Python: not executable at {PYTHON}")
        add_check(
            checks,
            "import",
            subject,
            True,
            False,
            fix(f"Restore the HydroCraft Python interpreter at {PYTHON}"),
        )
        return False
    result = subprocess.run(
        [str(PYTHON), "-V"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=8,
    )
    passed = result.returncode == 0 and "Python" in result.stdout
    if passed:
        print(f"  OK    HydroCraft Python: {subject} ({result.stdout.strip()})")
    else:
        print(f"  FAIL  HydroCraft Python: {PYTHON} did not start")
    add_check(
        checks,
        "import",
        subject,
        True,
        passed,
        fix(f"Repair or recreate the HydroCraft Python environment at {PYTHON}"),
    )
    return passed


def check_import(checks, module, critical=True):
    result = subprocess.run(
        [str(PYTHON), "-c", f"import {module}"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=12,
    )
    passed = result.returncode == 0
    if passed:
        print(f"  OK    import {module}: using {PYTHON}")
    else:
        detail = (result.stderr or result.stdout).strip().splitlines()[-1:]
        print(f"  FAIL  import {module}: {' '.join(detail)}")
    add_check(
        checks,
        "import",
        f"{PYTHON}:{module}",
        critical,
        passed,
        fix(f"Install Python dependency '{module.split('.')[0]}' in {PYTHON.parent.parent}"),
    )
    return passed


def check_py_compile(checks, path):
    result = subprocess.run(
        [str(PYTHON), "-m", "py_compile", str(path)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=12,
    )
    passed = result.returncode == 0
    if passed:
        print(f"  OK    tool syntax: {path.relative_to(KI_DIR)}")
    else:
        detail = (result.stderr or result.stdout).strip().splitlines()[-1:]
        print(f"  FAIL  tool syntax: {path.relative_to(KI_DIR)}: {' '.join(detail)}")
    add_check(
        checks,
        "import",
        path.resolve(strict=False),
        True,
        passed,
        fix(f"Fix Python syntax/import-time issue in {path}"),
    )
    return passed


def manifest_binary_path():
    manifest = KI_DIR / "knowledge_infrastructure.yaml"
    try:
        text = manifest.read_text(encoding="utf-8")
    except OSError:
        return None
    match = re.search(r"(?m)^\s{4}path:\s*(\S.*)$", text)
    return Path(match.group(1).strip().strip("'\"")) if match else None


def check_manifest_binary(checks):
    manifest_path = manifest_binary_path()
    expected = SNOWPACK_BIN.resolve(strict=False)
    passed = manifest_path is not None and manifest_path.resolve(strict=False) == expected
    if passed:
        print(f"  OK    manifest binary path: {manifest_path}")
    elif manifest_path is None:
        print("  FAIL  manifest binary path: not declared in knowledge_infrastructure.yaml")
    else:
        print(f"  FAIL  manifest binary path: {manifest_path} != {SNOWPACK_BIN}")
    add_check(
        checks,
        "data",
        KI_DIR / "knowledge_infrastructure.yaml",
        True,
        passed,
        fix(f"Set package.implementation.binary.path to {SNOWPACK_BIN}"),
    )
    return passed


def check_binary(checks):
    subject = SNOWPACK_BIN.resolve(strict=False)
    if not SNOWPACK_BIN.is_file():
        print(f"  FAIL  SNOWPACK binary: not found at {SNOWPACK_BIN}")
        add_check(
            checks,
            "binary",
            subject,
            True,
            False,
            fix(f"Restore or rebuild the SNOWPACK executable at {SNOWPACK_BIN}"),
        )
        return False
    if not os.access(SNOWPACK_BIN, os.X_OK):
        print(f"  FAIL  SNOWPACK binary: not executable at {SNOWPACK_BIN}")
        add_check(checks, "binary", subject, True, False, fix(f"Run chmod +x {SNOWPACK_BIN}"))
        return False

    result = subprocess.run(
        [str(SNOWPACK_BIN), "--help"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=8,
    )
    output = result.stdout or ""
    passed = result.returncode == 0 and "Snowpack version" in output and "Usage:" in output
    if passed:
        first = output.splitlines()[0].strip()
        print(f"  OK    SNOWPACK binary starts: {subject} ({first})")
    else:
        print(f"  FAIL  SNOWPACK binary did not start cleanly: {SNOWPACK_BIN}")
    add_check(
        checks,
        "binary",
        subject,
        True,
        passed,
        fix(f"Rebuild SNOWPACK/MeteoIO or replace the executable at {SNOWPACK_BIN}"),
    )
    return passed


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}, sort_keys=True))
    sys.exit(0 if all(c["status"] == "pass" or not c.get("critical") for c in checks) else 1)


def main():
    checks = []
    print(f"{' PREFLIGHT: SNOWPACK ':=^60}")
    print()

    check_dir(checks, KI_DIR / "tools", "KI tools directory")
    for path in REQUIRED_FILES:
        check_file(checks, path, f"required file {path.relative_to(KI_DIR)}")
    for path in TOOL_FILES:
        check_file(checks, path, f"tool file {path.relative_to(KI_DIR)}")

    check_manifest_binary(checks)
    check_binary(checks)

    if check_python(checks):
        for module in ("numpy", "pandas", "xarray", "matplotlib", "yaml"):
            check_import(checks, module)
        for path in TOOL_FILES:
            check_py_compile(checks, path)
    else:
        for module in ("numpy", "pandas", "xarray", "matplotlib", "yaml"):
            add_check(
                checks,
                "import",
                f"{PYTHON}:{module}",
                True,
                False,
                fix(f"Cannot check import '{module}' until {PYTHON} starts"),
            )
        for path in TOOL_FILES:
            add_check(
                checks,
                "import",
                path.resolve(strict=False),
                True,
                False,
                fix(f"Cannot compile-check {path} until {PYTHON} starts"),
            )

    print()
    passed = sum(1 for c in checks if c["status"] == "pass")
    failed = sum(1 for c in checks if c["status"] == "fail")
    print(f"  Results: {passed} passed, {failed} failed")
    if failed:
        print(f"  Fix failures using diagnostics first: {DIAGNOSTICS}")
    else:
        print("  STATUS: PREFLIGHT PASSED")
    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
