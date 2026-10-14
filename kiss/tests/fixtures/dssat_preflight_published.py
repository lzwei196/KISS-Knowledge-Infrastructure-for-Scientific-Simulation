#!/usr/bin/env python3
"""
Preflight check for DSSAT-CSM v4.8.5.

Run this from the KI root before attempting model execution. The final output
line is consumed by the KDT gate and must remain:
    PREFLIGHT_REPORT=<json>
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


MODEL_ID = "DSSAT"
KI_DIR = Path(__file__).resolve().parent
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"

DSSAT_BINARY = Path("KISSPATH_HOME/DSSAT/build/bin/dscsm048")
DSSAT_DATA = Path("KISSPATH_HOME/DSSAT/Data")
HYDROCRAFT_PYTHON = Path("KISSPATH_PYTHON_ENV/bin/python")


checks: list[dict[str, object]] = []


def triplets_fix(action: str) -> str:
    return f"{action}; then check {TRIPLETS} for known DSSAT recovery steps"


def add_check(
    kind: str,
    subject: str | Path,
    critical: bool,
    ok: bool,
    fix: str = "",
) -> None:
    status = "pass" if ok else "fail"
    subject_text = str(subject)
    checks.append(
        {
            "kind": kind,
            "subject": subject_text,
            "critical": critical,
            "status": status,
            "fix": "" if ok else fix,
        }
    )
    label = "OK" if ok else ("FAIL" if critical else "WARN")
    print(f"  {label:<5} {kind}: {subject_text}")
    if not ok and fix:
        print(f"        Fix: {fix}")


def check_file(path: Path, label: str, critical: bool, executable: bool = False) -> Path:
    resolved = path.resolve(strict=False)
    ok = path.is_file()
    fix = triplets_fix(f"Create or restore {label} at {path}")
    if ok and executable:
        ok = os.access(path, os.X_OK)
        fix = triplets_fix(f"Run chmod +x {path} or rebuild/install {label}")
    add_check("data", resolved, critical, ok, fix)
    return resolved


def check_executable(path: Path, label: str, critical: bool, report_realpath: bool = False) -> Path:
    resolved = path.resolve(strict=False)
    subject = resolved if report_realpath else path
    ok = path.is_file() and os.access(path, os.X_OK)
    fix = triplets_fix(f"Run chmod +x {path} or rebuild/install {label}")
    add_check("binary" if report_realpath else "data", subject, critical, ok, fix)
    return resolved


def check_dir(path: Path, label: str, critical: bool, nonempty: bool = True) -> None:
    resolved = path.resolve(strict=False)
    ok = path.is_dir() and (not nonempty or any(path.iterdir()))
    fix = triplets_fix(f"Restore {label} at {path}")
    add_check("data", resolved, critical, ok, fix)


def check_binary_starts(binary: Path) -> None:
    resolved = binary.resolve(strict=False)
    if not binary.is_file() or not os.access(binary, os.X_OK):
        add_check(
            "run",
            resolved,
            True,
            False,
            triplets_fix(f"Restore executable DSSAT binary at {binary}"),
        )
        return

    try:
        proc = subprocess.run(
            [str(binary)],
            cwd=str(KI_DIR),
            text=True,
            input="\n",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=5,
        )
    except subprocess.TimeoutExpired:
        add_check(
            "run",
            resolved,
            True,
            False,
            triplets_fix("DSSAT did not return from its no-argument startup check within 5 seconds"),
        )
        return
    except OSError as exc:
        add_check(
            "run",
            resolved,
            True,
            False,
            triplets_fix(f"DSSAT executable could not be started: {exc}"),
        )
        return

    output = proc.stdout or ""
    ok = "DSSAT COMMAND LINE USAGE" in output or "Runmode not specified" in output
    add_check(
        "run",
        resolved,
        True,
        ok,
        triplets_fix(
            f"DSSAT started but did not print expected command-line usage; return code {proc.returncode}"
        ),
    )


def check_import(module: str, critical: bool, extra_pythonpath: list[Path] | None = None) -> None:
    subject = f"{HYDROCRAFT_PYTHON} import {module}"
    if not HYDROCRAFT_PYTHON.is_file():
        add_check(
            "import",
            subject,
            critical,
            False,
            triplets_fix(f"Restore HydroCraft Python interpreter at {HYDROCRAFT_PYTHON}"),
        )
        return

    env = os.environ.copy()
    if extra_pythonpath:
        prefix = os.pathsep.join(str(p) for p in extra_pythonpath)
        env["PYTHONPATH"] = prefix + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")

    proc = subprocess.run(
        [str(HYDROCRAFT_PYTHON), "-c", f"import {module}"],
        cwd=str(KI_DIR),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
    )
    detail = (proc.stderr or proc.stdout or "").strip().splitlines()
    fix = triplets_fix(
        f"Install or repair Python dependency '{module.split('.')[0]}' in {HYDROCRAFT_PYTHON}"
        + (f" ({detail[-1]})" if detail else "")
    )
    add_check("import", subject, critical, proc.returncode == 0, fix)


def check_common_data() -> None:
    optional_paths = [
        (Path("KISSPATH_OBS"), "observation data"),
        (Path("KISSPATH_FORCING"), "forcing data"),
        (Path("KISSPATH_STATIC"), "DEM data"),
        (Path("KISSPATH_STATIC"), "soil data"),
    ]
    for path, label in optional_paths:
        check_dir(path, label, critical=False, nonempty=False)


def emit_report() -> None:
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": MODEL_ID, "checks": checks}, sort_keys=True))
    has_critical = any(c.get("critical") for c in checks)
    critical_failed = any(c["status"] != "pass" and c.get("critical") for c in checks)
    sys.exit(0 if has_critical and not critical_failed else 1)


def main() -> None:
    print("=" * 60)
    print("  PREFLIGHT CHECK: DSSAT-CSM v4.8.5")
    print("=" * 60)

    binary_realpath = check_executable(
        DSSAT_BINARY,
        "DSSAT CSM v4.8.5",
        critical=True,
        report_realpath=True,
    )
    check_binary_starts(DSSAT_BINARY)

    check_file(DSSAT_DATA / "MODEL.ERR", "DSSAT MODEL.ERR support file", critical=True)
    check_dir(DSSAT_DATA / "Genotype" / "China", "Chinese cultivar library", critical=True)
    for cultivar in [
        "MZCER048_China.CUL",
        "WHCER048_China.CUL",
        "RICER048_China.CUL",
        "SBGRO048_China.CUL",
    ]:
        check_file(DSSAT_DATA / "Genotype" / "China" / cultivar, f"cultivar file {cultivar}", critical=True)

    check_executable(HYDROCRAFT_PYTHON, "HydroCraft Python interpreter", critical=True)
    for module in ["numpy", "pandas", "scipy", "ki_tools_common.crop_obs", "ki_tools_common.metrics"]:
        check_import(module, critical=True)
    check_import("dssat_workdir_setup", critical=True, extra_pythonpath=[KI_DIR / "tools"])

    for relpath in [
        "SKILL.md",
        "knowledge_infrastructure.yaml",
        "dag.yaml",
        "docs/format_spec.yaml",
        "tools/dssat_workdir_setup.py",
        "tools/s2_weather_prep/convert_cmfd_to_wth.py",
        "tools/s3_soil_setup/convert_soilgrids_to_sol.py",
        "tools/s8_batch_execution/run_grid_ensemble.py",
        "tools/s9_output_parsing/parse_summary_out.py",
        "tools/s9_output_parsing/validate_yield_timeseries.py",
        "diagnostics/triplets.yaml",
    ]:
        check_file(KI_DIR / relpath, f"KI file {relpath}", critical=True)

    check_common_data()

    print(f"  INFO  Binary realpath verified for models DB comparison: {binary_realpath}")
    print(f"  INFO  Diagnostic triplets: {TRIPLETS}")
    emit_report()


if __name__ == "__main__":
    main()
