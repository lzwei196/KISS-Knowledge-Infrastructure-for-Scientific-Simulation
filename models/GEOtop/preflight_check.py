#!/usr/bin/env python3
"""Contract preflight check for the GEOtop Knowledge Infrastructure."""

import json
import os
import subprocess
import sys
from pathlib import Path


MODEL_ID = "GEOtop"
KI_DIR = Path(__file__).resolve().parent
MODEL_ROOT = KI_DIR.parent
GEOTOP_BINARY = MODEL_ROOT / "geotop"
HYDRO_PYTHON = Path("KISSPATH_PYTHON_ENV/bin/python_with_gdal")
FALLBACK_HYDRO_PYTHON = Path("KISSPATH_PYTHON_ENV/bin/python")
DIAGNOSTIC_TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"


checks = []


def record(kind, subject, critical, ok, fix):
    status = "pass" if ok else "fail"
    checks.append(
        {
            "kind": kind,
            "subject": str(subject),
            "critical": bool(critical),
            "status": status,
            "fix": "" if ok else fix,
        }
    )
    label = "OK" if ok else "FAIL"
    print(f"  {label:<5} {kind}: {subject}")
    if not ok:
        print(f"        Fix: {fix}")


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}))
    failed_critical = any(c["status"] == "fail" and c.get("critical") for c in checks)
    sys.exit(1 if failed_critical else 0)


def check_file(path, label, critical=True, executable=False):
    path = Path(path)
    subject = path.resolve(strict=False)
    ok = path.is_file() and (not executable or os.access(path, os.X_OK))
    if path.is_file() and executable and not os.access(path, os.X_OK):
        fix = f"chmod +x {path}; see {DIAGNOSTIC_TRIPLETS}"
    else:
        fix = f"Restore {label} at {path}; see {DIAGNOSTIC_TRIPLETS}"
    record("binary" if executable else "data", subject, critical, ok, fix)
    return ok


def check_dir(path, label, critical=True, require_nonempty=True):
    path = Path(path)
    ok = path.is_dir() and (not require_nonempty or any(path.iterdir()))
    detail = path.resolve(strict=False)
    fix = f"Restore {label} at {path}; see {DIAGNOSTIC_TRIPLETS}"
    record("data", detail, critical, ok, fix)
    return ok


def check_import(module, critical=True, python_exe=None):
    python_exe = Path(python_exe or HYDRO_PYTHON)
    subject = f"{python_exe}: import {module}"
    cmd = [str(python_exe), "-c", f"import importlib; importlib.import_module({module!r})"]
    try:
        proc = subprocess.run(cmd, text=True, capture_output=True, timeout=20)
        ok = proc.returncode == 0
        err = (proc.stderr or proc.stdout).strip().splitlines()
        reason = f" ({err[-1]})" if err else ""
    except Exception as exc:
        ok = False
        reason = f" ({type(exc).__name__}: {exc})"
    fix = (
        f"Install/repair Python dependency {module!r} in "
        f"KISSPATH_PYTHON_ENV; see {DIAGNOSTIC_TRIPLETS}{reason}"
    )
    record("import", subject, critical, ok, fix)
    return ok


def check_python_tool_syntax(tool_paths, critical=True):
    subject = f"{HYDRO_PYTHON}: py_compile KI tools"
    cmd = [str(HYDRO_PYTHON), "-m", "py_compile"] + [str(p) for p in tool_paths]
    try:
        proc = subprocess.run(cmd, text=True, capture_output=True, timeout=30)
        ok = proc.returncode == 0
        err = (proc.stderr or proc.stdout).strip().splitlines()
        reason = f" ({err[-1]})" if err else ""
    except Exception as exc:
        ok = False
        reason = f" ({type(exc).__name__}: {exc})"
    fix = f"Fix syntax/import-time compile errors in tools/; see {DIAGNOSTIC_TRIPLETS}{reason}"
    record("import", subject, critical, ok, fix)
    return ok


def check_geotop_starts(binary):
    binary = Path(binary)
    real_binary = binary.resolve(strict=False)
    subject = f"{real_binary}: startup banner"
    if not binary.is_file() or not os.access(binary, os.X_OK):
        record(
            "run",
            subject,
            True,
            False,
            f"Restore executable GEOtop binary at {binary}; see {DIAGNOSTIC_TRIPLETS}",
        )
        return False
    try:
        proc = subprocess.run(
            [str(binary), "__preflight_missing_sim_dir__"],
            cwd=str(KI_DIR),
            text=True,
            capture_output=True,
            timeout=5,
        )
        output = (proc.stdout or "") + (proc.stderr or "")
        ok = "Geotop 3.0.0" in output or "geotop:STATEMENT" in output
        reason = " expected startup banner not found" if not ok else ""
    except Exception as exc:
        ok = False
        reason = f" {type(exc).__name__}: {exc}"
    fix = f"Rebuild GEOtop and restore executable at {binary}; see {DIAGNOSTIC_TRIPLETS}.{reason}"
    record("run", subject, True, ok, fix)
    return ok


def main():
    print("=" * 60)
    print("  PREFLIGHT CHECK: GEOtop")
    print("=" * 60)

    python_exe = HYDRO_PYTHON if HYDRO_PYTHON.is_file() else FALLBACK_HYDRO_PYTHON
    record(
        "data",
        python_exe.resolve(strict=False),
        True,
        python_exe.is_file() and os.access(python_exe, os.X_OK),
        f"Restore HydroCraft Python environment at {python_exe}; see {DIAGNOSTIC_TRIPLETS}",
    )

    check_file(GEOTOP_BINARY, "GEOtop binary", critical=True, executable=True)
    check_geotop_starts(GEOTOP_BINARY)

    for rel in (
        "SKILL.md",
        "knowledge_infrastructure.yaml",
        "dag.yaml",
        "docs/format_spec.yaml",
        "diagnostics/triplets.yaml",
    ):
        check_file(KI_DIR / rel, rel, critical=True)

    tool_files = [
        KI_DIR / "tools" / "build_domain.py",
        KI_DIR / "tools" / "convert_forcing.py",
        KI_DIR / "tools" / "convert_soil.py",
        KI_DIR / "tools" / "parse_output.py",
        KI_DIR / "tools" / "read_modis_lst.py",
        KI_DIR / "tools" / "run_geotop.py",
    ]
    check_dir(KI_DIR / "tools", "KI tools directory", critical=True)
    for tool in tool_files:
        check_file(tool, tool.relative_to(KI_DIR), critical=True)
    check_python_tool_syntax(tool_files, critical=True)

    for module in (
        "numpy",
        "pandas",
        "rasterio",
        "pyproj",
        "osgeo.gdal",
        "ki_tools_common.load_forcing",
        "ki_tools_common.humidity",
        "ki_tools_common.soil_utils",
        "ki_tools_common.terrain_ops.delineate",
        "whitebox",
    ):
        check_import(module, critical=True, python_exe=python_exe)

    cmfd_root = Path("KISSPATH_FORCING/Data_forcing_03hr_010deg")
    check_dir(cmfd_root, "CMFD V2.0 3-hourly forcing root", critical=True)
    for subdir in ("Temp", "Prec", "SRad", "LRad", "Wind", "SHum", "Pres"):
        check_dir(cmfd_root / subdir, f"CMFD {subdir} subdirectory", critical=True)

    check_file(
        Path("KISSPATH_STATIC/HWSD_RASTER/hwsd.bil"),
        "HWSD raster",
        critical=True,
    )
    check_file(
        Path("KISSPATH_STATIC/HWSD_DATA.csv"),
        "HWSD attribute table",
        critical=True,
    )

    check_dir(Path("KISSPATH_FORCING"), "MSWX forcing root", critical=False)
    check_dir(Path("KISSPATH_DATA/obs/nasa/modis_lst"), "MODIS LST observations", critical=False)

    passed = sum(1 for c in checks if c["status"] == "pass")
    failed = len(checks) - passed
    print()
    print(f"  Results: {passed} passed, {failed} failed")
    if failed:
        print(f"  STATUS: PREFLIGHT FAILED - check fixes above and {DIAGNOSTIC_TRIPLETS}")
    else:
        print("  STATUS: PREFLIGHT PASSED - safe to proceed with GEOtop execution")
    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
