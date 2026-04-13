#!/usr/bin/env python3
"""
generate_glm_nml.py — Generate glm3.nml namelist file from lake parameters.

Assembles all 13 namelist blocks from upstream tool outputs (morphometry.json,
init_profiles.json, outflow_config.json, etc.) into a valid Fortran namelist.

CRITICAL Fortran namelist format rules:
  - Strings must be SINGLE-quoted (not double-quoted)
  - Booleans must be .true. or .false.
  - Arrays are comma-separated
  - Each block starts with &block_name and ends with /
  - bsn_vals must exactly match the length of H[] and A[] arrays

Usage:
    python generate_glm_nml.py \
        --morphometry morphometry.json \
        --init_profiles init_profiles.json \
        --met_csv bcs/met_hourly.csv \
        --start_date "2000-01-01 00:00:00" \
        --end_date "2010-12-31 23:00:00" \
        --output glm3.nml

    python generate_glm_nml.py \
        --morphometry morphometry.json \
        --init_profiles init_profiles.json \
        --met_csv bcs/met_hourly.csv \
        --inflow_csv bcs/inflow_1.csv \
        --outflow_config outflow_config.json \
        --start_date "2000-01-01" --end_date "2010-12-31" \
        --timezone 8 --output glm3.nml
"""

import argparse
import json
import math
import os
import sys


def validate_inputs(args):
    """Validate inputs."""
    errors = []
    if not os.path.exists(args.morphometry):
        errors.append(f"Morphometry file not found: {args.morphometry}")
    if args.init_profiles and not os.path.exists(args.init_profiles):
        errors.append(f"Init profiles file not found: {args.init_profiles}")
    if args.outflow_config and not os.path.exists(args.outflow_config):
        errors.append(f"Outflow config not found: {args.outflow_config}")
    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)


def fmt_bool(val):
    """Format boolean for Fortran namelist."""
    return '.true.' if val else '.false.'


def fmt_str(val):
    """Format string for Fortran namelist. MUST use single quotes."""
    return f"'{val}'"


def fmt_arr(vals, fmt='{}'):
    """Format array for Fortran namelist."""
    return ', '.join(fmt.format(v) for v in vals)


def sed_temp_mean_from_lat(lat):
    """Estimate mean annual sediment temperature from latitude."""
    abs_lat = abs(lat)
    if abs_lat < 23:
        return 22.0  # Tropical
    elif abs_lat < 35:
        return 15.0  # Subtropical
    elif abs_lat < 50:
        return 8.0   # Temperate
    elif abs_lat < 60:
        return 5.0   # Boreal
    else:
        return 3.0   # Arctic


def sed_temp_amplitude_from_lat(lat):
    """Estimate sediment temperature amplitude from latitude."""
    abs_lat = abs(lat)
    if abs_lat < 23:
        return 2.0
    elif abs_lat < 35:
        return 5.0
    elif abs_lat < 50:
        return 8.0
    else:
        return 6.0


def process(args):
    """Generate glm3.nml content."""
    # Load morphometry
    with open(args.morphometry) as f:
        morph = json.load(f)

    # Load init profiles
    if args.init_profiles and os.path.exists(args.init_profiles):
        with open(args.init_profiles) as f:
            init_prof = json.load(f)
    else:
        depth = morph['H'][-1] - morph['H'][0]
        init_prof = {
            "lake_depth": depth,
            "num_depths": 3,
            "the_depths": [0.0, depth / 2, depth],
            "the_temps": [10.0, 6.0, 4.0],
            "the_sals": [0.0, 0.0, 0.0],
            "num_wq_vars": 0,
        }

    # Load outflow config
    if args.outflow_config and os.path.exists(args.outflow_config):
        with open(args.outflow_config) as f:
            outflow = json.load(f)
    else:
        outflow = {
            "num_outlet": 0,
            "flt_off_sw": False,
            "outl_elvs": morph['crest_elev'] - 5.0,
            "crest_width": 100.0,
            "crest_factor": 0.61,
        }

    lat = morph.get('latitude', 40.0)
    lon = morph.get('longitude', 116.0)
    lake_name = morph.get('lake_name', 'GLM_Lake')

    # Format dates
    start = args.start_date
    stop = args.end_date
    if len(start) == 10:
        start += ' 00:00:00'
    if len(stop) == 10:
        stop += ' 23:00:00'

    # Determine met file path (relative)
    met_path = args.met_csv or 'bcs/met_hourly.csv'

    # Determine LW type
    lw_type = args.lw_type

    # Auto-detect timefmt: 2 for datetime strings, 3 for seconds
    # timefmt=2 expects 'YYYY-MM-DD HH:MM:SS' strings
    # timefmt=3 expects integer seconds since start
    timefmt = 2 if '-' in start else 3

    # Sediment parameters from latitude
    sed_temp_mean = sed_temp_mean_from_lat(lat)
    sed_temp_amp = sed_temp_amplitude_from_lat(lat)
    sed_peak_doy = 242 if lat >= 0 else 60  # Northern vs Southern hemisphere

    # Inflow configuration
    num_inflows = 0
    inflow_block_extra = ""
    if args.inflow_csv:
        inflow_files = args.inflow_csv.split(',')
        num_inflows = len(inflow_files)
        stream_names = [f"'Stream{i+1}'" for i in range(num_inflows)]
        inflow_fl = [f"'{f.strip()}'" for f in inflow_files]
        inflow_block_extra = f"""   names_of_strms = {', '.join(stream_names)}
   subm_flag = {', '.join([fmt_bool(False)] * num_inflows)}
   strm_hf_angle = {', '.join(['65.0'] * num_inflows)}
   strmbd_slope = {', '.join(['2.0'] * num_inflows)}
   strmbd_drag = {', '.join(['0.016'] * num_inflows)}
   inflow_factor = {', '.join(['1.0'] * num_inflows)}
   inflow_fl = {', '.join(inflow_fl)}
   inflow_varnum = 3
   inflow_vars = 'FLOW','TEMP','SALT'"""

    # Build namelist
    H = morph['H']
    A = morph['A']
    bsn_vals = len(H)

    # Outflow block
    outflow_fl = outflow.get('outflow_fl', '')
    num_outlet = outflow.get('num_outlet', 0)

    nml = f"""
&glm_setup
   sim_name = {fmt_str(lake_name)}
   max_layers = {args.max_layers}
   min_layer_vol = 0.5
   min_layer_thick = {args.min_layer_thick}
   max_layer_thick = {args.max_layer_thick}
   density_model = 1
   non_avg = {fmt_bool(True)}
/

&mixing
   surface_mixing = 1
   coef_mix_conv = {args.coef_mix_conv}
   coef_wind_stir = {args.coef_wind_stir}
   coef_mix_shear = 0.2
   coef_mix_turb = 0.51
   coef_mix_KH = 0.3
   deep_mixing = 2
   coef_mix_hyp = {args.coef_mix_hyp}
   diff = 0.0
/

&morphometry
   lake_name = {fmt_str(lake_name)}
   latitude = {lat}
   longitude = {lon}
   bsn_len = {morph['bsn_len']}
   bsn_wid = {morph['bsn_wid']}
   crest_elev = {morph['crest_elev']}
   bsn_vals = {bsn_vals}
   H = {fmt_arr(H)}
   A = {fmt_arr(A)}
/

&time
   timefmt = {timefmt}
   start = {fmt_str(start)}
   stop = {fmt_str(stop)}
   dt = {args.dt}
   timezone = {args.timezone}
/

&output
   out_dir = {fmt_str(args.out_dir)}
   out_fn = {fmt_str('output')}
   nsave = {args.nsave}
   csv_lake_fname = {fmt_str('lake')}
   csv_point_nlevs = 0
   csv_point_fname = {fmt_str('WQ_')}
   csv_point_at = 17
   csv_point_nvars = 2
   csv_point_vars = 'temp','salt'
   csv_outlet_allinone = {fmt_bool(False)}
   csv_outlet_fname = {fmt_str('outlet_')}
   csv_outlet_nvars = 3
   csv_outlet_vars = 'flow','temp','salt'
   csv_ovrflw_fname = {fmt_str('overflow')}
/

&init_profiles
   lake_depth = {init_prof['lake_depth']}
   num_depths = {init_prof['num_depths']}
   the_depths = {fmt_arr(init_prof['the_depths'])}
   the_temps = {fmt_arr(init_prof['the_temps'])}
   the_sals = {fmt_arr(init_prof['the_sals'])}
   num_wq_vars = {init_prof.get('num_wq_vars', 0)}
/

&meteorology
   met_sw = {fmt_bool(True)}
   lw_type = {fmt_str(lw_type)}
   rain_sw = {fmt_bool(False)}
   atm_stab = 0
   catchrain = {fmt_bool(args.catchrain)}
   rad_mode = 1
   albedo_mode = 1
   cloud_mode = 4
   fetch_mode = 0
   subdaily = {fmt_bool(args.subdaily)}
   meteo_fl = {fmt_str(met_path)}
   wind_factor = {args.wind_factor}
   sw_factor = {args.sw_factor}
   lw_factor = 1.0
   at_factor = 1.0
   rh_factor = 1.0
   rain_factor = 1.0
   ce = {args.ce}
   ch = {args.ch}
   cd = {args.cd}
   rain_threshold = 0.01
   runoff_coef = {args.runoff_coef}
/

&bird_model
   AP = 973
   Oz = 0.279
   WatVap = 1.1
   AOD500 = 0.033
   AOD380 = 0.038
   Albedo = 0.2
/

&light
   light_mode = 0
   n_bands = 4
   light_extc = 1.0, 0.5, 2.0, 4.0
   energy_frac = 0.51, 0.45, 0.035, 0.005
   Benthic_Imin = 10
   Kw = {args.kw}
/

&inflow
   num_inflows = {num_inflows}
{inflow_block_extra}
/

&outflow
   num_outlet = {num_outlet}
   flt_off_sw = {fmt_bool(outflow.get('flt_off_sw', False))}
   outl_elvs = {outflow.get('outl_elvs', morph['crest_elev'] - 5.0)}
   bsn_len_outl = {outflow.get('bsn_len_outl', 100)}
   bsn_wid_outl = {outflow.get('bsn_wid_outl', 50)}
   outflow_fl = {fmt_str(outflow_fl) if outflow_fl else fmt_str('')}
   outflow_factor = {outflow.get('outflow_factor', 1.0)}
   crest_width = {outflow.get('crest_width', 100)}
   crest_factor = {outflow.get('crest_factor', 0.61)}
/

&sediment
   sed_heat_Ksoil = 2.0
   sed_temp_depth = 0.2
   sed_temp_mean = {sed_temp_mean}
   sed_temp_amplitude = {sed_temp_amp}
   sed_temp_peak_doy = {sed_peak_doy}
   benthic_mode = 2
   n_zones = 1
   zone_heights = {init_prof['lake_depth'] + 2.0}
   sed_reflectivity = 0.1
   sed_roughness = 0.01
/

&snowice
   snow_albedo_factor = 1.0
   snow_rho_max = 500
   snow_rho_min = 100
   dt_iceon_avg = 0.02
   min_ice_thickness = 0.001
/
"""
    return nml


def validate_outputs(nml_content, args):
    """Validate the generated namelist."""
    warnings = []

    # Check for double quotes (should be single)
    if '"' in nml_content.replace('"', ''):
        warnings.append("Double quotes found — Fortran requires single quotes")

    # Check bsn_vals consistency
    with open(args.morphometry) as f:
        morph = json.load(f)
    if len(morph['H']) != len(morph['A']):
        warnings.append("H and A array lengths do not match!")

    # Check file references exist
    met_path = args.met_csv or 'bcs/met_hourly.csv'
    if not os.path.isabs(met_path):
        # Relative to output directory
        check_path = os.path.join(os.path.dirname(args.output), met_path)
        if not os.path.exists(check_path):
            warnings.append(f"Met file not found at relative path: {met_path}")

    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)

    return warnings


def main():
    parser = argparse.ArgumentParser(
        description="Generate glm3.nml namelist file")
    # Required inputs
    parser.add_argument("--morphometry", type=str, required=True,
                        help="Morphometry JSON file")
    parser.add_argument("--start_date", type=str, required=True,
                        help="Simulation start (YYYY-MM-DD [HH:MM:SS])")
    parser.add_argument("--end_date", type=str, required=True,
                        help="Simulation end (YYYY-MM-DD [HH:MM:SS])")
    parser.add_argument("--output", type=str, required=True,
                        help="Output glm3.nml path")

    # Optional inputs
    parser.add_argument("--init_profiles", type=str,
                        help="Init profiles JSON")
    parser.add_argument("--met_csv", type=str,
                        help="Meteorological CSV path (relative)")
    parser.add_argument("--inflow_csv", type=str,
                        help="Inflow CSV path(s), comma-separated for multiple")
    parser.add_argument("--outflow_config", type=str,
                        help="Outflow config JSON")

    # Parameters
    parser.add_argument("--timezone", type=int, default=0,
                        help="Timezone offset from UTC (default: 0)")
    parser.add_argument("--dt", type=int, default=3600,
                        help="Timestep in seconds (default: 3600)")
    parser.add_argument("--max_layers", type=int, default=500,
                        help="Maximum layers (default: 500)")
    parser.add_argument("--min_layer_thick", type=float, default=0.15,
                        help="Minimum layer thickness (m, default: 0.15)")
    parser.add_argument("--max_layer_thick", type=float, default=0.5,
                        help="Maximum layer thickness (m, default: 0.5)")
    parser.add_argument("--nsave", type=int, default=24,
                        help="Output save interval in timesteps (default: 24)")
    parser.add_argument("--out_dir", type=str, default="output",
                        help="Output directory (default: output)")
    parser.add_argument("--kw", type=float, default=0.5,
                        help="Light extinction coefficient Kw (m^-1, default: 0.5)")
    parser.add_argument("--coef_wind_stir", type=float, default=0.402,
                        help="Wind stirring coefficient (default: 0.402)")
    parser.add_argument("--coef_mix_conv", type=float, default=0.2,
                        help="Convective mixing coefficient (default: 0.2)")
    parser.add_argument("--coef_mix_hyp", type=float, default=0.5,
                        help="Hypolimnetic mixing coefficient (default: 0.5)")
    parser.add_argument("--wind_factor", type=float, default=1.0,
                        help="Wind speed scaling factor (default: 1.0)")
    parser.add_argument("--sw_factor", type=float, default=1.0,
                        help="Shortwave radiation scaling (default: 1.0)")
    parser.add_argument("--ce", type=float, default=0.0013,
                        help="Latent heat transfer coefficient (default: 0.0013)")
    parser.add_argument("--ch", type=float, default=0.0014,
                        help="Sensible heat transfer coefficient (default: 0.0014)")
    parser.add_argument("--cd", type=float, default=0.0013,
                        help="Drag coefficient (default: 0.0013)")
    parser.add_argument("--lw_type", type=str, default="LW_IN",
                        choices=["LW_IN", "LW_CC", "LW_NET"],
                        help="Longwave radiation type (default: LW_IN)")
    parser.add_argument("--subdaily", action="store_true",
                        help="Enable subdaily meteorological input")
    parser.add_argument("--catchrain", action="store_true",
                        help="Enable catchment rainfall runoff")
    parser.add_argument("--runoff_coef", type=float, default=0.3,
                        help="Catchment runoff coefficient (default: 0.3)")
    args = parser.parse_args()

    validate_inputs(args)
    nml_content = process(args)
    warnings = validate_outputs(nml_content, args)

    os.makedirs(os.path.dirname(args.output) or '.', exist_ok=True)
    with open(args.output, 'w') as f:
        f.write(nml_content)

    print(json.dumps({
        "status": "success",
        "output_file": args.output,
        "warnings": warnings,
    }, indent=2))


if __name__ == "__main__":
    main()
