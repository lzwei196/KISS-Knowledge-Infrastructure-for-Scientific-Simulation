#!/usr/bin/env python3
"""Parse COSIPY output netCDF files and extract results to CSV/summary.

Supports:
- Time series extraction for specific grid cells or domain averages
- Mass balance summary statistics
- Energy balance component analysis
- Comparison with stake observations (if available)

Usage:
    python parse_output.py \\
        --input data/output/Zhadang_ERA5_20090101-20090110.nc \\
        --output results.csv \\
        --mode timeseries

    python parse_output.py \\
        --input data/output/Zhadang_ERA5_20090101-20090110.nc \\
        --mode summary
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr


# Variable groups for organized output
ENERGY_VARS = ["G", "LWin", "LWout", "H", "LE", "B", "QRR", "ME"]
MASS_VARS = ["MB", "surfMB", "intMB", "SNOWFALL", "RAIN", "Q", "EVAPORATION",
             "SUBLIMATION", "CONDENSATION", "DEPOSITION", "REFREEZE", "surfM", "subM"]
STATE_VARS = ["SNOWHEIGHT", "TOTALHEIGHT", "TS", "ALBEDO", "LAYERS", "Z0"]

# Pore-close density [kg m^-3]: layers below this are snow/firn, above are ice.
# Matches constants.toml snow_ice_threshold; used to isolate the seasonal
# snowpack water equivalent (SWE) from the underlying glacier ice.
SNOW_ICE_THRESHOLD = 900.0


def open_dataset(path: str) -> xr.Dataset:
    """Open a COSIPY netCDF, trying the netCDF4 backend then h5netcdf.

    Some HydroCraft python environments have a broken netCDF4/HDF5 read path
    (OSError -101 HDF error) while h5netcdf reads the same file fine. Try both.
    """
    for engine in (None, "h5netcdf", "netcdf4"):
        try:
            return xr.open_dataset(path) if engine is None else xr.open_dataset(path, engine=engine)
        except Exception:
            continue
    # Last attempt: let the default raise a clear error
    return xr.open_dataset(path)


def derive_swe(ds: xr.Dataset, lat=None, lon=None) -> pd.Series:
    """Derive snow water equivalent (m w.e.) time series from layer fields.

    SWE = sum over snow layers (density < SNOW_ICE_THRESHOLD) of
          LAYER_HEIGHT [m] * LAYER_RHO [kg m^-3] / 1000  ->  m w.e.

    Requires full_field output (LAYER_HEIGHT, LAYER_RHO). Returns a time-indexed
    Series. This is the physically exact snowpack SWE, excluding glacier ice.
    """
    if "LAYER_HEIGHT" not in ds or "LAYER_RHO" not in ds:
        raise KeyError("LAYER_HEIGHT/LAYER_RHO not in output — run with full_field=true")
    sub = ds
    if lat is not None and lon is not None:
        sub = ds.sel(lat=lat, lon=lon, method="nearest")
    elif "lat" in ds.dims and "lon" in ds.dims:
        sub = ds.isel(lat=0, lon=0)
    H = np.asarray(sub["LAYER_HEIGHT"].values, dtype=float)  # (time, layer)
    R = np.asarray(sub["LAYER_RHO"].values, dtype=float)
    snow = (R < SNOW_ICE_THRESHOLD) & np.isfinite(R) & np.isfinite(H)
    swe = np.nansum(np.where(snow, H * R, 0.0), axis=1) / 1000.0
    return pd.Series(swe, index=pd.DatetimeIndex(sub["time"].values), name="SWE")


def compare_to_obs(sim: pd.Series, obs_csv: str, obs_col: str,
                   date_col: str = "Date", obs_scale: float = 1.0,
                   obs_offset: float = 0.0, comment: str = "#",
                   eval_start: str = None, eval_end: str = None,
                   cal_start: str = None, cal_end: str = None,
                   val_start: str = None, val_end: str = None) -> dict:
    """Align a simulated daily series with an observation CSV and score it.

    Uses ki_tools_common.metrics (NSE/KGE/r/PBIAS) — the shared HydroCraft
    metric implementation. obs values are scaled/offset into the sim units
    (e.g. SNOTEL SWE inches -> metres w.e. via obs_scale=0.0254).
    """
    from ki_tools_common.metrics import nse, kge, pbias, pearson_r

    obs = pd.read_csv(obs_csv, comment=comment)
    obs[date_col] = pd.to_datetime(obs[date_col])
    obs = obs.set_index(date_col)[obs_col].apply(pd.to_numeric, errors="coerce")
    obs = obs * obs_scale + obs_offset

    sim_d = sim.copy()
    sim_d.index = pd.DatetimeIndex(sim_d.index).normalize()
    sim_d = sim_d[~sim_d.index.duplicated(keep="last")]

    def _metrics(a_obs, a_sim):
        df = pd.DataFrame({"obs": a_obs, "sim": a_sim}).dropna()
        if len(df) < 3:
            return {"n": len(df)}
        return {
            "n": int(len(df)),
            "nse": float(nse(df["obs"].values, df["sim"].values)),
            "kge": float(kge(df["obs"].values, df["sim"].values)),
            "r": float(pearson_r(df["obs"].values, df["sim"].values)),
            "pbias": float(pbias(df["obs"].values, df["sim"].values)),
        }

    joined = pd.DataFrame({"sim": sim_d}).join(pd.DataFrame({"obs": obs}), how="inner")
    if eval_start or eval_end:
        joined = joined.loc[eval_start:eval_end]

    out = {"overall": _metrics(joined["obs"], joined["sim"]),
           "period": (str(joined.index.min())[:10], str(joined.index.max())[:10])}
    if cal_start or cal_end:
        c = joined.loc[cal_start:cal_end]
        out["cal"] = {**_metrics(c["obs"], c["sim"]),
                      "period": (str(c.index.min())[:10], str(c.index.max())[:10])}
    if val_start or val_end:
        v = joined.loc[val_start:val_end]
        out["val"] = {**_metrics(v["obs"], v["sim"]),
                      "period": (str(v.index.min())[:10], str(v.index.max())[:10])}
    return out


def validate_input(input_path: str) -> bool:
    """Validate input file exists and is a valid netCDF.

    Args:
        input_path: Path to output netCDF.

    Returns:
        True if valid.

    Raises:
        FileNotFoundError: File not found.
        ValueError: Not a valid netCDF.
    """
    path = Path(input_path)
    if not path.exists():
        raise FileNotFoundError(f"Output file not found: {input_path}")
    if path.suffix != ".nc":
        raise ValueError(f"Expected .nc file, got: {path.suffix}")
    return True


def get_dataset_info(ds: xr.Dataset) -> dict:
    """Get summary information about the dataset.

    Args:
        ds: COSIPY output dataset.

    Returns:
        Dictionary with dataset metadata.
    """
    info = {
        "dimensions": dict(ds.dims),
        "time_range": (str(ds.time.values[0])[:19], str(ds.time.values[-1])[:19]),
        "n_timesteps": len(ds.time),
        "variables": list(ds.data_vars),
        "n_variables": len(ds.data_vars),
    }

    # Grid info
    if "lat" in ds.coords:
        info["lat_range"] = (float(ds.lat.min()), float(ds.lat.max()))
        info["lon_range"] = (float(ds.lon.min()), float(ds.lon.max()))
    elif "south_north" in ds.dims:
        info["grid_type"] = "WRF"
        info["grid_size"] = (ds.dims["south_north"], ds.dims["west_east"])

    return info


def extract_timeseries(ds: xr.Dataset, lat: float = None, lon: float = None,
                       domain_mean: bool = False) -> pd.DataFrame:
    """Extract time series from COSIPY output.

    Args:
        ds: COSIPY output dataset.
        lat: Latitude for point extraction (optional).
        lon: Longitude for point extraction (optional).
        domain_mean: If True, average over all grid cells.

    Returns:
        DataFrame with time series of all available variables.
    """
    if lat is not None and lon is not None:
        # Point extraction
        subset = ds.sel(lat=lat, lon=lon, method="nearest")
    elif domain_mean:
        # Domain average (only over non-NaN cells)
        if "lat" in ds.dims and "lon" in ds.dims:
            subset = ds.mean(dim=["lat", "lon"], skipna=True)
        elif "south_north" in ds.dims:
            subset = ds.mean(dim=["south_north", "west_east"], skipna=True)
        else:
            subset = ds
    else:
        # Default: first grid point
        if "lat" in ds.dims and "lon" in ds.dims:
            subset = ds.isel(lat=0, lon=0)
        elif "south_north" in ds.dims:
            subset = ds.isel(south_north=0, west_east=0)
        else:
            subset = ds

    # Convert to dataframe
    df = subset.to_dataframe()

    # Clean up multi-index if present
    if isinstance(df.index, pd.MultiIndex):
        df = df.reset_index()
        if "time" in df.columns:
            df = df.set_index("time")

    return df


def compute_mass_balance_summary(ds: xr.Dataset) -> dict:
    """Compute mass balance summary statistics.

    Args:
        ds: COSIPY output dataset.

    Returns:
        Dictionary with mass balance statistics.
    """
    summary = {}

    # Domain mean for all mass balance components
    for var in MASS_VARS:
        if var in ds.data_vars:
            values = ds[var].values
            # Sum over time (cumulative MB), then spatial mean
            if values.ndim == 3:  # (time, lat, lon)
                cum = np.nansum(values, axis=0)  # cumulative per cell
                summary[f"{var}_cumulative_mean"] = float(np.nanmean(cum))
                summary[f"{var}_cumulative_std"] = float(np.nanstd(cum))
            elif values.ndim == 1:  # point model
                summary[f"{var}_cumulative"] = float(np.nansum(values))

    # Total mass balance
    if "MB" in ds.data_vars:
        mb = ds["MB"].values
        if mb.ndim == 3:
            total_mb = np.nansum(mb, axis=0)
            summary["total_MB_mean_m_we"] = float(np.nanmean(total_mb))
            summary["total_MB_min_m_we"] = float(np.nanmin(total_mb))
            summary["total_MB_max_m_we"] = float(np.nanmax(total_mb))
        else:
            summary["total_MB_m_we"] = float(np.nansum(mb))

    return summary


def compute_energy_balance_summary(ds: xr.Dataset) -> dict:
    """Compute energy balance summary statistics.

    Args:
        ds: COSIPY output dataset.

    Returns:
        Dictionary with energy balance means.
    """
    summary = {}

    for var in ENERGY_VARS:
        if var in ds.data_vars:
            values = ds[var].values
            summary[f"{var}_mean_W_m2"] = float(np.nanmean(values))
            summary[f"{var}_std_W_m2"] = float(np.nanstd(values))

    return summary


def compute_state_summary(ds: xr.Dataset) -> dict:
    """Compute snowpack state variable summary.

    Args:
        ds: COSIPY output dataset.

    Returns:
        Dictionary with state variable statistics.
    """
    summary = {}

    if "SNOWHEIGHT" in ds.data_vars:
        sh = ds["SNOWHEIGHT"].values
        summary["snowheight_mean_m"] = float(np.nanmean(sh))
        summary["snowheight_max_m"] = float(np.nanmax(sh))
        summary["snowheight_final_m"] = float(np.nanmean(sh[-1] if sh.ndim > 1 else sh[-1]))

    if "TS" in ds.data_vars:
        ts = ds["TS"].values
        summary["surface_temp_mean_K"] = float(np.nanmean(ts))
        summary["surface_temp_min_K"] = float(np.nanmin(ts))
        summary["surface_temp_max_K"] = float(np.nanmax(ts))

    if "ALBEDO" in ds.data_vars:
        alb = ds["ALBEDO"].values
        summary["albedo_mean"] = float(np.nanmean(alb))
        summary["albedo_min"] = float(np.nanmin(alb))
        summary["albedo_max"] = float(np.nanmax(alb))

    if "LAYERS" in ds.data_vars or "NLAYERS" in ds.data_vars:
        lvar = "LAYERS" if "LAYERS" in ds.data_vars else "NLAYERS"
        layers = ds[lvar].values
        summary["layers_mean"] = float(np.nanmean(layers))
        summary["layers_max"] = int(np.nanmax(layers))

    return summary


def print_summary(info: dict, mb_summary: dict, energy_summary: dict,
                  state_summary: dict):
    """Print formatted summary to console.

    Args:
        info: Dataset metadata.
        mb_summary: Mass balance statistics.
        energy_summary: Energy balance statistics.
        state_summary: State variable statistics.
    """
    print("=" * 60)
    print("COSIPY Output Summary")
    print("=" * 60)

    print(f"\nTime range: {info['time_range'][0]} to {info['time_range'][1]}")
    print(f"Timesteps:  {info['n_timesteps']}")
    print(f"Variables:  {info['n_variables']}")

    if mb_summary:
        print("\n--- Mass Balance ---")
        for k, v in mb_summary.items():
            print(f"  {k}: {v:.4f}")

    if energy_summary:
        print("\n--- Energy Balance (mean, W/m2) ---")
        for k, v in energy_summary.items():
            if k.endswith("mean_W_m2"):
                name = k.replace("_mean_W_m2", "")
                print(f"  {name:>8s}: {v:8.2f}")

    if state_summary:
        print("\n--- Snowpack State ---")
        for k, v in state_summary.items():
            print(f"  {k}: {v:.4f}")


def validate_output(output_path: str) -> bool:
    """Validate written CSV output.

    Args:
        output_path: Path to output CSV.

    Returns:
        True if file exists and has data.
    """
    path = Path(output_path)
    if not path.exists():
        print(f"ERROR: Output file not written: {output_path}")
        return False

    df = pd.read_csv(output_path)
    if len(df) == 0:
        print(f"ERROR: Output file is empty: {output_path}")
        return False

    print(f"Output validation: PASSED ({len(df)} rows, {len(df.columns)} columns)")
    return True


def main():
    parser = argparse.ArgumentParser(description="Parse COSIPY output")
    parser.add_argument("-i", "--input", required=True, help="Input COSIPY output netCDF")
    parser.add_argument("-o", "--output", default=None, help="Output CSV file (optional)")
    parser.add_argument("--mode", default="summary",
                        choices=["summary", "timeseries", "both", "compare"])
    parser.add_argument("--lat", type=float, default=None, help="Latitude for point extraction")
    parser.add_argument("--lon", type=float, default=None, help="Longitude for point extraction")
    parser.add_argument("--domain-mean", action="store_true", help="Compute domain average")
    # --- compare mode (validate SWE/snow-height against an obs CSV) ---
    parser.add_argument("--variable", default="SWE",
                        help="Quantity to compare: SWE (derived) or SNOWHEIGHT")
    parser.add_argument("--obs-csv", default=None, help="Observation CSV path")
    parser.add_argument("--obs-col", default=None, help="Observation column name")
    parser.add_argument("--date-col", default="Date", help="Date column in obs CSV")
    parser.add_argument("--obs-scale", type=float, default=1.0,
                        help="Multiply obs by this to reach sim units (e.g. 0.0254 in->m)")
    parser.add_argument("--obs-offset", type=float, default=0.0)
    parser.add_argument("--eval-start", default=None)
    parser.add_argument("--eval-end", default=None)
    parser.add_argument("--cal-start", default=None)
    parser.add_argument("--cal-end", default=None)
    parser.add_argument("--val-start", default=None)
    parser.add_argument("--val-end", default=None)
    args = parser.parse_args()

    # Validate input
    validate_input(args.input)

    # Open dataset (robust to broken netCDF4 backend)
    ds = open_dataset(args.input)

    if args.mode == "compare":
        import json
        if args.variable.upper() == "SWE":
            sim = derive_swe(ds, lat=args.lat, lon=args.lon)
        else:
            tsdf = extract_timeseries(ds, lat=args.lat, lon=args.lon,
                                      domain_mean=args.domain_mean)
            sim = tsdf[args.variable]
        result = compare_to_obs(
            sim, args.obs_csv, args.obs_col, date_col=args.date_col,
            obs_scale=args.obs_scale, obs_offset=args.obs_offset,
            eval_start=args.eval_start, eval_end=args.eval_end,
            cal_start=args.cal_start, cal_end=args.cal_end,
            val_start=args.val_start, val_end=args.val_end)
        print(json.dumps(result, indent=2))
        if args.output:
            sim.to_csv(args.output)
        ds.close()
        return

    # Get info
    info = get_dataset_info(ds)

    if args.mode in ["summary", "both"]:
        mb_summary = compute_mass_balance_summary(ds)
        energy_summary = compute_energy_balance_summary(ds)
        state_summary = compute_state_summary(ds)
        print_summary(info, mb_summary, energy_summary, state_summary)

    if args.mode in ["timeseries", "both"]:
        df = extract_timeseries(ds, lat=args.lat, lon=args.lon,
                                domain_mean=args.domain_mean)

        if args.output:
            df.to_csv(args.output)
            validate_output(args.output)
            print(f"Time series written to: {args.output}")
        else:
            print("\n--- Time Series (first 10 rows) ---")
            print(df.head(10).to_string())

    ds.close()


if __name__ == "__main__":
    main()
