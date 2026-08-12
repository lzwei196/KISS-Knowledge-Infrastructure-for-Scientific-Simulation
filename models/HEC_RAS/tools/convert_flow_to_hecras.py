#!/usr/bin/env python3
"""
convert_flow_to_hecras.py -- Set the steady discharges (one per profile) that
the HEC-RAS solver reads, by editing the 'Section - Flow Data' block of an
existing run file (.rNN). Copy-first: we replace the numeric field in place,
preserving Fortran column width -- we never regenerate the run file.

HEC-RAS is a HYDRAULICS model: its "forcing" is DISCHARGE, not meteorology.
This is the Layer-1 (ki_tools_common) tie-in for HEC-RAS:

  * discharges may be passed directly (--flows 500,1000)         [cfs or m3/s]
  * or read from an ObservedQ CSV (--observedq file --quantiles 0.5,0.9,0.99)
    -- annual-peak quantiles become design profiles.

Units: HEC-RAS English projects expect cfs; SI projects expect m3/s. Pass
--in-units m3/s to convert to cfs via ki_tools_common.units.convert
(factor 35.3147). We do NOT call load_daily_forcing -- precip/temp are not
HEC-RAS inputs (see docs/input_preparation.md).

Usage:
  python3 convert_flow_to_hecras.py --run MIXED.r01 --out MIXED.r01 --flows 800,1500
  python3 convert_flow_to_hecras.py --run MIXED.r01 --out new.r01 \
        --observedq /path/Q.csv --quantiles 0.5,0.9,0.99 --in-units m3/s
"""
import argparse
import json
import os
import re
import shutil
import sys


def _to_cfs(flows, in_units):
    if in_units in ("cfs", "ft3/s", "english"):
        return [float(q) for q in flows]
    # SI -> English
    try:
        from ki_tools_common.units import convert
        return [float(convert(float(q), "m3/s", "ft3/s")) for q in flows]
    except Exception:  # noqa  -- fall back to the exact factor
        return [float(q) * 35.3146667 for q in flows]


def _quantile(sorted_vals, p):
    if not sorted_vals:
        return 0.0
    k = (len(sorted_vals) - 1) * p
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return sorted_vals[f]
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def flows_from_observedq(csv_path, quantiles):
    """Annual-peak quantiles from an ObservedQ table (date,Q or columns w/ 'flow').

    See data_ki/ObservedQ/SKILL.md. Returns one design discharge per quantile,
    in the table's native units (caller declares them via --in-units).

    Robust to the Huai-gauge format used across the platform's primary Chinese
    discharge stations (bengbu_51080 / wangjiaba_51030 / xixian_51012 / nuxia):
    TAB-separated with header ``stcd  dates  z  Q  name`` and a GBK-encoded
    ``name`` column. We therefore (a) sniff the delimiter (tab vs comma),
    (b) read latin-1 so non-UTF-8 station-name bytes never crash the parse, and
    (c) match the date column on a ``date``-prefix (so ``dates`` is found, not
    silently defaulted to ``stcd`` -- which would collapse every record into one
    pseudo-year and make all quantiles equal the global max).
    """
    import csv as _csv
    from collections import defaultdict
    peaks = defaultdict(float)
    # latin-1 never raises on arbitrary bytes; the date/Q columns are pure ASCII.
    with open(csv_path, encoding="latin-1") as fh:
        sample = fh.readline()
        fh.seek(0)
        delim = "\t" if ("\t" in sample and sample.count("\t") >= sample.count(",")) else ","
        rdr = _csv.reader(fh, delimiter=delim)
        header = next(rdr)
        hl = [h.strip().lower() for h in header]
        # date column: exact match OR a 'date'-prefix ('dates' -> col 1)
        dcol = next((i for i, h in enumerate(hl)
                     if h in ("date", "datetime", "time") or h.startswith("date")), 0)
        # flow column: prefer an exact name, else fall back to a substring match
        qcol = next((i for i, h in enumerate(hl)
                     if h in ("q", "flow", "discharge", "flow_m3s", "discharge_m3s")),
                    None)
        if qcol is None:
            qcol = next((i for i, h in enumerate(hl)
                         if any(k in h for k in ("flow", "discharge"))),
                        len(header) - 1)
        for row in rdr:
            if len(row) <= max(dcol, qcol):
                continue
            try:
                q = float(row[qcol])
            except ValueError:
                continue
            yr = row[dcol][:4]
            if q > peaks[yr]:
                peaks[yr] = q
    annual_peaks = sorted(peaks.values())
    return [round(_quantile(annual_peaks, p), 2) for p in quantiles]


def set_flows(run_path, out_path, flows_cfs):
    """Replace discharges in the run file's 'Section - Flow Data' block.

    Each profile is two lines:  '<...>PF n'  then  '<Q>   <count>'.
    We rewrite the first numeric field of each value line, right-justified to its
    original width to keep the Fortran reader happy.
    """
    if out_path != run_path:
        shutil.copy2(run_path, out_path)
    with open(out_path) as fh:
        lines = fh.readlines()

    # find the Flow Data section
    start = next((i for i, l in enumerate(lines)
                  if l.strip() == "Section - Flow Data"), None)
    if start is None:
        raise ValueError("no 'Section - Flow Data' block in run file; "
                         "see triplets.yaml 'no_flow_data_section'")
    end = next((i for i in range(start + 1, len(lines))
                if lines[i].startswith("Section - ")), len(lines))

    n_set = 0
    qi = 0
    i = start + 1
    while i < end and qi < len(flows_cfs):
        # a profile header line contains 'PF'
        if "PF" in lines[i]:
            val_line = lines[i + 1]
            m = re.match(r"^(\s*)(\d+(?:\.\d+)?)(.*)$", val_line)
            if m:
                lead, num, rest = m.groups()
                width = len(lead) + len(num)
                newnum = ("%g" % flows_cfs[qi])
                field = newnum.rjust(width)
                lines[i + 1] = field + rest if rest.startswith((" ", "\t")) \
                    else field + " " + rest
                if not lines[i + 1].endswith("\n"):
                    lines[i + 1] += "\n"
                n_set += 1
                qi += 1
            i += 2
        else:
            i += 1

    with open(out_path, "w") as fh:
        fh.writelines(lines)
    return {"profiles_set": n_set, "flows_cfs": flows_cfs, "out": out_path}


def validate_outputs(result):
    flows = result.get("flows_cfs", [])
    if not flows:
        return False, "no flows written"
    if any(q <= 0 for q in flows):
        return False, "non-positive discharge"
    if any(q > 5_000_000 for q in flows):
        return False, "implausibly large discharge (>5e6 cfs) -- unit error?"
    return True, f"set {result['profiles_set']} profile flow(s): {flows} cfs"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True, help="input run file (.rNN)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--flows", default=None, help="comma list of discharges")
    ap.add_argument("--observedq", default=None, help="ObservedQ CSV path")
    ap.add_argument("--quantiles", default="0.5,0.9,0.99")
    ap.add_argument("--in-units", default="cfs", choices=["cfs", "ft3/s", "m3/s"])
    a = ap.parse_args()

    if a.flows:
        flows = a.flows.split(",")
    elif a.observedq:
        qs = [float(x) for x in a.quantiles.split(",")]
        flows = flows_from_observedq(a.observedq, qs)
    else:
        ap.error("provide --flows or --observedq")

    flows_cfs = _to_cfs(flows, a.in_units)
    res = set_flows(a.run, a.out, flows_cfs)
    ok, msg = validate_outputs(res)
    res["validation"] = {"ok": ok, "detail": msg}
    print(json.dumps(res, indent=2))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
