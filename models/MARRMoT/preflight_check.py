#!/usr/bin/env python3
"""Contract-compliant preflight check for the MARRMoT KI."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


MODEL_ID = "MARRMoT"
KI_DIR = Path(__file__).resolve().parent
DIAGNOSTICS = KI_DIR / "diagnostics" / "triplets.yaml"
HYDROCRAFT_PYTHON = Path("KISSPATH_PYTHON_ENV/bin/python")
OCTAVE_BINARY = Path("/usr/bin/octave")
MARRMOT_SOURCE = Path("KISSPATH_KI_ROOT/MARRMoT/source/repo/MARRMoT")
SOURCE_SENTINELS = [
    MARRMOT_SOURCE / "Models" / "Model files" / "MARRMoT_model.m",
    MARRMOT_SOURCE / "Models" / "Model files" / "m_01_collie1_1p_1s.m",
    MARRMOT_SOURCE / "Functions" / "Optimisation functions" / "my_cmaes.m",
]
REQUIRED_KI_FILES = [
    KI_DIR / "SKILL.md",
    KI_DIR / "knowledge_infrastructure.yaml",
    KI_DIR / "dag.yaml",
    KI_DIR / "tools" / "run_marrmot.py",
    KI_DIR / "tools" / "convert_forcing.py",
    KI_DIR / "tools" / "convert_parameters.py",
    KI_DIR / "tools" / "parse_output.py",
    KI_DIR / "tools" / "octave_shims" / "lsqnonlin.m",
    KI_DIR / "calib" / "forcing.csv",
    KI_DIR / "calib" / "params.json",
    DIAGNOSTICS,
]


checks = []


def add_check(kind, subject, critical, status, fix=""):
    check = {
        "kind": kind,
        "subject": str(subject),
        "critical": bool(critical),
        "status": status,
        "fix": fix,
    }
    checks.append(check)
    label = "OK" if status == "pass" else "FAIL"
    print(f"  {label:<5} {kind}: {subject}")
    if status != "pass" and fix:
        print(f"        Fix: {fix}")


def check_executable(path, label, critical=True):
    subject = Path(os.path.realpath(path))
    if subject.is_file() and os.access(subject, os.X_OK):
        add_check("binary", subject, critical, "pass")
        return subject
    fix = f"Install executable or update knowledge_infrastructure.yaml; see {DIAGNOSTICS}"
    add_check("binary", subject, critical, "fail", fix)
    return subject


def check_subprocess(command, label, critical=True, timeout=30, kind="run"):
    subject = " ".join(str(part) for part in command)
    try:
        result = subprocess.run(
            [str(part) for part in command],
            cwd=str(KI_DIR),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        add_check(kind, subject, critical, "fail", f"{exc}; see {DIAGNOSTICS}")
        return
    except subprocess.TimeoutExpired:
        add_check(kind, subject, critical, "fail", f"Command timed out; see {DIAGNOSTICS}")
        return

    if result.returncode == 0:
        add_check(kind, subject, critical, "pass")
        return

    stderr = (result.stderr or result.stdout or "").strip().splitlines()
    detail = f" Exit {result.returncode}."
    if stderr:
        detail += f" Last output: {stderr[-1][:300]}"
    add_check(kind, subject, critical, "fail", f"{label} failed.{detail} See {DIAGNOSTICS}")


def check_file(path, label, critical=True):
    path = Path(path)
    if path.is_file():
        add_check("data", path, critical, "pass")
    else:
        add_check("data", path, critical, "fail", f"Restore {label}; see {DIAGNOSTICS}")


def check_dir(path, label, critical=True):
    path = Path(path)
    if path.is_dir():
        add_check("data", path, critical, "pass")
    else:
        add_check("data", path, critical, "fail", f"Restore {label}; see {DIAGNOSTICS}")


def check_python_import(module, label, critical=True):
    if HYDROCRAFT_PYTHON.is_file():
        interpreter = HYDROCRAFT_PYTHON
    else:
        interpreter = Path(sys.executable)

    command = [
        interpreter,
        "-c",
        f"import {module}; print(getattr({module}, '__version__', 'ok'))",
    ]
    subject = f"{interpreter}: import {module}"
    try:
        result = subprocess.run(
            [str(part) for part in command],
            cwd=str(KI_DIR),
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        add_check("import", subject, critical, "fail", f"{exc}; see {DIAGNOSTICS}")
        return

    if result.returncode == 0:
        add_check("import", subject, critical, "pass")
    else:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        msg = detail[-1][:300] if detail else f"exit {result.returncode}"
        add_check(
            "import",
            subject,
            critical,
            "fail",
            f"Install {module} in {interpreter}; {msg}; see {DIAGNOSTICS}",
        )


def emit_report(model_id, report_checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": report_checks}))
    failed_critical = any(c["status"] != "pass" and c.get("critical") for c in report_checks)
    sys.exit(1 if failed_critical else 0)


def main():
    print(f"{' PREFLIGHT: MARRMoT ':=^60}")
    print(f"KI directory: {KI_DIR}")
    print()

    octave = check_executable(OCTAVE_BINARY, "GNU Octave", critical=True)
    check_subprocess(
        [octave, "--no-gui", "--no-window-system", "--eval", "disp('octave-preflight-ok')"],
        "GNU Octave startup",
        critical=True,
        timeout=30,
    )

    check_dir(MARRMOT_SOURCE, "MARRMoT source tree", critical=True)
    for sentinel in SOURCE_SENTINELS:
        check_file(sentinel, sentinel.name, critical=True)

    check_subprocess(
        [
            octave,
            "--no-gui",
            "--no-window-system",
            "--eval",
            (
                f"addpath(genpath('{MARRMOT_SOURCE}')); "
                "m=feval('m_01_collie1_1p_1s'); "
                "assert(m.numParams==1); assert(m.numStores==1); "
                "disp('marrmot-source-ok')"
            ),
        ],
        "MARRMoT source instantiation",
        critical=True,
        timeout=60,
    )

    for path in REQUIRED_KI_FILES:
        check_file(path, path.name, critical=True)

    check_python_import("numpy", "NumPy for run_marrmot.py", critical=True)
    check_python_import("pandas", "pandas for converters/parsers", critical=False)
    check_python_import("xarray", "xarray for NetCDF forcing conversion", critical=False)
    check_python_import("matplotlib", "matplotlib for validation figures", critical=False)

    print()
    passed = sum(1 for c in checks if c["status"] == "pass")
    failed = len(checks) - passed
    print(f"  Results: {passed} passed, {failed} failed")
    if failed:
        print(f"  STATUS: PREFLIGHT FAILED; check fixes above and {DIAGNOSTICS}")
    else:
        print("  STATUS: PREFLIGHT PASSED")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
