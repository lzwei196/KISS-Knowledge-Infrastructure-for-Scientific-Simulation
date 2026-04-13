#!/usr/bin/env python3
"""
convert_forcing_to_modflow.py — Convert climate/hydrological forcing to MODFLOW packages.

Converts global forcing datasets (CMFD, ERA5, MSWX, etc.) to MODFLOW boundary
condition arrays: recharge (RCH), evapotranspiration (EVT), river stages (RIV),
and well pumping rates (WEL).

Critical Unit Conversions:
  - Recharge: mm/day → m/day (divide by 1000!) — dt_002
  - Well pumping: L/s → m³/day (multiply by 86.4) — dt_003
  - ET: mm/day → m/day (divide by 1000) — dt_008
  - River stage: must match grid elevation datum (m ASL) — dt_006

Input:
  - Precipitation time series (CSV or NetCDF, mm/day or mm/hr)
  - ET time series (CSV or NetCDF, mm/day)
  - River discharge/stage data (CSV)
  - Well pumping schedule (CSV with dates, rates)
  - Grid metadata (from build_grid_from_dem.py)

Output:
  - Recharge arrays per stress period (nrow, ncol)
  - ET arrays per stress period (nrow, ncol)
  - River stress period data (list of [lay, row, col, stage, cond, rbot])
  - Well stress period data (list of [lay, row, col, flux])

Usage:
    python convert_forcing_to_modflow.py --precip precip.csv --et et.csv \\
        --grid_meta grid_metadata.json --output_dir ./forcing \\
        --time_unit days --length_unit meters
    python convert_forcing_to_modflow.py --precip precip_mm_day.csv \\
        --rivers rivers.csv --wells wells.csv \\
        --grid_meta grid_metadata.json --recharge_fraction 0.15
"""

import argparse
import json
import os
import sys
from datetime import datetime

import numpy as np
import pandas as pd


def validate_inputs(args):
    """Validate all inputs before processing."""
    errors = []
    warnings = []

    if not os.path.exists(args.grid_meta):
        errors.append(f"Grid metadata not found: {args.grid_meta}")

    if args.precip and not os.path.exists(args.precip):
        errors.append(f"Precipitation file not found: {args.precip}")

    if args.et and not os.path.exists(args.et):
        errors.append(f"ET file not found: {args.et}")

    if args.rivers and not os.path.exists(args.rivers):
        errors.append(f"River data not found: {args.rivers}")

    if args.wells and not os.path.exists(args.wells):
        errors.append(f"Well data not found: {args.wells}")

    if not args.precip and not args.rivers and not args.wells:
        errors.append("Must provide at least one forcing input "
                       "(--precip, --rivers, or --wells)")

    if args.recharge_fraction:
        if args.recharge_fraction <= 0 or args.recharge_fraction > 1.0:
            errors.append(
                f"Recharge fraction must be in (0, 1], "
                f"got {args.recharge_fraction}")

    os.makedirs(args.output_dir, exist_ok=True)

    if errors:
        print(json.dumps({
            "status": "error", "errors": errors, "warnings": warnings
        }))
        sys.exit(1)

    return warnings


def convert_precip_to_recharge(precip_path, grid_meta, recharge_fraction,
                                precip_unit='mm/day', length_unit='meters'):
    """
    Convert precipitation to recharge arrays.

    CRITICAL: Recharge in MODFLOW must be in model length/time units.
    If length_unit=meters and time=days, recharge must be m/day.
    Precipitation in mm/day must be divided by 1000!
    """
    df = pd.read_csv(precip_path, parse_dates=[0])
    date_col = df.columns[0]
    value_col = df.columns[1] if len(df.columns) > 1 else df.columns[0]

    precip_values = df[value_col].values.astype(float)

    # Unit conversion
    if 'mm' in precip_unit.lower():
        if length_unit == 'meters':
            # mm/day → m/day
            recharge_values = precip_values / 1000.0 * recharge_fraction
        elif length_unit == 'feet':
            # mm/day → ft/day
            recharge_values = precip_values / 304.8 * recharge_fraction
        else:
            recharge_values = precip_values / 1000.0 * recharge_fraction
    elif 'm/day' in precip_unit.lower() or 'm/d' in precip_unit.lower():
        recharge_values = precip_values * recharge_fraction
    else:
        print(f"WARNING: Unknown precip unit '{precip_unit}', "
              "assuming mm/day", file=sys.stderr)
        recharge_values = precip_values / 1000.0 * recharge_fraction

    # Sanity checks
    if np.any(recharge_values > 0.1):
        print("WARNING: Recharge > 0.1 m/day detected. "
              "Check units — likely mm/day not converted to m/day! (dt_002)",
              file=sys.stderr)
    if np.any(recharge_values < 0):
        print("WARNING: Negative recharge detected. Clipping to 0.",
              file=sys.stderr)
        recharge_values = np.maximum(recharge_values, 0.0)

    nrow = grid_meta['nrow']
    ncol = grid_meta['ncol']

    # Create spatially uniform recharge per stress period
    stress_period_data = {}
    for kper, rch_val in enumerate(recharge_values):
        stress_period_data[kper] = np.full((nrow, ncol), rch_val)

    return stress_period_data, {
        'n_periods': len(recharge_values),
        'min_recharge_m_day': float(np.min(recharge_values)),
        'max_recharge_m_day': float(np.max(recharge_values)),
        'mean_recharge_m_day': float(np.mean(recharge_values)),
        'recharge_fraction': recharge_fraction,
        'input_unit': precip_unit,
        'output_unit': f'{length_unit}/day'
    }


def convert_et_to_arrays(et_path, grid_meta, et_unit='mm/day',
                          length_unit='meters'):
    """
    Convert evapotranspiration to MODFLOW EVT arrays.

    Same unit trap as recharge: mm/day must be converted to m/day.
    """
    df = pd.read_csv(et_path, parse_dates=[0])
    value_col = df.columns[1] if len(df.columns) > 1 else df.columns[0]
    et_values = df[value_col].values.astype(float)

    if 'mm' in et_unit.lower():
        if length_unit == 'meters':
            et_values = et_values / 1000.0
        elif length_unit == 'feet':
            et_values = et_values / 304.8

    # Sanity
    if np.any(et_values > 0.02):
        print("WARNING: ET > 20 mm/day (0.02 m/day). Check values.",
              file=sys.stderr)

    nrow = grid_meta['nrow']
    ncol = grid_meta['ncol']

    stress_period_data = {}
    for kper, et_val in enumerate(et_values):
        stress_period_data[kper] = np.full((nrow, ncol), et_val)

    return stress_period_data, {
        'n_periods': len(et_values),
        'max_et_m_day': float(np.max(et_values)),
        'mean_et_m_day': float(np.mean(et_values))
    }


def convert_rivers(river_path, grid_meta):
    """
    Convert river data to MODFLOW RIV stress period data.

    River data CSV format: date, row, col, stage_m, conductance_m2_day, rbot_m
    Or: date, row, col, stage_m (conductance computed from K_bed and geometry)

    CRITICAL: River stage must be in same datum and units as model grid (dt_006).
    River bottom (rbot) must be below river stage.
    Conductance = K_bed * Length * Width / bed_thickness (dt_005).
    """
    df = pd.read_csv(river_path)

    required_cols = ['row', 'col', 'stage']
    for col in required_cols:
        if col not in df.columns:
            print(f"ERROR: Missing column '{col}' in river data",
                  file=sys.stderr)
            sys.exit(1)

    # Default layer = 0 (top layer)
    if 'layer' not in df.columns:
        df['layer'] = 0

    # Default conductance
    if 'conductance' not in df.columns:
        print("WARNING: No conductance column. Using default 100 m²/day.",
              file=sys.stderr)
        df['conductance'] = 100.0

    # Default rbot
    if 'rbot' not in df.columns:
        df['rbot'] = df['stage'] - 1.0  # 1m below stage

    # Validate: rbot must be < stage
    if np.any(df['rbot'] >= df['stage']):
        print("WARNING: River bottom >= stage in some cells. "
              "This causes numerical issues.", file=sys.stderr)

    # Group by stress period
    if 'stress_period' in df.columns:
        grouped = df.groupby('stress_period')
    else:
        grouped = {0: df}
        if isinstance(grouped, dict):
            pass
        else:
            grouped = dict(list(grouped))

    stress_period_data = {}
    for kper, group_df in (grouped.items() if isinstance(grouped, dict)
                           else grouped):
        if isinstance(group_df, pd.DataFrame):
            spd = []
            for _, r in group_df.iterrows():
                spd.append([
                    int(r['layer']), int(r['row']), int(r['col']),
                    float(r['stage']), float(r['conductance']),
                    float(r['rbot'])
                ])
            stress_period_data[kper] = spd

    return stress_period_data, {
        'n_river_cells': len(df),
        'stage_range': [float(df['stage'].min()), float(df['stage'].max())],
        'conductance_range': [float(df['conductance'].min()),
                              float(df['conductance'].max())]
    }


def convert_wells(well_path, grid_meta, time_unit='days'):
    """
    Convert well pumping data to MODFLOW WEL stress period data.

    CRITICAL UNIT TRAP (dt_003):
      - If pumping rates are in L/s: multiply by 86.4 to get m³/day
      - If pumping rates are in m³/hr: multiply by 24 to get m³/day
      - If pumping rates are in gal/min (US): multiply by 5.451 to get m³/day
      - Pumping (extraction) should be NEGATIVE in MODFLOW convention
      - Injection should be POSITIVE
    """
    df = pd.read_csv(well_path)

    required_cols = ['layer', 'row', 'col', 'flux']
    for col in required_cols:
        if col not in df.columns:
            print(f"ERROR: Missing column '{col}' in well data",
                  file=sys.stderr)
            sys.exit(1)

    # Check for common unit issues
    if 'flux_unit' in df.columns:
        unit = df['flux_unit'].iloc[0].lower()
        if 'l/s' in unit or 'lps' in unit:
            print("Converting well flux from L/s to m³/day (*86.4)",
                  file=sys.stderr)
            df['flux'] = df['flux'] * 86.4
        elif 'm3/h' in unit or 'cmh' in unit:
            print("Converting well flux from m³/hr to m³/day (*24)",
                  file=sys.stderr)
            df['flux'] = df['flux'] * 24.0
        elif 'gpm' in unit or 'gal/min' in unit:
            print("Converting well flux from gal/min to m³/day (*5.451)",
                  file=sys.stderr)
            df['flux'] = df['flux'] * 5.451

    # Ensure extraction is negative
    if np.all(df['flux'] > 0):
        print("WARNING: All well fluxes are positive. "
              "In MODFLOW, extraction = negative. Negating values.",
              file=sys.stderr)
        df['flux'] = -df['flux']

    # Group by stress period
    if 'stress_period' in df.columns:
        grouped = df.groupby('stress_period')
    else:
        grouped = {0: df}
        if isinstance(grouped, dict):
            pass

    stress_period_data = {}
    for kper, group_df in (grouped.items() if isinstance(grouped, dict)
                           else grouped):
        if isinstance(group_df, pd.DataFrame):
            spd = []
            for _, r in group_df.iterrows():
                spd.append([
                    int(r['layer']), int(r['row']), int(r['col']),
                    float(r['flux'])
                ])
            stress_period_data[kper] = spd

    return stress_period_data, {
        'n_wells': len(df[['layer', 'row', 'col']].drop_duplicates()),
        'total_extraction_m3_day': float(df['flux'].sum()),
        'flux_range': [float(df['flux'].min()), float(df['flux'].max())]
    }


def process(args, warnings_list):
    """Main processing: forcing data → MODFLOW boundary conditions."""
    with open(args.grid_meta) as f:
        grid_meta = json.load(f)

    results = {'warnings': warnings_list}

    # Recharge from precipitation
    if args.precip:
        rch_fraction = args.recharge_fraction or 0.15
        rch_data, rch_meta = convert_precip_to_recharge(
            args.precip, grid_meta, rch_fraction,
            precip_unit=args.precip_unit or 'mm/day',
            length_unit=args.length_unit or 'meters')

        # Save recharge arrays
        for kper, arr in rch_data.items():
            np.save(os.path.join(args.output_dir, f'rch_sp{kper}.npy'), arr)

        results['recharge'] = rch_meta
        print(f"Recharge: {rch_meta['n_periods']} periods, "
              f"mean={rch_meta['mean_recharge_m_day']:.6f} m/day",
              file=sys.stderr)

    # ET
    if args.et:
        et_data, et_meta = convert_et_to_arrays(
            args.et, grid_meta,
            et_unit=args.et_unit or 'mm/day',
            length_unit=args.length_unit or 'meters')
        for kper, arr in et_data.items():
            np.save(os.path.join(args.output_dir, f'et_sp{kper}.npy'), arr)
        results['et'] = et_meta

    # Rivers
    if args.rivers:
        riv_data, riv_meta = convert_rivers(args.rivers, grid_meta)
        riv_path = os.path.join(args.output_dir, 'riv_stress_period_data.json')
        # Convert numpy types for JSON serialization
        with open(riv_path, 'w') as f:
            json.dump({str(k): v for k, v in riv_data.items()}, f, indent=2)
        results['rivers'] = riv_meta

    # Wells
    if args.wells:
        wel_data, wel_meta = convert_wells(
            args.wells, grid_meta, time_unit=args.time_unit or 'days')
        wel_path = os.path.join(args.output_dir, 'wel_stress_period_data.json')
        with open(wel_path, 'w') as f:
            json.dump({str(k): v for k, v in wel_data.items()}, f, indent=2)
        results['wells'] = wel_meta

    # Save metadata
    meta_path = os.path.join(args.output_dir, 'forcing_metadata.json')
    with open(meta_path, 'w') as f:
        json.dump(results, f, indent=2)

    return results


def validate_outputs(results, output_dir):
    """Post-processing validation."""
    errors = []
    warnings = []

    if 'recharge' in results:
        rch = results['recharge']
        if rch['max_recharge_m_day'] > 0.1:
            warnings.append(
                f"Max recharge = {rch['max_recharge_m_day']:.4f} m/day "
                f"= {rch['max_recharge_m_day']*1000:.1f} mm/day — "
                "verify units (dt_002)")
        if rch['max_recharge_m_day'] > 1.0:
            errors.append(
                f"Recharge {rch['max_recharge_m_day']:.2f} m/day is "
                "unrealistic (>1000 mm/day). Likely mm not converted to m.")
        if rch['mean_recharge_m_day'] < 1e-6:
            warnings.append("Mean recharge is near zero — check input data")

    if 'wells' in results:
        wel = results['wells']
        if wel['total_extraction_m3_day'] > 0:
            warnings.append(
                "Total well flux is positive — "
                "extraction should be negative in MODFLOW (dt_003)")

    result = {
        "status": "error" if errors else "ok",
        "errors": errors,
        "warnings": warnings
    }
    print(json.dumps(result, indent=2))
    return len(errors) == 0


def main():
    parser = argparse.ArgumentParser(
        description='Convert forcing data to MODFLOW boundary conditions')
    parser.add_argument('--grid_meta', required=True)
    parser.add_argument('--precip', default=None,
                        help='Precipitation CSV (date, value)')
    parser.add_argument('--et', default=None,
                        help='Evapotranspiration CSV (date, value)')
    parser.add_argument('--rivers', default=None,
                        help='River data CSV')
    parser.add_argument('--wells', default=None,
                        help='Well pumping data CSV')
    parser.add_argument('--recharge_fraction', type=float, default=0.15,
                        help='Fraction of precipitation becoming recharge')
    parser.add_argument('--precip_unit', default='mm/day',
                        help='Precipitation input unit')
    parser.add_argument('--et_unit', default='mm/day',
                        help='ET input unit')
    parser.add_argument('--length_unit', default='meters',
                        help='Model length unit')
    parser.add_argument('--time_unit', default='days',
                        help='Model time unit')
    parser.add_argument('--output_dir', default='./forcing')
    args = parser.parse_args()

    warnings_list = validate_inputs(args)
    results = process(args, warnings_list)
    validate_outputs(results, args.output_dir)


if __name__ == '__main__':
    main()
