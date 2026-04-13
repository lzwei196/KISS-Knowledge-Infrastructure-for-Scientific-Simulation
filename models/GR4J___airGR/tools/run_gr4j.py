#!/usr/bin/env python3
"""
Execute GR4J model via rpy2 (R bridge) or subprocess.

Pipeline stage: s3 (Model execution) and s4 (Calibration)
Pattern: validate inputs -> process -> validate outputs

Modes:
  - simulation: Run GR4J with given parameters
  - calibration: Run Calibration_Michel to find optimal parameters

This tool wraps the complete airGR workflow:
  CreateInputsModel -> CreateRunOptions -> RunModel_GR4J / Calibration_Michel
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def validate_inputs(forcing_csv: str, params: dict = None,
                    mode: str = "simulation") -> list:
    """Validate inputs before model execution."""
    errors = []

    # Check forcing file exists
    if not Path(forcing_csv).exists():
        errors.append(f"Forcing file not found: {forcing_csv}")
        return errors

    df = pd.read_csv(forcing_csv, parse_dates=["Date"], nrows=10)

    required_cols = ["Date", "Precip_mm", "PotEvap_mm"]
    for col in required_cols:
        if col not in df.columns:
            errors.append(f"Missing required column: {col}")

    if mode == "simulation" and params is not None:
        if len(params) != 4:
            errors.append(f"GR4J requires exactly 4 parameters, got {len(params)}")
        if params.get("X1", 0) < 0.01:
            errors.append(f"X1 must be >= 0.01, got {params.get('X1')}")
        if params.get("X3", 0) < 0.01:
            errors.append(f"X3 must be >= 0.01, got {params.get('X3')}")
        if params.get("X4", 0) < 0.5:
            errors.append(f"X4 must be >= 0.5, got {params.get('X4')}")

    if mode == "calibration":
        if "Qobs_mm" not in df.columns:
            errors.append(
                "Calibration requires 'Qobs_mm' column in forcing CSV. "
                "Convert observed discharge to mm/day first."
            )

    return errors


def validate_outputs(result: dict) -> list:
    """Validate model outputs."""
    warnings = []

    if "qsim" in result:
        qsim = np.array(result["qsim"])
        if np.all(qsim == 0):
            warnings.append("All simulated discharge = 0 — check forcing data.")
        if np.any(qsim < 0):
            warnings.append("Negative simulated discharge found — numerical issue.")
        if np.nanmax(qsim) > 500:
            warnings.append(
                f"Max Qsim = {np.nanmax(qsim):.1f} mm/d — unrealistically high."
            )

    if "params" in result:
        p = result["params"]
        if p[0] > 2000:
            warnings.append(f"X1 = {p[0]:.1f} mm — at upper bound, may need wider range.")
        if p[3] > 10:
            warnings.append(f"X4 = {p[3]:.2f} d — unusually high time constant.")

    return warnings


# ---------------------------------------------------------------------------
# R script generation
# ---------------------------------------------------------------------------

def generate_r_script(forcing_csv: str, output_csv: str,
                       mode: str = "simulation",
                       params: dict = None,
                       warmup_years: int = 1,
                       run_start: str = None,
                       run_end: str = None,
                       criterion: str = "NSE",
                       output_json: str = None) -> str:
    """
    Generate R script for GR4J execution.

    Returns
    -------
    r_script : str, complete R script
    """
    param_str = ""
    if params and mode == "simulation":
        param_str = f"c({params['X1']}, {params['X2']}, {params['X3']}, {params['X4']})"

    crit_func = {
        "NSE": "ErrorCrit_NSE",
        "KGE": "ErrorCrit_KGE",
        "KGE2": "ErrorCrit_KGE2",
        "RMSE": "ErrorCrit_RMSE",
    }.get(criterion, "ErrorCrit_NSE")

    r_script = f'''
library(airGR)

# --- Read forcing data ---
data_raw <- read.csv("{forcing_csv}", stringsAsFactors = FALSE)
data_raw$Date <- as.POSIXct(data_raw$Date, format = "%Y-%m-%d", tz = "UTC")

# --- Prepare inputs ---
InputsModel <- CreateInputsModel(
  FUN_MOD = RunModel_GR4J,
  DatesR  = data_raw$Date,
  Precip  = data_raw$Precip_mm,
  PotEvap = data_raw$PotEvap_mm
)

# --- Define run period ---
'''
    if run_start and run_end:
        r_script += f'''
Ind_Run <- seq(
  which(format(data_raw$Date, format = "%Y-%m-%d") == "{run_start}"),
  which(format(data_raw$Date, format = "%Y-%m-%d") == "{run_end}")
)
'''
    else:
        r_script += '''
# Use second half of data for run, first half for warmup
n <- nrow(data_raw)
n_warmup <- min(365, floor(n / 3))
Ind_Run <- as.integer((n_warmup + 1):n)
'''

    r_script += f'''
# --- Create run options (warmup = {warmup_years} year) ---
RunOptions <- CreateRunOptions(
  FUN_MOD      = RunModel_GR4J,
  InputsModel  = InputsModel,
  IndPeriod_Run = Ind_Run,
  verbose      = FALSE
)
'''

    if mode == "calibration":
        r_script += f'''
# --- Calibration mode ---
# Prepare observed discharge for calibration
Qobs <- data_raw$Qobs_mm[Ind_Run]

InputsCrit <- CreateInputsCrit(
  FUN_CRIT    = {crit_func},
  InputsModel = InputsModel,
  RunOptions  = RunOptions,
  VarObs      = "Q",
  Obs         = Qobs
)

CalibOptions <- CreateCalibOptions(
  FUN_MOD   = RunModel_GR4J,
  FUN_CALIB = Calibration_Michel
)

OutputsCalib <- Calibration_Michel(
  InputsModel = InputsModel,
  RunOptions  = RunOptions,
  InputsCrit  = InputsCrit,
  CalibOptions = CalibOptions,
  FUN_MOD     = RunModel_GR4J,
  verbose     = TRUE
)

Param <- OutputsCalib$ParamFinalR
cat("CALIBRATED_PARAMS:", paste(Param, collapse = ","), "\\n")
cat("CALIBRATION_CRIT:", OutputsCalib$CritFinal, "\\n")
cat("CALIBRATION_NRUNS:", OutputsCalib$NRuns, "\\n")
'''
    else:
        r_script += f'''
# --- Simulation mode ---
Param <- {param_str}
'''

    r_script += f'''
# --- Run model ---
OutputsModel <- RunModel_GR4J(
  InputsModel = InputsModel,
  RunOptions  = RunOptions,
  Param       = Param
)

# --- Save outputs ---
results <- data.frame(
  Date      = format(OutputsModel$DatesR, "%Y-%m-%d"),
  Qsim_mm   = OutputsModel$Qsim,
  PotEvap   = OutputsModel$PotEvap,
  Precip    = OutputsModel$Precip,
  Prod      = OutputsModel$Prod,
  Pn        = OutputsModel$Pn,
  AE        = OutputsModel$AE,
  Perc      = OutputsModel$Perc,
  PR        = OutputsModel$PR,
  Rout      = OutputsModel$Rout,
  Exch      = OutputsModel$Exch,
  QR        = OutputsModel$QR,
  QD        = OutputsModel$QD
)
write.csv(results, "{output_csv}", row.names = FALSE)
cat("OUTPUT_ROWS:", nrow(results), "\\n")
cat("PARAM_USED:", paste(Param, collapse = ","), "\\n")
'''

    if mode == "calibration":
        r_script += f'''
# --- Compute efficiency ---
OutputsCrit_NSE <- ErrorCrit_NSE(InputsCrit = InputsCrit, OutputsModel = OutputsModel, verbose = FALSE)
OutputsCrit_KGE <- ErrorCrit_KGE(InputsCrit = InputsCrit, OutputsModel = OutputsModel, verbose = FALSE)
cat("NSE:", OutputsCrit_NSE$CritValue, "\\n")
cat("KGE:", OutputsCrit_KGE$CritValue, "\\n")
'''

    if output_json:
        r_script += f'''
# --- Save metadata ---
meta <- list(
  param = as.list(Param),
  n_timesteps = nrow(results),
  qsim_mean = mean(results$Qsim_mm, na.rm = TRUE),
  qsim_max = max(results$Qsim_mm, na.rm = TRUE),
  mode = "{mode}"
)
jsonlite_available <- requireNamespace("jsonlite", quietly = TRUE)
if (jsonlite_available) {{
  writeLines(jsonlite::toJSON(meta, auto_unbox = TRUE, pretty = TRUE), "{output_json}")
}}
'''

    return r_script


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def run_gr4j(forcing_csv: str, output_csv: str,
             mode: str = "simulation",
             params: dict = None,
             warmup_years: int = 1,
             run_start: str = None,
             run_end: str = None,
             criterion: str = "NSE",
             output_json: str = None) -> dict:
    """
    Run GR4J model.

    Parameters
    ----------
    forcing_csv   : path to forcing CSV
    output_csv    : path for output CSV
    mode          : 'simulation' or 'calibration'
    params        : dict with X1, X2, X3, X4 (simulation mode only)
    warmup_years  : number of years for warmup
    run_start     : start date (YYYY-MM-DD) or None for auto
    run_end       : end date (YYYY-MM-DD) or None for auto
    criterion     : calibration criterion (NSE, KGE, KGE2, RMSE)
    output_json   : optional path for metadata JSON

    Returns
    -------
    result : dict with execution summary
    """
    # --- Validate inputs ---
    errors = validate_inputs(forcing_csv, params, mode)
    if errors:
        raise ValueError("Input validation failed:\n" + "\n".join(errors))

    # --- Generate R script ---
    r_script = generate_r_script(
        forcing_csv=forcing_csv,
        output_csv=output_csv,
        mode=mode,
        params=params,
        warmup_years=warmup_years,
        run_start=run_start,
        run_end=run_end,
        criterion=criterion,
        output_json=output_json,
    )

    # --- Write and execute R script ---
    with tempfile.NamedTemporaryFile(mode="w", suffix=".R", delete=False) as f:
        f.write(r_script)
        r_script_path = f.name

    print(f"[run_gr4j] Executing R script: {r_script_path}")
    proc = subprocess.run(
        ["Rscript", "--vanilla", r_script_path],
        capture_output=True, text=True, timeout=600
    )

    # --- Parse results ---
    result = {
        "mode": mode,
        "forcing_csv": forcing_csv,
        "output_csv": output_csv,
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }

    if proc.returncode != 0:
        print(f"[run_gr4j] ERROR: R script failed with code {proc.returncode}")
        print(f"[run_gr4j] STDERR:\n{proc.stderr[:2000]}")
        result["status"] = "failed"
        return result

    # Parse stdout for key values
    for line in proc.stdout.split("\n"):
        if line.startswith("CALIBRATED_PARAMS:"):
            vals = line.split(":")[1].strip().split(",")
            result["calibrated_params"] = [float(v) for v in vals]
        elif line.startswith("PARAM_USED:"):
            vals = line.split(":")[1].strip().split(",")
            result["params"] = [float(v) for v in vals]
        elif line.startswith("NSE:"):
            result["NSE"] = float(line.split(":")[1].strip())
        elif line.startswith("KGE:"):
            result["KGE"] = float(line.split(":")[1].strip())
        elif line.startswith("OUTPUT_ROWS:"):
            result["n_timesteps"] = int(line.split(":")[1].strip())
        elif line.startswith("CALIBRATION_CRIT:"):
            result["calib_crit"] = float(line.split(":")[1].strip())

    # Read output and compute basic stats
    if Path(output_csv).exists():
        df = pd.read_csv(output_csv)
        result["qsim_mean"] = float(df["Qsim_mm"].mean())
        result["qsim_max"] = float(df["Qsim_mm"].max())
        result["qsim_min"] = float(df["Qsim_mm"].min())
        result["qsim"] = df["Qsim_mm"].tolist()

    # Validate outputs
    warnings = validate_outputs(result)
    for w in warnings:
        print(f"[run_gr4j] WARNING: {w}")

    result["status"] = "completed"
    print(f"[run_gr4j] Completed in {mode} mode, {result.get('n_timesteps', '?')} timesteps")
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Run GR4J model via airGR")
    parser.add_argument("--forcing", required=True, help="Input forcing CSV path")
    parser.add_argument("--output", required=True, help="Output CSV path")
    parser.add_argument("--mode", choices=["simulation", "calibration"],
                        default="simulation")
    parser.add_argument("--x1", type=float, help="Parameter X1 [mm]")
    parser.add_argument("--x2", type=float, help="Parameter X2 [mm/d]")
    parser.add_argument("--x3", type=float, help="Parameter X3 [mm]")
    parser.add_argument("--x4", type=float, help="Parameter X4 [d]")
    parser.add_argument("--warmup", type=int, default=1, help="Warmup years")
    parser.add_argument("--start", help="Run start date (YYYY-MM-DD)")
    parser.add_argument("--end", help="Run end date (YYYY-MM-DD)")
    parser.add_argument("--criterion", default="NSE",
                        choices=["NSE", "KGE", "KGE2", "RMSE"])
    parser.add_argument("--meta-json", help="Output metadata JSON path")

    args = parser.parse_args()

    params = None
    if args.mode == "simulation" and all([args.x1, args.x3, args.x4]):
        params = {"X1": args.x1, "X2": args.x2 or 0.0,
                  "X3": args.x3, "X4": args.x4}

    run_gr4j(
        forcing_csv=args.forcing,
        output_csv=args.output,
        mode=args.mode,
        params=params,
        warmup_years=args.warmup,
        run_start=args.start,
        run_end=args.end,
        criterion=args.criterion,
        output_json=args.meta_json,
    )


if __name__ == "__main__":
    main()
