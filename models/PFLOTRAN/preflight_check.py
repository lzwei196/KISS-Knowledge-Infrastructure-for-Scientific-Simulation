#!/usr/bin/env python3
"""Preflight check for the PFLOTRAN Knowledge Infrastructure."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


MODEL_ID = "PFLOTRAN"
KI_DIR = Path(__file__).resolve().parent
HYDROCRAFT_PYTHON = Path("KISSPATH_PYTHON_ENV/bin/python")
PFLOTRAN_BIN = Path(
    "KISSPATH_KI_ROOT/PFLOTRAN/source/repo/src/pflotran/pflotran"
)
AUTO_DISSECT_DIR = Path("KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect")
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"


checks: list[dict[str, object]] = []


def add_check(kind: str, subject: str, critical: bool, status: str, fix: str = "") -> None:
    check = {
        "kind": kind,
        "subject": subject,
        "critical": critical,
        "status": status,
        "fix": fix,
    }
    checks.append(check)
    marker = "OK" if status == "pass" else ("FAIL" if critical else "WARN")
    print(f"  {marker:<5} {kind}: {subject}")
    if status != "pass" and fix:
        print(f"        Fix: {fix}")


def emit_report(model_id: str, report_checks: list[dict[str, object]]) -> None:
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": report_checks}))
    failed_critical = any(
        c["status"] != "pass" and bool(c.get("critical")) for c in report_checks
    )
    sys.exit(1 if failed_critical else 0)


def check_file(path: Path, label: str, *, critical: bool, executable: bool = False) -> None:
    subject = str(path.resolve(strict=False))
    if not path.is_file():
        add_check(
            "data",
            subject,
            critical,
            "fail",
            f"Restore {label}; consult {TRIPLETS} for recovery.",
        )
        return
    if executable and not os.access(path, os.X_OK):
        add_check(
            "binary",
            subject,
            critical,
            "fail",
            f"Run chmod +x {path}; consult {TRIPLETS} if execution still fails.",
        )
        return
    add_check("binary" if executable else "data", subject, critical, "pass")


def check_dir(path: Path, label: str, *, critical: bool) -> None:
    subject = str(path.resolve(strict=False))
    if path.is_dir():
        add_check("data", subject, critical, "pass")
    else:
        add_check(
            "data",
            subject,
            critical,
            "fail",
            f"Restore {label}; consult {TRIPLETS} for recovery.",
        )


def check_python_interpreter() -> None:
    subject = str(HYDROCRAFT_PYTHON)
    if HYDROCRAFT_PYTHON.is_file() and os.access(HYDROCRAFT_PYTHON, os.X_OK):
        add_check("import", subject, True, "pass")
    else:
        add_check(
            "import",
            subject,
            True,
            "fail",
            f"Restore the HydroCraft Python environment at {HYDROCRAFT_PYTHON}; consult {TRIPLETS}.",
        )


def run_python_probe(label: str, code: str, *, critical: bool = True) -> None:
    subject = f"{HYDROCRAFT_PYTHON}:{label}"
    if not HYDROCRAFT_PYTHON.is_file():
        add_check(
            "import",
            subject,
            critical,
            "fail",
            f"Cannot run import probe without {HYDROCRAFT_PYTHON}; consult {TRIPLETS}.",
        )
        return

    env = os.environ.copy()
    pythonpath = [str(KI_DIR), str(AUTO_DISSECT_DIR)]
    if env.get("PYTHONPATH"):
        pythonpath.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(pythonpath)

    try:
        result = subprocess.run(
            [str(HYDROCRAFT_PYTHON), "-c", code],
            cwd=str(KI_DIR),
            env=env,
            text=True,
            capture_output=True,
            timeout=20,
        )
    except subprocess.TimeoutExpired:
        add_check(
            "import",
            subject,
            critical,
            "fail",
            f"Import probe timed out; inspect the tool and consult {TRIPLETS}.",
        )
        return

    if result.returncode == 0:
        add_check("import", subject, critical, "pass")
    else:
        detail = (result.stderr or result.stdout).strip().splitlines()
        reason = detail[-1] if detail else f"exit code {result.returncode}"
        add_check(
            "import",
            subject,
            critical,
            "fail",
            f"{reason}. Install missing packages in {HYDROCRAFT_PYTHON}'s environment; consult {TRIPLETS}.",
        )


def check_imports() -> None:
    run_python_probe(
        "core packages",
        "import numpy, h5py, netCDF4, pandas, geopandas, shapely; "
        "from ki_tools_common.units import CMFD_PRECIP_KGM2S_TO_MMDAY",
    )
    for rel_path in (
        "tools/run_pflotran.py",
        "tools/convert_forcing_to_pflotran.py",
        "tools/convert_soil_to_pflotran.py",
        "tools/parse_pflotran_output.py",
    ):
        code = (
            "import importlib.util, pathlib; "
            f"path = pathlib.Path({str(KI_DIR / rel_path)!r}); "
            "spec = importlib.util.spec_from_file_location(path.stem, path); "
            "mod = importlib.util.module_from_spec(spec); "
            "spec.loader.exec_module(mod)"
        )
        run_python_probe(rel_path, code)


def check_pflotran_starts() -> None:
    subject = str(PFLOTRAN_BIN.resolve(strict=False))
    if not (PFLOTRAN_BIN.is_file() and os.access(PFLOTRAN_BIN, os.X_OK)):
        add_check(
            "run",
            subject,
            True,
            "fail",
            f"Fix the PFLOTRAN executable at {PFLOTRAN_BIN}; consult {TRIPLETS}.",
        )
        return

    try:
        result = subprocess.run(
            [str(PFLOTRAN_BIN), "-help"],
            cwd=str(KI_DIR),
            text=True,
            capture_output=True,
            timeout=15,
        )
    except subprocess.TimeoutExpired:
        add_check(
            "run",
            subject,
            True,
            "fail",
            f"PFLOTRAN did not return from a cheap -help startup probe; consult {TRIPLETS}.",
        )
        return

    output = f"{result.stdout}\n{result.stderr}"
    if output.strip() and ("PETSc" in output or "PFLOTRAN" in output or "Options" in output):
        add_check("run", subject, True, "pass")
    else:
        add_check(
            "run",
            subject,
            True,
            "fail",
            f"PFLOTRAN started with exit code {result.returncode} but did not print recognizable help output; consult {TRIPLETS}.",
        )


def check_mpi_available() -> None:
    mpi = shutil.which("mpirun") or shutil.which("mpiexec")
    if mpi:
        add_check("binary", str(Path(mpi).resolve(strict=False)), False, "pass")
    else:
        add_check(
            "binary",
            "mpirun/mpiexec",
            False,
            "fail",
            f"Install OpenMPI or run PFLOTRAN with nproc=1; consult {TRIPLETS} for recovery.",
        )


def main() -> None:
    print(f"{' PREFLIGHT: PFLOTRAN ':=^60}")
    print()

    check_dir(KI_DIR / "tools", "KI tools directory", critical=True)
    for rel_path in (
        "tools/run_pflotran.py",
        "tools/convert_forcing_to_pflotran.py",
        "tools/convert_soil_to_pflotran.py",
        "tools/parse_pflotran_output.py",
        "knowledge_infrastructure.yaml",
        "dag.yaml",
        "SKILL.md",
    ):
        check_file(KI_DIR / rel_path, rel_path, critical=True)

    check_file(TRIPLETS, "diagnostic triplets", critical=True)
    check_file(PFLOTRAN_BIN, "PFLOTRAN binary", critical=True, executable=True)
    check_pflotran_starts()
    check_python_interpreter()
    check_imports()
    check_mpi_available()

    print()
    passed = sum(1 for c in checks if c["status"] == "pass")
    failed = len(checks) - passed
    print(f"  Results: {passed} passed, {failed} failed")
    failed_critical = [c for c in checks if c["status"] != "pass" and c.get("critical")]
    if failed_critical:
        print(f"  STATUS: PREFLIGHT FAILED - consult {TRIPLETS} for recovery.")
    else:
        print("  STATUS: PREFLIGHT PASSED - safe to proceed with model execution.")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
