#!/usr/bin/env python3
"""
parse_output_wasp.py -- Parse WASP simulation output and compute validation metrics.

Reads the JSON output from run_wasp.py, extracts temperature and dissolved
oxygen time series and profiles, computes evaluation metrics (R, RMSE, bias,
MAE) against observed data, computes Carlson TSI, and optionally generates
a multi-panel validation figure.

Output units:
  - Temperature: deg C
  - Dissolved oxygen: mg/L
  - Depth: m
  - TSI: dimensionless (Carlson 1977 scale)
  - Metrics: unitless (except RMSE and bias which have units of the variable)

CRITICAL:
  - Observed T must be in deg C. If in Fahrenheit, convert first (dt_001).
  - Observed DO must be in mg/L. If in % saturation, convert using
    DO_mg_l = DO_pct * DO_sat(T) / 100 (dt_004).
  - Depth must be in meters for profile comparison (dt_005).
  - Profile metrics only valid for summer stratification (Jun-Aug in NH).
  - Warmup data (first year) should generally be excluded for seasonal models.

Usage:
    python parse_output_wasp.py \\
        --input simulation.json \\
        --output results.csv \\
        --metrics-json metrics.json

    python parse_output_wasp.py \\
        --input calibrated.json \\
        --output results.csv \\
        --metrics-json metrics.json \\
        --figure validation.png

    python parse_output_wasp.py \\
        --input profiles.json \\
        --metrics-json metrics.json \\
        --figure profiles.png
"""

import argparse
import json
import os
import sys

import numpy as np

try:
    import pandas as pd
except ImportError:
    pd = None

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.gridspec as gridspec
    HAS_MPL = True
except ImportError:
    HAS_MPL = False


# ============================================================================
# PHYSICS (duplicated from run_wasp.py for standalone operation)
# ============================================================================

def do_saturation(T_celsius):
    """DO saturation concentration (mg/L) -- Benson & Krause (1984)."""
    TK = np.asarray(T_celsius, dtype=float) + 273.15
    ln_DO = (-139.34411 + 1.575701e5 / TK - 6.642308e7 / TK**2
             + 1.2438e10 / TK**3 - 8.621949e11 / TK**4)
    return np.exp(ln_DO)


def carlson_tsi(chla=None, secchi=None, tp=None):
    """Carlson Trophic State Index (1977)."""
    tsi = {}
    if chla is not None and chla > 0:
        tsi["TSI_chla"] = 9.81 * np.log(chla) + 30.6
    if secchi is not None and secchi > 0:
        tsi["TSI_secchi"] = 60 - 14.41 * np.log(secchi)
    if tp is not None and tp > 0:
        tsi["TSI_tp"] = 14.42 * np.log(tp) + 4.15
    if tsi:
        tsi["TSI_mean"] = float(np.mean(list(tsi.values())))
    return tsi


# ============================================================================
# METRICS
# ============================================================================

def compute_r(obs, sim):
    """Pearson correlation coefficient."""
    obs, sim = np.asarray(obs, float), np.asarray(sim, float)
    mask = ~(np.isnan(obs) | np.isnan(sim))
    obs, sim = obs[mask], sim[mask]
    if len(obs) < 3:
        return float("nan")
    return float(np.corrcoef(obs, sim)[0, 1])


def compute_rmse(obs, sim):
    """Root Mean Square Error."""
    obs, sim = np.asarray(obs, float), np.asarray(sim, float)
    mask = ~(np.isnan(obs) | np.isnan(sim))
    obs, sim = obs[mask], sim[mask]
    if len(obs) == 0:
        return float("nan")
    return float(np.sqrt(np.mean((obs - sim)**2)))


def compute_bias(obs, sim):
    """Mean bias (sim - obs)."""
    obs, sim = np.asarray(obs, float), np.asarray(sim, float)
    mask = ~(np.isnan(obs) | np.isnan(sim))
    obs, sim = obs[mask], sim[mask]
    if len(obs) == 0:
        return float("nan")
    return float(np.mean(sim - obs))


def compute_mae(obs, sim):
    """Mean Absolute Error."""
    obs, sim = np.asarray(obs, float), np.asarray(sim, float)
    mask = ~(np.isnan(obs) | np.isnan(sim))
    obs, sim = obs[mask], sim[mask]
    if len(obs) == 0:
        return float("nan")
    return float(np.mean(np.abs(sim - obs)))


def compute_all_metrics(obs, sim):
    """Compute all metrics."""
    n_valid = int(np.sum(~np.isnan(np.asarray(obs)) & ~np.isnan(np.asarray(sim))))
    return {
        "R": round(compute_r(obs, sim), 4),
        "RMSE": round(compute_rmse(obs, sim), 4),
        "bias": round(compute_bias(obs, sim), 4),
        "MAE": round(compute_mae(obs, sim), 4),
        "n": n_valid,
    }


# ============================================================================
# INPUT HANDLING
# ============================================================================

def validate_inputs(args):
    """Validate input files and arguments."""
    errors = []

    if not os.path.isfile(args.input):
        errors.append(f"Input file not found: {args.input}")

    if pd is None:
        errors.append("pandas required. Run: pip install pandas")

    return errors


def load_simulation(input_path, log):
    """Load simulation results from JSON (output of run_wasp.py).

    Returns the parsed data dict.
    """
    with open(input_path) as f:
        data = json.load(f)

    if data.get("status") == "error":
        raise ValueError(f"Input file has error status: {data.get('errors')}")

    mode = data.get("mode", "unknown")
    log.append(f"Loaded simulation: mode={mode}")
    return data


# ============================================================================
# PROCESSING
# ============================================================================

def process_seasonal(data, log):
    """Process seasonal T/DO simulation or calibration results.

    Returns metrics dict and DataFrames for CSV export.
    """
    output = data.get("output", {})
    all_metrics = {}
    export_frames = {}

    # --- Temperature ---
    temp_data = output.get("seasonal_temp")
    temp_cal = output.get("temperature", {})

    if temp_data and "T_obs" in temp_data and "T_sim" in temp_data:
        T_obs = np.array(temp_data["T_obs"], dtype=float)
        T_sim = np.array(temp_data["T_sim"], dtype=float)
        metrics = compute_all_metrics(T_obs, T_sim)
        all_metrics["temperature"] = metrics
        log.append(
            f"  Temperature: R={metrics['R']:.3f}, "
            f"RMSE={metrics['RMSE']:.2f} C, n={metrics['n']}")

        if "dates" in temp_data:
            export_frames["temperature"] = pd.DataFrame({
                "date": temp_data["dates"],
                "doy": temp_data.get("doy", []),
                "T_obs_C": T_obs,
                "T_sim_C": T_sim,
            })

    # Calibration metrics (already computed in run_wasp.py)
    if temp_cal and "calibration_metrics" in temp_cal:
        all_metrics["temperature_calibration"] = temp_cal["calibration_metrics"]
        all_metrics["temperature_validation"] = temp_cal.get(
            "validation_metrics", {})

    # --- DO ---
    do_data = output.get("seasonal_do")
    do_cal = output.get("dissolved_oxygen", {})

    if do_data and "DO_obs" in do_data and "DO_sim" in do_data:
        DO_obs = np.array(do_data["DO_obs"], dtype=float)
        DO_sim = np.array(do_data["DO_sim"], dtype=float)
        metrics = compute_all_metrics(DO_obs, DO_sim)
        all_metrics["dissolved_oxygen"] = metrics
        log.append(
            f"  DO: R={metrics['R']:.3f}, "
            f"RMSE={metrics['RMSE']:.2f} mg/L, n={metrics['n']}")

        if "dates" in do_data:
            export_frames["dissolved_oxygen"] = pd.DataFrame({
                "date": do_data["dates"],
                "doy": do_data.get("doy", []),
                "DO_obs_mg_l": DO_obs,
                "DO_sim_mg_l": DO_sim,
            })

    if do_cal and "calibration_metrics" in do_cal:
        all_metrics["do_calibration"] = do_cal["calibration_metrics"]
        all_metrics["do_validation"] = do_cal.get("validation_metrics", {})

    # --- Calibrated parameters ---
    cal_params = output.get("calibrated_params")
    if cal_params:
        all_metrics["calibrated_params"] = cal_params

    return all_metrics, export_frames


def process_profiles(data, log):
    """Process vertical profile results.

    Returns metrics dict and DataFrame for export.
    """
    output = data.get("output", {})
    all_metrics = {}
    export_frames = {}

    # Direct profile output (from --mode profile)
    if "depths_m" in output:
        depths = np.array(output["depths_m"], dtype=float)
        T_prof = np.array(output["T_profile_c"], dtype=float)
        DO_prof = np.array(output["DO_profile_mg_l"], dtype=float)

        DOsat_prof = output.get("DOsat_profile_mg_l")
        if DOsat_prof:
            DOsat_prof = np.array(DOsat_prof, dtype=float)
        else:
            DOsat_prof = do_saturation(T_prof)

        log.append(
            f"  Profile: {len(depths)} depths, "
            f"T=[{T_prof.min():.1f}, {T_prof.max():.1f}] C, "
            f"DO=[{DO_prof.min():.1f}, {DO_prof.max():.1f}] mg/L")

        all_metrics["profile_stats"] = output.get("stats", {})

        export_df = pd.DataFrame({
            "depth_m": depths,
            "T_sim_C": T_prof,
            "DO_sim_mg_l": DO_prof,
            "DOsat_mg_l": DOsat_prof,
        })
        export_frames["profiles"] = export_df

    # Profiles embedded in simulation output
    prof_out = output.get("profiles", {})
    if isinstance(prof_out, dict) and "depths_m" in prof_out:
        depths = np.array(prof_out["depths_m"], dtype=float)
        T_prof = np.array(prof_out["T_profile_c"], dtype=float)
        DO_prof = np.array(prof_out["DO_profile_mg_l"], dtype=float)

        all_metrics["profile_thermal_params"] = prof_out.get(
            "thermal_params", {})

        export_df = pd.DataFrame({
            "depth_m": depths,
            "T_sim_C": T_prof,
            "DO_sim_mg_l": DO_prof,
            "DOsat_mg_l": do_saturation(T_prof),
        })
        export_frames["profiles"] = export_df

    return all_metrics, export_frames


def process_tsi(data, log):
    """Extract or compute TSI values."""
    output = data.get("output", {})
    tsi = output.get("tsi", {})

    if tsi:
        log.append("  TSI values:")
        for k, v in tsi.items():
            log.append(f"    {k} = {v:.1f}")

        # Classify trophic state
        tsi_mean = tsi.get("TSI_mean", 0)
        if tsi_mean < 30:
            tsi["classification"] = "oligotrophic"
        elif tsi_mean < 50:
            tsi["classification"] = "mesotrophic"
        elif tsi_mean < 70:
            tsi["classification"] = "eutrophic"
        else:
            tsi["classification"] = "hypereutrophic"
        log.append(f"    Classification: {tsi['classification']}")

    return tsi


# ============================================================================
# FIGURE GENERATION
# ============================================================================

def generate_figure(data, all_metrics, figure_path, log):
    """Generate multi-panel validation figure."""
    if not HAS_MPL:
        log.append("matplotlib not available, skipping figure")
        return

    output = data.get("output", {})
    mode = data.get("mode", "unknown")

    # Determine number of panels needed
    has_temp = output.get("seasonal_temp") is not None or \
        output.get("temperature", {}).get("calibration_metrics")
    has_do = output.get("seasonal_do") is not None or \
        output.get("dissolved_oxygen", {}).get("calibration_metrics")
    has_profile = "profiles" in output or "depths_m" in output
    has_tsi = "tsi" in output
    has_sp = "streeter_phelps" in output
    has_dosat = True  # always generate DO saturation curve

    n_panels = sum([has_temp, has_do, has_profile, has_tsi, has_sp, has_dosat])
    n_panels = max(n_panels, 1)

    # Layout: up to 3 columns, as many rows as needed
    n_cols = min(3, n_panels)
    n_rows = (n_panels + n_cols - 1) // n_cols

    fig = plt.figure(figsize=(6 * n_cols, 5 * n_rows))
    gs = gridspec.GridSpec(n_rows, n_cols, hspace=0.4, wspace=0.35)

    panel_idx = 0

    # --- Panel: Temperature seasonal ---
    if has_temp:
        ax = fig.add_subplot(gs[panel_idx // n_cols, panel_idx % n_cols])
        panel_idx += 1

        temp_data = output.get("seasonal_temp", {})
        if temp_data and "T_obs" in temp_data:
            doy = np.array(temp_data.get("doy", []))
            T_obs = np.array(temp_data["T_obs"])
            T_sim = np.array(temp_data["T_sim"])

            ax.scatter(doy, T_obs, s=4, alpha=0.1, c="steelblue", label="Observed")

            # Sort for clean line
            sort_idx = np.argsort(doy)
            doy_sorted = doy[sort_idx]
            T_sim_sorted = T_sim[sort_idx]
            ax.plot(doy_sorted, T_sim_sorted, "r-", lw=2, alpha=0.8,
                    label="WASP model")

            metrics = all_metrics.get("temperature", {})
            ax.set_xlabel("Day of Year")
            ax.set_ylabel("Temperature (C)")
            ax.set_title(
                f"Temperature Seasonal\n"
                f"R={metrics.get('R', 'N/A')}, RMSE={metrics.get('RMSE', 'N/A')} C")
            ax.legend(fontsize=8, markerscale=3)
            ax.grid(True, alpha=0.3)
        else:
            # Calibration-only mode
            temp_cal = output.get("temperature", {})
            cal_m = temp_cal.get("calibration_metrics", {})
            val_m = temp_cal.get("validation_metrics", {})
            text = f"Cal R={cal_m.get('R', 'N/A')}\nVal R={val_m.get('R', 'N/A')}"
            ax.text(0.5, 0.5, text, transform=ax.transAxes,
                    fontsize=14, ha="center", va="center")
            ax.set_title("Temperature Calibration Metrics")

    # --- Panel: DO seasonal ---
    if has_do:
        ax = fig.add_subplot(gs[panel_idx // n_cols, panel_idx % n_cols])
        panel_idx += 1

        do_data = output.get("seasonal_do", {})
        if do_data and "DO_obs" in do_data:
            doy = np.array(do_data.get("doy", []))
            DO_obs = np.array(do_data["DO_obs"])
            DO_sim = np.array(do_data["DO_sim"])

            ax.scatter(doy, DO_obs, s=4, alpha=0.1, c="steelblue", label="Observed")
            sort_idx = np.argsort(doy)
            ax.plot(doy[sort_idx], DO_sim[sort_idx], "r-", lw=2, alpha=0.8,
                    label="WASP model")

            metrics = all_metrics.get("dissolved_oxygen", {})
            ax.set_xlabel("Day of Year")
            ax.set_ylabel("DO (mg/L)")
            ax.set_title(
                f"Dissolved Oxygen Seasonal\n"
                f"R={metrics.get('R', 'N/A')}, RMSE={metrics.get('RMSE', 'N/A')} mg/L")
            ax.legend(fontsize=8, markerscale=3)
            ax.grid(True, alpha=0.3)

    # --- Panel: Vertical profiles ---
    if has_profile:
        ax = fig.add_subplot(gs[panel_idx // n_cols, panel_idx % n_cols])
        panel_idx += 1

        prof = output.get("profiles", {})
        if isinstance(prof, dict) and "depths_m" in prof:
            depths = np.array(prof["depths_m"])
            T_prof = np.array(prof["T_profile_c"])
            DO_prof = np.array(prof["DO_profile_mg_l"])

            ax.plot(T_prof, depths, "r-", lw=2, label="Temperature (C)")
            ax.plot(DO_prof, depths, "b--", lw=2, label="DO (mg/L)")
            ax.invert_yaxis()
            ax.set_xlabel("Value")
            ax.set_ylabel("Depth (m)")
            ax.set_title("Vertical Profiles (Summer)")
            ax.legend(fontsize=8)
            ax.grid(True, alpha=0.3)
        elif "depths_m" in output:
            depths = np.array(output["depths_m"])
            T_prof = np.array(output["T_profile_c"])
            DO_prof = np.array(output["DO_profile_mg_l"])

            ax.plot(T_prof, depths, "r-", lw=2, label="Temperature (C)")
            ax.plot(DO_prof, depths, "b--", lw=2, label="DO (mg/L)")
            ax.invert_yaxis()
            ax.set_xlabel("Value")
            ax.set_ylabel("Depth (m)")
            ax.set_title("Vertical Profiles")
            ax.legend(fontsize=8)
            ax.grid(True, alpha=0.3)

    # --- Panel: DO saturation curve ---
    if has_dosat:
        ax = fig.add_subplot(gs[panel_idx // n_cols, panel_idx % n_cols])
        panel_idx += 1

        T_range = np.linspace(0, 35, 200)
        DOsat = do_saturation(T_range)
        ax.plot(T_range, DOsat, "b-", lw=2, label="Benson-Krause (WASP)")
        ax.set_xlabel("Temperature (C)")
        ax.set_ylabel("DO saturation (mg/L)")
        ax.set_title("DO Saturation Curve\n(WASP thermal coupling)")
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)

    # --- Panel: Streeter-Phelps ---
    if has_sp:
        ax = fig.add_subplot(gs[panel_idx // n_cols, panel_idx % n_cols])
        panel_idx += 1

        sp_data = output["streeter_phelps"]
        t_sp = np.array(sp_data["t_days"])
        BOD_sp = np.array(sp_data["BOD_mg_l"])
        DO_sp = np.array(sp_data["DO_mg_l"])

        ax.plot(t_sp, DO_sp, "b-", lw=2, label="DO")
        ax.plot(t_sp, BOD_sp, "r--", lw=2, label="BOD")
        ax.axhline(sp_data["DOsat_mg_l"], color="gray", ls=":",
                    label=f"DOsat ({sp_data['DOsat_mg_l']:.1f})")
        ax.set_xlabel("Time (days)")
        ax.set_ylabel("Concentration (mg/L)")
        ax.set_title(
            f"Streeter-Phelps BOD-DO\n(T_ref={sp_data['T_ref_c']} C)")
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)

    # --- Panel: TSI ---
    if has_tsi:
        ax = fig.add_subplot(gs[panel_idx // n_cols, panel_idx % n_cols])
        panel_idx += 1

        tsi = output["tsi"]
        tsi_vals = {k: v for k, v in tsi.items()
                    if k.startswith("TSI_") and k != "TSI_mean"}
        if tsi_vals:
            names = list(tsi_vals.keys())
            values = list(tsi_vals.values())
            bars = ax.barh(names, values, color="steelblue", alpha=0.7)
            if "TSI_mean" in tsi:
                ax.axvline(tsi["TSI_mean"], color="red", ls="--",
                           label=f"Mean={tsi['TSI_mean']:.1f}")

            # TSI thresholds
            for tv, lb, clr in [(30, "Oligo", "blue"),
                                 (50, "Meso", "green"),
                                 (70, "Eutro", "orange")]:
                ax.axvline(tv, color=clr, ls=":", alpha=0.5)

            ax.set_xlabel("Carlson TSI")
            ax.set_title("Trophic State Index")
            ax.legend(fontsize=8)
            ax.grid(True, alpha=0.3, axis="x")

    plt.suptitle("WASP Water Quality Model Output", fontsize=13,
                 fontweight="bold", y=1.01)

    out_dir = os.path.dirname(figure_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    plt.savefig(figure_path, dpi=150, bbox_inches="tight")
    plt.close()
    log.append(f"Figure saved: {figure_path}")


# ============================================================================
# OUTPUT VALIDATION
# ============================================================================

def validate_output(all_metrics, log):
    """Final validation of parsed output."""
    warnings_list = []

    for var_key in ("temperature", "dissolved_oxygen"):
        metrics = all_metrics.get(var_key, {})
        r_val = metrics.get("R")
        if r_val is not None and not np.isnan(r_val):
            if r_val < 0:
                warnings_list.append(
                    f"{var_key}: R = {r_val:.3f} < 0 -- model worse than mean")
            elif r_val < 0.3:
                warnings_list.append(
                    f"{var_key}: R = {r_val:.3f} -- weak correlation")

        rmse = metrics.get("RMSE")
        if rmse is not None and not np.isnan(rmse):
            if var_key == "temperature" and rmse > 8:
                warnings_list.append(
                    f"{var_key}: RMSE = {rmse:.2f} C -- very high error")
            elif var_key == "dissolved_oxygen" and rmse > 5:
                warnings_list.append(
                    f"{var_key}: RMSE = {rmse:.2f} mg/L -- high error")

    if warnings_list:
        log.append("\nDiagnostic warnings:")
        for w in warnings_list:
            log.append(f"  [WARN] {w}")

    return warnings_list


# ============================================================================
# MAIN
# ============================================================================

def process(args):
    """Main processing: parse output, compute metrics, export."""
    log = []
    log.append("WASP Output Parser")
    log.append("=" * 50)

    # Load simulation results
    data = load_simulation(args.input, log)
    mode = data.get("mode", "unknown")

    all_metrics = {}
    export_frames = {}

    # Process based on mode
    if mode in ("simulate", "calibrate"):
        seasonal_metrics, seasonal_frames = process_seasonal(data, log)
        all_metrics.update(seasonal_metrics)
        export_frames.update(seasonal_frames)

    # Profiles (available in simulate and profile modes)
    profile_metrics, profile_frames = process_profiles(data, log)
    all_metrics.update(profile_metrics)
    export_frames.update(profile_frames)

    # TSI
    tsi = process_tsi(data, log)
    if tsi:
        all_metrics["tsi"] = tsi

    # Validate
    warnings_list = validate_output(all_metrics, log)
    all_metrics["warnings"] = warnings_list

    # Export CSVs
    if args.output and export_frames:
        out_dir = os.path.dirname(args.output)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)

        # If single frame, write directly; if multiple, write each
        if len(export_frames) == 1:
            key = list(export_frames.keys())[0]
            export_frames[key].to_csv(args.output, index=False)
            log.append(f"Exported {key} to {args.output}")
        else:
            base, ext = os.path.splitext(args.output)
            for key, df in export_frames.items():
                out_path = f"{base}_{key}{ext}"
                df.to_csv(out_path, index=False)
                log.append(f"Exported {key} to {out_path}")

    # Write metrics JSON
    if args.metrics_json:
        mdir = os.path.dirname(args.metrics_json)
        if mdir:
            os.makedirs(mdir, exist_ok=True)

        # Convert any numpy types for JSON serialization
        def np2py(obj):
            if isinstance(obj, (np.integer,)):
                return int(obj)
            if isinstance(obj, (np.floating,)):
                return float(obj)
            if isinstance(obj, np.ndarray):
                return obj.tolist()
            if isinstance(obj, dict):
                return {k: np2py(v) for k, v in obj.items()}
            if isinstance(obj, (list, tuple)):
                return [np2py(x) for x in obj]
            return obj

        metrics_out = np2py(all_metrics)

        with open(args.metrics_json, "w") as f:
            json.dump(metrics_out, f, indent=2)
        log.append(f"Metrics written to {args.metrics_json}")

    # Generate figure
    if args.figure:
        generate_figure(data, all_metrics, args.figure, log)

    result = {
        "status": "success",
        "model": "WASP",
        "output": {
            "mode": mode,
            "metrics": all_metrics,
            "n_export_files": len(export_frames),
        },
        "log": log,
    }

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Parse WASP output and compute validation metrics")
    parser.add_argument("--input", required=True,
                        help="Simulation JSON from run_wasp.py")
    parser.add_argument("--output", default=None,
                        help="Output CSV file for time series / profiles")
    parser.add_argument("--metrics-json", default=None,
                        help="Output JSON file for metrics")
    parser.add_argument("--figure", default=None,
                        help="Output validation figure (PNG)")

    args = parser.parse_args()

    # Step 1: validate inputs
    errors = validate_inputs(args)
    if errors:
        print(json.dumps({"status": "error", "errors": errors}, indent=2))
        sys.exit(1)

    # Step 2: process
    result = process(args)

    # Step 3: print summary
    if result["status"] == "error":
        print(json.dumps(result, indent=2))
        sys.exit(1)
    else:
        for line in result.get("log", []):
            print(line)
        print("\n" + json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
