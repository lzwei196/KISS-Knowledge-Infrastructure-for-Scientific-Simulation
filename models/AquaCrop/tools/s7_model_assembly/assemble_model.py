#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
Tool ID:      assemble_model
Stage:        s7_model_assembly
Description:  Combines all components into AquaCropModel. Validates date format
              (MUST use slashes YYYY/MM/DD, not dashes) and component compatibility.

Inputs:
  - sim_start_time: 'YYYY/MM/DD'
  - sim_end_time: 'YYYY/MM/DD'
  - weather_df, soil, crop, initial_water_content
  - Optional: irrigation_management, field_management, off_season

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import json
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def assemble(sim_start_time, sim_end_time, weather_df, soil, crop,
             initial_water_content, irrigation_management=None,
             field_management=None, off_season=False):
    """
    Assemble AquaCropModel with pre-flight validation.

    CRITICAL: Dates MUST use slashes ('YYYY/MM/DD'), NOT dashes.

    Returns: AquaCropModel instance
    """
    # Pre-flight: date format
    for date_str, name in [(sim_start_time, 'sim_start_time'), (sim_end_time, 'sim_end_time')]:
        if '-' in date_str and '/' not in date_str:
            logger.error(f"{name}='{date_str}' uses dashes. AquaCrop requires slashes: YYYY/MM/DD")
            # Auto-fix
            fixed = date_str.replace('-', '/')
            logger.info(f"Auto-correcting to: {fixed}")
            if name == 'sim_start_time':
                sim_start_time = fixed
            else:
                sim_end_time = fixed

    # Pre-flight: weather coverage
    import pandas as pd
    start_ts = pd.Timestamp(sim_start_time.replace('/', '-'))
    end_ts = pd.Timestamp(sim_end_time.replace('/', '-'))
    if weather_df['Date'].min() > start_ts:
        logger.warning(f"Weather starts {weather_df['Date'].min()} but sim starts {start_ts}")
    if weather_df['Date'].max() < end_ts:
        logger.warning(f"Weather ends {weather_df['Date'].max()} but sim ends {end_ts}")

    # Pre-flight: soil depth vs crop root depth
    if hasattr(soil, 'zSoil') and hasattr(crop, 'Zmax'):
        if soil.zSoil < crop.Zmax:
            logger.warning(f"Soil depth ({soil.zSoil}m) < crop max root depth ({crop.Zmax}m). "
                           f"Root growth will be limited.")

    # Assemble
    try:
        from aquacrop import AquaCropModel
    except ImportError:
        logger.error("aquacrop not installed. Run: pip install aquacrop")
        sys.exit(2)

    kwargs = {
        'sim_start_time': sim_start_time,
        'sim_end_time': sim_end_time,
        'weather_df': weather_df,
        'soil': soil,
        'crop': crop,
        'initial_water_content': initial_water_content,
        'off_season': off_season,
    }
    if irrigation_management is not None:
        kwargs['irrigation_management'] = irrigation_management
    if field_management is not None:
        kwargs['field_management'] = field_management

    model = AquaCropModel(**kwargs)
    logger.info(f"AquaCropModel assembled: {sim_start_time} to {sim_end_time}, "
                f"crop={crop.Name}, soil={soil.Name}")
    return model


if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    logger.info("Usage: from assemble_model import assemble")
    logger.info("       model = assemble(start, end, weather, soil, crop, iwc, irr, field)")
    sys.exit(0)
