#!/usr/bin/env python3
"""Preflight check for the CWatM Knowledge Infrastructure."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


MODEL_ID = "CWatM"
KI_DIR = Path(__file__).resolve().parent
MODEL_REPO = Path("KISSPATH_KI_ROOT/CWatM/source/repo")
ENTRYPOINT = MODEL_REPO / "run_cwatm.py"
PYTHON = Path("KISSPATH_PYTHON_ENV/bin/python")
LD_PRELOAD = "/lib/x86_64-linux-gnu/libstdc++.so.6"
ROUTING_SO = (
    MODEL_REPO
    / "cwatm"
    / "hydrological_modules"
    / "routing_reservoirs"
    / "t5_linux.so"
)

CHECKS: list[dict[str, object]] = []


def emit_report(model_id: str, checks: list[dict[str, object]]) -> None:
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}))
    sys.exit(0 if all(c["status"] == "pass" or not c.get("critical") for c in checks) else 1)


def add_check(
    kind: str,
    subject: str | Path,
    critical: bool,
    passed: bool,
    fix: str = "",
    detail: str = "",
) -> None:
    status = "pass" if passed else "fail"
    check = {
        "kind": kind,
        "subject": str(subject),
        "critical": critical,
        "status": status,
        "fix": "" if passed else fix,
    }
    if detail:
        check["detail"] = detail
    CHECKS.append(check)

    label = "OK" if passed else "FAIL"
    print(f"  {label:<5} {kind}: {subject}")
    if detail:
        print(f"        {detail}")
    if not passed and fix:
        print(f"        Fix: {fix}")


def check_file(
    path: Path,
    label: str,
    critical: bool = True,
    executable: bool = False,
    realpath_subject: bool = True,
) -> None:
    real = path.resolve(strict=False)
    subject = real if realpath_subject else path
    if not path.is_file():
        add_check(
            "data",
            subject,
            critical,
            False,
            f"Restore {label}; see diagnostics/triplets.yaml before attempting a workaround.",
            label,
        )
        return
    if executable and not os.access(path, os.X_OK):
        add_check(
            "binary",
            subject,
            critical,
            False,
            f"chmod +x {real}; see diagnostics/triplets.yaml if execution still fails.",
            f"{label} exists but is not executable",
        )
        return
    detail = label
    if not realpath_subject:
        detail = f"{label}; realpath={real}"
    add_check("binary" if executable else "data", subject, critical, True, detail=detail)


def check_dir(path: Path, label: str, critical: bool = True, min_items: int = 1) -> None:
    real = path.resolve(strict=False)
    if not path.is_dir():
        add_check(
            "data",
            real,
            critical,
            False,
            f"Restore {label}; check diagnostics/triplets.yaml for known CWatM layout fixes.",
            label,
        )
        return
    n_items = len(list(path.iterdir()))
    add_check(
        "data",
        real,
        critical,
        n_items >= min_items,
        f"{label} is empty or incomplete; restore KI contents and review diagnostics/triplets.yaml.",
        f"{label} ({n_items} items)",
    )


def run_hydro_python(code: str, label: str, critical: bool = True) -> None:
    env = os.environ.copy()
    env["LD_PRELOAD"] = LD_PRELOAD
    env["PYTHONPATH"] = str(MODEL_REPO)
    subject = f"{PYTHON} -c {label}"
    if not PYTHON.is_file() or not os.access(PYTHON, os.X_OK):
        add_check(
            "run",
            PYTHON,
            critical,
            False,
            "Restore KISSPATH_PYTHON_ENV/bin/python; see diagnostics/triplets.yaml.",
            label,
        )
        return
    proc = subprocess.run(
        [str(PYTHON), "-c", code],
        cwd=str(KI_DIR),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
    )
    output = (proc.stdout + proc.stderr).strip()
    add_check(
        "run",
        subject,
        critical,
        proc.returncode == 0,
        f"Run with {PYTHON} and LD_PRELOAD={LD_PRELOAD}; check diagnostics/triplets.yaml.",
        output[-300:] if output else label,
    )


def check_import(module: str, critical: bool = True) -> None:
    code = (
        "import importlib\n"
        f"importlib.import_module({module!r})\n"
        f"print('import {module} ok')\n"
    )
    env = os.environ.copy()
    env["LD_PRELOAD"] = LD_PRELOAD
    env["PYTHONPATH"] = str(MODEL_REPO)
    subject = f"{PYTHON} import {module}"
    if not PYTHON.is_file() or not os.access(PYTHON, os.X_OK):
        add_check(
            "import",
            subject,
            critical,
            False,
            "Restore the HydroCraft Python environment; see diagnostics/triplets.yaml.",
        )
        return
    proc = subprocess.run(
        [str(PYTHON), "-c", code],
        cwd=str(KI_DIR),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
    )
    output = (proc.stdout + proc.stderr).strip()
    add_check(
        "import",
        subject,
        critical,
        proc.returncode == 0,
        f"Install/fix {module} in {PYTHON}; for GDAL TLS errors use LD_PRELOAD={LD_PRELOAD}; see diagnostics/triplets.yaml.",
        output[-300:] if output else f"import {module}",
    )


def check_entrypoint_starts() -> None:
    env = os.environ.copy()
    env["LD_PRELOAD"] = LD_PRELOAD
    env["PYTHONPATH"] = str(MODEL_REPO)
    real_entrypoint = ENTRYPOINT.resolve(strict=False)
    proc = subprocess.run(
        [str(PYTHON), str(ENTRYPOINT)],
        cwd=str(MODEL_REPO),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
    )
    output = proc.stdout + proc.stderr
    started = proc.returncode == 0 and "CWATM - Community Water Model" in output
    add_check(
        "binary",
        real_entrypoint,
        True,
        started,
        f"Run {PYTHON} {real_entrypoint} from {MODEL_REPO}; if GDAL fails, use LD_PRELOAD={LD_PRELOAD}; then consult diagnostics/triplets.yaml.",
        "CWatM entry point starts and prints usage with no settings file"
        if started
        else output[-300:].strip(),
    )


def main() -> None:
    print(f"{' PREFLIGHT: CWatM ':=^60}")
    print()

    check_file(
        PYTHON,
        "HydroCraft Python interpreter",
        critical=True,
        executable=True,
        realpath_subject=False,
    )
    check_dir(KI_DIR / "tools", "KI tools directory", critical=True, min_items=7)
    for tool in (
        "build_cwatm_ancillary.py",
        "build_cwatm_static.py",
        "build_cwatm_waterbodies.py",
        "convert_forcing_to_cwatm.py",
        "convert_soil_to_cwatm.py",
        "parse_cwatm_output.py",
        "run_cwatm_wrapper.py",
    ):
        check_file(KI_DIR / "tools" / tool, f"KI tool {tool}", critical=True)

    for required in (
        ("knowledge_infrastructure.yaml", "KI manifest"),
        ("dag.yaml", "KDT DAG"),
        ("diagnostics/triplets.yaml", "diagnostic triplets for recovery"),
    ):
        check_file(KI_DIR / required[0], required[1], critical=True)

    check_dir(MODEL_REPO, "CWatM source repository", critical=True)
    check_file(ENTRYPOINT, "CWatM model entry point from models DB", critical=True)
    check_file(MODEL_REPO / "requirements.txt", "CWatM requirements file", critical=True)
    check_file(MODEL_REPO / "cwatm" / "metaNetcdf.xml", "CWatM NetCDF metadata", critical=True)
    check_file(
        MODEL_REPO / "Tutorials" / "01_Turn-ON" / "settings_Rhine-30min_Tutorial-1.ini",
        "shipped tutorial settings file",
        critical=False,
    )
    check_file(ROUTING_SO, "CWatM C++ kinematic-routing shared library", critical=True)

    for module in (
        "numpy",
        "scipy",
        "netCDF4",
        "osgeo.gdal",
        "rasterio",
        "pandas",
        "ki_tools_common.metrics",
        "cwatm.management_modules.globals",
    ):
        check_import(module, critical=True)

    run_hydro_python(
        "import ctypes\n"
        f"ctypes.CDLL({str(ROUTING_SO)!r})\n"
        "print('routing shared library loaded')\n",
        "load CWatM routing shared library",
        critical=True,
    )
    check_entrypoint_starts()

    passed = sum(1 for c in CHECKS if c["status"] == "pass")
    failed = len(CHECKS) - passed
    print()
    print(f"  Results: {passed} passed, {failed} failed")
    if failed:
        print("  STATUS: PREFLIGHT FAILED; apply fixes above, then check diagnostics/triplets.yaml.")
    else:
        print("  STATUS: PREFLIGHT PASSED; model package is ready for execution.")

    emit_report(MODEL_ID, CHECKS)


if __name__ == "__main__":
    main()
