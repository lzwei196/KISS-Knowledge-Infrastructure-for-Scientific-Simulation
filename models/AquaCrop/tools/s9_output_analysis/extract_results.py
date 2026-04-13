#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
Tool ID:      extract_results
Stage:        s9_output_analysis
Description:  Extracts all four output types (final_stats, water_flux, water_storage,
              crop_growth) from executed model into DataFrames and saves as CSV files.

Inputs:
  - model: Executed AquaCropModel (after run_model)
  - output_dir: Directory for output CSV files

Outputs:
  - final_stats.csv: Seasonal summary
  - water_flux.csv: Daily water balance
  - crop_growth.csv: Daily crop growth
  - water_storage.csv: Daily soil water per compartment

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

OUTPUT_DIR = ""  # Set before running


def extract_and_save(model, output_dir):
    """
    Extract all outputs from executed AquaCrop model and save to CSV.

    Args:
        model: AquaCropModel (after run_model)
        output_dir: Directory path for CSV files

    Returns:
        dict with DataFrames and file paths
    """
    import pandas as pd

    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # Extract outputs
    final_stats = model.get_simulation_results()
    water_flux = model.get_water_flux()
    crop_growth = model.get_crop_growth()
    water_storage = model.get_water_storage()

    results = {}

    # Save final stats
    if final_stats is not False and final_stats is not None:
        path = os.path.join(output_dir, 'final_stats.csv')
        final_stats.to_csv(path, index=False)
        results['final_stats'] = {'path': path, 'rows': len(final_stats)}
        logger.info(f"Saved final_stats: {path} ({len(final_stats)} seasons)")
    else:
        logger.warning("No final_stats available (model may not have finished)")

    # Save water flux
    if water_flux is not None and hasattr(water_flux, 'to_csv'):
        path = os.path.join(output_dir, 'water_flux.csv')
        water_flux.to_csv(path, index=False)
        results['water_flux'] = {'path': path, 'rows': len(water_flux)}
        logger.info(f"Saved water_flux: {path} ({len(water_flux)} days)")

    # Save crop growth
    if crop_growth is not None and hasattr(crop_growth, 'to_csv'):
        path = os.path.join(output_dir, 'crop_growth.csv')
        crop_growth.to_csv(path, index=False)
        results['crop_growth'] = {'path': path, 'rows': len(crop_growth)}
        logger.info(f"Saved crop_growth: {path} ({len(crop_growth)} days)")

    # Save water storage
    if water_storage is not None and hasattr(water_storage, 'to_csv'):
        path = os.path.join(output_dir, 'water_storage.csv')
        water_storage.to_csv(path, index=False)
        results['water_storage'] = {'path': path, 'rows': len(water_storage)}
        logger.info(f"Saved water_storage: {path} ({len(water_storage)} days)")

    # Validation checks
    if final_stats is not False and len(final_stats) > 0:
        dry_yield = final_stats['Dry yield (tonne/ha)'].iloc[0]
        if dry_yield == 0:
            logger.warning("DIAGNOSTIC: Dry yield is 0 -- see triplet dt_014")
        elif dry_yield > 25:
            logger.warning(f"DIAGNOSTIC: Dry yield ({dry_yield:.1f} t/ha) unusually high")

    print(json.dumps(results, indent=2))
    return results


if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    logger.info("Usage: from extract_results import extract_and_save")
    logger.info("       results = extract_and_save(model, 'outputs/run1/aquacrop/')")
    sys.exit(0)
