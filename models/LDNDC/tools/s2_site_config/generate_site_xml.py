#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
Tool ID:      generate_site_xml
Stage:        s2_site_config
Description:  Generate LDNDC site.xml from soil data (output of hwsd_to_ldndc_soil.py).
              Uses the proven <site><soil><general>...<layers> format.

Inputs:
  - project_dir: LDNDC project root (directory containing input/)
  - soil_data: JSON — either the full output of hwsd_to_ldndc_soil.py, or a list of
    layer dicts with {depth_cm, clay_pct, sand_pct, bd_gcm3, pH, corg_fraction}
  - use_history: "arable" or "forest" (default: arable)

Outputs:
  - site.xml at {project_dir}/input/site.xml

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import json
import logging
from pathlib import Path

PROJECT_DIR = ""
SOIL_DATA = {}
USE_HISTORY = "arable"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def validate_inputs():
    errors = []
    if not PROJECT_DIR or not Path(PROJECT_DIR).is_dir():
        errors.append(f"PROJECT_DIR not found: {PROJECT_DIR}")
    if not SOIL_DATA:
        errors.append("SOIL_DATA is empty")
    # Validate layer data
    layers = _get_layers()
    if len(layers) < 1:
        errors.append("No soil layers found in SOIL_DATA")
    for i, layer in enumerate(layers):
        bd = layer.get("bd", layer.get("bd_gcm3", 0))
        if bd <= 0 or bd > 2.65:
            errors.append(f"Layer {i} bd={bd} out of range (0, 2.65]")
        corg = layer.get("corg", layer.get("corg_fraction", 0))
        if corg > 0.60:
            errors.append(f"Layer {i} corg={corg} > 0.60 — likely percentage, not fraction")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def _get_layers():
    """Extract layer list from SOIL_DATA (handles both hwsd tool output and simple list)."""
    if isinstance(SOIL_DATA, list):
        return SOIL_DATA
    if isinstance(SOIL_DATA, dict):
        if "layers" in SOIL_DATA:
            return SOIL_DATA["layers"]
        if "soil_data" in SOIL_DATA:
            sd = SOIL_DATA["soil_data"]
            if isinstance(sd, list):
                return sd
            if isinstance(sd, dict) and "layers" in sd:
                return sd["layers"]
    return []


def process():
    """Write site.xml in the proven <site><soil><general>...<layers> format."""
    layers = _get_layers()

    # Get metadata from SOIL_DATA if available (hwsd tool output)
    if isinstance(SOIL_DATA, dict):
        sd = SOIL_DATA.get("soil_data", SOIL_DATA)
        soil_type = sd.get("soil_type", "LOAM")
        corg5 = sd.get("corg5", layers[0].get("corg", 0.01))
        corg30 = sd.get("corg30", corg5 * 0.9)
        mu = sd.get("mu_global", "unknown")
    else:
        soil_type = "LOAM"
        corg5 = layers[0].get("corg", layers[0].get("corg_fraction", 0.01))
        corg30 = corg5 * 0.9
        mu = "unknown"

    humus = "NONE" if USE_HISTORY == "arable" else "MODER"
    litter = "0.0" if USE_HISTORY == "arable" else "50.0"

    output_path = Path(PROJECT_DIR) / "input" / "site.xml"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write("<site>\n")
        f.write("  <description>\n")
        f.write(f"    <dataset>HWSD-MU{mu}</dataset>\n")
        f.write("  </description>\n")
        f.write("  <soil>\n")
        f.write(
            f'    <general usehistory="{USE_HISTORY}" corg5="{corg5:.4f}" '
            f'corg30="{corg30:.4f}" soil="{soil_type}" '
            f'humus="{humus}" litterheight="{litter}" />\n'
        )
        f.write("    <layers>\n")
        for layer in layers:
            # Support both naming conventions
            depth = layer.get("depth_mm", layer.get("depth_cm", 30) * 10)
            bd = layer.get("bd", layer.get("bd_gcm3", 1.3))
            clay = layer.get("clay", layer.get("clay_pct", 20) / 100)
            corg = layer.get("corg", layer.get("corg_fraction", 0.01))
            norg = layer.get("norg", layer.get("norg_fraction", corg / 10))
            ph = layer.get("ph", layer.get("pH", 7.0))
            scel = layer.get("scel", layer.get("stone_fraction", 0.1))
            sks = layer.get("sks", layer.get("sks_cmmin", 0.01))
            wc_fc = layer.get("wc_fc", 300)
            wc_wp = layer.get("wc_wp", 150)

            # Apply corg floor (LDNDC needs > 0)
            if corg < 0.0005:
                corg = 0.0005

            f.write(
                f'      <layer depth="{depth:.1f}" bd="{bd:.2f}" '
                f'clay="{clay:.2f}" corg="{corg:.4f}" '
                f'ph="{ph:.1f}" scel="{scel:.2f}" '
                f'sks="{sks:.4f}" wc_fc="{wc_fc:.1f}" wc_wp="{wc_wp:.1f}" />\n'
            )
        f.write("    </layers>\n")
        f.write("  </soil>\n")
        f.write("</site>\n")

    logger.info(f"Generated site.xml with {len(layers)} layers at {output_path}")
    return str(output_path)


def validate_outputs(output_path):
    if not Path(output_path).exists():
        logger.error(f"Output not created: {output_path}")
        sys.exit(3)
    content = Path(output_path).read_text()
    if "<soil>" not in content:
        logger.error("site.xml missing <soil> element")
        sys.exit(3)
    if content.count("<layer") < 1:
        logger.error("site.xml has no soil layers")
        sys.exit(3)
    logger.info("Output validation passed.")


if __name__ == "__main__":
    if len(sys.argv) >= 3:
        PROJECT_DIR = sys.argv[1]
        SOIL_DATA = json.loads(sys.argv[2])
    if len(sys.argv) >= 4:
        USE_HISTORY = sys.argv[3]
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try:
        output_path = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        sys.exit(2)
    validate_outputs(output_path)
    print(json.dumps({"status": "success", "site_xml": output_path}))
    sys.exit(0)
