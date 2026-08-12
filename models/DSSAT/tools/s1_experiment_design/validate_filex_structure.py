#!/usr/bin/env python3
"""
validate_filex_structure.py - Validates the structure of a DSSAT FileX experiment file.

The FileX is the central experiment description file in DSSAT. It defines treatments,
cultivar selections, field conditions, management practices, and simulation controls.

FileX Structure Reference:
    *EXP.DETAILS: header line
    *GENERAL: @PEOPLE, @ADDRESS, @SITE
    *TREATMENTS: treatment table with factor level references
    *CULTIVARS: cultivar code mapping
    *FIELDS: field/location info including WSTA, ID_SOIL
    *INITIAL CONDITIONS: soil water/N initial state
    *PLANTING DETAILS: planting date, density, method
    *IRRIGATION AND WATER MANAGEMENT: irrigation schedule
    *FERTILIZERS: fertilizer applications
    *SIMULATION CONTROLS: model options and output settings

Cross-reference checks:
    - WSTA code -> .WTH file exists
    - ID_SOIL -> profile in .SOL file
    - INGENO -> cultivar in .CUL file
    - Treatment factor levels reference valid section entries

Exit codes:
    0 = success (validation complete, may have warnings)
    1 = input error (file not found, not readable)
    2 = processing error (unparseable format)
    3 = output error (validation failed with errors)
"""

import sys
import os
import logging
import json
import re
from collections import OrderedDict

# ---------------------------------------------------------------------------
# INPUT VARIABLES (agent sets these before invocation)
# ---------------------------------------------------------------------------
FILEX_PATH = ""             # Path to the FileX experiment file (required)
WEATHER_DIR = ""            # Directory containing .WTH files (optional, for cross-ref)
SOIL_FILE = ""              # Path to .SOL file (optional, for cross-ref)
GENOTYPE_DIR = ""           # Directory containing .CUL files (optional, for cross-ref)
STRICT_MODE = False         # If True, treat warnings as errors
OUTPUT_JSON = True          # If True, print JSON report to stdout

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s | %(message)s"
)
logger = logging.getLogger("validate_filex_structure")

# ---------------------------------------------------------------------------
# DSSAT FileX Section Definitions
# ---------------------------------------------------------------------------
REQUIRED_SECTIONS = [
    "*TREATMENTS",
    "*CULTIVARS",
    "*FIELDS",
    "*PLANTING DETAILS",
    "*SIMULATION CONTROLS",
]

OPTIONAL_SECTIONS = [
    "*GENERAL",
    "*INITIAL CONDITIONS",
    "*IRRIGATION AND WATER MANAGEMENT",
    "*FERTILIZERS (INORGANIC)",
    "*FERTILIZERS",
    "*RESIDUES AND ORGANIC FERTILIZER",
    "*CHEMICAL APPLICATIONS",
    "*TILLAGE AND ROTATIONS",
    "*TILLAGE",
    "*ENVIRONMENT MODIFICATIONS",
    "*HARVEST DETAILS",
    "*AUTOMATIC MANAGEMENT",
]

# Treatment table factor columns and corresponding sections
# Format: treatment_col -> (section_name, id_col_in_section)
TREATMENT_FACTOR_MAP = {
    "CU": ("*CULTIVARS", "C"),
    "FL": ("*FIELDS", "L"),
    "SA": ("*INITIAL CONDITIONS", "C"),     # SA=0 means "not used"
    "IC": ("*INITIAL CONDITIONS", "C"),
    "MP": ("*PLANTING DETAILS", "P"),
    "MI": ("*IRRIGATION AND WATER MANAGEMENT", "I"),
    "MF": ("*FERTILIZERS", "F"),
    "MR": ("*RESIDUES AND ORGANIC FERTILIZER", "R"),
    "MC": ("*CHEMICAL APPLICATIONS", "C"),
    "MT": ("*TILLAGE", "T"),
    "ME": ("*ENVIRONMENT MODIFICATIONS", "E"),
    "MH": ("*HARVEST DETAILS", "H"),
    "SM": ("*SIMULATION CONTROLS", "N"),
}


def find_sections(lines):
    """Find all section headers and their line indices in the FileX.

    Args:
        lines: List of file lines.

    Returns:
        dict mapping section name (e.g., '*TREATMENTS') to line index.
    """
    sections = OrderedDict()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("*"):
            # Normalize section name
            sections[stripped] = i
    return sections


def parse_treatment_table(lines, trt_line_idx):
    """Parse the treatment table from the FileX.

    The treatment table starts with @N R O C TNAME... followed by data lines.

    Args:
        lines: All file lines.
        trt_line_idx: Line index of the *TREATMENTS section header.

    Returns:
        tuple of (treatments_list, header_columns, header_line_idx)
        where treatments_list is a list of dicts.
    """
    treatments = []
    header_cols = []
    header_line_idx = None

    # Find the @ header line after *TREATMENTS
    for i in range(trt_line_idx + 1, len(lines)):
        stripped = lines[i].strip()
        if stripped.startswith("*"):
            break  # Next section
        if stripped.startswith("@"):
            header_cols = stripped.lstrip("@").split()
            header_line_idx = i
            continue
        if not stripped or stripped.startswith("!"):
            continue
        if header_cols:
            # Parse treatment data line
            parts = stripped.split()
            trt = {}
            for j, col in enumerate(header_cols):
                if j < len(parts):
                    trt[col] = parts[j]
                else:
                    trt[col] = None
            treatments.append(trt)

    return treatments, header_cols, header_line_idx


def parse_section_entries(lines, section_line_idx, id_column):
    """Parse entries from a FileX section, extracting the ID column values.

    Args:
        lines: All file lines.
        section_line_idx: Line index of the section header.
        id_column: Name of the ID column to extract (e.g., 'C', 'L', 'P').

    Returns:
        set of ID values found in the section.
    """
    ids = set()
    header_cols = []
    id_col_idx = None

    for i in range(section_line_idx + 1, len(lines)):
        stripped = lines[i].strip()
        if stripped.startswith("*"):
            break  # Next section
        if stripped.startswith("@"):
            header_cols = stripped.lstrip("@").split()
            # Find ID column index
            id_col_idx = None
            for j, col in enumerate(header_cols):
                if col == id_column:
                    id_col_idx = j
                    break
            continue
        if not stripped or stripped.startswith("!"):
            continue
        if id_col_idx is not None and header_cols:
            parts = stripped.split()
            if id_col_idx < len(parts):
                ids.add(parts[id_col_idx])

    return ids


def parse_cultivars_section(lines, section_line_idx):
    """Parse the *CULTIVARS section to extract INGENO codes.

    Args:
        lines: All file lines.
        section_line_idx: Line index of *CULTIVARS header.

    Returns:
        dict mapping cultivar level (C value) to INGENO code.
    """
    cultivars = {}
    header_cols = []

    for i in range(section_line_idx + 1, len(lines)):
        stripped = lines[i].strip()
        if stripped.startswith("*"):
            break
        if stripped.startswith("@"):
            header_cols = stripped.lstrip("@").split()
            continue
        if not stripped or stripped.startswith("!"):
            continue
        if header_cols:
            parts = stripped.split()
            rec = {}
            for j, col in enumerate(header_cols):
                if j < len(parts):
                    rec[col] = parts[j]

            c_val = rec.get("C")
            ingeno = rec.get("INGENO")
            cr = rec.get("CR")
            if c_val and ingeno:
                cultivars[c_val] = {"INGENO": ingeno, "CR": cr}

    return cultivars


def parse_fields_section(lines, section_line_idx):
    """Parse the *FIELDS section to extract WSTA and ID_SOIL codes.

    Args:
        lines: All file lines.
        section_line_idx: Line index of *FIELDS header.

    Returns:
        dict mapping field level (L value) to {WSTA, ID_SOIL, ...}.
    """
    fields = {}
    header_cols = []
    parsing_first_table = True  # Fields has two @ header lines

    for i in range(section_line_idx + 1, len(lines)):
        stripped = lines[i].strip()
        if stripped.startswith("*"):
            break
        if stripped.startswith("@"):
            header_cols = stripped.lstrip("@").split()
            # Detect which sub-table we're in
            if "WSTA" in header_cols or "ID_SOIL" in header_cols:
                parsing_first_table = True
            else:
                parsing_first_table = False
            continue
        if not stripped or stripped.startswith("!"):
            continue
        if header_cols and parsing_first_table:
            parts = stripped.split()
            rec = {}
            for j, col in enumerate(header_cols):
                if j < len(parts):
                    rec[col] = parts[j]

            l_val = rec.get("L")
            if l_val:
                # Merge with existing entry if any
                if l_val in fields:
                    fields[l_val].update(rec)
                else:
                    fields[l_val] = rec

    return fields


def check_weather_file(wsta_code, weather_dir):
    """Check if a weather station code has a corresponding .WTH file.

    DSSAT constructs weather file names as WSTA + YYYY.WTH or just WSTA*.WTH.
    The WSTA code in the FileX is typically 4 characters (station) or
    4 chars station + 4 chars year.

    Args:
        wsta_code: Weather station code from FileX (e.g., 'UFGA' or 'UFGA8201').
        weather_dir: Directory to search for .WTH files.

    Returns:
        tuple of (found_bool, matching_files_list).
    """
    if not weather_dir or not os.path.isdir(weather_dir):
        return None, []

    wsta_clean = wsta_code.strip()
    matching = []

    for fname in os.listdir(weather_dir):
        if fname.upper().endswith(".WTH"):
            # Match by station code prefix
            basename = os.path.splitext(fname)[0]
            if basename.upper().startswith(wsta_clean.upper()):
                matching.append(os.path.join(weather_dir, fname))
            elif wsta_clean.upper().startswith(basename.upper()):
                matching.append(os.path.join(weather_dir, fname))

    return len(matching) > 0, matching


def check_soil_profile(soil_id, soil_file):
    """Check if a soil ID exists in a .SOL file.

    Args:
        soil_id: Soil profile ID (e.g., 'IBMZ910014').
        soil_file: Path to .SOL file.

    Returns:
        tuple of (found_bool, line_number_or_none).
    """
    if not soil_file or not os.path.isfile(soil_file):
        return None, None

    try:
        with open(soil_file, "r", encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f, 1):
                stripped = line.strip()
                if stripped.startswith("*") and not stripped.startswith("*SOILS"):
                    # Profile header: *PEDON_ID ...
                    profile_id = stripped[1:].split()[0]
                    if profile_id == soil_id:
                        return True, i
    except IOError:
        return None, None

    return False, None


def check_cultivar(ingeno, crop_code, genotype_dir):
    """Check if a genotype code exists in the appropriate .CUL file.

    Args:
        ingeno: Genotype code (e.g., 'IB0035').
        crop_code: Crop code (e.g., 'MZ' for maize).
        genotype_dir: Directory containing .CUL files.

    Returns:
        tuple of (found_bool, cul_file_path_or_none).
    """
    if not genotype_dir or not os.path.isdir(genotype_dir):
        return None, None

    # Look for .CUL files that might contain this crop
    cul_files = []
    for fname in os.listdir(genotype_dir):
        if fname.upper().endswith(".CUL"):
            cul_files.append(os.path.join(genotype_dir, fname))

    for cul_path in cul_files:
        try:
            with open(cul_path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    stripped = line.strip()
                    if stripped.startswith("!") or stripped.startswith("@") or stripped.startswith("*"):
                        continue
                    if not stripped:
                        continue
                    parts = stripped.split()
                    if parts and parts[0] == ingeno:
                        return True, cul_path
        except IOError:
            continue

    return False, None


def validate():
    """Run all validation checks on the FileX.

    Returns:
        dict with keys: passed, errors, warnings, info, cross_references.
    """
    errors = []
    warnings = []
    info = OrderedDict()
    cross_refs = {}

    # -----------------------------------------------------------------------
    # INPUT VALIDATION
    # -----------------------------------------------------------------------
    if not FILEX_PATH:
        return {"passed": False, "errors": ["FILEX_PATH not specified"],
                "warnings": [], "info": {}, "cross_references": {}}

    if not os.path.isfile(FILEX_PATH):
        return {"passed": False,
                "errors": [f"File not found: {FILEX_PATH}"],
                "warnings": [], "info": {}, "cross_references": {}}

    try:
        with open(FILEX_PATH, "r", encoding="utf-8", errors="replace") as f:
            raw_lines = f.readlines()
    except IOError as e:
        return {"passed": False, "errors": [f"Cannot read file: {e}"],
                "warnings": [], "info": {}, "cross_references": {}}

    if not raw_lines:
        errors.append("File is empty.")
        return {"passed": False, "errors": errors,
                "warnings": warnings, "info": info, "cross_references": cross_refs}

    info["file_path"] = os.path.abspath(FILEX_PATH)
    info["total_lines"] = len(raw_lines)

    # -----------------------------------------------------------------------
    # CHECK FILE HEADER
    # -----------------------------------------------------------------------
    first_content_line = None
    for line in raw_lines:
        stripped = line.strip()
        if stripped:
            first_content_line = stripped
            break

    if first_content_line is None:
        errors.append("File contains only blank lines.")
        return {"passed": False, "errors": errors,
                "warnings": warnings, "info": info, "cross_references": cross_refs}

    if not first_content_line.startswith("*EXP.DETAILS") and not first_content_line.startswith("*EXP"):
        errors.append(
            f"File does not start with *EXP.DETAILS header. "
            f"First line: '{first_content_line[:80]}'"
        )
    else:
        # Extract experiment description
        if ":" in first_content_line:
            info["experiment_description"] = first_content_line.split(":", 1)[1].strip()
        else:
            info["experiment_description"] = first_content_line

    # -----------------------------------------------------------------------
    # FIND ALL SECTIONS
    # -----------------------------------------------------------------------
    sections = find_sections(raw_lines)
    info["sections_found"] = list(sections.keys())

    # Check required sections
    for req_section in REQUIRED_SECTIONS:
        found = False
        for sec_name in sections:
            if req_section.upper() in sec_name.upper():
                found = True
                break
        if not found:
            errors.append(f"Required section missing: {req_section}")

    # Report optional sections
    missing_optional = []
    for opt_section in OPTIONAL_SECTIONS:
        found = False
        for sec_name in sections:
            if opt_section.upper() in sec_name.upper():
                found = True
                break
        if not found:
            missing_optional.append(opt_section)

    if missing_optional:
        info["missing_optional_sections"] = missing_optional
        # Only warn about commonly used optional sections
        important_optional = [
            "*INITIAL CONDITIONS",
            "*IRRIGATION AND WATER MANAGEMENT",
            "*FERTILIZERS",
        ]
        for imp_opt in important_optional:
            if imp_opt in missing_optional:
                found_variant = any(
                    imp_opt.split()[0].upper() in sec_name.upper()
                    for sec_name in sections
                )
                if not found_variant:
                    warnings.append(
                        f"Optional section not found: {imp_opt}. "
                        f"DSSAT will use default values."
                    )

    # -----------------------------------------------------------------------
    # PARSE AND VALIDATE TREATMENT TABLE
    # -----------------------------------------------------------------------
    trt_section_idx = None
    for sec_name, sec_idx in sections.items():
        if "TREATMENTS" in sec_name.upper():
            trt_section_idx = sec_idx
            break

    treatments = []
    if trt_section_idx is not None:
        treatments, trt_headers, trt_header_line = parse_treatment_table(
            raw_lines, trt_section_idx
        )
        info["treatment_count"] = len(treatments)

        if not treatments:
            errors.append("No treatments found in *TREATMENTS section.")

        # Validate treatment factor level references
        for trt in treatments:
            trt_name = trt.get("TNAME................", trt.get("TNAME", "?"))
            trt_num = trt.get("N", "?")

            for factor_col, (section_name, id_col) in TREATMENT_FACTOR_MAP.items():
                factor_val = trt.get(factor_col)
                if factor_val is None:
                    continue

                try:
                    factor_int = int(factor_val)
                except ValueError:
                    continue

                # 0 means "not used"
                if factor_int == 0:
                    continue

                # Check if the referenced section exists
                section_found = False
                section_idx = None
                for sec_name, sec_idx in sections.items():
                    # Match section name flexibly
                    if section_name.replace("*", "").upper().split()[0] in sec_name.upper():
                        section_found = True
                        section_idx = sec_idx
                        break

                if not section_found and factor_int > 0:
                    warnings.append(
                        f"Treatment {trt_num} ({factor_col}={factor_int}): "
                        f"references section {section_name} which was not found."
                    )
                elif section_idx is not None:
                    # Check if the referenced ID exists in the section
                    entry_ids = parse_section_entries(raw_lines, section_idx, id_col)
                    if entry_ids and str(factor_int) not in entry_ids:
                        warnings.append(
                            f"Treatment {trt_num} ({factor_col}={factor_int}): "
                            f"level {factor_int} not found in {section_name} "
                            f"(found: {sorted(entry_ids)})."
                        )

    # -----------------------------------------------------------------------
    # PARSE CULTIVARS SECTION
    # -----------------------------------------------------------------------
    cultivars = {}
    for sec_name, sec_idx in sections.items():
        if "CULTIVAR" in sec_name.upper():
            cultivars = parse_cultivars_section(raw_lines, sec_idx)
            break

    info["cultivar_count"] = len(cultivars)

    # -----------------------------------------------------------------------
    # PARSE FIELDS SECTION
    # -----------------------------------------------------------------------
    fields = {}
    for sec_name, sec_idx in sections.items():
        if "FIELDS" in sec_name.upper():
            fields = parse_fields_section(raw_lines, sec_idx)
            break

    info["field_count"] = len(fields)

    # -----------------------------------------------------------------------
    # CROSS-REFERENCE CHECKS
    # -----------------------------------------------------------------------
    # Check WSTA -> .WTH file
    for l_val, field_data in fields.items():
        wsta = field_data.get("WSTA....")
        if wsta is None:
            wsta = field_data.get("WSTA")
        if wsta and wsta != "-99":
            wsta_clean = wsta.rstrip(".")
            if WEATHER_DIR:
                found, matching = check_weather_file(wsta_clean, WEATHER_DIR)
                cross_refs[f"WSTA_{wsta_clean}"] = {
                    "type": "weather",
                    "code": wsta_clean,
                    "found": found,
                    "matching_files": matching,
                }
                if found is False:
                    errors.append(
                        f"Field {l_val}: WSTA code '{wsta_clean}' has no matching "
                        f".WTH file in {WEATHER_DIR}."
                    )
                elif found is True:
                    logger.info(
                        "Field %s: WSTA '%s' matched %d weather file(s).",
                        l_val, wsta_clean, len(matching)
                    )
            else:
                info[f"wsta_code_field_{l_val}"] = wsta_clean

    # Check ID_SOIL -> .SOL profile
    for l_val, field_data in fields.items():
        soil_id = field_data.get("ID_SOIL")
        if soil_id and soil_id != "-99":
            if SOIL_FILE:
                found, line_num = check_soil_profile(soil_id, SOIL_FILE)
                cross_refs[f"SOIL_{soil_id}"] = {
                    "type": "soil",
                    "code": soil_id,
                    "found": found,
                    "line_number": line_num,
                }
                if found is False:
                    errors.append(
                        f"Field {l_val}: ID_SOIL '{soil_id}' not found in {SOIL_FILE}."
                    )
                elif found is True:
                    logger.info(
                        "Field %s: ID_SOIL '%s' found at line %d in %s.",
                        l_val, soil_id, line_num, SOIL_FILE
                    )
            else:
                info[f"soil_id_field_{l_val}"] = soil_id

    # Check INGENO -> .CUL file
    for c_val, cul_data in cultivars.items():
        ingeno = cul_data.get("INGENO")
        cr = cul_data.get("CR")
        if ingeno and ingeno != "-99":
            if GENOTYPE_DIR:
                found, cul_file = check_cultivar(ingeno, cr, GENOTYPE_DIR)
                cross_refs[f"CULTIVAR_{ingeno}"] = {
                    "type": "cultivar",
                    "code": ingeno,
                    "crop": cr,
                    "found": found,
                    "cul_file": cul_file,
                }
                if found is False:
                    errors.append(
                        f"Cultivar {c_val}: INGENO '{ingeno}' not found in any "
                        f".CUL file in {GENOTYPE_DIR}."
                    )
                elif found is True:
                    logger.info(
                        "Cultivar %s: INGENO '%s' found in %s.",
                        c_val, ingeno, cul_file
                    )
            else:
                info[f"ingeno_cultivar_{c_val}"] = ingeno

    # -----------------------------------------------------------------------
    # STRICT MODE
    # -----------------------------------------------------------------------
    if STRICT_MODE:
        errors.extend(warnings)
        warnings = []

    # -----------------------------------------------------------------------
    # BUILD REPORT
    # -----------------------------------------------------------------------
    passed = len(errors) == 0
    report = {
        "passed": passed,
        "errors": errors,
        "warnings": warnings,
        "info": dict(info),
        "cross_references": cross_refs,
    }

    return report


def main():
    """Entry point: validate FileX structure.

    The target may be supplied on the command line
    (``validate_filex_structure.py /path/to/EXP.MZX``) so a batch driver can
    validate many FileX files without rewriting the module. The module global
    FILEX_PATH stays the default when no argument is given, so existing
    set-the-global callers are unaffected.
    """
    global FILEX_PATH
    _pos = [a for a in sys.argv[1:] if not a.startswith("-")]
    if _pos:
        FILEX_PATH = _pos[0]

    # -----------------------------------------------------------------------
    # PRECONDITIONS
    # -----------------------------------------------------------------------
    if not FILEX_PATH:
        logger.error("FILEX_PATH must be set before running.")
        sys.exit(1)

    # -----------------------------------------------------------------------
    # CORE PROCESSING
    # -----------------------------------------------------------------------
    try:
        report = validate()
    except Exception as e:
        logger.error("Unexpected processing error: %s", e, exc_info=True)
        sys.exit(2)

    # -----------------------------------------------------------------------
    # POSTCONDITIONS
    # -----------------------------------------------------------------------
    required_keys = {"passed", "errors", "warnings", "info", "cross_references"}
    if not required_keys.issubset(report.keys()):
        logger.error(
            "Report missing required keys: %s",
            required_keys - report.keys()
        )
        sys.exit(3)

    if not isinstance(report["passed"], bool):
        logger.error("report['passed'] must be bool, got %s", type(report["passed"]))
        sys.exit(3)

    # -----------------------------------------------------------------------
    # OUTPUT
    # -----------------------------------------------------------------------
    if report["passed"]:
        logger.info("VALIDATION PASSED for %s", FILEX_PATH)
    else:
        logger.warning(
            "VALIDATION FAILED for %s (%d errors)",
            FILEX_PATH, len(report["errors"])
        )

    if report["warnings"]:
        logger.info("%d warning(s) generated.", len(report["warnings"]))

    if OUTPUT_JSON:
        print(json.dumps(report, indent=2, default=str))

    if not report["passed"]:
        sys.exit(3)
    sys.exit(0)


if __name__ == "__main__":
    main()
