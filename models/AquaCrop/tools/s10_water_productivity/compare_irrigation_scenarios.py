#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
Tool ID:      compare_irrigation_scenarios
Stage:        s10_water_productivity
Description:  Runs and compares multiple irrigation strategies (rainfed, full,
              deficit at various SMT levels) for yield-water tradeoff analysis.
              Produces comparison table and yield-vs-water plot.

Inputs:
  - weather_df: Weather DataFrame
  - soil: Soil object
  - crop: Crop object
  - iwc: InitialWaterContent object
  - sim_start, sim_end: Simulation dates
  - scenarios: List of scenario dicts (name, method, params)
  - output_dir: Directory for output files

Outputs:
  - scenario_comparison.csv: Table with all scenarios
  - scenario_comparison.png: Yield vs irrigation plot

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def compare_scenarios(weather_df, soil, crop, iwc, sim_start, sim_end,
                      scenarios=None, output_dir=None):
    """
    Run and compare multiple irrigation scenarios.

    Args:
        weather_df: AquaCrop weather DataFrame
        soil: Soil object
        crop: Crop object
        iwc: InitialWaterContent object
        sim_start: 'YYYY/MM/DD'
        sim_end: 'YYYY/MM/DD'
        scenarios: List of dicts, each with 'name', 'irrigation_method', and optional params
        output_dir: Directory for output files

    Default scenarios if none provided:
        - Rainfed (method=0)
        - Deficit 50% (method=1, SMT=[50]*4)
        - Deficit 70% (method=1, SMT=[70]*4)
        - Full irrigation (method=4, NetIrrSMT=100)

    Returns:
        pandas DataFrame with comparison results
    """
    import pandas as pd
    from aquacrop import AquaCropModel, IrrigationManagement

    if scenarios is None:
        scenarios = [
            {'name': 'Rainfed', 'irrigation_method': 0},
            {'name': 'Deficit_30', 'irrigation_method': 1, 'SMT': [30]*4},
            {'name': 'Deficit_50', 'irrigation_method': 1, 'SMT': [50]*4},
            {'name': 'Deficit_70', 'irrigation_method': 1, 'SMT': [70]*4},
            {'name': 'Deficit_90', 'irrigation_method': 1, 'SMT': [90]*4},
            {'name': 'Full_Irrigation', 'irrigation_method': 4, 'NetIrrSMT': 100},
        ]

    results = []
    for scenario in scenarios:
        name = scenario.pop('name', f"Scenario_{len(results)}")
        method = scenario.pop('irrigation_method')
        logger.info(f"Running scenario: {name} (method={method})")

        irr = IrrigationManagement(irrigation_method=method, **scenario)
        # Restore popped keys for potential re-use
        scenario['name'] = name
        scenario['irrigation_method'] = method

        model = AquaCropModel(
            sim_start_time=sim_start,
            sim_end_time=sim_end,
            weather_df=weather_df,
            soil=soil, crop=crop,
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
            tr = flux['Tr'].sum()
            cwp = (yld * 1000) / (et * 10) if et > 0 else 0.0
        else:
            yld = irr_total = et = tr = cwp = 0.0

        results.append({
            'Scenario': name,
            'Method': method,
            'Yield_tha': round(yld, 3),
            'ET_mm': round(et, 1),
            'Tr_mm': round(tr, 1),
            'Irrigation_mm': round(irr_total, 1),
            'CWP_kg_m3': round(cwp, 3),
        })

    df = pd.DataFrame(results)

    if output_dir:
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        csv_path = os.path.join(output_dir, 'scenario_comparison.csv')
        df.to_csv(csv_path, index=False)
        logger.info(f"Saved comparison: {csv_path}")

        # Generate plot
        try:
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt

            fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

            # Yield vs Irrigation
            ax1.bar(df['Scenario'], df['Yield_tha'], color='steelblue')
            ax1.set_ylabel('Dry Yield (tonne/ha)')
            ax1.set_title('Yield by Irrigation Scenario')
            ax1.tick_params(axis='x', rotation=45)

            # CWP comparison
            ax2.bar(df['Scenario'], df['CWP_kg_m3'], color='seagreen')
            ax2.set_ylabel('CWP (kg/m3)')
            ax2.set_title('Crop Water Productivity')
            ax2.tick_params(axis='x', rotation=45)

            plt.tight_layout()
            plot_path = os.path.join(output_dir, 'scenario_comparison.png')
            plt.savefig(plot_path, dpi=150)
            plt.close()
            logger.info(f"Saved plot: {plot_path}")
        except Exception as e:
            logger.warning(f"Could not generate plot: {e}")

    print(json.dumps(results, indent=2))
    return df


if __name__ == "__main__":
    logger.info("Usage: from compare_irrigation_scenarios import compare_scenarios")
    logger.info("       df = compare_scenarios(weather, soil, crop, iwc, start, end, scenarios, output_dir)")
    sys.exit(0)
