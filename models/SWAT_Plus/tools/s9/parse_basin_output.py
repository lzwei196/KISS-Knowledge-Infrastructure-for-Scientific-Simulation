#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
Tool ID:      parse_basin_output
Stage:        s9_output_parsing
Description:  Parse basin-level SWAT+ output files (basin_wb, basin_nb, basin_ls).

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys, os, logging, json
from pathlib import Path

TXTINOUT_DIR = ""
OUTPUT_TYPE = "basin_wb"  # basin_wb, basin_nb, basin_ls, basin_pw
FREQUENCY = "day"  # day, mon, yr, aa

if len(sys.argv) >= 3:
    TXTINOUT_DIR = sys.argv[1]
    OUTPUT_TYPE = sys.argv[2]
if len(sys.argv) >= 4:
    FREQUENCY = sys.argv[3]

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def validate_inputs():
    errors = []
    fname = f"{OUTPUT_TYPE}_{FREQUENCY}.txt"
    if not TXTINOUT_DIR or not (Path(TXTINOUT_DIR) / fname).exists():
        errors.append(f"Output file not found: {fname} in {TXTINOUT_DIR}")
    if errors:
        for e in errors: logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")

def process():
    fname = f"{OUTPUT_TYPE}_{FREQUENCY}.txt"
    filepath = Path(TXTINOUT_DIR) / fname
    lines = filepath.read_text().strip().split('\n')

    header = lines[0].split()
    data = []

    for line in lines[1:]:
        parts = line.split()
        if len(parts) < len(header): continue
        record = {}
        for i, col_name in enumerate(header):
            try:
                record[col_name] = float(parts[i])
            except ValueError:
                record[col_name] = parts[i]
        data.append(record)

    # Summary
    numeric_cols = [k for k in header if k not in ["jday", "mon", "day", "yr", "unit", "gis_id", "name"]]
    summary = {}
    for col in numeric_cols:
        values = [r[col] for r in data if isinstance(r.get(col), (int, float))]
        if values:
            summary[col] = {
                "mean": sum(values) / len(values),
                "min": min(values),
                "max": max(values)
            }

    logger.info(f"Parsed {len(data)} records from {fname}")
    return {
        "status": "success",
        "file": fname,
        "n_records": len(data),
        "columns": header,
        "summary": summary,
        "sample_data": data[:5]
    }

def validate_outputs(result):
    if result["n_records"] == 0:
        logger.error("No data records found"); sys.exit(3)
    logger.info("Output validation passed.")

if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try: result = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}"); sys.exit(2)
    validate_outputs(result)
    print(json.dumps(result, indent=2)); sys.exit(0)
