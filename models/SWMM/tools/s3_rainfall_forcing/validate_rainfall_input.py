#!/usr/bin/env python3
"""
Validate SWMM rainfall timeseries input.

Checks rainfall timeseries for common issues:
  - Negative values
  - Unreasonably high intensities (> threshold, default 300 mm/hr)
  - Temporal gaps (missing timesteps)
  - Non-monotonic timestamps
  - All-zero data
  - Extreme value statistics

Reads SWMM timeseries format (tab-separated: name date time value)
or simple CSV format.

Outputs a JSON validation report to stdout.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path


def parse_swmm_timeseries(filepath):
    """Parse SWMM timeseries format."""
    records = []
    with open(filepath, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith(";"):
                continue
            parts = line.split()
            if len(parts) >= 4:
                # name date time value
                name = parts[0]
                try:
                    dt = datetime.strptime(f"{parts[1]} {parts[2]}", "%m/%d/%Y %H:%M:%S")
                    value = float(parts[3])
                    records.append({"datetime": dt, "value": value, "name": name})
                except ValueError:
                    try:
                        dt = datetime.strptime(f"{parts[1]} {parts[2]}", "%m/%d/%Y %H:%M")
                        value = float(parts[3])
                        records.append({"datetime": dt, "value": value, "name": name})
                    except ValueError:
                        continue
            elif len(parts) >= 3:
                # date time value (no name)
                try:
                    dt = datetime.strptime(f"{parts[0]} {parts[1]}", "%m/%d/%Y %H:%M:%S")
                    value = float(parts[2])
                    records.append({"datetime": dt, "value": value, "name": ""})
                except ValueError:
                    continue

    records.sort(key=lambda x: x["datetime"])
    return records


def validate_timeseries(records, max_intensity=300.0):
    """Run validation checks on rainfall timeseries."""
    issues = []
    warnings = []

    if not records:
        issues.append({
            "type": "empty_data",
            "message": "No valid records found in timeseries",
        })
        return {
            "n_records": 0,
            "n_issues": 1,
            "n_warnings": 0,
            "issues": issues,
            "warnings": warnings,
            "valid": False,
            "statistics": {},
        }

    values = [r["value"] for r in records]
    datetimes = [r["datetime"] for r in records]

    # Check for negative values
    negatives = [(i, r["value"]) for i, r in enumerate(records) if r["value"] < 0]
    if negatives:
        issues.append({
            "type": "negative_values",
            "count": len(negatives),
            "first_occurrence": str(records[negatives[0][0]]["datetime"]),
            "message": f"{len(negatives)} negative rainfall value(s) found",
        })

    # Check for extreme intensities
    extremes = [(i, r["value"]) for i, r in enumerate(records) if r["value"] > max_intensity]
    if extremes:
        warnings.append({
            "type": "extreme_intensity",
            "count": len(extremes),
            "max_value": max(e[1] for e in extremes),
            "threshold": max_intensity,
            "message": (f"{len(extremes)} value(s) exceed {max_intensity} mm/hr "
                        f"(max: {max(e[1] for e in extremes):.2f})"),
        })

    # Check for non-monotonic timestamps
    non_monotonic = 0
    for i in range(1, len(datetimes)):
        if datetimes[i] <= datetimes[i - 1]:
            non_monotonic += 1
    if non_monotonic:
        issues.append({
            "type": "non_monotonic",
            "count": non_monotonic,
            "message": f"{non_monotonic} non-monotonic timestamp(s)",
        })

    # Check for temporal gaps
    if len(datetimes) >= 2:
        # Infer expected timestep from most common delta
        deltas = [(datetimes[i] - datetimes[i - 1]).total_seconds()
                  for i in range(1, len(datetimes))
                  if datetimes[i] > datetimes[i - 1]]
        if deltas:
            from collections import Counter
            delta_counts = Counter([int(d) for d in deltas])
            expected_delta = delta_counts.most_common(1)[0][0]
            gaps = [i for i, d in enumerate(deltas)
                    if abs(d - expected_delta) > expected_delta * 0.5
                    and d > expected_delta * 1.5]
            if gaps:
                warnings.append({
                    "type": "temporal_gaps",
                    "count": len(gaps),
                    "expected_timestep_sec": expected_delta,
                    "message": f"{len(gaps)} temporal gap(s) detected "
                               f"(expected timestep: {expected_delta}s)",
                })

    # Check for all-zero data
    nonzero = [v for v in values if v > 0]
    if not nonzero:
        warnings.append({
            "type": "all_zero",
            "message": "All rainfall values are zero — no precipitation event",
        })

    # Statistics
    stats = {
        "n_records": len(records),
        "n_nonzero": len(nonzero),
        "start": str(datetimes[0]),
        "end": str(datetimes[-1]),
        "duration_hours": (datetimes[-1] - datetimes[0]).total_seconds() / 3600,
        "max_intensity_mm_hr": round(max(values), 4),
        "min_value": round(min(values), 4),
        "mean_intensity_mm_hr": round(sum(values) / len(values), 4),
    }
    if nonzero:
        stats["mean_nonzero_mm_hr"] = round(sum(nonzero) / len(nonzero), 4)
        stats["total_depth_mm"] = round(
            sum(values) * (stats["duration_hours"] / len(values)), 2
        )

    report = {
        "n_records": len(records),
        "n_issues": len(issues),
        "n_warnings": len(warnings),
        "issues": issues,
        "warnings": warnings,
        "valid": len(issues) == 0,
        "statistics": stats,
    }
    return report


def main():
    parser = argparse.ArgumentParser(
        description="Validate SWMM rainfall timeseries input"
    )
    parser.add_argument("--timeseries", required=True,
                        help="SWMM timeseries file (.dat)")
    parser.add_argument("--max_intensity", type=float, default=300.0,
                        help="Maximum reasonable intensity in mm/hr (default: 300)")
    args = parser.parse_args()

    if not os.path.isfile(args.timeseries):
        print(f"ERROR: File not found: {args.timeseries}", file=sys.stderr)
        sys.exit(1)

    print(f"Validating {args.timeseries}...", file=sys.stderr)
    records = parse_swmm_timeseries(args.timeseries)
    print(f"  Parsed {len(records)} records", file=sys.stderr)

    report = validate_timeseries(records, args.max_intensity)
    print(json.dumps(report, indent=2, default=str))

    if report["valid"]:
        print(f"\nVALID: {report['n_records']} records, "
              f"{report['n_warnings']} warning(s)", file=sys.stderr)
    else:
        print(f"\nINVALID: {report['n_issues']} issue(s)", file=sys.stderr)

    sys.exit(0 if report["valid"] else 1)


if __name__ == "__main__":
    main()
