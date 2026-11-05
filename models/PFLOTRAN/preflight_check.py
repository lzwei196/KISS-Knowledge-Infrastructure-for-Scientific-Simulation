#!/usr/bin/env python3
"""Preflight check for the PFLOTRAN Knowledge Infrastructure."""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import re
import signal
import subprocess
import tempfile
import sys
from pathlib import Path


MODEL_ID = "PFLOTRAN"
KI_DIR = Path(__file__).resolve().parent
HYDROCRAFT_PYTHON = Path("KISSPATH_PYTHON_ENV/bin/python")
SERVER_DEFAULT_PFLOTRAN_BIN = (
    "KISSPATH_KI_ROOT/PFLOTRAN/source/repo/src/pflotran/pflotran"
)
# Same choice as tools/run_pflotran.py: $PFLOTRAN_BIN if set (non-empty), else the server build.
PFLOTRAN_BIN = Path(os.path.abspath(os.environ.get("PFLOTRAN_BIN") or SERVER_DEFAULT_PFLOTRAN_BIN))
RUN_TOOL = KI_DIR / "tools" / "run_pflotran.py"
# Name of an input deck that never exists: the startup probes stop at "file not found"
# (PFLOTRAN exit 87 = EXIT_USER_ERROR) after PETSc/MPI start-up, so no simulation runs.
PROBE_INPUT = "preflight_probe_missing_input.in"
AUTO_DISSECT_DIR = Path("KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect")
TRIPLETS = KI_DIR / "diagnostics" / "triplets.yaml"


checks: list[dict[str, object]] = []


def add_check(kind: str, subject: str, critical: bool, status: str, fix: str = "") -> None:
    check = {
        "kind": kind,
        "subject": subject,
        "critical": critical,
        "status": status,
        "fix": fix,
    }
    checks.append(check)
    marker = "OK" if status == "pass" else ("FAIL" if critical else "WARN")
    print(f"  {marker:<5} {kind}: {subject}")
    if status != "pass" and fix:
        print(f"        Fix: {fix}")


def emit_report(model_id: str, report_checks: list[dict[str, object]]) -> None:
    print("PREFLIGHT_REPORT=" + json.dumps({"model_id": model_id, "checks": report_checks}))
    failed_critical = any(
        c["status"] != "pass" and bool(c.get("critical")) for c in report_checks
    )
    sys.exit(1 if failed_critical else 0)


def check_file(path: Path, label: str, *, critical: bool, executable: bool = False) -> None:
    subject = str(path.resolve(strict=False))
    if not path.is_file():
        add_check(
            "data",
            subject,
            critical,
            "fail",
            f"Restore {label}; consult {TRIPLETS} for recovery.",
        )
        return
    if executable and not os.access(path, os.X_OK):
        add_check(
            "binary",
            subject,
            critical,
            "fail",
            f"Run chmod +x {path}; consult {TRIPLETS} if execution still fails.",
        )
        return
    add_check("binary" if executable else "data", subject, critical, "pass")


def check_dir(path: Path, label: str, *, critical: bool) -> None:
    subject = str(path.resolve(strict=False))
    if path.is_dir():
        add_check("data", subject, critical, "pass")
    else:
        add_check(
            "data",
            subject,
            critical,
            "fail",
            f"Restore {label}; consult {TRIPLETS} for recovery.",
        )


def check_python_interpreter() -> None:
    subject = str(HYDROCRAFT_PYTHON)
    if HYDROCRAFT_PYTHON.is_file() and os.access(HYDROCRAFT_PYTHON, os.X_OK):
        add_check("import", subject, True, "pass")
    else:
        add_check(
            "import",
            subject,
            True,
            "fail",
            f"Restore the HydroCraft Python environment at {HYDROCRAFT_PYTHON}; consult {TRIPLETS}.",
        )


def run_python_probe(label: str, code: str, *, critical: bool = True) -> None:
    subject = f"{HYDROCRAFT_PYTHON}:{label}"
    if not HYDROCRAFT_PYTHON.is_file():
        add_check(
            "import",
            subject,
            critical,
            "fail",
            f"Cannot run import probe without {HYDROCRAFT_PYTHON}; consult {TRIPLETS}.",
        )
        return

    env = os.environ.copy()
    pythonpath = [str(KI_DIR), str(AUTO_DISSECT_DIR)]
    if env.get("PYTHONPATH"):
        pythonpath.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(pythonpath)

    try:
        result = subprocess.run(
            [str(HYDROCRAFT_PYTHON), "-c", code],
            cwd=str(KI_DIR),
            env=env,
            text=True,
            capture_output=True,
            timeout=20,
        )
    except subprocess.TimeoutExpired:
        add_check(
            "import",
            subject,
            critical,
            "fail",
            f"Import probe timed out; inspect the tool and consult {TRIPLETS}.",
        )
        return

    if result.returncode == 0:
        add_check("import", subject, critical, "pass")
    else:
        detail = (result.stderr or result.stdout).strip().splitlines()
        reason = detail[-1] if detail else f"exit code {result.returncode}"
        add_check(
            "import",
            subject,
            critical,
            "fail",
            f"{reason}. Install missing packages in {HYDROCRAFT_PYTHON}'s environment; consult {TRIPLETS}.",
        )


def check_imports() -> None:
    run_python_probe(
        "core packages",
        "import numpy, h5py, netCDF4, pandas, geopandas, shapely; "
        "from ki_tools_common.units import CMFD_PRECIP_KGM2S_TO_MMDAY",
    )
    for rel_path in (
        "tools/run_pflotran.py",
        "tools/convert_forcing_to_pflotran.py",
        "tools/convert_soil_to_pflotran.py",
        "tools/parse_pflotran_output.py",
    ):
        code = (
            "import importlib.util, pathlib; "
            f"path = pathlib.Path({str(KI_DIR / rel_path)!r}); "
            "spec = importlib.util.spec_from_file_location(path.stem, path); "
            "mod = importlib.util.module_from_spec(spec); "
            "spec.loader.exec_module(mod)"
        )
        run_python_probe(rel_path, code)


def run_startup_probe(cmd: list[str], timeout: int) -> tuple[int | None, str]:
    """Run a PFLOTRAN start-up probe in an empty temp dir; kill its process group on timeout.

    The probe asks for a missing input deck plus PETSc -log_view: PETSc and MPI start,
    PFLOTRAN stops with 'File ... not found' (exit 87), and PETSc's summary says how
    many processes formed the communicator. Returns (exit code or None on timeout, output);
    exit code -1 if the program could not be started (OSError).
    """
    with tempfile.TemporaryDirectory(prefix="pflotran_preflight_") as tmp:
        try:
            proc = subprocess.Popen(
                cmd,
                cwd=tmp,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except OSError as exc:
            return -1, f"could not start {cmd[0]}: {exc}"
        try:
            out, _ = proc.communicate(timeout=timeout)
            return proc.returncode, out or ""
        except subprocess.TimeoutExpired:
            if proc.pid > 1:
                with contextlib.suppress(ProcessLookupError, PermissionError):
                    os.killpg(proc.pid, signal.SIGKILL)
            out, _ = proc.communicate()
            return None, out or ""


LOAD_ERROR_MARKERS = (
    "symbol lookup error",
    "undefined symbol",
    "error while loading shared libraries",
)


def judge_startup_probe(rc: int | None, output: str, nproc: int) -> str:
    """Return '' if the probe shows a clean start with one nproc-process communicator, else why not."""
    if rc is None:
        return "probe timed out"
    for marker in LOAD_ERROR_MARKERS:
        if marker in output:
            line = next(l for l in output.splitlines() if marker in l)
            return f"library error: {line.strip()}"
    if rc != 87:
        return f"exit code {rc}, expected 87 (PFLOTRAN EXIT_USER_ERROR for the missing probe input)"
    if f'File: "{PROBE_INPUT}" not found' not in output:
        return "PFLOTRAN did not reach its input-file check (no 'not found' message for the probe input)"
    sizes = re.findall(r" with (\d+) process(?:es)?, by ", output)
    if sizes != [str(nproc)]:
        return (
            f"PETSc -log_view did not report exactly one {nproc}-process communicator "
            f"(reported sizes: {sizes or 'none'})"
        )
    return ""


def last_lines(output: str, n: int = 3) -> str:
    lines = [l.strip() for l in output.strip().splitlines() if l.strip()]
    return " | ".join(lines[-n:]) if lines else "no output"


def check_pflotran_starts() -> None:
    subject = str(PFLOTRAN_BIN.resolve(strict=False))
    if not (PFLOTRAN_BIN.is_file() and os.access(PFLOTRAN_BIN, os.X_OK)):
        add_check(
            "run",
            subject,
            True,
            "fail",
            f"Fix the PFLOTRAN executable at {PFLOTRAN_BIN} (or point $PFLOTRAN_BIN at a working build); consult {TRIPLETS}.",
        )
        return

    rc, output = run_startup_probe(
        [str(PFLOTRAN_BIN), "-pflotranin", PROBE_INPUT, "-log_view"], timeout=60
    )
    problem = judge_startup_probe(rc, output, 1)
    if not problem:
        add_check("run", subject, True, "pass")
    else:
        add_check(
            "run",
            subject,
            True,
            "fail",
            f"PFLOTRAN 1-rank start-up probe failed: {problem}; last output: {last_lines(output)}. "
            f"Check the PETSc/MPI libraries the binary links (ldd {PFLOTRAN_BIN}); consult {TRIPLETS}.",
        )


def load_run_tool_mpirun():
    """Load the run tool's own launcher lookup so the preflight checks what the tool will use.

    Returns (launcher or None, server default, messages printed by the lookup, load error or '').
    """
    try:
        spec = importlib.util.spec_from_file_location("pflotran_run_tool_for_preflight", RUN_TOOL)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            launcher = mod.find_mpirun(None)
        return launcher, str(mod.SERVER_DEFAULT_MPIRUN), buf.getvalue().strip(), ""
    except Exception as exc:  # noqa: BLE001 - any load problem becomes a critical check
        return None, "", "", f"{type(exc).__name__}: {exc}"


def libmpi_of_binary() -> str:
    """Path of libmpi.so.* that ldd resolves for the PFLOTRAN binary (diagnostic only)."""
    try:
        result = subprocess.run(
            ["ldd", str(PFLOTRAN_BIN)], text=True, capture_output=True, timeout=30
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown (ldd failed)"
    for line in result.stdout.splitlines():
        m = re.match(r"\s*libmpi\.so\S*\s+=>\s+(\S+)", line)
        if m:
            return os.path.realpath(m.group(1))
    return "unknown (no libmpi in ldd output)"


def check_mpi_launcher() -> None:
    """Check the MPI launcher tools/run_pflotran.py uses for --nproc > 1.

    Same lookup as the tool ($PFLOTRAN_MPIRUN, else the server default; no PATH search),
    then a 2-rank start-up probe that must report ONE 2-process communicator.
    """
    launcher, default, lookup_msg, load_error = load_run_tool_mpirun()
    if load_error:
        add_check(
            "binary",
            f"MPI launcher lookup in {RUN_TOOL}",
            True,
            "fail",
            f"Could not load find_mpirun() from {RUN_TOOL}: {load_error}; consult {TRIPLETS}.",
        )
        return

    env_choice = os.environ.get("PFLOTRAN_MPIRUN")
    if launcher is None:
        if env_choice:
            add_check(
                "binary",
                f"$PFLOTRAN_MPIRUN={env_choice}",
                True,
                "fail",
                f"{lookup_msg or 'not an executable file'}. Unset $PFLOTRAN_MPIRUN to use the server default "
                f"{default}, or point it at the mpirun of the MPI PFLOTRAN links; consult {TRIPLETS}.",
            )
        elif os.path.exists(default):
            add_check(
                "binary",
                default,
                True,
                "fail",
                f"Server default MPI launcher {default} exists but is not an executable file; "
                f"fix its permissions or set $PFLOTRAN_MPIRUN; consult {TRIPLETS}.",
            )
        else:
            add_check(
                "binary",
                default,
                False,
                "fail",
                f"No MPI launcher: serial runs only (nproc=1); MPI runs (nproc>1) unavailable. Restore the "
                f"miniconda OpenMPI at {default} or set $PFLOTRAN_MPIRUN to the mpirun of the MPI PFLOTRAN "
                f"links; consult {TRIPLETS}.",
            )
        return

    subject = f"{launcher} (MPI launcher of tools/run_pflotran.py)"
    if not (PFLOTRAN_BIN.is_file() and os.access(PFLOTRAN_BIN, os.X_OK)):
        add_check(
            "run",
            subject,
            True,
            "fail",
            f"Cannot test the launcher without a working PFLOTRAN binary at {PFLOTRAN_BIN}; consult {TRIPLETS}.",
        )
        return

    rc, output = run_startup_probe(
        [launcher, "-n", "2", str(PFLOTRAN_BIN), "-pflotranin", PROBE_INPUT, "-log_view"],
        timeout=60,
    )
    problem = judge_startup_probe(rc, output, 2)
    if not problem:
        add_check("run", subject, True, "pass")
    else:
        add_check(
            "run",
            subject,
            True,
            "fail",
            f"2-rank start-up probe with {launcher} failed: {problem}; last output: {last_lines(output)}. "
            f"PFLOTRAN links {libmpi_of_binary()}; the launcher must come from that same MPI "
            f"(server default {default}). Unset or fix $PFLOTRAN_MPIRUN; consult {TRIPLETS}.",
        )


def main() -> None:
    print(f"{' PREFLIGHT: PFLOTRAN ':=^60}")
    print()

    check_dir(KI_DIR / "tools", "KI tools directory", critical=True)
    for rel_path in (
        "tools/run_pflotran.py",
        "tools/convert_forcing_to_pflotran.py",
        "tools/convert_soil_to_pflotran.py",
        "tools/parse_pflotran_output.py",
        "knowledge_infrastructure.yaml",
        "dag.yaml",
        "SKILL.md",
    ):
        check_file(KI_DIR / rel_path, rel_path, critical=True)

    check_file(TRIPLETS, "diagnostic triplets", critical=True)
    check_file(PFLOTRAN_BIN, "PFLOTRAN binary", critical=True, executable=True)
    check_pflotran_starts()
    check_python_interpreter()
    check_imports()
    check_mpi_launcher()

    print()
    passed = sum(1 for c in checks if c["status"] == "pass")
    failed = len(checks) - passed
    print(f"  Results: {passed} passed, {failed} failed")
    failed_critical = [c for c in checks if c["status"] != "pass" and c.get("critical")]
    if failed_critical:
        print(f"  STATUS: PREFLIGHT FAILED - consult {TRIPLETS} for recovery.")
    else:
        print("  STATUS: PREFLIGHT PASSED - safe to proceed with model execution.")
        if any(c["status"] != "pass" and "No MPI launcher" in str(c.get("fix")) for c in checks):
            print("  NOTE: MPI unavailable - serial runs (nproc=1) only.")

    emit_report(MODEL_ID, checks)


if __name__ == "__main__":
    main()
