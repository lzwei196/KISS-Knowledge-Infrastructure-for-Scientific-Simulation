#!/usr/bin/env python3
"""Preflight check for the HexWatershed Knowledge Infrastructure."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


MODEL_ID = "HexWatershed"
KI_DIR = Path(__file__).resolve().parent
PYTHON_ENV = Path("KISSPATH_PYTHON_ENV/bin/python")
DIAGNOSTICS = KI_DIR / "diagnostics" / "triplets.yaml"
START_TIMEOUT_SECONDS = 5


def emit_report(checks):
    print(
        "PREFLIGHT_REPORT="
        + json.dumps({"model_id": MODEL_ID, "checks": checks}, separators=(",", ":"))
    )
    failed_critical = any(
        check["critical"] and check["status"] != "pass" for check in checks
    )
    sys.exit(1 if failed_critical else 0)


def add_check(checks, kind, subject, critical, passed, fix=""):
    status = "pass" if passed else "fail"
    check = {
        "kind": kind,
        "subject": str(subject),
        "critical": bool(critical),
        "status": status,
        "fix": "" if passed else fix,
    }
    checks.append(check)
    label = "OK" if passed else ("FAIL" if critical else "WARN")
    print(f"  {label:<5} {kind}: {subject}")
    if not passed and fix:
        print(f"        Fix: {fix}")
    return passed


def manifest_binary_path():
    manifest = KI_DIR / "knowledge_infrastructure.yaml"
    if not manifest.is_file():
        return None

    in_binary = False
    for raw_line in manifest.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if stripped == "binary:":
            in_binary = True
            continue
        if in_binary and stripped.startswith("path:"):
            value = stripped.split(":", 1)[1].strip().strip("'\"")
            return Path(value) if value else None
        if in_binary and stripped and not raw_line.startswith((" ", "\t")):
            in_binary = False
    return None


def discover_binary():
    from_manifest = manifest_binary_path()
    if from_manifest is not None:
        return from_manifest

    from_path = shutil.which("hexwatershed")
    if from_path:
        return Path(from_path)

    return Path(
        "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/"
        "HexWatershed/source/repo/build/hexwatershed"
    )


def check_file(checks, path, label, critical=True, executable=False):
    path = Path(path)
    subject = path.resolve() if path.exists() else path
    if not path.is_file():
        return add_check(
            checks,
            "data",
            subject,
            critical,
            False,
            f"Restore {label}; check {DIAGNOSTICS} for recovery guidance.",
        )
    if executable and not os.access(path, os.X_OK):
        return add_check(
            checks,
            "binary",
            subject,
            critical,
            False,
            f"Run chmod +x {path}; check {DIAGNOSTICS} if execution still fails.",
        )

    kind = "binary" if executable else "data"
    return add_check(checks, kind, subject, critical, True)


def check_python_env(checks):
    if not PYTHON_ENV.is_file():
        return add_check(
            checks,
            "import",
            PYTHON_ENV,
            True,
            False,
            "Restore KISSPATH_PYTHON_ENV; do not use bare python3 for KI import checks.",
        )
    if not os.access(PYTHON_ENV, os.X_OK):
        return add_check(
            checks,
            "import",
            PYTHON_ENV,
            True,
            False,
            f"Run chmod +x {PYTHON_ENV}; check {DIAGNOSTICS} if the environment is damaged.",
        )
    return add_check(checks, "import", PYTHON_ENV, True, True)


def check_import(checks, module, critical, fix):
    subject = f"{PYTHON_ENV} import {module}"
    if not PYTHON_ENV.is_file():
        return add_check(checks, "import", subject, critical, False, fix)

    code = (
        "import importlib.util, sys; "
        f"sys.exit(0 if importlib.util.find_spec({module!r}) else 1)"
    )
    proc = subprocess.run(
        [str(PYTHON_ENV), "-c", code],
        text=True,
        capture_output=True,
        timeout=START_TIMEOUT_SECONDS,
    )
    return add_check(checks, "import", subject, critical, proc.returncode == 0, fix)


def check_tools_compile(checks):
    tools = [
        KI_DIR / "tools" / "flowline_converter.py",
        KI_DIR / "tools" / "mesh_converter.py",
        KI_DIR / "tools" / "output_parser.py",
        KI_DIR / "tools" / "run_hexwatershed.py",
    ]

    for tool in tools:
        check_file(checks, tool, tool.name, critical=True)

    if not PYTHON_ENV.is_file():
        return

    proc = subprocess.run(
        [str(PYTHON_ENV), "-m", "py_compile", *[str(tool) for tool in tools]],
        text=True,
        capture_output=True,
        timeout=START_TIMEOUT_SECONDS,
        cwd=str(KI_DIR),
    )
    fix = (
        "Fix Python syntax/import-time issues in tools/*.py using the HydroCraft "
        f"environment; check {DIAGNOSTICS} for known failures."
    )
    add_check(
        checks,
        "import",
        f"{PYTHON_ENV} -m py_compile tools/*.py",
        True,
        proc.returncode == 0,
        fix,
    )


def check_binary_starts(checks, binary):
    binary = Path(binary)
    subject = binary.resolve() if binary.exists() else binary
    if not binary.is_file() or not os.access(binary, os.X_OK):
        add_check(
            checks,
            "run",
            subject,
            True,
            False,
            f"Restore executable binary first; check {DIAGNOSTICS}.",
        )
        return

    try:
        proc = subprocess.run(
            [str(binary)],
            text=True,
            capture_output=True,
            timeout=START_TIMEOUT_SECONDS,
            cwd=str(binary.parent),
        )
    except subprocess.TimeoutExpired:
        add_check(
            checks,
            "run",
            subject,
            True,
            False,
            f"Binary did not return within {START_TIMEOUT_SECONDS}s with no config; check {DIAGNOSTICS}.",
        )
        return
    except OSError as exc:
        add_check(
            checks,
            "run",
            subject,
            True,
            False,
            f"Binary could not be started ({exc}); check shared libraries and {DIAGNOSTICS}.",
        )
        return

    output = (proc.stdout or "") + (proc.stderr or "")
    starts = proc.returncode >= 0 and (
        proc.returncode == 0
        or "configuration file" in output.lower()
        or "no arguments" in output.lower()
    )
    add_check(
        checks,
        "run",
        subject,
        True,
        starts,
        f"Run the binary manually with a valid config and inspect {DIAGNOSTICS}.",
    )


def main():
    checks = []
    print("=" * 60)
    print(f"  PREFLIGHT CHECK: {MODEL_ID}")
    print("=" * 60)

    binary = discover_binary()
    check_file(checks, binary, "HexWatershed executable", critical=True, executable=True)
    check_binary_starts(checks, binary)

    check_python_env(checks)
    check_tools_compile(checks)
    check_import(
        checks,
        "osgeo",
        critical=False,
        fix=(
            "Install GDAL/OGR in KISSPATH_PYTHON_ENV for "
            "GeoTIFF and shapefile support; see diagnostics/triplets.yaml."
        ),
    )
    check_import(
        checks,
        "pyflowline",
        critical=False,
        fix=(
            "Install pyflowline in KISSPATH_PYTHON_ENV when "
            "generating production meshes; see diagnostics/triplets.yaml."
        ),
    )

    required_files = [
        KI_DIR / "SKILL.md",
        KI_DIR / "knowledge_infrastructure.yaml",
        KI_DIR / "dag.yaml",
        DIAGNOSTICS,
        KI_DIR / "docs" / "format_spec.yaml",
    ]
    for path in required_files:
        check_file(checks, path, path.relative_to(KI_DIR), critical=(path == DIAGNOSTICS))

    passed = sum(1 for check in checks if check["status"] == "pass")
    failed = len(checks) - passed
    print(f"\n  Results: {passed} passed, {failed} failed")
    if failed:
        print(f"  Recovery: inspect {DIAGNOSTICS} for matching diagnostics.")

    emit_report(checks)


if __name__ == "__main__":
    main()
