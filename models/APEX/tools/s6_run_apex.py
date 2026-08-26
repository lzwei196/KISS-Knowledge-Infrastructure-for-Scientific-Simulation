"""s6_run_apex.py — Invoke APEX0806 inside a workspace and collect outputs.

The binary always reads from and writes to the *current working directory*, so
we ``chdir`` into the workspace before invoking it. Because APEX0806 can return
exit code 0 even on Fortran severe errors (Known Trap #10), we cannot trust
``returncode`` — instead we check that the run produced *some* primary output
file (``.OUT``/``.ACY``/``.SAD``/``.MSW``) and that ``EPICERR.DAT`` is clean.

RUN1501.SUM trap: this file is the **multi-run** summary and is legitimately
empty when APEXRUN.DAT defines a single run (APEX only populates it when
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

# APEX v0806 PE32 binary run via Wine (v1501 has crop growth issues — see s1 docstring)
BINARY_NAME = "APEX0806.exe"
KI_ROOT = Path(__file__).resolve().parents[1]
SOURCE_BINARY = KI_ROOT / "reference" / "APEX0806.exe"

# File extensions that indicate a per-run APEX output was written. The
# presence of any one of these (non-empty) is the authoritative success signal.
_RUN_OUTPUT_EXTS = (".OUT", ".ACY", ".SAD", ".MSW", ".SUS", ".MAN")


def validate_inputs(workspace: Path) -> None:
    if not workspace.is_dir():
        raise FileNotFoundError(f"Workspace does not exist: {workspace}")
    for f in ("APEXFILE.DAT", "APEXCONT.DAT", "APEXRUN.DAT"):
        if not (workspace / f).is_file():
            raise FileNotFoundError(f"Required input missing in workspace: {f}")


def _ensure_binary(ws: Path) -> Path:
    bin_path = ws / BINARY_NAME
    if not bin_path.is_file():
        if not SOURCE_BINARY.is_file():
            raise FileNotFoundError(f"APEX0806 binary not found at {SOURCE_BINARY}")
        shutil.copy2(SOURCE_BINARY, bin_path)
    return bin_path


def _collect_run_outputs(ws: Path) -> list[str]:
    seen: set[str] = set()
    for ext in _RUN_OUTPUT_EXTS:
        for p in ws.glob(f"*{ext}"):
            if p.stat().st_size > 0:
                seen.add(p.name)
    return sorted(seen)


# ── APEX0806 terminal-fault gate ─────────────────────────────────────────
# APEX0806 can access-violate (forrtl severe 157) while writing the end-of-run
# timing footer on long runs (observed with APEXCONT.DAT NBYR=56 and with an
# OPC/MGT rotation of >= 50 years). The exact trigger is input-dependent -- the
# SAME workspace exits rc=0 after a small forcing perturbation -- so it cannot
# be gated on NBYR. What is stable is that the fault happens AFTER the
# simulation: measured 2026-08-09 on the Huaibin GDHY cell, the rc=157 run left
# a complete OUTPUT.ACY (224 CORN rows spanning YR#=1..56 == NBYR) and an
# OUTPUT.OUT carrying both end-of-run balance blocks, and repeat runs of the
# same workspace are bit-reproducible apart from the timestamp header line.
# Discarding such a run throws away a complete, correct result. We therefore
# accept it -- but ONLY when every completeness marker below is present. Every
# other severe error (24 EOF, 38 CONOUT$, a genuine mid-run abort, ...) still
# raises exactly as before.
_COMPLETION_MARKERS = ("TOTAL WATER BALANCE", "TOTAL SEDIMENT BALANCE")


def _nbyr_from_control(ws: Path) -> int | None:
    """NBYR from APEXCONT.DAT line 1 (fixed-width I4, or free format)."""
    p = ws / "APEXCONT.DAT"
    if not p.is_file():
        return None
    line = p.read_text(errors="replace").splitlines()[0] if p.read_text(errors="replace") else ""
    for cand in (line[:4], line.split()[0] if line.split() else ""):
        try:
            v = int(cand)
            if v > 0:
                return v
        except ValueError:
            continue
    return None


def _acy_max_year_index(ws: Path) -> int | None:
    """Largest YR# (4th column) over all CORN/crop rows of every *.ACY."""
    best = None
    for acy in list(ws.glob("*.ACY")) + list(ws.glob("*.acy")):
        for ln in acy.read_text(errors="replace").splitlines():
            f = ln.split()
            if len(f) >= 5 and all(x.lstrip("-").isdigit() for x in f[:4]):
                yr = int(f[3])
                best = yr if best is None else max(best, yr)
    return best


def _terminal_fault_only(ws: Path, stderr: str, err_text: str) -> tuple[bool, str]:
    """True iff the ONLY failure is the post-simulation footer access violation.

    Requires ALL of: EPICERR clean; the severe error is 157/access violation
    and nothing else; the end-of-run balance blocks were written; and *.ACY
    spans the full NBYR requested in APEXCONT.DAT.
    """
    if "ERROR" in err_text.upper():
        return False, "EPICERR.DAT is not clean"
    low = stderr.lower()
    if "severe (157)" not in low or "access violation" not in low:
        return False, "severe error is not the (157) access violation"
    if low.count("severe (") > 1:
        return False, "more than one severe error reported"
    out = ws / "OUTPUT.OUT"
    if not out.is_file():
        return False, "OUTPUT.OUT missing"
    text = out.read_text(errors="replace")
    missing = [m for m in _COMPLETION_MARKERS if m not in text]
    if missing:
        return False, f"end-of-run block(s) missing from OUTPUT.OUT: {missing}"
    nbyr = _nbyr_from_control(ws)
    span = _acy_max_year_index(ws)
    if nbyr is None or span is None:
        return False, "could not verify the *.ACY year span against NBYR"
    if span < nbyr:
        return False, f"*.ACY reaches YR#={span} but APEXCONT.DAT asks for NBYR={nbyr}"
    return True, (f"all of {list(_COMPLETION_MARKERS)} present in OUTPUT.OUT and "
                  f"*.ACY spans YR#=1..{span} == NBYR={nbyr}")


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
        ["wine", f"./{BINARY_NAME}"],
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
            f"APEX0806 produced no per-run output files in {ws} "
            f"(rc={proc.returncode}).\nstderr:\n{proc.stderr}\n"
            f"EPICERR.DAT:\n{err_text}"
        )

    terminal_fault = False
    if "severe" in (proc.stderr or "").lower() or "ERROR" in err_text.upper():
        ok, why = _terminal_fault_only(ws, proc.stderr or "", err_text)
        if not ok:
            raise RuntimeError(
                f"APEX0806 reported errors (rc={proc.returncode}).\n"
                f"stderr:\n{proc.stderr}\nEPICERR.DAT:\n{err_text}"
            )
        terminal_fault = True
        sys.stderr.write(
            f"[s6] WARNING: APEX0806 access-violated while writing the end-of-run "
            f"footer, but the simulation itself COMPLETED ({why}). Accepting the "
            f"outputs. Seen on long runs (NBYR=56 / OPC rotation >= 50 years); the "
            f"trigger is input-dependent -- see "
            f"diagnostics/triplets.yaml:apex0806_terminal_footer_fault.\n"
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
        "terminal_fault_accepted": terminal_fault,
        "out_files": out_files,
        "run_outputs": run_outputs,
        "sum_path": str(sum_path),
        "sum_bytes": sum_bytes,
    }


def validate_outputs(ws: Path, run_outputs: list[str]) -> None:
    if not run_outputs:
        raise RuntimeError(f"APEX0806 wrote no per-run output files in {ws}")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--workspace", required=True)
    p.add_argument("--timeout", type=int, default=600)
    args = p.parse_args()
    info = run(args.workspace, timeout=args.timeout)
    print(f"[OK] APEX run completed; outputs: {info['run_outputs']}")
