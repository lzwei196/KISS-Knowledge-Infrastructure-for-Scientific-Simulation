#!/usr/bin/env python3
"""
Convert CMFD or MSWX forcing data to TOPMODEL inputs.dat format.

TOPMODEL requires:
  - rain in m/hr
  - pe (potential evapotranspiration) in m/hr
  - Qobs (observed discharge) in m/hr

CMFD provides:
  - prec in mm/day → divide by 24,000 to get m/hr
  - temp in K → subtract 273.15 for °C (used for PET calc)
  - srad in W/m² → used for PET calculation
  - wind, pres, shum → used for Penman-Monteith PET

Pipeline: validate → process → validate
"""

import os
import sys
import argparse
import numpy as np
from datetime import datetime, timedelta

def validate_inputs(forcing_dir, start_date, end_date, shapefile):
    """Validate that the forcing root and shapefile exist.

    Variable/file discovery is delegated to ki_tools_common.load_forcing, which
    knows each source's on-disk layout (CMFD subdirs, MSWX, NASA-POWER), so we
    no longer guess filenames here.
    """
    errors = []

    if forcing_dir and not os.path.isdir(forcing_dir):
        errors.append(f"Forcing directory not found: {forcing_dir}")

    if shapefile and not os.path.exists(shapefile):
        errors.append(f"Basin shapefile not found: {shapefile}")

    return errors


def compute_pet_hargreaves(tmin_C, tmax_C, tmean_C, lat_deg, doy):
    """
    Compute PET using Hargreaves method.

    Returns PET in mm/day.
    """
    # Extraterrestrial radiation (Ra) approximation
    lat_rad = np.radians(lat_deg)
    dr = 1 + 0.033 * np.cos(2 * np.pi * doy / 365)
    delta = 0.409 * np.sin(2 * np.pi * doy / 365 - 1.39)
    ws = np.arccos(-np.tan(lat_rad) * np.tan(delta))
    ws = np.clip(ws, 0, np.pi)

    Gsc = 0.0820  # solar constant MJ/m²/min
    Ra_MJ = (24 * 60 / np.pi) * Gsc * dr * (
        ws * np.sin(lat_rad) * np.sin(delta) +
        np.cos(lat_rad) * np.cos(delta) * np.sin(ws)
    )
    Ra_MJ = np.maximum(Ra_MJ, 0)

    # Hargreaves (FAO-56) requires Ra in EQUIVALENT EVAPORATION (mm/day), not in
    # MJ/m²/day. Convert with the latent-heat factor 0.408 (= 1/2.45 MJ/kg).
    # Omitting this inflates PET by ~2.45x (e.g. ~2500 mm/yr instead of the
    # realistic ~1000 mm/yr for the Huai basin), which silently dries the model
    # and suppresses runoff.
    Ra_mm = Ra_MJ * 0.408

    # Hargreaves equation
    trange = np.maximum(tmax_C - tmin_C, 0.1)
    pet = 0.0023 * (tmean_C + 17.8) * np.sqrt(trange) * Ra_mm
    pet = np.maximum(pet, 0)

    return pet


def extract_basin_mean_forcing(forcing_dir, shapefile, start_date, end_date,
                                lat_center=None, lon_center=None, source='cmfd'):
    """
    Extract basin forcing via the shared ki_tools_common loader.

    Uses ``ki_tools_common.load_forcing.load_daily_forcing`` which correctly
    handles the on-disk CMFD/MSWX/NASA-POWER directory layout (e.g. CMFD V0200
    stores monthly files under Prec/ Temp/ SRad/ subdirectories). The previous
    implementation globbed ``{var}*{year}*.nc`` directly in ``forcing_dir`` and
    only read ``files[0]`` — on the current CMFD layout it matched nothing and
    silently produced all-zero forcing. See triplet dt_016.

    TOPMODEL is lumped (single subcatchment), so a representative point at the
    basin centroid is extracted (the loader returns the nearest grid cell).

    Returns dict with daily arrays: prec_mm_day, temp_K, tmin_C, tmax_C, srad_Wm2.
    """
    from ki_tools_common.load_forcing import load_daily_forcing

    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    ndays = (end_dt - start_dt).days + 1

    fc = load_daily_forcing(source, lat_center, lon_center,
                            start_dt.year, end_dt.year,
                            forcing_dir=forcing_dir)

    # Normalize loader dates to python datetime. The MSWX loader returns
    # numpy.datetime64 (no .year/.month/.day attrs) while CMFD returns python
    # datetime; pd.Timestamp coerces both so the mapping below is source-robust.
    # (Prior bug: datetime(d.year,...) crashed on MSWX -> AttributeError.)
    import pandas as pd
    dates = [pd.Timestamp(d).to_pydatetime() for d in fc['dates']]
    # Map loader days onto the requested [start_dt, end_dt] window.
    prec_daily = np.full(ndays, np.nan)
    temp_daily = np.full(ndays, np.nan)
    tmin_daily = np.full(ndays, np.nan)
    tmax_daily = np.full(ndays, np.nan)
    srad_daily = np.full(ndays, np.nan)

    for i, d in enumerate(dates):
        dd = datetime(d.year, d.month, d.day)
        if dd < start_dt or dd > end_dt:
            continue
        j = (dd - start_dt).days
        if 0 <= j < ndays:
            prec_daily[j] = fc['precip_mm'][i]
            temp_daily[j] = fc['temp_mean_c'][i] + 273.15
            tmin_daily[j] = fc['temp_min_c'][i]
            tmax_daily[j] = fc['temp_max_c'][i]
            srad_daily[j] = fc['srad_wm2'][i]

    n_valid = int(np.sum(~np.isnan(prec_daily)))
    print(f"  load_daily_forcing({source}): {n_valid}/{ndays} days populated "
          f"(precip mean {np.nanmean(prec_daily):.2f} mm/day, "
          f"Tmean {np.nanmean(temp_daily)-273.15:.1f} C)")

    return {
        'prec_mm_day': prec_daily,
        'temp_K': temp_daily,
        'tmin_C': tmin_daily,
        'tmax_C': tmax_daily,
        'srad_Wm2': srad_daily,
        'ndays': ndays,
        'start_date': start_date,
    }


def load_obs_qmhr(obs_file, start_date, ndays, basin_area_km2,
                  seconds_per_day=86400.0):
    """
    Load observed daily discharge (m3/s) and convert to per-DAY runoff depth (m).

    TOPMODEL discharge is a DEPTH PER TIMESTEP. With one model step per day the
    matching observed quantity is the daily runoff depth:
        depth_per_day (m) = Q_m3s * 86400 / area_m2
    (i.e. the full day's volume spread over the basin). This must use 86400 s,
    NOT 3600 — a per-hour factor would leave obs 24x smaller than the simulated
    per-day depth and make NSE/PBIAS meaningless. The caller disaggregates this
    daily depth evenly across steps_per_day sub-steps.

    Missing days -> 0.0 (the Qobs column only feeds the binary's internal
    objective; authoritative cal/val metrics are computed externally on valid
    obs only).
    """
    import pandas as pd
    q = np.zeros(ndays)
    if not (obs_file and os.path.exists(obs_file) and basin_area_km2):
        return q
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    area_m2 = basin_area_km2 * 1e6
    # Encoding auto-detect (GBK for most Huai stations); only date/Q columns used.
    for enc in ('utf-8', 'gbk', 'gb18030'):
        try:
            df = pd.read_csv(obs_file, sep='\t', encoding=enc)
            break
        except Exception:
            df = None
    if df is None:
        print(f"WARNING: could not read obs file {obs_file}")
        return q
    df['date'] = pd.to_datetime(df['dates'])
    df = df[df['Q'] > -90]  # filter -99 / -99.9 missing flags
    for _, row in df.iterrows():
        dd = row['date'].to_pydatetime()
        j = (datetime(dd.year, dd.month, dd.day) - start_dt).days
        if 0 <= j < ndays:
            q[j] = float(row['Q']) * seconds_per_day / area_m2
    return q


def convert_to_topmodel_inputs(forcing_data, dt_hours, lat_center,
                                obs_file=None, basin_area_km2=None,
                                output_file='inputs.dat'):
    """
    Convert forcing data to TOPMODEL inputs.dat format.

    CRITICAL CONVERSIONS:
      - prec: mm/day → m/hr  (÷ 24,000)
      - PET: mm/day → m/hr   (÷ 24,000)
      - Qobs: m³/s → m/hr    (÷ (area_m² / 3600))  but if not available, use 0
    """
    ndays = forcing_data['ndays']
    steps_per_day = int(round(24 / dt_hours))
    nstep = ndays * steps_per_day

    prec_mm_day = forcing_data['prec_mm_day']
    temp_K = forcing_data['temp_K']
    temp_C = temp_K - 273.15

    # Prefer real daily Tmin/Tmax from the forcing source; fall back to +-5C.
    tmin_C = forcing_data.get('tmin_C')
    tmax_C = forcing_data.get('tmax_C')
    if tmin_C is None or np.all(np.isnan(tmin_C)):
        tmin_C = temp_C - 5.0
        tmax_C = temp_C + 5.0

    start_dt = datetime.strptime(forcing_data['start_date'], "%Y-%m-%d")
    doys = np.array([(start_dt + timedelta(days=i)).timetuple().tm_yday
                     for i in range(ndays)])

    pet_mm_day = compute_pet_hargreaves(tmin_C, tmax_C, temp_C, lat_center, doys)

    # CRITICAL UNIT CONVERSION.
    # The TOPMODEL C engine treats rain[it]/pe[it] as DEPTH PER TIMESTEP (m),
    # NOT a rate: see topmodel.c `*p=rain[it]; deficit_root_zone-=*p`. The
    # timestep dt (hours) is used only for rate conversions (infiltration p/dt,
    # uz drainage td*dt, channel routing chv*dt).
    #   daily depth (m) = mm/day / 1000
    #   per-step depth  = daily depth / steps_per_day
    # => at dt=1h  (24 steps/day): /1000/24 = /24000   (matches hourly convention)
    #    at dt=24h ( 1 step/day):  /1000               (daily convention)
    daily_depth_m = np.nan_to_num(prec_mm_day, nan=0.0) / 1000.0
    daily_pet_m = np.nan_to_num(pet_mm_day, nan=0.0) / 1000.0
    prec_step = daily_depth_m / steps_per_day
    pet_step = daily_pet_m / steps_per_day

    # Observed discharge (per-step depth). Disaggregating obs the same way keeps
    # it on the same per-step footing as the simulated flow.
    qobs_daily = load_obs_qmhr(obs_file, forcing_data['start_date'], ndays,
                               basin_area_km2)
    qobs_step = qobs_daily / steps_per_day

    # Disaggregate daily to sub-daily (uniform within day)
    rain_hourly = np.repeat(prec_step, steps_per_day)
    pet_hourly = np.repeat(pet_step, steps_per_day)
    qobs_hourly = np.repeat(qobs_step, steps_per_day)

    # Header timestep MUST be 1.0. The NOAA-OWP standalone binary advances time
    # as `current_time_step += dt` (bmi_topmodel.c Update) and then uses
    # current_time_step as the 1-based index into rain[]/pe[]/Qobs[]. Any dt!=1
    # makes it index rain[dt], rain[2*dt], ... — skipping (dt-1)/dt of the data,
    # reading past the array end (SUMP collapses, eventually SIGSEGV). So one
    # model timestep == one input row, regardless of the physical step length.
    # For a daily run (steps_per_day=1) each step represents one day and the
    # rate parameters (t0, td, chv, rv) are therefore interpreted per-day.
    model_dt = 1.0
    with open(output_file, 'w') as f:
        f.write(f"{nstep}  {model_dt:.1f}\n")
        for i in range(nstep):
            f.write(f"   {rain_hourly[i]:.8f}  {pet_hourly[i]:.8f}  {qobs_hourly[i]:.8f}\n")

    phys_hours = 24.0 / steps_per_day
    print(f"Wrote {output_file}: {nstep} steps (model dt=1.0, "
          f"1 step = {phys_hours:.1f} physical hours), "
          f"max rain/step={rain_hourly.max():.5f} m")
    return nstep


def validate_outputs(output_file, nstep):
    """Validate the generated inputs.dat file."""
    errors = []

    if not os.path.exists(output_file):
        errors.append(f"Output file not created: {output_file}")
        return errors

    with open(output_file, 'r') as f:
        lines = f.readlines()

    header = lines[0].split()
    file_nstep = int(header[0])
    file_dt = float(header[1])

    if file_nstep != nstep:
        errors.append(f"nstep mismatch: expected {nstep}, got {file_nstep}")

    data_lines = len(lines) - 1
    if data_lines != nstep:
        errors.append(f"Data lines mismatch: expected {nstep}, got {data_lines}")

    # Value-range checks are on PER-STEP DEPTH (m/step). The header dt is always
    # 1.0 (see convert_to_topmodel_inputs), so use a physically generous ceiling:
    # an extreme daily storm is ~250 mm = 0.25 m; allow some margin.
    rain_ceiling = 0.5
    for i, line in enumerate(lines[1:], 1):
        vals = line.split()
        if len(vals) != 3:
            errors.append(f"Line {i}: expected 3 values, got {len(vals)}")
            continue
        rain, pe, qobs = float(vals[0]), float(vals[1]), float(vals[2])

        if rain > rain_ceiling:
            errors.append(f"Line {i}: rain={rain} m/step exceeds {rain_ceiling:.3f} m "
                          f"(implausible at dt={file_dt}h)")
        if rain < 0:
            errors.append(f"Line {i}: negative rainfall")
        if pe < 0:
            errors.append(f"Line {i}: negative PE")

    if not errors:
        print(f"VALIDATION PASSED: {output_file}")
    else:
        for e in errors[:10]:
            print(f"VALIDATION WARNING: {e}")

    return errors


def main():
    parser = argparse.ArgumentParser(description="Convert CMFD forcing to TOPMODEL inputs.dat")
    parser.add_argument('--forcing-dir', required=True, help='Forcing root directory (CMFD/MSWX)')
    parser.add_argument('--source', default='cmfd', help='Forcing source: cmfd|mswx|nasa_power')
    parser.add_argument('--start-date', required=True, help='Start date YYYY-MM-DD')
    parser.add_argument('--end-date', required=True, help='End date YYYY-MM-DD')
    parser.add_argument('--lat', type=float, required=True, help='Basin center latitude')
    parser.add_argument('--lon', type=float, required=True, help='Basin center longitude')
    parser.add_argument('--dt-hours', type=float, default=1.0, help='Time step in hours')
    parser.add_argument('--shapefile', default=None, help='Basin shapefile for spatial averaging')
    parser.add_argument('--obs-file', default=None, help='Observed discharge file')
    parser.add_argument('--basin-area-km2', type=float, default=None, help='Basin area in km²')
    parser.add_argument('--output', default='inputs.dat', help='Output file path')

    args = parser.parse_args()

    # Step 1: Validate inputs
    print("=== Step 1: Validating inputs ===")
    errors = validate_inputs(args.forcing_dir, args.start_date, args.end_date, args.shapefile)
    if errors:
        for e in errors:
            print(f"  ERROR: {e}")
        print("Continuing with available data...")

    # Step 2: Extract and convert
    print("=== Step 2: Extracting basin-mean forcing ===")
    forcing_data = extract_basin_mean_forcing(
        args.forcing_dir, args.shapefile, args.start_date, args.end_date,
        lat_center=args.lat, lon_center=args.lon, source=args.source
    )

    print("=== Step 3: Converting to TOPMODEL format ===")
    nstep = convert_to_topmodel_inputs(
        forcing_data, args.dt_hours, args.lat,
        obs_file=args.obs_file, basin_area_km2=args.basin_area_km2,
        output_file=args.output
    )

    # Step 3: Validate outputs
    print("=== Step 4: Validating outputs ===")
    validate_outputs(args.output, nstep)


if __name__ == '__main__':
    main()
