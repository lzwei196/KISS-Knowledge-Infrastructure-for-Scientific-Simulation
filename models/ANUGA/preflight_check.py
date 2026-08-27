#!/usr/bin/env python3
"""Contract preflight for the ANUGA knowledge infrastructure.

This script checks the ANUGA package, declared runner, KI tools, diagnostics,
and data paths before model execution. It always finishes with exactly one
PREFLIGHT_REPORT= JSON line for the KDT gate.
"""

from __future__ import annotations

import json
import os
import py_compile
import subprocess
import sys
from pathlib import Path


MODEL_ID = "ANUGA"
KI_DIR = Path(__file__).resolve().parent
DIAGNOSTICS = KI_DIR / "diagnostics" / "triplets.yaml"
PYTHON = Path("KISSPATH_PYTHON_ENV/bin/python")
KI_TOOLS_COMMON = Path("KISSPATH_KI_TOOLS_COMMON")
MODEL_ENTRYPOINT = Path("KISSPATH_KI_ROOT/ANUGA/run_and_score.py")

REQUIRED_TOOLS = [
    "convert_forcing_to_anuga.py",
    "load_hydat_series.py",
    "build_inflow_hydrograph.py",
    "run_anuga.py",
    "parse_anuga_output.py",
]

REQUIRED_DATA = [
    ("KISSPATH_OBS/flood/gfd_huai/GFD_Huai/GFD_Huai_2269_NA_NA.tif",
     "GFD Huai event 2269 observation raster"),
    ("KISSPATH_FORCING/huai/Data_forcing_01dy_025deg",
     "Huai CMFD daily forcing directory"),
    ("KISSPATH_STATIC/china_dem_90m/china_dem_90m.tif",
     "China 90 m DEM"),
    ("KISSPATH_DATA/MERIT_DEM",
     "MERIT DEM fallback directory"),
    ("KISSPATH_DATA/Hydat_sqlite3_20260116/Hydat.sqlite3",
     "HYDAT SQLite database used by load_hydat_series.py"),
]

OPTIONAL_DATA = [
    ("KISSPATH_OBS", "Observation data root"),
    ("KISSPATH_STATIC", "Soil data root"),
]


def fix_for(message: str) -> str:
    return f"{message}; then check {DIAGNOSTICS} for matching recovery triplets."


def make_check(kind: str, subject: str, critical: bool, ok: bool, fix: str = "") -> dict:
    return {
        "kind": kind,
        "subject": subject,
        "critical": critical,
        "status": "pass" if ok else "fail",
        "fix": "" if ok else fix,
    }


def print_check(label: str, check: dict) -> None:
    status = "OK" if check["status"] == "pass" else ("FAIL" if check["critical"] else "WARN")
    print(f"  {status:<5} {label}: {check['subject']}")
    if check["status"] == "fail":
        print(f"        Fix: {check['fix']}")


def check_file(path: Path, label: str, *, critical: bool = True, executable: bool = False) -> dict:
    subject = os.path.realpath(path)
    if not path.is_file():
        return make_check("data", subject, critical, False, fix_for(f"Restore missing file {path}"))
    if not os.access(path, os.R_OK):
        return make_check("data", subject, critical, False, fix_for(f"Make file readable: chmod +r {path}"))
    if executable and not os.access(path, os.X_OK):
        return make_check("binary", subject, critical, False, fix_for(f"Make entrypoint executable: chmod +x {path}"))
    return make_check("binary" if executable else "data", subject, critical, True)


def check_dir(path: Path, label: str, *, critical: bool = True, nonempty: bool = False) -> dict:
    subject = os.path.realpath(path)
    if not path.is_dir():
        return make_check("data", subject, critical, False, fix_for(f"Restore missing directory {path}"))
    if nonempty and not any(path.iterdir()):
        return make_check("data", subject, critical, False, fix_for(f"Populate required directory {path}"))
    return make_check("data", subject, critical, True)


def check_import(module: str, label: str, *, critical: bool = True) -> dict:
    env = os.environ.copy()
    # The HydroCraft interpreter already activates its site-packages. Do not
    # prepend that directory to PYTHONPATH: it contains a legacy pathlib backport
    # that must not shadow the Python 3.12 stdlib.
    env["PYTHONPATH"] = os.pathsep.join([str(KI_TOOLS_COMMON), env.get("PYTHONPATH", "")])
    cmd = [
        str(PYTHON),
        "-c",
        (
            "import importlib, json, os; "
            f"m=importlib.import_module({module!r}); "
            "print(json.dumps({'file': os.path.realpath(getattr(m, '__file__', 'built-in'))}))"
        ),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=20)
    except Exception as exc:
        return make_check(
            "import",
            module,
            critical,
            False,
            fix_for(f"Run import with {PYTHON} and fix {label}: {type(exc).__name__}: {exc}"),
        )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()[-1:] or ["unknown import failure"]
        return make_check(
            "import",
            module,
            critical,
            False,
            fix_for(f"Install/repair {label} in {PYTHON}: {detail[0]}"),
        )
    return make_check("import", module, critical, True)


def check_python_interpreter() -> dict:
    subject = os.path.realpath(PYTHON)
    if not PYTHON.is_file() and not PYTHON.exists():
        return make_check("binary", subject, True, False, fix_for(f"Restore HydroCraft Python interpreter {PYTHON}"))
    if not os.access(PYTHON, os.X_OK):
        return make_check("binary", subject, True, False, fix_for(f"Make interpreter executable: chmod +x {PYTHON}"))
    try:
        result = subprocess.run(
            [str(PYTHON), "-c", "import sys; print(sys.version.split()[0])"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception as exc:
        return make_check("run", subject, True, False, fix_for(f"Repair interpreter startup: {exc}"))
    if result.returncode != 0:
        return make_check("run", subject, True, False, fix_for(f"Repair interpreter startup: {result.stderr.strip()}"))
    return make_check("binary", subject, True, True)


def check_model_entrypoint() -> dict:
    subject = os.path.realpath(MODEL_ENTRYPOINT)
    base = check_file(MODEL_ENTRYPOINT, "Model entrypoint", critical=True, executable=True)
    if base["status"] == "fail":
        base["subject"] = subject
        base["kind"] = "binary"
        return base
    try:
        py_compile.compile(str(MODEL_ENTRYPOINT), doraise=True)
    except py_compile.PyCompileError as exc:
        return make_check("binary", subject, True, False, fix_for(f"Fix Python syntax in {MODEL_ENTRYPOINT}: {exc.msg}"))
    return make_check("binary", subject, True, True)


def check_anuga_starts() -> dict:
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([str(KI_TOOLS_COMMON), env.get("PYTHONPATH", "")])
    code = (
        "import anuga; "
        "points, vertices, boundary = anuga.rectangular_cross(1, 1, 1.0, 1.0); "
        "from anuga import Domain; "
        "d = Domain(points, vertices, boundary); "
        "d.set_flow_algorithm('DE0'); "
        "print('started')"
    )
    try:
        result = subprocess.run([str(PYTHON), "-c", code], capture_output=True, text=True, env=env, timeout=30)
    except Exception as exc:
        return make_check("run", "ANUGA minimal Domain startup", True, False, fix_for(f"Repair ANUGA startup: {exc}"))
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()[-1:] or ["unknown startup failure"]
        return make_check("run", "ANUGA minimal Domain startup", True, False, fix_for(f"Repair ANUGA startup: {detail[0]}"))
    return make_check("run", "ANUGA minimal Domain startup", True, True)


def emit_report(model_id: str, checks: list[dict]) -> None:
    failed_critical = [c for c in checks if c["status"] == "fail" and c.get("critical")]
    if failed_critical:
        print()
        print("  Blockers found:")
        for c in failed_critical:
            print(f"  - {c['subject']}: {c['fix']}")
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}, sort_keys=True))
    sys.exit(1 if failed_critical else 0)


def main() -> None:
    checks: list[dict] = []
    print("=" * 60)
    print("  PREFLIGHT CHECK: ANUGA")
    print("=" * 60)
    print()

    planned = [
        ("HydroCraft Python interpreter", check_python_interpreter()),
        ("Model entrypoint from manifest", check_model_entrypoint()),
        ("ANUGA core import", check_import("anuga", "ANUGA core")),
        ("NumPy import", check_import("numpy", "NumPy")),
        ("SciPy import", check_import("scipy", "SciPy")),
        ("Rasterio import", check_import("rasterio", "Rasterio")),
        ("ki_tools_common forcing import", check_import("ki_tools_common.load_forcing", "ki_tools_common.load_forcing")),
        ("ki_tools_common terrain import", check_import("ki_tools_common.terrain", "ki_tools_common.terrain")),
        ("ANUGA minimal startup", check_anuga_starts()),
        ("Diagnostics triplets", check_file(DIAGNOSTICS, "Diagnostics triplets", critical=True)),
        ("KI tools directory", check_dir(KI_DIR / "tools", "KI tools directory", critical=True, nonempty=True)),
    ]

    for script in REQUIRED_TOOLS:
        path = KI_DIR / "tools" / script
        planned.append((f"KI tool {script}", check_file(path, f"KI tool {script}", critical=True)))

    planned.append((
        "Diagnostic dam-break runner",
        check_file(KI_DIR / "diagnostics" / "run_dam_break_wet.py", "Diagnostic dam-break runner", critical=True),
    ))

    for path, label in REQUIRED_DATA:
        p = Path(path)
        if p.is_dir() or path.endswith("/"):
            planned.append((label, check_dir(p, label, critical=True, nonempty=True)))
        else:
            planned.append((label, check_file(p, label, critical=True)))

    for path, label in OPTIONAL_DATA:
        p = Path(path)
        planned.append((label, check_dir(p, label, critical=False, nonempty=False)))

    for label, check in planned:
        checks.append(check)
        print_check(label, check)

    print()
    passed = sum(1 for c in checks if c["status"] == "pass")
    failed = len(checks) - passed
    print(f"  Results: {passed} passed, {failed} failed")
    print("  STATUS: PREFLIGHT PASSED" if not any(c["status"] == "fail" and c["critical"] for c in checks)
          else "  STATUS: PREFLIGHT FAILED")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
