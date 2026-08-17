#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      build_sto_package
Stage:        s3_layer_properties
Description:  Create MODFLOW 6 STO (Storage) package via FloPy.
              Sets specific storage (Ss), specific yield (Sy), and
              steady-state/transient flags per stress period.

Inputs:
  - SIM_PATH: simulation workspace directory
  - MODEL_NAME: GWF model name
  - SS_VALUES: specific storage per layer (1/m)
  - SY_VALUES: specific yield per layer (dimensionless)
  - STEADY_STATE: list of booleans per stress period

Outputs:
  - STO package attached to GWF model

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import json
import logging
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SIM_PATH = "KISSPATH_OUTPUTS/qinghai_lake_1951_2024/modflow6/workspace"
MODEL_NAME = "gwf"
SS_VALUES = [1e-5, 1e-5]     # Specific storage per layer (1/m)
SY_VALUES = [0.15, 0.10]     # Specific yield per layer
STEADY_STATE = [True, False]        # First period steady, rest transient
ICONVERT = 1                 # 1 = convertible (Sy active while head < cell top),
                             # 0 = confined (Ss only, Sy IGNORED). Scalar or
                             # per-layer list. MUST be 1 for water-table layers
                             # (SKILL.md fact #5); flopy's default is 0.
SAVE_FLOWS = True

# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def validate_inputs():
    errors = []
    if not SIM_PATH:
        errors.append("SIM_PATH is not set")
    import numpy as _np
    for i, ss in enumerate(_np.atleast_1d(_np.asarray(SS_VALUES, dtype=object))):
        if _np.nanmin(_np.asarray(ss, dtype=float)) <= 0:
            errors.append(f"Ss[{i}] must be positive: {ss}")
    for i, sy in enumerate(_np.atleast_1d(_np.asarray(SY_VALUES, dtype=object))):
        _sy = _np.asarray(sy, dtype=float)
        if _np.nanmin(_sy) <= 0 or _np.nanmax(_sy) >= 0.5:
            errors.append(f"Sy[{i}] must be in (0, 0.5): {sy}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def process():
    import flopy

    sim = flopy.mf6.MFSimulation.load(sim_ws=SIM_PATH)
    gwf = sim.get_model(MODEL_NAME)

    # ---------------------------------------------------------------------
    # KDT FIX (2026-07-27, frenchpiezo run) — SILENT ALL-STEADY-STATE BUG.
    # The previous implementation passed ONE dict to `steady_state`:
    #     steady_state={0: ["ss"], 1: ["tr"], ...}
    # flopy's ModflowGwfsto treats `steady_state[iper]` as a TRUTHY flag, so the
    # non-empty list ["tr"] marked EVERY period STEADY-STATE. Verified against
    # flopy 3.10.0: the written gwf.sto contained "STEADY-STATE" in all periods.
    # Consequence: storage was inert in every "transient" run — Sy/Ss could not
    # move the objective at all (documented, measured, in calibration.yaml:
    # sy=0.02 and sy=0.30 gave bit-identical metrics). For a water-table
    # fluctuation problem that removes the ENTIRE storage lag/amplitude physics.
    # flopy's API needs TWO separate dicts (steady_state= and transient=), and
    # iconvert must be 1 or Sy is ignored even in a genuinely transient run.
    # ---------------------------------------------------------------------
    ss_periods = {i: True for i, is_ss in enumerate(STEADY_STATE) if is_ss}
    tr_periods = {i: True for i, is_ss in enumerate(STEADY_STATE) if not is_ss}

    sto = flopy.mf6.ModflowGwfsto(
        gwf,
        iconvert=ICONVERT,
        ss=SS_VALUES,
        sy=SY_VALUES,
        steady_state=ss_periods if ss_periods else None,
        transient=tr_periods if tr_periods else None,
        save_flows=SAVE_FLOWS,
    )

    sim.write_simulation()

    # Post-write ASSERTION: the period blocks actually written must match the
    # requested steady/transient pattern (this bug was silent for 4 prior runs).
    sto_file = Path(SIM_PATH) / f"{MODEL_NAME}.sto"
    written = []
    if sto_file.exists():
        txt = sto_file.read_text().upper()
        import re as _re
        for blk in _re.findall(r"BEGIN PERIOD\s+(\d+)(.*?)END PERIOD", txt, _re.S):
            written.append((int(blk[0]), "STEADY-STATE" in blk[1]))
        # MODFLOW 6 carries the flag forward until it changes, so only the
        # periods where the setting CHANGES appear in the file.
        state, mismatches = None, []
        wdict = dict(written)
        for i, is_ss in enumerate(STEADY_STATE):
            if (i + 1) in wdict:
                state = wdict[i + 1]
            if state is None or state != bool(is_ss):
                mismatches.append(i)
        if mismatches:
            raise RuntimeError(
                f"STO period flags written to {sto_file.name} do not match "
                f"STEADY_STATE for periods {mismatches[:10]} "
                f"(written blocks: {written[:10]}). Refusing to continue — a "
                f"silently-steady 'transient' run makes Ss/Sy inert.")
    logger.info(f"STO package created: Ss={SS_VALUES}, Sy={SY_VALUES}, "
                f"ICONVERT={ICONVERT}, "
                f"{len(ss_periods)} steady / {len(tr_periods)} transient periods")

    return {
        "ss_per_layer": SS_VALUES if not hasattr(SS_VALUES, "tolist") else "array",
        "sy_per_layer": SY_VALUES if not hasattr(SY_VALUES, "tolist") else "array",
        "iconvert": ICONVERT if not hasattr(ICONVERT, "tolist") else "array",
        "steady_state_periods": [i for i, s in enumerate(STEADY_STATE) if s],
        "transient_periods_count": len(tr_periods),
        "written_period_blocks": written[:10],
    }


def validate_outputs(result):
    logger.info("Output validation passed.")


if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    if len(sys.argv) > 1:
        SIM_PATH = sys.argv[1]
    validate_inputs()
    try:
        result = process()
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        sys.exit(2)
    validate_outputs(result)
    print(json.dumps(result, indent=2))
    sys.exit(0)
