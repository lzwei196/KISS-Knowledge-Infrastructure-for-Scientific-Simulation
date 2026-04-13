#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
Tool ID:      setup_calibration
Stage:        s10_calibration
Description:  Generate optpar.txt for HYPE built-in calibration (DDS/DEMC/Monte Carlo)
              and update info.txt to enable calibration mode with criteria settings.

HYPE's built-in optimizer (optim.f90) handles calibration internally -- no external
optimizer is needed. This tool:
  1. Generates optpar.txt with parameter ranges and optimization task settings
  2. Updates info.txt to add calibration=Y and criteria definition lines

Usage:
    # DDS-equivalent calibration (Monte Carlo with staged search):
    python setup_calibration.py \
        --method MC \
        --geoclass modelfiles/GeoClass.txt \
        --info_txt info.txt \
        --output modelfiles/optpar.txt \
        --num_runs 500 \
        --criterion MKG \
        --crit_variable cout \
        --obs_variable rout \
        --outlet_subid 3

    # DEMC calibration (Bayesian posterior sampling):
    python setup_calibration.py \
        --method DEMC \
        --geoclass modelfiles/GeoClass.txt \
        --info_txt info.txt \
        --output modelfiles/optpar.txt \
        --demc_ngen 100 \
        --demc_npop 5 \
        --criterion MKG \
        --crit_variable cout \
        --obs_variable rout \
        --outlet_subid 3

    # Include NPC parameters for nutrient calibration:
    python setup_calibration.py \
        --method MC \
        --geoclass modelfiles/GeoClass.txt \
        --info_txt info.txt \
        --output modelfiles/optpar.txt \
        --num_runs 500 \
        --criterion MKG \
        --crit_variable cout \
        --obs_variable rout \
        --outlet_subid 3 \
        --substances "N P"

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import argparse
import sys
import os
import re
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


# =============================================================================
# Parameter calibration ranges (from WWH and HYPE literature)
# =============================================================================

# Parameter type: 'general' (1 value), 'landuse' (nlanduse values), 'soil' (nsoil values)
# Format: (param_name, param_type, min_val, max_val, precision, description)
HYDROLOGY_PARAMS = [
    # Core hydrological parameters -- high sensitivity
    ('lp',     'general', 0.1,   1.0,   3, 'PET reduction threshold'),
    ('cevpam', 'general', 0.0,   1.0,   3, 'PET seasonal amplitude'),
    ('cevpph', 'general', 0.0,   60.0,  1, 'PET phase shift (days)'),
    ('rrcs3',  'general', 0.0001,0.1,   5, 'Deep groundwater recession'),
    ('rivvel', 'general', 0.1,   5.0,   2, 'River velocity (m/s)'),
    ('damp',   'general', 0.0,   1.0,   3, 'Damping coefficient'),
    # Land-use dependent
    ('ttmp',   'landuse', -3.0,  3.0,   2, 'Snow threshold temperature (C)'),
    ('cmlt',   'landuse', 1.0,   10.0,  2, 'Degree-day snowmelt factor'),
    ('cevp',   'landuse', 0.05,  0.50,  3, 'PET coefficient'),
    ('srrcs',  'landuse', 0.001, 0.50,  4, 'Surface runoff recession'),
    # Soil-type dependent
    ('wcfc',   'soil',    0.05,  0.50,  3, 'Field capacity'),
    ('wcwp',   'soil',    0.01,  0.30,  3, 'Wilting point'),
    ('wcep',   'soil',    0.10,  0.70,  3, 'Effective porosity'),
    ('rrcs1',  'soil',    0.001, 0.50,  4, 'Upper soil recession'),
    ('rrcs2',  'soil',    0.001, 0.20,  4, 'Lower soil recession'),
]

# NPC (nutrient) calibration parameters -- used when --substances includes N or P
NPC_PARAMS_N = [
    ('fastn0',   'general', 1.0,   100.0, 2, 'Initial fast N pool (kg/km2)'),
    ('humusn0',  'landuse', 50.0,  500.0, 1, 'Humus N pool (kg/km2/m)'),
    ('denitrlu', 'landuse', 0.0001,0.005, 5, 'Land denitrification (kg/m2/day)'),
    ('minerfn',  'landuse', 0.001, 0.010, 4, 'Fast N mineralization (1/day)'),
    ('dissolhn', 'landuse', 0.001, 0.020, 4, 'Humus N dissolution'),
    ('dissolfn', 'landuse', 0.001, 0.050, 4, 'Fast N dissolution'),
    ('degradhn', 'landuse', 0.0001,0.005, 5, 'Humus N degradation'),
    ('denitwrm', 'general', 0.001, 0.050, 4, 'River denitrification (kg/m2/day)'),
    ('sedon',    'general', 0.0001,0.010, 5, 'ON sedimentation (kg/m2/day)'),
]

NPC_PARAMS_P = [
    ('fastp0',   'general', 0.1,   50.0,  2, 'Initial fast P pool (kg/km2)'),
    ('humusp0',  'landuse', 5.0,   50.0,  1, 'Humus P pool (kg/km2/m)'),
    ('minerfp',  'landuse', 0.001, 0.010, 4, 'Fast P mineralization (1/day)'),
    ('dissolhp', 'landuse', 0.001, 0.020, 4, 'Humus P dissolution'),
    ('dissolfp', 'landuse', 0.001, 0.050, 4, 'Fast P dissolution'),
    ('partp0',   'landuse', 5.0,   200.0, 1, 'Particulate P pool (kg/km2/m)'),
    ('sedpp',    'general', 0.0001,0.010, 5, 'PP sedimentation (kg/m2/day)'),
    ('freuc',    'soil',    0.01,  20.0,  3, 'Freundlich coefficient'),
    ('freuexp',  'soil',    0.1,   1.0,   3, 'Freundlich exponent'),
    ('freurate', 'soil',    0.001, 0.50,  4, 'Freundlich rate'),
    ('soilcoh',  'soil',    1.0,   20.0,  2, 'Soil cohesion for erosion (kPa)'),
    ('soilerod', 'soil',    0.1,   5.0,   2, 'Soil erodibility factor'),
]

# Criteria codes supported by HYPE (from compout.f90)
VALID_CRITERIA = {
    'TAU': 'Kendall tau (max -> 1)',
    'MNS': 'Mean Nash-Sutcliffe Efficiency (max -> 1)',
    'MRA': 'Mean RA (max -> 1)',
    'MRE': 'Mean Relative Error (min -> 0, absolute value used)',
    'MAR': 'Mean Absolute Relative Error (min -> 0)',
    'MCC': 'Mean Correlation Coefficient (max -> 1)',
    'MKG': 'Mean Kling-Gupta Efficiency (max -> 1, RECOMMENDED)',
    'MRS': 'Median RMSE (min -> 0)',
    'MDA': 'Median NSE (max -> 1)',
    'MNW': 'Mean NSE adjusted for bias (max -> 1)',
    'MD2': 'Median R2 (max -> 1)',
}


def read_geoclass(filepath):
    """Read GeoClass.txt and return landuse/soil type counts."""
    landuse_ids = set()
    soil_ids = set()

    with open(filepath) as f:
        for line in f:
            if line.startswith('!!') or line.strip() == '':
                continue
            parts = line.strip().split()
            if len(parts) >= 3:
                try:
                    landuse = int(parts[1])
                    soil = int(parts[2])
                    landuse_ids.add(landuse)
                    soil_ids.add(soil)
                except ValueError:
                    continue

    if not landuse_ids or not soil_ids:
        logger.error("Could not parse any land-use/soil types from GeoClass.txt")
        sys.exit(1)

    return max(landuse_ids), max(soil_ids)


def generate_optpar(method, n_landuse, n_soil, output_path,
                    num_runs=500, substances='none',
                    demc_ngen=100, demc_npop=5,
                    demc_gammascale=1.0, demc_crossover=1.0,
                    demc_sigma=0.01, demc_accprob=0.0,
                    write_all=True, cal_log=True,
                    params_subset=None):
    """
    Generate optpar.txt for HYPE calibration.

    The file has two sections:
    1. Header (20 lines): optimization task settings
    2. Parameter block: triplets of (min, max, precision) for each parameter

    Parameters in optpar.txt appear as 3 consecutive lines per parameter:
      paramname  min_val1  min_val2 ...  (for each soil/landuse type)
      paramname  max_val1  max_val2 ...
      paramname  precision  precision ...

    When min == max, the parameter is NOT calibrated (fixed).
    """
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)

    # Collect parameters to calibrate
    params = list(HYDROLOGY_PARAMS)

    if substances and substances != 'none':
        subs = substances.upper().split()
        if 'N' in subs:
            params.extend(NPC_PARAMS_N)
        if 'P' in subs:
            params.extend(NPC_PARAMS_P)

    # Filter to subset if specified
    if params_subset:
        subset_names = [p.strip().lower() for p in params_subset.split(',')]
        params = [p for p in params if p[0].lower() in subset_names]
        if not params:
            logger.error(f"No valid parameters found in subset: {params_subset}")
            sys.exit(1)

    with open(output_path, 'w') as f:
        # Header line (1 line, skipped by HYPE via nskip=1)
        f.write("!! optpar.txt generated by HydroCraft HYPE calibration tools\n")

        # CRITICAL: HYPE reads exactly ninfolines=20 lines as info lines after
        # the 1 skipped header line. Lines that don't match any keyword are
        # silently ignored. We MUST write exactly 20 lines here before the
        # parameter block, otherwise the first parameter triplets get consumed
        # as info lines (and lost).
        info_lines = []

        if method.upper() == 'MC':
            info_lines.append(f"task MC")
            if write_all:
                info_lines.append(f"task WA")
            info_lines.append(f"num_mc {num_runs}")
            info_lines.append(f"num_ens {min(num_runs, 10)}")
        elif method.upper() == 'DEMC':
            info_lines.append(f"task DE")
            if write_all:
                info_lines.append(f"task WA")
            info_lines.append(f"DEMC_ngen {demc_ngen}")
            info_lines.append(f"DEMC_npop {max(demc_npop, 3)}")
            info_lines.append(f"DEMC_gammascale {demc_gammascale}")
            info_lines.append(f"DEMC_crossover {demc_crossover}")
            info_lines.append(f"DEMC_sigma {demc_sigma}")
            info_lines.append(f"DEMC_accprob {demc_accprob}")
        elif method.upper() == 'SM':
            info_lines.append(f"task SM")
            if write_all:
                info_lines.append(f"task WA")
            info_lines.append(f"num_mc {num_runs}")
            info_lines.append(f"num_ens {min(num_runs, 10)}")
            info_lines.append(f"num_stages 3")
            info_lines.append(f"num_zoom 0.5")
        elif method.upper() == 'BN':
            info_lines.append(f"task BN")
            info_lines.append(f"num_maxItr {num_runs}")
            info_lines.append(f"num_criItr 10")
            info_lines.append(f"num_criTol 0.001")
        elif method.upper() == 'Q2':
            info_lines.append(f"task Q2")
            info_lines.append(f"num_maxItr {num_runs}")
            info_lines.append(f"num_criItr 10")
            info_lines.append(f"num_criTol 0.001")
        else:
            logger.error(f"Unknown method: {method}. Use MC, DEMC, SM, BN, or Q2.")
            sys.exit(1)

        if cal_log:
            info_lines.append(f"cal_log Y")
        else:
            info_lines.append(f"cal_log N")

        # Pad with empty comment lines to reach exactly 20 info lines
        while len(info_lines) < 20:
            info_lines.append("!! (reserved)")

        for line in info_lines:
            f.write(line + "\n")

        # Write parameter blocks: triplets of (min, max, precision)
        f.write("!! --- Parameter ranges below (min / max / precision triplets) ---\n")

        for name, ptype, pmin, pmax, prec, desc in params:
            if ptype == 'general':
                nvals = 1
            elif ptype == 'landuse':
                nvals = n_landuse
            elif ptype == 'soil':
                nvals = n_soil
            else:
                nvals = 1

            # Format min line
            min_vals = '\t'.join([f'{pmin}'] * nvals)
            # Format max line
            max_vals = '\t'.join([f'{pmax}'] * nvals)
            # Format precision line (number of decimal places)
            prec_vals = '\t'.join([f'{prec}'] * nvals)

            f.write(f"{name}\t{min_vals}\n")
            f.write(f"{name}\t{max_vals}\n")
            f.write(f"{name}\t{prec_vals}\n")

    logger.info(f"Generated optpar.txt: {output_path}")
    logger.info(f"  Method: {method.upper()}")
    logger.info(f"  Parameters: {len(params)} ({n_landuse} land-use types, {n_soil} soil types)")
    if method.upper() == 'MC':
        logger.info(f"  Monte Carlo runs: {num_runs}")
    elif method.upper() == 'DEMC':
        logger.info(f"  DEMC: {demc_ngen} generations x {demc_npop} populations")
    return params


def update_info_txt(info_path, criterion, crit_variable, obs_variable,
                    outlet_subid=None, crit_weight=1.0, crit_period='d'):
    """
    Add calibration=Y and criteria lines to an existing info.txt.

    HYPE criteria format in info.txt:
        calibration Y
        crit 1 criterion <CODE>
        crit 1 cvariable <comp_var>
        crit 1 rvariable <rec_var>
        crit 1 weight <weight>
        crit meanperiod <period>

    Where:
        CODE: TAU, MNS, MKG, MRA, MRE, MAR, MCC, MRS, etc.
        comp_var: computed variable (e.g., cout = simulated outflow)
        rec_var: recorded variable (e.g., rout = observed outflow from Qobs.txt)
        weight: weight for multi-criteria (default 1.0)
        period: d=daily (default)
    """
    if not os.path.exists(info_path):
        logger.error(f"info.txt not found: {info_path}")
        sys.exit(1)

    criterion = criterion.upper()
    if criterion not in VALID_CRITERIA:
        logger.error(f"Invalid criterion '{criterion}'. Valid options: {list(VALID_CRITERIA.keys())}")
        sys.exit(1)

    with open(info_path, 'r') as f:
        content = f.read()
        lines = content.split('\n')

    # Check if calibration is already enabled
    has_calibration = False
    has_crit = False
    calibration_line_idx = None

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('calibration'):
            has_calibration = True
            calibration_line_idx = i
        if stripped.startswith('crit '):
            has_crit = True

    # Build calibration block
    cal_block = []
    if not has_calibration:
        cal_block.append("!! Calibration settings")
        cal_block.append("calibration Y")
    else:
        # Update existing calibration line to Y
        lines[calibration_line_idx] = "calibration Y"

    if not has_crit:
        cal_block.append(f"crit 1 criterion {criterion}")
        cal_block.append(f"crit 1 cvariable {crit_variable}")
        cal_block.append(f"crit 1 rvariable {obs_variable}")
        cal_block.append(f"crit 1 weight {crit_weight}")

        # Map period string to HYPE integer codes
        period_map = {'d': 1, 'w': 2, 'm': 3, 'y': 4, 's': 5}
        period_val = period_map.get(crit_period, 1)
        cal_block.append(f"crit meanperiod {period_val}")

        if outlet_subid:
            cal_block.append(f"crit subbasin {outlet_subid}")

    if cal_block:
        # Insert calibration block before the first modeloption line or at the end
        insert_idx = len(lines)
        for i, line in enumerate(lines):
            if line.strip().startswith('modeloption'):
                insert_idx = i
                break

        for j, cal_line in enumerate(cal_block):
            lines.insert(insert_idx + j, cal_line)

    with open(info_path, 'w') as f:
        f.write('\n'.join(lines))

    logger.info(f"Updated info.txt: {info_path}")
    logger.info(f"  Calibration: enabled")
    logger.info(f"  Criterion: {criterion} ({VALID_CRITERIA[criterion]})")
    logger.info(f"  Computed variable: {crit_variable}")
    logger.info(f"  Recorded variable: {obs_variable}")
    if outlet_subid:
        logger.info(f"  Outlet subbasin: {outlet_subid}")


def main():
    parser = argparse.ArgumentParser(
        description='Set up HYPE built-in calibration (optpar.txt + info.txt criteria)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Methods:
  MC    Monte Carlo random sampling (recommended for first exploration)
  DEMC  Differential Evolution Markov Chain (Bayesian posterior sampling)
  SM    Staged Monte Carlo (progressive zoom)
  BN    Brent line search (local optimization)
  Q2    Quasi-Newton BFGS (gradient-based local optimization)

Criteria (most useful):
  MKG   Mean Kling-Gupta Efficiency (RECOMMENDED -- balanced bias/variability/correlation)
  MNS   Mean Nash-Sutcliffe Efficiency (classic, penalizes bias less)
  TAU   Kendall tau (rank correlation -- robust to outliers)
  MRE   Mean Relative Error (volume bias only)
  MAR   Mean Absolute Relative Error (absolute volume bias)

Examples:
  # Quick 200-run Monte Carlo with KGE criterion:
  python setup_calibration.py --method MC --geoclass modelfiles/GeoClass.txt \\
      --info_txt info.txt --output modelfiles/optpar.txt \\
      --num_runs 200 --criterion MKG --crit_variable cout --obs_variable rout

  # DEMC with 50 generations, 5 chains:
  python setup_calibration.py --method DEMC --geoclass modelfiles/GeoClass.txt \\
      --info_txt info.txt --output modelfiles/optpar.txt \\
      --demc_ngen 50 --demc_npop 5 --criterion MKG \\
      --crit_variable cout --obs_variable rout

  # Calibrate only specific parameters:
  python setup_calibration.py --method MC --geoclass modelfiles/GeoClass.txt \\
      --info_txt info.txt --output modelfiles/optpar.txt \\
      --num_runs 500 --criterion MKG --crit_variable cout --obs_variable rout \\
      --params_subset "lp,cevpam,wcfc,wcwp,wcep,rrcs1,rrcs2,cmlt"
        """)

    parser.add_argument('--method', required=True,
                       help='Optimization method: MC, DEMC, SM, BN, Q2')
    parser.add_argument('--geoclass', required=True,
                       help='GeoClass.txt path (to determine landuse/soil counts)')
    parser.add_argument('--info_txt', required=True,
                       help='info.txt path (will be updated with calibration settings)')
    parser.add_argument('--output', required=True,
                       help='Output optpar.txt path')
    parser.add_argument('--criterion', default='MKG',
                       help='Calibration criterion code (default: MKG)')
    parser.add_argument('--crit_variable', default='cout',
                       help='Computed variable for criteria (default: cout)')
    parser.add_argument('--obs_variable', default='rout',
                       help='Recorded/observed variable for criteria (default: rout)')
    parser.add_argument('--outlet_subid', type=int, default=None,
                       help='Outlet subbasin ID for single-station calibration')
    parser.add_argument('--crit_weight', type=float, default=1.0,
                       help='Criterion weight (default: 1.0)')
    parser.add_argument('--crit_period', default='d',
                       help='Criterion period: d=daily, w=weekly, m=monthly (default: d)')

    # Monte Carlo specific
    parser.add_argument('--num_runs', type=int, default=500,
                       help='Number of MC runs or max iterations (default: 500)')

    # DEMC specific
    parser.add_argument('--demc_ngen', type=int, default=100,
                       help='DEMC: number of generations (default: 100)')
    parser.add_argument('--demc_npop', type=int, default=5,
                       help='DEMC: number of populations/chains, min 3 (default: 5)')
    parser.add_argument('--demc_gammascale', type=float, default=1.0,
                       help='DEMC: gamma scale factor (default: 1.0)')
    parser.add_argument('--demc_crossover', type=float, default=1.0,
                       help='DEMC: crossover probability (default: 1.0)')
    parser.add_argument('--demc_sigma', type=float, default=0.01,
                       help='DEMC: perturbation std dev (default: 0.01)')
    parser.add_argument('--demc_accprob', type=float, default=0.0,
                       help='DEMC: minimum acceptance probability (default: 0.0)')

    # NPC / substances
    parser.add_argument('--substances', default='none',
                       help='Include NPC parameters: "none", "N", "P", "N P" (default: none)')

    # Advanced
    parser.add_argument('--write_all', action='store_true', default=True,
                       help='Write allsim.txt with all simulation results (default: True)')
    parser.add_argument('--no_write_all', action='store_true',
                       help='Disable writing allsim.txt')
    parser.add_argument('--cal_log', action='store_true', default=True,
                       help='Write calibration.log (default: True)')
    parser.add_argument('--params_subset', default=None,
                       help='Comma-separated list of parameter names to calibrate (default: all)')
    parser.add_argument('--skip_info_update', action='store_true',
                       help='Skip updating info.txt (only generate optpar.txt)')

    args = parser.parse_args()

    # Validate inputs
    if not os.path.exists(args.geoclass):
        logger.error(f"GeoClass.txt not found: {args.geoclass}")
        sys.exit(1)

    if not args.skip_info_update and not os.path.exists(args.info_txt):
        logger.error(f"info.txt not found: {args.info_txt}")
        sys.exit(1)

    if args.method.upper() == 'DEMC' and args.demc_npop < 3:
        logger.error("DEMC requires at least 3 populations (--demc_npop >= 3)")
        sys.exit(1)

    # Read GeoClass to get dimensions
    n_landuse, n_soil = read_geoclass(args.geoclass)
    logger.info(f"GeoClass.txt: {n_landuse} land-use types, {n_soil} soil types")

    # Generate optpar.txt
    write_all = args.write_all and not args.no_write_all
    params = generate_optpar(
        method=args.method,
        n_landuse=n_landuse,
        n_soil=n_soil,
        output_path=args.output,
        num_runs=args.num_runs,
        substances=args.substances,
        demc_ngen=args.demc_ngen,
        demc_npop=args.demc_npop,
        demc_gammascale=args.demc_gammascale,
        demc_crossover=args.demc_crossover,
        demc_sigma=args.demc_sigma,
        demc_accprob=args.demc_accprob,
        write_all=write_all,
        cal_log=args.cal_log,
        params_subset=args.params_subset,
    )

    # Update info.txt with calibration criteria
    if not args.skip_info_update:
        update_info_txt(
            info_path=args.info_txt,
            criterion=args.criterion,
            crit_variable=args.crit_variable,
            obs_variable=args.obs_variable,
            outlet_subid=args.outlet_subid,
            crit_weight=args.crit_weight,
            crit_period=args.crit_period,
        )

    # Summary
    total_params = 0
    for name, ptype, pmin, pmax, prec, desc in params:
        if ptype == 'general':
            total_params += 1
        elif ptype == 'landuse':
            total_params += n_landuse
        elif ptype == 'soil':
            total_params += n_soil
    logger.info(f"Total calibrated dimensions: {total_params}")
    logger.info(f"Setup complete. Run HYPE to start calibration:")
    logger.info(f"  /mnt/disk1/Hydrocraft_server/model/hype/hype ./")
    logger.info(f"Output files (in resultdir):")
    logger.info(f"  allsim.txt     -- all simulation results (criterion + parameters)")
    logger.info(f"  bestsims.txt   -- best parameter sets")
    logger.info(f"  calibration.log -- calibration progress details")


if __name__ == '__main__':
    main()
