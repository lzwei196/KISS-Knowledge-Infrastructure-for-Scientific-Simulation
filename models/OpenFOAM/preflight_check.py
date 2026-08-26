#!/usr/bin/env python3
"""Preflight checks for the OpenFOAM knowledge infrastructure."""

import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


MODEL_ID = "OpenFOAM"
KI_DIR = Path(__file__).resolve().parent
HYDROCRAFT_PYTHON = Path("KISSPATH_PYTHON_ENV/bin/python")
MANIFEST = KI_DIR / "knowledge_infrastructure.yaml"
DIAGNOSTIC_TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"
OPENFOAM_BINARY_FROM_MANIFEST = (
    "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/OpenFOAM/"
    "source/repo/platforms/linux64GccDPInt32Opt/bin/foamRun"
)
REQUIRED_TOOL_MODULES = [
    "tools.check_case",
    "tools.configure_case",
    "tools.convert_forcing_to_openfoam",
    "tools.convert_properties_to_openfoam",
    "tools.generate_mesh",
    "tools.parse_openfoam_output",
    "tools.run_openfoam",
]
REQUIRED_FILES = [
    "SKILL.md",
    "knowledge_infrastructure.yaml",
    "dag.yaml",
    "docs/format_spec.yaml",
    "diagnostics/triplets.yaml",
    "tools/check_case.py",
    "tools/configure_case.py",
    "tools/convert_forcing_to_openfoam.py",
    "tools/convert_properties_to_openfoam.py",
    "tools/generate_mesh.py",
    "tools/parse_openfoam_output.py",
    "tools/run_openfoam.py",
]


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}))
    failed_critical = any(
        c["status"] != "pass" and c.get("critical") for c in checks
    )
    sys.exit(1 if failed_critical else 0)


def add_check(checks, kind, subject, critical, ok, fix=""):
    status = "pass" if ok else "fail"
    check = {
        "kind": kind,
        "subject": str(subject),
        "critical": bool(critical),
        "status": status,
        "fix": "" if ok else fix,
    }
    checks.append(check)
    prefix = "OK" if ok else "FAIL"
    print(f"  {prefix:<5} {kind}: {subject}")
    if not ok and fix:
        print(f"        Fix: {fix}")
    return ok


def run_command(command, env=None, timeout=20):
    return subprocess.run(
        command,
        cwd=str(KI_DIR),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )


def source_openfoam_env(bashrc):
    if not bashrc or not bashrc.is_file():
        return os.environ.copy()

    proc = run_command(
        ["bash", "-lc", f"source {shlex_quote(str(bashrc))} >/dev/null 2>&1 && env"],
        timeout=30,
    )
    env = os.environ.copy()
    if proc.returncode != 0:
        return env
    for line in proc.stdout.splitlines():
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key] = value
    return env


def shlex_quote(value):
    return "'" + value.replace("'", "'\"'\"'") + "'"


def find_openfoam_bashrc(binary_path):
    for parent in [binary_path.parent, *binary_path.parents]:
        candidate = parent / "etc" / "bashrc"
        if candidate.is_file():
            return candidate.resolve()
    return None


def resolve_executable(name, preferred=None, env=None):
    candidates = []
    if preferred:
        candidates.append(Path(preferred))
    found = shutil.which(name, path=(env or os.environ).get("PATH"))
    if found:
        candidates.append(Path(found))
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return None


def check_executable(checks, name, label, preferred=None, bashrc=None, critical=True):
    env = source_openfoam_env(bashrc)
    exe = resolve_executable(name, preferred=preferred, env=env)
    subject = exe if exe else (preferred or name)
    fix = (
        f"Install/build OpenFOAM, source its etc/bashrc, then check "
        f"{DIAGNOSTIC_TRIPLETS} for known recovery steps."
    )
    if not add_check(checks, "binary", subject, critical, bool(exe), fix):
        return None, env

    executable = os.access(exe, os.X_OK)
    add_check(
        checks,
        "binary",
        exe,
        critical,
        executable,
        f"Run chmod +x {exe}; if that is not sufficient, check {DIAGNOSTIC_TRIPLETS}.",
    )
    return exe, env


def check_starts(checks, exe, args, env, label, critical=True):
    if not exe:
        return
    subject = exe.resolve()
    try:
        proc = run_command([str(exe), *args], env=env, timeout=20)
        output = (proc.stdout + proc.stderr).lower()
        ok = proc.returncode == 0 and ("usage:" in output or "options:" in output)
    except (OSError, subprocess.TimeoutExpired) as exc:
        ok = False
        proc = None
        output = str(exc)
    fix = (
        f"{label} did not start cleanly. Source the OpenFOAM bashrc and check "
        f"{DIAGNOSTIC_TRIPLETS} before running model cases."
    )
    add_check(checks, "run", subject, critical, ok, fix)
    if not ok and proc is not None:
        tail = (proc.stderr or proc.stdout or "").strip()[-500:]
        if tail:
            print(f"        Output tail: {tail}")


def check_required_files(checks):
    for rel_path in REQUIRED_FILES:
        path = KI_DIR / rel_path
        add_check(
            checks,
            "data",
            path,
            True,
            path.is_file(),
            f"Restore {rel_path}; use {DIAGNOSTIC_TRIPLETS} for KI recovery hints.",
        )


def check_triplets_nonempty(checks):
    ok = DIAGNOSTIC_TRIPLETS.is_file() and DIAGNOSTIC_TRIPLETS.stat().st_size > 0
    add_check(
        checks,
        "data",
        DIAGNOSTIC_TRIPLETS,
        True,
        ok,
        f"Restore diagnostics/triplets.yaml; failures must point to {DIAGNOSTIC_TRIPLETS}.",
    )


def check_tool_imports(checks):
    python = HYDROCRAFT_PYTHON if HYDROCRAFT_PYTHON.is_file() else Path(sys.executable)
    add_check(
        checks,
        "data",
        python,
        False,
        python.is_file(),
        "Restore KISSPATH_PYTHON_ENV/bin/python or run with a valid Python interpreter.",
    )
    for module in REQUIRED_TOOL_MODULES:
        code = (
            "import importlib, sys; "
            f"sys.path.insert(0, {str(KI_DIR)!r}); "
            f"importlib.import_module({module!r})"
        )
        try:
            proc = run_command([str(python), "-c", code], timeout=20)
            ok = proc.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            ok = False
        add_check(
            checks,
            "import",
            f"{python}:{module}",
            True,
            ok,
            f"Fix import errors for {module}; check {DIAGNOSTIC_TRIPLETS} before changing model workflow.",
        )


def check_manifest_binary_agrees(checks, foam_run):
    if not foam_run or not MANIFEST.is_file():
        return
    manifest_text = MANIFEST.read_text(encoding="utf-8", errors="replace")
    realpath = str(foam_run.resolve())
    ok = realpath in manifest_text
    add_check(
        checks,
        "data",
        MANIFEST,
        True,
        ok,
        f"Update knowledge_infrastructure.yaml binary.path to the verified realpath {realpath}; see {DIAGNOSTIC_TRIPLETS}.",
    )


def main():
    checks = []
    print(f"{' PREFLIGHT: OpenFOAM ':=^60}")
    print(f"KI directory: {KI_DIR}")

    preferred_foam = Path(OPENFOAM_BINARY_FROM_MANIFEST)
    bashrc = find_openfoam_bashrc(preferred_foam)
    add_check(
        checks,
        "data",
        bashrc if bashrc else preferred_foam,
        True,
        bool(bashrc and bashrc.is_file()),
        f"Find the OpenFOAM etc/bashrc matching foamRun and check {DIAGNOSTIC_TRIPLETS}.",
    )

    foam_run, foam_env = check_executable(
        checks,
        "foamRun",
        "OpenFOAM solver driver",
        preferred=preferred_foam,
        bashrc=bashrc,
        critical=True,
    )
    check_starts(checks, foam_run, ["-help"], foam_env, "foamRun", critical=True)

    block_mesh_preferred = (
        preferred_foam.parent / "blockMesh" if preferred_foam.parent else None
    )
    block_mesh, block_env = check_executable(
        checks,
        "blockMesh",
        "OpenFOAM mesh generator",
        preferred=block_mesh_preferred,
        bashrc=bashrc,
        critical=True,
    )
    check_starts(checks, block_mesh, ["-help"], block_env, "blockMesh", critical=True)

    check_required_files(checks)
    check_triplets_nonempty(checks)
    check_tool_imports(checks)
    check_manifest_binary_agrees(checks, foam_run)

    passed = sum(1 for c in checks if c["status"] == "pass")
    failed = len(checks) - passed
    print(f"\nResults: {passed} passed, {failed} failed")
    if failed:
        print(f"Recovery: inspect {DIAGNOSTIC_TRIPLETS} for matching fixes.")
    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
