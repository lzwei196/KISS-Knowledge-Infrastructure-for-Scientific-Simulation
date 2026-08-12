#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      configure_pcse_engine
Stage:        s5_engine_config
Description:  Assemble ParameterProvider from crop/soil/site dicts,
              select engine class (PP/WLP_FD/WLP_CWB), instantiate engine.

Inputs:
  - SIMULATION_MODE: 'PP', 'WLP_FD', or 'WLP_CWB'
  - CROP_NAME, VARIETY_NAME: for YAMLCropDataProvider
  - SOIL_PARAMS_JSON: path to soil parameter JSON
  - WEATHER_CSV: path to PCSE weather CSV
  - AGRO_YAML: path to agromanagement YAML
  - CO2: atmospheric CO2 (ppm, default 400)
  - WAV: initial available water (cm, default 20)

Outputs:
  - JSON summary of engine configuration on stdout
  - Engine object (when called as library)

Exit codes:
  0 — success, 1 — input error, 2 — processing error
"""

import sys
import os
import json
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

SIMULATION_MODE = "WLP_FD"
CROP_NAME = "wheat"
VARIETY_NAME = "Winter_wheat_101"
SOIL_PARAMS_JSON = ""
WEATHER_CSV = ""
AGRO_YAML = ""
CO2 = 400
WAV = 20


def validate_inputs():
    errors = []
    if SIMULATION_MODE not in ("PP", "WLP_FD", "WLP_CWB"):
        errors.append(f"SIMULATION_MODE must be PP, WLP_FD, or WLP_CWB, got '{SIMULATION_MODE}'")
    if not CROP_NAME or not VARIETY_NAME:
        errors.append("CROP_NAME and VARIETY_NAME must be set")
    if SIMULATION_MODE != "PP" and (not SOIL_PARAMS_JSON or not Path(SOIL_PARAMS_JSON).exists()):
        errors.append(f"Soil params required for {SIMULATION_MODE} mode: {SOIL_PARAMS_JSON}")
    if not WEATHER_CSV or not Path(WEATHER_CSV).exists():
        errors.append(f"Weather CSV not found: {WEATHER_CSV}")
    if not AGRO_YAML or not Path(AGRO_YAML).exists():
        errors.append(f"Agromanagement YAML not found: {AGRO_YAML}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)


def process():
    """Configure and instantiate PCSE engine."""
    import yaml
    from pcse.input import YAMLCropDataProvider, CSVWeatherDataProvider
    # PCSE 6.0+: WOFOST72SiteDataProvider moved from pcse.util to pcse.input (dt_v001)
    from pcse.input import WOFOST72SiteDataProvider
    from pcse.base import ParameterProvider

    # 1. Crop parameters
    cropdata = YAMLCropDataProvider()
    cropdata.set_active_crop(CROP_NAME, VARIETY_NAME)
    logger.info(f"Crop: {CROP_NAME} / {VARIETY_NAME}")

    # 2. Soil parameters
    if SIMULATION_MODE != "PP":
        with open(SOIL_PARAMS_JSON) as f:
            soildata = json.load(f)
        logger.info(f"Soil: SMW={soildata['SMW']}, SMFCF={soildata['SMFCF']}, SM0={soildata['SM0']}")
    else:
        soildata = {}
        logger.info("PP mode — soil parameters not used")

    # 3. Site parameters
    # PCSE 6.0+: CO2 no longer accepted by SiteDataProvider; handled internally
    # via crop CO2 tables (dt_v002). Use WAV only.
    sitedata = WOFOST72SiteDataProvider(WAV=WAV)
    logger.info(f"Site: WAV={WAV} cm (CO2 handled internally in PCSE 6.0+)")

    # 4. Assemble ParameterProvider
    params = ParameterProvider(cropdata=cropdata, soildata=soildata, sitedata=sitedata)

    # 5. Weather
    weather = CSVWeatherDataProvider(WEATHER_CSV)
    logger.info(f"Weather: {weather.first_date} to {weather.last_date}")

    # 6. Agromanagement
    with open(AGRO_YAML) as f:
        agro = yaml.safe_load(f)

    # 7. Instantiate engine
    if SIMULATION_MODE == "PP":
        from pcse.models import Wofost72_PP
        engine = Wofost72_PP(params, weather, agro)
    elif SIMULATION_MODE == "WLP_FD":
        from pcse.models import Wofost72_WLP_FD
        engine = Wofost72_WLP_FD(params, weather, agro)
    elif SIMULATION_MODE == "WLP_CWB":
        from pcse.models import Wofost72_WLP_CWB
        engine = Wofost72_WLP_CWB(params, weather, agro)

    logger.info(f"Engine instantiated: {type(engine).__name__}")

    result = {
        "status": "success",
        "engine_class": type(engine).__name__,
        "simulation_mode": SIMULATION_MODE,
        "crop": f"{CROP_NAME}/{VARIETY_NAME}",
        "weather_period": f"{weather.first_date} to {weather.last_date}",
        "co2_ppm": CO2,
        "wav_cm": WAV,
    }

    return result, engine


if __name__ == "__main__":
    if len(sys.argv) >= 6:
        SIMULATION_MODE = sys.argv[1]
        CROP_NAME = sys.argv[2]
        VARIETY_NAME = sys.argv[3]
        WEATHER_CSV = sys.argv[4]
        AGRO_YAML = sys.argv[5]
    if len(sys.argv) >= 7:
        SOIL_PARAMS_JSON = sys.argv[6]

    validate_inputs()
    try:
        result, engine = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        sys.exit(2)

    print(json.dumps(result, indent=2, default=str))
    sys.exit(0)
