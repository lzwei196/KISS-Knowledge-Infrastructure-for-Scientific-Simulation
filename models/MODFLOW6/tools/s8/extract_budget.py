#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      extract_budget
Stage:        s8_output_extraction
Description:  Read MODFLOW 6 cell budget file (.cbc) using FloPy.
              Extracts flow terms by package and computes budget balance.

              SIGN CONVENTION:
              - Positive = inflow (water entering aquifer)
              - Negative = outflow (water leaving aquifer)
              - DRN flux is negative (outflow to drains)
              - When coupling to routing: baseflow = -drn_flux (negate!)

Inputs:
  - CBC_PATH: path to cell budget file (.cbc)
  - KSTPKPER: (kstp, kper) tuple or "last"
  - TEXT: budget term to extract (e.g., "RCH", "DRN", "WEL") or "all"

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import json
import logging
import numpy as np
from pathlib import Path

CBC_PATH = ""
KSTPKPER = "last"
TEXT = "all"  # "all" or specific: "RCH", "DRN", "WEL", "RIV", "CHD", "STO-SS", "STO-SY"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def validate_inputs():
    errors = []
    if not CBC_PATH or not Path(CBC_PATH).exists():
        errors.append(f"Budget file not found: {CBC_PATH}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)


def process():
    import flopy.utils.binaryfile as bf

    cbb = bf.CellBudgetFile(CBC_PATH)

    # Get available records
    records = cbb.get_unique_record_names()
    record_names = [r.strip().decode() if isinstance(r, bytes) else r.strip() for r in records]
    logger.info(f"Budget terms: {record_names}")

    kstpkper_list = cbb.get_kstpkper()
    if KSTPKPER == "last":
        target = kstpkper_list[-1]
    else:
        target = tuple(KSTPKPER)

    # Extract budget terms
    budget_summary = {}
    total_in = 0.0
    total_out = 0.0

    terms_to_extract = record_names if TEXT == "all" else [TEXT]

    for term_name in terms_to_extract:
        try:
            data = cbb.get_data(kstpkper=target, text=term_name)
            if data:
                # Sum all flows for this term
                flux_sum = 0.0
                for d in data:
                    if isinstance(d, np.recarray):
                        flux_sum += d["q"].sum()
                    else:
                        flux_sum += float(np.sum(d))

                budget_summary[term_name] = round(float(flux_sum), 4)

                if flux_sum > 0:
                    total_in += flux_sum
                else:
                    total_out += abs(flux_sum)
        except Exception as e:
            logger.warning(f"Could not extract {term_name}: {e}")

    # Compute discrepancy
    if total_in + total_out > 0:
        pct_disc = 100 * (total_in - total_out) / ((total_in + total_out) / 2)
    else:
        pct_disc = 0.0

    result = {
        "kstpkper": list(target),
        "budget_terms": budget_summary,
        "total_in_m3day": round(total_in, 4),
        "total_out_m3day": round(total_out, 4),
        "percent_discrepancy": round(pct_disc, 6),
        "available_terms": record_names,
    }

    if abs(pct_disc) > 0.1:
        logger.warning(
            f"Budget discrepancy {pct_disc:.4f}% exceeds 0.1%. "
            f"See triplet dt_mf6_003."
        )

    return result


def validate_outputs(result):
    if not result["budget_terms"]:
        logger.error("No budget terms extracted")
        sys.exit(3)
    logger.info("Output validation passed.")


if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    if len(sys.argv) > 1:
        CBC_PATH = sys.argv[1]
    validate_inputs()
    try:
        result = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        sys.exit(2)
    validate_outputs(result)
    print(json.dumps(result, indent=2))
    sys.exit(0)
