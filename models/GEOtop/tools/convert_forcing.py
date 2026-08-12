#!/usr/bin/env python3
"""
convert_forcing.py - Convert global meteorological data to GEOtop meteo CSV format.

Supports: CMFD, MSWX, ERA5, NASA POWER, generic CSV.

CRITICAL UNIT CONVERSIONS:
  - GEOtop expects RelHum in PERCENT (0-100), not fraction (0-1)
  - GEOtop expects Iprec in mm per time step, not mm/hr or m/s
  - GEOtop expects AirT in Celsius, not Kelvin
  - GEOtop expects Swglobal in W/m2 (instantaneous, not accumulated)
  - GEOtop expects dates in DD/MM/YYYY hh:mm format (European)
  - Missing values MUST be -9999 (not NaN, -999, or blank)

Usage:
    python convert_forcing.py \\
        --source cmfd \\
        --input /path/to/forcing/data \\
        --lat 46.668 --lon 10.579 --elev 1480 \\
        --start "02/10/2009 00:00" --end "02/11/2009 00:00" \\
        --dt 3600 \\
        --output /path/to/sim/meteo/meteo0001.txt

    python convert_forcing.py \\
        --source csv \\
        --input /path/to/generic.csv \\
        --col-map '{"datetime":"Date","temp":"AirT","precip":"Iprec","rh":"RelHum","wind":"WindSp","srad":"Swglobal"}' \\
        --temp-unit K --rh-unit fraction --precip-unit mm_hr \\
        --dt 3600 \\
        --output /path/to/sim/meteo/meteo0001.txt
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

NODATA = -9999
GEOTOP_DATE_FMT = "%d/%m/%Y %H:%M"

# Julian Day reference: days from year 0 (GEOtop convention)
JULIAN_EPOCH = datetime(1, 1, 1)
JULIAN_OFFSET = 1721424.5  # JD of 1 Jan 0001


def validate_inputs(args):
    """Validate all input arguments before processing."""
    errors = []

    if args.source not in ("cmfd", "mswx", "era5", "nasa_power", "csv"):
        errors.append(f"Unknown source: {args.source}. Must be one of: cmfd, mswx, era5, nasa_power, csv")

    # nasa_power is an online point API with no local input file/dir.
    # mswx may pass a forcing-root dir but defaults are resolved by load_forcing.
    if args.source not in ("nasa_power", "mswx"):
        if not os.path.exists(args.input):
            errors.append(f"Input path does not exist: {args.input}")

    if args.lat < -90 or args.lat > 90:
        errors.append(f"Latitude out of range: {args.lat}")

    if args.lon < -180 or args.lon > 360:
        errors.append(f"Longitude out of range: {args.lon}")

    if args.dt <= 0:
        errors.append(f"Time step must be positive: {args.dt}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}), file=sys.stderr)
        sys.exit(1)


def date_to_jd_from0(dt):
    """Convert datetime to Julian Day from year 0 (GEOtop convention).

    JDfrom0 = integer day count since GEOtop's day-0 epoch PLUS the
    fractional day (hour/24). The fractional part MUST equal the time of day
    so that GEOtop's solar-position routine (radiation.cc: solar hour
    h = (JD-floor(JD))*24 + dh) lands the sun at the correct local clock time.

    Calibration anchor (shipped reference test tests/1D/Matsch_B2_Ref_007):
        02/10/2009 00:00  ->  734047.0000   (midnight => .0000, not .25)
        02/10/2009 01:00  ->  734047.0417
    datetime(2009,10,2) - datetime(1,1,1) = 733681 days, so the integer
    offset is 734047 - 733681 = 366 (an INTEGER).

    BUGFIX (2026-06-23, GEOtop MODIS-LST real case): the previous constant
    `+ 365.25 + 1` (= 366.25) injected a spurious +0.25 day = +6 h into the
    FRACTIONAL part of every timestamp. Midnight became .25 (=06:00), so
    GEOtop placed the sun ~6 h late and applied the shortwave pulse hours
    after the real solar noon. Surface/skin temperature (Tsurface) came out
    far too cold at the true daytime overpass time (~10 K low vs MODIS LST),
    while air temperature -- which GEOtop reads directly and does not phase
    against sun position -- looked fine. A classic silent error. Use the
    correct integer offset so frac(JDfrom0)*24 == hour-of-day exactly.
    """
    delta = dt - datetime(1, 1, 1)
    return delta.days + delta.seconds / 86400.0 + 366


def kelvin_to_celsius(t):
    """Convert temperature from Kelvin to Celsius."""
    return t - 273.15


def fraction_to_percent(rh):
    """Convert relative humidity from fraction (0-1) to percent (0-100)."""
    return rh * 100.0


def specific_to_relative_humidity(q, t_celsius, p_mbar=1013.25):
    """Convert specific humidity (kg/kg) to relative humidity (%).

    Args:
        q: Specific humidity in kg/kg
        t_celsius: Air temperature in Celsius
        p_mbar: Air pressure in mbar

    Returns:
        Relative humidity in percent (0-100)
    """
    # Saturation vapor pressure (Tetens formula, mbar)
    es = 6.1078 * np.exp(17.27 * t_celsius / (t_celsius + 237.3))
    # Vapor pressure from specific humidity
    e = q * p_mbar / (0.622 + 0.378 * q)
    rh = 100.0 * e / es
    return np.clip(rh, 0, 100)


def convert_precip(precip, from_unit, dt_seconds):
    """Convert precipitation to mm per time step.

    CRITICAL: GEOtop Iprec = total mm accumulated over the time step.

    Args:
        precip: Precipitation values
        from_unit: One of 'mm_hr', 'mm_day', 'mm_step', 'm_s', 'kg_m2_s'
        dt_seconds: Model time step in seconds
    """
    if from_unit == "mm_step":
        return precip
    elif from_unit == "mm_hr":
        return precip * (dt_seconds / 3600.0)
    elif from_unit == "mm_day":
        return precip * (dt_seconds / 86400.0)
    elif from_unit in ("m_s", "kg_m2_s"):
        # m/s -> mm/step: multiply by 1000 (m->mm) * dt (s)
        return precip * 1000.0 * dt_seconds
    else:
        raise ValueError(f"Unknown precipitation unit: {from_unit}")


"""CMFD note (2026-07-21, GEOtop NCP MODIS-LST real case)
------------------------------------------------------
There used to be a bespoke ``read_cmfd()`` here that did
``xr.open_mfdataset(input/*.nc)`` and then ``ds.sel(latitude=, longitude=)``,
assuming (a) every CMFD variable lives as a *.nc in ONE flat directory,
(b) the coordinates are named latitude/longitude and (c) prec is in mm/hr.

None of that matches CMFD V2.0 as shipped on this server
(/media/server/hc_ssd/forcing/Data_forcing_03hr_010deg/): the store is
per-variable SUBDIRECTORIES (Temp/ Prec/ SRad/ LRad/ Wind/ SHum/ Pres/) with
one file per MONTH, coordinates are lat/lon, and prec is kg/m2/s. The reader
raised/garbled on the real store, so `--source cmfd` was effectively dead.

Per the KDT 5.0 rule, the fix is NOT to re-implement a CMFD reader here but
to route through the canonical loader, ki_tools_common.load_forcing, which
already knows the on-disk layout and the unit conversions (K->C,
kg/m2/s->mm per 3-h step). `cmfd` now goes through read_via_load_forcing()
exactly like nasa_power / mswx.
"""


def read_generic_csv(input_path, col_map, temp_unit, rh_unit, precip_unit, dt_seconds):
    """Read a generic CSV file with user-specified column mapping and units."""
    mapping = json.loads(col_map) if isinstance(col_map, str) else col_map

    df = pd.read_csv(input_path, parse_dates=[mapping.get("datetime", "datetime")])
    df = df.set_index(mapping.get("datetime", "datetime"))

    result = pd.DataFrame(index=df.index)

    # Temperature
    temp_col = mapping.get("temp", "AirT")
    if temp_col in df.columns:
        result["AirT"] = df[temp_col]
        if temp_unit == "K":
            result["AirT"] = kelvin_to_celsius(result["AirT"])

    # Relative humidity
    rh_col = mapping.get("rh", "RelHum")
    if rh_col in df.columns:
        result["RelHum"] = df[rh_col]
        if rh_unit == "fraction":
            result["RelHum"] = fraction_to_percent(result["RelHum"])

    # Precipitation
    precip_col = mapping.get("precip", "Iprec")
    if precip_col in df.columns:
        result["Iprec"] = convert_precip(df[precip_col], precip_unit, dt_seconds)

    # Wind speed
    wind_col = mapping.get("wind", "WindSp")
    if wind_col in df.columns:
        result["WindSp"] = df[wind_col]

    # Shortwave radiation
    srad_col = mapping.get("srad", "Swglobal")
    if srad_col in df.columns:
        result["Swglobal"] = df[srad_col]

    # Wind direction (optional)
    wdir_col = mapping.get("wdir", "WindDir")
    if wdir_col in df.columns:
        result["WindDir"] = df[wdir_col]

    # Longwave radiation (optional)
    lw_col = mapping.get("lwin", "LWin")
    if lw_col in df.columns:
        result["LWin"] = df[lw_col]

    return result


def read_via_load_forcing(source, lat, lon, start, end, forcing_dir=None, dt=3600):
    """Read forcing through ki_tools_common.load_forcing (nasa_power / mswx / cmfd).

    This is the canonical HydroCraft forcing loader. It returns point series
    already in SI-ish units, which we map onto the GEOtop meteo columns:

        precip_mm  (mm per timestep)  -> Iprec      (mm per step) [direct]
        temp_c     (Celsius)          -> AirT       (Celsius)
        srad_wm2   (W/m2)             -> Swglobal   (W/m2)
        wind_ms    (m/s)             -> WindSp      (m/s)
        shum_kgkg + pres_pa + temp   -> RelHum      (PERCENT, via humidity util)
        lrad_wm2   (W/m2)             -> LWin       (W/m2, optional)
        pres_pa    (Pa)              -> AirPress    (mbar, optional)

    WindDir is not provided by the point loader -> NODATA.
    Returns a DatetimeIndex-ed DataFrame; the caller resamples to --dt.

    PERF FIX (2026-06-21, GEOtop real-case 05FA012): when the requested model
    step is daily (dt >= 86400) we call load_DAILY_forcing instead of
    load_hourly_forcing. The hourly loader for MSWX/NASA-POWER scans many
    sub-daily files and is ~minutes *per year* (times out on a 10-yr run);
    the daily loader returns the same point series in ~3 s/yr. GEOtop happily
    interpolates daily meteo entries to its internal TimeStepEnergyAndWater,
    exactly as the shipped Bengbu reference run does. The daily NASA-POWER
    schema names mean temperature `temp_mean_c` (not `temp_c`), so we coalesce.
    """
    from ki_tools_common.humidity import specific_humidity_to_rh

    daily = dt >= 86400
    if daily:
        from ki_tools_common.load_forcing import load_daily_forcing
        out = load_daily_forcing(source, lat, lon, start.year, end.year, forcing_dir=forcing_dir)
    else:
        from ki_tools_common.load_forcing import load_hourly_forcing
        out = load_hourly_forcing(source, lat, lon, start.year, end.year, forcing_dir=forcing_dir)

    dates = pd.to_datetime(out["dates"])
    # Mean air temperature: hourly schema uses `temp_c`, daily uses `temp_mean_c`.
    if "temp_c" in out:
        temp_c = np.asarray(out["temp_c"], dtype=float)
    else:
        temp_c = np.asarray(out["temp_mean_c"], dtype=float)
    pres_pa = np.asarray(out.get("pres_pa", np.full(len(dates), 101325.0)), dtype=float)
    shum = np.asarray(out.get("shum_kgkg", np.full(len(dates), np.nan)), dtype=float)

    # Relative humidity in PERCENT (dt_005). Clip to physical 1-100 range.
    rh = specific_humidity_to_rh(shum, temp_c + 273.15, pres_pa)
    rh = np.clip(np.asarray(rh, dtype=float), 1.0, 100.0)

    # PRECIP DEPTH (corrected 2026-07-21, GEOtop NCP MODIS-LST real case):
    # load_forcing returns precip_mm as the DEPTH accumulated over its own
    # native step (mm/day for the daily loader, mm/3h for CMFD/MSWX sub-daily),
    # which is exactly GEOtop's Iprec semantics -- meteodata.cc::fill_Pint
    # divides Iprec by the record spacing to get the intensity. So it is passed
    # through VERBATIM here; any change of record spacing is handled once, and
    # depth-conservingly, by resample_meteo(). The former unconditional
    # `if daily: iprec /= 24` (which assumed Iprec was an mm/h intensity) is
    # removed: it was compensating for the old interpolating resample, and left
    # in place it would now under-count daily-forced precipitation 24x.
    iprec = np.asarray(out["precip_mm"], dtype=float)
    df = pd.DataFrame({
        "Iprec": iprec,                                          # mm accumulated per record
        "WindSp": np.asarray(out.get("wind_ms", np.zeros(len(dates))), dtype=float),
        "WindDir": np.full(len(dates), NODATA, dtype=float),
        "RelHum": rh,
        "AirT": temp_c,
        "Swglobal": np.asarray(out["srad_wm2"], dtype=float),
        "LWin": np.asarray(out.get("lrad_wm2", np.full(len(dates), np.nan)), dtype=float),
        "AirPress": pres_pa / 100.0,                            # Pa -> mbar
    }, index=dates)
    df = df[(df.index >= start) & (df.index <= end)]
    # Drop optional columns that are entirely missing
    for c in ("LWin", "AirPress"):
        if df[c].isna().all():
            df = df.drop(columns=[c])
    return df


def resample_meteo(df, dt_seconds):
    """Resample a meteo DataFrame to `dt_seconds`, conserving precipitation DEPTH.

    Iprec is NOT a rate: GEOtop reads it as the water depth ACCUMULATED since
    the previous meteo record and derives the intensity itself by dividing by
    the record spacing --

        meteodata.cc :: fill_Pint()
            data[i][PrecInt] = data[i][Prec] / (JD[i] - JD[i-1]);  // mm/d
            data[i][PrecInt] /= 24.;                               // mm/h

    so a record at time t owns the interval (t-dt, t].

    BUGFIX (2026-07-21, GEOtop NCP MODIS-LST real case): the old line

        df = df.resample(f"{dt}s").interpolate(method="linear")

    interpolated EVERY column, Iprec included. Upsampling 3-hourly CMFD
    (mm per 3 h) to an hourly meteo file therefore wrote the full 3-hour depth
    into each of the 3 hourly records -- 3x the true precipitation, silently.
    The same defect inflated daily->hourly by 24x; a prior run papered over
    that specific case with an unconditional `iprec /= 24` in the daily branch
    of read_via_load_forcing() (see its PRECIP-INTENSITY note, whose stated
    rationale -- "GEOtop reads Iprec as an intensity in mm/h" -- is refuted by
    fill_Pint above). That /24 is now redundant *and wrong* once the resample
    conserves depth, so it has been removed: depth handling lives HERE, in one
    place, driven by the actual native-vs-target step.

    Rules:
      * state/flux columns (AirT, RelHum, WindSp, Swglobal, LWin, ...):
        upsample -> linear interpolation; downsample -> interval mean.
      * Iprec (accumulated depth): upsample -> split the depth evenly across
        the sub-intervals it covers; downsample -> sum over the interval.

    CONSERVED INVARIANT -- verify with this, not with the raw column sum:

        sum(Iprec[1:])  before  ==  sum(Iprec[1:])  after

    The FIRST record is excluded on purpose. Its interval reaches back before
    the file starts, so fill_Pint sets data[0][PrecInt] = novalue and GEOtop
    never integrates it. Upsampling likewise has nowhere to put that leading
    depth. Checked at 3h->1h, 3h->6h, 3h->3h and 1d->1h: the depth GEOtop
    actually applies is preserved exactly. A naive total-column-sum check will
    look "lossy" by exactly the first record and must not be re-"fixed".
    """
    if len(df) < 2:
        return df

    native = int(round(pd.Series(df.index).diff().dropna().dt.total_seconds().median()))
    if native == dt_seconds:
        return df

    target = f"{dt_seconds}s"
    others = [c for c in df.columns if c != "Iprec"]

    if dt_seconds < native:  # upsample
        out = df[others].resample(target).interpolate(method="linear") if others else None
        if "Iprec" in df.columns:
            ratio = native / float(dt_seconds)
            # record at t owns (t-dt, t] -> the covering native record is the
            # first native stamp at or after t: backward fill.
            pr = df["Iprec"].resample(target).bfill() / ratio
            out = pr.to_frame() if out is None else out.join(pr.rename("Iprec"))
    else:  # downsample
        out = df[others].resample(target, label="right", closed="right").mean() if others else None
        if "Iprec" in df.columns:
            pr = df["Iprec"].resample(target, label="right", closed="right").sum()
            out = pr.to_frame() if out is None else out.join(pr.rename("Iprec"))

    return out[[c for c in df.columns if c in out.columns]].dropna(how="all")


def process(args):
    """Main processing: read source data and write GEOtop meteo file."""
    start = datetime.strptime(args.start, GEOTOP_DATE_FMT)
    end = datetime.strptime(args.end, GEOTOP_DATE_FMT)

    if args.source in ("nasa_power", "mswx", "cmfd"):
        # Online/point loader via ki_tools_common (canonical HydroCraft path).
        fdir = args.input if (args.input and os.path.exists(args.input)) else None
        df = read_via_load_forcing(args.source, args.lat, args.lon, start, end, fdir, dt=args.dt)
        precip_unit = "mm_step"
    elif args.source == "csv":
        df = read_generic_csv(
            args.input, args.col_map,
            args.temp_unit, args.rh_unit, args.precip_unit, args.dt
        )
        precip_unit = args.precip_unit
    else:
        print(json.dumps({"status": "error", "errors": [f"Source '{args.source}' reader not yet implemented"]}),
              file=sys.stderr)
        sys.exit(1)

    # Resample to target time step if needed (depth-conserving for Iprec)
    df = resample_meteo(df, args.dt)

    # Build output DataFrame
    out_cols = ["Date", "JDfrom0"]
    meteo_cols = ["Iprec", "WindSp", "WindDir", "RelHum", "AirT", "Swglobal", "CloudTrans"]
    optional_cols = ["LWin", "DewT", "AirPress"]

    rows = []
    for ts, row in df.iterrows():
        dt_obj = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
        date_str = dt_obj.strftime(GEOTOP_DATE_FMT)
        jd = date_to_jd_from0(dt_obj)

        r = {
            "Date": date_str,
            "JDfrom0": f"{jd:.4f}",
            "Iprec": f"{row.get('Iprec', 0):.4f}" if pd.notna(row.get("Iprec")) else str(NODATA),
            "WindSp": f"{row.get('WindSp', 0):.2f}" if pd.notna(row.get("WindSp")) else str(NODATA),
            "WindDir": f"{row.get('WindDir', 0):.2f}" if pd.notna(row.get("WindDir")) else str(NODATA),
            "RelHum": f"{row.get('RelHum', 50):.2f}" if pd.notna(row.get("RelHum")) else str(NODATA),
            "AirT": f"{row.get('AirT', 10):.2f}" if pd.notna(row.get("AirT")) else str(NODATA),
            "Swglobal": f"{row.get('Swglobal', 0):.2f}" if pd.notna(row.get("Swglobal")) else str(NODATA),
            "CloudTrans": str(NODATA),  # Default to nodata (model will parameterize)
        }

        for col in optional_cols:
            if col in row and pd.notna(row[col]):
                r[col] = f"{row[col]:.2f}"

        rows.append(r)

    # Determine output columns
    all_cols = ["Date", "JDfrom0"] + meteo_cols
    for col in optional_cols:
        if any(col in r for r in rows):
            all_cols.append(col)

    # Write output
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w") as f:
        f.write(",".join(all_cols) + "\n")
        for r in rows:
            vals = [r.get(c, str(NODATA)) for c in all_cols]
            f.write(",".join(vals) + "\n")

    return len(rows)


def validate_outputs(output_path):
    """Validate the generated meteo file for common errors."""
    warnings = []

    df = pd.read_csv(output_path)

    # Check RelHum range
    if "RelHum" in df.columns:
        rh_valid = df["RelHum"][df["RelHum"] != NODATA]
        if len(rh_valid) > 0:
            if rh_valid.max() <= 1.0:
                warnings.append(
                    "CRITICAL: RelHum max <= 1.0 -- likely in fraction (0-1) instead of percent (0-100). "
                    "GEOtop expects PERCENT. Multiply by 100."
                )
            if rh_valid.max() > 100:
                warnings.append(f"RelHum max = {rh_valid.max():.1f} > 100%. Check input data.")

    # Check AirT range (should be Celsius)
    if "AirT" in df.columns:
        at_valid = df["AirT"][df["AirT"] != NODATA]
        if len(at_valid) > 0:
            if at_valid.mean() > 100:
                warnings.append(
                    "CRITICAL: AirT mean > 100 -- likely in Kelvin instead of Celsius. "
                    "Subtract 273.15."
                )

    # Check Iprec (should be non-negative, reasonable range)
    if "Iprec" in df.columns:
        prec_valid = df["Iprec"][df["Iprec"] != NODATA]
        if len(prec_valid) > 0:
            if prec_valid.max() > 200:
                warnings.append(
                    f"Iprec max = {prec_valid.max():.1f} mm/step. Very high. "
                    "Check if units are mm/hr vs mm/step."
                )

    # Check date format
    first_date = df.iloc[0]["Date"]
    if "/" not in str(first_date):
        warnings.append("Date column may not be in DD/MM/YYYY hh:mm format.")
    else:
        parts = str(first_date).split("/")
        if len(parts) >= 2:
            day = int(parts[0])
            month = int(parts[1])
            if day > 12 and month <= 12:
                pass  # Correctly DD/MM
            elif day <= 12 and month > 12:
                warnings.append("Date appears to be MM/DD/YYYY. GEOtop expects DD/MM/YYYY.")

    # Check for nodata
    nodata_count = (df == NODATA).sum().sum()
    total_values = df.shape[0] * df.shape[1]
    nodata_pct = 100.0 * nodata_count / total_values
    if nodata_pct > 50:
        warnings.append(f"{nodata_pct:.0f}% of values are nodata (-9999). Check input completeness.")

    result = {
        "status": "ok" if not warnings else "warning",
        "n_rows": len(df),
        "columns": list(df.columns),
        "warnings": warnings,
    }
    print(json.dumps(result, indent=2), file=sys.stderr)
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Convert meteorological forcing data to GEOtop meteoXXXX.txt format"
    )
    parser.add_argument("--source", required=True, choices=["cmfd", "mswx", "era5", "nasa_power", "csv"],
                        help="Data source type")
    parser.add_argument("--input", required=True, help="Input file or directory path")
    parser.add_argument("--lat", type=float, required=True, help="Latitude (degrees)")
    parser.add_argument("--lon", type=float, required=True, help="Longitude (degrees)")
    parser.add_argument("--elev", type=float, default=0, help="Elevation (m)")
    parser.add_argument("--start", required=True, help="Start date DD/MM/YYYY hh:mm")
    parser.add_argument("--end", required=True, help="End date DD/MM/YYYY hh:mm")
    parser.add_argument("--dt", type=int, default=3600, help="Time step in seconds (default: 3600)")
    parser.add_argument("--output", required=True, help="Output meteo file path")

    # Generic CSV options
    parser.add_argument("--col-map", default="{}", help="JSON column name mapping")
    parser.add_argument("--temp-unit", default="C", choices=["C", "K"], help="Input temperature unit")
    parser.add_argument("--rh-unit", default="percent", choices=["percent", "fraction", "specific"],
                        help="Input humidity unit")
    parser.add_argument("--precip-unit", default="mm_hr",
                        choices=["mm_hr", "mm_day", "mm_step", "m_s", "kg_m2_s"],
                        help="Input precipitation unit")

    args = parser.parse_args()
    validate_inputs(args)
    n_rows = process(args)
    validate_outputs(args.output)
    print(f"Wrote {n_rows} rows to {args.output}")


if __name__ == "__main__":
    main()
