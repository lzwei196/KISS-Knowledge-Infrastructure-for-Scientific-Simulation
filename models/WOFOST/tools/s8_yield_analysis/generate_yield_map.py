#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      generate_yield_map
Stage:        s8_yield_analysis
Description:  Create spatial yield map visualization from gridded WOFOST output.
              Delegates to HydroCraft's plot_crop_yield_map.py for consistent styling.

Inputs:
  - GRIDDED_YIELD_CSV: gridded yield CSV with lat, lon, twso_kgha columns
  - SHP_PATH: basin boundary shapefile (optional)
  - OUTPUT_PNG: output map PNG path
  - TITLE: map title
  - VALUE_COL: column to plot (default: twso_kgha)

Outputs:
  - Yield map PNG

Exit codes:
  0 — success, 1 — input error, 2 — processing error
"""

import sys
import os
import json
import logging
import subprocess
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

GRIDDED_YIELD_CSV = ""
SHP_PATH = ""
OUTPUT_PNG = ""
TITLE = "WOFOST Yield"
VALUE_COL = "twso_kgha"
LABEL = "Yield (kg/ha)"

# Path to HydroCraft plotting tool
PLOT_SCRIPT = "/mnt/disk1/Hydrocraft_server/skills/plot/plot_crop_yield_map.py"
PYTHON = "/mnt/disk1/Hydrocraft_server/python_env/bin/python"


def validate_inputs():
    errors = []
    if not GRIDDED_YIELD_CSV or not Path(GRIDDED_YIELD_CSV).exists():
        errors.append(f"Gridded yield CSV not found: {GRIDDED_YIELD_CSV}")
    if not OUTPUT_PNG:
        errors.append("OUTPUT_PNG not set")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)


def process():
    """Generate yield map using HydroCraft plotting tool."""
    cmd = [PYTHON, PLOT_SCRIPT,
           "--csv", GRIDDED_YIELD_CSV,
           "--value_col", VALUE_COL,
           "--title", TITLE,
           "--label", LABEL,
           "--output", OUTPUT_PNG]

    if SHP_PATH and Path(SHP_PATH).exists():
        cmd.extend(["--shp", SHP_PATH])

    os.makedirs(os.path.dirname(OUTPUT_PNG) or '.', exist_ok=True)

    # Check if plot script exists
    if not Path(PLOT_SCRIPT).exists():
        logger.warning(f"HydroCraft plot script not found at {PLOT_SCRIPT}")
        logger.info("Generating basic yield map with matplotlib fallback...")

        # Fallback: simple matplotlib plot
        import pandas as pd
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt

        df = pd.read_csv(GRIDDED_YIELD_CSV)
        fig, ax = plt.subplots(1, 1, figsize=(10, 8))
        scatter = ax.scatter(df['lon'], df['lat'], c=df[VALUE_COL],
                            cmap='RdYlGn', s=100, edgecolors='black', linewidth=0.5)
        plt.colorbar(scatter, label=LABEL)
        ax.set_xlabel('Longitude')
        ax.set_ylabel('Latitude')
        ax.set_title(TITLE)
        plt.tight_layout()
        plt.savefig(OUTPUT_PNG, dpi=150, bbox_inches='tight')
        plt.close()
        logger.info(f"Fallback map saved: {OUTPUT_PNG}")
        return OUTPUT_PNG

    logger.info(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error(f"Plot script failed: {result.stderr}")
        sys.exit(2)

    logger.info(f"Yield map saved: {OUTPUT_PNG}")
    return OUTPUT_PNG


if __name__ == "__main__":
    if len(sys.argv) >= 3:
        GRIDDED_YIELD_CSV = sys.argv[1]
        OUTPUT_PNG = sys.argv[2]
    if len(sys.argv) >= 4:
        TITLE = sys.argv[3]
    if len(sys.argv) >= 5:
        SHP_PATH = sys.argv[4]

    validate_inputs()
    try:
        result = process()
    except Exception as e:
        logger.error(f"Failed: {e}")
        sys.exit(2)
    print(json.dumps({"status": "success", "output_file": result}))
    sys.exit(0)
