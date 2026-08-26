#!/usr/bin/env python3
"""
update_cultivar.py
==================
Update the DSSAT cultivar parameters in a RZWQM2 scenario.

RZWQM2 uses an older DSSAT (MZCER040/WHCER040/SBGRO040). The cultivar is
selected by the 6-char VAR# in RZCropSel.rzq, which is looked up in the
.CUL file inside the scenario's DSSAT/ directory.

CRITICAL: RZWQM2 matches cultivar by the VAR# in RZCropSel.rzq (NOT
rzwqm.dat). The safest way to change cultivar parameters is to OVERWRITE
the existing VAR# line in the .CUL file with new parameters, keeping the
same VAR# ID. This avoids any ID-matching issues.

This tool can:
1. List available cultivars from the DSSAT China library
2. Auto-select cultivar by latitude (using the latitude-based guide)
3. Write the selected cultivar's params into the scenario's .CUL file

Data source: KISSPATH_HOME/DSSAT/Data/Genotype/China/ (DSSAT v4.8 format)
Conversion: MZCER048 → MZCER040 (drop EXPNO field, add Height/Biomass defaults)

Inputs:
    scenario_dir  - Scenario directory
    crop          - Crop name: maize, wheat, soybean, rice
    lat           - Latitude for auto-selection (optional if cultivar_id given)
    cultivar_id   - Specific cultivar ID from China library (optional)

Exit codes: 0=success, 1=input error, 2=processing error
"""
import sys
import os
import json
import re

SCENARIO_DIR = ""
CROP = ""
LAT = ""
CULTIVAR_ID = ""  # e.g., CN0001. If empty, auto-select by latitude.

# DSSAT China cultivar library
CHINA_CUL_DIR = "KISSPATH_HOME/DSSAT/Data/Genotype/China"

# Crop → CUL file mapping
CROP_CUL_MAP = {
    'maize': ('MZCER048_China.CUL', 'MZCER040.CUL'),
    'corn':  ('MZCER048_China.CUL', 'MZCER040.CUL'),
    'wheat': ('WHCER048_China.CUL', 'WHCER040.CUL'),
    'rice':  ('RICER048_China.CUL', 'RICER040.CUL'),  # if exists
    'soybean': ('SBGRO048_China.CUL', 'SBGRO040.CUL'),
}

# Latitude-based cultivar selection (from DSSAT China README)
CULTIVAR_BY_LAT = {
    'maize': [
        (40.0, 999, 'CN0018', 'NEC Spring Medium'),
        (31.0, 40.0, 'CN0001', 'Zhengdan 958'),       # HHH includes Huai River (31-40N)
        (0.0, 31.0, 'CN0021', 'SC Summer Generic'),    # South China < 31N
    ],
    'wheat': [
        (33.0, 999, 'CN0112', 'NCP Early Maturing'),
        (28.0, 33.0, 'CN0121', 'YZR Winter Wheat'),
    ],
    'soybean': [
        (40.0, 999, 'CN0301', 'NEC Soybean Early'),
        (33.0, 40.0, 'CN0311', 'HHH Soybean'),
        (0.0, 33.0, 'CN0321', 'YZR Soybean'),
    ],
}

# Crop-specific 040 format definitions
# Each crop: (param_count, has_height_biomass, height_default, biomass_default, eco_map)
# eco_map: maps 048 ECO# → 040 ECO# (because some ECO# names differ between versions)
CROP_FORMAT_040 = {
    'maize': {
        'param_count': 6,          # P1 P2 P5 G2 G3 PHINT
        'extra_cols': ('14037', '3173.'),  # Height, Biomass (maize-specific)
        'eco_map': {},             # IB0001 stays IB0001
        'fmt': lambda p: (f"{p[0]:5.1f} {p[1]:5.3f} {p[2]:5.1f} "
                          f"{p[3]:5.1f} {p[4]:5.3f} {p[5]:5.2f}"),
    },
    'wheat': {
        'param_count': 7,          # P1V P1D P5 G1 G2 G3 PHINT
        'extra_cols': None,        # No Height/Biomass in WHCER040
        'eco_map': {'DFAULT': 'DSWH02'},  # DFAULT → winter wheat ecotype
        'fmt': lambda p: (f"{p[0]:5.0f} {p[1]:5.2f} {p[2]:5.1f} "
                          f"{p[3]:5.2f} {p[4]:5.2f} {p[5]:5.3f} {p[6]:5.2f}"),
    },
    'soybean': {
        # SBGRO048 has 18 params; SBGRO040 uses first 15 (last 3: THRSH,SDPRO,SDLIP are in ECO file)
        'param_count': 15,         # CSDL PPSEN EM-FL FL-SH FL-SD SD-PM FL-LF LFMAX SLAVR SIZLF XFRT WTPSD SFDUR SDPDV PODUR
        'extra_cols': None,
        'eco_map': {},             # SB0001/SB0201/etc. already exist in SBGRO040.ECO
        'fmt': lambda p: (f"{p[0]:5.2f} {p[1]:5.3f} {p[2]:5.2f} {p[3]:5.3f} "
                          f"{p[4]:5.2f} {p[5]:5.2f} {p[6]:5.2f} {p[7]:5.3f} "
                          f"{p[8]:5.1f} {p[9]:5.1f} {p[10]:5.3f} {p[11]:5.3f} "
                          f"{p[12]:5.2f} {p[13]:5.3f} {p[14]:5.2f}"),
    },
}


def _select_by_lat(crop, lat):
    """Select cultivar ID by latitude."""
    entries = CULTIVAR_BY_LAT.get(crop, CULTIVAR_BY_LAT.get('maize', []))
    for lat_min, lat_max, cul_id, cul_name in entries:
        if lat_min <= lat < lat_max:
            return cul_id, cul_name
    # Default: first entry
    if entries:
        return entries[0][2], entries[0][3]
    return None, None


def _read_china_cul(crop):
    """Read all cultivar entries from the China CUL file."""
    src_file, _ = CROP_CUL_MAP.get(crop, CROP_CUL_MAP['maize'])
    src_path = os.path.join(CHINA_CUL_DIR, src_file)
    if not os.path.isfile(src_path):
        return {}, f"China CUL file not found: {src_path}"

    cultivars = {}
    with open(src_path) as f:
        for line in f:
            line = line.rstrip()
            if line and not line.startswith('!') and not line.startswith('*') and not line.startswith('@'):
                # Parse: VAR#(6) VRNAME(16) EXPNO(6) ECO#(6) params...
                var_id = line[:6].strip()
                if var_id and var_id[0].isalpha():
                    # DSSAT 048 format: skip EXPNO, find ECO# (6-char code)
                    # Matches IB0001, SB0201, DSWH02, DFAULT, etc.
                    eco_match = re.search(r'([A-Z]{2}\d{4}|DFAULT)', line[20:])
                    if eco_match:
                        eco_start = line.index(eco_match.group(), 20)
                        eco = eco_match.group()
                        params_str = line[eco_start + len(eco):].strip()
                        name = line[7:23].strip()
                        cultivars[var_id] = {
                            'id': var_id,
                            'name': name,
                            'eco': eco,
                            'params': params_str,
                            'raw_line': line,
                        }
    return cultivars, None


def _convert_to_040(cultivar, crop, target_var_id):
    """Convert a *CER048 cultivar entry to *CER040 format.

    Crop-aware: handles maize (6 params + Height/Biomass), wheat (7 params),
    soybean (6 params) with correct column widths and ECO# mapping.

    CRITICAL: Fortran fixed-width format — ECO# must start at column 25
    (1-indexed) = position 24 (0-indexed). VRNAME occupies positions 7-23
    (17 chars: 16 name chars + 1 separator space).
    """
    crop_key = 'corn' if crop == 'corn' else crop
    if crop_key == 'corn':
        crop_key = 'maize'
    fmt_def = CROP_FORMAT_040.get(crop_key, CROP_FORMAT_040['maize'])

    # Parse params from source cultivar
    src = cultivar['params'].split()
    n = fmt_def['param_count']
    params = [float(x) for x in src[:n]]

    # Map ECO# if needed (e.g., DFAULT → DSWH02 for wheat)
    eco = cultivar['eco']
    eco = fmt_def['eco_map'].get(eco, eco)

    # Build fixed-width line
    name_padded = cultivar['name'][:16].ljust(17)  # 16 chars + 1 separator
    params_str = fmt_def['fmt'](params)

    line = f"{target_var_id} {name_padded}{eco} {params_str}"

    # Append extra columns if crop has them (e.g., maize Height/Biomass)
    if fmt_def['extra_cols']:
        height, biomass = fmt_def['extra_cols']
        line += f" {height} {biomass}"

    return line


def _find_closest_cultivar(cultivar_id, cultivars):
    """Snap an unknown cultivar ID to the numerically closest existing one.

    Example: CN0005 not found → compares distance to all CNxxxx IDs →
    returns CN0004 (dist=1) rather than CN0011 (dist=6).
    Falls back to the first entry in the dict if prefix doesn't match.
    """
    m = re.search(r'(\d+)$', cultivar_id)
    if not m:
        return next(iter(cultivars.values()))

    req_num = int(m.group())
    prefix = cultivar_id[:m.start()]

    best_id = None
    best_dist = float('inf')
    for cid in cultivars:
        m2 = re.search(r'(\d+)$', cid)
        if m2 and cid[:m2.start()] == prefix:
            dist = abs(int(m2.group()) - req_num)
            if dist < best_dist:
                best_dist = dist
                best_id = cid

    if best_id:
        return cultivars[best_id]
    # Prefix mismatch — return first entry as last resort
    return next(iter(cultivars.values()))


def _find_active_var_id(scenario_dir, crop):
    """Find the VAR# that RZCropSel.rzq uses for this crop."""
    crop_codes = {'maize': '7000', 'corn': '7000', 'wheat': '7002', 'soybean': '7001'}
    code = crop_codes.get(crop, '7000')

    for fname in ('RZCropSel.rzq',):
        fpath = os.path.join(scenario_dir, fname)
        if os.path.isfile(fpath):
            with open(fpath) as f:
                for line in f:
                    if line.strip().startswith(code):
                        parts = line.split()
                        if len(parts) >= 3:
                            return parts[2]  # cultivar ID
    return 'IB1068'  # fallback


def main():
    scenario_dir = sys.argv[1] if len(sys.argv) > 1 else SCENARIO_DIR
    crop = (sys.argv[2] if len(sys.argv) > 2 else CROP).strip().lower()
    lat_str = sys.argv[3] if len(sys.argv) > 3 else LAT
    cultivar_id = sys.argv[4] if len(sys.argv) > 4 else CULTIVAR_ID

    if not scenario_dir or not crop:
        print(json.dumps({"status": "INPUT_ERROR",
                          "message": "Usage: update_cultivar.py <scenario_dir> <crop> [lat] [cultivar_id]"}))
        sys.exit(1)

    # Parse latitude
    lat = float(lat_str) if lat_str else None

    # Auto-select or use provided cultivar_id
    if not cultivar_id and lat is not None:
        cultivar_id, cul_name = _select_by_lat(crop, lat)
        if not cultivar_id:
            print(json.dumps({"status": "PROCESSING_ERROR",
                              "message": f"No cultivar found for crop={crop}, lat={lat}"}))
            sys.exit(2)

    if not cultivar_id:
        print(json.dumps({"status": "INPUT_ERROR",
                          "message": "Either LAT (for auto-select) or CULTIVAR_ID is required."}))
        sys.exit(1)

    # Read China cultivar database
    cultivars, err = _read_china_cul(crop)
    if err:
        print(json.dumps({"status": "PROCESSING_ERROR", "message": err}))
        sys.exit(2)

    if cultivar_id not in cultivars:
        closest = _find_closest_cultivar(cultivar_id, cultivars)
        print(
            f"[WARNING] Cultivar {cultivar_id} not in database "
            f"(ID gap) — snapping to closest: {closest['id']} ({closest['name']})",
            file=sys.stderr,
        )
        cultivar_id = closest['id']

    selected = cultivars[cultivar_id]

    # Find the active VAR# the model uses (from RZCropSel.rzq)
    target_var_id = _find_active_var_id(scenario_dir, crop)

    # Convert to MZCER040 format using the active VAR# as ID
    new_line = _convert_to_040(selected, crop, target_var_id)

    # Find and overwrite the target VAR# line in the .CUL file.
    # CRITICAL: RZWQM2 may read from EITHER the scenario root CUL file OR
    # the DSSAT/ subdirectory CUL file depending on the binary's search order.
    # The RZX file specifies "DSSAT/" as the genotype path, but empirically
    # the binary also reads from the scenario root. To be safe, update BOTH.
    _, cul_filename = CROP_CUL_MAP.get(crop, CROP_CUL_MAP['maize'])

    cul_paths = []
    # Primary: DSSAT/ subdirectory (referenced in RZX)
    dssat_cul = os.path.join(scenario_dir, 'DSSAT', cul_filename)
    if os.path.isfile(dssat_cul):
        cul_paths.append(dssat_cul)
    # Secondary: scenario root (where RZWQM2 binary may also look)
    root_cul = os.path.join(scenario_dir, cul_filename)
    if os.path.isfile(root_cul):
        cul_paths.append(root_cul)

    if not cul_paths:
        print(json.dumps({"status": "PROCESSING_ERROR",
                          "message": f"CUL file not found in DSSAT/ or scenario root: {cul_filename}"}))
        sys.exit(2)

    updated_files = []
    for cul_path in cul_paths:
        with open(cul_path) as f:
            lines = f.readlines()

        replaced = False
        old_line = "(not found)"
        for i, line in enumerate(lines):
            if line.startswith(target_var_id):
                old_line = line.rstrip()
                lines[i] = new_line + '\n'
                replaced = True
                break

        if not replaced:
            # Append if target VAR# not found
            lines.append(new_line + '\n')
            old_line = "(appended — not found)"

        with open(cul_path, 'w') as f:
            f.writelines(lines)
        updated_files.append(cul_path)

    print(json.dumps({
        "status": "SUCCESS",
        "message": (
            f"Cultivar updated: {target_var_id} now has {cultivar_id} ({selected['name']}) params. "
            f"P1={selected['params'].split()[0]}, P5={selected['params'].split()[2]}"
        ),
        "result": {
            "target_var_id": target_var_id,
            "source_cultivar": cultivar_id,
            "source_name": selected['name'],
            "cul_files_updated": updated_files,
            "old_line": old_line,
            "new_line": new_line,
        }
    }))
    sys.exit(0)


if __name__ == '__main__':
    main()
