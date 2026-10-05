#!/usr/bin/env python3
"""
parse_hydrotrend_output.py

Parses HydroTrend ASCII output files into structured CSV and JSON summaries.

Input files parsed (one row per averaging record: HYDRO.IN line 5 interval
D=daily, M=monthly, S=seasonal, Y=yearly; HydroTrend uses a FIXED 365-day
model year, no Feb 29):
  - {PREFIX}ASCII.Q   — water discharge (m³/s)
  - {PREFIX}ASCII.QS  — suspended sediment (kg/s)
  - {PREFIX}ASCII.QB  — bedload (kg/s)
  - {PREFIX}ASCII.CS  — sediment concentration, one column per grain size (kg/m³);
                        Cs_kgm3 = sum over grain sizes, Cs_g1..Cs_gN per grain size
  - {PREFIX}ASCII.VWD — velocity(m/s), width(m), depth(m)

Output:
  - Combined CSV with date, Q, Qs, Qb, Cs, velocity, width, depth
  - JSON summary with annual statistics
  - Optional: compute NSE, KGE, PBIAS against observed data

Usage:
    python parse_hydrotrend_output.py \\
        --out-dir ./HYDRO_OUTPUT \\
        --prefix HYDRO \\
        --start-year 1908 \\
        --output-csv results.csv \\
        --output-json summary.json

    python parse_hydrotrend_output.py \\
        --out-dir ./HYDRO_OUTPUT \\
        --prefix HYDRO \\
        --start-year 1908 \\
        --observed observed_Q.csv \\
        --obs-date-col date \\
        --obs-value-col discharge_m3s \\
        --output-csv results.csv \\
        --output-json summary.json
"""

import argparse
import csv
import json
import math
import os
import sys
from datetime import datetime, timedelta
from collections import defaultdict

# HydroTrend's fixed 365-day model year (hydrooutput.c: daysiy, recperyear).
_MONTH_DAYS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
_SEASON_START_DOY = [1, 91, 182, 274]          # season ends: day 90, 181, 273, 365
_SEASON_DAYS = [90, 91, 92, 92]
RECORDS_PER_YEAR = {"D": 365, "M": 12, "S": 4, "Y": 1}


# --------------------------------------------------------------------------- #
#  Validation
# --------------------------------------------------------------------------- #
def validate_inputs(args):
    """Validate input arguments and file existence."""
    errors = []

    if not os.path.isdir(args.out_dir):
        errors.append(f"Output directory not found: {args.out_dir}")

    q_file = os.path.join(args.out_dir, f"{args.prefix}ASCII.Q")
    if not os.path.isfile(q_file):
        errors.append(
            f"Discharge file not found: {q_file}. "
            "Check that ASCII output was ON in HYDRO.IN line 2."
        )

    if args.observed and not os.path.isfile(args.observed):
        errors.append(f"Observed data file not found: {args.observed}")

    if errors:
        return {"status": "error", "errors": errors}
    return {"status": "ok"}


def validate_parsed_data(data):
    """Check parsed data for physical plausibility."""
    warnings = []

    if not data:
        warnings.append("No data parsed — output files may be empty")
        return warnings

    q_vals = [d["Q_m3s"] for d in data if d["Q_m3s"] is not None]
    qs_vals = [d["Qs_kgs"] for d in data if d["Qs_kgs"] is not None]

    if q_vals:
        q_min, q_max = min(q_vals), max(q_vals)
        q_mean = sum(q_vals) / len(q_vals)
        if q_min < 0:
            warnings.append(f"Negative discharge found: min Q = {q_min:.3f}")
        if q_max > 1e6:
            warnings.append(
                f"Extremely high discharge: max Q = {q_max:.1f} m³/s "
                "(larger than Amazon)"
            )
        if q_mean == 0:
            warnings.append("Mean discharge is 0 — check input parameters")

    if qs_vals:
        qs_max = max(qs_vals)
        if qs_max > 1e5:
            warnings.append(
                f"Extremely high sediment load: max Qs = {qs_max:.1f} kg/s"
            )

    return warnings


# --------------------------------------------------------------------------- #
#  Parsing
# --------------------------------------------------------------------------- #
def read_hydro_in(in_file):
    """Return (start_year, n_years, interval, n_epochs) from a HYDRO.IN file
    (line 4: number of epochs; line 5: "<start year> <no. of years> <D/M/S/Y>").
    Returns None if the file is missing; raises HydroParseError if malformed."""
    if not os.path.isfile(in_file):
        return None
    try:
        with open(in_file, "r", errors="replace") as f:
            lines = f.readlines()
        n_epochs = int(lines[3].split()[0])
        parts = lines[4].split()
        interval = parts[2][0].upper()
        start, nyears = int(parts[0]), int(parts[1])
    except (IndexError, ValueError) as e:
        raise HydroParseError(f"{in_file}: cannot read lines 4-5 ({e})")
    if interval not in RECORDS_PER_YEAR:
        raise HydroParseError(f"{in_file}: unknown averaging interval {parts[2]!r} (line 5)")
    return start, nyears, interval, n_epochs


def noleap_date(year, doy):
    """(month, day) of day-of-year `doy` (1..365) on the 365-day model calendar."""
    m = 0
    while doy > _MONTH_DAYS[m]:
        doy -= _MONTH_DAYS[m]
        m += 1
    return m + 1, doy


def record_calendar(i, start_year, interval):
    """Model-calendar info for record i: (year, month, day, day_of_year, n_days)."""
    rpy = RECORDS_PER_YEAR[interval]
    year = start_year + i // rpy
    k = i % rpy
    if interval == "D":
        doy, ndays = k + 1, 1
    elif interval == "M":
        doy, ndays = sum(_MONTH_DAYS[:k]) + 1, _MONTH_DAYS[k]
    elif interval == "S":
        doy, ndays = _SEASON_START_DOY[k], _SEASON_DAYS[k]
    else:
        doy, ndays = 1, 365
    month, day = noleap_date(year, doy)
    return year, month, day, doy, ndays


class HydroParseError(ValueError):
    """Output file that this parser cannot read safely."""


def read_multi_column(filepath, n_header=2):
    """Read a HydroTrend ASCII output file -> list of float lists.

    Exactly `n_header` header lines are skipped (HydroTrend writes a name line
    and a dashes line); any other non-numeric line is an error, so a bad row
    can never silently shift the record dates.  Returns None if missing.
    """
    if not os.path.isfile(filepath):
        return None
    rows = []
    with open(filepath, "r") as f:
        for ln, line in enumerate(f, 1):
            if ln <= n_header:
                continue
            parts = line.split()
            if not parts:
                continue
            try:
                rows.append([float(x) for x in parts])
            except ValueError:
                raise HydroParseError(f"{filepath}: line {ln} is not numeric: {line.strip()[:80]!r}")
    return rows


def read_river_column(filepath, name):
    """Single-value-per-record file (Q, QS, QB) -> list of floats.

    More than one column means the run used the multi-outlet option
    (one extra column per outlet), which this parser does not support.
    """
    rows = read_multi_column(filepath)
    if rows is None:
        return None
    if any(len(r) != 1 for r in rows):
        raise HydroParseError(
            f"{filepath}: rows with more than one column (multi-outlet run?); "
            f"{name} parsing supports single-outlet output only")
    return [r[0] for r in rows]


def read_single_column(filepath):
    """Read a single-column ASCII file, returning list of floats."""
    values = []
    if not os.path.isfile(filepath):
        return None

    with open(filepath, "r") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                values.append(float(line))
            except ValueError:
                continue
    return values


def read_vwd_file(filepath):
    """Read velocity-width-depth file (three columns per line)."""
    velocities, widths, depths = [], [], []
    if not os.path.isfile(filepath):
        return None, None, None

    with open(filepath, "r") as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) >= 3:
                try:
                    velocities.append(float(parts[0]))
                    widths.append(float(parts[1]))
                    depths.append(float(parts[2]))
                except ValueError:
                    continue
    return velocities, widths, depths


def parse_all_outputs(out_dir, prefix, start_year, interval="D", cs_grain_columns=False):
    """Parse all HydroTrend ASCII output files into a combined dataset.

    interval: averaging interval of the run (HYDRO.IN line 5): D, M, S or Y.
    Dates follow HydroTrend's 365-day model year (no Feb 29); for M/S/Y the
    date is the first day of the record.  Cs_kgm3 is the sum of the per-grain
    concentrations; cs_grain_columns=True also adds Cs_g1..Cs_gN.
    Raises HydroParseError for malformed or multi-outlet output, or files
    whose record counts disagree.
    """
    interval = (interval or "D").upper()[0]
    q_vals = read_river_column(os.path.join(out_dir, f"{prefix}ASCII.Q"), "Q")
    qs_vals = read_river_column(os.path.join(out_dir, f"{prefix}ASCII.QS"), "Qs")
    qb_vals = read_river_column(os.path.join(out_dir, f"{prefix}ASCII.QB"), "Qb")
    # One column per grain size: Cs_kgm3 = total (sum), Cs_g<k> per size.
    cs_rows = read_multi_column(
        os.path.join(out_dir, f"{prefix}ASCII.CS")
    )
    vwd_rows = read_multi_column(os.path.join(out_dir, f"{prefix}ASCII.VWD"))
    if vwd_rows is not None and any(len(r) != 3 for r in vwd_rows):
        raise HydroParseError(f"{prefix}ASCII.VWD: rows without exactly 3 columns "
                              "(multi-outlet run?)")
    vel = [r[0] for r in vwd_rows] if vwd_rows is not None else None
    wid = [r[1] for r in vwd_rows] if vwd_rows is not None else None
    dep = [r[2] for r in vwd_rows] if vwd_rows is not None else None

    if q_vals is None:
        return []
    for name, vals in (("QS", qs_vals), ("QB", qb_vals), ("CS", cs_rows), ("VWD", vwd_rows)):
        if vals is not None and len(vals) != len(q_vals):
            raise HydroParseError(f"{prefix}ASCII.{name} has {len(vals)} records, "
                                  f"{prefix}ASCII.Q has {len(q_vals)}")
    if cs_rows and len({len(r) for r in cs_rows}) != 1:
        raise HydroParseError(f"{prefix}ASCII.CS: rows with different numbers of columns")

    n_records = len(q_vals)
    n_grain = len(cs_rows[0]) if (cs_rows and cs_grain_columns) else 0

    data = []
    for i in range(n_records):
        year, month, day, doy, ndays = record_calendar(i, start_year, interval)
        cs = cs_rows[i] if cs_rows and i < len(cs_rows) else None
        record = {
            "date": f"{year:04d}-{month:02d}-{day:02d}",
            "year": year,
            "month": month,
            "day_of_year": doy,
            "Q_m3s": q_vals[i] if i < len(q_vals) else None,
            "Qs_kgs": qs_vals[i] if qs_vals and i < len(qs_vals) else None,
            "Qb_kgs": qb_vals[i] if qb_vals and i < len(qb_vals) else None,
            "Cs_kgm3": sum(cs) if cs else None,
            "velocity_ms": vel[i] if vel and i < len(vel) else None,
            "width_m": wid[i] if wid and i < len(wid) else None,
            "depth_m": dep[i] if dep and i < len(dep) else None,
        }
        for g in range(n_grain):
            record[f"Cs_g{g + 1}"] = cs[g] if cs and g < len(cs) else None
        record["_n_days"] = ndays
        data.append(record)

    return data


def compute_annual_stats(data):
    """Compute annual statistics (records of any averaging interval).

    Means are unweighted means of the records; annual volume/mass weight each
    record by the number of model days it covers."""
    yearly = defaultdict(lambda: {"Q": [], "Qs": [], "Qb": [], "Cs": [],
                                  "Qvol": 0.0, "Qsmass": 0.0})

    for d in data:
        yr = d["year"]
        nd = d.get("_n_days", 1)   # days represented by this record
        if d["Q_m3s"] is not None:
            yearly[yr]["Q"].append(d["Q_m3s"])
            yearly[yr]["Qvol"] += d["Q_m3s"] * nd * 86400
        if d["Qs_kgs"] is not None:
            yearly[yr]["Qs"].append(d["Qs_kgs"])
            yearly[yr]["Qsmass"] += d["Qs_kgs"] * nd * 86400
        if d["Qb_kgs"] is not None:
            yearly[yr]["Qb"].append(d["Qb_kgs"])
        if d["Cs_kgm3"] is not None:
            yearly[yr]["Cs"].append(d["Cs_kgm3"])

    annual = []
    for yr in sorted(yearly.keys()):
        y = yearly[yr]
        stats = {"year": yr}
        if y["Q"]:
            stats["Q_mean_m3s"] = round(sum(y["Q"]) / len(y["Q"]), 3)
            stats["Q_max_m3s"] = round(max(y["Q"]), 3)
            stats["Q_min_m3s"] = round(min(y["Q"]), 3)
            # Annual volume in km³
            stats["Q_annual_km3"] = round(y["Qvol"] / 1e9, 4)
        if y["Qs"]:
            stats["Qs_mean_kgs"] = round(sum(y["Qs"]) / len(y["Qs"]), 3)
            # Annual sediment in Mt
            stats["Qs_annual_Mt"] = round(y["Qsmass"] / 1e9, 6)
        if y["Qb"]:
            stats["Qb_mean_kgs"] = round(sum(y["Qb"]) / len(y["Qb"]), 3)
        if y["Cs"]:
            stats["Cs_mean_kgm3"] = round(sum(y["Cs"]) / len(y["Cs"]), 4)

        annual.append(stats)

    return annual


# --------------------------------------------------------------------------- #
#  Metrics
# --------------------------------------------------------------------------- #
def compute_nse(obs, sim):
    """Nash-Sutcliffe Efficiency."""
    if len(obs) != len(sim) or len(obs) == 0:
        return None
    obs_mean = sum(obs) / len(obs)
    numerator = sum((o - s) ** 2 for o, s in zip(obs, sim))
    denominator = sum((o - obs_mean) ** 2 for o in obs)
    if denominator == 0:
        return None
    return round(1 - numerator / denominator, 4)


def compute_kge(obs, sim):
    """Kling-Gupta Efficiency."""
    if len(obs) != len(sim) or len(obs) < 2:
        return None
    n = len(obs)
    obs_mean = sum(obs) / n
    sim_mean = sum(sim) / n
    obs_std = math.sqrt(sum((o - obs_mean) ** 2 for o in obs) / (n - 1))
    sim_std = math.sqrt(sum((s - sim_mean) ** 2 for s in sim) / (n - 1))

    if obs_std == 0 or obs_mean == 0:
        return None

    # Correlation
    cov = sum((o - obs_mean) * (s - sim_mean) for o, s in zip(obs, sim))
    r = cov / ((n - 1) * obs_std * sim_std) if obs_std * sim_std > 0 else 0

    alpha = sim_std / obs_std
    beta = sim_mean / obs_mean

    kge = 1 - math.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2)
    return round(kge, 4)


def compute_pbias(obs, sim):
    """Percent Bias."""
    if len(obs) != len(sim) or len(obs) == 0:
        return None
    obs_sum = sum(obs)
    if obs_sum == 0:
        return None
    pbias = 100 * sum(s - o for o, s in zip(obs, sim)) / obs_sum
    return round(pbias, 2)


# --------------------------------------------------------------------------- #
#  Main
# --------------------------------------------------------------------------- #
def main():
    parser = argparse.ArgumentParser(
        description="Parse HydroTrend output files"
    )
    parser.add_argument("--out-dir", required=True,
                        help="HydroTrend output directory")
    parser.add_argument("--prefix", default="HYDRO",
                        help="File prefix")
    parser.add_argument("--start-year", type=int, required=True,
                        help="Simulation start year")
    parser.add_argument("--interval", default="auto",
                        choices=["auto", "D", "M", "S", "Y", "d", "m", "s", "y"],
                        help="Averaging interval of the run (HYDRO.IN line 5). auto: read "
                             "it from --in-file, else <out-dir>/<prefix>.IN; if not found, "
                             "assume D (daily) with a warning")
    parser.add_argument("--in-file", default=None,
                        help="Path to the run's <prefix>.IN (for --interval auto); must exist "
                             "if given")
    parser.add_argument("--cs-grain-columns", action="store_true",
                        help="Also write one Cs_g<k> column per grain size to the CSV "
                             "(Cs_kgm3 is always the sum over grain sizes)")
    parser.add_argument("--output-csv", default=None,
                        help="Output CSV file path")
    parser.add_argument("--output-json", default=None,
                        help="Output JSON summary path")
    parser.add_argument("--observed", default=None,
                        help="Observed data CSV for validation (matched on the date "
                             "column; for M/S/Y runs the record date is the first day "
                             "of the month/season/year)")
    parser.add_argument("--obs-date-col", default="date",
                        help="Date column in observed CSV")
    parser.add_argument("--obs-value-col", default="discharge_m3s",
                        help="Value column in observed CSV")
    args = parser.parse_args()

    # Step 1: Validate
    check = validate_inputs(args)
    if check["status"] == "error":
        print(json.dumps(check, indent=2))
        sys.exit(1)

    # Step 2: Parse (averaging interval from HYDRO.IN line 5)
    interval = args.interval.upper()
    info = None
    try:
        in_file = args.in_file or os.path.join(args.out_dir, f"{args.prefix}.IN")
        if args.in_file and not os.path.isfile(args.in_file):
            raise HydroParseError(f"--in-file not found: {args.in_file}")
        if interval == "AUTO" or args.in_file:
            info = read_hydro_in(in_file)
        if interval == "AUTO":
            if info is None:
                interval = "D"
                print(f"WARNING: {in_file} not found; cannot read the averaging interval; "
                      "assuming daily (D). Pass --interval or --in-file.", file=sys.stderr)
            else:
                interval = info[2]
        if info is not None and info[0] != args.start_year:
            print(f"WARNING: --start-year {args.start_year} differs from "
                  f"{in_file} start year {info[0]}; using --start-year.", file=sys.stderr)
        data = parse_all_outputs(args.out_dir, args.prefix, args.start_year, interval,
                                 cs_grain_columns=args.cs_grain_columns)
        if not data:
            raise HydroParseError(f"{args.prefix}ASCII.Q in {args.out_dir} has no data records")
        if info is not None and info[3] == 1:
            expect = info[1] * RECORDS_PER_YEAR[interval]
            if len(data) != expect:
                raise HydroParseError(
                    f"{len(data)} records but {in_file} line 5 gives {info[1]} years x "
                    f"{RECORDS_PER_YEAR[interval]} records/year = {expect}")
    except HydroParseError as e:
        print(json.dumps({"status": "error", "errors": [str(e)]}, indent=2))
        sys.exit(1)

    # Step 3: Validate parsed data
    warnings = validate_parsed_data(data)
    if warnings:
        for w in warnings:
            print(f"WARNING: {w}", file=sys.stderr)

    # Step 4: Write CSV
    if args.output_csv and data:
        fieldnames = [k for k in data[0].keys() if not k.startswith("_")]
        with open(args.output_csv, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(data)

    # Step 5: Compute statistics
    annual = compute_annual_stats(data)

    # Step 6: Compute metrics against observed if provided
    metrics = {}
    if args.observed and os.path.isfile(args.observed):
        obs_data = {}
        with open(args.observed, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                obs_data[row[args.obs_date_col]] = float(
                    row[args.obs_value_col]
                )

        sim_dict = {d["date"]: d["Q_m3s"] for d in data if d["Q_m3s"]}
        common_dates = sorted(set(obs_data.keys()) & set(sim_dict.keys()))
        if common_dates:
            obs = [obs_data[d] for d in common_dates]
            sim = [sim_dict[d] for d in common_dates]
            metrics = {
                "n_common_days": len(common_dates),
                "NSE": compute_nse(obs, sim),
                "KGE": compute_kge(obs, sim),
                "PBIAS": compute_pbias(obs, sim),
            }

    # Step 7: Write JSON summary
    q_vals = [d["Q_m3s"] for d in data if d["Q_m3s"] is not None]
    summary = {
        "status": "success",
        "n_days": sum(d.get("_n_days", 1) for d in data),
        "n_records": len(data),
        "interval": interval,
        "n_years": len(annual),
        "discharge_stats": {
            "mean_m3s": round(sum(q_vals) / len(q_vals), 3) if q_vals else 0,
            "max_m3s": round(max(q_vals), 3) if q_vals else 0,
            "min_m3s": round(min(q_vals), 3) if q_vals else 0,
        },
        "annual_summaries": annual[:5],  # First 5 years
        "metrics": metrics,
        "warnings": warnings,
        "output_csv": args.output_csv,
    }

    if args.output_json:
        with open(args.output_json, "w") as f:
            json.dump(summary, f, indent=2)

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
