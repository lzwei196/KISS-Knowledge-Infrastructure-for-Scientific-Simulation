#!/usr/bin/env python3
"""Toggle which EPIC output files are produced via PRNT1102.DAT.

PRNT1102.DAT is the EPIC print control file. Lines 15 and 16 contain a grid
of per-column integer toggles; the matching extension names are listed in the
trailing two comment/header lines of the shipped template.

Rather than regenerating PRNT1102.DAT from scratch, this tool:
  1. Reads the shipped template's header to learn which column maps to which
     extension.
  2. Copies the template into the workspace if it is missing.
  3. Rewrites only lines 15/16 with 1 or 0 per column.

Valid extensions (from the EPIC 1102 user manual):
    OUT ACM SUM DHY DPS MFS MPS ANN SOT DTP
    MCM DCS SCO ACN DCN SCN DGN DWT ACY ACO
    DSL MWC ABR ATG MSW APS DWC DHS DGZ DNC
    ASL DDN

USAGE:
    python set_output_types.py --workspace ./run1 --enable ACY,DGN,ANN,ABR,ACN
"""

import argparse
import os
import shutil
import sys
from pathlib import Path


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import TEMPLATES_DIR  # noqa: E402

TEMPLATE = Path(TEMPLATES_DIR) / "PRNT1102.DAT"

VALID_EXTS = {
    "OUT", "ACM", "SUM", "DHY", "DPS", "MFS", "MPS", "ANN", "SOT", "DTP",
    "MCM", "DCS", "SCO", "ACN", "DCN", "SCN", "DGN", "DWT", "ACY", "ACO",
    "DSL", "MWC", "ABR", "ATG", "MSW", "APS", "DWC", "DHS", "DGZ", "DNC",
    "ASL", "DDN",
}

# Fixed column layout from the template (manual table 17):
# Line 15 columns are ACM ... ACO (IDs 1-20) in 4-char fields.
# Line 16 columns are DSL ... DDN (IDs 21-32).
L15_EXT = ["OUT", "ACM", "SUM", "DHY", "DPS", "MFS", "MPS", "ANN",
           "SOT", "DTP", "MCM", "DCS", "SCO", "ACN", "DCN", "SCN",
           "DGN", "DWT", "ACY", "ACO"]
L16_EXT = ["DSL", "MWC", "ABR", "ATG", "MSW", "APS", "DWC", "DHS",
           "DGZ", "DNC", "ASL", "DDN"]


def build_toggle_line(wanted, ext_list):
    toks = []
    for i, ext in enumerate(ext_list, 1):
        toks.append(f"{i if ext in wanted else 0:4d}")
    return "".join(toks) + "\n"


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--workspace", required=True)
    p.add_argument("--enable", required=True,
                   help="Comma-separated list of output extensions to enable")
    args = p.parse_args()

    wanted = {e.strip().upper() for e in args.enable.split(",") if e.strip()}
    bad = wanted - VALID_EXTS
    if bad:
        print(f"ERROR: unknown extensions: {sorted(bad)}")
        print(f"Valid: {sorted(VALID_EXTS)}")
        sys.exit(2)

    os.makedirs(args.workspace, exist_ok=True)
    target = os.path.join(args.workspace, "PRNT1102.DAT")
    if not os.path.exists(target):
        if not TEMPLATE.exists():
            print(f"ERROR: PRNT1102.DAT template missing at {TEMPLATE}")
            sys.exit(2)
        shutil.copy2(TEMPLATE, target)
        print(f"Seeded PRNT1102.DAT from template -> {target}")

    with open(target) as f:
        lines = f.readlines()

    # Lines 15/16 are 1-indexed in the manual -> 0-indexed 14/15.
    if len(lines) < 16:
        print(f"ERROR: PRNT1102.DAT too short ({len(lines)} lines)")
        sys.exit(2)
    lines[14] = build_toggle_line(wanted, L15_EXT)
    lines[15] = build_toggle_line(wanted, L16_EXT)

    with open(target, "w") as f:
        f.writelines(lines)

    print(f"Updated {target}")
    print(f"Enabled outputs: {sorted(wanted)}")


if __name__ == "__main__":
    main()
