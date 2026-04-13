#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      plot_water_budget
Stage:        s9_postprocessing
Description:  Generate a bar chart of volumetric water budget from listing file.
              Shows inflow (positive) and outflow (negative) by component.

Inputs:
  - LISTING_FILE: MODFLOW 6 listing file (.lst)
  - OUTPUT_PNG: output image path

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import json
import logging
import re
from pathlib import Path

LISTING_FILE = ""
OUTPUT_PNG = ""
TITLE = "MODFLOW 6 Water Budget"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def validate_inputs():
    errors = []
    if not LISTING_FILE or not Path(LISTING_FILE).exists():
        errors.append(f"Listing file not found: {LISTING_FILE}")
    if not OUTPUT_PNG:
        errors.append("OUTPUT_PNG is not set")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)


def parse_budget_from_listing(lst_path):
    """Parse the last volumetric budget summary from listing file."""
    content = Path(lst_path).read_text()

    # Find the last VOLUME BUDGET section
    budget_pattern = r"VOLUME BUDGET FOR ENTIRE MODEL.*?(?=VOLUME BUDGET|$)"
    matches = list(re.finditer(budget_pattern, content, re.DOTALL))

    if not matches:
        logger.warning("No VOLUME BUDGET found in listing file")
        return {}, {}

    last_budget = matches[-1].group()

    # Parse IN and OUT terms
    in_terms = {}
    out_terms = {}

    # Match lines like "    STORAGE-SS =     1234.5678"
    term_pattern = r"\s+(\S[\S\s]*?)\s+=\s+([\d.E+\-]+)"

    in_section = False
    out_section = False

    for line in last_budget.split("\n"):
        if "IN:" in line:
            in_section = True
            out_section = False
            continue
        if "OUT:" in line:
            in_section = False
            out_section = True
            continue
        if "PERCENT DISCREPANCY" in line:
            break

        match = re.match(term_pattern, line)
        if match:
            term_name = match.group(1).strip()
            value = float(match.group(2))
            if in_section:
                in_terms[term_name] = value
            elif out_section:
                out_terms[term_name] = value

    return in_terms, out_terms


def process():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    in_terms, out_terms = parse_budget_from_listing(LISTING_FILE)

    if not in_terms and not out_terms:
        logger.warning("No budget data found. Creating empty plot.")

    # Combine terms
    all_terms = set(list(in_terms.keys()) + list(out_terms.keys()))
    # Remove TOTAL
    all_terms = [t for t in all_terms if "TOTAL" not in t.upper()]

    labels = []
    in_values = []
    out_values = []

    for term in sorted(all_terms):
        labels.append(term)
        in_values.append(in_terms.get(term, 0))
        out_values.append(-out_terms.get(term, 0))  # Negative for outflow

    # Plot
    fig, ax = plt.subplots(figsize=(12, 6))

    x = np.arange(len(labels))
    width = 0.35

    ax.bar(x - width/2, in_values, width, label="Inflow", color="#2196F3", alpha=0.8)
    ax.bar(x + width/2, out_values, width, label="Outflow", color="#F44336", alpha=0.8)

    ax.set_xlabel("Budget Component")
    ax.set_ylabel("Volume (m3)")
    ax.set_title(TITLE, fontsize=14)
    ax.set_xticks(x)
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.legend()
    ax.axhline(y=0, color="black", linewidth=0.5)
    ax.grid(axis="y", alpha=0.3)

    # Save
    output_path = Path(OUTPUT_PNG)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(str(output_path), dpi=150, bbox_inches="tight")
    plt.close(fig)

    logger.info(f"Water budget chart saved: {output_path}")
    return str(output_path)


def validate_outputs(output_path):
    if not Path(output_path).exists():
        logger.error(f"Output not created: {output_path}")
        sys.exit(3)
    logger.info("Output validation passed.")


if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    if len(sys.argv) > 1:
        LISTING_FILE = sys.argv[1]
    if len(sys.argv) > 2:
        OUTPUT_PNG = sys.argv[2]
    validate_inputs()
    try:
        output_path = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        sys.exit(2)
    validate_outputs(output_path)
    print(json.dumps({"output": output_path}))
    sys.exit(0)
