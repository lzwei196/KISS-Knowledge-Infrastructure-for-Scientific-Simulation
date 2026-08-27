#!/usr/bin/env python3
"""Preflight checks for the MONICA knowledge infrastructure."""

import json
import os
import subprocess
import sys


MODEL_ID = "MONICA"
KI_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.abspath(os.path.join(KI_DIR, os.pardir))
TOOLS_DIR = os.path.join(KI_DIR, "tools")
DIAGNOSTICS = os.path.join(KI_DIR, "diagnostics", "triplets.yaml")
MONICA_BINARY = os.path.join(MODEL_DIR, "bin", "monica-run")
PARAMETERS_DIR = os.path.join(MODEL_DIR, "source", "monica-parameters")
HYDROCRAFT_PYTHON = "KISSPATH_PYTHON_ENV/bin/python"


def make_check(kind, subject, critical, status, fix):
    return {
        "kind": kind,
        "subject": subject,
        "critical": bool(critical),
        "status": status,
        "fix": fix,
    }


def report_status(label, status, subject, fix):
    if status == "pass":
        print(f"  OK    {label}: {subject}")
    else:
        print(f"  FAIL  {label}: {subject}")
        print(f"         Fix: {fix}")


def check_dir(path, label, critical=True, require_nonempty=True):
    subject = os.path.realpath(path)
    if not os.path.isdir(path):
        fix = f"Restore {path}; then consult {DIAGNOSTICS} if model setup still fails."
        report_status(label, "fail", subject, fix)
        return make_check("data", subject, critical, "fail", fix)
    if require_nonempty and not os.listdir(path):
        fix = f"Populate {path}; then consult {DIAGNOSTICS} if model setup still fails."
        report_status(label, "fail", subject, fix)
        return make_check("data", subject, critical, "fail", fix)
    report_status(label, "pass", subject, "")
    return make_check("data", subject, critical, "pass", "")


def check_file(path, label, critical=True, executable=False):
    subject = os.path.realpath(path)
    if not os.path.isfile(path):
        fix = f"Restore {path}; then consult {DIAGNOSTICS} for recovery steps."
        report_status(label, "fail", subject, fix)
        return make_check("binary" if executable else "data", subject, critical, "fail", fix)
    if executable and not os.access(path, os.X_OK):
        fix = f"Run chmod +x {path}; then consult {DIAGNOSTICS} if execution still fails."
        report_status(label, "fail", subject, fix)
        return make_check("binary", subject, critical, "fail", fix)
    report_status(label, "pass", subject, "")
    return make_check("binary" if executable else "data", subject, critical, "pass", "")


def check_binary_starts(path):
    subject = os.path.realpath(path)
    if not (os.path.isfile(path) and os.access(path, os.X_OK)):
        fix = f"Fix the MONICA executable at {path}; then consult {DIAGNOSTICS}."
        report_status("MONICA binary startup", "fail", subject, fix)
        return make_check("run", subject, True, "fail", fix)

    try:
        proc = subprocess.run(
            [path, "--help"],
            cwd=KI_DIR,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception as exc:
        fix = f"Ensure {path} can start and shared libraries are available; consult {DIAGNOSTICS}."
        report_status("MONICA binary startup", "fail", f"{subject}: {exc}", fix)
        return make_check("run", subject, True, "fail", fix)

    if proc.returncode != 0 or "monica-run" not in (proc.stdout + proc.stderr):
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        detail_text = detail[0] if detail else f"exit code {proc.returncode}"
        fix = f"Repair the MONICA binary startup path/dependencies; consult {DIAGNOSTICS}."
        report_status("MONICA binary startup", "fail", f"{subject}: {detail_text}", fix)
        return make_check("run", subject, True, "fail", fix)

    report_status("MONICA binary startup", "pass", subject, "")
    return make_check("run", subject, True, "pass", "")


def check_parameters_dir(path):
    checks = [check_dir(path, "MONICA_PARAMETERS directory", critical=True)]
    for subdir in ["crops", "crop-residues", "mineral-fertilisers"]:
        checks.append(check_dir(os.path.join(path, subdir), f"parameter subdirectory {subdir}", critical=True))
    return checks


def check_tool_import(module):
    subject = module
    if not os.path.isfile(HYDROCRAFT_PYTHON):
        fix = f"Restore HydroCraft Python interpreter at {HYDROCRAFT_PYTHON}; consult {DIAGNOSTICS}."
        report_status(f"import {module}", "fail", subject, fix)
        return make_check("import", subject, True, "fail", fix)

    code = f"import {module}"
    env = os.environ.copy()
    env["PYTHONPATH"] = KI_DIR + os.pathsep + env.get("PYTHONPATH", "")
    try:
        proc = subprocess.run(
            [HYDROCRAFT_PYTHON, "-c", code],
            cwd=KI_DIR,
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception as exc:
        fix = f"Fix HydroCraft Python imports for {module}; consult {DIAGNOSTICS}."
        report_status(f"import {module}", "fail", f"{subject}: {exc}", fix)
        return make_check("import", subject, True, "fail", fix)

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        detail_text = detail[-1] if detail else f"exit code {proc.returncode}"
        fix = f"Install/fix dependencies in {HYDROCRAFT_PYTHON} for {module}; consult {DIAGNOSTICS}."
        report_status(f"import {module}", "fail", f"{subject}: {detail_text}", fix)
        return make_check("import", subject, True, "fail", fix)

    report_status(f"import {module}", "pass", subject, "")
    return make_check("import", subject, True, "pass", "")


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}, sort_keys=True))
    critical_failed = any(c["status"] != "pass" and c.get("critical") for c in checks)
    sys.exit(1 if critical_failed else 0)


def main():
    checks = []
    print(f"{' PREFLIGHT: MONICA ':=^60}")
    print()

    checks.append(check_dir(TOOLS_DIR, "KI tools directory", critical=True))

    for script in [
        "convert_climate_to_monica.py",
        "convert_soil_to_monica.py",
        "parse_monica_output.py",
        "run_monica.py",
    ]:
        checks.append(check_file(os.path.join(TOOLS_DIR, script), f"tool script {script}", critical=True))

    checks.append(check_file(MONICA_BINARY, "MONICA binary", critical=True, executable=True))
    checks.append(check_binary_starts(MONICA_BINARY))
    checks.extend(check_parameters_dir(PARAMETERS_DIR))

    for module in [
        "tools.convert_climate_to_monica",
        "tools.convert_soil_to_monica",
        "tools.parse_monica_output",
        "tools.run_monica",
    ]:
        checks.append(check_tool_import(module))

    checks.append(check_file(DIAGNOSTICS, "diagnostic triplets", critical=False))

    passed = sum(1 for check in checks if check["status"] == "pass")
    failed = len(checks) - passed
    print(f"\n  Results: {passed} passed, {failed} failed")
    if failed:
        print(f"  STATUS: PREFLIGHT FAILED - consult {DIAGNOSTICS}")
    else:
        print("  STATUS: PREFLIGHT PASSED - safe to proceed with MONICA execution")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
