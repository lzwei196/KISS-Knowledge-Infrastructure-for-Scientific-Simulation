#!/usr/bin/env python3
"""
Convert global forcing data (CMFD/ERA5/gauge) to airGR GR4J input format.

Pipeline stage: s1 (Forcing preparation)
Pattern: validate inputs -> process -> validate outputs

Input:  CMFD NetCDF or CSV with sub-daily meteorological data
Output: CSV with columns: Date, Precip_mm, PotEvap_mm, TempMean_degC

Unit conversions:
  - CMFD temperature: K -> degC (subtract 273.15)
  - CMFD precipitation: mm/3hr -> mm/day (sum 8 timesteps)
  - PE computed via Oudin formula from temperature and latitude
  - Observed discharge: m3/s or l/s -> mm/day
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime, timedelta
import math

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def validate_inputs(df: pd.DataFrame, source_type: str) -> list:
    """Validate raw input data before processing."""
    errors = []

    if df.empty:
        errors.append("Input dataframe is empty")
        return errors

    if source_type == "cmfd":
        required = ["date", "temp", "prec"]
        for col in required:
            if col not in df.columns:
                errors.append(f"Missing required column: {col}")

        if "temp" in df.columns:
            t_mean = df["temp"].mean()
            if t_mean > 200:
                # Temperature likely in Kelvin
                pass  # Will convert
            elif t_mean < -100:
                errors.append(f"Temperature mean={t_mean:.1f} is unrealistic")

        if "prec" in df.columns:
            if df["prec"].min() < 0:
                errors.append("Negative precipitation values found")

    elif source_type == "csv":
        required = ["Date"]
        for col in required:
            if col not in df.columns:
                errors.append(f"Missing required column: {col}")

    return errors


def validate_outputs(df_out: pd.DataFrame) -> list:
    """Validate processed output data."""
    warnings = []

    if "Precip_mm" in df_out.columns:
        p_max = df_out["Precip_mm"].max()
        p_mean = df_out["Precip_mm"].mean()
        if p_max > 500:
            warnings.append(
                f"Max precipitation = {p_max:.1f} mm/d — unrealistically high. "
                "Check if values are in mm/3hr (not aggregated) or m/day (not mm/day)."
            )
        if p_mean < 0.01:
            warnings.append(
                f"Mean precipitation = {p_mean:.4f} mm/d — near zero. "
                "Check if values are in m/day instead of mm/day (UT-002)."
            )

    if "PotEvap_mm" in df_out.columns:
        pe_max = df_out["PotEvap_mm"].max()
        pe_mean = df_out["PotEvap_mm"].mean()
        if pe_max > 30:
            warnings.append(
                f"Max PE = {pe_max:.1f} mm/d — too high. "
                "Check if temperature is in Kelvin instead of Celsius (UT-001)."
            )
        if pe_mean < 0.1:
            warnings.append(
                f"Mean PE = {pe_mean:.4f} mm/d — suspiciously low."
            )

    if "TempMean_degC" in df_out.columns:
        t_max = df_out["TempMean_degC"].max()
        if t_max > 100:
            warnings.append(
                f"Max temperature = {t_max:.1f} degC — likely still in Kelvin (UT-001)."
            )

    return warnings


# ---------------------------------------------------------------------------
# PE_Oudin: potential evapotranspiration from temperature and latitude
# ---------------------------------------------------------------------------

def pe_oudin(julian_day: np.ndarray, temp_degc: np.ndarray,
             lat_deg: float) -> np.ndarray:
    """
    Compute potential evapotranspiration using Oudin's formula.

    Parameters
    ----------
    julian_day : array of int, day of year (1-366)
    temp_degc  : array of float, daily mean temperature [degC]
    lat_deg    : float, latitude in degrees

    Returns
    -------
    pe : array of float, potential evapotranspiration [mm/day]
    """
    fi = lat_deg * math.pi / 180.0
    cos_fi = math.cos(fi)

    pe = np.zeros_like(temp_degc, dtype=float)

    for k in range(len(temp_degc)):
        jd = julian_day[k]
        teta = 0.4093 * math.sin(jd / 58.1 - 1.405)
        cos_teta = math.cos(teta)
        cos_gz = max(0.001, math.cos(fi - teta))
        gz = math.acos(cos_gz)
        cos_om = 1.0 - cos_gz / cos_fi / cos_teta
        cos_om = max(-1.0, min(1.0, cos_om))

        cos_om2 = cos_om * cos_om
        sin_om = 0.0 if cos_om2 >= 1.0 else math.sqrt(1.0 - cos_om2)

        om = math.acos(cos_om)
        cos_pz = cos_gz + cos_fi * cos_teta * (sin_om / om - 1.0) if om > 0 else cos_gz
        cos_pz = max(0.001, cos_pz)

        eta = 1.0 + math.cos(jd / 58.1) / 30.0
        ge = 446.0 * om * cos_pz * eta

        t = temp_degc[k]
        if np.isnan(t):
            pe[k] = np.nan
        elif t >= -5.0:
            pe[k] = ge * (t + 5.0) / 100.0 / 28.5
        else:
            pe[k] = 0.0

    return pe


# ---------------------------------------------------------------------------
# Conversion: discharge m3/s -> mm/day
# ---------------------------------------------------------------------------

def discharge_m3s_to_mmday(q_m3s: np.ndarray, area_km2: float) -> np.ndarray:
    """
    Convert discharge from m3/s to mm/day.

    Q_mm = Q_m3s * 86400 / (area_km2 * 1e6) * 1000
         = Q_m3s * 86.4 / area_km2
    """
    if area_km2 <= 0:
        raise ValueError(f"Catchment area must be positive, got {area_km2}")
    return q_m3s * 86.4 / area_km2


def discharge_ls_to_mmday(q_ls: np.ndarray, area_km2: float) -> np.ndarray:
    """Convert discharge from l/s to mm/day."""
    return discharge_m3s_to_mmday(q_ls / 1000.0, area_km2)


# ---------------------------------------------------------------------------
# Main conversion: CMFD -> airGR
# ---------------------------------------------------------------------------

def convert_cmfd_to_airgr(cmfd_csv: str, lat_deg: float,
                           output_csv: str,
                           area_km2: float = None,
                           qobs_csv: str = None) -> pd.DataFrame:
    """
    Convert CMFD forcing data to airGR GR4J input format.

    Parameters
    ----------
    cmfd_csv   : path to CMFD CSV with columns: date, temp, prec, [shum, pres, srad, wind]
    lat_deg    : catchment centroid latitude [degrees]
    output_csv : output path for airGR-format CSV
    area_km2   : catchment area [km2], needed for Qobs conversion
    qobs_csv   : optional path to observed discharge CSV

    Returns
    -------
    df_out : DataFrame with Date, Precip_mm, PotEvap_mm, TempMean_degC, [Qobs_mm]
    """
    # --- Read and validate inputs ---
    df = pd.read_csv(cmfd_csv, parse_dates=["date"])
    errors = validate_inputs(df, "cmfd")
    if errors:
        raise ValueError("Input validation failed:\n" + "\n".join(errors))

    # --- Temperature: K -> degC ---
    temp = df["temp"].values.copy()
    if np.nanmean(temp) > 200:
        print("[convert_forcing] Temperature appears to be in Kelvin, converting to degC")
        temp = temp - 273.15

    # --- Precipitation: aggregate sub-daily to daily ---
    df["date_day"] = df["date"].dt.date
    daily = df.groupby("date_day").agg(
        prec_sum=("prec", "sum"),
        temp_mean=("temp", "mean"),
    ).reset_index()
    daily["date_day"] = pd.to_datetime(daily["date_day"])

    # Temperature conversion for daily aggregated
    if np.nanmean(daily["temp_mean"].values) > 200:
        daily["temp_mean"] = daily["temp_mean"] - 273.15

    # Precipitation is already summed (mm/3hr * 8 timesteps = mm/day)
    precip_mm = daily["prec_sum"].values
    temp_degc = daily["temp_mean"].values

    # --- Compute PE via Oudin formula ---
    julian_days = daily["date_day"].dt.dayofyear.values
    pe_mm = pe_oudin(julian_days, temp_degc, lat_deg)

    # Clip negative PE to zero
    pe_mm = np.maximum(pe_mm, 0.0)

    # --- Build output DataFrame ---
    df_out = pd.DataFrame({
        "Date": daily["date_day"],
        "Precip_mm": np.round(precip_mm, 4),
        "PotEvap_mm": np.round(pe_mm, 4),
        "TempMean_degC": np.round(temp_degc, 2),
    })

    # --- Optional: merge observed discharge ---
    if qobs_csv and area_km2:
        df_q = pd.read_csv(qobs_csv, parse_dates=["date"])
        if "Q_m3s" in df_q.columns:
            df_q["Qobs_mm"] = discharge_m3s_to_mmday(df_q["Q_m3s"].values, area_km2)
        elif "Q_ls" in df_q.columns:
            df_q["Qobs_mm"] = discharge_ls_to_mmday(df_q["Q_ls"].values, area_km2)
        elif "Qmm" in df_q.columns:
            df_q["Qobs_mm"] = df_q["Qmm"]
        else:
            print("[convert_forcing] WARNING: No recognized Q column in qobs_csv")
            df_q["Qobs_mm"] = np.nan

        df_q["date_day"] = pd.to_datetime(df_q["date"]).dt.normalize()
        df_out = df_out.merge(
            df_q[["date_day", "Qobs_mm"]],
            left_on="Date", right_on="date_day", how="left"
        ).drop(columns=["date_day"], errors="ignore")

    # --- Validate outputs ---
    warnings = validate_outputs(df_out)
    for w in warnings:
        print(f"[convert_forcing] WARNING: {w}")

    # --- Write output ---
    df_out.to_csv(output_csv, index=False)
    print(f"[convert_forcing] Wrote {len(df_out)} daily records to {output_csv}")
    return df_out


# ---------------------------------------------------------------------------
# Main conversion: GRDC-Caravan basin-mean NetCDF -> airGR
# ---------------------------------------------------------------------------

def convert_caravan_to_airgr(caravan_nc: str, lat_deg: float,
                             output_csv: str,
                             start_date: str = None,
                             end_date: str = None,
                             pe_method: str = "oudin") -> pd.DataFrame:
    """
    Convert a GRDC-Caravan basin-mean timeseries NetCDF to airGR GR4J input.

    Caravan ships *basin-averaged* daily ERA5-Land forcing matched 1:1 with the
    standardised streamflow (already in mm/day), which is exactly the lumped
    catchment-average input GR4J needs — far more appropriate than a single
    point of MSWX/NASA-POWER for a large basin. This is the correct path for
    any global GRDC-Caravan gauge (e.g. Missouri R. at Hermann, 1.32e6 km2).

    Variables used:
      total_precipitation_sum   [mm]      -> Precip_mm   (daily basin-mean total)
      temperature_2m_mean       [degC]    -> TempMean_degC
      streamflow                [mm/day]  -> Qobs_mm      (already mm/day, no conversion)
      potential_evaporation_sum [mm]      -> PE if pe_method='era5land'

    PE handling:
      pe_method='oudin' (default, recommended): compute PE via the Oudin formula
        from basin-mean temperature + latitude. ERA5-Land potential_evaporation
        is strongly overestimated (~2300 mm/yr for the Missouri basin vs a
        realistic ~700-1100 mm/yr), which drains GR4J's production store; Oudin
        is the airGR-recommended PE input (Oudin et al. 2005).
      pe_method='era5land': use the shipped potential_evaporation_sum directly.

    Parameters
    ----------
    caravan_nc : path to GRDC-Caravan timeseries NetCDF (HDF5/NETCDF4)
    lat_deg    : basin centroid latitude [degrees] (for Oudin PE)
    output_csv : output path for airGR-format CSV
    start_date : optional 'YYYY-MM-DD' clip start
    end_date   : optional 'YYYY-MM-DD' clip end
    pe_method  : 'oudin' (default) or 'era5land'

    Returns
    -------
    df_out : DataFrame with Date, Precip_mm, PotEvap_mm, TempMean_degC, Qobs_mm
    """
    try:
        import xarray as xr
    except ImportError:
        raise ImportError("xarray required for Caravan loading. pip install xarray")

    # Caravan NetCDFs are HDF5; the default netCDF4 engine can hit HDF lock
    # errors on these read-only mounts, so prefer h5netcdf and fall back.
    try:
        ds = xr.open_dataset(caravan_nc, engine="h5netcdf")
    except Exception:
        ds = xr.open_dataset(caravan_nc)

    dates = pd.to_datetime(ds["date"].values)
    precip = ds["total_precipitation_sum"].values.astype(float)
    temp = ds["temperature_2m_mean"].values.astype(float)
    qobs = ds["streamflow"].values.astype(float)  # already mm/day
    pe_era5 = (ds["potential_evaporation_sum"].values.astype(float)
               if "potential_evaporation_sum" in ds else None)
    ds.close()

    df = pd.DataFrame({
        "Date": dates,
        "Precip_mm": precip,
        "TempMean_degC": temp,
        "Qobs_mm": qobs,
    })
    if pe_era5 is not None:
        df["_pe_era5"] = pe_era5

    # --- Clip to requested window ---
    if start_date:
        df = df[df["Date"] >= pd.Timestamp(start_date)]
    if end_date:
        df = df[df["Date"] <= pd.Timestamp(end_date)]
    df = df.sort_values("Date").reset_index(drop=True)

    # --- Forcing must contain no NA in Precip/PE (airGR stops on NA) ---
    # ERA5-Land basin means are gap-free, but guard anyway.
    df["Precip_mm"] = df["Precip_mm"].clip(lower=0).fillna(0.0)
    df["TempMean_degC"] = df["TempMean_degC"].interpolate().ffill().bfill()

    # --- PE ---
    if pe_method == "era5land" and "_pe_era5" in df.columns:
        pe_mm = np.maximum(df["_pe_era5"].fillna(0.0).values, 0.0)
    else:
        julian_days = df["Date"].dt.dayofyear.values
        pe_mm = pe_oudin(julian_days, df["TempMean_degC"].values, lat_deg)
        pe_mm = np.maximum(pe_mm, 0.0)

    df_out = pd.DataFrame({
        "Date": df["Date"].dt.strftime("%Y-%m-%d"),
        "Precip_mm": np.round(df["Precip_mm"].values, 4),
        "PotEvap_mm": np.round(pe_mm, 4),
        "TempMean_degC": np.round(df["TempMean_degC"].values, 2),
        "Qobs_mm": np.round(df["Qobs_mm"].values, 6),  # NA allowed in Qobs
    })

    warnings = validate_outputs(df_out)
    for w in warnings:
        print(f"[convert_forcing] WARNING: {w}")

    df_out.to_csv(output_csv, index=False)
    print(f"[convert_forcing] Caravan -> airGR: wrote {len(df_out)} daily records "
          f"to {output_csv} (PE={pe_method}, lat={lat_deg})")
    print(f"[convert_forcing]   P mean {df_out['Precip_mm'].mean():.3f} mm/d, "
          f"PE mean {df_out['PotEvap_mm'].mean():.3f} mm/d, "
          f"Qobs mean {df_out['Qobs_mm'].mean():.3f} mm/d")
    return df_out


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Convert CMFD/ERA5/Caravan forcing to airGR GR4J format"
    )
    parser.add_argument("--source", choices=["cmfd", "caravan"], default="cmfd",
                        help="Input source type")
    parser.add_argument("--cmfd-csv", help="Input CMFD CSV path (source=cmfd)")
    parser.add_argument("--caravan-nc", help="GRDC-Caravan timeseries NetCDF (source=caravan)")
    parser.add_argument("--lat", type=float, required=True, help="Catchment latitude [deg]")
    parser.add_argument("--output", required=True, help="Output CSV path")
    parser.add_argument("--area-km2", type=float, help="Catchment area [km2]")
    parser.add_argument("--qobs-csv", help="Observed discharge CSV path (source=cmfd)")
    parser.add_argument("--start-date", help="Clip start YYYY-MM-DD (source=caravan)")
    parser.add_argument("--end-date", help="Clip end YYYY-MM-DD (source=caravan)")
    parser.add_argument("--pe-method", choices=["oudin", "era5land"], default="oudin",
                        help="PE source for Caravan (default oudin)")

    args = parser.parse_args()
    if args.source == "caravan":
        if not args.caravan_nc:
            parser.error("--caravan-nc required when --source caravan")
        convert_caravan_to_airgr(
            caravan_nc=args.caravan_nc,
            lat_deg=args.lat,
            output_csv=args.output,
            start_date=args.start_date,
            end_date=args.end_date,
            pe_method=args.pe_method,
        )
    else:
        if not args.cmfd_csv:
            parser.error("--cmfd-csv required when --source cmfd")
        convert_cmfd_to_airgr(
            cmfd_csv=args.cmfd_csv,
            lat_deg=args.lat,
            output_csv=args.output,
            area_km2=args.area_km2,
            qobs_csv=args.qobs_csv,
        )


if __name__ == "__main__":
    main()
