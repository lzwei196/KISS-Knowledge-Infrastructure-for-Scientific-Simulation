#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
====================================================
Tool ID:      adapt_swatplus_project
Stage:        s7_simulation_config
Description:  Adapt a working SWAT+ TxtInOut template project for a new basin by
              replacing weather files, soil data, time period, and file.cio header.

This script is a VALIDATED TOOL: an executable that the AI agent calls
rather than writes. It guarantees correctness independent of the language
model. The agent should never modify this script -- only call it.

Inputs:
  --template_dir  : Path to a working SWAT+ TxtInOut directory (str)
  --output_dir    : Path for the adapted project output (str)
  --weather_dir   : Path to new weather files produced by vic_forcing_to_swatplus (str)
  --soil_file     : Path to new soils.sol from hwsd_to_swatplus_soil (str)
  --start_year    : Simulation start year (int)
  --end_year      : Simulation end year (int)
  --basin_name    : Name for the new basin (str)
  --warmup_years  : Number of warmup years for print.prt nyskip (int, default 2)

Outputs:
  - Complete SWAT+ TxtInOut directory at output_dir with all files adapted

Preconditions:
  - template_dir must exist and contain a valid SWAT+ TxtInOut project
  - weather_dir must exist and contain .pcp, .tmp, .slr, .hmd, .wnd files
  - soil_file must exist and be a valid soils.sol file
  - start_year < end_year

Postconditions:
  - output_dir contains all template files, with weather/soil/time updated
  - pcp.cli, tmp.cli, slr.cli, hmd.cli, wnd.cli point to new weather files
  - weather-sta.cli references the new weather files
  - soils.sol is replaced with the new soil file
  - time.sim reflects the new simulation period
  - file.cio header updated with basin name

Usage:
  python adapt_swatplus_project.py \\
    --template_dir /path/to/template/TxtInOut \\
    --output_dir /path/to/new_project \\
    --weather_dir /path/to/new_weather \\
    --soil_file /path/to/new_soils.sol \\
    --start_year 2000 --end_year 2010 \\
    --basin_name my_basin

Exit codes:
  0 -- success
  1 -- input validation failed
  2 -- processing error
  3 -- output validation failed
"""

import sys
import os
import logging
import json
import shutil
import argparse
import re
from pathlib import Path
from datetime import datetime

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Weather file extensions and their .cli index counterparts
# ---------------------------------------------------------------------------
WEATHER_TYPES = {
    "pcp": {"ext": ".pcp", "cli": "pcp.cli", "description": "Precipitation"},
    "tmp": {"ext": ".tmp", "cli": "tmp.cli", "description": "Temperature"},
    "slr": {"ext": ".slr", "cli": "slr.cli", "description": "Solar radiation"},
    "hmd": {"ext": ".hmd", "cli": "hmd.cli", "description": "Relative humidity"},
    "wnd": {"ext": ".wnd", "cli": "wnd.cli", "description": "Wind speed"},
}

# Files in the template that are weather data (not to be blindly copied)
WEATHER_EXTENSIONS = {".pcp", ".tmp", ".slr", ".hmd", ".wnd"}

# Files that will be regenerated, so skip during copy
REGENERATED_FILES = {"pcp.cli", "tmp.cli", "slr.cli", "hmd.cli", "wnd.cli",
                     "weather-sta.cli", "soils.sol", "time.sim", "file.cio",
                     "print.prt"}


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
def parse_args():
    parser = argparse.ArgumentParser(
        description="Adapt a SWAT+ TxtInOut template project for a new basin."
    )
    parser.add_argument("--template_dir", required=True,
                        help="Path to a working SWAT+ TxtInOut directory")
    parser.add_argument("--output_dir", required=True,
                        help="Path for the adapted project output")
    parser.add_argument("--weather_dir", required=True,
                        help="Path to new weather files (.pcp, .tmp, .slr, .hmd, .wnd)")
    parser.add_argument("--soil_file", required=True,
                        help="Path to new soils.sol file")
    parser.add_argument("--start_year", type=int, required=True,
                        help="Simulation start year")
    parser.add_argument("--end_year", type=int, required=True,
                        help="Simulation end year")
    parser.add_argument("--basin_name", required=True,
                        help="Name for the new basin")
    parser.add_argument("--warmup_years", type=int, default=2,
                        help="Number of warmup years for print.prt nyskip (default: 2)")
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------
def validate_inputs(args):
    """Check that all preconditions are met before processing."""
    errors = []

    template_dir = Path(args.template_dir)
    weather_dir = Path(args.weather_dir)
    soil_file = Path(args.soil_file)

    # Template directory must exist and contain essential SWAT+ files
    if not template_dir.is_dir():
        errors.append(f"Template directory not found: {args.template_dir}")
    else:
        essential_files = ["file.cio", "time.sim", "print.prt", "soils.sol",
                           "pcp.cli", "tmp.cli", "weather-sta.cli"]
        for ef in essential_files:
            if not (template_dir / ef).exists():
                errors.append(f"Template missing essential file: {ef}")

    # Weather directory must exist and contain at least one weather data file
    if not weather_dir.is_dir():
        errors.append(f"Weather directory not found: {args.weather_dir}")
    else:
        weather_file_count = 0
        for ext in WEATHER_EXTENSIONS:
            weather_file_count += len(list(weather_dir.glob(f"*{ext}")))
        if weather_file_count == 0:
            errors.append(f"No weather data files (.pcp/.tmp/.slr/.hmd/.wnd) "
                          f"found in {args.weather_dir}")

    # Soil file must exist
    if not soil_file.is_file():
        errors.append(f"Soil file not found: {args.soil_file}")

    # Time period validation
    if args.start_year >= args.end_year:
        errors.append(f"start_year ({args.start_year}) must be < end_year ({args.end_year})")

    if args.start_year < 1900 or args.end_year > 2100:
        errors.append(f"Year range {args.start_year}-{args.end_year} seems unreasonable")

    if args.warmup_years < 0:
        errors.append(f"warmup_years must be >= 0, got {args.warmup_years}")

    if not args.basin_name or not args.basin_name.strip():
        errors.append("basin_name cannot be empty")

    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)

    logger.info("Input validation passed.")


def validate_outputs(output_dir, expected_weather_files):
    """Check that postconditions are met after processing."""
    errors = []
    output_path = Path(output_dir)

    # Check essential output files exist
    essential = ["file.cio", "time.sim", "print.prt", "soils.sol",
                 "pcp.cli", "tmp.cli", "slr.cli", "hmd.cli", "wnd.cli",
                 "weather-sta.cli"]
    for ef in essential:
        if not (output_path / ef).exists():
            errors.append(f"Essential output file missing: {ef}")

    # Check that weather data files were copied
    for wf in expected_weather_files:
        if not (output_path / wf).exists():
            errors.append(f"Weather data file not copied: {wf}")

    # Check soils.sol is non-empty
    soil_path = output_path / "soils.sol"
    if soil_path.exists() and soil_path.stat().st_size == 0:
        errors.append("soils.sol is empty")

    # Check time.sim has correct structure (3 lines: header, col names, data)
    time_path = output_path / "time.sim"
    if time_path.exists():
        lines = time_path.read_text().strip().split('\n')
        if len(lines) < 3:
            errors.append(f"time.sim has only {len(lines)} lines, expected >= 3")

    # Count total files
    total_files = len(list(output_path.iterdir()))
    if total_files < 10:
        errors.append(f"Output directory has only {total_files} files, "
                      f"expected many more from template")

    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(3)

    logger.info("Output validation passed.")
    return total_files


# ---------------------------------------------------------------------------
# Core processing functions
# ---------------------------------------------------------------------------
def discover_weather_files(weather_dir):
    """Discover all weather data files in the weather directory, grouped by type."""
    weather_dir = Path(weather_dir)
    files_by_type = {}
    for wtype, info in WEATHER_TYPES.items():
        ext = info["ext"]
        found = sorted([f.name for f in weather_dir.glob(f"*{ext}")])
        files_by_type[wtype] = found
        if found:
            logger.info(f"  Found {len(found)} {info['description']} files ({ext})")
        else:
            logger.warning(f"  No {info['description']} files ({ext}) found")
    return files_by_type


def copy_template_files(template_dir, output_dir):
    """Copy all non-weather, non-regenerated template files to output."""
    template_dir = Path(template_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    copied = 0
    skipped = []
    for src_file in sorted(template_dir.iterdir()):
        if not src_file.is_file():
            continue

        name = src_file.name

        # Skip weather data files from the template (we'll copy new ones)
        if src_file.suffix in WEATHER_EXTENSIONS:
            skipped.append(name)
            continue

        # Skip files that will be regenerated
        if name in REGENERATED_FILES:
            skipped.append(name)
            continue

        # Skip SWAT+ output files (will be regenerated by the model run)
        if name.endswith(('.out', '.txt')) and name not in REGENERATED_FILES:
            # Keep config .txt files, skip output .txt files
            # Output files have patterns like basin_wb_yr.txt, channel_yr.txt
            if re.match(r'^(basin|channel|hru|region|lsunit|aquifer|reservoir)_.*\.(txt|out)$', name):
                skipped.append(name)
                continue

        dst_file = output_dir / name
        shutil.copy2(src_file, dst_file)
        copied += 1

    logger.info(f"Copied {copied} template files, skipped {len(skipped)} "
                f"(weather data + regenerated + outputs)")
    return copied


def copy_weather_files(weather_dir, output_dir, files_by_type):
    """Copy new weather data files from weather_dir to output_dir."""
    weather_dir = Path(weather_dir)
    output_dir = Path(output_dir)

    all_weather_files = []
    for wtype, file_list in files_by_type.items():
        for fname in file_list:
            src = weather_dir / fname
            dst = output_dir / fname
            shutil.copy2(src, dst)
            all_weather_files.append(fname)

    logger.info(f"Copied {len(all_weather_files)} new weather data files")
    return all_weather_files


def write_cli_file(output_dir, cli_name, header_desc, filenames):
    """Write a SWAT+ .cli index file listing the weather data file names."""
    output_path = Path(output_dir) / cli_name
    with open(output_path, 'w') as f:
        f.write(f"{cli_name}: {header_desc} - file written by adapt_swatplus_project\n")
        f.write("filename\n")
        for fn in filenames:
            f.write(f"{fn}\n")
    logger.info(f"Wrote {cli_name} with {len(filenames)} entries")


def write_weather_sta_cli(output_dir, files_by_type, basin_name):
    """Write weather-sta.cli mapping stations to their weather files.

    Each precipitation station gets its own entry. Temperature, solar, humidity,
    and wind use the first available file (SWAT+ assigns to subbasin centroids).
    If multiple .tmp/.slr/.hmd/.wnd files exist, each pcp station maps to the
    corresponding index (or wraps to the last).
    """
    output_path = Path(output_dir) / "weather-sta.cli"

    pcp_files = files_by_type.get("pcp", [])
    tmp_files = files_by_type.get("tmp", [])
    slr_files = files_by_type.get("slr", [])
    hmd_files = files_by_type.get("hmd", [])
    wnd_files = files_by_type.get("wnd", [])

    # Number of stations = max across all types (at least 1)
    n_stations = max(len(pcp_files), len(tmp_files), len(slr_files),
                     len(hmd_files), len(wnd_files), 1)

    def get_or_last(file_list, idx):
        """Get file at index, or the last file, or 'null' if empty."""
        if not file_list:
            return "null"
        return file_list[min(idx, len(file_list) - 1)]

    # Build the header -- SWAT+ uses fixed-width columns
    col_w = 27  # column width matching template format
    with open(output_path, 'w') as f:
        f.write(f"weather-sta.cli: written by adapt_swatplus_project for {basin_name}\n")
        header_cols = ["name", "wgn", "pcp", "tmp", "slr", "hmd", "wnd",
                       "wnd_dir", "atmo_dep"]
        f.write("".join(c.ljust(col_w) for c in header_cols).rstrip() + "\n")

        for i in range(n_stations):
            sta_name = f"sta{i+1:02d}"
            # Use 'sim' as default wgn -- this tells SWAT+ to use simulated weather
            # generator. If weather-wgn.cli has entries, reference the first one.
            wgn_name = "sim"
            # Try to read wgn name from template's weather-wgn.cli if it exists
            wgn_cli_path = Path(output_dir) / "weather-wgn.cli"
            if wgn_cli_path.exists():
                wgn_lines = wgn_cli_path.read_text().strip().split('\n')
                if len(wgn_lines) >= 2:
                    # First non-header line has the wgn station name
                    wgn_name = wgn_lines[1].split()[0]

            pcp_name = get_or_last(pcp_files, i)
            tmp_name = get_or_last(tmp_files, i)
            slr_name = get_or_last(slr_files, i)
            hmd_name = get_or_last(hmd_files, i)
            wnd_name = get_or_last(wnd_files, i)

            row = [sta_name, wgn_name, pcp_name, tmp_name, slr_name,
                   hmd_name, wnd_name, "null", "null"]
            f.write("".join(c.ljust(col_w) for c in row).rstrip() + "\n")

    logger.info(f"Wrote weather-sta.cli with {n_stations} station entries")
    return n_stations


def write_time_sim(output_dir, start_year, end_year):
    """Write time.sim with the new simulation period.

    SWAT+ time.sim format:
      Line 1: header comment
      Line 2: column names
      Line 3: day_start  yrc_start  day_end  yrc_end  step
    """
    output_path = Path(output_dir) / "time.sim"
    with open(output_path, 'w') as f:
        f.write(f"time.sim: written by adapt_swatplus_project\n")
        f.write("day_start  yrc_start   day_end   yrc_end      step  \n")
        # Start on Jan 1 of start_year, end on Dec 31 of end_year
        # Dec 31 = day 365 (non-leap) or 366 (leap).
        # Use 365 as default -- SWAT+ handles this correctly regardless.
        f.write(f"       1      {start_year}         365      {end_year}         0  \n")

    logger.info(f"Wrote time.sim: {start_year}-01-01 to {end_year}-12-31")


def write_print_prt(output_dir, template_dir, start_year, end_year, warmup_years):
    """Write print.prt preserving template output selections but updating nyskip.

    Reads the template print.prt to preserve which outputs are enabled,
    but updates nyskip (warmup years) and time period bounds.
    """
    template_path = Path(template_dir) / "print.prt"
    output_path = Path(output_dir) / "print.prt"

    if template_path.exists():
        lines = template_path.read_text().split('\n')
    else:
        # Minimal default if template lacks print.prt
        lines = []

    if len(lines) >= 3:
        # Line 0: header
        # Line 1: nyskip    day_start  yrc_start  day_end  yrc_end  interval
        # Line 2: values
        # Rewrite line 2 with updated nyskip
        new_lines = [lines[0]]
        new_lines.append(lines[1])

        # Parse the original values line for the interval
        parts = lines[2].split()
        interval = parts[5] if len(parts) >= 6 else "1"

        new_lines.append(
            f"     {warmup_years}              0          0        0         0"
            f"          {interval}"
        )
        # Keep all remaining lines (output object selections) unchanged
        new_lines.extend(lines[3:])
        content = '\n'.join(new_lines)
    else:
        # Fallback: write a minimal print.prt
        content = (
            f"print.prt: written by adapt_swatplus_project\n"
            f"nyskip      day_start  yrc_start  day_end   yrc_end   interval\n"
            f"     {warmup_years}              0          0        0         0          1\n"
            f"aa_int_cnt\n"
            f"         0\n"
            f"csvout        dbout         cdfout\n"
            f"     n            n              n\n"
            f"soilout       mgtout        hydcon        fdcout\n"
            f"      n            n             n             n\n"
            f"objects                  daily       monthly        yearly         avann\n"
            f"basin_wb                     n             n             y             y\n"
            f"basin_nb                     n             n             n             n\n"
            f"basin_ls                     n             n             n             n\n"
            f"basin_pw                     n             n             n             n\n"
        )

    output_path.write_text(content)
    logger.info(f"Wrote print.prt with nyskip={warmup_years}")


def write_file_cio(output_dir, template_dir, basin_name):
    """Write file.cio preserving template structure but updating the header.

    file.cio is the master index file for SWAT+. We preserve all file
    references from the template (which are valid since we copied them),
    only updating the first-line header comment.
    """
    template_path = Path(template_dir) / "file.cio"
    output_path = Path(output_dir) / "file.cio"

    content = template_path.read_text()
    lines = content.split('\n')

    # Replace only the first line (header comment)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines[0] = (f"file.cio: adapted for {basin_name} by adapt_swatplus_project "
                f"on {timestamp}")

    output_path.write_text('\n'.join(lines))
    logger.info(f"Wrote file.cio with updated header for {basin_name}")


def replace_soils_sol(output_dir, soil_file):
    """Copy the new soils.sol to the output directory."""
    soil_src = Path(soil_file)
    soil_dst = Path(output_dir) / "soils.sol"
    shutil.copy2(soil_src, soil_dst)

    # Verify it has the expected header
    first_line = soil_dst.read_text().split('\n')[0]
    if 'soils.sol' not in first_line.lower() and 'sol' not in first_line.lower():
        logger.warning(f"soils.sol first line may not have standard header: {first_line[:60]}")

    n_lines = sum(1 for _ in soil_dst.open())
    logger.info(f"Replaced soils.sol ({n_lines} lines)")
    return n_lines


def fix_cal_parms_cal(output_dir):
    """Fix cal_parms.cal for pySWATPlus compatibility.

    pySWATPlus reads cal_parms.cal with pandas.read_csv and expects:
    1. Lowercase column headers ('name', not 'NAME')
    2. Single-word units (no spaces: 'kg_N' not 'kg N')
    3. No Windows carriage returns (\\r)

    Without this fix, pySWATPlus raises:
    - ParserError "Expected 5 fields, saw 6" (multi-word units)
    - KeyError 'name' (uppercase headers)

    See diagnostic triplet dt_v003.
    """
    cal_path = Path(output_dir) / "cal_parms.cal"
    if not cal_path.exists():
        logger.warning("cal_parms.cal not found — skipping fix")
        return 0

    content = cal_path.read_text()
    original = content
    n_fixes = 0

    # Fix 1: Remove Windows carriage returns
    if '\r' in content:
        content = content.replace('\r', '')
        n_fixes += 1
        logger.info("  Removed Windows \\r characters")

    # Fix 2: Lowercase header line
    # Match the header pattern: NAME  OBJ_TYP  ABSMIN  ABSMAX  UNITS (any case)
    lines = content.split('\n')
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.upper().startswith('NAME') and 'OBJ_TYP' in stripped.upper():
            if stripped != stripped.lower():
                lines[i] = stripped.lower()
                # Preserve original spacing by lowercasing in-place
                lines[i] = line.lower()
                n_fixes += 1
                logger.info("  Lowercased header: NAME→name, OBJ_TYP→obj_typ, etc.")
            break

    # Fix 3: Replace multi-word units with underscored versions
    unit_replacements = {
        'kg P': 'kg_P', 'kg N': 'kg_N', 'kg C': 'kg_C',
        'kg p': 'kg_p', 'kg n': 'kg_n', 'kg c': 'kg_c',
        'm**3': 'm3', 'julian day': 'julian_day', 'Julian day': 'julian_day',
        'deg c': 'deg_c', 'deg C': 'deg_C', 'Deg C': 'deg_C',
        'mg N': 'mg_N', 'mg P': 'mg_P',
    }
    content_joined = '\n'.join(lines)
    for old, new in unit_replacements.items():
        if old in content_joined:
            content_joined = content_joined.replace(old, new)
            n_fixes += 1
            logger.info(f"  Fixed unit: '{old}' → '{new}'")

    if content_joined != original:
        cal_path.write_text(content_joined)
        logger.info(f"  cal_parms.cal: {n_fixes} fixes applied")
    else:
        logger.info("  cal_parms.cal: no fixes needed")

    return n_fixes


# ---------------------------------------------------------------------------
# Main processing
# ---------------------------------------------------------------------------
def process(args):
    """Adapt the SWAT+ template project for a new basin."""
    template_dir = Path(args.template_dir)
    output_dir = Path(args.output_dir)
    weather_dir = Path(args.weather_dir)

    logger.info(f"Adapting SWAT+ project from template: {template_dir}")
    logger.info(f"  Basin: {args.basin_name}")
    logger.info(f"  Period: {args.start_year}-{args.end_year}")
    logger.info(f"  Weather: {weather_dir}")
    logger.info(f"  Soil: {args.soil_file}")

    # Step 1: Discover new weather files
    logger.info("Step 1: Discovering weather files...")
    files_by_type = discover_weather_files(weather_dir)

    # Step 2: Copy template files (excluding weather data and regenerated files)
    logger.info("Step 2: Copying template structure...")
    n_copied = copy_template_files(template_dir, output_dir)

    # Step 3: Copy new weather data files
    logger.info("Step 3: Copying new weather data files...")
    all_weather_files = copy_weather_files(weather_dir, output_dir, files_by_type)

    # Step 4: Write .cli index files for each weather type
    logger.info("Step 4: Writing weather .cli index files...")
    for wtype, info in WEATHER_TYPES.items():
        filenames = files_by_type.get(wtype, [])
        if filenames:
            write_cli_file(output_dir, info["cli"], info["description"], filenames)
        else:
            # Write empty .cli with no entries -- SWAT+ will use weather generator
            write_cli_file(output_dir, info["cli"], info["description"], [])

    # Step 5: Write weather-sta.cli
    logger.info("Step 5: Writing weather-sta.cli...")
    n_stations = write_weather_sta_cli(output_dir, files_by_type, args.basin_name)

    # Step 6: Replace soils.sol
    logger.info("Step 6: Replacing soils.sol...")
    soil_lines = replace_soils_sol(output_dir, args.soil_file)

    # Step 7: Write time.sim
    logger.info("Step 7: Writing time.sim...")
    write_time_sim(output_dir, args.start_year, args.end_year)

    # Step 8: Write print.prt (preserving template output selections)
    logger.info("Step 8: Writing print.prt...")
    write_print_prt(output_dir, template_dir, args.start_year, args.end_year,
                    args.warmup_years)

    # Step 9: Write file.cio
    logger.info("Step 9: Writing file.cio...")
    write_file_cio(output_dir, template_dir, args.basin_name)

    # Step 10: Fix cal_parms.cal for pySWATPlus compatibility (dt_v003)
    logger.info("Step 10: Fixing cal_parms.cal for pySWATPlus compatibility...")
    n_fixes = fix_cal_parms_cal(output_dir)
    if n_fixes > 0:
        logger.info(f"  Fixed {n_fixes} issues in cal_parms.cal")

    # Count total files in output
    total_files = len(list(output_dir.iterdir()))

    result = {
        "status": "success",
        "project_path": str(output_dir.resolve()),
        "file_count": total_files,
        "basin_name": args.basin_name,
        "period": f"{args.start_year}-{args.end_year}",
        "warmup_years": args.warmup_years,
        "template_files_copied": n_copied,
        "weather_files_copied": len(all_weather_files),
        "weather_stations": n_stations,
        "soil_lines": soil_lines,
        "weather_files_by_type": {
            wtype: len(files) for wtype, files in files_by_type.items()
        }
    }
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")

    args = parse_args()
    validate_inputs(args)

    try:
        result = process(args)
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(2)

    # Collect expected weather files for output validation
    weather_dir = Path(args.weather_dir)
    expected_weather = []
    for ext in WEATHER_EXTENSIONS:
        expected_weather.extend(f.name for f in weather_dir.glob(f"*{ext}"))

    validate_outputs(args.output_dir, expected_weather)

    logger.info(f"Tool completed successfully. Project: {result['project_path']}")
    print(json.dumps(result, indent=2))
    sys.exit(0)
