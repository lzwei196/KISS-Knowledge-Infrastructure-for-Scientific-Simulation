#!/usr/bin/env python3
"""
Validate MAINDOWN topology for HYPE GeoData.txt.

Checks:
1. Exactly one outlet (MAINDOWN=0)
2. No cycles in the routing network
3. All subbasins reachable from upstream to outlet
4. SUBID values are positive integers
5. MAINDOWN values reference valid SUBIDs or 0

Usage:
    python validate_topology.py --geodata modelfiles/GeoData.txt
    python validate_topology.py --csv maindown.csv
"""

import argparse
import sys
import pandas as pd
from collections import defaultdict


def read_geodata(filepath):
    """Read GeoData.txt or maindown.csv"""
    with open(filepath) as f:
        first_line = f.readline()

    if first_line.startswith('!!'):
        # Skip comment lines
        skip = 0
        with open(filepath) as f:
            for line in f:
                if line.startswith('!!'):
                    skip += 1
                else:
                    break
        df = pd.read_csv(filepath, sep='\t', skiprows=skip)
    else:
        df = pd.read_csv(filepath, sep='\t')

    return df


def validate_topology(df):
    """Validate MAINDOWN topology. Returns list of (severity, message) tuples."""
    issues = []

    if 'SUBID' not in df.columns or 'MAINDOWN' not in df.columns:
        issues.append(('FATAL', 'Missing SUBID or MAINDOWN column'))
        return issues

    subids = set(df['SUBID'].values)
    maindown = dict(zip(df['SUBID'], df['MAINDOWN']))

    # Check 1: Exactly one outlet
    outlets = [sid for sid, md in maindown.items() if md == 0]
    if len(outlets) == 0:
        issues.append(('FATAL', 'No outlet found (no MAINDOWN=0)'))
    elif len(outlets) > 1:
        issues.append(('WARNING', f'Multiple outlets: {outlets}. HYPE supports multi-outlet but unusual.'))

    # Check 2: MAINDOWN references valid SUBIDs
    for sid, md in maindown.items():
        if md != 0 and md not in subids:
            issues.append(('FATAL', f'SUBID {sid} has MAINDOWN={md} which is not a valid SUBID'))

    # Check 3: No cycles (topological sort)
    visited = set()
    in_stack = set()

    def has_cycle(node):
        if node in in_stack:
            return True
        if node in visited:
            return False
        visited.add(node)
        in_stack.add(node)
        downstream = maindown.get(node, 0)
        if downstream != 0:
            if has_cycle(downstream):
                return True
        in_stack.remove(node)
        return False

    for sid in subids:
        visited.clear()
        in_stack.clear()
        if has_cycle(sid):
            issues.append(('FATAL', f'Cycle detected involving SUBID {sid}'))
            break

    # Check 4: All subbasins reachable to outlet
    for sid in subids:
        current = sid
        steps = 0
        while current != 0 and steps < len(subids) + 1:
            current = maindown.get(current, 0)
            steps += 1
        if steps > len(subids):
            issues.append(('FATAL', f'SUBID {sid} cannot reach outlet (possible disconnection)'))

    # Check 5: Positive integer SUBIDs
    for sid in subids:
        if sid <= 0:
            issues.append(('FATAL', f'SUBID {sid} is not a positive integer'))

    # Check 6: SLC fractions sum to 1.0
    slc_cols = [c for c in df.columns if c.startswith('SLC_')]
    if slc_cols:
        for idx, row in df.iterrows():
            slc_sum = sum(row[c] for c in slc_cols)
            if abs(slc_sum - 1.0) > 0.01:
                issues.append(('WARNING', f'SUBID {row["SUBID"]}: SLC fractions sum to {slc_sum:.4f} (should be 1.0)'))

    if not issues:
        issues.append(('PASS', 'Topology validation passed'))

    return issues


def main():
    parser = argparse.ArgumentParser(description='Validate HYPE MAINDOWN topology')
    parser.add_argument('--geodata', help='GeoData.txt file path')
    parser.add_argument('--csv', help='MAINDOWN CSV file path')

    args = parser.parse_args()

    filepath = args.geodata or args.csv
    if not filepath:
        print('ERROR: Provide --geodata or --csv')
        sys.exit(1)

    df = read_geodata(filepath)
    issues = validate_topology(df)

    has_fatal = False
    for severity, msg in issues:
        prefix = {'FATAL': 'FAIL', 'WARNING': 'WARN', 'PASS': 'PASS'}[severity]
        print(f'[{prefix}] {msg}')
        if severity == 'FATAL':
            has_fatal = True

    sys.exit(1 if has_fatal else 0)


if __name__ == '__main__':
    main()
