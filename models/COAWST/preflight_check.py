#!/usr/bin/env python3
"""Preflight check for the COAWST knowledge infrastructure."""

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


MODEL_ID = "COAWST"
KI_DIR = Path(__file__).resolve().parent
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"
PYTHON_ENV_SITE = Path("KISSPATH_PYTHON_ENV/lib/python3.12/site-packages")
COAWST_BINARY = Path(
    "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/COAWST/source/repo/coawstM"
)


def diagnostics_fix(message):
    return f"{message}; then check {TRIPLETS} for matching recovery triplets."


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}, sort_keys=True))
    sys.exit(0 if all(c["status"] == "pass" or not c.get("critical") for c in checks) else 1)


def add_check(checks, kind, subject, critical, passed, fix=""):
    status = "pass" if passed else "fail"
    subject = str(subject)
    check = {
        "kind": kind,
        "subject": subject,
        "critical": bool(critical),
        "status": status,
        "fix": "" if passed else fix,
    }
    checks.append(check)
    label = "OK" if passed else "FAIL"
    print(f"  {label:<5} {kind}: {subject}")
    if not passed and fix:
        print(f"        Fix: {fix}")
    return passed


def check_file(checks, path, label, critical=True, executable=False):
    path = Path(path)
    subject = path.resolve(strict=False)
    exists = path.is_file()
    can_execute = (not executable) or os.access(path, os.X_OK)
    if exists and can_execute:
        return add_check(checks, "binary" if executable else "data", subject, critical, True)

    if not exists:
        fix = diagnostics_fix(f"{label} is missing at {subject}")
    else:
        fix = diagnostics_fix(f"{label} exists but is not executable; run chmod +x {subject}")
    return add_check(checks, "binary" if executable else "data", subject, critical, False, fix)


def check_dir(checks, path, label, critical=True):
    path = Path(path)
    subject = path.resolve(strict=False)
    passed = path.is_dir() and any(path.iterdir())
    if passed:
        return add_check(checks, "data", subject, critical, True)
    return add_check(
        checks,
        "data",
        subject,
        critical,
        False,
        diagnostics_fix(f"{label} directory is missing or empty"),
    )


def check_import(checks, module, label, critical=True):
    if PYTHON_ENV_SITE.is_dir() and str(PYTHON_ENV_SITE) not in sys.path:
        sys.path.insert(0, str(PYTHON_ENV_SITE))

    spec = importlib.util.find_spec(module)
    if spec is None:
        return add_check(
            checks,
            "import",
            module,
            critical,
            False,
            diagnostics_fix(f"Install Python dependency for {label}: {module}"),
        )

    try:
        __import__(module)
    except Exception as exc:
        return add_check(
            checks,
            "import",
            module,
            critical,
            False,
            diagnostics_fix(f"Import {module} failed under {sys.executable}: {exc}"),
        )
    return add_check(checks, "import", module, critical, True)


def check_ldd(checks, binary):
    """Inspect platform linkage metadata; startup separately proves loading."""
    binary = Path(binary).resolve()
    subject = str(binary) + " dynamic libraries"
    def result(passed, message=""):
        return add_check(checks, "binary", subject, True, passed,
                         diagnostics_fix(message) if message else "")
    if not binary.is_file():
        return result(False, "Cannot inspect libraries until the COAWST binary exists")
    darwin = sys.platform == "darwin"
    name = "otool" if darwin else "ldd"
    tool = shutil.which(name)
    if not tool:
        return result(False, f"{name} is unavailable; install the platform developer tools")
    argv = [tool, "-L", str(binary)] if darwin else [tool, str(binary)]
    try:
        proc = subprocess.run(argv, text=True, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, timeout=10)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return result(False, f"COAWST library inspection failed: {exc}")
    output = proc.stdout or ""
    if proc.returncode != 0:
        return result(False, f"{name} exited {proc.returncode}: {output[-500:]}")
    if darwin:
        dependencies = [line.strip().split(" (compatibility", 1)[0]
                        for line in output.splitlines()[1:] if line.strip()]
        # Apple system libraries can reside only in the dyld shared cache.
        missing = [dep for dep in dependencies if dep.startswith("/")
                   and not dep.startswith(("/usr/lib/", "/System/Library/"))
                   and not Path(dep).is_file()]
        if not dependencies:
            return result(False, "otool returned no dynamic-library metadata")
    else:
        missing = [line for line in output.splitlines() if "not found" in line]
    if missing:
        return result(False, "COAWST has unresolved libraries: " + "; ".join(missing))
    return result(True)


def check_binary_starts(checks, binary):
    """Probe without project inputs; a prompt cannot override a failed exit."""
    binary = Path(binary).resolve()
    subject = str(binary) + " startup"
    def result(passed, message=""):
        return add_check(checks, "run", subject, True, passed,
                         diagnostics_fix(message) if message else "")
    if not binary.is_file() or not os.access(binary, os.X_OK):
        return result(False, "Cannot probe a missing or nonexecutable COAWST binary")
    try:
        with tempfile.TemporaryDirectory(prefix="coawst-startup-") as empty:
            proc = subprocess.run([str(binary), "--version"], text=True,
                                  stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, timeout=10, cwd=empty)
            created = list(Path(empty).iterdir())
    except subprocess.TimeoutExpired:
        return result(False, "COAWST startup timed out; any partial prompt is not success")
    except OSError as exc:
        return result(False, f"COAWST could not start: {exc}")
    output = (proc.stdout or "").replace("\x00", "")
    if proc.returncode != 0:
        return result(False, f"COAWST startup exited {proc.returncode}; crash/signal or input-error termination requires review")
    if created:
        return result(False, "COAWST startup created files; installation-only boundary not established")
    if any(text in output.lower() for text in
           ["dyld:", "library not loaded", "symbol not found", "segmentation fault", "abort trap"]):
        return result(False, "COAWST startup reported a loader or crash diagnostic")
    expected = "Coupled Input File name" in output or "READ_COAWST_PAR" in output
    if not expected:
        return result(False, "COAWST did not establish the expected coupled input boundary; ocean-only banners are insufficient")
    return result(True)


def main():
    checks = []
    print(f"{' PREFLIGHT: COAWST ':=^60}")
    print()

    check_dir(checks, KI_DIR / "tools", "KI tools")
    for tool in [
        "convert_forcing.py",
        "convert_grid.py",
        "generate_config.py",
        "parse_output.py",
        "run_coawst.py",
    ]:
        check_file(checks, KI_DIR / "tools" / tool, f"KI tool {tool}", critical=True)

    check_file(checks, COAWST_BINARY, "COAWST binary", critical=True, executable=True)
    check_ldd(checks, COAWST_BINARY)
    check_binary_starts(checks, COAWST_BINARY)

    check_import(checks, "numpy", "NumPy", critical=True)
    check_import(checks, "netCDF4", "NetCDF4", critical=True)
    check_import(checks, "xarray", "xarray", critical=False)
    for module in [
        "tools.convert_forcing",
        "tools.convert_grid",
        "tools.generate_config",
        "tools.parse_output",
        "tools.run_coawst",
    ]:
        check_import(checks, module, module, critical=True)

    check_file(checks, TRIPLETS, "diagnostic triplets", critical=True)
    check_file(checks, KI_DIR / "SKILL.md", "KI skill document", critical=True)
    check_file(checks, KI_DIR / "knowledge_infrastructure.yaml", "KI manifest", critical=True)
    check_file(checks, KI_DIR / "dag.yaml", "KI DAG", critical=True)

    passed = sum(1 for check in checks if check["status"] == "pass")
    failed = len(checks) - passed
    print()
    print(f"  Results: {passed} passed, {failed} failed")
    if failed:
        print(f"  STATUS: PREFLIGHT FAILED - check fixes above and {TRIPLETS}")
    else:
        print("  STATUS: PREFLIGHT PASSED - safe to proceed with COAWST execution")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
