#!/usr/bin/env python3
"""Build an EPIC .SIT file by copying umstead.SIT and updating lat/lon/elev/slope/CO2."""
import argparse
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import copy_template, read_text_crlf, write_text_crlf


def _fmt(val, width=8, decimals=2):
    return f"{val:>{width}.{decimals}f}"


def build(name, lat, lon, elev, slope, co2, workspace):
    os.makedirs(workspace, exist_ok=True)
    dst = copy_template("umstead.SIT", workspace, new_name=f"{name}.SIT")

    text = read_text_crlf(dst)
    lines = text.splitlines()

    lines[0] = f"{name:<80}"
    lines[1] = f"{name}.SIT".ljust(79)

    row = lines[3] if len(lines) > 3 else ""
    head = _fmt(lat) + _fmt(lon) + _fmt(elev) + _fmt(slope) + _fmt(co2)
    if len(row) >= 48:
        tail = row[48:]
    else:
        tail = "    0.00    0.00     0.0     0.0     0.0     0.0"
    if len(lines) <= 3:
        lines.append(head + tail)
    else:
        lines[3] = head + tail

    write_text_crlf(dst, "\r\n".join(lines))
    return dst


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--lat", type=float, required=True)
    ap.add_argument("--lon", type=float, required=True)
    ap.add_argument("--elev", type=float, default=100.0)
    ap.add_argument("--slope", type=float, default=0.01)
    ap.add_argument("--co2", type=float, default=410.0)
    ap.add_argument("--workspace", required=True)
    args = ap.parse_args()
    path = build(args.name, args.lat, args.lon, args.elev, args.slope,
                 args.co2, args.workspace)
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
