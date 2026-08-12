#!/usr/bin/env python3
"""Edit EPICCONT.DAT to configure irrigation mode.

IRR = 0 dryland, 1 scheduled, 2 auto-stress, 3 auto-deficit
"""
import argparse
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import copy_template, read_text_crlf, write_text_crlf


MODE_MAP = {"dryland": 0, "scheduled": 1, "auto": 2, "auto_deficit": 3}


def configure(workspace, mode, water_stress, efficiency):
    os.makedirs(workspace, exist_ok=True)
    dst = os.path.join(workspace, "EPICCONT.DAT")
    if not os.path.isfile(dst):
        copy_template("EPICCONT.DAT", workspace)

    irr = MODE_MAP[mode]
    text = read_text_crlf(dst)
    lines = text.splitlines()

    row1 = lines[1].rstrip()
    cols = [row1[i:i + 5] for i in range(0, len(row1), 5)]
    while len(cols) < 21:
        cols.append("    0")
    cols[7] = f"{irr:>5d}"
    lines[1] = "".join(cols)

    write_text_crlf(dst, "\r\n".join(lines))
    print(f"  set IRR={irr} ({mode}) in {dst}")
    if mode.startswith("auto"):
        print(f"  note: water_stress={water_stress} efficiency={efficiency} "
              f"advisory — edit PARM1102 index 67 for fine control")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--mode", choices=list(MODE_MAP), default="auto")
    ap.add_argument("--water-stress", type=float, default=0.8)
    ap.add_argument("--efficiency", type=float, default=0.85)
    args = ap.parse_args()
    configure(args.workspace, args.mode, args.water_stress, args.efficiency)


if __name__ == "__main__":
    main()
