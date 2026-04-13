#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
Tool ID:      run_ldndc
Stage:        s8_execution
Description:  Execute LDNDC binary with project.xml, capture stdout/stderr, check exit code.

Inputs:
  - ldndc_binary: Path to ldndc executable
  - project_xml: Path to project.xml

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""
import sys, os, json, logging, subprocess
from pathlib import Path

LDNDC_BINARY = "/home/server/LDNDC/bin/ldndc"
PROJECT_XML = ""

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def validate_inputs():
    errors = []
    if not Path(LDNDC_BINARY).exists():
        errors.append(f"LDNDC binary not found: {LDNDC_BINARY}")
    elif not os.access(LDNDC_BINARY, os.X_OK):
        errors.append(f"LDNDC binary not executable: {LDNDC_BINARY}")
    if not PROJECT_XML or not Path(PROJECT_XML).exists():
        errors.append(f"project.xml not found: {PROJECT_XML}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")

def process():
    project_dir = Path(PROJECT_XML).parent
    logger.info(f"Running LDNDC from {project_dir}")
    logger.info(f"Command: {LDNDC_BINARY} {Path(PROJECT_XML).name}")
    result = subprocess.run(
        [LDNDC_BINARY, Path(PROJECT_XML).name],
        cwd=str(project_dir),
        capture_output=True,
        text=True,
        timeout=3600,  # 1 hour max
    )
    if result.stdout:
        logger.info(f"STDOUT:\n{result.stdout[-2000:]}")
    if result.stderr:
        logger.warning(f"STDERR:\n{result.stderr[-2000:]}")
    if result.returncode != 0:
        logger.error(f"LDNDC exited with code {result.returncode}")
        # Check for common errors
        combined = result.stdout + result.stderr
        if "Segmentation fault" in combined or "SIGSEGV" in combined:
            logger.error("Segfault detected -- check site.xml for zero bulk density or zero-thickness layers (dt_010)")
        if "NaN" in combined or "nan" in combined:
            logger.error("NaN detected -- check for extreme soil parameters or climate values (dt_011)")
        if "Cannot open" in combined or "not found" in combined:
            logger.error("File not found -- check sourceprefix in project.xml (dt_001)")
        raise RuntimeError(f"LDNDC failed with exit code {result.returncode}")
    output_dir = project_dir / "output"
    output_files = list(output_dir.glob("*.txt")) if output_dir.exists() else []
    logger.info(f"LDNDC completed successfully. {len(output_files)} output files generated.")
    return str(output_dir)

def validate_outputs(output_dir):
    p = Path(output_dir)
    if not p.is_dir():
        logger.error(f"Output directory not found: {output_dir}")
        sys.exit(3)
    files = list(p.glob("*.txt"))
    if len(files) == 0:
        logger.error("No output files generated")
        sys.exit(3)
    for f in files:
        if f.stat().st_size < 10:
            logger.warning(f"Output file is nearly empty: {f}")
    logger.info(f"Output validation passed: {len(files)} files")

if __name__ == "__main__":
    if len(sys.argv) >= 3:
        LDNDC_BINARY = sys.argv[1]
        PROJECT_XML = sys.argv[2]
    elif len(sys.argv) >= 2:
        PROJECT_XML = sys.argv[1]
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try:
        output_dir = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        sys.exit(2)
    validate_outputs(output_dir)
    print(json.dumps({"status": "success", "output_dir": output_dir}))
    sys.exit(0)
