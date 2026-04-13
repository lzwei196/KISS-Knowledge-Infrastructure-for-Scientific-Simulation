#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
Tool ID:      compute_water_productivity
Stage:        s10_water_productivity
Description:  Computes Crop Water Productivity (CWP, kg/m3), Irrigation Water Use
              Efficiency (IWUE, kg/m3), and Water Footprint (WF, m3/tonne) from
              AquaCrop simulation outputs.

Inputs:
  - final_stats: DataFrame from model.get_simulation_results()
  - water_flux: DataFrame from model.get_water_flux()

Outputs:
  - JSON with per-season WP metrics

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import json
import logging
import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def compute_wp(final_stats, water_flux):
    """
    Compute water productivity metrics from AquaCrop output.

    Args:
        final_stats: DataFrame from model.get_simulation_results()
        water_flux: DataFrame from model.get_water_flux()

    Returns:
        list of dicts, one per season, with WP metrics
    """
    results = []

    # Group water flux by season
    seasonal = water_flux.groupby('season_counter').agg({
        'Es': 'sum',
        'Tr': 'sum',
        'IrrDay': 'sum',
        'Runoff': 'sum',
        'DeepPerc': 'sum',
    }).reset_index()

    for i, row in final_stats.iterrows():
        season = int(row.get('Season', i + 1))
        yield_tha = row['Dry yield (tonne/ha)']
        yield_kg_ha = yield_tha * 1000  # kg/ha
        irr_mm = row.get('Seasonal irrigation (mm)', 0)

        # Find matching water flux season
        flux_row = seasonal[seasonal['season_counter'] == season]
        if len(flux_row) == 0:
            flux_row = seasonal.iloc[[i]] if i < len(seasonal) else None

        if flux_row is not None and len(flux_row) > 0:
            es = flux_row['Es'].values[0]
            tr = flux_row['Tr'].values[0]
            et = es + tr
            irr_total = flux_row['IrrDay'].values[0]
        else:
            es = tr = et = irr_total = 0

        # CWP: Crop Water Productivity (kg yield per m3 water consumed)
        # 1 mm over 1 ha = 10 m3, so CWP = yield_kg_ha / (ET_mm * 10)
        cwp_et = yield_kg_ha / (et * 10) if et > 0 else 0.0
        cwp_tr = yield_kg_ha / (tr * 10) if tr > 0 else 0.0  # Transpiration-only WP

        # IWUE: Irrigation Water Use Efficiency
        iwue = yield_kg_ha / (irr_total * 10) if irr_total > 0 else float('inf')

        # Water Footprint (m3/tonne)
        wf_total = (et * 10) / yield_tha if yield_tha > 0 else float('inf')
        wf_green = (tr * 10) / yield_tha if yield_tha > 0 else float('inf')
        wf_blue = (irr_total * 10) / yield_tha if yield_tha > 0 else float('inf')

        season_result = {
            'season': season,
            'yield_tha': round(yield_tha, 3),
            'ET_mm': round(et, 1),
            'Es_mm': round(es, 1),
            'Tr_mm': round(tr, 1),
            'irrigation_mm': round(irr_total, 1),
            'CWP_ET_kg_m3': round(cwp_et, 3),
            'CWP_Tr_kg_m3': round(cwp_tr, 3),
            'IWUE_kg_m3': round(iwue, 3) if iwue != float('inf') else 'inf',
            'WF_total_m3_t': round(wf_total, 1) if wf_total != float('inf') else 'inf',
            'WF_green_m3_t': round(wf_green, 1) if wf_green != float('inf') else 'inf',
            'WF_blue_m3_t': round(wf_blue, 1) if wf_blue != float('inf') else 'inf',
            'evap_fraction': round(es / et, 3) if et > 0 else 0.0,
        }
        results.append(season_result)

    print(json.dumps(results, indent=2))
    return results


if __name__ == "__main__":
    logger.info("Usage: from compute_water_productivity import compute_wp")
    logger.info("       wp = compute_wp(final_stats, water_flux)")
    sys.exit(0)
