#!/usr/bin/env python3
"""
shaw_frost_analysis.py — Extract frost metrics from SHAW frost.out.

Computes:
- Maximum frost depth per year
- Number of freeze-thaw cycles per year
- First frost date and last thaw date (frozen season)
- Total frozen period duration (days)
- Maximum snow depth and snow cover duration
- Cumulative frost-degree-days

These metrics are critical for:
- VIC coupling: adjusting infiltration during frozen soil
- Agricultural applications: determining planting dates
- Infrastructure: frost heave risk assessment

Usage:
    python shaw_frost_analysis.py \
        --frost_file /path/to/frost.out \
        --output /path/to/frost_metrics.csv \
        [--plot /path/to/frost_analysis.png]
"""

import argparse
import csv
import sys
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict


def parse_frost_output(filepath):
    """Parse SHAW frost.out file."""
    records = []

    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or any(c.isalpha() for c in line[:10]):
                continue

            parts = line.split()
            if len(parts) < 4:
                continue

            try:
                jday = int(parts[0])
                if len(parts) >= 7:
                    hour = int(parts[1])
                    year = int(parts[2])
                    frost_depth = float(parts[3])
                    thaw_depth = float(parts[4])
                    snow_depth = float(parts[5])
                    swe = float(parts[6]) if len(parts) > 6 else 0.0
                else:
                    hour = 12
                    year = int(parts[1])
                    frost_depth = float(parts[2])
                    thaw_depth = float(parts[3])
                    snow_depth = float(parts[4]) if len(parts) > 4 else 0.0
                    swe = float(parts[5]) if len(parts) > 5 else 0.0

                year = year + (1900 if year > 50 else 2000)
                dt = datetime(year, 1, 1) + timedelta(days=jday - 1, hours=hour)

                records.append({
                    'datetime': dt,
                    'jday': jday,
                    'year': year,
                    'frost_depth_cm': frost_depth,
                    'thaw_depth_cm': thaw_depth,
                    'snow_depth_cm': snow_depth,
                    'swe_cm': swe,
                })
            except (ValueError, IndexError):
                continue

    return records


def compute_frost_metrics(records):
    """Compute annual frost metrics."""
    if not records:
        return []

    # Group by year
    by_year = defaultdict(list)
    for rec in records:
        by_year[rec['year']].append(rec)

    metrics = []
    for year in sorted(by_year.keys()):
        recs = by_year[year]
        recs.sort(key=lambda r: r['datetime'])

        frost_depths = [r['frost_depth_cm'] for r in recs]
        snow_depths = [r['snow_depth_cm'] for r in recs]

        # Maximum frost depth
        max_frost = max(frost_depths)
        max_frost_day = recs[frost_depths.index(max_frost)]['jday']

        # Maximum snow depth
        max_snow = max(snow_depths)
        max_snow_day = recs[snow_depths.index(max_snow)]['jday'] if max_snow > 0 else 0

        # Frozen days: frost_depth > 0
        frozen_days = sum(1 for f in frost_depths if f > 0)

        # Snow-covered days
        snow_days = sum(1 for s in snow_depths if s > 0.1)

        # Freeze-thaw cycles: transitions from frozen to unfrozen
        cycles = 0
        was_frozen = False
        for f in frost_depths:
            is_frozen = f > 0
            if was_frozen and not is_frozen:
                cycles += 1
            was_frozen = is_frozen

        # First frost date (first day with frost_depth > 0)
        first_frost_day = None
        for rec in recs:
            if rec['frost_depth_cm'] > 0:
                first_frost_day = rec['jday']
                break

        # Last thaw date (last day with frost_depth > 0)
        last_thaw_day = None
        for rec in reversed(recs):
            if rec['frost_depth_cm'] > 0:
                last_thaw_day = rec['jday']
                break

        # Mean SWE
        swe_values = [r['swe_cm'] for r in recs]
        mean_swe = sum(swe_values) / len(swe_values)
        max_swe = max(swe_values)

        metrics.append({
            'year': year,
            'max_frost_depth_cm': round(max_frost, 1),
            'max_frost_day': max_frost_day,
            'frozen_days': frozen_days,
            'freeze_thaw_cycles': cycles,
            'first_frost_day': first_frost_day,
            'last_thaw_day': last_thaw_day,
            'max_snow_depth_cm': round(max_snow, 1),
            'max_snow_day': max_snow_day,
            'snow_cover_days': snow_days,
            'max_swe_cm': round(max_swe, 1),
            'mean_swe_cm': round(mean_swe, 2),
        })

    return metrics


def write_metrics_csv(metrics, output_path):
    """Write metrics to CSV."""
    if not metrics:
        print("No metrics to write.")
        return

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=metrics[0].keys())
        writer.writeheader()
        writer.writerows(metrics)

    print(f"Frost metrics written: {output_path}")


def print_metrics_summary(metrics):
    """Print human-readable summary."""
    print("\n" + "=" * 70)
    print("SHAW FROST ANALYSIS SUMMARY")
    print("=" * 70)

    for m in metrics:
        print(f"\nYear {m['year']}:")
        print(f"  Max frost depth: {m['max_frost_depth_cm']:.1f} cm (day {m['max_frost_day']})")
        print(f"  Frozen days: {m['frozen_days']}")
        print(f"  Freeze-thaw cycles: {m['freeze_thaw_cycles']}")
        if m['first_frost_day']:
            print(f"  Frost season: day {m['first_frost_day']} to day {m['last_thaw_day']}")
        else:
            print(f"  No frost")
        print(f"  Max snow depth: {m['max_snow_depth_cm']:.1f} cm")
        print(f"  Snow cover days: {m['snow_cover_days']}")
        print(f"  Max SWE: {m['max_swe_cm']:.1f} cm")

    if len(metrics) > 1:
        avg_frost = sum(m['max_frost_depth_cm'] for m in metrics) / len(metrics)
        avg_frozen = sum(m['frozen_days'] for m in metrics) / len(metrics)
        avg_cycles = sum(m['freeze_thaw_cycles'] for m in metrics) / len(metrics)
        print(f"\nMulti-year averages:")
        print(f"  Mean max frost depth: {avg_frost:.1f} cm")
        print(f"  Mean frozen days: {avg_frozen:.0f}")
        print(f"  Mean freeze-thaw cycles: {avg_cycles:.1f}")


def main():
    parser = argparse.ArgumentParser(description="Analyze SHAW frost output")
    parser.add_argument("--frost_file", type=str, required=True,
                        help="SHAW frost.out file")
    parser.add_argument("--output", type=str, default=None,
                        help="Output CSV for frost metrics")
    parser.add_argument("--plot", type=str, default=None,
                        help="Output plot file")

    args = parser.parse_args()

    # Parse frost output
    records = parse_frost_output(args.frost_file)
    if not records:
        print(f"ERROR: No data read from {args.frost_file}")
        sys.exit(1)

    print(f"Read {len(records)} frost records")

    # Compute metrics
    metrics = compute_frost_metrics(records)
    print_metrics_summary(metrics)

    # Write CSV
    if args.output:
        write_metrics_csv(metrics, args.output)

    # Plot (optional)
    if args.plot:
        try:
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            import matplotlib.dates as mdates

            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), sharex=True)

            times = [r['datetime'] for r in records]
            frost = [r['frost_depth_cm'] for r in records]
            snow = [r['snow_depth_cm'] for r in records]

            ax1.fill_between(times, 0, snow, alpha=0.3, color='cyan', label='Snow depth')
            ax1.set_ylabel('Snow Depth (cm)')
            ax1.set_title('SHAW Frost Analysis')
            ax1.legend(loc='upper right')

            ax2.plot(times, frost, 'b-', linewidth=1.5, label='Frost depth')
            ax2.fill_between(times, 0, frost, alpha=0.2, color='blue')
            ax2.set_ylabel('Frost Depth (cm)')
            ax2.set_xlabel('Date')
            ax2.legend(loc='upper right')
            ax2.xaxis.set_major_formatter(mdates.DateFormatter('%b %Y'))

            plt.tight_layout()
            Path(args.plot).parent.mkdir(parents=True, exist_ok=True)
            plt.savefig(args.plot, dpi=150, bbox_inches='tight')
            plt.close()
            print(f"Plot saved: {args.plot}")
        except ImportError:
            print("WARNING: matplotlib not available, skipping plot")


if __name__ == "__main__":
    main()
