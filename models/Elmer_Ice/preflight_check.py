#!/usr/bin/env python3
"""Preflight check for the Elmer/Ice KI.

This script verifies the executable, Python tool dependencies, KI support files,
and bundled example mesh before model execution.
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys


MODEL_ID = "Elmer-Ice"
KI_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_ROOT = os.path.dirname(KI_DIR)
DIAGNOSTICS = os.path.join(KI_DIR, "diagnostics", "triplets.yaml")
PYTHON_ENV_SITE = "KISSPATH_PYTHON_ENV/lib/python3.12/site-packages"

# Elmer/Ice engine = an ElmerSolver build that ships the Elmer/Ice libraries
# (ElmerIceSolvers, ElmerIceUSF). Lookup, same as the official test cases:
# $ELMERSOLVER_BIN / $ELMERGRID_BIN -> `which` -> the server's Elmer/Ice build.
# An explicit env value is used as-is (no silent fallback if it is broken).
ICE_INSTALL_BIN = (
    "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/"
    "Elmer_Ice/install_ice/bin"
)


def select_binary(env_name, name):
    # Absolute, so the file checks, the --version probe (cwd=KI_DIR) and the printed
    # --solver_binary value all mean the same file.
    explicit = os.environ.get(env_name, "").strip()
    if explicit:
        return os.path.abspath(shutil.which(explicit) or explicit)
    return os.path.abspath(shutil.which(name) or os.path.join(ICE_INSTALL_BIN, name))


SOLVER = select_binary("ELMERSOLVER_BIN", "ElmerSolver")
ELMERGRID = select_binary("ELMERGRID_BIN", "ElmerGrid")
# The selected build's install prefix: <prefix>/bin/ElmerSolver,
# <prefix>/lib/elmersolver (core libs), <prefix>/share/elmersolver/lib (solver modules).
SOLVER_PREFIX = os.path.dirname(os.path.dirname(os.path.realpath(SOLVER)))
SOLVER_LIBDIR = os.path.join(SOLVER_PREFIX, "lib", "elmersolver")
MODULE_DIR = os.path.join(SOLVER_PREFIX, "share", "elmersolver", "lib")
ICE_LIBS = ["ElmerIceUtils", "ElmerIceUSF", "ElmerIceSolvers"]
ICE_LIBS_REQUIRED = ["ElmerIceUSF", "ElmerIceSolvers"]

# Plain Elmer builds WITHOUT the Elmer/Ice libraries. Kept as non-critical
# information only: they start, but cannot run Elmer/Ice solvers or USFs.
LOCAL_PLAIN_SOLVER = os.path.join(MODEL_ROOT, "bin", "bin", "ElmerSolver")
LEGACY_SOLVER = (
    "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/"
    "Elmer_Ice/install/bin/ElmerSolver"
)


def add_check(checks, kind, subject, critical, status, fix=""):
    checks.append(
        {
            "kind": kind,
            "subject": subject,
            "critical": bool(critical),
            "status": status,
            "fix": fix,
        }
    )
    label = "OK" if status == "pass" else "FAIL"
    print(f"  {label:<5} {kind}: {subject}")
    if status != "pass" and fix:
        print(f"        Fix: {fix}")


def recovery_hint(action):
    return f"{action}; then check {DIAGNOSTICS} for matching recovery triplets."


def real_subject(path):
    return os.path.realpath(path) if os.path.exists(path) else path


def check_file(checks, path, label, critical=True, executable=False):
    subject = real_subject(path)
    if not os.path.isfile(path):
        add_check(
            checks,
            "data",
            subject,
            critical,
            "fail",
            recovery_hint(f"Restore missing {label}: {path}"),
        )
        return False
    if executable and not os.access(path, os.X_OK):
        add_check(
            checks,
            "binary",
            subject,
            critical,
            "fail",
            recovery_hint(f"Make {label} executable: chmod +x {path}"),
        )
        return False
    add_check(checks, "binary" if executable else "data", subject, critical, "pass")
    return True


def check_dir(checks, path, label, critical=True, expected_files=None):
    subject = real_subject(path)
    if not os.path.isdir(path):
        add_check(
            checks,
            "data",
            subject,
            critical,
            "fail",
            recovery_hint(f"Restore missing {label}: {path}"),
        )
        return False

    missing = [
        rel for rel in (expected_files or [])
        if not os.path.isfile(os.path.join(path, rel))
    ]
    if missing:
        add_check(
            checks,
            "data",
            subject,
            critical,
            "fail",
            recovery_hint(f"Restore {label}; missing files: {', '.join(missing)}"),
        )
        return False

    suffix = f" ({len(os.listdir(path))} items)"
    add_check(checks, "data", subject + suffix, critical, "pass")
    return True


def check_import(checks, module, critical=True):
    if PYTHON_ENV_SITE not in sys.path and os.path.isdir(PYTHON_ENV_SITE):
        sys.path.insert(0, PYTHON_ENV_SITE)

    if importlib.util.find_spec(module) is None:
        add_check(
            checks,
            "import",
            f"{sys.executable}: import {module}",
            critical,
            "fail",
            recovery_hint(
                f"Install {module.split('.')[0]} for this interpreter "
                f"({sys.executable}) or HydroCraft python_env"
            ),
        )
        return False

    add_check(checks, "import", f"{sys.executable}: import {module}", critical, "pass")
    return True


def solver_env():
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = (
        SOLVER_LIBDIR + os.pathsep + env["LD_LIBRARY_PATH"]
        if env.get("LD_LIBRARY_PATH")
        else SOLVER_LIBDIR
    )
    return env


def check_elmerice_libs(checks):
    """Critical: the selected build has the Elmer/Ice libraries and they load.

    Loads each library in a fresh Python with RTLD_NOW|RTLD_GLOBAL, so every
    symbol must resolve against the build's own core libraries. No simulation.
    """
    subject = f"Elmer/Ice libraries in {MODULE_DIR}"
    hint = (
        f"The selected ElmerSolver ({SOLVER}) is not an Elmer/Ice build. Use the "
        f"Elmer/Ice build ({ICE_INSTALL_BIN}/ElmerSolver) or set ELMERSOLVER_BIN to "
        "an ElmerSolver whose install has ElmerIceSolvers.so and ElmerIceUSF.so"
    )
    missing = [
        n for n in ICE_LIBS_REQUIRED
        if not os.path.isfile(os.path.join(MODULE_DIR, n + ".so"))
    ]
    if missing:
        add_check(
            checks, "library", subject, True, "fail",
            recovery_hint(f"Missing {', '.join(n + '.so' for n in missing)}. {hint}"),
        )
        return False

    paths = [
        os.path.join(MODULE_DIR, n + ".so") for n in ICE_LIBS
        if os.path.isfile(os.path.join(MODULE_DIR, n + ".so"))
    ]
    code = (
        "import ctypes, os, sys\n"
        "for p in sys.argv[1:]:\n"
        "    ctypes.CDLL(p, mode=os.RTLD_GLOBAL | os.RTLD_NOW)\n"
        "print('loaded', len(sys.argv) - 1)\n"
    )
    try:
        result = subprocess.run(
            [sys.executable, "-c", code] + paths,
            cwd=KI_DIR,
            env=solver_env(),
            text=True,
            capture_output=True,
            timeout=60,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        add_check(
            checks, "library", subject, True, "fail",
            recovery_hint(f"Elmer/Ice library load probe could not run: {exc}"),
        )
        return False
    if result.returncode != 0:
        lines = (result.stderr or result.stdout or "").strip().splitlines()
        detail = lines[-1] if lines else f"exit code {result.returncode}"
        add_check(
            checks, "library", subject, True, "fail",
            recovery_hint(
                f"Elmer/Ice libraries exist but do not load "
                f"(LD_LIBRARY_PATH={SOLVER_LIBDIR}): {detail}"
            ),
        )
        return False
    add_check(
        checks, "library",
        subject + " (" + ", ".join(os.path.basename(p) for p in paths) + " load)",
        True, "pass",
    )
    return True


def check_binary_starts(checks, binary):
    subject = real_subject(binary)
    if not os.path.isfile(binary) or not os.access(binary, os.X_OK):
        add_check(
            checks,
            "run",
            subject,
            True,
            "fail",
            recovery_hint(f"Restore executable before startup test: {binary}"),
        )
        return False

    env = solver_env()

    try:
        result = subprocess.run(
            [binary, "--version"],
            cwd=KI_DIR,
            env=env,
            text=True,
            capture_output=True,
            timeout=10,
        )
    except subprocess.TimeoutExpired:
        add_check(
            checks,
            "run",
            subject + " --version",
            True,
            "fail",
            recovery_hint("ElmerSolver startup timed out"),
        )
        return False
    except OSError as exc:
        add_check(
            checks,
            "run",
            subject + " --version",
            True,
            "fail",
            recovery_hint(f"ElmerSolver could not start: {exc}"),
        )
        return False

    combined = (result.stdout or "") + (result.stderr or "")
    # --version starts the solver, prints the banner and exits 0 without a case.
    if result.returncode == 0 and "ElmerSolver finite element" in combined:
        add_check(checks, "run", subject + " --version", True, "pass")
        return True

    add_check(
        checks,
        "run",
        subject + " --version",
        True,
        "fail",
        recovery_hint(
            "ElmerSolver --version did not exit 0 with the startup banner "
            f"(exit {result.returncode}): "
            f"{(combined.strip().splitlines() or ['no output'])[-1]}"
        ),
    )
    return False


def check_elmergrid_starts(checks, binary):
    """Critical: ElmerGrid runs with no arguments (prints its usage banner, no files)."""
    subject = real_subject(binary) + " (no-argument start)"
    if not os.path.isfile(binary) or not os.access(binary, os.X_OK):
        add_check(
            checks, "run", subject, True, "fail",
            recovery_hint(f"Restore executable ElmerGrid before startup test: {binary}"),
        )
        return False
    try:
        result = subprocess.run(
            [binary],
            cwd=KI_DIR,
            env=solver_env(),
            stdin=subprocess.DEVNULL,
            text=True,
            capture_output=True,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        add_check(
            checks, "run", subject, True, "fail",
            recovery_hint(f"ElmerGrid could not start: {exc}"),
        )
        return False
    combined = (result.stdout or "") + (result.stderr or "")
    if result.returncode == 0 and "ElmerGrid mesh conversion and manipulation utility" in combined:
        add_check(checks, "run", subject, True, "pass")
        return True
    lines = combined.strip().splitlines()
    add_check(
        checks, "run", subject, True, "fail",
        recovery_hint(
            "ElmerGrid did not print its startup banner "
            f"(exit {result.returncode}): {lines[-1] if lines else 'no output'}"
        ),
    )
    return False


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}))
    has_failed_critical = any(
        c["status"] != "pass" and c.get("critical") for c in checks
    )
    sys.exit(1 if has_failed_critical else 0)


def main():
    checks = []

    print(f"{' PREFLIGHT: Elmer/Ice ':=^60}")
    print()

    check_dir(
        checks,
        os.path.join(KI_DIR, "tools"),
        "KI tools directory",
        critical=True,
        expected_files=[
            "convert_geometry.py",
            "convert_forcing.py",
            "generate_sif.py",
            "run_elmerice.py",
            "parse_vtu_output.py",
        ],
    )
    check_file(checks, os.path.join(KI_DIR, "SKILL.md"), "SKILL.md", critical=True)
    check_file(
        checks,
        os.path.join(KI_DIR, "knowledge_infrastructure.yaml"),
        "knowledge_infrastructure.yaml",
        critical=True,
    )
    check_file(checks, os.path.join(KI_DIR, "dag.yaml"), "dag.yaml", critical=True)
    check_file(checks, DIAGNOSTICS, "diagnostic triplets", critical=True)

    check_file(checks, SOLVER, "Elmer/Ice ElmerSolver", critical=True, executable=True)
    check_binary_starts(checks, SOLVER)
    check_elmerice_libs(checks)
    check_file(checks, ELMERGRID, "ElmerGrid mesh generator", critical=True, executable=True)
    check_elmergrid_starts(checks, ELMERGRID)
    check_file(
        checks,
        LOCAL_PLAIN_SOLVER,
        "KI-local plain Elmer ElmerSolver (no Elmer/Ice libraries; info only)",
        critical=False,
        executable=True,
    )
    check_file(
        checks,
        LEGACY_SOLVER,
        "models-DB plain Elmer ElmerSolver (no Elmer/Ice libraries; info only)",
        critical=False,
        executable=True,
    )

    check_import(checks, "numpy", critical=True)
    check_import(checks, "scipy", critical=False)
    check_import(checks, "netCDF4", critical=False)

    check_dir(
        checks,
        os.path.join(MODEL_ROOT, "example_Density", "mesh"),
        "bundled example mesh",
        critical=False,
        expected_files=[
            "mesh.header",
            "mesh.nodes",
            "mesh.elements",
            "mesh.boundary",
        ],
    )
    check_file(
        checks,
        os.path.join(MODEL_ROOT, "example_Density", "density.sif"),
        "bundled density SIF",
        critical=False,
    )

    passed = sum(1 for c in checks if c["status"] == "pass")
    failed = len(checks) - passed
    print(f"\n  Results: {passed} passed, {failed} failed")
    if any(c["status"] != "pass" and c.get("critical") for c in checks):
        print(f"  STATUS: PREFLIGHT FAILED; check {DIAGNOSTICS} for recovery.")
    else:
        print("  STATUS: PREFLIGHT PASSED; ready for model execution.")
    print(
        f"  Checked engine: {SOLVER} (real file {os.path.realpath(SOLVER)}, "
        f"prefix {SOLVER_PREFIX})."
    )
    print(
        "  Note: run tools/run_elmerice.py with --solver_binary set to this "
        "ElmerSolver; the plain Elmer builds cannot run Elmer/Ice solvers."
    )

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
