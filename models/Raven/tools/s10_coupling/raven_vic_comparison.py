#!/usr/bin/env python3
"""
raven_vic_comparison.py — Compare Raven output with VIC output for the same basin.

Reads Raven Hydrographs.csv and VIC routing output, computes comparison
statistics (NSE, KGE, PBIAS, correlation), and generates summary.

Usage:
    python raven_vic_comparison.py \
        --raven_hydro outputs/chaohe_raven/output/Hydrographs.csv \
        --vic_discharge outputs/chaohe_2000_2010_025deg/routing_param/rout_out/discharge.day \
        --output_dir outputs/chaohe_comparison/ \
        --basin_name chaohe
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta

try:
    import numpy as np
    import pandas as pd
    sys.path.insert(0, "/home/server/knowledge-dissection-toolkit/auto_dissect")
    from ki_tools_common.metrics import nse as calc_nse, kge as calc_kge, pbias as calc_pbias, rmse as calc_rmse
except ImportError as e:
    print(json.dumps({"status": "error", "message": f"Missing dependency: {e}"}))
    sys.exit(1)


def read_raven_hydrograph(filepath):
    """Read Raven Hydrographs.csv — extract date and simulated discharge."""
    df = pd.read_csv(filepath)

    date_col = None
    sim_col = None

    for c in df.columns:
        cl = c.lower().strip()
        if "date" in cl:
            date_col = c
        elif ("m3/s" in cl or "cms" in cl) and "obs" not in cl:
            if sim_col is None:
                sim_col = c

    if date_col is None:
        date_col = df.columns[0]
    if sim_col is None and len(df.columns) >= 3:
        sim_col = df.columns[2]

    result = pd.DataFrame()
    result["date"] = pd.to_datetime(df[date_col], errors="coerce")
    result["raven_m3s"] = pd.to_numeric(df[sim_col], errors="coerce")

    return result.dropna(subset=["date"])


def read_vic_discharge(filepath):
    """Read VIC Lohmann routing output (.day file) or CaMa-Flood output."""
    # Try Lohmann routing format: YYYY MM DD Q
    try:
        data = np.loadtxt(filepath)
        if data.ndim == 1:
            data = data.reshape(1, -1)

        if data.shape[1] >= 4:
            dates = [datetime(int(r[0]), int(r[1]), int(r[2])) for r in data]
            discharge = data[:, 3]
            df = pd.DataFrame({"date": dates, "vic_m3s": discharge})
            return df
    except Exception:
        pass

    # Try CSV format
    try:
        df = pd.read_csv(filepath, sep=r"\s+|,", engine="python")
        if len(df.columns) >= 4:
            dates = [datetime(int(r[0]), int(r[1]), int(r[2]))
                     for _, r in df.iterrows()]
            df2 = pd.DataFrame({"date": dates, "vic_m3s": pd.to_numeric(df.iloc[:, 3])})
            return df2
    except Exception:
        pass

    return None


def compute_comparison(raven_df, vic_df):
    """Compute comparison statistics between Raven and VIC discharge."""
    # Merge on date
    merged = pd.merge(raven_df, vic_df, on="date", how="inner")

    if len(merged) < 10:
        return {"warning": f"Only {len(merged)} overlapping dates — insufficient for comparison"}

    sim = merged["raven_m3s"].values
    ref = merged["vic_m3s"].values

    # Remove NaN
    mask = ~(np.isnan(sim) | np.isnan(ref))
    sim = sim[mask]
    ref = ref[mask]

    if len(sim) < 10:
        return {"warning": "Insufficient valid data pairs"}

    # Correlation
    r = float(np.corrcoef(sim, ref)[0, 1])

    # Bias
    pbias = 100 * (np.sum(sim) - np.sum(ref)) / np.sum(ref) if np.sum(ref) > 0 else -999

    # RMSE
    rmse = float(np.sqrt(np.mean((sim - ref) ** 2)))

    # Volume ratio
    vol_ratio = float(np.sum(sim) / np.sum(ref)) if np.sum(ref) > 0 else -999

    # NSE (using VIC as "reference" — shows how well Raven matches VIC)
    nse_vs_vic = calc_nse(ref, sim)

    return {
        "n_overlap_days": len(sim),
        "period": f"{merged['date'].min().strftime('%Y-%m-%d')} to {merged['date'].max().strftime('%Y-%m-%d')}",
        "raven_mean_m3s": round(float(np.mean(sim)), 2),
        "vic_mean_m3s": round(float(np.mean(ref)), 2),
        "raven_max_m3s": round(float(np.max(sim)), 2),
        "vic_max_m3s": round(float(np.max(ref)), 2),
        "correlation_r": round(r, 4),
        "PBIAS_pct": round(pbias, 2),
        "RMSE_m3s": round(rmse, 2),
        "volume_ratio": round(vol_ratio, 3),
        "NSE_vs_VIC": round(nse_vs_vic, 4),
    }


def process(args):
    """Main comparison processing."""
    # Read Raven output
    raven_df = read_raven_hydrograph(args.raven_hydro)

    # Read VIC output
    vic_df = read_vic_discharge(args.vic_discharge)
    if vic_df is None:
        return {"status": "error", "message": f"Could not parse VIC discharge: {args.vic_discharge}"}

    # Compare
    comparison = compute_comparison(raven_df, vic_df)

    # Save comparison CSV
    os.makedirs(args.output_dir, exist_ok=True)
    merged = pd.merge(raven_df, vic_df, on="date", how="inner")
    csv_path = os.path.join(args.output_dir, f"{args.basin_name}_raven_vic_comparison.csv")
    merged.to_csv(csv_path, index=False)

    return {
        "status": "success",
        "comparison": comparison,
        "output_csv": csv_path,
        "raven_records": len(raven_df),
        "vic_records": len(vic_df),
    }


def main():
    parser = argparse.ArgumentParser(description="Compare Raven vs VIC output")
    parser.add_argument("--raven_hydro", required=True, help="Raven Hydrographs.csv path")
    parser.add_argument("--vic_discharge", required=True, help="VIC routing output path")
    parser.add_argument("--output_dir", required=True, help="Output directory")
    parser.add_argument("--basin_name", default="basin", help="Basin name")

    args = parser.parse_args()

    try:
        results = process(args)
    except Exception as e:
        print(json.dumps({"status": "error", "message": str(e)}))
        sys.exit(2)

    print(json.dumps(results, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
