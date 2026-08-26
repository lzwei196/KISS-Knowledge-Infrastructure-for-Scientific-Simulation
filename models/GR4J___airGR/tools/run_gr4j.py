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
                    mode: str = "simulation",
                    model: str = "gr4j") -> list:
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

    # CemaNeige snow module needs daily mean air temperature.
    if model == "cemaneige_gr4j" and "TempMean_degC" not in df.columns:
        errors.append(
            "CemaNeige (model=cemaneige_gr4j) requires a 'TempMean_degC' column "
            "in the forcing CSV. convert_forcing_to_gr4j writes this by default."
        )

    n_par = 6 if model == "cemaneige_gr4j" else 4
    if mode == "simulation" and params is not None:
        if len(params) != n_par:
            errors.append(f"{model} requires exactly {n_par} parameters, got {len(params)}")
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
                       output_json: str = None,
                       model: str = "gr4j",
                       hypso: list = None,
                       nlayers: int = 5) -> str:
    """
    Generate R script for GR4J execution.

    model : 'gr4j' (4-parameter, default) or 'cemaneige_gr4j' (6-parameter,
            snow-accounting via CemaNeige — use for snowmelt-dominated /
            cold-region catchments where winter precipitation falls as snow
            and the hydrograph is driven by a spring/summer freshet). The
            CemaNeige variant adds X5 (CTG, cold-content weighting [0,1]) and
            X6 (Kf, degree-day melt factor) and requires TempMean_degC forcing.

    hypso : optional 101-element hypsometric curve [m] (percentiles 0-100,
            ascending) for CemaNeige elevation layers. Without it CemaNeige
            runs as a single layer at the forcing elevation, which smears
            snow across the full relief of high-relief catchments; with it,
            airGR extrapolates T and P over `nlayers` elevation bands
            (DataAltiExtrapolation_Valery). Ignored for model='gr4j'.
    nlayers : number of CemaNeige elevation layers when hypso is given
            (airGR default 5).

    Returns
    -------
    r_script : str, complete R script
    """
    fun_mod = "RunModel_CemaNeigeGR4J" if model == "cemaneige_gr4j" else "RunModel_GR4J"

    # Extra CreateInputsModel arguments for CemaNeige (TempMean, and the
    # optional elevation-layer discretization from the hypsometric curve).
    hypso_decl = ""
    extra_inputs = ""
    if model == "cemaneige_gr4j":
        extra_inputs = ",\n  TempMean = data_raw$TempMean_degC"
        if hypso is not None:
            if len(hypso) != 101:
                raise ValueError(
                    f"HypsoData must have exactly 101 values (percentiles 0-100), got {len(hypso)}"
                )
            if any(hypso[i] > hypso[i + 1] for i in range(100)):
                raise ValueError("HypsoData must be ascending (min to max elevation)")
            vals = ", ".join(f"{float(h):.2f}" for h in hypso)
            hypso_decl = f"HypsoData <- c({vals})\n"
            extra_inputs += (
                ",\n  HypsoData = HypsoData"
                ",\n  ZInputs  = median(HypsoData)"
                f",\n  NLayers  = {int(nlayers)}L"
            )
    param_str = ""
    if params and mode == "simulation":
        if model == "cemaneige_gr4j":
            param_str = (f"c({params['X1']}, {params['X2']}, {params['X3']}, "
                         f"{params['X4']}, {params['X5']}, {params['X6']})")
        else:
            param_str = f"c({params['X1']}, {params['X2']}, {params['X3']}, {params['X4']})"

    crit_func = {
        "NSE": "ErrorCrit_NSE",
        "KGE": "ErrorCrit_KGE",
        "KGE2": "ErrorCrit_KGE2",
        "RMSE": "ErrorCrit_RMSE",
    }.get(criterion, "ErrorCrit_NSE")

    r_script = f'''
# airGR is installed in the HydroCraft user library; --vanilla/--no-environ
# may not pick up R_LIBS_USER, so register it explicitly (robust fix).
.libPaths(c("KISSPATH_HOME/R/library", .libPaths()))
library(airGR)

# --- Read forcing data ---
data_raw <- read.csv("{forcing_csv}", stringsAsFactors = FALSE)
data_raw$Date <- as.POSIXct(data_raw$Date, format = "%Y-%m-%d", tz = "UTC")

# --- Prepare inputs ---
{hypso_decl}InputsModel <- CreateInputsModel(
  FUN_MOD = {fun_mod},
  DatesR  = data_raw$Date,
  Precip  = data_raw$Precip_mm,
  PotEvap = data_raw$PotEvap_mm{extra_inputs}
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
# --- Explicit warm-up period (warmup = {warmup_years} year) ---
# Previously `warmup_years` was only echoed in this comment: it never set
# IndPeriod_WarmUp, so airGR silently fell back to its default (the year
# preceding Ind_Run IF present in the forcing, else NO warm-up with only a
# quiet warning). That made `--warmup` a no-op and, when --start sat at the
# first forcing record, scored the un-spun-up first-year transient into the
# calibration criterion -- which depressed the reported NSE dramatically even
# though the fitted parameters were fine (HYDAT 09AC007, 2026-06-23: reported
# cal NSE 0.25 vs an actual post-warm-up 0.61). We now build IndPeriod_WarmUp
# explicitly as the warmup_years*365 days immediately preceding the run period
# (identical to airGR's auto-default when a buffer exists, so prior validated
# runs are unchanged) and warn loudly when no buffer is available.
warmup_len <- as.integer({warmup_years} * 365)
ws <- max(1L, as.integer(Ind_Run[1] - warmup_len))
if (ws < Ind_Run[1]) {{
  IndPeriod_WarmUp <- as.integer(seq(ws, Ind_Run[1] - 1L))
}} else {{
  # airGR sentinel for "run with no warm-up" is the single value 0L
  # (integer(0) trips an internal tail()/identical check and errors).
  IndPeriod_WarmUp <- 0L
  cat("WARMUP_WARNING: the run period starts at the first forcing record, so",
      "no warm-up buffer is available. Provide forcing that extends >=",
      {warmup_years}, "year(s) before --start; otherwise the first year is an",
      "un-spun-up transient that depresses the calibration criterion.\\n")
}}

RunOptions <- CreateRunOptions(
  FUN_MOD          = {fun_mod},
  InputsModel      = InputsModel,
  IndPeriod_WarmUp = IndPeriod_WarmUp,
  IndPeriod_Run    = Ind_Run,
  verbose          = FALSE
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
  FUN_MOD   = {fun_mod},
  FUN_CALIB = Calibration_Michel
)

OutputsCalib <- Calibration_Michel(
  InputsModel = InputsModel,
  RunOptions  = RunOptions,
  InputsCrit  = InputsCrit,
  CalibOptions = CalibOptions,
  FUN_MOD     = {fun_mod},
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
OutputsModel <- {fun_mod}(
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
  AExch     = OutputsModel$AExch,
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
             output_json: str = None,
             model: str = "gr4j",
             hypso: list = None,
             nlayers: int = 5) -> dict:
    """
    Run GR4J model.

    Parameters
    ----------
    forcing_csv   : path to forcing CSV
    output_csv    : path for output CSV
    mode          : 'simulation' or 'calibration'
    params        : dict with X1, X2, X3, X4 (simulation mode only;
                    plus X5, X6 when model='cemaneige_gr4j')
    warmup_years  : number of years for warmup
    run_start     : start date (YYYY-MM-DD) or None for auto
    run_end       : end date (YYYY-MM-DD) or None for auto
    criterion     : calibration criterion (NSE, KGE, KGE2, RMSE)
    output_json   : optional path for metadata JSON
    model         : 'gr4j' (default) or 'cemaneige_gr4j' (snow-accounting)
    hypso         : optional 101-point hypsometric curve [m] for CemaNeige
                    elevation layers (see generate_r_script)
    nlayers       : CemaNeige elevation layers when hypso is given (default 5)

    Returns
    -------
    result : dict with execution summary
    """
    # --- Validate inputs ---
    errors = validate_inputs(forcing_csv, params, mode, model)
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
        model=model,
        hypso=hypso,
        nlayers=nlayers,
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
        if line.startswith("WARMUP_WARNING:"):
            print(f"[run_gr4j] WARNING: {line.split(':', 1)[1].strip()}")
            result["warmup_warning"] = line.split(":", 1)[1].strip()
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
    # Surface calibration results so the CLI user/agent can see them without
    # having to re-parse the R stdout (previously these were parsed into the
    # result dict but never printed).
    if "calibrated_params" in result:
        print(f"[run_gr4j] Calibrated params: {result['calibrated_params']}")
    if "calib_crit" in result:
        print(f"[run_gr4j] Calibration {criterion}: {result['calib_crit']:.4f}")
    if "NSE" in result:
        print(f"[run_gr4j] NSE: {result['NSE']:.4f}  KGE: {result.get('KGE', float('nan')):.4f}")
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
    parser.add_argument("--x5", type=float,
                        help="CemaNeige X5 (CTG, cold-content weight [0,1])")
    parser.add_argument("--x6", type=float,
                        help="CemaNeige X6 (Kf, degree-day melt factor)")
    parser.add_argument("--model", choices=["gr4j", "cemaneige_gr4j"],
                        default="gr4j",
                        help="gr4j (4-param) or cemaneige_gr4j (6-param snow module)")
    parser.add_argument("--snow", action="store_true",
                        help="Shortcut for --model cemaneige_gr4j (snow accounting)")
    parser.add_argument("--hypso-json",
                        help="Catchment params JSON (from convert_catchment_params) "
                             "with a 101-point 'hypsometry' array [m]; enables "
                             "CemaNeige elevation layers for high-relief basins")
    parser.add_argument("--nlayers", type=int, default=5,
                        help="CemaNeige elevation layers with --hypso-json (default 5)")
    parser.add_argument("--warmup", type=int, default=1, help="Warmup years")
    parser.add_argument("--start", help="Run start date (YYYY-MM-DD)")
    parser.add_argument("--end", help="Run end date (YYYY-MM-DD)")
    parser.add_argument("--criterion", default="NSE",
                        choices=["NSE", "KGE", "KGE2", "RMSE"])
    parser.add_argument("--meta-json", help="Output metadata JSON path")

    args = parser.parse_args()

    model = "cemaneige_gr4j" if (args.snow or args.model == "cemaneige_gr4j") else "gr4j"

    hypso = None
    if args.hypso_json:
        if model != "cemaneige_gr4j":
            print("[run_gr4j] WARNING: --hypso-json is only used with "
                  "--snow/--model cemaneige_gr4j; ignoring.")
        else:
            with open(args.hypso_json) as f:
                cp = json.load(f)
            hypso = cp.get("hypsometry")
            if hypso is None:
                raise ValueError(
                    f"No 'hypsometry' array in {args.hypso_json}. Run "
                    "convert_catchment_params with DEM-derived hypsometry first."
                )

    params = None
    if args.mode == "simulation" and all([args.x1, args.x3, args.x4]):
        params = {"X1": args.x1, "X2": args.x2 or 0.0,
                  "X3": args.x3, "X4": args.x4}
        if model == "cemaneige_gr4j":
            params["X5"] = args.x5 if args.x5 is not None else 0.5
            params["X6"] = args.x6 if args.x6 is not None else 3.0

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
        model=model,
        hypso=hypso,
        nlayers=args.nlayers,
    )


if __name__ == "__main__":
    main()
