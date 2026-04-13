#!/usr/bin/env python3
"""
build_spatial_weights.py  --  WRF-Hydro Phase 2, Tool 4
=======================================================
Build spatialweights.nc — the LSM-to-channel mapping file required
for reach-based routing (channel_option=1 or 2) with UDMP_OPT=1.

The file maps each channel reach/link (from Route_Link.nc) to the LSM
grid cells that contribute runoff, along with area-fraction weights.

Algorithm:
  1. Read Fulldom_hires.nc (routing grid) and Route_Link.nc (link IDs)
  2. Build upstream catchment for each link by tracing flow direction
     upstream from each channel cell
  3. Map routing-grid catchments onto the coarser LSM grid (geo_em)
  4. Compute weight (fraction of catchment in each LSM cell) and
     regridweight (fraction of LSM cell covered by each catchment)
  5. Write CF-compliant spatialweights.nc

NetCDF structure (WRF-Hydro Appendix A13):
  Dimensions:
    polyid  — number of links/reaches
    data    — total number of LSM-cell-to-link mapping records
  Variables:
    polyid      (polyid)  i4  — link ID for each reach
    IDmask      (data)    i4  — link ID associated with each record
    overlaps    (polyid)  i4  — number of LSM cells per link
    weight      (data)    f8  — fraction of catchment area in this LSM cell
    regridweight(data)    f8  — fraction of LSM cell area in this catchment
    i_index     (data)    i4  — 1-based x index into LSM grid (LL corner)
    j_index     (data)    i4  — 1-based y index into LSM grid (LL corner)

Weight conventions (verified against NWM example):
  - weight sums to 1.0 per polyid (link)
  - regridweight sums to 1.0 per (i_index, j_index) LSM cell

Usage
-----
    python build_spatial_weights.py \\
        --fulldom  DOMAIN/Fulldom_hires.nc \\
        --geo_em   DOMAIN/geo_em.d01.nc \\
        --route_link DOMAIN/Route_Link.nc \\
        --output   DOMAIN/spatialweights.nc
"""

import argparse
import os
import sys
from collections import defaultdict
from pathlib import Path

import netCDF4 as nc
import numpy as np


# ArcGIS D8 flow direction encoding
#   1=E, 2=SE, 4=S, 8=SW, 16=W, 32=NW, 64=N, 128=NE
# Maps flow direction code -> (row_offset, col_offset)
# Row increases downward (south), col increases rightward (east)
ARCGIS_D8_OFFSETS = {
    1:   (0,  1),    # E
    2:   (1,  1),    # SE
    4:   (1,  0),    # S
    8:   (1, -1),    # SW
    16:  (0, -1),    # W
    32:  (-1, -1),   # NW
    64:  (-1,  0),   # N
    128: (-1,  1),   # NE
}

# Reverse D8: for each direction code, the code that points back
REVERSE_D8 = {
    1:   16,    # E  <- W
    2:   32,    # SE <- NW
    4:   64,    # S  <- N
    8:   128,   # SW <- NE
    16:  1,     # W  <- E
    32:  2,     # NW <- SE
    64:  4,     # N  <- S
    128: 8,     # NE <- SW
}


def detect_aggfactrt(fulldom_path, geo_em_path):
    """Detect AGGFACTRT from grid dimension ratios.

    Parameters
    ----------
    fulldom_path : str
        Path to Fulldom_hires.nc.
    geo_em_path : str
        Path to geo_em.d01.nc.

    Returns
    -------
    aggfactrt : int
        Aggregation factor (routing cells per LSM cell, per dimension).
    ny_rt, nx_rt : int
        Routing grid dimensions.
    e_sn, e_we : int
        LSM grid dimensions.
    """
    ds_fd = nc.Dataset(fulldom_path, "r")
    ny_rt = len(ds_fd.dimensions["y"])
    nx_rt = len(ds_fd.dimensions["x"])
    ds_fd.close()

    ds_ge = nc.Dataset(geo_em_path, "r")
    e_sn = len(ds_ge.dimensions["south_north"])
    e_we = len(ds_ge.dimensions["west_east"])
    ds_ge.close()

    agg_y = ny_rt // e_sn
    agg_x = nx_rt // e_we

    if agg_y != agg_x:
        print(f"[SpatialWeights] WARNING: AGGFACTRT differs in y ({agg_y}) "
              f"and x ({agg_x}). Using y value.", file=sys.stderr)

    if ny_rt % e_sn != 0 or nx_rt % e_we != 0:
        print(f"[SpatialWeights] WARNING: Routing grid ({ny_rt}x{nx_rt}) is "
              f"not an exact multiple of LSM grid ({e_sn}x{e_we}).",
              file=sys.stderr)

    aggfactrt = agg_y
    return aggfactrt, ny_rt, nx_rt, e_sn, e_we


def build_upstream_catchments(channelgrid, flowdir, ny_rt, nx_rt):
    """Assign each routing grid cell to its nearest downstream channel cell.

    Uses upstream tracing from each channel cell: for every cell in the
    routing grid, trace downstream until hitting a channel cell. That
    channel cell's link "owns" the routing cell.

    Parameters
    ----------
    channelgrid : ndarray (ny_rt, nx_rt), int
        CHANNELGRID array. 0 = channel cell, -9999 = non-channel.
    flowdir : ndarray (ny_rt, nx_rt), int
        ArcGIS D8 flow direction.
    ny_rt, nx_rt : int
        Routing grid dimensions.

    Returns
    -------
    catchment_map : ndarray (ny_rt, nx_rt), int
        For each cell, the (flattened) index of the channel cell it
        drains to. -1 if it does not drain to any channel cell.
    chan_indices : list of int
        Flattened indices of all channel cells.
    """
    chan_mask = (channelgrid == 0)
    catchment_map = np.full((ny_rt, nx_rt), -1, dtype=np.int32)

    # Channel cells drain to themselves
    chan_rows, chan_cols = np.where(chan_mask)
    for r, c in zip(chan_rows, chan_cols):
        catchment_map[r, c] = r * nx_rt + c

    chan_flat_set = set(int(r * nx_rt + c) for r, c in zip(chan_rows, chan_cols))

    # For non-channel cells, trace downstream until hitting a channel cell
    # Use caching: once we know where a cell drains, store it
    for r in range(ny_rt):
        for c in range(nx_rt):
            if catchment_map[r, c] >= 0:
                continue  # Already assigned

            # Trace downstream
            path = [(r, c)]
            cr, cc = r, c
            found = False

            while True:
                fd = int(flowdir[cr, cc])
                if fd not in ARCGIS_D8_OFFSETS:
                    break  # No valid flow direction

                dr, dc = ARCGIS_D8_OFFSETS[fd]
                nr, ncc = cr + dr, cc + dc

                if nr < 0 or nr >= ny_rt or ncc < 0 or ncc >= nx_rt:
                    break  # Flows out of domain

                # Check if we've already resolved this cell
                if catchment_map[nr, ncc] >= 0:
                    target = catchment_map[nr, ncc]
                    for pr, pc in path:
                        catchment_map[pr, pc] = target
                    found = True
                    break

                # Check for cycle (cell already in path)
                if (nr, ncc) in set(path):
                    break

                path.append((nr, ncc))
                cr, cc = nr, ncc

            # If we traced to a dead end without finding a channel,
            # these cells remain -1 (unassigned)

    chan_indices = [int(r * nx_rt + c) for r, c in zip(chan_rows, chan_cols)]
    return catchment_map, chan_indices


def build_spatial_weights(fulldom_path, geo_em_path, route_link_path,
                          output_path):
    """Build spatialweights.nc from Fulldom, geo_em, and Route_Link.

    Parameters
    ----------
    fulldom_path : str
        Path to Fulldom_hires.nc.
    geo_em_path : str
        Path to geo_em.d01.nc.
    route_link_path : str
        Path to Route_Link.nc.
    output_path : str
        Path to write spatialweights.nc.
    """
    # ------------------------------------------------------------------
    # 1. Read inputs
    # ------------------------------------------------------------------
    print(f"[SpatialWeights] Reading inputs...")
    print(f"  Fulldom:    {fulldom_path}")
    print(f"  geo_em:     {geo_em_path}")
    print(f"  Route_Link: {route_link_path}")

    # Detect AGGFACTRT
    aggfactrt, ny_rt, nx_rt, e_sn, e_we = detect_aggfactrt(
        fulldom_path, geo_em_path
    )
    print(f"  AGGFACTRT:  {aggfactrt}")
    print(f"  Routing grid: {ny_rt} x {nx_rt}")
    print(f"  LSM grid:     {e_sn} x {e_we}")

    # Read Fulldom
    ds_fd = nc.Dataset(fulldom_path, "r")
    channelgrid = ds_fd.variables["CHANNELGRID"][:]
    flowdir = ds_fd.variables["FLOWDIRECTION"][:]
    ds_fd.close()

    # Read Route_Link
    ds_rl = nc.Dataset(route_link_path, "r")
    link_ids = ds_rl.variables["link"][:]
    ds_rl.close()

    n_links = len(link_ids)
    n_channels = int((channelgrid == 0).sum())
    print(f"  Channel cells in Fulldom: {n_channels}")
    print(f"  Links in Route_Link:      {n_links}")

    if n_links != n_channels:
        print(f"[SpatialWeights] WARNING: Link count ({n_links}) differs from "
              f"channel cell count ({n_channels}). Using Route_Link link IDs.")

    # ------------------------------------------------------------------
    # 2. Build link_id map from channel cells
    # ------------------------------------------------------------------
    # Route_Link assigns link IDs in the same order as channel cells
    # extracted from Fulldom (row-major scan order), matching
    # build_route_link.py convention.
    chan_rows, chan_cols = np.where(channelgrid == 0)

    if len(chan_rows) != n_links:
        print(f"[SpatialWeights] WARNING: Adjusting — using first "
              f"{min(len(chan_rows), n_links)} matches.")

    # Map flat index of channel cell -> link_id
    chan_flat_to_link = {}
    for idx in range(min(len(chan_rows), n_links)):
        r, c = int(chan_rows[idx]), int(chan_cols[idx])
        flat_idx = r * nx_rt + c
        chan_flat_to_link[flat_idx] = int(link_ids[idx])

    # ------------------------------------------------------------------
    # 3. Build upstream catchments
    # ------------------------------------------------------------------
    print(f"[SpatialWeights] Building upstream catchments...")
    catchment_map, chan_indices = build_upstream_catchments(
        channelgrid, flowdir, ny_rt, nx_rt
    )

    n_assigned = int((catchment_map >= 0).sum())
    n_unassigned = ny_rt * nx_rt - n_assigned
    print(f"  Assigned cells:   {n_assigned}")
    print(f"  Unassigned cells: {n_unassigned} (boundary/inactive)")

    # ------------------------------------------------------------------
    # 4. Map catchments to LSM grid and compute weights
    # ------------------------------------------------------------------
    print(f"[SpatialWeights] Computing LSM cell overlaps...")

    # Index mapping:
    #   Routing grid y-axis is top-down (row 0 = north)
    #   LSM south_north is bottom-up (row 0 = south)
    #   j_index (1-based, starting from LL): j = (ny_rt - 1 - r_rt) // aggfactrt + 1
    #   i_index (1-based, starting from LL): i = c_rt // aggfactrt + 1

    # For each link, collect which LSM cells contribute and count
    # routing cells per (link, i, j) combination.
    # Also track total routing cells per link and per LSM cell.
    link_lsm_counts = defaultdict(lambda: defaultdict(int))
    link_total_cells = defaultdict(int)
    lsm_total_cells = defaultdict(int)

    # Total number of routing cells per LSM cell (for regridweight)
    cells_per_lsm = aggfactrt * aggfactrt

    for r_rt in range(ny_rt):
        for c_rt in range(nx_rt):
            chan_flat = catchment_map[r_rt, c_rt]
            if chan_flat < 0:
                continue  # Unassigned cell

            if chan_flat not in chan_flat_to_link:
                continue  # Channel cell not in Route_Link

            link_id = chan_flat_to_link[chan_flat]

            # Compute LSM indices (1-based)
            j_lsm = (ny_rt - 1 - r_rt) // aggfactrt + 1
            i_lsm = c_rt // aggfactrt + 1

            # Bounds check
            if j_lsm < 1 or j_lsm > e_sn or i_lsm < 1 or i_lsm > e_we:
                continue

            link_lsm_counts[link_id][(i_lsm, j_lsm)] += 1
            link_total_cells[link_id] += 1
            lsm_total_cells[(i_lsm, j_lsm)] += 1

    # ------------------------------------------------------------------
    # 5. Build output arrays
    # ------------------------------------------------------------------
    # Count total data records
    n_data = sum(len(cells) for cells in link_lsm_counts.values())
    n_poly = len(link_lsm_counts)
    print(f"  Links with LSM overlap: {n_poly}")
    print(f"  Total data records:     {n_data}")

    if n_data == 0:
        print("[SpatialWeights] ERROR: No LSM-to-link mappings found. "
              "Check that flow directions connect to channel cells.",
              file=sys.stderr)
        sys.exit(1)

    # Allocate output arrays
    out_polyid = np.zeros(n_poly, dtype=np.int32)
    out_overlaps = np.zeros(n_poly, dtype=np.int32)
    out_idmask = np.zeros(n_data, dtype=np.int32)
    out_weight = np.zeros(n_data, dtype=np.float64)
    out_regridweight = np.zeros(n_data, dtype=np.float64)
    out_i_index = np.zeros(n_data, dtype=np.int32)
    out_j_index = np.zeros(n_data, dtype=np.int32)

    # Sort link IDs to maintain deterministic order
    sorted_link_ids = sorted(link_lsm_counts.keys())

    data_idx = 0
    for poly_idx, link_id in enumerate(sorted_link_ids):
        lsm_cells = link_lsm_counts[link_id]
        total_catchment = link_total_cells[link_id]

        out_polyid[poly_idx] = link_id
        out_overlaps[poly_idx] = len(lsm_cells)

        for (i_lsm, j_lsm), count in sorted(lsm_cells.items()):
            out_idmask[data_idx] = link_id
            out_i_index[data_idx] = i_lsm
            out_j_index[data_idx] = j_lsm

            # weight: fraction of this link's catchment in this LSM cell
            out_weight[data_idx] = count / total_catchment

            # regridweight: fraction of this LSM cell covered by this
            # link's catchment
            out_regridweight[data_idx] = count / cells_per_lsm

            data_idx += 1

    # Verify weight sums
    for poly_idx, link_id in enumerate(sorted_link_ids):
        mask = out_idmask[:data_idx] == link_id
        w_sum = out_weight[:data_idx][mask].sum()
        if abs(w_sum - 1.0) > 0.01:
            print(f"[SpatialWeights] WARNING: weight sum for link "
                  f"{link_id} = {w_sum:.6f} (expected 1.0)")

    # ------------------------------------------------------------------
    # 6. Write spatialweights.nc
    # ------------------------------------------------------------------
    print(f"[SpatialWeights] Writing {output_path} ...")
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    out = nc.Dataset(output_path, "w", format="NETCDF4")

    # Dimensions
    out.createDimension("polyid", n_poly)
    out.createDimension("data", n_data)

    # Variables
    v = out.createVariable("polyid", "i4", ("polyid",))
    v.long_name = "ID of polygon"
    v[:] = out_polyid

    v = out.createVariable("overlaps", "i4", ("polyid",))
    v.long_name = "Number of intersecting polygons"
    v[:] = out_overlaps

    v = out.createVariable("IDmask", "i4", ("data",))
    v.long_name = ("Polygon ID (polyid) associated with each record")
    v[:] = out_idmask

    v = out.createVariable("weight", "f8", ("data",))
    v.long_name = ("fraction of polygon(polyid) intersected by "
                    "polygon identified by poly2")
    v[:] = out_weight

    v = out.createVariable("regridweight", "f8", ("data",))
    v.long_name = ("fraction of intersecting polyid(overlapper) "
                    "intersected by polygon(polyid)")
    v[:] = out_regridweight

    v = out.createVariable("i_index", "i4", ("data",))
    v.long_name = ("Index in the x dimension of the raster grid "
                    "(starting with 1,1 in LL corner)")
    v[:] = out_i_index

    v = out.createVariable("j_index", "i4", ("data",))
    v.long_name = ("Index in the y dimension of the raster grid "
                    "(starting with 1,1 in LL corner)")
    v[:] = out_j_index

    # Global attributes
    out.history = ("Created by build_spatial_weights.py "
                   "(HydroCraft WRF-Hydro KI)")
    out.Conventions = "CF-1.5"
    out.AGGFACTRT = aggfactrt
    out.routing_grid = f"{ny_rt}x{nx_rt}"
    out.lsm_grid = f"{e_sn}x{e_we}"

    out.close()

    # ------------------------------------------------------------------
    # 7. Summary
    # ------------------------------------------------------------------
    overlap_arr = out_overlaps
    weight_per_link = []
    for pid in sorted_link_ids:
        mask = out_idmask == pid
        weight_per_link.append(out_weight[mask].sum())
    weight_per_link = np.array(weight_per_link)

    # regridweight per LSM cell
    unique_ij = set(zip(out_i_index, out_j_index))
    rw_per_cell = []
    for i, j in unique_ij:
        mask = (out_i_index == i) & (out_j_index == j)
        rw_per_cell.append(out_regridweight[mask].sum())
    rw_per_cell = np.array(rw_per_cell)

    print(f"\n[SpatialWeights] === Summary ===")
    print(f"  Output:         {output_path}")
    print(f"  Links (polyid): {n_poly}")
    print(f"  Data records:   {n_data}")
    print(f"  Overlaps/link:  {overlap_arr.min()} – {overlap_arr.max()} "
          f"(mean {overlap_arr.mean():.1f})")
    print(f"  weight sum:     {weight_per_link.min():.6f} – "
          f"{weight_per_link.max():.6f} (should be 1.0)")
    print(f"  LSM cells used: {len(unique_ij)}")
    print(f"  i_index range:  {out_i_index.min()} – {out_i_index.max()}")
    print(f"  j_index range:  {out_j_index.min()} – {out_j_index.max()}")
    print(f"  regridweight/cell: {rw_per_cell.min():.6f} – "
          f"{rw_per_cell.max():.6f} (should be ≤1.0)")
    print(f"[SpatialWeights] Done.")

    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="Build spatialweights.nc for WRF-Hydro reach-based "
                    "routing (UDMP_OPT=1).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python build_spatial_weights.py \\
      --fulldom    DOMAIN/Fulldom_hires.nc \\
      --geo_em     DOMAIN/geo_em.d01.nc \\
      --route_link DOMAIN/Route_Link.nc \\
      --output     DOMAIN/spatialweights.nc

After generating, set in hydro.namelist:
  channel_option = 1       ! or 2
  UDMP_OPT = 1
  route_link_f = "./DOMAIN/Route_Link.nc"
  udmap_file   = "./DOMAIN/spatialweights.nc"
"""
    )
    parser.add_argument("--fulldom", required=True,
                        help="Path to Fulldom_hires.nc (routing grid)")
    parser.add_argument("--geo_em", required=True,
                        help="Path to geo_em.d01.nc (LSM grid)")
    parser.add_argument("--route_link", required=True,
                        help="Path to Route_Link.nc (link IDs)")
    parser.add_argument("--output", required=True,
                        help="Path to write spatialweights.nc")
    args = parser.parse_args()

    # Validate inputs
    for label, path in [("Fulldom", args.fulldom), ("geo_em", args.geo_em),
                        ("Route_Link", args.route_link)]:
        if not os.path.isfile(path):
            print(f"ERROR: {label} file not found: {path}", file=sys.stderr)
            sys.exit(1)

    build_spatial_weights(
        fulldom_path=args.fulldom,
        geo_em_path=args.geo_em,
        route_link_path=args.route_link,
        output_path=args.output,
    )


if __name__ == "__main__":
    main()
