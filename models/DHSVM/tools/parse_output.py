#!/usr/bin/env python3
"""
parse_output.py — Parse DHSVM output files to CSV and compute metrics.

Extracts data from Aggregated.Values, Stream.Flow, Mass.Balance, and
pixel time series files. Computes hydrology metrics (NSE, KGE, PBIAS)
when observed data is provided.

Usage:
  python parse_output.py --aggregated output/Aggregated.Values \\
      --output results.csv

  python parse_output.py --streamflow output/Stream.Flow \\
      --observed obs_Q.csv --metrics nse,kge,pbias \\
      --output validation.json

  python parse_output.py --mass-balance output/Mass.Final.Balance \\
      --output balance.json
"""

import argparse
import csv
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import numpy as np


# --------------------------------------------------------------------------- #
# DHSVM date parsing
# --------------------------------------------------------------------------- #

def parse_dhsvm_date(datestr):
    """Parse DHSVM date formats.

    Handles: MM/DD/YYYY-HH:MM:SS, MM/DD/YYYY-HH, MM.DD.YYYY-HH:MM:SS
    """
    datestr = datestr.strip()
    # Replace dots with slashes for Stream.Flow format
    datestr = datestr.replace(".", "/", 2)

    for fmt in ["%m/%d/%Y-%H:%M:%S", "%m/%d/%Y-%H", "%m/%d/%Y-%H:%M"]:
        try:
            return datetime.strptime(datestr, fmt)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse DHSVM date: {datestr}")


# --------------------------------------------------------------------------- #
# Output parsers
# --------------------------------------------------------------------------- #

def parse_aggregated(filepath):
    """Parse DHSVM Aggregated.Values file.

    Returns list of dicts with datetime + all variable columns.
    """
    records = []

    with open(filepath, "r") as f:
        lines = f.readlines()

    if not lines:
        return {"status": "error", "errors": ["Empty file"]}

    # First line is header (comma or whitespace separated)
    header_line = lines[0].strip()
    if "," in header_line:
        headers = [h.strip() for h in header_line.split(",")]
    else:
        headers = header_line.split()

    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue
        if "," in line:
            parts = [p.strip() for p in line.split(",")]
        else:
            parts = line.split()

        if len(parts) < 2:
            continue

        try:
            dt = parse_dhsvm_date(parts[0])
        except ValueError:
            continue

        record = {"datetime": dt.strftime("%Y-%m-%d %H:%M:%S")}
        for i, val in enumerate(parts[1:], 1):
            col_name = headers[i] if i < len(headers) else f"col_{i}"
            try:
                record[col_name] = float(val)
            except ValueError:
                record[col_name] = val
        records.append(record)

    return records


def min_gap_seconds(datetimes):
    """Smallest gap in seconds between distinct times (None if < 2 times)."""
    times = sorted(set(datetimes))
    gaps = [(b - a).total_seconds() for a, b in zip(times, times[1:])]
    return min(gaps) if gaps else None


def parse_streamflow(filepath, step_hours=None):
    """Parse DHSVM Stream.Flow file (channel network runs).

    DHSVM writes one row per saved segment per MODEL time step
    (channel.c channel_save_outflow_text):
      date  segment_id  inflow  lateral_inflow  outflow  storage_change  "name"
    and one network "Totals" row per step with another column order
      date  0  total_lateral_inflow  total_outflow  total_storage  storage_change  error  "Totals"
    All flow columns are water VOLUMES in m3 per model step (channel.c
    outflow * deltat), not m3/s; total_storage is the m3 held. Totals rows
    are skipped here. The first model step has a Totals row only.
    (With no channel network, Stream.Flow is "date value" in m3/s; such
    2-column lines are not read by this function.)

    Returns (records, step_seconds). Each record: datetime, segment_id, name,
    outflow_m3 (m3 per model step) and flow_m3s (outflow_m3 / step_seconds,
    the mean rate over the step; None when the step length is unknown).
    step_seconds = step_hours * 3600 when given, else the smallest gap
    between row times (rows are written every model step).
    """
    rows = []

    with open(filepath, "r") as f:
        for line in f:
            # DHSVM ends every row with a newline (channel.c:654, 664); a
            # last line without one is a cut-off write: skip it, and warn when
            # it is a segment row (id > 0). A cut inside the date cannot be
            # told from a Totals row, so it gets no warning.
            if not line.endswith("\n"):
                cut = line.split()
                if (len(cut) >= 2 and re.fullmatch(r"[0-9]+", cut[1])
                        and int(cut[1]) > 0):
                    seg = cut[1] if len(cut) >= 3 else cut[1] + " (id may be cut)"
                    print(f"WARNING: {filepath}: skipped last line (no newline, "
                          f"segment {seg}): {line.strip()[:80]}", file=sys.stderr)
                continue
            parts = line.split()
            if len(parts) < 5:
                continue

            # Extract name if quoted at end (a SAVE segment may have no name)
            name_match = re.search(r'"([^"]+)"', line)
            name = name_match.group(1) if name_match else ""

            try:
                dt = parse_dhsvm_date(parts[0])
                segment_id = int(parts[1])
                outflow = float(parts[4])
            except (ValueError, IndexError):
                continue
            # Totals rows have id 0; real segment ids are > 0 (channel.c:384)
            if segment_id <= 0:
                continue
            rows.append((dt, segment_id, name, outflow))

    if step_hours is not None:
        step_s = float(step_hours) * 3600.0
    else:
        step_s = min_gap_seconds([r[0] for r in rows])

    records = []
    for dt, segment_id, name, outflow in rows:
        records.append({
            "datetime": dt.strftime("%Y-%m-%d %H:%M:%S"),
            "segment_id": segment_id,
            "name": name,
            "outflow_m3": outflow,
            "flow_m3s": outflow / step_s if step_s else None,
        })

    return records, step_s


def parse_mass_balance_final(filepath):
    """Parse DHSVM Mass.Final.Balance file (from stderr)."""
    balance = {}

    with open(filepath, "r") as f:
        text = f.read()

    patterns = {
        "total_inflow_mm": r"Total Inflow\s*\.+\s*([\d.e+-]+)",
        "precip_inflow_mm": r"Precip/Inflow\s*\.+\s*([\d.e+-]+)",
        "snow_vapor_flux_mm": r"SnowVaporFlux\s*\.+\s*([\d.e+-]+)",
        "total_outflow_mm": r"Total Outflow\s*\.+\s*([\d.e+-]+)",
        "et_mm": r"ET\s*\.+\s*([\d.e+-]+)",
        "channel_int_mm": r"ChannelInt\s*\.+\s*([\d.e+-]+)",
        "road_int_mm": r"RoadInt\s*\.+\s*([\d.e+-]+)",
        "storage_change_mm": r"Storage Change\s*\.+\s*([\d.e+-]+)",
        "initial_storage_mm": r"Initial Storage\s*\.+\s*([\d.e+-]+)",
        "final_storage_mm": r"Final Storage\s*\.+\s*([\d.e+-]+)",
        "final_swq_mm": r"Final SWQ\s*\.+\s*([\d.e+-]+)",
        "final_soil_moisture_mm": r"Final Soil Moisture\s*\.+\s*([\d.e+-]+)",
    }

    for key, pattern in patterns.items():
        match = re.search(pattern, text)
        if match:
            try:
                balance[key] = float(match.group(1))
            except ValueError:
                pass

    return balance


def parse_pixel_output(filepath):
    """Parse DHSVM pixel time series output (same format as Aggregated)."""
    return parse_aggregated(filepath)


# --------------------------------------------------------------------------- #
# Hydrological metrics
# --------------------------------------------------------------------------- #

def calc_nse(obs, sim):
    """Nash-Sutcliffe Efficiency."""
    obs, sim = np.array(obs), np.array(sim)
    mask = ~(np.isnan(obs) | np.isnan(sim))
    obs, sim = obs[mask], sim[mask]
    if len(obs) == 0:
        return np.nan
    mean_obs = np.mean(obs)
    ss_res = np.sum((obs - sim) ** 2)
    ss_tot = np.sum((obs - mean_obs) ** 2)
    if ss_tot == 0:
        return np.nan
    return 1.0 - ss_res / ss_tot


def calc_kge(obs, sim):
    """Kling-Gupta Efficiency."""
    obs, sim = np.array(obs), np.array(sim)
    mask = ~(np.isnan(obs) | np.isnan(sim))
    obs, sim = obs[mask], sim[mask]
    if len(obs) < 2:
        return np.nan
    r = np.corrcoef(obs, sim)[0, 1]
    alpha = np.std(sim) / np.std(obs) if np.std(obs) > 0 else np.nan
    beta = np.mean(sim) / np.mean(obs) if np.mean(obs) > 0 else np.nan
    if np.isnan(r) or np.isnan(alpha) or np.isnan(beta):
        return np.nan
    return 1.0 - np.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2)


def calc_pbias(obs, sim):
    """Percent Bias (%)."""
    obs, sim = np.array(obs), np.array(sim)
    mask = ~(np.isnan(obs) | np.isnan(sim))
    obs, sim = obs[mask], sim[mask]
    if np.sum(obs) == 0:
        return np.nan
    return 100.0 * np.sum(sim - obs) / np.sum(obs)


def calc_rmse(obs, sim):
    """Root Mean Square Error."""
    obs, sim = np.array(obs), np.array(sim)
    mask = ~(np.isnan(obs) | np.isnan(sim))
    obs, sim = obs[mask], sim[mask]
    if len(obs) == 0:
        return np.nan
    return np.sqrt(np.mean((obs - sim) ** 2))


def calc_r(obs, sim):
    """Pearson correlation coefficient."""
    obs, sim = np.array(obs), np.array(sim)
    mask = ~(np.isnan(obs) | np.isnan(sim))
    obs, sim = obs[mask], sim[mask]
    if len(obs) < 2:
        return np.nan
    return float(np.corrcoef(obs, sim)[0, 1])


METRIC_FUNCS = {
    "nse": calc_nse,
    "kge": calc_kge,
    "pbias": calc_pbias,
    "rmse": calc_rmse,
    "r": calc_r,
}


# --------------------------------------------------------------------------- #
# Main processing
# --------------------------------------------------------------------------- #

def validate_inputs(args):
    """Validate input arguments."""
    errors = []

    sources = [args.aggregated, args.streamflow, args.mass_balance, args.pixel]
    if not any(sources):
        errors.append("Must provide at least one input: --aggregated, "
                      "--streamflow, --mass-balance, or --pixel")

    for src in sources:
        if src and not os.path.isfile(src):
            errors.append(f"File not found: {src}")

    if args.step_hours is not None and not args.step_hours > 0:
        errors.append(f"--step-hours must be > 0, got {args.step_hours}")

    if args.observed and not os.path.isfile(args.observed):
        errors.append(f"Observed file not found: {args.observed}")

    if args.metrics:
        for m in args.metrics.split(","):
            if m.strip() not in METRIC_FUNCS:
                errors.append(f"Unknown metric: {m}. "
                              f"Valid: {list(METRIC_FUNCS.keys())}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}, indent=2))
        sys.exit(1)


def process(args):
    """Process DHSVM output files."""
    result = {"status": "success"}

    # Parse aggregated output
    if args.aggregated:
        records = parse_aggregated(args.aggregated)
        result["aggregated"] = {
            "file": args.aggregated,
            "n_records": len(records),
            "columns": list(records[0].keys()) if records else [],
        }

        # Write CSV
        if args.output and args.output.endswith(".csv"):
            write_csv(records, args.output)
            result["csv_output"] = args.output

    # Parse streamflow
    if args.streamflow:
        records, step_s = parse_streamflow(args.streamflow, args.step_hours)
        segments = set(r["segment_id"] for r in records)
        result["streamflow"] = {
            "file": args.streamflow,
            "n_records": len(records),
            "n_segments": len(segments),
            "segments": sorted(segments),
            "segment_names": sorted(set(r["name"] for r in records if r["name"])),
            "units": "outflow_m3 = m3 per model step; flow_m3s = outflow_m3 / step_seconds",
            "step_seconds": step_s,
            "step_source": ("--step-hours" if args.step_hours is not None
                            else "smallest gap between Stream.Flow row times"),
        }
        gap_s = min_gap_seconds(
            [datetime.strptime(r["datetime"], "%Y-%m-%d %H:%M:%S")
             for r in records])
        result["streamflow"]["row_gap_seconds"] = gap_s
        if (args.step_hours is not None and gap_s
                and abs(gap_s - step_s) > 1e-6):
            result["streamflow"]["step_warning"] = (
                f"--step-hours gives {step_s:.0f} s but Stream.Flow rows are "
                f"{gap_s:.0f} s apart; check the config Time Step")

        # Write CSV (was previously only done for --aggregated, so a
        # documented `--streamflow ... --output results.csv` call silently
        # produced no file). Write the parsed streamflow records too.
        if args.output and args.output.endswith(".csv"):
            write_csv(records, args.output)
            result["csv_output"] = args.output

        # Compute metrics if observed data provided
        if args.observed:
            metrics = compute_validation_metrics(
                records, args.observed, args.metrics, args.segment)
            result["metrics"] = metrics
            if "error" in metrics:
                result["status"] = "error"
                result["errors"] = [metrics["error"]]

    # Parse mass balance
    if args.mass_balance:
        balance = parse_mass_balance_final(args.mass_balance)
        result["mass_balance"] = balance

    # Parse pixel output
    if args.pixel:
        records = parse_pixel_output(args.pixel)
        result["pixel"] = {
            "file": args.pixel,
            "n_records": len(records),
            "columns": list(records[0].keys()) if records else [],
        }

    return result


def compute_validation_metrics(sim_records, obs_file, metric_str, segment=None):
    """Compute validation metrics between simulated and observed."""
    import pandas as pd

    # Load observed data
    obs_df = pd.read_csv(obs_file)

    # Find datetime column
    date_cols = [c for c in obs_df.columns
                 if "date" in c.lower() or "time" in c.lower()]
    if date_cols:
        obs_df["datetime"] = pd.to_datetime(obs_df[date_cols[0]])
    else:
        obs_df["datetime"] = pd.to_datetime(obs_df.iloc[:, 0])

    # Find flow column
    flow_cols = [c for c in obs_df.columns
                 if any(k in c.lower() for k in ["flow", "q", "discharge"])]
    if flow_cols:
        obs_df["obs_flow"] = obs_df[flow_cols[0]]
    else:
        obs_df["obs_flow"] = obs_df.iloc[:, 1]

    if not sim_records:
        return {"error": "no segment rows in Stream.Flow (no SAVE segments, "
                         "or a no-network file with one m3/s value per step)"}

    # Use ONE saved segment (the gauge's). Totals rows are already skipped
    # by parse_streamflow; never mix several segments in one series.
    seg_keys = sorted({(r["segment_id"], r["name"]) for r in sim_records})
    if segment is not None:
        outlet_records = [r for r in sim_records
                          if r["name"] == segment
                          or str(r["segment_id"]) == str(segment)]
        if not outlet_records:
            return {"error": f"segment {segment!r} not in Stream.Flow; "
                             f"saved segments: {seg_keys[:10]}"}
        picked = sorted({(r["segment_id"], r["name"]) for r in outlet_records})
        if len(picked) > 1:
            return {"error": f"--segment {segment!r} matches {len(picked)} "
                             f"segments {picked[:10]}: pass an id or name "
                             f"that picks only one"}
    elif len(seg_keys) == 1:
        outlet_records = sim_records
    else:
        return {"error": f"Stream.Flow holds {len(seg_keys)} saved segments "
                         f"{seg_keys[:10]}: pass --segment (name or id)"}
    if any(r["flow_m3s"] is None for r in outlet_records):
        return {"error": "model step length unknown: pass --step-hours"}

    sim_df = pd.DataFrame(outlet_records)
    sim_df["datetime"] = pd.to_datetime(sim_df["datetime"])

    # Merge on datetime
    merged = pd.merge(obs_df[["datetime", "obs_flow"]],
                       sim_df[["datetime", "flow_m3s"]],
                       on="datetime", how="inner")

    if len(merged) == 0:
        return {"error": "No overlapping timestamps between obs and sim"}

    obs = merged["obs_flow"].values
    sim = merged["flow_m3s"].values

    metrics_to_compute = (metric_str or "nse,kge,pbias,rmse,r").split(",")
    results = {
        "n_matched": len(merged),
        "obs_mean": float(np.nanmean(obs)),
        "sim_mean": float(np.nanmean(sim)),
    }

    for m in metrics_to_compute:
        m = m.strip()
        if m in METRIC_FUNCS:
            results[m] = round(float(METRIC_FUNCS[m](obs, sim)), 4)

    return results


def write_csv(records, filepath):
    """Write records to CSV."""
    if not records:
        return
    os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
    with open(filepath, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=records[0].keys())
        writer.writeheader()
        writer.writerows(records)


def validate_outputs(result):
    """Validate parsed output."""
    if result.get("status") != "success":
        return result

    warnings = []

    agg = result.get("aggregated", {})
    if agg and agg.get("n_records", 0) == 0:
        warnings.append("Aggregated file parsed but no records found")

    sf = result.get("streamflow", {})
    if sf and sf.get("n_records", 0) == 0:
        warnings.append("Stream.Flow file parsed but no records found")
    if sf and sf.get("step_warning"):
        warnings.append(sf["step_warning"])

    metrics = result.get("metrics", {})
    if metrics:
        nse = metrics.get("nse")
        if nse is not None and nse < 0:
            warnings.append(f"NSE = {nse} < 0: model worse than mean")
        kge = metrics.get("kge")
        if kge is not None and kge < -0.41:
            warnings.append(f"KGE = {kge} < -0.41: model not useful")

    result["warnings"] = warnings
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Parse DHSVM output files and compute metrics")
    parser.add_argument("--aggregated",
                        help="Path to Aggregated.Values file")
    parser.add_argument("--streamflow",
                        help="Path to Stream.Flow file")
    parser.add_argument("--mass-balance",
                        help="Path to Mass.Final.Balance file")
    parser.add_argument("--pixel",
                        help="Path to pixel time series file")
    parser.add_argument("--observed",
                        help="Observed data CSV for validation")
    parser.add_argument("--step-hours", type=float,
                        help="DHSVM model time step in hours (TIME section "
                             "'Time Step'); default: smallest gap between "
                             "Stream.Flow row times")
    parser.add_argument("--segment",
                        help="Stream.Flow segment name or id to compare "
                             "with --observed")
    parser.add_argument("--metrics", default="nse,kge,pbias,rmse,r",
                        help="Metrics to compute (comma-separated)")
    parser.add_argument("--output",
                        help="Output file (.csv or .json)")
    args = parser.parse_args()

    validate_inputs(args)
    result = process(args)
    result = validate_outputs(result)

    if args.output and args.output.endswith(".json"):
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        print(f"Output written to {args.output}", file=sys.stderr)
    elif not (args.output and args.output.endswith(".csv")):
        print(json.dumps(result, indent=2, ensure_ascii=False))

    if result.get("status") != "success":
        print("ERROR: " + "; ".join(result.get("errors", [])), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
