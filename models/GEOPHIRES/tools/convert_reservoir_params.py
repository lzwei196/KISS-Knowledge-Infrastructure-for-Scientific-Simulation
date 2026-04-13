#!/usr/bin/env python3
"""
Convert reservoir characterization data to GEOPHIRES input parameter format.

Handles unit conversions from common field/SI units to GEOPHIRES internal units:
  - Depth: meters -> km
  - Gradient: degC/m -> degC/km
  - Flow rate: m3/s or L/s -> kg/s
  - Well diameter: cm or m -> inches
  - Heat capacity: kJ/kg/K -> J/kg/K
  - Density: g/cm3 -> kg/m3
  - Thermal conductivity: mW/m/K -> W/m/K

Usage:
    python convert_reservoir_params.py --config reservoir_config.json --output reservoir_params.txt
"""

import argparse
import json
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# --- Validation ranges for GEOPHIRES parameters ---
PARAM_RANGES = {
    'Reservoir Depth': {'min': 0.1, 'max': 15.0, 'unit': 'km'},
    'Gradient 1': {'min': 5.0, 'max': 200.0, 'unit': 'degC/km'},
    'Gradient 2': {'min': 0.0, 'max': 200.0, 'unit': 'degC/km'},
    'Gradient 3': {'min': 0.0, 'max': 200.0, 'unit': 'degC/km'},
    'Gradient 4': {'min': 0.0, 'max': 200.0, 'unit': 'degC/km'},
    'Maximum Temperature': {'min': 50.0, 'max': 600.0, 'unit': 'degC'},
    'Number of Production Wells': {'min': 1, 'max': 100, 'unit': '-'},
    'Number of Injection Wells': {'min': 1, 'max': 100, 'unit': '-'},
    'Production Well Diameter': {'min': 1.0, 'max': 20.0, 'unit': 'inch'},
    'Injection Well Diameter': {'min': 1.0, 'max': 20.0, 'unit': 'inch'},
    'Production Flow Rate per Well': {'min': 1.0, 'max': 500.0, 'unit': 'kg/s'},
    'Injection Temperature': {'min': 10.0, 'max': 200.0, 'unit': 'degC'},
    'Reservoir Heat Capacity': {'min': 100.0, 'max': 5000.0, 'unit': 'J/kg/K'},
    'Reservoir Density': {'min': 1000.0, 'max': 4000.0, 'unit': 'kg/m3'},
    'Reservoir Thermal Conductivity': {'min': 0.5, 'max': 10.0, 'unit': 'W/m/K'},
    'Drawdown Parameter': {'min': 0.0, 'max': 0.1, 'unit': '1/year'},
    'Number of Fractures': {'min': 1, 'max': 1000000, 'unit': '-'},
    'Fracture Height': {'min': 10.0, 'max': 5000.0, 'unit': 'm'},
    'Fracture Width': {'min': 10.0, 'max': 5000.0, 'unit': 'm'},
    'Number of Segments': {'min': 1, 'max': 4, 'unit': '-'},
    'Reservoir Model': {'min': 0, 'max': 8, 'unit': '-'},
}

# --- Unit conversion functions ---
CONVERSIONS = {
    'depth_m_to_km': lambda x: x / 1000.0,
    'gradient_degC_per_m_to_degC_per_km': lambda x: x * 1000.0,
    'flow_m3s_to_kgs': lambda x, density=958.0: x * density,
    'flow_Ls_to_kgs': lambda x, density=958.0: x * density / 1000.0,
    'diameter_cm_to_inch': lambda x: x / 2.54,
    'diameter_m_to_inch': lambda x: x * 39.3701,
    'heat_capacity_kJ_to_J': lambda x: x * 1000.0,
    'density_gcm3_to_kgm3': lambda x: x * 1000.0,
    'conductivity_mW_to_W': lambda x: x / 1000.0,
}


def validate_inputs(config: dict) -> list:
    """Validate input configuration before processing.

    Returns:
        List of warning/error messages. Empty list means all valid.
    """
    issues = []

    # Check required fields
    required = ['reservoir_model']
    for field in required:
        if field not in config:
            issues.append(f"ERROR: Missing required field '{field}'")

    # Check depth is specified
    if 'depth_km' not in config and 'depth_m' not in config:
        issues.append("ERROR: Must specify either 'depth_km' or 'depth_m'")

    # Check gradient
    if 'gradient_degC_per_km' not in config and 'gradient_degC_per_m' not in config:
        issues.append("WARNING: No gradient specified; GEOPHIRES will use default (50 degC/km)")

    # Validate reservoir model ID
    model_id = config.get('reservoir_model', 4)
    if model_id not in range(9):
        issues.append(f"ERROR: Invalid reservoir_model={model_id}. Must be 0-8.")

    return issues


def convert_depth(config: dict) -> float:
    """Convert depth to km."""
    if 'depth_km' in config:
        return float(config['depth_km'])
    elif 'depth_m' in config:
        depth_km = CONVERSIONS['depth_m_to_km'](float(config['depth_m']))
        logger.info(f"Converted depth: {config['depth_m']} m -> {depth_km:.3f} km")
        return depth_km
    return 3.0  # default


def convert_gradient(config: dict) -> list:
    """Convert gradient(s) to degC/km. Returns list of up to 4 gradients."""
    gradients = []
    for i in range(1, 5):
        key_km = f'gradient{i}_degC_per_km'
        key_m = f'gradient{i}_degC_per_m'
        key_simple = 'gradient_degC_per_km' if i == 1 else None
        key_simple_m = 'gradient_degC_per_m' if i == 1 else None

        if key_km in config:
            gradients.append(float(config[key_km]))
        elif key_m in config:
            val = CONVERSIONS['gradient_degC_per_m_to_degC_per_km'](float(config[key_m]))
            logger.info(f"Converted gradient {i}: {config[key_m]} degC/m -> {val:.2f} degC/km")
            gradients.append(val)
        elif key_simple and key_simple in config:
            gradients.append(float(config[key_simple]))
        elif key_simple_m and key_simple_m in config:
            val = CONVERSIONS['gradient_degC_per_m_to_degC_per_km'](float(config[key_simple_m]))
            logger.info(f"Converted gradient: {config[key_simple_m]} degC/m -> {val:.2f} degC/km")
            gradients.append(val)

    if not gradients:
        gradients = [50.0]  # default
        logger.warning("No gradient specified, using default 50 degC/km")

    return gradients


def convert_flow_rate(config: dict) -> float:
    """Convert flow rate to kg/s."""
    density = float(config.get('fluid_density_kg_m3', 958.0))

    if 'flow_rate_kg_per_s' in config:
        return float(config['flow_rate_kg_per_s'])
    elif 'flow_rate_m3_per_s' in config:
        val = CONVERSIONS['flow_m3s_to_kgs'](float(config['flow_rate_m3_per_s']), density)
        logger.info(f"Converted flow: {config['flow_rate_m3_per_s']} m3/s -> {val:.1f} kg/s "
                     f"(density={density} kg/m3)")
        return val
    elif 'flow_rate_L_per_s' in config:
        val = CONVERSIONS['flow_Ls_to_kgs'](float(config['flow_rate_L_per_s']), density)
        logger.info(f"Converted flow: {config['flow_rate_L_per_s']} L/s -> {val:.1f} kg/s "
                     f"(density={density} kg/m3)")
        return val
    return 55.0  # default


def convert_well_diameter(config: dict, key_prefix: str = 'production') -> float:
    """Convert well diameter to inches."""
    key_inch = f'{key_prefix}_well_diameter_inch'
    key_cm = f'{key_prefix}_well_diameter_cm'
    key_m = f'{key_prefix}_well_diameter_m'

    if key_inch in config:
        return float(config[key_inch])
    elif key_cm in config:
        val = CONVERSIONS['diameter_cm_to_inch'](float(config[key_cm]))
        logger.info(f"Converted {key_prefix} well diameter: {config[key_cm]} cm -> {val:.2f} inches")
        return val
    elif key_m in config:
        val = CONVERSIONS['diameter_m_to_inch'](float(config[key_m]))
        logger.info(f"Converted {key_prefix} well diameter: {config[key_m]} m -> {val:.2f} inches")
        return val
    return 7.0  # default


def process(config: dict) -> dict:
    """Process reservoir configuration and return GEOPHIRES parameters.

    Args:
        config: Dictionary with reservoir characterization data.

    Returns:
        Dictionary of GEOPHIRES parameter name -> value pairs.
    """
    params = {}

    # Reservoir model
    params['Reservoir Model'] = int(config.get('reservoir_model', 4))

    # Depth
    params['Reservoir Depth'] = convert_depth(config)

    # Segments
    n_segments = int(config.get('number_of_segments', 1))
    params['Number of Segments'] = n_segments

    # Gradients
    gradients = convert_gradient(config)
    for i, g in enumerate(gradients, 1):
        params[f'Gradient {i}'] = g

    # Maximum temperature
    if 'maximum_temperature_degC' in config:
        params['Maximum Temperature'] = float(config['maximum_temperature_degC'])

    # Wells
    params['Number of Production Wells'] = int(config.get('n_production_wells', 2))
    params['Number of Injection Wells'] = int(config.get('n_injection_wells', 2))
    params['Production Well Diameter'] = convert_well_diameter(config, 'production')
    params['Injection Well Diameter'] = convert_well_diameter(config, 'injection')

    # Flow rate
    params['Production Flow Rate per Well'] = convert_flow_rate(config)

    # Temperatures
    if 'injection_temperature_degC' in config:
        params['Injection Temperature'] = float(config['injection_temperature_degC'])

    # Rock properties
    if 'heat_capacity_J_per_kgK' in config:
        params['Reservoir Heat Capacity'] = float(config['heat_capacity_J_per_kgK'])
    elif 'heat_capacity_kJ_per_kgK' in config:
        val = CONVERSIONS['heat_capacity_kJ_to_J'](float(config['heat_capacity_kJ_per_kgK']))
        logger.info(f"Converted heat capacity: {config['heat_capacity_kJ_per_kgK']} kJ/kg/K -> {val:.0f} J/kg/K")
        params['Reservoir Heat Capacity'] = val

    if 'density_kg_per_m3' in config:
        params['Reservoir Density'] = float(config['density_kg_per_m3'])
    elif 'density_g_per_cm3' in config:
        val = CONVERSIONS['density_gcm3_to_kgm3'](float(config['density_g_per_cm3']))
        logger.info(f"Converted density: {config['density_g_per_cm3']} g/cm3 -> {val:.0f} kg/m3")
        params['Reservoir Density'] = val

    if 'thermal_conductivity_W_per_mK' in config:
        params['Reservoir Thermal Conductivity'] = float(config['thermal_conductivity_W_per_mK'])

    # Fracture parameters (for models 1, 3)
    if params['Reservoir Model'] in (1, 3):
        if 'fracture_shape' in config:
            params['Fracture Shape'] = int(config['fracture_shape'])
        if 'fracture_height_m' in config:
            params['Fracture Height'] = float(config['fracture_height_m'])
        if 'fracture_width_m' in config:
            params['Fracture Width'] = float(config['fracture_width_m'])
        if 'number_of_fractures' in config:
            params['Number of Fractures'] = int(config['number_of_fractures'])
        if 'fracture_separation_m' in config:
            params['Fracture Separation'] = float(config['fracture_separation_m'])

    # Drawdown parameter (for model 4)
    if params['Reservoir Model'] == 4:
        if 'drawdown_parameter' in config:
            params['Drawdown Parameter'] = float(config['drawdown_parameter'])

    # Porosity (for model 2)
    if params['Reservoir Model'] == 2:
        if 'porosity' in config:
            params['Reservoir Porosity'] = float(config['porosity'])

    return params


def validate_outputs(params: dict) -> list:
    """Validate converted parameters against GEOPHIRES ranges.

    Returns:
        List of warning/error messages.
    """
    issues = []

    for name, value in params.items():
        if name in PARAM_RANGES:
            r = PARAM_RANGES[name]
            if value < r['min'] or value > r['max']:
                issues.append(
                    f"WARNING: {name} = {value} is outside expected range "
                    f"[{r['min']}, {r['max']}] {r['unit']}"
                )

    # Cross-parameter checks
    depth = params.get('Reservoir Depth', 3.0)
    gradient = params.get('Gradient 1', 50.0)
    max_temp = params.get('Maximum Temperature', 400.0)
    bottom_hole = depth * gradient + 15.0  # approximate (surface temp ~15C)

    if bottom_hole > max_temp:
        issues.append(
            f"INFO: Bottom-hole temperature ({bottom_hole:.0f}°C) exceeds Maximum Temperature "
            f"({max_temp:.0f}°C). Temperature will be capped."
        )

    return issues


def format_geophires_line(name: str, value, comment: str = '') -> str:
    """Format a single GEOPHIRES input line."""
    comment_str = f'                        ---{comment}' if comment else ''
    return f'{name},{value},{comment_str}'


def write_params(params: dict, output_path: Path):
    """Write parameters to GEOPHIRES input format."""
    lines = ['# Reservoir parameters generated by convert_reservoir_params.py']
    lines.append(f'# Generated parameters: {len(params)}')
    lines.append('')

    unit_comments = {
        'Reservoir Depth': '[km]',
        'Gradient 1': '[degC/km]', 'Gradient 2': '[degC/km]',
        'Gradient 3': '[degC/km]', 'Gradient 4': '[degC/km]',
        'Maximum Temperature': '[degC]',
        'Production Well Diameter': '[inch]',
        'Injection Well Diameter': '[inch]',
        'Production Flow Rate per Well': '[kg/s]',
        'Injection Temperature': '[degC]',
        'Reservoir Heat Capacity': '[J/kg/K]',
        'Reservoir Density': '[kg/m3]',
        'Reservoir Thermal Conductivity': '[W/m/K]',
        'Fracture Height': '[m]', 'Fracture Width': '[m]',
        'Fracture Separation': '[m]',
        'Drawdown Parameter': '[1/year]',
    }

    for name, value in params.items():
        comment = unit_comments.get(name, '')
        lines.append(format_geophires_line(name, value, comment))

    output_path.write_text('\n'.join(lines) + '\n')
    logger.info(f"Wrote {len(params)} parameters to {output_path}")


def main():
    parser = argparse.ArgumentParser(description='Convert reservoir data to GEOPHIRES parameters')
    parser.add_argument('--config', required=True, help='JSON config file with reservoir data')
    parser.add_argument('--output', required=True, help='Output GEOPHIRES parameter file (.txt)')
    args = parser.parse_args()

    config_path = Path(args.config)
    output_path = Path(args.output)

    if not config_path.exists():
        logger.error(f"Config file not found: {config_path}")
        sys.exit(1)

    with open(config_path) as f:
        config = json.load(f)

    # Validate inputs
    input_issues = validate_inputs(config)
    for issue in input_issues:
        if issue.startswith('ERROR'):
            logger.error(issue)
        else:
            logger.warning(issue)

    if any(i.startswith('ERROR') for i in input_issues):
        logger.error("Input validation failed. Fix errors and retry.")
        sys.exit(1)

    # Process
    params = process(config)

    # Validate outputs
    output_issues = validate_outputs(params)
    for issue in output_issues:
        logger.warning(issue)

    # Write
    write_params(params, output_path)

    # Summary
    print(json.dumps({
        'status': 'success',
        'n_params': len(params),
        'output_file': str(output_path),
        'warnings': [i for i in output_issues if i.startswith('WARNING')],
    }, indent=2))


if __name__ == '__main__':
    main()
