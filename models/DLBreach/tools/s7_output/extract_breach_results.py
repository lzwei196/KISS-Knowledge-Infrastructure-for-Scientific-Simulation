#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
==========================================
Tool ID:      extract_breach_results
Stage:        s7_output
Description:  Parse DLBreach 13-column ASCII output file into structured
              CSV and JSON formats with summary statistics.

Output columns (from DLBreach documentation):
  1.  time (hours)
  2.  breach_flow (m3/s)
  3.  spillway_gate_flow (m3/s)
  4.  upstream_wsl (m, above embankment base)
  5.  downstream_wsl (m)
  6.  breach_bottom_elevation (m)
  7.  breach_bottom_width (m)
  8.  breach_top_width (m)
  9.  breach_flow_area (m2)
  10. breach_side_slope (V/H)
  11. cumulative_volume (m3)
  12. sediment_upstream (m3/s)
  13. sediment_downstream (m3/s)

Inputs:
  --output_file:    Path to casename.out
  --format:         Output format: csv, json, or both (default both)
  --output_dir:     Directory for extracted files

Outputs:
  - JSON with peak_q, failure_time, max_breach_width, max_breach_depth,
    cumulative_volume, output_path

Exit codes:
  0 -- success
  1 -- output file not found
  2 -- parse error
  3 -- output validation failed
"""

import sys
import json
import csv
import argparse
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

COLUMN_NAMES = [
    "time_hr",
    "breach_flow_m3s",
    "spillway_gate_flow_m3s",
    "upstream_wsl_m",
    "downstream_wsl_m",
    "breach_bottom_elev_m",
    "breach_bottom_width_m",
    "breach_top_width_m",
    "breach_flow_area_m2",
    "breach_side_slope_vh",
    "cumulative_volume_m3",
    "sediment_upstream_m3s",
    "sediment_downstream_m3s",
]


def parse_output_file(filepath):
    """Parse the 13-column DLBreach output file."""
    data = []
    with open(filepath) as f:
        for line_num, line in enumerate(f, 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or stripped.startswith("!"):
                continue
            parts = stripped.split()
            if len(parts) < 13:
                logger.warning(f"Line {line_num}: expected 13 columns, got {len(parts)}, skipping")
                continue
            try:
                row = [float(x) for x in parts[:13]]
                data.append(row)
            except ValueError as e:
                logger.warning(f"Line {line_num}: parse error: {e}, skipping")
                continue
    return data


def compute_summary(data):
    """Compute summary statistics from parsed data."""
    if not data:
        return {"error": "no data"}

    times = [row[0] for row in data]
    breach_q = [row[1] for row in data]
    spillway_q = [row[2] for row in data]
    upstream_wsl = [row[3] for row in data]
    downstream_wsl = [row[4] for row in data]
    breach_bottom = [row[5] for row in data]
    breach_bw = [row[6] for row in data]
    breach_tw = [row[7] for row in data]
    cumvol = [row[10] for row in data]

    # Peak breach discharge
    peak_q_idx = breach_q.index(max(breach_q))
    peak_total_q = max(breach_q[i] + spillway_q[i] for i in range(len(data)))

    # Failure time: time when breach flow first exceeds 10% of peak
    peak_q = max(breach_q)
    threshold = 0.1 * peak_q
    failure_start_hr = None
    for i, q in enumerate(breach_q):
        if q > threshold:
            failure_start_hr = times[i]
            break

    # Breach geometry at peak
    summary = {
        "n_timesteps": len(data),
        "simulation_duration_hr": round(times[-1] - times[0], 4),
        "peak_breach_q_m3s": round(peak_q, 2),
        "peak_breach_time_hr": round(times[peak_q_idx], 4),
        "peak_total_q_m3s": round(peak_total_q, 2),
        "max_spillway_q_m3s": round(max(spillway_q), 2),
        "max_breach_top_width_m": round(max(breach_tw), 2),
        "max_breach_bottom_width_m": round(max(breach_bw), 2),
        "min_breach_bottom_elev_m": round(min(breach_bottom), 2),
        "max_breach_depth_m": round(breach_bottom[0] - min(breach_bottom), 2),
        "total_outflow_volume_m3": round(cumvol[-1], 0),
        "initial_upstream_wsl_m": round(upstream_wsl[0], 2),
        "final_upstream_wsl_m": round(upstream_wsl[-1], 2),
        "peak_downstream_wsl_m": round(max(downstream_wsl), 2),
        "failure_onset_hr": round(failure_start_hr, 4) if failure_start_hr else None,
        "breach_width_at_peak_m": round(breach_tw[peak_q_idx], 2),
        "breach_bottom_at_peak_m": round(breach_bottom[peak_q_idx], 2),
    }

    return summary


def write_csv(data, filepath):
    """Write parsed data to CSV."""
    with open(filepath, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(COLUMN_NAMES)
        for row in data:
            writer.writerow([round(v, 6) for v in row])


def write_json(data, summary, filepath):
    """Write parsed data and summary to JSON."""
    records = []
    for row in data:
        record = {COLUMN_NAMES[i]: row[i] for i in range(13)}
        records.append(record)

    output = {
        "summary": summary,
        "n_records": len(records),
        "columns": COLUMN_NAMES,
        "data": records,
    }

    with open(filepath, "w") as f:
        json.dump(output, f, indent=2)


def main():
    parser = argparse.ArgumentParser(description="Extract DLBreach results")
    parser.add_argument("--output_file", type=str, required=True, help="Path to casename.out")
    parser.add_argument("--format", type=str, default="both", choices=["csv", "json", "both"])
    parser.add_argument("--output_dir", type=str, help="Output directory for extracted files")
    parser.add_argument("--output", type=str, help="Output JSON metadata path")
    args = parser.parse_args()

    result = {
        "csv_path": None,
        "json_path": None,
        "summary": None,
        "status": "error",
        "errors": [],
    }

    output_path = Path(args.output_file)
    if not output_path.exists():
        result["errors"].append(f"Output file not found: {output_path}")
        print(json.dumps(result, indent=2))
        sys.exit(1)

    # Parse
    data = parse_output_file(str(output_path))
    if not data:
        result["errors"].append("No valid data lines parsed from output file")
        print(json.dumps(result, indent=2))
        sys.exit(2)

    logger.info(f"Parsed {len(data)} data lines from {output_path}")

    # Compute summary
    summary = compute_summary(data)
    result["summary"] = summary

    # Write outputs
    out_dir = Path(args.output_dir) if args.output_dir else output_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = output_path.stem

    if args.format in ["csv", "both"]:
        csv_path = out_dir / f"{stem}_results.csv"
        write_csv(data, str(csv_path))
        result["csv_path"] = str(csv_path)
        logger.info(f"CSV written: {csv_path}")

    if args.format in ["json", "both"]:
        json_path = out_dir / f"{stem}_results.json"
        write_json(data, summary, str(json_path))
        result["json_path"] = str(json_path)
        logger.info(f"JSON written: {json_path}")

    result["status"] = "success"
    logger.info(f"Peak breach Q: {summary['peak_breach_q_m3s']} m3/s at "
                f"t={summary['peak_breach_time_hr']} hr, "
                f"max width={summary['max_breach_top_width_m']} m")

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(result, indent=2))

    print(json.dumps(result, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
