#!/usr/bin/env python3
"""
build_connectivity.py — Build RAPID Stage-1 connectivity from a river network.

Implements the workflow documented in docs/s1_connectivity.md, which had NO
implementing tool in tools/. Every downstream RAPID tool requires these
Stage-1 products as inputs:
  - generate_namelist.py      requires --rapid_connect --riv_bas_id
  - convert_lsm_to_vlat.py    requires --riv_bas_id (and --connectivity,
                              --catchment_file)
  - generate_muskingum_params requires --riv_bas_id (and --reach_properties)

This tool reads a river-network vector layer (HydroSHEDS/HydroRIVERS,
MERIT-Hydro, or NHDPlus — anything geopandas can open) that carries a reach
id, a next-downstream id, and (optionally) reach length and catchment area.
It traces the sub-basin upstream from a chosen outlet and writes the four
files RAPID needs:

  rapid_connect.csv        reach_id down_id n_up up_1 ... up_n   (FULL domain)
  riv_bas_id.csv           one reach_id per line (sub-basin, routing order)
  rapid_catchment_file.csv reach_id,area_m2   (for convert_lsm_to_vlat)
  reach_properties.csv     reach_id,length_m  (for generate_muskingum_params)

Outlet convention (s1_connectivity.md "Traps"): the outlet reach gets
down_id = 0 in rapid_connect.csv so flow does not silently leave the domain.

Usage:
  python build_connectivity.py \\
    --river_network /path/to/HydroRIVERS_v10_as.gpkg \\
    --id_field HYRIV_ID --down_field NEXT_DOWN \\
    --length_field LENGTH_KM --length_units km \\
    --area_field UPLAND_SKM --area_units km2 \\
    --outlet_id 40012345 \\
    --outdir /path/to/workspace
"""

import argparse
import json
import os
import sys

import numpy as np

try:
    import geopandas as gpd
except Exception as exc:  # pragma: no cover
    print(f"ERROR: geopandas required to read the river network: {exc}",
          file=sys.stderr)
    sys.exit(2)

import networkx as nx


def load_network(path, id_field, down_field, length_field, area_field):
    gdf = gpd.read_file(path)
    for col in (id_field, down_field):
        if col not in gdf.columns:
            raise KeyError(f"Field '{col}' not in {path}; have {list(gdf.columns)}")
    rows = {}
    for _, r in gdf.iterrows():
        rid = int(r[id_field])
        down = int(r[down_field]) if r[down_field] not in (None, "") else 0
        # HydroSHEDS marks terminal/coastal sinks with NEXT_DOWN == 0; keep that.
        length = float(r[length_field]) if length_field and length_field in gdf.columns \
            and r[length_field] not in (None, "") else float("nan")
        area = float(r[area_field]) if area_field and area_field in gdf.columns \
            and r[area_field] not in (None, "") else float("nan")
        rows[rid] = {"down": down, "length": length, "area": area}
    return rows


def trace_subbasin(rows, outlet_id):
    """Collect every reach that drains to outlet_id (inclusive) via BFS upstream."""
    up = {}  # down_id -> [up_ids]
    for rid, rec in rows.items():
        up.setdefault(rec["down"], []).append(rid)
    sub = set()
    stack = [outlet_id]
    while stack:
        cur = stack.pop()
        if cur in sub:
            continue
        sub.add(cur)
        for u in up.get(cur, []):
            if u not in sub:
                stack.append(u)
    return sub


def topo_order(rows, sub):
    """Upstream-to-downstream topological order (headwaters first)."""
    g = nx.DiGraph()
    for rid in sub:
        g.add_node(rid)
    for rid in sub:
        d = rows[rid]["down"]
        if d in sub:
            g.add_edge(rid, d)
    try:
        return list(nx.topological_sort(g))
    except nx.NetworkXUnfeasible:
        print("WARNING: network has a cycle; falling back to id-sorted order",
              file=sys.stderr)
        return sorted(sub)


def write_outputs(rows, sub, outlet_id, length_units, area_units, outdir):
    os.makedirs(outdir, exist_ok=True)
    up = {}
    for rid, rec in rows.items():
        up.setdefault(rec["down"], []).append(rid)

    # rapid_connect.csv covers the FULL domain (s1_connectivity.md procedure step 4).
    max_up = 0
    connect_lines = []
    for rid in sorted(rows):
        ups = sorted(up.get(rid, []))
        max_up = max(max_up, len(ups))
        down = rows[rid]["down"]
        # Mark the chosen outlet (and reaches draining out of domain) as down_id 0.
        if rid == outlet_id or down not in rows:
            down = 0
        connect_lines.append(
            " ".join([str(rid), str(down), str(len(ups))] + [str(u) for u in ups]))
    with open(os.path.join(outdir, "rapid_connect.csv"), "w") as fh:
        fh.write("\n".join(connect_lines) + "\n")

    order = topo_order(rows, sub)
    with open(os.path.join(outdir, "riv_bas_id.csv"), "w") as fh:
        fh.write("\n".join(str(r) for r in order) + "\n")

    lfac = 1000.0 if length_units == "km" else 1.0
    afac = 1e6 if area_units in ("km2", "skm") else 1.0
    with open(os.path.join(outdir, "reach_properties.csv"), "w") as fh:
        for r in order:
            L = rows[r]["length"]
            fh.write(f"{r} {(L * lfac) if L == L else ''}\n")
    with open(os.path.join(outdir, "rapid_catchment_file.csv"), "w") as fh:
        for r in order:
            A = rows[r]["area"]
            fh.write(f"{r} {(A * afac) if A == A else ''}\n")

    return {"IS_riv_tot": len(rows), "IS_riv_bas": len(order),
            "IS_max_up": max_up, "outlet_id": outlet_id, "outdir": outdir}


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--river_network", required=True,
                   help="River network vector (gpkg/shp/geojson) geopandas can read")
    p.add_argument("--id_field", required=True, help="Reach id column (e.g. HYRIV_ID, COMID)")
    p.add_argument("--down_field", required=True, help="Next-downstream id column (e.g. NEXT_DOWN)")
    p.add_argument("--outlet_id", required=True, type=int, help="Reach id of the sub-basin outlet")
    p.add_argument("--length_field", default=None, help="Reach length column")
    p.add_argument("--length_units", default="km", choices=["km", "m"])
    p.add_argument("--area_field", default=None, help="Catchment / upland area column")
    p.add_argument("--area_units", default="km2", choices=["km2", "skm", "m2"])
    p.add_argument("--outdir", required=True, help="Output directory for the 4 CSVs")
    args = p.parse_args()

    rows = load_network(args.river_network, args.id_field, args.down_field,
                        args.length_field, args.area_field)
    if args.outlet_id not in rows:
        print(f"ERROR: outlet_id {args.outlet_id} not in network", file=sys.stderr)
        sys.exit(1)
    sub = trace_subbasin(rows, args.outlet_id)
    summary = write_outputs(rows, sub, args.outlet_id, args.length_units,
                            args.area_units, args.outdir)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
