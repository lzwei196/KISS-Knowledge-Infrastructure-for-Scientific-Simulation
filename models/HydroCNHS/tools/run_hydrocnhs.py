#!/usr/bin/env python3
"""
run_hydrocnhs.py — Execute HydroCNHS model simulation or calibration.

Wraps hydrocnhs.Model.run() and hydrocnhs.calibration.GA_DEAP for automated
execution. Handles loading climate data, running the model, and saving results.

CRITICAL:
  - Climate data must be Python dicts: {outlet_name: [daily_values]}
  - temp in °C, prec in cm/day, pet in cm/day (optional)
  - Model YAML must have correct DataLength matching the date range
  - Parameters set to -99 require calibration (will cause errors in direct runs)

Modes:
  simulate  — Run a single simulation with fixed parameters
  calibrate — Run GA optimization against observed data

Usage:
    # Simulation
    python run_hydrocnhs.py \\
        --mode simulate \\
        --model model.yaml \\
        --climate-pickle inputs.pickle \\
        --output results.json

    # Calibration
    python run_hydrocnhs.py \\
        --mode calibrate \\
        --model model.yaml \\
        --climate-pickle inputs.pickle \\
        --observed-pickle observed.pickle \\
        --generations 100 \\
        --population 50 \\
        --output calibrated_model.yaml
"""

import argparse
import json
import os
import pickle
import sys
import time


def validate_inputs(args):
    """Validate all inputs before running."""
    errors = []

    if not os.path.exists(args.model):
        errors.append(f"Model YAML not found: {args.model}")

    if not os.path.exists(args.climate_pickle):
        errors.append(f"Climate data pickle not found: {args.climate_pickle}")

    if args.mode == "calibrate":
        if not args.observed_pickle or not os.path.exists(args.observed_pickle):
            errors.append(f"Observed data pickle required for calibration: {args.observed_pickle}")

    if args.mode not in ["simulate", "calibrate"]:
        errors.append(f"Mode must be 'simulate' or 'calibrate', got: {args.mode}")

    return errors


def validate_climate_data(temp, prec, pet, log):
    """Check climate data for common unit errors before running."""
    import numpy as np

    for outlet in temp:
        t = np.array(temp[outlet])
        p = np.array(prec[outlet])

        # Temperature sanity
        if np.mean(t) > 100:
            log.append(f"[CRITICAL] {outlet}: mean temp={np.mean(t):.1f} — likely Kelvin, subtract 273.15")
            return False

        # Precipitation sanity
        if np.mean(p) > 5:
            log.append(f"[CRITICAL] {outlet}: mean prec={np.mean(p):.2f} cm/day — likely mm/day, divide by 10")
            return False
        if np.mean(p) > 0 and np.mean(p) < 0.001:
            log.append(f"[CRITICAL] {outlet}: mean prec={np.mean(p):.5f} cm/day — likely m/day, multiply by 100")
            return False
        if np.any(p < 0):
            log.append(f"[WARN] {outlet}: negative precipitation values detected")

    log.append("Climate data validation passed")
    return True


def run_simulation(args):
    """Run a single model simulation."""
    import hydrocnhs
    import numpy as np

    log = []
    log.append(f"Loading model: {args.model}")

    # Load climate data
    with open(args.climate_pickle, "rb") as f:
        climate = pickle.load(f)

    temp = climate.get("temp", climate.get("Temp", {}))
    prec = climate.get("prec", climate.get("Prec", {}))
    pet = climate.get("pet", climate.get("PET", None))

    # Validate climate data
    if not validate_climate_data(temp, prec, pet, log):
        return {"status": "error", "errors": log}

    # Run model
    log.append("Initializing model...")
    t0 = time.time()
    model = hydrocnhs.Model(args.model)
    log.append(f"Model loaded in {time.time() - t0:.1f}s")

    log.append("Running simulation...")
    t0 = time.time()
    Q = model.run(temp=temp, prec=prec, pet=pet)
    elapsed = time.time() - t0
    log.append(f"Simulation completed in {elapsed:.1f}s")

    # Extract results
    q_routed = {}
    for outlet in model.dc.Q_routed:
        arr = np.array(model.dc.Q_routed[outlet])
        q_routed[outlet] = {
            "values": arr.tolist(),
            "mean": float(np.mean(arr)),
            "max": float(np.max(arr)),
            "min": float(np.min(arr)),
            "std": float(np.std(arr)),
        }
        log.append(f"  {outlet}: mean Q = {np.mean(arr):.3f} cms, max = {np.max(arr):.3f} cms")

    result = {
        "status": "success",
        "output": {
            "Q_routed": q_routed,
            "n_timesteps": len(next(iter(model.dc.Q_routed.values()))),
            "elapsed_s": elapsed,
        },
        "log": log
    }

    # Save results
    if args.output:
        # Save a simplified version (without full time series) to JSON
        summary = {
            "status": "success",
            "outlets": {},
            "elapsed_s": elapsed,
        }
        for outlet, data in q_routed.items():
            summary["outlets"][outlet] = {
                k: v for k, v in data.items() if k != "values"
            }

        with open(args.output, "w") as f:
            json.dump(summary, f, indent=2)
        log.append(f"Summary written to {args.output}")

        # Save full results as pickle
        pkl_path = args.output.replace(".json", ".pickle")
        with open(pkl_path, "wb") as f:
            pickle.dump({"Q_routed": model.dc.Q_routed, "dc": model.dc}, f)
        log.append(f"Full results written to {pkl_path}")

    return result


def run_calibration(args):
    """Run GA calibration using the real hydrocnhs.calibration API.

    Rewritten to match the installed HydroCNHS calibration API
    (Convertor().gen_cali_inputs / GA_DEAP.set(cali_inputs, config, formatter)).
    """
    import hydrocnhs
    import hydrocnhs.calibration as cali
    import numpy as np
    import pandas as pd
    from copy import deepcopy

    log = []
    log.append(f"Starting calibration: {args.model}")

    with open(args.climate_pickle, "rb") as f:
        climate = pickle.load(f)
    with open(args.observed_pickle, "rb") as f:
        observed = pickle.load(f)

    temp = climate.get("temp", climate.get("Temp", {}))
    prec = climate.get("prec", climate.get("Prec", {}))
    pet = climate.get("pet", climate.get("PET", None))

    if not validate_climate_data(temp, prec, pet, log):
        return {"status": "error", "errors": log}

    model_dict = hydrocnhs.load_model(args.model)
    wd = model_dict["Path"]["WD"]

    # Observed -> DataFrame indexed by simulation date (for date-aligned KGE)
    start_date = model_dict["WaterSystem"]["StartDate"]
    data_length = model_dict["WaterSystem"]["DataLength"]
    date_index = pd.date_range(start=pd.to_datetime(start_date, format="%Y/%m/%d"),
                               periods=data_length, freq="D")
    obv_df = pd.DataFrame({o: list(v) for o, v in observed.items()}, index=date_index)
    cali_target = list(observed.keys())

    # Build calibration inputs (correct API)
    df_list, df_name = hydrocnhs.write_model_to_df(model_dict)
    par_bound_df_list, df_name = hydrocnhs.gen_default_bounds(model_dict)
    converter = cali.Convertor()
    cali_inputs = converter.gen_cali_inputs(wd, df_list, par_bound_df_list)
    formatter = converter.formatter
    log.append(f"Calibration parameters: {sum(len(f.get('par_name', [])) for f in [formatter])}")

    def evaluation(individual, info):
        cali_wd, gen, ith, fmt, _ = info
        name = f"{gen}-{ith}"
        dfs = cali.Convertor.to_df_list(individual, fmt)
        model = deepcopy(model_dict)
        for i, df in enumerate(dfs):
            s = df_name[i].split("_")[0]
            model = hydrocnhs.load_df_to_model_dict(model, df, s, "Pars")
        m = hydrocnhs.Model(model, name)
        Q = m.run(temp, prec, pet)
        sim_Q_D = pd.DataFrame(Q, index=m.pd_date_index)[cali_target]
        kges = []
        for tgt in cali_target:
            # obv has NaN outside the calibration window; get_kge strips NaN,
            # so KGE is evaluated only on the unmasked (calibration) period.
            kge = hydrocnhs.Indicator.get_kge(
                obv_df[tgt].values, sim_Q_D[tgt].values, r_na=True)
            kges.append(kge)
        return (float(np.mean(kges)),)

    config = {
        "min_or_max": "max",
        "pop_size": args.population,
        "num_ellite": 1,
        "prob_cross": 0.5,
        "prob_mut": 0.15,
        "stochastic": False,
        "max_gen": args.generations,
        "sampling_method": "LHC",
        "drop_record": False,
        "paral_cores": 1,
        "paral_verbose": 0,
        "auto_save": False,
        "print_level": 1,
        "plot": False,
    }
    log.append(f"GA config: pop={args.population}, gen={args.generations}")

    rn_gen = hydrocnhs.create_rn_gen(args.seed)
    ga = cali.GA_DEAP(evaluation, rn_gen)
    ga.set(cali_inputs, config, formatter, name=args.cali_name)

    t0 = time.time()
    ga.run()
    elapsed = time.time() - t0
    individual = ga.solution
    best_fitness = float(ga.summary["max_fitness"][-1]) if hasattr(ga, "summary") else None

    log.append(f"Calibration completed in {elapsed:.1f}s")
    log.append(f"Best fitness (KGE): {best_fitness}")

    if args.output:
        dfs = cali.Convertor.to_df_list(individual, formatter)
        model_best = deepcopy(model_dict)
        for i, df in enumerate(dfs):
            s = df_name[i].split("_")[0]
            model_best = hydrocnhs.load_df_to_model_dict(model_best, df, s, "Pars")
        hydrocnhs.write_model(model_best, args.output)
        log.append(f"Calibrated model written to {args.output}")

    return {
        "status": "success",
        "output": {
            "best_fitness": best_fitness,
            "elapsed_s": elapsed,
            "generations": args.generations,
            "population": args.population,
        },
        "log": log,
    }


def main():
    parser = argparse.ArgumentParser(description="Run HydroCNHS simulation or calibration")
    parser.add_argument("--mode", required=True, choices=["simulate", "calibrate"],
                        help="Run mode: simulate or calibrate")
    parser.add_argument("--model", required=True, help="Path to model.yaml")
    parser.add_argument("--climate-pickle", required=True, help="Climate data pickle file")
    parser.add_argument("--observed-pickle", default=None, help="Observed data pickle (for calibration)")
    parser.add_argument("--generations", type=int, default=100, help="GA generations")
    parser.add_argument("--population", type=int, default=50, help="GA population size")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--cali-name", default="Cali_Bengbu",
                        help="GA working-subdirectory name (default preserves the original 'Cali_Bengbu')")
    parser.add_argument("--output", default=None, help="Output file path")

    args = parser.parse_args()

    errors = validate_inputs(args)
    if errors:
        print(json.dumps({"status": "error", "errors": errors}, indent=2))
        sys.exit(1)

    if args.mode == "simulate":
        result = run_simulation(args)
    else:
        result = run_calibration(args)

    if result["status"] == "error":
        print(json.dumps(result, indent=2))
        sys.exit(1)
    else:
        for line in result.get("log", []):
            print(line)


if __name__ == "__main__":
    main()
