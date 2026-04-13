#!/usr/bin/env python3
"""Convert meteorological forcing data to COSIPY input netCDF format.

Handles ERA5, AWS station data, and generic CSV/netCDF inputs.
Performs unit conversions, bounds checking, and lapse rate corrections.

Usage:
    python convert_forcing.py \\
        --input forcing.csv \\
        --output cosipy_input.nc \\
        --static static.nc \\
        --source era5 \\
        --start "2009-01-01" \\
        --end "2009-12-31"
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr


# ─── Variable specification ────────────────────────────────────────────
COSIPY_VARIABLES = {
    "T2":       {"units": "K",      "bounds": (223.16, 316.16), "desc": "2m air temperature"},
    "RH2":      {"units": "%",      "bounds": (0.0, 100.0),     "desc": "2m relative humidity"},
    "U2":       {"units": "m/s",    "bounds": (0.0, 50.0),      "desc": "2m wind speed"},
    "G":        {"units": "W/m2",   "bounds": (0.0, 1600.0),    "desc": "Incoming shortwave radiation"},
    "PRES":     {"units": "hPa",    "bounds": (200.0, 1080.0),  "desc": "Surface air pressure"},
    "RRR":      {"units": "mm",     "bounds": (0.0, 20.0),      "desc": "Total precipitation per timestep"},
    "N":        {"units": "fraction","bounds": (0.0, 1.0),      "desc": "Cloud cover fraction"},
    "LWin":     {"units": "W/m2",   "bounds": (0.0, 400.0),     "desc": "Incoming longwave radiation"},
    "SNOWFALL": {"units": "m",      "bounds": (0.0, 0.05),      "desc": "Snowfall in snow height per timestep"},
}

STATIC_VARIABLES = ["HGT", "ASPECT", "SLOPE", "MASK"]


def validate_inputs(input_path: str, source: str) -> bool:
    """Validate input file exists and source type is recognized.

    Args:
        input_path: Path to input file.
        source: Data source type.

    Returns:
        True if inputs are valid.

    Raises:
        FileNotFoundError: Input file not found.
        ValueError: Unknown source type.
    """
    if not Path(input_path).exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    valid_sources = ["era5", "aws", "csv", "wrf", "generic"]
    if source not in valid_sources:
        raise ValueError(f"Unknown source: {source}. Valid: {valid_sources}")

    return True


def read_era5_data(input_path: str, start_date: str, end_date: str) -> pd.DataFrame:
    """Read ERA5 netCDF or CSV data and convert units.

    ERA5 native units:
        - T2: K (no conversion needed)
        - dewpoint temperature: K (needs RH conversion)
        - u10, v10: m/s at 10m (needs height correction)
        - ssrd: J/m2 accumulated (needs /dt to get W/m2)
        - strd: J/m2 accumulated (needs /dt to get W/m2)
        - tp: m accumulated (needs /dt and *1000 for mm)
        - sp: Pa (needs /100 for hPa)

    Args:
        input_path: Path to ERA5 data file.
        start_date: Start date string.
        end_date: End date string.

    Returns:
        DataFrame with COSIPY-formatted forcing data.
    """
    if input_path.endswith(".nc"):
        ds = xr.open_dataset(input_path)
        df = ds.to_dataframe().reset_index()
        ds.close()
    else:
        df = pd.read_csv(input_path, parse_dates=["TIMESTAMP"], index_col="TIMESTAMP")
        df = df.loc[start_date:end_date]
        return df

    # Unit conversions for ERA5
    result = pd.DataFrame(index=df.index)

    # Temperature: ERA5 gives K, COSIPY expects K — no conversion
    if "t2m" in df.columns:
        result["T2"] = df["t2m"].values
    elif "T2" in df.columns:
        result["T2"] = df["T2"].values

    # Relative humidity from dewpoint
    if "d2m" in df.columns:
        t2 = df["t2m"].values
        d2 = df["d2m"].values
        # Magnus formula: RH = 100 * exp(17.625*Td/(243.04+Td)) / exp(17.625*T/(243.04+T))
        # where Td and T are in Celsius
        t2c = t2 - 273.16
        d2c = d2 - 273.16
        rh = 100.0 * np.exp(17.625 * d2c / (243.04 + d2c)) / np.exp(17.625 * t2c / (243.04 + t2c))
        result["RH2"] = np.clip(rh, 0.0, 100.0)
    elif "RH2" in df.columns:
        result["RH2"] = df["RH2"].values

    # Wind speed: ERA5 gives u10, v10 at 10m; COSIPY expects U2 at 2m
    if "u10" in df.columns and "v10" in df.columns:
        u10 = np.sqrt(df["u10"].values ** 2 + df["v10"].values ** 2)
        # Log wind profile correction: U2 = U10 * ln(2/z0) / ln(10/z0)
        z0 = 0.001  # roughness length in m (typical for snow)
        result["U2"] = u10 * np.log(2.0 / z0) / np.log(10.0 / z0)
    elif "U2" in df.columns:
        result["U2"] = df["U2"].values

    # Shortwave radiation: ERA5 gives accumulated J/m2, convert to W/m2
    if "ssrd" in df.columns:
        # De-accumulate and convert J/m2 to W/m2
        ssrd = df["ssrd"].values
        dt_seconds = 3600.0  # assuming hourly
        result["G"] = np.maximum(ssrd / dt_seconds, 0.0)
    elif "G" in df.columns:
        result["G"] = np.maximum(df["G"].values, 0.0)

    # Longwave radiation: ERA5 gives accumulated J/m2
    if "strd" in df.columns:
        strd = df["strd"].values
        dt_seconds = 3600.0
        result["LWin"] = np.maximum(strd / dt_seconds, 0.0)
    elif "LWin" in df.columns:
        result["LWin"] = df["LWin"].values

    # Pressure: ERA5 gives Pa, COSIPY expects hPa
    if "sp" in df.columns:
        result["PRES"] = df["sp"].values / 100.0
    elif "PRES" in df.columns:
        result["PRES"] = df["PRES"].values

    # Precipitation: ERA5 gives m accumulated, COSIPY expects mm per timestep
    if "tp" in df.columns:
        result["RRR"] = np.maximum(df["tp"].values * 1000.0, 0.0)  # m -> mm
    elif "RRR" in df.columns:
        result["RRR"] = np.maximum(df["RRR"].values, 0.0)

    # Cloud cover (if available)
    if "tcc" in df.columns:
        result["N"] = np.clip(df["tcc"].values, 0.0, 1.0)
    elif "N" in df.columns:
        result["N"] = df["N"].values

    # Snowfall (if available)
    if "sf" in df.columns:
        # ERA5 snowfall in m w.e., convert to m snow height
        density_fresh = 250.0  # approximate fresh snow density
        result["SNOWFALL"] = np.maximum(df["sf"].values * 1000.0 / density_fresh, 0.0)
    elif "SNOWFALL" in df.columns:
        result["SNOWFALL"] = df["SNOWFALL"].values

    return result


def read_aws_data(input_path: str, start_date: str, end_date: str,
                  temp_in_celsius: bool = False) -> pd.DataFrame:
    """Read AWS station CSV data.

    Args:
        input_path: Path to CSV file.
        start_date: Start date.
        end_date: End date.
        temp_in_celsius: If True, convert temperature from C to K.

    Returns:
        DataFrame with forcing data.
    """
    df = pd.read_csv(input_path, parse_dates=["TIMESTAMP"], index_col="TIMESTAMP")
    df = df.loc[start_date:end_date]

    if temp_in_celsius and "T2" in df.columns:
        df["T2"] = df["T2"] + 273.16

    return df


def apply_lapse_rates(df: pd.DataFrame, station_alt: float, target_alt: float,
                      lapse_T: float = -0.006, lapse_RH: float = 0.0,
                      lapse_RRR: float = 0.0) -> pd.DataFrame:
    """Apply lapse rate corrections for elevation difference.

    Args:
        df: Forcing dataframe.
        station_alt: Station elevation (m).
        target_alt: Target grid cell elevation (m).
        lapse_T: Temperature lapse rate (K/m), default -0.006.
        lapse_RH: Relative humidity lapse rate (%/m), default 0.
        lapse_RRR: Precipitation lapse rate (mm/m), default 0.

    Returns:
        Corrected dataframe.
    """
    dz = target_alt - station_alt

    if "T2" in df.columns:
        df["T2"] = df["T2"] + dz * lapse_T

    if "RH2" in df.columns:
        df["RH2"] = np.clip(df["RH2"] + dz * lapse_RH, 0.0, 100.0)

    if "RRR" in df.columns:
        df["RRR"] = np.maximum(df["RRR"] + dz * lapse_RRR, 0.0)

    return df


def validate_forcing(df: pd.DataFrame) -> list:
    """Validate forcing data ranges.

    Args:
        df: Forcing dataframe.

    Returns:
        List of warning messages (empty if all OK).
    """
    warnings = []

    for var_name, spec in COSIPY_VARIABLES.items():
        if var_name not in df.columns:
            continue

        values = df[var_name].dropna()
        if len(values) == 0:
            warnings.append(f"WARNING: {var_name} has no valid data")
            continue

        lo, hi = spec["bounds"]
        vmin, vmax = values.min(), values.max()

        if vmin < lo:
            warnings.append(f"WARNING: {var_name} min={vmin:.2f} < lower bound {lo} ({spec['units']})")
        if vmax > hi:
            warnings.append(f"WARNING: {var_name} max={vmax:.2f} > upper bound {hi} ({spec['units']})")

        # Unit detection heuristics
        if var_name == "T2" and vmax < 100:
            warnings.append(f"UNIT TRAP: T2 max={vmax:.1f} — likely Celsius, needs +273.16 for Kelvin")
        if var_name == "RH2" and vmax < 1.5:
            warnings.append(f"UNIT TRAP: RH2 max={vmax:.3f} — likely fraction (0-1), needs *100 for %")
        if var_name == "PRES" and vmin > 2000:
            warnings.append(f"UNIT TRAP: PRES min={vmin:.0f} — likely Pa, needs /100 for hPa")
        if var_name == "G" and vmax > 2000:
            warnings.append(f"UNIT TRAP: G max={vmax:.0f} — likely J/m2 accumulated, needs /dt_s for W/m2")
        if var_name == "N" and vmax > 1.5:
            warnings.append(f"UNIT TRAP: N max={vmax:.1f} — likely %, needs /100 for fraction")
        if var_name == "SNOWFALL" and vmax > 0.1:
            warnings.append(f"UNIT TRAP: SNOWFALL max={vmax:.3f} — likely mm or m w.e., check units")

    # Check for NaN
    nan_counts = df.isna().sum()
    for col, count in nan_counts.items():
        if count > 0:
            warnings.append(f"WARNING: {col} has {count} NaN values ({count/len(df)*100:.1f}%)")

    return warnings


def write_cosipy_netcdf(df: pd.DataFrame, static_ds: xr.Dataset,
                        output_path: str, point_lat: float, point_lon: float):
    """Write COSIPY-format netCDF input file.

    Args:
        df: Forcing dataframe (time-indexed).
        static_ds: Static dataset with HGT, SLOPE, ASPECT, MASK.
        output_path: Output file path.
        point_lat: Latitude for point model.
        point_lon: Longitude for point model.
    """
    # Create dataset
    ds = xr.Dataset()

    # Coordinates
    ds.coords["time"] = ("time", df.index.values)
    ds.coords["lat"] = ("lat", [point_lat])
    ds.coords["lon"] = ("lon", [point_lon])

    ds.lat.attrs = {"standard_name": "latitude", "units": "degrees_north"}
    ds.lon.attrs = {"standard_name": "longitude", "units": "degrees_east"}

    # Static variables from static file or defaults
    if static_ds is not None:
        for var in STATIC_VARIABLES:
            if var in static_ds:
                ds[var] = (("lat", "lon"), static_ds[var].values.reshape(1, 1))
    else:
        ds["HGT"] = (("lat", "lon"), np.array([[5000.0]]))
        ds["SLOPE"] = (("lat", "lon"), np.array([[0.0]]))
        ds["ASPECT"] = (("lat", "lon"), np.array([[0.0]]))
        ds["MASK"] = (("lat", "lon"), np.array([[1]]))

    # Time-varying forcing variables
    metadata = {
        "T2": ("K", "Temperature at 2 m"),
        "RH2": ("%", "Relative humidity at 2 m"),
        "U2": ("m s-1", "Wind velocity at 2 m"),
        "G": ("W m-2", "Incoming shortwave radiation"),
        "PRES": ("hPa", "Atmospheric Pressure"),
        "RRR": ("mm", "Total precipitation"),
        "N": ("%", "Cloud cover fraction"),
        "LWin": ("W m-2", "Incoming longwave radiation"),
        "SNOWFALL": ("m", "Snowfall"),
    }

    for var_name in metadata:
        if var_name in df.columns:
            data = df[var_name].values.reshape(-1, 1, 1)
            units, long_name = metadata[var_name]
            ds[var_name] = (("time", "lat", "lon"), data)
            ds[var_name].attrs = {"units": units, "long_name": long_name}

    # Write
    ds.to_netcdf(output_path)
    print(f"Output written: {output_path}")
    print(f"  Time steps: {len(df)}")
    print(f"  Variables: {list(ds.data_vars)}")


def validate_output(output_path: str) -> bool:
    """Validate the output netCDF file.

    Args:
        output_path: Path to output file.

    Returns:
        True if valid.
    """
    ds = xr.open_dataset(output_path)

    required = ["T2", "RH2", "U2", "G", "PRES", "MASK", "HGT"]
    missing = [v for v in required if v not in ds.data_vars and v not in ds.coords]
    if missing:
        print(f"ERROR: Missing required variables: {missing}")
        ds.close()
        return False

    # Check for either RRR or SNOWFALL
    if "RRR" not in ds.data_vars and "SNOWFALL" not in ds.data_vars:
        print("ERROR: Need at least one of RRR or SNOWFALL")
        ds.close()
        return False

    # Check for either LWin or N
    if "LWin" not in ds.data_vars and "N" not in ds.data_vars:
        print("ERROR: Need at least one of LWin or N (cloud cover)")
        ds.close()
        return False

    print("Output validation: PASSED")
    ds.close()
    return True


def main():
    parser = argparse.ArgumentParser(description="Convert forcing data to COSIPY format")
    parser.add_argument("-i", "--input", required=True, help="Input data file (CSV or netCDF)")
    parser.add_argument("-o", "--output", required=True, help="Output COSIPY netCDF file")
    parser.add_argument("-s", "--static", default=None, help="Static file (optional)")
    parser.add_argument("--source", default="generic", choices=["era5", "aws", "csv", "wrf", "generic"])
    parser.add_argument("--start", default=None, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", default=None, help="End date (YYYY-MM-DD)")
    parser.add_argument("--lat", type=float, default=30.47, help="Latitude")
    parser.add_argument("--lon", type=float, default=90.64, help="Longitude")
    parser.add_argument("--temp-celsius", action="store_true", help="Temperature is in Celsius")
    args = parser.parse_args()

    # Validate inputs
    validate_inputs(args.input, args.source)

    # Read data based on source
    if args.source == "era5":
        df = read_era5_data(args.input, args.start, args.end)
    elif args.source == "aws":
        df = read_aws_data(args.input, args.start, args.end, args.temp_celsius)
    else:
        df = pd.read_csv(args.input, parse_dates=["TIMESTAMP"], index_col="TIMESTAMP")
        if args.start and args.end:
            df = df.loc[args.start:args.end]

    # Validate forcing
    warnings = validate_forcing(df)
    for w in warnings:
        print(w)

    if any("UNIT TRAP" in w for w in warnings):
        print("\n*** UNIT TRAPS DETECTED — review warnings above before proceeding ***")

    # Read static file if provided
    static_ds = None
    if args.static:
        static_ds = xr.open_dataset(args.static)
        static_ds = static_ds.sel(lat=args.lat, lon=args.lon, method="nearest")

    # Write output
    write_cosipy_netcdf(df, static_ds, args.output, args.lat, args.lon)

    # Validate output
    validate_output(args.output)

    if static_ds is not None:
        static_ds.close()


if __name__ == "__main__":
    main()
