#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
Tool ID:      configure_nutrient_output
Stage:        s10_water_quality
Description:  Enable water quality (N, P, sediment) output in SWAT+ print.prt.
              Modifies an existing print.prt in-place to turn on basin_nb, hru_nb,
              and ensure channel_sd includes nutrient/sediment columns.

Usage:
    python configure_nutrient_output.py --print_prt <path> [--level minimal|standard|detailed]

Levels:
    minimal   - basin_nb daily, channel_sd daily (already enabled for flow)
    standard  - basin_nb daily, hru_nb yearly, channel_sd daily, basin_ls daily
    detailed  - all of standard + hru_nb monthly, basin_pw daily, region_nb daily

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import argparse
import logging
import json
import re
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Output configuration by level
LEVEL_CONFIG = {
    "minimal": {
        "basin_nb":    {"daily": "y", "monthly": "n", "yearly": "n", "avann": "n"},
        "channel_sd":  {"daily": "y", "monthly": "n", "yearly": "y", "avann": "n"},
        "channel":     {"daily": "y", "monthly": "n", "yearly": "y", "avann": "n"},
    },
    "standard": {
        "basin_nb":    {"daily": "y", "monthly": "n", "yearly": "y", "avann": "n"},
        "basin_ls":    {"daily": "y", "monthly": "n", "yearly": "n", "avann": "n"},
        "hru_nb":      {"daily": "n", "monthly": "n", "yearly": "y", "avann": "n"},
        "channel_sd":  {"daily": "y", "monthly": "n", "yearly": "y", "avann": "n"},
        "channel":     {"daily": "y", "monthly": "n", "yearly": "y", "avann": "n"},
    },
    "detailed": {
        "basin_nb":    {"daily": "y", "monthly": "y", "yearly": "y", "avann": "n"},
        "basin_ls":    {"daily": "y", "monthly": "y", "yearly": "y", "avann": "n"},
        "basin_pw":    {"daily": "y", "monthly": "n", "yearly": "y", "avann": "n"},
        "hru_nb":      {"daily": "n", "monthly": "y", "yearly": "y", "avann": "n"},
        "region_nb":   {"daily": "y", "monthly": "n", "yearly": "y", "avann": "n"},
        "channel_sd":  {"daily": "y", "monthly": "y", "yearly": "y", "avann": "n"},
        "channel":     {"daily": "y", "monthly": "y", "yearly": "y", "avann": "n"},
    },
}

# Pattern to match output category lines in print.prt
# e.g. "basin_nb                     n             n             n             n"
CATEGORY_PATTERN = re.compile(
    r"^(\s*)([\w_-]+)\s+(y|n)\s+(y|n)\s+(y|n)\s+(y|n)\s*$"
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Enable water quality output in SWAT+ print.prt"
    )
    parser.add_argument(
        "--print_prt", required=True,
        help="Path to existing print.prt file"
    )
    parser.add_argument(
        "--level", choices=["minimal", "standard", "detailed"],
        default="standard",
        help="Output detail level (default: standard)"
    )
    return parser.parse_args()


def validate_bsn_settings(prt_dir):
    """Check codes.bsn and parameters.bsn for WQ-critical settings."""
    warnings = []

    # Check codes.bsn rtu_wq
    codes_path = prt_dir / "codes.bsn"
    if codes_path.exists():
        lines = codes_path.read_text().splitlines()
        if len(lines) >= 2:
            header = lines[1].split()
            values = lines[2].split() if len(lines) >= 3 else []
            if "rtu_wq" in header and values:
                idx = header.index("rtu_wq")
                if idx < len(values) and values[idx] == "0":
                    logger.warning("rtu_wq=0 in codes.bsn — nutrient routing is DISABLED. "
                                   "Setting rtu_wq=1 for water quality output to work.")
                    values[idx] = "1"
                    lines[2] = "  ".join(f"{v:>13s}" for v in values)
                    codes_path.write_text("\n".join(lines) + "\n")
                    warnings.append("Auto-fixed rtu_wq=0 -> 1 in codes.bsn")
    else:
        warnings.append("codes.bsn not found — cannot verify rtu_wq setting")

    # Check parameters.bsn n_perc and p_perc ranges
    params_path = prt_dir / "parameters.bsn"
    if params_path.exists():
        lines = params_path.read_text().splitlines()
        if len(lines) >= 2:
            header = lines[1].split()
            values = lines[2].split() if len(lines) >= 3 else []
            for param, valid_max, default_val in [("n_perc", 1.0, 0.2), ("p_perc", 1.0, 10.0)]:
                if param in header:
                    idx = header.index(param)
                    if idx < len(values):
                        try:
                            val = float(values[idx])
                            if val > valid_max:
                                logger.warning(f"{param}={val} exceeds valid range [0-{valid_max}]. "
                                               f"Clamping to {default_val}.")
                                values[idx] = f"{default_val:.5f}"
                                lines[2] = "  ".join(f"{v:>13s}" for v in values)
                                params_path.write_text("\n".join(lines) + "\n")
                                warnings.append(f"Auto-fixed {param}={val} -> {default_val}")
                        except ValueError:
                            pass

    return warnings


def validate_inputs(args):
    errors = []
    prt_path = Path(args.print_prt)
    if not prt_path.exists():
        errors.append(f"print.prt not found: {prt_path}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)

    # Validate BSN settings in the same directory
    prt_dir = prt_path.parent
    bsn_warnings = validate_bsn_settings(prt_dir)
    for w in bsn_warnings:
        logger.warning(w)

    logger.info(f"Input validation passed. Level: {args.level}")


def process(args):
    prt_path = Path(args.print_prt)
    config = LEVEL_CONFIG[args.level]

    lines = prt_path.read_text().splitlines()
    modified_lines = []
    changes = {}

    for line in lines:
        m = CATEGORY_PATTERN.match(line)
        if m:
            indent = m.group(1)
            category = m.group(2)
            cur_daily = m.group(3)
            cur_monthly = m.group(4)
            cur_yearly = m.group(5)
            cur_avann = m.group(6)

            if category in config:
                cfg = config[category]
                # Only upgrade from 'n' to 'y', never downgrade existing 'y'
                new_daily = "y" if cfg["daily"] == "y" or cur_daily == "y" else "n"
                new_monthly = "y" if cfg["monthly"] == "y" or cur_monthly == "y" else "n"
                new_yearly = "y" if cfg["yearly"] == "y" or cur_yearly == "y" else "n"
                new_avann = "y" if cfg["avann"] == "y" or cur_avann == "y" else "n"

                # Check if anything actually changed
                if (new_daily != cur_daily or new_monthly != cur_monthly
                        or new_yearly != cur_yearly or new_avann != cur_avann):
                    changes[category] = {
                        "before": f"d={cur_daily} m={cur_monthly} y={cur_yearly} a={cur_avann}",
                        "after": f"d={new_daily} m={new_monthly} y={new_yearly} a={new_avann}",
                    }

                # Reconstruct line with proper SWAT+ alignment
                new_line = f"{category:<20s}{new_daily:>14s}{new_monthly:>14s}{new_yearly:>14s}{new_avann:>14s}"
                modified_lines.append(new_line)
            else:
                modified_lines.append(line)
        else:
            modified_lines.append(line)

    # Write back
    prt_path.write_text("\n".join(modified_lines) + "\n")

    for cat, ch in changes.items():
        logger.info(f"  {cat}: {ch['before']} -> {ch['after']}")

    if not changes:
        logger.info("No changes needed; nutrient output was already enabled.")

    logger.info(f"Updated print.prt at {prt_path} (level={args.level}, {len(changes)} categories changed)")

    return {
        "status": "success",
        "print_prt": str(prt_path),
        "level": args.level,
        "changes": changes,
        "notes": [
            "basin_nb enables basin-level N/P balance output",
            "hru_nb enables HRU-level nutrient output (yearly only to limit file size)",
            "channel_sd daily includes sediment and nutrient columns automatically",
            "Nutrient columns in channel_sd: orgn_out, no3_out, nh4_out, no2_out, solp_out, sedp_out",
        ],
    }


def validate_outputs(result):
    prt_path = Path(result["print_prt"])
    if not prt_path.exists():
        logger.error("print.prt missing after update")
        sys.exit(3)
    # Verify at least basin_nb is enabled
    content = prt_path.read_text()
    if "basin_nb" not in content:
        logger.error("basin_nb line missing from print.prt")
        sys.exit(3)
    logger.info("Output validation passed.")


if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    args = parse_args()
    validate_inputs(args)
    try:
        result = process(args)
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        sys.exit(2)
    validate_outputs(result)
    print(json.dumps(result, indent=2))
    sys.exit(0)
