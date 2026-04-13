#!/usr/bin/env python3
"""
Parse GEOPHIRES .out text report into structured CSV and JSON.

Extracts:
  - Summary metrics (LCOE, LCOH, NPV, IRR, net power/heat)
  - Capital costs breakdown (MUSD)
  - O&M costs breakdown (MUSD/yr)
  - Year-by-year production profile
  - Annual energy profile
  - Revenue and cashflow tables

Usage:
    python parse_geophires_output.py --input output_file.out \
        --csv production_profile.csv --json summary.json
"""

import argparse
import csv
import json
import logging
import re
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def validate_inputs(input_path: Path) -> list:
    """Validate the .out file before parsing."""
    issues = []

    if not input_path.exists():
        issues.append(f"FATAL: Output file not found: {input_path}")
        return issues

    if input_path.stat().st_size == 0:
        issues.append("FATAL: Output file is empty")
        return issues

    content = input_path.read_text()

    # Check for GEOPHIRES header
    if 'GEOPHIRES' not in content[:500]:
        issues.append("WARNING: File may not be a GEOPHIRES output (no header found)")

    # Check for key sections
    expected_sections = ['SUMMARY OF RESULTS', 'ECONOMIC PARAMETERS',
                         'CAPITAL COSTS', 'OPERATING AND MAINTENANCE COSTS']
    for section in expected_sections:
        if section not in content:
            issues.append(f"WARNING: Missing section '{section}'")

    return issues


def _extract_value(line: str) -> tuple:
    """Extract parameter name and value from an output line.

    Lines are formatted as:
      '      Parameter Name:                          Value Unit'

    Returns:
        (name, value_str, unit_str) or (None, None, None) if not parseable.
    """
    # Match lines like "  Parameter Name:                    12.34 Unit"
    match = re.match(r'\s+(.+?):\s+([\d.,\-+eE]+)\s*(.*)', line)
    if match:
        name = match.group(1).strip()
        value_str = match.group(2).strip().replace(',', '')
        unit_str = match.group(3).strip()
        return name, value_str, unit_str
    return None, None, None


def _parse_table(lines: list, start_idx: int) -> tuple:
    """Parse a tabular section starting from a header line.

    Returns:
        (headers, rows, end_idx)
    """
    # Find header line (contains multiple column titles separated by spaces)
    headers = []
    rows = []

    # Look for dashed separator
    header_idx = start_idx
    for i in range(start_idx, min(start_idx + 10, len(lines))):
        if '---' in lines[i] or '***' in lines[i] or '===' in lines[i]:
            continue
        parts = lines[i].split()
        if len(parts) >= 2:
            headers = parts
            header_idx = i
            break

    if not headers:
        return [], [], start_idx

    # Parse data rows
    for i in range(header_idx + 1, len(lines)):
        line = lines[i].strip()
        if not line or line.startswith('*') or line.startswith('='):
            return headers, rows, i
        parts = line.split()
        if parts and parts[0].replace('.', '').replace('-', '').isdigit():
            rows.append(parts)

    return headers, rows, len(lines)


def parse_summary(content: str) -> dict:
    """Extract summary metrics from the SUMMARY OF RESULTS section."""
    summary = {}
    lines = content.splitlines()

    in_summary = False
    for line in lines:
        if 'SUMMARY OF RESULTS' in line:
            in_summary = True
            continue
        if in_summary and ('***' in line or '===' in line):
            # End of section (new section header)
            if summary:
                break
            continue

        if in_summary:
            name, value, unit = _extract_value(line)
            if name and value:
                try:
                    summary[name] = {'value': float(value), 'unit': unit}
                except ValueError:
                    summary[name] = {'value': value, 'unit': unit}

    return summary


def parse_section(content: str, section_name: str) -> dict:
    """Generic section parser for key-value sections."""
    result = {}
    lines = content.splitlines()

    in_section = False
    for line in lines:
        if section_name.upper() in line.upper():
            in_section = True
            continue
        if in_section and ('***' in line or '===' in line):
            if result:
                break
            continue

        if in_section:
            name, value, unit = _extract_value(line)
            if name and value:
                try:
                    result[name] = {'value': float(value), 'unit': unit}
                except ValueError:
                    result[name] = {'value': value, 'unit': unit}

    return result


def parse_production_profile(content: str) -> list:
    """Extract the year-by-year production profile table.

    Returns list of dicts with year, drawdown, temperature, pump_power,
    net_power (or net_heat), first_law_efficiency.
    """
    profile = []
    lines = content.splitlines()

    # Find the production profile section
    start = None
    for i, line in enumerate(lines):
        if 'HEAT AND/OR ELECTRICITY EXTRACTION AND GENERATION PROFILE' in line.upper() or \
           'POWER GENERATION PROFILE' in line.upper() or \
           'HEATING GENERATION PROFILE' in line.upper():
            start = i
            break

    if start is None:
        logger.warning("Production profile section not found")
        return profile

    # Skip to data rows (past headers and separator)
    data_start = start
    for i in range(start + 1, min(start + 15, len(lines))):
        line = lines[i].strip()
        # Look for first numeric data row
        parts = line.split()
        if parts and parts[0].replace('.', '').replace('-', '').isdigit():
            data_start = i
            break

    # Parse data rows
    for i in range(data_start, len(lines)):
        line = lines[i].strip()
        if not line or line.startswith('*') or line.startswith('='):
            break
        parts = line.split()
        if len(parts) >= 4:
            try:
                entry = {
                    'year': int(float(parts[0])),
                    'thermal_drawdown': float(parts[1]),
                    'geofluid_temperature_degC': float(parts[2]),
                    'pump_power_MW': float(parts[3]),
                }
                if len(parts) >= 5:
                    entry['net_power_or_heat_MW'] = float(parts[4])
                if len(parts) >= 6:
                    entry['first_law_efficiency_pct'] = float(parts[5])
                profile.append(entry)
            except (ValueError, IndexError):
                continue

    return profile


def parse_energy_profile(content: str) -> list:
    """Extract annual energy production profile."""
    energy = []
    lines = content.splitlines()

    start = None
    for i, line in enumerate(lines):
        if 'ANNUAL HEATING, COOLING AND/OR ELECTRICITY PRODUCTION PROFILE' in line.upper() or \
           'ANNUAL ENERGY PRODUCTION PROFILE' in line.upper():
            start = i
            break

    if start is None:
        return energy

    data_start = start
    for i in range(start + 1, min(start + 15, len(lines))):
        parts = lines[i].strip().split()
        if parts and parts[0].replace('.', '').replace('-', '').isdigit():
            data_start = i
            break

    for i in range(data_start, len(lines)):
        line = lines[i].strip()
        if not line or line.startswith('*') or line.startswith('='):
            break
        parts = line.split()
        if len(parts) >= 3:
            try:
                entry = {
                    'year': int(float(parts[0])),
                    'energy_provided_GWh': float(parts[1]),
                    'heat_extracted_GWh': float(parts[2]),
                }
                if len(parts) >= 4:
                    entry['reservoir_heat_content_1e15J'] = float(parts[3])
                if len(parts) >= 5:
                    entry['percentage_heat_mined'] = float(parts[4])
                energy.append(entry)
            except (ValueError, IndexError):
                continue

    return energy


def parse_cashflow(content: str) -> list:
    """Extract revenue and cashflow profile."""
    cashflow = []
    lines = content.splitlines()

    start = None
    for i, line in enumerate(lines):
        if 'REVENUE & CASHFLOW PROFILE' in line.upper() or \
           'CASHFLOW PROFILE' in line.upper():
            start = i
            break

    if start is None:
        return cashflow

    data_start = start
    for i in range(start + 1, min(start + 20, len(lines))):
        parts = lines[i].strip().split()
        if parts and (parts[0].replace('.', '').replace('-', '').isdigit() or parts[0] == '1'):
            data_start = i
            break

    for i in range(data_start, len(lines)):
        line = lines[i].strip()
        if not line or line.startswith('*') or line.startswith('='):
            break
        parts = line.split()
        if len(parts) >= 3:
            try:
                entry = {'year': int(float(parts[0]))}
                # Remaining fields depend on end-use type; store as raw values
                for j, val in enumerate(parts[1:], 1):
                    try:
                        entry[f'col_{j}'] = float(val)
                    except ValueError:
                        entry[f'col_{j}'] = val
                cashflow.append(entry)
            except (ValueError, IndexError):
                continue

    return cashflow


def process(input_path: Path) -> dict:
    """Parse the complete .out file.

    Returns:
        Dictionary with all extracted data.
    """
    content = input_path.read_text()

    result = {
        'source_file': str(input_path),
        'summary': parse_summary(content),
        'economic_parameters': parse_section(content, 'ECONOMIC PARAMETERS'),
        'capital_costs': parse_section(content, 'CAPITAL COSTS'),
        'om_costs': parse_section(content, 'OPERATING AND MAINTENANCE COSTS'),
        'reservoir_parameters': parse_section(content, 'RESERVOIR PARAMETERS'),
        'reservoir_simulation': parse_section(content, 'RESERVOIR SIMULATION RESULTS'),
        'surface_equipment': parse_section(content, 'SURFACE EQUIPMENT SIMULATION RESULTS'),
        'production_profile': parse_production_profile(content),
        'energy_profile': parse_energy_profile(content),
        'cashflow': parse_cashflow(content),
    }

    # Extract key scalar metrics for quick access
    metrics = {}
    for section_name, section_data in result.items():
        if isinstance(section_data, dict):
            for key, val in section_data.items():
                if isinstance(val, dict) and 'value' in val:
                    metrics[key] = val['value']

    result['metrics'] = metrics

    return result


def validate_outputs(result: dict) -> list:
    """Validate parsed results."""
    issues = []

    if not result['summary']:
        issues.append("WARNING: No summary data extracted")

    if not result['production_profile']:
        issues.append("WARNING: No production profile extracted")

    if not result['energy_profile']:
        issues.append("WARNING: No energy profile extracted")

    # Check for reasonable values
    metrics = result.get('metrics', {})
    for key in ['Average Net Electricity Production', 'Average Net Heat Production']:
        if key in metrics:
            val = metrics[key]
            if isinstance(val, (int, float)) and val < 0:
                issues.append(f"WARNING: {key} = {val} is negative (check pump power)")

    return issues


def write_csv(profile: list, output_path: Path):
    """Write production/energy profile to CSV."""
    if not profile:
        logger.warning(f"No data to write to {output_path}")
        return

    fieldnames = list(profile[0].keys())
    with open(output_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(profile)

    logger.info(f"Wrote {len(profile)} rows to {output_path}")


def main():
    parser = argparse.ArgumentParser(description='Parse GEOPHIRES output')
    parser.add_argument('--input', required=True, help='GEOPHIRES .out file')
    parser.add_argument('--json', default=None, help='Output JSON file')
    parser.add_argument('--csv', default=None, help='Output CSV file (production profile)')
    parser.add_argument('--energy-csv', default=None, help='Output CSV file (energy profile)')
    args = parser.parse_args()

    input_path = Path(args.input)

    # Validate
    input_issues = validate_inputs(input_path)
    for issue in input_issues:
        if issue.startswith('FATAL'):
            logger.error(issue)
            sys.exit(1)
        else:
            logger.warning(issue)

    # Process
    result = process(input_path)

    # Validate outputs
    output_issues = validate_outputs(result)
    for issue in output_issues:
        logger.warning(issue)

    # Write outputs
    if args.json:
        json_path = Path(args.json)
        with open(json_path, 'w') as f:
            json.dump(result, f, indent=2, default=str)
        logger.info(f"Wrote JSON to {json_path}")

    if args.csv:
        csv_path = Path(args.csv)
        write_csv(result['production_profile'], csv_path)

    if args.energy_csv:
        energy_csv_path = Path(args.energy_csv)
        write_csv(result['energy_profile'], energy_csv_path)

    # Print summary to stdout
    n_years = len(result['production_profile'])
    n_metrics = len(result.get('metrics', {}))
    print(json.dumps({
        'status': 'success',
        'n_metrics': n_metrics,
        'n_production_years': n_years,
        'n_energy_years': len(result['energy_profile']),
        'key_metrics': {k: v for k, v in list(result.get('metrics', {}).items())[:10]},
    }, indent=2))


if __name__ == '__main__':
    main()
