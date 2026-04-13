#!/usr/bin/env python3
"""Generate a complete DNDC .dnd input configuration file.

Follows the validate-process-validate pattern:
  1. Validate inputs (config dict / JSON, parameter ranges)
  2. Process: assemble .dnd file content in strict line-by-line format
  3. Validate output (.dnd file structure and completeness)

The .dnd file is a plain-text format with strict field ordering. Each line
encodes one parameter, often with tab-separated key-value formatting.

Input is a JSON configuration with the following top-level sections:
  site      - lat, lon, elevation, N_deposition, etc.
  climate   - climate file paths (one per year), CO2 concentration
  soil      - profile file path or inline properties
  crop      - crop type, planting/harvest dates, yield parameters
  management - time blocks with tillage, fertilization, irrigation
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Parameter range validation tables
# ---------------------------------------------------------------------------

PARAM_RANGES = {
    # Site
    "latitude":         (-90.0, 90.0),
    "longitude":        (-180.0, 180.0),
    "elevation":        (-500.0, 9000.0),     # m
    "N_deposition":     (0.0, 100.0),         # kg N/ha/yr
    "CO2_ppm":          (200.0, 1500.0),

    # Soil (if inline)
    "soil_pH":          (3.0, 9.0),
    "soil_SOC_top":     (0.0, 60.0),          # percent
    "soil_clay":        (0.0, 100.0),         # percent
    "soil_bulk_density": (0.5, 2.0),          # g/cm3
    "soil_depth":       (0.1, 10.0),          # m

    # Crop
    "planting_doy":     (1, 366),
    "harvest_doy":      (1, 366),
    "max_yield":        (0.0, 30000.0),       # kgC/ha

    # Management
    "fert_rate":        (0.0, 1000.0),        # kg N/ha
    "irrigation_amount": (0.0, 50.0),         # cm
    "tillage_depth":    (0.0, 1.0),           # m
}

# DNDC crop type codes
CROP_TYPES = {
    "rice":         1,   "wheat_winter":  2,  "wheat_spring":  3,
    "corn":         4,   "soybean":       5,  "barley":        6,
    "potato":       7,   "cotton":        8,  "tobacco":       9,
    "sugarcane":    10,  "alfalfa":       11, "grass":         12,
    "sorghum":      13,  "millet":        14, "oat":           15,
    "rapeseed":     16,  "peanut":        17, "vegetables":    18,
}

# DNDC fertilizer type codes
FERT_TYPES = {
    "urea":             1,  "ammonium_bicarbonate": 2,
    "ammonium_sulfate": 3,  "ammonium_nitrate":     4,
    "anhydrous_ammonia": 5, "nitrate":              6,
    "manure":           7,  "no_fertilizer":        0,
}

# DNDC tillage type codes
TILLAGE_TYPES = {
    "no_till":          0,
    "conventional":     1,
    "reduced":          2,
    "chisel":           3,
}


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

def validate_config(config: dict) -> list[str]:
    """Validate the configuration dictionary.

    Returns list of error/warning strings (empty if all OK).
    """
    errors: list[str] = []

    # Required top-level sections
    for section in ("site", "climate", "soil", "crop"):
        if section not in config:
            errors.append(f"Missing required section: '{section}'")

    if errors:
        return errors  # can't validate further without required sections

    # Site validation
    site = config["site"]
    for param in ("latitude", "longitude"):
        if param in site:
            lo, hi = PARAM_RANGES[param]
            val = float(site[param])
            if not (lo <= val <= hi):
                errors.append(f"site.{param} = {val} outside [{lo}, {hi}]")

    # Climate validation
    climate = config["climate"]
    if "files" not in climate and "file_pattern" not in climate:
        errors.append("climate section needs 'files' list or 'file_pattern'")

    # Soil validation
    soil = config["soil"]
    if "profile_file" not in soil and "clay" not in soil:
        errors.append("soil section needs 'profile_file' or inline properties")

    if "clay" in soil:
        for param in ("soil_pH", "soil_SOC_top", "soil_clay", "soil_bulk_density"):
            short_key = param.replace("soil_", "")
            if short_key in soil:
                lo, hi = PARAM_RANGES[param]
                val = float(soil[short_key])
                if not (lo <= val <= hi):
                    errors.append(f"soil.{short_key} = {val} outside [{lo}, {hi}]")

    # Crop validation
    crop = config["crop"]
    if isinstance(crop, dict):
        crop = [crop]
    for ci, c in enumerate(crop):
        ctype = c.get("type", "").lower()
        if ctype and ctype not in CROP_TYPES:
            errors.append(
                f"crop[{ci}].type = '{ctype}' not in known crop types"
            )
        for param in ("planting_doy", "harvest_doy"):
            if param in c:
                lo, hi = PARAM_RANGES[param]
                val = int(c[param])
                if not (lo <= val <= hi):
                    errors.append(f"crop[{ci}].{param} = {val} outside [{lo}, {hi}]")

    # Management validation (optional)
    mgmt = config.get("management", {})
    time_blocks = mgmt.get("time_blocks", [mgmt]) if mgmt else []
    for bi, block in enumerate(time_blocks):
        ferts = block.get("fertilization", [])
        for fi, fert in enumerate(ferts):
            if "rate" in fert:
                lo, hi = PARAM_RANGES["fert_rate"]
                val = float(fert["rate"])
                if not (lo <= val <= hi):
                    errors.append(
                        f"management.time_blocks[{bi}].fertilization[{fi}]."
                        f"rate = {val} outside [{lo}, {hi}]"
                    )

    return errors


# ---------------------------------------------------------------------------
# DND file generation
# ---------------------------------------------------------------------------

def _format_line(value, label: str = "", width: int = 12) -> str:
    """Format a single .dnd line with value and optional label."""
    if label:
        return f"{str(value):<{width}}\t{label}"
    return str(value)


def generate_dnd_content(config: dict) -> str:
    """Generate the full text content of a .dnd file.

    Parameters
    ----------
    config : dict
        Validated configuration dictionary.

    Returns
    -------
    str
        Complete .dnd file content.
    """
    lines: list[str] = []

    site = config["site"]
    climate = config["climate"]
    soil = config["soil"]
    crop_list = config["crop"]
    if isinstance(crop_list, dict):
        crop_list = [crop_list]
    mgmt = config.get("management", {})

    # ---- Header / Simulation control ----
    sim = config.get("simulation", {})
    start_year = int(sim.get("start_year", climate.get("start_year", 2000)))
    end_year = int(sim.get("end_year", climate.get("end_year", 2000)))
    num_years = end_year - start_year + 1
    dt = sim.get("time_step", 1)  # hours

    lines.append(_format_line(num_years, "Simulation years:"))
    lines.append(_format_line(dt, "Time step (hour):"))
    lines.append(_format_line(sim.get("spinup_years", 0), "Spin-up years:"))

    # ---- Site ----
    lines.append("# Site Parameters")
    lines.append(_format_line(site.get("latitude", 0.0), "Latitude:"))
    lines.append(_format_line(site.get("longitude", 0.0), "Longitude:"))
    lines.append(_format_line(site.get("elevation", 0), "Elevation (m):"))
    lines.append(_format_line(site.get("N_deposition", 5.0),
                              "Atmospheric N deposition (kg N/ha/yr):"))
    lines.append(_format_line(site.get("precipitation_N", 0.0),
                              "N in precipitation (mg N/L):"))

    # ---- Climate ----
    lines.append("# Climate")
    co2 = climate.get("CO2_ppm", 400)
    lines.append(_format_line(co2, "CO2 concentration (ppm):"))
    lines.append(_format_line(climate.get("use_monthly", 0),
                              "Use monthly climate (0=daily):"))

    climate_files = climate.get("files", [])
    if not climate_files and "file_pattern" in climate:
        pattern = climate["file_pattern"]
        for y in range(start_year, end_year + 1):
            climate_files.append(pattern.format(year=y))

    lines.append(_format_line(len(climate_files), "Number of climate files:"))
    for cf in climate_files:
        lines.append(_format_line(cf, "Climate file:"))

    # ---- Soil ----
    lines.append("# Soil")
    if "profile_file" in soil:
        lines.append(_format_line(1, "Use soil profile file (1=yes):"))
        lines.append(_format_line(soil["profile_file"], "Soil profile file:"))
    else:
        lines.append(_format_line(0, "Use soil profile file (1=yes):"))
        texture_id = soil.get("texture_id", 5)
        lines.append(_format_line(texture_id, "Soil texture ID:"))
        lines.append(_format_line(soil.get("pH", 6.5), "Soil pH:"))
        lines.append(_format_line(soil.get("SOC_top", 1.5),
                                  "SOC at surface (%):"))
        lines.append(_format_line(soil.get("clay", 20.0), "Clay fraction (%):"))
        lines.append(_format_line(soil.get("bulk_density", 1.35),
                                  "Bulk density (g/cm3):"))
        lines.append(_format_line(soil.get("depth", 2.0),
                                  "Soil depth (m):"))
        lines.append(_format_line(soil.get("slope", 0.0), "Slope (%):"))
        lines.append(_format_line(
            soil.get("water_retention_layer", 0),
            "Water retention layer (0=none, depth in cm):"
        ))

    # ---- Crop / Farming ----
    lines.append("# Farming")
    num_crops = len(crop_list)
    lines.append(_format_line(num_crops, "Number of cropping systems:"))

    for ci, crop in enumerate(crop_list):
        lines.append(f"# Cropping system {ci + 1}")
        ctype = crop.get("type", "corn").lower()
        crop_code = CROP_TYPES.get(ctype, 4)
        lines.append(_format_line(crop_code, f"Crop type ({ctype}):"))
        lines.append(_format_line(crop.get("planting_doy", 100),
                                  "Planting day (DOY):"))
        lines.append(_format_line(crop.get("harvest_doy", 280),
                                  "Harvest day (DOY):"))
        lines.append(_format_line(crop.get("max_yield", 6000),
                                  "Max yield (kgC/ha):"))
        lines.append(_format_line(crop.get("residue_left", 0.5),
                                  "Residue left on field (fraction):"))
        lines.append(_format_line(crop.get("grain_CN", 40),
                                  "Grain C/N ratio:"))
        lines.append(_format_line(crop.get("leaf_CN", 30),
                                  "Leaf/stem C/N ratio:"))
        lines.append(_format_line(crop.get("root_CN", 45),
                                  "Root C/N ratio:"))
        lines.append(_format_line(crop.get("root_shoot_ratio", 0.18),
                                  "Root/shoot ratio:"))
        lines.append(_format_line(
            int(crop.get("is_legume", 0)),
            "Is legume (0=no, 1=yes):"
        ))
        lines.append(_format_line(
            int(crop.get("is_perennial", 0)),
            "Is perennial (0=no, 1=yes):"
        ))
        lines.append(_format_line(crop.get("water_demand", 300),
                                  "Water demand (mm):"))
        lines.append(_format_line(crop.get("N_demand", 150),
                                  "N demand (kg N/ha):"))
        lines.append(_format_line(crop.get("optimal_temp", 25),
                                  "Optimal temperature (C):"))
        lines.append(_format_line(crop.get("TDD_maturity", 2500),
                                  "TDD for maturity:"))

        # Cover crop / fallow between rotations
        if crop.get("cover_crop"):
            cc = crop["cover_crop"]
            lines.append(_format_line(1, "Cover crop (1=yes):"))
            cc_code = CROP_TYPES.get(cc.get("type", "grass").lower(), 12)
            lines.append(_format_line(cc_code, "Cover crop type:"))
            lines.append(_format_line(cc.get("planting_doy", 285),
                                      "Cover crop planting DOY:"))
            lines.append(_format_line(cc.get("kill_doy", 90),
                                      "Cover crop kill DOY:"))
        else:
            lines.append(_format_line(0, "Cover crop (1=yes):"))

    # ---- Management / Time blocks ----
    lines.append("# Management")
    time_blocks = mgmt.get("time_blocks", [])
    if not time_blocks and mgmt:
        time_blocks = [mgmt]

    lines.append(_format_line(max(len(time_blocks), 1),
                              "Number of time blocks:"))

    for bi, block in enumerate(time_blocks):
        lines.append(f"# Time block {bi + 1}")
        lines.append(_format_line(block.get("start_year", start_year),
                                  "Block start year:"))
        lines.append(_format_line(block.get("end_year", end_year),
                                  "Block end year:"))

        # Tillage
        tillage_events = block.get("tillage", [])
        lines.append(_format_line(len(tillage_events), "Number of tillage events:"))
        for ti, till in enumerate(tillage_events):
            till_type = till.get("type", "conventional").lower()
            till_code = TILLAGE_TYPES.get(till_type, 1)
            lines.append(_format_line(till.get("doy", 90),
                                      f"Tillage {ti+1} DOY:"))
            lines.append(_format_line(till_code,
                                      f"Tillage {ti+1} type:"))
            lines.append(_format_line(till.get("depth", 0.20),
                                      f"Tillage {ti+1} depth (m):"))

        # Fertilization
        fert_events = block.get("fertilization", [])
        lines.append(_format_line(len(fert_events),
                                  "Number of fertilization events:"))
        for fi, fert in enumerate(fert_events):
            ftype = fert.get("type", "urea").lower()
            fcode = FERT_TYPES.get(ftype, 1)
            lines.append(_format_line(fert.get("doy", 100),
                                      f"Fertilization {fi+1} DOY:"))
            lines.append(_format_line(fcode,
                                      f"Fertilization {fi+1} type:"))
            lines.append(_format_line(fert.get("rate", 100),
                                      f"Fertilization {fi+1} rate (kg N/ha):"))
            lines.append(_format_line(fert.get("depth", 0.05),
                                      f"Fertilization {fi+1} depth (m):"))

        # Irrigation
        irr_events = block.get("irrigation", [])
        lines.append(_format_line(len(irr_events),
                                  "Number of irrigation events:"))
        for ii, irr in enumerate(irr_events):
            lines.append(_format_line(irr.get("start_doy", 150),
                                      f"Irrigation {ii+1} start DOY:"))
            lines.append(_format_line(irr.get("end_doy", 250),
                                      f"Irrigation {ii+1} end DOY:"))
            lines.append(_format_line(irr.get("amount", 5.0),
                                      f"Irrigation {ii+1} amount (cm):"))
            lines.append(_format_line(irr.get("interval", 7),
                                      f"Irrigation {ii+1} interval (days):"))

        # Flooding (for rice paddies)
        flooding = block.get("flooding")
        if flooding:
            lines.append(_format_line(1, "Flooding (1=yes):"))
            lines.append(_format_line(flooding.get("start_doy", 120),
                                      "Flooding start DOY:"))
            lines.append(_format_line(flooding.get("end_doy", 240),
                                      "Flooding end DOY:"))
            lines.append(_format_line(flooding.get("water_depth", 5.0),
                                      "Flooding water depth (cm):"))
        else:
            lines.append(_format_line(0, "Flooding (1=yes):"))

        # Manure / organic amendment
        org_events = block.get("organic_amendments", [])
        lines.append(_format_line(len(org_events),
                                  "Number of organic amendments:"))
        for oi, org in enumerate(org_events):
            lines.append(_format_line(org.get("doy", 80),
                                      f"Amendment {oi+1} DOY:"))
            lines.append(_format_line(org.get("rate", 1000),
                                      f"Amendment {oi+1} rate (kgC/ha):"))
            lines.append(_format_line(org.get("CN_ratio", 15),
                                      f"Amendment {oi+1} C/N ratio:"))

        # Grazing
        grazing = block.get("grazing")
        if grazing:
            lines.append(_format_line(1, "Grazing (1=yes):"))
            lines.append(_format_line(grazing.get("start_doy", 120),
                                      "Grazing start DOY:"))
            lines.append(_format_line(grazing.get("end_doy", 280),
                                      "Grazing end DOY:"))
            lines.append(_format_line(grazing.get("intensity", 0.5),
                                      "Grazing intensity (fraction removed):"))
        else:
            lines.append(_format_line(0, "Grazing (1=yes):"))

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Output validation
# ---------------------------------------------------------------------------

def validate_dnd_output(filepath: Path) -> list[str]:
    """Re-read and validate a written .dnd file.

    Returns list of issues.
    """
    issues: list[str] = []

    if not filepath.exists():
        issues.append(f"Output file does not exist: {filepath}")
        return issues

    with open(filepath, "r") as fh:
        content = fh.read()

    lines = [l for l in content.splitlines() if l.strip() and not l.strip().startswith("#")]

    if len(lines) < 10:
        issues.append(f"DND file has only {len(lines)} non-comment lines; seems too short")

    # Check for required sections by looking for key labels
    required_labels = [
        "Latitude:", "Longitude:", "Crop type", "Planting day",
    ]
    for label in required_labels:
        if label not in content:
            issues.append(f"Missing expected label: '{label}'")

    # Check climate file references exist (if absolute paths)
    for line in content.splitlines():
        if "Climate file:" in line:
            parts = line.split("\t")
            if parts:
                fpath = parts[0].strip()
                if os.path.isabs(fpath) and not os.path.exists(fpath):
                    issues.append(f"Referenced climate file not found: {fpath}")

    return issues


# ---------------------------------------------------------------------------
# Main processing
# ---------------------------------------------------------------------------

def process(config: dict, output_file: str) -> str:
    """End-to-end: validate config -> generate .dnd -> validate output.

    Parameters
    ----------
    config : dict
        Configuration dictionary (or loaded from JSON).
    output_file : str
        Output .dnd file path.

    Returns
    -------
    str
        Path to created .dnd file.
    """
    # --- Phase 1: Validate inputs ---
    errors = validate_config(config)
    if errors:
        for e in errors:
            logger.error("Config validation: %s", e)
        raise ValueError(
            f"Configuration has {len(errors)} validation error(s):\n  "
            + "\n  ".join(errors)
        )
    logger.info("Configuration validation passed.")

    # --- Phase 2: Process ---
    dnd_content = generate_dnd_content(config)
    out_path = Path(output_file)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as fh:
        fh.write(dnd_content)
    logger.info("Wrote DND file: %s (%d lines)",
                out_path, dnd_content.count("\n"))

    # --- Phase 3: Validate output ---
    issues = validate_dnd_output(out_path)
    if issues:
        logger.warning("DND output validation issues:")
        for issue in issues:
            logger.warning("  %s", issue)
    else:
        logger.info("DND output validation passed.")

    return str(out_path)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(
        description="Generate a DNDC .dnd input file from JSON configuration."
    )
    parser.add_argument("--config", required=True,
                        help="JSON configuration file path")
    parser.add_argument("--output", required=True,
                        help="Output .dnd file path")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])

    args = parser.parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    try:
        with open(args.config, "r") as fh:
            config = json.load(fh)

        result = process(config=config, output_file=args.output)
        print(f"Created DND file: {result}")
    except Exception:
        logger.exception("Fatal error during DND file generation")
        sys.exit(1)


if __name__ == "__main__":
    main()
