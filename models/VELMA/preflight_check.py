#!/usr/bin/env python3
"""Preflight check for the VELMA Knowledge Infrastructure."""

import json
import os
import shutil
import subprocess
import sys


MODEL_ID = "VELMA"
KI_DIR = os.path.dirname(os.path.abspath(__file__))
TOOLS_DIR = os.path.join(KI_DIR, "tools")
# Python SURROGATE (lumped 4-layer stand-in, NOT EPA VELMA); kept, checked non-critically.
RUN_VELMA = os.path.join(TOOLS_DIR, "run_velma.py")
# REAL engine: EPA VELMA 2.1 JVelma.jar, driven headless by tools/run_velma_engine.py.
RUN_ENGINE = os.path.join(TOOLS_DIR, "run_velma_engine.py")
ENGINE_LAUNCHER = "KISSPATH_HOME/engine_builds_20261006/VELMA/run_velma_headless.sh"
ENGINE_JAR = "KISSPATH_HOME/engine_builds_20261006/VELMA/jars/JVelma.jar"
TRIPLETS = os.path.join(KI_DIR, "diagnostics", "triplets.yaml")
# interpreter for the import checks: $KI_PYTHON, else the HydroCraft python_env, else this python
_ENV_PY = os.environ.get("KI_PYTHON", "")
PYTHON_ENV = "KISSPATH_PYTHON_ENV/bin/python3"
if _ENV_PY and os.path.exists(_ENV_PY):
    PYTHON = _ENV_PY
elif os.path.exists(PYTHON_ENV):
    PYTHON = PYTHON_ENV
else:
    PYTHON = sys.executable
CHECKS = []


def recovery_hint(fix):
    return f"{fix}; see {TRIPLETS} for recovery."


def add_check(kind, subject, critical, status, fix=""):
    CHECKS.append(
        {
            "kind": kind,
            "subject": subject,
            "critical": bool(critical),
            "status": status,
            "fix": fix,
        }
    )


def line(status, label, detail):
    print(f"  {status:<5} {label}: {detail}")


def check_file(path, label, critical=True, executable=False):
    subject = os.path.realpath(path)
    if not os.path.isfile(path):
        fix = recovery_hint(f"Restore required file at {path}")
        line("FAIL", label, f"NOT FOUND at {path}")
        add_check("binary" if executable else "data", subject, critical, "fail", fix)
        return False
    if executable and not os.access(path, os.X_OK):
        fix = recovery_hint(f"Run: chmod +x {path}")
        line("FAIL", label, f"exists but is not executable: {path}")
        add_check("binary", subject, critical, "fail", fix)
        return False
    line("OK", label, subject)
    add_check("binary" if executable else "data", subject, critical, "pass", "")
    return True


def check_dir(path, label, critical=True):
    subject = os.path.realpath(path)
    if os.path.isdir(path):
        n_items = len(os.listdir(path))
        line("OK", label, f"{subject} ({n_items} items)")
        add_check("data", subject, critical, "pass", "")
        return True
    fix = recovery_hint(f"Restore required directory at {path}")
    line("FAIL", label, f"directory NOT FOUND at {path}")
    add_check("data", subject, critical, "fail", fix)
    return False


def check_import(module, label, critical=True):
    subject = f"{os.path.realpath(PYTHON)}:import:{module}"
    code = f"import importlib; importlib.import_module({module!r})"
    try:
        subprocess.run(
            [PYTHON, "-c", code],
            cwd=KI_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15,
            check=True,
        )
    except (subprocess.CalledProcessError, OSError, subprocess.TimeoutExpired) as exc:
        detail = str(exc)
        if isinstance(exc, subprocess.CalledProcessError):
            detail = (exc.stderr or exc.stdout or str(exc)).strip()
        fix = recovery_hint(
            f"Install {module.split('.')[0]} for {PYTHON} or restore the HydroCraft python_env"
        )
        line("FAIL", label, f"import {module} failed: {detail}")
        add_check("import", subject, critical, "fail", fix)
        return False
    line("OK", label, f"{subject}")
    add_check("import", subject, critical, "pass", "")
    return True


def check_help_start(path, label, critical=True, marker="Run VELMA"):
    subject = os.path.realpath(path)
    try:
        result = subprocess.run(
            [PYTHON, subject, "--help"],
            cwd=KI_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        fix = recovery_hint(f"Verify the shebang and executable permissions for {path}")
        line("FAIL", label, f"could not start: {exc}")
        add_check("run", subject, critical, "fail", fix)
        return False
    if result.returncode != 0 or marker not in result.stdout:
        fix = recovery_hint(f"Run {path} --help and repair its imports/CLI")
        detail = (result.stderr or result.stdout or "").strip()
        line("FAIL", label, f"--help exited {result.returncode}: {detail}")
        add_check("run", subject, critical, "fail", fix)
        return False
    line("OK", label, "--help starts and reports the VELMA CLI")
    add_check("run", subject, critical, "pass", "")
    return True


def check_engine_starts(critical=True):
    """java + JVelma.jar: the command-line class must print its version banner."""
    subject = f"{ENGINE_JAR}:gov.epa.velmasimulator.VelmaSimulatorCmdLine"
    java = shutil.which("java")
    if not java:
        line("FAIL", "java", "java not on PATH (VELMA 2.1 needs Java 7+)")
        add_check("binary", "java", critical, "fail", recovery_hint("Install a JDK/JRE (OpenJDK 21 works)"))
        return False
    try:
        result = subprocess.run(
            [java, "-Djava.awt.headless=true", "-cp", ENGINE_JAR,
             "gov.epa.velmasimulator.VelmaSimulatorCmdLine"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=60, check=False)
        out = result.stdout or ""
    except (OSError, subprocess.TimeoutExpired) as exc:
        out = str(exc)
    if "VELMA_2.1" not in out or "Usage: VelmaSimulatorCmdLine" not in out:
        line("FAIL", "VELMA engine startup", f"no VELMA_2.1 banner: {out.strip()[:200]}")
        add_check("run", subject, critical, "fail",
                  recovery_hint(f"Check {ENGINE_JAR} and java; see KISSPATH_HOME/engine_builds_20261006/VELMA/BUILD_LOG.md"))
        return False
    line("OK", "VELMA engine startup", out.strip().splitlines()[0])
    add_check("run", subject, critical, "pass", "")
    return True


def emit_report():
    print(
        "PREFLIGHT_REPORT="
        + json.dumps({"model_id": MODEL_ID, "checks": CHECKS}, sort_keys=True)
    )
    critical_failed = any(c["critical"] and c["status"] != "pass" for c in CHECKS)
    sys.exit(1 if critical_failed else 0)


def main():
    print(f"{' PREFLIGHT: VELMA ':=^60}")
    print(f"  Python for import checks: {PYTHON}")
    print()

    check_dir(TOOLS_DIR, "KI tools directory", critical=True)
    # REAL engine (critical): launcher, jar, java start-up, KI run tool
    check_file(ENGINE_LAUNCHER, "VELMA 2.1 engine launcher", critical=True, executable=True)
    check_file(ENGINE_JAR, "VELMA 2.1 JVelma.jar", critical=True)
    check_engine_starts(critical=True)
    check_file(RUN_ENGINE, "real-engine run tool", critical=True, executable=True)
    check_help_start(RUN_ENGINE, "real-engine run tool CLI", critical=True,
                     marker="REAL EPA VELMA 2.1")
    check_file(os.path.join(TOOLS_DIR, "build_velma_weather_from_source.py"),
               "engine weather-driver tool", critical=True)
    # Python SURROGATE (non-critical): not the EPA model
    check_file(RUN_VELMA, "Python SURROGATE run_velma.py", critical=False)
    check_help_start(RUN_VELMA, "Python SURROGATE CLI", critical=False)

    for rel_path in (
        "knowledge_infrastructure.yaml",
        "dag.yaml",
        "docs/surrogate_velma_4layer_dag.yaml",
        "SKILL.md",
        "docs/format_spec.yaml",
        "diagnostics/triplets.yaml",
        "tools/convert_forcing_to_velma.py",
        "tools/convert_soil_to_velma.py",
        "tools/parse_output_velma.py",
    ):
        check_file(os.path.join(KI_DIR, rel_path), rel_path, critical=True)

    for module in (
        "numpy",
        "pandas",
        "scipy",
        "xarray",
        "geopandas",
        "shapely",
        "netCDF4",
    ):
        check_import(module, module, critical=True)
    check_import("matplotlib", "matplotlib", critical=False)

    passed = sum(1 for c in CHECKS if c["status"] == "pass")
    failed = len(CHECKS) - passed
    print()
    print(f"  Results: {passed} passed, {failed} failed")
    if failed:
        print(f"  STATUS: PREFLIGHT FAILED; fixes point to {TRIPLETS}")
    else:
        print("  STATUS: PREFLIGHT PASSED")
    emit_report()


if __name__ == "__main__":
    main()
