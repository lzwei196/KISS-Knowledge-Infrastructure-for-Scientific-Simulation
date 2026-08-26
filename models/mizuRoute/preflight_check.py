#!/usr/bin/env python3
"""
Preflight check for the mizuRoute Knowledge Infrastructure.

This script verifies the executable, Python runtime dependencies, KI metadata,
tool scripts, and diagnostics before a run attempts model execution.
"""

import json
import os
import subprocess
import sys
from pathlib import Path


MODEL_ID = "mizuRoute"
HYDROCRAFT_ROOT = Path(os.environ.get("HYDROCRAFT_ROOT", "KISSPATH_ROOT"))
KI_DIR = Path(__file__).resolve().parent
PYTHON = HYDROCRAFT_ROOT / "python_env" / "bin" / "python"
MIZUROUTE_EXE = (
    HYDROCRAFT_ROOT
    / "model"
    / "mizuRoute"
    / "mizuRoute-main"
    / "route"
    / "bin"
    / "mizuroute.exe"
)
MIZUROUTE_SOURCE = HYDROCRAFT_ROOT / "model" / "mizuRoute" / "mizuRoute-main"
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"

TOOL_FILES = [
    KI_DIR / "tools" / "s1_network" / "build_network_topology.py",
    KI_DIR / "tools" / "s2_remap" / "create_remap_weights.py",
    KI_DIR / "tools" / "s3_runoff" / "convert_vic_runoff.py",
    KI_DIR / "tools" / "s4_control" / "generate_control_file.py",
    KI_DIR / "tools" / "s5_execution" / "run_mizuroute.py",
    KI_DIR / "tools" / "s6_postprocess" / "extract_discharge.py",
    KI_DIR / "tools" / "s6_postprocess" / "compare_routing_methods.py",
]

METADATA_FILES = [
    KI_DIR / "SKILL.md",
    KI_DIR / "knowledge_infrastructure.yaml",
    KI_DIR / "dag.yaml",
    KI_DIR / "docs" / "format_spec.yaml",
    TRIPLETS,
]

PYTHON_IMPORTS = [
    "netCDF4",
    "numpy",
    "geopandas",
    "shapely",
    "rasterio",
    "scipy",
    "whitebox",
    "ki_tools_common.units",
]


def make_check(kind, subject, critical, status, fix=""):
    return {
        "kind": kind,
        "subject": str(subject),
        "critical": bool(critical),
        "status": status,
        "fix": fix,
    }


def add_file_check(checks, path, label, critical=True, executable=False):
    subject = os.path.realpath(path)
    if not Path(path).is_file():
        checks.append(
            make_check(
                "binary" if executable else "data",
                subject,
                critical,
                "fail",
                f"Restore {label} at {path}; check {TRIPLETS} for recovery steps.",
            )
        )
        print(f"FAIL {label}: not found at {path}")
        return

    if executable and not os.access(path, os.X_OK):
        checks.append(
            make_check(
                "binary",
                subject,
                critical,
                "fail",
                f"Run chmod +x {path}; check {TRIPLETS} if the binary was rebuilt.",
            )
        )
        print(f"FAIL {label}: exists but is not executable: {path}")
        return

    checks.append(make_check("binary" if executable else "data", subject, critical, "pass"))
    print(f"OK   {label}: {path}")


def add_dir_check(checks, path, label, critical=True, require_nonempty=True):
    subject = os.path.realpath(path)
    p = Path(path)
    if not p.is_dir():
        checks.append(
            make_check(
                "data",
                subject,
                critical,
                "fail",
                f"Restore {label} at {path}; check {TRIPLETS} for recovery steps.",
            )
        )
        print(f"FAIL {label}: directory not found at {path}")
        return

    if require_nonempty and not any(p.iterdir()):
        checks.append(
            make_check(
                "data",
                subject,
                critical,
                "fail",
                f"Populate {label} at {path}; check {TRIPLETS} for expected layout.",
            )
        )
        print(f"FAIL {label}: directory is empty at {path}")
        return

    checks.append(make_check("data", subject, critical, "pass"))
    print(f"OK   {label}: {path}")


def add_python_import_check(checks, module):
    subject = f"{PYTHON} -c import {module}"
    if not PYTHON.is_file() or not os.access(PYTHON, os.X_OK):
        checks.append(
            make_check(
                "import",
                subject,
                True,
                "fail",
                f"Restore the HydroCraft Python interpreter at {PYTHON}; check {TRIPLETS}.",
            )
        )
        print(f"FAIL import {module}: HydroCraft Python is unavailable")
        return

    result = subprocess.run(
        [str(PYTHON), "-c", f"import {module}"],
        capture_output=True,
        text=True,
        timeout=20,
    )
    if result.returncode == 0:
        checks.append(make_check("import", subject, True, "pass"))
        print(f"OK   import {module}: {PYTHON}")
        return

    detail = (result.stderr or result.stdout or "").strip().splitlines()
    message = detail[-1] if detail else f"return code {result.returncode}"
    checks.append(
        make_check(
            "import",
            subject,
            True,
            "fail",
            f"Install or repair Python dependency '{module}' in {PYTHON}; check {TRIPLETS}. Error: {message}",
        )
    )
    print(f"FAIL import {module}: {message}")


def add_binary_start_check(checks):
    subject = os.path.realpath(MIZUROUTE_EXE)
    if not MIZUROUTE_EXE.is_file() or not os.access(MIZUROUTE_EXE, os.X_OK):
        checks.append(
            make_check(
                "run",
                subject,
                True,
                "fail",
                f"Restore executable permissions for {MIZUROUTE_EXE}; check {TRIPLETS}.",
            )
        )
        print("FAIL mizuRoute startup: executable missing or not executable")
        return

    try:
        result = subprocess.run(
            [str(MIZUROUTE_EXE)],
            capture_output=True,
            text=True,
            timeout=5,
            cwd=str(KI_DIR),
        )
    except subprocess.TimeoutExpired:
        checks.append(
            make_check(
                "run",
                subject,
                True,
                "fail",
                f"{MIZUROUTE_EXE} did not return from the no-control-file startup check within 5 seconds; check {TRIPLETS}.",
            )
        )
        print("FAIL mizuRoute startup: timed out")
        return
    except OSError as exc:
        checks.append(
            make_check(
                "run",
                subject,
                True,
                "fail",
                f"Fix the executable or its loader dependencies for {MIZUROUTE_EXE}; check {TRIPLETS}. Error: {exc}",
            )
        )
        print(f"FAIL mizuRoute startup: {exc}")
        return

    output = f"{result.stdout}\n{result.stderr}"
    loader_failed = (
        "error while loading shared libraries" in output
        or "No such file or directory" in output
        or result.returncode in (126, 127)
    )
    expected_usage_failure = "control file" in output.lower()
    if loader_failed or not expected_usage_failure:
        checks.append(
            make_check(
                "run",
                subject,
                True,
                "fail",
                f"Run {MIZUROUTE_EXE} manually and repair startup/runtime libraries; check {TRIPLETS}.",
            )
        )
        print("FAIL mizuRoute startup: executable did not reach expected control-file validation")
        return

    checks.append(make_check("run", subject, True, "pass"))
    print("OK   mizuRoute startup: executable launches and requests a control file")


def add_ldd_check(checks):
    subject = os.path.realpath(MIZUROUTE_EXE)
    if not MIZUROUTE_EXE.is_file():
        checks.append(
            make_check(
                "binary",
                subject,
                True,
                "fail",
                f"Restore {MIZUROUTE_EXE}; check {TRIPLETS}.",
            )
        )
        print("FAIL mizuRoute libraries: executable missing")
        return

    result = subprocess.run(["ldd", str(MIZUROUTE_EXE)], capture_output=True, text=True, timeout=10)
    output = f"{result.stdout}\n{result.stderr}"
    if result.returncode != 0 or "not found" in output:
        checks.append(
            make_check(
                "binary",
                subject,
                True,
                "fail",
                f"Install missing shared libraries for {MIZUROUTE_EXE}; check {TRIPLETS}.",
            )
        )
        print("FAIL mizuRoute libraries: missing shared library")
        return

    checks.append(make_check("binary", subject, True, "pass"))
    print("OK   mizuRoute libraries: dynamic libraries resolve")


def add_tool_compile_check(checks):
    subject = " ".join(str(path.relative_to(KI_DIR)) for path in TOOL_FILES)
    missing = [path for path in TOOL_FILES if not path.is_file()]
    if missing:
        checks.append(
            make_check(
                "data",
                subject,
                True,
                "fail",
                f"Restore missing tool scripts: {', '.join(str(p) for p in missing)}; check {TRIPLETS}.",
            )
        )
        print(f"FAIL KI tools: {len(missing)} script(s) missing")
        return

    cmd = [str(PYTHON), "-m", "py_compile"] + [str(path) for path in TOOL_FILES]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=str(KI_DIR))
    if result.returncode == 0:
        checks.append(make_check("import", subject, True, "pass"))
        print(f"OK   KI tools: {len(TOOL_FILES)} scripts compile with HydroCraft Python")
        return

    detail = (result.stderr or result.stdout or "").strip().splitlines()
    message = detail[-1] if detail else f"return code {result.returncode}"
    checks.append(
        make_check(
            "import",
            subject,
            True,
            "fail",
            f"Fix KI tool syntax/import-path compile errors; check {TRIPLETS}. Error: {message}",
        )
    )
    print(f"FAIL KI tools: {message}")


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}, sort_keys=True))
    critical_failed = any(c["status"] != "pass" and c.get("critical") for c in checks)
    sys.exit(1 if critical_failed else 0)


def main():
    checks = []
    print("=" * 60)
    print(f"  PREFLIGHT CHECK: {MODEL_ID}")
    print("=" * 60)

    add_file_check(checks, MIZUROUTE_EXE, "mizuRoute executable", critical=True, executable=True)
    add_ldd_check(checks)
    add_binary_start_check(checks)
    add_dir_check(checks, MIZUROUTE_SOURCE, "mizuRoute source tree", critical=True)
    add_file_check(checks, PYTHON, "HydroCraft Python interpreter", critical=True, executable=True)

    for module in PYTHON_IMPORTS:
        add_python_import_check(checks, module)

    for path in METADATA_FILES:
        add_file_check(checks, path, path.relative_to(KI_DIR), critical=True)

    add_tool_compile_check(checks)

    failures = [c for c in checks if c["status"] != "pass" and c.get("critical")]
    if failures:
        print()
        print("Blocking fixes:")
        for check in failures:
            print(f"  - {check['subject']}: {check['fix']}")
    else:
        print()
        print(f"Preflight passed: {len(checks)} checks.")
        print(f"Diagnostics for recovery: {TRIPLETS}")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
