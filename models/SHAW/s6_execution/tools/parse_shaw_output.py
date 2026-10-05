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
import calendar
import csv
import math
from pathlib import Path
from datetime import datetime, timedelta


def _date_fields(jday, hour, year):
    """Preserve SHAW's date columns and add a normalized ISO timestamp.

    Hour 24 is midnight at the start of the following day. Four-digit years
    are already calendar years; only SHAW's legacy two-digit years expand.
    """
    if 0 <= year < 100:
        year += 1900 if year > 50 else 2000
    if not (1 <= year <= 9999 and 1 <= jday <= 365 + calendar.isleap(year) and 0 <= hour <= 24):
        raise ValueError("invalid SHAW day/hour/year")
    stamp = datetime(year, 1, 1) + timedelta(days=jday - 1, hours=hour)
    return {"jday": jday, "hour": hour, "year": year, "datetime": stamp.isoformat()}


def _numeric_rows(filepath, minimum):
    """Read the standard SHAW 3.03 DAY HR YR columns, ignoring text headers.

    Never silently turn a truncated or nonfinite scientific row into a shorter
    apparently successful time series. Layouts are from the official Trial
    reference outputs, not guessed from whichever column count happens to fit.
    """
    with open(filepath, encoding="utf-8") as source:
        for number, line in enumerate(source, 1):
            fields = line.split()
            if not fields:
                continue
            try:
                int(fields[0])
            except ValueError:
                continue
            try:
                if len(fields) < 3:
                    raise ValueError("truncated numeric date row")
                date = [int(value) for value in fields[:3]]
                stamp = _date_fields(*date)
                if len(fields) < minimum:
                    raise ValueError(f"expected at least {minimum} columns, found {len(fields)}")
                values = [float(value.replace("D", "E").replace("d", "e")) for value in fields[3:]]
                if not all(math.isfinite(value) for value in values):
                    raise ValueError("nonfinite scientific output")
            except ValueError as error:
                raise ValueError(f"{filepath}:{number}: {error}") from error
            yield stamp, values


def parse_frost_file(filepath):
    """Read DAY HR YR THAW(cm) FROST(cm) SNOW(cm) SWE(mm), then node ice."""
    return [{**stamp, "thaw_depth_cm": values[0], "frost_depth_cm": values[1],
             "snow_depth_cm": values[2], "swe_mm": values[3], "swe_cm": values[3] / 10.0}
            for stamp, values in _numeric_rows(filepath, 7)]


def parse_water_file(filepath):
    """Read the official SHAW 3.03 water-balance layout; keep native flux signs.

    PRECIP is total precipitation and SNOWMELT is melt, not rainfall/snowfall.
    Storage change is the sum of the canopy, snow, residue and soil columns.
    """
    columns = ("precip_mm", "snowmelt_mm", "intercepted_precip_mm", "et_mm", "transpiration_mm",
               "canopy_storage_change_mm", "snow_storage_change_mm", "residue_storage_change_mm",
               "soil_storage_change_mm", "drainage_mm", "runoff_mm", "ponded_mm", "lateral_outflow_mm",
               "sink_mm", "cumulative_et_mm", "balance_error_mm")
    return [{**stamp, **dict(zip(columns, values)), "storage_change_mm": sum(values[5:9])}
            for stamp, values in _numeric_rows(filepath, 19)]


def parse_energy_file(filepath):
    """Read the material-resolved radiation layout; Rn = net solar + net longwave."""
    return [{**stamp, "rnet_wm2": values[6] + values[13], "sensible_wm2": values[14],
             "latent_wm2": values[15], "ground_wm2": values[16],
             "net_solar_wm2": values[6], "net_longwave_wm2": values[13]}
            for stamp, values in _numeric_rows(filepath, 20)]


def read_profile_depths(filepath):
    """Return the actual soil-node depths (metres) from a standard profile header."""
    with open(filepath, encoding="utf-8") as source:
        for line in source:
            fields = line.split()
            if len(fields) > 3 and fields[0].upper() in ("DY", "DAY") and fields[1:3] == ["HR", "YR"]:
                depths = [float(value) for value in fields[3:]]
                if not all(math.isfinite(value) for value in depths):
                    raise ValueError(f"{filepath}: nonfinite profile depth")
                return depths
    return []


def parse_profile_file(filepath, var_name="value"):
    """Read DAY HR YR followed by a consistent, header-matching soil-node count."""
    expected = len(read_profile_depths(filepath)) or None
    records = []
    for stamp, values in _numeric_rows(filepath, 4):
        expected = expected or len(values)
        if len(values) != expected:
            raise ValueError(f"{filepath}: profile has {len(values)} nodes; expected {expected}")
        records.append({**stamp, **{f"{var_name}_node{i}": value for i, value in enumerate(values, 1)}})
    return records


def write_csv(records, output_path):
    """Write records to CSV."""
    if not records:
        print(f"  WARNING: No records to write for {output_path}")
        return

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    keys = records[0].keys()
    with open(output_path, 'w', newline='', encoding='utf-8') as f:
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
