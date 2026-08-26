#!/usr/bin/env python3
"""
calculate_pet.py — Calculate potential evapotranspiration for wflow forcing.

Supports two methods:
  1. Hargreaves (default): Requires only Tmax, Tmin, latitude. Simple and robust.
  2. Penman-Monteith (FAO-56): Requires T, humidity, wind speed, radiation. More accurate.

wflow can also compute PET internally (Penman-Monteith or De Bruin) if individual
meteorological variables are provided instead of PET. This tool is for when you
want to pre-compute PET externally (e.g., for consistency with VIC PET).

CRITICAL: PET units must be mm/timestep (matching the TOML timestepsecs).
For daily wflow runs: mm/day. For hourly: mm/hour.

Usage:
    python calculate_pet.py \
      --method hargreaves \
      --forcing_nc /path/to/forcing.nc \
      --output /path/to/forcing_with_pet.nc

    python calculate_pet.py \
      --method penman_monteith \
      --forcing_nc /path/to/forcing.nc \
      --elevation 500 \
      --output /path/to/forcing_with_pet.nc
"""

import argparse
import json
import os
import sys
import time

import numpy as np
sys.path.insert(0, "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect")
from ki_tools_common.units import celsius_to_kelvin, kelvin_to_celsius
from ki_tools_common.humidity import saturation_vapor_pressure


def hargreaves_pet(tmax, tmin, lat_deg, doy):
    """Calculate PET using Hargreaves method (mm/day).

    Parameters
    ----------
    tmax : ndarray — maximum daily temperature (degC)
    tmin : ndarray — minimum daily temperature (degC)
    lat_deg : float or ndarray — latitude in degrees
    doy : int or ndarray — day of year (1-366)

    Returns
    -------
    pet : ndarray — potential evapotranspiration (mm/day)
    """
    lat_rad = np.radians(lat_deg)

    # Extraterrestrial radiation (Ra) in MJ/m2/day
    dr = 1.0 + 0.033 * np.cos(2 * np.pi * doy / 365.0)
    delta = 0.4093 * np.sin(2 * np.pi * doy / 365.0 - 1.39)

    # Handle array broadcasting for lat and delta
    if isinstance(lat_rad, np.ndarray) and lat_rad.ndim > 0:
        # Expand dims for broadcasting
        ws = np.arccos(
            np.clip(-np.tan(lat_rad) * np.tan(delta), -1, 1)
        )
    else:
        ws = np.arccos(np.clip(-np.tan(lat_rad) * np.tan(delta), -1, 1))

    ra = (
        24.0 * 60.0 / np.pi * 0.0820 * dr
        * (
            ws * np.sin(lat_rad) * np.sin(delta)
            + np.cos(lat_rad) * np.cos(delta) * np.sin(ws)
        )
    )
    ra = np.maximum(ra, 0.0)

    # Hargreaves equation
    t_range = np.maximum(tmax - tmin, 0.1)
    t_mean = (tmax + tmin) / 2.0

    # 0.408 converts MJ/m2/day to mm/day (latent heat of vaporization ~ 2.45 MJ/kg)
    pet = 0.0023 * (t_mean + 17.78) * np.sqrt(t_range) * 0.408 * ra
    pet = np.maximum(pet, 0.0)

    return pet


def penman_monteith_pet(temp, rh, wind, srad, elevation=0.0):
    """Calculate PET using FAO-56 Penman-Monteith (mm/day).

    Parameters
    ----------
    temp : ndarray — mean daily temperature (degC)
    rh : ndarray — relative humidity (%)
    wind : ndarray — wind speed at 2m (m/s)
    srad : ndarray — incoming shortwave radiation (W/m2)
    elevation : float — elevation above sea level (m)

    Returns
    -------
    pet : ndarray — potential evapotranspiration (mm/day)
    """
    # Constants
    # Psychrometric constant (kPa/degC)
    pressure = 101.3 * ((293.0 - 0.0065 * elevation) / 293.0) ** 5.26
    gamma = 0.000665 * pressure

    # Slope of saturation vapour pressure curve (kPa/degC)
    delta_vp = (
        4098.0
        * 0.6108
        * np.exp(17.27 * temp / (temp + 237.3))  # TODO: consider ki_tools_common.humidity.saturation_vapor_pressure
        / (temp + 237.3) ** 2
    )

    # Saturation and actual vapour pressure
    es = 0.6108 * np.exp(17.27 * temp / (temp + 237.3))  # TODO: consider ki_tools_common.humidity.saturation_vapor_pressure
    ea = es * rh / 100.0

    # Net radiation (approximate from shortwave)
    rn_sw = srad * 0.0864 * (1 - 0.23)  # W/m2 -> MJ/m2/day, albedo=0.23
    # Net longwave (simplified)
    sigma = 4.903e-9  # Stefan-Boltzmann MJ/m2/day/K4
    rn_lw = sigma * ((celsius_to_kelvin(temp)) ** 4) * (0.34 - 0.14 * np.sqrt(ea))
    rn = rn_sw - rn_lw
    rn = np.maximum(rn, 0.0)

    # FAO-56 Penman-Monteith
    pet = (
        (0.408 * delta_vp * rn + gamma * 900 / (temp + 273) * wind * (es - ea))
        / (delta_vp + gamma * (1 + 0.34 * wind))
    )
    pet = np.maximum(pet, 0.0)

    return pet


def process(args):
    """Calculate PET and add to forcing NetCDF."""
    import xarray as xr

    start_time = time.time()

    ds = xr.open_dataset(args.forcing_nc)

    # Get temperature
    temp_var = None
    for name in ["temp", "temperature", "t2m", "Tair"]:
        if name in ds:
            temp_var = name
            break
    if temp_var is None:
        return {"status": "failed", "error": "No temperature variable found in forcing.nc"}

    temp = ds[temp_var].values
    print(f"  Temperature range: {np.nanmin(temp):.1f} to {np.nanmax(temp):.1f} degC",
          file=sys.stderr)

    # Check if temperature is in Kelvin
    if np.nanmean(temp) > 100:
        print("  WARNING: Temperature appears to be in Kelvin. Converting to Celsius.",
              file=sys.stderr)
        temp = kelvin_to_celsius(temp)

    if args.method == "hargreaves":
        # Need Tmax and Tmin — if only Tmean available, estimate range
        tmax_var = None
        tmin_var = None
        for name in ["tmax", "Tmax", "tasmax"]:
            if name in ds:
                tmax_var = name
                break
        for name in ["tmin", "Tmin", "tasmin"]:
            if name in ds:
                tmin_var = name
                break

        if tmax_var and tmin_var:
            tmax = ds[tmax_var].values
            tmin = ds[tmin_var].values
        else:
            # Estimate Tmax/Tmin from Tmean with typical diurnal range
            dtr = 10.0  # default diurnal temperature range
            tmax = temp + dtr / 2
            tmin = temp - dtr / 2
            print("  NOTE: Using estimated diurnal range of 10 degC", file=sys.stderr)

        # Get latitude for each grid cell
        if "y" in ds.coords:
            lats = ds["y"].values
        elif "lat" in ds.coords:
            lats = ds["lat"].values
        else:
            lats = np.linspace(-90, 90, temp.shape[1])

        # Compute day of year
        times = ds["time"].values
        import pandas as pd
        doy = np.array([pd.Timestamp(t).timetuple().tm_yday for t in times])

        # Compute PET for each timestep
        nt, ny, nx = temp.shape
        pet = np.zeros_like(temp)
        for t_idx in range(nt):
            for j_idx in range(ny):
                pet[t_idx, j_idx, :] = hargreaves_pet(
                    tmax[t_idx, j_idx, :],
                    tmin[t_idx, j_idx, :],
                    lats[j_idx],
                    doy[t_idx],
                )

    elif args.method == "penman_monteith":
        # Need humidity, wind, radiation
        rh = ds.get("rh", ds.get("RelHum", None))
        wind = ds.get("wind", ds.get("WindSpeed", None))
        srad = ds.get("srad", ds.get("ShortWave", ds.get("sw", None)))

        if rh is None or wind is None or srad is None:
            return {
                "status": "failed",
                "error": "Penman-Monteith requires rh, wind, srad variables in forcing.nc",
            }

        pet = penman_monteith_pet(
            temp, rh.values, wind.values, srad.values, args.elevation
        )

    # Add PET to dataset
    ds["pet"] = (
        ds[temp_var].dims,
        pet.astype(np.float32),
        {
            "units": "mm",
            "long_name": "Potential evapotranspiration",
            "standard_name": "land_surface_water__potential_evaporation_volume_flux",
            "method": args.method,
        },
    )

    # Write output
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    ds.to_netcdf(args.output)

    elapsed = time.time() - start_time

    mean_pet = float(np.nanmean(pet))
    max_pet = float(np.nanmax(pet))

    return {
        "status": "success",
        "method": args.method,
        "output_path": args.output,
        "mean_pet_mm_day": round(mean_pet, 2),
        "max_pet_mm_day": round(max_pet, 2),
        "elapsed_seconds": round(elapsed, 1),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Calculate PET for wflow forcing"
    )
    parser.add_argument("--forcing_nc", type=str, required=True)
    parser.add_argument(
        "--method",
        type=str,
        default="hargreaves",
        choices=["hargreaves", "penman_monteith"],
    )
    parser.add_argument("--elevation", type=float, default=0.0)
    parser.add_argument("--output", type=str, required=True)
    args = parser.parse_args()

    if not os.path.exists(args.forcing_nc):
        print(f"ERROR: Forcing file not found: {args.forcing_nc}", file=sys.stderr)
        sys.exit(1)

    try:
        result = process(args)
    except Exception as e:
        print(json.dumps({"status": "failed", "error": str(e)}, indent=2))
        sys.exit(2)

    print(json.dumps(result, indent=2))
    sys.exit(0 if result["status"] == "success" else 2)


if __name__ == "__main__":
    main()
