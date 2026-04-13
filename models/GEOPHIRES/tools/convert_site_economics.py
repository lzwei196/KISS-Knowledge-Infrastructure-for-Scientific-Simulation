#!/usr/bin/env python3
"""
Convert economic/financial site data to GEOPHIRES economic input parameters.

Supports all 5 GEOPHIRES economic models:
  1. Fixed Charge Rate (FCR)
  2. Standard Levelized Cost
  3. BICYCLE
  4. CLGS (Closed-Loop Geothermal System)
  5. SAM Single Owner PPA

Handles conversions:
  - Percent to fraction (e.g., 5% -> 0.05)
  - Currency normalization (USD assumed)
  - End-use option mapping

Usage:
    python convert_site_economics.py --config economics_config.json --output economics_params.txt
"""

import argparse
import json
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# --- Valid ranges for economic parameters ---
ECONOMIC_RANGES = {
    'Economic Model': {'min': 1, 'max': 5, 'unit': '-'},
    'End-Use Option': {'min': 1, 'max': 52, 'unit': '-'},
    'Power Plant Type': {'min': 1, 'max': 9, 'unit': '-'},
    'Fixed Charge Rate': {'min': 0.01, 'max': 0.20, 'unit': 'fraction'},
    'Discount Rate': {'min': 0.01, 'max': 0.30, 'unit': 'fraction'},
    'Inflation Rate During Construction': {'min': 0.0, 'max': 0.15, 'unit': 'fraction'},
    'Plant Lifetime': {'min': 10, 'max': 100, 'unit': 'yr'},
    'Utilization Factor': {'min': 0.1, 'max': 1.0, 'unit': 'fraction'},
    'Circulation Pump Efficiency': {'min': 0.1, 'max': 1.0, 'unit': 'fraction'},
    'Surface Temperature': {'min': -30.0, 'max': 50.0, 'unit': 'degC'},
    'Electricity Rate': {'min': 0.0, 'max': 1.0, 'unit': '$/kWh'},
    'Heat Rate': {'min': 0.0, 'max': 100.0, 'unit': '$/MMBTU'},
    'Time steps per year': {'min': 1, 'max': 36, 'unit': '-'},
    # BICYCLE model parameters
    'Fraction of Investment in Bonds': {'min': 0.0, 'max': 1.0, 'unit': 'fraction'},
    'Inflated Bond Interest Rate': {'min': 0.0, 'max': 0.30, 'unit': 'fraction'},
    'Inflated Equity Interest Rate': {'min': 0.0, 'max': 0.50, 'unit': 'fraction'},
    'Inflation Rate': {'min': 0.0, 'max': 0.15, 'unit': 'fraction'},
    'Combined Income Tax Rate': {'min': 0.0, 'max': 0.60, 'unit': 'fraction'},
}

# End-use option mapping
END_USE_MAP = {
    'electricity': 1,
    'direct_use_heat': 2,
    'heat': 2,
    'cogen_topping_elec': 31,
    'cogen_topping_heat': 32,
    'cogen_bottoming_elec': 41,
    'cogen_bottoming_heat': 42,
    'cogen_parallel_elec': 51,
    'cogen_parallel_heat': 52,
}

# Plant type mapping
PLANT_TYPE_MAP = {
    'subcritical_orc': 1,
    'supercritical_orc': 2,
    'single_flash': 3,
    'double_flash': 4,
    'absorption_chiller': 5,
    'heat_pump': 6,
    'district_heating': 7,
    'sutra': 8,
    'industrial_heat': 9,
}


def validate_inputs(config: dict) -> list:
    """Validate input configuration."""
    issues = []

    econ_model = config.get('economic_model', 1)
    if econ_model not in range(1, 6):
        issues.append(f"ERROR: economic_model={econ_model} invalid. Must be 1-5.")

    # Model-specific required fields
    if econ_model == 1:
        if 'fixed_charge_rate' not in config and 'fixed_charge_rate_percent' not in config:
            issues.append("WARNING: FCR model (1) requires 'fixed_charge_rate'. Using default 0.05.")
    elif econ_model == 2:
        if 'discount_rate' not in config and 'discount_rate_percent' not in config:
            issues.append("WARNING: Standard model (2) requires 'discount_rate'. Using default 0.05.")
    elif econ_model == 3:
        bicycle_required = ['fraction_investment_bonds', 'bond_interest_rate',
                            'equity_interest_rate', 'inflation_rate', 'combined_tax_rate']
        missing = [f for f in bicycle_required if f not in config
                   and f'{f}_percent' not in config]
        if missing:
            issues.append(f"WARNING: BICYCLE model (3) ideally needs: {', '.join(missing)}")

    return issues


def convert_rate(config: dict, key: str, default: float = 0.05) -> float:
    """Convert a rate that may be given as fraction or percent."""
    if key in config:
        val = float(config[key])
        # Auto-detect if given as percent
        if val > 1.0:
            logger.warning(f"'{key}' = {val} appears to be a percentage. Converting to fraction: {val/100}")
            return val / 100.0
        return val
    elif f'{key}_percent' in config:
        val = float(config[f'{key}_percent']) / 100.0
        logger.info(f"Converted {key}: {config[f'{key}_percent']}% -> {val}")
        return val
    return default


def process(config: dict) -> dict:
    """Process economic configuration and return GEOPHIRES parameters."""
    params = {}

    # Economic model
    econ_model = int(config.get('economic_model', 1))
    params['Economic Model'] = econ_model

    # End-use option
    end_use = config.get('end_use_option', 'electricity')
    if isinstance(end_use, str):
        end_use = END_USE_MAP.get(end_use.lower(), 1)
    params['End-Use Option'] = int(end_use)

    # Power plant type
    plant_type = config.get('power_plant_type', None)
    if plant_type is not None:
        if isinstance(plant_type, str):
            plant_type = PLANT_TYPE_MAP.get(plant_type.lower(), 9)
        params['Power Plant Type'] = int(plant_type)

    # Plant lifetime
    params['Plant Lifetime'] = int(config.get('plant_lifetime_years', 30))

    # Utilization factor
    if 'utilization_factor' in config:
        params['Utilization Factor'] = float(config['utilization_factor'])

    # Pump efficiency
    if 'pump_efficiency' in config:
        params['Circulation Pump Efficiency'] = float(config['pump_efficiency'])

    # Surface temperature
    if 'surface_temperature_degC' in config:
        params['Surface Temperature'] = float(config['surface_temperature_degC'])

    # Time steps
    if 'time_steps_per_year' in config:
        params['Time steps per year'] = int(config['time_steps_per_year'])

    # Print output control
    params['Print Output to Console'] = int(config.get('print_to_console', 0))

    # --- Model-specific parameters ---

    if econ_model == 1:  # FCR
        params['Fixed Charge Rate'] = convert_rate(config, 'fixed_charge_rate', 0.05)

    elif econ_model == 2:  # Standard Levelized Cost
        params['Discount Rate'] = convert_rate(config, 'discount_rate', 0.05)

    elif econ_model == 3:  # BICYCLE
        params['Fraction of Investment in Bonds'] = convert_rate(
            config, 'fraction_investment_bonds', 0.5)
        params['Inflated Bond Interest Rate'] = convert_rate(
            config, 'bond_interest_rate', 0.05)
        params['Inflated Equity Interest Rate'] = convert_rate(
            config, 'equity_interest_rate', 0.10)
        params['Inflation Rate'] = convert_rate(
            config, 'inflation_rate', 0.025)
        params['Combined Income Tax Rate'] = convert_rate(
            config, 'combined_tax_rate', 0.30)

    elif econ_model == 5:  # SAM PPA
        if 'sam_ppa_params' in config:
            for k, v in config['sam_ppa_params'].items():
                params[k] = v

    # Revenue parameters
    if 'electricity_rate_usd_per_kwh' in config:
        params['Electricity Rate'] = float(config['electricity_rate_usd_per_kwh'])
    if 'heat_rate_usd_per_mmbtu' in config:
        params['Heat Rate'] = float(config['heat_rate_usd_per_mmbtu'])

    # Cost overrides
    cost_mappings = {
        'well_drilling_cost_musd_per_well': 'Well Drilling Cost',
        'stimulation_cost_musd': 'Reservoir Stimulation Capital Cost',
        'surface_plant_cost_musd': 'Surface Plant Capital Cost',
        'exploration_cost_musd': 'Exploration Capital Cost',
        'om_cost_musd_per_year': 'Total O&M Cost',
    }
    for config_key, param_name in cost_mappings.items():
        if config_key in config:
            params[param_name] = float(config[config_key])

    return params


def validate_outputs(params: dict) -> list:
    """Validate output parameters against expected ranges."""
    issues = []

    for name, value in params.items():
        if name in ECONOMIC_RANGES:
            r = ECONOMIC_RANGES[name]
            if isinstance(value, (int, float)):
                if value < r['min'] or value > r['max']:
                    issues.append(
                        f"WARNING: {name} = {value} outside expected range "
                        f"[{r['min']}, {r['max']}] {r['unit']}"
                    )

    # Cross-checks
    econ_model = params.get('Economic Model', 1)
    end_use = params.get('End-Use Option', 1)

    if end_use == 2 and params.get('Power Plant Type') in (1, 2, 3, 4):
        issues.append(
            "WARNING: End-Use is Direct-Use Heat but Power Plant Type is electricity-only. "
            "This combination may produce unexpected results."
        )

    return issues


def write_params(params: dict, output_path: Path):
    """Write parameters to GEOPHIRES input format."""
    lines = ['# Economic parameters generated by convert_site_economics.py']
    lines.append(f'# Economic Model: {params.get("Economic Model", "?")}')
    lines.append('')

    for name, value in params.items():
        lines.append(f'{name},{value},')

    output_path.write_text('\n'.join(lines) + '\n')
    logger.info(f"Wrote {len(params)} parameters to {output_path}")


def main():
    parser = argparse.ArgumentParser(description='Convert economic data to GEOPHIRES parameters')
    parser.add_argument('--config', required=True, help='JSON config file with economic data')
    parser.add_argument('--output', required=True, help='Output GEOPHIRES parameter file (.txt)')
    args = parser.parse_args()

    config_path = Path(args.config)
    output_path = Path(args.output)

    if not config_path.exists():
        logger.error(f"Config file not found: {config_path}")
        sys.exit(1)

    with open(config_path) as f:
        config = json.load(f)

    # Validate -> Process -> Validate
    input_issues = validate_inputs(config)
    for issue in input_issues:
        logger.warning(issue) if issue.startswith('WARNING') else logger.error(issue)

    if any(i.startswith('ERROR') for i in input_issues):
        sys.exit(1)

    params = process(config)

    output_issues = validate_outputs(params)
    for issue in output_issues:
        logger.warning(issue)

    write_params(params, output_path)

    print(json.dumps({
        'status': 'success',
        'n_params': len(params),
        'economic_model': params.get('Economic Model'),
        'end_use': params.get('End-Use Option'),
        'output_file': str(output_path),
        'warnings': output_issues,
    }, indent=2))


if __name__ == '__main__':
    main()
