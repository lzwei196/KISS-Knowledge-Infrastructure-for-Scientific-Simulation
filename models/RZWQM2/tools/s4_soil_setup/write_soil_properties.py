#!/usr/bin/env python3
"""
write_soil_properties.py
========================
Write complete soil properties to RZWQM.dat: horizon depths, physical
properties, hydraulic properties (Brooks-Corey), heat model, micropore,
macropore, and infiltration parameters.

All soil sections are written atomically to ensure consistent horizon counts
across sections. This prevents the fatal "things went wrong when adjusting
the calibration input" error (dt_005).

Uses multiple write methods from the RZWQM class in rzwqm_file.py.

Inputs:
    project_path    - RZWQM2 project root path
    station_id      - Station or grid identifier
    soil_config     - JSON file or JSON string with soil properties per horizon

Exit codes:
    0 - Success
    1 - Input validation error
    2 - Processing error
    3 - Output validation error
"""

import sys
import os
import json

# ---------------------------------------------------------------------------
# INPUTS
# ---------------------------------------------------------------------------
PROJECT_PATH = ""       # RZWQM2 project root path
STATION_ID = ""         # Station or grid identifier
SOIL_CONFIG = ""        # JSON file path or JSON string with soil configuration

# ---------------------------------------------------------------------------
# Add lib to path
# ---------------------------------------------------------------------------
DATA_PREP_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'lib')
sys.path.insert(0, os.path.abspath(DATA_PREP_DIR))


def validate_inputs(project_path, station_id, soil_config_raw):
    """Validate inputs. Returns (valid, error_msg, parsed_args)."""
    errors = []

    if not project_path:
        errors.append("PROJECT_PATH is required.")
    elif not os.path.isdir(project_path):
        errors.append(f"PROJECT_PATH does not exist: {project_path}")

    if not station_id:
        errors.append("STATION_ID is required.")

    if not soil_config_raw:
        errors.append("SOIL_CONFIG is required (JSON file path or JSON string).")

    # Parse soil config
    soil_config = None
    if soil_config_raw:
        if os.path.isfile(soil_config_raw):
            try:
                with open(soil_config_raw) as f:
                    soil_config = json.load(f)
            except json.JSONDecodeError as e:
                errors.append(f"Invalid JSON in soil config file: {e}")
        else:
            try:
                soil_config = json.loads(soil_config_raw)
            except json.JSONDecodeError as e:
                errors.append(f"SOIL_CONFIG is not a valid file path or JSON string: {e}")

    if soil_config is not None:
        if 'horizons' not in soil_config:
            errors.append("SOIL_CONFIG must have a 'horizons' key with a list of horizon configs.")
        elif not isinstance(soil_config['horizons'], list) or len(soil_config['horizons']) == 0:
            errors.append("SOIL_CONFIG 'horizons' must be a non-empty list.")

    # Check RZWQM.dat exists
    dat_path = None
    if project_path and station_id:
        dat_path = os.path.join(project_path, station_id, 'RZWQM.dat')
        if not os.path.isfile(dat_path):
            alt_path = os.path.join(project_path, station_id, 'rzwqm.dat')
            if os.path.isfile(alt_path):
                dat_path = alt_path
            else:
                errors.append(f"RZWQM.dat not found: {dat_path}")

    if errors:
        return False, "; ".join(errors), None

    return True, "", {
        'project_path': project_path,
        'station_id': station_id,
        'soil_config': soil_config,
        'dat_path': dat_path
    }


def process(args):
    """
    Write ALL soil properties to RZWQM.dat atomically.

    Writes 7 sections in order (matching rzwqm_scenario_mass_generation):
      1. Horizon depths + node discretization
      2. Physical properties (bulk_density, particle_density, porosity, sand, silt, clay)
      3. Hydraulic properties (Brooks-Corey: bubbling_pressure, pore_size_dist, ksat, ws, wr, fc33, fc10, fc15)
      4. Heat model properties
      5. Micropore properties (texture-based defaults)
      6. Macropore properties (general + per-horizon)
      7. Infiltration properties (single line, 19 parameters)

    All sections use the same horizon count to prevent dt_005 fatal error.

    Returns (success, error_msg, summary).
    """
    from rzwqm_file import (RZWQM, soil_hydraulic_properties_each_horizon,
                             soil_physical_properties_each_horizon,
                             soil_infiltration_properties,
                             soil_macropore_properties_each_horizon,
                             soil_macropore_general_properties,
                             soil_texture_setter,
                             default_microporosity_for_each_soil_type)

    project_path = args['project_path']
    station_id = args['station_id']
    soil_config = args['soil_config']
    horizons = soil_config['horizons']
    num_horizons = len(horizons)
    particle_density = 2.65

    try:
        rz = RZWQM(project_path, station_id)

        # --- Step 1: Write horizon depths + node discretization ---
        horizon_depths = [h['depth_cm'] for h in horizons]
        rz.insert_new_horizon_to_existing_dat_file(horizon_depths)
        sections_written = ['horizon_depths', 'node_discretization']

        # --- Step 2: Write physical properties ---
        # (bulk_density, particle_density, porosity, sand, silt, clay)
        physical_dict = {}
        for i, h in enumerate(horizons):
            horizon_num = i + 1
            sand = h.get('sand_pct', 40) / 100.0 if h.get('sand_pct') else 0.40
            clay = h.get('clay_pct', 20) / 100.0 if h.get('clay_pct') else 0.20
            silt = 1.0 - sand - clay
            bd = h.get('bulk_density_gcc', 1.4)
            physical_dict[horizon_num] = soil_physical_properties_each_horizon(
                bulk_density=bd,
                particle_density=particle_density,
                sand=round(sand, 2),
                silt=round(silt, 2),
                clay=round(clay, 2)
            )
        rz.write_new_soil_physical_properties_to_dat(physical_dict)
        sections_written.append('physical')

        # --- Step 3: Write hydraulic properties (Brooks-Corey) ---
        # Uses values from soil_config horizons directly (already computed
        # by soil_source_adapter or vic_soil_converter with pedotransfer)
        hydraulic_dict = {}
        for i, h in enumerate(horizons):
            horizon_num = i + 1
            hydraulic_dict[horizon_num] = soil_hydraulic_properties_each_horizon(
                pore_size_dist=h.get('pore_size_dist', 0.5),
                saturated_water_content=h.get('ws', 0.45),
                residual_water_content=h.get('wr', 0.05),
                bubbling_pressure=h.get('bubbling_pressure', 20.0),
                constant_for_oh=0,
                lateral_ksat=h.get('ksat_cm_hr', h.get('ksat', 1.0)),
                ksat=h.get('ksat_cm_hr', h.get('ksat', 1.0)),
                eps=h.get('N2', 12.0),
                second_intercept_c2=h.get('C2', h.get('c2', 0.0)),
                horizon_num=horizon_num,
                fc33=h.get('fc33', 0.3),
                fc10=h.get('fc10', 0.35),
                fc15=h.get('fc15', 0.15)
            )
        rz.write_new_hydraulic_properties_to_dat(hydraulic_dict)
        sections_written.append('hydraulic')

        # --- Step 4: Write heat model properties ---
        # Original mass_generation uses: '2  0.00111  ' per layer
        heat_dict = {}
        for i in range(num_horizons):
            heat_dict[i] = '2  0.00111  '
        rz.write_new_soil_heat_properties_to_dat(heat_dict)
        sections_written.append('heat')

        # --- Step 5: Write micropore properties ---
        # Uses texture-based defaults from default_microporosity_for_each_soil_type()
        micropore_dict = {}
        for i, h in enumerate(horizons):
            sand = h.get('sand_pct', 40) / 100.0 if h.get('sand_pct') else 0.40
            clay = h.get('clay_pct', 20) / 100.0 if h.get('clay_pct') else 0.20
            texture = h.get('texture_class')
            if not texture:
                try:
                    texture = soil_texture_setter(sand, clay)
                except Exception:
                    texture = 'loam'
            try:
                micropore_val = default_microporosity_for_each_soil_type(texture)
            except Exception:
                micropore_val = 0.254  # loam default
            if micropore_val is None:
                micropore_val = 0.254
            micropore_dict[i] = micropore_val
        rz.write_new_soil_micropore_properties_to_dat(micropore_dict)
        sections_written.append('micropore')

        # --- Step 6: Write macropore properties ---
        # General macropore settings (single header) + per-horizon values
        macro_general = soil_macropore_general_properties(
            macropores_present=0,
            sorptivity_factor=1,
            tile_drain_express=0,
            radial_holes=0.5,
            cracks_columns=0.5
        )
        macro_dict = {}
        for i in range(num_horizons):
            macro_dict[i] = soil_macropore_properties_each_horizon(
                total_macroporosity=0.01,
                average_radius=0.0,
                width=0.05,
                crack_length=10.0,
                length_of_aggregate=10.0,
                fraction_of_dead_end=0.5
            )
        rz.write_new_soil_macropore_properties_to_dat(macro_dict, macro_general)
        sections_written.append('macropore')

        # --- Step 7: Write infiltration properties ---
        # Single line with 19 parameters (same defaults as original mass_generation)
        infil = soil_infiltration_properties(
            surface_crust_present=0,
            crust_hydraulic_conductivity=0.4285,
            bottom_boundry_condition=2,
            Field_saturation_fraction=0.99,
            Convergence_Criteria='1.000E-05',
            Maximum_number_of_iterations=4000,
            Maximum_number_of_cycles=2,
            Management_cutoff_threshold_for_soil_moisture_content=0.99,
            Perched_water_table=0,
            water_table_leakage_rate='1.000E-09',
            Drains_are_present=0,
            depth_from_surface_to_drains=10.0,
            drain_spacing=1000.0,
            radius_of_drain=20.0,
            Init_gradient_flow=0,
            Lateral_hydraulic_gradient='1.0000E-04',
            Minimum_water_suction_head=-15000,
            Field_Capacity_water_suction_head=-333.0,
            Wilting_Point_water_suction_head=-15000
        )
        rz.write_new_soil_infiltration_to_dat(infil)
        sections_written.append('infiltration')

        # Count nodes for summary
        try:
            nodes = rz.parse_soil_discretization_nodes()
            num_nodes = len(nodes)
        except Exception:
            num_nodes = 0

        summary = {
            'num_horizons': num_horizons,
            'horizon_depths_cm': horizon_depths,
            'num_nodes': num_nodes,
            'sections_written': sections_written,
        }

        return True, "", summary

    except Exception as e:
        return False, f"Processing error: {e}", None


def validate_outputs(args):
    """Verify that soil properties were written consistently."""
    from rzwqm_file import RZWQM

    errors = []

    try:
        rz = RZWQM(args['project_path'], args['station_id'])
        num_horizons = rz.return_number_of_soil_horizons()

        if num_horizons == 0:
            errors.append("No soil horizons found after write.")

        expected = len(args['soil_config']['horizons'])
        if num_horizons != expected:
            errors.append(
                f"Horizon count mismatch: expected {expected}, found {num_horizons}."
            )

        # Check hydraulic section has correct number of entries
        head, end = rz.line_number_of_soil_hydraulic()
        hydraulic_lines = end - head + 1
        expected_lines = num_horizons * 3
        if hydraulic_lines != expected_lines:
            errors.append(
                f"Hydraulic section has {hydraulic_lines} lines, "
                f"expected {expected_lines} (3 per horizon)."
            )

    except Exception as e:
        errors.append(f"Could not verify outputs: {e}")

    if errors:
        return False, "; ".join(errors)
    return True, ""


def main():
    project_path = sys.argv[1] if len(sys.argv) > 1 else PROJECT_PATH
    station_id = sys.argv[2] if len(sys.argv) > 2 else STATION_ID
    soil_config_raw = sys.argv[3] if len(sys.argv) > 3 else SOIL_CONFIG

    # Ensure project_path ends with separator for RZWQM class compatibility
    if project_path and not project_path.endswith(('/', '\\')):
        project_path = project_path + '/'

    # --- Step 1: Validate inputs ---
    valid, err, args = validate_inputs(project_path, station_id, soil_config_raw)
    if not valid:
        print(json.dumps({"status": "INPUT_ERROR", "message": err}))
        sys.exit(1)

    # --- Step 2: Process ---
    success, err, summary = process(args)
    if not success:
        print(json.dumps({"status": "PROCESSING_ERROR", "message": err}))
        sys.exit(2)

    # --- Step 3: Validate outputs ---
    valid, err = validate_outputs(args)
    if not valid:
        print(json.dumps({"status": "OUTPUT_ERROR", "message": err}))
        sys.exit(3)

    print(json.dumps({
        "status": "SUCCESS",
        "dat_file": args['dat_path'],
        "summary": summary,
        "message": (
            f"Soil properties written for {summary['num_horizons']} horizons "
            f"(depths: {summary['horizon_depths_cm']} cm). "
            f"{summary['num_nodes']} computational nodes generated."
        )
    }))
    sys.exit(0)


if __name__ == '__main__':
    main()
