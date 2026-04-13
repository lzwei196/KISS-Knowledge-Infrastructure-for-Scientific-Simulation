#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
Tool ID:      generate_project_xml
Stage:        s1_project_setup
Description:  Generate LDNDC project.xml using the sourceprefix format.
              Uses absolute paths for portability (LDNDC resolves relative to its
              own projects/ directory, not the project.xml location).

Inputs:
  - project_dir: LDNDC project root (must contain input/ and output/ subdirs)
  - lat, lon: Site coordinates
  - start_date, end_date: Simulation period (YYYY-MM-DD)
  - site_name: Optional label for output file prefix (default: "site")

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import json
import logging
from pathlib import Path
from datetime import datetime

PROJECT_DIR = ""
LAT = 0.0
LON = 0.0
START_DATE = ""
END_DATE = ""
SITE_NAME = "site"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def validate_inputs():
    errors = []
    if not PROJECT_DIR:
        errors.append("PROJECT_DIR is not set")
    elif not Path(PROJECT_DIR).is_dir():
        errors.append(f"PROJECT_DIR not found: {PROJECT_DIR}")
    if not START_DATE or not END_DATE:
        errors.append("START_DATE and END_DATE are required (YYYY-MM-DD)")
    else:
        try:
            s = datetime.strptime(START_DATE, "%Y-%m-%d")
            e = datetime.strptime(END_DATE, "%Y-%m-%d")
            if s >= e:
                errors.append("START_DATE must be before END_DATE")
        except ValueError as ex:
            errors.append(f"Date format error: {ex}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def process():
    project_path = Path(PROJECT_DIR).resolve()
    input_prefix = str(project_path / "input") + "/"
    output_prefix = str(project_path / "output" / f"{SITE_NAME}_")

    sy = int(START_DATE[:4])
    ey = int(END_DATE[:4])
    duration = ey - sy

    output_path = project_path / "project.xml"

    with open(output_path, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" ?>\n')
        f.write('<ldndcproject PackageMinimumVersionRequired="1.3">\n')
        f.write(f'    <schedule time="{sy}-01-01/24 -> +{duration}-0-0" />\n')
        f.write("    <input>\n")
        f.write(f'        <sources sourceprefix="{input_prefix}">\n')
        f.write('            <setup source="setup.xml" />\n')
        f.write('            <site source="site.xml" />\n')
        f.write('            <airchemistry source="airchem.txt" format="txt" />\n')
        f.write('            <climate source="climate.txt" />\n')
        f.write('            <event source="mana.xml" />\n')
        f.write("        </sources>\n")
        f.write('        <attributes use="0" endless="0">\n')
        f.write('            <airchemistry endless="yes" />\n')
        f.write('            <climate endless="1" />\n')
        f.write("        </attributes>\n")
        f.write("    </input>\n")
        f.write("    <output>\n")
        f.write(f'        <sinks sinkprefix="{output_prefix}" />\n')
        f.write("    </output>\n")
        f.write("</ldndcproject>\n")

    logger.info(f"Generated project.xml at {output_path}")
    return str(output_path)


def validate_outputs(output_path):
    content = Path(output_path).read_text()
    if "<ldndcproject" not in content:
        logger.error("project.xml missing root element")
        sys.exit(3)
    if "sourceprefix" not in content:
        logger.error("project.xml missing sourceprefix")
        sys.exit(3)
    logger.info("Output validation passed.")


if __name__ == "__main__":
    if len(sys.argv) >= 6:
        PROJECT_DIR = sys.argv[1]
        LAT = float(sys.argv[2])
        LON = float(sys.argv[3])
        START_DATE = sys.argv[4]
        END_DATE = sys.argv[5]
    if len(sys.argv) >= 7:
        SITE_NAME = sys.argv[6]
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try:
        output_path = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        sys.exit(2)
    validate_outputs(output_path)
    print(json.dumps({"status": "success", "project_xml": output_path}))
    sys.exit(0)
