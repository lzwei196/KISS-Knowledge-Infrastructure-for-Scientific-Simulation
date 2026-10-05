#!/usr/bin/env python3
"""Preflight check for the PCR_GLOBWB_2 knowledge infrastructure."""

import json
import os
import subprocess
import sys
from pathlib import Path


MODEL_ID = "PCR_GLOBWB_2"
KI_DIR = Path(__file__).resolve().parent
HC_PYTHON = Path("KISSPATH_PYTHON_ENV/bin/python")  # KI converter tools
_WORK = "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/PCR_GLOBWB_2"
# The PCR-GLOBWB engine: tools/run_pcrglobwb.py imports pcraster + netCDF4 and runs
# [sys.executable, <model_dir>/deterministic_runner.py], so it must be started with this conda
# python and --model-dir set to MODEL_DIR (models/PCR_GLOBWB_2/source/repo is an empty repo).
# Overrides: PCRGLOBWB_PYTHON, PCRGLOBWB_MODEL_DIR. An override set to "" is invalid and fails.
_PY_OVERRIDE = os.environ.get("PCRGLOBWB_PYTHON")
MODEL_PYTHON = Path(
    _PY_OVERRIDE if _PY_OVERRIDE is not None
    else _WORK + "/miniconda/envs/pcrglobwb_python3/bin/python"
)
_DIR_OVERRIDE = os.environ.get("PCRGLOBWB_MODEL_DIR")
MODEL_DIR = Path(_DIR_OVERRIDE if _DIR_OVERRIDE is not None else _WORK + "/source/repo/model")
IMPORT_TIMEOUT_S = 180
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"
LOCAL_INPUT_TREE = Path("KISSPATH_OUTPUTS_ALT/pcrglobwb2_huai_bengbu/input")

CHECKS = []


def add_check(kind, subject, critical, status, fix=""):
    """Append one contract-shaped preflight check and print a readable line."""
    status = "pass" if status == "pass" else "fail"
    check = {
        "kind": kind,
        "subject": str(subject),
        "critical": bool(critical),
        "status": status,
        "fix": "" if status == "pass" else fix,
    }
    CHECKS.append(check)

    label = "OK" if status == "pass" else "FAIL"
    print(f"  {label:<5} {kind}: {subject}")
    if status == "fail" and fix:
        print(f"        Fix: {fix}")


def emit_report(model_id, checks):
    """Emit the required KDT preflight report line and exit."""
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}, sort_keys=True))
    has_failed_critical = any(c["status"] != "pass" and c.get("critical") for c in checks)
    sys.exit(1 if has_failed_critical else 0)


def triplet_fix(message):
    return f"{message}; check {TRIPLETS} for matching diagnostics and recovery steps."


def check_file(path, label, critical=True, executable=False, kind="data"):
    path = Path(path)
    subject = path
    if path.exists():
        subject = path.resolve()
    if not path.is_file():
        add_check(kind, subject, critical, "fail", triplet_fix(f"Restore or correct missing {label}: {path}"))
        return False
    if executable and not os.access(path, os.X_OK):
        add_check(kind, subject, critical, "fail", triplet_fix(f"Make {label} executable: chmod +x {path}"))
        return False
    add_check(kind, subject, critical, "pass")
    return True


def check_dir(path, label, critical=True, min_items=1):
    path = Path(path)
    subject = path.resolve() if path.exists() else path
    if not path.is_dir():
        add_check("data", subject, critical, "fail", triplet_fix(f"Restore or correct missing {label}: {path}"))
        return False
    item_count = sum(1 for _ in path.iterdir())
    if item_count < min_items:
        add_check("data", subject, critical, "fail", triplet_fix(f"Populate {label}: {path} has {item_count} items"))
        return False
    add_check("data", subject, critical, "pass")
    return True


def run_python_check(python_path, code, label, critical=True):
    python_path = Path(python_path)
    subject = python_path.resolve() if python_path.exists() else python_path
    if not python_path.is_file() or not os.access(python_path, os.X_OK):
        add_check("binary", subject, critical, "fail", triplet_fix(f"Restore executable Python for {label}: {python_path}"))
        return False

    env = os.environ.copy()
    modelspath = "KISSPATH_KI_TOOLS_COMMON"
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = modelspath if not existing else modelspath + os.pathsep + existing

    try:
        proc = subprocess.run(
            [str(python_path), "-c", code],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=IMPORT_TIMEOUT_S,
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        add_check("run", subject, critical, "fail", triplet_fix(f"{label} did not start: {exc}"))
        return False

    if proc.returncode == 0:
        add_check("binary", subject, critical, "pass")
        return True

    detail = (proc.stderr or proc.stdout or "").strip().splitlines()
    reason = detail[-1] if detail else f"exit code {proc.returncode}"
    add_check("binary", subject, critical, "fail", triplet_fix(f"Fix {label}: {reason}"))
    return False


def check_import_with(python_path, module, label, critical=True):
    code = (
        "import os, sys\n"
        "sys.path.insert(0, 'KISSPATH_KI_TOOLS_COMMON')\n"
        f"__import__({module!r})\n"
    )
    subject = f"{Path(python_path).resolve() if Path(python_path).exists() else python_path} imports {module}"
    try:
        proc = subprocess.run(
            [str(python_path), "-c", code],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=IMPORT_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        add_check("import", subject, critical, "fail", triplet_fix(f"Import {label} with {python_path} did not finish: {exc}"))
        return False

    if proc.returncode == 0:
        add_check("import", subject, critical, "pass")
        return True

    detail = (proc.stderr or proc.stdout or "").strip().splitlines()
    reason = detail[-1] if detail else f"exit code {proc.returncode}"
    add_check("import", subject, critical, "fail", triplet_fix(f"Install or expose {label} for {python_path}: {reason}"))
    return False


def check_nc_count(path, label, critical=True, minimum=1):
    path = Path(path)
    subject = path.resolve() if path.exists() else path
    if not path.is_dir():
        add_check("data", subject, critical, "fail", triplet_fix(f"Restore local PCR-GLOBWB input tree for {label}: {path}"))
        return False
    count = sum(1 for _ in path.rglob("*.nc"))
    if count < minimum:
        add_check("data", subject, critical, "fail", triplet_fix(f"{label} has only {count} NetCDF files; expected at least {minimum}"))
        return False
    add_check("data", f"{subject} ({count} NetCDF files)", critical, "pass")
    return True


def main():
    print(f"{' PREFLIGHT: PCR_GLOBWB_2 ':=^60}")

    check_file(HC_PYTHON, "HydroCraft Python interpreter", critical=True, executable=True, kind="binary")
    run_python_check(
        HC_PYTHON,
        "import sys; print(sys.executable)",
        "HydroCraft Python interpreter startup",
        critical=True,
    )

    for module, label in [
        ("numpy", "NumPy"),
        ("netCDF4", "netCDF4"),
        ("ki_tools_common.load_forcing", "ki_tools_common.load_forcing"),
    ]:
        check_import_with(HC_PYTHON, module, label, critical=True)

    # Engine python (run_pcrglobwb.py + deterministic_runner.py run under it)
    print(f"  Engine python (PCRGLOBWB_PYTHON): {MODEL_PYTHON}")
    check_file(MODEL_PYTHON, "PCR-GLOBWB engine Python (set PCRGLOBWB_PYTHON)", critical=True, executable=True, kind="binary")
    if run_python_check(
        MODEL_PYTHON,
        "import sys; print(sys.executable)",
        "PCR-GLOBWB engine Python startup",
        critical=True,
    ):
        for module, label in [
            ("pcraster", "PCRaster"),
            ("netCDF4", "netCDF4"),
        ]:
            check_import_with(MODEL_PYTHON, module, f"{label} (engine Python; set PCRGLOBWB_PYTHON)", critical=True)

    check_dir(KI_DIR / "tools", "KI tools directory", critical=True, min_items=6)
    for tool in [
        "make_clone_map.py",
        "fetch_pcrglobwb_inputs.py",
        "convert_forcing_to_pcrglobwb.py",
        "convert_soil_params.py",
        "run_pcrglobwb.py",
        "parse_pcrglobwb_output.py",
    ]:
        check_file(KI_DIR / "tools" / tool, f"KI tool {tool}", critical=True)

    if _DIR_OVERRIDE == "":
        add_check("data", "PCRGLOBWB_MODEL_DIR (empty)", True, "fail",
                  triplet_fix("PCRGLOBWB_MODEL_DIR is set but empty; point it at the PCR-GLOBWB model/ folder or unset it"))
    else:
        check_file(MODEL_DIR / "deterministic_runner.py", "PCR-GLOBWB deterministic runner (set PCRGLOBWB_MODEL_DIR)", critical=True)
    check_file(TRIPLETS, "diagnostic triplets", critical=True)
    check_nc_count(LOCAL_INPUT_TREE, "known local 30 arcmin PCR-GLOBWB input cache", critical=False, minimum=30)

    failures = [c for c in CHECKS if c["status"] != "pass"]
    print(f"\n  Results: {len(CHECKS) - len(failures)} passed, {len(failures)} failed")
    for failed in failures:
        print(f"  BLOCKER: {failed['subject']}")
        print(f"           {failed['fix']}")

    emit_report(MODEL_ID, CHECKS)


if __name__ == "__main__":
    main()
