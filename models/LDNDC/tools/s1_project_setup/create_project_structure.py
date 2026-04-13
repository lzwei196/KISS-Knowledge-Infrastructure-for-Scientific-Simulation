#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
Tool ID:      create_project_structure
Stage:        s1_project_setup
Description:  Create LDNDC project directory with input/ and output/ subdirectories

Inputs:
  - project_dir: Root directory for the LDNDC project (directory)
  - basin_name: Basin/site identifier (string)

Outputs:
  - project_dir/: Created directory with input/ and output/ subdirs

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import json
import logging
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
PROJECT_DIR = ""    # e.g., "outputs/huaihe_ldndc/ldndc_project"
BASIN_NAME = ""     # e.g., "huaihe"

# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def validate_inputs():
    errors = []
    if not PROJECT_DIR:
        errors.append("PROJECT_DIR is not set")
    if not BASIN_NAME:
        errors.append("BASIN_NAME is not set")
    parent = Path(PROJECT_DIR).parent
    if PROJECT_DIR and not parent.exists():
        errors.append(f"Parent directory does not exist: {parent}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")

def process():
    project_path = Path(PROJECT_DIR)
    project_path.mkdir(parents=True, exist_ok=True)
    (project_path / "input").mkdir(exist_ok=True)
    (project_path / "output").mkdir(exist_ok=True)
    logger.info(f"Created project structure at {project_path}")
    return str(project_path)

def validate_outputs(output_path):
    p = Path(output_path)
    errors = []
    if not (p / "input").is_dir():
        errors.append("input/ subdirectory not created")
    if not (p / "output").is_dir():
        errors.append("output/ subdirectory not created")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(3)
    logger.info("Output validation passed.")

if __name__ == "__main__":
    if len(sys.argv) >= 3:
        PROJECT_DIR = sys.argv[1]
        BASIN_NAME = sys.argv[2]
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try:
        output_path = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        sys.exit(2)
    validate_outputs(output_path)
    print(json.dumps({"status": "success", "project_dir": output_path}))
    sys.exit(0)
