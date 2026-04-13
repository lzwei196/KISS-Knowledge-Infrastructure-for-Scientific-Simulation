#!/usr/bin/env python3
"""
Execute GEOPHIRES simulation with preflight checks and output capture.

Handles:
  - Input file validation (existence, basic format checks)
  - Virtual environment activation
  - GEOPHIRES execution via 'python -m geophires_x'
  - Output capture (.out and .json)
  - Error logging and timeout handling

Usage:
    python run_geophires.py --input input_file.txt --output output_file.out \
        [--venv /path/to/venv] [--timeout 300]
"""

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 300  # seconds
DEFAULT_OUTPUT = 'HDR.out'


def validate_inputs(input_path: Path, venv_path: Path = None) -> list:
    """Preflight checks before running GEOPHIRES.

    Checks:
      1. Input file exists and is readable
      2. Input file has valid format (comma-separated, non-empty)
      3. Python/venv is available
      4. geophires_x module is importable

    Returns:
        List of issues (empty = all clear).
    """
    issues = []

    # Check input file
    if not input_path.exists():
        issues.append(f"FATAL: Input file not found: {input_path}")
        return issues

    if input_path.stat().st_size == 0:
        issues.append(f"FATAL: Input file is empty: {input_path}")
        return issues

    # Basic format check
    content = input_path.read_text()
    lines = [l.strip() for l in content.splitlines()
             if l.strip() and not l.strip().startswith('#')]

    if len(lines) == 0:
        issues.append("FATAL: Input file has no parameter lines (only comments/blanks)")
        return issues

    # Check that lines have comma-separated values
    bad_lines = []
    for i, line in enumerate(lines, 1):
        if ',' not in line:
            bad_lines.append(i)

    if bad_lines:
        issues.append(
            f"WARNING: Lines without commas (may be malformed): {bad_lines[:5]}"
            f"{'...' if len(bad_lines) > 5 else ''}"
        )

    # Check Python executable
    python_exe = _get_python(venv_path)
    if not shutil.which(python_exe) and not Path(python_exe).exists():
        issues.append(f"FATAL: Python executable not found: {python_exe}")
        return issues

    # Check geophires_x is importable
    try:
        result = subprocess.run(
            [python_exe, '-c', 'import geophires_x; print(geophires_x.__file__)'],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            issues.append(
                f"FATAL: geophires_x not importable. "
                f"Install with: pip install -e git+https://github.com/NREL/GEOPHIRES-X.git#egg=geophires-x\n"
                f"stderr: {result.stderr[:200]}"
            )
    except subprocess.TimeoutExpired:
        issues.append("WARNING: Import check timed out (may still work)")
    except FileNotFoundError:
        issues.append(f"FATAL: Python executable not found: {python_exe}")

    return issues


def _get_python(venv_path: Path = None) -> str:
    """Get the Python executable path."""
    if venv_path:
        venv_python = venv_path / 'bin' / 'python'
        if venv_python.exists():
            return str(venv_python)
        # Windows fallback
        venv_python_win = venv_path / 'Scripts' / 'python.exe'
        if venv_python_win.exists():
            return str(venv_python_win)
        logger.warning(f"Venv python not found at {venv_python}, falling back to system python")
    return sys.executable


def run_simulation(
    input_path: Path,
    output_path: Path,
    venv_path: Path = None,
    timeout: int = DEFAULT_TIMEOUT,
    source_dir: Path = None,
) -> dict:
    """Run GEOPHIRES simulation.

    Args:
        input_path: Path to .txt input file.
        output_path: Path for .out output file.
        venv_path: Optional path to Python virtual environment.
        timeout: Execution timeout in seconds.
        source_dir: Optional path to GEOPHIRES source (for editable installs).

    Returns:
        Dictionary with execution results.
    """
    python_exe = _get_python(venv_path)

    # Build command
    cmd = [python_exe, '-m', 'geophires_x', str(input_path.resolve()), str(output_path.resolve())]

    logger.info(f"Running: {' '.join(cmd)}")

    # Set up environment
    env = os.environ.copy()
    if source_dir:
        env['PYTHONPATH'] = str(source_dir / 'src') + os.pathsep + env.get('PYTHONPATH', '')

    start_time = time.time()

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(input_path.parent),
            env=env,
        )
        elapsed = time.time() - start_time

        # Check output files
        out_exists = output_path.exists()
        json_path = output_path.with_suffix('.json')
        json_exists = json_path.exists()

        return {
            'status': 'success' if result.returncode == 0 else 'error',
            'returncode': result.returncode,
            'elapsed_seconds': round(elapsed, 2),
            'stdout': result.stdout[:2000] if result.stdout else '',
            'stderr': result.stderr[:2000] if result.stderr else '',
            'output_file': str(output_path) if out_exists else None,
            'json_file': str(json_path) if json_exists else None,
            'output_size_bytes': output_path.stat().st_size if out_exists else 0,
        }

    except subprocess.TimeoutExpired:
        elapsed = time.time() - start_time
        return {
            'status': 'timeout',
            'returncode': -1,
            'elapsed_seconds': round(elapsed, 2),
            'stdout': '',
            'stderr': f'Execution timed out after {timeout} seconds',
            'output_file': None,
            'json_file': None,
            'output_size_bytes': 0,
        }

    except Exception as e:
        elapsed = time.time() - start_time
        return {
            'status': 'error',
            'returncode': -1,
            'elapsed_seconds': round(elapsed, 2),
            'stdout': '',
            'stderr': str(e),
            'output_file': None,
            'json_file': None,
            'output_size_bytes': 0,
        }


def validate_outputs(result: dict) -> list:
    """Validate execution results.

    Returns:
        List of issues found.
    """
    issues = []

    if result['status'] == 'timeout':
        issues.append("FATAL: Simulation timed out. Check input file for invalid parameters.")
        return issues

    if result['status'] == 'error':
        issues.append(f"FATAL: Simulation failed (exit code {result['returncode']})")
        if result['stderr']:
            issues.append(f"  stderr: {result['stderr'][:500]}")
        return issues

    if result['output_file'] is None:
        issues.append("WARNING: No .out output file generated")

    if result['output_size_bytes'] == 0:
        issues.append("WARNING: Output file is empty")

    if result['json_file'] is None:
        issues.append("INFO: No .json output file generated (may be expected for older versions)")

    # Check for common error patterns in output
    if result['stderr']:
        stderr = result['stderr'].lower()
        if 'error' in stderr or 'exception' in stderr:
            issues.append(f"WARNING: Errors in stderr: {result['stderr'][:300]}")

    return issues


def main():
    parser = argparse.ArgumentParser(description='Run GEOPHIRES simulation')
    parser.add_argument('--input', required=True, help='GEOPHIRES input file (.txt)')
    parser.add_argument('--output', default=DEFAULT_OUTPUT, help='Output file path (.out)')
    parser.add_argument('--venv', default=None, help='Path to Python virtual environment')
    parser.add_argument('--timeout', type=int, default=DEFAULT_TIMEOUT, help='Timeout in seconds')
    parser.add_argument('--source-dir', default=None, help='Path to GEOPHIRES source directory')
    parser.add_argument('--skip-preflight', action='store_true', help='Skip preflight checks')
    args = parser.parse_args()

    input_path = Path(args.input).resolve()
    output_path = Path(args.output).resolve()
    venv_path = Path(args.venv) if args.venv else None
    source_dir = Path(args.source_dir) if args.source_dir else None

    # Preflight
    if not args.skip_preflight:
        preflight_issues = validate_inputs(input_path, venv_path)
        for issue in preflight_issues:
            if issue.startswith('FATAL'):
                logger.error(issue)
            else:
                logger.warning(issue)

        if any(i.startswith('FATAL') for i in preflight_issues):
            print(json.dumps({'status': 'preflight_failed', 'issues': preflight_issues}, indent=2))
            sys.exit(1)

    # Run
    result = run_simulation(input_path, output_path, venv_path, args.timeout, source_dir)

    # Post-flight
    post_issues = validate_outputs(result)
    for issue in post_issues:
        logger.warning(issue)

    result['post_issues'] = post_issues
    print(json.dumps(result, indent=2))

    sys.exit(0 if result['status'] == 'success' else 1)


if __name__ == '__main__':
    main()
