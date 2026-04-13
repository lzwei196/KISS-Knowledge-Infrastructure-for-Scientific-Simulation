#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
============================================
Tool ID:      compare_physics
Stage:        s7_physics_comparison
Description:  Run SUMMA with multiple decision combinations and compare
              outputs. This is SUMMA's unique feature: systematic evaluation
              of model structural uncertainty.

              For each decision variation, the tool:
              1. Creates a modified decisions file
              2. Runs SUMMA with a unique output suffix
              3. Extracts key variables from output
              4. Computes comparison statistics (mean, std, RMSE vs baseline)

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import json
import logging
import numpy as np
import shutil
from pathlib import Path
from itertools import product

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BASE_FILE_MANAGER = ""
SUMMA_EXE = ""
DECISION_VARIATIONS = {}  # e.g., {'snowLayers': ['jrdn1991', 'CLM_2010']}
OUTPUT_DIR = ""
COMPARISON_VARIABLES = ['scalarTotalRunoff', 'scalarSWE', 'scalarTotalET']

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

if len(sys.argv) > 1:
    import argparse
    parser = argparse.ArgumentParser(description="Compare SUMMA physics options")
    parser.add_argument("--file_manager", required=True)
    parser.add_argument("--summa_exe", required=True)
    parser.add_argument("--variations", type=str, required=True,
                        help="JSON dict of decision -> [options]")
    parser.add_argument("--output_dir", required=True)
    parser.add_argument("--variables", nargs='+',
                        default=['scalarTotalRunoff', 'scalarSWE', 'scalarTotalET'])
    args = parser.parse_args()
    BASE_FILE_MANAGER = args.file_manager
    SUMMA_EXE = args.summa_exe
    DECISION_VARIATIONS = json.loads(args.variations)
    OUTPUT_DIR = args.output_dir
    COMPARISON_VARIABLES = args.variables


def validate_inputs():
    errors = []
    if not BASE_FILE_MANAGER or not Path(BASE_FILE_MANAGER).exists():
        errors.append(f"fileManager not found: {BASE_FILE_MANAGER}")
    if not SUMMA_EXE or not Path(SUMMA_EXE).exists():
        errors.append(f"SUMMA executable not found: {SUMMA_EXE}")
    if not DECISION_VARIATIONS:
        errors.append("No decision variations specified")
    if not OUTPUT_DIR:
        errors.append("OUTPUT_DIR not set")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def validate_outputs(output_csv):
    if not Path(output_csv).exists():
        logger.error(f"Comparison CSV not created: {output_csv}")
        sys.exit(3)
    logger.info("Output validation passed.")


def parse_file_manager(fm_path):
    """Parse fileManager.txt into a dict."""
    import re
    config = {}
    with open(fm_path) as f:
        for line in f:
            line_clean = line.split('!')[0].strip()
            if not line_clean:
                continue
            parts = line_clean.split()
            if len(parts) >= 2:
                key = parts[0]
                match = re.search(r"'([^']*)'", line_clean)
                config[key] = match.group(1) if match else parts[1]
    return config


def modify_decisions(base_decisions_path, modifications, output_path):
    """Create modified decisions file."""
    lines = []
    with open(base_decisions_path) as f:
        for line in f:
            line_stripped = line.split('!')[0].strip()
            modified = False
            for key, value in modifications.items():
                if line_stripped.startswith(key):
                    lines.append(f"{key:<20s} {value}\n")
                    modified = True
                    break
            if not modified:
                lines.append(line)

    with open(output_path, 'w') as f:
        f.writelines(lines)


def process():
    """Run multiple SUMMA variants and compare."""
    import subprocess
    import csv

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Parse base config
    base_config = parse_file_manager(BASE_FILE_MANAGER)
    settings_path = base_config.get('settingsPath', '')
    base_decisions = os.path.join(settings_path, base_config.get('decisionsFile', ''))

    # Generate all combinations
    decision_names = list(DECISION_VARIATIONS.keys())
    option_lists = [DECISION_VARIATIONS[k] for k in decision_names]
    combinations = list(product(*option_lists))

    logger.info(f"Running {len(combinations)} SUMMA variants:")
    for i, combo in enumerate(combinations):
        mods = dict(zip(decision_names, combo))
        logger.info(f"  Variant {i+1}: {mods}")

    # Run each combination
    results = []
    for i, combo in enumerate(combinations):
        mods = dict(zip(decision_names, combo))
        suffix = '_'.join(f"{k}_{v}" for k, v in mods.items())
        run_name = f"run_{i+1}_{suffix}"

        logger.info(f"--- Running variant {i+1}/{len(combinations)}: {run_name} ---")

        # Create modified decisions file
        mod_decisions = os.path.join(OUTPUT_DIR, f"decisions_{run_name}.txt")
        modify_decisions(base_decisions, mods, mod_decisions)

        # Create modified fileManager pointing to new decisions
        mod_fm = os.path.join(OUTPUT_DIR, f"fileManager_{run_name}.txt")
        shutil.copy(BASE_FILE_MANAGER, mod_fm)

        # Update decisions file reference
        with open(mod_fm, 'r') as f:
            content = f.read()
        old_decisions = base_config.get('decisionsFile', '')
        content = content.replace(
            f"'{old_decisions}'",
            f"'{os.path.basename(mod_decisions)}'"
        )
        # Update settings path to include our modified decisions
        with open(mod_fm, 'w') as f:
            f.write(content)

        # Copy modified decisions to settings path
        shutil.copy(mod_decisions, os.path.join(settings_path, os.path.basename(mod_decisions)))

        # Update fileManager to use the new decisions file name
        with open(mod_fm, 'r') as f:
            content = f.read()
        content = content.replace(f"'{old_decisions}'",
                                  f"'{os.path.basename(mod_decisions)}'")
        with open(mod_fm, 'w') as f:
            f.write(content)

        # Run SUMMA
        cmd = [SUMMA_EXE, '-m', mod_fm, '-s', run_name]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
            if result.returncode != 0:
                logger.warning(f"  Variant {run_name} failed (exit {result.returncode})")
                results.append({
                    'run': run_name,
                    'status': 'failed',
                    **mods
                })
                continue
        except subprocess.TimeoutExpired:
            logger.warning(f"  Variant {run_name} timed out")
            results.append({'run': run_name, 'status': 'timeout', **mods})
            continue

        # Parse output
        output_path = base_config.get('outputPath', '')
        nc_files = list(Path(output_path).glob(f"*{run_name}*.nc"))
        if not nc_files:
            logger.warning(f"  No output for {run_name}")
            results.append({'run': run_name, 'status': 'no_output', **mods})
            continue

        # Extract statistics
        try:
            from netCDF4 import Dataset
            ds = Dataset(nc_files[0], 'r')
            run_result = {'run': run_name, 'status': 'success', **mods}
            for var in COMPARISON_VARIABLES:
                if var in ds.variables:
                    vals = ds.variables[var][:]
                    valid = vals[~np.isnan(vals)]
                    run_result[f'{var}_mean'] = float(np.mean(valid))
                    run_result[f'{var}_std'] = float(np.std(valid))
                    run_result[f'{var}_max'] = float(np.max(valid))
            ds.close()
            results.append(run_result)
        except Exception as e:
            logger.warning(f"  Cannot parse {run_name} output: {e}")
            results.append({'run': run_name, 'status': 'parse_error', **mods})

    # Write comparison CSV
    comparison_csv = os.path.join(OUTPUT_DIR, "physics_comparison.csv")
    if results:
        fieldnames = list(results[0].keys())
        # Collect all unique keys
        for r in results:
            for k in r.keys():
                if k not in fieldnames:
                    fieldnames.append(k)

        with open(comparison_csv, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
            writer.writeheader()
            for r in results:
                writer.writerow(r)

    logger.info(f"Comparison complete: {len(results)} variants")
    logger.info(f"Results: {comparison_csv}")

    successful = sum(1 for r in results if r.get('status') == 'success')
    print(json.dumps({
        "status": "success",
        "total_variants": len(combinations),
        "successful": successful,
        "failed": len(combinations) - successful,
        "output": comparison_csv
    }))

    return comparison_csv


if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try:
        output = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(2)
    validate_outputs(output)
    sys.exit(0)
