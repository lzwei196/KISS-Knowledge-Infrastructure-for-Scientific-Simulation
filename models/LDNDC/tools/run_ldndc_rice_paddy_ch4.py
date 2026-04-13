#!/usr/bin/env python3
"""
LDNDC Rice Paddy CH4 simulation pipeline for SE China.

Test 7 of expanded capability validation suite.
Adapts the validated Bengbu wheat-maize pipeline to rice paddy with:
  - :RICE: species (built-in LDNDC Lresources)
  - Paddy flooding via irrigate events
  - Single-crop rice rotation (May transplant → Oct harvest)
  - SE China soil from HWSD

Usage:
    python run_ldndc_rice_paddy_ch4.py
    python run_ldndc_rice_paddy_ch4.py --lat 31.125 --lon 117.375
"""

import argparse
import csv
import io
import json
import logging
import math
import os
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np

# ── Paths ─────────────────────��───────────────────────────��────────────────
PROJECT_ROOT = Path("/mnt/disk1/Hydrocraft_server")
LDNDC_BASE = PROJECT_ROOT / "model" / "ldndc" / "ldndc-1.37.linux64"
LDNDC_BIN = LDNDC_BASE / "bin" / "ldndc"
PROJECTS_DIR = LDNDC_BASE / "projects"
HWSD_RASTER = PROJECT_ROOT / "data" / "soil" / "HWSD_RASTER" / "hwsd.bil"
HWSD_MDB = PROJECT_ROOT / "data" / "forcing" / "huaihe_raw" / "soil" / "HWSD.mdb"
VIC_FORCING_DIR = (
    PROJECT_ROOT
    / "outputs"
    / "bengbu_2000-2005_025deg"
    / "vic_temp"
    / "forcing"
    / "forcing_final"
)

# Simulation defaults — SE China rice paddy
DEFAULT_LAT = 32.125   # Nearest VIC forcing to SE China
DEFAULT_LON = 117.375
DEFAULT_ELEVATION = 15.0
START_YEAR = 2000
END_YEAR = 2005
STEPS_PER_DAY = 8  # VIC 3-hourly

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("ldndc_rice_ch4")


# ── Reuse from bengbu pipeline ──────────────────────────────────────────────
# Import shared functions from the bengbu pipeline
sys.path.insert(0, str(Path(__file__).parent))
from run_ldndc_bengbu_ghg import (
    find_nearest_forcing,
    vic_forcing_to_ldndc_climate,
    get_hwsd_soil,
    write_site_xml,
    write_airchem,
    parse_output,
    parse_yearly_output,
    pedotransfer_sks,
    pedotransfer_wc,
    compute_usda_texture,
)


# ── Rice Paddy Management (single rice, SE China) ──────────────────────────
def write_rice_management_xml(output_path: Path, start_year: int, end_year: int) -> None:
    """
    Generate single-season rice paddy management for SE China.

    Typical Yangtze Delta / SE China single rice:
      - Transplant: May 15-25 (seedlings from nursery)
      - Basal fertilizer at transplant
      - Topdressing 1: Jun 15 (tillering)
      - Topdressing 2: Jul 20 (panicle initiation)
      - Continuous flooding: maintained from transplant to ~3 weeks before harvest
      - Mid-season drain: ~Jul 1 (7-10 days) to reduce CH4
      - Harvest: Oct 1-15
      - N application: ~200 kgN/ha/yr total

    LDNDC irrigate event: adds water to surface, simulating paddy flooding.
    Heavy irrigation (every 3-5 days) needed to maintain standing water
    even with low-Ksat paddy soil. The metrx module handles CH4 production
    under sustained anaerobic conditions.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w") as f:
        f.write('<?xml version="1.0" ?>\n\n')
        f.write("<ldndcevent>\n")
        f.write('    <event id="0">\n')

        for yr in range(start_year, end_year + 1):
            f.write(f"\n        <!-- {yr} Single Rice Paddy Season -->\n")

            # Spring tillage (puddling for paddy)
            f.write(f'        <event type="till" time="{yr}-05-01">\n')
            f.write('            <till depth="0.15" />\n')
            f.write("        </event>\n")

            # Initial flooding (pre-transplant puddling)
            for d in [5, 8, 11, 14, 17]:
                f.write(f'        <event type="irrigate" time="{yr}-05-{d:02d}">\n')
                f.write('            <irrigate amount="60.0" />\n')
                f.write("        </event>\n")

            # Transplant rice
            f.write(f'        <event type="plant" time="{yr}-05-20">\n')
            f.write('            <plant type=":RICE:">\n')
            f.write('                <crop initialbiomass="50.0" />\n')
            f.write("            </plant>\n")
            f.write("        </event>\n")

            # Basal fertilizer
            f.write(f'        <event type="fertilize" time="{yr}-05-21">\n')
            f.write('            <fertilize type="urea" amount="60" depth="0.02" />\n')
            f.write("        </event>\n")

            # Maintain continuous flooding May 20 - Jun 28 (every 3 days)
            for d in [20, 23, 26, 29]:
                f.write(f'        <event type="irrigate" time="{yr}-05-{d:02d}">\n')
                f.write('            <irrigate amount="40.0" />\n')
                f.write("        </event>\n")

            for d in [1, 4, 7, 10, 13]:
                f.write(f'        <event type="irrigate" time="{yr}-06-{d:02d}">\n')
                f.write('            <irrigate amount="40.0" />\n')
                f.write("        </event>\n")

            # Topdressing 1 — tillering stage
            f.write(f'        <event type="fertilize" time="{yr}-06-15">\n')
            f.write('            <fertilize type="urea" amount="50" depth="0.02" />\n')
            f.write("        </event>\n")

            for d in [15, 18, 21, 24, 27]:
                f.write(f'        <event type="irrigate" time="{yr}-06-{d:02d}">\n')
                f.write('            <irrigate amount="40.0" />\n')
                f.write("        </event>\n")

            # Mid-season drain Jul 1-10: NO irrigation events
            # (standard practice to control CH4 and promote root growth)

            # Resume flooding after mid-season drain: Jul 12 - Sep 10
            for d in [12, 15, 18]:
                f.write(f'        <event type="irrigate" time="{yr}-07-{d:02d}">\n')
                f.write('            <irrigate amount="50.0" />\n')
                f.write("        </event>\n")

            # Topdressing 2 — panicle initiation
            f.write(f'        <event type="fertilize" time="{yr}-07-20">\n')
            f.write('            <fertilize type="urea" amount="50" depth="0.02" />\n')
            f.write("        </event>\n")

            for d in [20, 23, 26, 29]:
                f.write(f'        <event type="irrigate" time="{yr}-07-{d:02d}">\n')
                f.write('            <irrigate amount="40.0" />\n')
                f.write("        </event>\n")

            # August: heading and grain filling — maintain flooding
            for d in [1, 4, 7]:
                f.write(f'        <event type="irrigate" time="{yr}-08-{d:02d}">\n')
                f.write('            <irrigate amount="40.0" />\n')
                f.write("        </event>\n")

            # Topdressing 3 — grain filling (smaller dose)
            f.write(f'        <event type="fertilize" time="{yr}-08-10">\n')
            f.write('            <fertilize type="urea" amount="40" depth="0.02" />\n')
            f.write("        </event>\n")

            for d in [10, 13, 16, 19, 22, 25, 28]:
                f.write(f'        <event type="irrigate" time="{yr}-08-{d:02d}">\n')
                f.write('            <irrigate amount="35.0" />\n')
                f.write("        </event>\n")

            # September: ripening — reduce irrigation, then final drain
            for d in [1, 5, 10]:
                f.write(f'        <event type="irrigate" time="{yr}-09-{d:02d}">\n')
                f.write('            <irrigate amount="25.0" />\n')
                f.write("        </event>\n")

            # No irrigation after Sep 15 = final drain before harvest

            # Harvest
            f.write(f'        <event type="harvest" time="{yr}-10-10">\n')
            f.write('            <harvest name=":RICE:" remains="0.70" />\n')
            f.write("        </event>\n")

            # Post-harvest straw incorporation (common in China)
            f.write(f'        <event type="till" time="{yr}-10-20">\n')
            f.write('            <till depth="0.10" />\n')
            f.write("        </event>\n")

        f.write("\n    </event>\n")
        f.write("</ldndcevent>\n")

    logger.info(f"Rice paddy management XML written: {output_path} ({start_year}-{end_year})")


# ── Rice Paddy Setup (enable metrx for CH4) ───────────────────────────���────
def write_rice_setup_xml(output_path: Path, lat: float, lon: float, elevation: float) -> None:
    """Write LDNDC setup.xml with modules appropriate for rice paddy CH4."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        f.write('<?xml version="1.0"?>\n')
        f.write("<ldndcsetup>\n")
        f.write(f'    <setup id="0" name="Rice_Paddy_CH4">\n')
        f.write(
            f'        <location elevation="{elevation:.1f}" latitude="{lat:.2f}" '
            f'longitude="{lon:.2f}" slope="0" />\n'
        )
        f.write("        <models>\n")
        f.write('            <model id="_MoBiLE" />\n')
        f.write("        </models>\n")
        f.write("        <mobile>\n")
        f.write("            <modulelist>\n")
        f.write('                <module id="microclimate:canopyecm" timemode="subdaily" />\n')
        f.write('                <module id="watercycle:watercycledndc" timemode="subdaily" />\n')
        f.write('                <module id="airchemistry:airchemistrydndc" timemode="subdaily" />\n')
        f.write('                <module id="physiology:plamox" timemode="subdaily" />\n')
        f.write('                <module id="soilchemistry:metrx" timemode="subdaily" />\n')
        f.write("\n")
        f.write("                <!-- outputs -->\n")
        f.write('                <module id="output:microclimate:daily" />\n')
        f.write('                <module id="output:watercycle:daily" />\n')
        f.write('                <module id="output:physiology:daily" />\n')
        f.write('                <module id="output:soilchemistry:daily" />\n')
        f.write('                <module id="output:soilchemistry:yearly" />\n')
        f.write('                <module id="output:report:arable:harvest" timemode="subdaily" />\n')
        f.write('                <module id="output:report:arable:fertilize" timemode="subdaily" />\n')
        f.write("            </modulelist>\n")
        f.write("        </mobile>\n")
        f.write("    </setup>\n")
        f.write("</ldndcsetup>\n")

    logger.info(f"Rice paddy setup XML written: {output_path}")


def write_rice_project_xml(output_path: Path, start_year: int, end_year: int, run_tag: str) -> None:
    """Write LDNDC project descriptor XML for rice paddy."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    nyears = end_year - start_year + 1

    with open(output_path, "w") as f:
        f.write('<?xml version="1.0" ?>\n')
        f.write('<ldndcproject PackageMinimumVersionRequired="1.3">\n')
        f.write(
            f'    <schedule time="{start_year}-01-01/24 -> +{nyears}-0-0" />\n'
        )
        f.write("    <input>\n")
        f.write(f'        <sources sourceprefix="arable/{run_tag}/rice_">\n')
        f.write('            <setup source="setup.xml" />\n')
        f.write('            <site source="site.xml" />\n')
        f.write('            <airchemistry source="airchem.txt" format="txt" />\n')
        f.write('            <climate source="climate.txt" format="txt" />\n')
        f.write('            <event source="mana.xml" />\n')
        f.write("        </sources>\n")
        f.write('        <attributes use="0" endless="0">\n')
        f.write('            <airchemistry endless="yes" />\n')
        f.write('            <climate endless="1" />\n')
        f.write("        </attributes>\n")
        f.write("    </input>\n")
        f.write("    <output>\n")
        f.write(f'        <sinks sinkprefix="arable/{run_tag}/{run_tag}_output/rice_" />\n')
        f.write("    </output>\n")
        f.write("</ldndcproject>\n")

    logger.info(f"Rice paddy project XML written: {output_path}")


def run_ldndc(project_file: Path) -> tuple:
    """Execute LDNDC binary with the project file. Returns (exit_code, stdout, stderr)."""
    logger.info(f"Running LDNDC: {LDNDC_BIN} {project_file}")
    logger.info(f"Working directory: {LDNDC_BASE}")

    result = subprocess.run(
        [str(LDNDC_BIN), str(project_file)],
        cwd=str(LDNDC_BASE),
        capture_output=True,
        text=True,
        timeout=3600,
    )

    if result.stdout:
        stdout_tail = result.stdout[-3000:]
        logger.info(f"LDNDC stdout (tail):\n{stdout_tail}")

    if result.stderr:
        stderr_tail = result.stderr[-2000:]
        logger.warning(f"LDNDC stderr (tail):\n{stderr_tail}")

    if result.returncode != 0:
        logger.error(f"LDNDC exited with code {result.returncode}")
    else:
        logger.info("LDNDC completed successfully.")

    return result.returncode, result.stdout, result.stderr


def main():
    parser = argparse.ArgumentParser(
        description="Run LDNDC rice paddy CH4 simulation for SE China"
    )
    parser.add_argument("--lat", type=float, default=DEFAULT_LAT)
    parser.add_argument("--lon", type=float, default=DEFAULT_LON)
    parser.add_argument("--elevation", type=float, default=DEFAULT_ELEVATION)
    parser.add_argument("--forcing_file", type=str, default=None)
    parser.add_argument("--forcing_dir", type=str, default=str(VIC_FORCING_DIR))
    parser.add_argument("--start_year", type=int, default=START_YEAR)
    parser.add_argument("--end_year", type=int, default=END_YEAR)
    parser.add_argument("--dry_run", action="store_true")
    args = parser.parse_args()

    lat = args.lat
    lon = args.lon
    elevation = args.elevation
    start_year = args.start_year
    end_year = args.end_year

    logger.info("=" * 60)
    logger.info("LDNDC Rice Paddy CH4 Simulation — SE China")
    logger.info(f"Location: ({lat}, {lon}), Elevation: {elevation} m")
    logger.info(f"Period: {start_year}-{end_year}")
    logger.info("=" * 60)

    # ── Step 1: Find forcing file ──
    if args.forcing_file:
        forcing_file = Path(args.forcing_file)
    else:
        forcing_dir = Path(args.forcing_dir)
        forcing_file = find_nearest_forcing(forcing_dir, lat, lon)

    # ── Set up project directory ──
    run_tag = f"rice_paddy_{lat:.4f}_{lon:.4f}_{start_year}"
    project_dir = PROJECTS_DIR / "arable" / run_tag
    output_dir = project_dir / f"{run_tag}_output"
    project_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── Step 2: Convert VIC forcing → LDNDC climate ──
    logger.info("\n--- Step 2: Convert VIC forcing to LDNDC climate ---")
    climate_path = project_dir / "rice_climate.txt"
    vic_forcing_to_ldndc_climate(forcing_file, climate_path, lat, lon, elevation, start_year)

    # ── Step 3: Extract HWSD soil → site.xml ──
    logger.info("\n--- Step 3: Extract HWSD soil data ---")
    soil = get_hwsd_soil(lat, lon)

    # For rice paddy: use lower Ksat (compacted paddy bottom) and higher initial moisture
    site_path = project_dir / "rice_site.xml"
    write_site_xml(soil, site_path)

    # Post-process: corg floor + paddy soil modifications
    import re as _re
    _site_txt = site_path.read_text()
    _site_txt = _re.sub(r'corg="0\.0000"', 'corg="0.0005"', _site_txt)
    _site_txt = _site_txt.replace("Bengbu-China-HWSD", "SEChina-RicePaddy-HWSD")

    # Critical: modify soil for rice paddy — reduce Ksat to simulate plow pan
    # Rice paddies have compacted puddled layer at 10-30 cm with very low Ksat
    # Typical paddy Ksat: 0.0001-0.001 cm/min vs upland 0.01-0.1 cm/min
    # Also increase topsoil OC (straw incorporation) and adjust pH for paddy
    import xml.etree.ElementTree as ET
    tree = ET.parse(site_path)
    root = tree.getroot()
    layers = root.find('.//layers')
    if layers is not None:
        for i, layer in enumerate(layers.findall('layer')):
            if i < 3:  # Top 3 layers (0-30 cm): puddled paddy soil
                # Reduce Ksat drastically (plow pan effect)
                layer.set('sks', '0.0003' if i == 0 else '0.0001')
                # Increase bulk density for compacted paddy
                old_bd = float(layer.get('bd', '1.35'))
                layer.set('bd', f'{min(old_bd + 0.10, 1.60):.2f}')
                # Increase field capacity (puddled soil holds more water)
                old_fc = float(layer.get('wc_fc', '300'))
                layer.set('wc_fc', f'{min(old_fc + 50, 420):.1f}')
                # Increase OC (straw incorporation)
                old_corg = float(layer.get('corg', '0.01'))
                layer.set('corg', f'{max(old_corg * 1.3, 0.012):.4f}')
                # Remove gravel (paddy fields are stone-free)
                layer.set('scel', '0.00')
            elif i == 3:  # Layer below plow pan — transitional
                layer.set('sks', '0.0010')
    tree.write(site_path, xml_declaration=True, encoding='UTF-8')
    logger.info("  Applied paddy soil modifications: low Ksat plow pan, increased FC/OC")

    # ── Step 4: Write setup.xml ──
    logger.info("\n--- Step 4: Write rice paddy setup.xml ---")
    setup_path = project_dir / "rice_setup.xml"
    write_rice_setup_xml(setup_path, lat, lon, elevation)

    # ── Step 5: Write rice management ──
    logger.info("\n--- Step 5: Write rice paddy management ---")
    mana_path = project_dir / "rice_mana.xml"
    write_rice_management_xml(mana_path, start_year, end_year)

    # ── Step 6: Write airchemistry ──
    logger.info("\n--- Step 6: Write airchemistry ---")
    airchem_path = project_dir / "rice_airchem.txt"
    write_airchem(airchem_path)

    # ── Step 7: Write project.ldndc ──
    logger.info("\n--- Step 7: Write project.ldndc ---")
    project_xml_path = project_dir / "rice.ldndc"
    write_rice_project_xml(project_xml_path, start_year, end_year, run_tag=run_tag)

    # Summary of generated files
    logger.info("\n--- Generated files ---")
    for p in [climate_path, site_path, setup_path, mana_path, airchem_path, project_xml_path]:
        size = p.stat().st_size if p.exists() else 0
        logger.info(f"  {p.name}: {size:,} bytes")

    if args.dry_run:
        logger.info("\n--- DRY RUN: Skipping LDNDC execution ---")
        print(json.dumps({"status": "dry_run", "project_dir": str(project_dir)}, indent=2))
        return

    # ── Step 8: Run LDNDC ──
    logger.info("\n--- Step 8: Run LDNDC ---")
    project_rel = project_xml_path.relative_to(LDNDC_BASE)
    exit_code, stdout, stderr = run_ldndc(project_rel)

    if exit_code != 0:
        logger.error(f"LDNDC failed with exit code {exit_code}")
        # Check for common issues
        combined = stdout + stderr
        if "species" in combined.lower() or "unknown" in combined.lower():
            logger.error("Possible species name issue — check :RICE: in Lresources")
        if "irrigate" in combined.lower() or "event" in combined.lower():
            logger.error("Possible event type issue — check irrigate event syntax")

        # Try listing output dir for any partial output
        if output_dir.exists():
            existing = [f.name for f in output_dir.iterdir()]
            logger.info(f"Partial output files: {existing}")

        sys.exit(exit_code)

    # ── Step 9: Parse output ──
    logger.info("\n--- Step 9: Parse LDNDC output ---")
    results = parse_output(output_dir, start_year, end_year)

    yearly = parse_yearly_output(output_dir)
    if yearly:
        results["yearly_summary"] = {str(k): v for k, v in sorted(yearly.items())}

    # ── Print results ──
    logger.info("\n" + "=" * 60)
    logger.info("RICE PADDY CH4 ANNUAL BUDGET SUMMARY")
    logger.info("=" * 60)

    for yr_str, vals in sorted(results.get("years", {}).items()):
        logger.info(f"\n  Year {yr_str} ({vals.get('days', '?')} days):")
        logger.info(f"    N2O emission:    {vals['n2o_kgN_ha']:.3f} kgN/ha "
                     f"({vals.get('n2o_kg_ha', 0):.3f} kg N2O/ha)")
        logger.info(f"    CH4 emission:    {vals['ch4_kgC_ha']:.4f} kgC/ha")
        logger.info(f"    CO2 hetero resp: {vals['co2_hetero_kgC_ha']:.1f} kgC/ha")
        logger.info(f"    NO3 leaching:    {vals['no3_leach_kgN_ha']:.2f} kgN/ha")
        logger.info(f"    GHG total:       {vals.get('total_ghg_co2eq_kg_ha', 0):.1f} kg CO2eq/ha")

    if results.get("totals"):
        t = results["totals"]
        logger.info(f"\n  Period averages ({t['period']}, {t['n_years']} years):")
        logger.info(f"    N2O: {t['avg_n2o_kgN_ha_yr']:.3f} kgN/ha/yr")
        logger.info(f"    CH4: {t['avg_ch4_kgC_ha_yr']:.4f} kgC/ha/yr")
        logger.info(f"    CO2 (Rh): {t['avg_co2_hetero_kgC_ha_yr']:.1f} kgC/ha/yr")
        logger.info(f"    NO3 leach: {t['avg_no3_leach_kgN_ha_yr']:.2f} kgN/ha/yr")
        logger.info(f"    Total GHG: {t['avg_total_ghg_co2eq_kg_ha_yr']:.1f} kg CO2eq/ha/yr")

    # Output JSON
    json_path = output_dir / f"{run_tag}_ch4_summary.json"
    with open(json_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    logger.info(f"\nJSON summary written: {json_path}")

    print(json.dumps(results, indent=2, default=str))


if __name__ == "__main__":
    main()
