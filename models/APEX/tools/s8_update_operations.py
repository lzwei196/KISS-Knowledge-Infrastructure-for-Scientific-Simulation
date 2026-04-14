"""s8_update_operations.py — Edit OPSC*.MGT / *.OPC operation schedules in place.

APEX hard-codes crop type and management calendar inside the operation
schedule file referenced by ``MNGTLIST.DAT``. The shipped template
(``OPSC01.MGT``) encodes the USDA-ARS WRE Marena OK pasture-grazing dataset
(op code 132 = plant forage/pasture). Running the pipeline on a new site
with the template unchanged means only *hydrology* variables transfer — any
``crop_yield`` output stays pinned to the original crop and calendar.

This tool offers two pragmatic ways to retarget the operation schedule:

1. ``replace_plant_code(workspace, old, new)``
   — Swap every occurrence of operation code ``old`` on column 4 for ``new``.
   Use this when you know the template's plant op code and want to swap
   the crop for a different PLANTABLE.DAT row (e.g. 132 → 4 for CORN).

2. ``rewrite_from_rows(workspace, name, rows)``
   — Overwrite ``OPSC01.MGT`` with a caller-supplied list of ``OperationRow``
   tuples. This is the escape hatch when the replacement is structural
   (different rotation length, different set of operations) rather than a
   single-code swap.

The schedule file format (per APEX1501 Manual §2.10):

    Line 1: title
    Line 2: header line (" NN" rotation count)
    Line 3..N: operation rows, fixed-width 16 fields:
       col  1: rotation year  (I3)
       col  2: month          (I3)
       col  3: day            (I3)
       col  4: op code        (I5)   — references PLANT/TILL/FERT/PEST tables
       col  5: code2          (I5)
       col  6: code3          (I5)
       col  7: code4          (I5)
       col  8: code5          (I5)
       col  9..16: 8 × F9.2 operation parameters

Widths were confirmed by character-level inspection of the shipped example;
APEX itself reads the rows list-directed so whitespace separation is the
only hard requirement.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Sequence

OPSC_NAME = "OPSC01.MGT"


@dataclass
class OperationRow:
    year: int
    month: int
    day: int
    op_code: int
    code2: int = 0
    code3: int = 0
    code4: int = 0
    code5: int = 0
    params: List[float] = field(default_factory=lambda: [0.0] * 8)

    def format(self) -> str:
        p = list(self.params) + [0.0] * (8 - len(self.params))
        p = p[:8]
        return (
            f"{self.year:3d}{self.month:3d}{self.day:3d}"
            f"{self.op_code:5d}{self.code2:5d}{self.code3:5d}"
            f"{self.code4:5d}{self.code5:5d}"
            + "".join(f"{v:9.2f}" for v in p)
        )


def _ensure(workspace: Path, name: str = OPSC_NAME) -> Path:
    ws = Path(workspace).expanduser().resolve()
    if not ws.is_dir():
        raise FileNotFoundError(f"Workspace does not exist: {ws}")
    path = ws / name
    if not path.is_file():
        raise FileNotFoundError(f"{name} missing in workspace: {path}")
    return path


def replace_plant_code(workspace, *, old_plant_code: int, new_plant_code: int,
                       name: str = OPSC_NAME) -> Path:
    """Swap every row whose op_code column equals ``old_plant_code`` to
    ``new_plant_code``. Only column 4 (the operation code) is rewritten; the
    rest of each row is preserved byte-for-byte."""
    path = _ensure(Path(workspace), name)
    lines = path.read_text().splitlines()
    if len(lines) < 3:
        raise RuntimeError(f"{path}: expected ≥3 lines, got {len(lines)}")

    n_replaced = 0
    out = [lines[0], lines[1]]
    for raw in lines[2:]:
        if not raw.strip():
            out.append(raw)
            continue
        parts = raw.split()
        if len(parts) < 4:
            out.append(raw)
            continue
        try:
            if int(parts[3]) == old_plant_code:
                parts[3] = str(new_plant_code)
                # Rewrite the first 4 integer cols with fixed widths while
                # keeping the param tail exactly as it was.
                head = (
                    f"{int(parts[0]):3d}"
                    f"{int(parts[1]):3d}"
                    f"{int(parts[2]):3d}"
                    f"{int(parts[3]):5d}"
                )
                # Find where column 4 ends in the original line and splice.
                # Original layout: 3+3+3+5 = 14 chars of header cols.
                tail = raw[14:] if len(raw) > 14 else ""
                out.append(head + tail)
                n_replaced += 1
                continue
        except ValueError:
            pass
        out.append(raw)

    if n_replaced == 0:
        raise RuntimeError(
            f"{path}: no rows found with op_code={old_plant_code} — "
            f"check the template before swapping crop codes"
        )

    path.write_text("\n".join(out) + "\n")
    return path


def rewrite_from_rows(workspace, *, title: str, rows: Sequence[OperationRow],
                      name: str = OPSC_NAME) -> Path:
    """Overwrite OPSC01.MGT with a caller-supplied rotation. Useful when the
    default Marena pasture calendar is unsuitable for the target site/crop.

    The caller is responsible for choosing valid APEX operation codes — see
    PLANTABLE.DAT / TILLTABLE.DAT / FERTTABLE.DAT in the workspace for the
    indices that the op code column references.
    """
    path = _ensure(Path(workspace), name)
    n_rot = max((r.year for r in rows), default=0)
    header = [f"   {title[:70]}", f"{n_rot:4d}                        "]
    body = [r.format() for r in rows]
    path.write_text("\n".join(header + body) + "\n\n")
    validate_outputs(path)
    return path


def validate_outputs(path: Path) -> None:
    lines = path.read_text().splitlines()
    if len(lines) < 3:
        raise RuntimeError(f"{path}: expected ≥3 lines after rewrite, got {len(lines)}")
    # Spot-check: every non-empty data row must parse into at least 4 integers.
    for i, raw in enumerate(lines[2:], start=3):
        if not raw.strip():
            continue
        parts = raw.split()
        if len(parts) < 4:
            raise RuntimeError(f"{path}:{i}: too few fields: {raw!r}")
        try:
            [int(parts[k]) for k in range(4)]
        except ValueError as e:
            raise RuntimeError(f"{path}:{i}: non-integer in cols 1-4: {raw!r}") from e


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("replace-plant-code",
                        help="Swap plant operation code across the rotation")
    pr.add_argument("--workspace", required=True)
    pr.add_argument("--old", type=int, required=True)
    pr.add_argument("--new", type=int, required=True)

    args = p.parse_args()
    if args.cmd == "replace-plant-code":
        out = replace_plant_code(args.workspace,
                                 old_plant_code=args.old,
                                 new_plant_code=args.new)
        print(f"[OK] operation schedule updated at {out}")
