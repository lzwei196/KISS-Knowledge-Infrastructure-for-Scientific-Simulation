#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
Tool ID:      validate_species_params
Stage:        s7_species_params
Description:  Cross-validate species names between mana.xml and parameters_species.xml.
              CRITICAL: Mismatch causes silent zero-yield (see dt_009).

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""
import sys, os, json, logging, re
from pathlib import Path

SPECIES_XML = ""
MANA_XML = ""

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def validate_inputs():
    errors = []
    if not SPECIES_XML or not Path(SPECIES_XML).exists():
        errors.append(f"species_xml not found: {SPECIES_XML}")
    if not MANA_XML or not Path(MANA_XML).exists():
        errors.append(f"mana_xml not found: {MANA_XML}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")

def process():
    # Extract species from mana.xml sowing events
    mana_content = Path(MANA_XML).read_text()
    mana_species = set(re.findall(r'species="([^"]+)"', mana_content))
    # Extract species from parameters_species.xml
    species_content = Path(SPECIES_XML).read_text()
    # Look for species name attributes or elements
    defined_species = set(re.findall(r'name="([^"]+)"', species_content))
    defined_species.update(re.findall(r'<species[^>]*id="([^"]+)"', species_content))
    missing = mana_species - defined_species
    matched = mana_species & defined_species
    result = {
        "mana_species": list(mana_species),
        "defined_species": list(defined_species),
        "matched": list(matched),
        "missing": list(missing),
        "status": "FAIL" if missing else "PASS",
    }
    if missing:
        logger.error(f"Species in mana.xml but NOT in parameters_species.xml: {missing}")
        logger.error("These crops will be silently skipped -- yield will be zero! (dt_009)")
    else:
        logger.info(f"All {len(matched)} species matched successfully")
    return result

def validate_outputs(result):
    if result["status"] == "FAIL":
        sys.exit(3)
    logger.info("Output validation passed.")

if __name__ == "__main__":
    if len(sys.argv) >= 3:
        SPECIES_XML = sys.argv[1]
        MANA_XML = sys.argv[2]
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs()
    try:
        result = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        sys.exit(2)
    validate_outputs(result)
    print(json.dumps(result))
    sys.exit(0)
