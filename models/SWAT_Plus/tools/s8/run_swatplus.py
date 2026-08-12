#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
Tool ID:      run_swatplus
Stage:        s8_model_execution
Description:  Execute SWAT+ binary from TxtInOut directory. Binary reads file.cio from CWD.

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys, os, logging, json, subprocess, time
from pathlib import Path

EXECUTABLE_PATH = ""
TXTINOUT_DIR = ""

if len(sys.argv) >= 3:
    EXECUTABLE_PATH = sys.argv[1]
    TXTINOUT_DIR = sys.argv[2]

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def validate_inputs():
    errors = []
    if not EXECUTABLE_PATH or not Path(EXECUTABLE_PATH).exists():
        errors.append(f"SWAT+ binary not found: {EXECUTABLE_PATH}")
    elif not os.access(EXECUTABLE_PATH, os.X_OK):
        errors.append(f"SWAT+ binary not executable: {EXECUTABLE_PATH}")
    if not TXTINOUT_DIR or not Path(TXTINOUT_DIR).is_dir():
        errors.append(f"TxtInOut directory not found: {TXTINOUT_DIR}")
    elif not (Path(TXTINOUT_DIR) / "file.cio").exists():
        errors.append("file.cio not found in TxtInOut — SWAT+ requires file.cio in CWD")
    if errors:
        for e in errors: logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")

def process():
    exe = str(Path(EXECUTABLE_PATH).resolve())
    txtinout = Path(TXTINOUT_DIR)
    log_path = txtinout / "swatplus_run.log"

    logger.info(f"Running SWAT+ from {txtinout}...")
    start_time = time.time()

    result = subprocess.run(
        [exe],
        cwd=str(txtinout),
        capture_output=True,
        text=True,
        timeout=7200  # 2 hour timeout
    )

    elapsed = time.time() - start_time

    # Save log
    with open(log_path, 'w') as f:
        f.write(f"=== SWAT+ Run Log ===\n")
        f.write(f"Executable: {exe}\n")
        f.write(f"Working dir: {txtinout}\n")
        f.write(f"Exit code: {result.returncode}\n")
        f.write(f"Elapsed: {elapsed:.1f} seconds\n")
        f.write(f"\n=== STDOUT ===\n{result.stdout}\n")
        f.write(f"\n=== STDERR ===\n{result.stderr}\n")

    # Check for errors
    errors_found = []
    for line in (result.stdout + result.stderr).split('\n'):
        line_lower = line.lower()
        if any(kw in line_lower for kw in ['stop', 'error', 'segmentation fault', 'nan', 'infinity']):
            errors_found.append(line.strip())

    # Check output files. Names depend on which channel module and print
    # interval are active: sd_channel emits channel_sd_*; the lte channel
    # module emits channel_*. Accept any of the common markers so a successful
    # run is not falsely reported as producing no output.
    output_files = []
    for pattern in ["channel_sd_day.txt", "channel_day.txt",
                    "channel_sd_yr.txt", "channel_yr.txt",
                    "basin_wb_day.txt", "basin_wb_yr.txt",
                    "basin_nb_day.txt", "basin_nb_yr.txt"]:
        if (txtinout / pattern).exists():
            size = (txtinout / pattern).stat().st_size
            output_files.append({"file": pattern, "size_bytes": size})

    logger.info(f"SWAT+ finished in {elapsed:.1f}s, exit code={result.returncode}")

    return {
        "status": "success" if result.returncode == 0 else "failed",
        "exit_code": result.returncode,
        "elapsed_seconds": round(elapsed, 1),
        "log_file": str(log_path),
        "output_files": output_files,
        "errors": errors_found[:20]
    }

def validate_outputs(result):
    if result["exit_code"] != 0:
        logger.error(f"SWAT+ failed with exit code {result['exit_code']}")
        if result["errors"]:
            for e in result["errors"][:5]:
                logger.error(f"  {e}")
        sys.exit(3)
    if not result["output_files"]:
        logger.error("No output files created")
        sys.exit(3)
    logger.info("Output validation passed.")

if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try: result = process()
    except subprocess.TimeoutExpired:
        logger.error("SWAT+ timed out after 7200 seconds"); sys.exit(2)
    except Exception as e:
        logger.error(f"Processing failed: {e}"); sys.exit(2)
    validate_outputs(result)
    print(json.dumps(result, indent=2)); sys.exit(0)
