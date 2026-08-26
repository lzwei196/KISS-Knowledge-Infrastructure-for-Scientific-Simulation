#!/usr/bin/env python3
"""Contract preflight check for the Amanzi_ATS KI."""

import json
import os
import shutil
import subprocess
import sys


MODEL_ID = "Amanzi_ATS"
KI_DIR = os.path.dirname(os.path.abspath(__file__))
PYTHON_ENV = "KISSPATH_PYTHON_ENV/bin/python"
DIAGNOSTICS = os.path.join(KI_DIR, "diagnostics", "triplets.yaml")
REGISTERED_EXECUTABLE = os.path.join(KI_DIR, "tools", "run_amanzi.py")


def recovery_hint(detail):
    return f"{detail}; check diagnostics/triplets.yaml for recovery guidance"


def status_line(status, label, subject):
    prefix = "OK" if status == "pass" else "FAIL"
    print(f"  {prefix:<5} {label}: {subject}")


def add_check(checks, kind, subject, critical, status, fix=""):
    check = {
        "kind": kind,
        "subject": subject,
        "critical": bool(critical),
        "status": status,
        "fix": "" if status == "pass" else fix,
    }
    checks.append(check)
    return check


def check_file(checks, path, label, critical=True, executable=False):
    subject = os.path.realpath(path)
    if not os.path.isfile(path):
        fix = recovery_hint(f"restore required file at {path}")
        status_line("fail", label, f"NOT FOUND at {path}")
        add_check(checks, "data", subject, critical, "fail", fix)
        return False
    if executable and not os.access(path, os.X_OK):
        fix = recovery_hint(f"make executable with chmod +x {path}")
        status_line("fail", label, f"exists but is not executable: {path}")
        add_check(checks, "binary", subject, critical, "fail", fix)
        return False
    status_line("pass", label, subject)
    add_check(checks, "binary" if executable else "data", subject, critical, "pass")
    return True


def check_dir(checks, path, label, critical=True, nonempty=True):
    subject = os.path.realpath(path)
    if not os.path.isdir(path):
        fix = recovery_hint(f"restore required directory at {path}")
        status_line("fail", label, f"NOT FOUND at {path}")
        add_check(checks, "data", subject, critical, "fail", fix)
        return False
    entries = os.listdir(path)
    if nonempty and not entries:
        fix = recovery_hint(f"populate required directory {path}")
        status_line("fail", label, f"empty directory: {path}")
        add_check(checks, "data", subject, critical, "fail", fix)
        return False
    status_line("pass", label, f"{subject} ({len(entries)} items)")
    add_check(checks, "data", subject, critical, "pass")
    return True


def check_import(checks, module, critical=True):
    python = PYTHON_ENV if os.path.exists(PYTHON_ENV) else sys.executable
    subject = f"{os.path.realpath(python)} import {module}"
    proc = subprocess.run(
        [python, "-c", f"import {module}"],
        text=True,
        capture_output=True,
        timeout=15,
    )
    if proc.returncode == 0:
        status_line("pass", f"Python import {module}", subject)
        add_check(checks, "import", subject, critical, "pass")
        return True
    detail = (proc.stderr or proc.stdout or "import failed").strip().splitlines()[-1]
    fix = recovery_hint(
        f"install {module.split('.')[0]} into KISSPATH_PYTHON_ENV"
    )
    status_line("fail", f"Python import {module}", detail)
    add_check(checks, "import", subject, critical, "fail", fix)
    return False


def check_tool_starts(checks, relpath, critical=True):
    python = PYTHON_ENV if os.path.exists(PYTHON_ENV) else sys.executable
    path = os.path.join(KI_DIR, relpath)
    subject = os.path.realpath(path)
    if not os.path.isfile(path):
        fix = recovery_hint(f"restore tool {relpath}")
        status_line("fail", f"Tool startup {relpath}", f"NOT FOUND at {path}")
        add_check(checks, "run", subject, critical, "fail", fix)
        return False
    proc = subprocess.run(
        [python, path, "--help"],
        cwd=KI_DIR,
        text=True,
        capture_output=True,
        timeout=15,
    )
    if proc.returncode == 0:
        status_line("pass", f"Tool startup {relpath}", f"{subject} --help")
        add_check(checks, "run", subject, critical, "pass")
        return True
    detail = (proc.stderr or proc.stdout or "startup failed").strip().splitlines()[-1]
    fix = recovery_hint(f"fix {relpath} so it starts with --help")
    status_line("fail", f"Tool startup {relpath}", detail)
    add_check(checks, "run", subject, critical, "fail", fix)
    return False


def check_native_amanzi_binary(checks):
    found = shutil.which("ats") or shutil.which("amanzi")
    subject = os.path.realpath(found) if found else "ats|amanzi on PATH"
    if not found:
        fix = recovery_hint(
            "build Amanzi/ATS from source per SKILL.md Installation and put ats or amanzi on PATH"
        )
        status_line("fail", "Native Amanzi/ATS binary", "ats/amanzi not found on PATH")
        add_check(checks, "binary", subject, True, "fail", fix)
        return False
    if not os.access(found, os.X_OK):
        fix = recovery_hint(f"make native binary executable with chmod +x {found}")
        status_line("fail", "Native Amanzi/ATS binary", f"not executable: {found}")
        add_check(checks, "binary", subject, True, "fail", fix)
        return False

    proc = subprocess.run(
        [found, "--help"],
        text=True,
        capture_output=True,
        timeout=20,
    )
    if proc.returncode in (0, 1):
        status_line("pass", "Native Amanzi/ATS binary", subject)
        add_check(checks, "binary", subject, True, "pass")
        return True
    detail = (proc.stderr or proc.stdout or "binary did not start").strip().splitlines()[-1]
    fix = recovery_hint(f"verify the Amanzi/ATS installation at {found}")
    status_line("fail", "Native Amanzi/ATS binary", detail)
    add_check(checks, "binary", subject, True, "fail", fix)
    return False


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}))
    ok = checks and all(c["status"] == "pass" or not c.get("critical") for c in checks)
    sys.exit(0 if ok else 1)


def main():
    checks = []

    print(f"{' PREFLIGHT: Amanzi_ATS ':=^60}")
    print(f"  KI root: {KI_DIR}")
    print()

    check_file(checks, REGISTERED_EXECUTABLE, "Registered KI executable", True, True)
    check_native_amanzi_binary(checks)

    print()
    check_dir(checks, os.path.join(KI_DIR, "tools"), "KI tools directory", True)
    for relpath in (
        "SKILL.md",
        "knowledge_infrastructure.yaml",
        "dag.yaml",
        "diagnostics/triplets.yaml",
    ):
        check_file(checks, os.path.join(KI_DIR, relpath), relpath, True)

    print()
    for module in ("numpy", "pandas", "h5py", "matplotlib", "lxml"):
        check_import(checks, module, True)

    print()
    for relpath in (
        "tools/run_amanzi.py",
        "tools/convert_forcing_to_amanzi.py",
        "tools/convert_soil_to_amanzi.py",
        "tools/parse_amanzi_output.py",
    ):
        check_tool_starts(checks, relpath, True)

    print()
    failed = [c for c in checks if c["status"] == "fail"]
    if failed:
        print(f"  Results: {len(checks) - len(failed)} passed, {len(failed)} failed")
        print(f"  STATUS: PREFLIGHT FAILED; fixes reference {DIAGNOSTICS}")
    else:
        print(f"  Results: {len(checks)} passed, 0 failed")
        print("  STATUS: PREFLIGHT PASSED")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
