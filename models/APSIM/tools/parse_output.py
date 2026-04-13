#!/usr/bin/env python3
"""
parse_output.py — Extract APSIM simulation results from SQLite .db to CSV.

APSIM stores output in SQLite databases. This tool extracts data from
Report tables, handles unit conversions, and produces analysis-ready CSV files.

CRITICAL: APSIM biomass outputs (Wt) are in g/m², NOT kg/ha.
  To convert to kg/ha: multiply by 10.
  To convert to t/ha: divide by 100.

Output columns typically include:
  - SimulationID, CheckpointID (internal)
  - Clock.Today (date)
  - Crop variables (Grain.Wt, AboveGround.Wt, Leaf.LAI, etc.)
  - Soil variables (SW, ESW, Drainage, Runoff, etc.)
  - Weather variables (Rain, MaxT, MinT, Radn, etc.)

Usage:
  python parse_output.py --db simulation.db --output results.csv

  python parse_output.py --db simulation.db --output results.csv \\
      --table Report --convert-yield --simulation "Dalby*"

  python parse_output.py --db simulation.db --output results.csv \\
      --list-tables
"""

import argparse
import csv
import json
import os
import sqlite3
import sys
from datetime import datetime


def validate_inputs(args):
    """Validate input arguments."""
    errors = []

    if not os.path.isfile(args.db):
        errors.append(f"Database file not found: {args.db}")
    else:
        # Check it's a valid SQLite file
        try:
            conn = sqlite3.connect(args.db)
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            conn.close()
            if not tables:
                errors.append(f"Database {args.db} contains no tables")
        except sqlite3.Error as e:
            errors.append(f"Cannot open SQLite database {args.db}: {e}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)


def list_tables(db_path):
    """List all tables and their row counts in the database."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [row[0] for row in cursor.fetchall()]

    table_info = []
    for table in tables:
        try:
            cursor.execute(f'SELECT COUNT(*) FROM "{table}"')
            count = cursor.fetchone()[0]
            cursor.execute(f'PRAGMA table_info("{table}")')
            columns = [row[1] for row in cursor.fetchall()]
            table_info.append({
                "name": table,
                "rows": count,
                "columns": columns,
            })
        except sqlite3.Error:
            table_info.append({"name": table, "rows": -1, "columns": []})

    conn.close()
    return table_info


def get_units(db_path):
    """Extract unit information from the _Units table if it exists."""
    units = {}
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='_Units'")
        if cursor.fetchone():
            cursor.execute("SELECT TableName, ColumnHeading, Units FROM _Units")
            for row in cursor.fetchall():
                key = f"{row[0]}.{row[1]}"
                units[key] = row[2]
        conn.close()
    except sqlite3.Error:
        pass
    return units


def process(args):
    """Extract data from SQLite database."""
    if args.list_tables:
        tables = list_tables(args.db)
        return {"status": "ok", "tables": tables, "mode": "list_tables"}

    conn = sqlite3.connect(args.db)
    cursor = conn.cursor()

    # Get available tables (excluding internal ones)
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    all_tables = [row[0] for row in cursor.fetchall()]

    # Determine which table to extract
    table = args.table
    if table is None:
        # Auto-select: prefer "Report", then first non-internal table
        internal = {"_Simulations", "_Checkpoints", "_Units", "_Messages"}
        report_tables = [t for t in all_tables if t not in internal]
        if "Report" in report_tables:
            table = "Report"
        elif report_tables:
            table = report_tables[0]
        else:
            conn.close()
            return {"status": "error", "errors": ["No data tables found in database"]}

    if table not in all_tables:
        conn.close()
        return {"status": "error", "errors": [f"Table '{table}' not found. Available: {all_tables}"]}

    # Build query
    query = f'SELECT * FROM "{table}"'
    conditions = []

    if args.simulation:
        # Join with _Simulations to filter by name
        cursor.execute("SELECT ID, Name FROM _Simulations")
        sim_rows = cursor.fetchall()
        matching_ids = []
        for sid, sname in sim_rows:
            if args.simulation.endswith("*"):
                if sname.startswith(args.simulation[:-1]):
                    matching_ids.append(str(sid))
            elif sname == args.simulation:
                matching_ids.append(str(sid))
        if matching_ids:
            conditions.append(f"SimulationID IN ({','.join(matching_ids)})")
        else:
            conn.close()
            return {"status": "error",
                    "errors": [f"No simulations matching '{args.simulation}' found"]}

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    # Execute query
    cursor.execute(query)
    columns = [description[0] for description in cursor.description]
    rows = cursor.fetchall()

    # Get units
    units = get_units(args.db)

    # Get simulation names for ID mapping
    sim_names = {}
    try:
        cursor.execute("SELECT ID, Name FROM _Simulations")
        for sid, sname in cursor.fetchall():
            sim_names[sid] = sname
    except sqlite3.Error:
        pass

    conn.close()

    # Convert to records
    records = []
    for row in rows:
        record = {}
        for i, col in enumerate(columns):
            val = row[i]
            # Replace SimulationID with name
            if col == "SimulationID" and val in sim_names:
                record["SimulationName"] = sim_names[val]
            record[col] = val
        records.append(record)

    # Unit conversions
    if args.convert_yield:
        for rec in records:
            for col in columns:
                # Convert biomass g/m² → kg/ha (× 10)
                if any(bm in col for bm in [".Wt", ".Weight", "Biomass"]):
                    if rec.get(col) is not None:
                        try:
                            rec[f"{col}_kg_ha"] = round(float(rec[col]) * 10, 1)
                        except (ValueError, TypeError):
                            pass
                # Convert biomass g/m² → t/ha (÷ 100)
                if "Grain.Wt" in col or "Yield" in col:
                    if rec.get(col) is not None:
                        try:
                            rec[f"{col}_t_ha"] = round(float(rec[col]) / 100, 3)
                        except (ValueError, TypeError):
                            pass

    # Update columns list if we added converted columns
    if records:
        columns = list(records[0].keys())

    return {
        "status": "ok",
        "table": table,
        "n_rows": len(records),
        "columns": columns,
        "records": records,
        "units": {k: v for k, v in units.items() if k.startswith(table)},
        "available_tables": all_tables,
    }


def validate_outputs(result):
    """Validate extracted data quality."""
    warnings = []

    if result.get("mode") == "list_tables":
        return result

    if result["status"] != "ok":
        return result

    if result["n_rows"] == 0:
        warnings.append("No data rows extracted — check simulation ran successfully")

    # Check for common issues
    records = result.get("records", [])
    if records:
        # Check for all-null columns
        for col in result["columns"]:
            all_null = all(r.get(col) is None for r in records)
            if all_null:
                warnings.append(f"Column '{col}' is entirely NULL")

        # Check date range
        date_cols = [c for c in result["columns"] if "Today" in c or "Date" in c]
        for dc in date_cols:
            dates = [r.get(dc) for r in records if r.get(dc)]
            if dates:
                try:
                    first = str(dates[0])[:10]
                    last = str(dates[-1])[:10]
                    result["date_range"] = f"{first} to {last}"
                except Exception:
                    pass

    result["warnings"] = warnings
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Extract APSIM output from SQLite database to CSV"
    )
    parser.add_argument("--db", required=True, help="Path to APSIM output .db file")
    parser.add_argument("--output", type=str, default=None, help="Output CSV file path")
    parser.add_argument("--table", type=str, default=None,
                        help="Table name to extract (default: auto-detect 'Report')")
    parser.add_argument("--simulation", type=str, default=None,
                        help="Filter by simulation name (supports trailing *)")
    parser.add_argument("--convert-yield", action="store_true",
                        help="Add kg/ha and t/ha columns for biomass variables")
    parser.add_argument("--list-tables", action="store_true",
                        help="List all tables in database and exit")

    args = parser.parse_args()

    validate_inputs(args)
    result = process(args)
    result = validate_outputs(result)

    # Write CSV
    if args.output and result["status"] == "ok" and result.get("records"):
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=result["columns"])
            writer.writeheader()
            writer.writerows(result["records"])

    # Print summary (without full records)
    summary = {k: v for k, v in result.items() if k != "records"}
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
