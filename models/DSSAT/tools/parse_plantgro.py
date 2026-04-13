#!/usr/bin/env python3
"""
parse_plantgro.py — Parse DSSAT PlantGro.OUT for detailed daily growth analysis.

PlantGro.OUT contains daily values for all major growth variables:
  - Phenology: growth stage (GSTD), days after planting (DAP)
  - Canopy: LAI (LAID), leaf weight (LWAD), stem weight (SWAD)
  - Grain/fruit: grain weight (GWAD), grain number (G#AD), grain size (GWGD)
  - Biomass: crop weight (CWAD = total aboveground), root weight (RWAD)
  - Harvest index: HIAD
  - Stress: water stress (WSPD, WSGD), N stress (NSTD)
  - Root: root depth (RDPD), root density by layer (RL1D...RL10D)

This parser handles:
  - Multi-run files (consecutive *RUN blocks)
  - Variable column sets across crops (maize vs rice vs soybean have
    different columns)
  - Missing value detection (-99)
  - Extraction of key phenology events (emergence, anthesis, maturity)
  - Peak LAI and biomass computation

Usage as library:
    from parse_plantgro import parse_plantgro, extract_growth_summary
    records = parse_plantgro("/path/to/PlantGro.OUT")
    summary = extract_growth_summary(records)

Usage from CLI:
    python parse_plantgro.py /path/to/PlantGro.OUT --format json
    python parse_plantgro.py /path/to/PlantGro.OUT --format csv --output growth.csv
    python parse_plantgro.py /path/to/PlantGro.OUT --summary

Author: HydroCraft KI / DSSAT Knowledge Infrastructure
"""

import os
import sys
import json
import csv
import math
import logging
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timedelta

logger = logging.getLogger("parse_plantgro")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")

# =========================================================================
# Key variable definitions for growth analysis
# =========================================================================
# These are the most commonly needed variables from PlantGro.OUT
# Full list depends on crop model, but these are universal across
# CERES (maize, wheat, rice) and CROPGRO (soybean, peanut, etc.)

KEY_VARIABLES = {
    # Timing
    "YEAR": {"desc": "Calendar year", "unit": "year", "type": int},
    "DOY":  {"desc": "Day of year", "unit": "day", "type": int},
    "DAS":  {"desc": "Days after start of simulation", "unit": "days", "type": int},
    "DAP":  {"desc": "Days after planting", "unit": "days", "type": int},
    # Phenology
    "GSTD": {"desc": "Growth stage (Zadoks/BBCH scale for cereals)", "unit": "-", "type": int},
    "L#SD": {"desc": "Leaf number on main stem", "unit": "#", "type": float},
    # Canopy
    "LAID": {"desc": "Leaf area index", "unit": "m2/m2", "type": float},
    "LWAD": {"desc": "Leaf weight (dry)", "unit": "kg/ha", "type": int},
    "SWAD": {"desc": "Stem weight (dry)", "unit": "kg/ha", "type": int},
    "SLAD": {"desc": "Specific leaf area", "unit": "cm2/g", "type": float},
    "CHTD": {"desc": "Canopy height", "unit": "m", "type": float},
    "CWID": {"desc": "Canopy width", "unit": "m", "type": float},
    # Grain/fruit
    "GWAD": {"desc": "Grain weight (dry)", "unit": "kg/ha", "type": int},
    "G#AD": {"desc": "Grain number", "unit": "#/m2", "type": int},
    "GWGD": {"desc": "Individual grain weight", "unit": "mg", "type": float},
    "HIAD": {"desc": "Harvest index (aboveground)", "unit": "fraction", "type": float},
    "HIPD": {"desc": "Harvest index (pod/panicle)", "unit": "fraction", "type": float},
    # Biomass
    "CWAD": {"desc": "Crop weight total aboveground (dry)", "unit": "kg/ha", "type": int},
    "RWAD": {"desc": "Root weight (dry)", "unit": "kg/ha", "type": int},
    "VWAD": {"desc": "Vegetative weight above ground", "unit": "kg/ha", "type": int},
    "PWAD": {"desc": "Pod/panicle weight", "unit": "kg/ha", "type": int},
    # Stress
    "WSPD": {"desc": "Water stress (photosynthesis), 0=max stress 1=no stress",
             "unit": "0-1", "type": float},
    "WSGD": {"desc": "Water stress (growth)", "unit": "0-1", "type": float},
    "NSTD": {"desc": "Nitrogen stress, 0=max stress 1=no stress",
             "unit": "0-1", "type": float},
    "KSTD": {"desc": "Potassium stress", "unit": "0-1", "type": float},
    "EWSD": {"desc": "Excess water stress", "unit": "0-1", "type": float},
    "PST1A": {"desc": "Phosphorus stress 1", "unit": "0-1", "type": float},
    "PST2A": {"desc": "Phosphorus stress 2", "unit": "0-1", "type": float},
    # Root
    "RDPD": {"desc": "Root depth", "unit": "m", "type": float},
    # Composition
    "LN%D": {"desc": "Leaf N concentration", "unit": "%", "type": float},
    "SH%D": {"desc": "Shell/husk percentage", "unit": "%", "type": float},
    # Thermal time
    "DTTD": {"desc": "Daily thermal time", "unit": "C-day", "type": float},
    # Soil N (when in PlantGro.OUT)
    "SNW0C": {"desc": "Soil nitrate in top layer", "unit": "kg/ha", "type": int},
    "SNW1C": {"desc": "Soil nitrate in profile", "unit": "kg/ha", "type": int},
}

# Growth stage interpretations (CERES model Zadoks-like scale)
GROWTH_STAGES_CERES = {
    0: "Pre-emergence",
    1: "Emergence (V0)",
    2: "Vegetative (V1+)",
    3: "End juvenile",
    4: "Panicle initiation / Tassel initiation",
    5: "End ear growth / Heading",
    6: "Anthesis (flowering)",
    7: "Grain fill start",
    8: "Dough stage",
    9: "Maturity",
}


def parse_plantgro(
    filepath: str,
    variables: Optional[List[str]] = None,
    run_number: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Parse a DSSAT PlantGro.OUT file into a list of daily records.

    Parameters
    ----------
    filepath : str
        Path to PlantGro.OUT file.
    variables : list of str, optional
        Only return these variables (plus YEAR, DOY, DAS, DAP always included).
        If None, returns all variables found in the file.
    run_number : int, optional
        Only parse this run number (1-based). If None, parses all runs.

    Returns
    -------
    list of dict
        Each dict is one daily record with parsed values.
        Missing values (-99) are converted to None.
        Each record also has '_RUN' (int) and '_DATE' (YYYY-MM-DD str) keys.

    Raises
    ------
    FileNotFoundError
        If the file does not exist.
    ValueError
        If the file format is not recognized.
    """
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"PlantGro.OUT not found: {filepath}")

    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        raw_lines = f.readlines()

    if not raw_lines:
        raise ValueError(f"PlantGro.OUT is empty: {filepath}")

    records = []
    current_run = 0
    columns = []
    col_positions = []
    in_data_block = False

    for line_no, line in enumerate(raw_lines):
        stripped = line.strip()

        # Detect run header
        if stripped.startswith("*RUN"):
            current_run += 1
            in_data_block = False
            columns = []
            col_positions = []
            continue

        # Skip metadata lines
        if (stripped.startswith("*") or stripped.startswith("MODEL") or
            stripped.startswith("EXPERIMENT") or stripped.startswith("DATA PATH") or
            stripped.startswith("TREATMENT") or stripped.startswith("!") or
            not stripped):
            continue

        # Detect column header line
        if stripped.startswith("@YEAR"):
            # Parse column positions from the raw line (preserving whitespace)
            header_raw = line.rstrip("\n\r")
            # Remove leading @ from first column name
            header_for_parse = header_raw
            if header_for_parse.lstrip().startswith("@"):
                idx = header_for_parse.index("@")
                header_for_parse = header_for_parse[:idx] + " " + header_for_parse[idx+1:]

            # Split into column names
            col_names = header_for_parse.split()
            columns = col_names

            # Build position map for fixed-width parsing
            col_positions = []
            search_start = 0
            for col in col_names:
                pos = header_raw.find(col, search_start)
                if pos < 0:
                    # Handle @YEAR -> YEAR (remove @)
                    pos = header_raw.find("@" + col, search_start)
                    if pos >= 0:
                        pos += 1  # skip the @
                if pos >= 0:
                    col_positions.append((pos, col))
                    search_start = pos + len(col)
                else:
                    col_positions.append((search_start, col))
                    search_start += len(col) + 1

            in_data_block = True
            continue

        # Parse data lines
        if in_data_block and columns:
            if run_number is not None and current_run != run_number:
                continue

            record = {"_RUN": current_run}

            # Use whitespace splitting (more robust for PlantGro.OUT
            # which has variable column widths)
            parts = stripped.split()
            if len(parts) < 4:
                continue  # Too few fields, skip

            for i, col_name in enumerate(columns):
                if i >= len(parts):
                    record[col_name] = None
                    continue

                val_str = parts[i]

                # Parse value
                try:
                    fval = float(val_str)
                    if fval == -99.0 or math.isnan(fval) or math.isinf(fval):
                        record[col_name] = None
                    elif col_name in ("YEAR", "DOY", "DAS", "DAP", "GSTD",
                                       "LWAD", "SWAD", "GWAD", "G#AD", "CWAD",
                                       "RWAD", "VWAD", "PWAD", "P#AD", "CDAD",
                                       "LDAD", "SDAD", "SNW0C", "SNW1C"):
                        record[col_name] = int(round(fval))
                    else:
                        record[col_name] = fval
                except ValueError:
                    record[col_name] = val_str if val_str != "-99" else None

            # Add computed date
            year = record.get("YEAR")
            doy = record.get("DOY")
            if year and doy:
                try:
                    dt = datetime(year, 1, 1) + timedelta(days=doy - 1)
                    record["_DATE"] = dt.strftime("%Y-%m-%d")
                except (ValueError, OverflowError):
                    record["_DATE"] = None

            # Filter variables if requested
            if variables:
                keep_keys = set(variables) | {"YEAR", "DOY", "DAS", "DAP",
                                               "_RUN", "_DATE"}
                record = {k: v for k, v in record.items() if k in keep_keys}

            records.append(record)

    if not records:
        logger.warning("No data records parsed from %s", filepath)

    logger.info("Parsed %d daily records from %d runs in %s",
                len(records), current_run, filepath)

    return records


def extract_growth_summary(
    records: List[Dict[str, Any]],
    run_number: Optional[int] = None,
) -> Dict[str, Any]:
    """Extract key growth metrics from parsed PlantGro.OUT records.

    Parameters
    ----------
    records : list of dict
        Output from parse_plantgro().
    run_number : int, optional
        Summarize this run only. If None, summarizes each run separately.

    Returns
    -------
    dict with keys per run:
        runs : list of dict, each containing:
            run : int
            peak_lai : float (maximum LAI)
            peak_lai_date : str (date of peak LAI)
            peak_lai_dap : int (DAP at peak LAI)
            max_biomass_kgha : int (maximum CWAD)
            final_grain_kgha : int (last GWAD before maturity)
            final_harvest_index : float (last HIAD)
            emergence_dap : int (DAP at GSTD=1)
            anthesis_dap : int (DAP at GSTD=6)
            maturity_dap : int (DAP at GSTD=9)
            emergence_date : str
            anthesis_date : str
            maturity_date : str
            total_stress_days_water : int (days with WSPD < 0.9)
            total_stress_days_nitrogen : int (days with NSTD < 0.9)
            max_root_depth_m : float
            grain_number_per_m2 : int
            final_grain_weight_mg : float
    """
    # Group records by run
    runs_data = {}
    for rec in records:
        run = rec.get("_RUN", 1)
        if run_number is not None and run != run_number:
            continue
        if run not in runs_data:
            runs_data[run] = []
        runs_data[run].append(rec)

    results = {"runs": []}

    for run, recs in sorted(runs_data.items()):
        summary = {"run": run}

        # Peak LAI
        lai_vals = [(r.get("LAID", 0) or 0, r.get("_DATE"), r.get("DAP", 0))
                    for r in recs]
        if lai_vals:
            peak = max(lai_vals, key=lambda x: x[0])
            summary["peak_lai"] = round(peak[0], 2)
            summary["peak_lai_date"] = peak[1]
            summary["peak_lai_dap"] = peak[2]
        else:
            summary["peak_lai"] = None

        # Max biomass
        cwad_vals = [r.get("CWAD", 0) or 0 for r in recs]
        summary["max_biomass_kgha"] = max(cwad_vals) if cwad_vals else None

        # Final grain yield (last non-zero GWAD)
        gwad_vals = [(r.get("GWAD", 0) or 0, r.get("HIAD"), r.get("G#AD"),
                      r.get("GWGD")) for r in recs if (r.get("GWAD") or 0) > 0]
        if gwad_vals:
            last_grain = gwad_vals[-1]
            summary["final_grain_kgha"] = last_grain[0]
            summary["final_harvest_index"] = (round(last_grain[1], 3)
                                               if last_grain[1] else None)
            summary["grain_number_per_m2"] = last_grain[2]
            summary["final_grain_weight_mg"] = last_grain[3]
        else:
            summary["final_grain_kgha"] = 0
            summary["final_harvest_index"] = None
            summary["grain_number_per_m2"] = None
            summary["final_grain_weight_mg"] = None

        # Phenology events from growth stage
        stage_events = {
            1: ("emergence", None, None),
            4: ("panicle_init", None, None),
            6: ("anthesis", None, None),
            9: ("maturity", None, None),
        }
        for rec in recs:
            gstd = rec.get("GSTD")
            if gstd is not None and gstd in stage_events:
                key = stage_events[gstd][0]
                if summary.get(f"{key}_dap") is None:  # First occurrence
                    summary[f"{key}_dap"] = rec.get("DAP")
                    summary[f"{key}_date"] = rec.get("_DATE")

        # Stress analysis
        water_stress_days = sum(
            1 for r in recs
            if r.get("DAP", 0) and r.get("DAP", 0) > 0
            and r.get("WSPD") is not None and r.get("WSPD") < 0.9
        )
        n_stress_days = sum(
            1 for r in recs
            if r.get("DAP", 0) and r.get("DAP", 0) > 0
            and r.get("NSTD") is not None and r.get("NSTD") < 0.9
        )
        summary["total_stress_days_water"] = water_stress_days
        summary["total_stress_days_nitrogen"] = n_stress_days

        # Root depth
        rdpd_vals = [r.get("RDPD", 0) or 0 for r in recs]
        summary["max_root_depth_m"] = round(max(rdpd_vals), 2) if rdpd_vals else None

        # Season duration
        dap_vals = [r.get("DAP", 0) or 0 for r in recs]
        summary["season_length_days"] = max(dap_vals) if dap_vals else None

        # Daily thermal time accumulation
        dttd_vals = [r.get("DTTD", 0) or 0 for r in recs
                     if r.get("DAP", 0) and r.get("DAP", 0) > 0]
        summary["total_thermal_time"] = round(sum(dttd_vals), 1) if dttd_vals else None

        results["runs"].append(summary)

    return results


def get_timeseries(
    records: List[Dict[str, Any]],
    variables: List[str],
    run_number: int = 1,
) -> Dict[str, List]:
    """Extract time series for specific variables from parsed records.

    Parameters
    ----------
    records : list of dict
        Output from parse_plantgro().
    variables : list of str
        Variable names to extract (e.g., ['LAID', 'CWAD', 'GWAD']).
    run_number : int
        Which run to extract (default 1).

    Returns
    -------
    dict with keys:
        dates : list of str (YYYY-MM-DD)
        dap : list of int
        <variable_name> : list of float/int (one per day)
    """
    filtered = [r for r in records if r.get("_RUN") == run_number]

    result = {
        "dates": [],
        "dap": [],
    }
    for var in variables:
        result[var] = []

    for rec in filtered:
        result["dates"].append(rec.get("_DATE"))
        result["dap"].append(rec.get("DAP"))
        for var in variables:
            result[var].append(rec.get(var))

    return result


def records_to_csv(
    records: List[Dict[str, Any]],
    output_path: str,
    variables: Optional[List[str]] = None,
) -> str:
    """Write parsed records to CSV file.

    Parameters
    ----------
    records : list of dict
        Output from parse_plantgro().
    output_path : str
        Path for output CSV file.
    variables : list of str, optional
        Columns to include. If None, includes all.

    Returns
    -------
    str
        Path to written CSV file.
    """
    if not records:
        raise ValueError("No records to write")

    # Determine columns
    if variables:
        columns = ["_RUN", "_DATE", "YEAR", "DOY", "DAS", "DAP"] + \
                  [v for v in variables if v not in
                   ("_RUN", "_DATE", "YEAR", "DOY", "DAS", "DAP")]
    else:
        # Use all columns from first record, ordered
        columns = list(records[0].keys())

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for rec in records:
            writer.writerow(rec)

    logger.info("CSV written: %s (%d records, %d columns)",
                output_path, len(records), len(columns))
    return output_path


# =========================================================================
# CLI
# =========================================================================

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Parse DSSAT PlantGro.OUT for growth analysis"
    )
    parser.add_argument("filepath", help="Path to PlantGro.OUT file")
    parser.add_argument("--format", choices=["json", "csv", "summary"],
                        default="summary", help="Output format")
    parser.add_argument("--output", type=str, default=None,
                        help="Output file path (default: stdout)")
    parser.add_argument("--run", type=int, default=None,
                        help="Parse only this run number")
    parser.add_argument("--variables", type=str, nargs="+", default=None,
                        help="Variables to extract (e.g., LAID CWAD GWAD)")
    parser.add_argument("--summary", action="store_true",
                        help="Print growth summary (peak LAI, yield, phenology)")

    args = parser.parse_args()

    # Parse the file
    records = parse_plantgro(
        args.filepath,
        variables=args.variables,
        run_number=args.run,
    )

    if not records:
        print("No records found in file.")
        sys.exit(1)

    if args.format == "summary" or args.summary:
        summary = extract_growth_summary(records, run_number=args.run)
        output = json.dumps(summary, indent=2, default=str)
        if args.output:
            with open(args.output, "w") as f:
                f.write(output)
            print(f"Summary written to {args.output}")
        else:
            print(output)

    elif args.format == "json":
        output = json.dumps(records, indent=2, default=str)
        if args.output:
            with open(args.output, "w") as f:
                f.write(output)
            print(f"JSON written to {args.output}")
        else:
            print(output)

    elif args.format == "csv":
        out_path = args.output or "plantgro_parsed.csv"
        records_to_csv(records, out_path, variables=args.variables)
        print(f"CSV written to {out_path}")


if __name__ == "__main__":
    main()
