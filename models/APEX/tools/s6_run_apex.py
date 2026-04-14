"""s6_run_apex.py — Invoke the apex1501 binary inside a workspace and collect outputs.

The binary always reads from and writes to the *current working directory*, so
we ``chdir`` into the workspace before invoking it. Because apex1501 returns
exit code 0 even on Fortran severe errors (Known Trap #10), we cannot trust
``returncode`` — instead we check that the run produced *some* primary output
file (``.OUT``/``.ACY``/``.SAD``/``.MSW``) and that ``EPICERR.DAT`` is clean.

RUN1501.SUM trap: this file is the **multi-run** summary and is legitimately
empty when APEXRUN.DAT defines a single run (apex1501 only populates it when
there are ≥2 runs to summarise). Treating an empty SUM as a failure is a
false positive — the per-run outputs ``001RUN.OUT`` and ``001RUN.ACY`` are
the real success signal. We therefore only require that the run produced
at least one ``*.OUT`` / ``*.ACY`` file, and that EPICERR is clean.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

BINARY_NAME = "apex1501"
SOURCE_BINARY = Path(
    "/home/server/knowledge-dissection-toolkit/auto_dissect_multi_agent/_work_v2/APEX/source/repo/Apex 1501 - Linux/apex1501"
)

# File extensions that indicate a per-run APEX output was written. The
# presence of any one of these (non-empty) is the authoritative success signal.
_RUN_OUTPUT_EXTS = (".OUT", ".ACY", ".SAD", ".MSW", ".SUS", ".MAN")


def validate_inputs(workspace: Path) -> None:
    if not workspace.is_dir():
        raise FileNotFoundError(f"Workspace does not exist: {workspace}")
    for f in ("APEXFILE.DAT", "APEXCONT.DAT", "APEXRUN.DAT", "SITE01.SIT", "SUBA01.SUB", "SOIL01.SOL"):
        if not (workspace / f).is_file():
            raise FileNotFoundError(f"Required input missing in workspace: {f}")


def _ensure_binary(ws: Path) -> Path:
    bin_path = ws / BINARY_NAME
    if not bin_path.is_file():
        if not SOURCE_BINARY.is_file():
            raise FileNotFoundError(f"apex1501 binary not found at {SOURCE_BINARY}")
        shutil.copy2(SOURCE_BINARY, bin_path)
    os.chmod(bin_path, 0o755)
    return bin_path


def _collect_run_outputs(ws: Path) -> list[str]:
    seen: set[str] = set()
    for ext in _RUN_OUTPUT_EXTS:
        for p in ws.glob(f"*{ext}"):
            if p.stat().st_size > 0:
                seen.add(p.name)
    return sorted(seen)


def run(workspace, *, timeout: int = 600) -> dict:
    ws = Path(workspace).expanduser().resolve()
    validate_inputs(ws)
    bin_path = _ensure_binary(ws)

    # Clear stale per-run outputs and the multi-run summary so a fresh-run
    # failure can't be masked by leftover files from a previous invocation.
    for stale in ("RUN1501.SUM", "EPICERR.DAT"):
        p = ws / stale
        if p.exists():
            p.unlink()
    for ext in _RUN_OUTPUT_EXTS:
        for p in ws.glob(f"*{ext}"):
            try:
                p.unlink()
            except OSError:
                pass

    proc = subprocess.run(
        [f"./{BINARY_NAME}"],
        cwd=str(ws),
        capture_output=True,
        text=True,
        timeout=timeout,
    )

    err_path = ws / "EPICERR.DAT"
    err_text = err_path.read_text() if err_path.exists() else ""

    run_outputs = _collect_run_outputs(ws)
    if not run_outputs:
        raise RuntimeError(
            f"apex1501 produced no per-run output files in {ws} "
            f"(rc={proc.returncode}).\nstderr:\n{proc.stderr}\n"
            f"EPICERR.DAT:\n{err_text}"
        )

    if "severe" in (proc.stderr or "").lower() or "ERROR" in err_text.upper():
        raise RuntimeError(
            f"apex1501 reported errors (rc={proc.returncode}).\n"
            f"stderr:\n{proc.stderr}\nEPICERR.DAT:\n{err_text}"
        )

    sum_path = ws / "RUN1501.SUM"
    # RUN1501.SUM is populated only for multi-run setups; empty is legal.
    sum_bytes = sum_path.stat().st_size if sum_path.exists() else 0

    out_files = sorted(p.name for p in ws.glob("*.OUT"))
    validate_outputs(ws, run_outputs)
    return {
        "workspace": str(ws),
        "binary": str(bin_path),
        "returncode": proc.returncode,
        "out_files": out_files,
        "run_outputs": run_outputs,
        "sum_path": str(sum_path),
        "sum_bytes": sum_bytes,
    }


def validate_outputs(ws: Path, run_outputs: list[str]) -> None:
    if not run_outputs:
        raise RuntimeError(f"apex1501 wrote no per-run output files in {ws}")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--workspace", required=True)
    p.add_argument("--timeout", type=int, default=600)
    args = p.parse_args()
    info = run(args.workspace, timeout=args.timeout)
    print(f"[OK] APEX run completed; outputs: {info['run_outputs']}")
