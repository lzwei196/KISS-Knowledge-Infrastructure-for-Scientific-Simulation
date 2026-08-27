#!/usr/bin/env python3
"""Preflight checks for the ISSM Knowledge Infrastructure.

This script is intentionally executable from a bare KI checkout. It checks the
real ISSM executable, the ISSM Python API environment, HydroCraft Python
dependencies, KI tools, and diagnostics before model execution.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


MODEL_ID = "ISSM"
KI_DIR = Path(__file__).resolve().parent
HYDRO_PYTHON = Path("KISSPATH_PYTHON_ENV/bin/python")

ISSM_DIR_CANDIDATES = [
    Path(os.environ["ISSM_DIR"]).expanduser()
    if os.environ.get("ISSM_DIR")
    else None,
    Path("KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/ISSM/source/repo"),
    Path("KISSPATH_KI_ROOT/ISSM/source/repo"),
]

REQUIRED_TOOLS = [
    KI_DIR / "tools" / "convert_forcing_to_issm.py",
    KI_DIR / "tools" / "convert_geometry_to_issm.py",
    KI_DIR / "tools" / "parse_issm_output.py",
    KI_DIR / "tools" / "run_issm.py",
]


def emit_report(model_id: str, checks: list[dict]) -> None:
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}, sort_keys=True))
    sys.exit(0 if all(c["status"] == "pass" or not c.get("critical") for c in checks) else 1)


def check(kind: str, subject: str, critical: bool, ok: bool, fix: str) -> dict:
    status = "pass" if ok else "fail"
    label = "OK" if ok else ("FAIL" if critical else "WARN")
    print(f"  {label:<5} {kind}: {subject}")
    if not ok:
        print(f"        Fix: {fix}")
    return {
        "kind": kind,
        "subject": subject,
        "critical": critical,
        "status": status,
        "fix": "" if ok else fix,
    }


def run_command(cmd: list[str], *, env: dict | None = None, timeout: int = 10) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout,
        env=env,
    )


def choose_issm_dir() -> Path:
    for candidate in ISSM_DIR_CANDIDATES:
        if candidate is None:
            continue
        if (candidate / "bin" / "issm.exe").is_file() or (candidate / "bin" / "issm").is_file():
            return candidate.resolve()
    for candidate in ISSM_DIR_CANDIDATES:
        if candidate is not None and candidate.is_dir():
            return candidate.resolve()
    return Path("KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/ISSM/source/repo")


def issm_env(issm_dir: Path) -> dict:
    env = os.environ.copy()
    env["ISSM_DIR"] = str(issm_dir)
    env["PATH"] = f"{issm_dir / 'bin'}:{issm_dir / 'scripts'}:{env.get('PATH', '')}"
    env["PYTHONPATH"] = ":".join(
        [
            str(issm_dir / "bin"),
            str(issm_dir / "lib"),
            str(issm_dir / "scripts"),
            env.get("PYTHONPATH", ""),
        ]
    )
    lib_paths = [
        issm_dir / "lib",
        issm_dir / "externalpackages" / "petsc" / "install" / "lib",
        issm_dir / "externalpackages" / "triangle" / "install" / "lib",
    ]
    env["LD_LIBRARY_PATH"] = ":".join([str(p) for p in lib_paths] + [env.get("LD_LIBRARY_PATH", "")])
    return env


def check_python_imports(checks: list[dict]) -> None:
    subject = str(HYDRO_PYTHON.resolve()) if HYDRO_PYTHON.exists() else str(HYDRO_PYTHON)
    checks.append(
        check(
            "binary",
            subject,
            True,
            HYDRO_PYTHON.is_file() and os.access(HYDRO_PYTHON, os.X_OK),
            "Restore KISSPATH_PYTHON_ENV or run diagnostics/triplets.yaml recovery guidance.",
        )
    )
    if checks[-1]["status"] != "pass":
        return

    code = (
        "import importlib\n"
        "mods=['numpy','scipy','netCDF4']\n"
        "missing=[]\n"
        "for m in mods:\n"
        "    try: importlib.import_module(m)\n"
        "    except Exception as e: missing.append(f'{m}: {e}')\n"
        "print('; '.join(missing))\n"
        "raise SystemExit(1 if missing else 0)\n"
    )
    try:
        result = run_command([str(HYDRO_PYTHON), "-c", code], timeout=12)
        ok = result.returncode == 0
        detail = result.stdout.strip()
    except Exception as exc:
        ok = False
        detail = str(exc)
    fix = (
        "Install missing packages in KISSPATH_PYTHON_ENV "
        "and consult diagnostics/triplets.yaml for dependency recovery."
    )
    checks.append(check("import", "numpy, scipy, netCDF4 via HydroCraft python_env", True, ok, fix))
    if not ok and detail:
        print(f"        Detail: {detail[:500]}")


def check_issm_python_api(checks: list[dict], issm_dir: Path) -> None:
    if not HYDRO_PYTHON.exists():
        return
    code = "from model import model\nfrom triangle import triangle\nfrom solve import solve\nprint(type(model()).__name__)\n"
    try:
        result = run_command([str(HYDRO_PYTHON), "-c", code], env=issm_env(issm_dir), timeout=12)
        ok = result.returncode == 0 and "model" in result.stdout
        detail = result.stdout.strip()
    except Exception as exc:
        ok = False
        detail = str(exc)
    fix = (
        f"Source {issm_dir}/etc/environment.sh and ensure ISSM bin/lib/scripts are on PYTHONPATH; "
        "see diagnostics/triplets.yaml dt_016."
    )
    checks.append(check("import", "ISSM Python API modules: model, triangle, solve", True, ok, fix))
    if not ok and detail:
        print(f"        Detail: {detail[:500]}")


def main() -> None:
    checks: list[dict] = []
    issm_dir = choose_issm_dir()
    env_script = issm_dir / "etc" / "environment.sh"
    executable = issm_dir / "bin" / "issm.exe"
    if not executable.exists():
        executable = issm_dir / "bin" / "issm"
    executable_subject = str(executable.resolve()) if executable.exists() else str(executable)

    print("=" * 60)
    print(f"  PREFLIGHT CHECK: {MODEL_ID}")
    print("=" * 60)

    checks.append(
        check(
            "data",
            str(issm_dir),
            True,
            issm_dir.is_dir(),
            "Restore the ISSM install tree or update ISSM_DIR; check diagnostics/triplets.yaml.",
        )
    )
    checks.append(
        check(
            "data",
            str(env_script),
            True,
            env_script.is_file(),
            "Restore ISSM etc/environment.sh or rebuild ISSM; see diagnostics/triplets.yaml dt_016.",
        )
    )
    checks.append(
        check(
            "binary",
            executable_subject,
            True,
            executable.is_file() and os.access(executable, os.X_OK),
            "Restore/rebuild the ISSM executable and ensure it is executable; see diagnostics/triplets.yaml dt_016.",
        )
    )

    if checks[-1]["status"] == "pass" and env_script.is_file():
        try:
            result = run_command(
                [
                    "bash",
                    "-lc",
                    f"source {str(env_script)!r} >/dev/null 2>&1; {str(executable)!r}",
                ],
                env=issm_env(issm_dir),
                timeout=8,
            )
            output = result.stdout or ""
            # With no solution requested, ISSM exits nonzero after printing its banner.
            starts = "Ice-sheet and Sea-level System Model" in output and "no solution requested" in output
            detail = output.strip()
        except Exception as exc:
            starts = False
            detail = str(exc)
        checks.append(
            check(
                "run",
                f"{executable_subject} starts and reaches ISSM argument parser",
                True,
                starts,
                "Fix ISSM shared libraries/startup; begin with diagnostics/triplets.yaml dt_016.",
            )
        )
        if not starts and detail:
            print(f"        Detail: {detail[:700]}")

        try:
            result = run_command(
                ["bash", "-lc", f"source {str(env_script)!r} >/dev/null 2>&1; ldd {str(executable)!r}"],
                env=issm_env(issm_dir),
                timeout=8,
            )
            ldd_output = result.stdout or ""
            ok = result.returncode == 0 and "not found" not in ldd_output
        except Exception as exc:
            ok = False
            ldd_output = str(exc)
        checks.append(
            check(
                "data",
                f"shared libraries for {executable_subject}",
                True,
                ok,
                "Repair LD_LIBRARY_PATH/PETSc/Triangle libraries; see diagnostics/triplets.yaml dt_016.",
            )
        )
        if not ok and ldd_output:
            print(f"        Detail: {ldd_output[:700]}")

    check_python_imports(checks)
    check_issm_python_api(checks, issm_dir)

    for tool in REQUIRED_TOOLS:
        checks.append(
            check(
                "data",
                str(tool),
                True,
                tool.is_file(),
                "Restore the KI tools from the ISSM knowledge infrastructure package.",
            )
        )

    triplets = KI_DIR / "diagnostics" / "triplets.yaml"
    checks.append(
        check(
            "data",
            str(triplets),
            False,
            triplets.is_file(),
            "Restore diagnostics/triplets.yaml so failures have recovery guidance.",
        )
    )
    if triplets.is_file():
        print(f"  INFO  Recovery diagnostics: {triplets}")

    failed = [c for c in checks if c["status"] == "fail" and c.get("critical")]
    print(f"\n  Results: {len(checks) - len(failed)} passed, {len(failed)} critical failed")
    if failed:
        print("  STATUS: PREFLIGHT FAILED - fix critical issues above before running ISSM.")
        print("  Start recovery at diagnostics/triplets.yaml.")
    else:
        print("  STATUS: PREFLIGHT PASSED - safe to proceed with ISSM execution.")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        fallback = [
            {
                "kind": "run",
                "subject": "preflight_check.py",
                "critical": True,
                "status": "fail",
                "fix": f"Preflight crashed: {exc}. Check diagnostics/triplets.yaml and repair this script.",
            }
        ]
        print(f"  FAIL  preflight_check.py crashed: {exc}")
        emit_report(MODEL_ID, fallback)
