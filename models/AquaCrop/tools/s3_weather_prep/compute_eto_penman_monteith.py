#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
Tool ID:      compute_eto_penman_monteith
Stage:        s3_weather_prep
Description:  Computes FAO-56 Penman-Monteith reference evapotranspiration (ET0)
              from daily meteorological data. Required when source data does not
from ki_tools_common.humidity import saturation_vapor_pressure
              include ET0 (VIC, CMFD, MSWX, station data).

Reference:    Allen et al. (1998) FAO Irrigation and Drainage Paper 56

Inputs:
  - tmin: Daily minimum temperature (deg C), numpy array
  - tmax: Daily maximum temperature (deg C), numpy array
  - solar_rad: Daily solar radiation (MJ/m2/day), numpy array
  - wind: Wind speed at 2m height (m/s), numpy array
  - lat: Latitude (degrees), float
  - elevation: Elevation (m), float
  - doy: Day of year (1-366), numpy array (optional, computed from dates)
  - rh_min: Minimum relative humidity (%), optional
  - rh_max: Maximum relative humidity (%), optional

Outputs:
  - et0: Reference evapotranspiration (mm/day), numpy array

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import logging
import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def compute_et0_fao56(tmin, tmax, solar_rad, wind, lat, elevation, doy,
                       rh_min=None, rh_max=None):
    """
    FAO-56 Penman-Monteith reference ET0 computation.

    Args:
        tmin: Daily min temperature (C), array
        tmax: Daily max temperature (C), array
        solar_rad: Solar radiation (MJ/m2/day), array
        wind: Wind speed at 2m (m/s), array
        lat: Latitude (degrees)
        elevation: Elevation (m)
        doy: Day of year (1-366), array
        rh_min: Min relative humidity (%), optional
        rh_max: Max relative humidity (%), optional

    Returns:
        et0: Reference ET (mm/day), array
    """
    tmin = np.asarray(tmin, dtype=float)
    tmax = np.asarray(tmax, dtype=float)
    solar_rad = np.asarray(solar_rad, dtype=float)
    wind = np.asarray(wind, dtype=float)
    doy = np.asarray(doy, dtype=float)

    # Mean temperature
    tmean = (tmin + tmax) / 2.0

    # Atmospheric pressure (kPa)
    P = 101.3 * ((293.0 - 0.0065 * elevation) / 293.0) ** 5.26

    # Psychrometric constant (kPa/C)
    gamma = 0.000665 * P

    # Saturation vapor pressure (kPa)
    es_tmin = 0.6108 * np.exp(17.27 * tmin / (tmin + 237.3))  # TODO: consider ki_tools_common.humidity.saturation_vapor_pressure
    es_tmax = 0.6108 * np.exp(17.27 * tmax / (tmax + 237.3))  # TODO: consider ki_tools_common.humidity.saturation_vapor_pressure
    es = (es_tmin + es_tmax) / 2.0

    # Actual vapor pressure (kPa)
    if rh_min is not None and rh_max is not None:
        ea = (es_tmin * np.asarray(rh_max) / 100.0 + es_tmax * np.asarray(rh_min) / 100.0) / 2.0
    else:
        # Estimate from Tmin (FAO-56 equation 48)
        ea = es_tmin

    # Slope of saturation vapor pressure curve (kPa/C)
    delta = 4098.0 * (0.6108 * np.exp(17.27 * tmean / (tmean + 237.3))) / (tmean + 237.3) ** 2  # TODO: consider ki_tools_common.humidity.saturation_vapor_pressure

    # Extraterrestrial radiation (MJ/m2/day)
    lat_rad = lat * np.pi / 180.0
    dr = 1.0 + 0.033 * np.cos(2.0 * np.pi * doy / 365.0)
    delta_s = 0.409 * np.sin(2.0 * np.pi * doy / 365.0 - 1.39)
    ws = np.arccos(-np.tan(lat_rad) * np.tan(delta_s))
    Ra = (24.0 * 60.0 / np.pi) * 0.0820 * dr * (
        ws * np.sin(lat_rad) * np.sin(delta_s) +
        np.cos(lat_rad) * np.cos(delta_s) * np.sin(ws)
    )

    # Clear-sky solar radiation
    Rso = (0.75 + 2e-5 * elevation) * Ra

    # Net shortwave radiation
    Rns = (1 - 0.23) * solar_rad  # albedo = 0.23

    # Net longwave radiation
    sigma = 4.903e-9  # Stefan-Boltzmann (MJ/m2/day/K4)
    Rnl = sigma * ((tmax + 273.16) ** 4 + (tmin + 273.16) ** 4) / 2.0 * \
          (0.34 - 0.14 * np.sqrt(np.maximum(ea, 0.0))) * \
          (1.35 * np.minimum(solar_rad / np.maximum(Rso, 0.1), 1.0) - 0.35)

    # Net radiation
    Rn = Rns - Rnl

    # Soil heat flux (assumed 0 for daily)
    G = 0.0

    # FAO-56 Penman-Monteith equation
    numerator = 0.408 * delta * (Rn - G) + gamma * (900.0 / (tmean + 273.0)) * wind * (es - ea)
    denominator = delta + gamma * (1.0 + 0.34 * wind)

    et0 = numerator / denominator

    # Clip to minimum 0.1
    et0 = np.maximum(et0, 0.1)

    return et0


if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    logger.info("This tool provides the compute_et0_fao56() function.")
    logger.info("Usage: from compute_eto_penman_monteith import compute_et0_fao56")
    logger.info("       et0 = compute_et0_fao56(tmin, tmax, solar_rad, wind, lat, elev, doy)")
    sys.exit(0)
