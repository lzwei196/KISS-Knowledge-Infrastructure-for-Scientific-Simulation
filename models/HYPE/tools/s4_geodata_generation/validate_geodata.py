#!/usr/bin/env python3
"""
Validate GeoData.txt for HYPE — checks topology, SLC sums, required columns, value ranges.

Usage:
    python validate_geodata.py --geodata modelfiles/GeoData.txt
"""

import argparse
import sys
import pandas as pd


def validate_geodata(filepath):
    """Comprehensive validation of HYPE GeoData.txt. Returns (pass, issues list)."""
    issues = []

    # Read file
    try:
        with open(filepath) as f:
            lines = f.readlines()

        # Skip comment lines
        data_start = 0
        for i, line in enumerate(lines):
            if not line.startswith('!!'):
                data_start = i
                break

        header = lines[data_start].strip().split('\t')
        rows = []
        for line in lines[data_start + 1:]:
            if line.strip() and not line.startswith('!!'):
                rows.append(line.strip().split('\t'))

        df = pd.DataFrame(rows, columns=header)

        # Convert numeric columns
        for col in df.columns:
            try:
                df[col] = pd.to_numeric(df[col])
            except (ValueError, TypeError):
                pass

    except Exception as e:
        issues.append(('FATAL', f'Cannot read file: {e}'))
        return False, issues

    # Check required columns
    required = ['SUBID', 'MAINDOWN', 'AREA']
    for col in required:
        if col not in df.columns:
            issues.append(('FATAL', f'Missing required column: {col}'))

    if any(s == 'FATAL' for s, _ in issues):
        return False, issues

    # Check SUBID uniqueness
    if df['SUBID'].duplicated().any():
        dups = df[df['SUBID'].duplicated()]['SUBID'].tolist()
        issues.append(('FATAL', f'Duplicate SUBIDs: {dups}'))

    # Check MAINDOWN topology
    subids = set(df['SUBID'].values)
    outlets = df[df['MAINDOWN'] == 0]
    if len(outlets) == 0:
        issues.append(('FATAL', 'No outlet (MAINDOWN=0) found'))
    elif len(outlets) > 1:
        issues.append(('WARNING', f'{len(outlets)} outlets found (multi-outlet setup)'))

    for _, row in df.iterrows():
        md = row['MAINDOWN']
        if md != 0 and md not in subids:
            issues.append(('FATAL', f'SUBID {row["SUBID"]}: MAINDOWN={md} not in SUBID list'))

    # Check for cycles
    maindown = dict(zip(df['SUBID'], df['MAINDOWN']))
    for sid in subids:
        visited = set()
        current = sid
        while current != 0:
            if current in visited:
                issues.append(('FATAL', f'Cycle detected at SUBID {current}'))
                break
            visited.add(current)
            current = maindown.get(current, 0)

    # Check SLC fractions
    slc_cols = [c for c in df.columns if c.startswith('SLC_')]
    if not slc_cols:
        issues.append(('WARNING', 'No SLC columns found'))
    else:
        for _, row in df.iterrows():
            slc_sum = sum(float(row[c]) for c in slc_cols)
            if abs(slc_sum - 1.0) > 0.01:
                issues.append(('FATAL', f'SUBID {row["SUBID"]}: SLC sum = {slc_sum:.4f} (must be 1.0)'))
            elif abs(slc_sum - 1.0) > 0.001:
                issues.append(('WARNING', f'SUBID {row["SUBID"]}: SLC sum = {slc_sum:.6f} (minor deviation)'))

    # Check AREA values
    if 'AREA' in df.columns:
        for _, row in df.iterrows():
            area = float(row['AREA'])
            if area < 1e4:
                issues.append(('WARNING', f'SUBID {row["SUBID"]}: AREA={area:.1E} very small (units should be m^2)'))
            if area > 1e12:
                issues.append(('WARNING', f'SUBID {row["SUBID"]}: AREA={area:.1E} very large (check units)'))

    # Check RIVLEN
    if 'RIVLEN' in df.columns:
        for _, row in df.iterrows():
            rivlen = float(row['RIVLEN'])
            if rivlen <= 0:
                issues.append(('WARNING', f'SUBID {row["SUBID"]}: RIVLEN={rivlen} (should be > 0 for routing)'))

    has_fatal = any(s == 'FATAL' for s, _ in issues)

    if not issues:
        issues.append(('PASS', 'All validation checks passed'))

    return not has_fatal, issues


def main():
    parser = argparse.ArgumentParser(description='Validate HYPE GeoData.txt')
    parser.add_argument('--geodata', required=True, help='GeoData.txt file path')

    args = parser.parse_args()

    passed, issues = validate_geodata(args.geodata)

    for severity, msg in issues:
        prefix = {'FATAL': 'FAIL', 'WARNING': 'WARN', 'PASS': 'PASS'}[severity]
        print(f'[{prefix}] {msg}')

    print(f"\n{'PASSED' if passed else 'FAILED'} ({len([i for s,i in issues if s=='FATAL'])} errors, {len([i for s,i in issues if s=='WARNING'])} warnings)")
    sys.exit(0 if passed else 1)


if __name__ == '__main__':
    main()
