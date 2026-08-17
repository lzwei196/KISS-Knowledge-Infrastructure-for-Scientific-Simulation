#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      extract_heads
Stage:        s8_output_extraction
Description:  Read MODFLOW 6 binary head file (.hds) using FloPy.
              Returns head arrays, water table elevation, and dry cell count.
              CRITICAL: Masks HDRY sentinel (1e30) before any analysis.

Inputs:
  - HDS_PATH: path to binary head file (.hds)
  - MODEL_PATH: model workspace for grid info
  - KSTPKPER: (kstp, kper) tuple or "last" or "all"

Outputs:
  - JSON with head statistics, water table, dry cell count

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import json
import logging
import numpy as np
from pathlib import Path

HDS_PATH = "KISSPATH_OUTPUTS/qinghai_lake_1951_2024/modflow6/workspace/gwf.hds"
MODEL_PATH = ""
KSTPKPER = "last"  # "last", "all", or tuple like (0, 0)
HDRY_THRESHOLD = 0.9e30  # Values above this are dry cells

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def _json_safe(o):
    """Recursively convert numpy scalars/arrays to plain Python types.

    flopy's HeadFile/CellBudgetFile .get_kstpkper() returns numpy int32 pairs
    (verified live on a real gwf.hds: (np.int32(4), np.int32(79))), which the
    stdlib json encoder refuses to serialise.  Any consumer that json-dumps this
    tool's result -- including this tool's OWN CLI print -- then dies with
    "TypeError: Object of type int32 is not JSON serializable", and if it was
    dumping to a file it leaves that file TRUNCATED and syntactically invalid.
    See triplet dt_mf6_018.
    """
    import numpy as _np
    if isinstance(o, dict):
        return {str(k): _json_safe(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_json_safe(v) for v in o]
    if isinstance(o, _np.ndarray):
        return _json_safe(o.tolist())
    if isinstance(o, _np.integer):
        return int(o)
    if isinstance(o, _np.floating):
        return float(o)
    if isinstance(o, _np.bool_):
        return bool(o)
    return o


def validate_inputs():
    errors = []
    if not HDS_PATH or not Path(HDS_PATH).exists():
        errors.append(f"Head file not found: {HDS_PATH}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)


def process():
    import flopy.utils.binaryfile as bf

    hds = bf.HeadFile(HDS_PATH)

    # Get available records
    times = hds.get_times()
    kstpkper_list = hds.get_kstpkper()
    logger.info(f"Head file: {len(times)} timesteps, times {times[0]:.1f} to {times[-1]:.1f}")

    # Select timestep
    if KSTPKPER == "last":
        target_kstpkper = kstpkper_list[-1]
    elif KSTPKPER == "all":
        target_kstpkper = None  # Process all
    else:
        target_kstpkper = tuple(KSTPKPER)

    if target_kstpkper is not None:
        heads = hds.get_data(kstpkper=target_kstpkper)
    else:
        heads = hds.get_data(kstpkper=kstpkper_list[-1])

    # Mask HDRY sentinel values
    heads_masked = np.where(heads > HDRY_THRESHOLD, np.nan, heads)

    # Count dry cells
    dry_count = int((heads > HDRY_THRESHOLD).sum())
    total_cells = int(heads.size)
    active_cells = total_cells - int(np.isnan(heads_masked).sum())

    # Water table: head in topmost non-dry layer per column
    nlay, nrow, ncol = heads.shape
    water_table = np.full((nrow, ncol), np.nan)
    for i in range(nrow):
        for j in range(ncol):
            for k in range(nlay):
                if heads[k, i, j] < HDRY_THRESHOLD:
                    water_table[i, j] = heads[k, i, j]
                    break

    wt_valid = water_table[~np.isnan(water_table)]

    result = {
        "shape": list(heads.shape),
        "total_cells": total_cells,
        "dry_cells": dry_count,
        "dry_cell_pct": round(100 * dry_count / total_cells, 2) if total_cells > 0 else 0,
        "head_min": round(float(np.nanmin(heads_masked)), 3) if wt_valid.size > 0 else None,
        "head_max": round(float(np.nanmax(heads_masked)), 3) if wt_valid.size > 0 else None,
        "head_mean": round(float(np.nanmean(heads_masked)), 3) if wt_valid.size > 0 else None,
        "water_table_min": round(float(wt_valid.min()), 3) if wt_valid.size > 0 else None,
        "water_table_max": round(float(wt_valid.max()), 3) if wt_valid.size > 0 else None,
        "water_table_mean": round(float(wt_valid.mean()), 3) if wt_valid.size > 0 else None,
        "timesteps_available": len(times),
        "kstpkper_extracted": ([int(x) for x in target_kstpkper]
                              if target_kstpkper is not None else "last"),
    }

    if dry_count > 0:
        logger.warning(f"Dry cells: {dry_count} ({result['dry_cell_pct']}%). See dt_mf6_002.")

    return _json_safe(result)


def validate_outputs(result):
    # regression guard (dt_mf6_018): the result MUST be JSON-serialisable, or a
    # caller that dumps it to a file leaves that file truncated and unreadable.
    try:
        json.dumps(result)
    except TypeError as e:
        logger.error(f"result dict is not JSON-serialisable: {e}")
        sys.exit(3)
    if result["head_min"] is None:
        logger.error("No valid head values extracted")
        sys.exit(3)
    if result["dry_cell_pct"] > 50:
        logger.warning("More than 50% of cells are dry — model may be severely dewatered")
    logger.info("Output validation passed.")


if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    if len(sys.argv) > 1:
        HDS_PATH = sys.argv[1]
    if len(sys.argv) > 2:
        MODEL_PATH = sys.argv[2]
    validate_inputs()
    try:
        result = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        sys.exit(2)
    validate_outputs(result)
    print(json.dumps(result, indent=2))
    sys.exit(0)
