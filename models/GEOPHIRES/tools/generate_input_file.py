#!/usr/bin/env python3
"""
Assemble a complete GEOPHIRES .txt input file from reservoir and economic parameter sets.

Merges parameters from multiple sources:
  - Reservoir parameter file (from convert_reservoir_params.py)
  - Economic parameter file (from convert_site_economics.py)
  - Additional override parameters (JSON)

Validates parameter combinations and warns about incompatible settings.

Usage:
    python generate_input_file.py \
        --reservoir reservoir_params.txt \
        --economics economics_params.txt \
        --overrides overrides.json \
        --output complete_input.txt
"""

import argparse
import json
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# --- Required parameter sets for each reservoir model ---
RESERVOIR_MODEL_PARAMS = {
    0: ['Reservoir Depth', 'Gradient 1'],  # Cylindrical
    1: ['Reservoir Depth', 'Gradient 1', 'Number of Fractures',
        'Fracture Shape'],  # Multiple Parallel Fractures
    2: ['Reservoir Depth', 'Gradient 1', 'Reservoir Porosity'],  # Linear Heat Sweep
    3: ['Reservoir Depth', 'Gradient 1', 'Fracture Shape'],  # Single Fracture
    4: ['Reservoir Depth', 'Gradient 1', 'Drawdown Parameter'],  # Percentage Drawdown
    5: ['Reservoir Depth'],  # User-Provided
    6: ['Reservoir Depth'],  # TOUGH2
    7: ['Reservoir Depth'],  # SUTRA
    8: ['Reservoir Depth'],  # SBT
}

# --- Required parameter sets for each economic model ---
ECONOMIC_MODEL_PARAMS = {
    1: ['Fixed Charge Rate'],
    2: ['Discount Rate'],
    3: ['Fraction of Investment in Bonds', 'Inflated Bond Interest Rate',
        'Inflated Equity Interest Rate', 'Inflation Rate', 'Combined Income Tax Rate'],
    4: [],  # CLGS simplified
    5: [],  # SAM (many optional params)
}

# --- End-use / plant type compatibility ---
ELECTRICITY_PLANT_TYPES = {1, 2, 3, 4}  # ORC, Flash
HEAT_PLANT_TYPES = {5, 6, 7, 8, 9}  # Chiller, HP, DH, SUTRA, Industrial


def validate_inputs(reservoir_path: Path = None, economics_path: Path = None,
                    overrides_path: Path = None) -> list:
    """Validate that input files exist."""
    issues = []

    if reservoir_path and not reservoir_path.exists():
        issues.append(f"WARNING: Reservoir parameter file not found: {reservoir_path}")
    if economics_path and not economics_path.exists():
        issues.append(f"WARNING: Economics parameter file not found: {economics_path}")
    if overrides_path and not overrides_path.exists():
        issues.append(f"ERROR: Overrides file not found: {overrides_path}")

    return issues


def parse_geophires_txt(path: Path) -> dict:
    """Parse a GEOPHIRES .txt parameter file into a dictionary."""
    params = {}
    if not path.exists():
        return params

    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        parts = line.split(',', 2)
        if len(parts) >= 2:
            name = parts[0].strip()
            value = parts[1].strip()
            params[name] = value

    return params


def validate_compatibility(params: dict) -> list:
    """Check parameter combinations for compatibility."""
    issues = []

    reservoir_model = int(float(params.get('Reservoir Model', 4)))
    econ_model = int(float(params.get('Economic Model', 1)))
    end_use = int(float(params.get('End-Use Option', 1)))
    plant_type = int(float(params.get('Power Plant Type', 9)))

    # Check reservoir model required params
    required = RESERVOIR_MODEL_PARAMS.get(reservoir_model, [])
    for p in required:
        if p not in params:
            issues.append(f"WARNING: Reservoir Model {reservoir_model} typically needs '{p}'")

    # Check economic model required params
    econ_required = ECONOMIC_MODEL_PARAMS.get(econ_model, [])
    for p in econ_required:
        if p not in params:
            issues.append(f"WARNING: Economic Model {econ_model} typically needs '{p}'")

    # Check end-use / plant type compatibility
    if end_use == 1 and plant_type in HEAT_PLANT_TYPES:
        issues.append(
            f"WARNING: End-Use=Electricity but Plant Type={plant_type} is heat-only. "
            "Results may be incorrect."
        )
    if end_use == 2 and plant_type in ELECTRICITY_PLANT_TYPES:
        issues.append(
            f"WARNING: End-Use=Direct-Use Heat but Plant Type={plant_type} is electricity-only. "
            "Consider using Industrial Heat (9) or District Heating (7)."
        )

    # Check for common mistakes
    depth = float(params.get('Reservoir Depth', 3.0))
    if depth > 100:
        issues.append(
            f"ERROR: Reservoir Depth={depth} is likely in meters, not km. "
            f"Expected range: 0.1-15 km."
        )

    gradient = float(params.get('Gradient 1', 50.0))
    if gradient < 1:
        issues.append(
            f"ERROR: Gradient 1={gradient} is likely in degC/m, not degC/km. "
            f"Expected range: 5-200 degC/km."
        )

    flow_rate = float(params.get('Production Flow Rate per Well', 55.0))
    if flow_rate > 500:
        issues.append(
            f"WARNING: Flow Rate={flow_rate} kg/s seems very high. "
            "Typical range: 20-150 kg/s."
        )

    fcr = float(params.get('Fixed Charge Rate', 0.05))
    if econ_model == 1 and fcr > 1:
        issues.append(
            f"ERROR: Fixed Charge Rate={fcr} appears to be a percentage. "
            "GEOPHIRES expects a fraction (e.g., 0.05 for 5%)."
        )

    return issues


def process(reservoir_path: Path = None, economics_path: Path = None,
            overrides: dict = None) -> dict:
    """Merge parameters from all sources.

    Priority: overrides > economics > reservoir (later source wins on conflict).
    """
    params = {}

    # Load reservoir params
    if reservoir_path and reservoir_path.exists():
        reservoir_params = parse_geophires_txt(reservoir_path)
        params.update(reservoir_params)
        logger.info(f"Loaded {len(reservoir_params)} reservoir parameters")

    # Load economics params
    if economics_path and economics_path.exists():
        econ_params = parse_geophires_txt(economics_path)
        params.update(econ_params)
        logger.info(f"Loaded {len(econ_params)} economic parameters")

    # Apply overrides
    if overrides:
        params.update(overrides)
        logger.info(f"Applied {len(overrides)} override parameters")

    return params


def write_input_file(params: dict, output_path: Path):
    """Write merged parameters as a GEOPHIRES .txt input file."""
    lines = [
        '# GEOPHIRES Input File',
        '# Generated by generate_input_file.py',
        f'# Parameters: {len(params)}',
        '',
        '# --- Reservoir Parameters ---',
    ]

    # Group parameters by category
    reservoir_keys = ['Reservoir Model', 'Reservoir Depth', 'Number of Segments',
                      'Gradient 1', 'Gradient 2', 'Gradient 3', 'Gradient 4',
                      'Maximum Temperature', 'Drawdown Parameter', 'Reservoir Porosity',
                      'Reservoir Heat Capacity', 'Reservoir Density',
                      'Reservoir Thermal Conductivity', 'Reservoir Volume',
                      'Fracture Shape', 'Fracture Height', 'Fracture Width',
                      'Fracture Area', 'Number of Fractures', 'Fracture Separation']

    well_keys = ['Number of Production Wells', 'Number of Injection Wells',
                 'Production Well Diameter', 'Injection Well Diameter',
                 'Production Flow Rate per Well', 'Injection Temperature',
                 'Production Wellbore Temperature Drop']

    plant_keys = ['End-Use Option', 'Power Plant Type', 'Plant Lifetime',
                  'Utilization Factor', 'Circulation Pump Efficiency',
                  'Surface Temperature', 'Time steps per year']

    econ_keys = ['Economic Model', 'Fixed Charge Rate', 'Discount Rate',
                 'Fraction of Investment in Bonds', 'Inflated Bond Interest Rate',
                 'Inflated Equity Interest Rate', 'Inflation Rate',
                 'Combined Income Tax Rate', 'Electricity Rate', 'Heat Rate']

    written = set()

    def write_group(keys, header):
        nonlocal lines
        group_lines = []
        for k in keys:
            if k in params:
                group_lines.append(f'{k},{params[k]},')
                written.add(k)
        if group_lines:
            lines.append(f'\n# --- {header} ---')
            lines.extend(group_lines)

    write_group(reservoir_keys, 'Reservoir Parameters')
    write_group(well_keys, 'Well Parameters')
    write_group(plant_keys, 'Surface Plant Parameters')
    write_group(econ_keys, 'Economic Parameters')

    # Write remaining parameters
    remaining = {k: v for k, v in params.items() if k not in written}
    if remaining:
        lines.append('\n# --- Additional Parameters ---')
        for k, v in remaining.items():
            lines.append(f'{k},{v},')

    output_path.write_text('\n'.join(lines) + '\n')
    logger.info(f"Wrote {len(params)} parameters to {output_path}")


def validate_outputs(params: dict) -> list:
    """Final validation of the assembled parameter set."""
    return validate_compatibility(params)


def main():
    parser = argparse.ArgumentParser(description='Generate GEOPHIRES input file')
    parser.add_argument('--reservoir', default=None, help='Reservoir parameter file (.txt)')
    parser.add_argument('--economics', default=None, help='Economics parameter file (.txt)')
    parser.add_argument('--overrides', default=None, help='Override parameters (JSON file)')
    parser.add_argument('--output', required=True, help='Output GEOPHIRES input file (.txt)')
    args = parser.parse_args()

    reservoir_path = Path(args.reservoir) if args.reservoir else None
    economics_path = Path(args.economics) if args.economics else None
    overrides_path = Path(args.overrides) if args.overrides else None

    # Validate inputs
    input_issues = validate_inputs(reservoir_path, economics_path, overrides_path)
    for issue in input_issues:
        if issue.startswith('ERROR'):
            logger.error(issue)
            sys.exit(1)
        else:
            logger.warning(issue)

    # Load overrides
    overrides = {}
    if overrides_path and overrides_path.exists():
        with open(overrides_path) as f:
            overrides = json.load(f)

    # Process
    params = process(reservoir_path, economics_path, overrides)

    if not params:
        logger.error("No parameters loaded. Provide at least one input source.")
        sys.exit(1)

    # Validate outputs
    output_issues = validate_outputs(params)
    for issue in output_issues:
        if issue.startswith('ERROR'):
            logger.error(issue)
        else:
            logger.warning(issue)

    # Write
    output_path = Path(args.output)
    write_input_file(params, output_path)

    print(json.dumps({
        'status': 'success',
        'n_params': len(params),
        'output_file': str(output_path),
        'errors': [i for i in output_issues if i.startswith('ERROR')],
        'warnings': [i for i in output_issues if i.startswith('WARNING')],
    }, indent=2))


if __name__ == '__main__':
    main()
