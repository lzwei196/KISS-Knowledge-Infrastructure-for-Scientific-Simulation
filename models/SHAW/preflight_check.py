#!/usr/bin/env python3
"""
Preflight check for SHAW v3.03.

Run this before model execution. It verifies the compiled SHAW executables,
the Python environment used by HydroCraft tooling, the KI metadata/tool files,
and baseline data paths needed by the workflows.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


MODEL_ID = "SHAW"
HYDROCRAFT_ROOT = Path("KISSPATH_ROOT")
KI_DIR = Path(__file__).resolve().parent
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"
PYTHON_ENV = HYDROCRAFT_ROOT / "python_env" / "bin" / "python"

# Canonical binary path projected into knowledge_infrastructure.yaml from the
# models DB. The report subject for this check is its realpath for drift checks.
MANIFEST_BINARY = HYDROCRAFT_ROOT / "model" / "shaw" / "shaw"

# The execution helper defaults to this symlink, so verify it too.
TOOL_DEFAULT_BINARY = HYDROCRAFT_ROOT / "model" / "shaw" / "shaw303"

SHAW_DIST_DIR = HYDROCRAFT_ROOT / "model" / "shaw" / "Shaw303"

checks = []


def add_check(kind, subject, critical, status, fix=""):
    checks.append(
        {
            "kind": kind,
            "subject": str(subject),
            "critical": bool(critical),
            "status": status,
            "fix": fix,
        }
    )


def print_result(status, label, subject, fix=""):
    prefix = "OK" if status == "pass" else "FAIL"
    print(f"  {prefix:<5} {label}: {subject}")
    if status != "pass" and fix:
        print(f"         Fix: {fix}")


def realpath(path):
    return os.path.realpath(str(path))


def check_file(path, label, *, kind="data", critical=True, executable=False, nonempty=False):
    subject = realpath(path) if executable else path
    fix = f"Restore {path}; see {TRIPLETS} for recovery guidance."
    status = "pass"
    if not path.is_file():
        status = "fail"
        fix = f"Create or restore missing file {path}; see {TRIPLETS}."
    elif nonempty and path.stat().st_size == 0:
        status = "fail"
        fix = f"Replace empty file {path} with a valid SHAW/KI file; see {TRIPLETS}."
    elif executable and not os.access(path, os.X_OK):
        status = "fail"
        fix = f"Run chmod +x {path} or rebuild SHAW with {HYDROCRAFT_ROOT}/model/shaw/compile.sh; see {TRIPLETS}."
    print_result(status, label, subject, fix)
    add_check(kind, subject, critical, status, "" if status == "pass" else fix)
    return status == "pass"


def check_dir(path, label, *, critical=True, nonempty=True):
    fix = f"Restore directory {path}; see {TRIPLETS} for recovery guidance."
    status = "pass"
    detail = path
    if not path.is_dir():
        status = "fail"
        fix = f"Create or restore missing directory {path}; see {TRIPLETS}."
    elif nonempty and not any(path.iterdir()):
        status = "fail"
        fix = f"Populate empty directory {path}; see {TRIPLETS}."
    else:
        try:
            detail = f"{path} ({len(os.listdir(path))} items)"
        except OSError:
            detail = path
    print_result(status, label, detail, fix)
    add_check("data", path, critical, status, "" if status == "pass" else fix)
    return status == "pass"


def check_binary_search(name, label):
    """Keep the legacy PATH/common-location executable search as a noncritical check."""
    found = shutil.which(name)
    if found:
        subject = realpath(found)
        print_result("pass", label, subject)
        add_check("binary", subject, False, "pass", "")
        return True

    # The old preflight recursively walked KISSPATH_HOME and the full model
    # tree, which can hang the gate on large shared volumes. Keep the intent
    # by checking the real SHAW locations documented by this KI.
    candidates = [
        HYDROCRAFT_ROOT / "model" / "shaw" / name,
        HYDROCRAFT_ROOT / "model" / "shaw" / "shaw303",
        HYDROCRAFT_ROOT / "model" / "shaw" / "Shaw303" / "shaw303",
        Path("/usr/local/bin") / name,
    ]
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            subject = realpath(candidate)
            print_result("pass", label, subject)
            add_check("binary", subject, False, "pass", "")
            return True

    fix = f"Check SKILL.md and restore the SHAW executable; see {TRIPLETS}."
    print_result("fail", label, f"binary '{name}' not found", fix)
    add_check("binary", name, False, "fail", fix)
    return False


def check_binary_starts(path, label):
    subject = realpath(path)
    fix = f"Rebuild or repair SHAW binary; then check startup failures in {TRIPLETS}."
    if not path.is_file() or not os.access(path, os.X_OK):
        print_result("fail", label, subject, fix)
        add_check("run", subject, True, "fail", fix)
        return False

    try:
        result = subprocess.run(
            [str(path)],
            input="",
            cwd=str(path.parent),
            text=True,
            capture_output=True,
            timeout=3,
        )
    except subprocess.TimeoutExpired:
        fix = f"SHAW hung during startup; inspect stdin handling and {TRIPLETS}."
        print_result("fail", label, subject, fix)
        add_check("run", subject, True, "fail", fix)
        return False
    except OSError as exc:
        fix = f"Cannot execute {path}: {exc}; see {TRIPLETS}."
        print_result("fail", label, subject, fix)
        add_check("run", subject, True, "fail", fix)
        return False

    output = (result.stdout or "") + (result.stderr or "")
    ok = "Simultaneous Heat And Water" in output and "Enter the file" in output
    status = "pass" if ok else "fail"
    if not ok:
        fix = f"Expected SHAW banner/prompt not seen; rebuild with compile.sh and review {TRIPLETS}."
    print_result(status, label, f"{subject} (startup return code {result.returncode})", fix)
    add_check("run", subject, True, status, "" if status == "pass" else fix)
    return ok


def check_import_with_python(module, label):
    subject = f"{PYTHON_ENV}: import {module}"
    fix = f"Install {module.split('.')[0]} into {PYTHON_ENV}; see {TRIPLETS}."
    if not PYTHON_ENV.is_file():
        status = "fail"
        fix = f"Restore HydroCraft Python interpreter at {PYTHON_ENV}; see {TRIPLETS}."
    else:
        result = subprocess.run(
            [str(PYTHON_ENV), "-c", f"import {module}"],
            cwd=str(KI_DIR),
            text=True,
            capture_output=True,
            timeout=10,
        )
        status = "pass" if result.returncode == 0 else "fail"
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip().splitlines()
            if detail:
                fix = f"{fix} Import error: {detail[-1]}"
    print_result(status, label, subject, fix)
    add_check("import", subject, True, status, "" if status == "pass" else fix)
    return status == "pass"


def check_common_data():
    """Preserve the legacy HydroCraft data probes as noncritical checks."""
    common = [
        (HYDROCRAFT_ROOT / "data" / "obs", "Observation data"),
        (Path("KISSPATH_FORCING"), "Forcing data"),
        (HYDROCRAFT_ROOT / "data" / "dem", "DEM data"),
        (HYDROCRAFT_ROOT / "data" / "soil", "Soil data"),
    ]
    for path, label in common:
        check_dir(path, label, critical=False, nonempty=False)


def emit_report(model_id, report_checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": report_checks}, sort_keys=True))
    sys.exit(0 if all(c["status"] == "pass" or not c.get("critical") for c in report_checks) else 1)


def main():
    print("=" * 60)
    print(f"  PREFLIGHT CHECK: {MODEL_ID}")
    print("=" * 60)
    print()

    print("Executable checks")
    check_file(MANIFEST_BINARY, "SHAW manifest binary", kind="binary", critical=True, executable=True, nonempty=True)
    check_binary_starts(MANIFEST_BINARY, "SHAW manifest binary startup")
    check_file(TOOL_DEFAULT_BINARY, "SHAW tool default binary", kind="binary", critical=True, executable=True, nonempty=True)
    check_binary_search("shaw", "SHAW binary in PATH/common locations")
    print()

    print("Python import checks")
    check_file(PYTHON_ENV, "HydroCraft Python interpreter", kind="binary", critical=True, executable=True)
    for module in [
        "numpy",
        "ki_tools_common",
        "ki_tools_common.soil_utils",
        "ki_tools_common.load_forcing",
    ]:
        check_import_with_python(module, module)
    print()

    print("KI file checks")
    for path, label in [
        (KI_DIR / "SKILL.md", "SKILL.md"),
        (KI_DIR / "knowledge_infrastructure.yaml", "knowledge_infrastructure.yaml"),
        (KI_DIR / "dag.yaml", "dag.yaml"),
        (TRIPLETS, "diagnostics/triplets.yaml"),
        (KI_DIR / "docs" / "format_spec.yaml", "docs/format_spec.yaml"),
    ]:
        check_file(path, label, critical=True, nonempty=True)
    print()

    print("KI tool checks")
    tool_files = [
        "s1_site_setup/tools/create_site_file.py",
        "s2_weather_prep/tools/convert_forcing_to_shaw.py",
        "s3_plant_config/tools/create_plant_file.py",
        "s4_initial_conditions/tools/set_initial_conditions.py",
        "s5_snow_residue_config/tools/configure_residue.py",
        "s5_snow_residue_config/tools/configure_snow_params.py",
        "s6_execution/tools/parse_shaw_output.py",
        "s6_execution/tools/plot_shaw_profiles.py",
        "s6_execution/tools/run_shaw.py",
        "s6_execution/tools/shaw_frost_analysis.py",
        "s6_execution/tools/validate_shaw_inputs.py",
        "s7_vic_coupling/tools/vic_to_shaw_soil.py",
        "tools/s1_site_setup/setup_shaw_from_template.py",
    ]
    for relpath in tool_files:
        check_file(KI_DIR / relpath, relpath, critical=True, nonempty=True)
    print()

    print("SHAW distribution input checks")
    check_dir(SHAW_DIST_DIR, "SHAW v3.03 distribution", critical=True)
    for filename in ["Trial.303.inp", "Trial.30.sit", "Trial.30.wea", "Trial.moi", "Trial.tem"]:
        check_file(SHAW_DIST_DIR / filename, f"SHAW example {filename}", critical=True, nonempty=True)
    print()

    print("Common HydroCraft data checks")
    check_common_data()
    print()

    if TRIPLETS.is_file():
        print(f"  INFO  Diagnostic triplets available at: {TRIPLETS}")
        print("        If the model fails, check triplets FIRST for known fixes.")
    else:
        print(f"  FAIL  Diagnostic triplets missing at: {TRIPLETS}")

    passed = sum(1 for c in checks if c["status"] == "pass")
    failed = sum(1 for c in checks if c["status"] != "pass")
    critical_failed = sum(1 for c in checks if c["status"] != "pass" and c.get("critical"))
    print()
    print(f"  Results: {passed} passed, {failed} failed ({critical_failed} critical failed)")
    if critical_failed:
        print(f"  STATUS: PREFLIGHT FAILED - fix critical issues above before running; see {TRIPLETS}.")
    else:
        print("  STATUS: PREFLIGHT PASSED - safe to proceed with model execution.")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
