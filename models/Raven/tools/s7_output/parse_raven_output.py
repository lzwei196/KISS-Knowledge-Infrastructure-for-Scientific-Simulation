#!/usr/bin/env python3
"""
parse_raven_output.py — Parse Raven output files and extract results.

Reads Hydrographs.csv, WatershedStorage.csv, Diagnostics.csv and produces
standardized output: discharge time series, water balance components,
performance metrics, and summary statistics.

Usage:
    python parse_raven_output.py \
        --output_dir outputs/chaohe_raven/output/ \
        --basin_name chaohe \
        --obs_file data/obs/chaohe/observed.txt \
        --export_csv outputs/chaohe_raven/raven_discharge.csv
"""

import argparse
import json
import os
import sys
from datetime import datetime

try:
    import numpy as np
    import pandas as pd
except ImportError as e:
    print(json.dumps({"status": "error", "message": f"Missing dependency: {e}"}))
    sys.exit(1)


def find_output_file(output_dir, basename, filename):
    """Find an output file with or without RunName prefix."""
    candidates = [
        os.path.join(output_dir, filename),
        os.path.join(output_dir, f"{basename}_{filename}"),
    ]
    # Also check for files with RunName pattern
    if os.path.isdir(output_dir):
        for f in os.listdir(output_dir):
            if filename.lower() in f.lower():
                candidates.append(os.path.join(output_dir, f))

    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def parse_hydrographs(filepath):
    """
    Parse Raven Hydrographs.csv.

    Format (comma-separated):
    date,hour,sub1 [m3/s],sub1 (observed) [m3/s],...
    or
    date,hour,sub_ID [m3/s] (sim),sub_ID [m3/s] (obs),...

    Returns DataFrame with columns: date, simulated, observed (if present).
    """
    try:
        df = pd.read_csv(filepath, skip_blank_lines=True)
    except Exception as e:
        return None, str(e)

    # Find date column
    date_col = None
    for c in df.columns:
        if "date" in c.lower():
            date_col = c
            break

    if date_col is None and len(df.columns) >= 1:
        date_col = df.columns[0]

    # Find simulated discharge column (typically 3rd column)
    sim_col = None
    obs_col = None
    for c in df.columns:
        cl = c.lower().strip()
        if "m3/s" in cl or "cms" in cl:
            if "obs" in cl or "observed" in cl:
                obs_col = c
            elif sim_col is None:
                sim_col = c

    if sim_col is None and len(df.columns) >= 3:
        sim_col = df.columns[2]  # Default: 3rd column is simulated

    if obs_col is None:
        # Check 4th column
        if len(df.columns) >= 4:
            c4 = df.columns[3].lower()
            if "obs" in c4 or "observed" in c4:
                obs_col = df.columns[3]

    result = pd.DataFrame()
    if date_col:
        result["date"] = pd.to_datetime(df[date_col], errors="coerce")
    if sim_col:
        result["simulated_m3s"] = pd.to_numeric(df[sim_col], errors="coerce")
    if obs_col:
        result["observed_m3s"] = pd.to_numeric(df[obs_col], errors="coerce")
        # Replace Raven's missing value marker
        result.loc[result["observed_m3s"] < -9000, "observed_m3s"] = np.nan

    return result, None


def parse_diagnostics(filepath):
    """Parse Raven's Diagnostics.csv into a flat {metric_name: value} dict.

    Raven writes a HEADER row plus ONE DATA ROW PER OBSERVATION SERIES, not
    `name,value` pairs (dt_rav_037):

        observed_data_series,filename,DIAG_NASH_SUTCLIFFE,DIAG_KLING_GUPTA,...
        HYDROGRAPH_ALL[1],bengbu_obs.rvt,-1.42864,-0.285628,...

    The previous row-wise `parts[0] -> float(parts[1])` parser therefore matched
    nothing at all: on the header row column 1 is the literal "filename", and on
    the data row it is the .rvt name. Every caller got {} and fell back to the
    -999 sentinel. This is THE canonical Raven diagnostics parser — the s8
    ensemble and s9 calibration tools import it rather than re-deriving it.

    Returns metric names both as written (DIAG_NASH_SUTCLIFFE) and with Raven's
    DIAG_ prefix stripped (NASH_SUTCLIFFE), taken from the FIRST data row. When
    the file holds more than one observation series, every series is also
    reported under "<series>:<METRIC>" keys so nothing is silently dropped.
    """
    metrics = {}
    try:
        with open(filepath) as f:
            rows = [[c.strip() for c in line.strip().split(",")]
                    for line in f
                    if line.strip() and not line.lstrip().startswith(("#", "*"))]
    except Exception:
        return metrics

    if len(rows) < 2:
        return metrics

    header = rows[0]
    data_rows = rows[1:]
    for row_i, data in enumerate(data_rows):
        series = data[0] if data and data[0] else f"series{row_i + 1}"
        for name, value in zip(header, data):
            if not name:
                continue
            try:
                val = float(value)
            except ValueError:
                continue
            short = name[len("DIAG_"):] if name.startswith("DIAG_") else name
            if row_i == 0:
                metrics[name] = val
                metrics[short] = val
            if len(data_rows) > 1:
                metrics[f"{series}:{short}"] = val

    return metrics


def parse_watershed_storage(filepath):
    """Parse WatershedStorage.csv for water balance components."""
    try:
        df = pd.read_csv(filepath, skip_blank_lines=True)
        summary = {}
        for col in df.columns:
            if col.lower() in ("date", "hour"):
                continue
            try:
                values = pd.to_numeric(df[col], errors="coerce").dropna()
                if len(values) > 0:
                    summary[col.strip()] = {
                        "mean": round(float(values.mean()), 3),
                        "min": round(float(values.min()), 3),
                        "max": round(float(values.max()), 3),
                    }
            except Exception:
                continue
        return summary
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Calendar-dated series + closure checks (dt_rav_034 / dt_rav_035)
#
# Raven writes Hydrographs.csv and WatershedStorage.csv with a PERIOD-ENDING
# stamp: the row labelled date d holds the flow *of calendar day d-1*, and the
# row at time=0 is the initial condition only (RavenUsersManual v4.1, "Output
# files"). Joining the raw stamps to a gauge file therefore scores every model
# on a ONE-DAY LAG and disagrees with Raven's own Diagnostics.csv.
#
# Verified at Tangnaihai (2026-07-27): shifting the stamps back one day makes
# the "(observed)" column Raven echoes equal the raw gauge file EXACTLY on
# identical calendar dates (3286 days, max abs diff 0.0); the unshifted join
# differs by up to 580 m3/s.
# ---------------------------------------------------------------------------

# Columns of WatershedStorage.csv that are CUMULATIVE ACCUMULATORS or fluxes,
# not storage. "Total [mm]" bundles "Cum. Losses to Atmosphere", so taking
# dS = delta(Total) double-counts ET and makes the closure check FAIL on a run
# whose native MB Error is ~1e-12 mm (dt_rav_035).
_WS_ACCUMULATORS = (
    "Cum. Losses to Atmosphere [mm]", "Total [mm]",
    "Cum. Inputs [mm]", "Cum. Outflow [mm]", "MB Error [mm]",
)
_WS_FLUXES = ("rainfall [mm/day]", "snowfall [mm/d SWE]")
_WS_INDEX = ("time [d]", "time", "date", "hour")


def _read_raven_csv(path):
    """Read a Raven output CSV, stripping the padding spaces from headers."""
    df = pd.read_csv(path, skip_blank_lines=True)
    df.columns = [str(c).strip() for c in df.columns]
    return df


def load_discharge_series(output_dir, basin_name, date_convention="period_ending"):
    """Return (simulated, observed) discharge as calendar-dated pandas Series.

    date_convention:
      "period_ending" (Raven's own convention, DEFAULT) -- shift stamps back one
          day and drop the time=0 initial-condition row.
      "as_written"    -- keep the raw stamps (only for inspecting the raw file).

    Units m3/s. The observed series is Raven's echo of the :ObservationData in
    the .rvt, with the -1.2e30 / -9999 missing markers removed.
    """
    path = find_output_file(output_dir, basin_name, "Hydrographs.csv")
    if not path:
        raise FileNotFoundError(f"Hydrographs.csv not found under {output_dir}")

    df = _read_raven_csv(path)
    if "time" in df.columns:
        # time=0 is the initial condition, not a simulated day
        df = df[pd.to_numeric(df["time"], errors="coerce") > 0]

    date_col = "date" if "date" in df.columns else df.columns[0]
    dates = pd.to_datetime(df[date_col], errors="coerce")
    if date_convention == "period_ending":
        dates = dates - pd.Timedelta(days=1)
    elif date_convention != "as_written":
        raise ValueError(f"unknown date_convention: {date_convention}")

    sim_col = obs_col = None
    for c in df.columns:
        cl = c.lower()
        if "m3/s" not in cl and "cms" not in cl:
            continue
        if "observed" in cl or "(obs" in cl:
            obs_col = obs_col or c
        elif sim_col is None:
            sim_col = c
    if sim_col is None:
        raise ValueError(f"no simulated [m3/s] column in {path}: {list(df.columns)}")

    def _series(col):
        if col is None:
            return None
        s = pd.Series(pd.to_numeric(df[col], errors="coerce").values, index=dates)
        s = s[~s.index.isna()]
        s = s[~s.index.duplicated(keep="first")].sort_index()
        return s[s > -9000].dropna()

    return _series(sim_col), _series(obs_col)


def compute_water_balance(output_dir, basin_name, start=None, end=None):
    """Accumulator-free basin water-balance closure from WatershedStorage.csv.

    P, ET and Q are read from Raven's cumulative columns as END-minus-START
    differences; dS sums only the true STORAGE compartments (accumulators
    excluded -- dt_rav_035). Status comes from the shared
    ki_tools_common.validation.validate_water_balance so the verdict is the
    same one every HydroCraft model reports.
    """
    path = find_output_file(output_dir, basin_name, "WatershedStorage.csv")
    if not path:
        return {"status": "N/A", "residual_mm": None, "residual_pct": None,
                "diagnostics": ["WatershedStorage.csv not found"]}

    df = _read_raven_csv(path)
    dates = pd.to_datetime(df["date"], errors="coerce")
    df = df.set_index(dates)
    if start:
        df = df[df.index >= pd.Timestamp(start)]
    if end:
        df = df[df.index <= pd.Timestamp(end)]
    if len(df) < 2:
        return {"status": "N/A", "residual_mm": None, "residual_pct": None,
                "diagnostics": [f"only {len(df)} storage rows in {start}..{end}"]}

    skip = set(_WS_ACCUMULATORS) | set(_WS_FLUXES) | set(_WS_INDEX)
    storage_cols = [c for c in df.columns if c not in skip]
    num = df.apply(pd.to_numeric, errors="coerce")
    first, last = num.iloc[0], num.iloc[-1]

    def _delta(col):
        return float(last[col] - first[col]) if col in num.columns else 0.0

    precip = _delta("Cum. Inputs [mm]")
    et = _delta("Cum. Losses to Atmosphere [mm]")
    runoff = _delta("Cum. Outflow [mm]")
    d_storage = float(sum(last[c] for c in storage_cols)
                      - sum(first[c] for c in storage_cols))

    try:
        from ki_tools_common.validation import validate_water_balance
        wb = validate_water_balance(
            precip_mm=precip, et_mm=et, runoff_mm=runoff,
            delta_storage_mm=d_storage, period_days=len(df))
        out = {"status": wb.get("status"),
               "residual_mm": wb.get("residual_mm"),
               "residual_pct": wb.get("residual_pct"),
               "diagnostics": wb.get("diagnostics", [])}
    except Exception as e:  # shared validator unavailable -> local closure only
        resid = precip - et - runoff - d_storage
        out = {"status": "PASS" if abs(resid) < 0.01 * max(precip, 1.0) else "FAIL",
               "residual_mm": round(resid, 4),
               "residual_pct": round(100.0 * resid / precip, 4) if precip else None,
               "diagnostics": [f"ki_tools_common.validation unavailable: {e}"]}

    out["totals_mm"] = {"precip": round(precip, 1), "et": round(et, 1),
                        "runoff": round(runoff, 1),
                        "delta_storage": round(d_storage, 1)}
    if "MB Error [mm]" in num.columns:
        out["raven_mb_error_mm"] = float(last["MB Error [mm]"])
    out["storage_columns_used"] = storage_cols
    out["period"] = [str(df.index[0].date()), str(df.index[-1].date())]
    return out


def select_best_member(rows, cal_key="cal", metric="nse"):
    """Rank ensemble members on the CALIBRATION window and return (best, ranked).

    Structure choice is tuning: ranking members on the held-out window and then
    reporting that member's held-out score makes the headline a FITTED
    statistic. Selection must therefore read `cal_key` only (dt_rav_036).
    """
    scored = [r for r in rows
              if isinstance(r.get(cal_key), dict)
              and r[cal_key].get(metric) is not None]
    ranked = sorted(scored, key=lambda r: r[cal_key][metric], reverse=True)
    return (ranked[0] if ranked else None), ranked


def compute_additional_metrics(sim, obs):
    """Compute NSE, KGE, PBIAS, RMSE from simulated and observed arrays."""
    metrics = {}

    # Remove NaN pairs
    mask = ~(np.isnan(sim) | np.isnan(obs))
    s = sim[mask]
    o = obs[mask]

    if len(s) < 10:
        return {"warning": f"Only {len(s)} valid data points — metrics unreliable"}

    # NSE
    numerator = np.sum((s - o) ** 2)
    denominator = np.sum((o - np.mean(o)) ** 2)
    nse = 1 - numerator / denominator if denominator > 0 else -999
    metrics["NSE"] = round(nse, 4)

    # PBIAS
    pbias = 100 * np.sum(s - o) / np.sum(o) if np.sum(o) != 0 else -999
    metrics["PBIAS"] = round(pbias, 2)

    # RMSE
    rmse = np.sqrt(np.mean((s - o) ** 2))
    metrics["RMSE"] = round(rmse, 3)

    # KGE
    r = np.corrcoef(s, o)[0, 1] if len(s) > 1 else 0
    alpha = np.std(s) / np.std(o) if np.std(o) > 0 else 1
    beta = np.mean(s) / np.mean(o) if np.mean(o) > 0 else 1
    kge = 1 - np.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2)
    metrics["KGE"] = round(kge, 4)

    # Correlation
    metrics["r"] = round(r, 4)

    # Volume ratio
    metrics["volume_ratio"] = round(np.sum(s) / np.sum(o), 3) if np.sum(o) > 0 else -999

    return metrics


def process(args):
    """Main processing."""
    results = {}

    # Parse Hydrographs.csv
    hydro_path = find_output_file(args.output_dir, args.basin_name, "Hydrographs.csv")
    if hydro_path:
        df_hydro, err = parse_hydrographs(hydro_path)
        if err:
            results["hydrograph_error"] = err
        elif df_hydro is not None and "simulated_m3s" in df_hydro.columns:
            sim = df_hydro["simulated_m3s"].dropna()
            results["discharge_stats"] = {
                "mean_m3s": round(float(sim.mean()), 2),
                "max_m3s": round(float(sim.max()), 2),
                "min_m3s": round(float(sim.min()), 2),
                "std_m3s": round(float(sim.std()), 2),
                "n_records": len(sim),
            }

            # Export CSV if requested
            if args.export_csv:
                os.makedirs(os.path.dirname(args.export_csv) or ".", exist_ok=True)
                df_hydro.to_csv(args.export_csv, index=False)
                results["exported_csv"] = args.export_csv

            # Compute metrics if observed data available
            if "observed_m3s" in df_hydro.columns:
                obs = df_hydro["observed_m3s"].values
                sim_arr = df_hydro["simulated_m3s"].values
                metrics = compute_additional_metrics(sim_arr, obs)
                results["computed_metrics"] = metrics
    else:
        results["hydrograph_warning"] = "Hydrographs.csv not found"

    # Parse Diagnostics.csv
    diag_path = find_output_file(args.output_dir, args.basin_name, "Diagnostics.csv")
    if diag_path:
        results["raven_diagnostics"] = parse_diagnostics(diag_path)

    # Parse WatershedStorage.csv
    storage_path = find_output_file(args.output_dir, args.basin_name, "WatershedStorage.csv")
    if storage_path:
        results["watershed_storage"] = parse_watershed_storage(storage_path)

    # Check for solution.rvc (for warm restart)
    sol_path = find_output_file(args.output_dir, args.basin_name, "solution.rvc")
    if sol_path:
        results["solution_rvc"] = sol_path

    # Calendar-dated series (dt_rav_034) — always reported so callers can see
    # the convention that was applied without re-deriving it.
    try:
        sim_s, obs_s = load_discharge_series(args.output_dir, args.basin_name)
        results["discharge_series"] = {
            "date_convention": "period_ending",
            "n_days": int(len(sim_s)),
            "start": str(sim_s.index.min().date()) if len(sim_s) else None,
            "end": str(sim_s.index.max().date()) if len(sim_s) else None,
        }
    except Exception as e:
        results["discharge_series_error"] = str(e)

    # Water-balance closure (dt_rav_035) — mandatory post-run check
    if getattr(args, "water_balance", False):
        results["water_balance"] = compute_water_balance(
            args.output_dir, args.basin_name,
            start=getattr(args, "wb_start", None),
            end=getattr(args, "wb_end", None))

    results["status"] = "success"
    results["output_dir"] = args.output_dir

    return results


def main():
    parser = argparse.ArgumentParser(description="Parse Raven output files")
    parser.add_argument("--output_dir", required=True, help="Raven output directory")
    parser.add_argument("--basin_name", default="", help="Basin name (RunName prefix)")
    parser.add_argument("--obs_file", default=None, help="Observed discharge file")
    parser.add_argument("--export_csv", default=None, help="Export discharge to CSV")
    parser.add_argument("--water_balance", action="store_true",
                        help="Compute the accumulator-free basin water-balance closure")
    parser.add_argument("--wb_start", default=None,
                        help="Water-balance window start (YYYY-MM-DD)")
    parser.add_argument("--wb_end", default=None,
                        help="Water-balance window end (YYYY-MM-DD)")

    args = parser.parse_args()

    try:
        results = process(args)
    except Exception as e:
        print(json.dumps({"status": "error", "message": str(e)}))
        sys.exit(2)

    print(json.dumps(results, indent=2, default=str))
    sys.exit(0)


if __name__ == "__main__":
    main()
