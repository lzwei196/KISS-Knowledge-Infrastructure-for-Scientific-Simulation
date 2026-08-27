#!/usr/bin/env python3
"""
Preflight check for the RZWQM2 Knowledge Infrastructure.

This verifies the real model executable, core template inputs, KI tools,
diagnostics, and Python imports before a run. The final output line is the
KDT gate contract:

    PREFLIGHT_REPORT=<json>
"""

import json
import os
import platform
import re
import subprocess
import sys
import tempfile
from pathlib import Path


MODEL_ID = "RZWQM2"
KI_DIR = Path(__file__).resolve().parent
MANIFEST = KI_DIR / "knowledge_infrastructure.yaml"
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"

DEFAULT_BINARY = Path("KISSPATH_BINARIES/rzwqm2/main_ryzen_patched")
TEMPLATE_DIR = Path("KISSPATH_HOME/RZWQM2/RZWQM2/template_bengbu/bengbu_wheat")
PYTHON_ENV = Path("KISSPATH_PYTHON_ENV/bin/python")

CHECKS = []


def diagnostic_fix(action):
    return f"{action}. Check diagnostics/triplets.yaml for matching recovery guidance."


def record(kind, subject, critical, passed, fix="", detail=""):
    status = "pass" if passed else "fail"
    check = {
        "kind": kind,
        "subject": str(subject),
        "critical": bool(critical),
        "status": status,
        "fix": "" if passed else fix,
    }
    CHECKS.append(check)

    label = "OK" if passed else ("FAIL" if critical else "WARN")
    print(f"  {label:<5} {kind}: {subject}")
    if detail:
        print(f"        {detail}")
    if not passed and fix:
        print(f"        Fix: {fix}")


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}, sort_keys=True))
    critical_failed = any(c["status"] != "pass" and c.get("critical") for c in checks)
    sys.exit(1 if critical_failed else 0)


def read_manifest_binary():
    if not MANIFEST.is_file():
        return DEFAULT_BINARY
    text = MANIFEST.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"(?m)^\s{4}path:\s*(\S+)\s*$", text)
    return Path(match.group(1)) if match else DEFAULT_BINARY


def read_manifest_tools():
    if not MANIFEST.is_file():
        return []
    text = MANIFEST.read_text(encoding="utf-8", errors="replace")
    return sorted(set(re.findall(r"(?m)^\s{2}- (tools/[^\s]+\.py)\s*$", text)))


def check_file(path, label, critical=True, executable=False, kind="data"):
    path = Path(path)
    exists = path.is_file()
    can_execute = (not executable) or os.access(path, os.X_OK)
    passed = exists and can_execute
    if executable:
        subject = os.path.realpath(path)
    else:
        subject = path

    if exists and executable and not can_execute:
        fix = diagnostic_fix(f"Run chmod +x {path}")
    else:
        fix = diagnostic_fix(f"Restore or correct {label}: {path}")

    detail = label
    if executable and exists:
        detail = f"{label}; executable={can_execute}"
    record(kind, subject, critical, passed, fix, detail)
    return passed


def check_dir(path, label, critical=True, min_items=1):
    path = Path(path)
    count = len(list(path.iterdir())) if path.is_dir() else 0
    passed = path.is_dir() and count >= min_items
    fix = diagnostic_fix(f"Restore or correct {label}: {path}")
    record("data", path, critical, passed, fix, f"{label}; items={count}" if path.is_dir() else label)
    return passed


def check_import(module, python_exe, critical=True):
    subject = f"{python_exe}:{module}"
    if not Path(python_exe).is_file() or not os.access(python_exe, os.X_OK):
        record(
            "import",
            subject,
            critical,
            False,
            diagnostic_fix(f"Restore HydroCraft Python interpreter at {python_exe}"),
        )
        return False

    result = subprocess.run(
        [str(python_exe), "-c", f"import {module}"],
        capture_output=True,
        text=True,
        timeout=20,
    )
    passed = result.returncode == 0
    detail = "import succeeded" if passed else (result.stderr.strip() or result.stdout.strip())
    record(
        "import",
        subject,
        critical,
        passed,
        diagnostic_fix(f"Install {module.split('.')[0]} into {python_exe}"),
        detail,
    )
    return passed


def check_elf_dependencies(binary_path):
    result = subprocess.run(["ldd", str(binary_path)], capture_output=True, text=True, timeout=20)
    output = result.stdout + result.stderr
    passed = result.returncode == 0 and "not found" not in output
    record(
        "binary",
        f"ldd:{os.path.realpath(binary_path)}",
        True,
        passed,
        diagnostic_fix("Restore missing dynamic libraries or patch the ELF interpreter (dt_012)"),
        "dynamic libraries resolved" if passed else output.strip(),
    )
    return passed


def check_binary_launches(binary_path):
    try:
        with tempfile.TemporaryDirectory(prefix="rzwqm2-preflight-") as tmpdir:
            result = subprocess.run(
                [str(binary_path)],
                cwd=tmpdir,
                capture_output=True,
                text=True,
                timeout=3,
            )
        detail = f"process launched; return_code={result.returncode}"
        # A non-zero return is expected without scenario inputs; exec failure is
        # what this cheap launch probe is meant to catch.
        record("run", os.path.realpath(binary_path), True, True, "", detail)
        return True
    except subprocess.TimeoutExpired:
        record("run", os.path.realpath(binary_path), True, True, "", "process launched and exceeded 3s")
        return True
    except OSError as exc:
        record(
            "run",
            os.path.realpath(binary_path),
            True,
            False,
            diagnostic_fix(f"Make the RZWQM2 binary executable and runnable: {binary_path}"),
            str(exc),
        )
        return False


def check_avx2():
    if platform.system() != "Linux":
        record("run", "CPU AVX2 support", False, True, "", f"not checked on {platform.system()}")
        return True
    cpuinfo = Path("/proc/cpuinfo")
    if not cpuinfo.is_file():
        record("run", "CPU AVX2 support", False, True, "", "/proc/cpuinfo unavailable")
        return True
    has_avx2 = "avx2" in cpuinfo.read_text(encoding="utf-8", errors="ignore")
    record(
        "run",
        "CPU AVX2 support",
        True,
        has_avx2,
        diagnostic_fix("Run on an x86-64 host with AVX2 support (dt_007)"),
    )
    return has_avx2


def check_manifest_tools():
    tools = read_manifest_tools()
    missing = [tool for tool in tools if not (KI_DIR / tool).is_file()]
    passed = bool(tools) and not missing
    detail = f"{len(tools) - len(missing)}/{len(tools)} manifest-listed tools present"
    if missing:
        detail += "; missing: " + ", ".join(missing[:8])
    record(
        "data",
        MANIFEST,
        True,
        passed,
        diagnostic_fix("Restore missing tools listed in knowledge_infrastructure.yaml"),
        detail,
    )
    return passed


def main():
    print("=" * 60)
    print("  PREFLIGHT CHECK: RZWQM2")
    print("=" * 60)

    binary_path = read_manifest_binary()
    python_exe = PYTHON_ENV if PYTHON_ENV.is_file() and os.access(PYTHON_ENV, os.X_OK) else Path(sys.executable)

    print(f"  KI directory: {KI_DIR}")
    print(f"  Binary path from manifest/default: {binary_path}")
    print(f"  Python import interpreter: {python_exe}")
    print()

    binary_ok = check_file(binary_path, "RZWQM2 binary from manifest", critical=True, executable=True, kind="binary")
    if binary_ok:
        check_elf_dependencies(binary_path)
        check_binary_launches(binary_path)
    check_avx2()

    check_dir(TEMPLATE_DIR, "Canonical Bengbu wheat template", critical=True)
    for rel in [
        "IPNAMES.DAT",
        "rzwqm.dat",
        "rzinit.dat",
        "plgen.dat",
        "cntrl.dat",
        "main_ryzen_patched",
        "WHDSSAT.RZX",
        "WHCER040.CUL",
        "WHCER040.ECO",
        "WHCER040.SPE",
        "DSSAT/WHCER040.CUL",
        "DSSAT/WHCER040.ECO",
        "DSSAT/WHCER040.SPE",
    ]:
        executable = rel == "main_ryzen_patched"
        check_file(TEMPLATE_DIR / rel, f"Template {rel}", critical=True, executable=executable)

    check_file(KI_DIR / "tools" / "s8_execution" / "run_rzwqm2.py", "RZWQM2 execution wrapper", critical=True)
    check_manifest_tools()
    check_file(TRIPLETS, "Diagnostic triplets for recovery", critical=True)

    for module in ["numpy", "pandas", "xarray"]:
        check_import(module, python_exe, critical=True)

    passed = sum(1 for c in CHECKS if c["status"] == "pass")
    failed = len(CHECKS) - passed
    print()
    print(f"  Results: {passed} passed, {failed} failed")
    if any(c["status"] != "pass" and c.get("critical") for c in CHECKS):
        print("  STATUS: PREFLIGHT FAILED - fix critical issues before running RZWQM2")
    else:
        print("  STATUS: PREFLIGHT PASSED - safe to proceed with RZWQM2 execution")

    emit_report(MODEL_ID, CHECKS)


if __name__ == "__main__":
    main()
