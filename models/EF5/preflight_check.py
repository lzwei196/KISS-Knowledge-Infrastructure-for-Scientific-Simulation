#!/usr/bin/env python3
"""Preflight check for the EF5 Knowledge Infrastructure.

This script verifies the real EF5 executable, runtime loader environment,
HydroCraft Python imports, KI tool files, and recovery diagnostics before a run.
It always finishes with a PREFLIGHT_REPORT= JSON line for the KDT gate.
"""

import glob
import json
import os
from pathlib import Path
import subprocess
import sys


MODEL_ID = "EF5"
KI_DIR = Path(__file__).resolve().parent
MODEL_DIR = KI_DIR.parent
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"
PYTHON_ENV = Path("KISSPATH_PYTHON_ENV/bin/python")
EF5_BINARY = MODEL_DIR / "bin" / "ef5"

REQUIRED_KI_FILES = [
    KI_DIR / "SKILL.md",
    KI_DIR / "knowledge_infrastructure.yaml",
    KI_DIR / "dag.yaml",
    KI_DIR / "docs" / "format_spec.yaml",
    TRIPLETS,
]

REQUIRED_TOOLS = [
    KI_DIR / "tools" / "prepare_basic_grids.py",
    KI_DIR / "tools" / "convert_forcing_to_ef5.py",
    KI_DIR / "tools" / "convert_params_to_ef5.py",
    KI_DIR / "tools" / "run_ef5.py",
    KI_DIR / "tools" / "parse_ef5_output.py",
]

REQUIRED_IMPORTS = [
    "numpy",
    "pandas",
    "rasterio",
    "yaml",
    "whitebox",
    "ki_tools_common.load_forcing",
    "ki_tools_common.metrics",
    "ki_tools_common.soil_utils",
    "ki_tools_common.cross_platform",
    "ki_tools_common.debug_framework",
]

KNOWN_LIB_DIRS = [
    "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/PCR_GLOBWB_2/miniconda/envs/pcrglobwb_python3/lib",
    "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/PCR_GLOBWB_2/miniconda/pkgs/geotiff-1.7.4-h222b469_0/lib",
    "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/CWatM/conda_env/lib",
]


def diagnostic_fix(message):
    return f"{message}; check {TRIPLETS} for known recovery triplets"


def add_check(checks, kind, subject, critical, status, fix=""):
    check = {
        "kind": kind,
        "subject": str(subject),
        "critical": bool(critical),
        "status": status,
        "fix": fix if status == "fail" else "",
    }
    checks.append(check)
    level = "OK" if status == "pass" else ("FAIL" if critical else "WARN")
    print(f"  {level:<5} {kind}: {subject}")
    if status == "fail" and fix:
        print(f"        Fix: {fix}")
    return status == "pass"


def emit_report(model_id, checks):
    report = {"model_id": model_id, "checks": checks}
    print("PREFLIGHT_REPORT=" + json.dumps(report, sort_keys=True))
    critical_failed = any(c["critical"] and c["status"] != "pass" for c in checks)
    sys.exit(1 if critical_failed else 0)


def check_file(checks, path, label, critical=True, executable=False, kind="data"):
    p = Path(path)
    subject = p.resolve() if p.exists() else p
    if not p.is_file():
        return add_check(
            checks,
            kind,
            subject,
            critical,
            "fail",
            diagnostic_fix(f"{label} is missing; restore or regenerate {p}"),
        )
    if executable and not os.access(p, os.X_OK):
        return add_check(
            checks,
            kind,
            p.resolve(),
            critical,
            "fail",
            diagnostic_fix(f"{label} exists but is not executable; run chmod +x {p}"),
        )
    return add_check(checks, kind, p.resolve(), critical, "pass")


def check_dir(checks, path, label, critical=True):
    p = Path(path)
    if p.is_dir() and any(p.iterdir()):
        return add_check(checks, "data", p.resolve(), critical, "pass")
    state = "missing" if not p.is_dir() else "empty"
    return add_check(
        checks,
        "data",
        p.resolve() if p.exists() else p,
        critical,
        "fail",
        diagnostic_fix(f"{label} directory is {state}; restore the KI layout"),
    )


def run_command(cmd, timeout=20, env=None, cwd=None):
    try:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            cwd=cwd,
        )
    except subprocess.TimeoutExpired as exc:
        completed = subprocess.CompletedProcess(cmd, -1, exc.stdout or "", exc.stderr or "")
        completed.timeout = True
        return completed
    except OSError as exc:
        return subprocess.CompletedProcess(cmd, -2, "", str(exc))


def check_import(checks, module):
    if not PYTHON_ENV.is_file():
        return add_check(
            checks,
            "import",
            f"{PYTHON_ENV} import {module}",
            True,
            "fail",
            diagnostic_fix(f"HydroCraft Python interpreter is missing at {PYTHON_ENV}"),
        )

    code = f"import {module}; print('ok')"
    result = run_command([str(PYTHON_ENV), "-c", code], timeout=20, cwd=str(KI_DIR))
    if result.returncode == 0:
        return add_check(checks, "import", f"{PYTHON_ENV} import {module}", True, "pass")
    detail = (result.stderr or result.stdout or "").strip().splitlines()
    reason = detail[-1] if detail else f"exit code {result.returncode}"
    return add_check(
        checks,
        "import",
        f"{PYTHON_ENV} import {module}",
        True,
        "fail",
        diagnostic_fix(f"install or repair Python dependency '{module}' in KISSPATH_PYTHON_ENV ({reason})"),
    )


def parse_ldd_missing(output):
    missing = []
    for line in output.splitlines():
        if "=> not found" in line:
            missing.append(line.split("=>", 1)[0].strip())
    return missing


def lib_dirs_for(binary):
    dirs = []
    for d in KNOWN_LIB_DIRS:
        if os.path.isdir(d) and d not in dirs:
            dirs.append(d)
    dirs.extend(d for d in sorted(glob.glob("KISSPATH_HOME/miniconda3/envs/*/lib")) if d not in dirs)

    ldd = run_command(["ldd", str(binary)], timeout=20)
    missing = parse_ldd_missing(ldd.stdout + ldd.stderr)
    for soname in missing:
        for d in dirs:
            if os.path.exists(os.path.join(d, soname)):
                break
        else:
            for root in [
                "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/PCR_GLOBWB_2",
                "KISSPATH_KI_ROOT/EF5",
            ]:
                for found in glob.glob(os.path.join(root, "**", soname), recursive=True):
                    d = os.path.dirname(found)
                    if d not in dirs:
                        dirs.insert(0, d)
                    break
    return dirs


def check_shared_libs(checks, binary_realpath, lib_dirs):
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = ":".join(lib_dirs + ([env["LD_LIBRARY_PATH"]] if env.get("LD_LIBRARY_PATH") else []))
    result = run_command(["ldd", binary_realpath], timeout=20, env=env)
    output = result.stdout + result.stderr
    missing = parse_ldd_missing(output)
    if result.returncode == 0 and not missing:
        return add_check(checks, "binary", f"{binary_realpath} shared libraries", True, "pass"), env
    fix = diagnostic_fix(
        "repair EF5 shared libraries or export LD_LIBRARY_PATH including "
        + ":".join(KNOWN_LIB_DIRS)
    )
    if missing:
        fix = diagnostic_fix(f"missing EF5 shared libraries: {', '.join(missing)}")
    return add_check(checks, "binary", f"{binary_realpath} shared libraries", True, "fail", fix), env


def check_binary_starts(checks, binary_realpath, env):
    result = run_command([binary_realpath], timeout=10, env=env, cwd=str(KI_DIR))
    output = (result.stdout or "") + (result.stderr or "")
    started = "Ensemble Framework For Flash Flood Forecasting" in output
    expected_no_control = "Failed to open configuration file control.txt" in output
    if started and expected_no_control:
        return add_check(checks, "run", binary_realpath, True, "pass")
    if getattr(result, "timeout", False):
        fix = diagnostic_fix("EF5 did not reach its startup banner within 10 seconds")
    else:
        detail = output.strip().splitlines()[-1] if output.strip() else f"exit code {result.returncode}"
        fix = diagnostic_fix(f"EF5 binary did not start cleanly ({detail})")
    return add_check(checks, "run", binary_realpath, True, "fail", fix)


def main():
    checks = []
    print("=" * 60)
    print("PREFLIGHT CHECK: EF5")
    print("=" * 60)

    check_dir(checks, KI_DIR / "tools", "KI tools", critical=True)
    for path in REQUIRED_KI_FILES:
        check_file(checks, path, path.name, critical=True)
    for path in REQUIRED_TOOLS:
        check_file(checks, path, path.name, critical=True)

    binary_ok = check_file(checks, EF5_BINARY, "EF5 binary", critical=True, executable=True, kind="binary")
    if binary_ok:
        binary_realpath = str(EF5_BINARY.resolve())
        lib_dirs = lib_dirs_for(binary_realpath)
        libs_ok, env = check_shared_libs(checks, binary_realpath, lib_dirs)
        if libs_ok:
            check_binary_starts(checks, binary_realpath, env)

    check_file(checks, PYTHON_ENV, "HydroCraft Python interpreter", critical=True, executable=True, kind="import")
    for module in REQUIRED_IMPORTS:
        check_import(checks, module)

    passed = sum(1 for c in checks if c["status"] == "pass")
    failed = len(checks) - passed
    print(f"Results: {passed} passed, {failed} failed")
    if failed:
        print(f"Failures point to {TRIPLETS} for recovery guidance.")
    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
