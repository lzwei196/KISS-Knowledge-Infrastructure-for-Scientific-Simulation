#!/usr/bin/env python3
"""Preflight check for the DART Knowledge Infrastructure."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


MODEL_ID = "DART"
KI_DIR = Path(__file__).resolve().parent
PYTHON_ENV = Path("KISSPATH_PYTHON_ENV/bin/python")

# Server default: the real Lorenz-63 build (filter + perfect_model_obs) used by tools/run_dart.py
# (--work_dir that folder). Override with DART_FILTER_BINARY; an explicit override never falls back.
DART_SERVER_FILTER = Path(
    "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/DART/source/repo/models/lorenz_63/work/filter"
)
# An override set to "" is invalid (it fails below); it does not fall back to the default.
DART_FILTER_OVERRIDE = os.environ.get("DART_FILTER_BINARY")
DART_FILTER_CANDIDATES = [Path(DART_FILTER_OVERRIDE)] if DART_FILTER_OVERRIDE is not None else [
    DART_SERVER_FILTER,
    KI_DIR.parent / "source" / "repo" / "models" / "lorenz_63" / "work" / "filter",
    KI_DIR.parent / "repo" / "models" / "lorenz_63" / "work" / "filter",
    KI_DIR.parent / "DART" / "models" / "lorenz_63" / "work" / "filter",
]


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}))
    failed_critical = any(
        check["status"] != "pass" and check.get("critical") for check in checks
    )
    sys.exit(1 if failed_critical else 0)


def add_check(checks, kind, subject, critical, status, fix=""):
    check = {
        "kind": kind,
        "subject": str(subject),
        "critical": bool(critical),
        "status": status,
        "fix": fix,
    }
    checks.append(check)
    label = "OK" if status == "pass" else "FAIL"
    print(f"  {label:<5} {kind}: {subject}")
    if status != "pass" and fix:
        print(f"        Fix: {fix}")


def check_file(checks, path, label, critical=True, executable=False):
    path = Path(path)
    subject = path.resolve(strict=False)
    if not path.is_file():
        add_check(
            checks,
            "data",
            subject,
            critical,
            "fail",
            f"{label} is missing. Restore it in this KI; consult diagnostics/triplets.yaml for recovery.",
        )
        return False
    if executable and not os.access(path, os.X_OK):
        add_check(
            checks,
            "binary",
            subject,
            critical,
            "fail",
            f"{label} exists but is not executable. Run: chmod +x {path}",
        )
        return False
    add_check(checks, "binary" if executable else "data", subject, critical, "pass")
    return True


def check_dir(checks, path, label, critical=True):
    path = Path(path)
    subject = path.resolve(strict=False)
    if not path.is_dir():
        add_check(
            checks,
            "data",
            subject,
            critical,
            "fail",
            f"{label} is missing. Restore the KI layout; consult diagnostics/triplets.yaml.",
        )
        return False
    if not any(path.iterdir()):
        add_check(
            checks,
            "data",
            subject,
            critical,
            "fail",
            f"{label} is empty. Restore the generated KI files.",
        )
        return False
    add_check(checks, "data", subject, critical, "pass")
    return True


def check_import(checks, module, critical=True):
    subject = f"{PYTHON_ENV}: import {module}"
    if not PYTHON_ENV.is_file():
        add_check(
            checks,
            "import",
            subject,
            critical,
            "fail",
            "HydroCraft Python environment is missing; restore KISSPATH_PYTHON_ENV.",
        )
        return False

    try:
        result = subprocess.run(
            [str(PYTHON_ENV), "-c", f"import {module}"],
            capture_output=True,
            text=True,
            timeout=180,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        add_check(
            checks,
            "import",
            subject,
            critical,
            "fail",
            f"import {module} did not finish: {exc}. Check the HydroCraft Python environment; consult diagnostics/triplets.yaml.",
        )
        return False
    if result.returncode == 0:
        add_check(checks, "import", subject, critical, "pass")
        return True

    detail = (result.stderr or result.stdout).strip().splitlines()
    message = detail[-1] if detail else f"import {module} failed"
    add_check(
        checks,
        "import",
        subject,
        critical,
        "fail",
        f"{message}. Install into the HydroCraft Python environment; consult diagnostics/triplets.yaml.",
    )
    return False


def find_filter_binary():
    for candidate in DART_FILTER_CANDIDATES:
        if candidate and candidate.is_file():
            return candidate
    return None


def probe_dart_program(checks, program):
    """Start a DART program in a fresh EMPTY temp dir (never its work dir, so no real
    run starts). A loadable build stops with DART's own 'input.nml must exist' error."""
    try:
        with tempfile.TemporaryDirectory(prefix="dart_preflight_") as tmp:
            result = subprocess.run(
                [str(program)],
                cwd=tmp,
                capture_output=True,
                text=True,
                timeout=60,
            )
    except subprocess.TimeoutExpired:
        add_check(
            checks,
            "run",
            program,
            True,
            "fail",
            f"{program.name} did not return within 60 seconds in an empty dir. Check whether it is an MPI build and launch through tools/run_dart.py with mpirun; see diagnostics/triplets.yaml.",
        )
        return
    except OSError as exc:
        add_check(
            checks,
            "run",
            program,
            True,
            "fail",
            f"{program.name} could not be started: {exc}. Rebuild Lorenz 63 with quickbuild.sh; see diagnostics/triplets.yaml.",
        )
        return

    output = (result.stdout + result.stderr).strip()
    if "find_namelist_in_file" in output and "input.nml must exist" in output:
        add_check(checks, "run", program, True, "pass")
        return
    lines = output.splitlines()
    detail = lines[-1] if lines else "no output"
    add_check(
        checks,
        "run",
        program,
        True,
        "fail",
        f"{program.name} did not start normally (rc={result.returncode}: {detail}). Expected DART's 'input.nml must exist' message in an empty dir; rebuild and check diagnostics/triplets.yaml.",
    )


def check_dart_filter(checks):
    binary = find_filter_binary()
    searched = [
        str(path.resolve(strict=False)) for path in DART_FILTER_CANDIDATES if path is not None
    ]
    if binary is None:
        if DART_FILTER_OVERRIDE is not None:
            fix = f"DART_FILTER_BINARY={DART_FILTER_OVERRIDE!r} is not a file. Point it at a built filter (server build: {DART_SERVER_FILTER}) or unset it; see diagnostics/triplets.yaml."
        else:
            fix = f"No built DART filter executable found (server build expected at {DART_SERVER_FILTER}). Build Lorenz 63 with quickbuild.sh or set DART_FILTER_BINARY to the real filter path; see diagnostics/triplets.yaml."
        add_check(
            checks,
            "binary",
            "DART filter executable (DART_FILTER_BINARY, server build, KI layout)",
            True,
            "fail",
            fix,
        )
        add_check(
            checks,
            "data",
            "DART filter search paths: " + "; ".join(searched),
            False,
            "fail",
            "Expected the built DART filter at one of these paths.",
        )
        return

    real_binary = binary.resolve(strict=True)
    programs = [real_binary, real_binary.parent / "perfect_model_obs"]
    for program in programs:
        if not program.is_file():
            add_check(
                checks,
                "binary",
                program,
                True,
                "fail",
                f"{program.name} is missing next to filter; tools/run_dart.py needs it in --work_dir {real_binary.parent}. Build Lorenz 63 with quickbuild.sh; see diagnostics/triplets.yaml.",
            )
            continue
        if not os.access(program, os.X_OK):
            add_check(
                checks,
                "binary",
                program,
                True,
                "fail",
                f"{program.name} is not executable. Run: chmod +x {program}",
            )
            continue
        add_check(checks, "binary", program, True, "pass")
        probe_dart_program(checks, program)


def main():
    checks = []
    print(f"{' PREFLIGHT: DART ':=^60}")
    print(f"KI directory: {KI_DIR}")
    print()

    check_dir(checks, KI_DIR / "tools", "KI tools directory", critical=True)
    for relpath in [
        "tools/convert_obs_to_dart.py",
        "tools/generate_input_nml.py",
        "tools/parse_dart_output.py",
        "tools/run_dart.py",
        "SKILL.md",
        "knowledge_infrastructure.yaml",
        "dag.yaml",
        "docs/format_spec.yaml",
    ]:
        check_file(checks, KI_DIR / relpath, relpath, critical=True)

    check_file(
        checks,
        KI_DIR / "diagnostics" / "triplets.yaml",
        "diagnostics/triplets.yaml",
        critical=True,
    )

    for module in ["numpy", "pandas", "netCDF4", "yaml"]:
        check_import(checks, module, critical=True)

    check_dart_filter(checks)

    print()
    passed = sum(1 for check in checks if check["status"] == "pass")
    failed = len(checks) - passed
    print(f"Results: {passed} passed, {failed} failed")
    if failed:
        print("Blockers found. Start recovery with diagnostics/triplets.yaml.")
    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
