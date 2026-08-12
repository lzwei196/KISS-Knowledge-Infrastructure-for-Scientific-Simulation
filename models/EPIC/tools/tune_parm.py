#!/usr/bin/env python3
"""Tune PARM1102.DAT parameters by index, preserving fixed-width layout.

PARM1102.DAT contains 112 global EPIC parameters on fixed-width lines of
10 fields x 8 characters each. Parameters are referenced by 1-based index
(PRMT(N) in the manual). This tool overwrites the target cell in place,
then writes the updated file back.

USAGE:
    # Set PRMT(30) = 0.75  (Hargreaves/Kemanian mix)
    python tune_parm.py --workspace ./run1 --set 30=0.75

    # Set multiple parameters
    python tune_parm.py --workspace ./run1 --set 30=0.75 --set 38=0.0030

    # Show a parameter
    python tune_parm.py --workspace ./run1 --get 30
"""

import argparse
import os
import shutil
import sys
from pathlib import Path


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import TEMPLATES_DIR  # noqa: E402

TEMPLATE = Path(TEMPLATES_DIR) / "PARM1102.DAT"

FIELD_WIDTH = 8
FIELDS_PER_LINE = 10
# PRMT lines start at line 23 (index 22) in PARM1102.DAT: lines 1-22 are
# S-curve parameter pairs (SCRP). This can vary between versions; we locate
# them by the first line whose layout matches 10 x F8.
FIRST_PARM_LINE_HINT = 22


def _parm_index_to_line_col(index):
    """Convert 1-based PRMT index to (line_offset_from_first_parm, field_index)."""
    i0 = index - 1
    return divmod(i0, FIELDS_PER_LINE)


def _find_first_parm_line(lines):
    for i in range(max(0, FIRST_PARM_LINE_HINT - 3),
                   min(len(lines), FIRST_PARM_LINE_HINT + 5)):
        ln = lines[i].rstrip("\r\n")
        if len(ln) >= 16 and all(c in "0123456789.- " for c in ln[:80]):
            try:
                float(ln[0:8])
                float(ln[8:16])
                return i
            except ValueError:
                continue
    return FIRST_PARM_LINE_HINT


def get_parm(lines, index, first_line):
    line_off, field = _parm_index_to_line_col(index)
    row = first_line + line_off
    if row >= len(lines):
        raise IndexError(f"PRMT({index}) is past the end of PARM1102.DAT")
    col = field * FIELD_WIDTH
    cell = lines[row][col:col + FIELD_WIDTH]
    return float(cell)


def set_parm(lines, index, value, first_line):
    line_off, field = _parm_index_to_line_col(index)
    row = first_line + line_off
    col = field * FIELD_WIDTH
    ln = lines[row].rstrip("\r\n")
    if len(ln) < col + FIELD_WIDTH:
        ln = ln.ljust(col + FIELD_WIDTH)
    text = f"{value:8.4f}"[:FIELD_WIDTH]
    new_ln = ln[:col] + text + ln[col + FIELD_WIDTH:]
    lines[row] = new_ln + "\n"


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--workspace", required=True)
    p.add_argument("--set", action="append", default=[],
                   help="Assignments like INDEX=VALUE, may be repeated")
    p.add_argument("--get", type=int, action="append", default=[],
                   help="Print PRMT(index)")
    args = p.parse_args()

    os.makedirs(args.workspace, exist_ok=True)
    target = os.path.join(args.workspace, "PARM1102.DAT")
    if not os.path.exists(target):
        if not TEMPLATE.exists():
            print(f"ERROR: PARM1102.DAT template missing at {TEMPLATE}")
            sys.exit(2)
        shutil.copy2(TEMPLATE, target)
        print(f"Seeded PARM1102.DAT from template -> {target}")

    with open(target) as f:
        lines = f.readlines()
    first = _find_first_parm_line(lines)

    for assign in args.set:
        if "=" not in assign:
            print(f"ERROR: --set expects INDEX=VALUE, got {assign!r}")
            sys.exit(2)
        idx, val = assign.split("=", 1)
        before = get_parm(lines, int(idx), first)
        set_parm(lines, int(idx), float(val), first)
        print(f"PRMT({idx}): {before:.4f} -> {float(val):.4f}")

    if args.set:
        with open(target, "w") as f:
            f.writelines(lines)
        print(f"Wrote {target}")

    for idx in args.get:
        print(f"PRMT({idx}) = {get_parm(lines, idx, first):.4f}")


if __name__ == "__main__":
    main()
