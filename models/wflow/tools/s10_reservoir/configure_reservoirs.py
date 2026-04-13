#!/usr/bin/env python3
"""
configure_reservoirs.py -- Add reservoir module to a wflow TOML config and
generate reservoir parameter layers in staticmaps.nc.

This tool does TWO things:
  1. Patches an existing wflow_sbm.toml to enable reservoir__flag and add
     all required reservoir CSDMS variable mappings
  2. Adds reservoir parameter arrays to an existing staticmaps.nc file

IMPORTANT NOTES:
  - wflow v1.1.0+ uses CSDMS standard names for reservoir variables
  - Reservoir locations must be placed ON the river network (wflow_river=1)
  - Each reservoir is identified by a unique integer ID in reservoir_location__count
  - The "simple reservoir" (outflowfunc=4) is the recommended default for
    GRanD-derived parameters; it needs: maxstorage, area, demand, maxrelease,
    targetfullfrac, targetminfrac
  - Units must be SI: m^3, m^2, m^3/s (NOT MCM, km^2)

Usage:
    # From lookup_dams.py JSON output:
    python configure_reservoirs.py \
        --reservoir_json reservoirs.json \
        --toml wflow_sbm.toml \
        --staticmaps staticmaps.nc

    # Manual single reservoir:
    python configure_reservoirs.py \
        --toml wflow_sbm.toml \
        --staticmaps staticmaps.nc \
        --lat 33.087 --lon 118.729 \
        --area_m2 161147891000 --maxstorage_m3 13500000000 \
        --demand_m3s 21.4 --maxrelease_m3s 420.0

    # Dry run (TOML only, no staticmaps modification):
    python configure_reservoirs.py \
        --reservoir_json reservoirs.json \
        --toml wflow_sbm.toml \
        --dry_run
"""

import argparse
import json
import os
import sys
import math
from pathlib import Path
from copy import deepcopy


# CSDMS standard names used by wflow v1.1.0+ for reservoir parameters
# These must match the names in Wflow.jl src/routing/reservoir.jl
RESERVOIR_STATIC_VARS = {
    # Variable CSDMS name -> (NetCDF var name in staticmaps, description, unit)
    "reservoir_location__count": ("wflow_reservoirlocs", "Reservoir location IDs", "-"),
    "reservoir_surface__area": ("reservoir_area", "Reservoir surface area", "m^2"),
    "reservoir_water__max_volume": ("ResMaxVolume", "Maximum reservoir storage", "m^3"),
    "reservoir_water_demand__required_downstream_volume_flow_rate": (
        "ResDemand", "Required downstream flow", "m^3/s"
    ),
    "reservoir_water_release_below_spillway__max_volume_flow_rate": (
        "ResMaxRelease", "Maximum release below spillway", "m^3/s"
    ),
    "reservoir_water__target_full_volume_fraction": (
        "ResTargetFullFrac", "Target storage fraction", "-"
    ),
    "reservoir_water__target_min_volume_fraction": (
        "ResTargetMinFrac", "Minimum storage fraction", "-"
    ),
    "reservoir_water_surface__initial_elevation": (
        "waterlevel_reservoir", "Initial water level", "m"
    ),
    "reservoir_water__rating_curve_type_count": (
        "outflowfunc", "Outflow function type", "-"
    ),
    "reservoir_water__storage_curve_type_count": (
        "storfunc", "Storage function type", "-"
    ),
}

# Additional input fields needed for reservoir area masking
RESERVOIR_AREA_VAR = "reservoir_area__count"
RESERVOIR_AREA_NC = "wflow_reservoirareas"


def find_nearest_river_cell(lat, lon, lats, lons, river_mask):
    """Find the nearest grid cell that is ON the river network.

    Reservoirs must be placed on river cells (wflow_river=1) to intercept
    flow. If the exact lat/lon falls on a non-river cell, snap to the
    nearest river cell within 2 grid cells.

    Returns (row_idx, col_idx) or None if no river cell found nearby.
    """
    import numpy as np

    # Find closest cell to lat/lon
    lat_diff = np.abs(lats - lat)
    lon_diff = np.abs(lons - lon)

    # Handle 1D vs 2D coordinate arrays
    if lats.ndim == 1 and lons.ndim == 1:
        row_nearest = np.argmin(lat_diff)
        col_nearest = np.argmin(lon_diff)
    else:
        dist = lat_diff ** 2 + lon_diff ** 2
        row_nearest, col_nearest = np.unravel_index(np.argmin(dist), dist.shape)

    # Check if nearest cell is a river cell
    if river_mask[row_nearest, col_nearest] == 1:
        return int(row_nearest), int(col_nearest)

    # Search in expanding rings (up to 3 cells away)
    nrows, ncols = river_mask.shape
    for radius in range(1, 4):
        best_dist = float("inf")
        best_rc = None
        for dr in range(-radius, radius + 1):
            for dc in range(-radius, radius + 1):
                r = row_nearest + dr
                c = col_nearest + dc
                if 0 <= r < nrows and 0 <= c < ncols:
                    if river_mask[r, c] == 1:
                        dist = dr ** 2 + dc ** 2
                        if dist < best_dist:
                            best_dist = dist
                            best_rc = (int(r), int(c))
        if best_rc is not None:
            return best_rc

    return None


def add_reservoirs_to_staticmaps(staticmaps_path, reservoirs, dry_run=False):
    """Add reservoir parameter arrays to staticmaps.nc.

    Creates new variables in staticmaps.nc for each reservoir parameter.
    Reservoir locations are placed on the nearest river cell.

    Returns list of placed reservoirs with their grid positions.
    """
    import numpy as np

    if dry_run:
        print("DRY RUN: Skipping staticmaps modification")
        return [{"index": r["reservoir_index"], "name": r["name"],
                 "status": "dry_run"} for r in reservoirs]

    try:
        import netCDF4 as nc
    except ImportError:
        print("ERROR: netCDF4 required. Install with: pip install netCDF4",
              file=sys.stderr)
        sys.exit(1)

    if not os.path.exists(staticmaps_path):
        print(f"ERROR: staticmaps not found: {staticmaps_path}", file=sys.stderr)
        sys.exit(1)

    ds = nc.Dataset(staticmaps_path, "r+")

    # Get grid dimensions and coordinates
    # wflow uses y,x or lat,lon dimensions
    if "y" in ds.dimensions:
        lat_dim, lon_dim = "y", "x"
    elif "lat" in ds.dimensions:
        lat_dim, lon_dim = "lat", "lon"
    else:
        ds.close()
        print("ERROR: Cannot determine grid dimensions in staticmaps.nc",
              file=sys.stderr)
        sys.exit(1)

    lats = ds.variables[lat_dim][:]
    lons = ds.variables[lon_dim][:]
    nrows = len(lats)
    ncols = len(lons)

    # Get river mask
    river_var = None
    for vname in ["wflow_river", "river_location__mask"]:
        if vname in ds.variables:
            river_var = vname
            break
    if river_var is None:
        ds.close()
        print("ERROR: No river mask (wflow_river) found in staticmaps.nc",
              file=sys.stderr)
        sys.exit(1)

    river_mask = ds.variables[river_var][:]

    # Initialize parameter arrays (NaN for inactive cells)
    res_locs = np.full((nrows, ncols), 0, dtype=np.int32)
    res_areas_mask = np.full((nrows, ncols), 0, dtype=np.int32)
    res_area = np.full((nrows, ncols), np.nan, dtype=np.float64)
    res_maxvol = np.full((nrows, ncols), np.nan, dtype=np.float64)
    res_demand = np.full((nrows, ncols), np.nan, dtype=np.float64)
    res_maxrelease = np.full((nrows, ncols), np.nan, dtype=np.float64)
    res_targetfull = np.full((nrows, ncols), np.nan, dtype=np.float64)
    res_targetmin = np.full((nrows, ncols), np.nan, dtype=np.float64)
    res_wl_init = np.full((nrows, ncols), np.nan, dtype=np.float64)
    res_outflowfunc = np.full((nrows, ncols), 0, dtype=np.int32)
    res_storfunc = np.full((nrows, ncols), 0, dtype=np.int32)

    placed = []
    for res in reservoirs:
        rc = find_nearest_river_cell(
            res["lat"], res["lon"], lats, lons, river_mask
        )
        if rc is None:
            print(f"  WARNING: Could not place {res['name']} (ID={res['grand_id']}) "
                  f"on river network. Skipping.", file=sys.stderr)
            placed.append({
                "index": res["reservoir_index"],
                "name": res["name"],
                "status": "SKIPPED_no_river_cell",
            })
            continue

        r, c = rc
        rid = res["reservoir_index"]

        # Check for collision
        if res_locs[r, c] != 0:
            print(f"  WARNING: Cell ({r},{c}) already has reservoir "
                  f"{res_locs[r, c]}. Overwriting with {res['name']}.",
                  file=sys.stderr)

        res_locs[r, c] = rid
        res_areas_mask[r, c] = rid
        res_area[r, c] = res["area_m2"]
        res_maxvol[r, c] = res["maxstorage_m3"]
        res_demand[r, c] = res["demand_m3s"]
        res_maxrelease[r, c] = res["maxrelease_m3s"]
        res_targetfull[r, c] = res["targetfullfrac"]
        res_targetmin[r, c] = res["targetminfrac"]
        res_wl_init[r, c] = res["waterlevel_init_m"]
        res_outflowfunc[r, c] = res["outflowfunc"]
        res_storfunc[r, c] = res["storfunc"]

        actual_lat = float(lats[r]) if lats.ndim == 1 else float(lats[r, c])
        actual_lon = float(lons[c]) if lons.ndim == 1 else float(lons[r, c])

        placed.append({
            "index": rid,
            "name": res["name"],
            "grand_id": res["grand_id"],
            "status": "placed",
            "grid_row": r,
            "grid_col": c,
            "actual_lat": round(actual_lat, 4),
            "actual_lon": round(actual_lon, 4),
            "requested_lat": res["lat"],
            "requested_lon": res["lon"],
        })
        print(f"  Placed {res['name']} at grid[{r},{c}] "
              f"(lat={actual_lat:.3f}, lon={actual_lon:.3f})")

    # Write arrays to NetCDF
    var_data = {
        "wflow_reservoirlocs": (res_locs, np.int32, "Reservoir location IDs"),
        "wflow_reservoirareas": (res_areas_mask, np.int32, "Reservoir area mask"),
        "reservoir_area": (res_area, np.float64, "Reservoir surface area [m^2]"),
        "ResMaxVolume": (res_maxvol, np.float64, "Max reservoir storage [m^3]"),
        "ResDemand": (res_demand, np.float64, "Required downstream flow [m^3/s]"),
        "ResMaxRelease": (res_maxrelease, np.float64, "Max release [m^3/s]"),
        "ResTargetFullFrac": (res_targetfull, np.float64, "Target full fraction [-]"),
        "ResTargetMinFrac": (res_targetmin, np.float64, "Target min fraction [-]"),
        "waterlevel_reservoir": (res_wl_init, np.float64, "Initial water level [m]"),
        "outflowfunc": (res_outflowfunc, np.int32, "Outflow function type"),
        "storfunc": (res_storfunc, np.int32, "Storage function type"),
    }

    for vname, (data, dtype, desc) in var_data.items():
        if vname in ds.variables:
            ds.variables[vname][:] = data
        else:
            var = ds.createVariable(
                vname, dtype, (lat_dim, lon_dim),
                fill_value=-9999 if dtype == np.int32 else np.nan,
            )
            var[:] = data
            var.long_name = desc

    ds.sync()
    ds.close()

    n_placed = sum(1 for p in placed if p["status"] == "placed")
    print(f"\n  {n_placed}/{len(reservoirs)} reservoir(s) placed in {staticmaps_path}")

    return placed


def patch_toml(toml_path, reservoirs, output_path=None, dry_run=False):
    """Add reservoir configuration to an existing wflow TOML file.

    Adds/modifies:
      [model] reservoir__flag = true
      [input] reservoir_location__count, reservoir_area__count
      [input.static] all reservoir parameter mappings
      [state.variables] reservoir_water_surface__elevation
      [output.netcdf_grid.variables] reservoir_water__volume
      [[output.csv.column]] reservoir storage

    The TOML is modified line-by-line to preserve structure and comments.
    """
    if not os.path.exists(toml_path):
        print(f"ERROR: TOML file not found: {toml_path}", file=sys.stderr)
        sys.exit(1)

    with open(toml_path, "r") as f:
        lines = f.readlines()

    output_path = output_path or toml_path
    new_lines = []
    in_model = False
    in_input = False
    in_input_static = False
    in_state_vars = False
    in_output_grid_vars = False
    reservoir_flag_added = False
    reservoir_input_added = False
    reservoir_static_added = False
    reservoir_state_added = False
    reservoir_output_added = False

    for line in lines:
        stripped = line.strip()

        # Track sections
        if stripped.startswith("[") and not stripped.startswith("[["):
            in_model = (stripped == "[model]")
            in_input = (stripped == "[input]")
            in_input_static = (stripped == "[input.static]")
            in_state_vars = (stripped == "[state.variables]")
            in_output_grid_vars = (stripped == "[output.netcdf_grid.variables]")

        # Replace reservoir__flag = false with true
        if in_model and "reservoir__flag" in stripped:
            new_lines.append("reservoir__flag = true\n")
            reservoir_flag_added = True
            continue

        new_lines.append(line)

        # Add reservoir__flag after model section if not already present
        if in_model and stripped.startswith("type") and not reservoir_flag_added:
            # Check if reservoir__flag exists later in this section
            pass

        # Add reservoir location mappings after river_location__mask
        if in_input and "river_location__mask" in stripped and not reservoir_input_added:
            new_lines.append(f'{RESERVOIR_AREA_VAR} = "{RESERVOIR_AREA_NC}"\n')
            new_lines.append(
                'reservoir_location__count = "wflow_reservoirlocs"\n'
            )
            reservoir_input_added = True

        # Add reservoir static parameter mappings at end of [input.static]
        if in_input_static and stripped and not stripped.startswith("#"):
            # We'll add after detecting the next section
            pass

        # Add reservoir state variable after river state vars
        if in_state_vars and "river_water__depth" in stripped and not reservoir_state_added:
            new_lines.append(
                'reservoir_water_surface__elevation = "waterlevel_reservoir"\n'
            )
            reservoir_state_added = True

        # Add reservoir output variable
        if in_output_grid_vars and "river_water__volume_flow_rate" in stripped and \
                not reservoir_output_added:
            new_lines.append(
                'reservoir_water__volume = "storage_reservoir"\n'
            )
            reservoir_output_added = True

    # Now inject the reservoir static variables
    # Find the [input.static] section end and inject before it
    final_lines = []
    in_input_static = False
    next_section_found = False

    for i, line in enumerate(new_lines):
        stripped = line.strip()

        if stripped == "[input.static]":
            in_input_static = True
            reservoir_static_added = False

        # Detect when we leave [input.static]
        if in_input_static and not reservoir_static_added:
            is_new_section = (
                stripped.startswith("[") and
                stripped != "[input.static]" and
                not stripped.startswith("[[")
            )
            if is_new_section:
                # Inject reservoir parameters before this line
                final_lines.append("\n# Reservoir parameters (added by configure_reservoirs.py)\n")
                for csdms_name, (nc_name, desc, unit) in RESERVOIR_STATIC_VARS.items():
                    if csdms_name == "reservoir_location__count":
                        continue  # already in [input]
                    final_lines.append(f'{csdms_name} = "{nc_name}"\n')
                final_lines.append("\n")
                reservoir_static_added = True

        final_lines.append(line)

    # If we never found the end of [input.static], append at end
    if not reservoir_static_added:
        final_lines.append("\n# Reservoir parameters (added by configure_reservoirs.py)\n")
        for csdms_name, (nc_name, desc, unit) in RESERVOIR_STATIC_VARS.items():
            if csdms_name == "reservoir_location__count":
                continue
            final_lines.append(f'{csdms_name} = "{nc_name}"\n')

    # Ensure reservoir__flag is present in [model]
    if not reservoir_flag_added:
        model_lines = []
        for i, line in enumerate(final_lines):
            model_lines.append(line)
            if line.strip() == "[model]":
                # Add reservoir__flag right after [model]
                model_lines.append("reservoir__flag = true\n")
                reservoir_flag_added = True
        final_lines = model_lines

    # Add CSV output for reservoir storage
    final_lines.append("\n[[output.csv.column]]\n")
    final_lines.append('header = "reservoir_storage"\n')
    final_lines.append("index = 1\n")
    final_lines.append('parameter = "reservoir_water__volume"\n')

    content = "".join(final_lines)

    if dry_run:
        print("\n--- DRY RUN: TOML output ---")
        print(content)
        print("--- END DRY RUN ---")
    else:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w") as f:
            f.write(content)
        print(f"  TOML updated: {output_path}")

    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="Add reservoir module to wflow TOML config and staticmaps.nc"
    )

    # Input sources
    parser.add_argument("--reservoir_json", type=str,
                        help="JSON file from lookup_dams.py (recommended)")
    parser.add_argument("--toml", type=str, required=True,
                        help="Path to existing wflow_sbm.toml")
    parser.add_argument("--staticmaps", type=str, default="",
                        help="Path to staticmaps.nc (required unless --dry_run)")
    parser.add_argument("--output_toml", type=str, default="",
                        help="Output TOML path (default: overwrite input)")

    # Manual single reservoir (alternative to JSON)
    parser.add_argument("--lat", type=float, help="Reservoir latitude")
    parser.add_argument("--lon", type=float, help="Reservoir longitude")
    parser.add_argument("--area_m2", type=float, help="Reservoir area [m^2]")
    parser.add_argument("--maxstorage_m3", type=float,
                        help="Max storage [m^3]")
    parser.add_argument("--demand_m3s", type=float, default=0.0,
                        help="Demand flow [m^3/s]")
    parser.add_argument("--maxrelease_m3s", type=float, default=0.0,
                        help="Max release [m^3/s]")
    parser.add_argument("--name", type=str, default="Manual",
                        help="Reservoir name")

    # Options
    parser.add_argument("--dry_run", action="store_true",
                        help="Show TOML changes without modifying files")

    args = parser.parse_args()

    # Build reservoir list
    reservoirs = []

    if args.reservoir_json:
        if not os.path.exists(args.reservoir_json):
            print(f"ERROR: JSON file not found: {args.reservoir_json}",
                  file=sys.stderr)
            sys.exit(1)
        with open(args.reservoir_json) as f:
            data = json.load(f)
        reservoirs = data.get("reservoirs", [])
        if not reservoirs:
            print("WARNING: No reservoirs in JSON file.", file=sys.stderr)
    elif args.lat is not None and args.lon is not None:
        if not args.area_m2 or not args.maxstorage_m3:
            print("ERROR: --area_m2 and --maxstorage_m3 required for manual mode",
                  file=sys.stderr)
            sys.exit(1)
        reservoirs = [{
            "reservoir_index": 1,
            "name": args.name,
            "grand_id": 0,
            "lat": args.lat,
            "lon": args.lon,
            "area_m2": args.area_m2,
            "maxstorage_m3": args.maxstorage_m3,
            "demand_m3s": args.demand_m3s,
            "maxrelease_m3s": args.maxrelease_m3s,
            "targetfullfrac": 0.8,
            "targetminfrac": 0.2,
            "waterlevel_init_m": args.maxstorage_m3 * 0.8 / args.area_m2
                if args.area_m2 > 0 else 10.0,
            "storfunc": 1,
            "outflowfunc": 4,
        }]
    else:
        print("ERROR: Provide --reservoir_json or --lat/--lon with params",
              file=sys.stderr)
        sys.exit(1)

    if not reservoirs:
        print("No reservoirs to configure.")
        sys.exit(0)

    # Validate staticmaps is provided when not dry_run
    if not args.dry_run and not args.staticmaps:
        print("ERROR: --staticmaps required (or use --dry_run)", file=sys.stderr)
        sys.exit(1)

    print(f"\nConfiguring {len(reservoirs)} reservoir(s) for wflow...")
    print(f"  TOML:       {args.toml}")
    if args.staticmaps:
        print(f"  Staticmaps: {args.staticmaps}")
    print()

    # Step 1: Patch TOML
    output_toml = args.output_toml or args.toml
    patch_toml(args.toml, reservoirs, output_toml, args.dry_run)

    # Step 2: Add to staticmaps
    placed = []
    if args.staticmaps or args.dry_run:
        placed = add_reservoirs_to_staticmaps(
            args.staticmaps, reservoirs, args.dry_run
        )

    # Summary
    n_placed = sum(1 for p in placed if p.get("status") == "placed")
    n_skipped = sum(1 for p in placed if "SKIPPED" in p.get("status", ""))

    result = {
        "status": "success",
        "toml_path": output_toml,
        "staticmaps_path": args.staticmaps,
        "reservoirs_total": len(reservoirs),
        "reservoirs_placed": n_placed,
        "reservoirs_skipped": n_skipped,
        "placement_details": placed,
        "dry_run": args.dry_run,
    }

    print(f"\n{'='*60}")
    print(f"Reservoir configuration complete")
    print(f"  Total:   {len(reservoirs)}")
    print(f"  Placed:  {n_placed}")
    print(f"  Skipped: {n_skipped}")
    if args.dry_run:
        print(f"  Mode:    DRY RUN (no files modified)")
    print(f"{'='*60}")

    # Print JSON summary
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
