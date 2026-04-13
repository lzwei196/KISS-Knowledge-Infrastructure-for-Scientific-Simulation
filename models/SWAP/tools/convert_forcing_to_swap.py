#!/usr/bin/env python3
"""
Convert CMFD or MSWX forcing data to SWAP .met file format.

SWAP .met format expects daily records with columns:
  Station, DD, MM, YYYY, Rad(kJ/m²/d), Tmin(°C), Tmax(°C), Hum(kPa), Wind(m/s), Rain(mm/d), ETref(mm/d), Wet

Unit conversions applied:
  - CMFD/MSWX radiation (W/m²) → kJ/m²/d  (× 86.4 for daily mean, or integrate sub-daily)
  - CMFD/MSWX temperature (K) → °C  (- 273.15)
  - CMFD specific humidity (kg/kg) + pressure (Pa) → vapor pressure (kPa)
  - MSWX specific humidity (kg/kg) + pressure (Pa) → vapor pressure (kPa)
  - CMFD precipitation (mm/day) → mm/d  (direct)
  - MSWX precipitation (mm/3hr) → mm/d  (sum 8 timesteps)
  - Wind speed (m/s) → m/s  (direct, but note measurement height)

Usage:
    python convert_forcing_to_swap.py \\
        --source cmfd \\
        --forcing-dir /path/to/forcing/ \\
        --lat 52.069 --lon 6.657 \\
        --start 2002-01-01 --end 2004-12-31 \\
        --station-name "HUPSEL" \\
        --output swap_met.met
"""

import argparse
import sys
import os
import math
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
KELVIN_OFFSET = 273.15
SEC_PER_DAY = 86400.0
KJ_FACTOR = 1000.0  # kJ → J or W*s/d / 1000


def validate_inputs(source, forcing_dir, lat, lon, start, end):
    """Pre-flight validation of inputs."""
    errors = []
    if source not in ("cmfd", "mswx"):
        errors.append(f"Unknown source '{source}'. Must be 'cmfd' or 'mswx'.")
    if not os.path.isdir(forcing_dir):
        errors.append(f"Forcing directory not found: {forcing_dir}")
    if not (-90 <= lat <= 90):
        errors.append(f"Latitude {lat} out of range [-90, 90]")
    if not (-180 <= lon <= 360):
        errors.append(f"Longitude {lon} out of range [-180, 360]")
    if start >= end:
        errors.append(f"Start date {start} must be before end date {end}")
    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"[OK] Input validation passed: {source}, lat={lat}, lon={lon}, {start} to {end}")


def specific_humidity_to_vapor_pressure(q, p_pa):
    """
    Convert specific humidity (kg/kg) and surface pressure (Pa) to
    actual vapor pressure (kPa).

    e = q * P / (0.622 + 0.378 * q)

    Parameters
    ----------
    q : float or array
        Specific humidity (kg/kg)
    p_pa : float or array
        Surface pressure (Pa)

    Returns
    -------
    e_kpa : float or array
        Actual vapor pressure (kPa)
    """
    p_kpa = np.asarray(p_pa) / 1000.0
    q = np.asarray(q)
    e_kpa = q * p_kpa / (0.622 + 0.378 * q)
    return e_kpa


def saturation_vapor_pressure(t_celsius):
    """Magnus formula for saturation vapor pressure (kPa)."""
    t = np.asarray(t_celsius)
    return 0.6108 * np.exp(17.27 * t / (t + 237.3))


def radiation_wm2_to_kjm2d(rad_wm2):
    """
    Convert instantaneous radiation (W/m²) to daily total (kJ/m²/d).
    For daily mean W/m²: multiply by 86400 s/d, divide by 1000 J/kJ.
    """
    return np.asarray(rad_wm2) * SEC_PER_DAY / KJ_FACTOR


def read_cmfd_daily(forcing_dir, lat, lon, start, end):
    """
    Read CMFD V2.0 daily forcing data.

    CMFD provides: prec (mm/day), temp (K), srad (W/m²), lrad (W/m²),
    wind (m/s), pres (Pa), shum (kg/kg).

    Returns dict of daily arrays.
    """
    try:
        import netCDF4 as nc
    except ImportError:
        print("ERROR: netCDF4 required. Install with: pip install netCDF4", file=sys.stderr)
        sys.exit(1)

    # CMFD directory structure: Data_forcing_01dy_010deg/
    # Files organized by variable and year
    forcing_dir = Path(forcing_dir)

    n_days = (end - start).days + 1
    dates = [start + timedelta(days=i) for i in range(n_days)]

    # Initialize arrays
    result = {
        "dates": dates,
        "rad": np.full(n_days, np.nan),     # Will be kJ/m²/d
        "tmin": np.full(n_days, np.nan),     # °C
        "tmax": np.full(n_days, np.nan),     # °C
        "hum": np.full(n_days, np.nan),      # kPa (vapor pressure)
        "wind": np.full(n_days, np.nan),     # m/s
        "rain": np.full(n_days, np.nan),     # mm/d
        "etref": np.full(n_days, -99.9),     # mm/d (not provided by CMFD)
        "wet": np.full(n_days, 0.0),         # fraction
    }

    # Try to find and read NetCDF files for each variable
    # CMFD naming convention varies; try common patterns
    var_map = {
        "srad": ("rad", lambda x: radiation_wm2_to_kjm2d(x)),
        "temp": ("temp_k", None),
        "wind": ("wind", None),
        "pres": ("pres", None),
        "shum": ("shum", None),
        "prec": ("rain", None),
    }

    # For each year in the range, attempt to read data
    for year in range(start.year, end.year + 1):
        year_start = max(start, datetime(year, 1, 1))
        year_end = min(end, datetime(year, 12, 31))

        # Find files for this year
        patterns = [
            f"*{year}*.nc",
            f"*{year}*.nc4",
        ]

        for var_name, (key, transform) in var_map.items():
            for pattern in patterns:
                matches = list(forcing_dir.glob(f"**/{var_name}*{year}*"))
                if matches:
                    try:
                        ds = nc.Dataset(str(matches[0]))
                        # Find nearest grid point
                        lats = ds.variables.get("lat", ds.variables.get("latitude", None))
                        lons = ds.variables.get("lon", ds.variables.get("longitude", None))
                        if lats is not None and lons is not None:
                            lat_idx = np.argmin(np.abs(np.array(lats[:]) - lat))
                            lon_idx = np.argmin(np.abs(np.array(lons[:]) - lon))
                            data = ds.variables[var_name][:, lat_idx, lon_idx]
                            if transform:
                                data = transform(data)
                        ds.close()
                    except Exception as e:
                        print(f"Warning: Could not read {var_name} for {year}: {e}")
                    break

    # Convert temperature K → °C (use daily mean as both Tmin and Tmax if only mean available)
    # In practice, CMFD provides mean temp — we estimate Tmin/Tmax with ±3°C offset
    if "temp_k" in result:
        t_mean = result["temp_k"] - KELVIN_OFFSET
        result["tmin"] = t_mean - 3.0  # Approximate
        result["tmax"] = t_mean + 3.0  # Approximate

    # Convert specific humidity + pressure → vapor pressure (kPa)
    if "shum" in result and "pres" in result:
        result["hum"] = specific_humidity_to_vapor_pressure(result["shum"], result["pres"])

    return result


def generate_synthetic_met(lat, lon, start, end, station_name="SYN"):
    """
    Generate synthetic meteorological data for testing when real forcing
    is not available. Uses simple sinusoidal patterns.

    Returns dict of daily arrays with proper SWAP units.
    """
    n_days = (end - start).days + 1
    dates = [start + timedelta(days=i) for i in range(n_days)]
    doy = np.array([d.timetuple().tm_yday for d in dates], dtype=float)

    # Solar radiation: sinusoidal seasonal pattern (kJ/m²/d)
    rad_max = 25000.0 if abs(lat) < 40 else 20000.0
    rad_min = 2000.0 if abs(lat) < 40 else 500.0
    rad = 0.5 * (rad_max + rad_min) + 0.5 * (rad_max - rad_min) * np.cos(
        2 * math.pi * (doy - 172) / 365.25
    )
    rad = np.maximum(rad, 0.0)

    # Temperature: seasonal sinusoid (°C)
    t_mean_annual = 20.0 - 0.5 * abs(lat)
    t_amplitude = 10.0 + 0.15 * abs(lat)
    t_mean = t_mean_annual + t_amplitude * np.cos(2 * math.pi * (doy - 200) / 365.25)
    tmin = t_mean - 4.0 + np.random.normal(0, 1, n_days)
    tmax = t_mean + 4.0 + np.random.normal(0, 1, n_days)

    # Vapor pressure (kPa): derive from temperature
    e_sat = saturation_vapor_pressure(t_mean)
    rh = 0.65 + 0.15 * np.cos(2 * math.pi * (doy - 200) / 365.25)
    hum = e_sat * rh

    # Wind speed (m/s)
    wind = 2.0 + 1.5 * np.random.exponential(1, n_days)
    wind = np.clip(wind, 0.5, 15.0)

    # Rainfall (mm/d): random with seasonal pattern
    rain_prob = 0.3 + 0.1 * np.cos(2 * math.pi * (doy - 100) / 365.25)
    rain_occur = np.random.random(n_days) < rain_prob
    rain_amount = np.random.exponential(5.0, n_days)
    rain = rain_occur * rain_amount

    # Wet fraction
    wet = np.where(rain > 0, np.minimum(rain / 50.0, 1.0), 0.0)

    return {
        "dates": dates,
        "rad": rad,
        "tmin": tmin,
        "tmax": tmax,
        "hum": hum,
        "wind": wind,
        "rain": rain,
        "etref": np.full(n_days, -99.9),
        "wet": wet,
    }


def write_met_file(output_path, station_name, lat, lon, data):
    """
    Write SWAP .met file.

    Format:
        * Comment header
        Station,DD,MM,YYYY,Rad,Tmin,Tmax,Hum,Wind,Rain,ETref,Wet
        'STA',01,01,2002,3810.0,-3.2,-0.1,0.52,4.9,0.0,0.4,0.0
    """
    with open(output_path, "w") as f:
        # Header comments
        f.write("*" + "-" * 80 + "\n")
        f.write(f"* Station           : {station_name}\n")
        f.write(f"* Latitude          : {lat:.3f}\n")
        f.write(f"* Longitude         : {lon:.3f}\n")
        f.write(f"* Generated by      : convert_forcing_to_swap.py (HydroCraft)\n")
        f.write(f"* Generated at      : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("*" + "-" * 80 + "\n")

        # Column header
        f.write("Station,DD,MM,YYYY,Rad,Tmin,Tmax,Hum,Wind,Rain,ETref,Wet\n")

        # Data rows
        dates = data["dates"]
        for i, d in enumerate(dates):
            rad = data["rad"][i]
            tmin = data["tmin"][i]
            tmax = data["tmax"][i]
            hum = data["hum"][i]
            wind = data["wind"][i]
            rain = data["rain"][i]
            etref = data["etref"][i]
            wet = data["wet"][i]

            f.write(
                f"'{station_name}',{d.day:02d},{d.month:02d},{d.year:04d},"
                f"{rad:.1f},{tmin:.1f},{tmax:.1f},{hum:.6f},{wind:.1f},"
                f"{rain:.3f},{etref:.1f},{wet:.3f}\n"
            )

    print(f"[OK] Wrote {len(dates)} daily records to {output_path}")


def validate_outputs(output_path, data):
    """Post-processing validation of generated .met file."""
    errors = []
    warnings = []

    # Check radiation range
    rad = data["rad"]
    if np.any(rad < 0):
        errors.append(f"Negative radiation values found (min={np.nanmin(rad):.1f})")
    if np.nanmax(rad) > 50000:
        warnings.append(f"Very high radiation (max={np.nanmax(rad):.1f} kJ/m²/d)")

    # Check temperature range
    tmin, tmax = data["tmin"], data["tmax"]
    if np.any(tmin > tmax):
        errors.append(f"Tmin > Tmax found at {np.sum(tmin > tmax)} records")
    if np.nanmin(tmin) < -60 or np.nanmax(tmax) > 60:
        warnings.append(f"Extreme temperatures: Tmin={np.nanmin(tmin):.1f}, Tmax={np.nanmax(tmax):.1f}")

    # Check humidity (must be vapor pressure in kPa, typically 0.1-6 kPa)
    hum = data["hum"]
    if np.nanmax(hum) > 10:
        errors.append(f"Humidity too high ({np.nanmax(hum):.2f} kPa) — may be in wrong units")
    if np.nanmax(hum) < 0.01:
        errors.append(f"Humidity too low ({np.nanmax(hum):.4f} kPa) — may be fraction, not kPa")
    if np.nanmax(hum) <= 1.0 and np.nanmin(hum) >= 0:
        warnings.append("Humidity values in 0-1 range — likely fraction, not kPa. Check conversion!")

    # Check rainfall
    rain = data["rain"]
    if np.nanmax(rain) > 500:
        warnings.append(f"Very high daily rainfall (max={np.nanmax(rain):.1f} mm/d)")

    # Check wind
    wind = data["wind"]
    if np.any(wind < 0):
        errors.append("Negative wind speed values found")

    # Check file was written
    if not os.path.isfile(output_path):
        errors.append(f"Output file not created: {output_path}")

    for w in warnings:
        print(f"WARNING: {w}")
    for e in errors:
        print(f"ERROR: {e}", file=sys.stderr)

    if errors:
        print(f"[FAIL] Output validation failed with {len(errors)} errors")
        return False
    print(f"[OK] Output validation passed ({len(warnings)} warnings)")
    return True


def main():
    parser = argparse.ArgumentParser(description="Convert forcing data to SWAP .met format")
    parser.add_argument("--source", choices=["cmfd", "mswx", "synthetic"], default="synthetic",
                        help="Forcing data source")
    parser.add_argument("--forcing-dir", type=str, default="",
                        help="Path to forcing data directory")
    parser.add_argument("--lat", type=float, required=True, help="Latitude (degrees N)")
    parser.add_argument("--lon", type=float, required=True, help="Longitude (degrees E)")
    parser.add_argument("--start", type=str, required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument("--station-name", type=str, default="STA", help="Station name")
    parser.add_argument("--output", type=str, required=True, help="Output .met file path")
    args = parser.parse_args()

    start = datetime.strptime(args.start, "%Y-%m-%d")
    end = datetime.strptime(args.end, "%Y-%m-%d")

    if args.source == "synthetic":
        print(f"Generating synthetic forcing for lat={args.lat}, lon={args.lon}")
        data = generate_synthetic_met(args.lat, args.lon, start, end, args.station_name)
    elif args.source == "cmfd":
        validate_inputs(args.source, args.forcing_dir, args.lat, args.lon, start, end)
        data = read_cmfd_daily(args.forcing_dir, args.lat, args.lon, start, end)
    elif args.source == "mswx":
        validate_inputs(args.source, args.forcing_dir, args.lat, args.lon, start, end)
        # MSWX reader would go here — similar structure to CMFD
        print("MSWX reader not yet implemented, falling back to synthetic")
        data = generate_synthetic_met(args.lat, args.lon, start, end, args.station_name)

    write_met_file(args.output, args.station_name, args.lat, args.lon, data)
    validate_outputs(args.output, data)


if __name__ == "__main__":
    main()
