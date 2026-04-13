#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
Tool ID:      generate_weather_stations
Stage:        s3_weather_preparation
Description:  Create weather-sta.cli and wgn.wgn for SWAT+.

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys, os, logging, json
from pathlib import Path

PCP_CLI_PATH = ""
STATION_COORDS = []
SUBBASIN_CENTROIDS = []
OUTPUT_DIR = ""

if len(sys.argv) >= 5:
    PCP_CLI_PATH = sys.argv[1]
    STATION_COORDS = json.loads(sys.argv[2])
    SUBBASIN_CENTROIDS = json.loads(sys.argv[3])
    OUTPUT_DIR = sys.argv[4]

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def validate_inputs():
    errors = []
    if not PCP_CLI_PATH or not Path(PCP_CLI_PATH).exists():
        errors.append(f"pcp.cli not found: {PCP_CLI_PATH}")
    if not OUTPUT_DIR:
        errors.append("OUTPUT_DIR is not set")
    if errors:
        for e in errors: logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")

def process():
    output_dir = Path(OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Read station names from pcp.cli
    pcp_lines = Path(PCP_CLI_PATH).read_text().strip().split('\n')
    station_files = [l.strip() for l in pcp_lines[2:] if l.strip()]
    station_names = [Path(f).stem for f in station_files]

    # Write weather-sta.cli
    wsta_path = output_dir / "weather-sta.cli"
    with open(wsta_path, 'w') as f:
        f.write("weather-sta.cli: written by SWAT+ knowledge infrastructure\n")
        f.write("  name           pcp          tmp          slr          hmd          wnd          wgn\n")
        for name in station_names:
            f.write(f"  {name:<14s} {name:<12s} {name:<12s} {name:<12s} {name:<12s} {name:<12s} {name:<12s}\n")

    # Write wgn.wgn (weather generator with placeholder monthly stats)
    wgn_path = output_dir / "wgn.wgn"
    with open(wgn_path, 'w') as f:
        f.write("wgn.wgn: written by SWAT+ knowledge infrastructure\n")
        f.write("  name           lat        lon        elev       rain_yrs\n")
        for i, name in enumerate(station_names):
            lat = STATION_COORDS[i][0] if i < len(STATION_COORDS) else 0.0
            lon = STATION_COORDS[i][1] if i < len(STATION_COORDS) else 0.0
            f.write(f"  {name:<14s} {lat:10.5f} {lon:10.5f} {'0.0':>10s} {'30':>10s}\n")
            # 12 monthly rows with placeholder values
            f.write("  mon  tmp_max  tmp_min  tmp_sd_max tmp_sd_min pcp_mean pcp_sd   pcp_skew pcp_days "
                    "pcp_hhr  slr_mean dew_mean wnd_mean\n")
            for m in range(12):
                f.write(f"  {m+1:<5d} {25.0:8.1f} {15.0:8.1f} {5.0:10.1f} {3.0:10.1f} "
                        f"{50.0:8.1f} {30.0:8.1f} {1.5:8.1f} {10:8d} "
                        f"{30.0:8.1f} {18.0:8.1f} {10.0:8.1f} {2.5:8.1f}\n")

    logger.info(f"Created weather-sta.cli ({len(station_names)} stations) and wgn.wgn")
    return {
        "status": "success",
        "weather_sta_cli": str(wsta_path),
        "wgn_wgn": str(wgn_path),
        "n_stations": len(station_names)
    }

def validate_outputs(result):
    errors = []
    for key in ["weather_sta_cli", "wgn_wgn"]:
        if not Path(result[key]).exists():
            errors.append(f"Expected output not created: {result[key]}")
    if errors:
        for e in errors: logger.error(e)
        sys.exit(3)
    logger.info("Output validation passed.")

if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try: result = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}"); sys.exit(2)
    validate_outputs(result)
    print(json.dumps(result, indent=2)); sys.exit(0)
