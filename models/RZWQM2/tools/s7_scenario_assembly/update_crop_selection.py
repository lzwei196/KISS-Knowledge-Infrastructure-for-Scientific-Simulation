#!/usr/bin/env python3
"""
update_crop_selection.py
========================
Update the crop cultivar selection in a RZWQM2 scenario.

CRITICAL: The crop selection that RZWQM2 actually reads lives in RZWQM.DAT
(not RZCropSel.rzq — that's a GUI artifact). The crop list is inside
rzwqm.dat near line ~494, with format:

    4                                    <- number of crop entries
    7000  maize IB1068 DEKALB 521        <- code 7000 = maize
    7001  soybean 990002 M GROUP 2       <- code 7001 = soybean
    7002  wheat 990001 SPRING-HIGH LAT   <- code 7002 = wheat
    9700  OT-Oat  (default)              <- code 9700 = generic

Crop codes are HARDWIRED in RZWQM2:
    7000 = maize (uses MZDSSAT.RZX)
    7001 = soybean (uses SBDSSAT.RZX)
    7002 = wheat (uses WHDSSAT.RZX)

This tool updates the cultivar ID and description for a given crop code
in BOTH rzwqm.dat and RZCropSel.rzq.

Inputs:
    scenario_dir    - Scenario directory
    crop_code       - Crop code: "7000" (maize), "7001" (soybean), "7002" (wheat)
    crop_name       - Crop name (e.g., "wheat")
    cultivar_id     - DSSAT cultivar ID (e.g., "990001")
    cultivar_desc   - Cultivar description (e.g., "SPRING-HIGH LAT")

Exit codes:
    0 - Success
    1 - Input validation error
    2 - Processing error
"""
import sys
import os
import json

SCENARIO_DIR = ""
CROP_CODE = ""
CROP_NAME = ""
CULTIVAR_ID = ""
CULTIVAR_DESC = ""

# Add lib to path
DATA_PREP_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'lib')
sys.path.insert(0, os.path.abspath(DATA_PREP_DIR))


def _update_file(filepath, crop_code, new_line):
    """Find and replace the line starting with crop_code in a file. Returns old line or None."""
    if not os.path.isfile(filepath):
        return None, f"File not found: {filepath}"

    with open(filepath, 'r') as f:
        lines = [line.rstrip('\n') for line in f]

    old_line = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(crop_code + ' ') or stripped.startswith(crop_code + '\t'):
            old_line = stripped
            lines[i] = new_line
            break

    if old_line is None:
        return None, f"Crop code {crop_code} not found in {filepath}"

    with open(filepath, 'w') as f:
        for line in lines:
            f.write(line + '\n')

    return old_line, None


# Crop code → plant reference number mapping (1-indexed in rzwqm.dat)
CROP_CODE_TO_PLANT_REF = {
    '7000': '1',   # maize
    '7001': '2',   # soybean
    '7002': '3',   # wheat
}


def _update_planting_references(dat_path, target_plant_ref):
    """
    Update ALL planting schedule entries to use the target plant reference.

    In rzwqm.dat, the planting section looks like:
        6                          <- number of plantings
        2  10   6  2012  50.0 ...  <- plant_ref  day  month  year ...
        ...

    The first number on each planting line is the plant reference (1=maize,
    2=soybean, 3=wheat). If the template used a different crop, all planting
    lines will reference the wrong crop. This function rewrites them.

    Returns (count_updated, error_msg).
    """
    import re

    with open(dat_path, 'r', encoding='ISO-8859-1') as f:
        content = f.read()

    # Find planting data lines: they follow the "===...===" separator line
    # that comes after the planting control comments, and look like:
    #   <plant_ref>  <day>  <month>  <year>  <row_spacing> ...
    # Pattern: a single digit, then spaces, then day (1-31), month (1-12), year (19xx/20xx)
    pattern = re.compile(
        r'^(\d)\s+(\d{1,2}\s+\d{1,2}\s+(?:19|20)\d{2}\s+.*)',
        re.MULTILINE
    )

    count = 0

    def _replace_ref(m):
        nonlocal count
        old_ref = m.group(1)
        rest = m.group(2)
        count += 1
        return f"{target_plant_ref}  {rest}"

    content_new = pattern.sub(_replace_ref, content)

    if count > 0:
        with open(dat_path, 'w', encoding='ISO-8859-1') as f:
            f.write(content_new)

    return count, None


def main():
    scenario_dir = sys.argv[1] if len(sys.argv) > 1 else SCENARIO_DIR
    crop_code = sys.argv[2] if len(sys.argv) > 2 else CROP_CODE
    crop_name = sys.argv[3] if len(sys.argv) > 3 else CROP_NAME
    cultivar_id = sys.argv[4] if len(sys.argv) > 4 else CULTIVAR_ID
    cultivar_desc = sys.argv[5] if len(sys.argv) > 5 else CULTIVAR_DESC

    if not scenario_dir or not crop_code or not crop_name:
        print(json.dumps({"status": "INPUT_ERROR",
                          "message": "SCENARIO_DIR, CROP_CODE, and CROP_NAME are required."}))
        sys.exit(1)

    if crop_code not in ('7000', '7001', '7002', '9700'):
        print(json.dumps({"status": "INPUT_ERROR",
                          "message": f"Invalid CROP_CODE '{crop_code}'. Must be 7000 (maize), 7001 (soybean), 7002 (wheat), or 9700 (other)."}))
        sys.exit(1)

    # CRITICAL: cultivar_id MUST be present — without it, RZWQM2 cannot find
    # the cultivar in the .CUL file and falls through to a wrong default.
    DEFAULT_CULTIVARS = {
        '7000': ('IB1068', 'DEKALB 521'),
        '7001': ('990002', 'M GROUP   2'),
        '7002': ('990003', 'WINTER-US'),
        '9700': ('990001', '(default)'),
    }
    if not cultivar_id:
        cultivar_id, cultivar_desc = DEFAULT_CULTIVARS.get(crop_code, ('IB1068', 'UNKNOWN'))
        print(json.dumps({"warning": f"No cultivar_id provided — defaulting to {cultivar_id} ({cultivar_desc})"}),
              file=sys.stderr)

    new_line = f"{crop_code}  {crop_name} {cultivar_id} {cultivar_desc}".rstrip()

    try:
        updated = []

        # 1. Update rzwqm.dat crop definition (THE REAL SOURCE the model reads)
        dat_path = None
        for name in ('rzwqm.dat', 'RZWQM.dat'):
            p = os.path.join(scenario_dir, name)
            if os.path.isfile(p):
                dat_path = p
                break
        if dat_path:
            old, err = _update_file(dat_path, crop_code, new_line)
            if err:
                print(json.dumps({"status": "PROCESSING_ERROR", "message": f"rzwqm.dat: {err}"}))
                sys.exit(2)
            updated.append(f"rzwqm.dat: '{old}' -> '{new_line}'")

        # 2. Update ALL planting schedule references to point to this crop
        #    This is CRITICAL: if the template had soybean (ref=2) and we switch
        #    to maize (ref=1), every planting line must be updated or the model
        #    will try to plant the wrong crop and crash looking for .CUL files.
        target_ref = CROP_CODE_TO_PLANT_REF.get(crop_code)
        if dat_path and target_ref:
            n_updated, err = _update_planting_references(dat_path, target_ref)
            if n_updated > 0:
                updated.append(f"planting_schedule: {n_updated} entries → plant_ref={target_ref}")
            elif n_updated == 0:
                updated.append("planting_schedule: no entries found (may need manual check)")

        # 3. Update RZCropSel.rzq (GUI file, keep in sync)
        rzq_path = os.path.join(scenario_dir, 'RZCropSel.rzq')
        if os.path.isfile(rzq_path):
            old_rzq, err = _update_file(rzq_path, crop_code, new_line)
            if old_rzq:
                updated.append(f"RZCropSel.rzq: updated")

        print(json.dumps({
            "status": "SUCCESS",
            "message": f"Crop {crop_code} set to: {new_line}",
            "result": {
                "crop_code": crop_code,
                "new_entry": new_line,
                "files_updated": updated
            }
        }))
        sys.exit(0)

    except Exception as e:
        print(json.dumps({"status": "PROCESSING_ERROR", "message": str(e)}))
        sys.exit(2)


if __name__ == '__main__':
    main()
