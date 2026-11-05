#!/usr/bin/env python3
"""Preflight check for the LISFLOOD Knowledge Infrastructure.

This script checks the installed LISFLOOD runtime and KI-local support files
before model execution. It always emits the KDT preflight JSON report as the
last line of output.
"""

import json
import os
import py_compile
import re
import shutil
import subprocess
import sys
from pathlib import Path


MODEL_ID = "LISFLOOD"
KI_DIR = Path(__file__).resolve().parent
MANIFEST = KI_DIR / "knowledge_infrastructure.yaml"
DIAGNOSTICS = KI_DIR / "diagnostics" / "triplets.yaml"
DEFAULT_BINARY = Path("KISSPATH_HOME/miniconda3/envs/lisflood/bin/lisflood")
# Separate env built from LISFLOOD's own environment.yml (py3.7, old xarray/dask);
# needed ONLY for the official chunked-NetCDF test case inputs. GeoForge runs use
# the env above, so this is a non-critical info check.
OFFICIAL_CASE_BINARY = Path("KISSPATH_HOME/miniconda3/envs/lisflood_official/bin/lisflood")
PROBE_TIMEOUT = 180
IMPORT_MODULES = [
    "lisflood",
    "netCDF4",
    "numpy",
    "numba",
    "pcraster",
    "xarray",
    "pandas",
    "lxml",
    "bs4",
]
KI_FILES = [
    "SKILL.md",
    "knowledge_infrastructure.yaml",
    "dag.yaml",
    "diagnostics/triplets.yaml",
    "tools/run_lisflood.py",
    "tools/convert_forcing.py",
    "tools/convert_soil_params.py",
    "tools/parse_output.py",
]


def diagnostic_fix(message):
    return f"{message}; then check {DIAGNOSTICS} for matching recovery triplets."


def add_check(checks, kind, subject, critical, ok, fix=""):
    checks.append(
        {
            "kind": kind,
            "subject": str(subject),
            "critical": bool(critical),
            "status": "pass" if ok else "fail",
            "fix": "" if ok else fix,
        }
    )


def emit_report(model_id, checks):
    failed = [c for c in checks if c["status"] == "fail"]
    critical_failed = [c for c in failed if c.get("critical")]
    if failed:
        print()
        print("Fixes for failed checks:")
        for c in failed:
            print(f"  - {c['kind']} {c['subject']}: {c['fix']}")
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}))
    sys.exit(1 if critical_failed else 0)


def manifest_binary_path():
    if not MANIFEST.is_file():
        return DEFAULT_BINARY

    in_binary = False
    for raw in MANIFEST.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if stripped == "binary:":
            in_binary = True
            continue
        if in_binary and stripped.startswith("path:"):
            value = stripped.split(":", 1)[1].strip().strip("'\"")
            return Path(value) if value else DEFAULT_BINARY
        if in_binary and raw and not raw.startswith(" "):
            break
    return DEFAULT_BINARY


def check_required_files(checks):
    for relpath in KI_FILES:
        path = KI_DIR / relpath
        add_check(
            checks,
            "data",
            path,
            relpath != "diagnostics/triplets.yaml",
            path.is_file(),
            diagnostic_fix(f"Restore or regenerate required KI file {path}"),
        )


def check_tool_syntax(checks):
    for relpath in KI_FILES:
        if not relpath.endswith(".py"):
            continue
        path = KI_DIR / relpath
        if not path.is_file():
            continue
        try:
            py_compile.compile(str(path), doraise=True)
            add_check(checks, "import", path, False, True)
        except py_compile.PyCompileError as exc:
            add_check(
                checks,
                "import",
                path,
                False,
                False,
                diagnostic_fix(f"Fix Python syntax error in {path}: {exc.msg}"),
            )


def check_binary(checks, binary):
    binary_realpath = Path(os.path.realpath(binary)) if binary.exists() else binary
    ok = binary.is_file() and os.access(binary, os.X_OK)
    add_check(
        checks,
        "binary",
        binary_realpath,
        True,
        ok,
        diagnostic_fix(f"Install LISFLOOD or chmod +x the executable at {binary}"),
    )
    return binary_realpath, ok


def run_env_python(binary):
    if binary.is_file():
        try:
            first = binary.read_text(encoding="utf-8", errors="ignore").splitlines()[0]
            if first.startswith("#!"):
                interpreter = Path(first[2:].strip().split()[0])
                if interpreter.is_file():
                    return interpreter
        except OSError:
            pass
    fallback = binary.parent / "python"
    return fallback if fallback.is_file() else None


def check_runtime_imports(checks, python_exe):
    if not python_exe:
        for module in IMPORT_MODULES:
            add_check(
                checks,
                "import",
                module,
                True,
                False,
                diagnostic_fix("Cannot run LISFLOOD import checks because the environment Python was not found"),
            )
        return

    for module in IMPORT_MODULES:
        snippet = f"import {module}; print(getattr({module}, '__file__', 'built-in'))"
        subject = f"{python_exe}:import {module}"
        try:
            result = subprocess.run(
                [str(python_exe), "-c", snippet],
                cwd=str(KI_DIR),
                capture_output=True,
                text=True,
                timeout=PROBE_TIMEOUT,
            )
            ok = result.returncode == 0
            detail = (result.stderr or result.stdout or "").strip().splitlines()
            last_line = detail[-1] if detail else ""
        except subprocess.TimeoutExpired:
            ok = False
            last_line = f"import did not finish within {PROBE_TIMEOUT}s"
        except OSError as exc:
            ok = False
            last_line = f"cannot start {python_exe}: {exc}"
        fix = diagnostic_fix(
            f"Repair package {module} in {python_exe.parent.parent}; last error: {last_line}"
        )
        add_check(checks, "import", subject, True, ok, fix)


def check_binary_starts(checks, binary):
    if not (binary.is_file() and os.access(binary, os.X_OK)):
        return

    # LISFLOOD reads argument 1 as the settings XML path, so `--help`/`--version`
    # are not valid probes. With no arguments it prints its banner (with
    # "Version:") and the usage text ("settings.xml"), then exits 1.
    subject = f"{binary} (no arguments: banner + usage)"
    try:
        result = subprocess.run(
            [str(binary)],
            cwd=str(KI_DIR),
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        add_check(checks, "run", subject, True, False, diagnostic_fix(
            f"Make the LISFLOOD CLI start cleanly; `{binary}` with no arguments did not finish within {PROBE_TIMEOUT}s"))
        return
    except OSError as exc:
        add_check(checks, "run", subject, True, False, diagnostic_fix(
            f"Make the LISFLOOD CLI start cleanly; cannot start {binary}: {exc}"))
        return
    combined = (result.stdout or "") + "\n" + (result.stderr or "")
    version = re.search(r"^\s*Version:\s*(\S+)", combined, flags=re.M)
    ok = (
        result.returncode in (0, 1)
        and "Lisflood" in combined
        and version is not None
        and "settings.xml" in combined
        and "Traceback" not in combined
    )
    if version:
        subject = f"{binary} (no arguments) -> Version {version.group(1)}"
    output = combined.strip().splitlines()
    last_line = output[-1].strip() if output else f"exit code {result.returncode}"
    add_check(
        checks,
        "run",
        subject,
        True,
        ok,
        diagnostic_fix(
            f"Make the LISFLOOD CLI start cleanly (expected banner with Version: and usage text, "
            f"exit 0/1; got exit {result.returncode}); last line: {last_line}"
        ),
    )


def resolve_tool_engine():
    """The engine tools/run_lisflood.py would run without --lisflood-bin, from the tool's own
    resolve_lisflood_bin() ($LISFLOOD_BIN -> server default -> PATH only if the default is
    absent). Returns (Path, source) or (None, error text)."""
    import importlib.util
    old = sys.dont_write_bytecode
    sys.dont_write_bytecode = True  # no __pycache__ in the live tools folder
    try:
        spec = importlib.util.spec_from_file_location(
            "_ki_run_lisflood", KI_DIR / "tools" / "run_lisflood.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        path, source = module.resolve_lisflood_bin(None)
        return Path(path), source
    except Exception as exc:  # import or resolution failure
        return None, f"{type(exc).__name__}: {exc}"
    finally:
        sys.dont_write_bytecode = old


def check_tool_engine(checks, binary, source):
    # The binary checked here IS the run tool's own choice (no PATH requirement any more).
    add_check(
        checks,
        "run",
        f"tools/run_lisflood.py engine lookup -> {binary or 'none'} ({source})",
        True,
        binary is not None,
        diagnostic_fix(
            f"tools/run_lisflood.py cannot select a LISFLOOD engine ({source}); give it with "
            f"--lisflood-bin (run tool) or $LISFLOOD_BIN (run tool and this preflight), or restore "
            f"the server default {DEFAULT_BINARY}"
        ),
    )


def check_official_case_env(checks):
    ok = OFFICIAL_CASE_BINARY.is_file() and os.access(OFFICIAL_CASE_BINARY, os.X_OK)
    add_check(
        checks,
        "binary",
        f"{OFFICIAL_CASE_BINARY} (info: only for the official chunked-NetCDF test case)",
        False,
        ok,
        "Optional: the official LISFLOOD test case inputs (chunked NetCDF) need the separate env "
        "lisflood_official built from LISFLOOD's environment.yml; GeoForge runs do not need it",
    )
    print(f"Official test case env: {OFFICIAL_CASE_BINARY} "
          f"({'present' if ok else 'missing - optional, not needed for GeoForge runs'})")


def main():
    checks = []
    manifest_binary = manifest_binary_path()
    binary, engine_source = resolve_tool_engine()

    print(f"{' PREFLIGHT: LISFLOOD ':=^60}")
    print(f"KI directory: {KI_DIR}")
    print(f"Diagnostics: {DIAGNOSTICS}")
    print(f"Executable from manifest: {manifest_binary}")
    print(f"Engine used by tools/run_lisflood.py: {binary or 'NONE'} ({engine_source})")

    check_required_files(checks)
    check_tool_syntax(checks)
    check_tool_engine(checks, binary, engine_source)
    if binary is None:
        # no fallback to another engine: the run tool would fail the same way
        check_official_case_env(checks)
        passed = sum(1 for c in checks if c["status"] == "pass")
        print(f"Results: {passed} passed, {len(checks) - passed} failed")
        emit_report(MODEL_ID, checks)
        return
    _, binary_ok = check_binary(checks, binary)

    python_exe = run_env_python(binary) if binary_ok else None
    if python_exe:
        add_check(checks, "binary", python_exe, True, True)
    else:
        add_check(
            checks,
            "binary",
            binary.parent / "python",
            True,
            False,
            diagnostic_fix("Restore the LISFLOOD environment Python next to the executable"),
        )

    check_runtime_imports(checks, python_exe)
    check_binary_starts(checks, binary)
    check_official_case_env(checks)

    passed = sum(1 for c in checks if c["status"] == "pass")
    failed = len(checks) - passed
    print(f"Results: {passed} passed, {failed} failed")
    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
