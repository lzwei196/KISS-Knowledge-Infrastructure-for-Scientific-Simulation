#!/usr/bin/env python3
"""
Execute HYPE with progress monitoring and error handling.

Runs the HYPE binary, monitors the log file for progress,
and parses error messages if the run fails.

Usage:
    python run_hype.py \
        --hype_binary KISSPATH_BINARIES/hype/hype \
        --run_dir outputs/hype_run/ \
        --timeout 3600

CRITICAL:
    - Run directory must contain info.txt
    - The directory path argument to HYPE MUST end with /
    - HYPE binary is at KISSPATH_BINARIES/hype/hype
"""

import argparse
import subprocess
import sys
import os
import time
import glob
from pathlib import Path


HYPE_BINARY = os.environ.get('HYPE_BINARY', os.path.join(
    os.environ.get('HYDROCRAFT_ROOT', 'KISSPATH_ROOT'),
    'model', 'hype', 'hype'))


def find_latest_log(run_dir):
    """Find the most recent hyss_*.log file."""
    pattern = os.path.join(run_dir, 'hyss_*.log')
    logs = sorted(glob.glob(pattern), key=os.path.getmtime)
    if logs:
        return logs[-1]

    # Also check logdir
    logdir = os.path.join(run_dir, 'logdir')
    if os.path.exists(logdir):
        pattern = os.path.join(logdir, 'hyss_*.log')
        logs = sorted(glob.glob(pattern), key=os.path.getmtime)
        if logs:
            return logs[-1]

    return None


def parse_log_for_errors(log_path):
    """Parse HYPE log file for error messages."""
    errors = []
    warnings = []

    with open(log_path) as f:
        for line in f:
            line = line.strip()
            if 'ERROR' in line.upper():
                errors.append(line)
            elif 'WARNING' in line.upper():
                warnings.append(line)

    return errors, warnings


def run_hype(run_dir, hype_binary=HYPE_BINARY, timeout=3600):
    """
    Run HYPE simulation.

    Args:
        run_dir: Directory containing info.txt and all input files
        hype_binary: Path to HYPE executable
        timeout: Maximum runtime in seconds

    Returns:
        (success: bool, message: str)
    """
    run_dir = str(run_dir)

    # Validate inputs
    if not os.path.exists(hype_binary):
        return False, f"HYPE binary not found: {hype_binary}"

    info_path = os.path.join(run_dir, 'info.txt')
    if not os.path.exists(info_path):
        return False, f"info.txt not found in {run_dir}"

    # CRITICAL: Ensure trailing slash
    if not run_dir.endswith('/'):
        run_dir += '/'

    # Create output directories if needed
    for subdir in ['resultdir', 'logdir']:
        # Read from info.txt
        with open(info_path) as f:
            for line in f:
                if line.startswith(subdir):
                    parts = line.strip().split('\t')
                    if len(parts) >= 2:
                        dir_path = parts[1].strip()
                        if not os.path.isabs(dir_path):
                            dir_path = os.path.join(run_dir, dir_path)
                        os.makedirs(dir_path, exist_ok=True)

    # Run HYPE
    print(f"Running HYPE...")
    print(f"  Binary: {hype_binary}")
    print(f"  Run dir: {run_dir}")

    start_time = time.time()

    try:
        result = subprocess.run(
            [hype_binary, run_dir],
            cwd=run_dir.rstrip('/'),
            capture_output=True,
            text=True,
            timeout=timeout
        )

        elapsed = time.time() - start_time

        # Check exit code
        if result.returncode == 0:
            # Check for result files
            result_dir = os.path.join(run_dir, 'resultdir')
            result_files = os.listdir(result_dir) if os.path.exists(result_dir) else []

            msg = f"HYPE completed successfully in {elapsed:.1f}s"
            if result_files:
                msg += f"\n  Output files: {', '.join(result_files)}"

            # Check log for warnings
            log_path = find_latest_log(run_dir)
            if log_path:
                errors, warnings = parse_log_for_errors(log_path)
                if warnings:
                    msg += f"\n  Warnings ({len(warnings)}):"
                    for w in warnings[:5]:
                        msg += f"\n    {w}"

            return True, msg
        else:
            # Parse log for error details
            log_path = find_latest_log(run_dir)
            error_details = ""
            if log_path:
                errors, _ = parse_log_for_errors(log_path)
                if errors:
                    error_details = "\n  Log errors:\n    " + "\n    ".join(errors)

            msg = f"HYPE failed with exit code {result.returncode} ({elapsed:.1f}s)"
            if result.stderr:
                msg += f"\n  stderr: {result.stderr[:500]}"
            if result.stdout:
                msg += f"\n  stdout: {result.stdout[:500]}"
            msg += error_details

            return False, msg

    except subprocess.TimeoutExpired:
        return False, f"HYPE timed out after {timeout}s"
    except Exception as e:
        return False, f"Error running HYPE: {e}"


def main():
    parser = argparse.ArgumentParser(description='Run HYPE model')
    parser.add_argument('--run_dir', required=True, help='HYPE run directory (contains info.txt)')
    parser.add_argument('--hype_binary', default=HYPE_BINARY, help='Path to HYPE executable')
    parser.add_argument('--timeout', type=int, default=3600, help='Maximum runtime in seconds')

    args = parser.parse_args()

    success, msg = run_hype(args.run_dir, args.hype_binary, args.timeout)
    print(msg)
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
