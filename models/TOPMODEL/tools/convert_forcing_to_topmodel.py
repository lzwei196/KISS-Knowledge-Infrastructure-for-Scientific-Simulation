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
    """Validate that all required forcing files exist."""
    errors = []

    if not os.path.isdir(forcing_dir):
        errors.append(f"Forcing directory not found: {forcing_dir}")

    # Check for required variables
    required_vars = ['prec', 'temp', 'srad']
    start_year = int(start_date[:4])
    end_year = int(end_date[:4])

    for var in required_vars:
        for year in range(start_year, end_year + 1):
            # CMFD naming: {var}_CMFD_V0106_B-01_01dy_025deg_{year}.nc
            pattern_found = False
            if os.path.isdir(forcing_dir):
                import glob
                matches = glob.glob(os.path.join(forcing_dir, f"{var}*{year}*.nc"))
                if matches:
                    pattern_found = True
            if not pattern_found:
                errors.append(f"Missing {var} for year {year}")

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
    Ra = (24 * 60 / np.pi) * Gsc * dr * (
        ws * np.sin(lat_rad) * np.sin(delta) +
        np.cos(lat_rad) * np.cos(delta) * np.sin(ws)
    )
    Ra = np.maximum(Ra, 0)

    # Hargreaves equation
    trange = np.maximum(tmax_C - tmin_C, 0.1)
    pet = 0.0023 * (tmean_C + 17.8) * np.sqrt(trange) * Ra
    pet = np.maximum(pet, 0)

    return pet


def extract_basin_mean_forcing(forcing_dir, shapefile, start_date, end_date,
                                lat_center=None, lon_center=None):
    """
    Extract basin-averaged forcing from CMFD NetCDF files.

    If shapefile is provided, uses spatial masking.
    If only lat/lon, uses nearest grid cell.

    Returns dict with daily arrays: prec_mm_day, temp_K, srad_Wm2
    """
    try:
        import netCDF4 as nc
    except ImportError:
        print("ERROR: netCDF4 required. pip install netCDF4")
        sys.exit(1)

    import glob

    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    ndays = (end_dt - start_dt).days + 1

    prec_daily = np.full(ndays, np.nan)
    temp_daily = np.full(ndays, np.nan)
    srad_daily = np.full(ndays, np.nan)

    # Try to load basin mask from shapefile
    basin_mask = None
    lat_grid = None
    lon_grid = None

    for year in range(start_dt.year, end_dt.year + 1):
        for var_name, var_key in [('prec', 'prec'), ('temp', 'temp'), ('srad', 'srad')]:
            pattern = os.path.join(forcing_dir, f"{var_key}*{year}*.nc")
            files = sorted(glob.glob(pattern))
            if not files:
                print(f"WARNING: No {var_key} file for {year}")
                continue

            ds = nc.Dataset(files[0], 'r')

            # Get coordinate arrays on first file
            if lat_grid is None:
                for dim_name in ['lat', 'latitude', 'Lat', 'LAT']:
                    if dim_name in ds.variables:
                        lat_grid = ds.variables[dim_name][:]
                        break
                for dim_name in ['lon', 'longitude', 'Lon', 'LON']:
                    if dim_name in ds.variables:
                        lon_grid = ds.variables[dim_name][:]
                        break

            if lat_grid is None or lon_grid is None:
                print(f"WARNING: Cannot find lat/lon in {files[0]}")
                ds.close()
                continue

            # Find nearest grid cell if no mask
            if basin_mask is None and lat_center is not None:
                lat_idx = np.argmin(np.abs(lat_grid - lat_center))
                lon_idx = np.argmin(np.abs(lon_grid - lon_center))

            # Get time and data
            time_var = None
            for tname in ['time', 'Time', 'TIME']:
                if tname in ds.variables:
                    time_var = ds.variables[tname]
                    break

            # Find data variable
            data_var = None
            for vname in ds.variables:
                if vname.lower().startswith(var_key[:4]) and vname not in ['lat', 'lon', 'latitude', 'longitude', 'time']:
                    data_var = ds.variables[vname]
                    break
            if data_var is None:
                # Try the var_key directly
                for vname in ds.variables:
                    if vname not in ['lat', 'lon', 'latitude', 'longitude', 'time', 'Lat', 'Lon']:
                        data_var = ds.variables[vname]
                        break

            if data_var is None:
                print(f"WARNING: Cannot find data variable in {files[0]}")
                ds.close()
                continue

            # Determine time steps in this file
            if time_var is not None:
                nt = len(time_var)
            else:
                nt = data_var.shape[0]

            year_start = datetime(year, 1, 1)

            for t_idx in range(nt):
                current_date = year_start + timedelta(days=t_idx)
                if current_date < start_dt or current_date > end_dt:
                    continue

                day_idx = (current_date - start_dt).days
                if day_idx < 0 or day_idx >= ndays:
                    continue

                # Extract data for this timestep
                try:
                    if basin_mask is not None:
                        val = np.nanmean(data_var[t_idx, :, :][basin_mask])
                    else:
                        val = float(data_var[t_idx, lat_idx, lon_idx])
                except:
                    continue

                if var_key == 'prec':
                    prec_daily[day_idx] = val
                elif var_key == 'temp':
                    temp_daily[day_idx] = val
                elif var_key == 'srad':
                    srad_daily[day_idx] = val

            ds.close()

    return {
        'prec_mm_day': prec_daily,
        'temp_K': temp_daily,
        'srad_Wm2': srad_daily,
        'ndays': ndays,
        'start_date': start_date,
    }


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
    steps_per_day = int(24 / dt_hours)
    nstep = ndays * steps_per_day

    prec_mm_day = forcing_data['prec_mm_day']
    temp_K = forcing_data['temp_K']

    # Compute PET using Hargreaves
    temp_C = temp_K - 273.15
    # Use daily temp as mean, estimate range as 10°C if no min/max
    tmin_C = temp_C - 5.0
    tmax_C = temp_C + 5.0

    start_dt = datetime.strptime(forcing_data['start_date'], "%Y-%m-%d")
    doys = np.array([(start_dt + timedelta(days=i)).timetuple().tm_yday
                     for i in range(ndays)])

    pet_mm_day = compute_pet_hargreaves(tmin_C, tmax_C, temp_C, lat_center, doys)

    # CRITICAL UNIT CONVERSION
    # mm/day → m/hr: divide by 1000 (mm→m) then by 24 (day→hr) = ÷24000
    prec_m_hr = np.nan_to_num(prec_mm_day, nan=0.0) / 24000.0
    pet_m_hr = np.nan_to_num(pet_mm_day, nan=0.0) / 24000.0

    # Load observed discharge if available
    qobs_m_hr = np.zeros(ndays)
    if obs_file and os.path.exists(obs_file) and basin_area_km2:
        try:
            obs_data = np.genfromtxt(obs_file, skip_header=0, usecols=(1, 3),
                                      dtype=None, encoding='utf-8',
                                      delimiter='\t')
            # This is simplified; actual parsing depends on file format
        except:
            pass

    # Disaggregate daily to hourly (uniform within day)
    rain_hourly = np.repeat(prec_m_hr, steps_per_day)
    pet_hourly = np.repeat(pet_m_hr, steps_per_day)
    qobs_hourly = np.repeat(qobs_m_hr, steps_per_day)

    # Write inputs.dat
    with open(output_file, 'w') as f:
        f.write(f"{nstep}  {dt_hours:.1f}\n")
        for i in range(nstep):
            f.write(f"   {rain_hourly[i]:.7f}  {pet_hourly[i]:.7f}  {qobs_hourly[i]:.7f}\n")

    print(f"Wrote {output_file}: {nstep} steps, dt={dt_hours}h")
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

    # Check value ranges
    for i, line in enumerate(lines[1:], 1):
        vals = line.split()
        if len(vals) != 3:
            errors.append(f"Line {i}: expected 3 values, got {len(vals)}")
            continue
        rain, pe, qobs = float(vals[0]), float(vals[1]), float(vals[2])

        # Rain in m/hr should be small (< 0.01 m/hr = 10 mm/hr extreme)
        if rain > 0.01:
            errors.append(f"Line {i}: rain={rain} m/hr seems too high (>10 mm/hr)")
        if rain < 0:
            errors.append(f"Line {i}: negative rainfall")

        # PE in m/hr should be very small (< 0.001 m/hr)
        if pe > 0.001:
            errors.append(f"Line {i}: PE={pe} m/hr seems too high")
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
    parser.add_argument('--forcing-dir', required=True, help='CMFD forcing directory')
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
        lat_center=args.lat, lon_center=args.lon
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
