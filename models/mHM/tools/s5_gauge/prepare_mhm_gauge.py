#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
Tool ID:      prepare_mhm_gauge
Stage:        s5_gauge
Description:  Convert HydroCraft/GRDC/HYDAT observed discharge to mHM gauge format.

mHM gauge format:
  - Plain text, one file per gauge
  - Columns: YYYY MM DD Q(m3/s) -- space or tab separated
  - NODATA: -9999
  - Filename: GGGGG.txt where G is zero-padded gauge ID

HydroCraft obs format:
  - Tab-separated columns: stcd, dates, z, Q, name
  - dates in YYYY-MM-DD format

Inputs:
  - OBS_FILE: path to observed discharge file
  - GAUGE_ID: integer gauge ID
  - OUTPUT_DIR: target directory (input/gauge/)
  - START_YEAR / END_YEAR: period to extract

Outputs:
  - GGGGG.txt in OUTPUT_DIR
"""

import sys
import os
import json
import logging
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

OBS_FILE = ""
GAUGE_ID = 1
GAUGE_NAME = ""
OUTPUT_DIR = ""
START_YEAR = 2000
END_YEAR = 2010

if len(sys.argv) > 1:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--obs_file", required=True)
    parser.add_argument("--gauge_id", type=int, default=1)
    parser.add_argument("--gauge_name", default="")
    parser.add_argument("--output_dir", required=True)
    parser.add_argument("--start_year", type=int, default=2000)
    parser.add_argument("--end_year", type=int, default=2010)
    args = parser.parse_args()
    OBS_FILE = args.obs_file
    GAUGE_ID = args.gauge_id
    GAUGE_NAME = args.gauge_name
    OUTPUT_DIR = args.output_dir
    START_YEAR = args.start_year
    END_YEAR = args.end_year


def write_gauge_header(f, start_date, end_date):
    """mHM gauge header -- FIVE lines, then SIX columns (dt_s13).

    Verified against mhm_src/test_domain/input/gauge/00398.txt.  mo_read_timeseries.f90
    skips five header lines and parses `YYYY MM DD HH MM Q`.  A bare 4-column
    `YYYY MM DD Q` file makes mHM eat the first data rows as the header and then read
    discharge out of the DAY column.
    """
    name = GAUGE_NAME or f"GAUGE {GAUGE_ID}"
    f.write(f"{GAUGE_ID} {name} (daily discharge)\n")
    f.write("nodata   -9999\n")
    f.write("n       1       measurements per day [1, 1440]\n")
    f.write(f"start  {start_date.year}  {start_date.month:02d}  {start_date.day:02d}"
            f"  00  00   (YYYY MM DD HH MM)\n")
    f.write(f"end    {end_date.year}  {end_date.month:02d}  {end_date.day:02d}"
            f"  00  00   (YYYY MM DD HH MM)\n")


def validate_inputs():
    errors = []
    if not OBS_FILE or not Path(OBS_FILE).exists():
        errors.append(f"Obs file not found: {OBS_FILE}")
    if not OUTPUT_DIR:
        errors.append("OUTPUT_DIR not set")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)


def process():
    out_dir = Path(OUTPUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Read HydroCraft obs format
    dates = []
    q_vals = []

    with open(OBS_FILE, encoding='latin-1') as f:
        header = f.readline()
        for line in f:
            parts = line.strip().split('\t')
            if len(parts) < 4:
                parts = line.strip().split()
            if len(parts) >= 4:
                try:
                    date_str = parts[1].strip()
                    q = float(parts[3])
                    # Parse date
                    for fmt in ["%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"]:
                        try:
                            dt = datetime.strptime(date_str, fmt)
                            break
                        except ValueError:
                            continue
                    else:
                        continue

                    if START_YEAR <= dt.year <= END_YEAR:
                        dates.append(dt)
                        q_vals.append(q if q >= 0 else -9999)
                except (ValueError, IndexError):
                    continue

    logger.info(f"Read {len(dates)} discharge records from {OBS_FILE}")

    # Fill gaps with -9999 to create continuous daily series
    if dates:
        start_date = datetime(START_YEAR, 1, 1)
        end_date = datetime(END_YEAR, 12, 31)
        date_q_map = {d.strftime("%Y%m%d"): q for d, q in zip(dates, q_vals)}

        filename = f"{GAUGE_ID:05d}.txt"
        out_path = out_dir / filename
        n_records = 0
        n_missing = 0

        with open(out_path, 'w') as f:
            write_gauge_header(f, start_date, end_date)
            current = start_date
            while current <= end_date:
                key = current.strftime("%Y%m%d")
                q = date_q_map.get(key, -9999)
                if q == -9999:
                    n_missing += 1
                f.write(f"{current.year}  {current.month:02d}  {current.day:02d}"
                        f"  00  00  {q:12.3f}\n")
                n_records += 1
                current += timedelta(days=1)

        logger.info(f"Written: {out_path} ({n_records} records, {n_missing} missing)")
    else:
        logger.error("No valid discharge records found in the specified period")
        sys.exit(2)

    result = {
        "status": "success",
        "gauge_file": str(out_dir / filename),
        "gauge_id": GAUGE_ID,
        "n_records": len(dates),
        "period": f"{START_YEAR}-{END_YEAR}",
    }
    print(json.dumps(result, indent=2))
    return str(out_dir / filename)


def validate_outputs(output_path):
    if not Path(output_path).exists():
        logger.error(f"Gauge file not created: {output_path}")
        sys.exit(3)


if __name__ == "__main__":
    validate_inputs()
    try:
        output_path = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        import traceback; traceback.print_exc()
        sys.exit(2)
    validate_outputs(output_path)
    sys.exit(0)
