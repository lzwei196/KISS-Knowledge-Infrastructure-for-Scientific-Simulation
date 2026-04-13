#!/usr/bin/env python3
"""
write_management_events.py
==========================
Write crop management events (planting, fertilizer, harvest, irrigation) to
RZWQM.dat using data acquired from global geospatial datasets.

Locates management sections in RZWQM.dat by their header/end delimiter
strings, replaces the data lines between them, and writes the file back.

Inputs:
    project_path       - RZWQM2 project root directory
    station_id         - Station/scenario identifier
    management_config  - JSON dict with planting, fertilizer, irrigation data
    simulation_years   - List of years to generate planting events for

Exit codes:
    0 - Success
    1 - Input validation error
    2 - Processing error
    3 - Output validation error
"""

import sys
import os
import json
from datetime import datetime, timedelta

# Section identifiers (must match rzwqm.dat comment lines exactly)
PLANTING_HEAD = '=    5       planting window in days after plant date (# of days) [0-45]'
PLANTING_END = '==               M A N U R E   M A N A G E M E N T                    =='

MANURE_DATA_HEAD = '=     3...   repeat record 2 for each application.'
MANURE_END = '==            F E R T I L I Z E R   M A N A G E M E N T               =='

FERT_DATA_HEAD = '=     ...   repeat record 2 for each application.'
FERT_END = '==                   B M P   M A N A G E M E N T                      =='

BMP_HEAD = '=     11     Depth of anhydrous injector used for fertlizer app      [cm]'
BMP_END = '==            P E S T I C I D E   M A N A G E M E N T                 =='

IRRIG_HEAD = '=   . . .  repeat Rec 2-4 for each operation'
# Irrigation is the last management section; its data extends to end-of-file


def _find_section(lines, head_id, end_id):
    """
    Find the data region between head_id and end_id in the file lines.
    Returns (data_start, data_end) as an exclusive range [start, end).

    The pattern in rzwqm.dat is:
      head_id comment line
      ========================================================================   <-- separator
      <DATA LINES>                                                               <-- what we return
      ========================================================================   <-- separator (start of next section header block)
      ==                                                                    ==
      ==               NEXT SECTION TITLE                                   ==   <-- end_id
    """
    head_line = None
    end_line = None

    for i, line in enumerate(lines):
        stripped = line.rstrip()
        if stripped == head_id:
            head_line = i
        if end_id and stripped == end_id:
            end_line = i

    if head_line is None:
        raise ValueError(f"Could not find section header: '{head_id}'")

    # Data starts after the '===...' separator line that follows the head comment
    data_start = head_line + 1
    while data_start < len(lines) and lines[data_start].rstrip().startswith('=' * 10):
        data_start += 1

    if end_line is not None:
        # Walk backwards from end_id to find the '===...' block that opens the
        # next section header. The data ends just before that separator block.
        data_end = end_line
        while data_end > data_start:
            stripped = lines[data_end - 1].rstrip()
            if stripped.startswith('=' * 10) or stripped.startswith('=='):
                data_end -= 1
            else:
                break
        # data_end is now the index of the first separator/header line
        # i.e., lines[data_start:data_end] are pure data lines
    else:
        # Last section (irrigation): data goes to end of file
        data_end = len(lines)

    return data_start, data_end


def _doy_to_date(doy, year):
    """Convert day-of-year to (day, month, year) tuple."""
    dt = datetime(year, 1, 1) + timedelta(days=int(doy) - 1)
    return dt.day, dt.month, dt.year


def _format_planting_lines(planting_cfg, years):
    """
    Generate planting section data lines for the given years.

    Each planting event is 3 lines:
    Line 1: ref dd mm yyyy row_spacing depth density method init_mat emerg sprout age
    Line 2: harvest_when stage class pct h_dd h_mm h_yyyy
    Line 3: stubble eff type sw window
    """
    num_plantings = len(years)
    lines = [str(num_plantings)]

    plant_doy = planting_cfg.get('planting_doy', 120)
    harvest_doy = planting_cfg.get('harvest_doy', 280)
    row_spacing = planting_cfg.get('row_spacing_cm', 76.0)
    depth = planting_cfg.get('depth_layer_index', 7)
    density = planting_cfg.get('density_seeds_per_ha', 72000)
    method = planting_cfg.get('method', 0)
    harvest_when = planting_cfg.get('harvest_trigger', 1)
    growth_stage = planting_cfg.get('growth_stage_threshold', 1.0)
    stubble = planting_cfg.get('stubble_height_cm', 30.0)
    harvest_eff = planting_cfg.get('harvest_efficiency', 1.0)
    harvest_type = planting_cfg.get('harvest_type', 3)

    # crop_ref selects which crop in RZCropSel.rzq (1=first crop).
    # Use 1 for all years to plant the same crop. For rotation, pass
    # a per-year crop_ref in planting_cfg.
    crop_ref = planting_cfg.get('crop_ref', 1)

    for ref_num, year in enumerate(years, start=1):
        p_dd, p_mm, p_yyyy = _doy_to_date(plant_doy, year)

        # Harvest date: if harvest_doy < plant_doy, harvest is next year (winter crop)
        if harvest_doy >= plant_doy:
            h_dd, h_mm, h_yyyy = _doy_to_date(harvest_doy, year)
        else:
            h_dd, h_mm, h_yyyy = _doy_to_date(harvest_doy, year + 1)

        # Line 1: planting parameters
        # First field = crop reference (index into RZCropSel.rzq), NOT sequence number
        line1 = (
            f"{crop_ref}  {p_dd}   {p_mm}  {p_yyyy}  {row_spacing:.1f}   {depth} "
            f"{density:.1f}   {method} -99.0   -99 -99.0   -99 "
        )

        # Line 2: harvest parameters (indented)
        line2 = (
            f"               {harvest_when} {growth_stage:.1f}   0 0.0  "
            f"{h_dd} {h_mm} {h_yyyy} "
        )

        # Line 3: stubble/efficiency (indented)
        line3 = (
            f"               {stubble:.1f}  {harvest_eff:.1f}   {harvest_type} 0 0"
        )

        lines.extend([line1, line2, line3])

    return lines


def _format_fertilizer_lines(fert_cfg, planting_doy, years):
    """
    Generate fertilizer section data lines.

    Each application is 1 line:
    ref timing dd mm yyyy method no3 nh4 urea bmp_chem bmp_method split_days split_frac split_max p_mass
    """
    applications = fert_cfg.get('applications', [])

    if not applications:
        return ['0']

    # Total applications = per-planting apps * number of years
    total_apps = len(applications) * len(years)
    lines = [str(total_apps)]

    for ref_num, year in enumerate(years, start=1):
        for app in applications:
            timing = app.get('timing', 1)
            offset_days = app.get('offset_days', 0)
            method = app.get('method', 2)
            no3 = app.get('no3_kg_ha', 0.0)
            nh4 = app.get('nh4_kg_ha', 0.0)
            urea = app.get('urea_kg_ha', 0.0)
            bmp_chem = app.get('bmp_chem', 1)
            bmp_method = app.get('bmp_method', 1)
            split_days = app.get('split_min_days', 0)
            split_frac = app.get('split_starter_frac', 0.0)
            split_max = app.get('split_max_n', 0.0)
            p_mass = app.get('p_mass_kg_ha', 0.0)

            # For specified-date timing (5), compute absolute date
            if timing == 5:
                app_doy = planting_doy + offset_days
                if timing == 1:  # preplant: before planting
                    app_doy = planting_doy - offset_days
                a_dd, a_mm, a_yyyy = _doy_to_date(max(1, app_doy), year)
                line = (
                    f"{ref_num}  {timing}  {a_dd}  {a_mm}  {a_yyyy}  {method}  "
                    f"{no3:.1f}  {nh4:.1f}  {urea:.1f}  {bmp_chem}  {bmp_method}  "
                    f"{split_days}  {split_frac:.1f}  {split_max:.1f}  {p_mass:.1f}  "
                )
            else:
                # For relative timing (1-4,6-7):
                # Format: ref timing offset method NO3 NH4 UREA bmp_chem bmp_method split_days split_frac split_max p_mass
                line = (
                    f"{ref_num}  {timing}  {offset_days}  {method}  "
                    f"{no3:.1f}  {nh4:.1f}  {urea:.1f}  {bmp_chem}  {bmp_method}  "
                    f"{split_days}  {split_frac:.1f}  {split_max:.1f}  {p_mass:.1f}  "
                )

            lines.append(line)

    return lines


def _format_irrigation_lines(irrig_cfg, planting_doy, years):
    """
    Generate irrigation section data lines.

    For rainfed: just the control line with 0 operations.
    For irrigated: auto-irrigation with ET deficit timing.
    """
    is_irrigated = irrig_cfg.get('is_irrigated', False)

    if not is_irrigated:
        # Rainfed: 0 operations, standard control line
        return ['0  0  0  0.0  100.0  15.0  0.0  0  ']

    # Irrigated: one operation per year using timing=2 (specific dates)
    # This format matches all working RZWQM2 examples.
    # Do NOT use timing=4 (ET-deficit) — causes "INPUT INCORRECT FOR IRRIGATION => IDOI"
    num_ops = len(years)
    amount_cm = irrig_cfg.get('amount_cm', 5.0)  # default 5cm = 50mm per event
    lines = [f'{num_ops}  0  0  0.0  100.0  15.0  0.0  0  ']

    for ref_num, year in enumerate(years, start=1):
        harvest_doy = irrig_cfg.get('harvest_doy', planting_doy + 150)
        # Irrigate at mid-season (halfway between planting and harvest)
        if harvest_doy >= planting_doy:
            mid_doy = (planting_doy + harvest_doy) // 2
            mid_year = year
        else:
            mid_doy = (planting_doy + harvest_doy + 365) // 2
            if mid_doy > 365:
                mid_doy -= 365
                mid_year = year + 1
            else:
                mid_year = year
        i_dd, i_mm, i_yyyy = _doy_to_date(mid_doy, mid_year)

        # Rec 2: ref type=2(flood) timing=2(specific date) methodology=1(fixed amount)
        rec2 = f"{ref_num}  2  2  1 {i_dd} {i_mm} {i_yyyy}  {amount_cm:.1f}  1.0  0.9  "
        lines.append(rec2)

    return lines


def validate_inputs(project_path, station_id, management_config, simulation_years):
    """Validate inputs."""
    errors = []

    if not project_path:
        errors.append("project_path is required.")
    if not station_id:
        errors.append("station_id is required.")
    if not management_config:
        errors.append("management_config is required.")
    if not simulation_years:
        errors.append("simulation_years is required (list of years).")

    dat_path = os.path.join(project_path, station_id, 'RZWQM.dat')
    if project_path and station_id and not os.path.isfile(dat_path):
        alt_path = os.path.join(project_path, station_id, 'rzwqm.dat')
        if os.path.isfile(alt_path):
            dat_path = alt_path
        else:
            errors.append(f"RZWQM.dat not found at {dat_path}")

    if errors:
        return False, "; ".join(errors), None

    # Parse JSON strings if passed from CLI
    if isinstance(management_config, str):
        management_config = json.loads(management_config)
    if isinstance(simulation_years, str):
        simulation_years = json.loads(simulation_years)

    return True, "", {
        'project_path': project_path,
        'station_id': station_id,
        'management_config': management_config,
        'simulation_years': simulation_years,
        'dat_path': dat_path,
    }


def process(args):
    """Write management events to RZWQM.dat."""
    dat_path = args['dat_path']
    mgmt = args['management_config']
    years = args['simulation_years']

    try:
        # Read file
        with open(dat_path, encoding='ISO-8859-1') as f:
            lines = [line.rstrip('\n') for line in f]

        sections_written = []

        # --- Write planting section ---
        if 'planting' in mgmt:
            planting_cfg = mgmt['planting']
            start, end = _find_section(lines, PLANTING_HEAD, PLANTING_END)
            new_lines = _format_planting_lines(planting_cfg, years)
            lines = lines[:start] + new_lines + lines[end:]
            sections_written.append('planting')

        # --- Write fertilizer section ---
        if 'fertilizer' in mgmt:
            fert_cfg = mgmt['fertilizer']
            planting_doy = mgmt.get('planting', {}).get('planting_doy', 120)
            start, end = _find_section(lines, FERT_DATA_HEAD, FERT_END)
            new_lines = _format_fertilizer_lines(fert_cfg, planting_doy, years)
            lines = lines[:start] + new_lines + lines[end:]
            sections_written.append('fertilizer')

        # --- Write irrigation section ---
        if 'irrigation' in mgmt:
            irrig_cfg = mgmt['irrigation']
            planting_doy = mgmt.get('planting', {}).get('planting_doy', 120)
            irrig_cfg['harvest_doy'] = mgmt.get('planting', {}).get('harvest_doy', 280)
            start, end = _find_section(lines, IRRIG_HEAD, None)
            new_lines = _format_irrigation_lines(irrig_cfg, planting_doy, years)
            lines = lines[:start] + new_lines
            sections_written.append('irrigation')

        # Write back
        with open(dat_path, 'w', encoding='ISO-8859-1') as f:
            for line in lines:
                f.write(line + '\n')

        return True, "", {
            'dat_path': dat_path,
            'sections_written': sections_written,
            'num_plantings': len(years),
            'num_fert_apps': len(mgmt.get('fertilizer', {}).get('applications', [])) * len(years),
        }

    except Exception as e:
        return False, f"Processing error: {e}", None


def validate_outputs(result):
    """Check that at least one section was written."""
    if not result or not result.get('sections_written'):
        return False, "No management sections were written."
    return True, ""


def main():
    """CLI entry point."""
    if len(sys.argv) < 5:
        print(json.dumps({
            "status": "INPUT_ERROR",
            "message": "Usage: write_management_events.py <project_path> <station_id> <management_config_json> <years_json>"
        }))
        sys.exit(1)

    project_path = sys.argv[1]
    station_id = sys.argv[2]
    management_config = json.loads(sys.argv[3])
    simulation_years = json.loads(sys.argv[4])

    valid, err, args = validate_inputs(project_path, station_id, management_config, simulation_years)
    if not valid:
        print(json.dumps({"status": "INPUT_ERROR", "message": err}))
        sys.exit(1)

    success, err, result = process(args)
    if not success:
        print(json.dumps({"status": "PROCESSING_ERROR", "message": err}))
        sys.exit(2)

    valid, err = validate_outputs(result)
    if not valid:
        print(json.dumps({"status": "OUTPUT_ERROR", "message": err}))
        sys.exit(3)

    print(json.dumps({
        "status": "SUCCESS",
        "result": result,
        "message": f"Wrote {', '.join(result['sections_written'])} to {result['dat_path']}"
    }))
    sys.exit(0)


if __name__ == '__main__':
    main()
