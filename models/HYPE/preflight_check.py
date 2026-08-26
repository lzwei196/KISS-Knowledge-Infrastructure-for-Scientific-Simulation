#!/usr/bin/env python3
"""
Preflight check for the HydroCraft HYPE KI.

This script verifies the real HYPE executable, the HydroCraft Python
environment used by this KI's tools, reference/demo model inputs, and recovery
diagnostics before a model run starts.
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


MODEL_ID = "HYPE"
HYDROCRAFT_ROOT = Path("KISSPATH_ROOT")
KI_DIR = Path(__file__).resolve().parent
HYPE_BINARY = HYDROCRAFT_ROOT / "model" / "hype" / "hype"
HYPE_DEMO = HYDROCRAFT_ROOT / "model" / "hype" / "demo"
PYTHON_ENV = HYDROCRAFT_ROOT / "python_env" / "bin" / "python"
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"

CHECKS = []


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}))
    ready = all(c["status"] == "pass" or not c.get("critical") for c in checks)
    sys.exit(0 if ready else 1)


def add_check(kind, subject, critical, status, fix=""):
    check = {
        "kind": kind,
        "subject": str(subject),
        "critical": bool(critical),
        "status": status,
        "fix": fix,
    }
    CHECKS.append(check)
    label = "OK" if status == "pass" else ("FAIL" if critical else "WARN")
    print(f"  {label:<5} {kind}: {subject}")
    if status != "pass" and fix:
        print(f"        Fix: {fix}")


def check_file(path, label, critical=True, executable=False, subject_realpath=False):
    path = Path(path)
    subject = path
    if path.exists():
        subject = path.resolve() if subject_realpath else path
    if not path.is_file():
        add_check(
            "binary" if executable else "data",
            subject,
            critical,
            "fail",
            f"Restore {label} at {path}; see {TRIPLETS} for recovery.",
        )
        return False
    if executable and not os.access(path, os.X_OK):
        add_check(
            "binary",
            subject,
            critical,
            "fail",
            f"Run chmod +x {path}; see {TRIPLETS} for recovery.",
        )
        return False
    add_check("binary" if executable else "data", subject, critical, "pass")
    return True


def check_dir(path, label, critical=True, non_empty=False):
    path = Path(path)
    if not path.is_dir():
        add_check(
            "data",
            path,
            critical,
            "fail",
            f"Restore {label} directory at {path}; see {TRIPLETS} for recovery.",
        )
        return False
    if non_empty and not any(path.iterdir()):
        add_check(
            "data",
            path,
            critical,
            "fail",
            f"Populate {label} directory at {path}; see {TRIPLETS} for recovery.",
        )
        return False
    add_check("data", path, critical, "pass")
    return True


def check_binary_starts(binary_path):
    binary_path = Path(binary_path)
    subject = binary_path.resolve() if binary_path.exists() else binary_path
    if not binary_path.is_file() or not os.access(binary_path, os.X_OK):
        add_check(
            "run",
            subject,
            True,
            "fail",
            f"Fix executable availability first: {binary_path}; see {TRIPLETS}.",
        )
        return

    try:
        with tempfile.TemporaryDirectory(prefix="hype_preflight_") as tmp:
            infodir = tmp + os.sep
            result = subprocess.run(
                [str(binary_path), infodir],
                cwd=tmp,
                capture_output=True,
                text=True,
                timeout=5,
            )
            combined = "\n".join([result.stdout or "", result.stderr or ""])
            log_mentions_info = "info.txt" in combined
            for log in Path(tmp).glob("hyss_*.log"):
                try:
                    if "info.txt" in log.read_text(errors="ignore"):
                        log_mentions_info = True
                        break
                except OSError:
                    pass

        if result.returncode in (0, 1) or log_mentions_info:
            add_check("run", subject, True, "pass")
        else:
            add_check(
                "run",
                subject,
                True,
                "fail",
                f"HYPE started but returned unexpected code {result.returncode}; see {TRIPLETS}.",
            )
    except subprocess.TimeoutExpired:
        add_check(
            "run",
            subject,
            True,
            "fail",
            f"HYPE did not return within 5 seconds during startup check; see {TRIPLETS}.",
        )
    except OSError as exc:
        add_check(
            "run",
            subject,
            True,
            "fail",
            f"Could not start HYPE executable: {exc}; see {TRIPLETS}.",
        )


def python_env():
    env = os.environ.copy()
    # The HydroCraft interpreter already adds its site-packages directory.
    # Putting site-packages in PYTHONPATH makes Python process .pth files while
    # a legacy pathlib backport can shadow the stdlib pathlib module.
    env.pop("PYTHONPATH", None)
    return env


def check_import(module):
    subject = f"{PYTHON_ENV}: import {module}"
    if not PYTHON_ENV.is_file() or not os.access(PYTHON_ENV, os.X_OK):
        add_check(
            "import",
            subject,
            True,
            "fail",
            f"Restore HydroCraft Python interpreter at {PYTHON_ENV}; see {TRIPLETS}.",
        )
        return
    result = subprocess.run(
        [str(PYTHON_ENV), "-c", f"import {module}"],
        capture_output=True,
        text=True,
        env=python_env(),
        cwd=str(KI_DIR),
        timeout=10,
    )
    if result.returncode == 0:
        add_check("import", subject, True, "pass")
    else:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        message = detail[-1] if detail else "import failed"
        add_check(
            "import",
            subject,
            True,
            "fail",
            f"Install/fix {module} in {PYTHON_ENV}: {message}; see {TRIPLETS}.",
        )


def check_common_data():
    common_data = [
        (HYDROCRAFT_ROOT / "data" / "obs", "observation data"),
        (Path("KISSPATH_FORCING"), "forcing data"),
        (HYDROCRAFT_ROOT / "data" / "dem", "DEM data"),
        (HYDROCRAFT_ROOT / "data" / "soil", "soil data"),
    ]
    for path, label in common_data:
        check_dir(path, label, critical=False, non_empty=False)


def main():
    print("=" * 60)
    print("  PREFLIGHT CHECK: HYPE")
    print("=" * 60)
    print()

    check_file(HYPE_BINARY, "HYPE v5.35.0 binary", critical=True, executable=True, subject_realpath=True)
    check_binary_starts(HYPE_BINARY)

    check_file(PYTHON_ENV, "HydroCraft Python interpreter", critical=True, executable=True)
    for module in [
        "numpy",
        "pandas",
        "geopandas",
        "rasterio",
        "shapely",
        "xarray",
        "matplotlib",
        "ki_tools_common",
    ]:
        check_import(module)

    for relpath in [
        "tools/s3_forcing_preparation/convert_forcing_to_hype.py",
        "tools/s4_geodata_generation/generate_geodata.py",
        "tools/s5_parameter_setup/setup_parameters.py",
        "tools/s7_execution/configure_info.py",
        "tools/s7_execution/run_hype.py",
        "tools/s8_output_analysis/parse_hype_output.py",
    ]:
        check_file(KI_DIR / relpath, f"KI tool {relpath}", critical=True)

    for path, label in [
        (HYPE_DEMO / "info.txt", "HYPE demo info.txt"),
        (HYPE_DEMO / "modelfiles" / "GeoData.txt", "HYPE demo GeoData.txt"),
        (HYPE_DEMO / "modelfiles" / "GeoClass.txt", "HYPE demo GeoClass.txt"),
        (HYPE_DEMO / "modelfiles" / "par.txt", "HYPE demo par.txt"),
        (HYPE_DEMO / "forcingdir" / "Pobs.txt", "HYPE demo precipitation forcing"),
        (HYPE_DEMO / "forcingdir" / "Tobs.txt", "HYPE demo temperature forcing"),
        (HYPE_DEMO / "forcingdir" / "ForcKey.txt", "HYPE demo forcing key"),
    ]:
        check_file(path, label, critical=True)

    check_file(TRIPLETS, "diagnostic triplets", critical=True)
    check_common_data()

    print()
    passed = sum(1 for c in CHECKS if c["status"] == "pass")
    failed = len(CHECKS) - passed
    print(f"  Results: {passed} passed, {failed} failed")
    if any(c["status"] == "fail" and c["critical"] for c in CHECKS):
        print(f"  STATUS: PREFLIGHT FAILED - fix blockers above; start with {TRIPLETS}")
    else:
        print("  STATUS: PREFLIGHT PASSED - critical checks are ready")

    emit_report(MODEL_ID, CHECKS)


if __name__ == "__main__":
    main()
