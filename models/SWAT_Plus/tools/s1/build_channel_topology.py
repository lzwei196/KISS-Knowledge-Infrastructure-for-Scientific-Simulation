#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
====================================================
Tool ID:      build_channel_topology
Stage:        s1_watershed_delineation
Description:  Derive the REAL SWAT+ channel cascade from the D8 flow network and
              emit it as a reusable topology JSON.

Why this tool exists
--------------------
Before this tool, tools/s2/generate_hru_from_global.py hardcoded every channel's
downstream target as the literal constant 1, producing a one-hop "star": N-1
channels discharging directly into cha1, and cha1 discharging to nothing. A star
is NOT a distributed stream network -- SWAT+ ChannelRouting never executes as a
cascade, there is no travel-time lag and no floodplain attenuation, and the
outlet series is a lumped basin water-yield proxy even though the model runs
cleanly and can score a plausible NSE.

This tool derives, for every subbasin, which subbasin it actually drains into, by
tracing the D8 flow network downstream from that subbasin's outlet cell. It also
computes TRUE network-accumulated upstream area (not a running sum in id order),
Strahler order, reach length and reach slope.

Inputs (exactly ONE of --subbasin_shp / --subbasin_raster is required):
  --subbasin_shp   : Subbasin polygons. Must be the SAME partition that
                     generate_hru_from_global.py uses (it sorts sub_id and emits
                     cha{idx+1}); channel ids here are assigned the same way.
  --subbasin_raster: Subbasin id raster, e.g. the subbasins.tif written by
                     tools/s1/delineate_watershed.py (step 7,
                     `wbt.subbasins(fdir, streams_raster, subbasins_raster)`).
                     PREFERRED over the shapefile: that raster is produced ON the
                     flow-direction grid, so ids are used as-is with no
                     re-rasterization and no CRS/extent mismatch. Cell values are
                     the sub_ids (0/nodata = outside basin); local area comes from
                     exact cell counts. Polygons are derived internally (only for
                     adjacency repair, stream-length intersection and slope
                     masking) via rasterio.features.shapes.
  --dem_path       : DEM raster. Used to derive the flow network when
                     --flow_dir is not supplied.
  --flow_dir       : Optional pre-computed D8 pointer raster (e.g. the
                     flow_direction.tif written by delineate_watershed.py).
  --flow_acc       : Optional pre-computed D8 flow accumulation raster.
  --streams_shp    : Optional stream network; used for per-reach length.
  --pointer_convention : whitebox (default) or esri. These encodings DIFFER and
                     silently mis-trace if confused -- whitebox is
                     clockwise-from-east in powers of two (1=E,2=NE,4=N,...),
                     ESRI is clockwise-from-east too but 2=SE,4=S,8=SW,...
  --output         : Path for channel_topology.json.
  --repair_spurious_outlets : Opt-in. If the trace yields more than one terminal
                     channel (usually because a subbasin's outlet cell drains off
                     the clipped DEM edge), attach each spurious terminal to a
                     polygon-adjacent downstream neighbour instead of failing.
                     Every repair is logged as a loud WARNING.

Output JSON:
  {
    "<channel_id>": {
        "sub_id": int,
        "downstream_id": int|null,      # null ONLY for the single terminal
        "local_area_ha": float,
        "upstream_accumulated_area_ha": float,
        "strahler_order": int,
        "length_km": float,
        "length_source": "stream_geometry"|"local_area_fallback",
        "slope": float
    }, ...
  }
  plus a "_meta" block with basin area, outlet id and validation results.

Which quantity sizes what (read this before changing the geometry writers)
------------------------------------------------------------------------
  CHW / CHD (width, depth) <- upstream_accumulated_area_ha. These scale with the
      discharge the reach CONVEYS, so they MUST come from network-accumulated
      area. Sizing them from local subbasin area is the defect that made the
      Xixian outlet a rivulet.
  CHL (reach length)       <- length_km, which is the length of stream network
      lying INSIDE that subbasin. Reach length is a LOCAL geometric property of
      the subbasin partition, not a function of accumulated area: a headwater
      subbasin and a downstream subbasin of the same size hold similar lengths of
      channel regardless of what drains through them. Deriving CHL from
      accumulated area would make every downstream reach spuriously longer and
      would double-count travel time down the cascade. When no stream geometry is
      available the fallback is 1.3*sqrt(local_area) (a basin-length relation,
      still local, flagged as length_source="local_area_fallback").
  CHS (slope)              <- local DEM relief over reach length. Also local.

Validation performed BEFORE writing (hard failures, exit 2):
  - exactly one channel has downstream_id null
  - the graph is acyclic
  - the terminal channel's accumulated area equals basin area within --area_tol

Exit codes: 0=success, 1=input error, 2=processing/validation error, 3=output error
"""

import sys
import os
import json
import logging
import argparse
import tempfile
from collections import defaultdict
from pathlib import Path

import numpy as np

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# D8 pointer encodings. (drow, dcol) with row increasing SOUTHWARD.
# WhiteboxTools D8Pointer: clockwise from east, powers of two.
# ESRI D8: clockwise from east, but starting E,SE,S,SW,...
# Mixing these silently produces a plausible-looking but wrong network.
# ---------------------------------------------------------------------------
WHITEBOX_D8 = {
    1: (0, 1),     # E
    2: (-1, 1),    # NE
    4: (-1, 0),    # N
    8: (-1, -1),   # NW
    16: (0, -1),   # W
    32: (1, -1),   # SW
    64: (1, 0),    # S
    128: (1, 1),   # SE
}

ESRI_D8 = {
    1: (0, 1),     # E
    2: (1, 1),     # SE
    4: (1, 0),     # S
    8: (1, -1),    # SW
    16: (0, -1),   # W
    32: (-1, -1),  # NW
    64: (-1, 0),   # N
    128: (-1, 1),  # NE
}


def parse_args():
    p = argparse.ArgumentParser(
        description="Derive SWAT+ channel cascade from the D8 flow network.")
    p.add_argument("--subbasin_shp", default="",
                   help="Subbasin polygons. Mutually exclusive with "
                        "--subbasin_raster; exactly one is required.")
    p.add_argument("--subbasin_raster", default="",
                   help="Subbasin id raster (e.g. subbasins.tif from "
                        "delineate_watershed.py). Preferred: already on the "
                        "flow-direction grid.")
    p.add_argument("--dem_path", default="")
    p.add_argument("--flow_dir", default="")
    p.add_argument("--flow_acc", default="")
    p.add_argument("--streams_shp", default="")
    p.add_argument("--output", required=True)
    p.add_argument("--work_dir", default="")
    p.add_argument("--pointer_convention", default="whitebox",
                   choices=["whitebox", "esri"])
    p.add_argument("--area_tol", type=float, default=0.01,
                   help="Terminal accumulated area must match basin area within "
                        "this relative tolerance (default 0.01 = 1%%).")
    p.add_argument("--repair_spurious_outlets", action="store_true")
    p.add_argument("--max_trace_steps", type=int, default=2_000_000)
    return p.parse_args()


def validate_inputs(args):
    errors = []
    if bool(args.subbasin_shp) == bool(args.subbasin_raster):
        errors.append("Exactly ONE of --subbasin_shp / --subbasin_raster is "
                      f"required (got subbasin_shp={args.subbasin_shp!r}, "
                      f"subbasin_raster={args.subbasin_raster!r})")
    if args.subbasin_shp and not Path(args.subbasin_shp).exists():
        errors.append(f"Subbasin shapefile not found: {args.subbasin_shp}")
    if args.subbasin_raster and not Path(args.subbasin_raster).exists():
        errors.append(f"Subbasin raster not found: {args.subbasin_raster}")
    if not args.flow_dir:
        if not args.dem_path or not Path(args.dem_path).exists():
            errors.append("Either --flow_dir or an existing --dem_path is required "
                          f"(got dem_path={args.dem_path!r})")
    elif not Path(args.flow_dir).exists():
        errors.append(f"Flow direction raster not found: {args.flow_dir}")
    if args.flow_acc and not Path(args.flow_acc).exists():
        errors.append(f"Flow accumulation raster not found: {args.flow_acc}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


# ---------------------------------------------------------------------------
# Flow network
# ---------------------------------------------------------------------------
def derive_flow_network(dem_path, work_dir):
    """Run WhiteboxTools to produce a D8 pointer + accumulation from the DEM."""
    import whitebox

    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)

    wbt = whitebox.WhiteboxTools()
    wbt.set_verbose_mode(False)
    wbt.set_working_dir(str(work))

    filled = str(work / "topo_dem_filled.tif")
    fdir = str(work / "topo_flow_direction.tif")
    facc = str(work / "topo_flow_accumulation.tif")

    logger.info("Deriving flow network with WhiteboxTools (breach -> d8 pointer -> d8 accum)")
    wbt.breach_depressions(str(Path(dem_path).resolve()), filled)
    wbt.d8_pointer(filled, fdir)
    wbt.d8_flow_accumulation(filled, facc, out_type="cells")

    for pth in (fdir, facc):
        if not Path(pth).exists():
            raise RuntimeError(f"WhiteboxTools did not produce {pth}")
    # WhiteboxTools always writes its native pointer encoding.
    return fdir, facc, "whitebox"


def load_subbasins_from_raster(subbasin_raster, ref_transform, ref_crs, shape):
    """Read a subbasin id raster that is ALREADY on the flow-direction grid.

    Returns (channel_id_array, records) with exactly the same contract as
    rasterize_subbasins(), so the rest of the pipeline is input-agnostic.

    Channel ids follow generate_hru_from_global.py: sorted sub_id -> cha{idx+1}.
    Polygons are vectorized only so adjacency repair, stream-length intersection
    and slope masking keep working; the id grid itself is used as read, with no
    re-rasterization, which is why this path cannot suffer a CRS/extent mismatch.
    """
    import geopandas as gpd
    import rasterio
    from rasterio import features
    from shapely.geometry import shape as shapely_shape
    from shapely.ops import unary_union

    with rasterio.open(subbasin_raster) as src:
        arr = src.read(1)
        rast_transform = src.transform
        rast_crs = src.crs
        rast_nodata = src.nodata

    if arr.shape != shape:
        raise RuntimeError(
            f"Subbasin raster {subbasin_raster} has shape {arr.shape} but the "
            f"flow-direction grid has shape {shape}. --subbasin_raster must be "
            "on the SAME grid as the flow network (subbasins.tif from "
            "delineate_watershed.py is, because wbt.subbasins() is run on that "
            "very flow-direction raster). Use --subbasin_shp instead if the "
            "grids genuinely differ.")
    if rast_transform != ref_transform:
        raise RuntimeError(
            f"Subbasin raster {subbasin_raster} has affine transform "
            f"{rast_transform} but the flow-direction grid has {ref_transform}. "
            "Same shape but a different transform means the grids are offset; "
            "refusing to trace a mis-registered network.")

    invalid = {0}
    if rast_nodata is not None and not (isinstance(rast_nodata, float)
                                        and np.isnan(rast_nodata)):
        invalid.add(int(rast_nodata))

    sub_ids = sorted(int(v) for v in np.unique(arr) if int(v) not in invalid)
    if not sub_ids:
        raise RuntimeError(f"Subbasin raster {subbasin_raster} contains no valid "
                           "subbasin ids (all cells are 0/nodata).")

    # Remap raw sub_id -> channel_id (sorted order), matching the shapefile path.
    remap = {sid: idx + 1 for idx, sid in enumerate(sub_ids)}
    burned = np.zeros(arr.shape, dtype="int32")
    for sid, cid in remap.items():
        burned[arr == sid] = cid

    # Vectorize each subbasin once, for the geometry-dependent steps only.
    polys = defaultdict(list)
    for geom, val in features.shapes(burned, mask=(burned > 0),
                                     transform=rast_transform):
        polys[int(val)].append(shapely_shape(geom))

    geoms = {cid: unary_union(parts) for cid, parts in polys.items()}
    missing = [cid for cid in remap.values() if cid not in geoms]
    if missing:
        raise RuntimeError(f"Vectorization lost channel(s) {missing} from "
                           f"{subbasin_raster}")

    gs = gpd.GeoSeries([geoms[idx + 1] for idx in range(len(sub_ids))],
                       crs=rast_crs)
    local_area_ha = (gs.to_crs(epsg=6933).area / 10000.0).tolist()

    records = []
    for idx, sid in enumerate(sub_ids):
        records.append({
            "channel_id": idx + 1,
            "sub_id": int(sid),
            "local_area_ha": float(local_area_ha[idx]),
            "geometry": geoms[idx + 1],
            "crs": rast_crs,
        })

    logger.info("Loaded %d subbasins directly from raster %s (no "
                "re-rasterization; %d cells in basin)",
                len(records), subbasin_raster, int((burned > 0).sum()))
    return burned, records


def rasterize_subbasins(subbasin_shp, ref_profile, ref_transform, ref_crs, shape):
    """Burn subbasin ids onto the flow-network grid. Returns (id_array, records)."""
    import geopandas as gpd
    from rasterio import features

    gdf = gpd.read_file(subbasin_shp)
    if gdf.empty:
        raise RuntimeError(f"Subbasin shapefile is empty: {subbasin_shp}")

    if "sub_id" in gdf.columns:
        gdf = gdf.sort_values("sub_id").reset_index(drop=True)
        sub_ids = [int(v) for v in gdf["sub_id"].tolist()]
    else:
        logger.warning("No 'sub_id' column in %s -- using 1..N in file order. "
                       "This MUST match the sub_id ordering used by "
                       "generate_hru_from_global.py or channel numbering will "
                       "desynchronize from the HRU grouping.", subbasin_shp)
        sub_ids = list(range(1, len(gdf) + 1))
        gdf["sub_id"] = sub_ids

    if ref_crs is not None and gdf.crs is not None and gdf.crs != ref_crs:
        gdf = gdf.to_crs(ref_crs)

    # Equal-area local area per subbasin (ha)
    gdf_ea = gdf.to_crs(epsg=6933)
    local_area_ha = (gdf_ea.geometry.area / 10000.0).tolist()

    # channel_id follows generate_hru_from_global.py: sorted sub_id -> cha{idx+1}
    shapes = [(geom, idx + 1) for idx, geom in enumerate(gdf.geometry)]
    burned = features.rasterize(
        shapes, out_shape=shape, transform=ref_transform,
        fill=0, dtype="int32", all_touched=False)

    records = []
    for idx, sid in enumerate(sub_ids):
        records.append({
            "channel_id": idx + 1,
            "sub_id": int(sid),
            "local_area_ha": float(local_area_ha[idx]),
            "geometry": gdf.geometry.iloc[idx],
            "crs": gdf.crs,
        })

    n_burned = int((burned > 0).sum())
    logger.info("Rasterized %d subbasins onto the flow grid (%d cells burned)",
                len(records), n_burned)
    if n_burned == 0:
        raise RuntimeError("No subbasin cells burned onto the flow grid -- CRS or "
                           "extent mismatch between the subbasin shapefile and the "
                           "flow direction raster.")
    return burned, records


def trace_downstream(fdir, subid_grid, start_rc, offsets, nodata_dirs,
                     max_steps):
    """Step downstream from start_rc until entering a DIFFERENT subbasin.

    Returns (downstream_channel_id, exited_domain). downstream is None when the
    trace leaves the grid or hits nodata without ever entering another subbasin.
    """
    nrows, ncols = fdir.shape
    r, c = start_rc
    home = int(subid_grid[r, c])
    steps = 0
    while steps < max_steps:
        steps += 1
        d = int(fdir[r, c])
        if d in nodata_dirs or d not in offsets:
            return None, True
        dr, dc = offsets[d]
        r, c = r + dr, c + dc
        if r < 0 or r >= nrows or c < 0 or c >= ncols:
            return None, True
        sid = int(subid_grid[r, c])
        if sid != 0 and sid != home:
            return sid, False
    logger.warning("Trace exceeded max_steps from cell %s -- treating as terminal",
                   start_rc)
    return None, True


def build_topology(args):
    import rasterio

    work_dir = args.work_dir or tempfile.mkdtemp(prefix="chtopo_")

    convention = args.pointer_convention
    if args.flow_dir:
        fdir_path, facc_path = args.flow_dir, args.flow_acc
        logger.info("Reusing supplied flow network: %s", fdir_path)
    else:
        fdir_path, facc_path, convention = derive_flow_network(args.dem_path, work_dir)
        logger.info("Pointer convention forced to '%s' (produced by WhiteboxTools)",
                    convention)

    offsets = WHITEBOX_D8 if convention == "whitebox" else ESRI_D8
    logger.info("Using %s D8 pointer encoding", convention)

    with rasterio.open(fdir_path) as src:
        fdir = src.read(1)
        transform = src.transform
        crs = src.crs
        profile = src.profile
        fdir_nodata = src.nodata

    # A pointer cell is USABLE only if its value is one of the 8 direction codes
    # of the declared convention. Everything else is a sink/edge/nodata sentinel:
    # WhiteboxTools writes -1, and MERIT-Hydro (the right flow network for flat
    # basins like the Huai, where D8 on a coarse DEM is noise) writes 0 at river
    # mouths, -1 at inland depressions and -9 for undefined/ocean. Enumerating
    # sentinels one by one has silently mis-traced before; invert the test and
    # accept only known-good codes.
    nodata_dirs = {0, -1, -9}
    if fdir_nodata is not None and not np.isnan(fdir_nodata):
        nodata_dirs.add(int(fdir_nodata))
    valid_dir_mask = np.isin(fdir, list(offsets.keys()))
    n_valid = int(valid_dir_mask.sum())
    logger.info("Flow-direction grid: %d/%d cells carry a valid %s direction code",
                n_valid, fdir.size, convention)
    if n_valid == 0:
        raise RuntimeError(
            f"No cell in {fdir_path} carries a valid {convention} D8 code "
            f"{sorted(offsets.keys())}. Observed values: "
            f"{sorted(set(np.unique(fdir).tolist()))[:12]}. The "
            "--pointer_convention is almost certainly wrong for this raster.")

    if facc_path and Path(facc_path).exists():
        with rasterio.open(facc_path) as src:
            facc = src.read(1).astype("float64")
        if facc.shape != fdir.shape:
            raise RuntimeError("flow_acc and flow_dir grids have different shapes")
    else:
        logger.warning("No flow accumulation raster -- outlet cells will be chosen "
                       "by downstream-most position rather than max accumulation.")
        facc = None

    if args.subbasin_raster:
        subid_grid, records = load_subbasins_from_raster(
            args.subbasin_raster, transform, crs, fdir.shape)
    else:
        subid_grid, records = rasterize_subbasins(
            args.subbasin_shp, profile, transform, crs, fdir.shape)

    # ---- outlet cell per subbasin = max flow accumulation within the polygon ----
    downstream = {}
    outlet_cells = {}
    for rec in records:
        cid = rec["channel_id"]
        mask = (subid_grid == cid)
        # Accept only cells whose pointer is a real direction code (see
        # valid_dir_mask above). Excluding an enumerated sentinel list instead
        # would let an unknown sentinel be chosen as the outlet cell, and the
        # trace from it would terminate immediately -- fabricating a terminal.
        valid = mask & valid_dir_mask
        if not valid.any():
            logger.warning("Channel %d has no valid flow-direction cells -- it will "
                           "be treated as terminal unless repaired.", cid)
            downstream[cid] = None
            outlet_cells[cid] = None
            continue
        idxs = np.argwhere(valid)
        if facc is not None:
            best = idxs[np.argmax(facc[valid])]
        else:
            best = idxs[-1]
        rc = (int(best[0]), int(best[1]))
        outlet_cells[cid] = rc
        ds, _exited = trace_downstream(fdir, subid_grid, rc, offsets,
                                       nodata_dirs, args.max_trace_steps)
        downstream[cid] = ds

    # ---- terminal resolution ----
    terminals = [cid for cid, ds in downstream.items() if ds is None]
    logger.info("Initial trace produced %d terminal channel(s): %s",
                len(terminals), terminals)

    if len(terminals) > 1:
        if not args.repair_spurious_outlets:
            logger.error(
                "Flow trace produced %d terminal channels (%s) but a SWAT+ deck "
                "must have exactly ONE (s9/extract_discharge auto-detects the "
                "scored outlet as the channel with out_tot==0). This usually means "
                "some subbasin outlets drain off the clipped DEM edge. Re-run with "
                "--repair_spurious_outlets to attach them to a polygon-adjacent "
                "downstream neighbour, or fix the DEM clip.",
                len(terminals), terminals)
            sys.exit(2)
        downstream = repair_terminals(downstream, terminals, records, facc,
                                      outlet_cells)
        terminals = [cid for cid, ds in downstream.items() if ds is None]

    if len(terminals) != 1:
        logger.error("Could not reduce to exactly one terminal channel (have %s)",
                     terminals)
        sys.exit(2)
    outlet_id = terminals[0]
    logger.info("Terminal (scored outlet) channel: cha%d", outlet_id)

    # ---- acyclicity ----
    for cid in downstream:
        seen = set()
        cur = cid
        while cur is not None:
            if cur in seen:
                logger.error("Cycle detected in channel topology starting at cha%d "
                             "(revisited cha%d). The deck would route water in a "
                             "loop.", cid, cur)
                sys.exit(2)
            seen.add(cur)
            cur = downstream[cur]
    logger.info("Acyclicity check passed (%d channels)", len(downstream))

    # ---- network-accumulated upstream area (topological, NOT id order) ----
    local = {r["channel_id"]: r["local_area_ha"] for r in records}
    upstream_of = {cid: [] for cid in downstream}
    for cid, ds in downstream.items():
        if ds is not None:
            upstream_of[ds].append(cid)

    accum = {}

    def accumulate(cid):
        if cid in accum:
            return accum[cid]
        total = local[cid] + sum(accumulate(u) for u in upstream_of[cid])
        accum[cid] = total
        return total

    sys.setrecursionlimit(max(10000, len(downstream) * 20))
    for cid in downstream:
        accumulate(cid)

    basin_area_ha = sum(local.values())
    rel_err = abs(accum[outlet_id] - basin_area_ha) / basin_area_ha if basin_area_ha else 1.0
    if rel_err > args.area_tol:
        logger.error("Terminal channel accumulated area %.2f ha does not match basin "
                     "area %.2f ha (rel err %.4f > tol %.4f). The network does not "
                     "drain everything to one outlet.",
                     accum[outlet_id], basin_area_ha, rel_err, args.area_tol)
        sys.exit(2)
    logger.info("Accumulated-area check passed: outlet %.1f ha vs basin %.1f ha "
                "(rel err %.5f)", accum[outlet_id], basin_area_ha, rel_err)

    # ---- Strahler order ----
    order = {}

    def strahler(cid):
        if cid in order:
            return order[cid]
        ups = upstream_of[cid]
        if not ups:
            order[cid] = 1
        else:
            child = sorted((strahler(u) for u in ups), reverse=True)
            if len(child) >= 2 and child[0] == child[1]:
                order[cid] = child[0] + 1
            else:
                order[cid] = child[0]
        return order[cid]

    for cid in downstream:
        strahler(cid)

    # ---- reach length + slope ----
    lengths, length_sources = reach_lengths(records, args.streams_shp)
    slopes = reach_slopes(records, outlet_cells, args.dem_path, lengths)

    topology = {}
    for rec in records:
        cid = rec["channel_id"]
        topology[str(cid)] = {
            "sub_id": rec["sub_id"],
            "downstream_id": downstream[cid],
            "local_area_ha": round(local[cid], 4),
            "upstream_accumulated_area_ha": round(accum[cid], 4),
            "strahler_order": int(order[cid]),
            "length_km": round(lengths[cid], 5),
            "length_source": length_sources[cid],
            "slope": round(slopes[cid], 6),
        }

    topology["_meta"] = {
        "tool": "build_channel_topology",
        "subbasin_source": str(args.subbasin_raster or args.subbasin_shp),
        "subbasin_source_kind": "raster" if args.subbasin_raster else "shapefile",
        "n_length_from_stream_geometry": sum(
            1 for s in length_sources.values() if s == "stream_geometry"),
        "n_length_from_local_area_fallback": sum(
            1 for s in length_sources.values() if s == "local_area_fallback"),
        "sizing_contract": ("CHW/CHD from upstream_accumulated_area_ha; "
                            "CHL from local in-subbasin stream length; "
                            "CHS from local DEM relief"),
        "flow_dir": str(fdir_path),
        "pointer_convention": convention,
        "n_channels": len(records),
        "outlet_channel_id": outlet_id,
        "basin_area_ha": round(basin_area_ha, 4),
        "outlet_accumulated_area_ha": round(accum[outlet_id], 4),
        "area_rel_err": round(rel_err, 6),
        "max_strahler_order": int(max(order.values())),
        "validation": {
            "single_terminal": True,
            "acyclic": True,
            "outlet_area_matches_basin": True,
        },
    }
    return topology


def repair_terminals(downstream, terminals, records, facc, outlet_cells):
    """Attach spurious terminals to a polygon-adjacent neighbour. Loud by design."""
    geoms = {r["channel_id"]: r["geometry"] for r in records}
    areas = {r["channel_id"]: r["local_area_ha"] for r in records}

    # True outlet = terminal draining the largest local area (best proxy without
    # a completed accumulation pass).
    keep = max(terminals, key=lambda c: areas.get(c, 0.0))
    logger.warning("REPAIR: keeping cha%d as the true terminal; re-attaching %d "
                   "spurious terminal(s).", keep, len(terminals) - 1)

    def is_upstream_of(candidate, node, ds_map):
        cur = ds_map[candidate]
        seen = set()
        while cur is not None and cur not in seen:
            if cur == node:
                return True
            seen.add(cur)
            cur = ds_map[cur]
        return False

    for cid in terminals:
        if cid == keep:
            continue
        neighbours = [other for other in geoms
                      if other != cid and geoms[other].touches(geoms[cid])]
        neighbours = [n for n in neighbours if not is_upstream_of(n, cid, downstream)]
        if not neighbours:
            logger.error("REPAIR FAILED: cha%d has no non-upstream adjacent "
                         "neighbour to drain into.", cid)
            continue
        target = max(neighbours, key=lambda n: areas.get(n, 0.0))
        downstream[cid] = target
        logger.warning("REPAIR: cha%d had no in-domain downstream cell (drains off "
                       "the DEM edge); attached to adjacent cha%d. This edge is "
                       "NOT flow-network-derived -- verify the DEM clip.",
                       cid, target)
    return downstream


def reach_lengths(records, streams_shp):
    """Per-subbasin reach length (km). Prefers real stream geometry.

    Reach length is deliberately a LOCAL quantity -- the length of stream lying
    inside this subbasin -- NOT a function of network-accumulated area. See the
    'Which quantity sizes what' block in the module docstring: accumulated area
    sizes width/depth, never length. Returns (lengths, sources) so the JSON can
    record, per channel, whether the length came from real stream geometry or
    from the local-area fallback.
    """
    lengths = {}
    sources = {}
    stream_gdf = None
    if streams_shp and Path(streams_shp).exists():
        try:
            import geopandas as gpd
            stream_gdf = gpd.read_file(streams_shp).to_crs(epsg=6933)
        except Exception as e:
            logger.warning("Could not read streams shapefile (%s) -- falling back "
                           "to area-based reach length.", e)
            stream_gdf = None

    if stream_gdf is not None:
        import geopandas as gpd
        for rec in records:
            try:
                poly = gpd.GeoSeries([rec["geometry"]], crs=rec["crs"]) \
                          .to_crs(epsg=6933).iloc[0]
                total_m = float(stream_gdf.intersection(poly).length.sum())
            except Exception:
                total_m = 0.0
            if total_m > 0:
                lengths[rec["channel_id"]] = total_m / 1000.0
                sources[rec["channel_id"]] = "stream_geometry"
    for rec in records:
        cid = rec["channel_id"]
        if cid not in lengths or lengths[cid] <= 0:
            # Local basin-length relation L ~ 1.3*sqrt(A_local). Still LOCAL --
            # accumulated area is never used for length.
            area_km2 = rec["local_area_ha"] / 100.0
            lengths[cid] = max(0.5, (area_km2 ** 0.5) * 1.3)
            sources[cid] = "local_area_fallback"
    n_fb = sum(1 for s in sources.values() if s == "local_area_fallback")
    if n_fb:
        logger.warning("%d/%d reach lengths fell back to the local-area relation "
                       "(no usable stream geometry). They are flagged "
                       "length_source='local_area_fallback' in the topology JSON.",
                       n_fb, len(records))
    return lengths, sources


def reach_slopes(records, outlet_cells, dem_path, lengths):
    """Per-reach slope from the DEM relief within the subbasin over reach length."""
    slopes = {r["channel_id"]: 0.001 for r in records}
    if not dem_path or not Path(dem_path).exists():
        logger.warning("No DEM available for reach slope -- defaulting to 0.001 m/m")
        return slopes
    try:
        import rasterio
        import geopandas as gpd
        from rasterio.mask import mask as rio_mask
        with rasterio.open(dem_path) as src:
            nodata = src.nodata
            for rec in records:
                cid = rec["channel_id"]
                try:
                    geom = rec["geometry"]
                    if src.crs is not None and rec["crs"] is not None \
                            and rec["crs"] != src.crs:
                        geom = gpd.GeoSeries([geom], crs=rec["crs"]) \
                                  .to_crs(src.crs).iloc[0]
                    arr, _ = rio_mask(src, [geom], crop=True, filled=True)
                    band = arr[0].astype("float64")
                    if nodata is not None:
                        band = band[band != nodata]
                    band = band[np.isfinite(band)]
                    if band.size < 2:
                        continue
                    relief = float(np.percentile(band, 90) - np.percentile(band, 10))
                    length_m = max(1.0, lengths[cid] * 1000.0)
                    slopes[cid] = max(0.0001, min(0.5, relief / length_m))
                except Exception:
                    continue
    except Exception as e:
        logger.warning("Reach slope computation failed (%s) -- defaulting to 0.001", e)
    return slopes


def main():
    args = parse_args()
    logger.info("Running tool: %s", os.path.basename(__file__))
    validate_inputs(args)
    try:
        topology = build_topology(args)
    except SystemExit:
        raise
    except Exception as e:
        logger.exception("Processing failed: %s", e)
        sys.exit(2)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        out.write_text(json.dumps(topology, indent=2))
    except Exception as e:
        logger.error("Could not write %s: %s", out, e)
        sys.exit(3)

    if not out.exists():
        logger.error("Expected output not created: %s", out)
        sys.exit(3)

    meta = topology["_meta"]
    logger.info("Wrote %s (%d channels, outlet=cha%d, max order=%d)",
                out, meta["n_channels"], meta["outlet_channel_id"],
                meta["max_strahler_order"])
    print(json.dumps({"status": "success",
                      "channel_topology": str(out),
                      **meta}, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
