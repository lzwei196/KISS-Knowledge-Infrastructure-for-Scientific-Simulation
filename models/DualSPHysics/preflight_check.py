#!/usr/bin/env python3
"""Preflight check for the DualSPHysics knowledge infrastructure."""

import json
import os
import subprocess
import sys


MODEL_ID = "DualSPHysics"
KI_DIR = os.path.dirname(os.path.abspath(__file__))
TRIPLETS = os.path.join(KI_DIR, "diagnostics", "triplets.yaml")
PYTHON_ENV = "KISSPATH_PYTHON_ENV/bin/python"
BIN_DIR = (
    "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/"
    "DualSPHysics/source/repo/bin/linux"
)

GENCASE = os.path.join(BIN_DIR, "GenCase_linux64")
DSPH_CPU = os.path.join(BIN_DIR, "DualSPHysics5.4CPU_linux64")
MEASURETOOL = os.path.join(BIN_DIR, "MeasureTool_linux64")
PARTVTK = os.path.join(BIN_DIR, "PartVTK_linux64")
DSPH_CONFIG = os.path.join(BIN_DIR, "DsphConfig.xml")
DSPH_CHRONO = os.path.join(BIN_DIR, "libdsphchrono.so")
CHRONO_ENGINE = os.path.join(BIN_DIR, "libChronoEngine.so")

CHECKS = []


def fix_text(message):
    return f"{message} Check diagnostics/triplets.yaml for recovery."


def add_check(kind, subject, critical, status, fix=""):
    check = {
        "kind": kind,
        "subject": subject,
        "critical": bool(critical),
        "status": status,
        "fix": fix if status == "fail" else "",
    }
    CHECKS.append(check)
    label = "OK" if status == "pass" else ("FAIL" if critical else "WARN")
    print(f"  {label:<5} {kind}: {subject}")
    if status == "fail":
        print(f"        Fix: {check['fix']}")
    return status == "pass"


def check_file(path, label, *, executable=False, critical=True, kind="data"):
    subject = os.path.realpath(path) if os.path.exists(path) else path
    if not os.path.isfile(path):
        return add_check(
            kind,
            subject,
            critical,
            "fail",
            fix_text(f"{label} is missing at {path}."),
        )
    if executable and not os.access(path, os.X_OK):
        return add_check(
            kind,
            os.path.realpath(path),
            critical,
            "fail",
            fix_text(f"{label} exists but is not executable; run chmod +x {path}."),
        )
    return add_check(kind, os.path.realpath(path), critical, "pass")


def check_dir(path, label, *, critical=True):
    subject = os.path.realpath(path) if os.path.exists(path) else path
    if not os.path.isdir(path):
        return add_check(
            "data",
            subject,
            critical,
            "fail",
            fix_text(f"{label} directory is missing at {path}."),
        )
    if not os.listdir(path):
        return add_check(
            "data",
            os.path.realpath(path),
            critical,
            "fail",
            fix_text(f"{label} directory exists but is empty: {path}."),
        )
    return add_check("data", os.path.realpath(path), critical, "pass")


def command_env():
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = BIN_DIR + (
        os.pathsep + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else ""
    )
    return env


def check_command_starts(path, args, label, *, critical=True, expect_text=None):
    subject = os.path.realpath(path) if os.path.exists(path) else path
    if not os.path.isfile(path) or not os.access(path, os.X_OK):
        return add_check(
            "run",
            subject,
            critical,
            "fail",
            fix_text(f"{label} cannot be started because its executable is unavailable."),
        )
    try:
        proc = subprocess.run(
            [path] + list(args),
            cwd=KI_DIR,
            env=command_env(),
            text=True,
            capture_output=True,
            timeout=15,
        )
    except subprocess.TimeoutExpired:
        return add_check(
            "run",
            os.path.realpath(path),
            critical,
            "fail",
            fix_text(f"{label} did not return from a cheap startup check within 15s."),
        )
    except OSError as exc:
        return add_check(
            "run",
            os.path.realpath(path),
            critical,
            "fail",
            fix_text(f"{label} failed to start: {exc}."),
        )

    output = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        return add_check(
            "run",
            os.path.realpath(path),
            critical,
            "fail",
            fix_text(
                f"{label} startup returned {proc.returncode}; "
                f"first output: {output[:240].strip()}"
            ),
        )
    if expect_text and expect_text not in output:
        return add_check(
            "run",
            os.path.realpath(path),
            critical,
            "fail",
            fix_text(f"{label} started but did not print expected marker {expect_text!r}."),
        )
    return add_check("run", os.path.realpath(path), critical, "pass")


def check_python_import(module, *, critical=True):
    if not os.path.isfile(PYTHON_ENV):
        return add_check(
            "import",
            f"{PYTHON_ENV} import {module}",
            critical,
            "fail",
            fix_text("HydroCraft python_env interpreter is missing."),
        )
    code = f"import {module}"
    proc = subprocess.run(
        [PYTHON_ENV, "-c", code],
        cwd=KI_DIR,
        text=True,
        capture_output=True,
        timeout=15,
    )
    if proc.returncode != 0:
        return add_check(
            "import",
            f"{PYTHON_ENV} import {module}",
            critical,
            "fail",
            fix_text(
                f"Install or repair Python module {module!r} in "
                "KISSPATH_PYTHON_ENV."
            ),
        )
    return add_check("import", f"{PYTHON_ENV} import {module}", critical, "pass")


def check_python_compile(path, *, critical=True):
    subject = os.path.realpath(path) if os.path.exists(path) else path
    if not os.path.isfile(path):
        return add_check(
            "import",
            subject,
            critical,
            "fail",
            fix_text(f"Required KI tool is missing: {path}."),
        )
    proc = subprocess.run(
        [PYTHON_ENV, "-m", "py_compile", path],
        cwd=KI_DIR,
        text=True,
        capture_output=True,
        timeout=15,
    )
    if proc.returncode != 0:
        return add_check(
            "import",
            os.path.realpath(path),
            critical,
            "fail",
            fix_text(f"Required KI tool does not compile: {proc.stderr[:240].strip()}"),
        )
    return add_check("import", os.path.realpath(path), critical, "pass")


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}))
    sys.exit(0 if all(c["status"] == "pass" or not c.get("critical") for c in checks) else 1)


def main():
    print("=" * 60)
    print(f"  PREFLIGHT CHECK: {MODEL_ID}")
    print("=" * 60)
    print()

    check_dir(os.path.join(KI_DIR, "tools"), "KI tools", critical=True)
    check_file(os.path.join(KI_DIR, "SKILL.md"), "KI skill", critical=True)
    check_file(os.path.join(KI_DIR, "knowledge_infrastructure.yaml"), "KI manifest", critical=True)
    check_file(os.path.join(KI_DIR, "dag.yaml"), "KI DAG", critical=True)
    check_file(TRIPLETS, "Diagnostic triplets", critical=False)

    check_file(PYTHON_ENV, "HydroCraft Python interpreter", executable=True, critical=True)
    for module in ("json", "xml.etree.ElementTree", "argparse"):
        check_python_import(module, critical=True)
    for module in ("numpy", "pandas", "matplotlib", "lxml"):
        check_python_import(module, critical=False)

    for tool in (
        "convert_forcing_to_dsph.py",
        "convert_parameters.py",
        "generate_case_xml.py",
        "parse_dsph_output.py",
        "run_dualsphysics.py",
    ):
        check_python_compile(os.path.join(KI_DIR, "tools", tool), critical=True)

    check_dir(BIN_DIR, "DualSPHysics bin/linux", critical=True)
    check_file(DSPH_CONFIG, "DualSPHysics configuration", critical=True)
    check_file(DSPH_CHRONO, "DualSPHysics Chrono library", critical=True)
    check_file(CHRONO_ENGINE, "Chrono engine library", critical=True)
    check_file(GENCASE, "GenCase binary", executable=True, critical=True, kind="binary")
    check_file(DSPH_CPU, "DualSPHysics CPU binary", executable=True, critical=True, kind="binary")
    check_file(MEASURETOOL, "MeasureTool binary", executable=True, critical=False, kind="binary")
    check_file(PARTVTK, "PartVTK binary", executable=True, critical=False, kind="binary")

    check_command_starts(GENCASE, ["-h"], "GenCase", critical=True, expect_text="GenCase v")
    check_command_starts(
        DSPH_CPU,
        ["-h"],
        "DualSPHysics CPU solver",
        critical=True,
        expect_text="DualSPHysics5 v",
    )

    print()
    passed = sum(1 for check in CHECKS if check["status"] == "pass")
    failed = len(CHECKS) - passed
    print(f"  Results: {passed} passed, {failed} failed")
    if failed:
        print(f"  STATUS: PREFLIGHT FAILED. Start recovery with {TRIPLETS}")
    else:
        print("  STATUS: PREFLIGHT PASSED. Safe to proceed with model execution.")

    emit_report(MODEL_ID, CHECKS)


if __name__ == "__main__":
    main()
