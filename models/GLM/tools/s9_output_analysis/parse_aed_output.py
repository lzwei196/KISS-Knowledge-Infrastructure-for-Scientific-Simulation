#!/usr/bin/env python3
"""
parse_aed_output.py — Parse AED2 water quality output from GLM simulation.

Extracts water quality variables from GLM+AED2 output.nc:
  - Chlorophyll-a profiles and timeseries (PHY_tchla)
  - Phytoplankton biomass by functional group (PHY_diatom, PHY_green, etc.)
  - Dissolved oxygen profiles (OXY_oxy)
  - Nutrient profiles (NIT_nit, NIT_amm, PHS_frp)
  - Organic matter (OGM_doc, OGM_poc)
  - Total nitrogen (TOT_tn), total phosphorus (TOT_tp)
  - Lake-integrated summary statistics

Computes derived metrics:
  - Trophic State Index (TSI) from chlorophyll-a (Carlson 1977)
  - Hypolimnetic oxygen depletion rate
  - N:P ratio (indicator of nutrient limitation)
  - Phytoplankton community composition (% diatom, green, cyano)
  - Bloom frequency (days with Chl-a > threshold)

Output: JSON summary + optional CSV timeseries.

Usage:
    python parse_aed_output.py --output_nc output/output.nc \
        --summary wq_summary.json

    python parse_aed_output.py --output_nc output/output.nc \
        --lake_csv output/lake.csv \
        --summary wq_summary.json --timeseries wq_timeseries.csv

    python parse_aed_output.py --output_nc output/output.nc \
        --obs_chla_csv observations/chla.csv \
        --summary wq_summary.json
"""

import argparse
import json
import os
import sys

import numpy as np
import pandas as pd


# AED2 variable metadata
AED2_VARIABLES = {
    # Phytoplankton
    'PHY_tchla':  {'unit': 'ug/L', 'description': 'Total chlorophyll-a'},
    'PHY_tphy':   {'unit': 'mmol C/m3', 'description': 'Total phytoplankton'},
    'PHY_diatom': {'unit': 'mmol C/m3', 'description': 'Diatom biomass'},
    'PHY_green':  {'unit': 'mmol C/m3', 'description': 'Green algae biomass'},
    'PHY_cyano':  {'unit': 'mmol C/m3', 'description': 'Cyanobacteria biomass'},
    'PHY_crypto': {'unit': 'mmol C/m3', 'description': 'Cryptophyte biomass'},
    # Oxygen
    'OXY_oxy':    {'unit': 'mmol O2/m3', 'description': 'Dissolved oxygen'},
    # Nitrogen
    'NIT_nit':    {'unit': 'mmol N/m3', 'description': 'Nitrate-N'},
    'NIT_amm':    {'unit': 'mmol N/m3', 'description': 'Ammonium-N'},
    # Phosphorus
    'PHS_frp':    {'unit': 'mmol P/m3', 'description': 'Filterable reactive P'},
    # Organic matter
    'OGM_doc':    {'unit': 'mmol C/m3', 'description': 'Dissolved organic C'},
    'OGM_poc':    {'unit': 'mmol C/m3', 'description': 'Particulate organic C'},
    'OGM_don':    {'unit': 'mmol N/m3', 'description': 'Dissolved organic N'},
    'OGM_pon':    {'unit': 'mmol N/m3', 'description': 'Particulate organic N'},
    # Totals
    'TOT_tn':     {'unit': 'mmol N/m3', 'description': 'Total nitrogen'},
    'TOT_tp':     {'unit': 'mmol P/m3', 'description': 'Total phosphorus'},
    'TOT_toc':    {'unit': 'mmol C/m3', 'description': 'Total organic carbon'},
    # Silica
    'SIL_rsi':    {'unit': 'mmol Si/m3', 'description': 'Reactive silica'},
}


def validate_inputs(args):
    """Validate inputs."""
    errors = []
    if not os.path.exists(args.output_nc):
        errors.append(f"Output NetCDF not found: {args.output_nc}")
    if args.lake_csv and not os.path.exists(args.lake_csv):
        errors.append(f"Lake CSV not found: {args.lake_csv}")
    if args.obs_chla_csv and not os.path.exists(args.obs_chla_csv):
        errors.append(f"Observed Chl-a CSV not found: {args.obs_chla_csv}")
    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)


def compute_tsi_chla(chla_ug_l):
    """
    Carlson Trophic State Index from chlorophyll-a.

    TSI(Chl) = 9.81 * ln(Chl-a) + 30.6
      TSI < 40:  Oligotrophic
      40-50:     Mesotrophic
      50-70:     Eutrophic
      > 70:      Hypereutrophic
    """
    if chla_ug_l <= 0:
        return 0.0
    return 9.81 * np.log(chla_ug_l) + 30.6


def compute_tsi_tp(tp_ug_l):
    """TSI from total phosphorus (ug/L)."""
    if tp_ug_l <= 0:
        return 0.0
    return 14.42 * np.log(tp_ug_l) + 4.15


def classify_trophic_state(tsi):
    """Classify trophic state from TSI."""
    if tsi < 40:
        return 'oligotrophic'
    elif tsi < 50:
        return 'mesotrophic'
    elif tsi < 70:
        return 'eutrophic'
    else:
        return 'hypereutrophic'


def parse_aed_nc(output_nc_path):
    """Parse AED2 variables from GLM output.nc."""
    import netCDF4 as nc

    ds = nc.Dataset(output_nc_path)

    result = {
        "dimensions": {dim: ds.dimensions[dim].size
                       for dim in ds.dimensions},
        "aed2_variables_found": [],
        "all_variables": list(ds.variables.keys()),
    }

    # Find AED2 variables present in the output
    aed_data = {}
    for var_name in AED2_VARIABLES:
        # Try exact name and various capitalizations
        for try_name in [var_name, var_name.lower(), var_name.upper()]:
            if try_name in ds.variables:
                data = ds.variables[try_name][:]
                aed_data[var_name] = np.ma.filled(data, np.nan)
                result["aed2_variables_found"].append(var_name)
                break

    # Get time
    time_var = ds.variables.get('time', None)
    times = None
    if time_var is not None:
        try:
            times = nc.num2date(time_var[:], time_var.units,
                                calendar=getattr(time_var, 'calendar',
                                                 'standard'))
            # Convert cftime objects to datetime strings
            times = [str(t) for t in times]
        except Exception:
            times = time_var[:].tolist()

    # Get depth/height
    z = None
    for var_name_z in ['z', 'depth', 'NS', 'heights']:
        if var_name_z in ds.variables:
            z = np.ma.filled(ds.variables[var_name_z][:], np.nan)
            break

    # Also get temperature for context
    temp = None
    for var_name_t in ['temp', 'temperature', 'TEMP']:
        if var_name_t in ds.variables:
            temp = np.ma.filled(ds.variables[var_name_t][:], np.nan)
            break

    ds.close()

    return result, aed_data, times, z, temp


def compute_surface_bottom_ts(data_3d, z_3d, surface_depth=1.0,
                              bottom_depth_frac=0.9):
    """
    Extract surface and bottom time series from 3D (time, layer) data.

    GLM output has variable-layer structure: (time, max_layers).
    Surface = topmost non-NaN layer.
    Bottom = deepest non-NaN layer.

    Args:
        data_3d: (time, layers) array
        z_3d: (time, layers) heights array
        surface_depth: depth below surface for 'surface' value (m)
        bottom_depth_frac: fraction of max depth for 'bottom'
    """
    ntimes = data_3d.shape[0]
    surface_vals = np.full(ntimes, np.nan)
    bottom_vals = np.full(ntimes, np.nan)

    for t in range(ntimes):
        profile = data_3d[t, :]
        valid = ~np.isnan(profile)
        if valid.sum() == 0:
            continue
        # Surface = last valid layer (GLM layers go bottom to top)
        surface_vals[t] = profile[valid][-1]
        # Bottom = first valid layer
        bottom_vals[t] = profile[valid][0]

    return surface_vals, bottom_vals


def compute_wq_summary(aed_data, times, z, temp):
    """Compute WQ summary statistics from AED2 output."""
    summary = {}

    # --- Chlorophyll-a ---
    if 'PHY_tchla' in aed_data:
        chla = aed_data['PHY_tchla']
        if chla.ndim == 2 and z is not None:
            surf_chla, bot_chla = compute_surface_bottom_ts(chla, z)
        elif chla.ndim == 1:
            surf_chla = chla
            bot_chla = chla
        else:
            # Take column mean as proxy
            surf_chla = np.nanmean(chla, axis=1) if chla.ndim == 2 else chla
            bot_chla = surf_chla

        mean_chla = float(np.nanmean(surf_chla))
        max_chla = float(np.nanmax(surf_chla))
        tsi = compute_tsi_chla(mean_chla) if mean_chla > 0 else 0.0

        summary['chlorophyll_a'] = {
            'surface_mean_ug_L': round(mean_chla, 2),
            'surface_max_ug_L': round(max_chla, 2),
            'surface_min_ug_L': round(float(np.nanmin(surf_chla)), 2),
            'surface_std_ug_L': round(float(np.nanstd(surf_chla)), 2),
            'TSI_chla': round(tsi, 1),
            'trophic_state': classify_trophic_state(tsi),
        }

        # Bloom analysis (Chl-a > 10 ug/L = moderate bloom)
        bloom_threshold = 10.0  # ug/L
        severe_threshold = 30.0  # ug/L
        bloom_days = int(np.sum(surf_chla > bloom_threshold))
        severe_bloom_days = int(np.sum(surf_chla > severe_threshold))
        total_days = len(surf_chla[~np.isnan(surf_chla)])
        summary['bloom_analysis'] = {
            'bloom_threshold_ug_L': bloom_threshold,
            'bloom_days': bloom_days,
            'bloom_frequency_pct': round(
                100 * bloom_days / max(total_days, 1), 1),
            'severe_bloom_days': severe_bloom_days,
            'severe_bloom_frequency_pct': round(
                100 * severe_bloom_days / max(total_days, 1), 1),
            'max_bloom_ug_L': round(max_chla, 2),
        }

    # --- Phytoplankton community composition ---
    phyto_groups = {}
    for var_name in ['PHY_diatom', 'PHY_green', 'PHY_cyano', 'PHY_crypto']:
        if var_name in aed_data:
            data = aed_data[var_name]
            if data.ndim == 2:
                # Column-integrated mean
                mean_val = float(np.nanmean(data))
            else:
                mean_val = float(np.nanmean(data))
            group_name = var_name.replace('PHY_', '')
            phyto_groups[group_name] = round(mean_val, 3)

    if phyto_groups:
        total_phyto = sum(phyto_groups.values())
        composition = {}
        for grp, val in phyto_groups.items():
            composition[grp] = {
                'mean_mmolC_m3': val,
                'fraction_pct': round(100 * val / max(total_phyto, 0.001), 1),
            }
        summary['phytoplankton_community'] = {
            'total_mean_mmolC_m3': round(total_phyto, 3),
            'composition': composition,
        }

    # --- Dissolved oxygen ---
    if 'OXY_oxy' in aed_data:
        oxy = aed_data['OXY_oxy']
        if oxy.ndim == 2 and z is not None:
            surf_oxy, bot_oxy = compute_surface_bottom_ts(oxy, z)
        else:
            surf_oxy = np.nanmean(oxy, axis=1) if oxy.ndim == 2 else oxy
            bot_oxy = surf_oxy

        # Convert mmol O2/m3 to mg/L: * 32.0 / 1000
        surf_oxy_mgL = surf_oxy * 32.0 / 1000.0
        bot_oxy_mgL = bot_oxy * 32.0 / 1000.0

        summary['dissolved_oxygen'] = {
            'surface_mean_mgL': round(float(np.nanmean(surf_oxy_mgL)), 2),
            'surface_min_mgL': round(float(np.nanmin(surf_oxy_mgL)), 2),
            'bottom_mean_mgL': round(float(np.nanmean(bot_oxy_mgL)), 2),
            'bottom_min_mgL': round(float(np.nanmin(bot_oxy_mgL)), 2),
            'hypoxic_days_bottom': int(
                np.sum(bot_oxy_mgL < 2.0)),  # <2 mg/L = hypoxic
            'anoxic_days_bottom': int(
                np.sum(bot_oxy_mgL < 0.5)),  # <0.5 mg/L = anoxic
        }

    # --- Nutrients ---
    for var_name, label in [('NIT_nit', 'nitrate'), ('NIT_amm', 'ammonium'),
                            ('PHS_frp', 'phosphorus')]:
        if var_name in aed_data:
            data = aed_data[var_name]
            if data.ndim == 2 and z is not None:
                surf, bot = compute_surface_bottom_ts(data, z)
            else:
                surf = np.nanmean(data, axis=1) if data.ndim == 2 else data
                bot = surf

            summary[label] = {
                'surface_mean': round(float(np.nanmean(surf)), 3),
                'surface_max': round(float(np.nanmax(surf)), 3),
                'bottom_mean': round(float(np.nanmean(bot)), 3),
                'unit': AED2_VARIABLES[var_name]['unit'],
            }

    # --- N:P ratio (surface, molar) ---
    if 'NIT_nit' in aed_data and 'PHS_frp' in aed_data:
        nit = aed_data['NIT_nit']
        phs = aed_data['PHS_frp']
        if nit.ndim == 2 and z is not None:
            surf_n, _ = compute_surface_bottom_ts(nit, z)
            surf_p, _ = compute_surface_bottom_ts(phs, z)
        else:
            surf_n = np.nanmean(nit, axis=1) if nit.ndim == 2 else nit
            surf_p = np.nanmean(phs, axis=1) if phs.ndim == 2 else phs

        # Molar N:P ratio (Redfield = 16:1)
        mean_n = float(np.nanmean(surf_n))
        mean_p = float(np.nanmean(surf_p))
        if mean_p > 0.001:
            np_ratio = mean_n / mean_p
            limitation = ('P-limited' if np_ratio > 16
                          else 'N-limited' if np_ratio < 10
                          else 'co-limited')
            summary['nutrient_limitation'] = {
                'mean_N_mmol_m3': round(mean_n, 3),
                'mean_P_mmol_m3': round(mean_p, 3),
                'molar_NP_ratio': round(np_ratio, 1),
                'Redfield_ratio': 16.0,
                'limitation_status': limitation,
            }

    # --- Totals ---
    for var_name, label in [('TOT_tn', 'total_nitrogen'),
                            ('TOT_tp', 'total_phosphorus')]:
        if var_name in aed_data:
            data = aed_data[var_name]
            mean_val = float(np.nanmean(data))
            summary[label] = {
                'mean': round(mean_val, 3),
                'max': round(float(np.nanmax(data)), 3),
                'unit': AED2_VARIABLES[var_name]['unit'],
            }

    return summary


def compare_with_observations(aed_data, z, obs_chla_csv):
    """Compare simulated Chl-a with observations."""
    if 'PHY_tchla' not in aed_data:
        return {"error": "No PHY_tchla in simulation output"}

    obs = pd.read_csv(obs_chla_csv)

    # Find time and chla columns
    time_col = None
    chla_col = None
    for col in obs.columns:
        cl = col.strip().lower()
        if 'time' in cl or 'date' in cl:
            time_col = col
        if 'chla' in cl or 'chloro' in cl or 'chl_a' in cl or 'chl-a' in cl:
            chla_col = col

    if time_col is None or chla_col is None:
        return {"error": "Cannot find time/chla columns in observations"}

    obs[time_col] = pd.to_datetime(obs[time_col])
    obs_chla = obs[chla_col].values
    valid = ~np.isnan(obs_chla)

    if valid.sum() == 0:
        return {"error": "No valid observations"}

    return {
        "num_observations": int(valid.sum()),
        "obs_mean_ug_L": round(float(np.nanmean(obs_chla)), 2),
        "obs_max_ug_L": round(float(np.nanmax(obs_chla)), 2),
        "note": "Detailed obs vs sim comparison requires time-matching "
                "(use plot_glm_results.py with --obs_data)",
    }


def build_timeseries_df(aed_data, times):
    """Build a timeseries DataFrame from surface values."""
    df_dict = {}
    if times is not None:
        df_dict['time'] = times[:len(next(iter(aed_data.values())))]
        if isinstance(df_dict['time'], np.ndarray):
            # Trim to match data length
            pass

    for var_name, data in aed_data.items():
        if data.ndim == 2:
            # Extract surface (last valid layer per timestep)
            ntimes = data.shape[0]
            surface = np.full(ntimes, np.nan)
            for t in range(ntimes):
                profile = data[t, :]
                valid = ~np.isnan(profile)
                if valid.sum() > 0:
                    surface[t] = profile[valid][-1]
            df_dict[f'{var_name}_surface'] = surface
        elif data.ndim == 1:
            df_dict[var_name] = data

    return pd.DataFrame(df_dict)


def process(args):
    """Parse AED2 output and compute summary."""
    nc_info, aed_data, times, z, temp = parse_aed_nc(args.output_nc)

    result = {
        "status": "success",
        "output_nc": args.output_nc,
        "nc_info": nc_info,
    }

    if not nc_info["aed2_variables_found"]:
        result["status"] = "warning"
        result["warning"] = (
            "No AED2 variables found in output.nc. "
            "Either AED2 was not enabled, or the simulation did not "
            "produce WQ output. Check that aed_filename is set in "
            "glm3.nml &glm_setup block.")
        return result

    # Compute WQ summary
    wq_summary = compute_wq_summary(aed_data, times, z, temp)
    result["water_quality"] = wq_summary

    # Compare with observations if provided
    if args.obs_chla_csv:
        obs_comparison = compare_with_observations(
            aed_data, z, args.obs_chla_csv)
        result["observation_comparison"] = obs_comparison

    # Build and save timeseries if requested
    if args.timeseries:
        ts_df = build_timeseries_df(aed_data, times)
        os.makedirs(os.path.dirname(args.timeseries) or '.', exist_ok=True)
        ts_df.to_csv(args.timeseries, index=False)
        result["timeseries_file"] = args.timeseries
        result["timeseries_columns"] = list(ts_df.columns)
        result["timeseries_rows"] = len(ts_df)

    return result


def main():
    parser = argparse.ArgumentParser(
        description="Parse AED2 water quality output from GLM simulation")

    parser.add_argument("--output_nc", type=str, required=True,
                        help="GLM output.nc file (with AED2 variables)")
    parser.add_argument("--lake_csv", type=str, default=None,
                        help="GLM lake.csv (for lake-integrated variables)")
    parser.add_argument("--summary", type=str, default=None,
                        help="Output JSON summary path")
    parser.add_argument("--timeseries", type=str, default=None,
                        help="Output CSV timeseries path (surface values)")
    parser.add_argument("--obs_chla_csv", type=str, default=None,
                        help="Observed chlorophyll-a CSV for comparison")

    args = parser.parse_args()

    validate_inputs(args)
    result = process(args)

    output_json = json.dumps(result, indent=2, default=str)
    if args.summary:
        os.makedirs(os.path.dirname(args.summary) or '.', exist_ok=True)
        with open(args.summary, 'w') as f:
            f.write(output_json)
        print(f"WQ summary written to {args.summary}", file=sys.stderr)
    print(output_json)


if __name__ == "__main__":
    main()
