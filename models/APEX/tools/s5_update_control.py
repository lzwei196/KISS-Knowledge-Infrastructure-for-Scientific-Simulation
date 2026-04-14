"""s5_update_control.py — Update APEXCONT.DAT simulation period in place.

APEXCONT.DAT line 1 holds the time-control header:
    NBYR  IYR  IMO  IDA  IPD  NGN  ...

We rewrite NBYR (number of years), IYR (start year), IMO/IDA (start month/day),
optionally IPD (print frequency) and NGN (weather generator code). Everything
else on that line, and every subsequent line of APEXCONT.DAT, is preserved.

Width trap: APEX reads line 1 list-directed, so the values must be separated
by whitespace. Writing everything with pure ``%4d`` glues 1-digit NBYR onto
4-digit IYR (e.g. ``'   62010'``), after which list-directed parsing swallows
the pair as the single integer 62010 — all downstream fields shift, simulation
silently targets the wrong period. The shipped example template uses mixed
widths that always leave ≥1 space between tokens; we reproduce those widths
exactly: I4 I5 I4 I4 I4 I5 + 14×I4 = 82 columns.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

CONT_NAME = "APEXCONT.DAT"

_CONT_WIDTHS = [4, 5, 4, 4, 4, 5] + [4] * 14  # 82 cols, matches example template


def validate_inputs(workspace: Path, year1: int, year2: int) -> None:
    if not workspace.is_dir():
        raise FileNotFoundError(f"Workspace does not exist: {workspace}")
    if not (workspace / CONT_NAME).is_file():
        raise FileNotFoundError(f"{CONT_NAME} missing in workspace")
    if year2 < year1:
        raise ValueError(f"year2 ({year2}) must be >= year1 ({year1})")
    if year1 < 1900 or year2 > 2100:
        raise ValueError(f"year range {year1}-{year2} outside [1900, 2100]")


def update_control(workspace, *, year1: int, year2: int,
                   month1: int = 1, day1: int = 1,
                   ipd: int = 3, ngn: int = 2345) -> Path:
    ws = Path(workspace).expanduser().resolve()
    validate_inputs(ws, year1, year2)

    cont_path = ws / CONT_NAME
    lines = cont_path.read_text().splitlines()
    if not lines:
        raise RuntimeError(f"{cont_path} is empty")

    nbyr = year2 - year1 + 1
    fields = lines[0].split()
    while len(fields) < len(_CONT_WIDTHS):
        fields.append("0")
    fields[0] = str(nbyr)
    fields[1] = str(year1)
    fields[2] = str(month1)
    fields[3] = str(day1)
    fields[4] = str(ipd)
    fields[5] = str(ngn)
    lines[0] = "".join(
        f"{int(v):{w}d}" for v, w in zip(fields[: len(_CONT_WIDTHS)], _CONT_WIDTHS)
    )

    cont_path.write_text("\n".join(lines) + "\n")
    validate_outputs(cont_path, year1, year2)
    return cont_path


def validate_outputs(cont_path: Path, year1: int, year2: int) -> None:
    lines = cont_path.read_text().splitlines()
    fields = lines[0].split()
    if int(fields[0]) != year2 - year1 + 1:
        raise RuntimeError(f"{cont_path}: NBYR write-back mismatch")
    if int(fields[1]) != year1:
        raise RuntimeError(f"{cont_path}: IYR write-back mismatch")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--workspace", required=True)
    p.add_argument("--year1", type=int, required=True)
    p.add_argument("--year2", type=int, required=True)
    p.add_argument("--ngn", type=int, default=2345)
    args = p.parse_args()
    out = update_control(args.workspace, year1=args.year1, year2=args.year2, ngn=args.ngn)
    print(f"[OK] control updated at {out}")
