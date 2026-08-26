#!/usr/bin/env python3
"""Preflight check for the EPANET Knowledge Infrastructure."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path


MODEL_ID = "EPANET"
KI_DIR = Path(__file__).resolve().parent
MODEL_DIR = KI_DIR.parent
PYTHON_ENV = Path("KISSPATH_PYTHON_ENV/bin/python")
SITE_PACKAGES = Path("KISSPATH_PYTHON_ENV/lib/python3.12/site-packages")

BINARY_CANDIDATES = [
    MODEL_DIR / "source/repo/SRC_engines/build/src/run/runepanet",
    MODEL_DIR / "source/repo/SRC_engines/build_fresh/src/run/runepanet",
]
LIBEPANET_CANDIDATES = [
    MODEL_DIR / "source/repo/SRC_engines/build/src/solver/libepanet2.so",
    MODEL_DIR / "source/repo/SRC_engines/build_fresh/src/solver/libepanet2.so",
]
TUTORIAL_INP = MODEL_DIR / "source/repo/User_Manual/docs/tutorial.inp"
TRIPLETS = KI_DIR / "diagnostics/triplets.yaml"


def check(kind: str, subject: str, critical: bool, passed: bool, fix: str = "") -> dict:
    status = "pass" if passed else "fail"
    label = "OK" if passed else "FAIL"
    print(f"  {label:<5} {kind}: {subject}")
    if not passed and fix:
        print(f"        Fix: {fix}")
    return {
        "kind": kind,
        "subject": subject,
        "critical": critical,
        "status": status,
        "fix": "" if passed else fix,
    }


def first_existing_executable(candidates: list[Path]) -> Path | None:
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate.resolve()
    return None


def first_existing_file(candidates: list[Path]) -> Path | None:
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return None


def run_check(cmd: list[str], timeout: int = 5) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, f"timed out after {timeout}s"
    except OSError as exc:
        return False, str(exc)

    output = (result.stdout + result.stderr).strip()
    if result.returncode == 0:
        return True, output
    return False, f"exit {result.returncode}: {output}"


def python_import_check(module: str) -> tuple[bool, str]:
    if PYTHON_ENV.is_file() and os.access(PYTHON_ENV, os.X_OK):
        code = f"import {module}; print('ok')"
        ok, detail = run_check([str(PYTHON_ENV), "-c", code], timeout=10)
        return ok, detail

    if SITE_PACKAGES.is_dir():
        sys.path.insert(0, str(SITE_PACKAGES))
    spec = importlib.util.find_spec(module)
    return spec is not None, "module not found"


def emit_report(model_id: str, checks: list[dict]) -> None:
    critical_failed = [c for c in checks if c["critical"] and c["status"] != "pass"]
    if critical_failed:
        print()
        print("  STATUS: PREFLIGHT FAILED")
        print(f"  Recovery: inspect {TRIPLETS} for matching errors and remedies.")
        for failed in critical_failed:
            if failed.get("fix"):
                print(f"  Blocker fix: {failed['fix']}")
    else:
        print()
        print("  STATUS: PREFLIGHT PASSED")

    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}, sort_keys=True))
    sys.exit(1 if critical_failed else 0)


def main() -> None:
    checks: list[dict] = []

    print(f"{' PREFLIGHT: EPANET ':=^60}")
    print()

    binary = first_existing_executable(BINARY_CANDIDATES)
    if binary is None:
        checks.append(
            check(
                "binary",
                "runepanet",
                True,
                False,
                f"Rebuild EPANET under {MODEL_DIR}/source/repo/SRC_engines/build or check {TRIPLETS}.",
            )
        )
    else:
        binary_realpath = os.path.realpath(binary)
        checks.append(
            check(
                "binary",
                binary_realpath,
                True,
                True,
            )
        )
        ok, detail = run_check([binary_realpath], timeout=5)
        checks.append(
            check(
                "run",
                f"{binary_realpath} usage start",
                True,
                ok and "Usage:" in detail,
                f"Run {binary_realpath} without arguments; if it fails, rebuild EPANET and check {TRIPLETS}.",
            )
        )

    libepanet = first_existing_file(LIBEPANET_CANDIDATES)
    checks.append(
        check(
            "data",
            os.path.realpath(libepanet) if libepanet else "libepanet2.so",
            True,
            libepanet is not None,
            f"Rebuild the EPANET shared library in {MODEL_DIR}/source/repo/SRC_engines/build.",
        )
    )

    checks.append(
        check(
            "data",
            str(TUTORIAL_INP),
            True,
            TUTORIAL_INP.is_file(),
            f"Restore the EPANET user manual tutorial input or check {TRIPLETS}.",
        )
    )

    for rel_tool in [
        "tools/convert_demands_to_inp.py",
        "tools/convert_network_params.py",
        "tools/parse_epanet_output.py",
        "tools/run_epanet.py",
    ]:
        tool_path = KI_DIR / rel_tool
        checks.append(
            check(
                "data",
                str(tool_path),
                True,
                tool_path.is_file(),
                f"Restore missing KI tool {rel_tool} from source control or regenerate the KI.",
            )
        )

    checks.append(
        check(
            "data",
            str(TRIPLETS),
            False,
            TRIPLETS.is_file(),
            "Restore diagnostics/triplets.yaml so runtime failures point at documented remedies.",
        )
    )

    checks.append(
        check(
            "import",
            str(PYTHON_ENV),
            True,
            PYTHON_ENV.is_file() and os.access(PYTHON_ENV, os.X_OK),
            "Create or repair KISSPATH_PYTHON_ENV; KI Python imports must use this interpreter.",
        )
    )

    for module in ["pandas", "numpy", "matplotlib"]:
        ok, _detail = python_import_check(module)
        checks.append(
            check(
                "import",
                f"{module} via {PYTHON_ENV if PYTHON_ENV.exists() else sys.executable}",
                True,
                ok,
                f"Install {module} into KISSPATH_PYTHON_ENV.",
            )
        )

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
