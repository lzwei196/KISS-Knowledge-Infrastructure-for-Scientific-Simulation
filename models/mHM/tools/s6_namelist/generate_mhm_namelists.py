#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
Tool ID:      generate_mhm_namelists
Stage:        s6_namelist
Description:  Generate the 4 Fortran namelist files required by mHM.

Generates:
  1. mhm.nml -- main configuration (domains, resolution, time, processes, paths)
  2. mhm_parameter.nml -- MPR global parameters with bounds and flags
  3. mhm_outputs.nml -- hydrological output selection
  4. mrm_outputs.nml -- routing output selection

CRITICAL:
  - resolution_Hydrology and resolution_Routing must be in METERS
  - All paths in namelists are RELATIVE to the run directory
  - processCase(5) = PET method, processCase(8) = routing method
  - iFlag_soilDB must match the soil_classdefinition format
  - Gauge IDs must match idgauges.asc values

Inputs:
  - CONFIG_PATH: config.json from s0
  - DOMAIN_INFO_PATH: domain_info.json from s1
  - GAUGE_ID: integer gauge ID (default 1)
  - GAUGE_FILENAME: gauge data filename (default "00001.txt")
  - WARMUP_DAYS: number of warmup days (default 365)

Outputs:
  - mhm.nml, mhm_parameter.nml, mhm_outputs.nml, mrm_outputs.nml in run directory

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import json
import logging
import shutil
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
CONFIG_PATH = ""
DOMAIN_INFO_PATH = ""
GAUGE_ID = 1
GAUGE_FILENAME = "00001.txt"
WARMUP_DAYS = 365
OPTIMIZE = False
EVAL_START_YEAR = 0     # 0 => config["start_year"] + (warmup consumed before it)
EVAL_END_YEAR = 0       # 0 => config["end_year"]
OPTI_METHOD = 1         # 1=DDS, 2=SA, 3=SCE
OPTI_FUNCTION = 1       # 1 = 1-NSE, 9 = 1-KGE  (both discharge-only)
N_ITERATIONS = 400
PARAM_NML = ""          # e.g. <cal_dir>/FinalParam.nml -> copied to mhm_parameter.nml

# Template parameter file from mHM source
MHM_PARAM_TEMPLATE = os.path.join(os.environ.get("HYDROCRAFT_ROOT", "KISSPATH_ROOT"), "model/mhm_src/mhm_parameter.nml")
MHM_OUTPUTS_TEMPLATE = os.path.join(os.environ.get("HYDROCRAFT_ROOT", "KISSPATH_ROOT"), "model/mhm_src/mhm_outputs.nml")
MRM_OUTPUTS_TEMPLATE = os.path.join(os.environ.get("HYDROCRAFT_ROOT", "KISSPATH_ROOT"), "model/mhm_src/mrm_outputs.nml")

if len(sys.argv) > 1:
    import argparse
    parser = argparse.ArgumentParser(description="Generate mHM namelists")
    parser.add_argument("--config", required=True)
    parser.add_argument("--domain_info", required=True)
    parser.add_argument("--gauge_id", type=int, default=1)
    parser.add_argument("--gauge_filename", default="00001.txt")
    parser.add_argument("--warmup_days", type=int, default=365)
    parser.add_argument("--optimize", action="store_true")
    parser.add_argument("--eval_start_year", type=int, default=0)
    parser.add_argument("--eval_end_year", type=int, default=0)
    parser.add_argument("--opti_method", type=int, default=1)
    parser.add_argument("--opti_function", type=int, default=1,
                        help="1 = 1-NSE, 9 = 1-KGE. NEVER 10 -- that is KGE of "
                             "catchment-average SOIL MOISTURE and needs "
                             "&optional_data (dt_r15).")
    parser.add_argument("--n_iterations", type=int, default=400,
                        help="DDS requires >= 6 (dt_r14)")
    parser.add_argument("--param_nml", default="",
                        help="Parameter namelist (e.g. FinalParam.nml from s9) to "
                             "install as mhm_parameter.nml for a forward run")
    args = parser.parse_args()
    CONFIG_PATH = args.config
    DOMAIN_INFO_PATH = args.domain_info
    GAUGE_ID = args.gauge_id
    GAUGE_FILENAME = args.gauge_filename
    WARMUP_DAYS = args.warmup_days
    OPTIMIZE = args.optimize
    EVAL_START_YEAR = args.eval_start_year
    EVAL_END_YEAR = args.eval_end_year
    OPTI_METHOD = args.opti_method
    OPTI_FUNCTION = args.opti_function
    N_ITERATIONS = args.n_iterations
    PARAM_NML = args.param_nml

    # NOTE: `logger` is configured below this block, so report to stderr directly.
    if OPTIMIZE and OPTI_FUNCTION in (10, 11, 12, 13, 15, 17, 27, 29, 30):
        print(f"ERROR: opti_function={OPTI_FUNCTION} needs a &optional_data namelist "
              f"(soil moisture / TWS / ET / neutrons). For discharge calibration use "
              f"1 (1-NSE) or 9 (1-KGE). See dt_r15.", file=sys.stderr)
        sys.exit(1)
    if OPTIMIZE and N_ITERATIONS < 6:
        print(f"ERROR: nIterations={N_ITERATIONS} < 6: mo_dds.F90 Fortran-STOPs with "
              f"exit status 0 and writes no FinalParam.nml (dt_r14).", file=sys.stderr)
        sys.exit(1)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def generate_mhm_nml(config, domain_info, run_dir):
    """Generate the main mhm.nml namelist."""
    start_year = config["start_year"]
    end_year = config["end_year"]
    pet_method = config["pet_method"]

    # eval_Per is the window the OPTIMISER sees. Set it to the calibration years and
    # give the spin-up as warming_Days -- mHM warms up on the days immediately BEFORE
    # eval_Per, so the forcing must start earlier than eval_start.
    eval_start = EVAL_START_YEAR or start_year
    eval_end = EVAL_END_YEAR or end_year

    # PET processCase mapping:
    # -1: PET is input, LAI driven correction
    #  0: PET is input, aspect driven correction
    #  1: Hargreaves-Samani
    #  2: Priestley-Taylor
    #  3: Penman-Monteith
    pet_process = pet_method if pet_method > 0 else 0

    # Determine coordinate system
    # mHM convention: 0 = regular X-Y (projected/metric), 1 = lat-lon (geographic)
    is_geo = domain_info.get("is_geographic", True)
    coord_sys = 1 if is_geo else 0  # 1=lat/lon (geographic), 0=projected/X-Y (metric)

    # Resolution: mHM expects degrees for geographic CRS, meters for projected
    if is_geo:
        res_l1 = domain_info["header_L1"]["cellsize"]   # degrees
        res_l11 = domain_info.get("header_L11", domain_info["header_L1"])["cellsize"]
    else:
        res_l1 = config["resolution_L1_m"]
        res_l11 = config["resolution_L11_m"]

    nml = f"""!> mHM main namelist -- auto-generated by HydroCraft
!> Basin: {config['basin_name']}
!> Period: {start_year}-{end_year}

&project_description
project_details="HydroCraft mHM run for {config['basin_name']}"
setup_description="Automated mHM simulation with CMFD/MSWX forcing"
simulation_type="historical simulation"
Conventions="CF-1.6"
contact="HydroCraft (Zhang Jianyun Research Group)"
mHM_details="mHM v5.13.1 via HydroCraft"
history="auto-generated"
/

&mainconfig
iFlag_cordinate_sys = {coord_sys}
nDomains = 1
resolution_Hydrology(1) = {res_l1}
L0Domain(1) = 1
write_restart = .FALSE.
read_opt_domain_data(1) = 0
/

&mainconfig_mhm_mrm
mhm_file_RestartIn(1) = "restart/mHM_restart_001.nc"
mrm_file_RestartIn(1) = "restart/mRM_restart_001.nc"
resolution_Routing(1) = {res_l11}
timestep = 1
read_restart = .FALSE.
optimize = {'.TRUE.' if OPTIMIZE else '.FALSE.'}
optimize_restart = .FALSE.
opti_method = {OPTI_METHOD}
opti_function = {OPTI_FUNCTION}
/

&mainconfig_mrm
/

&directories_general
dirConfigOut = "./"
dirCommonFiles = "input/morph/"
dir_Morpho(1) = "input/morph/"
dir_LCover(1) = "input/luse/"
mhm_file_RestartOut(1) = "restart/mHM_restart_001.nc"
mrm_file_RestartOut(1) = "restart/mRM_restart_001.nc"
dir_Out(1) = "output_b1/"
file_LatLon(1) = "input/latlon/latlon_1.nc"
/

&directories_mHM
inputFormat_meteo_forcings = "nc"
dir_Precipitation(1) = "input/meteo/pre/"
dir_Temperature(1) = "input/meteo/tavg/"
dir_minTemperature(1) = "input/meteo/tmin/"
dir_maxTemperature(1) = "input/meteo/tmax/"
dir_ReferenceET(1) = "input/meteo/pet/"
time_step_model_inputs(1) = 0
/

&directories_mRM
dir_Gauges(1) = "input/gauge/"
dir_Total_Runoff(1) = "output_b1/"
dir_Bankfull_Runoff(1) = "input/optional_data/"
/

&processSelection
processCase(1) = 1
processCase(2) = 1
processCase(3) = 1
processCase(4) = 1
processCase(5) = {pet_process}
processCase(6) = 1
processCase(7) = 1
processCase(8) = 3
processCase(9) = 1
/

&LCover
nLCoverScene = 1
LCoverYearStart(1) = {start_year}
LCoverYearEnd(1) = {eval_end}
LCoverfName(1) = 'lc_{start_year}.asc'
/

&time_periods
warming_Days(1) = {WARMUP_DAYS}
eval_Per(1)%yStart = {eval_start}
eval_Per(1)%mStart = 01
eval_Per(1)%dStart = 01
eval_Per(1)%yEnd = {eval_end}
eval_Per(1)%mEnd = 12
eval_Per(1)%dEnd = 31
/

&soildata
iFlag_soilDB = 0
tillageDepth = 200
nSoilHorizons_mHM = 2
soil_Depth(1) = 200
/

&LAI_data_information
timeStep_LAI_input = 0
inputFormat_gridded_LAI = "nc"
/

&LCover_MPR
fracSealed_cityArea = 0.6
/

&evaluation_gauges
nGaugesTotal = 1
NoGauges_domain(1) = 1
Gauge_id(1,1) = {GAUGE_ID}
gauge_filename(1,1) = "{GAUGE_FILENAME}"
/

&inflow_gauges
InflowGauge_Headwater(1,1) = .FALSE.
/

&panEvapo
evap_coeff = 1.30, 1.20, 0.72, 0.75, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.00, 1.50
/

&nightDayRatio
read_meteo_weights = .FALSE.
fnight_prec = 0.46, 0.50, 0.52, 0.51, 0.48, 0.50, 0.49, 0.48, 0.52, 0.56, 0.50, 0.47
fnight_pet = 0.10, 0.10, 0.10, 0.10, 0.10, 0.10, 0.10, 0.10, 0.10, 0.10, 0.10, 0.10
fnight_temp = -0.76, -1.30, -1.88, -2.38, -2.72, -2.75, -2.74, -3.04, -2.44, -1.60, -0.94, -0.53
/

&Optimization
nIterations = {N_ITERATIONS}
seed = 1235876
dds_r = 0.2
sa_temp = -9.0
sce_ngs = 2
sce_npg = -9
sce_nps = -9
mcmc_opti = .FALSE.
mcmc_error_params = 0.01, 0.6
/
"""
    nml_path = run_dir / "mhm.nml"
    with open(nml_path, 'w') as f:
        f.write(nml)
    logger.info(f"Written: {nml_path}")
    return str(nml_path)


def validate_inputs():
    errors = []
    if not CONFIG_PATH or not Path(CONFIG_PATH).exists():
        errors.append(f"Config not found: {CONFIG_PATH}")
    if not DOMAIN_INFO_PATH or not Path(DOMAIN_INFO_PATH).exists():
        errors.append(f"Domain info not found: {DOMAIN_INFO_PATH}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def process():
    config = json.load(open(CONFIG_PATH))
    domain_info = json.load(open(DOMAIN_INFO_PATH))
    run_dir = Path(config["output_dir"])

    # Generate mhm.nml
    generate_mhm_nml(config, domain_info, run_dir)

    # Copy parameter, output namelists from source (they contain good defaults).
    # --param_nml overrides the template with calibrated MPR global parameters
    # (FinalParam.nml from s9); mHM always reads them from mhm_parameter.nml.
    param_src = MHM_PARAM_TEMPLATE
    if PARAM_NML:
        if not Path(PARAM_NML).exists():
            logger.error(f"--param_nml not found: {PARAM_NML}")
            sys.exit(1)
        param_src = PARAM_NML
        logger.info(f"Installing calibrated parameters from {PARAM_NML}")

    for src, dst in [
        (param_src, run_dir / "mhm_parameter.nml"),
        (MHM_OUTPUTS_TEMPLATE, run_dir / "mhm_outputs.nml"),
        (MRM_OUTPUTS_TEMPLATE, run_dir / "mrm_outputs.nml"),
    ]:
        if Path(src).exists():
            shutil.copy2(src, dst)
            logger.info(f"Copied: {src} -> {dst}")
        else:
            logger.warning(f"Template not found: {src}")

    result = {
        "status": "success",
        "run_dir": str(run_dir),
        "namelists": [
            "mhm.nml",
            "mhm_parameter.nml",
            "mhm_outputs.nml",
            "mrm_outputs.nml",
        ],
    }
    print(json.dumps(result, indent=2))
    return str(run_dir)


def validate_outputs(output_path):
    run_dir = Path(output_path)
    required = ["mhm.nml", "mhm_parameter.nml"]
    for f in required:
        p = run_dir / f
        if not p.exists():
            logger.error(f"Missing: {p}")
            sys.exit(3)
    logger.info("Output validation passed.")


if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try:
        output_path = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        import traceback; traceback.print_exc()
        sys.exit(2)
    validate_outputs(output_path)
    sys.exit(0)
