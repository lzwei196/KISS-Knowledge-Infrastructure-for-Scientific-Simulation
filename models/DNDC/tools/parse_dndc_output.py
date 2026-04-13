#!/usr/bin/env python3
"""Parse DNDC model output summary files to structured CSV/JSON.

Follows the validate-process-validate pattern:
  1. Validate inputs (output directory exists, summary files present)
  2. Process: parse Summary-* files, extract key variables, build DataFrame
  3. Validate outputs (physical plausibility of parsed values)

DNDC output structure:
  - Result/Inter/          contains Summary-* files
  - Result/Record/Site/    contains per-site detailed output
  - Result/Record/Batch/   contains batch-level summaries

Summary file format (tab-separated):
  value\\tfield_name:\\t

Key variables extracted:
  - Crop yield (kgC/ha)
  - N2O, NO, N2, NH3 emissions (kgN/ha)
  - NO3 leaching (kgN/ha)
  - SOC change (kgC/ha/yr)
  - Water balance components (cm)
  - Methane flux (kgC/ha) for rice systems
"""

import argparse
import csv
import json
import logging
import os
import re
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Physical plausibility bounds for output validation
# ---------------------------------------------------------------------------

PLAUSIBILITY_RANGES = {
    "crop_yield_kgC_ha":    (-100.0, 30000.0),
    "N2O_kgN_ha":           (-1.0, 100.0),
    "NO_kgN_ha":            (-1.0, 50.0),
    "N2_kgN_ha":            (-1.0, 200.0),
    "NH3_kgN_ha":           (-1.0, 200.0),
    "NO3_leach_kgN_ha":     (-1.0, 500.0),
    "SOC_change_kgC_ha_yr": (-5000.0, 5000.0),
    "ET_cm":                (0.0, 300.0),
    "drainage_cm":          (0.0, 500.0),
    "CH4_kgC_ha":           (-500.0, 2000.0),
}

# Mapping from DNDC summary field names to standardized output names
FIELD_MAP = {
    # Crop yield
    "Grain yield":              "crop_yield_kgC_ha",
    "Total grain yield":        "crop_yield_kgC_ha",
    "Crop yield":               "crop_yield_kgC_ha",
    "Grain C":                  "crop_yield_kgC_ha",
    "Total crop C":             "crop_yield_kgC_ha",

    # Gas emissions
    "N2O emission":             "N2O_kgN_ha",
    "Annual N2O":               "N2O_kgN_ha",
    "Total N2O flux":           "N2O_kgN_ha",
    "N2O flux":                 "N2O_kgN_ha",
    "NO emission":              "NO_kgN_ha",
    "Annual NO":                "NO_kgN_ha",
    "NO flux":                  "NO_kgN_ha",
    "N2 emission":              "N2_kgN_ha",
    "Annual N2":                "N2_kgN_ha",
    "N2 flux":                  "N2_kgN_ha",
    "NH3 emission":             "NH3_kgN_ha",
    "Annual NH3":               "NH3_kgN_ha",
    "NH3 flux":                 "NH3_kgN_ha",
    "NH3 volatilization":       "NH3_kgN_ha",

    # Leaching
    "NO3 leaching":             "NO3_leach_kgN_ha",
    "N leaching":               "NO3_leach_kgN_ha",
    "Nitrate leaching":         "NO3_leach_kgN_ha",
    "Annual N leaching":        "NO3_leach_kgN_ha",

    # SOC
    "SOC change":               "SOC_change_kgC_ha_yr",
    "Change in SOC":            "SOC_change_kgC_ha_yr",
    "Annual SOC change":        "SOC_change_kgC_ha_yr",
    "Total SOC":                "SOC_total_kgC_ha",
    "SOC":                      "SOC_total_kgC_ha",
    "Soil organic C":           "SOC_total_kgC_ha",

    # Water balance
    "Evapotranspiration":       "ET_cm",
    "Annual ET":                "ET_cm",
    "Total ET":                 "ET_cm",
    "Drainage":                 "drainage_cm",
    "Annual drainage":          "drainage_cm",
    "Water drainage":           "drainage_cm",
    "Runoff":                   "runoff_cm",
    "Surface runoff":           "runoff_cm",

    # Methane (rice)
    "CH4 emission":             "CH4_kgC_ha",
    "Annual CH4":               "CH4_kgC_ha",
    "CH4 flux":                 "CH4_kgC_ha",
    "Methane emission":         "CH4_kgC_ha",

    # N budget items
    "N uptake":                 "N_uptake_kgN_ha",
    "Crop N uptake":            "N_uptake_kgN_ha",
    "Total N uptake":           "N_uptake_kgN_ha",
    "N fixation":               "N_fix_kgN_ha",
    "Denitrification":          "denitrification_kgN_ha",
    "Nitrification":            "nitrification_kgN_ha",
    "Mineralization":           "mineralization_kgN_ha",
    "N mineralization":         "mineralization_kgN_ha",

    # Carbon budget
    "CO2 emission":             "CO2_kgC_ha",
    "Soil respiration":         "soil_resp_kgC_ha",
    "Heterotrophic respiration": "het_resp_kgC_ha",
}


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------

def validate_inputs(output_dir: str) -> dict:
    """Validate that the DNDC output directory and files exist.

    Returns dict with validated paths.

    Raises
    ------
    FileNotFoundError  if directory or expected files are missing
    """
    out_path = Path(output_dir)
    if not out_path.is_dir():
        raise FileNotFoundError(f"Output directory not found: {output_dir}")

    # Find summary files
    summary_files: list[Path] = []
    search_dirs = [
        out_path / "Result" / "Inter",
        out_path / "Result" / "Record" / "Site",
        out_path / "Result" / "Record" / "Batch",
        out_path / "Result",
        out_path,
    ]

    for sd in search_dirs:
        if sd.is_dir():
            for f in sd.iterdir():
                if f.is_file() and (
                    f.name.lower().startswith("summary")
                    or f.suffix.lower() in (".txt", ".out", ".dat", ".csv")
                ):
                    summary_files.append(f)

    if not summary_files:
        raise FileNotFoundError(
            f"No summary/output files found in {output_dir}. "
            f"Searched: {[str(d) for d in search_dirs if d.is_dir()]}"
        )

    logger.info("Found %d candidate output files", len(summary_files))
    return {
        "output_dir": out_path,
        "summary_files": summary_files,
    }


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_summary_file(filepath: Path) -> dict:
    """Parse a single DNDC summary file.

    DNDC summary format: "value\\tfield_name:\\t"
    Some files may also use space-delimited or other formats.

    Returns dict mapping standardized field names to float values.
    """
    parsed: dict[str, float] = {}
    parsed["_source_file"] = str(filepath)

    # Try to extract year from filename
    year_match = re.search(r"(\d{4})", filepath.name)
    if year_match:
        parsed["year"] = int(year_match.group(1))

    with open(filepath, "r", errors="replace") as fh:
        content = fh.read()

    # Strategy 1: tab-separated "value\tfield_name:\t" format
    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue

        # Pattern: value<tab>field_name:<tab> (standard DNDC)
        tab_match = re.match(r"^([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\t(.+?):\s*$", line)
        if tab_match:
            val_str = tab_match.group(1)
            field = tab_match.group(2).strip()
            try:
                val = float(val_str)
                std_name = _map_field_name(field)
                if std_name:
                    parsed[std_name] = val
                else:
                    parsed[field] = val
            except ValueError:
                pass
            continue

        # Pattern: "field_name: value" or "field_name = value"
        kv_match = re.match(
            r"^(.+?)[\s]*[:=]\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\s*$", line
        )
        if kv_match:
            field = kv_match.group(1).strip()
            val_str = kv_match.group(2)
            try:
                val = float(val_str)
                std_name = _map_field_name(field)
                if std_name:
                    parsed[std_name] = val
                else:
                    parsed[field] = val
            except ValueError:
                pass

    return parsed


def _map_field_name(raw_name: str) -> str | None:
    """Map a raw DNDC field name to a standardized name.

    Returns None if no mapping found.
    """
    # Direct match
    if raw_name in FIELD_MAP:
        return FIELD_MAP[raw_name]

    # Case-insensitive match
    raw_lower = raw_name.lower().strip()
    for key, val in FIELD_MAP.items():
        if key.lower() == raw_lower:
            return val

    # Partial match (for field names with extra units or text)
    for key, val in FIELD_MAP.items():
        if key.lower() in raw_lower:
            return val

    return None


def parse_all_summaries(summary_files: list[Path]) -> list[dict]:
    """Parse all summary files and return list of record dicts."""
    all_records: list[dict] = []

    for sf in summary_files:
        try:
            record = parse_summary_file(sf)
            # Only keep records that have at least one numeric field
            numeric_fields = {k: v for k, v in record.items()
                              if isinstance(v, (int, float)) and k != "year"}
            if numeric_fields:
                all_records.append(record)
                logger.info("Parsed %s: %d fields", sf.name, len(numeric_fields))
            else:
                logger.debug("Skipped %s: no numeric fields found", sf.name)
        except Exception as exc:
            logger.warning("Failed to parse %s: %s", sf, exc)

    return all_records


# ---------------------------------------------------------------------------
# Output assembly
# ---------------------------------------------------------------------------

def records_to_dataframe(records: list[dict]):
    """Convert parsed records to a pandas DataFrame.

    Returns a DataFrame (requires pandas).
    """
    import pandas as pd
    df = pd.DataFrame(records)

    # Sort by year if available
    if "year" in df.columns:
        df = df.sort_values("year").reset_index(drop=True)

    return df


def compute_summary_statistics(records: list[dict]) -> dict:
    """Compute summary statistics across all years.

    Returns dict of {variable: {mean, std, min, max, total}}.
    """
    import numpy as np

    # Collect all numeric fields
    all_keys: set[str] = set()
    for rec in records:
        for k, v in rec.items():
            if isinstance(v, (int, float)) and k not in ("year", "_source_file"):
                all_keys.add(k)

    stats: dict[str, dict] = {}
    for key in sorted(all_keys):
        values = [rec[key] for rec in records
                  if key in rec and isinstance(rec[key], (int, float))]
        if values:
            arr = np.array(values, dtype=np.float64)
            stats[key] = {
                "mean": float(np.mean(arr)),
                "std": float(np.std(arr)),
                "min": float(np.min(arr)),
                "max": float(np.max(arr)),
                "total": float(np.sum(arr)),
                "n_years": len(values),
            }

    return stats


def write_csv(records: list[dict], output_path: Path) -> None:
    """Write parsed records to CSV."""
    if not records:
        logger.warning("No records to write to CSV")
        return

    # Collect all field names
    all_keys: list[str] = []
    seen: set[str] = set()
    # Put year and source first
    for priority_key in ("year", "_source_file"):
        for rec in records:
            if priority_key in rec and priority_key not in seen:
                all_keys.append(priority_key)
                seen.add(priority_key)
    for rec in records:
        for k in rec:
            if k not in seen:
                all_keys.append(k)
                seen.add(k)

    with open(output_path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=all_keys, extrasaction="ignore")
        writer.writeheader()
        for rec in records:
            writer.writerow(rec)

    logger.info("Wrote CSV: %s (%d rows, %d columns)",
                output_path, len(records), len(all_keys))


def write_json(records: list[dict], stats: dict, output_path: Path) -> None:
    """Write parsed records and statistics to JSON."""
    output = {
        "records": records,
        "summary_statistics": stats,
        "n_years": len(records),
    }

    with open(output_path, "w") as fh:
        json.dump(output, fh, indent=2, default=str)

    logger.info("Wrote JSON: %s", output_path)


# ---------------------------------------------------------------------------
# Output validation
# ---------------------------------------------------------------------------

def validate_outputs(records: list[dict]) -> list[str]:
    """Validate parsed output values for physical plausibility.

    Returns list of warning strings.
    """
    warnings: list[str] = []

    if not records:
        warnings.append("No records parsed from output files")
        return warnings

    for ri, rec in enumerate(records):
        year_label = rec.get("year", f"record_{ri}")
        for key, (lo, hi) in PLAUSIBILITY_RANGES.items():
            if key in rec:
                val = rec[key]
                if not isinstance(val, (int, float)):
                    continue
                if not (lo <= val <= hi):
                    warnings.append(
                        f"Year {year_label}: {key} = {val} outside "
                        f"plausible range [{lo}, {hi}]"
                    )

        # Cross-variable checks
        if "N2O_kgN_ha" in rec and "NO_kgN_ha" in rec:
            n2o = rec["N2O_kgN_ha"]
            no = rec["NO_kgN_ha"]
            if isinstance(n2o, (int, float)) and isinstance(no, (int, float)):
                if n2o + no > 200:
                    warnings.append(
                        f"Year {year_label}: N2O + NO = {n2o + no:.1f} kgN/ha "
                        f"seems implausibly high"
                    )

    return warnings


def validate_output_files(csv_path: Path | None,
                          json_path: Path | None) -> list[str]:
    """Check that written output files exist and are non-empty."""
    issues: list[str] = []
    for path in (csv_path, json_path):
        if path is not None:
            if not path.exists():
                issues.append(f"Output file not created: {path}")
            elif path.stat().st_size == 0:
                issues.append(f"Output file is empty: {path}")
    return issues


# ---------------------------------------------------------------------------
# Main processing
# ---------------------------------------------------------------------------

def process(output_dir: str, csv_output: str | None = None,
            json_output: str | None = None) -> dict:
    """End-to-end: validate inputs -> parse -> validate outputs.

    Parameters
    ----------
    output_dir : str
        DNDC output directory containing Result/ subdirectories.
    csv_output : str or None
        Path for CSV output (None to skip).
    json_output : str or None
        Path for JSON output (None to skip).

    Returns
    -------
    dict
        Keys: records, statistics, warnings, output_files
    """
    # --- Phase 1: Validate inputs ---
    params = validate_inputs(output_dir)
    logger.info("Input validation passed. %d summary files found.",
                len(params["summary_files"]))

    # --- Phase 2: Process ---
    records = parse_all_summaries(params["summary_files"])
    logger.info("Parsed %d records from %d files",
                len(records), len(params["summary_files"]))

    stats = compute_summary_statistics(records)

    # Write outputs
    csv_path = Path(csv_output) if csv_output else None
    json_path = Path(json_output) if json_output else None

    if csv_path:
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        write_csv(records, csv_path)

    if json_path:
        json_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(records, stats, json_path)

    # --- Phase 3: Validate outputs ---
    value_warnings = validate_outputs(records)
    file_issues = validate_output_files(csv_path, json_path)
    all_warnings = value_warnings + file_issues

    if all_warnings:
        logger.warning("Completed with %d warnings:", len(all_warnings))
        for w in all_warnings[:30]:
            logger.warning("  %s", w)
    else:
        logger.info("All output validations passed.")

    return {
        "records": records,
        "statistics": stats,
        "warnings": all_warnings,
        "output_files": {
            "csv": str(csv_path) if csv_path else None,
            "json": str(json_path) if json_path else None,
        },
    }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(
        description="Parse DNDC output summary files to structured CSV/JSON."
    )
    parser.add_argument("--output-dir", required=True,
                        help="DNDC output directory (containing Result/)")
    parser.add_argument("--csv", default=None,
                        help="Output CSV file path")
    parser.add_argument("--json", default=None,
                        help="Output JSON file path")
    parser.add_argument("--print-stats", action="store_true",
                        help="Print summary statistics to stdout")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])

    args = parser.parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if not args.csv and not args.json:
        # Default to CSV output alongside the output dir
        args.csv = str(Path(args.output_dir) / "dndc_parsed_output.csv")
        logger.info("No output format specified; defaulting to CSV: %s", args.csv)

    try:
        result = process(
            output_dir=args.output_dir,
            csv_output=args.csv,
            json_output=args.json,
        )

        print(f"Parsed {len(result['records'])} record(s)")

        if args.print_stats and result["statistics"]:
            print("\nSummary Statistics:")
            print("-" * 70)
            for var, stat in sorted(result["statistics"].items()):
                print(f"  {var}:")
                print(f"    mean={stat['mean']:.3f}, std={stat['std']:.3f}, "
                      f"min={stat['min']:.3f}, max={stat['max']:.3f}")

        if result["warnings"]:
            print(f"\nWarnings ({len(result['warnings'])}):")
            for w in result["warnings"][:20]:
                print(f"  {w}")

        for fmt, path in result["output_files"].items():
            if path:
                print(f"Output {fmt}: {path}")

    except Exception:
        logger.exception("Fatal error during output parsing")
        sys.exit(1)


if __name__ == "__main__":
    main()
