#!/usr/bin/env python3
"""Aggregate daily precipitation into monthly totals."""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from datetime import date
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    totals: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    with args.input.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            day = date.fromisoformat(row["date"])
            value = float(row["precip_mm"])
            if value < 0:
                raise ValueError(f"negative precipitation on {day}")
            month = day.strftime("%Y-%m")
            totals[month] += value
            counts[month] += 1
    with args.output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["month", "total_precip_mm", "n_days"])
        for month in sorted(totals):
            writer.writerow([month, f"{totals[month]:.3f}", counts[month]])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
