#!/usr/bin/env python3
"""Preflight check for the KINEROS2 Knowledge Infrastructure."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


MODEL_ID = "KINEROS2"
KI_DIR = Path(__file__).resolve().parent
HYDROCRAFT_PYTHON = Path("KISSPATH_PYTHON_ENV/bin/python")
RUNNER = KI_DIR / "tools" / "run_kineros2.py"
DIAGNOSTICS = KI_DIR / "diagnostics" / "triplets.yaml"

CHECKS = []


def add_check(kind, subject, critical, passed, fix):
    status = "pass" if passed else "fail"
    CHECKS.append({
        "kind": kind,
        "subject": str(subject),
        "critical": bool(critical),
        "status": status,
        "fix": "" if passed else fix,
    })
    print(f"  {'OK' if passed else 'FAIL':5s} {kind}: {subject}")
    if not passed:
        print(f"        Fix: {fix}")


def run_command(args, timeout=20):
    return subprocess.run(
        [str(a) for a in args],
        cwd=str(KI_DIR),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )


def check_file(path, label, critical=True, executable=False, kind="data"):
    path = Path(path)
    realpath = os.path.realpath(path)
    if not path.is_file():
        add_check(
            kind,
            realpath,
            critical,
            False,
            f"Restore {label}; consult {DIAGNOSTICS} for recovery.",
        )
        return False
    if executable and not os.access(path, os.X_OK):
        add_check(
            kind,
            realpath,
            critical,
            False,
            f"Run: chmod +x {path}. If execution still fails, check {DIAGNOSTICS}.",
        )
        return False
    add_check(kind, realpath, critical, True, "")
    return True


def check_dir(path, label, critical=True):
    path = Path(path)
    if path.is_dir() and any(path.iterdir()):
        add_check("data", os.path.realpath(path), critical, True, "")
        return True
    add_check(
        "data",
        os.path.realpath(path),
        critical,
        False,
        f"Restore non-empty {label}; consult {DIAGNOSTICS} for recovery.",
    )
    return False


def check_import(module, critical=True):
    if not HYDROCRAFT_PYTHON.is_file():
        add_check(
            "import",
            f"{module} via {HYDROCRAFT_PYTHON}",
            critical,
            False,
            f"Restore HydroCraft Python at {HYDROCRAFT_PYTHON}; consult {DIAGNOSTICS}.",
        )
        return False
    proc = run_command(
        [
            HYDROCRAFT_PYTHON,
            "-c",
            (
                "import importlib, json; "
                f"m=importlib.import_module({module!r}); "
                "print(json.dumps({'module': m.__name__, "
                "'version': getattr(m, '__version__', '')}))"
            ),
        ],
        timeout=15,
    )
    passed = proc.returncode == 0
    fix = (
        f"Install {module.split('.')[0]} into {HYDROCRAFT_PYTHON}'s environment, "
        f"then rerun preflight. Check {DIAGNOSTICS} if import errors persist. "
        f"stderr: {proc.stderr.strip()[:300]}"
    )
    add_check("import", f"{module} via {HYDROCRAFT_PYTHON}", critical, passed, fix)
    return passed


def check_runner_starts():
    if not RUNNER.is_file() or not os.access(RUNNER, os.X_OK) or not HYDROCRAFT_PYTHON.is_file():
        return False
    proc = run_command([HYDROCRAFT_PYTHON, RUNNER, "--help"], timeout=15)
    passed = proc.returncode == 0 and "Run KINEROS2 analytic lumped model" in proc.stdout
    add_check(
        "run",
        f"{os.path.realpath(RUNNER)} --help via {HYDROCRAFT_PYTHON}",
        True,
        passed,
        f"Make the KINEROS2 runner start under {HYDROCRAFT_PYTHON}; check {DIAGNOSTICS}. stderr: {proc.stderr.strip()[:300]}",
    )
    return passed


def check_smoke_simulation():
    if not RUNNER.is_file() or not HYDROCRAFT_PYTHON.is_file():
        return False

    with tempfile.TemporaryDirectory(prefix="kineros2_preflight_") as tmp:
        tmpdir = Path(tmp)
        forcing = tmpdir / "forcing.json"
        params = tmpdir / "params.json"
        output = tmpdir / "simulation.json"

        forcing.write_text(json.dumps({
            "status": "success",
            "output": {
                "dates": ["2000-01-01", "2000-01-02", "2000-01-03"],
                "prec_mm_d": [2.0, 0.5, 8.0],
                "temp_deg_c": [18.0, 19.0, 20.0],
            },
        }))
        params.write_text(json.dumps({
            "parameters": {
                "Ks": 25.0,
                "psi_f": 170.0,
                "Smax": 250.0,
                "fc": 0.55,
                "k_fast": 0.12,
                "k_slow": 0.01,
                "f_slow": 0.35,
                "alpha": 1.5,
            },
        }))

        proc = run_command(
            [
                HYDROCRAFT_PYTHON,
                RUNNER,
                "--mode",
                "simulate",
                "--forcing",
                forcing,
                "--params",
                params,
                "--basin-area-km2",
                "10",
                "--latitude",
                "33",
                "--output",
                output,
            ],
            timeout=30,
        )

        passed = False
        if proc.returncode == 0 and output.is_file():
            try:
                data = json.loads(output.read_text())
                q = data.get("output", {}).get("Q_sim_m3s", [])
                passed = data.get("status") == "success" and len(q) == 3
            except json.JSONDecodeError:
                passed = False

        add_check(
            "run",
            f"{os.path.realpath(RUNNER)} smoke simulation via {HYDROCRAFT_PYTHON}",
            True,
            passed,
            f"Fix KINEROS2 simulate mode and input contract; check {DIAGNOSTICS}. stderr: {proc.stderr.strip()[:300]} stdout: {proc.stdout.strip()[:300]}",
        )
        return passed


def emit_report():
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": MODEL_ID, "checks": CHECKS}, sort_keys=True))
    critical_failed = any(c["critical"] and c["status"] != "pass" for c in CHECKS)
    sys.exit(1 if critical_failed else 0)


def main():
    print(f"{' PREFLIGHT: KINEROS2 ':=^60}")
    print(f"KI directory: {KI_DIR}")
    print(f"Diagnostics: {DIAGNOSTICS}")
    print()

    check_file(HYDROCRAFT_PYTHON, "HydroCraft Python interpreter", critical=True, executable=True, kind="binary")
    check_file(RUNNER, "KINEROS2 runner declared in knowledge_infrastructure.yaml", critical=True, executable=True, kind="binary")

    for relpath in [
        "SKILL.md",
        "knowledge_infrastructure.yaml",
        "dag.yaml",
        "docs/format_spec.yaml",
        "diagnostics/triplets.yaml",
    ]:
        check_file(KI_DIR / relpath, relpath, critical=True, kind="data")

    check_dir(KI_DIR / "tools", "KI tools directory", critical=True)
    for relpath in [
        "tools/convert_forcing_to_kineros2.py",
        "tools/convert_soil_to_kineros2.py",
        "tools/run_kineros2.py",
        "tools/parse_output_kineros2.py",
    ]:
        check_file(KI_DIR / relpath, relpath, critical=True, kind="data")

    for module in ["numpy", "pandas", "scipy", "xarray", "geopandas", "shapely"]:
        check_import(module, critical=True)
    check_import("matplotlib", critical=False)

    check_runner_starts()
    check_smoke_simulation()

    print()
    passed = sum(1 for c in CHECKS if c["status"] == "pass")
    failed = len(CHECKS) - passed
    print(f"Results: {passed} passed, {failed} failed")
    if failed:
        print(f"Blockers found. Start recovery with {DIAGNOSTICS}.")
    else:
        print("Preflight passed. KINEROS2 is ready for model execution.")

    emit_report()


if __name__ == "__main__":
    main()
