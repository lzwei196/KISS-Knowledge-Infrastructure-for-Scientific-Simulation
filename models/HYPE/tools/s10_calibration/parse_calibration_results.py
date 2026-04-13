#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
Tool ID:      parse_calibration_results
Stage:        s10_calibration
Description:  Parse HYPE calibration output files (allsim.txt, bestsims.txt,
              calibration.log) to extract best parameters, objective function
              evolution, and convergence diagnostics.

Usage:
    # Parse best parameters and print summary:
    python parse_calibration_results.py \
        --result_dir resultdir/ \
        --output_csv calibration_results.csv

    # Extract best parameters and write as par.txt update:
    python parse_calibration_results.py \
        --result_dir resultdir/ \
        --output_par best_par.txt \
        --geoclass modelfiles/GeoClass.txt

    # Full analysis with convergence plot data:
    python parse_calibration_results.py \
        --result_dir resultdir/ \
        --output_csv calibration_results.csv \
        --output_par best_par.txt \
        --geoclass modelfiles/GeoClass.txt \
        --plot_convergence convergence.png

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import argparse
import sys
import os
import logging
import json
import re
from pathlib import Path

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


# HYPE performance column names (from worvar.f90 performance_name)
PERF_NAMES = [
    'rr2', 'sr2', 'mr2', 'rmae', 'sre', 'rre', 'mre', 'rra',
    'sra', 'mra', 'tau', 'md2', 'mda', 'mrs', 'mcc', 'mdkg',
    'akg', 'asckg', 'mar', 'mdnr', 'mnw', 'snr', 'smb', 'numrc', 'nummc'
]

# Parameter type mapping (matches model_hype.f90 define_model_parameters)
PARAM_TYPES = {
    # General parameters
    'lp': 'general', 'cevpam': 'general', 'cevpph': 'general',
    'rrcs3': 'general', 'rivvel': 'general', 'damp': 'general',
    'fastn0': 'general', 'fastp0': 'general', 'denitwrm': 'general',
    'sedon': 'general', 'sedpp': 'general', 'sedexp': 'general',
    'rcgrw': 'general', 'epotdist': 'general', 'deepmem': 'general',
    'tcalt': 'general', 'gratk': 'general', 'gratp': 'general',
    'maxwidth': 'general', 'init1': 'general', 'init2': 'general',
    'littdays': 'general', 'tcelevadd': 'general', 'pcelevmax': 'general',
    'pcelevadd': 'general', 'pcelevth': 'general', 'pcaddg': 'general',
    'qmean': 'general', 'ttpd': 'general', 'ttpi': 'general',
    'sfdmax': 'general', 'numdir': 'general', 'wsfscale': 'general',
    'wsfbias': 'general', 'gldepi': 'general', 'sswcorr': 'general',
    'regirr': 'general', 'immdepth': 'general', 'iwdfrac': 'general',
    'irrdemand': 'general', 'wprodn': 'general',
    't1evap': 'general', 't1zero': 'general',
    'sndrlscale': 'general', 'sdnsscale': 'general', 'sndrwscale': 'general',
    # Land-use dependent parameters
    'ttmp': 'landuse', 'cmlt': 'landuse', 'cevp': 'landuse',
    'srrcs': 'landuse', 'frost': 'landuse', 'surfmem': 'landuse',
    'denitrlu': 'landuse', 'dissolfn': 'landuse', 'dissolfp': 'landuse',
    'humusn0': 'landuse', 'partp0': 'landuse', 'wsfluse': 'landuse',
    'dissolhn': 'landuse', 'dissolhp': 'landuse', 'degradhn': 'landuse',
    'minerfn': 'landuse', 'minerfp': 'landuse', 'depthrel': 'landuse',
    'hnhalf': 'landuse', 'pphalf': 'landuse', 'humusp0': 'landuse',
    # Soil-type dependent parameters
    'wcfc': 'soil', 'wcwp': 'soil', 'wcep': 'soil',
    'wcfc1': 'soil', 'wcwp1': 'soil', 'wcep1': 'soil',
    'wcfc2': 'soil', 'wcwp2': 'soil', 'wcep2': 'soil',
    'wcfc3': 'soil', 'wcwp3': 'soil', 'wcep3': 'soil',
    'rrcs1': 'soil', 'rrcs2': 'soil', 'trrcs': 'soil',
    'mperc1': 'soil', 'mperc2': 'soil',
    'freuc': 'soil', 'freuexp': 'soil', 'freurate': 'soil',
    'soilcoh': 'soil', 'soilerod': 'soil',
    # Region-dependent parameters
    'tempcorr': 'region', 'tpmean': 'region',
}


def parse_allsim(filepath):
    """
    Parse allsim.txt -- contains all simulation results from MC/DEMC.

    Format (CSV-like, comma-separated):
        NO,CRIT,perf1,perf2,...,param1,param2,...[,POPULATION,GENERATION,ACCEPTED]

    Returns:
        dict with keys: 'header', 'data' (list of dicts), 'param_names', 'n_sims'
    """
    if not os.path.exists(filepath):
        logger.warning(f"allsim.txt not found: {filepath}")
        return None

    with open(filepath, 'r') as f:
        header_line = f.readline().strip()
        if header_line.startswith('%'):
            header_line = header_line[1:]  # Strip matlab comment prefix

        headers = [h.strip() for h in header_line.split(',')]

        data = []
        for line in f:
            line = line.strip()
            if not line or line.startswith('!') or line.startswith('%'):
                continue
            try:
                values = [v.strip() for v in line.split(',')]
                row = {}
                for i, h in enumerate(headers):
                    if i < len(values):
                        try:
                            row[h] = float(values[i])
                        except ValueError:
                            row[h] = values[i]
                data.append(row)
            except Exception as e:
                logger.debug(f"Skipping malformed line: {e}")
                continue

    # Identify parameter columns (everything after perf columns, before POPULATION/GENERATION/ACCEPTED)
    meta_cols = {'NO', 'CRIT', 'POPULATION', 'GENERATION', 'ACCEPTED'}
    perf_cols = set(PERF_NAMES)
    param_names = [h for h in headers if h not in meta_cols and h.lower() not in perf_cols
                   and not any(h.lower().startswith(p) for p in PERF_NAMES)]

    # Better heuristic: param columns come after perf columns
    # In the heading: NO, CRIT, perf*numcrit, param1, param2, ..., [POP, GEN, ACC]
    crit_idx = headers.index('CRIT') if 'CRIT' in headers else 1
    # Count how many perf columns there are (groups of 25 per criterion)
    # Simpler: param names are those matching known parameter names or after perf block
    param_names_final = []
    for h in headers:
        h_lower = h.strip().lower()
        if h_lower in PARAM_TYPES:
            param_names_final.append(h)
        elif '_' in h_lower:
            # Could be param_soiltype like wcfc_1, wcfc_2
            base = h_lower.split('_')[0]
            if base in PARAM_TYPES:
                param_names_final.append(h)

    if not param_names_final:
        # Fallback: use the header-based detection
        param_names_final = param_names

    result = {
        'headers': headers,
        'data': data,
        'param_names': param_names_final,
        'n_sims': len(data),
    }

    logger.info(f"Parsed allsim.txt: {len(data)} simulations, {len(param_names_final)} parameters")
    return result


def parse_bestsims(filepath):
    """
    Parse bestsims.txt -- contains the best parameter sets.

    Same format as allsim.txt but only the top-N simulations.
    For DEMC, row 1 = median of populations, rows 2..npop+1 = individual populations.

    Returns:
        Same structure as parse_allsim
    """
    if not os.path.exists(filepath):
        logger.warning(f"bestsims.txt not found: {filepath}")
        return None

    return parse_allsim(filepath)  # Same format


def parse_calibration_log(filepath):
    """
    Parse calibration.log for convergence diagnostics.

    The format varies by method but generally contains iteration-by-iteration
    progress with criterion values.

    Returns:
        dict with iteration history
    """
    if not os.path.exists(filepath):
        logger.warning(f"calibration.log not found: {filepath}")
        return None

    iterations = []
    with open(filepath, 'r') as f:
        for line in f:
            # Look for lines with criterion values
            # Common patterns: "Gen X Pop Y: crit = Z" or "Iter X: crit = Z"
            line = line.strip()
            if not line:
                continue

            # Try to extract numeric criterion values
            # DEMC format: typically has generation and population info
            crit_match = re.search(r'crit\w*\s*[=:]\s*([-\d.eE+]+)', line, re.IGNORECASE)
            gen_match = re.search(r'[Gg]en\w*\s*[=:]\s*(\d+)', line)
            pop_match = re.search(r'[Pp]op\w*\s*[=:]\s*(\d+)', line)
            iter_match = re.search(r'[Ii]ter\w*\s*[=:]\s*(\d+)', line)

            if crit_match:
                entry = {'criterion': float(crit_match.group(1))}
                if gen_match:
                    entry['generation'] = int(gen_match.group(1))
                if pop_match:
                    entry['population'] = int(pop_match.group(1))
                if iter_match:
                    entry['iteration'] = int(iter_match.group(1))
                iterations.append(entry)

    logger.info(f"Parsed calibration.log: {len(iterations)} entries")
    return {'iterations': iterations}


def extract_best_parameters(allsim_data, bestsim_data=None):
    """
    Extract the best parameter set from calibration results.

    For DEMC: uses the median parameters (row 1 of bestsims.txt)
    For MC: uses the best criterion simulation

    Returns:
        dict mapping parameter_name -> value
    """
    # Prefer bestsims.txt if available
    if bestsim_data and bestsim_data['data']:
        best_row = bestsim_data['data'][0]  # First row = best (or median for DEMC)
        best_crit = best_row.get('CRIT', None)
        logger.info(f"Best criterion value (from bestsims.txt): {best_crit}")
    elif allsim_data and allsim_data['data']:
        # Find row with best criterion (highest for maximization criteria like KGE/NSE)
        best_row = max(allsim_data['data'], key=lambda r: r.get('CRIT', float('-inf')))
        best_crit = best_row.get('CRIT', None)
        logger.info(f"Best criterion value (from allsim.txt): {best_crit}")
    else:
        logger.error("No calibration data available")
        return None, None

    # Extract parameter values
    param_names = (bestsim_data or allsim_data)['param_names']
    best_params = {}
    for name in param_names:
        if name in best_row:
            best_params[name] = best_row[name]

    return best_params, best_crit


def read_geoclass(filepath):
    """Read GeoClass.txt and return landuse/soil type counts."""
    landuse_ids = set()
    soil_ids = set()

    with open(filepath) as f:
        for line in f:
            if line.startswith('!!') or line.strip() == '':
                continue
            parts = line.strip().split()
            if len(parts) >= 3:
                try:
                    landuse = int(parts[1])
                    soil = int(parts[2])
                    landuse_ids.add(landuse)
                    soil_ids.add(soil)
                except ValueError:
                    continue

    return max(landuse_ids) if landuse_ids else 1, max(soil_ids) if soil_ids else 1


def write_best_par_txt(best_params, output_path, n_landuse=None, n_soil=None):
    """
    Write the best calibrated parameters as a HYPE par.txt file.

    This can be used directly or merged with an existing par.txt.
    """
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)

    # Group parameters by type
    general_params = {}
    landuse_params = {}
    soil_params = {}
    unknown_params = {}

    for name, value in best_params.items():
        name_lower = name.strip().lower()
        # Handle indexed names like wcfc_1, wcfc_2
        base_name = name_lower.split('_')[0] if '_' in name_lower else name_lower
        ptype = PARAM_TYPES.get(base_name, 'unknown')

        if ptype == 'general':
            general_params[base_name] = value
        elif ptype == 'landuse':
            if base_name not in landuse_params:
                landuse_params[base_name] = {}
            if '_' in name_lower:
                idx = int(name_lower.split('_')[1]) - 1
            else:
                idx = 0
            landuse_params[base_name][idx] = value
        elif ptype == 'soil':
            if base_name not in soil_params:
                soil_params[base_name] = {}
            if '_' in name_lower:
                idx = int(name_lower.split('_')[1]) - 1
            else:
                idx = 0
            soil_params[base_name][idx] = value
        else:
            unknown_params[name] = value

    with open(output_path, 'w') as f:
        f.write("!! par.txt -- Best calibrated parameters from HYPE optimization\n")
        f.write("!! Generated by HydroCraft parse_calibration_results.py\n")
        f.write("!!\n")

        if general_params:
            f.write("!! General parameters (1 value each)\n")
            for name, val in sorted(general_params.items()):
                f.write(f"{name}\t{val}\n")

        if landuse_params:
            nlu = n_landuse or max(max(v.keys()) + 1 for v in landuse_params.values() if v)
            f.write(f"!! Land use dependent parameters ({nlu} values each)\n")
            for name in sorted(landuse_params.keys()):
                vals = landuse_params[name]
                line_vals = []
                for i in range(nlu):
                    line_vals.append(str(vals.get(i, 0.0)))
                f.write(f"{name}\t" + "\t".join(line_vals) + "\n")

        if soil_params:
            nso = n_soil or max(max(v.keys()) + 1 for v in soil_params.values() if v)
            f.write(f"!! Soil type dependent parameters ({nso} values each)\n")
            for name in sorted(soil_params.keys()):
                vals = soil_params[name]
                line_vals = []
                for i in range(nso):
                    line_vals.append(str(vals.get(i, 0.0)))
                f.write(f"{name}\t" + "\t".join(line_vals) + "\n")

        if unknown_params:
            f.write("!! Other parameters\n")
            for name, val in sorted(unknown_params.items()):
                f.write(f"{name}\t{val}\n")

    logger.info(f"Written best parameters to: {output_path}")
    logger.info(f"  General: {len(general_params)}, Land-use: {len(landuse_params)}, "
                f"Soil: {len(soil_params)}")


def write_csv(allsim_data, output_path):
    """Write parsed results to CSV for further analysis."""
    if not allsim_data or not allsim_data['data']:
        logger.warning("No data to write to CSV")
        return

    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)

    headers = allsim_data['headers']
    with open(output_path, 'w') as f:
        f.write(','.join(headers) + '\n')
        for row in allsim_data['data']:
            values = [str(row.get(h, '')) for h in headers]
            f.write(','.join(values) + '\n')

    logger.info(f"Written CSV: {output_path} ({len(allsim_data['data'])} rows)")


def compute_convergence_stats(allsim_data):
    """Compute convergence statistics from all simulations."""
    if not allsim_data or not allsim_data['data']:
        return None

    crits = [r.get('CRIT', float('nan')) for r in allsim_data['data']]
    crits = [c for c in crits if not np.isnan(c)]

    if not crits:
        return None

    # Running best
    running_best = []
    current_best = float('-inf')
    for c in crits:
        if c > current_best:
            current_best = c
        running_best.append(current_best)

    stats = {
        'n_simulations': len(crits),
        'best_criterion': max(crits),
        'worst_criterion': min(crits),
        'mean_criterion': np.mean(crits),
        'std_criterion': np.std(crits),
        'best_sim_index': crits.index(max(crits)) + 1,
        'running_best': running_best,
        'all_crits': crits,
    }

    # Check convergence: was there improvement in last 10% of runs?
    n = len(crits)
    if n > 20:
        early_best = max(crits[:int(n * 0.9)])
        late_best = max(crits[int(n * 0.9):])
        stats['converged'] = (late_best - early_best) < 0.001 * abs(early_best) if early_best != 0 else True
        stats['improvement_last_10pct'] = late_best - early_best
    else:
        stats['converged'] = None

    return stats


def plot_convergence(allsim_data, output_path):
    """Generate convergence plot (criterion vs simulation number)."""
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
    except ImportError:
        logger.warning("matplotlib not available -- skipping convergence plot")
        return

    stats = compute_convergence_stats(allsim_data)
    if not stats:
        logger.warning("No convergence data to plot")
        return

    fig, axes = plt.subplots(2, 1, figsize=(10, 8), sharex=True)

    # Top: All criterion values
    ax1 = axes[0]
    ax1.scatter(range(1, len(stats['all_crits']) + 1), stats['all_crits'],
                alpha=0.3, s=5, c='steelblue', label='All simulations')
    ax1.plot(range(1, len(stats['running_best']) + 1), stats['running_best'],
             'r-', linewidth=2, label='Running best')
    ax1.set_ylabel('Criterion Value')
    ax1.set_title('HYPE Calibration Convergence')
    ax1.legend()
    ax1.grid(True, alpha=0.3)

    # Bottom: Running best detail
    ax2 = axes[1]
    ax2.plot(range(1, len(stats['running_best']) + 1), stats['running_best'],
             'r-', linewidth=2)
    ax2.set_xlabel('Simulation Number')
    ax2.set_ylabel('Best Criterion Value')
    ax2.set_title(f"Best: {stats['best_criterion']:.4f} (sim #{stats['best_sim_index']})")
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    plt.close()

    logger.info(f"Convergence plot saved: {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description='Parse HYPE calibration output (allsim.txt, bestsims.txt, calibration.log)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Output files produced by HYPE calibration:
  allsim.txt       All simulation results (criterion, performance, parameters)
  bestsims.txt     Best N parameter sets
  calibration.log  Detailed calibration progress

This tool parses these files and produces:
  - CSV of all results for analysis
  - Best parameters in par.txt format (can be used directly)
  - Convergence plot (PNG)
  - Summary statistics printed to stdout

Examples:
  # Basic: just get best parameters
  python parse_calibration_results.py \\
      --result_dir resultdir/ --output_par best_par.txt --geoclass modelfiles/GeoClass.txt

  # Full analysis
  python parse_calibration_results.py \\
      --result_dir resultdir/ --output_csv calib.csv --output_par best_par.txt \\
      --geoclass modelfiles/GeoClass.txt --plot_convergence convergence.png
        """)

    parser.add_argument('--result_dir', required=True,
                       help='HYPE result directory (contains allsim.txt, bestsims.txt)')
    parser.add_argument('--output_csv', default=None,
                       help='Output CSV file with all simulation results')
    parser.add_argument('--output_par', default=None,
                       help='Output par.txt with best calibrated parameters')
    parser.add_argument('--geoclass', default=None,
                       help='GeoClass.txt path (needed for par.txt output formatting)')
    parser.add_argument('--plot_convergence', default=None,
                       help='Output PNG convergence plot path')
    parser.add_argument('--output_json', default=None,
                       help='Output JSON summary file')

    args = parser.parse_args()

    result_dir = args.result_dir.rstrip('/')

    # Parse available output files
    allsim_path = os.path.join(result_dir, 'allsim.txt')
    bestsim_path = os.path.join(result_dir, 'bestsims.txt')
    callog_path = os.path.join(result_dir, 'calibration.log')

    allsim_data = parse_allsim(allsim_path)
    bestsim_data = parse_bestsims(bestsim_path)
    callog_data = parse_calibration_log(callog_path)

    if not allsim_data and not bestsim_data:
        logger.error("No calibration output files found. Expected allsim.txt or bestsims.txt "
                     f"in {result_dir}")
        sys.exit(1)

    # Extract best parameters
    best_params, best_crit = extract_best_parameters(allsim_data, bestsim_data)

    # Compute convergence statistics
    conv_stats = compute_convergence_stats(allsim_data)

    # Print summary
    print("\n" + "=" * 60)
    print("HYPE CALIBRATION RESULTS SUMMARY")
    print("=" * 60)

    if conv_stats:
        print(f"Total simulations:  {conv_stats['n_simulations']}")
        print(f"Best criterion:     {conv_stats['best_criterion']:.6f}")
        print(f"Best at simulation: #{conv_stats['best_sim_index']}")
        print(f"Mean criterion:     {conv_stats['mean_criterion']:.6f}")
        print(f"Std criterion:      {conv_stats['std_criterion']:.6f}")
        if conv_stats['converged'] is not None:
            status = "YES" if conv_stats['converged'] else "NO (improvement still occurring)"
            print(f"Converged:          {status}")
            if conv_stats['improvement_last_10pct'] is not None:
                print(f"Last 10% improvement: {conv_stats['improvement_last_10pct']:.6f}")
    elif best_crit is not None:
        print(f"Best criterion: {best_crit:.6f}")

    if best_params:
        print(f"\nBest parameters ({len(best_params)}):")
        print("-" * 40)
        for name, val in sorted(best_params.items()):
            print(f"  {name:15s} = {val}")

    print("=" * 60 + "\n")

    # Write outputs
    if args.output_csv and allsim_data:
        write_csv(allsim_data, args.output_csv)

    if args.output_par and best_params:
        n_landuse, n_soil = None, None
        if args.geoclass and os.path.exists(args.geoclass):
            n_landuse, n_soil = read_geoclass(args.geoclass)
        write_best_par_txt(best_params, args.output_par, n_landuse, n_soil)

    if args.plot_convergence and allsim_data:
        plot_convergence(allsim_data, args.plot_convergence)

    if args.output_json:
        summary = {
            'best_criterion': best_crit,
            'best_parameters': best_params,
            'n_simulations': conv_stats['n_simulations'] if conv_stats else None,
            'converged': conv_stats['converged'] if conv_stats else None,
        }
        os.makedirs(os.path.dirname(args.output_json) or '.', exist_ok=True)
        with open(args.output_json, 'w') as f:
            json.dump(summary, f, indent=2, default=str)
        logger.info(f"Written JSON summary: {args.output_json}")


if __name__ == '__main__':
    main()
