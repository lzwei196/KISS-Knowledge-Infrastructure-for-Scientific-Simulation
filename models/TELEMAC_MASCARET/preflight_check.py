#!/usr/bin/env python3
"""Preflight check for the TELEMAC-MASCARET knowledge infrastructure."""

import json
import os
import subprocess
import sys


MODEL_ID = "TELEMAC-MASCARET"
KI_DIR = os.path.dirname(os.path.abspath(__file__))
PYTHON_ENV = "KISSPATH_PYTHON_ENV/bin/python"
TELEMAC_ROOT = "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/TELEMAC_MASCARET/source/repo"
TELEMAC_BUILD = os.path.join(TELEMAC_ROOT, "builds", "main_gfortran_release")
TELEMAC_BIN = os.path.join(TELEMAC_BUILD, "bin", "telemac2d")
TELEMAC_LIB = os.path.join(TELEMAC_BUILD, "lib")
TELEMAC_RUNNER = os.path.join(TELEMAC_ROOT, "scripts", "python3", "telemac2d.py")
SYSTEL_CFG = os.path.join(TELEMAC_BUILD, "systel.cfg")
T2D_DICO = os.path.join(TELEMAC_ROOT, "sources", "telemac2d", "telemac2d.dico")
TRIPLETS = os.path.join(KI_DIR, "diagnostics", "triplets.yaml")


checks = []


def add_check(kind, subject, critical, status, fix=""):
    check = {
        "kind": kind,
        "subject": subject,
        "critical": bool(critical),
        "status": status,
        "fix": fix,
    }
    checks.append(check)

    label = "OK" if status == "pass" else "FAIL"
    print(f"  {label:<5} {kind}: {subject}")
    if status != "pass" and fix:
        print(f"        Fix: {fix}")
    return status == "pass"


def check_file(path, label, critical=True, executable=False):
    subject = os.path.realpath(path) if os.path.exists(path) else path
    if not os.path.isfile(path):
        return add_check(
            "data",
            subject,
            critical,
            "fail",
            f"Restore {label}; check {TRIPLETS} for the matching recovery path.",
        )
    if executable and not os.access(path, os.X_OK):
        return add_check(
            "binary",
            subject,
            critical,
            "fail",
            f"Run chmod +x {path}; then check {TRIPLETS} if execution still fails.",
        )
    return add_check("binary" if executable else "data", subject, critical, "pass")


def check_dir(path, label, critical=True, non_empty=True):
    subject = os.path.realpath(path) if os.path.exists(path) else path
    if not os.path.isdir(path):
        return add_check(
            "data",
            subject,
            critical,
            "fail",
            f"Restore {label}; check {TRIPLETS} for recovery.",
        )
    if non_empty and not os.listdir(path):
        return add_check(
            "data",
            subject,
            critical,
            "fail",
            f"{label} is empty; restore KI contents and check {TRIPLETS}.",
        )
    return add_check("data", subject, critical, "pass")


def check_import(module, critical=True):
    python = PYTHON_ENV if os.path.exists(PYTHON_ENV) else sys.executable
    result = subprocess.run(
        [python, "-c", f"import {module}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=15,
    )
    if result.returncode == 0:
        return add_check("import", f"{python}: import {module}", critical, "pass")
    detail = (result.stderr or result.stdout).strip().splitlines()[-1:]
    detail = detail[0] if detail else f"import {module} failed"
    return add_check(
        "import",
        f"{python}: import {module}",
        critical,
        "fail",
        f"Install/repair {module.split('.')[0]} in {python}; see {TRIPLETS}. Last error: {detail}",
    )


def check_binary_starts():
    subject = os.path.realpath(TELEMAC_BIN) if os.path.exists(TELEMAC_BIN) else TELEMAC_BIN
    if not os.path.isfile(TELEMAC_BIN) or not os.access(TELEMAC_BIN, os.X_OK):
        return

    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = TELEMAC_LIB + os.pathsep + env.get("LD_LIBRARY_PATH", "")
    result = subprocess.run(
        [TELEMAC_BIN, "--help"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=5,
        env=env,
        cwd=KI_DIR,
    )
    output = (result.stdout or "") + (result.stderr or "")
    if "error while loading shared libraries" in output:
        add_check(
            "run",
            subject,
            True,
            "fail",
            f"Set LD_LIBRARY_PATH={TELEMAC_LIB}:$LD_LIBRARY_PATH and check {TRIPLETS}.",
        )
    elif "TELEMAC2D" in output or "LISTING OF TELEMAC2D" in output:
        add_check("run", subject, True, "pass")
    else:
        tail = " ".join(output.strip().splitlines()[-3:])[:400]
        add_check(
            "run",
            subject,
            True,
            "fail",
            f"telemac2d did not reach its startup banner. Check {TRIPLETS}. Tail: {tail}",
        )


def check_runner_help():
    python = PYTHON_ENV if os.path.exists(PYTHON_ENV) else sys.executable
    subject = os.path.realpath(TELEMAC_RUNNER) if os.path.exists(TELEMAC_RUNNER) else TELEMAC_RUNNER
    if not os.path.isfile(TELEMAC_RUNNER):
        add_check(
            "run",
            subject,
            True,
            "fail",
            f"Restore TELEMAC scripts/python3/telemac2d.py or set HOMETEL to a valid TELEMAC tree; see {TRIPLETS}.",
        )
        return

    env = os.environ.copy()
    env["HOMETEL"] = TELEMAC_ROOT
    env["SYSTELCFG"] = SYSTEL_CFG
    env["PATH"] = os.path.dirname(TELEMAC_RUNNER) + os.pathsep + env.get("PATH", "")
    env["LD_LIBRARY_PATH"] = TELEMAC_LIB + os.pathsep + env.get("LD_LIBRARY_PATH", "")
    result = subprocess.run(
        [python, TELEMAC_RUNNER, "--help"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=15,
        env=env,
        cwd=KI_DIR,
    )
    output = (result.stdout or "") + (result.stderr or "")
    if result.returncode == 0 and "usage: telemac2d.py" in output:
        add_check("run", subject, True, "pass")
    else:
        tail = " ".join(output.strip().splitlines()[-3:])[:400]
        add_check(
            "run",
            subject,
            True,
            "fail",
            f"Repair TELEMAC Python launcher environment with {python}; check {TRIPLETS}. Tail: {tail}",
        )


def emit_report():
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": MODEL_ID, "checks": checks}, sort_keys=True))
    failed_critical = any(c["critical"] and c["status"] != "pass" for c in checks)
    sys.exit(1 if failed_critical else 0)


def main():
    print("=" * 60)
    print(f"  PREFLIGHT CHECK: {MODEL_ID}")
    print("=" * 60)

    check_dir(os.path.join(KI_DIR, "tools"), "KI tools directory")
    for rel in (
        "SKILL.md",
        "knowledge_infrastructure.yaml",
        "dag.yaml",
        "diagnostics/triplets.yaml",
        "docs/format_spec.yaml",
        "tools/run_telemac.py",
        "tools/parse_selafin.py",
        "tools/convert_forcing.py",
        "tools/convert_bathymetry.py",
    ):
        check_file(os.path.join(KI_DIR, rel), rel, critical=True)

    check_file(PYTHON_ENV, "HydroCraft Python interpreter", critical=True, executable=True)
    for module in ("numpy", "scipy", "yaml", "ki_tools_common.load_forcing"):
        check_import(module, critical=True)

    check_file(TELEMAC_BIN, "TELEMAC telemac2d executable", critical=True, executable=True)
    check_dir(TELEMAC_LIB, "TELEMAC shared-library directory", critical=True)
    for lib in ("libtelemac2d.so", "libbief.so", "libspecial.so"):
        check_file(os.path.join(TELEMAC_LIB, lib), lib, critical=True)
    check_file(SYSTEL_CFG, "TELEMAC systel.cfg", critical=True)
    check_file(T2D_DICO, "TELEMAC-2D dictionary", critical=True)
    check_runner_help()
    check_binary_starts()

    if os.path.isfile(TRIPLETS):
        print(f"  INFO  Diagnostics available: {TRIPLETS}")
    else:
        print(f"  INFO  Diagnostics missing; restore {TRIPLETS} before debugging model failures.")

    passed = sum(1 for c in checks if c["status"] == "pass")
    failed = len(checks) - passed
    print(f"  Results: {passed} passed, {failed} failed")
    for c in checks:
        if c["critical"] and c["status"] != "pass":
            print(f"  BLOCKER: {c['subject']}")
            print(f"           {c['fix']}")
    emit_report()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        add_check(
            "run",
            "preflight_check.py",
            True,
            "fail",
            f"Preflight crashed: {exc!r}. Check {TRIPLETS} before running the model.",
        )
        emit_report()
