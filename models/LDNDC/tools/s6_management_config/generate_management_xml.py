#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
Tool ID:      generate_management_xml
Stage:        s6_management_config
Description:  Generate LDNDC management events XML (mana.xml).
              Uses the <ldndcevent><event id="0">...<event type="..."> nested format.

Supported rotation templates:
  - wheat_maize: Winter wheat + summer maize double cropping (Huang-Huai plain)
  - maize: Single summer maize
  - wheat: Single winter wheat
  - rice: Single rice paddy
  - forest: Forest initialization (single planting event)

Inputs:
  - project_dir: LDNDC project root
  - rotation: Rotation template name (see above)
  - start_year, end_year: Simulation period

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import json
import logging
from pathlib import Path

PROJECT_DIR = ""
ROTATION = "wheat_maize"
START_YEAR = "2000"
END_YEAR = "2005"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def validate_inputs():
    errors = []
    if not PROJECT_DIR or not Path(PROJECT_DIR).is_dir():
        errors.append(f"PROJECT_DIR not found: {PROJECT_DIR}")
    valid = ["wheat_maize", "maize", "wheat", "rice", "forest"]
    if ROTATION not in valid:
        errors.append(f"Unknown rotation: {ROTATION}. Must be: {valid}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def _write_wheat_maize(f, sy, ey):
    """Wheat-maize double cropping (Huang-Huai, ~300-360 kgN/ha/yr)."""
    for yr in range(sy, ey + 1):
        f.write(f"\n        <!-- {yr} Winter Wheat -->\n")
        if yr == sy:
            f.write(f'        <event type="till" time="{yr}-01-01">\n')
            f.write('            <till depth="0.15" />\n')
            f.write("        </event>\n")
            f.write(f'        <event type="plant" time="{yr}-01-02">\n')
            f.write('            <plant type="wiwh"><crop initialbiomass="150.0" /></plant>\n')
            f.write("        </event>\n")
        f.write(f'        <event type="fertilize" time="{yr}-03-10">\n')
        f.write('            <fertilize type="urea" amount="75" depth="0.05" />\n')
        f.write("        </event>\n")
        f.write(f'        <event type="fertilize" time="{yr}-04-20">\n')
        f.write('            <fertilize type="urea" amount="75" depth="0.05" />\n')
        f.write("        </event>\n")
        f.write(f'        <event type="harvest" time="{yr}-06-08">\n')
        f.write('            <harvest name="wiwh" remains="0.65" />\n')
        f.write("        </event>\n")

        f.write(f"\n        <!-- {yr} Summer Maize -->\n")
        f.write(f'        <event type="till" time="{yr}-06-10">\n')
        f.write('            <till depth="0.10" />\n')
        f.write("        </event>\n")
        f.write(f'        <event type="plant" time="{yr}-06-14">\n')
        f.write('            <plant type="CORN"><crop initialbiomass="150.0" /></plant>\n')
        f.write("        </event>\n")
        f.write(f'        <event type="fertilize" time="{yr}-06-15">\n')
        f.write('            <fertilize type="urea" amount="100" depth="0.05" />\n')
        f.write("        </event>\n")
        f.write(f'        <event type="fertilize" time="{yr}-07-20">\n')
        f.write('            <fertilize type="urea" amount="80" depth="0.05" />\n')
        f.write("        </event>\n")
        f.write(f'        <event type="harvest" time="{yr}-10-01">\n')
        f.write('            <harvest name="CORN" remains="0.65" />\n')
        f.write("        </event>\n")

        if yr < ey:
            f.write(f'        <event type="till" time="{yr}-10-10">\n')
            f.write('            <till depth="0.20" />\n')
            f.write("        </event>\n")
            f.write(f'        <event type="plant" time="{yr}-10-18">\n')
            f.write('            <plant type="wiwh"><crop initialbiomass="150.0" /></plant>\n')
            f.write("        </event>\n")
            f.write(f'        <event type="fertilize" time="{yr}-10-19">\n')
            f.write('            <fertilize type="nh4no3" amount="30" depth="0.05" />\n')
            f.write("        </event>\n")


def _write_maize(f, sy, ey):
    """Single summer maize."""
    for yr in range(sy, ey + 1):
        f.write(f'        <event type="till" time="{yr}-05-01"><till depth="0.15" /></event>\n')
        f.write(f'        <event type="plant" time="{yr}-06-10">\n')
        f.write('            <plant type="CORN"><crop initialbiomass="150.0" /></plant>\n')
        f.write("        </event>\n")
        f.write(f'        <event type="fertilize" time="{yr}-06-15"><fertilize type="urea" amount="120" depth="0.05" /></event>\n')
        f.write(f'        <event type="fertilize" time="{yr}-07-20"><fertilize type="urea" amount="60" depth="0.05" /></event>\n')
        f.write(f'        <event type="harvest" time="{yr}-10-01"><harvest name="CORN" remains="0.65" /></event>\n')


def _write_wheat(f, sy, ey):
    """Single winter wheat."""
    for yr in range(sy, ey + 1):
        if yr == sy:
            f.write(f'        <event type="plant" time="{yr}-01-01">\n')
            f.write('            <plant type="wiwh"><crop initialbiomass="150.0" /></plant>\n')
            f.write("        </event>\n")
        f.write(f'        <event type="fertilize" time="{yr}-03-15"><fertilize type="urea" amount="80" depth="0.05" /></event>\n')
        f.write(f'        <event type="harvest" time="{yr}-06-10"><harvest name="wiwh" remains="0.65" /></event>\n')
        if yr < ey:
            f.write(f'        <event type="till" time="{yr}-10-05"><till depth="0.20" /></event>\n')
            f.write(f'        <event type="plant" time="{yr}-10-15">\n')
            f.write('            <plant type="wiwh"><crop initialbiomass="150.0" /></plant>\n')
            f.write("        </event>\n")
            f.write(f'        <event type="fertilize" time="{yr}-10-16"><fertilize type="nh4no3" amount="40" depth="0.05" /></event>\n')


def _write_rice(f, sy, ey):
    """Single paddy rice — uses :RICE: class-path notation (bare 'RICE' is abstract and crashes).
    Irrigation events simulate paddy flooding (required for LDNDC water balance).
    Schedule: China single-season rice, transplant ~May, harvest ~Oct.
    """
    for yr in range(sy, ey + 1):
        # Land preparation + pre-flood
        f.write(f'        <event type="till" time="{yr}-04-20"><till depth="0.15" /></event>\n')
        f.write(f'        <event type="irrigate" time="{yr}-04-28"><irrigate amount="60.0" /></event>\n')
        f.write(f'        <event type="irrigate" time="{yr}-05-01"><irrigate amount="60.0" /></event>\n')
        f.write(f'        <event type="irrigate" time="{yr}-05-04"><irrigate amount="60.0" /></event>\n')
        # Transplant + basal N
        f.write(f'        <event type="plant" time="{yr}-05-08">\n')
        f.write('            <plant type=":RICE:"><crop initialbiomass="50.0" /></plant>\n')
        f.write("        </event>\n")
        f.write(f'        <event type="fertilize" time="{yr}-05-09"><fertilize type="urea" amount="80" depth="0.02" /></event>\n')
        # Growing season irrigation (every 3 days, 45mm — paddy ponding)
        import datetime
        d = datetime.date(yr, 5, 10)
        end = datetime.date(yr, 9, 10)
        while d <= end:
            f.write(f'        <event type="irrigate" time="{d.isoformat()}"><irrigate amount="45.0" /></event>\n')
            d += datetime.timedelta(days=3)
        # Topdress N at tillering and panicle
        f.write(f'        <event type="fertilize" time="{yr}-06-20"><fertilize type="urea" amount="60" depth="0.02" /></event>\n')
        f.write(f'        <event type="fertilize" time="{yr}-07-25"><fertilize type="urea" amount="40" depth="0.02" /></event>\n')
        # Harvest (no irrigation after Sep 10 → field drains before harvest)
        f.write(f'        <event type="harvest" time="{yr}-10-08"><harvest name=":RICE:" remains="0.50" /></event>\n')
        f.write(f'        <event type="till" time="{yr}-10-20"><till depth="0.10" /></event>\n')


def _write_forest(f, sy, ey):
    """Forest initialization — single planting event."""
    f.write(f'        <event type="plant" time="{sy}-01-01">\n')
    f.write('            <plant type="FASY"><crop initialbiomass="5000.0" /></plant>\n')
    f.write("        </event>\n")


WRITERS = {
    "wheat_maize": _write_wheat_maize,
    "maize": _write_maize,
    "wheat": _write_wheat,
    "rice": _write_rice,
    "forest": _write_forest,
}


def process():
    sy = int(START_YEAR)
    ey = int(END_YEAR)
    output_path = Path(PROJECT_DIR) / "input" / "mana.xml"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" ?>\n\n')
        f.write("<ldndcevent>\n")
        f.write('    <event id="0">\n')
        WRITERS[ROTATION](f, sy, ey)
        f.write("\n    </event>\n")
        f.write("</ldndcevent>\n")

    logger.info(f"Management XML written: {output_path} ({ROTATION}, {sy}-{ey})")
    return str(output_path)


def validate_outputs(output_path):
    content = Path(output_path).read_text()
    if "<ldndcevent>" not in content:
        logger.error("mana.xml missing <ldndcevent> root element")
        sys.exit(3)
    if '<event id="0">' not in content:
        logger.error("mana.xml missing <event id=\"0\"> wrapper")
        sys.exit(3)
    logger.info("Output validation passed.")


if __name__ == "__main__":
    if len(sys.argv) >= 5:
        PROJECT_DIR = sys.argv[1]
        ROTATION = sys.argv[2]
        START_YEAR = sys.argv[3]
        END_YEAR = sys.argv[4]
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try:
        output_path = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        sys.exit(2)
    validate_outputs(output_path)
    print(json.dumps({"status": "success", "mana_xml": output_path}))
    sys.exit(0)
