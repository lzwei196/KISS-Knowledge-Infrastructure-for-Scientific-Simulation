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
from datetime import datetime, timedelta, date as date_cls
from pathlib import Path

import numpy as np

from ki_tools_common.load_forcing import load_daily_forcing

REAL_SOURCES = ("cmfd", "mswx", "nasa_power", "gswp3")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
KELVIN_OFFSET = 273.15
SEC_PER_DAY = 86400.0
KJ_FACTOR = 1000.0  # kJ → J or W*s/d / 1000


def validate_inputs(source, forcing_dir, lat, lon, start, end):
    """Pre-flight validation of inputs."""
    errors = []
    if source not in REAL_SOURCES:
        errors.append(f"Unknown source '{source}'. Must be one of {REAL_SOURCES}.")
    # nasa_power is fetched live and needs no local directory.
    if forcing_dir and not os.path.isdir(forcing_dir):
        errors.append(f"Forcing directory not found: {forcing_dir}")
    if source in ("cmfd", "mswx", "gswp3") and not forcing_dir:
        errors.append(f"--forcing-dir is required for source '{source}'")
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


def read_real_forcing(source, forcing_dir, lat, lon, start, end):
    """
    Load a real daily forcing series through the shared KDT reader.

    Replaces a hand-rolled NetCDF path that read each variable into a LOCAL
    `data` name, never assigned it back into `result`, and never created the
    'temp_k'/'shum'/'pres' keys its own conversions were gated on — so every
    CMFD .met it produced was 100% NaN and passed validation because
    np.nanmax range checks ignore NaN (dt_020).

    Returns the SWAP .met column dict.
    """
    kwargs = {}
    if forcing_dir:
        kwargs["forcing_dir"] = forcing_dir

    print(f"[RUN] load_daily_forcing(source={source}, lat={lat}, lon={lon}, "
          f"{start.year}-{end.year})")
    raw = load_daily_forcing(
        source, lat, lon, start.year, end.year,
        variables=["tmin", "tmax", "prcp", "srad", "wind", "rh", "pres", "shum"],
        **kwargs
    )

    frame = _as_column_dict(raw)
    dates_all = frame["dates"]

    # Clip to the requested window
    keep = [i for i, d in enumerate(dates_all) if start.date() <= d <= end.date()]
    if not keep:
        print(f"ERROR: {source} returned no days inside {start:%Y-%m-%d}.."
              f"{end:%Y-%m-%d}", file=sys.stderr)
        sys.exit(1)

    def col(*names, required=True):
        for n in names:
            if n in frame and frame[n] is not None:
                return np.asarray(frame[n], dtype=float)[keep]
        if required:
            print(f"ERROR: {source} forcing has none of {names} "
                  f"(available: {sorted(frame)})", file=sys.stderr)
            sys.exit(1)
        return None

    dates = [dates_all[i] for i in keep]
    n_days = len(dates)

    tmin = col("tmin", "tmin_c", "tasmin")
    tmax = col("tmax", "tmax_c", "tasmax")
    rain = col("prcp", "precip", "precip_mm", "pr", "rain")
    wind = col("wind", "wind_speed", "sfcwind", "ws10m")
    srad = col("srad", "rsds", "swdown", "solar")

    # Radiation -> kJ/m2/d, dispatched on magnitude:
    #   MJ/m2/d ~ 5-30, W/m2 daily mean ~ 50-350, kJ/m2/d ~ 5e3-3e4
    rad_mean = float(np.nanmean(srad))
    if rad_mean < 60.0:
        rad = srad * 1000.0                       # MJ/m2/d
    elif rad_mean < 600.0:
        rad = radiation_wm2_to_kjm2d(srad)        # W/m2 daily mean
    else:
        rad = srad                                # already kJ/m2/d
    print(f"[INFO] Radiation input mean {rad_mean:.1f} -> "
          f"{float(np.nanmean(rad)):.0f} kJ/m2/d")

    # Humidity -> actual vapour pressure (kPa)
    shum = col("shum", "spfh", "huss", required=False)
    pres = col("pres", "ps", "psurf", required=False)
    rh = col("rh", "hurs", "relhum", required=False)
    if shum is not None and pres is not None:
        hum = specific_humidity_to_vapor_pressure(shum, pres)
    elif rh is not None:
        rh_frac = rh / 100.0 if np.nanmax(rh) > 1.5 else rh
        hum = saturation_vapor_pressure(0.5 * (tmin + tmax)) * rh_frac
    else:
        print("ERROR: forcing provides neither (shum, pres) nor rh — actual "
              "vapour pressure cannot be derived", file=sys.stderr)
        sys.exit(1)

    return {
        "dates": [datetime(d.year, d.month, d.day) for d in dates],
        "rad": np.asarray(rad, dtype=float),
        "tmin": np.asarray(tmin, dtype=float),
        "tmax": np.asarray(tmax, dtype=float),
        "hum": np.asarray(hum, dtype=float),
        "wind": np.asarray(wind, dtype=float),
        "rain": np.asarray(rain, dtype=float),
        "etref": np.full(n_days, -99.9),
        "wet": np.where(np.asarray(rain) > 0,
                        np.minimum(np.asarray(rain) / 50.0, 1.0), 0.0),
    }


def _as_column_dict(raw):
    """
    Normalise whatever load_daily_forcing returned into
    {'dates': [date, ...], '<var>': array, ...}.
    """
    if hasattr(raw, "to_dict") and hasattr(raw, "columns"):   # DataFrame
        frame = {c: raw[c].to_numpy() for c in raw.columns}
        if "dates" not in frame:
            if "date" in frame:
                frame["dates"] = frame.pop("date")
            elif "time" in frame:
                frame["dates"] = frame.pop("time")
            else:
                frame["dates"] = raw.index.to_numpy()
    elif isinstance(raw, dict):
        frame = dict(raw)
        for alt in ("date", "time", "dates"):
            if alt in frame:
                frame["dates"] = frame.pop(alt)
                break
    else:
        print(f"ERROR: unexpected load_daily_forcing return type: {type(raw)}",
              file=sys.stderr)
        sys.exit(1)

    if "dates" not in frame:
        print(f"ERROR: forcing has no date axis (keys: {sorted(frame)})",
              file=sys.stderr)
        sys.exit(1)

    normalised = []
    for d in frame["dates"]:
        if isinstance(d, str):
            normalised.append(datetime.strptime(d[:10], "%Y-%m-%d").date())
        elif hasattr(d, "date") and not isinstance(d, date_cls):
            normalised.append(d.date())
        elif isinstance(d, date_cls):
            normalised.append(d)
        else:                                  # numpy datetime64
            normalised.append(
                datetime.utcfromtimestamp(
                    np.datetime64(d, "s").astype("int64")
                ).date()
            )
    frame["dates"] = normalised
    return frame


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

    # NaN is a HARD failure and must be checked before any range test:
    # np.nanmax/np.nanmin silently ignore NaN, so an all-NaN column passes
    # every range comparison below and SWAP receives a file of blanks (dt_020).
    for key in ("rad", "tmin", "tmax", "hum", "wind", "rain"):
        col = np.asarray(data[key], dtype=float)
        n_nan = int(np.count_nonzero(~np.isfinite(col)))
        if n_nan:
            errors.append(
                f"Column '{key}' has {n_nan}/{col.size} non-finite values "
                f"({100.0 * n_nan / max(col.size, 1):.1f}%) — the forcing "
                f"reader did not populate it"
            )
    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        print(f"[FAIL] Output validation failed with {len(errors)} errors")
        return False

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
    parser.add_argument("--source",
                        choices=list(REAL_SOURCES) + ["synthetic"],
                        required=True,
                        help="Forcing data source. 'synthetic' is a fabricated "
                             "series for smoke tests only and must be chosen "
                             "explicitly — it is never a fallback.")
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
        print("*" * 78)
        print("WARNING: --source synthetic generates FABRICATED weather. "
              "Any metric computed")
        print("         from a run driven by it is meaningless. Smoke tests only.")
        print("*" * 78)
        data = generate_synthetic_met(args.lat, args.lon, start, end,
                                      args.station_name)
    else:
        validate_inputs(args.source, args.forcing_dir, args.lat, args.lon,
                        start, end)
        data = read_real_forcing(args.source, args.forcing_dir, args.lat,
                                 args.lon, start, end)

    write_met_file(args.output, args.station_name, args.lat, args.lon, data)
    if not validate_outputs(args.output, data):
        sys.exit(1)


if __name__ == "__main__":
    main()
