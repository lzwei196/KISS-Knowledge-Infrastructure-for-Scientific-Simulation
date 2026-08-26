#!/usr/bin/env python3
"""Preflight checks for the WASP knowledge infrastructure."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


MODEL_ID = "WASP"
KI_DIR = Path(__file__).resolve().parent
TOOLS_DIR = KI_DIR / "tools"
DIAGNOSTICS = KI_DIR / "diagnostics" / "triplets.yaml"
PYTHON_ENV = Path("KISSPATH_PYTHON_ENV/bin/python3")
PYTHON = PYTHON_ENV if PYTHON_ENV.is_file() and os.access(PYTHON_ENV, os.X_OK) else Path(sys.executable)
RUN_WASP = TOOLS_DIR / "run_wasp.py"


def make_check(kind, subject, critical, status, fix=""):
    check = {
        "kind": kind,
        "subject": str(subject),
        "critical": bool(critical),
        "status": status,
        "fix": fix,
    }
    print(f"  {status.upper():4s} {kind:7s} {subject}")
    if status != "pass" and fix:
        print(f"       Fix: {fix}")
    return check


def check_file(path, label, critical=True, executable=False):
    path = Path(path)
    subject = path.resolve() if path.exists() else path
    if not path.is_file():
        return make_check(
            "data",
            subject,
            critical,
            "fail",
            f"Restore {label}; consult {DIAGNOSTICS} for recovery.",
        )
    if executable and not os.access(path, os.X_OK):
        return make_check(
            "binary",
            subject.resolve(),
            critical,
            "fail",
            f"Run: chmod +x {path}; then check {DIAGNOSTICS} if execution still fails.",
        )
    return make_check("binary" if executable else "data", subject.resolve(), critical, "pass")


def check_dir(path, label, critical=True, min_items=1):
    path = Path(path)
    subject = path.resolve() if path.exists() else path
    if not path.is_dir():
        return make_check(
            "data",
            subject,
            critical,
            "fail",
            f"Restore {label}; consult {DIAGNOSTICS} for recovery.",
        )
    items = list(path.iterdir())
    if len(items) < min_items:
        return make_check(
            "data",
            subject.resolve(),
            critical,
            "fail",
            f"Populate {label}; consult {DIAGNOSTICS} for recovery.",
        )
    return make_check("data", subject.resolve(), critical, "pass")


def run_command(kind, subject, command, critical=True, timeout=20, fix=""):
    try:
        result = subprocess.run(
            [str(part) for part in command],
            cwd=str(KI_DIR),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return make_check(
            kind,
            subject,
            critical,
            "fail",
            fix or f"Command timed out; check {DIAGNOSTICS} for matching execution failures.",
        )
    except OSError as exc:
        return make_check(
            kind,
            subject,
            critical,
            "fail",
            fix or f"Could not start command: {exc}; check {DIAGNOSTICS}.",
        )

    if result.returncode == 0:
        return make_check(kind, subject, critical, "pass")

    detail = (result.stderr or result.stdout or "").strip().splitlines()
    if detail:
        print(f"       Detail: {detail[-1][:240]}")
    return make_check(
        kind,
        subject,
        critical,
        "fail",
        fix or f"Command exited {result.returncode}; check {DIAGNOSTICS} for recovery.",
    )


def check_import(module, critical=True):
    subject = f"{PYTHON} import {module}"
    code = f"import {module}; print({module.split('.')[0]}.__name__)"
    return run_command(
        "import",
        subject,
        [PYTHON, "-c", code],
        critical=critical,
        timeout=15,
        fix=f"Install {module.split('.')[0]} in {Path(PYTHON).parent.parent}: {PYTHON} -m pip install {module.split('.')[0]}; then check {DIAGNOSTICS}.",
    )


def check_python_env():
    if PYTHON_ENV.is_file() and os.access(PYTHON_ENV, os.X_OK):
        return make_check("import", PYTHON_ENV.resolve(), True, "pass")
    return make_check(
        "import",
        PYTHON_ENV,
        True,
        "fail",
        f"Restore the HydroCraft Python environment or update the KI to the correct interpreter; see {DIAGNOSTICS}.",
    )


def check_tool_help(tool):
    tool = Path(tool)
    return run_command(
        "run",
        tool.resolve(),
        [PYTHON, tool, "--help"],
        critical=True,
        timeout=20,
        fix=f"Fix CLI/import errors in {tool}; consult {DIAGNOSTICS} for known WASP failures.",
    )


def check_smoke_run():
    with tempfile.TemporaryDirectory(prefix="wasp_preflight_") as tmp:
        tmpdir = Path(tmp)
        params = tmpdir / "params.json"
        output = tmpdir / "profile.json"
        checks = []

        params_check = run_command(
            "run",
            "convert_parameters_to_wasp lake-preset erie",
            [PYTHON, TOOLS_DIR / "convert_parameters_to_wasp.py", "--lake-preset", "erie", "--output", params],
            critical=True,
            timeout=30,
            fix=f"Fix parameter generation; check {DIAGNOSTICS} for unit/configuration triplets.",
        )
        checks.append(params_check)
        if params_check["status"] != "pass":
            return checks

        run_check = run_command(
            "run",
            "run_wasp profile smoke test",
            [PYTHON, RUN_WASP, "--mode", "profile", "--params", params, "--z-max", "5", "--z-step", "1", "--output", output],
            critical=True,
            timeout=30,
            fix=f"Fix WASP profile execution; check {DIAGNOSTICS} for matching errors.",
        )
        checks.append(run_check)
        if run_check["status"] != "pass":
            return checks

        try:
            data = json.loads(output.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            checks.append(
                make_check(
                    "run",
                    "run_wasp profile smoke test output",
                    True,
                    "fail",
                    f"Smoke output was not valid JSON ({exc}); check {DIAGNOSTICS}.",
                )
            )
            return checks

        if data.get("status") == "success" and data.get("mode") == "profile":
            checks.append(make_check("run", "run_wasp profile smoke test output", True, "pass"))
            return checks

        checks.append(
            make_check(
                "run",
                "run_wasp profile smoke test output",
                True,
                "fail",
                f"Unexpected smoke output status: {data.get('status')!r}; check {DIAGNOSTICS}.",
            )
        )
        return checks


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}, sort_keys=True))
    critical_failed = any(c["status"] != "pass" and c.get("critical") for c in checks)
    sys.exit(1 if critical_failed else 0)


def main():
    print("=" * 60)
    print(f"  PREFLIGHT CHECK: {MODEL_ID}")
    print("=" * 60)
    print(f"  KI directory: {KI_DIR}")
    print(f"  Python: {PYTHON}")
    print(f"  Diagnostics: {DIAGNOSTICS}")
    print()

    checks = [
        check_python_env(),
        check_dir(TOOLS_DIR, "WASP tools directory", critical=True, min_items=4),
        check_file(RUN_WASP, "WASP executable", critical=True, executable=True),
        check_file(TOOLS_DIR / "convert_forcing_to_wasp.py", "forcing converter", critical=True, executable=True),
        check_file(TOOLS_DIR / "convert_parameters_to_wasp.py", "parameter converter", critical=True, executable=True),
        check_file(TOOLS_DIR / "parse_output_wasp.py", "output parser", critical=True, executable=True),
        check_file(KI_DIR / "knowledge_infrastructure.yaml", "KI manifest", critical=True),
        check_file(KI_DIR / "dag.yaml", "DAG contract", critical=True),
        check_file(KI_DIR / "SKILL.md", "operator instructions", critical=True),
        check_file(DIAGNOSTICS, "diagnostic triplets", critical=True),
        check_file(KI_DIR / "docs" / "format_spec.yaml", "format specification", critical=False),
        check_import("numpy", critical=True),
        check_import("pandas", critical=True),
        check_import("scipy", critical=True),
        check_import("matplotlib", critical=False),
        check_tool_help(RUN_WASP),
        check_tool_help(TOOLS_DIR / "convert_forcing_to_wasp.py"),
        check_tool_help(TOOLS_DIR / "convert_parameters_to_wasp.py"),
        check_tool_help(TOOLS_DIR / "parse_output_wasp.py"),
    ]
    checks.extend(check_smoke_run())

    print()
    passed = sum(1 for c in checks if c["status"] == "pass")
    failed = len(checks) - passed
    print(f"  Results: {passed} passed, {failed} failed")
    if failed:
        print(f"  STATUS: PREFLIGHT FAILED - fix failed checks above; start with {DIAGNOSTICS}")
    else:
        print("  STATUS: PREFLIGHT PASSED - WASP is ready for model execution")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
