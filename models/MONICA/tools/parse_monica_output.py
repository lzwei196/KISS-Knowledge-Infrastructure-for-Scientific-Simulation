#!/usr/bin/env python3
"""
parse_monica_output.py — Parse MONICA output CSV into clean timeseries and metrics

Handles the multi-header-row MONICA output format and extracts:
  - Clean daily/monthly/yearly timeseries CSV
  - Summary statistics (yield, total ET, N leaching, etc.)
  - Domain-appropriate metrics vs. observed data (RMSE, R², PBIAS, d-index)

Usage:
    python parse_monica_output.py --input out.csv --output-dir ./parsed/

    python parse_monica_output.py --input out.csv --output-dir ./parsed/ \
        --observed obs_yield.csv --obs-col Yield_kgha --sim-col Yield \
        --metric rmse r2 pbias
"""

import argparse
import csv
import json
import math
import os
import sys
from datetime import datetime


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def compute_rmse(obs, sim):
    """Root Mean Square Error."""
    n = len(obs)
    if n == 0:
        return float("nan")
    return math.sqrt(sum((o - s) ** 2 for o, s in zip(obs, sim)) / n)


def compute_r2(obs, sim):
    """Coefficient of determination (R²)."""
    n = len(obs)
    if n < 2:
        return float("nan")
    mean_o = sum(obs) / n
    ss_res = sum((o - s) ** 2 for o, s in zip(obs, sim))
    ss_tot = sum((o - mean_o) ** 2 for o in obs)
    if ss_tot == 0:
        return float("nan")
    return 1.0 - ss_res / ss_tot


def compute_pbias(obs, sim):
    """Percent bias (%)."""
    sum_obs = sum(obs)
    if sum_obs == 0:
        return float("nan")
    return 100.0 * sum(s - o for o, s in zip(obs, sim)) / sum_obs


def compute_nse(obs, sim):
    """Nash-Sutcliffe Efficiency."""
    n = len(obs)
    if n < 2:
        return float("nan")
    mean_o = sum(obs) / n
    ss_res = sum((o - s) ** 2 for o, s in zip(obs, sim))
    ss_tot = sum((o - mean_o) ** 2 for o in obs)
    if ss_tot == 0:
        return float("nan")
    return 1.0 - ss_res / ss_tot


def compute_d_index(obs, sim):
    """Willmott's index of agreement (d)."""
    n = len(obs)
    if n == 0:
        return float("nan")
    mean_o = sum(obs) / n
    num = sum((o - s) ** 2 for o, s in zip(obs, sim))
    den = sum((abs(s - mean_o) + abs(o - mean_o)) ** 2 for o, s in zip(obs, sim))
    if den == 0:
        return float("nan")
    return 1.0 - num / den


METRIC_FUNCS = {
    "rmse": compute_rmse,
    "r2": compute_r2,
    "pbias": compute_pbias,
    "nse": compute_nse,
    "d": compute_d_index,
}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_inputs(args):
    """Validate command-line arguments."""
    errors = []
    if not os.path.isfile(args.input):
        errors.append(f"Input file not found: {args.input}")
    if args.observed and not os.path.isfile(args.observed):
        errors.append(f"Observed data file not found: {args.observed}")
    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)


def validate_outputs(parsed_data, output_dir):
    """Validate parsed output data."""
    warnings = []
    if not parsed_data:
        warnings.append("No data rows parsed from output file")
        return warnings

    n_rows = len(parsed_data)
    warnings.append(f"Parsed {n_rows} data rows")

    # Check for common issues
    if "Yield" in parsed_data[0]:
        yields = [float(r["Yield"]) for r in parsed_data
                  if r.get("Yield") and r["Yield"] != ""]
        if yields:
            max_yield = max(yields)
            if max_yield > 50000:
                warnings.append(f"Max yield = {max_yield:.0f} kg ha⁻¹ — suspiciously high, "
                                "check radiation units")
            elif max_yield == 0:
                warnings.append("All yields are 0 — check if crop rotation was configured")

    return warnings


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

TAB = chr(9)
_SEPS = (";", ",", TAB)


def _detect_sep(line):
    """Separator of ONE block's header line (MONICA blocks may differ)."""
    if ";" in line:
        return ";"
    if TAB in line:
        return TAB
    return ","


def _is_section_label(line):
    """True only for MONICA's bare section-label line.

    monica-run writes every output event block under
        '"' + origSpec-with-inner-quotes-removed + '"'
    (src/run/monica-run-main.cpp:300/333/390), i.e. the label line is exactly
    ONE double-quoted token ("crop", "daily", "xxxx-03-31", "while|Stage|4")
    with no separator and no inner quote. The quotes are REQUIRED: an
    unquoted one-cell line - the `Precip` header of a "run" block, a legacy
    file's single-column header such as `Yield`, or a one-column data value -
    is never a label.
    """
    s = line.strip()
    if len(s) < 3 or s[0] != '"' or s[-1] != '"':
        return False
    inner = s[1:-1]
    if not inner or '"' in inner or any(c in inner for c in _SEPS):
        return False
    return True


def parse_monica_output(input_path):
    """
    Parse MONICA's multi-section, multi-header CSV output.

    A MONICA out.csv holds one block per output event ("crop", "daily",
    "yearly", ...). Each block is:
      Row 0: quoted section label, e.g. "crop"  (absent only in very old files)
      Row 1: column names (e.g., CM-count, Crop, Yield / Date, Mois/1 ...)
      Row 2: units (e.g., [kgDM ha-1], [mm]) - optional
      Row 3: aggregation metadata or JSON refs (m:/j:/c:) - optional
      Row 4+: data rows, ended by a blank line or the next section label
    Blocks have DIFFERENT headers and may use different separators, so the
    separator and header are detected per block, never from line 0 (which
    for an event file is the bare label "crop" - treating that as the header
    silently parsed zero usable rows; triplet dt_27).

    Returns (header_names, header_units, data).
      * ONE block (labelled or legacy label-less): header_names/header_units
        are exactly that block's columns/units and each row dict holds exactly
        those columns - no synthetic key is added (back-compatible).
      * MORE than one block: header_names is the union of all blocks' columns
        (first-seen order) preceded by a synthetic "section" column,
        header_units is aligned to it, and every row dict additionally carries
        its block label under "section".
    """
    # MONICA writes units like [degC d] in the platform's 8-bit encoding; never
    # let a non-UTF-8 byte abort the parse of an otherwise valid file.
    with open(input_path, "r", newline="", encoding="utf-8", errors="replace") as f:
        lines = f.read().splitlines()

    sections = []
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if _is_section_label(line):
            name = line.strip()[1:-1]
            i += 1
            while i < n and not lines[i].strip():
                i += 1
            if i >= n:
                break
            header_line = lines[i]
        else:
            name = "default" if not sections else f"section{len(sections)}"
            header_line = line
        sep = _detect_sep(header_line)
        header = [h.strip().strip('"') for h in header_line.split(sep)]
        i += 1
        units = [""] * len(header)
        if i < n:
            cand = [u.strip().strip('"') for u in lines[i].split(sep)]
            if len(cand) == len(header) and (any(c.startswith("[") for c in cand)
                                             or all(c == "" for c in cand)):
                units = cand
                i += 1
        while (i < n and lines[i].strip()
               and lines[i].split(sep)[0].strip().strip('"').startswith(("m:", "j:", "c:"))):
            i += 1
        rows = []
        while i < n:
            l = lines[i]
            if not l.strip() or _is_section_label(l):
                break
            vals = l.split(sep)
            i += 1
            if len(vals) != len(header):
                continue
            row = {}
            for hname, val in zip(header, vals):
                row[hname] = val.strip().strip('"')
            rows.append(row)
        sections.append({"name": name, "header": header, "units": units, "rows": rows})

    if not sections:
        return [], [], []

    if len(sections) == 1:
        sec = sections[0]
        return list(sec["header"]), list(sec["units"]), sec["rows"]

    header_names, header_units, seen = ["section"], [""], {"section"}
    for sec in sections:
        for hname, unit in zip(sec["header"], sec["units"]):
            if hname not in seen:
                seen.add(hname)
                header_names.append(hname)
                header_units.append(unit)
    data = []
    for sec in sections:
        for r in sec["rows"]:
            tagged = {"section": sec["name"]}
            tagged.update(r)
            data.append(tagged)
    return header_names, header_units, data


def extract_timeseries(data, columns, date_col="Date"):
    """Extract specific columns as a clean timeseries."""
    ts = []
    for row in data:
        entry = {}
        if date_col in row:
            entry["date"] = row[date_col]
        for col in columns:
            if col in row and row[col] != "":
                try:
                    entry[col] = float(row[col])
                except ValueError:
                    entry[col] = row[col]
        ts.append(entry)
    return ts


def compute_summary(data, header_names):
    """Compute summary statistics from parsed data."""
    summary = {}

    # Yield: take max non-empty value
    if "Yield" in header_names:
        yields = [float(r["Yield"]) for r in data
                  if r.get("Yield", "") not in ("", "0")]
        if yields:
            summary["max_yield_kg_ha"] = round(max(yields), 1)
            summary["n_harvests"] = len(yields)

    # Cumulative variables
    cum_vars = {
        "Act_ET": "total_et_mm",
        "Precip": "total_precip_mm",
        "NLeach": "total_n_leach_kg_ha",
        "Denit": "total_denit_kg_ha",
        "N2O": "total_n2o_kg_ha",
        "Irrig": "total_irrig_mm",
    }
    for var, key in cum_vars.items():
        if var in header_names:
            vals = [float(r[var]) for r in data if r.get(var, "") not in ("", )]
            if vals:
                summary[key] = round(sum(vals), 2)

    # Mean soil moisture (top layer)
    if "Mois/1" in header_names:
        mois = [float(r["Mois/1"]) for r in data if r.get("Mois/1", "") != ""]
        if mois:
            summary["mean_mois_layer1_m3m3"] = round(sum(mois) / len(mois), 4)

    return summary


def compare_with_observed(data, args):
    """Compare simulated vs observed data and compute metrics."""
    if not args.observed or not args.sim_col:
        return {}

    # Read observed data
    obs_data = {}
    with open(args.observed, "r", newline="") as f:
        reader = csv.DictReader(f)
        for rec in reader:
            date_key = rec.get(args.obs_date_col or "date", "").strip()
            val = rec.get(args.obs_col, "").strip()
            if date_key and val:
                try:
                    obs_data[date_key] = float(val)
                except ValueError:
                    pass

    # Match dates
    obs_vals = []
    sim_vals = []
    for row in data:
        date_key = row.get("Date", "").strip()
        if date_key in obs_data and row.get(args.sim_col, "") != "":
            try:
                sim_val = float(row[args.sim_col])
                obs_vals.append(obs_data[date_key])
                sim_vals.append(sim_val)
            except ValueError:
                pass

    if not obs_vals:
        return {"error": "No matching date pairs found between observed and simulated"}

    metrics = {"n_pairs": len(obs_vals)}
    requested = args.metric or ["rmse", "r2", "pbias"]
    for m in requested:
        if m in METRIC_FUNCS:
            metrics[m] = round(METRIC_FUNCS[m](obs_vals, sim_vals), 4)

    return metrics


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------

def write_clean_csv(timeseries, output_path, sep=","):
    """Write clean CSV from timeseries data."""
    if not timeseries:
        return
    # MONICA output mixes sections (e.g. daily vs crop/harvest events) whose
    # rows do not all carry the same columns; extract_timeseries only adds a
    # key when that row's cell is non-empty, so later rows can contain keys
    # absent from timeseries[0]. Build the fieldname set as the UNION of all
    # rows' keys (preserving first-seen order) and fill gaps with restval,
    # instead of trusting the first row alone (which raised
    # "dict contains fields not in fieldnames").
    keys = []
    seen = set()
    for entry in timeseries:
        for k in entry.keys():
            if k not in seen:
                seen.add(k)
                keys.append(k)
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=keys, delimiter=sep,
                                restval="", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(timeseries)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Parse MONICA output CSV and compute metrics")
    parser.add_argument("--input", required=True, help="MONICA output CSV path")
    parser.add_argument("--output-dir", required=True, help="Output directory for parsed files")
    parser.add_argument("--columns", nargs="*",
                        help="Columns to extract (default: all)")
    parser.add_argument("--observed", help="Observed data CSV for comparison")
    parser.add_argument("--obs-col", help="Observed value column name")
    parser.add_argument("--obs-date-col", default="date", help="Observed date column")
    parser.add_argument("--sim-col", help="Simulated column to compare")
    parser.add_argument("--metric", nargs="*", choices=list(METRIC_FUNCS.keys()),
                        help="Metrics to compute")

    args = parser.parse_args()
    validate_inputs(args)

    os.makedirs(args.output_dir, exist_ok=True)

    # Parse
    header_names, header_units, data = parse_monica_output(args.input)
    warnings = validate_outputs(data, args.output_dir)

    # Extract columns
    cols = args.columns or [h for h in header_names if h not in ("Date", "Crop")]
    ts = extract_timeseries(data, cols)

    # Write clean CSV
    clean_csv = os.path.join(args.output_dir, "timeseries.csv")
    write_clean_csv(ts, clean_csv)

    # Compute summary
    summary = compute_summary(data, header_names)

    # Compare with observed
    metrics = {}
    if args.observed:
        metrics = compare_with_observed(data, args)

    # Write summary
    result = {
        "status": "success",
        "input": args.input,
        "n_rows": len(data),
        "columns": header_names,
        "units": header_units,
        "clean_csv": clean_csv,
        "summary": summary,
        "metrics": metrics,
        "warnings": warnings,
    }

    summary_path = os.path.join(args.output_dir, "summary.json")
    with open(summary_path, "w") as f:
        json.dump(result, f, indent=2)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
