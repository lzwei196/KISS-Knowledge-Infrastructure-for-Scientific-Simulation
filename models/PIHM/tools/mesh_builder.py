#!/usr/bin/env python3
"""
mesh_builder.py — S1 + S2: HEADLESS DEM -> PIHM TIN generator.

Produces `<project>.mesh`, `<project>.att` and `<project>.riv` for an arbitrary
watershed WITHOUT PIHMgis (the interactive QGIS plugin that MM-PIHM documents as
the only S1/S2 path, and which is not installable headlessly).

This closes the DOMAIN CONSTRAINT documented in SKILL.md (and triplets dt_021 /
dt_023): before this tool, PIHM could only be run on the two basins that ship a
prebuilt mesh (ShaleHills, Chimborazo).

Pipeline
--------
1. Clip a DEM around the outlet and reproject to a local UTM (metres).
2. Delineate the basin with ``ki_tools_common.terrain_ops.delineate_basin``
   (whitebox: breach -> D8 -> accumulation -> snap -> watershed).
3. Vectorise the basin, drop holes, simplify + densify the ring.
4. Extract the main-stem centreline with
   ``ki_tools_common.terrain_ops.extract_river_centerline_from_streams``
   (streams raster masked to the basin), orient it downstream by elevation.
5. Build a conforming-Delaunay TIN with meshpy/Triangle using the ring and the
   river as CONSTRAINED segments, so every river reach lies on element edges
   (PIHM requires this: ``InitRiver`` looks up ``elem[left].nabr[j] == right``).
6. Emit .mesh/.att/.riv honouring the MM-PIHM reader conventions, verified
   against ``input/ShaleHills``:
     * elements must be COUNTER-CLOCKWISE — ``InitTopo`` computes a SIGNED area
       ``0.5*((x1-x0)*(y2-y0)-(y1-y0)*(x2-x0))``; a clockwise triangle yields a
       negative area and silently negative storage.
     * ``NABR[j]`` is the neighbour across the edge OPPOSITE node j (verified:
       1544/1544 ShaleHills neighbour records follow this convention), 0 = none.
     * the river chain must descend: the outlet uses DOWN = -3
       (ZERO_DPTH_GRAD), whose flux is ``sqrt(grad_h)`` with
       ``grad_h = (zbed - (node_zmax(to) - depth))/dist``.  If the `to` node is
       NOT lower than the segment mean, grad_h < 0 and the discharge is NaN,
       which poisons CVODE on the first step.  Node elevations along the river
       are therefore forced monotonically decreasing.

Usage
-----
    python mesh_builder.py --dem /mnt/datasets/MERIT_DEM/n40e005_dem.tif \\
        --outlet-lon 8.6124 --outlet-lat 42.1771 \\
        --out-dir input/Chiuni --project Chiuni \\
        --target-elem-area-km2 0.12 --aquifer-thickness-m 15

Returns a JSON summary on stdout; also written to ``<out_dir>/_mesh_meta.json``.
"""

import argparse
import json
import math
import os
import sys

import numpy as np
import rasterio
from rasterio import features
from rasterio.warp import calculate_default_transform, reproject, Resampling
from rasterio.windows import from_bounds
from shapely.geometry import LineString, Point, Polygon, shape
from shapely.ops import linemerge

from ki_tools_common.terrain_ops import (
    delineate_basin,
    extract_river_centerline_from_streams,
)

NODATA = -9999.0


# --------------------------------------------------------------------------- #
# geometry helpers
# --------------------------------------------------------------------------- #
def utm_epsg(lon, lat):
    """EPSG code of the UTM zone containing (lon, lat)."""
    zone = int((lon + 180.0) // 6.0) + 1
    return "EPSG:%d" % ((32600 if lat >= 0 else 32700) + zone)


def clip_and_project_dem(dem_path, lon, lat, half_deg, out_tif, res_m=90.0):
    """Clip `dem_path` to a box around (lon, lat) and reproject to local UTM."""
    with rasterio.open(dem_path) as src:
        bounds = (lon - half_deg, lat - half_deg * 0.82,
                  lon + half_deg, lat + half_deg * 0.82)
        win = from_bounds(*bounds, src.transform)
        arr = src.read(1, window=win).astype("float32")
        src_tr = src.window_transform(win)
        src_crs = src.crs
        src_bounds = rasterio.windows.bounds(win, src.transform)

    arr = np.where(arr < -1000.0, NODATA, arr)
    dst_crs = utm_epsg(lon, lat)
    tr, w, h = calculate_default_transform(
        src_crs, dst_crs, arr.shape[1], arr.shape[0], *src_bounds,
        resolution=res_m)
    prof = dict(driver="GTiff", height=h, width=w, count=1, dtype="float32",
                crs=dst_crs, transform=tr, nodata=NODATA)
    os.makedirs(os.path.dirname(os.path.abspath(out_tif)), exist_ok=True)
    with rasterio.open(out_tif, "w", **prof) as dst:
        reproject(source=arr, destination=rasterio.band(dst, 1),
                  src_transform=src_tr, src_crs=src_crs, src_nodata=NODATA,
                  dst_transform=tr, dst_crs=dst_crs, dst_nodata=NODATA,
                  resampling=Resampling.bilinear)
    return out_tif, dst_crs


def basin_polygon(basin_raster, simplify_m):
    """Largest connected basin polygon, holes removed, simplified."""
    with rasterio.open(basin_raster) as src:
        arr = src.read(1)
        msk = arr > 0
        polys = [shape(g) for g, v in
                 features.shapes(msk.astype("uint8"), mask=msk,
                                 transform=src.transform) if v == 1]
    if not polys:
        raise RuntimeError("delineation produced an empty basin raster")
    poly = max(polys, key=lambda p: p.area)
    poly = Polygon(poly.exterior)            # drop interior holes
    poly = poly.simplify(simplify_m, preserve_topology=True).buffer(0)
    if poly.geom_type == "MultiPolygon":
        poly = max(poly.geoms, key=lambda p: p.area)
    return Polygon(poly.exterior)


def densify_ring(poly, max_seg):
    """Ring coordinates with no segment longer than `max_seg` (open list)."""
    coords = list(poly.exterior.coords)
    if coords[0] == coords[-1]:
        coords = coords[:-1]
    out = []
    n = len(coords)
    for i in range(n):
        a = np.array(coords[i])
        b = np.array(coords[(i + 1) % n])
        out.append(tuple(a))
        d = float(np.hypot(*(b - a)))
        k = int(math.floor(d / max_seg))
        for j in range(1, k + 1):
            t = j / float(k + 1)
            out.append(tuple(a + t * (b - a)))
    return out


def resample_line(line, seg_len):
    """Points along `line` spaced ~seg_len, endpoints preserved."""
    n = max(2, int(round(line.length / seg_len)) + 1)
    return [tuple(line.interpolate(line.length * i / (n - 1)).coords[0])
            for i in range(n)]


def sample_raster(path, pts, band=1):
    """Bilinear-ish (nearest) sample of `path` at a list of (x, y)."""
    with rasterio.open(path) as src:
        return np.array([v[band - 1] for v in src.sample(pts)], dtype="float64")


# --------------------------------------------------------------------------- #
# TIN construction
# --------------------------------------------------------------------------- #
def build_tin(ring_pts, river_pts, max_area_m2, min_angle):
    """Constrained Delaunay TIN. Returns (points, triangles)."""
    from meshpy.triangle import MeshInfo, build

    pts = list(ring_pts)
    nring = len(pts)
    facets = [(i, (i + 1) % nring) for i in range(nring)]

    if river_pts:
        base = len(pts)
        pts.extend(river_pts)
        for i in range(len(river_pts) - 1):
            facets.append((base + i, base + i + 1))

    mi = MeshInfo()
    mi.set_points(pts)
    mi.set_facets(facets)
    mesh = build(mi, max_volume=max_area_m2, min_angle=min_angle,
                 generate_faces=True, attributes=False)

    P = np.array(mesh.points, dtype="float64")
    T = np.array(mesh.elements, dtype="int64")

    # enforce counter-clockwise node order (InitTopo uses a SIGNED area)
    a = P[T[:, 0]]
    b = P[T[:, 1]]
    c = P[T[:, 2]]
    cross = (b[:, 0] - a[:, 0]) * (c[:, 1] - a[:, 1]) - \
            (b[:, 1] - a[:, 1]) * (c[:, 0] - a[:, 0])
    flip = cross < 0
    T[flip] = T[flip][:, [0, 2, 1]]
    return P, T


def element_neighbors(T):
    """NABR table: nabr[i][j] = element across the edge OPPOSITE node j (1-based, 0=none)."""
    edge_map = {}
    for ei, tri in enumerate(T):
        for j in range(3):
            key = tuple(sorted((tri[(j + 1) % 3], tri[(j + 2) % 3])))
            edge_map.setdefault(key, []).append((ei, j))
    nabr = np.zeros((len(T), 3), dtype="int64")
    for key, owners in edge_map.items():
        if len(owners) == 2:
            (e0, j0), (e1, j1) = owners
            nabr[e0, j0] = e1 + 1
            nabr[e1, j1] = e0 + 1
        elif len(owners) > 2:
            raise RuntimeError("non-manifold edge %s" % (key,))
    return nabr, edge_map


def river_chain(P, edge_map, river_line, tol=1.0):
    """Mesh edges lying on `river_line`, ordered upstream -> downstream.

    Returns a list of dicts: {n0, n1 (0-based node ids), elems (list), s}.
    """
    cand = []
    for (a, b), owners in edge_map.items():
        if len(owners) != 2:
            continue                      # river must be an interior edge
        pa, pb = Point(P[a]), Point(P[b])
        if pa.distance(river_line) > tol or pb.distance(river_line) > tol:
            continue
        mid = Point((P[a] + P[b]) / 2.0)
        if mid.distance(river_line) > tol:
            continue
        sa = river_line.project(pa)
        sb = river_line.project(pb)
        n0, n1 = (a, b) if sa <= sb else (b, a)
        cand.append({"n0": int(n0), "n1": int(n1),
                     "elems": [o[0] for o in owners],
                     "s": 0.5 * (sa + sb)})
    cand.sort(key=lambda d: d["s"])
    if not cand:
        return []

    # keep the longest connected chain that terminates farthest downstream
    chains = []
    cur = [cand[0]]
    for e in cand[1:]:
        if e["n0"] == cur[-1]["n1"]:
            cur.append(e)
        else:
            chains.append(cur)
            cur = [e]
    chains.append(cur)
    return max(chains, key=len)


# --------------------------------------------------------------------------- #
# writers
# --------------------------------------------------------------------------- #
def write_mesh(path, P, T, nabr, zmax, zmin):
    with open(path, "w") as f:
        f.write("NUMELE\t%d\n" % len(T))
        f.write("INDEX\tNODE1\tNODE2\tNODE3\tNABR1\tNABR2\tNABR3\n")
        for i, tri in enumerate(T):
            f.write("%d\t%d\t%d\t%d\t%d\t%d\t%d\n" % (
                i + 1, tri[0] + 1, tri[1] + 1, tri[2] + 1,
                nabr[i, 0], nabr[i, 1], nabr[i, 2]))
        f.write("NUMNODE\t%d\n" % len(P))
        f.write("INDEX\tX\tY\tZMIN\tZMAX\n")
        f.write("#-\tm\tm\tm\tm\n")
        for i, (x, y) in enumerate(P):
            f.write("%d\t%.3f\t%.3f\t%.3f\t%.3f\n"
                    % (i + 1, x, y, zmin[i], zmax[i]))


def write_att(path, nelem, soil, geol, lc, meteo=1, lai=1):
    soil = np.broadcast_to(np.asarray(soil), (nelem,))
    geol = np.broadcast_to(np.asarray(geol), (nelem,))
    lc = np.broadcast_to(np.asarray(lc), (nelem,))

    # SOIL, GEOL and LC are all 1-BASED table indices; PIHM turns each into a
    # row subscript by subtracting 1 (e.g. src/init_soil.c: `soil_ind =
    # elem[i].attrib.soil - 1`). A 0 therefore addresses no row and yields the
    # subscript -1, so refuse to emit one rather than write a deck that is
    # invalid on its face. GEOL is not exempt: input/ShaleHills carries
    # GEOL = 1 on all 1544 elements against a `.geol` whose rows start at 1,
    # and soil_converter.py likewise numbers `.geol` rows 1..NUMGEOL.
    for name, col in (("SOIL", soil), ("GEOL", geol), ("LC", lc)):
        bad = np.asarray(col) < 1
        if bad.any():
            i = int(np.argmax(bad))
            raise ValueError(
                "%s must be a 1-based index into the corresponding table; "
                "element %d got %d" % (name, i + 1, int(np.asarray(col)[i])))

    with open(path, "w") as f:
        # NO "NUMATT" line: src/read_att.c CheckHeaders the FIRST line against
        # "INDEX SOIL GEOL LC METEO LAI BC1 BC2 BC3" and sizes the table from
        # nelem in the .mesh. SKILL.md section 4.2 documents a leading
        # "NUMATT <n>" record, which PIHM rejects ("format error ... at Line 1").
        #
        # Three of these columns are indices into files written by the sibling
        # tools, and PIHM validates them there rather than here:
        #   SOIL — must address a row of the `.soil` table, whose rows
        #     src/read_soil.c requires to be numbered 1..NUMSOIL *in order*
        #     ("i != index - 1" -> ERR_WRONG_FORMAT). soil_converter.py
        #     renumbers to that convention and reports an index_map; use it
        #     when the soil ids here come from a raster's own class codes.
        #   GEOL — same contract against the `.geol` table that
        #     soil_converter.py emits alongside the `.soil` one (one bedrock
        #     row per soil row, numbered 1..NUMGEOL). The default below is
        #     therefore 1, not 0: 0 is not a row, and the headless chain has
        #     to produce a valid deck without the caller overriding anything.
        #   LAI  — any value > 0 makes src/read_lai.c actually open the `.lai`
        #     file (ReadLai returns early with nlai=0 when every element has
        #     lai <= 0). So writing 1 here is what puts config_writer.py's
        #     2-column "TIME LAI" block on the critical path.
        f.write("INDEX\tSOIL\tGEOL\tLC\tMETEO\tLAI\tBC1\tBC2\tBC3\n")
        for i in range(nelem):
            f.write("%d\t%d\t%d\t%d\t%d\t%d\t0\t0\t0\n"
                    % (i + 1, soil[i], geol[i], lc[i], meteo, lai))


def write_riv(path, chain, widths, depths, rough, cwr, ksath):
    n = len(chain)
    with open(path, "w") as f:
        f.write("NUMRIV\t%d\n" % n)
        f.write("INDEX\tFROM\tTO\tDOWN\tLEFT\tRIGHT\tSHAPE\tMATL\tBC\tRES\n")
        for i, seg in enumerate(chain):
            down = i + 2 if i < n - 1 else -3      # -3 = ZERO_DPTH_GRAD outlet
            f.write("%d\t%d\t%d\t%d\t%d\t%d\t%d\t1\t0\t0\n" % (
                i + 1, seg["n0"] + 1, seg["n1"] + 1, down,
                seg["left"] + 1, seg["right"] + 1, i + 1))
        f.write("SHAPE\t%d\n" % n)
        f.write("INDEX\tDPTH\tOINT\tCWID\n")
        f.write("#-\tm\t-\t-\n")
        for i in range(n):
            f.write("%d\t%.3f\t1\t%.3f\n" % (i + 1, depths[i], widths[i]))
        f.write("MATERIAL\t1\n")
        f.write("INDEX\tROUGH\tCWR\tKH\n")
        f.write("#-\ts/m1/3\t-\tm/s\n")
        f.write("1\t%.4f\t%.3f\t%.4E\n" % (rough, cwr, ksath))
        f.write("BC\t0\n")
        f.write("RES\t0\n")


# --------------------------------------------------------------------------- #
# driver
# --------------------------------------------------------------------------- #
def build_domain(dem, outlet_lon, outlet_lat, out_dir, project,
                 work_dir=None,
                 half_deg=0.16, dem_res_m=90.0,
                 stream_threshold=150, snap_distance_m=2000.0,
                 simplify_m=90.0, boundary_seg_len_m=400.0,
                 riv_seg_len_m=700.0, target_elem_area_km2=0.12,
                 min_angle=30.0, aquifer_thickness_m=15.0,
                 boundary_clear_m=350.0,
                 soil_index=1, geol_index=1, lc_index=6,
                 riv_rough=0.04, riv_cwr=0.6, riv_ksath=1.0e-4,
                 width_a=1.5, width_b=0.5, depth_a=0.35, depth_b=0.30,
                 lc_raster=None):
    work_dir = work_dir or os.path.join(out_dir, "_work")
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(work_dir, exist_ok=True)

    dem_utm = os.path.join(work_dir, "dem_utm.tif")
    if not os.path.exists(dem_utm):
        clip_and_project_dem(dem, outlet_lon, outlet_lat, half_deg,
                             dem_utm, dem_res_m)

    deld = os.path.join(work_dir, "delineation")
    if not os.path.exists(os.path.join(deld, "basin.tif")):
        d = delineate_basin(dem_path=dem_utm,
                            pour_point=(outlet_lon, outlet_lat),
                            output_dir=deld,
                            stream_threshold=stream_threshold,
                            snap_distance_m=snap_distance_m,
                            pour_point_crs="EPSG:4326")
    else:
        d = {"basin_raster": os.path.join(deld, "basin.tif"),
             "streams_raster": os.path.join(deld, "streams.tif"),
             "d8_pointer": os.path.join(deld, "d8_pointer.tif"),
             "flow_accum": os.path.join(deld, "flow_accum.tif"),
             "filled_dem": os.path.join(deld, "dem_filled.tif")}
        with rasterio.open(d["basin_raster"]) as s:
            px = abs(s.transform.a * s.transform.e)
            d["basin_area_km2"] = float((s.read(1) > 0).sum() * px / 1e6)

    poly = basin_polygon(d["basin_raster"], simplify_m)

    # --- main stem, masked to the basin ------------------------------------ #
    st_masked = os.path.join(work_dir, "streams_basin.tif")
    with rasterio.open(d["streams_raster"]) as s, \
            rasterio.open(d["basin_raster"]) as b:
        sa = s.read(1).astype("float32")
        ba = b.read(1)
        sa = np.where(ba > 0, sa, 0.0)
        prof = s.profile.copy()
        prof.update(dtype="float32", nodata=0.0)
        with rasterio.open(st_masked, "w", **prof) as o:
            o.write(sa, 1)
    cl = extract_river_centerline_from_streams(
        streams_raster=st_masked, d8_pointer=d["d8_pointer"],
        output_dir=os.path.join(work_dir, "centerline"), select="longest")
    line = _load_line(cl)

    # orient downstream (lower filled-DEM elevation at the end)
    ends = [line.coords[0], line.coords[-1]]
    ez = sample_raster(d["filled_dem"], ends)
    if ez[0] < ez[1]:
        line = LineString(list(line.coords)[::-1])

    # --- PSLG ------------------------------------------------------------- #
    ring = densify_ring(poly, boundary_seg_len_m)
    ring_arr = np.array(ring)
    riv_pts_all = resample_line(line, riv_seg_len_m)
    boundary = poly.exterior
    riv_pts = [p for p in riv_pts_all
               if Point(p).distance(boundary) > boundary_clear_m
               and poly.contains(Point(p))]
    if len(riv_pts) < 2:
        raise RuntimeError("river centreline too short after boundary clearing")
    # terminate the chain on the ring vertex nearest the true outlet
    tail = np.array(riv_pts_all[-1])
    k = int(np.argmin(np.hypot(ring_arr[:, 0] - tail[0],
                               ring_arr[:, 1] - tail[1])))
    riv_pts.append(tuple(ring_arr[k]))
    riv_line = LineString(riv_pts)

    max_area = target_elem_area_km2 * 1.0e6
    P, T = build_tin(ring, riv_pts[:-1], max_area, min_angle)
    nabr, edge_map = element_neighbors(T)

    # --- elevations -------------------------------------------------------- #
    zmax = sample_raster(d["filled_dem"], [tuple(p) for p in P])
    bad = ~np.isfinite(zmax) | (zmax <= NODATA + 1.0)
    if bad.any():
        zmax[bad] = np.nanmedian(zmax[~bad])

    chain = river_chain(P, edge_map, riv_line)
    if not chain:
        raise RuntimeError("no mesh edge resolved onto the river centreline")

    # force monotonic descent along the river (guards the -3 outlet sqrt())
    order = [chain[0]["n0"]] + [s["n1"] for s in chain]
    for a, b in zip(order[:-1], order[1:]):
        if zmax[b] >= zmax[a]:
            zmax[b] = zmax[a] - 0.05
    zmin = zmax - float(aquifer_thickness_m)

    # --- river geometry from drainage area --------------------------------- #
    with rasterio.open(d["flow_accum"]) as fa:
        cell_km2 = abs(fa.transform.a * fa.transform.e) / 1.0e6
        mids = [tuple((P[s["n0"]] + P[s["n1"]]) / 2.0) for s in chain]
        acc = np.array([v[0] for v in fa.sample(mids)], dtype="float64")
    area_km2 = np.maximum(acc, 1.0) * cell_km2
    # A segment midpoint can miss the 1-cell-wide stream raster and sample an
    # off-channel accumulation of ~1 cell, which would emit a 1 m wide channel
    # in the middle of the main stem. Drainage area is monotonic downstream, so
    # take the running maximum and cap it at the delineated basin area.
    area_km2 = np.maximum.accumulate(area_km2)
    area_km2 = np.minimum(area_km2, float(poly.area / 1e6))
    widths = np.clip(width_a * area_km2 ** width_b, 1.0, 500.0)
    depths = np.clip(depth_a * area_km2 ** depth_b, 0.2, 20.0)

    # left/right banks (left = left-hand side looking downstream)
    for s in chain:
        v = P[s["n1"]] - P[s["n0"]]
        e0, e1 = s["elems"]
        c0 = P[T[e0]].mean(axis=0) - P[s["n0"]]
        cross = v[0] * c0[1] - v[1] * c0[0]
        s["left"], s["right"] = (e0, e1) if cross > 0 else (e1, e0)

    # --- attributes -------------------------------------------------------- #
    if lc_raster:
        cent = np.array([P[t].mean(axis=0) for t in T])
        lc = _lc_from_raster(lc_raster, cent, P.shape, dem_utm)
    else:
        lc = np.full(len(T), int(lc_index), dtype="int64")

    write_mesh(os.path.join(out_dir, project + ".mesh"), P, T, nabr, zmax, zmin)
    write_att(os.path.join(out_dir, project + ".att"), len(T),
              soil_index, geol_index, lc)
    write_riv(os.path.join(out_dir, project + ".riv"), chain, widths, depths,
              riv_rough, riv_cwr, riv_ksath)

    areas = np.abs(0.5 * ((P[T[:, 1], 0] - P[T[:, 0], 0]) * (P[T[:, 2], 1] - P[T[:, 0], 1]) -
                          (P[T[:, 1], 1] - P[T[:, 0], 1]) * (P[T[:, 2], 0] - P[T[:, 0], 0])))
    with rasterio.open(dem_utm) as s:
        crs = str(s.crs)
    meta = {
        "project": project,
        "crs": crs,
        "outlet_lonlat": [outlet_lon, outlet_lat],
        "basin_area_km2_raster": d.get("basin_area_km2"),
        "basin_area_km2_polygon": poly.area / 1e6,
        "nelem": int(len(T)),
        "nnode": int(len(P)),
        "nriver": int(len(chain)),
        "elem_area_km2": {"min": float(areas.min() / 1e6),
                          "median": float(np.median(areas) / 1e6),
                          "max": float(areas.max() / 1e6),
                          "total": float(areas.sum() / 1e6)},
        "elev_m": {"min": float(zmax.min()), "max": float(zmax.max()),
                   "mean": float(zmax.mean())},
        "aquifer_thickness_m": float(aquifer_thickness_m),
        "river_length_km": float(riv_line.length / 1000.0),
        "river_width_m": [float(widths.min()), float(widths.max())],
        "boundary_elems_no_nabr": int((nabr == 0).sum()),
        "work_dir": work_dir,
        "dem_utm": dem_utm,
        "filled_dem": d["filled_dem"],
    }
    with open(os.path.join(out_dir, "_mesh_meta.json"), "w") as f:
        json.dump(meta, f, indent=2)
    return meta


def _load_line(cl):
    """Accept whatever the centreline tool returns (dict/geojson path/geometry)."""
    import geopandas as gpd
    if isinstance(cl, dict):
        for k in ("centerline", "geometry", "line"):
            if k in cl and hasattr(cl[k], "geom_type"):
                return cl[k]
        for k in ("centerline_geojson", "centerline_vector", "vector",
                  "geojson", "path", "output"):
            if k in cl and isinstance(cl[k], str) and os.path.exists(cl[k]):
                cl = cl[k]
                break
        else:
            raise RuntimeError("cannot locate centreline geometry in %r" % (cl,))
    g = gpd.read_file(cl)
    geom = linemerge(list(g.geometry)) if len(g) > 1 else g.geometry.iloc[0]
    if geom.geom_type == "MultiLineString":
        geom = max(geom.geoms, key=lambda l: l.length)
    return geom


def _lc_from_raster(lc_raster, centroids, _shape, ref_tif):
    """Dominant land-cover class per element, ESA-CCI -> IGBP (vegprmt.tbl)."""
    from rasterio.warp import transform as warp_transform
    with rasterio.open(ref_tif) as r:
        src_crs = r.crs
    lon, lat = warp_transform(src_crs, "EPSG:4326",
                              centroids[:, 0].tolist(), centroids[:, 1].tolist())
    with rasterio.open(lc_raster) as s:
        vals = np.array([v[0] for v in s.sample(list(zip(lon, lat)))])
    return np.array([ESA_CCI_TO_IGBP.get(int(v), 6) for v in vals], dtype="int64")


# ESA CCI-LC (LCCS) -> IGBP index used by MM-PIHM's input/vegprmt.tbl
ESA_CCI_TO_IGBP = {
    10: 12, 11: 12, 12: 12, 20: 12, 30: 14, 40: 14,
    50: 2, 60: 4, 61: 4, 62: 4, 70: 1, 71: 1, 72: 1,
    80: 3, 81: 3, 82: 3, 90: 5, 100: 8, 110: 9, 120: 6,
    121: 6, 122: 7, 130: 10, 140: 10, 150: 16, 152: 16,
    153: 16, 160: 11, 170: 11, 180: 11, 190: 13, 200: 16,
    201: 16, 202: 16, 210: 17, 220: 15,
}


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dem", required=True)
    p.add_argument("--outlet-lon", type=float, required=True)
    p.add_argument("--outlet-lat", type=float, required=True)
    p.add_argument("--out-dir", required=True)
    p.add_argument("--project", required=True)
    p.add_argument("--work-dir", default=None)
    p.add_argument("--half-deg", type=float, default=0.16)
    p.add_argument("--dem-res-m", type=float, default=90.0)
    p.add_argument("--stream-threshold", type=int, default=150)
    p.add_argument("--snap-distance-m", type=float, default=2000.0)
    p.add_argument("--simplify-m", type=float, default=90.0)
    p.add_argument("--boundary-seg-len-m", type=float, default=400.0)
    p.add_argument("--riv-seg-len-m", type=float, default=700.0)
    p.add_argument("--target-elem-area-km2", type=float, default=0.12)
    p.add_argument("--min-angle", type=float, default=30.0)
    p.add_argument("--aquifer-thickness-m", type=float, default=15.0)
    p.add_argument("--boundary-clear-m", type=float, default=350.0)
    p.add_argument("--soil-index", type=int, default=1,
                   help="1-based row of the .soil table (default: 1)")
    p.add_argument("--geol-index", type=int, default=1,
                   help="1-based row of the .geol table (default: 1); "
                        "0 is not a row and is rejected")
    p.add_argument("--lc-index", type=int, default=6,
                   help="1-based row of vegprmt.tbl (default: 6)")
    p.add_argument("--lc-raster", default=None)
    a = p.parse_args()

    meta = build_domain(
        dem=a.dem, outlet_lon=a.outlet_lon, outlet_lat=a.outlet_lat,
        out_dir=a.out_dir, project=a.project, work_dir=a.work_dir,
        half_deg=a.half_deg, dem_res_m=a.dem_res_m,
        stream_threshold=a.stream_threshold, snap_distance_m=a.snap_distance_m,
        simplify_m=a.simplify_m, boundary_seg_len_m=a.boundary_seg_len_m,
        riv_seg_len_m=a.riv_seg_len_m,
        target_elem_area_km2=a.target_elem_area_km2, min_angle=a.min_angle,
        aquifer_thickness_m=a.aquifer_thickness_m,
        boundary_clear_m=a.boundary_clear_m,
        soil_index=a.soil_index, geol_index=a.geol_index,
        lc_index=a.lc_index, lc_raster=a.lc_raster)
    print(json.dumps({"status": "success", **meta}, indent=2))


if __name__ == "__main__":
    main()
