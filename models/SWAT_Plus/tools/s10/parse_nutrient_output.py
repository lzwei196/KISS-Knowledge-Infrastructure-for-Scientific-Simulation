#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
Tool ID:      parse_nutrient_output
Stage:        s10_water_quality
Description:  Parse SWAT+ nutrient output for sediment and nutrient loads.
              Supports two modes:
              1. --channel_output: Parse channel_day.txt (with QUAL2E blowup detection)
              2. --basin_ls: Parse basin_ls_day.txt (RECOMMENDED for Rev 59.3)

              Rev 59.3 QUAL2E WARNING: Channel routing has numerical instability
              during extreme flows. Use --basin_ls mode for reliable nutrient loads.

Usage:
    # RECOMMENDED: Use basin_ls_day.txt (HRU-level nutrient export)
    python parse_nutrient_output.py --basin_ls <path> \
        --basin_area_km2 <float> --output_csv <path>

    # Alternative: Use channel output (warns if QUAL2E blowup detected)
    python parse_nutrient_output.py --channel_output <path> \
        --basin_area_km2 <float> --output_csv <path> \
        [--channel_id <int>] [--start_date YYYY-MM-DD] [--end_date YYYY-MM-DD]

Nutrient columns parsed (SWAT+ Rev 60.5 channel_sd/channel output):
    sed_out   - Sediment (metric tons/day)
    orgn_out  - Organic nitrogen (kg/day)
    no3_out   - Nitrate nitrogen (kg/day)
    nh4_out   - Ammonium nitrogen (kg/day)
    no2_out   - Nitrite nitrogen (kg/day)
    solp_out  - Dissolved (soluble) phosphorus (kg/day)
    sedp_out  - Sediment-bound phosphorus (kg/day)

basin_ls_day columns (HRU-level, RELIABLE) — species and units taken from the SWAT+
source (`src/output_landscape_module.f90`, type output_nutcarb_gain_loss), NOT from the
column header, whose unit row prints "----" for several columns:
    sedyld    - Sediment yield                          (metric tons/ha/day)
    sedorgn   - Organic N transported in sediment       (kg N/ha/day)
    sedorgp   - Organic P transported in sediment       (kg P/ha/day)
    surqno3   - NO3-N in surface runoff                 (kg N/ha/day)
    lat3no3   - NO3-N in lateral runoff                 (kg N/ha/day)
    surqsolp  - Soluble P in surface runoff             (kg P/ha/day)
    usle      - USLE-predicted erosion                  (metric tons/ha/day)
    sedminp   - Mineral PHOSPHORUS in sediment          (kg P/ha/day)  <-- P, NOT N
                (printed as `sedmin` by Rev 2019.59.3 — see COLUMN ALIASES below)
    tileno3   - NO3-N in tile flow                      (kg N/ha/day)

  TRAP (fixed 2026-08-20): sedminp is mineral PHOSPHORUS (kg P/ha), not nitrogen. Older
  versions of this tool and of SKILL.md summed it into TN, which inflates the nitrogen
  load with a phosphorus flux, and simultaneously DROPPED the two genuine N terms
  lat3no3 and tileno3. Verified against swatplus/src/src/output_landscape_module.f90.

  COLUMN ALIASES (fixed 2026-08-20, round 2): the mineral-P header token is NOT stable
  across SWAT+ revisions. The source declares it `sedminp`
  (output_landscape_module.f90, `type output_losses_header` -> `sedminp`), which is what
  current revisions print; Rev 2019.59.3 — the binary shipped in bin/swatplus_rev59 —
  prints the truncated `sedmin`. Keying on ONE spelling silently drops mineral P from
  TP on the other revision (the column is simply "not in col_map", no error, TP just
  comes out low). This tool therefore resolves the canonical name through LS_COL_ALIASES
  and accepts either spelling; the CSVs it writes always use the canonical `sedminp`.

Computed metrics:
    TN = orgn + no3 + nh4 + no2 (kg/day)
    TP = solp + sedp (kg/day)
    Annual loads: sum of daily loads (kg/yr or t/yr)
    Yield: load / basin_area (kg/ha/yr or t/ha/yr)

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import argparse
import logging
import json
import csv
from pathlib import Path
from datetime import datetime
from collections import defaultdict

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Nutrient columns to extract (SWAT+ output column names)
NUTRIENT_COLS = {
    "sed_out":  {"unit": "tons", "description": "Sediment"},
    "orgn_out": {"unit": "kg",   "description": "Organic N"},
    "no3_out":  {"unit": "kg",   "description": "Nitrate N"},
    "nh4_out":  {"unit": "kg",   "description": "Ammonium N"},
    "no2_out":  {"unit": "kg",   "description": "Nitrite N"},
    "solp_out": {"unit": "kg",   "description": "Dissolved P"},
    "sedp_out": {"unit": "kg",   "description": "Sediment-bound P"},
}

# basin_ls_day.txt header tokens that changed spelling between SWAT+ revisions.
# canonical name -> candidate header tokens, most canonical FIRST.
#   sedminp : declared as `sedminp` in output_landscape_module.f90
#             (`type output_losses_header`) and printed that way by current
#             revisions; Rev 2019.59.3 prints `sedmin`.
# Anything not listed here resolves to itself.
LS_COL_ALIASES = {
    "sedminp": ("sedminp", "sedmin"),
}


def resolve_ls_col(canonical, col_map):
    """Return the header token actually present for `canonical`, or None.

    Lets one parser read both the `sedminp` (current source) and `sedmin`
    (Rev 2019.59.3) spellings of the mineral-P loss column instead of silently
    dropping mineral P from TP on whichever revision it was not keyed on.
    """
    for candidate in LS_COL_ALIASES.get(canonical, (canonical,)):
        if candidate in col_map:
            return candidate
    return None


def parse_args():
    parser = argparse.ArgumentParser(
        description="Parse SWAT+ nutrient/sediment output"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--channel_output",
        help="Path to channel_sd_day.txt or channel_day.txt"
    )
    group.add_argument(
        "--basin_ls",
        help="Path to basin_ls_day.txt (RECOMMENDED for Rev 59.3)"
    )
    parser.add_argument(
        "--basin_area_km2", type=float, required=True,
        help="Basin area in km2 (for yield calculation)"
    )
    parser.add_argument(
        "--output_csv", required=True,
        help="Output CSV path for parsed nutrient time series"
    )
    parser.add_argument(
        "--channel_id", type=int, default=1,
        help="Channel unit ID to extract (default: 1 = outlet)"
    )
    parser.add_argument(
        "--start_date", default=None,
        help="Start date for extraction (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--end_date", default=None,
        help="End date for extraction (YYYY-MM-DD)"
    )
    return parser.parse_args()


def validate_inputs(args):
    errors = []
    input_path = args.channel_output or args.basin_ls
    if not Path(input_path).exists():
        errors.append(f"Input file not found: {input_path}")
    if args.basin_area_km2 <= 0:
        errors.append(f"Invalid basin area: {args.basin_area_km2}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    if args.basin_ls:
        logger.info("Using basin_ls_day.txt (HRU-level nutrient export — RECOMMENDED)")
    else:
        logger.warning("Using channel output. Rev 59.3 QUAL2E may produce unrealistic values.")
    logger.info("Input validation passed.")


def process_basin_ls(args):
    """Parse basin_ls_day.txt for HRU-level nutrient export (RECOMMENDED)."""
    ls_path = Path(args.basin_ls)
    output_csv = Path(args.output_csv)
    basin_area_ha = args.basin_area_km2 * 100.0

    lines = ls_path.read_text().strip().split("\n")

    # Find header
    header_idx = None
    for i, line in enumerate(lines[:5]):
        if "jday" in line.lower():
            header_idx = i
            break
    if header_idx is None:
        header_idx = 1  # typical SWAT+ format

    header = lines[header_idx].split()
    col_map = {name: idx for idx, name in enumerate(header)}

    # Parse data
    daily_records = []
    annual_loads = defaultdict(lambda: defaultdict(float))

    # Species -> unit, straight from output_landscape_module.f90 (see module docstring).
    # sedminp is kg P/ha (mineral phosphorus) — it is NOT a nitrogen term.
    ls_cols = {
        "sedyld": "Sediment yield (t/ha)",
        "sedorgn": "Organic N in sediment (kg N/ha)",
        "sedorgp": "Organic P in sediment (kg P/ha)",
        "surqno3": "NO3-N in surface runoff (kg N/ha)",
        "lat3no3": "NO3-N in lateral runoff (kg N/ha)",
        "surqsolp": "Soluble P in surface runoff (kg P/ha)",
        "usle": "USLE erosion (t/ha)",
        "sedminp": "Mineral P in sediment (kg P/ha)",
        "tileno3": "NO3-N in tile flow (kg N/ha)",
    }
    N_COLS = ["sedorgn", "surqno3", "lat3no3", "tileno3"]
    P_COLS = ["sedorgp", "surqsolp", "sedminp"]

    # canonical name -> header token actually present in THIS file. `sedminp` is
    # spelled `sedmin` by Rev 2019.59.3; resolving here keeps the rest of the
    # function (and every CSV column it writes) on the canonical names.
    present_cols = {}
    for canonical in ls_cols:
        token = resolve_ls_col(canonical, col_map)
        if token is not None:
            present_cols[canonical] = token
    for canonical in P_COLS + N_COLS:
        if canonical not in present_cols:
            logger.warning(f"Column '{canonical}' not found in basin_ls_day.txt "
                           f"(header: {header}) — it contributes 0 to TN/TP")

    for line in lines[header_idx + 1:]:
        parts = line.split()
        if len(parts) < 5:
            continue
        try:
            if parts[col_map.get("unit", 4)] != "1":
                continue
            yr = int(parts[col_map["yr"]])
            mon = int(parts[col_map["mon"]])
            day = int(parts[col_map["day"]])

            record = {"date": f"{yr}-{mon:02d}-{day:02d}", "year": yr, "month": mon}
            for canonical, token in present_cols.items():
                val = float(parts[col_map[token]])
                record[canonical] = val
                annual_loads[yr][canonical] += val

            # TN = sedorgn + surqno3 + lat3no3 + tileno3   (all kg N/ha/day)
            # TP = sedorgp + surqsolp + sedminp            (all kg P/ha/day)
            tn = sum(record.get(c, 0.0) for c in N_COLS)
            tp = sum(record.get(c, 0.0) for c in P_COLS)
            record["TN_kgha"] = tn
            record["TP_kgha"] = tp
            # Absolute basin loads. validate_water_quality.py reads TN_kg / TP_kg /
            # sed_out from the sim CSV — emitting only the per-hectare columns silently
            # produced an all-zero comparison (the S10 step5 -> step6 chain in SKILL.md).
            record["TN_kg"] = tn * basin_area_ha
            record["TP_kg"] = tp * basin_area_ha
            record["sed_out"] = record.get("sedyld", 0.0) * basin_area_ha
            annual_loads[yr]["TN_kgha"] += tn
            annual_loads[yr]["TP_kgha"] += tp
            daily_records.append(record)
        except (ValueError, IndexError, KeyError):
            continue

    if not daily_records:
        raise ValueError("No data found in basin_ls_day.txt")

    logger.info(f"Parsed {len(daily_records)} daily records from basin_ls_day.txt")

    # Write daily CSV
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = (["date", "year", "month"]
                  + [c for c in ls_cols if c in present_cols]
                  + ["TN_kgha", "TP_kgha", "TN_kg", "TP_kg", "sed_out"])
    with open(output_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(daily_records)

    # Annual summary
    annual_summary = []
    for yr in sorted(annual_loads.keys()):
        loads = annual_loads[yr]
        summary = {
            "year": yr,
            "TN_kg_ha_yr": round(loads.get("TN_kgha", 0), 3),
            "TN_kg_yr": round(loads.get("TN_kgha", 0) * basin_area_ha, 1),
            "TP_kg_ha_yr": round(loads.get("TP_kgha", 0), 3),
            "TP_kg_yr": round(loads.get("TP_kgha", 0) * basin_area_ha, 1),
            "sedorgn_kgha_yr": round(loads.get("sedorgn", 0), 3),
            "surqno3_kgha_yr": round(loads.get("surqno3", 0), 3),
            "lat3no3_kgha_yr": round(loads.get("lat3no3", 0), 3),
            "tileno3_kgha_yr": round(loads.get("tileno3", 0), 3),
            "sedminp_kgPha_yr": round(loads.get("sedminp", 0), 3),
        }
        if "sedyld" in loads:
            summary["sediment_t_ha_yr"] = round(loads["sedyld"], 3)
        annual_summary.append(summary)
        logger.info(f"  {yr}: TN={summary['TN_kg_ha_yr']:.2f} kgN/ha/yr "
                     f"(sedorgn={summary['sedorgn_kgha_yr']:.2f}, "
                     f"surqno3={summary['surqno3_kgha_yr']:.2f})")

    annual_csv = output_csv.parent / (output_csv.stem + "_annual.csv")
    if annual_summary:
        with open(annual_csv, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=annual_summary[0].keys())
            writer.writeheader()
            writer.writerows(annual_summary)

    n_years = len(annual_summary)
    avg_tn = sum(a["TN_kg_ha_yr"] for a in annual_summary) / n_years if n_years else 0

    return {
        "status": "success",
        "mode": "basin_ls (HRU-level, RECOMMENDED)",
        "output_csv": str(output_csv),
        "annual_csv": str(annual_csv),
        "n_daily_records": len(daily_records),
        "n_years": n_years,
        "basin_area_km2": args.basin_area_km2,
        "average_annual_yield": {"TN_kg_ha_yr": round(avg_tn, 3)},
        "annual_summary": annual_summary,
        "reference_ranges": {
            "TN_kg_ha_yr": "5-20 (Chinese agricultural watersheds)",
            "sediment_t_ha_yr": "5-50 (USLE for agricultural land)",
        },
    }


def process(args):
    ch_path = Path(args.channel_output)
    output_csv = Path(args.output_csv)
    basin_area_ha = args.basin_area_km2 * 100.0  # km2 -> ha

    start = datetime.strptime(args.start_date, "%Y-%m-%d") if args.start_date else None
    end = datetime.strptime(args.end_date, "%Y-%m-%d") if args.end_date else None

    lines = ch_path.read_text().strip().split("\n")

    # SWAT+ output: line 0 is title (may contain model version info)
    # The header with column names may be line 0 or line 1
    # Detect header line by looking for "jday"
    header_idx = None
    for i, line in enumerate(lines[:5]):
        if "jday" in line.lower():
            header_idx = i
            break

    if header_idx is None:
        # Try first line as header directly
        header_idx = 0

    header = lines[header_idx].split()
    col_map = {name: idx for idx, name in enumerate(header)}

    # Verify required columns
    for req in ["jday", "mon", "day", "yr", "unit"]:
        if req not in col_map:
            raise ValueError(f"Required column '{req}' not found. Available: {header}")

    # Identify which nutrient columns are available
    available_nutrients = {}
    for col_name, meta in NUTRIENT_COLS.items():
        if col_name in col_map:
            available_nutrients[col_name] = meta
        else:
            logger.warning(f"Column '{col_name}' not found in output; skipping")

    if not available_nutrients:
        raise ValueError("No nutrient/sediment columns found in output file. "
                         "Ensure print.prt has basin_nb or channel_sd enabled.")

    logger.info(f"Found {len(available_nutrients)} nutrient/sediment columns: "
                f"{list(available_nutrients.keys())}")

    # Also look for flo_out (discharge) for concentration calculation
    has_flow = "flo_out" in col_map

    # Parse data
    daily_records = []
    annual_loads = defaultdict(lambda: defaultdict(float))  # {year: {col: sum}}
    monthly_loads = defaultdict(lambda: defaultdict(float))  # {(year,month): {col: sum}}

    for line in lines[header_idx + 1:]:
        parts = line.split()
        if len(parts) < len(header):
            continue

        try:
            unit = int(parts[col_map["unit"]])
            if unit != args.channel_id:
                continue

            yr = int(parts[col_map["yr"]])
            mon = int(parts[col_map["mon"]])
            day = int(parts[col_map["day"]])
            date = datetime(yr, mon, day)

            if start and date < start:
                continue
            if end and date > end:
                continue

            record = {"date": date.strftime("%Y-%m-%d"), "year": yr, "month": mon}

            # Extract flow if available
            if has_flow:
                record["flo_out_m3s"] = float(parts[col_map["flo_out"]])

            # Extract nutrient values (with QUAL2E blowup detection)
            has_blowup = False
            for col_name in available_nutrients:
                raw = parts[col_map[col_name]]
                if raw == "NaN":
                    val = 0.0
                    has_blowup = True
                else:
                    val = float(raw)
                    # Detect QUAL2E numerical blowup (>1000 kgN in a single day)
                    if col_name in ("no3_out", "orgn_out", "nh4_out") and val > 1000:
                        has_blowup = True
                        val = 0.0  # Cap blown-up values
                record[col_name] = val
                annual_loads[yr][col_name] += val
                monthly_loads[(yr, mon)][col_name] += val

            # Compute TN and TP
            tn = 0.0
            for ncol in ["orgn_out", "no3_out", "nh4_out", "no2_out"]:
                if ncol in record:
                    tn += record[ncol]
            record["TN_kg"] = tn

            tp = 0.0
            for pcol in ["solp_out", "sedp_out"]:
                if pcol in record:
                    tp += record[pcol]
            record["TP_kg"] = tp

            annual_loads[yr]["TN_kg"] += tn
            annual_loads[yr]["TP_kg"] += tp
            monthly_loads[(yr, mon)]["TN_kg"] += tn
            monthly_loads[(yr, mon)]["TP_kg"] += tp

            daily_records.append(record)

        except (ValueError, IndexError):
            continue

    if not daily_records:
        raise ValueError(f"No data found for channel {args.channel_id}. "
                         f"Check channel ID and date range.")

    logger.info(f"Parsed {len(daily_records)} daily records for channel {args.channel_id}")

    # Write daily CSV
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["date", "year", "month"]
    if has_flow:
        fieldnames.append("flo_out_m3s")
    fieldnames.extend(sorted(available_nutrients.keys()))
    fieldnames.extend(["TN_kg", "TP_kg"])

    with open(output_csv, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for rec in daily_records:
            writer.writerow(rec)

    logger.info(f"Wrote daily nutrient time series to {output_csv}")

    # Compute annual yield summaries
    annual_summary = []
    for yr in sorted(annual_loads.keys()):
        loads = annual_loads[yr]
        summary = {"year": yr}

        if "sed_out" in loads:
            summary["sediment_t_yr"] = round(loads["sed_out"], 2)
            summary["sediment_t_ha_yr"] = round(loads["sed_out"] / basin_area_ha, 4)

        summary["TN_kg_yr"] = round(loads.get("TN_kg", 0), 2)
        summary["TN_kg_ha_yr"] = round(loads.get("TN_kg", 0) / basin_area_ha, 4)
        summary["TP_kg_yr"] = round(loads.get("TP_kg", 0), 2)
        summary["TP_kg_ha_yr"] = round(loads.get("TP_kg", 0) / basin_area_ha, 4)

        # Breakdown
        for col in ["orgn_out", "no3_out", "nh4_out", "no2_out", "solp_out", "sedp_out"]:
            if col in loads:
                summary[f"{col}_kg_yr"] = round(loads[col], 2)

        annual_summary.append(summary)
        logger.info(f"  {yr}: TN={summary['TN_kg_ha_yr']:.2f} kgN/ha/yr, "
                     f"TP={summary['TP_kg_ha_yr']:.2f} kgP/ha/yr"
                     + (f", Sed={summary.get('sediment_t_ha_yr', 0):.2f} t/ha/yr"
                        if "sediment_t_ha_yr" in summary else ""))

    # Overall averages
    n_years = len(annual_summary)
    if n_years > 0:
        avg_tn = sum(a["TN_kg_ha_yr"] for a in annual_summary) / n_years
        avg_tp = sum(a["TP_kg_ha_yr"] for a in annual_summary) / n_years
        avg_sed = (sum(a.get("sediment_t_ha_yr", 0) for a in annual_summary) / n_years
                   if "sediment_t_yr" in annual_summary[0] else None)
    else:
        avg_tn = avg_tp = avg_sed = 0

    # Write annual summary CSV
    annual_csv = output_csv.parent / (output_csv.stem + "_annual.csv")
    if annual_summary:
        with open(annual_csv, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=annual_summary[0].keys())
            writer.writeheader()
            writer.writerows(annual_summary)
        logger.info(f"Wrote annual summary to {annual_csv}")

    return {
        "status": "success",
        "output_csv": str(output_csv),
        "annual_csv": str(annual_csv),
        "n_daily_records": len(daily_records),
        "n_years": n_years,
        "basin_area_km2": args.basin_area_km2,
        "available_columns": list(available_nutrients.keys()),
        "average_annual_yield": {
            "TN_kg_ha_yr": round(avg_tn, 3),
            "TP_kg_ha_yr": round(avg_tp, 3),
            "sediment_t_ha_yr": round(avg_sed, 3) if avg_sed is not None else None,
        },
        "annual_summary": annual_summary,
        "reference_ranges": {
            "TN_kg_ha_yr": "5-20 (Chinese agricultural watersheds)",
            "TP_kg_ha_yr": "0.5-3 (Chinese agricultural watersheds)",
            "sediment_t_ha_yr": "5-50 (USLE for agricultural land)",
        },
    }


def validate_outputs(result):
    csv_path = Path(result["output_csv"])
    if not csv_path.exists():
        logger.error(f"Output CSV not created: {csv_path}")
        sys.exit(3)
    if result["n_daily_records"] == 0:
        logger.error("No records parsed")
        sys.exit(3)

    # Warn about extreme values
    avg = result["average_annual_yield"]
    tn = avg.get("TN_kg_ha_yr", 0)
    tp = avg.get("TP_kg_ha_yr", 0)
    if tn == 0:
        logger.warning("TN yield is zero! Check: (1) fertilizer in management.sch, "
                        "(2) print.prt basin_nb enabled, (3) soil N pools initialized")
    elif tn > 50:
        logger.warning(f"TN yield = {tn:.1f} kgN/ha/yr is very high. "
                        "Check NPERCO in codes.bsn and fertilizer rates.")

    if tp == 0:
        logger.warning("TP yield is zero! Check: (1) P fertilizer applied, "
                        "(2) soil P pools in nutrients.sol")
    elif tp > 10:
        logger.warning(f"TP yield = {tp:.1f} kgP/ha/yr is very high. "
                        "Check PPERCO in codes.bsn and soil erosion rates.")

    logger.info("Output validation passed.")


if __name__ == "__main__":
    logger.info(f"Running tool: {os.path.basename(__file__)}")
    args = parse_args()
    validate_inputs(args)
    try:
        if args.basin_ls:
            result = process_basin_ls(args)
        else:
            result = process(args)
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        sys.exit(2)
    validate_outputs(result)
    print(json.dumps(result, indent=2))
    sys.exit(0)
