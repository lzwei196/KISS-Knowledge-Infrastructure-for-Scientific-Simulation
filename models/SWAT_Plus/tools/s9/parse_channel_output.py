#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
Tool ID:      parse_channel_output
Stage:        s9_output_parsing
Description:  Parse channel_sd_day.txt for discharge, sediment, and nutrient loads.

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys, os, logging, json
from pathlib import Path
from datetime import datetime, timedelta

CHANNEL_SD_PATH = ""
CHANNEL_ID = 1
START_DATE = ""
END_DATE = ""

if len(sys.argv) >= 5:
    CHANNEL_SD_PATH = sys.argv[1]
    CHANNEL_ID = int(sys.argv[2])
    START_DATE = sys.argv[3]
    END_DATE = sys.argv[4]

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def validate_inputs():
    errors = []
    if not CHANNEL_SD_PATH or not Path(CHANNEL_SD_PATH).exists():
        errors.append(f"channel_sd file not found: {CHANNEL_SD_PATH}")
    if CHANNEL_ID < 1:
        errors.append(f"Invalid channel ID: {CHANNEL_ID}")
    if errors:
        for e in errors: logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")

def process():
    lines = Path(CHANNEL_SD_PATH).read_text().strip().split('\n')

    # Parse header to find column indices
    header = lines[0].split()
    col_map = {name: idx for idx, name in enumerate(header)}

    required_cols = ["jday", "mon", "day", "yr", "unit", "flo_out"]
    for col in required_cols:
        if col not in col_map:
            raise ValueError(f"Required column '{col}' not found in header. Available: {header}")

    # Parse data
    discharge = []
    sediment = []
    nutrients = {"orgn": [], "no3": [], "solp": [], "sedp": []}

    start = datetime.strptime(START_DATE, "%Y-%m-%d") if START_DATE else None
    end = datetime.strptime(END_DATE, "%Y-%m-%d") if END_DATE else None

    for line in lines[1:]:
        parts = line.split()
        if len(parts) < len(header): continue

        try:
            unit = int(parts[col_map["unit"]])
            if unit != CHANNEL_ID: continue

            yr = int(parts[col_map["yr"]])
            mon = int(parts[col_map["mon"]])
            day = int(parts[col_map["day"]])
            date = datetime(yr, mon, day)

            if start and date < start: continue
            if end and date > end: continue

            flo = float(parts[col_map["flo_out"]])
            discharge.append({"date": date.strftime("%Y-%m-%d"), "flo_out_m3s": flo})

            if "sed_out" in col_map:
                sed = float(parts[col_map["sed_out"]])
                sediment.append({"date": date.strftime("%Y-%m-%d"), "sed_out_tons": sed})

            for nut_var in ["orgn_out", "no3_out", "solp_out", "sedp_out"]:
                if nut_var in col_map:
                    val = float(parts[col_map[nut_var]])
                    key = nut_var.replace("_out", "")
                    nutrients[key].append({"date": date.strftime("%Y-%m-%d"), "value_kg": val})

        except (ValueError, IndexError):
            continue

    # Summary statistics
    flo_values = [d["flo_out_m3s"] for d in discharge]
    summary = {
        "n_days": len(discharge),
        "mean_discharge_m3s": sum(flo_values) / len(flo_values) if flo_values else 0,
        "max_discharge_m3s": max(flo_values) if flo_values else 0,
        "min_discharge_m3s": min(flo_values) if flo_values else 0,
    }

    logger.info(f"Parsed {len(discharge)} days for channel {CHANNEL_ID}. "
                f"Mean Q: {summary['mean_discharge_m3s']:.2f} m3/s")

    return {
        "status": "success",
        "channel_id": CHANNEL_ID,
        "summary": summary,
        "discharge": discharge[:10],  # First 10 for preview
        "n_total_records": len(discharge)
    }

def validate_outputs(result):
    if result["n_total_records"] == 0:
        logger.error(f"No data found for channel {CHANNEL_ID}"); sys.exit(3)
    logger.info("Output validation passed.")

if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try: result = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}"); sys.exit(2)
    validate_outputs(result)
    print(json.dumps(result, indent=2)); sys.exit(0)
