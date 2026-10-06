#!/usr/bin/env python3
"""Preflight check for the pyGIMLi knowledge infrastructure."""

import json
import os
import subprocess
import sys
import tempfile


MODEL_ID = "pyGIMLi"
KI_DIR = os.path.dirname(os.path.abspath(__file__))
# pyGIMLi is not in HydroCraft python_env; it lives in its own venv. Lookup, same as
# the official test cases: $PYGIMLI_PYTHON -> the server venv. An explicit value is
# used as-is (no silent fallback). The venv path is executed as given (not its
# realpath), so the venv's site-packages are used.
DEFAULT_PYTHON = "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/pyGIMLi/venv/bin/python"
PYTHON = os.environ.get("PYGIMLI_PYTHON", "").strip() or DEFAULT_PYTHON
HYDROCRAFT_PYTHON = "KISSPATH_PYTHON_ENV/bin/python"
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


def run_command(argv, timeout=20, env=None, cwd=None):
    try:
        return subprocess.run(
            argv,
            cwd=cwd or KI_DIR,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
    except OSError as exc:
        return exc
    except subprocess.TimeoutExpired as exc:
        return exc


def command_detail(result):
    if isinstance(result, OSError):
        return str(result)
    if isinstance(result, subprocess.TimeoutExpired):
        return f"timed out after {result.timeout}s"
    output = "\n".join(part.strip() for part in (result.stdout, result.stderr) if part.strip())
    return output.splitlines()[-1] if output else f"exit code {result.returncode}"


def check_file(checks, path, label, critical=True, executable=False, keep_path=False):
    subject = os.path.realpath(path) if os.path.exists(path) and not keep_path else path
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


def check_site_packages(checks):
    """Ask the selected interpreter for its own site-packages (purelib)."""
    result = run_command(
        [PYTHON, "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
    )
    ok = not isinstance(result, Exception) and result.returncode == 0
    path = result.stdout.strip() if ok else ""
    if ok and os.path.isdir(path):
        check_dir(checks, path, "pyGIMLi Python site-packages", critical=True)
        return True
    checks.append(
        check(
            "data",
            f"site-packages of {PYTHON}",
            True,
            False,
            (
                f"Could not find site-packages of {PYTHON} (set PYGIMLI_PYTHON to a Python "
                f"with pygimli, default {DEFAULT_PYTHON}); check {TRIPLETS}."
            ),
            command_detail(result) if not ok else f"not a directory: {path}",
        )
    )
    return False


def check_python_import(checks, module, label, critical=True, python=None, fix=None):
    python = python or PYTHON
    result = run_command(
        [
            python,
            "-c",
            (
                "import importlib; "
                f"m = importlib.import_module({module!r}); "
                "v = getattr(m, '__version__', 'import-ok')\n"
                "try:\n"
                "    from importlib.metadata import version\n"
                f"    v = version({module.split('.')[0]!r})\n"
                "except Exception:\n"
                "    pass\n"
                "print(v)"
            ),
        ],
        timeout=180,
    )
    passed = not isinstance(result, Exception) and result.returncode == 0
    checks.append(
        check(
            "import",
            f"{module} via {python} (realpath {os.path.realpath(python)})",
            critical,
            passed,
            fix or (
                f"Install/repair {label} in {python} (or set PYGIMLI_PYTHON to a Python "
                f"with pygimli, default {DEFAULT_PYTHON}); start with diagnostics in "
                f"{TRIPLETS}."
            ),
            result.stdout.strip().splitlines()[-1] if passed and result.stdout.strip()
            else ("" if passed else command_detail(result)),
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


def check_launch_route(checks):
    """Check the launch route SKILL.md and GeoForge use: python_env starts run_pygimli.py,
    which re-launches itself with the pyGIMLi python and imports pygimli there.

    `--help` cannot test this (argparse exits before the engine is chosen), so the tool is
    started with a data file that does not exist: the re-launched python runs
    validate_inputs(), which imports pygimli and then stops with exactly one error,
    "Data file not found". No model is run and nothing is written. The environment is
    passed through unchanged, so $PYGIMLI_PYTHON is honoured as the tool would honour it.
    """
    selected = os.path.abspath(PYTHON)
    subject = (f"launch route: {HYDROCRAFT_PYTHON} tools/run_pygimli.py -> re-launch with "
               f"{selected} -> import pygimli")
    missing = ""
    try:
        with tempfile.TemporaryDirectory(prefix="pygimli_preflight_") as tmp:
            missing = os.path.join(tmp, "__preflight_missing__.ohm")
            result = run_command(
                [HYDROCRAFT_PYTHON, BINARY, "--data", missing, "--method", "ert",
                 "--mode", "forward", "--output", os.path.join(tmp, "out")],
                timeout=180,
                cwd=tmp,
            )
    except OSError as exc:  # temp dir could not be made/removed (disk full, no inodes)
        result = exc
    problem = ""
    if isinstance(result, Exception):
        problem = command_detail(result)
    else:
        lines = [ln.strip() for ln in result.stderr.splitlines() if ln.strip()]
        relaunch = f"[run_pygimli.py] re-launching with {selected} ("
        needs_relaunch = selected != os.path.abspath(HYDROCRAFT_PYTHON)
        last_json = None
        for line in reversed(lines):
            if line.startswith("{"):
                try:
                    last_json = json.loads(line)
                except ValueError:
                    last_json = None
                break
        expected = {"status": "error", "errors": [f"Data file not found: {missing}"]}
        if result.returncode != 1:
            problem = f"exit code {result.returncode}, expected 1"
        elif needs_relaunch and not any(ln.startswith(relaunch) for ln in lines):
            problem = f"no re-launch with {selected}"
        elif last_json != expected:
            problem = "tool did not stop with only the expected 'Data file not found' error"
        if problem:
            tail = " | ".join(lines[-3:]) if lines else command_detail(result)
            problem = f"{problem}; stderr: {tail}"
    passed = not problem
    checks.append(
        check(
            "run",
            subject,
            True,
            passed,
            (
                f"The SKILL.md launch line (python_env + tools/run_pygimli.py) does not reach "
                f"pygimli. Make PYGIMLI_PYTHON point to a working pyGIMLi Python (default "
                f"{DEFAULT_PYTHON}) or unset it, then check {TRIPLETS}."
            ),
            "" if passed else problem,
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

    check_file(
        checks,
        PYTHON,
        "pyGIMLi Python interpreter (PYGIMLI_PYTHON or venv)",
        critical=True,
        executable=True,
        keep_path=True,
    )
    check_site_packages(checks)
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
    engine_ok = all(c["status"] == "pass" for c in checks if c.get("critical"))
    # The real launch route: SKILL.md starts the tools with HydroCraft python_env (no
    # pygimli); run_pygimli.py re-launches itself with the pyGIMLi python.
    route_ok = check_launch_route(checks)

    failed = [c for c in checks if c["status"] == "fail"]
    print()
    print(f"  Results: {len(checks) - len(failed)} passed, {len(failed)} failed")
    if engine_ok:
        print(f"  Checked engine: {PYTHON} OK.")
    else:
        print(
            f"  Checked engine: {PYTHON} FAILED; repair it or set PYGIMLI_PYTHON to a "
            "working pyGIMLi Python, then rerun this preflight."
        )
    if route_ok:
        print("  Launch route OK: python_env tools/run_pygimli.py re-launches with "
              f"{os.path.abspath(PYTHON)} and imports pygimli (start the tools with "
              "python_env as SKILL.md says).")
    else:
        print("  Launch route FAILED: python_env tools/run_pygimli.py does not reach "
              "pygimli; see the check above.")
    if failed:
        print(f"  Recovery: inspect {TRIPLETS} first for known failure patterns.")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
