#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
Tool ID:      validate_weather_df
Stage:        s3_weather_prep
Description:  Validates weather DataFrame format, column presence (MinTemp, MaxTemp,
              Precipitation, ReferenceET, Date), value ranges, date continuity,
              and ET0 positivity.

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import json
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = ['MinTemp', 'MaxTemp', 'Precipitation', 'ReferenceET', 'Date']


def validate_weather(weather_df):
    """Validate AquaCrop weather DataFrame. Returns dict with results."""
    import pandas as pd
    checks = []

    # Column presence
    missing = set(REQUIRED_COLUMNS) - set(weather_df.columns)
    checks.append({
        "check": "All required columns present",
        "status": "PASS" if not missing else "FAIL",
        "values": f"missing={list(missing)}" if missing else "all present",
        "severity": "fatal"
    })

    if not missing:
        # ET0 positivity
        et0_min = weather_df['ReferenceET'].min()
        checks.append({
            "check": "ReferenceET > 0",
            "status": "PASS" if et0_min > 0 else "FAIL",
            "values": f"min={et0_min:.3f}",
            "severity": "fatal"
        })

        # Temperature ordering
        bad_temp = (weather_df['MaxTemp'] < weather_df['MinTemp']).sum()
        checks.append({
            "check": "MaxTemp >= MinTemp",
            "status": "PASS" if bad_temp == 0 else "WARN",
            "values": f"{bad_temp} violations",
            "severity": "warning"
        })

        # Precipitation non-negative
        neg_precip = (weather_df['Precipitation'] < 0).sum()
        checks.append({
            "check": "Precipitation >= 0",
            "status": "PASS" if neg_precip == 0 else "FAIL",
            "values": f"{neg_precip} negative values",
            "severity": "fatal"
        })

        # NaN check
        nan_count = weather_df[REQUIRED_COLUMNS[:4]].isna().sum().sum()
        checks.append({
            "check": "No NaN values",
            "status": "PASS" if nan_count == 0 else "FAIL",
            "values": f"{nan_count} NaN values",
            "severity": "fatal"
        })

        # Date continuity
        date_diff = weather_df['Date'].diff().dropna()
        gaps = (date_diff > pd.Timedelta(days=1)).sum()
        checks.append({
            "check": "No gaps in daily dates",
            "status": "PASS" if gaps == 0 else "WARN",
            "values": f"{gaps} gaps",
            "severity": "warning"
        })

        # Temperature range
        t_min_global = weather_df['MinTemp'].min()
        t_max_global = weather_df['MaxTemp'].max()
        reasonable = -60 < t_min_global and t_max_global < 60
        checks.append({
            "check": "Temperature range reasonable (-60 to 60 C)",
            "status": "PASS" if reasonable else "WARN",
            "values": f"range=[{t_min_global:.1f}, {t_max_global:.1f}]",
            "severity": "warning" if reasonable else "fatal"
        })

    report = {
        "n_days": len(weather_df),
        "date_range": f"{weather_df['Date'].min()} to {weather_df['Date'].max()}" if 'Date' in weather_df.columns else "unknown",
        "checks": checks,
        "all_pass": all(c["status"] == "PASS" for c in checks),
    }
    print(json.dumps(report, indent=2, default=str))
    return report


if __name__ == "__main__":
    logger.info("Usage: from validate_weather_df import validate_weather; validate_weather(df)")
    sys.exit(0)
