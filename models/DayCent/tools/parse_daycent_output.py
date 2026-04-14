#!/usr/bin/env python3
"""
parse_daycent_output.py — Parse DayCent .lis / summary.out / harvest.csv output
into a tidy CSV and (optionally) compute metrics against an observed series.

A `.lis` file produced by DDlist100 has a 2-line header:
    Line 1: source binary file name
    Line 2: column names (whitespace-delimited)
    Line 3+: data rows (whitespace-delimited, with quoted crop labels)

`summary.out` and `year_summary.out` are similar with their own header rows.

Usage:
    python parse_daycent_output.py --lis wooster.lis --out wooster_tidy.csv
    python parse_daycent_output.py --lis wooster.lis --var somsc \\
        --observed obs_soc.csv --metrics-out metrics.json
"""
import argparse
import csv
import json
import math
import sys
from pathlib import Path


def detect_format(path: Path):
    """Return one of {'lis', 'summary_out', 'harvest_csv', 'unknown'}."""
    name = path.name.lower()
    if name.endswith(".csv"):
        return "harvest_csv"
    if name.endswith(".lis"):
        return "lis"
    if name.endswith(".out"):
        return "summary_out"
    return "unknown"


def _to_float_or_nan(tok):
    try:
        return float(tok)
    except ValueError:
        return float("nan")


def parse_lis(path: Path):
    """Parse a DDlist100 .lis file. Returns (columns, rows[list[float]])."""
    with open(path) as f:
        lines = [ln.rstrip() for ln in f.readlines()]
    if len(lines) < 3:
        raise RuntimeError(f"{path}: too few lines for .lis format")

    cols = lines[1].split()
    rows = []
    for ln in lines[2:]:
        parts = ln.split()
        if not parts:
            continue
        row = [_to_float_or_nan(tok) for tok in parts]
        # If the first (time) column failed to parse, this is a header/blank
        # repeat; drop it.
        if math.isnan(row[0]):
            continue
        rows.append(row)
    return cols, rows


def parse_summary_out(path: Path):
    """Parse DayCent summary.out (whitespace-delimited with header)."""
    with open(path) as f:
        first = f.readline().split()
        rows = []
        for ln in f:
            parts = ln.split()
            if not parts:
                continue
            row = [_to_float_or_nan(tok) for tok in parts]
            if math.isnan(row[0]):
                continue
            rows.append(row)
    return first, rows


def parse_harvest_csv(path: Path):
    """harvest.csv from DayCent is comma-delimited, with header row."""
    with open(path) as f:
        reader = csv.reader(f)
        header = next(reader)
        rows = []
        for r in reader:
            row = [_to_float_or_nan(x) if x.strip() else float("nan") for x in r]
            rows.append(row)
    return header, rows


def write_tidy_csv(cols, rows, out_path: Path):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in rows:
            w.writerow(r)
    print(f"Wrote {out_path} ({len(rows)} rows, {len(cols)} cols)")


def compute_metrics(sim, obs):
    """Pearson r, RMSE, bias, NSE between matching pairs."""
    n = min(len(sim), len(obs))
    if n == 0:
        return {"n": 0}
    sim = [float(x) for x in sim[:n]]
    obs = [float(x) for x in obs[:n]]
    mean_o = sum(obs) / n
    mean_s = sum(sim) / n
    cov = sum((s - mean_s) * (o - mean_o) for s, o in zip(sim, obs))
    var_s = sum((s - mean_s) ** 2 for s in sim)
    var_o = sum((o - mean_o) ** 2 for o in obs)
    if var_s == 0 or var_o == 0:
        r = float("nan")
    else:
        r = cov / math.sqrt(var_s * var_o)
    rmse = math.sqrt(sum((s - o) ** 2 for s, o in zip(sim, obs)) / n)
    bias = mean_s - mean_o
    if var_o == 0:
        nse = float("nan")
    else:
        nse = 1.0 - sum((s - o) ** 2 for s, o in zip(sim, obs)) / var_o
    return {"n": n, "pearson_r": r, "rmse": rmse, "bias": bias, "nse": nse,
            "mean_obs": mean_o, "mean_sim": mean_s}


def validate_outputs(cols, rows):
    if not rows:
        raise RuntimeError("no data rows parsed")
    if not cols:
        raise RuntimeError("no columns parsed")
    print(f"  parsed: {len(rows)} rows x {len(cols)} cols")
    print(f"  cols  : {cols[:8]}{'...' if len(cols) > 8 else ''}")


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--lis", type=Path, help="path to .lis / .out / .csv to parse")
    p.add_argument("--out", type=Path, help="tidy CSV output path")
    p.add_argument("--var", help="variable name to extract for metric computation")
    p.add_argument("--time-var", default="time", help="time column name in .lis")
    p.add_argument("--observed", type=Path,
                   help="observed CSV with columns: time,value")
    p.add_argument("--metrics-out", type=Path,
                   help="write metrics JSON to this path")
    args = p.parse_args(argv)

    if not args.lis or not args.lis.is_file():
        print("FATAL: --lis path missing or does not exist", file=sys.stderr)
        return 2

    fmt = detect_format(args.lis)
    if fmt == "lis":
        cols, rows = parse_lis(args.lis)
    elif fmt == "summary_out":
        cols, rows = parse_summary_out(args.lis)
    elif fmt == "harvest_csv":
        cols, rows = parse_harvest_csv(args.lis)
    else:
        print(f"FATAL: unknown format for {args.lis}", file=sys.stderr)
        return 2

    validate_outputs(cols, rows)

    if args.out:
        write_tidy_csv(cols, rows, args.out)

    if args.var and args.observed:
        if args.var not in cols:
            print(f"FATAL: var '{args.var}' not in columns {cols}", file=sys.stderr)
            return 2
        if args.time_var not in cols:
            print(f"FATAL: time var '{args.time_var}' not in columns {cols}", file=sys.stderr)
            return 2
        var_idx = cols.index(args.var)
        time_idx = cols.index(args.time_var)
        # If multiple rows have the same time stamp (multi-event years),
        # take the LAST (end-of-year state).
        sim_by_time = {}
        for row in rows:
            t = row[time_idx]
            v = row[var_idx]
            if not math.isnan(t) and not math.isnan(v):
                sim_by_time[t] = v

        obs_pairs = []
        with open(args.observed) as f:
            reader = csv.DictReader(f)
            for r in reader:
                t = float(r["time"])
                v = float(r["value"])
                obs_pairs.append((t, v))

        sim, obs = [], []
        for t, v in obs_pairs:
            if t in sim_by_time:
                sim.append(sim_by_time[t])
                obs.append(v)
            else:
                near = min(sim_by_time.keys(), key=lambda x: abs(x - t))
                if abs(near - t) <= 1.0:
                    sim.append(sim_by_time[near])
                    obs.append(v)

        metrics = compute_metrics(sim, obs)
        print(f"  metrics: {metrics}")
        if args.metrics_out:
            args.metrics_out.parent.mkdir(parents=True, exist_ok=True)
            with open(args.metrics_out, "w") as f:
                json.dump({"variable": args.var,
                           "observed": obs,
                           "simulated": sim,
                           **metrics}, f, indent=2)
            print(f"  wrote {args.metrics_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
