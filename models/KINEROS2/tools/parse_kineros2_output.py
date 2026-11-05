#!/usr/bin/env python3
"""parse_kineros2_output.py -- read a REAL KINEROS2 output (.out) and PRINT=3 CSV files.

Turns the engine's text report into JSON + CSV without re-running anything:
  * run header (title, files, tfin, dt, Courant/sediment flags, multipliers),
  * engine warnings (CLEN increment too large, channel rating exceeded),
  * every printed element (PRINT >= 1): contributing area, peak flow (+ time), peak sediment
    discharge, element water/sediment balance, and for PRINT = 2 the hydrograph table
    (time_min, rain_rate, outflow_rate, discharge[, sediment_discharge]),
  * the event volume summary (rainfall, plane/channel infiltration, interception, storage,
    outflow, area, sediment yield by particle class, Courant flag),
  * the tabular element summary (when 'Tabular Summary' = Y),
  * all headline numbers converted to SI (m3/s, m3, mm, ha, t/ha) under "si".

PRINT = 3 writes a separate comma-delimited file per element; its name is UPPER-CASED by the
engine (FILE = chan2.csv -> CHAN2.CSV).  Pass such files with --csv.

Usage
  parse_kineros2_output.py RUN.out --json parsed.json [--hydrograph-dir DIR] [--csv CHAN2.CSV ...]
Exit codes: 0 parsed and the run finished | 3 the output shows an engine failure | 2 bad input
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _k2lib as k2  # noqa: E402


def read_print3_csv(path: Path) -> dict:
    """PRINT=3 file: quoted header row, quoted units row, then numeric rows."""
    with open(path, newline="") as fh:
        rows = list(csv.reader(fh, skipinitialspace=True))   # fields are padded before the quotes
    if len(rows) < 3:
        raise ValueError(f"{path}: fewer than 3 rows")
    head = [h.strip() for h in rows[0]]
    units = [u.strip().strip("()") for u in rows[1]]
    data = [[float(x) for x in r] for r in rows[2:] if r and r[0].strip()]
    return {"file": str(path), "columns": head, "units": units, "n_rows": len(data), "rows": data}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("outfile", help="KINEROS2 .out file")
    ap.add_argument("--json", required=True, help="where to write the parsed JSON")
    ap.add_argument("--hydrograph-dir", help="write one CSV per element hydrograph here")
    ap.add_argument("--csv", action="append", default=[], help="PRINT=3 element CSV file(s) to include")
    a = ap.parse_args(argv)
    p = Path(a.outfile)
    if not p.is_file():
        print(f"INPUT ERROR: {p} not found", file=sys.stderr)
        return 2
    parsed = k2.parse_output(p.read_text(errors="replace"))
    parsed["si"] = k2.to_si(parsed)
    parsed["source"] = str(p.resolve())
    if a.csv:
        parsed["print3_files"] = [read_print3_csv(Path(c)) for c in a.csv]
    if a.hydrograph_dir:
        d = Path(a.hydrograph_dir)
        d.mkdir(parents=True, exist_ok=True)
        for el in parsed["elements"]:
            if el.get("hydrograph"):
                fn = d / f"hydrograph_{el['type'].lower()}_{el['id']}.csv"
                with open(fn, "w", newline="") as fh:
                    w = csv.writer(fh)
                    w.writerow(el["hydrograph_columns"])
                    w.writerows(el["hydrograph"])
    Path(a.json).write_text(json.dumps(parsed, indent=2, default=str))
    es = parsed["event_summary"]
    print(f"{parsed.get('version')}  units={parsed.get('units')}  elements printed={len(parsed['elements'])}  "
          f"tabular rows={len(parsed['tabular_summary'])}")
    for k, v in parsed["si"].items():
        print(f"  {k:34s} {v:.6g}")
    if parsed["errors"]:
        for e in parsed["errors"]:
            print(f"  ENGINE FAILURE: {e}", file=sys.stderr)
        return 3
    if not es:
        print("  no event summary found", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
