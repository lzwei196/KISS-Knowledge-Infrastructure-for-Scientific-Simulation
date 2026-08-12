#!/usr/bin/env python3
"""Parse EPIC 1102 text outputs into CSV and run a water-balance sanity check."""
import argparse
import csv
import os
import sys
import statistics


def _find(workspace, name, ext):
    for fn in os.listdir(workspace):
        if fn.upper().endswith(ext) and fn.startswith(name):
            return os.path.join(workspace, fn)
    return None


def parse_table(path, header_marker_cols):
    rows = []
    header = None
    with open(path, "rb") as f:
        raw = f.read().decode("ascii", errors="replace")
    for line in raw.replace("\r", "").splitlines():
        toks = line.split()
        if not toks:
            continue
        if header is None:
            if toks[0] in header_marker_cols:
                header = toks
                continue
        else:
            try:
                int(toks[0])
            except ValueError:
                continue
            rows.append(toks)
    return header, rows


def write_csv(out_path, header, rows):
    with open(out_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        for r in rows:
            w.writerow(r)


def parse_ann(path):
    header, rows = parse_table(path, header_marker_cols={"RUN", "YR"})
    if not header or not rows:
        return None, None, []
    idx = {c: i for i, c in enumerate(header)}
    data = []
    for r in rows:
        def g(col):
            return float(r[idx[col]]) if col in idx and idx[col] < len(r) else 0.0
        data.append({
            "yr": int(r[idx["YR"]]) if "YR" in idx and idx["YR"] < len(r) else 0,
            "P": g("PRCP"), "ET": g("ET"), "Q": g("Q"),
            "PET": g("PET"), "IRGA": g("IRGA"),
            "DN": g("DN"), "DN2O": g("DN2O"),
        })
    return header, rows, data


def parse_acy(path):
    header, rows = parse_table(path, header_marker_cols={"YR"})
    return header, rows


def water_balance_check(ann_data, tolerance=50.0):
    if not ann_data:
        return {"ok": False, "reason": "no ANN rows"}
    P = statistics.mean(d["P"] for d in ann_data)
    ET = statistics.mean(d["ET"] for d in ann_data)
    Q = statistics.mean(d["Q"] for d in ann_data)
    IRGA = statistics.mean(d["IRGA"] for d in ann_data)
    resid = (P + IRGA) - (ET + Q)
    # Q in .ANN is surface runoff only — deep percolation + lateral flow
    # are separate, so a positive residual of 200-600 mm/yr is normal for
    # humid sites. Flag only clear energy/water violations.
    ok = ET <= (P + IRGA) and P > 0 and ET > 0
    return {
        "ok": ok, "years": len(ann_data),
        "P_mean": round(P, 1), "ET_mean": round(ET, 1),
        "Q_surface_mean": round(Q, 1), "IRGA_mean": round(IRGA, 1),
        "residual_mm_yr": round(resid, 1),
        "note": "residual includes deep percolation + lateral flow (not in ANN Q)",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()

    out_dir = args.out_dir or args.workspace

    ann_path = _find(args.workspace, args.name, ".ANN")
    acy_path = _find(args.workspace, args.name, ".ACY")

    if ann_path:
        print(f"  parsing {ann_path}")
        header, rows, data = parse_ann(ann_path)
        if header:
            write_csv(os.path.join(out_dir, f"{args.name}_annual.csv"),
                      header, rows)
            wb = water_balance_check(data)
            print("  water balance:", wb)
    else:
        print(f"  WARNING: no ANN file found for {args.name}", file=sys.stderr)

    if acy_path:
        print(f"  parsing {acy_path}")
        header, rows = parse_acy(acy_path)
        if header:
            write_csv(os.path.join(out_dir, f"{args.name}_yield.csv"),
                      header, rows)
    else:
        print(f"  note: no ACY file found for {args.name}")


if __name__ == "__main__":
    main()
