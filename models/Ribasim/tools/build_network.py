#!/usr/bin/env python3
"""
build_network.py — Build a Ribasim GeoPackage network from CSV/shapefile inputs.

This tool converts user-provided node definitions (CSV with coordinates and types)
and link definitions (CSV with from/to node IDs) into a Ribasim-compatible GeoPackage
database and TOML configuration file.

Pattern: validate → process → validate

Usage:
    python build_network.py \
        --nodes_csv nodes.csv \
        --links_csv links.csv \
        --basin_profile_csv basin_profiles.csv \
        --basin_state_csv basin_states.csv \
        --starttime 2020-01-01 \
        --endtime 2021-01-01 \
        --crs "EPSG:28992" \
        --output_dir my_model/
"""

import argparse
import json
import os
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import LineString, Point


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
VALID_NODE_TYPES = [
    "Basin",
    "Pump",
    "Outlet",
    "TabulatedRatingCurve",
    "LinearResistance",
    "ManningResistance",
    "FlowBoundary",
    "LevelBoundary",
    "UserDemand",
    "FlowDemand",
    "LevelDemand",
    "DiscreteControl",
    "ContinuousControl",
    "PidControl",
    "Junction",
    "Terminal",
]

VALID_LINK_TYPES = ["flow", "control", "listen", "observation"]

# NOTE: starttime/endtime are BARE TOML datetimes (no quotes). Ribasim's config
# parser (Configurations.jl) expects a TOML datetime, not a string — the shipped
# working model (test_model/ribasim.toml) uses `starttime = 2020-01-01 00:00:00`.
# ribasim_version must match the installed core (2026.1.0-rc2), not "2026.1.0".
TOML_TEMPLATE = """\
starttime = {starttime} 00:00:00
endtime = {endtime} 00:00:00
crs = "{crs}"
input_dir = "input"
results_dir = "results"
ribasim_version = "{ribasim_version}"

[solver]
algorithm = "QNDF"
saveat = {saveat}
abstol = 1e-5
reltol = 1e-5
sparse = true
autodiff = true
depth_threshold = {depth_threshold}

[logging]
verbosity = "info"

[results]
compression = true
compression_level = 1
"""


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------
def validate_nodes_csv(df: pd.DataFrame) -> list[str]:
    """Validate node CSV input. Returns list of error messages."""
    errors = []

    required_cols = {"node_id", "node_type", "x", "y"}
    missing = required_cols - set(df.columns)
    if missing:
        errors.append(f"Missing required columns in nodes CSV: {missing}")
        return errors

    # Check node_id uniqueness
    dupes = df[df["node_id"].duplicated()]["node_id"].tolist()
    if dupes:
        errors.append(f"Duplicate node_ids: {dupes}")

    # Check node types
    invalid_types = set(df["node_type"]) - set(VALID_NODE_TYPES)
    if invalid_types:
        errors.append(f"Invalid node types: {invalid_types}")

    # Check coordinates are numeric
    for col in ["x", "y"]:
        if not pd.to_numeric(df[col], errors="coerce").notna().all():
            errors.append(f"Non-numeric values in column '{col}'")

    return errors


def validate_links_csv(df: pd.DataFrame, node_ids: set) -> list[str]:
    """Validate link CSV input. Returns list of error messages."""
    errors = []

    required_cols = {"from_node_id", "to_node_id"}
    missing = required_cols - set(df.columns)
    if missing:
        errors.append(f"Missing required columns in links CSV: {missing}")
        return errors

    # Check references to existing nodes
    invalid_from = set(df["from_node_id"]) - node_ids
    if invalid_from:
        errors.append(f"from_node_id references non-existent nodes: {invalid_from}")

    invalid_to = set(df["to_node_id"]) - node_ids
    if invalid_to:
        errors.append(f"to_node_id references non-existent nodes: {invalid_to}")

    # Check link type if present
    if "link_type" in df.columns:
        invalid_lt = set(df["link_type"]) - set(VALID_LINK_TYPES)
        if invalid_lt:
            errors.append(f"Invalid link types: {invalid_lt}")

    return errors


def validate_basin_profile(df: pd.DataFrame) -> list[str]:
    """Validate basin profile data: level must be monotonically increasing per node."""
    errors = []
    required_cols = {"node_id", "level", "area"}
    missing = required_cols - set(df.columns)
    if missing:
        errors.append(f"Missing required columns in basin profile: {missing}")
        return errors

    for nid, group in df.groupby("node_id"):
        levels = group["level"].values
        if len(levels) < 2:
            errors.append(f"Basin {nid}: profile needs at least 2 level-area pairs")
        if not np.all(np.diff(levels) > 0):
            errors.append(f"Basin {nid}: profile levels must be monotonically increasing")
        areas = group["area"].values
        if np.any(areas < 0):
            errors.append(f"Basin {nid}: negative area values found")

    return errors


# ---------------------------------------------------------------------------
# Processing
# ---------------------------------------------------------------------------
def build_node_geodataframe(df: pd.DataFrame, crs: str) -> gpd.GeoDataFrame:
    """Convert node CSV DataFrame to GeoDataFrame with Point geometry."""
    geometry = [Point(row["x"], row["y"]) for _, row in df.iterrows()]
    # Ribasim 2026.1.0-rc2 reads Node with subnetwork_id, route_priority and
    # cyclic_time columns (queried explicitly at startup — a table without them
    # fails with "no such column"). Defaults follow the shipped working model:
    # subnetwork_id/route_priority NULL, cyclic_time false.
    gdf = gpd.GeoDataFrame(
        {
            "node_id": df["node_id"].astype("int32"),
            "node_type": df["node_type"].astype(str),
            "name": df.get("name", "").astype(str) if "name" in df.columns else "",
            "subnetwork_id": (
                df["subnetwork_id"].astype("Int32")
                if "subnetwork_id" in df.columns
                else pd.array([pd.NA] * len(df), dtype="Int32")
            ),
            "route_priority": (
                df["route_priority"].astype("Int32")
                if "route_priority" in df.columns
                else pd.array([pd.NA] * len(df), dtype="Int32")
            ),
            "cyclic_time": (
                df["cyclic_time"].astype(bool)
                if "cyclic_time" in df.columns
                else False
            ),
        },
        geometry=geometry,
        crs=crs,
    )
    return gdf


def build_link_geodataframe(
    df: pd.DataFrame, node_gdf: gpd.GeoDataFrame, crs: str
) -> gpd.GeoDataFrame:
    """Convert link CSV DataFrame to GeoDataFrame with LineString geometry."""
    node_coords = {
        row["node_id"]: row.geometry for _, row in node_gdf.iterrows()
    }

    geometries = []
    for _, row in df.iterrows():
        p1 = node_coords[row["from_node_id"]]
        p2 = node_coords[row["to_node_id"]]
        geometries.append(LineString([p1, p2]))

    link_type = df["link_type"] if "link_type" in df.columns else "flow"

    # Ribasim 2026.1.0-rc2 validation queries `link_id` explicitly
    # (core/src/validation.jl valid_link_types); a Link table without it fails
    # at startup with an SQLite prepare error.
    link_id = (
        df["link_id"].astype("int32")
        if "link_id" in df.columns
        else np.arange(1, len(df) + 1, dtype="int32")
    )
    gdf = gpd.GeoDataFrame(
        {
            "link_id": link_id,
            "from_node_id": df["from_node_id"].astype("int32"),
            "to_node_id": df["to_node_id"].astype("int32"),
            "link_type": link_type,
            "name": df.get("name", "").astype(str) if "name" in df.columns else "",
        },
        geometry=geometries,
        crs=crs,
    )
    return gdf


def write_geopackage(
    output_dir: Path,
    node_gdf: gpd.GeoDataFrame,
    link_gdf: gpd.GeoDataFrame,
    basin_profile_df: pd.DataFrame | None = None,
    basin_state_df: pd.DataFrame | None = None,
) -> Path:
    """Write all tables to a GeoPackage file."""
    gpkg_path = output_dir / "input" / "database.gpkg"
    gpkg_path.parent.mkdir(parents=True, exist_ok=True)

    # Remove existing file to avoid append issues
    if gpkg_path.exists():
        gpkg_path.unlink()

    node_gdf.to_file(gpkg_path, layer="Node", driver="GPKG")
    link_gdf.to_file(gpkg_path, layer="Link", driver="GPKG")

    if basin_profile_df is not None:
        # Write as non-spatial table via pandas + sqlite
        import sqlite3

        conn = sqlite3.connect(str(gpkg_path))
        basin_profile_df.to_sql("Basin / profile", conn, if_exists="replace", index=False)
        conn.close()

    if basin_state_df is not None:
        import sqlite3

        conn = sqlite3.connect(str(gpkg_path))
        basin_state_df.to_sql("Basin / state", conn, if_exists="replace", index=False)
        conn.close()

    return gpkg_path


def write_toml(
    output_dir: Path,
    starttime: str,
    endtime: str,
    crs: str,
    saveat: int = 86400,
    ribasim_version: str = "2026.1.0-rc2",
    depth_threshold: float = 0.1,
) -> Path:
    """Write ribasim.toml configuration file."""
    toml_path = output_dir / "ribasim.toml"
    content = TOML_TEMPLATE.format(
        starttime=starttime,
        endtime=endtime,
        crs=crs,
        saveat=saveat,
        ribasim_version=ribasim_version,
        depth_threshold=depth_threshold,
    )
    toml_path.write_text(content)
    return toml_path


# ---------------------------------------------------------------------------
# Parameter-table writers (Basin forcing, structures, boundaries)
# ---------------------------------------------------------------------------
# Ribasim 2026.1.0-rc2 schema facts (core/src/schema.jl — verified against the
# shipped working model's database.gpkg):
#   Basin / static|time : node_id, [time], drainage, potential_evaporation,
#                         infiltration, precipitation, surface_runoff
#     -> the evaporation column is named `potential_evaporation`, NOT
#        `evaporation`. A column named `evaporation` is not part of the schema.
#   TabulatedRatingCurve / static : node_id, level, flow_rate, ...
#   FlowBoundary / static : node_id, flow_rate ; / time adds a time column.
PARAM_TABLE_SPECS = {
    "basin_static": {
        "table": "Basin / static",
        "required": {"node_id"},
        "allowed_forcing": {"precipitation", "potential_evaporation",
                            "drainage", "infiltration", "surface_runoff"},
    },
    "basin_time": {
        "table": "Basin / time",
        "required": {"node_id", "time"},
        "allowed_forcing": {"precipitation", "potential_evaporation",
                            "drainage", "infiltration", "surface_runoff"},
    },
    "rating_curve": {
        "table": "TabulatedRatingCurve / static",
        "required": {"node_id", "level", "flow_rate"},
        "allowed_forcing": set(),
    },
    "flow_boundary": {
        # table name resolved at write time: "/ time" if a time column exists
        "table": None,
        "required": {"node_id", "flow_rate"},
        "allowed_forcing": set(),
    },
}


def validate_param_table(kind: str, df: pd.DataFrame) -> list[str]:
    """Validate a parameter table against the Ribasim 2026.1.0-rc2 schema."""
    errors = []
    spec = PARAM_TABLE_SPECS[kind]

    missing = spec["required"] - set(df.columns)
    if missing:
        errors.append(f"{kind}: missing required columns {missing}")
        return errors

    if "evaporation" in df.columns:
        errors.append(
            f"{kind}: column 'evaporation' is not in the Ribasim 2026.1.0-rc2 "
            "schema — rename it to 'potential_evaporation' (m/s)."
        )

    # Unit sanity for vertical fluxes (must be m/s; dt_001/dt_002)
    for col in ("precipitation", "potential_evaporation"):
        if col in df.columns and df[col].notna().any():
            vmax = df[col].max()
            if vmax > 1e-5:
                errors.append(
                    f"{kind}: {col} max = {vmax:.2e} — Ribasim expects m/s "
                    "(< 1e-5 m/s ~ 864 mm/day); values look like mm/day."
                )

    if kind == "rating_curve":
        for nid, group in df.groupby("node_id"):
            levels = group["level"].values
            flows = group["flow_rate"].values
            if len(levels) < 2:
                errors.append(f"rating_curve node {nid}: need >= 2 level points")
            if not np.all(np.diff(levels) > 0):
                errors.append(
                    f"rating_curve node {nid}: levels must be strictly increasing"
                )
            if np.any(flows < 0):
                errors.append(f"rating_curve node {nid}: negative flow_rate")
            if np.any(np.diff(flows) < 0):
                errors.append(
                    f"rating_curve node {nid}: flow_rate must be non-decreasing"
                )

    return errors


def write_param_table(gpkg_path: Path, kind: str, df: pd.DataFrame) -> str:
    """Write one parameter table into the GeoPackage. Returns the table name."""
    import sqlite3

    spec = PARAM_TABLE_SPECS[kind]
    table = spec["table"]
    if kind == "flow_boundary":
        table = "FlowBoundary / time" if "time" in df.columns else "FlowBoundary / static"

    out = df.copy()
    if "time" in out.columns:
        # Match the shipped working model: TIMESTAMP text 'YYYY-MM-DD HH:MM:SS'
        out["time"] = pd.to_datetime(out["time"]).dt.strftime("%Y-%m-%d %H:%M:%S")

    # Ribasim's table reader materializes EVERY schema column; a table missing
    # an optional column crashes at startup (UndefRefError in StructArrays sort)
    # rather than defaulting to missing. Pad optional columns with NULLs, as in
    # the shipped working model's database.gpkg.
    FULL_COLUMNS = {
        "Basin / static": ["node_id", "drainage", "potential_evaporation",
                           "infiltration", "precipitation", "surface_runoff"],
        "Basin / time": ["node_id", "time", "drainage", "potential_evaporation",
                         "infiltration", "precipitation", "surface_runoff"],
        "TabulatedRatingCurve / static": ["node_id", "level", "flow_rate",
                                          "max_downstream_level", "control_state",
                                          "allocation_controlled"],
        "FlowBoundary / static": ["node_id", "flow_rate"],
        "FlowBoundary / time": ["node_id", "time", "flow_rate"],
    }
    if table in FULL_COLUMNS:
        for col in FULL_COLUMNS[table]:
            if col not in out.columns:
                out[col] = None
        out = out[FULL_COLUMNS[table]]

    conn = sqlite3.connect(str(gpkg_path))
    out.to_sql(table, conn, if_exists="replace", index=False)
    conn.close()
    return table


def validate_output(output_dir: Path) -> list[str]:
    """Post-process validation: check output files exist and are valid."""
    errors = []
    toml_path = output_dir / "ribasim.toml"
    gpkg_path = output_dir / "input" / "database.gpkg"

    if not toml_path.exists():
        errors.append(f"TOML file not created: {toml_path}")
    if not gpkg_path.exists():
        errors.append(f"GeoPackage not created: {gpkg_path}")
    elif gpkg_path.stat().st_size < 100:
        errors.append(f"GeoPackage appears empty: {gpkg_path}")

    return errors


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Build Ribasim network from CSV inputs")
    parser.add_argument("--nodes_csv", required=True, help="CSV with node_id, node_type, x, y")
    parser.add_argument("--links_csv", required=True, help="CSV with from_node_id, to_node_id")
    parser.add_argument("--basin_profile_csv", help="CSV with node_id, level, area")
    parser.add_argument("--basin_state_csv", help="CSV with node_id, level")
    parser.add_argument("--basin_static_csv",
                        help="CSV -> 'Basin / static' (node_id, precipitation, "
                             "potential_evaporation, ... all fluxes in m/s)")
    parser.add_argument("--basin_time_csv",
                        help="CSV -> 'Basin / time' (node_id, time, precipitation, "
                             "potential_evaporation, ... all fluxes in m/s)")
    parser.add_argument("--rating_curve_csv",
                        help="CSV -> 'TabulatedRatingCurve / static' "
                             "(node_id, level [m], flow_rate [m3/s])")
    parser.add_argument("--flow_boundary_csv",
                        help="CSV -> 'FlowBoundary / static' or '/ time' "
                             "(node_id, [time], flow_rate [m3/s])")
    parser.add_argument("--starttime", required=True, help="Simulation start (YYYY-MM-DD)")
    parser.add_argument("--endtime", required=True, help="Simulation end (YYYY-MM-DD)")
    parser.add_argument("--crs", default="EPSG:28992", help="Coordinate reference system")
    parser.add_argument("--saveat", type=int, default=86400, help="Output interval (seconds)")
    parser.add_argument("--ribasim_version", default="2026.1.0-rc2",
                        help="ribasim_version string written to the TOML")
    parser.add_argument("--depth_threshold", type=float, default=0.1,
                        help="[solver] depth_threshold in metres (dt_011: flows are "
                             "damped below this depth; lower it for shallow basins)")
    parser.add_argument("--output_dir", required=True, help="Output directory")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "results").mkdir(exist_ok=True)

    # --- Step 1: Input validation ---
    print("[1/4] Validating inputs...")

    nodes_df = pd.read_csv(args.nodes_csv)
    links_df = pd.read_csv(args.links_csv)

    errors = validate_nodes_csv(nodes_df)
    if errors:
        print("ERROR: Node validation failed:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    node_ids = set(nodes_df["node_id"])
    errors = validate_links_csv(links_df, node_ids)
    if errors:
        print("ERROR: Link validation failed:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    basin_profile_df = None
    if args.basin_profile_csv:
        basin_profile_df = pd.read_csv(args.basin_profile_csv)
        errors = validate_basin_profile(basin_profile_df)
        if errors:
            print("ERROR: Basin profile validation failed:")
            for e in errors:
                print(f"  - {e}")
            sys.exit(1)

    basin_state_df = None
    if args.basin_state_csv:
        basin_state_df = pd.read_csv(args.basin_state_csv)

    param_tables: list[tuple[str, pd.DataFrame]] = []
    for kind, csv_arg in [
        ("basin_static", args.basin_static_csv),
        ("basin_time", args.basin_time_csv),
        ("rating_curve", args.rating_curve_csv),
        ("flow_boundary", args.flow_boundary_csv),
    ]:
        if csv_arg:
            pdf = pd.read_csv(csv_arg)
            errors = validate_param_table(kind, pdf)
            if errors:
                print(f"ERROR: {kind} table validation failed:")
                for e in errors:
                    print(f"  - {e}")
                sys.exit(1)
            param_tables.append((kind, pdf))

    print(f"  Nodes: {len(nodes_df)}, Links: {len(links_df)}")

    # --- Step 2: Build GeoDataFrames ---
    print("[2/4] Building network...")
    node_gdf = build_node_geodataframe(nodes_df, args.crs)
    link_gdf = build_link_geodataframe(links_df, node_gdf, args.crs)

    # --- Step 3: Write outputs ---
    print("[3/4] Writing GeoPackage and TOML...")
    gpkg_path = write_geopackage(output_dir, node_gdf, link_gdf, basin_profile_df, basin_state_df)
    for kind, pdf in param_tables:
        table = write_param_table(gpkg_path, kind, pdf)
        print(f"  Wrote table '{table}' ({len(pdf)} rows)")
    toml_path = write_toml(
        output_dir, args.starttime, args.endtime, args.crs, args.saveat,
        args.ribasim_version, args.depth_threshold,
    )

    # --- Step 4: Output validation ---
    print("[4/4] Validating outputs...")
    errors = validate_output(output_dir)
    if errors:
        print("ERROR: Output validation failed:")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    print(f"SUCCESS: Model written to {output_dir}")
    print(f"  TOML: {toml_path}")
    print(f"  GeoPackage: {gpkg_path}")

    # Write summary
    summary = {
        "status": "success",
        "n_nodes": len(nodes_df),
        "n_links": len(links_df),
        "node_types": nodes_df["node_type"].value_counts().to_dict(),
        "toml_path": str(toml_path),
        "gpkg_path": str(gpkg_path),
        "crs": args.crs,
        "starttime": args.starttime,
        "endtime": args.endtime,
    }
    summary_path = output_dir / "build_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2))
    print(f"  Summary: {summary_path}")


if __name__ == "__main__":
    main()
