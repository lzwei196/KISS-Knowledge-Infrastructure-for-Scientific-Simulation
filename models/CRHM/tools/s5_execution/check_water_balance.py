#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
============================================
Tool ID:      check_water_balance
Stage:        s5_execution
Description:  Compute a CLOSED CRHM basin water balance entirely from model
              output, summing ALL storage compartments for dS.

WHY THIS TOOL EXISTS
--------------------
CRHM water-balance checks historically FAILed (residual ~5-10%) even on runs
with excellent NSE/r/PBIAS, because the dS (storage change) term was hand-rolled
from an INCOMPLETE compartment list. Two recurring mistakes:

  1. Storage compartments omitted from the .prj Display_Variable. The Soil
     module exposes FIVE storage states as declstatvar -- SWE, soil_moist,
     soil_rechr, gw, AND **Sd (depression storage)**. Sd is routinely forgotten.
     The interception module holds canopy load **SI_Lo** (kg/m^2 == mm SWE).
     Omitting Sd/SI_Lo leaves their dS uncounted, inflating the residual.

  2. P estimated EXTERNALLY (raw forcing x precip_scale) instead of read from
     the model's own `hru_p` (obs module: "total precip includes snow catch
     adjustment"). Any mismatch between the external scale and the model's
     internal multipliers/snow-catch shows up as a fake residual.

  3. The Netroute routing reservoirs (hruDelay/ssrDelay/runDelay/gwDelay,
     ClassClark lag-storage) hold water in transit. Their TERMINAL storage is
     NOT a declvar -- it is only emitted at finish() to crhmRun.log as the
     "<name>Delay_in_storage ... (mm) (mm*km^2) (mm*basin)" lines. This tool
     parses those lines so routing storage is included in dS. (In practice it
     is only a few mm, but it removes the last unexplained term.)

CLOSURE EQUATION (basin-mean, mm over the run):
    residual = P - ET - Q - dS_storage - dS_routing
where dS_X = area_weighted(last) - area_weighted(first).

REQUIRED .prj Display_Variable for a clean close (per-HRU lists, e.g. "1 2 3"):
    obs       hru_p          <- model net precip (P)
    evap      hru_actet      <- ET
    Netroute  basinflow      <- Q (m^3/int)
    pbsm      SWE            soil storages ...
    Soil      soil_moist
    Soil      soil_rechr
    Soil      gw
    Soil      Sd             <- DEPRESSION STORAGE (commonly forgotten)
    intcp     SI_Lo          <- canopy load (kg/m^2 ~ mm); optional, small

Inputs:
  --csv         parsed crhm_results.csv (from parse_crhm_output.py)
  --hru_area    comma-separated HRU areas in km^2 (e.g. 110,221,111)
  --log         crhmRun.log (optional; adds terminal Netroute routing storage)
  --P_mm        fallback total precip (mm) if hru_p is absent from the csv
  --tol_pct     pass/fail tolerance on |residual|/P (default 5.0)

Exit codes:
  0 -- success (water balance computed; PASS/FAIL reported in JSON)
  1 -- input error
  2 -- processing error
"""

import sys
import os
import csv
import json
import argparse
import logging
import re
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Canonical CRHM storage state compartments (basin water balance).
# name -> CRHM variable base name.  All are per-HRU (mm), except SI_Lo (kg/m^2 ~ mm).
STORAGE_COMPARTMENTS = ["SWE", "soil_moist", "soil_rechr", "gw", "Sd", "SI_Lo"]
ROUTING_KEYS = ["hruDelay_in_storage", "ssrDelay_in_storage",
                "runDelay_in_storage", "gwDelay_in_storage"]


def parse_args():
    p = argparse.ArgumentParser(description="CRHM closed water balance")
    p.add_argument("--csv", required=True, help="parsed crhm_results.csv")
    p.add_argument("--hru_area", required=True,
                   help="comma-separated HRU areas in km^2, e.g. 110,221,111")
    p.add_argument("--log", default="", help="crhmRun.log (routing storage)")
    p.add_argument("--P_mm", type=float, default=None,
                   help="fallback total precip mm if hru_p absent from csv")
    p.add_argument("--tol_pct", type=float, default=5.0)
    return p.parse_args()


def _cols_for(header, base):
    """Return csv column names matching '<base>(i)' in HRU order."""
    pat = re.compile(rf"^{re.escape(base)}\((\d+)\)$")
    found = {}
    for c in header:
        m = pat.match(c)
        if m:
            found[int(m.group(1))] = c
    return [found[k] for k in sorted(found)]


def area_weighted_series(rows, cols, area):
    """basin-mean value per timestep = sum(val_hru * area_hru) / sum(area)."""
    A = sum(area)
    out = []
    for r in rows:
        s = 0.0
        for j, c in enumerate(cols):
            s += float(r[c]) * area[j]
        out.append(s / A)
    return out


def routing_storage_from_log(log_path):
    """Sum terminal Netroute *_in_storage across HRUs, using the (mm*basin) column.
    Line form:
      HRU N: 'Netroute (Netroute)' gwDelay_in_storage  (mm) (mm*km^2) (mm*basin): a b c
    The last numeric token (c) is already basin-mean mm.

    NOTE: crhmRun.log is APPENDED across every CRHM invocation (calibration
    loops write many finishReport blocks into one file). We must use only the
    FINAL block: keep the LAST value seen for each (HRU, key) pair, then sum.
    Summing all lines would multi-count and grossly overstate routing storage."""
    if not log_path or not Path(log_path).exists():
        return None
    hru_re = re.compile(r"HRU\s+(\d+):")
    last = {}  # (hru, key) -> basin-mm value (last occurrence wins)
    with open(log_path, "r", errors="replace") as f:
        for line in f:
            if "_in_storage" not in line:
                continue
            key = next((k for k in ROUTING_KEYS if k in line), None)
            if key is None:
                continue
            m = hru_re.search(line)
            hru = m.group(1) if m else "?"
            tail = line.rsplit(":", 1)[-1].split()
            if len(tail) >= 3:
                try:
                    last[(hru, key)] = float(tail[-1])  # (mm*basin) column
                except ValueError:
                    pass
    if not last:
        return None
    return sum(last.values())


def main():
    args = parse_args()
    if not Path(args.csv).exists():
        logger.error(f"csv not found: {args.csv}")
        sys.exit(1)
    try:
        area = [float(x) for x in args.hru_area.split(",")]
    except ValueError:
        logger.error("--hru_area must be comma-separated numbers")
        sys.exit(1)

    with open(args.csv) as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        header = reader.fieldnames
    if not rows:
        logger.error("csv has no data rows")
        sys.exit(2)

    n_hru = len(area)
    Am2 = sum(area) * 1e6  # km^2 -> m^2

    # ---- P (prefer model's own hru_p) ----
    p_cols = _cols_for(header, "hru_p")
    if not p_cols:  # fall back to hru_rain + hru_snow
        rain = _cols_for(header, "hru_rain")
        snow = _cols_for(header, "hru_snow")
        if rain and snow:
            P_mm = sum(area_weighted_series(rows, rain, area)) + \
                   sum(area_weighted_series(rows, snow, area))
            p_source = "hru_rain+hru_snow"
        elif args.P_mm is not None:
            P_mm = args.P_mm
            p_source = "external --P_mm (WARNING: not model net precip)"
        else:
            logger.error("No hru_p / hru_rain+hru_snow in csv and no --P_mm given")
            sys.exit(2)
    else:
        P_mm = sum(area_weighted_series(rows, p_cols, area))
        p_source = "hru_p (model net precip, incl snow-catch)"

    # ---- ET ----
    et_cols = _cols_for(header, "hru_actet")
    if not et_cols:
        logger.error("hru_actet not in csv -- add 'evap hru_actet' to Display_Variable")
        sys.exit(2)
    ET_mm = sum(area_weighted_series(rows, et_cols, area))

    # ---- Q (basinflow m^3/int -> basin mm) ----
    bf_cols = _cols_for(header, "basinflow")
    if not bf_cols:
        logger.error("basinflow not in csv -- add 'Netroute basinflow 1' to Display_Variable")
        sys.exit(2)
    Q_m3 = sum(float(r[bf_cols[0]]) for r in rows)  # BASIN dim, single column
    Q_mm = Q_m3 / Am2 * 1000.0

    # ---- dS over all storage compartments present ----
    dS = {}
    missing = []
    for comp in STORAGE_COMPARTMENTS:
        cols = _cols_for(header, comp)
        if not cols:
            missing.append(comp)
            continue
        series = area_weighted_series(rows, cols, area)
        dS[comp] = series[-1] - series[0]
    dS_storage = sum(dS.values())

    # ---- routing reservoir terminal storage ----
    dS_routing = routing_storage_from_log(args.log)
    routing_term = dS_routing if dS_routing is not None else 0.0

    residual = P_mm - ET_mm - Q_mm - dS_storage - routing_term
    resid_pct = abs(residual) / P_mm * 100.0 if P_mm else float("nan")
    status = "PASS" if resid_pct <= args.tol_pct else "FAIL"

    result = {
        "status": status,
        "P_mm": round(P_mm, 1),
        "P_source": p_source,
        "ET_mm": round(ET_mm, 1),
        "Q_mm": round(Q_mm, 1),
        "dS_storage_mm": round(dS_storage, 1),
        "dS_by_compartment_mm": {k: round(v, 1) for k, v in dS.items()},
        "dS_routing_mm": (round(dS_routing, 1) if dS_routing is not None else None),
        "residual_mm": round(residual, 1),
        "residual_pct": round(resid_pct, 2),
        "tol_pct": args.tol_pct,
        "n_hru": n_hru,
        "missing_storage_compartments": missing,
        "runoff_coef": round(Q_mm / P_mm, 3) if P_mm else None,
    }
    if missing:
        logger.warning("MISSING storage compartments from output (uncounted in dS): "
                       + ", ".join(missing)
                       + " -- add to .prj Display_Variable: "
                       + "; ".join(f"Soil {m}" if m in ("Sd",) else
                                   ("intcp SI_Lo" if m == "SI_Lo" else m) for m in missing))
    print(json.dumps(result, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    main()
