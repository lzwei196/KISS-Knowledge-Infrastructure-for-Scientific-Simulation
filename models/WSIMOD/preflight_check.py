#!/usr/bin/env python3
"""Preflight check for the WSIMOD Knowledge Infrastructure."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


MODEL_ID = "WSIMOD"
ROOT = Path("KISSPATH_ROOT")
KI_DIR = Path(__file__).resolve().parent
HYDRO_PYTHON = ROOT / "python_env" / "bin" / "python3"
RUNNER = ROOT / "models" / "WSIMOD" / "run_and_score.py"
KI_TOOLS_COMMON = ROOT / "models" / "ki_tools_common"
# WSIMOD is not pip-installed: GeoForge's run_and_score.py puts this source repo on
# PYTHONPATH (its WSI_REPO constant). Keep the two paths the same.
WSIMOD_REPO = Path("KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/WSIMOD/source/repo")
IMPORT_TIMEOUT = 180
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"


def emit_report(model_id: str, checks: list[dict]) -> None:
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}))
    ok = all(c["status"] == "pass" or not c.get("critical") for c in checks)
    sys.exit(0 if ok else 1)


def check(kind: str, subject: str, critical: bool, passed: bool, fix: str = "") -> dict:
    status = "pass" if passed else "fail"
    prefix = "OK" if passed else ("FAIL" if critical else "WARN")
    print(f"  {prefix:5} {kind}: {subject}")
    if not passed and fix:
        print(f"        Fix: {fix}")
    return {
        "kind": kind,
        "subject": subject,
        "critical": critical,
        "status": status,
        "fix": "" if passed else fix,
    }


def check_file(path: Path, label: str, critical: bool = True, executable: bool = False) -> dict:
    subject = str(path.resolve()) if path.exists() else str(path)
    if not path.is_file():
        return check(
            "data",
            subject,
            critical,
            False,
            f"Restore {label}; see {TRIPLETS} for recovery.",
        )
    if executable and not os.access(path, os.X_OK):
        return check(
            "binary",
            subject,
            critical,
            False,
            f"Run chmod +x {path}; then rerun this preflight. Check {TRIPLETS} if execution still fails.",
        )
    return check("binary" if executable else "data", subject, critical, True)


def check_dir(path: Path, label: str, critical: bool = True) -> dict:
    subject = str(path.resolve()) if path.exists() else str(path)
    if path.is_dir():
        return check("data", subject, critical, True)
    return check(
        "data",
        subject,
        critical,
        False,
        f"Restore {label}; see {TRIPLETS} for recovery.",
    )


def run_python_check(code: str, subject: str, critical: bool, fix: str) -> dict:
    if not HYDRO_PYTHON.is_file():
        return check(
            "import",
            str(HYDRO_PYTHON),
            True,
            False,
            f"Restore the HydroCraft Python environment at {HYDRO_PYTHON}.",
        )
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [str(KI_TOOLS_COMMON), str(WSIMOD_REPO), env.get("PYTHONPATH", "")]
    )
    try:
        proc = subprocess.run(
            [str(HYDRO_PYTHON), "-c", code],
            cwd=str(KI_DIR),
            env=env,
            capture_output=True,
            text=True,
            timeout=IMPORT_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        result = check("import", subject, critical, False, fix)
        print(f"        Detail: import did not finish within {IMPORT_TIMEOUT}s")
        return result
    except OSError as exc:
        result = check("import", subject, critical, False, fix)
        print(f"        Detail: {exc}")
        return result
    passed = proc.returncode == 0
    if not passed:
        detail = (proc.stderr or proc.stdout).strip().splitlines()
        result = check("import", subject, critical, False, fix)
        if detail:
            print(f"        Detail: {detail[-1]}")
        return result
    return check("import", subject, critical, True, fix)


def check_python_syntax(path: Path, critical: bool = True) -> dict:
    subject = str(path.resolve()) if path.exists() else str(path)
    if not HYDRO_PYTHON.is_file():
        return check(
            "run",
            subject,
            critical,
            False,
            f"Restore the HydroCraft Python environment at {HYDRO_PYTHON}.",
        )
    proc = subprocess.run(
        [str(HYDRO_PYTHON), "-m", "py_compile", str(path)],
        cwd=str(KI_DIR),
        capture_output=True,
        text=True,
        timeout=15,
    )
    passed = proc.returncode == 0
    if not passed:
        detail = (proc.stderr or proc.stdout).strip().splitlines()
        result = check(
            "run",
            subject,
            critical,
            False,
            f"Fix syntax/runtime startup errors in {path}; consult {TRIPLETS} for known WSIMOD failures.",
        )
        if detail:
            print(f"        Detail: {detail[-1]}")
        return result
    return check(
        "run",
        subject,
        critical,
        True,
        f"Fix syntax/runtime startup errors in {path}; consult {TRIPLETS} for known WSIMOD failures.",
    )


def main() -> None:
    print(f"{' PREFLIGHT: WSIMOD ':=^60}")
    print(f"Using HydroCraft Python: {HYDRO_PYTHON}")
    print(f"Diagnostics: {TRIPLETS}")
    print()

    checks: list[dict] = []

    checks.append(check_file(HYDRO_PYTHON, "HydroCraft Python interpreter", True, True))
    checks.append(check_file(RUNNER, "WSIMOD runner from models DB", True, True))
    checks.append(check_python_syntax(RUNNER, True))

    checks.append(
        run_python_check(
            "import yaml, pandas, dill, tqdm, numpy",
            "HydroCraft Python imports: yaml,pandas,dill,tqdm,numpy",
            True,
            f"Install missing runtime packages into {ROOT / 'python_env'}; check {TRIPLETS} dt_016.",
        )
    )
    checks.append(
        run_python_check(
            "import ki_tools_common; from ki_tools_common.load_forcing import load_daily_forcing; from ki_tools_common.metrics import all_metrics",
            "HydroCraft Python import: ki_tools_common",
            True,
            f"Restore or install ki_tools_common at {KI_TOOLS_COMMON}; check {TRIPLETS}.",
        )
    )
    checks.append(check_dir(WSIMOD_REPO, "WSIMOD source repo (WSI_REPO in run_and_score.py)", True))
    checks.append(check_file(WSIMOD_REPO / "wsimod" / "__init__.py", "WSIMOD source package wsimod/__init__.py", True))
    expected_init = WSIMOD_REPO / "wsimod" / "__init__.py"
    checks.append(
        run_python_check(
            "import wsimod, pathlib; "
            "from wsimod.orchestration.model import Model; "
            "from wsimod.validation import evaluate_input_file, validate_io_args, load_data_files, assign_data_to_settings; "
            f"got = pathlib.Path(wsimod.__file__).resolve(); want = pathlib.Path({str(expected_init)!r}).resolve(); "
            "assert got == want, f'wsimod loaded from {got}, expected {want}'",
            f"HydroCraft Python import: wsimod from {WSIMOD_REPO}",
            True,
            f"Restore the WSIMOD source repo at {WSIMOD_REPO} (the path run_and_score.py puts on PYTHONPATH; WSIMOD is not pip-installed in {ROOT / 'python_env'}); then rerun preflight. See {TRIPLETS} dt_016.",
        )
    )

    for tool in (
        KI_DIR / "tools" / "convert_forcing_data.py",
        KI_DIR / "tools" / "convert_parameters.py",
        KI_DIR / "tools" / "run_wsimod.py",
        KI_DIR / "tools" / "parse_wsimod_output.py",
    ):
        checks.append(check_file(tool, f"KI tool {tool.name}", True, False))
        checks.append(check_python_syntax(tool, True))

    checks.append(check_file(KI_DIR / "knowledge_infrastructure.yaml", "KI manifest", True))
    checks.append(check_file(KI_DIR / "dag.yaml", "KI DAG", True))
    checks.append(check_file(KI_DIR / "SKILL.md", "KI skill", True))
    checks.append(check_file(TRIPLETS, "diagnostic triplets", True))

    checks.append(
        check_dir(
            ROOT / "data" / "forcing" / "huai" / "Data_forcing_01dy_025deg",
            "CMFD Huai forcing directory",
            True,
        )
    )
    checks.append(
        check_file(
            ROOT / "data" / "obs" / "BB" / "51080_bengbu.txt",
            "Bengbu observed discharge file",
            True,
        )
    )

    failed = [c for c in checks if c["status"] == "fail"]
    print()
    print(f"  Results: {len(checks) - len(failed)} passed, {len(failed)} failed")
    if failed:
        print(f"  STATUS: PREFLIGHT FAILED. Check fixes above and {TRIPLETS}.")
    else:
        print("  STATUS: PREFLIGHT PASSED.")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
