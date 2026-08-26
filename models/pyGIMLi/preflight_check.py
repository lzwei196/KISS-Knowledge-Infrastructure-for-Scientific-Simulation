#!/usr/bin/env python3
"""Preflight check for the pyGIMLi knowledge infrastructure."""

import json
import os
import subprocess
import sys


MODEL_ID = "pyGIMLi"
KI_DIR = os.path.dirname(os.path.abspath(__file__))
PYTHON = "KISSPATH_PYTHON_ENV/bin/python"
SITE_PACKAGES = "KISSPATH_PYTHON_ENV/lib/python3.12/site-packages"
BINARY = os.path.join(KI_DIR, "tools", "run_pygimli.py")
TRIPLETS = os.path.join(KI_DIR, "diagnostics", "triplets.yaml")


def check(kind, subject, critical, passed, fix="", detail=""):
    status = "pass" if passed else "fail"
    label = "OK" if passed else ("FAIL" if critical else "WARN")
    print(f"  {label:<5} {kind}: {subject}")
    if detail:
        print(f"        {detail}")
    if not passed and fix:
        print(f"        Fix: {fix}")
    return {
        "kind": kind,
        "subject": subject,
        "critical": bool(critical),
        "status": status,
        "fix": "" if passed else fix,
    }


def run_command(argv, timeout=20, env=None):
    try:
        return subprocess.run(
            argv,
            cwd=KI_DIR,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        return exc
    except subprocess.TimeoutExpired as exc:
        return exc


def command_detail(result):
    if isinstance(result, FileNotFoundError):
        return str(result)
    if isinstance(result, subprocess.TimeoutExpired):
        return f"timed out after {result.timeout}s"
    output = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
    return output.splitlines()[-1] if output else f"exit code {result.returncode}"


def check_file(checks, path, label, critical=True, executable=False):
    subject = os.path.realpath(path) if os.path.exists(path) else path
    if not os.path.isfile(path):
        checks.append(
            check(
                "data",
                subject,
                critical,
                False,
                f"Restore {label}; check {TRIPLETS} for recovery guidance.",
            )
        )
        return False
    if executable and not os.access(path, os.X_OK):
        checks.append(
            check(
                "binary",
                subject,
                critical,
                False,
                f"chmod +x {path}; if execution still fails, check {TRIPLETS}.",
            )
        )
        return False
    checks.append(check("binary" if executable else "data", subject, critical, True))
    return True


def check_dir(checks, path, label, critical=True):
    subject = os.path.realpath(path) if os.path.exists(path) else path
    if not os.path.isdir(path):
        checks.append(
            check(
                "data",
                subject,
                critical,
                False,
                f"Restore {label}; check {TRIPLETS} for recovery guidance.",
            )
        )
        return False
    entries = len(os.listdir(path))
    checks.append(check("data", subject, critical, True, detail=f"{entries} entries"))
    return True


def check_python_import(checks, module, label, critical=True):
    result = run_command(
        [
            PYTHON,
            "-c",
            (
                "import importlib; "
                f"m = importlib.import_module({module!r}); "
                "print(getattr(m, '__version__', 'import-ok'))"
            ),
        ],
    )
    passed = not isinstance(result, Exception) and result.returncode == 0
    checks.append(
        check(
            "import",
            f"{module} via {PYTHON} (realpath {os.path.realpath(PYTHON)})",
            critical,
            passed,
            (
                f"Install/repair {label} in {PYTHON}; start with diagnostics in "
                f"{TRIPLETS}."
            ),
            "" if passed else command_detail(result),
        )
    )
    return passed


def check_binary_starts(checks):
    result = run_command([PYTHON, BINARY, "--help"])
    passed = not isinstance(result, Exception) and result.returncode == 0
    checks.append(
        check(
            "run",
            f"{os.path.realpath(BINARY)} --help via {PYTHON} (realpath {os.path.realpath(PYTHON)})",
            True,
            passed,
            f"Fix wrapper startup/import errors; check {TRIPLETS} before editing tools.",
            "" if passed else command_detail(result),
        )
    )
    return passed


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}))
    sys.exit(0 if all(c["status"] == "pass" or not c.get("critical") for c in checks) else 1)


def main():
    checks = []
    print("=" * 60)
    print(f"  PREFLIGHT CHECK: {MODEL_ID}")
    print("=" * 60)

    check_file(checks, PYTHON, "HydroCraft Python interpreter", critical=True, executable=True)
    check_dir(checks, SITE_PACKAGES, "HydroCraft Python site-packages", critical=True)
    check_file(checks, BINARY, "pyGIMLi runner", critical=True, executable=True)

    for relative in (
        "tools/convert_data_to_gimli.py",
        "tools/convert_parameters.py",
        "tools/parse_gimli_output.py",
        "knowledge_infrastructure.yaml",
        "dag.yaml",
        "SKILL.md",
    ):
        check_file(checks, os.path.join(KI_DIR, relative), relative, critical=True)

    check_file(checks, TRIPLETS, "diagnostic triplets", critical=True)

    check_python_import(checks, "numpy", "numpy", critical=True)
    check_python_import(checks, "pygimli", "pyGIMLi / pgcore", critical=True)
    check_python_import(checks, "pygimli.physics.ert", "pyGIMLi ERT module", critical=True)
    check_python_import(
        checks,
        "pygimli.physics.traveltime",
        "pyGIMLi traveltime module",
        critical=True,
    )
    check_binary_starts(checks)

    failed = [c for c in checks if c["status"] == "fail"]
    print()
    print(f"  Results: {len(checks) - len(failed)} passed, {len(failed)} failed")
    if failed:
        print(f"  Recovery: inspect {TRIPLETS} first for known failure patterns.")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
