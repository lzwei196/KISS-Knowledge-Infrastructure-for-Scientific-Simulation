#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
Tool ID:      generate_setup_xml
Stage:        s3_setup_modules
Description:  Generate LDNDC setup.xml with MoBiLE module selection.
              Uses the proven <ldndcsetup><setup><models><mobile><modulelist> format.

Inputs:
  - project_dir: LDNDC project root
  - ecosystem_type: "cropland", "forest", "grassland" (determines module selection)
  - output_detail: "standard" or "detailed" (controls output module count)
  - lat, lon, elevation: Site coordinates (optional, for location tag)

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import json
import logging
from pathlib import Path

PROJECT_DIR = ""
ECOSYSTEM_TYPE = "cropland"
OUTPUT_DETAIL = "standard"
LAT = "0"
LON = "0"
ELEVATION = "0"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# All ecosystem types use the same MoBiLE process modules
PROCESS_MODULES = [
    ("microclimate:canopyecm", "subdaily"),
    ("watercycle:watercycledndc", "subdaily"),
    ("airchemistry:airchemistrydndc", "subdaily"),
    ("physiology:plamox", "subdaily"),
    ("soilchemistry:metrx", "subdaily"),
]

OUTPUT_MODULES_STANDARD = [
    "output:soilchemistry:daily",
    "output:soilchemistry:yearly",
    "output:watercycle:daily",
    "output:physiology:daily",
    "output:microclimate:daily",
]

OUTPUT_MODULES_DETAILED = OUTPUT_MODULES_STANDARD + [
    "output:report:arable:harvest",
    "output:report:arable:fertilize",
]


def validate_inputs():
    errors = []
    if not PROJECT_DIR or not Path(PROJECT_DIR).is_dir():
        errors.append(f"PROJECT_DIR not found: {PROJECT_DIR}")
    if ECOSYSTEM_TYPE not in ("cropland", "forest", "grassland"):
        errors.append(f"Unknown ecosystem: {ECOSYSTEM_TYPE}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def process():
    output_mods = OUTPUT_MODULES_DETAILED if OUTPUT_DETAIL == "detailed" else OUTPUT_MODULES_STANDARD

    output_path = Path(PROJECT_DIR) / "input" / "setup.xml"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0"?>\n')
        f.write("<ldndcsetup>\n")
        f.write(f'    <setup id="0" name="{ECOSYSTEM_TYPE}_site">\n')
        f.write(f'        <location elevation="{ELEVATION}" latitude="{LAT}" longitude="{LON}" slope="0" />\n')
        f.write("        <models>\n")
        f.write('            <model id="_MoBiLE" />\n')
        f.write("        </models>\n")
        f.write("        <mobile>\n")
        f.write("            <modulelist>\n")
        for mod_id, timemode in PROCESS_MODULES:
            f.write(f'                <module id="{mod_id}" timemode="{timemode}" />\n')
        f.write("                <!-- outputs -->\n")
        for mod_id in output_mods:
            if "report" in mod_id:
                f.write(f'                <module id="{mod_id}" timemode="subdaily" />\n')
            else:
                f.write(f'                <module id="{mod_id}" />\n')
        f.write("            </modulelist>\n")
        f.write("        </mobile>\n")
        f.write("    </setup>\n")
        f.write("</ldndcsetup>\n")

    logger.info(f"Generated setup.xml for {ECOSYSTEM_TYPE} ({OUTPUT_DETAIL} output)")
    return str(output_path)


def validate_outputs(output_path):
    content = Path(output_path).read_text()
    if '_MoBiLE' not in content or "modulelist" not in content:
        logger.error("setup.xml missing required elements")
        sys.exit(3)
    logger.info("Output validation passed.")


if __name__ == "__main__":
    if len(sys.argv) >= 3:
        PROJECT_DIR = sys.argv[1]
        ECOSYSTEM_TYPE = sys.argv[2]
    if len(sys.argv) >= 4:
        OUTPUT_DETAIL = sys.argv[3]
    if len(sys.argv) >= 6:
        LAT = sys.argv[4]
        LON = sys.argv[5]
    if len(sys.argv) >= 7:
        ELEVATION = sys.argv[6]
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try:
        output_path = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        sys.exit(2)
    validate_outputs(output_path)
    print(json.dumps({"status": "success", "setup_xml": output_path}))
    sys.exit(0)
