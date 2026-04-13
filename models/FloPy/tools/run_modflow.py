#!/usr/bin/env python3
"""
run_modflow.py — Execute MODFLOW with preflight checks and output validation.

Wraps the MODFLOW execution with:
1. Input validation (files exist, packages consistent)
2. Binary discovery (mf6, mf2005, mfnwt via FloPy or direct path)
3. Execution with timeout and output capture
4. Output validation (files created, convergence check, water balance)

Supports MODFLOW 6, MODFLOW-2005, MODFLOW-NWT, and MODFLOW-USG.

Typical runtimes:
  - Small model (1000 cells, steady): < 1 second
  - Medium model (100k cells, 10 stress periods): 5-30 seconds
  - Large model (1M cells, 100 stress periods): 1-30 minutes

Usage:
    python run_modflow.py --workspace ./mymodel --version mf6
    python run_modflow.py --workspace ./mymodel --exe_path /path/to/mf6 --timeout 300
    python run_modflow.py --workspace ./mymodel --version mf2005 --namefile model.nam
"""

import argparse
import json
import os
import subprocess
import sys
import time


# Default binary names by version
DEFAULT_BINARIES = {
    'mf6': 'mf6',
    'mf2005': 'mf2005',
    'mfnwt': 'mfnwt',
    'mfusg': 'mfusg',
}

# Expected namefile patterns
NAMEFILE_PATTERNS = {
    'mf6': 'mfsim.nam',
    'mf2005': '*.nam',
    'mfnwt': '*.nam',
    'mfusg': '*.nam',
}


def validate_inputs(args):
    """Preflight checks before running MODFLOW."""
    errors = []
    warnings = []

    # Check workspace
    if not os.path.isdir(args.workspace):
        errors.append(f"Workspace not found: {args.workspace}")
        print(json.dumps({
            "status": "error", "errors": errors, "warnings": warnings}))
        sys.exit(1)

    # Resolve executable
    exe_path = args.exe_path
    if not exe_path:
        exe_name = DEFAULT_BINARIES.get(args.version, 'mf6')
        # Try FloPy appdata location
        flopy_bin = os.path.expanduser('~/.local/share/flopy/bin')
        candidate = os.path.join(flopy_bin, exe_name)
        if os.path.exists(candidate) and os.access(candidate, os.X_OK):
            exe_path = candidate
        else:
            # Try system PATH
            from shutil import which
            exe_path = which(exe_name)

    if not exe_path:
        errors.append(
            f"MODFLOW binary '{args.version}' not found. "
            f"Install with: get-modflow : "
            f"or specify --exe_path")
    elif not os.access(exe_path, os.X_OK):
        errors.append(f"Binary not executable: {exe_path}")

    # Check namefile
    if args.version == 'mf6':
        namefile = os.path.join(args.workspace, 'mfsim.nam')
        if not os.path.exists(namefile):
            errors.append(
                f"MF6 simulation namefile not found: {namefile}")
        else:
            # Parse mfsim.nam for model files
            with open(namefile) as f:
                content = f.read()
            # Check TDIS exists
            import re
            tdis_match = re.search(r'TDIS6?\s+(\S+)', content)
            if tdis_match:
                tdis_path = os.path.join(args.workspace,
                                         tdis_match.group(1))
                if not os.path.exists(tdis_path):
                    errors.append(f"TDIS file not found: {tdis_path}")
    else:
        # MODFLOW-2005/NWT
        namefile = args.namefile
        if not namefile:
            import glob
            nam_files = glob.glob(os.path.join(args.workspace, '*.nam'))
            if nam_files:
                namefile = os.path.basename(nam_files[0])
            else:
                errors.append("No .nam file found in workspace")
        if namefile:
            full_nam = os.path.join(args.workspace, namefile)
            if not os.path.exists(full_nam):
                errors.append(f"Namefile not found: {full_nam}")

    if errors:
        print(json.dumps({
            "status": "error", "errors": errors, "warnings": warnings}))
        sys.exit(1)

    args._exe_path = exe_path
    args._namefile = namefile
    return warnings


def process(args, preflight_warnings):
    """Run MODFLOW and collect results."""
    exe_path = args._exe_path
    workspace = args.workspace

    start_time = time.time()
    print(f"Running {args.version} in {workspace}...", file=sys.stderr)
    print(f"Executable: {exe_path}", file=sys.stderr)

    try:
        if args.version == 'mf6':
            cmd = [exe_path]
        else:
            cmd = [exe_path, args._namefile]

        result = subprocess.run(
            cmd,
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=args.timeout
        )

        elapsed = time.time() - start_time
        stdout = result.stdout
        stderr = result.stderr

        # Check for convergence failure in output
        converged = True
        convergence_warnings = []

        if 'FAILED TO CONVERGE' in stdout.upper():
            converged = False
            convergence_warnings.append(
                "Model failed to converge. Check solver settings (IMS/PCG).")
        if 'DRY' in stdout.upper() and 'CELL' in stdout.upper():
            convergence_warnings.append(
                "Dry cells detected. Consider rewetting or NWT solver.")

        run_result = {
            'status': 'completed' if result.returncode == 0 else 'failed',
            'return_code': result.returncode,
            'elapsed_seconds': round(elapsed, 2),
            'converged': converged,
            'stdout_head': stdout[:2000] if stdout else '',
            'stderr': stderr[:1000] if stderr else '',
            'warnings': preflight_warnings + convergence_warnings
        }

        if result.returncode == 0:
            print(f"MODFLOW completed in {elapsed:.1f}s", file=sys.stderr)
        else:
            print(f"MODFLOW failed (exit code {result.returncode})",
                  file=sys.stderr)
            if stderr:
                print(f"STDERR: {stderr[:500]}", file=sys.stderr)

        return run_result

    except subprocess.TimeoutExpired:
        elapsed = time.time() - start_time
        return {
            'status': 'timeout',
            'elapsed_seconds': round(elapsed, 2),
            'timeout_seconds': args.timeout,
            'warnings': preflight_warnings + [
                f"Execution timed out after {args.timeout}s. "
                "Try increasing --timeout or simplifying the model."
            ]
        }
    except Exception as e:
        return {
            'status': 'error',
            'error': str(e),
            'warnings': preflight_warnings
        }


def validate_outputs(run_result, workspace, version):
    """Post-run validation of MODFLOW outputs."""
    errors = []
    warnings = []

    if run_result['status'] != 'completed':
        errors.append(f"Run did not complete: {run_result['status']}")
        print(json.dumps({
            "status": "error", "run": run_result,
            "errors": errors, "warnings": warnings
        }, indent=2))
        return False

    # Check for expected output files
    if version == 'mf6':
        # Look for .hds and .bud files
        import glob
        hds_files = glob.glob(os.path.join(workspace, '*.hds'))
        bud_files = glob.glob(os.path.join(workspace, '*.bud'))
        lst_files = glob.glob(os.path.join(workspace, '*.lst'))

        if not hds_files:
            warnings.append(
                "No .hds (head) output file found. "
                "Check OC package configuration.")
        if not bud_files:
            warnings.append(
                "No .bud (budget) output file found. "
                "Check OC package and save_flows setting.")
        if lst_files:
            # Quick check listing file for errors
            with open(lst_files[0]) as f:
                lst_tail = f.read()[-5000:]
            if 'ERROR' in lst_tail.upper():
                errors.append(
                    "Errors found in listing file. "
                    "Check .lst file for details.")
            if 'BUDGET PERCENT DISCREPANCY' in lst_tail.upper():
                # Extract discrepancy value
                import re
                disc_match = re.search(
                    r'PERCENT DISCREPANCY\s+=\s+([-\d.]+)', lst_tail)
                if disc_match:
                    disc = abs(float(disc_match.group(1)))
                    if disc > 1.0:
                        warnings.append(
                            f"Water balance error = {disc:.2f}%. "
                            "Should be < 1%.")
                    if disc > 5.0:
                        errors.append(
                            f"Water balance error = {disc:.2f}% — "
                            "unacceptable. Check boundary conditions.")
    else:
        import glob
        hds_files = glob.glob(os.path.join(workspace, '*.hds'))
        cbc_files = glob.glob(os.path.join(workspace, '*.cbc'))
        if not hds_files:
            warnings.append("No head output file found.")

    if not run_result.get('converged', True):
        errors.append(
            "Model did not converge. Results may be unreliable. "
            "Increase MXITER or tighten solver parameters.")

    result = {
        "status": "error" if errors else "ok",
        "run": run_result,
        "errors": errors,
        "warnings": warnings,
        "output_files": {
            "hds": [os.path.basename(f)
                    for f in glob.glob(os.path.join(workspace, '*.hds'))],
            "bud": [os.path.basename(f)
                    for f in glob.glob(os.path.join(workspace, '*.bud'))],
            "lst": [os.path.basename(f)
                    for f in glob.glob(os.path.join(workspace, '*.lst'))],
        }
    }
    print(json.dumps(result, indent=2))
    return len(errors) == 0


def main():
    parser = argparse.ArgumentParser(
        description='Run MODFLOW with validation')
    parser.add_argument('--workspace', required=True,
                        help='Model workspace directory')
    parser.add_argument('--version', default='mf6',
                        choices=['mf6', 'mf2005', 'mfnwt', 'mfusg'],
                        help='MODFLOW version')
    parser.add_argument('--exe_path', default=None,
                        help='Path to MODFLOW executable')
    parser.add_argument('--namefile', default=None,
                        help='Name file (for MF2005/NWT)')
    parser.add_argument('--timeout', type=int, default=600,
                        help='Timeout in seconds (default 600)')
    args = parser.parse_args()

    warnings_list = validate_inputs(args)
    run_result = process(args, warnings_list)
    validate_outputs(run_result, args.workspace, args.version)


if __name__ == '__main__':
    main()
