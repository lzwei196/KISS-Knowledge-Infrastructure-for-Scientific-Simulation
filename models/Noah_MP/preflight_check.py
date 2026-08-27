#!/usr/bin/env python3
"""KDT contract preflight for the Noah-MP HRLDAS KI."""

import json
import os
import subprocess
import sys
import tempfile


MODEL_ID = "Noah-MP"
KI_DIR = os.path.dirname(os.path.abspath(__file__))
HYDROCRAFT_PYTHON = "KISSPATH_PYTHON_ENV/bin/python"
SOURCE_DIR = "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/Noah_MP/source/repo"
BINARY = "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/Noah_MP/source/hrldas/hrldas/run/hrldas.exe"
PARAM_TABLES = [
    "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/Noah_MP/source/hrldas/hrldas/run/NoahmpTable.TBL",
    os.path.join(SOURCE_DIR, "parameters", "NoahmpTable.TBL"),
]


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}, sort_keys=True))
    sys.exit(0 if all(c["status"] == "pass" or not c.get("critical") for c in checks) else 1)


def add_check(checks, kind, subject, critical, status, fix=""):
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


def check_file(checks, path, label, critical=True, executable=False, min_size=1):
    subject = os.path.realpath(path)
    fix = f"Restore {label}; diagnostics/triplets.yaml may have matching recovery steps."
    if not os.path.isfile(path):
        add_check(checks, "data", subject, critical, "fail", fix)
        return False
    if min_size and os.path.getsize(path) < min_size:
        add_check(checks, "data", subject, critical, "fail", f"{label} is empty or truncated; restore it.")
        return False
    if executable and not os.access(path, os.X_OK):
        add_check(checks, "binary", subject, critical, "fail", f"Run chmod +x {path}; then rerun preflight.")
        return False
    kind = "binary" if executable else "data"
    add_check(checks, kind, subject, critical, "pass")
    return True


def check_dir(checks, path, label, critical=True, required_files=None):
    subject = os.path.realpath(path)
    if not os.path.isdir(path):
        add_check(checks, "data", subject, critical, "fail", f"Restore {label}; check diagnostics/triplets.yaml.")
        return False
    missing = []
    for rel in required_files or []:
        if not os.path.isfile(os.path.join(path, rel)):
            missing.append(rel)
    if missing:
        add_check(
            checks,
            "data",
            subject,
            critical,
            "fail",
            f"Missing required files under {label}: {', '.join(missing)}",
        )
        return False
    add_check(checks, "data", subject, critical, "pass")
    return True


def check_imports(checks, modules):
    if not os.path.isfile(HYDROCRAFT_PYTHON):
        add_check(
            checks,
            "import",
            HYDROCRAFT_PYTHON,
            True,
            "fail",
            "Restore KISSPATH_PYTHON_ENV; this KI's Python tools depend on it.",
        )
        return

    code = "import importlib, sys\nmods = sys.argv[1:]\nfor m in mods:\n    importlib.import_module(m)\n"
    for module, critical in modules:
        result = subprocess.run(
            [HYDROCRAFT_PYTHON, "-c", code, module],
            text=True,
            capture_output=True,
            timeout=20,
        )
        if result.returncode == 0:
            add_check(checks, "import", f"{HYDROCRAFT_PYTHON}:{module}", critical, "pass")
        else:
            detail = (result.stderr or result.stdout).strip().splitlines()
            msg = detail[-1] if detail else "import failed"
            add_check(
                checks,
                "import",
                f"{HYDROCRAFT_PYTHON}:{module}",
                critical,
                "fail",
                f"Install/fix {module} in HydroCraft python_env ({msg}); see diagnostics/triplets.yaml.",
            )


def check_ldd(checks, binary):
    try:
        result = subprocess.run(["ldd", binary], text=True, capture_output=True, timeout=10)
    except Exception as exc:
        add_check(checks, "binary", f"ldd {os.path.realpath(binary)}", True, "fail", f"Cannot inspect binary libraries: {exc}")
        return
    output = (result.stdout or "") + (result.stderr or "")
    if result.returncode != 0 or "not found" in output:
        missing = [line.strip() for line in output.splitlines() if "not found" in line]
        add_check(
            checks,
            "binary",
            f"ldd {os.path.realpath(binary)}",
            True,
            "fail",
            "Install missing shared libraries: " + ("; ".join(missing) if missing else output.strip()),
        )
    else:
        add_check(checks, "binary", f"ldd {os.path.realpath(binary)}", True, "pass")


def check_binary_starts(checks, binary):
    subject = os.path.realpath(binary)
    try:
        with tempfile.TemporaryDirectory(prefix="noahmp_preflight_") as run_dir:
            result = subprocess.run([binary], cwd=run_dir, text=True, capture_output=True, timeout=5)
    except subprocess.TimeoutExpired:
        add_check(checks, "run", subject, True, "fail", "Binary did not reach namelist parsing within 5s; inspect diagnostics/triplets.yaml.")
        return
    except Exception as exc:
        add_check(checks, "run", subject, True, "fail", f"Binary could not be launched: {exc}")
        return

    output = (result.stdout or "") + "\n" + (result.stderr or "")
    if "Problem reading namelist" in output or "namelist.hrldas" in output:
        add_check(checks, "run", subject, True, "pass")
    elif result.returncode == 0:
        add_check(checks, "run", subject, True, "pass")
    else:
        snippet = " ".join(output.strip().split())[:300] or f"return code {result.returncode}"
        add_check(
            checks,
            "run",
            subject,
            True,
            "fail",
            f"Binary launched but failed before expected namelist read: {snippet}; see diagnostics/triplets.yaml.",
        )


def main():
    checks = []
    print("=" * 60)
    print("  PREFLIGHT CHECK: Noah-MP HRLDAS")
    print("=" * 60)

    binary_ok = check_file(checks, BINARY, "Noah-MP HRLDAS executable", critical=True, executable=True, min_size=1024)
    if binary_ok:
        check_ldd(checks, BINARY)
        check_binary_starts(checks, BINARY)

    check_dir(
        checks,
        os.path.join(KI_DIR, "tools"),
        "KI tools directory",
        critical=True,
        required_files=[
            "build_hrldas_setup.py",
            "convert_forcing_to_noahmp.py",
            "convert_soil_to_noahmp.py",
            "parse_noahmp_output.py",
            "run_noahmp.py",
        ],
    )
    check_file(
        checks,
        os.path.join(KI_DIR, "diagnostics", "triplets.yaml"),
        "diagnostic triplets",
        critical=True,
        executable=False,
        min_size=1024,
    )
    check_file(checks, os.path.join(KI_DIR, "dag.yaml"), "DAG metadata", critical=True, min_size=1024)
    check_file(checks, os.path.join(KI_DIR, "knowledge_infrastructure.yaml"), "KI manifest", critical=True, min_size=1024)
    check_dir(
        checks,
        SOURCE_DIR,
        "Noah-MP source repository",
        critical=True,
        required_files=["parameters/NoahmpTable.TBL", "drivers/hrldas/Makefile"],
    )

    table_ok = any(os.path.isfile(path) and os.path.getsize(path) > 1024 for path in PARAM_TABLES)
    add_check(
        checks,
        "data",
        "NoahmpTable.TBL",
        True,
        "pass" if table_ok else "fail",
        "" if table_ok else "Restore NoahmpTable.TBL in the source parameters directory or compiled HRLDAS run directory; see diagnostics/triplets.yaml.",
    )

    check_imports(
        checks,
        [
            ("netCDF4", True),
            ("numpy", True),
            ("pandas", True),
            ("xarray", True),
            ("yaml", True),
            ("scipy", False),
            ("ki_tools_common", True),
        ],
    )

    failures = [c for c in checks if c["status"] != "pass" and c.get("critical")]
    if failures:
        print("\nBlockers found. Start recovery with diagnostics/triplets.yaml.")
    else:
        print("\nPreflight passed. Per-run files are still validated by tools/run_noahmp.py.")
    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
