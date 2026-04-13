#!/usr/bin/env python3
"""
parse_modflow_output.py — Extract MODFLOW results to CSV, arrays, and plots.

Reads MODFLOW binary output files (.hds, .bud/.cbc, .ddn) and text listing
files (.lst) to extract:
  - Head arrays per layer and time step
  - Cell-by-cell budget terms (recharge, wells, rivers, storage)
  - Water balance summaries
  - Drawdown arrays
  - Specific discharge vectors (for flow visualization)

Supports MODFLOW 6 and MODFLOW-2005 output formats.

Input:
  - Model workspace directory with MODFLOW output files
  - Model version (mf6 or mf2005)
  - Optional: specific time steps, layers, budget terms to extract

Output:
  - CSV files with head/budget time series
  - NumPy arrays (.npy) for spatial data
  - Water balance summary (JSON)
  - Optional: head contour map and cross-section plots

Critical Notes:
  - Binary precision must match model (single vs double) — dt_013
  - HDRY values (-1e30) must be masked before analysis — dt_012
  - Zero-based layer/time indexing in FloPy — dt_009
  - MF6 budget text labels are uppercase with trailing spaces

Usage:
    python parse_modflow_output.py --workspace ./mymodel --version mf6
    python parse_modflow_output.py --workspace ./mymodel --version mf6 \\
        --extract heads,budget --layers 0,1 --output_dir ./results
    python parse_modflow_output.py --workspace ./mymodel --version mf2005 \\
        --precision double --plot
"""

import argparse
import glob
import json
import os
import sys

import numpy as np
import pandas as pd


HDRY_THRESHOLD = -1e29  # Values below this are dry cells
BUDGET_TERMS_MF6 = [
    'STO-SS', 'STO-SY', 'FLOW-JA-FACE', 'CHD', 'WEL', 'RCH',
    'RIV', 'DRN', 'GHB', 'EVT', 'DATA-SPDIS'
]


def validate_inputs(args):
    """Validate inputs before processing."""
    errors = []
    warnings = []

    if not os.path.isdir(args.workspace):
        errors.append(f"Workspace not found: {args.workspace}")

    # Check for output files
    hds_files = glob.glob(os.path.join(args.workspace, '*.hds'))
    bud_files = glob.glob(os.path.join(args.workspace, '*.bud')) + \
                glob.glob(os.path.join(args.workspace, '*.cbc'))
    lst_files = glob.glob(os.path.join(args.workspace, '*.lst')) + \
                glob.glob(os.path.join(args.workspace, '*.list'))

    if not hds_files and not bud_files:
        errors.append(
            "No binary output files found (.hds, .bud, .cbc). "
            "Run MODFLOW first or check workspace path.")

    if not lst_files:
        warnings.append("No listing file found — water balance unavailable")

    os.makedirs(args.output_dir, exist_ok=True)

    if errors:
        print(json.dumps({
            "status": "error", "errors": errors, "warnings": warnings
        }))
        sys.exit(1)

    return warnings


def parse_heads(workspace, precision='single', layers=None,
                timesteps=None):
    """
    Parse binary head file.

    Returns dict with:
      - head_data: dict of (kstpkper) -> ndarray
      - times: list of simulation times
      - summary: statistics
    """
    try:
        import flopy
    except ImportError:
        print("ERROR: flopy required. Install: pip install flopy",
              file=sys.stderr)
        sys.exit(1)

    hds_files = glob.glob(os.path.join(workspace, '*.hds'))
    if not hds_files:
        return None, "No head file found"

    hds_path = hds_files[0]
    print(f"Reading head file: {hds_path}", file=sys.stderr)

    try:
        hds = flopy.utils.HeadFile(hds_path, precision=precision)
    except Exception as e:
        # Try alternate precision
        alt_prec = 'double' if precision == 'single' else 'single'
        print(f"Failed with {precision} precision, trying {alt_prec}...",
              file=sys.stderr)
        try:
            hds = flopy.utils.HeadFile(hds_path, precision=alt_prec)
            print(f"Success with {alt_prec} precision (dt_013)",
                  file=sys.stderr)
        except Exception:
            return None, f"Cannot read head file: {e}"

    times = hds.get_times()
    kstpkper = hds.get_kstpkper()

    head_data = {}
    for idx, ksp in enumerate(kstpkper):
        if timesteps and idx not in timesteps:
            continue
        head = hds.get_data(kstpkper=ksp)
        # Mask dry cells (dt_012)
        head = np.where(head < HDRY_THRESHOLD, np.nan, head)
        head_data[str(ksp)] = head

    # Summary statistics (excluding dry cells)
    all_heads = hds.get_alldata()
    all_heads = np.where(all_heads < HDRY_THRESHOLD, np.nan, all_heads)

    if layers is not None:
        layer_list = [int(l) for l in layers.split(',')]
    else:
        layer_list = list(range(all_heads.shape[1]))

    summary = {
        'n_timesteps': len(times),
        'times': [float(t) for t in times],
        'shape': list(all_heads.shape),
        'layers_extracted': layer_list,
        'per_layer_stats': {}
    }

    for lay in layer_list:
        if lay < all_heads.shape[1]:
            layer_data = all_heads[:, lay, :, :]
            valid = layer_data[~np.isnan(layer_data)]
            if len(valid) > 0:
                summary['per_layer_stats'][f'layer_{lay}'] = {
                    'min': float(np.min(valid)),
                    'max': float(np.max(valid)),
                    'mean': float(np.mean(valid)),
                    'std': float(np.std(valid)),
                    'n_dry_cells': int(np.sum(np.isnan(layer_data)))
                }

    hds.close()
    return head_data, summary


def parse_budget(workspace, precision='single'):
    """
    Parse cell-by-cell budget file.

    Returns dict with budget term summaries.
    """
    try:
        import flopy
    except ImportError:
        print("ERROR: flopy required", file=sys.stderr)
        sys.exit(1)

    bud_files = glob.glob(os.path.join(workspace, '*.bud')) + \
                glob.glob(os.path.join(workspace, '*.cbc'))
    if not bud_files:
        return None, "No budget file found"

    bud_path = bud_files[0]
    print(f"Reading budget file: {bud_path}", file=sys.stderr)

    try:
        cbb = flopy.utils.CellBudgetFile(bud_path, precision=precision)
    except Exception:
        alt_prec = 'double' if precision == 'single' else 'single'
        try:
            cbb = flopy.utils.CellBudgetFile(bud_path, precision=alt_prec)
        except Exception as e:
            return None, f"Cannot read budget file: {e}"

    records = cbb.get_unique_record_names()
    record_names = [r.decode().strip() if isinstance(r, bytes) else r.strip()
                    for r in records]

    budget_summary = {
        'available_records': record_names,
        'per_record': {}
    }

    for rec_name in record_names:
        try:
            data_list = cbb.get_data(text=rec_name)
            if data_list:
                # Summarize
                all_vals = []
                for d in data_list:
                    if isinstance(d, np.recarray):
                        if 'q' in d.dtype.names:
                            all_vals.extend(d['q'].tolist())
                    elif isinstance(d, np.ndarray):
                        all_vals.extend(d.flatten().tolist())

                if all_vals:
                    vals = np.array(all_vals)
                    budget_summary['per_record'][rec_name] = {
                        'total_in': float(np.sum(vals[vals > 0])),
                        'total_out': float(np.sum(vals[vals < 0])),
                        'net': float(np.sum(vals)),
                        'n_records': len(data_list)
                    }
        except Exception as e:
            budget_summary['per_record'][rec_name] = {'error': str(e)}

    cbb.close()
    return budget_summary, None


def parse_listing_water_balance(workspace):
    """Parse water balance from listing file."""
    lst_files = glob.glob(os.path.join(workspace, '*.lst')) + \
                glob.glob(os.path.join(workspace, '*.list'))
    if not lst_files:
        return None

    with open(lst_files[0]) as f:
        content = f.read()

    # Look for volumetric budget
    import re
    # MF6 format
    budget_section = re.findall(
        r'VOLUME BUDGET FOR ENTIRE MODEL.*?(?=VOLUME BUDGET|$)',
        content, re.DOTALL)

    if budget_section:
        last_budget = budget_section[-1]
        # Extract percent discrepancy
        disc_match = re.search(
            r'PERCENT DISCREPANCY\s*=?\s*([-\d.]+)', last_budget)
        discrepancy = float(disc_match.group(1)) if disc_match else None

        return {
            'last_budget_text': last_budget[:2000],
            'percent_discrepancy': discrepancy,
            'balanced': abs(discrepancy) < 1.0 if discrepancy else None
        }

    return None


def create_head_csv(head_data, summary, output_dir, grid_meta=None):
    """Export head data to CSV for selected observation points."""
    if not head_data:
        return

    # Get the last timestep data
    last_key = list(head_data.keys())[-1]
    last_head = head_data[last_key]

    # Save last timestep as CSV (layer 0)
    if last_head.ndim >= 2:
        layer0 = last_head[0] if last_head.ndim == 3 else last_head
        df = pd.DataFrame(layer0)
        df.to_csv(os.path.join(output_dir, 'head_layer0_final.csv'),
                  index=False)

    # Save as numpy
    for key, head_arr in head_data.items():
        safe_key = key.replace('(', '').replace(')', '').replace(', ', '_')
        np.save(os.path.join(output_dir, f'head_{safe_key}.npy'), head_arr)

    # Time series at grid center
    if summary and summary.get('shape'):
        shape = summary['shape']
        if len(shape) == 4:
            center_row = shape[2] // 2
            center_col = shape[3] // 2
            ts_data = []
            for key, head_arr in head_data.items():
                if head_arr.ndim == 3:
                    val = head_arr[0, center_row, center_col]
                else:
                    val = head_arr[center_row, center_col]
                ts_data.append({'timestep': key, 'head_center': float(val)})

            if ts_data:
                ts_df = pd.DataFrame(ts_data)
                ts_df.to_csv(
                    os.path.join(output_dir, 'head_timeseries_center.csv'),
                    index=False)


def create_plot(head_data, output_dir):
    """Create head contour map for last timestep."""
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError:
        print("WARNING: matplotlib not available for plotting",
              file=sys.stderr)
        return

    if not head_data:
        return

    last_key = list(head_data.keys())[-1]
    head = head_data[last_key]
    if head.ndim == 3:
        head = head[0]  # Layer 0

    fig, ax = plt.subplots(figsize=(10, 8))
    im = ax.imshow(head, cmap='viridis', origin='upper')
    cs = ax.contour(head, levels=10, colors='white', linewidths=0.5)
    ax.clabel(cs, inline=True, fontsize=8)
    plt.colorbar(im, ax=ax, label='Head (m)', shrink=0.8)
    ax.set_title(f'Hydraulic Head — Layer 0, Time Step {last_key}')
    ax.set_xlabel('Column')
    ax.set_ylabel('Row')

    fig.tight_layout()
    fig.savefig(os.path.join(output_dir, 'head_contour_map.png'), dpi=150)
    plt.close(fig)
    print(f"Plot saved: {output_dir}/head_contour_map.png", file=sys.stderr)


def process(args, warnings_list):
    """Main processing: MODFLOW output → CSV, arrays, plots."""
    results = {'warnings': warnings_list}

    extract_items = (args.extract.split(',') if args.extract
                     else ['heads', 'budget', 'balance'])

    # Parse heads
    if 'heads' in extract_items:
        head_data, head_summary = parse_heads(
            args.workspace, precision=args.precision,
            layers=args.layers)
        if isinstance(head_summary, str):
            results['heads'] = {'error': head_summary}
        else:
            results['heads'] = head_summary
            create_head_csv(head_data, head_summary, args.output_dir)
            if args.plot:
                create_plot(head_data, args.output_dir)

    # Parse budget
    if 'budget' in extract_items:
        budget_summary, budget_error = parse_budget(
            args.workspace, precision=args.precision)
        if budget_error:
            results['budget'] = {'error': budget_error}
        else:
            results['budget'] = budget_summary

    # Parse water balance
    if 'balance' in extract_items:
        balance = parse_listing_water_balance(args.workspace)
        if balance:
            results['water_balance'] = balance

    # Save results metadata
    meta_path = os.path.join(args.output_dir, 'output_metadata.json')
    with open(meta_path, 'w') as f:
        json.dump(results, f, indent=2, default=str)

    return results


def validate_outputs(results, output_dir):
    """Post-processing validation."""
    errors = []
    warnings = []

    # Check head results
    if 'heads' in results and 'error' not in results['heads']:
        stats = results['heads'].get('per_layer_stats', {})
        for lay, s in stats.items():
            if s.get('n_dry_cells', 0) > 0:
                total = (results['heads']['shape'][2] *
                         results['heads']['shape'][3])
                dry_pct = 100 * s['n_dry_cells'] / total / \
                    results['heads']['n_timesteps']
                if dry_pct > 50:
                    warnings.append(
                        f"{lay}: {dry_pct:.0f}% cells dry — "
                        "check model setup")
            if s.get('min', 0) < -1000:
                warnings.append(
                    f"{lay}: min head = {s['min']:.1f}m — "
                    "check for HDRY artifacts (dt_012)")

    # Check water balance
    if 'water_balance' in results:
        wb = results['water_balance']
        if wb.get('percent_discrepancy') is not None:
            disc = abs(wb['percent_discrepancy'])
            if disc > 1.0:
                warnings.append(
                    f"Water balance error = {disc:.2f}%. Target < 1%.")
            if disc > 5.0:
                errors.append(
                    f"Water balance error = {disc:.2f}% — unacceptable")

    result = {
        "status": "error" if errors else "ok",
        "errors": errors,
        "warnings": warnings
    }
    print(json.dumps(result, indent=2))
    return len(errors) == 0


def main():
    parser = argparse.ArgumentParser(
        description='Parse MODFLOW output files')
    parser.add_argument('--workspace', required=True,
                        help='Model workspace directory')
    parser.add_argument('--version', default='mf6',
                        choices=['mf6', 'mf2005', 'mfnwt'])
    parser.add_argument('--precision', default='single',
                        choices=['single', 'double'],
                        help='Binary file precision (dt_013)')
    parser.add_argument('--extract', default=None,
                        help='Comma-separated: heads,budget,balance')
    parser.add_argument('--layers', default=None,
                        help='Comma-separated layer indices to extract')
    parser.add_argument('--plot', action='store_true',
                        help='Create visualization plots')
    parser.add_argument('--output_dir', default='./results',
                        help='Output directory for extracted data')
    args = parser.parse_args()

    warnings_list = validate_inputs(args)
    results = process(args, warnings_list)
    validate_outputs(results, args.output_dir)


if __name__ == '__main__':
    main()
