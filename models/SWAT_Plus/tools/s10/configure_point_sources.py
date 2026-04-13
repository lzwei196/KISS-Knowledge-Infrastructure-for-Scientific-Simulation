#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
Tool ID:      configure_point_sources
Stage:        s10_water_quality
Description:  Generate SWAT+ recall.rec entries for point source pollution.
              Converts a CSV of point sources (location, flow, nutrient
              concentrations) into the SWAT+ recall record format.

Usage:
    python configure_point_sources.py --sources_csv <path> --output_dir <path> [--recall_type 1]

sources_csv columns:
    name, lat, lon, flow_m3s, NO3_mg_l, NH4_mg_l, orgN_mg_l, minP_mg_l, orgP_mg_l, sed_mg_l
    (NO3_mg_l through sed_mg_l are optional; defaults from Chinese river averages are used)

recall_type:
    1 = constant (single average value for entire simulation)
    2 = monthly (12 rows per source, for seasonal variation)

Chinese river typical ranges (Liu et al., 2019; MEE China):
    NO3:  2-15 mg/L    NH4: 0.5-5 mg/L    orgN: 1-5 mg/L
    minP: 0.1-1.0 mg/L  orgP: 0.05-0.5 mg/L  sed: 50-500 mg/L

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import sys
import os
import argparse
import logging
import json
import csv
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Default concentrations for Chinese rivers (mg/L)
DEFAULTS = {
    "NO3_mg_l": 8.0,
    "NH4_mg_l": 2.0,
    "orgN_mg_l": 3.0,
    "minP_mg_l": 0.5,
    "orgP_mg_l": 0.2,
    "sed_mg_l": 200.0,
}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate SWAT+ recall.rec for point source pollution"
    )
    parser.add_argument(
        "--sources_csv", required=True,
        help="CSV file with point source data"
    )
    parser.add_argument(
        "--output_dir", required=True,
        help="Output directory for recall files (typically TxtInOut)"
    )
    parser.add_argument(
        "--recall_type", type=int, default=1, choices=[1, 2],
        help="1=constant, 2=monthly (default: 1)"
    )
    return parser.parse_args()


def validate_inputs(args):
    errors = []
    csv_path = Path(args.sources_csv)
    if not csv_path.exists():
        errors.append(f"Sources CSV not found: {csv_path}")
    else:
        # Check header
        with open(csv_path) as f:
            reader = csv.DictReader(f)
            fields = reader.fieldnames or []
            required = ["name", "flow_m3s"]
            for r in required:
                if r not in fields:
                    errors.append(f"Required column '{r}' missing from CSV. Found: {fields}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def concentration_to_load(conc_mg_l, flow_m3s):
    """Convert concentration (mg/L) and flow (m3/s) to daily load (kg/day).

    kg/day = conc_mg_l * flow_m3s * 86400 / 1e6
    """
    return conc_mg_l * flow_m3s * 86400.0 / 1.0e6


def process(args):
    csv_path = Path(args.sources_csv)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    sources = []
    with open(csv_path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            src = {
                "name": row["name"].strip(),
                "flow_m3s": float(row["flow_m3s"]),
            }
            # Optional location
            if "lat" in row and row["lat"]:
                src["lat"] = float(row["lat"])
            if "lon" in row and row["lon"]:
                src["lon"] = float(row["lon"])

            # Nutrient concentrations (use defaults if missing)
            for key, default in DEFAULTS.items():
                if key in row and row[key]:
                    src[key] = float(row[key])
                else:
                    src[key] = default

            sources.append(src)

    logger.info(f"Read {len(sources)} point sources from {csv_path}")

    # Generate recall.rec
    recall_path = output_dir / "recall.rec"
    rec_lines = []
    rec_lines.append("recall.rec: written by SWAT+ knowledge infrastructure (point source module)")

    if args.recall_type == 1:
        # Header for type 1 (constant)
        rec_lines.append(
            f"{'name':<20s}{'rec_typ':>8s}{'flo':>14s}{'sed':>14s}"
            f"{'orgn':>14s}{'sedp':>14s}{'no3':>14s}{'solp':>14s}"
            f"{'chla':>14s}{'nh3':>14s}{'no2':>14s}{'cbod':>14s}"
            f"{'dox':>14s}{'sand':>14s}{'silt':>14s}{'clay':>14s}"
            f"{'sag':>14s}{'lag':>14s}{'grv':>14s}{'tmp':>14s}"
        )
    else:
        rec_lines.append(
            f"{'name':<20s}{'rec_typ':>8s}"
        )

    data_files = []

    for src in sources:
        name = src["name"]
        flow = src["flow_m3s"]

        # Convert concentrations to daily loads (kg/day)
        sed_load = concentration_to_load(src["sed_mg_l"], flow)
        no3_load = concentration_to_load(src["NO3_mg_l"], flow)
        nh4_load = concentration_to_load(src["NH4_mg_l"], flow)
        orgn_load = concentration_to_load(src["orgN_mg_l"], flow)
        minp_load = concentration_to_load(src["minP_mg_l"], flow)
        orgp_load = concentration_to_load(src["orgP_mg_l"], flow)

        if args.recall_type == 1:
            # Constant recall: single line per source
            # SWAT+ recall format: flo(m3/s), sed(t), orgn(kg), sedp(kg),
            #   no3(kg), solp(kg), chla(kg), nh3(kg), no2(kg), cbod(kg),
            #   dox(kg), sand(t), silt(t), clay(t), sag(t), lag(t), grv(t), tmp(C)
            rec_lines.append(
                f"{name:<20s}{'1':>8s}"
                f"{flow:>14.4f}{sed_load:>14.4f}"
                f"{orgn_load:>14.4f}{orgp_load:>14.4f}"
                f"{no3_load:>14.4f}{minp_load:>14.4f}"
                f"{'0.0000':>14s}{nh4_load:>14.4f}{'0.0000':>14s}{'0.0000':>14s}"
                f"{'8.0000':>14s}{'0.0000':>14s}{'0.0000':>14s}{'0.0000':>14s}"
                f"{'0.0000':>14s}{'0.0000':>14s}{'0.0000':>14s}{'20.0000':>14s}"
            )
        else:
            # Monthly recall: separate data file per source
            data_filename = f"{name}.rec"
            data_path = output_dir / data_filename

            # Monthly variation factors (typical for Chinese rivers)
            # Wet season (Jun-Sep) has higher flow and loads
            monthly_factors = [0.6, 0.6, 0.7, 0.8, 0.9, 1.3, 1.5, 1.4, 1.2, 0.9, 0.7, 0.6]

            with open(data_path, "w") as df:
                df.write(f"Monthly recall data for {name}\n")
                df.write(
                    f"{'mo':>4s}{'flo':>14s}{'sed':>14s}"
                    f"{'orgn':>14s}{'sedp':>14s}{'no3':>14s}{'solp':>14s}"
                    f"{'chla':>14s}{'nh3':>14s}{'no2':>14s}{'cbod':>14s}"
                    f"{'dox':>14s}\n"
                )
                for mo_idx in range(12):
                    mf = monthly_factors[mo_idx]
                    df.write(
                        f"{mo_idx + 1:>4d}"
                        f"{flow * mf:>14.4f}{sed_load * mf:>14.4f}"
                        f"{orgn_load * mf:>14.4f}{orgp_load * mf:>14.4f}"
                        f"{no3_load * mf:>14.4f}{minp_load * mf:>14.4f}"
                        f"{'0.0000':>14s}{nh4_load * mf:>14.4f}{'0.0000':>14s}{'0.0000':>14s}"
                        f"{'8.0000':>14s}\n"
                    )

            data_files.append(str(data_path))
            rec_lines.append(f"{name:<20s}{'4':>8s}")  # type 4 = monthly file

            logger.info(f"  Wrote monthly data for {name} to {data_path}")

    # Write recall.rec
    with open(recall_path, "w") as f:
        f.write("\n".join(rec_lines) + "\n")

    logger.info(f"Wrote recall.rec with {len(sources)} sources to {recall_path}")

    # Summary
    total_n = sum(
        concentration_to_load(s["NO3_mg_l"] + s["NH4_mg_l"] + s["orgN_mg_l"], s["flow_m3s"])
        for s in sources
    )
    total_p = sum(
        concentration_to_load(s["minP_mg_l"] + s["orgP_mg_l"], s["flow_m3s"])
        for s in sources
    )

    return {
        "status": "success",
        "recall_rec": str(recall_path),
        "n_sources": len(sources),
        "recall_type": "constant" if args.recall_type == 1 else "monthly",
        "total_n_load_kg_day": round(total_n, 2),
        "total_p_load_kg_day": round(total_p, 2),
        "data_files": data_files,
        "notes": [
            "Add recall.rec to file.cio under the 'recall' category",
            "Connect recall objects to channels via recall.con",
            "Point source loads are additive to diffuse (agricultural) sources",
        ],
    }


def validate_outputs(result):
    rec_path = Path(result["recall_rec"])
    if not rec_path.exists():
        logger.error("recall.rec not created")
        sys.exit(3)
    if result["n_sources"] == 0:
        logger.error("No sources generated")
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
