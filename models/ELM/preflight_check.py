#!/usr/bin/env python3
"""Preflight check for the ELM knowledge infrastructure."""

import json
import os
import re
import subprocess
import sys
from pathlib import Path


MODEL_ID = "ELM"
KI_DIR = Path(__file__).resolve().parent
PYTHON_ENV = Path("KISSPATH_PYTHON_ENV/bin/python")
DEFAULT_BINARY = Path("KISSPATH_HOME/e3sm_scratch/elm_test_case/bld/e3sm.exe")
DIAGNOSTICS = KI_DIR / "diagnostics" / "triplets.yaml"


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}))
    sys.exit(0 if all(c["status"] == "pass" or not c.get("critical") for c in checks) else 1)


def fix_hint(message):
    return f"{message} Check {DIAGNOSTICS} for known recovery triplets."


def add_check(checks, kind, subject, critical, passed, fix):
    status = "pass" if passed else "fail"
    checks.append(
        {
            "kind": kind,
            "subject": str(subject),
            "critical": bool(critical),
            "status": status,
            "fix": "" if passed else fix,
        }
    )
    label = "OK" if passed else "FAIL"
    crit = "critical" if critical else "noncritical"
    print(f"  {label:<4} {kind:<7} {subject} ({crit})")
    if not passed:
        print(f"       Fix: {fix}")


def read_manifest_binary():
    manifest = KI_DIR / "knowledge_infrastructure.yaml"
    if not manifest.is_file():
        return DEFAULT_BINARY
    text = manifest.read_text(encoding="utf-8")
    binary_block = re.search(r"(?ms)^\s+binary:\s*\n(?P<body>(?:^[ \t]+[^\n]*\n?)+)", text)
    if not binary_block:
        return DEFAULT_BINARY
    path_match = re.search(r"(?m)^\s+path:\s*(?P<path>\S.*)$", binary_block.group("body"))
    if not path_match:
        return DEFAULT_BINARY
    return Path(path_match.group("path").strip().strip("'\""))


def check_file(checks, path, kind, critical, executable=False, nonempty=False):
    path = Path(path)
    subject = os.path.realpath(path) if executable else path
    if not path.is_file():
        add_check(checks, kind, subject, critical, False, fix_hint(f"Restore required file: {path}."))
        return False
    if executable and not os.access(path, os.X_OK):
        add_check(checks, kind, subject, critical, False, fix_hint(f"Make executable: chmod +x {path}."))
        return False
    if nonempty and path.stat().st_size == 0:
        add_check(checks, kind, subject, critical, False, fix_hint(f"Replace empty file: {path}."))
        return False
    add_check(checks, kind, subject, critical, True, "")
    return True


def check_dir(checks, path, kind, critical, nonempty=False):
    path = Path(path)
    if not path.is_dir():
        add_check(checks, kind, path, critical, False, fix_hint(f"Restore required directory: {path}."))
        return False
    if nonempty and not any(path.iterdir()):
        add_check(checks, kind, path, critical, False, fix_hint(f"Directory is empty: {path}."))
        return False
    add_check(checks, kind, path, critical, True, "")
    return True


def check_python_import(checks, module, critical=True):
    subject = f"{PYTHON_ENV}: import {module}"
    if not PYTHON_ENV.is_file():
        add_check(
            checks,
            "import",
            subject,
            critical,
            False,
            fix_hint(f"HydroCraft Python interpreter not found: {PYTHON_ENV}."),
        )
        return False
    cmd = [
        str(PYTHON_ENV),
        "-c",
        f"import importlib; importlib.import_module({module!r})",
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    except subprocess.TimeoutExpired:
        add_check(
            checks,
            "import",
            subject,
            critical,
            False,
            fix_hint(f"Import timed out for dependency '{module}' in {PYTHON_ENV}."),
        )
        return False
    if proc.returncode == 0:
        add_check(checks, "import", subject, critical, True, "")
        return True
    err = (proc.stderr or proc.stdout or "").strip().splitlines()
    detail = err[-1] if err else f"exit {proc.returncode}"
    add_check(
        checks,
        "import",
        subject,
        critical,
        False,
        fix_hint(f"Install/repair Python dependency '{module}' in {PYTHON_ENV}; last error: {detail}."),
    )
    return False


def check_tool_syntax(checks):
    tools = [
        KI_DIR / "tools" / "convert_forcing_to_elm.py",
        KI_DIR / "tools" / "convert_surface_data.py",
        KI_DIR / "tools" / "parse_elm_output.py",
        KI_DIR / "tools" / "run_elm.py",
    ]
    missing = [str(p) for p in tools if not p.is_file()]
    subject = ", ".join(str(p.relative_to(KI_DIR)) for p in tools)
    if missing:
        add_check(checks, "data", subject, True, False, fix_hint(f"Restore missing KI tool(s): {', '.join(missing)}."))
        return False
    if not PYTHON_ENV.is_file():
        add_check(
            checks,
            "import",
            subject,
            True,
            False,
            fix_hint(f"HydroCraft Python interpreter not found: {PYTHON_ENV}."),
        )
        return False
    cmd = [str(PYTHON_ENV), "-m", "py_compile"] + [str(p) for p in tools]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        add_check(
            checks,
            "import",
            subject,
            True,
            False,
            fix_hint("Python compilation of KI tools timed out."),
        )
        return False
    if proc.returncode == 0:
        add_check(checks, "import", subject, True, True, "")
        return True
    detail = (proc.stderr or proc.stdout or "").strip().splitlines()[-1:]
    add_check(
        checks,
        "import",
        subject,
        True,
        False,
        fix_hint(f"Fix Python syntax/import-time compile failure in KI tools: {' '.join(detail)}."),
    )
    return False


def check_binary_smoke_start(checks, binary):
    subject = f"{os.path.realpath(binary)} --help"
    if not Path(binary).is_file() or not os.access(binary, os.X_OK):
        add_check(
            checks,
            "run",
            subject,
            False,
            False,
            fix_hint("Binary smoke-start skipped because executable check failed."),
        )
        return False

    try:
        proc = subprocess.run(
            [str(binary), "--help"],
            cwd=str(KI_DIR),
            capture_output=True,
            text=True,
            timeout=8,
        )
    except subprocess.TimeoutExpired:
        add_check(
            checks,
            "run",
            subject,
            False,
            False,
            fix_hint("ELM smoke start timed out; verify by launching from the CIME case run directory."),
        )
        return False

    output = f"{proc.stdout}\n{proc.stderr}"
    started = proc.returncode == 0 or "cime_cpl_init" in output or "MPI_ABORT" in output
    if started:
        add_check(checks, "run", subject, False, True, "")
        return True

    detail = output.strip().splitlines()[-1:] or [f"exit {proc.returncode}"]
    add_check(
        checks,
        "run",
        subject,
        False,
        False,
        fix_hint(f"ELM executable did not reach initialization: {' '.join(detail)}."),
    )
    return False


def main():
    print(f"{' PREFLIGHT: ELM ':=^60}")
    print(f"KI directory: {KI_DIR}")
    print(f"Diagnostics: {DIAGNOSTICS}")
    print()

    checks = []
    binary = read_manifest_binary()
    run_dir = binary.parent.parent / "run"

    check_file(checks, KI_DIR / "knowledge_infrastructure.yaml", "data", True, nonempty=True)
    check_file(checks, KI_DIR / "dag.yaml", "data", True, nonempty=True)
    check_file(checks, KI_DIR / "SKILL.md", "data", True, nonempty=True)
    check_file(checks, DIAGNOSTICS, "data", True, nonempty=True)
    check_file(checks, KI_DIR / "docs" / "format_spec.yaml", "data", False, nonempty=True)

    check_dir(checks, KI_DIR / "tools", "data", True, nonempty=True)
    check_tool_syntax(checks)

    check_file(checks, binary, "binary", True, executable=True, nonempty=True)
    check_dir(checks, run_dir, "data", True, nonempty=True)
    for name in ["lnd_in", "drv_in", "datm_in", "cpl_modelio.nml", "lnd_modelio.nml"]:
        check_file(checks, run_dir / name, "data", True, nonempty=True)
    check_binary_smoke_start(checks, binary)

    for module in ["numpy", "pandas", "netCDF4", "xarray", "yaml"]:
        check_python_import(checks, module, critical=True)

    print()
    passed = sum(1 for c in checks if c["status"] == "pass")
    failed = len(checks) - passed
    print(f"Results: {passed} passed, {failed} failed")
    if failed:
        print(f"Failures should be recovered via {DIAGNOSTICS}.")
    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
