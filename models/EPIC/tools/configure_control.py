#!/usr/bin/env python3
"""Tune EPICCONT.DAT (the EPIC control file) via targeted value edits.

EPICCONT.DAT is a 7-line fixed-width Fortran file. This tool copies the shipped
template, then overwrites specific fields in-place using character slicing — it
NEVER regenerates the full file from a dict. The bulk of the physics defaults
in the template (CO2, snow parameters, etc.) are preserved.

Supported knobs (the most commonly-used EPICCONT fields):
    --duration           NBYR     Line 1, cols 1-4   (int years)
    --start-year         IYR0     Line 1, cols 5-9
    --start-month        IMO0     Line 1, cols 10-13
    --start-day          IDA0     Line 1, cols 14-17
    --print-code         IPD      Line 1, cols 18-21 (0=annual watershed ... 9=n-day growing)
    --weather-input      NGN      Line 1, cols 22-25 (0=generate,1=prcp,2=tmx/tmn/prcp,...)
    --water-erosion-eq   DRV      Line 6, field 4   (0=MUST 2=USLE 3=MUSS 4=MUSL 6=RUSL 7=RUS2)
    --irrigation-code    IRR      Site file, but also L4-F1 (e.g. 01 sprinkler flex, 15 drip rigid)
    --co2                CO2      Line 3, cols 9-16 (ppm)
    --pet-method         IET      Line 2 (1=Penman-Monteith 2=Penman 3=Priestley-Taylor 4=Hargreaves 5=Baier-Robertson)

USAGE:
    python configure_control.py --workspace ./run1 \
        --duration 10 --start-year 2005 --co2 420 --pet-method 1 --water-erosion-eq 3
"""

import argparse
import os
import shutil
import sys
from pathlib import Path


sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import TEMPLATES_DIR  # noqa: E402

TEMPLATE = Path(TEMPLATES_DIR) / "EPICCONT.DAT"


def _slice_replace(line, start, end, text):
    """Replace cols [start, end) with text, preserving line length."""
    width = end - start
    text = text[:width].rjust(width)
    return line[:start] + text + line[end:]


def patch_line1(lines, duration=None, start_year=None, start_month=None,
                start_day=None, print_code=None, weather_input=None):
    ln = lines[0].rstrip("\r\n")
    # Layout is space-delimited 4-char integer fields; the shipped template
    # uses 4-character right-aligned columns starting at col 0.
    if duration     is not None: ln = _slice_replace(ln,  0,  4, f"{duration:d}")
    if start_year   is not None: ln = _slice_replace(ln,  4,  9, f"{start_year:d}")
    if start_month  is not None: ln = _slice_replace(ln,  9, 13, f"{start_month:d}")
    if start_day    is not None: ln = _slice_replace(ln, 13, 17, f"{start_day:d}")
    if print_code   is not None: ln = _slice_replace(ln, 17, 21, f"{print_code:d}")
    if weather_input is not None: ln = _slice_replace(ln, 21, 25, f"{weather_input:d}")
    lines[0] = ln + "\n"
    return lines


def patch_line2(lines, pet_method=None):
    if pet_method is None:
        return lines
    ln = lines[1].rstrip("\r\n")
    # PET method lives in the second field of line 2 (IET)
    ln = _slice_replace(ln, 4, 9, f"{pet_method:d}")
    lines[1] = ln + "\n"
    return lines


def patch_line3(lines, co2=None):
    if co2 is None:
        return lines
    ln = lines[2].rstrip("\r\n")
    # CO2 = second floating field (cols 9-16 per manual)
    text = f"{co2:8.2f}"
    ln = ln[:8] + text + ln[16:]
    lines[2] = ln + "\n"
    return lines


def patch_line6(lines, water_erosion_eq=None):
    if water_erosion_eq is None or len(lines) < 6:
        return lines
    ln = lines[5].rstrip("\r\n")
    # DRV is the 4th float on line 6 (cols 25-32)
    text = f"{water_erosion_eq:8.2f}"
    ln = ln[:24] + text + ln[32:]
    lines[5] = ln + "\n"
    return lines


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--workspace", required=True,
                   help="Workspace directory containing (or to contain) EPICCONT.DAT")
    p.add_argument("--duration", type=int)
    p.add_argument("--start-year", type=int)
    p.add_argument("--start-month", type=int)
    p.add_argument("--start-day", type=int)
    p.add_argument("--print-code", type=int, choices=range(0, 10))
    p.add_argument("--weather-input", type=int,
                   help="NGN: 0=gen all, 1=prcp, 2=tmx/tmn+prcp, 23=tmx/tmn/srad/prcp, 2345=all")
    p.add_argument("--pet-method", type=int, choices=[1, 2, 3, 4, 5],
                   help="1=Penman-Monteith 2=Penman 3=Priestley-Taylor 4=Hargreaves 5=Baier-Robertson")
    p.add_argument("--co2", type=float, help="Atmospheric CO2 (ppm)")
    p.add_argument("--water-erosion-eq", type=int, choices=[0, 2, 3, 4, 6, 7],
                   help="DRV driving eq: 0=MUST 2=USLE 3=MUSS 4=MUSL 6=RUSL 7=RUS2")
    args = p.parse_args()

    os.makedirs(args.workspace, exist_ok=True)
    target = os.path.join(args.workspace, "EPICCONT.DAT")
    if not os.path.exists(target):
        if not TEMPLATE.exists():
            print(f"ERROR: EPICCONT template missing at {TEMPLATE}")
            sys.exit(2)
        shutil.copy2(TEMPLATE, target)
        print(f"Seeded EPICCONT.DAT from template -> {target}")

    with open(target) as f:
        lines = f.readlines()
    if len(lines) < 6:
        print("ERROR: EPICCONT.DAT has fewer than 6 lines — file is truncated")
        sys.exit(2)

    before = list(lines)
    patch_line1(lines,
                duration=args.duration,
                start_year=args.start_year,
                start_month=args.start_month,
                start_day=args.start_day,
                print_code=args.print_code,
                weather_input=args.weather_input)
    patch_line2(lines, pet_method=args.pet_method)
    patch_line3(lines, co2=args.co2)
    patch_line6(lines, water_erosion_eq=args.water_erosion_eq)

    with open(target, "w") as f:
        f.writelines(lines)

    print(f"Updated {target}")
    for i, (b, a) in enumerate(zip(before, lines)):
        if b != a:
            print(f"  line {i+1}:")
            print(f"    before: {b.rstrip()}")
            print(f"    after:  {a.rstrip()}")


if __name__ == "__main__":
    main()
