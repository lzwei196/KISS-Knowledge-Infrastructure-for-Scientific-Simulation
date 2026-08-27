#!/usr/bin/env python3
"""
Preflight check for the SWAT+ Knowledge Infrastructure.

This script verifies the executable, Python support environment, bundled
diagnostics, and runnable input deck before any model execution workflow starts.
It must finish with PREFLIGHT_REPORT=<json> for the KDT gate.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


MODEL_ID = "SWAT+"
KI_DIR = Path(__file__).resolve().parent
HYDRO_PYTHON = Path("KISSPATH_PYTHON_ENV/bin/python3")
HYDRO_SITE_PACKAGES = Path(
    "KISSPATH_PYTHON_ENV/lib/python3.12/site-packages"
)
PRIMARY_BINARY = Path(
    "KISSPATH_KI_ROOT/SWAT_Plus/test_rev59/swatplus_rev59"
)
REV59_CANDIDATES = [
    PRIMARY_BINARY,
    Path(
        "KISSPATH_OUTPUTS/chaohe_2000_2010_025deg/"
        "swatplus_cn2_test/swatplus_rev59"
    ),
]
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"
RUN_TXTINOUT = KI_DIR / "calib" / "run_txtinout"
REQUIRED_TXTINOUT_FILES = [
    "file.cio",
    "time.sim",
    "print.prt",
    "object.cnt",
    "soils.sol",
    "weather-sta.cli",
    "weather-wgn.cli",
    "pcp.cli",
    "tmp.cli",
    "slr.cli",
    "hmd.cli",
    "wnd.cli",
]
REQUIRED_TOOL_IMPORTS = [
    ("numpy", "pip install numpy"),
    ("pandas", "pip install pandas"),
    ("yaml", "pip install pyyaml"),
    ("rasterio", "pip install rasterio"),
    ("geopandas", "pip install geopandas"),
    ("netCDF4", "pip install netCDF4"),
    ("ki_tools_common", "install/repair HydroCraft ki_tools_common in python_env"),
    ("ki_tools_common.load_forcing", "install/repair HydroCraft ki_tools_common"),
    ("ki_tools_common.soil_utils", "install/repair HydroCraft ki_tools_common"),
]
COMMON_DATA_DIRS = [
    (Path("KISSPATH_OBS"), "Observation data"),
    (Path("KISSPATH_FORCING"), "Forcing data"),
    (Path("KISSPATH_STATIC"), "DEM data"),
    (Path("KISSPATH_STATIC"), "Soil data"),
]


checks: list[dict[str, object]] = []


def add_check(
    kind: str,
    subject: str | Path,
    critical: bool,
    status: str,
    fix: str = "",
) -> bool:
    """Record and print a KDT preflight check."""
    subject_s = str(subject)
    check = {
        "kind": kind,
        "subject": subject_s,
        "critical": bool(critical),
        "status": status,
        "fix": fix if status == "fail" else "",
    }
    checks.append(check)

    label = "OK" if status == "pass" else ("FAIL" if critical else "WARN")
    print(f"  {label:<5} {kind}: {subject_s}")
    if status == "fail" and fix:
        print(f"        Fix: {fix}")
    return status == "pass"


def emit_report(model_id: str, report_checks: list[dict[str, object]]) -> None:
    print(
        "PREFLIGHT_REPORT="
        + json.dumps({"model_id": model_id, "checks": report_checks}, sort_keys=True)
    )
    critical_failed = any(
        c["status"] == "fail" and bool(c.get("critical")) for c in report_checks
    )
    sys.exit(1 if critical_failed else 0)


def check_file(path: Path, label: str, critical: bool, executable: bool = False) -> bool:
    subject = path.resolve() if path.exists() else path
    if not path.is_file():
        return add_check(
            "data",
            subject,
            critical,
            "fail",
            f"restore {path}; see {TRIPLETS} for recovery",
        )
    if executable and not os.access(path, os.X_OK):
        return add_check(
            "binary",
            path.resolve(),
            critical,
            "fail",
            f"chmod +x {path}; see {TRIPLETS} for recovery",
        )
    kind = "binary" if executable else "data"
    return add_check(kind, path.resolve(), critical, "pass")


def check_dir(path: Path, label: str, critical: bool, require_nonempty: bool = True) -> bool:
    subject = path.resolve() if path.exists() else path
    if not path.is_dir():
        return add_check(
            "data",
            subject,
            critical,
            "fail",
            f"restore {label} at {path}; see {TRIPLETS} for recovery",
        )
    if require_nonempty and not any(path.iterdir()):
        return add_check(
            "data",
            path.resolve(),
            critical,
            "fail",
            f"populate {label} at {path}; see {TRIPLETS} for recovery",
        )
    return add_check("data", path.resolve(), critical, "pass")


def choose_binary() -> Path:
    for candidate in REV59_CANDIDATES:
        if candidate.is_file():
            return candidate
    return PRIMARY_BINARY


def check_binary_starts(binary: Path) -> bool:
    subject = f"{binary.resolve() if binary.exists() else binary} startup"
    if not binary.is_file() or not os.access(binary, os.X_OK):
        return add_check(
            "run",
            subject,
            True,
            "fail",
            f"restore executable binary first; see {TRIPLETS}",
        )

    try:
        with tempfile.TemporaryDirectory(prefix="swatplus_preflight_") as tmpdir:
            proc = subprocess.run(
                [str(binary)],
                cwd=tmpdir,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=5,
                check=False,
            )
    except subprocess.TimeoutExpired:
        return add_check(
            "run",
            subject,
            True,
            "fail",
            f"binary did not reach startup banner within 5s; see {TRIPLETS}",
        )
    except OSError as exc:
        return add_check(
            "run",
            subject,
            True,
            "fail",
            f"cannot start binary: {exc}; see {TRIPLETS}",
        )

    output = proc.stdout or ""
    if "SWAT+" in output and "Revision 59.3" in output:
        return add_check("run", subject, True, "pass")

    excerpt = " ".join(output.split()[:25]) or f"exit code {proc.returncode}"
    return add_check(
        "run",
        subject,
        True,
        "fail",
        f"expected SWAT+ Revision 59.3 startup banner, got: {excerpt}; see {TRIPLETS}",
    )


def check_python_environment() -> None:
    if HYDRO_PYTHON.is_file() and os.access(HYDRO_PYTHON, os.X_OK):
        add_check(
            "import",
            f"HydroCraft python_env interpreter {HYDRO_PYTHON}",
            True,
            "pass",
        )
        add_check("data", HYDRO_SITE_PACKAGES.resolve(), True, "pass") if HYDRO_SITE_PACKAGES.is_dir() else add_check(
            "data",
            HYDRO_SITE_PACKAGES,
            True,
            "fail",
            f"restore python_env site-packages at {HYDRO_SITE_PACKAGES}; see {TRIPLETS}",
        )
    else:
        add_check(
            "import",
            f"HydroCraft python_env interpreter {HYDRO_PYTHON}",
            True,
            "fail",
            f"restore executable interpreter at {HYDRO_PYTHON}; see {TRIPLETS}",
        )

    for module, fix in REQUIRED_TOOL_IMPORTS:
        if not HYDRO_PYTHON.is_file():
            add_check(
                "import",
                f"{module} via {HYDRO_PYTHON}",
                True,
                "fail",
                f"restore {HYDRO_PYTHON} before checking imports; see {TRIPLETS}",
            )
            continue
        code = (
            "import importlib; "
            f"importlib.import_module({module!r}); "
            f"print({module!r})"
        )
        proc = subprocess.run(
            [str(HYDRO_PYTHON), "-c", code],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=10,
        )
        if proc.returncode == 0:
            add_check("import", f"{module} via {HYDRO_PYTHON}", True, "pass")
        else:
            detail = (proc.stderr or proc.stdout).strip().splitlines()[-1:]
            suffix = f" ({detail[0]})" if detail else ""
            add_check(
                "import",
                f"{module} via {HYDRO_PYTHON}",
                True,
                "fail",
                f"{fix}{suffix}; see {TRIPLETS}",
            )


def check_required_txtinout() -> None:
    if not check_dir(RUN_TXTINOUT, "bundled calibration TxtInOut", True):
        return
    for name in REQUIRED_TXTINOUT_FILES:
        check_file(RUN_TXTINOUT / name, f"TxtInOut {name}", True)


def check_common_data() -> None:
    for path, label in COMMON_DATA_DIRS:
        check_dir(path, label, False)


def main() -> None:
    print("=" * 60)
    print("  PREFLIGHT CHECK: SWAT+")
    print("=" * 60)
    print()

    binary = choose_binary()
    check_file(binary, "SWAT+ Rev 59.3 binary", True, executable=True)
    check_binary_starts(binary)
    print(f"  INFO  Run with: python tools/s8/run_swatplus.py {binary} <TxtInOut>")
    print()

    check_python_environment()
    print()

    check_required_txtinout()
    print()

    check_file(TRIPLETS, "Diagnostic triplets", True)
    if TRIPLETS.is_file():
        print(f"  INFO  Diagnostic triplets available at: {TRIPLETS}")
        print("        If the model fails, check triplets FIRST for known fixes.")
    print()

    check_common_data()
    print()

    passed = sum(1 for c in checks if c["status"] == "pass")
    failed = sum(1 for c in checks if c["status"] == "fail")
    critical_failed = sum(
        1 for c in checks if c["status"] == "fail" and bool(c.get("critical"))
    )
    print(f"  Results: {passed} passed, {failed} failed")
    if critical_failed:
        print("  STATUS: PREFLIGHT FAILED - fix critical issues before running")
    else:
        print("  STATUS: PREFLIGHT PASSED - safe to proceed with model execution")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
