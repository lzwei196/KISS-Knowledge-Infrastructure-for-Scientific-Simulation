#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
Tool ID:      prepare_weather_df
Stage:        s3_weather_prep
Description:  Creates weather DataFrame from file or VIC output. Ensures correct
              column names (MinTemp, MaxTemp, Precipitation, ReferenceET, Date),
              date parsing, ET0 clipping (>= 0.1), and no missing days.

Inputs:
  - source_path: Path to weather data file (string)
  - source_type: Format: 'aquacrop_txt', 'vic_forcing', 'csv' (string)
  - start_date: Optional start date filter YYYY/MM/DD (string)
  - end_date: Optional end date filter YYYY/MM/DD (string)

Outputs:
  - weather_df: pandas DataFrame with correct AquaCrop columns

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
SOURCE_PATH = ""              # Path to weather data file
SOURCE_TYPE = "aquacrop_txt"  # 'aquacrop_txt', 'vic_forcing', 'csv'
START_DATE = None             # Optional: 'YYYY/MM/DD'
END_DATE = None               # Optional: 'YYYY/MM/DD'

# Required AquaCrop weather columns
REQUIRED_COLUMNS = ['MinTemp', 'MaxTemp', 'Precipitation', 'ReferenceET', 'Date']


def validate_inputs():
    errors = []
    if not SOURCE_PATH or not Path(SOURCE_PATH).exists():
        errors.append(f"Source file not found: {SOURCE_PATH}")
    if SOURCE_TYPE not in ('aquacrop_txt', 'vic_forcing', 'csv', 'manual'):
        errors.append(f"Unknown source_type: {SOURCE_TYPE}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def validate_outputs(weather_df):
    import pandas as pd
    errors = []

    # Check required columns
    missing = set(REQUIRED_COLUMNS) - set(weather_df.columns)
    if missing:
        errors.append(f"Missing columns: {missing}")

    if not errors:
        # Check ET0 positivity
        if weather_df['ReferenceET'].min() <= 0:
            logger.warning("ReferenceET has values <= 0, clipping to 0.1")
            weather_df['ReferenceET'] = weather_df['ReferenceET'].clip(lower=0.1)

        # Check temperature ordering
        bad_temp = (weather_df['MaxTemp'] < weather_df['MinTemp']).sum()
        if bad_temp > 0:
            errors.append(f"{bad_temp} days have MaxTemp < MinTemp")

        # Check for NaN
        nan_count = weather_df[REQUIRED_COLUMNS[:4]].isna().sum().sum()
        if nan_count > 0:
            errors.append(f"{nan_count} NaN values in weather data")

        # Check date continuity
        date_diff = weather_df['Date'].diff().dropna()
        gaps = (date_diff > pd.Timedelta(days=1)).sum()
        if gaps > 0:
            errors.append(f"{gaps} gaps in daily time series")

    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(3)

    logger.info(f"Output validation passed: {len(weather_df)} days, "
                f"ET0 range [{weather_df['ReferenceET'].min():.1f}, {weather_df['ReferenceET'].max():.1f}] mm/day")


def process():
    import pandas as pd

    if SOURCE_TYPE == 'aquacrop_txt':
        try:
            from aquacrop.utils import prepare_weather
            weather_df = prepare_weather(SOURCE_PATH)
        except ImportError:
            logger.error("aquacrop not installed. Run: pip install aquacrop")
            sys.exit(2)

    elif SOURCE_TYPE == 'csv':
        weather_df = pd.read_csv(SOURCE_PATH, parse_dates=['Date'])
        # Attempt standard column renaming
        rename_map = {
            'tmin': 'MinTemp', 'Tmin': 'MinTemp', 'min_temp': 'MinTemp',
            'tmax': 'MaxTemp', 'Tmax': 'MaxTemp', 'max_temp': 'MaxTemp',
            'precip': 'Precipitation', 'Precip': 'Precipitation', 'prcp': 'Precipitation',
            'et0': 'ReferenceET', 'ETo': 'ReferenceET', 'ET0': 'ReferenceET', 'ref_et': 'ReferenceET',
            'date': 'Date',
        }
        weather_df = weather_df.rename(columns=rename_map)

    elif SOURCE_TYPE == 'vic_forcing':
        logger.info("VIC forcing conversion requires ET0 computation -- use compute_eto_penman_monteith tool first")
        sys.exit(2)

    # Filter by date range if specified
    if START_DATE:
        start = pd.Timestamp(START_DATE.replace('/', '-'))
        weather_df = weather_df[weather_df['Date'] >= start]
    if END_DATE:
        end = pd.Timestamp(END_DATE.replace('/', '-'))
        weather_df = weather_df[weather_df['Date'] <= end]

    weather_df = weather_df.sort_values('Date').reset_index(drop=True)

    # Clip ET0
    if 'ReferenceET' in weather_df.columns:
        weather_df['ReferenceET'] = weather_df['ReferenceET'].clip(lower=0.1)

    return weather_df


if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try:
        weather_df = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        sys.exit(2)
    validate_outputs(weather_df)
    logger.info("Tool completed successfully.")
    sys.exit(0)
