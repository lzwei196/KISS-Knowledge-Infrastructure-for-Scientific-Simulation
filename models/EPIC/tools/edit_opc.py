#!/usr/bin/env python3
"""Edit an EPIC operation schedule (.OPC) file.

The .OPC format has a 2-line header followed by operation rows. Each operation
row uses fixed-width integers + floats:

    cols  1- 3  JX(1)  year in rotation   (I3)
    cols  4- 6  JX(2)  month              (I3)
    cols  7- 9  JX(3)  day of month       (I3)
    cols 10-14  JX(4)  equipment/op id    (I5)  -> TILLCOM.DAT
    cols 15-19  JX(5)  tractor id         (I5)
    cols 20-24  JX(6)  crop id            (I5)  -> CROPCOM.DAT
    cols 25-29  JX(7)  context id         (I5)  (fertilizer / pesticide / tree years)
    cols 30-37  OPV1                      (F8.2) rate / PHU / irrigation volume
    cols 38-45  OPV2                      (F8.2) land use or CN override
    cols 46-53  OPV3                      (F8.2) auto irrigation trigger
    cols 54-61  OPV4                      (F8.2) runoff/irrig ratio
    cols 62-69  OPV5                      (F8.2) plant population
    cols 70-77  OPV6                      (F8.2) max N fertilizer per crop
    cols 78-85  OPV7                      (F8.2) heat unit fraction
    cols 86-93  OPV8                      (F8.2) min C factor
    cols 94-101 OPV9                      (F8.2) grain moisture

The tool ships with subcommands for the most common edits:

    plant        Replace the crop id on existing planting rows, optionally
                 update plant population + PHU + planting date.
    fertilize    Append/replace a fertilizer application row.
    irrigate     Toggle auto-irrigation trigger (OPV3) on an existing row.
    add-row      Append a free-form operation row.
    show         Print parsed rows.

USAGE:
    python edit_opc.py plant      --opc opc/corn.OPC --crop-id 2 --phu 1600 --pop 7.5
    python edit_opc.py fertilize  --opc opc/corn.OPC --year 1 --month 4 --day 24 --fert-id 52 --rate 160
    python edit_opc.py irrigate   --opc opc/corn.OPC --trigger 0.8
    python edit_opc.py show       --opc opc/corn.OPC
"""

import argparse
import os
import sys


def _i(s):
    s = s.strip()
    return int(s) if s else 0


def _f(s):
    s = s.strip()
    return float(s) if s else 0.0


def parse_row(line):
    line = line.rstrip("\n").ljust(101)
    return {
        "year":  _i(line[0:3]),
        "month": _i(line[3:6]),
        "day":   _i(line[6:9]),
        "equip": _i(line[9:14]),
        "tract": _i(line[14:19]),
        "crop":  _i(line[19:24]),
        "ctx":   _i(line[24:29]),
        "opv1":  _f(line[29:37]),
        "opv2":  _f(line[37:45]),
        "opv3":  _f(line[45:53]),
        "opv4":  _f(line[53:61]),
        "opv5":  _f(line[61:69]),
        "opv6":  _f(line[69:77]),
        "opv7":  _f(line[77:85]),
        "opv8":  _f(line[85:93]),
        "opv9":  _f(line[93:101]),
    }


def format_row(r):
    return (
        f"{r['year']:3d}{r['month']:3d}{r['day']:3d}"
        f"{r['equip']:5d}{r['tract']:5d}{r['crop']:5d}{r['ctx']:5d}"
        f"{r['opv1']:8.2f}{r['opv2']:8.2f}{r['opv3']:8.2f}{r['opv4']:8.2f}"
        f"{r['opv5']:8.2f}{r['opv6']:8.2f}{r['opv7']:8.2f}{r['opv8']:8.2f}{r['opv9']:8.2f}\n"
    )


def load(opc_path):
    with open(opc_path) as f:
        lines = f.readlines()
    if len(lines) < 2:
        raise ValueError(f"{opc_path} has fewer than 2 header lines — not an OPC file")
    header = lines[:2]
    rows = []
    for ln in lines[2:]:
        if not ln.strip():
            continue
        rows.append(parse_row(ln))
    return header, rows


def save(opc_path, header, rows):
    with open(opc_path, "w") as f:
        f.writelines(header)
        for r in rows:
            f.write(format_row(r))


def cmd_plant(args):
    header, rows = load(args.opc)
    changed = 0
    # Equipment IDs 2, 3, 4, 136, 146 are all planting operations in the
    # shipped TILLCOM.DAT. Any row whose equipment id falls in that set and
    # carries a non-zero crop id is treated as an existing planting row.
    PLANT_EQUIP = {2, 3, 4, 136, 146}
    for r in rows:
        if r["equip"] in PLANT_EQUIP and r["crop"] > 0:
            r["crop"] = args.crop_id
            if args.phu is not None:
                r["opv1"] = args.phu
            if args.pop is not None:
                r["opv5"] = args.pop
            if args.month is not None:
                r["month"] = args.month
            if args.day is not None:
                r["day"] = args.day
            changed += 1
    save(args.opc, header, rows)
    print(f"plant: updated {changed} planting row(s) in {args.opc}")


def cmd_fertilize(args):
    header, rows = load(args.opc)
    new = {
        "year": args.year, "month": args.month, "day": args.day,
        "equip": 71,  # fertilizer application op code in TILLCOM.DAT
        "tract": 0, "crop": 0, "ctx": args.fert_id,
        "opv1": args.rate, "opv2": 0.0, "opv3": 0.0, "opv4": 0.0,
        "opv5": 0.0, "opv6": 0.0, "opv7": 0.0, "opv8": 0.0, "opv9": 0.0,
    }
    rows.append(new)
    rows.sort(key=lambda r: (r["year"], r["month"], r["day"]))
    save(args.opc, header, rows)
    print(f"fertilize: added {args.rate} kg/ha of fert {args.fert_id} "
          f"on {args.year:02d}-{args.month:02d}-{args.day:02d} in {args.opc}")


def cmd_irrigate(args):
    header, rows = load(args.opc)
    PLANT_EQUIP = {2, 3, 4, 136, 146}
    changed = 0
    for r in rows:
        if r["equip"] in PLANT_EQUIP and r["crop"] > 0:
            r["opv3"] = args.trigger
            changed += 1
    save(args.opc, header, rows)
    print(f"irrigate: set auto-irrigation trigger (OPV3) to {args.trigger} "
          f"on {changed} planting row(s)")


def cmd_add_row(args):
    header, rows = load(args.opc)
    new = {
        "year": args.year, "month": args.month, "day": args.day,
        "equip": args.equip, "tract": args.tract, "crop": args.crop,
        "ctx": args.ctx,
        "opv1": args.opv1, "opv2": args.opv2, "opv3": args.opv3,
        "opv4": args.opv4, "opv5": args.opv5, "opv6": args.opv6,
        "opv7": args.opv7, "opv8": args.opv8, "opv9": args.opv9,
    }
    rows.append(new)
    rows.sort(key=lambda r: (r["year"], r["month"], r["day"]))
    save(args.opc, header, rows)
    print(f"add-row: appended row in {args.opc}")


def cmd_show(args):
    header, rows = load(args.opc)
    for h in header:
        sys.stdout.write(h)
    print(f"\n{len(rows)} operation rows:")
    for i, r in enumerate(rows):
        print(f"  {i+1:3d}  yr={r['year']} {r['month']:02d}-{r['day']:02d}  "
              f"equip={r['equip']:4d}  crop={r['crop']:4d}  ctx={r['ctx']:4d}  "
              f"opv1={r['opv1']:8.2f} opv3_auto={r['opv3']:.2f}")


def build_parser():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("plant")
    sp.add_argument("--opc", required=True)
    sp.add_argument("--crop-id", type=int, required=True)
    sp.add_argument("--phu", type=float)
    sp.add_argument("--pop", type=float)
    sp.add_argument("--month", type=int)
    sp.add_argument("--day", type=int)
    sp.set_defaults(func=cmd_plant)

    sf = sub.add_parser("fertilize")
    sf.add_argument("--opc", required=True)
    sf.add_argument("--year", type=int, default=1)
    sf.add_argument("--month", type=int, required=True)
    sf.add_argument("--day", type=int, required=True)
    sf.add_argument("--fert-id", type=int, required=True,
                    help="Fertilizer id from FERT2012.DAT (e.g. 52=urea)")
    sf.add_argument("--rate", type=float, required=True, help="kg/ha")
    sf.set_defaults(func=cmd_fertilize)

    si = sub.add_parser("irrigate")
    si.add_argument("--opc", required=True)
    si.add_argument("--trigger", type=float, required=True,
                    help="Auto-irrigation trigger (0-1 = plant water stress, >1 = kPa)")
    si.set_defaults(func=cmd_irrigate)

    sa = sub.add_parser("add-row")
    sa.add_argument("--opc", required=True)
    sa.add_argument("--year", type=int, default=1)
    sa.add_argument("--month", type=int, required=True)
    sa.add_argument("--day", type=int, required=True)
    sa.add_argument("--equip", type=int, required=True)
    sa.add_argument("--tract", type=int, default=0)
    sa.add_argument("--crop", type=int, default=0)
    sa.add_argument("--ctx", type=int, default=0)
    sa.add_argument("--opv1", type=float, default=0.0)
    sa.add_argument("--opv2", type=float, default=0.0)
    sa.add_argument("--opv3", type=float, default=0.0)
    sa.add_argument("--opv4", type=float, default=0.0)
    sa.add_argument("--opv5", type=float, default=0.0)
    sa.add_argument("--opv6", type=float, default=0.0)
    sa.add_argument("--opv7", type=float, default=0.0)
    sa.add_argument("--opv8", type=float, default=0.0)
    sa.add_argument("--opv9", type=float, default=0.0)
    sa.set_defaults(func=cmd_add_row)

    ss = sub.add_parser("show")
    ss.add_argument("--opc", required=True)
    ss.set_defaults(func=cmd_show)

    return p


def main():
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
