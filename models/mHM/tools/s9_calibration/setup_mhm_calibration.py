#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
Tool ID:      setup_mhm_calibration
Stage:        s9_calibration
Description:  Configure and run mHM's built-in DDS/SCE calibration, then extract
              best-fit MPR global parameters for regionalization transfer.

mHM has a BUILT-IN optimizer. Calibration works by:
  1. Setting `optimize = .TRUE.` in mhm.nml
  2. Choosing optimizer: opti_method = 1 (DDS), 2 (SA), 3 (SCE)
  3. Choosing objective: opti_function = 10 (KGE), 1 (NSE), 9 (KGE v2012)
  4. Setting iteration count: nIterations (default 1000 for DDS)
  5. Running the mHM binary -- it self-calibrates
  6. Best parameters are written to FinalParam.nml and optimization log

The calibrated mhm_parameter.nml (FinalParam.nml) can then be transferred to
ungauged basins via s10_regionalize/transfer_mpr_params.py. This is the
CORE MPR VALUE CHAIN:
    calibrate (s9) -> extract best params -> transfer (s10) -> predict ungauged

Basin-type presets adjust the BOUNDS (not just starting values) to help the
optimizer converge faster. For example, semi-arid basins should search in
wider infiltration ranges but narrower snow ranges.

Inputs:
  --run_dir            : mHM run directory (must have mhm.nml and all input data ready)
  --opti_method        : 1=DDS (default, recommended), 2=SA, 3=SCE
  --opti_function      : 10=KGE (default), 1=1-NSE, 2=1-lnNSE, 9=KGE(2012)
  --n_iterations       : number of iterations (default 1000; use 200 for quick test)
  --basin_type         : humid_subtropical|semi_arid|cold_alpine|tropical (optional, adjusts bounds)
  --execute            : actually run mHM calibration (default: only generate config)
  --parse_results      : parse optimization output and extract best parameters

Outputs:
  - Modified mhm.nml with optimize=.TRUE. and optimizer settings
  - calibration_config.json documenting the setup
  - If --execute: runs mHM binary
  - If --parse_results: calibrated_parameters.json + copies FinalParam.nml

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import json
import logging
import re
import shutil
import subprocess
from pathlib import Path
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
RUN_DIR = ""
OPTI_METHOD = 1       # 1=DDS (recommended for mHM)
OPTI_FUNCTION = 10    # 10=KGE (recommended)
N_ITERATIONS = 1000   # DDS: 1000 is usually sufficient for ~50 active params
BASIN_TYPE = ""       # Optional: humid_subtropical, semi_arid, cold_alpine, tropical
EXECUTE = False       # Actually run the binary
PARSE_RESULTS = False # Parse calibration output

MHM_BINARY = os.path.join(
    os.environ.get("HYDROCRAFT_ROOT", "/mnt/disk1/Hydrocraft_server"),
    "model/mhm/mhm"
)

if len(sys.argv) > 1:
    import argparse
    parser = argparse.ArgumentParser(description="Setup mHM calibration")
    parser.add_argument("--run_dir", required=True, help="mHM run directory")
    parser.add_argument("--opti_method", type=int, default=1,
                        choices=[1, 2, 3],
                        help="1=DDS, 2=SA, 3=SCE")
    parser.add_argument("--opti_function", type=int, default=1,
                        help="Objective function: 10=KGE, 1=1-NSE, 9=KGE(2012)")
    parser.add_argument("--n_iterations", type=int, default=1000,
                        help="Number of optimization iterations")
    parser.add_argument("--basin_type", default="",
                        choices=["", "humid_subtropical", "semi_arid", "cold_alpine", "tropical"],
                        help="Basin type for parameter bound adjustment")
    parser.add_argument("--execute", action="store_true",
                        help="Actually run mHM calibration binary")
    parser.add_argument("--parse_results", action="store_true",
                        help="Parse calibration output to extract best parameters")
    args = parser.parse_args()
    RUN_DIR = args.run_dir
    OPTI_METHOD = args.opti_method
    OPTI_FUNCTION = args.opti_function
    N_ITERATIONS = args.n_iterations
    BASIN_TYPE = args.basin_type
    EXECUTE = args.execute
    PARSE_RESULTS = args.parse_results


# ---------------------------------------------------------------------------
# Basin-type-specific parameter BOUND adjustments
#
# The mHM template has German/European calibrated bounds. For different
# climates, the optimizer needs different search ranges. These adjustments
# widen or narrow bounds based on hydrological reasoning.
# ---------------------------------------------------------------------------

BASIN_TYPE_BOUNDS = {
    "humid_subtropical": {
        # Wider infiltration range (monsoon dynamics)
        "infiltrationShapeFactor":          (1.0, 4.0),
        # Wider interflow (deep subtropical soils)
        "interflowStorageCapacityFactor":   (75.0, 300.0),
        "interflowRecession_slope":         (0.0, 15.0),
        # Higher recharge potential
        "rechargeCoefficient":              (0.0, 50.0),
        # Wider baseflow recession (varied aquifer types)
        "GeoParam(1,:)":                    (1.0, 1000.0),
        "GeoParam(2,:)":                    (1.0, 1000.0),
        "GeoParam(3,:)":                    (1.0, 1000.0),
        "GeoParam(4,:)":                    (1.0, 1000.0),
        # Narrower snow ranges (snow is rare)
        "snowTreshholdTemperature":          (0.0, 2.0),
        "degreeDayFactor_forest":            (0.0, 2.0),
        # Higher canopy interception range (dense forests)
        "canopyInterceptionFactor":          (0.15, 0.40),
    },
    "semi_arid": {
        # High infiltration shape (Hortonian flow on crusted soils)
        "infiltrationShapeFactor":          (2.0, 4.0),
        # Narrow interflow (thin soils)
        "interflowStorageCapacityFactor":   (75.0, 150.0),
        "interflowRecession_slope":         (0.0, 8.0),
        # Low recharge
        "rechargeCoefficient":              (0.0, 20.0),
        # Slow baseflow (deep water table)
        "GeoParam(1,:)":                    (1.0, 500.0),
        "GeoParam(2,:)":                    (1.0, 500.0),
        "GeoParam(3,:)":                    (1.0, 500.0),
        "GeoParam(4,:)":                    (1.0, 500.0),
        # Snow still possible in continental semi-arid
        "snowTreshholdTemperature":          (-2.0, 2.0),
        # Low canopy interception (sparse vegetation)
        "canopyInterceptionFactor":          (0.10, 0.25),
    },
    "cold_alpine": {
        # Snow is dominant -- wide ranges
        "snowTreshholdTemperature":          (-2.0, 2.0),
        "degreeDayFactor_forest":            (0.0, 4.0),
        "degreeDayFactor_pervious":          (0.0, 3.0),
        "maxDegreeDayFactor_forest":         (0.0, 8.0),
        "maxDegreeDayFactor_pervious":       (0.0, 8.0),
        # Moderate infiltration
        "infiltrationShapeFactor":          (1.0, 3.0),
        # Moderate interflow
        "interflowStorageCapacityFactor":   (75.0, 200.0),
        # Moderate recharge
        "rechargeCoefficient":              (0.0, 40.0),
    },
    "tropical": {
        # No snow
        "snowTreshholdTemperature":          (1.5, 2.0),
        "degreeDayFactor_forest":            (0.0, 0.5),
        "degreeDayFactor_pervious":          (0.0, 0.5),
        # High infiltration shape (intense convective rainfall)
        "infiltrationShapeFactor":          (1.5, 4.0),
        # Large interflow (deep lateritic soils)
        "interflowStorageCapacityFactor":   (100.0, 300.0),
        "interflowRecession_slope":         (2.0, 15.0),
        # High recharge
        "rechargeCoefficient":              (10.0, 50.0),
        # High canopy interception (dense canopy)
        "canopyInterceptionFactor":          (0.20, 0.40),
        # Fast baseflow (laterite aquifers)
        "GeoParam(1,:)":                    (50.0, 1000.0),
        "GeoParam(2,:)":                    (50.0, 1000.0),
        "GeoParam(3,:)":                    (50.0, 1000.0),
        "GeoParam(4,:)":                    (50.0, 1000.0),
    },
}


def modify_mhm_nml_for_calibration(nml_path, opti_method, opti_function, n_iterations):
    """Modify mhm.nml to enable optimization.

    Key settings:
      optimize = .TRUE.
      opti_method = 1 (DDS) / 2 (SA) / 3 (SCE)
      opti_function = 10 (KGE) / 1 (1-NSE) / 9 (KGE 2012)
      nIterations = N
    """
    with open(nml_path) as f:
        content = f.read()

    # Replace optimize = .FALSE. with .TRUE.
    content = re.sub(
        r'(optimize\s*=\s*)\.FALSE\.',
        r'\g<1>.TRUE.',
        content
    )

    # Update opti_method
    content = re.sub(
        r'(opti_method\s*=\s*)\d+',
        rf'\g<1>{opti_method}',
        content
    )

    # Update opti_function
    content = re.sub(
        r'(opti_function\s*=\s*)\d+',
        rf'\g<1>{opti_function}',
        content
    )

    # Update nIterations
    content = re.sub(
        r'(nIterations\s*=\s*)\d+',
        rf'\g<1>{n_iterations}',
        content
    )

    # For SCE: set reasonable ngs based on parameter count
    if opti_method == 3:
        content = re.sub(
            r'(sce_ngs\s*=\s*)\d+',
            r'\g<1>5',
            content
        )

    with open(nml_path, 'w') as f:
        f.write(content)

    logger.info(f"Modified {nml_path}: optimize=.TRUE., method={opti_method}, "
                f"function={opti_function}, iterations={n_iterations}")


def adjust_parameter_bounds(param_nml_path, basin_type):
    """Adjust parameter bounds in mhm_parameter.nml based on basin type.

    Only modifies lower and upper bounds (columns 1 and 2), preserving
    the current value, flag, and scaling.
    """
    if basin_type not in BASIN_TYPE_BOUNDS:
        logger.info(f"No basin-type bound adjustments for '{basin_type}'")
        return 0

    bounds = BASIN_TYPE_BOUNDS[basin_type]
    logger.info(f"Adjusting parameter bounds for basin type: {basin_type} "
                f"({len(bounds)} parameters)")

    with open(param_nml_path) as f:
        lines = f.readlines()

    n_adjusted = 0
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('!') or stripped.startswith('&') or stripped == '/' or not stripped:
            new_lines.append(line)
            continue

        if '=' in stripped:
            param_name = stripped.split('=')[0].strip()
            if param_name in bounds:
                rhs = stripped.split('=', 1)[1]
                parts = [p.strip() for p in rhs.split(',')]
                if len(parts) >= 5:
                    new_lower, new_upper = bounds[param_name]
                    old_lower = float(parts[0])
                    old_upper = float(parts[1])
                    current_val = float(parts[2])

                    # Clamp current value to new bounds
                    if current_val < new_lower or current_val > new_upper:
                        current_val = (new_lower + new_upper) / 2.0
                        logger.info(f"  {param_name}: value reset to midpoint {current_val:.4f}")

                    parts[0] = f"{new_lower:8.4f}"
                    parts[1] = f"{new_upper:8.4f}"
                    parts[2] = f"{current_val:12.4f}"

                    leading = line[:len(line) - len(line.lstrip())]
                    new_rhs = ", ".join(p.strip() for p in parts)
                    new_line = f"{leading}{param_name.ljust(40)} = {new_rhs}\n"
                    new_lines.append(new_line)
                    logger.info(f"  {param_name}: bounds [{old_lower}, {old_upper}] -> [{new_lower}, {new_upper}]")
                    n_adjusted += 1
                    continue

        new_lines.append(line)

    with open(param_nml_path, 'w') as f:
        f.writelines(new_lines)

    logger.info(f"Adjusted {n_adjusted} parameter bounds")
    return n_adjusted


def run_mhm_calibration(run_dir, mhm_binary):
    """Execute the mHM binary for calibration.

    The binary reads mhm.nml (with optimize=.TRUE.) and runs the optimizer.
    Progress is printed to stdout. The best parameter set is written to
    FinalParam.nml in the run directory.
    """
    if not Path(mhm_binary).exists():
        logger.error(f"mHM binary not found: {mhm_binary}")
        sys.exit(2)

    logger.info(f"Starting mHM calibration in {run_dir}")
    logger.info(f"Binary: {mhm_binary}")
    logger.info("This may take minutes to hours depending on domain size and nIterations...")

    try:
        result = subprocess.run(
            [mhm_binary],
            cwd=str(run_dir),
            capture_output=True,
            text=True,
            timeout=86400  # 24 hour timeout
        )

        # Save stdout/stderr
        log_dir = Path(run_dir) / "calibration_logs"
        log_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        stdout_path = log_dir / f"calibration_stdout_{timestamp}.log"
        stderr_path = log_dir / f"calibration_stderr_{timestamp}.log"
        with open(stdout_path, 'w') as f:
            f.write(result.stdout)
        with open(stderr_path, 'w') as f:
            f.write(result.stderr)

        if result.returncode != 0:
            logger.error(f"mHM calibration failed with return code {result.returncode}")
            logger.error(f"stderr: {result.stderr[-2000:]}")
            sys.exit(2)

        # TRAP (dt_r14). mHM exits 0 having done nothing: a Fortran `stop '<msg>'`
        # returns status 0. mo_dds.F90:169 does exactly that when nIterations < 6.
        # NEVER trust the return code alone -- assert the expected artefact exists.
        final_param = Path(run_dir) / "FinalParam.nml"
        if not final_param.exists():
            tail = (result.stdout or "")[-2000:]
            logger.error(
                f"mHM exited 0 but wrote no FinalParam.nml -- a Fortran `stop` "
                f"(exit status 0) swallowed the run. Check nIterations >= 6 (dt_r14) "
                f"and the &optional_data requirement of opti_function (dt_r15).\n"
                f"stdout tail:\n{tail}")
            sys.exit(2)

        logger.info(f"mHM calibration completed. Logs saved to {log_dir}")
        return result.returncode

    except subprocess.TimeoutExpired:
        logger.error("mHM calibration timed out after 24 hours")
        sys.exit(2)
    except Exception as e:
        logger.error(f"Failed to run mHM: {e}")
        sys.exit(2)


def parse_calibration_output(run_dir):
    """Parse calibration output to extract best parameters and performance.

    mHM writes several calibration output files:
      - FinalParam.nml: best parameter set (namelist format)
      - daily_discharge.out: observed vs simulated with best params
      - mo_dds.out or similar: optimization trace
      - ConfigFile.log: run configuration
    """
    run_path = Path(run_dir)
    results = {
        "status": "success",
        "run_dir": str(run_dir),
        "timestamp": datetime.now().isoformat(),
    }

    # Look for FinalParam.nml (mHM writes this with best calibrated parameters)
    final_param = run_path / "FinalParam.nml"
    if not final_param.exists():
        # mHM may write it elsewhere or with different name
        candidates = list(run_path.glob("*inal*aram*")) + list(run_path.glob("*best*param*"))
        if candidates:
            final_param = candidates[0]

    if final_param.exists():
        # Copy to a stable name
        calibrated_nml = run_path / "mhm_parameter_calibrated.nml"
        shutil.copy2(final_param, calibrated_nml)
        results["calibrated_parameter_file"] = str(calibrated_nml)
        results["final_param_source"] = str(final_param)
        logger.info(f"Found calibrated parameters: {final_param}")

        # Parse parameter values
        params = {}
        current_group = None
        with open(final_param) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('!'):
                    continue
                if line.startswith('&'):
                    current_group = line[1:].strip()
                    continue
                if line == '/':
                    current_group = None
                    continue
                match = re.match(
                    r'(\w[\w(),:]*)\s*=\s*(-?[\d.eE+\-]+)\s*,\s*(-?[\d.eE+\-]+)\s*,\s*(-?[\d.eE+\-]+)',
                    line
                )
                if match:
                    name = match.group(1).strip()
                    key = f"{current_group}/{name}" if current_group else name
                    params[key] = {
                        "lower": float(match.group(2)),
                        "upper": float(match.group(3)),
                        "value": float(match.group(4)),
                    }
        results["n_parameters"] = len(params)
        results["parameters"] = params
    else:
        logger.warning("FinalParam.nml not found -- calibration may not have completed")
        results["calibrated_parameter_file"] = None

    # Parse daily_discharge.out for performance metrics
    daily_out = run_path / "output_b1" / "daily_discharge.out"
    if not daily_out.exists():
        daily_out = run_path / "daily_discharge.out"

    if daily_out.exists():
        import numpy as np
        obs_vals = []
        sim_vals = []
        with open(daily_out) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("!"):
                    continue
                parts = line.split()
                if len(parts) >= 6:
                    try:
                        obs = float(parts[4])
                        sim = float(parts[5])
                        obs_vals.append(obs)
                        sim_vals.append(sim)
                    except ValueError:
                        continue

        if obs_vals:
            obs_arr = np.array(obs_vals)
            sim_arr = np.array(sim_vals)

            # Skip warmup (first year)
            skip = min(365, len(obs_arr) // 3)
            obs_eval = obs_arr[skip:]
            sim_eval = sim_arr[skip:]

            # Mask out nodata
            mask = ~(np.isnan(obs_eval) | np.isnan(sim_eval) |
                     (obs_eval < 0) | (sim_eval < 0))
            obs_clean = obs_eval[mask]
            sim_clean = sim_eval[mask]

            if len(obs_clean) > 10:
                # NSE
                ss_res = np.sum((obs_clean - sim_clean) ** 2)
                ss_tot = np.sum((obs_clean - np.mean(obs_clean)) ** 2)
                nse = 1 - ss_res / ss_tot if ss_tot > 0 else float('nan')

                # KGE
                r = np.corrcoef(obs_clean, sim_clean)[0, 1]
                alpha = np.std(sim_clean) / np.std(obs_clean) if np.std(obs_clean) > 0 else 1
                beta = np.mean(sim_clean) / np.mean(obs_clean) if np.mean(obs_clean) > 0 else 1
                kge = 1 - np.sqrt((r - 1)**2 + (alpha - 1)**2 + (beta - 1)**2)

                # RMSE
                rmse = np.sqrt(np.mean((obs_clean - sim_clean) ** 2))

                # PBIAS
                pbias = 100.0 * np.sum(sim_clean - obs_clean) / np.sum(obs_clean)

                results["performance"] = {
                    "NSE": round(float(nse), 4),
                    "KGE": round(float(kge), 4),
                    "RMSE": round(float(rmse), 2),
                    "PBIAS": round(float(pbias), 2),
                    "r": round(float(r), 4),
                    "n_valid_days": int(len(obs_clean)),
                    "warmup_skipped": skip,
                }
                logger.info(f"Calibration performance: NSE={nse:.4f}, KGE={kge:.4f}, "
                            f"RMSE={rmse:.2f}, PBIAS={pbias:.2f}%")

    # Parse optimization trace (DDS writes to stdout, check logs)
    log_dir = run_path / "calibration_logs"
    if log_dir.exists():
        log_files = sorted(log_dir.glob("calibration_stdout_*.log"))
        if log_files:
            latest_log = log_files[-1]
            # Extract best objective function value from log
            best_obj = None
            n_evals = 0
            with open(latest_log) as f:
                for line in f:
                    if "best" in line.lower() and ("obj" in line.lower() or "kge" in line.lower() or "nse" in line.lower()):
                        # Try to extract numeric value
                        numbers = re.findall(r'[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?', line)
                        if numbers:
                            best_obj = float(numbers[-1])
                    if "iteration" in line.lower() or "eval" in line.lower():
                        n_evals += 1

            if best_obj is not None:
                results["optimization_trace"] = {
                    "best_objective_value": best_obj,
                    "n_evaluations_logged": n_evals,
                    "log_file": str(latest_log),
                }

    return results


def validate_inputs():
    errors = []
    if not RUN_DIR or not Path(RUN_DIR).exists():
        errors.append(f"Run directory not found: {RUN_DIR}")
    else:
        nml_path = Path(RUN_DIR) / "mhm.nml"
        if not nml_path.exists():
            errors.append(f"mhm.nml not found in run directory: {nml_path}")
        param_nml = Path(RUN_DIR) / "mhm_parameter.nml"
        if not param_nml.exists():
            errors.append(f"mhm_parameter.nml not found: {param_nml}")

    if EXECUTE and not Path(MHM_BINARY).exists():
        errors.append(f"mHM binary not found: {MHM_BINARY}")

    if OPTI_METHOD not in (1, 2, 3):
        errors.append(f"Invalid opti_method: {OPTI_METHOD}. Must be 1 (DDS), 2 (SA), or 3 (SCE)")

    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def process():
    run_dir = Path(RUN_DIR)
    nml_path = run_dir / "mhm.nml"
    param_nml = run_dir / "mhm_parameter.nml"

    # TRAP (dt_r16). This tool used to rewrite mhm.nml on EVERY invocation. Because
    # the documented recipe calls it three times (configure -> --execute ->
    # --parse_results) and the last two carry no optimizer flags, the --execute call
    # silently stamped the argparse DEFAULTS back into mhm.nml -- a run configured
    # `--opti_function 1 --n_iterations 2000` actually executed with 10/1000.
    # Only the CONFIGURE invocation (neither --execute nor --parse_results) may write.
    configuring = not (EXECUTE or PARSE_RESULTS)

    n_adjusted = 0
    if configuring:
        # Step 1: Modify mhm.nml for calibration
        modify_mhm_nml_for_calibration(nml_path, OPTI_METHOD, OPTI_FUNCTION, N_ITERATIONS)

        # Step 2: Adjust parameter bounds if basin type specified
        if BASIN_TYPE:
            n_adjusted = adjust_parameter_bounds(param_nml, BASIN_TYPE)
    else:
        logger.info(f"Not the configure call (execute={EXECUTE}, "
                    f"parse_results={PARSE_RESULTS}): leaving mhm.nml untouched (dt_r16)")

    # Document calibration setup
    opti_method_names = {1: "DDS", 2: "SA", 3: "SCE"}
    # Verified against v5.13.1 source: src/mRM/mo_mrm_objective_function_runoff.F90
    # (discharge-only) and src/mHM/mo_objective_function.F90 (multi-variable).
    # dt_r15: 10 is NOT KGE of discharge -- it is 1 - KGE of catchment-average SOIL
    # MOISTURE and requires &optional_data. For discharge use 1 or 9.
    opti_function_names = {
        1: "1-NSE(Q)", 2: "1-lnNSE(Q)", 3: "1-0.5*(NSE+lnNSE)(Q)",
        9: "1-KGE(Q)", 14: "multi-gauge KGE, power-6 norm",
        10: "1-KGE(soil moisture) [needs &optional_data]",
        15: "KGE(Q)*RMSE(TWS) [needs &optional_data]",
        17: "KGE(neutrons) [needs &optional_data]",
    }

    config = {
        "status": "configured",
        "run_dir": str(run_dir),
        "optimizer": opti_method_names.get(OPTI_METHOD, str(OPTI_METHOD)),
        "opti_method": OPTI_METHOD,
        "objective_function": opti_function_names.get(OPTI_FUNCTION, str(OPTI_FUNCTION)),
        "opti_function": OPTI_FUNCTION,
        "n_iterations": N_ITERATIONS,
        "basin_type": BASIN_TYPE or "default",
        "n_bounds_adjusted": n_adjusted,
        "mhm_binary": MHM_BINARY,
        "timestamp": datetime.now().isoformat(),
        "notes": (
            f"mHM will use {opti_method_names.get(OPTI_METHOD, '?')} optimizer with "
            f"{opti_function_names.get(OPTI_FUNCTION, '?')} objective for {N_ITERATIONS} iterations. "
            f"Best parameters will be written to FinalParam.nml. "
            f"Transfer these to ungauged basins using s10_regionalize/transfer_mpr_params.py."
        ),
    }

    config_path = run_dir / "calibration_config.json"
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)
    logger.info(f"Calibration config written to {config_path}")

    # Step 3: Execute if requested
    if EXECUTE:
        logger.info("=" * 60)
        logger.info("STARTING mHM CALIBRATION")
        logger.info("=" * 60)
        run_mhm_calibration(run_dir, MHM_BINARY)
        config["status"] = "completed"

    # Step 4: Parse results if requested
    if PARSE_RESULTS:
        results = parse_calibration_output(run_dir)
        config.update(results)

    # Update config file
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)

    print(json.dumps(config, indent=2))
    return str(config_path)


def validate_outputs(output_path):
    if not Path(output_path).exists():
        logger.error(f"Calibration config not created: {output_path}")
        sys.exit(3)

    config = json.load(open(output_path))
    if config.get("status") == "completed":
        # Verify calibrated parameters exist
        cal_file = config.get("calibrated_parameter_file")
        if cal_file and not Path(cal_file).exists():
            logger.warning(f"Calibrated parameter file not found: {cal_file}")

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
