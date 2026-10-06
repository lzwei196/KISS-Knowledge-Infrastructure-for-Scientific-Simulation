#!/usr/bin/env python3
"""Preflight checks for the WASP knowledge infrastructure."""

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path


MODEL_ID = "WASP"
KI_DIR = Path(__file__).resolve().parent
TOOLS_DIR = KI_DIR / "tools"
DIAGNOSTICS = KI_DIR / "diagnostics" / "triplets.yaml"
PYTHON_ENV = Path("KISSPATH_PYTHON_ENV/bin/python3")
PYTHON = PYTHON_ENV if PYTHON_ENV.is_file() and os.access(PYTHON_ENV, os.X_OK) else Path(sys.executable)
RUN_WASP = TOOLS_DIR / "run_wasp.py"  # analytic SURROGATE (not EPA WASP)
RUN_WASP_ENGINE = TOOLS_DIR / "run_wasp_engine.py"  # REAL EPA WASP 8.5 engine under WINE
# Real-engine discovery -- same order as tools/run_wasp_engine.py (env var -> server default).
DEFAULT_WINEPREFIX = "KISSPATH_HOME/engine_builds_20261006/wasp/wineprefix"
WASP_ENGINE_REL = Path("drive_c/WASP8/wasp/bin/waspccli.exe")
WASP_EXTRACT_REL = Path("drive_c/WASP8/wasp/bin/BMD2_Extract.exe")


def make_check(kind, subject, critical, status, fix=""):
    check = {
        "kind": kind,
        "subject": str(subject),
        "critical": bool(critical),
        "status": status,
        "fix": fix,
    }
    shown = "WARN" if status != "pass" and not critical else status.upper()
    print(f"  {shown:4s} {kind:7s} {subject}")
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


def _kill_session(sid):
    """Kill the processes of our own probe's session by explicit PID (wine may leave helpers)."""
    for sig in (signal.SIGTERM, signal.SIGKILL):
        pids = []
        for d in os.listdir("/proc"):
            if not d.isdigit():
                continue
            try:
                with open(f"/proc/{d}/stat") as f:
                    st = f.read()
            except OSError:
                continue
            fields = st[st.rfind(")") + 2:].split()
            if len(fields) > 3 and fields[3] == str(sid) and fields[0] != "Z":
                pids.append(int(d))
        if not pids:
            return
        for pid in pids:
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                pass
        time.sleep(1)


def check_real_engine():
    """REAL EPA WASP engine (WINE). Non-critical: if missing, the SURROGATE path still works,
    but real-engine runs (tools/run_wasp_engine.py) will exit 3."""
    checks = []
    prefix = Path(os.environ.get("WASP_WINEPREFIX") or DEFAULT_WINEPREFIX).expanduser().absolute()
    wine = os.environ.get("WASP_WINE") or shutil.which("wine")
    if wine:
        wine = str(Path(wine).expanduser().absolute())  # same normalisation as the run tool
    src = "$WASP_WINE" if os.environ.get("WASP_WINE") else "PATH"
    fix_w = "Install WINE (wine 9.x) or set WASP_WINE to the wine executable; real-engine runs need it."
    if wine and Path(wine).is_file() and os.access(wine, os.X_OK):
        checks.append(make_check("binary", f"wine ({src}): {wine}", False, "pass"))
    else:
        checks.append(make_check("binary", f"wine ({src}): {wine}", False, "fail", fix_w))
        wine = None
    engine = prefix / WASP_ENGINE_REL
    fix_e = (f"Install EPA WASP 8.5 into a WINE prefix and set WASP_WINEPREFIX "
             f"(default {DEFAULT_WINEPREFIX}); see SKILL.md section 0.")
    if engine.is_file():
        checks.append(make_check("binary", f"REAL EPA WASP engine {engine}", False, "pass"))
    else:
        checks.append(make_check("binary", f"REAL EPA WASP engine {engine}", False, "fail", fix_e))
    extractor = prefix / WASP_EXTRACT_REL
    xcheck = make_check("binary", f"EPA BMD2_Extract {extractor}", False,
                        "pass" if extractor.is_file() else "fail",
                        "" if extractor.is_file() else "BMD2_Extract.exe ships with the WASP 8.5 install; "
                        "without it runs work but --extract fails.")
    checks.append(xcheck)
    if not (wine and engine.is_file()):
        return checks
    # start probe: waspccli with no arguments prints its usage line and exits
    env = dict(os.environ, WINEPREFIX=str(prefix), WINEDEBUG="-all")
    env.pop("DISPLAY", None)
    subject = "REAL engine start probe (wine waspccli.exe, no arguments)"
    with tempfile.TemporaryDirectory(prefix="wasp_preflight_engine_") as tmp:
        try:
            p = subprocess.Popen([wine, r"C:\WASP8\wasp\bin\waspccli.exe"], cwd=tmp, env=env, text=True,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                 start_new_session=True)
        except OSError as exc:
            checks.append(make_check("run", subject, False, "fail", f"cannot start wine: {exc}"))
            return checks
        def _on_term(signum, frame):
            raise KeyboardInterrupt(f"signal {signum}")
        old_handler = signal.signal(signal.SIGTERM, _on_term)
        try:
            out, _ = p.communicate(timeout=120)
        except subprocess.TimeoutExpired:
            _kill_session(p.pid)
            p.kill()
            out, _ = p.communicate()
            checks.append(make_check("run", subject, False, "fail",
                                     "waspccli did not answer within 120 s; check the WINE prefix."))
            return checks
        except BaseException:  # Ctrl-C / SIGTERM: kill the probe's processes by PID and reap
            _kill_session(p.pid)
            try:
                p.kill()
            except OSError:
                pass
            p.wait()
            raise
        finally:
            signal.signal(signal.SIGTERM, old_handler)
        _kill_session(p.pid)
    if "Usage: waspccli" in (out or ""):
        checks.append(make_check("run", subject, False, "pass"))
    else:
        last = (out or "").strip().splitlines()[-1:] or ["no output"]
        checks.append(make_check("run", subject, False, "fail",
                                 f"unexpected output ({last[0][:160]}); check WINE and the WASP install."))
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
        check_file(RUN_WASP, "WASP analytic SURROGATE tool", critical=True, executable=True),
        check_file(RUN_WASP_ENGINE, "REAL WASP engine run tool", critical=True, executable=True),
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
        check_tool_help(RUN_WASP_ENGINE),
        check_tool_help(TOOLS_DIR / "convert_forcing_to_wasp.py"),
        check_tool_help(TOOLS_DIR / "convert_parameters_to_wasp.py"),
        check_tool_help(TOOLS_DIR / "parse_output_wasp.py"),
    ]
    checks.extend(check_smoke_run())
    print()
    print("  REAL EPA WASP engine (non-critical; the surrogate path does not need it):")
    engine_checks = check_real_engine()
    checks.extend(engine_checks)

    print()
    passed = sum(1 for c in checks if c["status"] == "pass")
    critical_failed = sum(1 for c in checks if c["status"] != "pass" and c.get("critical"))
    warned = len(checks) - passed - critical_failed
    engine_ok = all(c["status"] == "pass" for c in engine_checks if not c["subject"].startswith("EPA BMD2_Extract"))
    extractor_ok = all(c["status"] == "pass" for c in engine_checks if c["subject"].startswith("EPA BMD2_Extract"))
    print(f"  Results: {passed} passed, {critical_failed} critical failed, {warned} warnings")
    print(f"  REAL engine (tools/run_wasp_engine.py): {'READY' if engine_ok else 'NOT READY - see WARN lines (runs will fail)'}")
    print(f"  Result extraction (BMD2_Extract, --extract): {'READY' if extractor_ok else 'NOT AVAILABLE'}")
    print(f"  SURROGATE (tools/run_wasp.py, not EPA WASP): {'READY' if not critical_failed else 'see failures'}")
    if critical_failed:
        print(f"  STATUS: PREFLIGHT FAILED - fix failed checks above; start with {DIAGNOSTICS}")
    elif warned:
        print("  STATUS: PREFLIGHT PASSED WITH WARNINGS - see WARN lines above")
    else:
        print("  STATUS: PREFLIGHT PASSED - WASP is ready for model execution (real engine + surrogate)")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
