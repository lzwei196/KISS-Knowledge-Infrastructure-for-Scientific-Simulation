#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
Tool ID:      optimize_deficit_irrigation
Stage:        s5_irrigation
Description:  Runs multi-scenario SMT sweeps to find optimal deficit irrigation
              thresholds. Evaluates yield vs water use tradeoffs.
              This is AquaCrop's UNIQUE STRENGTH.

Inputs:
  - weather_df: Weather DataFrame (pandas.DataFrame)
  - soil: Soil object
  - crop: Crop object
  - iwc: InitialWaterContent object
  - sim_start: Start date 'YYYY/MM/DD'
  - sim_end: End date 'YYYY/MM/DD'
  - smt_values: List of SMT values to test (default: 0,10,20,...,100)
  - output_csv: Path for results CSV

Outputs:
  - CSV with columns: SMT, Yield_tha, ET_mm, Irrigation_mm, CWP_kg_m3, IWUE_kg_m3

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SMT_VALUES = list(range(0, 101, 10))  # 0, 10, 20, ..., 100
OUTPUT_CSV = ""  # Path for output CSV


def run_optimization(weather_df, soil, crop, iwc, sim_start, sim_end,
                     smt_values=None, output_csv=None):
    """
    Run deficit irrigation optimization sweep.

    Args:
        weather_df: AquaCrop weather DataFrame
        soil: Soil object
        crop: Crop object
        iwc: InitialWaterContent object
        sim_start: 'YYYY/MM/DD'
        sim_end: 'YYYY/MM/DD'
        smt_values: List of SMT thresholds to test (default 0-100 by 10)
        output_csv: Path to save results

    Returns:
        pandas DataFrame with optimization results
    """
    import pandas as pd
    from aquacrop import AquaCropModel, IrrigationManagement

    if smt_values is None:
        smt_values = list(range(0, 101, 10))

    results = []
    for smt in smt_values:
        logger.info(f"  Running SMT={smt}%...")
        if smt == 0:
            irr = IrrigationManagement(irrigation_method=0)  # rainfed
        else:
            irr = IrrigationManagement(irrigation_method=1, SMT=[smt] * 4)

        model = AquaCropModel(
            sim_start_time=sim_start,
            sim_end_time=sim_end,
            weather_df=weather_df,
            soil=soil,
            crop=crop,
            initial_water_content=iwc,
            irrigation_management=irr,
        )
        model.run_model(till_termination=True)

        stats = model.get_simulation_results()
        flux = model.get_water_flux()

        if stats is not False and len(stats) > 0:
            yld = stats['Dry yield (tonne/ha)'].iloc[0]
            irr_total = flux['IrrDay'].sum()
            et = flux['Es'].sum() + flux['Tr'].sum()
            cwp = (yld * 1000) / (et * 10) if et > 0 else 0.0
            iwue = (yld * 1000) / (irr_total * 10) if irr_total > 0 else float('inf')
        else:
            yld = irr_total = et = cwp = 0.0
            iwue = float('inf')

        results.append({
            'SMT': smt,
            'Yield_tha': round(yld, 3),
            'ET_mm': round(et, 1),
            'Irrigation_mm': round(irr_total, 1),
            'CWP_kg_m3': round(cwp, 3),
            'IWUE_kg_m3': round(iwue, 3) if iwue != float('inf') else 'inf',
        })

    df_results = pd.DataFrame(results)

    if output_csv:
        Path(output_csv).parent.mkdir(parents=True, exist_ok=True)
        df_results.to_csv(output_csv, index=False)
        logger.info(f"Results saved to: {output_csv}")

    # Find optimal
    finite_cwp = df_results[df_results['CWP_kg_m3'] > 0]
    if len(finite_cwp) > 0:
        best_idx = finite_cwp['CWP_kg_m3'].idxmax()
        best = finite_cwp.loc[best_idx]
        logger.info(f"Optimal CWP: SMT={best['SMT']}%, Yield={best['Yield_tha']} t/ha, "
                     f"CWP={best['CWP_kg_m3']} kg/m3, Irrigation={best['Irrigation_mm']} mm")

    return df_results


if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    logger.info("Usage: from optimize_deficit_irrigation import run_optimization")
    logger.info("       results = run_optimization(weather_df, soil, crop, iwc, start, end)")
    sys.exit(0)
