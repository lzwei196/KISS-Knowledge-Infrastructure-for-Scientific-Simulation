#!/usr/bin/env python3
"""
Convert CMFD/MSWX 3-hourly forcing to HYPE daily Pobs.txt + Tobs.txt.

CRITICAL UNIT CONVERSIONS:
- Precipitation: SUM 8 timesteps (NOT average!) to get mm/day
- Temperature: MEAN 8 timesteps
- CMFD temperature: K -> C (subtract 273.15)
- MSWX temperature: already in C

Usage:
    python convert_forcing_to_hype.py \
        --forcing_dir data/forcing/Data_forcing_03hr_010deg/ \
        --subbasins outputs/hype_run/subbasins/subbasins.shp \
        --output outputs/hype_run/forcingdir/ \
        --start_year 2005 --end_year 2010 \
        --source cmfd
"""

import argparse
import sys
import os
import warnings
warnings.filterwarnings('ignore')

sys.path.insert(0, "KISSPATH_INTERNAL_NOT_SHIPPED/auto_dissect")
from ki_tools_common.units import kelvin_to_celsius

import numpy as np
import xarray as xr
import geopandas as gpd
from datetime import datetime, timedelta
from pathlib import Path


def find_nearest_grid_cell(lat, lon, lats, lons):
    """Find the nearest grid cell index for a given lat/lon."""
    lat_idx = np.argmin(np.abs(lats - lat))
    lon_idx = np.argmin(np.abs(lons - lon))
    return lat_idx, lon_idx


def aggregate_3hourly_to_daily(data_3h, variable):
    """
    Aggregate 3-hourly data to daily.

    CRITICAL:
    - Precipitation: SUM (not mean!)
    - Temperature: MEAN
    - Other variables: MEAN
    """
    n_days = len(data_3h) // 8
    data_daily = np.zeros(n_days)

    for d in range(n_days):
        day_data = data_3h[d * 8:(d + 1) * 8]
        valid = ~np.isnan(day_data)

        if not np.any(valid):
            data_daily[d] = -9999  # missing
        elif variable in ['prec', 'precipitation', 'Prec', 'PREC']:
            # CRITICAL: SUM for precipitation (mm/3hr -> mm/day)
            data_daily[d] = np.nansum(day_data)
        else:
            # MEAN for temperature and other variables
            data_daily[d] = np.nanmean(day_data)

    return data_daily


def convert_cmfd_to_hype(forcing_dir, subbasins, output_dir, start_year, end_year):
    """Convert CMFD 3-hourly forcing to HYPE daily format."""
    forcing_dir = Path(forcing_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Get subbasin centroids for spatial extraction
    sub_gdf = gpd.read_file(subbasins)
    subids = []
    lats = []
    lons = []

    for _, row in sub_gdf.iterrows():
        subid = row.get('SUBID', row.name + 1)
        centroid = row.geometry.centroid
        subids.append(subid)
        lats.append(centroid.y)
        lons.append(centroid.x)

    print(f"Processing {len(subids)} subbasins, {start_year}-{end_year}")

    # Collect daily data
    all_dates = []
    all_prec = {sid: [] for sid in subids}
    all_temp = {sid: [] for sid in subids}

    for year in range(start_year, end_year + 1):
        for month in range(1, 13):
            # CMFD stores variables in subdirectories: Prec/, Temp/, etc.
            # Search both top-level and subdirectories
            prec_pattern_top = f"*prec*{year}{month:02d}*"
            temp_pattern_top = f"*temp*{year}{month:02d}*"

            prec_files = sorted(forcing_dir.glob(prec_pattern_top))
            temp_files = sorted(forcing_dir.glob(temp_pattern_top))

            # If not found at top level, search in Prec/ and Temp/ subdirs
            if not prec_files:
                for subdir in ['Prec', 'prec', 'PREC']:
                    prec_files = sorted((forcing_dir / subdir).glob(f"*{year}{month:02d}*")) if (forcing_dir / subdir).exists() else []
                    if prec_files:
                        break
            if not temp_files:
                for subdir in ['Temp', 'temp', 'TEMP']:
                    temp_files = sorted((forcing_dir / subdir).glob(f"*{year}{month:02d}*")) if (forcing_dir / subdir).exists() else []
                    if temp_files:
                        break

            if not prec_files or not temp_files:
                print(f"  Warning: No forcing files for {year}-{month:02d}")
                continue

            # Read and extract per subbasin
            for prec_file, temp_file in zip(prec_files, temp_files):
                try:
                    ds_p = xr.open_dataset(prec_file)
                    ds_t = xr.open_dataset(temp_file)

                    # Get coordinate arrays
                    grid_lats = ds_p['lat'].values if 'lat' in ds_p else ds_p['latitude'].values
                    grid_lons = ds_p['lon'].values if 'lon' in ds_p else ds_p['longitude'].values

                    # Get time dimension
                    times = ds_p['time'].values if 'time' in ds_p else None

                    for i, (sid, slat, slon) in enumerate(zip(subids, lats, lons)):
                        lat_idx, lon_idx = find_nearest_grid_cell(slat, slon, grid_lats, grid_lons)

                        # Extract 3-hourly data
                        prec_var = [v for v in ds_p.data_vars if 'prec' in v.lower()][0]
                        temp_var = [v for v in ds_t.data_vars if 'temp' in v.lower() or 'tmp' in v.lower()][0]

                        prec_3h = ds_p[prec_var][:, lat_idx, lon_idx].values
                        temp_3h = ds_t[temp_var][:, lat_idx, lon_idx].values

                        # CMFD precip is kg/m^2/s (mm/s). Auto-detect by units
                        # attribute or magnitude and convert to mm/3hr (x10800 s)
                        # before the daily SUM. See diagnostics triplet dt_u03.
                        prec_units = str(ds_p[prec_var].attrs.get('units', '')).lower()
                        if ('s-1' in prec_units or 's^-1' in prec_units
                                or 'kg m-2 s' in prec_units
                                or np.nanmean(prec_3h) < 0.01):
                            prec_3h = prec_3h * 10800.0

                        # CMFD temperature is in Kelvin -> convert to Celsius
                        temp_3h = kelvin_to_celsius(temp_3h)

                        # Aggregate to daily
                        prec_daily = aggregate_3hourly_to_daily(prec_3h, 'prec')
                        temp_daily = aggregate_3hourly_to_daily(temp_3h, 'temp')

                        all_prec[sid].extend(prec_daily)
                        all_temp[sid].extend(temp_daily)

                    # Generate dates
                    n_days_in_month = len(all_prec[subids[0]]) - len(all_dates)
                    base_date = datetime(year, month, 1)
                    for d in range(n_days_in_month):
                        all_dates.append(base_date + timedelta(days=d))

                    ds_p.close()
                    ds_t.close()

                except Exception as e:
                    print(f"  Error processing {prec_file}: {e}")

        print(f"  Year {year} processed")

    # Write Pobs.txt
    _write_hype_obs_file(output_dir / 'Pobs.txt', subids, all_dates, all_prec, 1)

    # Write Tobs.txt
    _write_hype_obs_file(output_dir / 'Tobs.txt', subids, all_dates, all_temp, 1)

    # Write ForcKey.txt
    with open(output_dir / 'ForcKey.txt', 'w') as f:
        f.write('SUBID\tFORSSESSION\n')
        for sid in subids:
            f.write(f'{sid}\t{sid}\n')

    print(f"\nOutput files:")
    print(f"  {output_dir / 'Pobs.txt'} ({len(all_dates)} days)")
    print(f"  {output_dir / 'Tobs.txt'} ({len(all_dates)} days)")
    print(f"  {output_dir / 'ForcKey.txt'} ({len(subids)} subbasins)")


def _write_hype_obs_file(filepath, subids, dates, data, decimals):
    """Write a HYPE observation file (Pobs.txt or Tobs.txt)."""
    with open(filepath, 'w') as f:
        # Header
        header = 'DATE\t' + '\t'.join(str(sid) for sid in subids)
        f.write(header + '\n')

        # Data
        for d, date in enumerate(dates):
            values = []
            for sid in subids:
                if d < len(data[sid]):
                    val = data[sid][d]
                    if val == -9999 or np.isnan(val):
                        values.append('-9999')
                    else:
                        values.append(f'{val:.{decimals}f}')
                else:
                    values.append('-9999')

            f.write(f'{date.strftime("%Y-%m-%d")}\t' + '\t'.join(values) + '\n')


def main():
    parser = argparse.ArgumentParser(description='Convert forcing to HYPE format')
    parser.add_argument('--forcing_dir', required=True, help='CMFD/MSWX forcing directory')
    parser.add_argument('--subbasins', required=True, help='Subbasin shapefile')
    parser.add_argument('--output', required=True, help='Output forcing directory')
    parser.add_argument('--start_year', type=int, required=True)
    parser.add_argument('--end_year', type=int, required=True)
    parser.add_argument('--source', choices=['cmfd', 'mswx'], default='cmfd',
                       help='Forcing data source')

    args = parser.parse_args()

    convert_cmfd_to_hype(
        args.forcing_dir, args.subbasins, args.output,
        args.start_year, args.end_year
    )


if __name__ == '__main__':
    main()
