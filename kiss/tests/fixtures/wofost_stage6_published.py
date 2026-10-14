#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      run_wofost_simulation
Stage:        s6_execution
Description:  Execute WOFOST simulation for a single grid cell:
              instantiate engine, run_till_terminate(), extract output
              and summary. Save daily output to CSV and summary to JSON.

Inputs:
  - SIMULATION_MODE: PP, WLP_FD, or WLP_CWB
  - CROP_NAME, VARIETY_NAME: crop specification
  - SOIL_PARAMS_JSON: path to soil parameter JSON
  - WEATHER_CSV: path to PCSE weather CSV
  - AGRO_YAML: path to agromanagement YAML
  - OUTPUT_CSV: output CSV file path
  - CO2, WAV: site parameters

Outputs:
  - Daily output CSV (DVS, LAI, TAGP, TWSO, TRA, RD, SM)
  - Summary JSON (yield, phenology dates)

Exit codes:
  0 — success, 1 — input error, 2 — processing error, 3 — output error
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
OUTPUT_CSV = ""
CO2 = 400
WAV = 20


def validate_inputs():
    errors = []
    if SIMULATION_MODE not in ("PP", "WLP_FD", "WLP_CWB"):
        errors.append(f"Invalid mode: {SIMULATION_MODE}")
    if not WEATHER_CSV or not Path(WEATHER_CSV).exists():
        errors.append(f"Weather CSV not found: {WEATHER_CSV}")
    if not AGRO_YAML or not Path(AGRO_YAML).exists():
        errors.append(f"Agro YAML not found: {AGRO_YAML}")
    if not OUTPUT_CSV:
        errors.append("OUTPUT_CSV not set")
    # PCSE 6.0 requires soil-hydraulic params for ALL modes incl. PP (see process()).
    if not SOIL_PARAMS_JSON or not Path(SOIL_PARAMS_JSON).exists():
        errors.append(f"Soil params required for {SIMULATION_MODE}: {SOIL_PARAMS_JSON}")
    try:
        import pcse
    except ImportError:
        errors.append("pcse not installed")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)


def validate_outputs(output_csv, summary_json):
    errors = []
    if not Path(output_csv).exists():
        errors.append(f"Output CSV not created: {output_csv}")
    else:
        import pandas as pd
        df = pd.read_csv(output_csv)
        if len(df) == 0:
            errors.append("Output CSV is empty")
        if 'TWSO' in df.columns and df['TWSO'].iloc[-1] <= 0:
            logger.warning("TWSO (yield) is zero! Check weather units. See dt_007.")

    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(3)


def process():
    """Run WOFOST simulation."""
    import yaml
    import pandas as pd
    from pcse.input import YAMLCropDataProvider, CSVWeatherDataProvider
    # PCSE 6.0+: WOFOST72SiteDataProvider moved from pcse.util to pcse.input (dt_v001)
    from pcse.input import WOFOST72SiteDataProvider
    from pcse.base import ParameterProvider

    # Load components
    cropdata = YAMLCropDataProvider()
    cropdata.set_active_crop(CROP_NAME, VARIETY_NAME)

    # PCSE 6.0 fix (2026-06-08): Wofost72_PP STILL requires the soil-hydraulic
    # parameters (SMFCF, SM0, K0, RDMSOL, ...) at construction even though water
    # is not limiting in potential-production mode — omitting them raises
    # `ParameterError: Value for parameter SMFCF missing`. The SKILL claim "PP
    # mode: no soil" is therefore wrong for PCSE 6.0. Load soil whenever a soil
    # JSON is provided, for ALL modes; only fall back to empty if none given.
    soildata = {}
    if SOIL_PARAMS_JSON and Path(SOIL_PARAMS_JSON).exists():
        with open(SOIL_PARAMS_JSON) as f:
            soildata = json.load(f)

    # PCSE 6.0+: CO2 no longer accepted by SiteDataProvider; handled internally
    # via crop CO2 tables (dt_v002). Use WAV only.
    sitedata = WOFOST72SiteDataProvider(WAV=WAV)
    params = ParameterProvider(cropdata=cropdata, soildata=soildata, sitedata=sitedata)

    weather = CSVWeatherDataProvider(WEATHER_CSV)
    with open(AGRO_YAML) as f:
        agro = yaml.safe_load(f)

    # Instantiate engine
    if SIMULATION_MODE == "PP":
        from pcse.models import Wofost72_PP
        engine = Wofost72_PP(params, weather, agro)
    elif SIMULATION_MODE == "WLP_FD":
        from pcse.models import Wofost72_WLP_FD
        engine = Wofost72_WLP_FD(params, weather, agro)
    elif SIMULATION_MODE == "WLP_CWB":
        from pcse.models import Wofost72_WLP_CWB
        engine = Wofost72_WLP_CWB(params, weather, agro)

    logger.info(f"Engine: {type(engine).__name__}")

    # Run simulation
    engine.run_till_terminate()
    logger.info("Simulation completed.")

    # Extract output
    output = engine.get_output()
    summary = engine.get_summary_output()

    # Convert to DataFrame
    df = pd.DataFrame(output)
    df = df.set_index('day')

    # Save daily output
    os.makedirs(os.path.dirname(OUTPUT_CSV) or '.', exist_ok=True)
    df.to_csv(OUTPUT_CSV)
    logger.info(f"Daily output saved: {OUTPUT_CSV} ({len(df)} days)")

    # Save summary
    summary_path = OUTPUT_CSV.replace('.csv', '_summary.json')
    summary_serializable = []
    for item in summary:
        item_str = {}
        for k, v in item.items():
            item_str[k] = str(v) if hasattr(v, 'strftime') else v
        summary_serializable.append(item_str)
    with open(summary_path, 'w') as f:
        json.dump(summary_serializable, f, indent=2, default=str)
    logger.info(f"Summary saved: {summary_path}")

    # Report key metrics
    final_dvs = df['DVS'].iloc[-1] if 'DVS' in df.columns else -1
    twso = df['TWSO'].iloc[-1] if 'TWSO' in df.columns else -1
    tagp = df['TAGP'].iloc[-1] if 'TAGP' in df.columns else -1
    lai_max = df['LAI'].max() if 'LAI' in df.columns else -1

    logger.info(f"Results: DVS={final_dvs:.2f}, TWSO={twso:.0f} kg/ha, "
                f"TAGP={tagp:.0f} kg/ha, LAI_max={lai_max:.2f}")

    if final_dvs < 2.0:
        logger.warning(f"Crop did NOT reach maturity (DVS={final_dvs:.2f}). See dt_005, dt_006, dt_014.")
    if twso <= 0:
        logger.warning("Zero yield! Check IRRAD units (dt_003) and RAIN units (dt_004).")

    result = {
        "status": "success",
        "output_csv": OUTPUT_CSV,
        "summary_json": summary_path,
        "final_dvs": round(final_dvs, 3),
        "yield_twso_kgha": round(twso, 1),
        "total_biomass_tagp_kgha": round(tagp, 1),
        "lai_max": round(lai_max, 2),
        "n_days": len(df),
        "maturity_reached": final_dvs >= 2.0,
    }

    return result


if __name__ == "__main__":
    if len(sys.argv) >= 7:
        SIMULATION_MODE = sys.argv[1]
        CROP_NAME = sys.argv[2]
        VARIETY_NAME = sys.argv[3]
        WEATHER_CSV = sys.argv[4]
        AGRO_YAML = sys.argv[5]
        OUTPUT_CSV = sys.argv[6]
    if len(sys.argv) >= 8:
        SOIL_PARAMS_JSON = sys.argv[7]

    validate_inputs()
    try:
        result = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(2)

    validate_outputs(result["output_csv"], result["summary_json"])
    print(json.dumps(result, indent=2, default=str))
    sys.exit(0)
