#!/usr/bin/env python3
"""
parse_shaw_output.py — Parse SHAW output files into CSV/DataFrame.

Reads the key SHAW output files and converts them to structured CSV format
for analysis and plotting.

Supported output files:
- frost.out: Frost depth, thaw depth, snow depth, SWE
- water.out: Water balance (precip, ET, runoff, drainage, storage change)
- energy.out: Surface energy balance (Rn, H, LE, G)
- temp.out: Soil temperature profiles
- moist.out: Soil moisture profiles

Usage:
    python parse_shaw_output.py \
        --workdir /path/to/shaw/run \
        --output_dir /path/to/csvs \
        [--files frost,water,energy]
"""

import argparse
import csv
import os
import re
from pathlib import Path
from datetime import datetime


def parse_frost_file(filepath):
    """
    Parse frost.out — frost depth, thaw depth, snow depth.

    Typical format:
    Header lines, then data rows with:
    JDAY HOUR YEAR frost_depth(cm) thaw_depth(cm) snow_depth(cm) SWE(cm) ...
    """
    records = []
    header_found = False

    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            # Skip header/comment lines
            if any(c.isalpha() for c in line[:10]):
                header_found = True
                continue

            parts = line.split()
            if len(parts) < 4:
                continue

            try:
                jday = int(parts[0])
                # Try different column layouts
                if len(parts) >= 7:
                    # Full format: JDAY HOUR YEAR frost thaw snow_depth SWE
                    hour = int(parts[1])
                    year = int(parts[2])
                    frost_depth = float(parts[3])
                    thaw_depth = float(parts[4])
                    snow_depth = float(parts[5])
                    swe = float(parts[6]) if len(parts) > 6 else 0.0
                elif len(parts) >= 4:
                    hour = 12
                    year = int(parts[1])
                    frost_depth = float(parts[2])
                    thaw_depth = float(parts[3])
                    snow_depth = float(parts[4]) if len(parts) > 4 else 0.0
                    swe = float(parts[5]) if len(parts) > 5 else 0.0
                else:
                    continue

                records.append({
                    'jday': jday,
                    'hour': hour,
                    'year': year + (1900 if year > 50 else 2000),
                    'frost_depth_cm': frost_depth,
                    'thaw_depth_cm': thaw_depth,
                    'snow_depth_cm': snow_depth,
                    'swe_cm': swe,
                })
            except (ValueError, IndexError):
                continue

    return records


def parse_water_file(filepath):
    """
    Parse water.out — water balance summary.

    Typical columns: JDAY YEAR Rain Snow ET Runoff Drainage StorageChange ...
    """
    records = []

    with open(filepath, 'r') as f:
        lines = f.readlines()

    for line in lines:
        line = line.strip()
        if not line or any(c.isalpha() for c in line[:10]):
            continue

        parts = line.split()
        if len(parts) < 6:
            continue

        try:
            jday = int(parts[0])
            year = int(parts[1])
            records.append({
                'jday': jday,
                'year': year + (1900 if year > 50 else 2000),
                'rain_mm': float(parts[2]),
                'snow_mm': float(parts[3]) if len(parts) > 3 else 0.0,
                'et_mm': float(parts[4]) if len(parts) > 4 else 0.0,
                'runoff_mm': float(parts[5]) if len(parts) > 5 else 0.0,
                'drainage_mm': float(parts[6]) if len(parts) > 6 else 0.0,
                'storage_change_mm': float(parts[7]) if len(parts) > 7 else 0.0,
            })
        except (ValueError, IndexError):
            continue

    return records


def parse_energy_file(filepath):
    """
    Parse energy.out — surface energy balance.

    Typical columns: JDAY HOUR YEAR Rn H LE G ...
    """
    records = []

    with open(filepath, 'r') as f:
        lines = f.readlines()

    for line in lines:
        line = line.strip()
        if not line or any(c.isalpha() for c in line[:10]):
            continue

        parts = line.split()
        if len(parts) < 6:
            continue

        try:
            jday = int(parts[0])
            hour = int(parts[1]) if len(parts) > 7 else 12
            year_idx = 2 if len(parts) > 7 else 1
            year = int(parts[year_idx])

            records.append({
                'jday': jday,
                'hour': hour,
                'year': year + (1900 if year > 50 else 2000),
                'rnet_wm2': float(parts[year_idx + 1]),
                'sensible_wm2': float(parts[year_idx + 2]),
                'latent_wm2': float(parts[year_idx + 3]),
                'ground_wm2': float(parts[year_idx + 4]),
            })
        except (ValueError, IndexError):
            continue

    return records


def parse_profile_file(filepath, var_name="value"):
    """
    Parse temp.out or moist.out — depth profiles over time.

    Format: JDAY HOUR YEAR value_node1 value_node2 ... value_nodeN
    """
    records = []

    with open(filepath, 'r') as f:
        lines = f.readlines()

    for line in lines:
        line = line.strip()
        if not line or any(c.isalpha() for c in line[:10]):
            continue

        parts = line.split()
        if len(parts) < 4:
            continue

        try:
            jday = int(parts[0])
            hour = int(parts[1])
            year = int(parts[2])

            values = [float(v) for v in parts[3:]]

            record = {
                'jday': jday,
                'hour': hour,
                'year': year + (1900 if year > 50 else 2000),
            }
            for i, v in enumerate(values):
                record[f'{var_name}_node{i+1}'] = v

            records.append(record)
        except (ValueError, IndexError):
            continue

    return records


def write_csv(records, output_path):
    """Write records to CSV."""
    if not records:
        print(f"  WARNING: No records to write for {output_path}")
        return

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    keys = records[0].keys()
    with open(output_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        writer.writerows(records)

    print(f"  {output_path.name}: {len(records)} records, {len(keys)} columns")


def main():
    parser = argparse.ArgumentParser(description="Parse SHAW output files to CSV")
    parser.add_argument("--workdir", type=str, required=True,
                        help="Directory containing SHAW output files")
    parser.add_argument("--output_dir", type=str, required=True,
                        help="Directory for CSV output files")
    parser.add_argument("--files", type=str, default="frost,water,energy,temp,moist",
                        help="Comma-separated list of files to parse")

    args = parser.parse_args()

    workdir = Path(args.workdir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    file_list = [f.strip() for f in args.files.split(',')]

    print(f"Parsing SHAW output from: {workdir}")

    parsers = {
        'frost': ('frost.out', parse_frost_file, 'shaw_frost.csv'),
        'water': ('water.out', parse_water_file, 'shaw_water_balance.csv'),
        'energy': ('energy.out', parse_energy_file, 'shaw_energy_balance.csv'),
        'temp': ('temp.out', lambda f: parse_profile_file(f, 'temp_C'), 'shaw_soil_temperature.csv'),
        'moist': ('moist.out', lambda f: parse_profile_file(f, 'moisture_m3m3'), 'shaw_soil_moisture.csv'),
    }

    for key in file_list:
        if key not in parsers:
            print(f"  Unknown file type: {key}")
            continue

        filename, parser_func, csv_name = parsers[key]
        filepath = workdir / filename

        if not filepath.exists():
            print(f"  {filename}: not found (skipping)")
            continue

        if filepath.stat().st_size == 0:
            print(f"  {filename}: empty file (skipping)")
            continue

        records = parser_func(str(filepath))
        write_csv(records, output_dir / csv_name)

    print(f"\nDone. CSV files in: {output_dir}")


if __name__ == "__main__":
    main()
