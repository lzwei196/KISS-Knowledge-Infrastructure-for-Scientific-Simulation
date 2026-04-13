#!/usr/bin/env python3
"""
parse_ana_output.py
===================
Parse an RZWQM2 .ana (analysis) output file and extract one or more variables
as a CSV with datetime and value columns.

The .ana file is a space-delimited daily output with 139 columns.
This tool extracts variables by friendly name, raw column number, or header
number, and writes results to CSV.

Usage (CLI):
    python parse_ana_output.py <project_path> <station_id> <variable> [output_csv]

    variable can be:
      - A friendly name:  grain_yield, biomass_above, lai, actual_et, ...
      - A header number:  h44   (column 44 in .ana header = BIOMASS OF GRAIN)
      - A raw 0-index:    col_43 (same as h44, 0-based Python index)
      - Multiple vars:    grain_yield,biomass_above,lai  (comma-separated)
      - "list"            to print all available variable names

Usage (Python import):
    from parse_ana_output import extract_variables
    df = extract_variables(ana_file, ['grain_yield', 'biomass_above', 'lai'])

Exit codes:
    0 - Success
    1 - Input validation error
    2 - Processing error
    3 - Output validation error
"""

import sys
import os
import csv
import json
from datetime import datetime

# ---------------------------------------------------------------------------
# INPUTS (for non-CLI use — set these before calling main())
# ---------------------------------------------------------------------------
PROJECT_PATH = ""
STATION_ID = ""
VARIABLE_NAME = ""
OUTPUT_CSV = ""

# ---------------------------------------------------------------------------
# Add lib to path
# ---------------------------------------------------------------------------
DATA_PREP_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'lib')
sys.path.insert(0, os.path.abspath(DATA_PREP_DIR))

# ---------------------------------------------------------------------------
# COMPLETE column map: all 139 .ana columns
# Keys are friendly names. Values are 0-based Python indices.
# The .ana header uses 1-based numbering: header N) = Python index N-1.
# ---------------------------------------------------------------------------
COLUMN_MAP = {
    # --- Time (col 1) ---
    'time':                         0,   #   1) TIME (YEAR.DAY)
    # --- Hydrology (cols 2-13) ---
    'stored_soil_water':            1,   #   2) STORED SOIL WATER (CM)
    'precipitation':                2,   #   3) PRECIPITATION (CM/DAY)
    'irrigation':                   3,   #   4) IRRIGATION (CM/DAY)
    'infiltration':                 4,   #   5) INFILTRATION (CM/DAY)
    'actual_evaporation':           5,   #   6) ACTUAL EVAPORATION (CM/DAY)
    'actual_transpiration':         6,   #   7) ACTUAL TRANSPIRATION (CM/DAY)
    'potential_evaporation':        7,   #   8) POTENTIAL EVAPORATION (CM/DAY)
    'potential_transpiration':      8,   #   9) POTENTIAL TRANSPIRATION (CM/DAY)
    'deep_seepage':                 9,   #  10) DEEP SEEPAGE (CM/DAY)
    'tile_drainage':               10,   #  11) TILE DRAINAGE (CM/DAY)
    'runoff':                      11,   #  12) RUNOFF (CM/DAY)
    'plant_water_stress':          12,   #  13) PLANT WATER STRESS
    # --- Nitrogen inputs (cols 14-20) ---
    'plant_usable_n':              13,   #  14) PLANT USABLE N IN ROOT DEPTH (KG-N/HA)
    'fertilizer_applied':          14,   #  15) FERTILIZER APPLIED (KG-N/HA/DAY)
    'manure_applied':              15,   #  16) MANURE APPLIED (KG-N/HA/DAY)
    'n_irrigation':                16,   #  17) N IN IRRIGATION WATER (KG-N/HA/DAY)
    'n_rain':                      17,   #  18) N IN RAIN WATER (KG-N/HA/DAY)
    'son_dead_roots':              18,   #  19) SON FROM DEAD ROOTS (KG-N/HA/DAY)
    'son_soil_residue':            19,   #  20) SON FROM SOIL RESIDUE (KG-N/HA/DAY)
    # --- Nitrogen cycling (cols 21-31) ---
    'nitrogen_uptake':             20,   #  21) NITROGEN UPTAKE (KG-N/HA/DAY)
    'total_crop_n_above':          21,   #  22) TOTAL CROP ABOVEGROUND (KG-N/HA)
    'total_crop_n_below':          22,   #  23) TOTAL CROP BELOWGROUND (KG-N/HA)
    'grain_n':                     23,   #  24) TOTAL IN GRAIN (KG-N/HA)
    'n_fixation':                  24,   #  25) FROM N-FIXATION (KG-N/HA/DAY)
    'denitrification':             25,   #  26) DENITRIFICATION (KG-N/HA/DAY)
    'volatilization':              26,   #  27) VOLATILIZATION (KG-N/HA/DAY)
    'mineralization':              27,   #  28) MINERALIZATION (KG-N/HA/DAY)
    'n_runoff':                    28,   #  29) N IN RUNOFF (KG-N/HA/DAY)
    'n_deep_seepage':              29,   #  30) N IN DEEP SEEPAGE (KG-N/HA/DAY)
    'no3_leaching':                30,   #  31) NO3/N IN TILE DRAINAGE (KG-N/HA/DAY)
    # --- Nitrogen pools (cols 32-40) ---
    'slow_residue_pool':           31,   #  32) SLOW RESIDUE POOL (KG-N/HA)
    'fast_residue_pool':           32,   #  33) FAST RESIDUE POOL (KG-N/HA)
    'fast_humus_pool':             33,   #  34) FAST HUMUS POOL (KG-N/HA)
    'transition_humus_pool':       34,   #  35) TRANSITION HUMUS POOL (KG-N/HA)
    'slow_humus_pool':             35,   #  36) SLOW HUMUS POOL (KG-N/HA)
    'aerobic_heterotrophs':        36,   #  37) AEROBIC HETEROTROPHS (KG-N/HA)
    'autotrophs':                  37,   #  38) AUTOTROPHS (KG-N/HA)
    'anaerobic_heterotrophs':      38,   #  39) ANEROBIC HETEROTROPHS (KG-N/HA)
    'plant_n_stress':              39,   #  40) PLANT NITROGEN STRESS
    # --- Crop (cols 41-45) ---
    'biomass_above':               40,   #  41) TOTAL ABOVE GROUND BIOMASS (KG/HA)
    'biomass_below':               41,   #  42) TOTAL BELOW GROUND BIOMASS (KG/HA)
    'lai':                         42,   #  43) LEAF AREA INDEX
    'grain_yield':                 43,   #  44) BIOMASS OF GRAIN (KG/HA)
    'growth_stage':                44,   #  45) PLANT GROWTH STAGE (0-1)
    # --- Pesticides (cols 46-60) ---
    'pest1_applied':               45,   #  46) PEST #1 APPLIED (KG/HA/DAY)
    'pest1_soil':                  46,   #  47) PEST #1 IN SOIL (KG/HA)
    'pest1_tile':                  47,   #  48) PEST #1 IN TILE DRAINAGE (KG/HA/DAY)
    'pest1_deep':                  48,   #  49) PEST #1 IN DEEP SEEPAGE (KG/HA/DAY)
    'pest1_runoff':                49,   #  50) PEST #1 IN RUNOFF (KG/HA/DAY)
    'pest2_applied':               50,   #  51) PEST #2 APPLIED (KG/HA/DAY)
    'pest2_soil':                  51,   #  52) PEST #2 IN SOIL (KG/HA)
    'pest2_tile':                  52,   #  53) PEST #2 IN TILE DRAINAGE (KG/HA/DAY)
    'pest2_deep':                  53,   #  54) PEST #2 IN DEEP SEEPAGE (KG/HA/DAY)
    'pest2_runoff':                54,   #  55) PEST #2 IN RUNOFF (KG/HA/DAY)
    'pest3_applied':               55,   #  56) PEST #3 APPLIED (KG/HA/DAY)
    'pest3_soil':                  56,   #  57) PEST #3 IN SOIL (KG/HA)
    'pest3_tile':                  57,   #  58) PEST #3 IN TILE DRAINAGE (KG/HA/DAY)
    'pest3_deep':                  58,   #  59) PEST #3 IN DEEP SEEPAGE (KG/HA/DAY)
    'pest3_runoff':                59,   #  60) PEST #3 IN RUNOFF (KG/HA/DAY)
    # --- Groundwater & crop detail (cols 61-74) ---
    'watertable_depth':            60,   #  61) WATERTABLE DEPTH (CM)
    'plant_height':                61,   #  62) PLANT HEIGHT (CM)
    'root_depth':                  62,   #  63) DEPTH OF ROOTS (CM)
    'temp_stress':                 63,   #  64) PLANT TEMPERATURE STRESS
    'leaf_biomass':                64,   #  65) LEAF BIOMASS (G/PLANT)
    'stem_biomass':                65,   #  66) STEM BIOMASS (G/PLANT)
    'root_biomass':                66,   #  67) ROOT BIOMASS (G/PLANT)
    'seed_biomass':                67,   #  68) SEED BIOMASS (G/PLANT)
    'standing_dead_biomass':       68,   #  69) STANDING DEAD BIOMASS (G/PLANT)
    'litter_biomass':              69,   #  70) LITTER BIOMASS (G/PLANT)
    'dead_root_biomass':           70,   #  71) DEAD ROOT BIOMASS (G/PLANT)
    'surface_residue_mass':        71,   #  72) SURFACE RESIDUE MASS (KG/HA)
    'standing_dead_residue':       72,   #  73) STANDING DEAD RESIDUE MASS (KG/HA)
    'deadend_macropore_pct':       73,   #  74) DEADEND MACROPORE PERCENTAGE
    # --- Lateral flow & C (cols 75-80) ---
    'n_lateral_flow':              74,   #  75) N IN LATERAL FLOW (KG-N/HA/DAY)
    'lateral_water_flow':          75,   #  76) LATERAL WATER FLOW (CM/DAY)
    'daily_immobilization':        76,   #  77) DAILY IMMOBILIZATION (KG-N/HA/DAY)
    'daily_co2':                   77,   #  78) DAILY CO2 RELEASE (KG-C/HA/DAY)
    'total_soil_humus_c':          78,   #  79) TOTAL SOIL HUMUS C (KG/HA)
    'total_soil_residue_c':        79,   #  80) TOTAL SOIL RESIDUE C (KG/HA)
    # --- ET & Weather (cols 81-90) ---
    'tall_ref_et':                 80,   #  81) TALL REFERENCE ET (CM)
    'short_ref_et':                81,   #  82) SHORT REFERENCE ET (CM)
    'pet':                         82,   #  83) POTENTIAL CROP ET (PET) (CM)
    'actual_et':                   83,   #  84) ACTUAL ET (CM)
    'tmin':                        84,   #  85) MINIMUM AIR TEMPERATURE (oC)
    'tmax':                        85,   #  86) MAXIMUM AIR TEMPERATURE (oC)
    'tmean':                       86,   #  87) MEAN AIR TEMPERATURE (oC)
    'radiation':                   87,   #  88) SOLAR RADIATION (MJ/M2/DAY)
    'rh':                          88,   #  89) RELATIVE HUMIDITY (%)
    'windspeed':                   89,   #  90) WINDSPEED (KM/DAY)
    # --- Snow & soil thermal (cols 91-95) ---
    'total_ice':                   90,   #  91) TOTAL ICE IN SOIL (CM)
    'snow':                        91,   #  92) SNOW DEPTH (CM)
    'surface_residue_temp':        92,   #  93) SURFACE RESIDUE TEMP (oC)
    'frozen_depth':                93,   #  94) FROZEN DEPTH (CM)
    'thawing_depth':               94,   #  95) THAWING DEPTH (CM)
    # --- GHG (cols 96-100) ---
    'ch4_emission':                95,   #  96) DAILY CH4 EMISSION (KG-C/HA/DAY)
    'n2o_emission':                96,   #  97) DAILY N2O EMISSION (Kg-N/HA/DAY)
    'nxo_emission':                97,   #  98) DAILY NxO EMISSION (KG-N/HA/DAY)
    'total_soil_inorganic_n':      98,   #  99) TOTAL SOIL INORGANIC N (Kg-N/ha)
    'water_stress_leaf':           99,   # 100) WATER STRESS FOR LEAF EXPANSION
    # --- GHG detail (cols 101-105) ---
    'n2o_nitrification':          100,   # 101) N2O EMISSION FROM NITRIFICATION (Kg N/ha/day)
    'nxo_nitrification':          101,   # 102) NxO EMISSION FROM NITRIFICATION (Kg N/ha/day)
    'ghg_nitrification':          102,   # 103) GHG ABSORBED FROM NITRIFICATION (KG N/HA/DAY)
    'ghg_denitrification':        103,   # 104) GHG ABSORBED FROM DENITRIFICATION (KG N/HA/DAY)
    'snow_melt':                  104,   # 105) SNOW MELT (CM)
    # --- DSSAT & erosion (cols 106-114) ---
    'potential_water_uptake':     105,   # 106) POTENTIAL WATER UPTAKE (DSSAT, CM)
    'pest1_eroded':               106,   # 107) PESTICIDE #1 ERODED (KG/HA/DAY)
    'pest2_eroded':               107,   # 108) PESTICIDE #2 ERODED (KG/HA/DAY)
    'pest3_eroded':               108,   # 109) PESTICIDE #3 ERODED (KG/HA/DAY)
    'soil_nh4_eroded':            109,   # 110) SOIL NH4 ERODED (KG/HA/DAY)
    'organic_n_eroded':           110,   # 111) ORGANIC-N ERODED (KG/HA/DAY)
    'organic_c_eroded':           111,   # 112) ORGANIC-C ERODED (KG/HA/DAY)
    'total_sediment_eroded':      112,   # 113) TOTAL SEDIMENT ERODED (KG/HA/DAY)
    'residue_cover_fraction':     113,   # 114) FRACTION OF RESIDUE COVER
    'water_added_measured_swc':   114,   # 115) WATER ADDED DUE TO USING MEASURED SWC (CM)
    # --- Lateral pesticide (cols 116-118) ---
    'pest1_lateral':              115,   # 116) PEST #1 IN LATERAL FLOW (KG/HA/DAY)
    'pest2_lateral':              116,   # 117) PEST #2 IN LATERAL FLOW (KG/HA/DAY)
    'pest3_lateral':              117,   # 118) PEST #3 IN LATERAL FLOW (KG/HA/DAY)
    # --- Phosphorus (cols 119-128) ---
    'drp_loss_runoff':            118,   # 119) DRP LOSS RUNOFF (KG-P/HA/DAY)
    'pp_loss_runoff':             119,   # 120) PP LOSS RUNOFF (KG-P/HA/DAY)
    'drp_loss_tile':              120,   # 121) DRP LOSS TILE (KG-P/HA/DAY)
    'pp_loss_tile':               121,   # 122) PP LOSS TILE (KG-P/HA/DAY)
    'plant_p_uptake':             122,   # 123) PLANT P UPTAKE (KG-P/HA/DAY)
    'drp_loss_lateral':           123,   # 124) DRP LOSS LATERAL FLOW (KG-P/HA/DAY)
    'pp_loss_lateral':            124,   # 125) PP LOSS LATERAL FLOW (KG-P/HA/DAY)
    'drp_loss_deep':              125,   # 126) DRP LOSS DEEP SEEPAGE (KG-P/HA/DAY)
    'pp_loss_deep':               126,   # 127) PP LOSS DEEP SEEPAGE (KG-P/HA/DAY)
    'plant_p_stress':             127,   # 128) PLANT P STRESS (0-1)
    # --- Advanced (cols 129-139) ---
    'plant_p':                    128,   # 129) PLANT P (KG/HA/DAY)
    'air_temp_2pm':               129,   # 130) AIR TEMPERATURE AT 2:00 PM (oC)
    'leaf_temp_2pm':              130,   # 131) CURRENT LEAF TEMPERATURE AT 2:00 PM (oC)
    'leaf_temp_nontranspiring':   131,   # 132) LEAF TEMPERATURE OF NON-TRANSPIRING PLANT (oC)
    'leaf_temp_transpiring':      132,   # 133) LEAF TEMPERATURE OF FULLY TRANSPIRING PLANT (oC)
    'cwsi':                       133,   # 134) CROP WATER STRESS INDEX (CSWI)
    'n_ion_exchange':             134,   # 135) INORGANIC N ONTO ION EXCHANGE SITES (KG N/HA/DAY)
    'leaf_n_pct':                 135,   # 136) LEAF N CONCENTRATION (%)
    'stem_n_pct':                 136,   # 137) STEM N CONCENTRATION (%)
    'root_n_pct':                 137,   # 138) ROOT N CONCENTRATION (%)
    'grain_n_pct':                138,   # 139) GRAIN N CONCENTRATION (%)
}

# Reverse map: 0-based index → friendly name (for --list and col_N display)
INDEX_TO_NAME = {v: k for k, v in COLUMN_MAP.items()}

# Special unit conversions (multiplier applied after reading)
UNIT_CONVERSIONS = {
    'tile_drainage': 10,   # cm -> mm (multiply by 10)
}


def resolve_variable(var_str):
    """
    Resolve a variable specifier to (0-based_index, display_name).
    Accepts:
      - friendly name: 'grain_yield' → (43, 'grain_yield')
      - header number: 'h44'         → (43, 'h44_biomass_of_grain')
      - raw 0-index:  'col_43'      → (43, 'col_43')
    """
    var_str = var_str.strip()

    # Header-based: h44 means header column 44 → Python index 43
    if var_str.startswith('h') and var_str[1:].isdigit():
        header_num = int(var_str[1:])
        idx = header_num - 1
        name = INDEX_TO_NAME.get(idx, f'h{header_num}')
        return idx, f'h{header_num}_{name}' if name != f'h{header_num}' else var_str

    # Raw 0-based: col_43 means Python index 43
    if var_str.startswith('col_'):
        try:
            idx = int(var_str.split('_', 1)[1])
            name = INDEX_TO_NAME.get(idx, var_str)
            return idx, var_str
        except ValueError:
            raise ValueError(f"Invalid column format: '{var_str}'. Use 'col_N' (e.g., col_43).")

    # Friendly name
    if var_str in COLUMN_MAP:
        return COLUMN_MAP[var_str], var_str

    raise ValueError(
        f"Unknown variable '{var_str}'. Use a friendly name, 'hN' (header number), "
        f"or 'col_N' (0-based index). Run with 'list' to see all variables."
    )


def extract_variables(ana_file, variables, encoding='ISO-8859-1'):
    """
    Extract one or more variables from an .ana file.
    Returns a dict: {var_name: [(datetime, value), ...]}

    Streams the file line-by-line (no full-file read) to handle large files.
    """
    from datetime import datetime as dt_cls

    # Resolve all variables
    resolved = []
    for var in variables:
        idx, name = resolve_variable(var)
        multiplier = UNIT_CONVERSIONS.get(var, 1)
        resolved.append((idx, name, multiplier))

    max_col = max(idx for idx, _, _ in resolved)

    results = {name: [] for _, name, _ in resolved}

    with open(ana_file, encoding=encoding) as f:
        # Skip header until '===...' separator
        in_header = True
        for line in f:
            if in_header:
                if line.strip().startswith('===='):
                    in_header = False
                continue

            parts = line.split()
            if len(parts) <= max_col:
                continue

            try:
                time_str = parts[0]
                # Parse YYYY.DDD format
                dot_pos = time_str.find('.')
                if dot_pos < 0:
                    continue
                year_str = time_str[:dot_pos]
                doy_str = time_str[dot_pos + 1:]
                year = int(year_str)
                doy = int(doy_str)

                if doy == 0:
                    # Day 0 = Dec 31 of previous year (some RZWQM2 versions)
                    date = dt_cls(year - 1, 12, 31)
                else:
                    date = dt_cls.strptime(f'{year}.{doy:03d}', '%Y.%j')

                for idx, name, mult in resolved:
                    val = float(parts[idx]) * mult
                    results[name].append((date, val))

            except (ValueError, IndexError):
                continue

    return results


def validate_inputs(project_path, station_id, variable_name, output_csv):
    """Validate inputs. Returns (valid, error_msg, parsed_args)."""
    errors = []

    if not project_path:
        errors.append("PROJECT_PATH is required.")
    elif not os.path.isdir(project_path):
        errors.append(f"PROJECT_PATH does not exist: {project_path}")

    if not station_id:
        errors.append("STATION_ID is required.")

    if not variable_name:
        errors.append(
            f"VARIABLE_NAME is required. Supported: {list(COLUMN_MAP.keys())} "
            f"or 'hN' (header number) or 'col_N' (0-based index)."
        )

    # Check .ana file exists
    ana_file = None
    if project_path and station_id:
        ana_file = os.path.join(project_path, 'Analysis', station_id + '.ana')
        if not os.path.isfile(ana_file):
            errors.append(f"Analysis file not found: {ana_file}")

    # Set default output path
    if not output_csv and project_path and station_id and variable_name:
        safe_name = variable_name.replace(',', '_')
        output_csv = os.path.join(
            project_path, 'Analysis', f"{station_id}_{safe_name}.csv"
        )

    if output_csv:
        out_dir = os.path.dirname(output_csv)
        if out_dir and not os.path.isdir(out_dir):
            errors.append(f"Output directory does not exist: {out_dir}")

    if errors:
        return False, "; ".join(errors), None

    return True, "", {
        'project_path': project_path,
        'station_id': station_id,
        'variable_name': variable_name,
        'output_csv': output_csv,
        'ana_file': ana_file
    }


def process(args):
    """
    Parse the .ana file and extract the specified variable(s) to CSV.
    Supports comma-separated variables for batch extraction.
    Returns (success, error_msg, summary).
    """
    variable_name = args['variable_name']
    output_csv = args['output_csv']
    ana_file = args['ana_file']

    try:
        # Parse comma-separated variables
        var_list = [v.strip() for v in variable_name.split(',')]

        # Resolve and validate all variables before reading
        for var in var_list:
            resolve_variable(var)

        # Extract using streaming reader
        results = extract_variables(ana_file, var_list)

        if not any(results.values()):
            return False, f"No data extracted for variable(s) '{variable_name}'.", None

        # Write CSV
        var_names = list(results.keys())
        with open(output_csv, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['datetime'] + var_names)

            # Use first variable's dates as reference
            ref_data = results[var_names[0]]
            # Build lookup for other variables
            other_lookups = {}
            for vn in var_names[1:]:
                other_lookups[vn] = {d: v for d, v in results[vn]}

            for date, val in ref_data:
                row = [date.strftime('%Y-%m-%d'), val]
                for vn in var_names[1:]:
                    row.append(other_lookups[vn].get(date, ''))
                writer.writerow(row)

        record_count = len(ref_data)
        dates = [d for d, _ in ref_data]

        summary = {
            'output_csv': output_csv,
            'variables': var_names,
            'record_count': record_count,
            'date_range': {
                'start': min(dates).strftime('%Y-%m-%d'),
                'end': max(dates).strftime('%Y-%m-%d')
            }
        }

        return True, "", summary

    except Exception as e:
        return False, f"Processing error: {e}", None


def validate_outputs(output_csv, variable_name):
    """Validate the output CSV. Returns (valid, error_msg)."""
    errors = []

    if not os.path.isfile(output_csv):
        return False, f"Output CSV was not created: {output_csv}"

    with open(output_csv, 'r') as f:
        reader = csv.reader(f)
        header = next(reader, None)
        first_row = next(reader, None)

    if header is None or len(header) < 2:
        errors.append("Output CSV has no header or too few columns.")
    elif header[0] != 'datetime':
        errors.append(f"First column should be 'datetime', got '{header[0]}'.")

    if first_row is None:
        errors.append("Output CSV has no data rows.")
    elif len(first_row) < 2:
        errors.append(f"First data row has {len(first_row)} columns, expected >= 2.")
    else:
        try:
            datetime.strptime(first_row[0], '%Y-%m-%d')
        except ValueError:
            errors.append(f"First row date '{first_row[0]}' is not YYYY-MM-DD.")
        try:
            float(first_row[1])
        except ValueError:
            errors.append(f"First row value '{first_row[1]}' is not numeric.")

    if errors:
        return False, "; ".join(errors)
    return True, ""


def print_variable_list():
    """Print all available variable names grouped by category."""
    categories = {
        'Hydrology':   range(0, 13),
        'Nitrogen':    range(13, 40),
        'Crop':        range(40, 45),
        'Pesticides':  range(45, 60),
        'GW & Detail': range(60, 74),
        'Lateral & C': range(74, 80),
        'ET & Weather':range(80, 90),
        'Snow & Frost': range(90, 95),
        'GHG':         range(95, 105),
        'Erosion':     range(105, 115),
        'Phosphorus':  range(118, 129),
        'Advanced':    range(129, 139),
    }
    print(f"{'Name':<30s} {'Header#':>7s}  {'Description'}")
    print("-" * 80)
    for cat, idx_range in categories.items():
        print(f"\n--- {cat} ---")
        for idx in idx_range:
            name = INDEX_TO_NAME.get(idx, f'(unmapped col_{idx})')
            hnum = idx + 1
            print(f"  {name:<28s}  h{hnum:<5d}")
    print(f"\nTotal: {len(COLUMN_MAP)} named variables (all 139 columns mapped)")
    print("Usage: pass name, hN (header number), or col_N (0-based index)")


def main():
    project_path = sys.argv[1] if len(sys.argv) > 1 else PROJECT_PATH
    station_id = sys.argv[2] if len(sys.argv) > 2 else STATION_ID
    variable_name = sys.argv[3] if len(sys.argv) > 3 else VARIABLE_NAME
    output_csv = sys.argv[4] if len(sys.argv) > 4 else OUTPUT_CSV

    # Special: list all variables
    if project_path == 'list' or variable_name == 'list':
        print_variable_list()
        sys.exit(0)

    # Ensure project_path ends with separator
    if project_path and not project_path.endswith(('/', '\\')):
        project_path = project_path + '/'

    # --- Step 1: Validate inputs ---
    valid, err, args = validate_inputs(project_path, station_id, variable_name, output_csv)
    if not valid:
        print(json.dumps({"status": "INPUT_ERROR", "message": err}))
        sys.exit(1)

    # --- Step 2: Process ---
    success, err, summary = process(args)
    if not success:
        print(json.dumps({"status": "PROCESSING_ERROR", "message": err}))
        sys.exit(2)

    # --- Step 3: Validate outputs ---
    valid, err = validate_outputs(args['output_csv'], args['variable_name'])
    if not valid:
        print(json.dumps({"status": "OUTPUT_ERROR", "message": err}))
        sys.exit(3)

    print(json.dumps({
        "status": "SUCCESS",
        "summary": summary,
        "message": (
            f"Extracted {summary['record_count']} records of {summary['variables']} "
            f"from {summary['date_range']['start']} to {summary['date_range']['end']}. "
            f"Written to {summary['output_csv']}."
        )
    }))
    sys.exit(0)


if __name__ == '__main__':
    main()
