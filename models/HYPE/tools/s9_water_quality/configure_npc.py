#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
Tool ID:      configure_npc
Stage:        s9_water_quality
Description:  Enable nitrogen and phosphorus simulation in HYPE by updating
              info.txt (substance declaration, NPC output variables, model options)
              and par.txt (NPC parameters with literature defaults).

Usage:
    python configure_npc.py \
        --info_txt <path> --par_txt <path> \
        --substances "N P" \
        --region huai_river|midwest_us|europe_temperate \
        [--geoclass <path>]

Substances:
    N   - Inorganic N (IN) + Organic N (ON)
    P   - Soluble P (SP) + Particulate P (PP)
    C   - Organic Carbon (OC)
    "N P" - Both nitrogen and phosphorus (recommended)

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import argparse
import sys
import os
import json
import logging
import re
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# NPC parameter defaults by region (from WWH calibration + Chinese literature)
NPC_DEFAULTS = {
    "huai_river": {
        # General parameters
        "fastn0":    50.0,     # Initial fast N pool (kg/km2)
        "fastp0":    5.0,      # Initial fast P pool (kg/km2)
        "denitwr":   0.003,    # Main river denitrification (kg/m2/day)
        "denitwrl":  0.003,    # Local river denitrification
        "denitwl":   0.001,    # Lake denitrification
        "sedon":     0.002,    # ON sedimentation (kg/m2/day)
        "sedpp":     0.002,    # PP sedimentation
        "sedss":     0.01,     # SS sedimentation
        "sedexp":    1.0,      # Sedimentation exponent
        "pprelmax":  10.0,     # Max P release from sediments (kg/km2)
        "pprelexp":  1.0,      # P release exponent
        "fertdays":  200,      # Growing season days
        "littdays":  100,      # Litter decomposition days
        # Land-use dependent (cropland defaults)
        "humusn0":   200.0,    # Humus N (kg/km2/m)
        "hnhalf":    2.0,      # Humus N decay depth (m)
        "humusp0":   20.0,     # Humus P (kg/km2/m)
        "hphalf":    2.0,      # Humus P decay depth (m)
        "partp0":    50.0,     # Particulate P (kg/km2/m)
        "pphalf":    1.0,      # Part P decay depth (m)
        "denitrlu":  0.0005,   # Land use denitrification (kg/m2/day)
        "onconc0":   5.0,      # Initial ON concentration (mg/L)
        "inconc0":   1.0,      # Initial IN concentration (mg/L)
        "ppconc0":   0.1,      # Initial PP concentration (mg/L)
        "spconc0":   0.05,     # Initial SP concentration (mg/L)
        # Soil dependent (soilpar)
        "macfilt":   0.5,      # Macropore filtration
        "freuc":     1.5,      # Freundlich P sorption coefficient (REQUIRED)
        "freuexp":   0.5,      # Freundlich exponent
        "freurate":  0.001,    # Freundlich rate
        # Crop uptake
        "minerfn":   0.002,    # Mineralization fast N (1/day)
        "minerfp":   0.001,    # Mineralization fast P
        "degradhn":  0.00005,  # Humus N degradation (1/day)
        "dissolhn":  0.0001,   # Dissolution humus N
        "dissolfn":  0.001,    # Dissolution fast N
        "dissolhp":  0.00005,  # Dissolution humus P
        "dissolfp":  0.0005,   # Dissolution fast P
        # Erosion
        "soilcoh":   10.0,     # Soil cohesion (kPa)
        "soilerod":  1.0,      # Soil erodibility
    },
    "midwest_us": {
        "fastn0":    80.0,
        "fastp0":    8.0,
        "denitwr":   0.005,
        "denitwrl":  0.004,
        "denitwl":   0.002,
        "sedon":     0.003,
        "sedpp":     0.003,
        "sedss":     0.015,
        "sedexp":    1.0,
        "pprelmax":  15.0,
        "pprelexp":  1.0,
        "fertdays":  180,
        "littdays":  120,
        "humusn0":   250.0,
        "hnhalf":    2.5,
        "humusp0":   25.0,
        "hphalf":    2.0,
        "partp0":    60.0,
        "pphalf":    1.5,
        "denitrlu":  0.0008,
        "onconc0":   8.0,
        "inconc0":   2.0,
        "ppconc0":   0.15,
        "spconc0":   0.08,
        "macfilt":   0.5,
        "freuc":     1.8,      # Freundlich P sorption coefficient
        "freuexp":   0.5,      # Freundlich exponent
        "freurate":  0.001,    # Freundlich rate
        "minerfn":   0.003,
        "minerfp":   0.0015,
        "degradhn":  0.00008,
        "dissolhn":  0.00015,
        "dissolfn":  0.0015,
        "dissolhp":  0.00008,
        "dissolfp":  0.0008,
        "soilcoh":   8.0,
        "soilerod":  1.2,
    },
    "europe_temperate": {
        "fastn0":    60.0,
        "fastp0":    6.0,
        "denitwr":   0.004,
        "denitwrl":  0.003,
        "denitwl":   0.0015,
        "sedon":     0.0025,
        "sedpp":     0.0025,
        "sedss":     0.012,
        "sedexp":    1.0,
        "pprelmax":  12.0,
        "pprelexp":  1.0,
        "fertdays":  160,
        "littdays":  150,
        "humusn0":   220.0,
        "hnhalf":    2.0,
        "humusp0":   22.0,
        "hphalf":    2.0,
        "partp0":    55.0,
        "pphalf":    1.2,
        "denitrlu":  0.0006,
        "onconc0":   6.0,
        "inconc0":   1.5,
        "ppconc0":   0.12,
        "spconc0":   0.06,
        "macfilt":   0.5,
        "freuc":     1.5,      # Freundlich P sorption coefficient
        "freuexp":   0.5,      # Freundlich exponent
        "freurate":  0.001,    # Freundlich rate
        "minerfn":   0.0025,
        "minerfp":   0.0012,
        "degradhn":  0.00006,
        "dissolhn":  0.00012,
        "dissolfn":  0.0012,
        "dissolhp":  0.00006,
        "dissolfp":  0.0006,
        "soilcoh":   9.0,
        "soilerod":  1.0,
    },
}

# NPC output variables to add to info.txt
# Use c1* (computed main flow) for modelled concentrations
# Do NOT use re* (requires observed nutrient data, outputs -9999 without it)
NPC_OUTPUT_VARS = {
    "N": ["c1IN", "c1ON", "c1TN"],
    "P": ["c1SP", "c1PP", "c1TP"],
    "C": ["c1OC"],
}


def parse_args():
    parser = argparse.ArgumentParser(description="Enable N/P simulation in HYPE")
    parser.add_argument("--info_txt", required=True, help="Path to info.txt")
    parser.add_argument("--par_txt", required=True, help="Path to par.txt")
    parser.add_argument("--substances", default="N P",
                        help='Substances: "N", "P", "N P", "N P C"')
    parser.add_argument("--region", default="huai_river",
                        choices=list(NPC_DEFAULTS.keys()),
                        help="Region for default NPC parameters")
    parser.add_argument("--geoclass", default=None,
                        help="Path to GeoClass.txt (for land use count)")
    return parser.parse_args()


def count_landuses(geoclass_path):
    """Count number of land use classes from GeoClass.txt.

    Uses max(landuse ID) from column 2 of GeoClass, since the number of
    land-use dependent parameter values must equal max(landuse ID).
    Note: GeoClass.txt has NO text header line (only !! comment lines),
    so we cannot just subtract 1 from line count.
    """
    if not geoclass_path or not Path(geoclass_path).exists():
        return 3  # default: cropland, forest, water
    max_luse = 1
    with open(geoclass_path) as f:
        for line in f:
            if line.strip() and not line.startswith('!'):
                parts = line.strip().split()
                try:
                    if len(parts) >= 2:
                        max_luse = max(max_luse, int(parts[1]))  # landuse is 2nd column
                except ValueError:
                    continue
    return max(1, max_luse)


def update_info_txt(info_path, substances):
    """Add substance declaration and NPC output variables to info.txt."""
    info = Path(info_path)
    if not info.exists():
        logger.error(f"info.txt not found: {info}")
        sys.exit(1)

    content = info.read_text()
    lines = content.split('\n')
    modified = False

    # Check if substance line already exists
    has_substance = any(re.match(r'^\s*substance\s', l) for l in lines)
    if has_substance:
        # Update existing substance line
        new_lines = []
        for l in lines:
            if re.match(r'^\s*substance\s', l):
                new_lines.append(f"substance\t{substances}")
                modified = True
            else:
                new_lines.append(l)
        lines = new_lines
    else:
        # Add substance line after edate
        new_lines = []
        for l in lines:
            new_lines.append(l)
            if l.strip().startswith('edate'):
                new_lines.append(f"substance\t{substances}")
                modified = True
        lines = new_lines

    # Add NPC output variables to timeoutput
    subs = substances.split()
    npc_vars = []
    for s in subs:
        if s in NPC_OUTPUT_VARS:
            npc_vars.extend(NPC_OUTPUT_VARS[s])

    # Find existing timeoutput variable line and append NPC vars
    for i, l in enumerate(lines):
        if 'timeoutput variable' in l and 'time' not in l.split('\t')[-1]:
            existing = l.split('\t')
            # Add NPC vars that aren't already there
            for v in npc_vars:
                if v not in existing:
                    existing.append(v)
            lines[i] = '\t'.join(existing)
            modified = True
            break

    if modified:
        info.write_text('\n'.join(lines))
        logger.info(f"Updated info.txt: substance={substances}, added {len(npc_vars)} output vars")
    else:
        logger.warning("No changes made to info.txt")

    return npc_vars


def count_soiltypes(geoclass_path):
    """Count number of soil types from GeoClass.txt."""
    if not geoclass_path or not Path(geoclass_path).exists():
        return 2  # default: loam, clay
    max_soil = 1
    with open(geoclass_path) as f:
        for line in f:
            if line.strip() and not line.startswith('!'):
                parts = line.strip().split()
                try:
                    if len(parts) >= 3:
                        max_soil = max(max_soil, int(parts[2]))  # soil is 3rd column
                except ValueError:
                    continue
    return max(1, max_soil)


def update_par_txt(par_path, region, n_landuses, substances, n_soiltypes=2):
    """Add NPC parameters to par.txt."""
    par = Path(par_path)
    if not par.exists():
        logger.error(f"par.txt not found: {par}")
        sys.exit(1)

    defaults = NPC_DEFAULTS[region]
    content = par.read_text()

    # Parameters to add, organized by type
    gen_params = {}   # genpar (single value)
    land_params = {}  # landpar (one value per land use)

    subs = substances.split()

    if 'N' in subs:
        gen_params.update({
            'fastn0': defaults['fastn0'],
            'denitwrm': defaults['denitwr'],
            'denitwrl': defaults['denitwrl'],
            'denitwl': defaults['denitwl'],
            'sedon': defaults['sedon'],
            'sedexp': defaults['sedexp'],
            'fertdays': defaults['fertdays'],
            'litterdays': defaults['littdays'],
        })
        land_params.update({
            'minerfn': defaults['minerfn'],
            'degradhn': defaults['degradhn'],
            'dissolhn': defaults['dissolhn'],
            'dissolfn': defaults['dissolfn'],
            'humusn0': defaults['humusn0'],
            'hnhalf': defaults['hnhalf'],
            'denitrlu': defaults['denitrlu'],
            'onconc0': defaults['onconc0'],
            'inconc0': defaults['inconc0'],
        })

    if 'P' in subs:
        gen_params.update({
            'fastp0': defaults['fastp0'],
            'sedpp': defaults['sedpp'],
            'sedss': defaults['sedss'],
            'pprelmax': defaults['pprelmax'],
            'pprelexp': defaults['pprelexp'],
        })
        land_params.update({
            'minerfp': defaults['minerfp'],
            'degradhp': defaults.get('degradhp', 0.00005),
            'dissolhp': defaults['dissolhp'],
            'dissolfp': defaults['dissolfp'],
            'humusp0': defaults['humusp0'],
            'hphalf': defaults['hphalf'],
            'partp0': defaults['partp0'],
            'pphalf': defaults['pphalf'],
            'ppconc0': defaults['ppconc0'],
            'spconc0': defaults['spconc0'],
        })

    # Soil-type dependent parameters
    soil_params = {}
    soil_params['macrofilt'] = defaults['macfilt']
    if 'P' in subs:
        soil_params['freuc'] = defaults['freuc']
        soil_params['freuexp'] = defaults['freuexp']
        soil_params['freurate'] = defaults['freurate']
        soil_params['soilcoh'] = defaults['soilcoh']
        soil_params['soilerod'] = defaults['soilerod']

    # Append NPC parameters to par.txt
    with open(par, 'a') as f:
        f.write("\n!! ============================================\n")
        f.write(f"!! NPC parameters (region: {region})\n")
        f.write("!! ============================================\n\n")

        # General parameters
        for name, value in gen_params.items():
            # Check if already in par.txt
            if re.search(rf'^\s*{name}\s', content, re.MULTILINE):
                logger.info(f"  {name} already exists in par.txt, skipping")
                continue
            f.write(f"{name}\t{value}\n")
            logger.info(f"  Added genpar: {name} = {value}")

        # Land-use dependent parameters
        f.write("\n!! Land-use dependent NPC parameters\n")
        for name, value in land_params.items():
            if re.search(rf'^\s*{name}\s', content, re.MULTILINE):
                logger.info(f"  {name} already exists in par.txt, skipping")
                continue
            # Write n_landuses copies of the same default value
            vals = '\t'.join([str(value)] * n_landuses)
            f.write(f"{name}\t{vals}\n")
            logger.info(f"  Added landpar: {name} = {value} (×{n_landuses} land uses)")

        # Soil-type dependent parameters
        f.write("\n!! Soil-type dependent NPC parameters\n")
        for name, value in soil_params.items():
            if re.search(rf'^\s*{name}\s', content, re.MULTILINE):
                logger.info(f"  {name} already exists in par.txt, skipping")
                continue
            vals = '\t'.join([str(value)] * n_soiltypes)
            f.write(f"{name}\t{vals}\n")
            logger.info(f"  Added soilpar: {name} = {value} (×{n_soiltypes} soil types)")

    total = len(gen_params) + len(land_params) + len(soil_params)
    logger.info(f"Added {total} NPC parameters to par.txt")
    return total


def count_subbasins(info_dir):
    """Count subbasins from GeoData.txt in the same directory as info.txt."""
    geodata_path = Path(info_dir) / "modelfiles" / "GeoData.txt"
    if not geodata_path.exists():
        geodata_path = Path(info_dir) / "GeoData.txt"
    if not geodata_path.exists():
        return None
    n = 0
    with open(geodata_path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('!'):
                n += 1
    return max(0, n - 1)  # subtract header


def main():
    args = parse_args()

    # Validate inputs
    for f in [args.info_txt, args.par_txt]:
        if not Path(f).exists():
            logger.error(f"File not found: {f}")
            sys.exit(1)

    # Warn on single-subbasin NPC setup
    info_dir = Path(args.info_txt).parent
    nsub = count_subbasins(info_dir)
    if nsub is not None and nsub <= 1:
        logger.warning(
            f"*** SINGLE-SUBBASIN NPC WARNING (nsubbasins={nsub}) ***\n"
            "  Dissolved inorganic N (IN) and soluble P (SP) will accumulate to\n"
            "  unrealistic concentrations (>1000 mg/L) because there is no downstream\n"
            "  routing to flush nutrients. Organic N (ON) and particulate P (PP) will\n"
            "  be realistic. For meaningful IN/SP concentrations, use 3+ subbasins\n"
            "  or increase denitrlu/denitwrm by 10-100x to compensate."
        )

    n_landuses = count_landuses(args.geoclass)
    n_soiltypes = count_soiltypes(args.geoclass)
    logger.info(f"Land use classes: {n_landuses}, Soil types: {n_soiltypes}")

    # Update info.txt
    npc_vars = update_info_txt(args.info_txt, args.substances)

    # Update par.txt
    n_params = update_par_txt(args.par_txt, args.region, n_landuses, args.substances, n_soiltypes)

    result = {
        "status": "success",
        "substances": args.substances,
        "region": args.region,
        "n_landuses": n_landuses,
        "n_params_added": n_params,
        "output_vars_added": npc_vars,
        "notes": [
            f"NPC enabled with {args.substances} for region {args.region}",
            "Use 3+ year warmup for nutrient pool initialization",
            "Check reTN/reTP in output for total nutrient loads at outlet",
            "Check ccIN/ccON for instream concentrations (ug/L)",
        ],
    }
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
