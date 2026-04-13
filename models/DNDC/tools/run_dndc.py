#!/usr/bin/env python3
"""Execution wrapper for running DNDC model simulations.

Follows the validate-process-validate pattern:
  1. Validate inputs (executable exists, .dnd files exist, output dir writable)
  2. Process: create batch file, run DNDC95.exe (via Wine on Linux or native on Windows)
  3. Validate outputs (check expected output files exist and are non-empty)

DNDC execution:
  - Windows: DNDC95.exe -s batch.txt -daily 0 -output outdir/
  - Linux:   wine DNDC95.exe -s batch.txt -daily 0 -output outdir/
  - Batch file format: first line = number of .dnd files, then one path per line
  - Output goes to Result/Record/Site/ or Result/Record/Batch/
"""

import argparse
import logging
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration defaults
# ---------------------------------------------------------------------------

DEFAULT_EXE_NAME = "DNDC95.exe"
DEFAULT_OUTPUT_SUBDIR = "Result"
EXPECTED_OUTPUT_DIRS = [
    "Result/Record/Site",
    "Result/Record/Batch",
    "Result/Inter",
]


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

def validate_inputs(exe_path: str, dnd_files: list[str],
                    output_dir: str, use_wine: bool | None = None) -> dict:
    """Validate all inputs before execution.

    Returns a dict with validated parameters.

    Raises
    ------
    FileNotFoundError  if executable or .dnd files are missing
    ValueError  on any invalid parameter
    """
    errors: list[str] = []

    # Resolve executable
    exe = Path(exe_path)
    if not exe.is_file():
        # Try finding it in common locations
        candidates = [
            Path(exe_path),
            Path.cwd() / exe_path,
            Path.cwd() / DEFAULT_EXE_NAME,
        ]
        found = False
        for c in candidates:
            if c.is_file():
                exe = c
                found = True
                break
        if not found:
            raise FileNotFoundError(
                f"DNDC executable not found: {exe_path} "
                f"(also checked: {[str(c) for c in candidates]})"
            )

    # Validate .dnd files
    if not dnd_files:
        errors.append("No .dnd files provided")
    validated_dnd: list[Path] = []
    for dnd in dnd_files:
        p = Path(dnd)
        if not p.is_file():
            errors.append(f"DND file not found: {dnd}")
        else:
            validated_dnd.append(p)

    # Output directory
    out_path = Path(output_dir)
    try:
        out_path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        errors.append(f"Cannot create output directory {output_dir}: {exc}")

    # Determine Wine usage
    is_linux = platform.system() != "Windows"
    if use_wine is None:
        use_wine = is_linux

    if use_wine and is_linux:
        wine_path = shutil.which("wine")
        if wine_path is None:
            errors.append(
                "Wine is required on Linux but not found in PATH. "
                "Install with: sudo apt install wine"
            )

    if errors:
        raise ValueError(
            "Input validation failed:\n  " + "\n  ".join(errors)
        )

    return {
        "exe_path": exe,
        "dnd_files": validated_dnd,
        "output_dir": out_path,
        "use_wine": use_wine,
    }


# ---------------------------------------------------------------------------
# Batch file creation
# ---------------------------------------------------------------------------

def create_batch_file(dnd_files: list[Path], batch_path: Path,
                      use_wine: bool = False) -> Path:
    """Create a DNDC batch file.

    Format:
      Line 1: number of .dnd files
      Lines 2+: paths to .dnd files (one per line)

    Parameters
    ----------
    dnd_files : list[Path]
        Validated .dnd file paths.
    batch_path : Path
        Where to write the batch file.
    use_wine : bool
        If True, convert paths to Wine-compatible format (Z:\\...).

    Returns
    -------
    Path
        Path to the created batch file.
    """
    with open(batch_path, "w") as fh:
        fh.write(f"{len(dnd_files)}\n")
        for dnd in dnd_files:
            if use_wine:
                # Convert Linux path to Wine path
                wine_path = "Z:" + str(dnd.resolve()).replace("/", "\\")
                fh.write(f"{wine_path}\n")
            else:
                fh.write(f"{dnd.resolve()}\n")

    logger.info("Created batch file: %s (%d entries)", batch_path, len(dnd_files))
    return batch_path


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def run_dndc(exe_path: Path, batch_path: Path, output_dir: Path,
             use_wine: bool, daily_output: int = 0,
             timeout: int = 3600) -> dict:
    """Execute DNDC and capture results.

    Parameters
    ----------
    exe_path : Path
        Path to DNDC95.exe.
    batch_path : Path
        Path to batch file.
    output_dir : Path
        Output directory.
    use_wine : bool
        Whether to use Wine.
    daily_output : int
        0 = summary only, 1 = daily output.
    timeout : int
        Maximum execution time in seconds.

    Returns
    -------
    dict
        Keys: returncode, stdout, stderr, elapsed_seconds, output_dir
    """
    # Build command
    if use_wine:
        exe_wine = "Z:" + str(exe_path.resolve()).replace("/", "\\")
        batch_wine = "Z:" + str(batch_path.resolve()).replace("/", "\\")
        output_wine = "Z:" + str(output_dir.resolve()).replace("/", "\\") + "\\"
        cmd = [
            "wine", str(exe_path.resolve()),
            "-s", str(batch_path.resolve()),
            "-daily", str(daily_output),
            "-output", str(output_dir.resolve()) + "/",
        ]
    else:
        cmd = [
            str(exe_path.resolve()),
            "-s", str(batch_path.resolve()),
            "-daily", str(daily_output),
            "-output", str(output_dir.resolve()) + os.sep,
        ]

    logger.info("Executing: %s", " ".join(cmd))

    start_time = time.time()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(exe_path.parent),
        )
        elapsed = time.time() - start_time

        if result.returncode != 0:
            logger.error("DNDC exited with code %d", result.returncode)
            logger.error("STDERR: %s", result.stderr[:2000] if result.stderr else "(empty)")
        else:
            logger.info("DNDC completed successfully in %.1f seconds", elapsed)

        return {
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "elapsed_seconds": elapsed,
            "output_dir": str(output_dir),
        }

    except subprocess.TimeoutExpired:
        elapsed = time.time() - start_time
        logger.error("DNDC timed out after %d seconds", timeout)
        return {
            "returncode": -1,
            "stdout": "",
            "stderr": f"Process timed out after {timeout} seconds",
            "elapsed_seconds": elapsed,
            "output_dir": str(output_dir),
        }
    except FileNotFoundError as exc:
        logger.error("Could not start DNDC: %s", exc)
        return {
            "returncode": -2,
            "stdout": "",
            "stderr": str(exc),
            "elapsed_seconds": 0.0,
            "output_dir": str(output_dir),
        }


# ---------------------------------------------------------------------------
# Output validation
# ---------------------------------------------------------------------------

def validate_outputs(output_dir: Path, num_sites: int = 1) -> dict:
    """Validate that expected DNDC outputs exist.

    Returns dict with:
        valid (bool), output_files (list[str]), issues (list[str])
    """
    issues: list[str] = []
    output_files: list[str] = []

    if not output_dir.exists():
        issues.append(f"Output directory does not exist: {output_dir}")
        return {"valid": False, "output_files": [], "issues": issues}

    # Check for expected subdirectories
    found_any_dir = False
    for subdir in EXPECTED_OUTPUT_DIRS:
        check_path = output_dir / subdir
        if check_path.exists():
            found_any_dir = True
            # Collect output files
            for f in check_path.rglob("*"):
                if f.is_file():
                    output_files.append(str(f))
                    if f.stat().st_size == 0:
                        issues.append(f"Empty output file: {f}")

    if not found_any_dir:
        # Also check top-level for any output files
        for f in output_dir.rglob("*"):
            if f.is_file() and f.suffix in (".csv", ".txt", ".out", ".dat"):
                output_files.append(str(f))
                found_any_dir = True

    if not found_any_dir:
        issues.append(
            f"No expected output subdirectories found in {output_dir}. "
            f"Expected one of: {EXPECTED_OUTPUT_DIRS}"
        )

    if not output_files:
        issues.append("No output files found")

    # Check for summary files
    summary_files = [f for f in output_files if "Summary" in f or "summary" in f]
    if not summary_files:
        issues.append("No summary output files found")
    else:
        logger.info("Found %d summary file(s)", len(summary_files))

    valid = len(issues) == 0
    if not valid:
        for issue in issues:
            logger.warning("Output validation: %s", issue)
    else:
        logger.info("Output validation passed: %d files found", len(output_files))

    return {
        "valid": valid,
        "output_files": output_files,
        "issues": issues,
    }


# ---------------------------------------------------------------------------
# Main processing
# ---------------------------------------------------------------------------

def process(exe_path: str, dnd_files: list[str], output_dir: str,
            use_wine: bool | None = None, daily_output: int = 0,
            timeout: int = 3600) -> dict:
    """End-to-end: validate -> run -> validate.

    Parameters
    ----------
    exe_path : str
        Path to DNDC95.exe.
    dnd_files : list[str]
        Paths to .dnd input files.
    output_dir : str
        Output directory for results.
    use_wine : bool or None
        Force Wine usage (None = auto-detect).
    daily_output : int
        0 = summary, 1 = daily.
    timeout : int
        Max execution time in seconds.

    Returns
    -------
    dict
        Execution results including output file paths and validation.
    """
    # --- Phase 1: Validate inputs ---
    params = validate_inputs(exe_path, dnd_files, output_dir, use_wine)
    logger.info(
        "Input validation passed. EXE: %s, DND files: %d, Wine: %s",
        params["exe_path"], len(params["dnd_files"]), params["use_wine"],
    )

    # --- Phase 2: Process ---
    batch_path = params["output_dir"] / "batch.txt"
    create_batch_file(params["dnd_files"], batch_path, params["use_wine"])

    run_result = run_dndc(
        exe_path=params["exe_path"],
        batch_path=batch_path,
        output_dir=params["output_dir"],
        use_wine=params["use_wine"],
        daily_output=daily_output,
        timeout=timeout,
    )

    # --- Phase 3: Validate outputs ---
    output_validation = validate_outputs(
        params["output_dir"],
        num_sites=len(params["dnd_files"]),
    )

    return {
        "execution": run_result,
        "validation": output_validation,
        "batch_file": str(batch_path),
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(
        description="Run DNDC model simulations."
    )
    parser.add_argument("--exe", required=True,
                        help="Path to DNDC95.exe")
    parser.add_argument("--dnd-files", nargs="+", required=True,
                        help="Path(s) to .dnd input files")
    parser.add_argument("--output-dir", required=True,
                        help="Output directory for results")
    parser.add_argument("--wine", action="store_true", default=None,
                        help="Force Wine usage (auto-detected if not set)")
    parser.add_argument("--no-wine", action="store_false", dest="wine",
                        help="Force direct execution (no Wine)")
    parser.add_argument("--daily-output", type=int, default=0, choices=[0, 1],
                        help="0=summary only, 1=daily output")
    parser.add_argument("--timeout", type=int, default=3600,
                        help="Max execution time in seconds (default 3600)")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])

    args = parser.parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    try:
        result = process(
            exe_path=args.exe,
            dnd_files=args.dnd_files,
            output_dir=args.output_dir,
            use_wine=args.wine,
            daily_output=args.daily_output,
            timeout=args.timeout,
        )

        exec_result = result["execution"]
        print(f"DNDC exit code: {exec_result['returncode']}")
        print(f"Elapsed: {exec_result['elapsed_seconds']:.1f}s")

        val = result["validation"]
        if val["valid"]:
            print(f"Output valid: {len(val['output_files'])} file(s) found")
            for f in val["output_files"][:20]:
                print(f"  {f}")
        else:
            print("Output validation FAILED:")
            for issue in val["issues"]:
                print(f"  {issue}")
            sys.exit(1)

    except Exception:
        logger.exception("Fatal error during DNDC execution")
        sys.exit(1)


if __name__ == "__main__":
    main()
