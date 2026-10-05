#!/usr/bin/env python3
"""Preflight check for the ROMS knowledge infrastructure."""

import json
import os
import py_compile
import shutil
import subprocess
import sys
from pathlib import Path


MODEL_ID = "ROMS"
KI_DIR = Path(__file__).resolve().parent
HYDROCRAFT_PYTHON = Path("KISSPATH_PYTHON_ENV/bin/python")
# A ROMS binary is compiled for ONE application (its header, e.g. upwelling.h, is built in).
# So there is no single "ROMS engine": the preflight lists every known build, names the
# application each was compiled for, and needs at least one serial build that starts.
# $ROMS_BIN (same name as the official test cases) pins one binary; then only it is checked.
ROMS_REPO = Path("KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect/_work/ROMS/source/repo")
ROMS_BIN_ENV = os.environ.get("ROMS_BIN", "").strip()
SERIAL_BUILDS = [ROMS_REPO / "build" / "romsS", ROMS_REPO / "build_upwelling" / "romsS"]
MPI_BUILDS = [ROMS_REPO / "build_mpi" / "romsM"]
APP_NOTE = (
    "A ROMS binary runs only the application compiled into it; this check proves startup, "
    "not case compatibility. Pass the build whose app matches the case to tools/run_roms.py "
    "--binary (the tool does not read ROMS_BIN; ROMS_BIN only picks the binary for this "
    "preflight and the reference test cases), or build one with cmake -DROMS_APP=<APP>."
)
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"
RECOVERY = f"Check {TRIPLETS} for recovery steps."


def emit_report(model_id, checks):
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": checks}))
    failed_critical = any(c["status"] != "pass" and c.get("critical") for c in checks)
    sys.exit(1 if failed_critical else 0)


def add_check(checks, kind, subject, critical, passed, fix=""):
    checks.append(
        {
            "kind": kind,
            "subject": str(subject),
            "critical": bool(critical),
            "status": "pass" if passed else "fail",
            "fix": "" if passed else fix,
        }
    )


def check_file(checks, path, label, critical=True, executable=False):
    path = Path(path)
    subject = path.resolve(strict=False)
    if not path.is_file():
        add_check(
            checks,
            "binary" if executable else "data",
            subject,
            critical,
            False,
            f"{label} not found at {subject}. {RECOVERY}",
        )
        return False
    if executable and not os.access(path, os.X_OK):
        add_check(
            checks,
            "binary",
            subject,
            critical,
            False,
            f"{label} exists but is not executable: chmod +x {subject}. {RECOVERY}",
        )
        return False
    add_check(checks, "binary" if executable else "data", subject, critical, True)
    return True


def check_dir(checks, path, label, critical=True, non_empty=False):
    path = Path(path)
    subject = path.resolve(strict=False)
    if not path.is_dir():
        add_check(
            checks,
            "data",
            subject,
            critical,
            False,
            f"{label} directory not found at {subject}. {RECOVERY}",
        )
        return False
    if non_empty and not any(path.iterdir()):
        add_check(
            checks,
            "data",
            subject,
            critical,
            False,
            f"{label} directory is empty at {subject}. Restore KI contents. {RECOVERY}",
        )
        return False
    add_check(checks, "data", subject, critical, True)
    return True


def check_import(checks, module, critical=True):
    subject = f"{HYDROCRAFT_PYTHON}:{module}"
    if not HYDROCRAFT_PYTHON.is_file() or not os.access(HYDROCRAFT_PYTHON, os.X_OK):
        add_check(
            checks,
            "import",
            subject,
            critical,
            False,
            f"HydroCraft Python interpreter is missing or not executable at {HYDROCRAFT_PYTHON}. {RECOVERY}",
        )
        return False

    result = subprocess.run(
        [str(HYDROCRAFT_PYTHON), "-c", f"import {module}"],
        cwd=str(KI_DIR),
        capture_output=True,
        text=True,
        timeout=15,
    )
    if result.returncode == 0:
        add_check(checks, "import", subject, critical, True)
        return True

    detail = (result.stderr or result.stdout).strip().splitlines()
    message = detail[-1] if detail else f"import {module} failed"
    add_check(
        checks,
        "import",
        subject,
        critical,
        False,
        f"{message}. Install/repair the package in {HYDROCRAFT_PYTHON}. {RECOVERY}",
    )
    return False


def check_python_syntax(checks, path, critical=True):
    path = Path(path)
    subject = path.resolve(strict=False)
    try:
        py_compile.compile(str(path), doraise=True)
    except Exception as exc:
        add_check(
            checks,
            "import",
            subject,
            critical,
            False,
            f"Python syntax/compile check failed for {subject}: {exc}. {RECOVERY}",
        )
        return False
    add_check(checks, "import", subject, critical, True)
    return True


def read_cmake_app(binary):
    cache = Path(os.path.realpath(binary)).parent / "CMakeCache.txt"
    found = {}
    try:
        if not cache.is_file():
            return ""
        text = cache.read_text(errors="replace")
    except OSError:
        return ""
    for line in text.splitlines():
        for key in ("ROMS_APP_HEADER", "ROMS_APP"):
            if line.startswith(key + ":"):
                found[key] = line.split("=", 1)[-1].strip()
    value = found.get("ROMS_APP_HEADER") or found.get("ROMS_APP")
    return f"{value} (from CMakeCache, not the binary)" if value else ""


def probe_binary(binary):
    """Start ROMS with empty stdin in its own folder; return (started, app, detail)."""
    binary = Path(binary).absolute()
    try:
        result = subprocess.run(
            [str(binary)],
            input=b"",
            cwd=str(binary.parent),
            capture_output=True,
            timeout=5,
        )
    except subprocess.TimeoutExpired:
        return False, "", "did not return from a no-input startup probe within 5s"
    except OSError as exc:
        return False, "", f"failed to start: {exc}"

    output = (result.stdout + result.stderr).decode("utf-8", errors="replace")
    loader_failed = "error while loading shared libraries" in output
    started = "ROMS" in output and not loader_failed
    app = ""
    for line in output.splitlines():
        if line.strip().startswith("Header file") and ":" in line:
            app = line.split(":", 1)[1].strip()
            break
    if not app:
        app = read_cmake_app(binary) or "unknown"
    tail = output.strip().splitlines()[-1:] or [f"exit code {result.returncode} with no ROMS banner"]
    return started, app, tail[0]


def check_binary_starts(checks, binary, critical=True):
    """Startup probe for one build; the check subject names the compiled application."""
    binary = Path(binary)
    subject = binary.resolve(strict=False)
    if not binary.is_file() or not os.access(binary, os.X_OK):
        add_check(
            checks,
            "run",
            subject,
            critical,
            False,
            f"Cannot launch missing or non-executable ROMS binary at {subject}. {RECOVERY}",
        )
        return False, ""

    started, app, detail = probe_binary(binary)
    if started:
        add_check(checks, "run", f"{subject} (app: {app})", critical, True)
        return True, app

    add_check(
        checks,
        "run",
        f"{subject} (app: {app})",
        critical,
        False,
        f"ROMS binary did not produce a recognizable startup banner: {detail}. {RECOVERY}",
    )
    return False, app


def check_roms_builds(checks):
    """Pinned $ROMS_BIN, or every known build; at least one serial build must start."""
    if ROMS_BIN_ENV:
        pinned = Path(ROMS_BIN_ENV)
        try:
            check_file(checks, pinned, "ROMS binary from ROMS_BIN", critical=True, executable=True)
            check_binary_starts(checks, pinned, critical=True)
        except (OSError, RuntimeError) as exc:
            add_check(checks, "run", pinned, True, False,
                      f"Cannot inspect ROMS binary from ROMS_BIN at {pinned}: {exc}. {RECOVERY}")
        return

    candidates = []
    on_path = shutil.which("romsS")
    if on_path:
        candidates.append(Path(on_path))
    for build in SERIAL_BUILDS:
        if os.path.realpath(build) not in [os.path.realpath(c) for c in candidates]:
            candidates.append(build)

    working = []
    for build in candidates:
        subject = os.path.realpath(build)
        try:
            if not build.is_file():
                add_check(
                    checks,
                    "binary",
                    subject,
                    False,
                    False,
                    f"Known ROMS build not found at {build} (optional; other builds may serve). {RECOVERY}",
                )
                continue
            started, app = check_binary_starts(checks, build, critical=False)
        except (OSError, RuntimeError) as exc:
            add_check(checks, "binary", subject, False, False,
                      f"Cannot inspect ROMS build at {build}: {exc} (optional). {RECOVERY}")
            continue
        if started:
            working.append(f"{subject} (app: {app})")

    # MPI builds need mpirun and an input file argument; listed for information only.
    for build in MPI_BUILDS:
        try:
            present = build.is_file()
            executable = present and os.access(build, os.X_OK)
        except OSError:
            continue
        if present:
            add_check(
                checks,
                "binary",
                f"{os.path.realpath(build)} (MPI build, app: {read_cmake_app(build) or 'unknown'}; "
                "needs mpirun; not startup-tested)",
                False,
                executable,
                f"MPI ROMS binary is not executable: chmod +x {build}. {RECOVERY}",
            )

    if working:
        add_check(
            checks,
            "run",
            "ROMS serial builds that start: " + "; ".join(working)
            + ". Case compatibility not tested.",
            True,
            True,
        )
    else:
        add_check(
            checks,
            "run",
            "at least one ROMS serial build (romsS) that starts",
            True,
            False,
            f"No ROMS serial build started (tried: {', '.join(str(c) for c in candidates)}). "
            f"{APP_NOTE} {RECOVERY}",
        )


def main():
    checks = []

    print(f"{' PREFLIGHT: ROMS ':=^60}")
    print("Checking ROMS binary, KI files, diagnostics, and Python dependencies.")

    # Original real checks retained: KI tools directory and ROMS executable.
    check_dir(checks, KI_DIR / "tools", "KI tools", critical=True, non_empty=True)
    check_roms_builds(checks)

    for rel in (
        "SKILL.md",
        "knowledge_infrastructure.yaml",
        "dag.yaml",
        "docs/format_spec.yaml",
        "diagnostics/triplets.yaml",
        "tools/build_roms_grid.py",
        "tools/convert_forcing.py",
        "tools/run_roms.py",
        "tools/parse_roms_output.py",
    ):
        check_file(checks, KI_DIR / rel, rel, critical=True)

    for module in ("numpy", "netCDF4", "scipy"):
        check_import(checks, module, critical=True)

    for tool in (
        "tools/build_roms_grid.py",
        "tools/convert_forcing.py",
        "tools/run_roms.py",
        "tools/parse_roms_output.py",
    ):
        check_python_syntax(checks, KI_DIR / tool, critical=True)

    failed = [c for c in checks if c["status"] != "pass"]
    blockers = [c for c in failed if c.get("critical")]
    warnings = [c for c in failed if not c.get("critical")]
    if blockers:
        print("Blockers found:")
        for check in blockers:
            print(f"  FAIL {check['kind']} {check['subject']}")
            print(f"       Fix: {check['fix']}")
    if warnings:
        print("Warnings (non-critical):")
        for check in warnings:
            print(f"  WARN {check['kind']} {check['subject']}")
            print(f"       Fix: {check['fix']}")
    if not failed:
        print("All preflight checks passed.")
    elif not blockers:
        print("All critical preflight checks passed.")

    for check in checks:
        if check["kind"] == "run" and "(app:" in check["subject"]:
            print(f"  {'OK  ' if check['status'] == 'pass' else 'FAIL'} {check['subject']}")
    print(f"Note: {APP_NOTE}")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
