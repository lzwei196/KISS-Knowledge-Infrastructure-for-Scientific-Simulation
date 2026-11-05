#!/usr/bin/env python3
"""
build_lpjguess_co2_file.py -- annual atmospheric CO2 file for the REAL
LPJ-GUESS engine (param "file_co2"; read by modules/globalco2file.cpp).

The 4.1.1 release does not ship a CO2 file. This tool splices two real
records into the engine's format, one "<year> <ppm>" line per year with no
gaps (the reader fails on a skipped year):
  * Law Dome ice core + Cape Grim spline (Etheridge et al. 1996;
    MacFarling Meure et al. 2006), NOAA NCEI law2006.txt, column 6
    "CO2 Spline (ppm)" -- used for years before the first Mauna Loa year;
  * NOAA GML Mauna Loa annual means, co2_annmean_mlo.txt (1959 onward).
Years before the first line of the file get the FIRST value inside the
engine; CO2 is read by calendar year, and the spin-up calendar starts
nyear_spinup years before the first forcing year. With forcing from 1984 and
a 500-year spin-up (1484-1983), 1484-1900 run at 296.2 ppm (the 1901 value)
and 1901-1983 follow the real record.

Exit codes: 0 ok, 2 bad input / gap / implausible value.

Usage:
  python build_lpjguess_co2_file.py --law_dome law2006.txt \
      --mauna_loa co2_annmean_mlo.txt --start_year 1901 --end_year 2014 --out co2.txt
"""
import argparse
import json
import sys


def read_law_dome(path):
    """Year -> CO2 spline value from law2006.txt (columns 5/6 of the spline table)."""
    out, in_table = {}, False
    with open(path, encoding="latin-1") as f:
        for line in f:
            s = line.split()
            if s[:1] == ["YearAD"] and "CO2spl" in s:
                in_table = True
                continue
            if not in_table:
                continue
            if len(s) < 6:
                if out:          # first short line after the table ends it
                    break
                continue
            try:
                yr, val = float(s[4]), float(s[5])
            except ValueError:
                break
            out[int(round(yr))] = val
    return out


def read_mauna_loa(path):
    out = {}
    with open(path) as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            s = line.split()
            out[int(s[0])] = float(s[1])
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--law_dome", required=True)
    ap.add_argument("--mauna_loa", required=True)
    ap.add_argument("--start_year", type=int, default=1901)
    ap.add_argument("--end_year", type=int, required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    if a.end_year < a.start_year:
        print(f"ERROR: end_year {a.end_year} < start_year {a.start_year}", file=sys.stderr)
        return 2
    try:
        ld, ml = read_law_dome(a.law_dome), read_mauna_loa(a.mauna_loa)
    except (OSError, ValueError, IndexError) as e:
        print(f"ERROR: could not read a CO2 record: {e}", file=sys.stderr)
        return 2
    if not ld or not ml:
        print("ERROR: could not parse one of the CO2 records", file=sys.stderr)
        return 2
    first_ml = min(ml)
    rows, src = [], {"law_dome": 0, "mauna_loa": 0}
    for y in range(a.start_year, a.end_year + 1):
        if y >= first_ml and y in ml:
            v, k = ml[y], "mauna_loa"
        elif y < first_ml and y in ld:
            v, k = ld[y], "law_dome"
        else:
            print(f"ERROR: no CO2 value for {y} (Mauna Loa {first_ml}-{max(ml)}, "
                  f"Law Dome {min(ld)}-{max(ld)})", file=sys.stderr)
            return 2
        if not 250 < v < 500:
            print(f"ERROR: CO2 {v} ppm in {y} is implausible", file=sys.stderr)
            return 2
        rows.append((y, v))
        src[k] += 1
    try:
        with open(a.out, "w") as f:
            for y, v in rows:
                f.write(f"{y} {v:.2f}\n")
    except OSError as e:
        print(f"ERROR: cannot write {a.out}: {e}", file=sys.stderr)
        return 2
    splice = None
    if first_ml in ld:
        splice = round(ml[first_ml] - ld[first_ml], 2)
    print(json.dumps({"status": "success", "out": a.out, "years": [rows[0][0], rows[-1][0]],
                      "first_ppm": rows[0][1], "last_ppm": rows[-1][1], "n_from": src,
                      "splice_offset_ppm_at_first_mauna_loa_year": splice}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
