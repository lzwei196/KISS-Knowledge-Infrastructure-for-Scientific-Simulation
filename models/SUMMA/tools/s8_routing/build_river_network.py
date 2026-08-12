#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
============================================
Tool ID:      build_river_network
Stage:        s8_routing
Description:  Build a mizuRoute river-network topology NetCDF (ntopo.nc) and the
              matching SUMMA gru_hru_mapping.csv from a HydroBASINS level-07
              shapefile, by upstream NEXT_DOWN traversal from an outlet sub-basin.

WHY COMPACT RENUMBERING IS MANDATORY (not cosmetic):
  mizuRoute stores river-network ids in type(var_ilength), whose payload is
  `integer(i4b), allocatable :: dat(:)` (dataTypes.f90:82-84), and
  read_streamSeg.f90:254 assigns `structNTOPO(..)%dat(1:jxCount) = iTemp(..)`.
  HydroBASINS HYBAS_ID reaches 4,071,348,160 > int32 max (2,147,483,647), so raw
  HYBAS_IDs OVERFLOW. Segments/HRUs are therefore renumbered 1..N (int32) and the
  original HYBAS_ID is preserved in the hybas_map.csv sidecar.

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""
import sys
import os
import csv
import json
import math
import logging
import argparse

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Nominal channel slope written ONLY to satisfy mizuRoute's reader:
# popMetadat.f90:134 marks meta_SEG(ixSEG%slope) required-from-file (.true.).
# The IRF scheme (route_opt=1) drives its unit hydrograph from Length plus
# velo/diff in param.nml and never consumes Slope. Any slope-dependent scheme
# (KWT/KW/MC/DW) WOULD consume it, which is why run_mizuroute.py hard-codes
# route_opt=1 and exposes no override.
NOMINAL_SLOPE = 0.001


def parse_args():
    p = argparse.ArgumentParser(description="Build mizuRoute topology + SUMMA GRU mapping from HydroBASINS")
    p.add_argument("--hybas_shp", required=True, help="HydroBASINS lev07 .shp (its .dbf must sit beside it)")
    p.add_argument("--outlet_hybas_id", required=True, type=int, help="HYBAS_ID of the sub-basin holding the gauge")
    p.add_argument("--dem", required=True, help="DEM GeoTIFF in EPSG:4326")
    p.add_argument("--output_dir", required=True)
    p.add_argument("--landcover_tif", default=None,
                   help="IGBP land-cover GeoTIFF (classes 0-16, e.g. AVHRR 1km). Per-GRU MODAL class, "
                        "crosswalked via ki_tools_common.landcover. Vegetation is an INPUT, not an assumption.")
    p.add_argument("--veg_scheme", choices=("usgs", "modis"), default=None,
                   help="Target table for the crosswalk. MUST equal the vegeParTbl decision (SKILL.md 2c): "
                        "usgs=USGS(27 classes), modis=MODIFIED_IGBP_MODIS_NOAH(20 classes).")
    p.add_argument("--veg_index", required=False, type=int, default=None,
                   help="UNIFORM vegTypeIndex for every GRU. Single-HRU sites only; --landcover_tif is preferred.")
    p.add_argument("--soil_index", required=True, type=int, help="uniform soilTypeIndex for every GRU")
    p.add_argument("--dem_sample_deg", type=float, default=0.02, help="DEM lattice spacing inside each polygon")
    a = p.parse_args()
    if not a.landcover_tif and a.veg_index is None:
        p.error("one of --landcover_tif (preferred, dataset-sourced) or --veg_index (uniform) is required")
    if a.landcover_tif and a.veg_scheme is None:
        p.error("--landcover_tif requires --veg_scheme {usgs,modis}; it MUST equal the vegeParTbl decision (SKILL.md 2c)")
    return a


def read_attributes(dbf_path):
    from dbfread import DBF
    recs = {}
    for r in DBF(dbf_path, load=False):
        recs[int(r["HYBAS_ID"])] = {
            "next_down": int(r["NEXT_DOWN"]),
            "sub_area": float(r["SUB_AREA"]),   # km2
            "dist_main": float(r["DIST_MAIN"]),  # km
        }
    if not recs:
        raise RuntimeError(f"no records read from {dbf_path}")
    return recs


def traverse_upstream(recs, outlet_id):
    if outlet_id not in recs:
        raise RuntimeError(f"outlet_hybas_id {outlet_id} not present in the shapefile")
    children = {}
    for hid, a in recs.items():
        children.setdefault(a["next_down"], []).append(hid)
    subset, stack = {outlet_id}, [outlet_id]
    while stack:
        cur = stack.pop()
        for up in children.get(cur, []):
            if up not in subset:
                subset.add(up)
                stack.append(up)
    return sorted(subset)


def reach_length_m(hid, recs_full, outlet_id):
    """Length = (DIST_MAIN[self] - DIST_MAIN[NEXT_DOWN[self]]) * 1000 m.

    DIST_MAIN[NEXT_DOWN] is ALWAYS looked up in the FULL, unsubset attribute
    table -- the outlet's own NEXT_DOWN lies outside the subset by construction.
    A NEXT_DOWN that is absent from the FULL table is a corrupt shapefile, and a
    non-positive length is a corrupt DIST_MAIN: both raise, never default.
    """
    nd = recs_full[hid]["next_down"]
    if nd == 0:
        if hid != outlet_id:
            raise RuntimeError(f"HYBAS_ID {hid} is an interior sink (NEXT_DOWN=0) but is not the outlet")
        raise RuntimeError(f"outlet {hid} has NEXT_DOWN=0; DIST_MAIN of the next downstream reach is undefined")
    if nd not in recs_full:
        raise RuntimeError(
            f"HYBAS_ID {hid} has NEXT_DOWN={nd} which is absent from the FULL attribute table; "
            f"cannot compute reach length. Refusing to treat it as a sink."
        )
    length = (recs_full[hid]["dist_main"] - recs_full[nd]["dist_main"]) * 1000.0
    if length <= 0.0:
        raise RuntimeError(
            f"non-positive reach length {length:.3f} m for HYBAS_ID {hid} "
            f"(DIST_MAIN self={recs_full[hid]['dist_main']} down={recs_full[nd]['dist_main']})"
        )
    return length


def sample_polygons(shp_path, subset, dem_path, spacing):
    """Per-polygon centroid (lat/lon) and DEM mean/min/max elevation.

    The DEM is read for its MEAN (GRU elevation) and for its MIN and MAX, which
    together give tan_slope = (max-min)/sqrt(area). Both extremes are part of the
    DEM contract, not just the mean.
    """
    import geopandas as gpd
    import rasterio
    from shapely.geometry import Point

    gdf = gpd.read_file(shp_path)
    gdf = gdf[gdf["HYBAS_ID"].astype("int64").isin(subset)]
    if len(gdf) != len(subset):
        raise RuntimeError(f"shapefile yielded {len(gdf)} polygons for {len(subset)} subset ids")
    gdf = gdf.set_index(gdf["HYBAS_ID"].astype("int64"))

    out = {}
    with rasterio.open(dem_path) as dem:
        nodata = dem.nodata
        for hid in subset:
            geom = gdf.loc[hid, "geometry"]
            c = geom.centroid
            minx, miny, maxx, maxy = geom.bounds
            xs = np.arange(minx + spacing / 2.0, maxx, spacing)
            ys = np.arange(miny + spacing / 2.0, maxy, spacing)
            pts = [(x, y) for y in ys for x in xs if geom.contains(Point(x, y))]
            if not pts:
                pts = [(c.x, c.y)]
            vals = np.array([v[0] for v in dem.sample(pts)], dtype=np.float64)
            if nodata is not None:
                vals = vals[vals != nodata]
            if vals.size == 0:
                raise RuntimeError(f"HYBAS_ID {hid}: no valid DEM samples inside polygon (DEM coverage gap)")
            out[hid] = {
                "lat": float(c.y),
                "lon": float(c.x),
                "elev_mean": float(vals.mean()),
                "elev_min": float(vals.min()),
                "elev_max": float(vals.max()),
                "n_samples": int(vals.size),
            }
    return out


NVEG_BY_SCHEME = {"usgs": 27, "modis": 20}


def sample_landcover(shp_path, subset, tif_path, scheme, spacing):
    """Per-polygon MODAL land-cover class, crosswalked IGBP -> {usgs,modis}.

    Samples the SAME lattice as sample_polygons() so vegetation and elevation
    describe the same polygon interior. The crosswalk is the single source of
    truth for the water class: IGBP numbers water 0, the Noah-MP MODIS table is
    1-based with ISWATER=17, so a bare identity map would hand SUMMA a
    vegTypeIndex outside 1..NVEG and read past the LAIM/HVT arrays.
    """
    import geopandas as gpd
    import rasterio
    from shapely.geometry import Point
    from collections import Counter

    sys.path.insert(0, "/mnt/disk1/Hydrocraft_server/models/ki_tools_common")
    from ki_tools_common.landcover import igbp_to_usgs, igbp_to_modis
    xwalk = igbp_to_usgs if scheme == "usgs" else igbp_to_modis
    nveg = NVEG_BY_SCHEME[scheme]

    gdf = gpd.read_file(shp_path)
    gdf = gdf[gdf["HYBAS_ID"].astype("int64").isin(subset)]
    gdf = gdf.set_index(gdf["HYBAS_ID"].astype("int64"))

    veg, igbp_modes = {}, {}
    with rasterio.open(tif_path) as lc:
        for hid in subset:
            geom = gdf.loc[hid, "geometry"]
            c = geom.centroid
            minx, miny, maxx, maxy = geom.bounds
            xs = np.arange(minx + spacing / 2.0, maxx, spacing)
            ys = np.arange(miny + spacing / 2.0, maxy, spacing)
            pts = [(x, y) for y in ys for x in xs if geom.contains(Point(x, y))]
            if not pts:
                pts = [(c.x, c.y)]
            vals = [int(v[0]) for v in lc.sample(pts)]
            vals = [v for v in vals if 0 <= v <= 16]
            if not vals:
                raise RuntimeError(f"HYBAS_ID {hid}: no valid IGBP samples inside polygon (land-cover coverage gap)")
            modal = Counter(vals).most_common(1)[0][0]
            cls = int(xwalk(modal))
            if not (1 <= cls <= nveg):
                raise RuntimeError(
                    f"HYBAS_ID {hid}: crosswalk({modal}) -> {cls}, outside 1..{nveg} for scheme {scheme}")
            veg[hid] = cls
            igbp_modes[hid] = modal
    return veg, igbp_modes


def main():
    args = parse_args()
    shp = args.hybas_shp
    dbf = os.path.splitext(shp)[0] + ".dbf"
    for pth in (shp, dbf, args.dem):
        if not os.path.exists(pth):
            logger.error(f"input not found: {pth}")
            sys.exit(1)
    os.makedirs(args.output_dir, exist_ok=True)

    recs = read_attributes(dbf)
    logger.info(f"read {len(recs)} HydroBASINS records from {dbf}")

    subset = traverse_upstream(recs, args.outlet_hybas_id)
    subset_set = set(subset)
    area_km2 = sum(recs[h]["sub_area"] for h in subset)
    logger.info(f"upstream subset: {len(subset)} sub-basins, {area_km2:.1f} km2")

    # Compact int32 renumbering, outlet LAST so its compact id == N (see docstring).
    ordered = [h for h in subset if h != args.outlet_hybas_id] + [args.outlet_hybas_id]
    compact = {h: i + 1 for i, h in enumerate(ordered)}
    if len(ordered) > np.iinfo(np.int32).max:
        raise RuntimeError("subset larger than int32")

    geo = sample_polygons(shp, ordered, args.dem, args.dem_sample_deg)

    seg_id, tosegment, length, slope, basin_area = [], [], [], [], []
    for h in ordered:
        seg_id.append(compact[h])
        nd = recs[h]["next_down"]
        # tosegment=0 means "network outlet". Only the outlet drains outside the subset.
        tosegment.append(compact[nd] if nd in subset_set else 0)
        length.append(reach_length_m(h, recs, args.outlet_hybas_id))
        slope.append(NOMINAL_SLOPE)
        basin_area.append(recs[h]["sub_area"] * 1.0e6)  # km2 -> m2

    n_out = sum(1 for t in tosegment if t == 0)
    if n_out != 1:
        raise RuntimeError(f"expected exactly 1 network outlet (tosegment=0), found {n_out}")

    ntopo_nc = os.path.join(args.output_dir, "ntopo.nc")
    from netCDF4 import Dataset
    ds = Dataset(ntopo_nc, "w", format="NETCDF4")
    ds.createDimension("seg", len(ordered))
    ds.createDimension("hru", len(ordered))
    v = ds.createVariable("seg_id", "i4", ("seg",));      v[:] = np.array(seg_id, dtype=np.int32)
    v = ds.createVariable("tosegment", "i4", ("seg",));   v[:] = np.array(tosegment, dtype=np.int32)
    v = ds.createVariable("hruid", "i4", ("hru",));       v[:] = np.array(seg_id, dtype=np.int32)
    v = ds.createVariable("seg_hru_id", "i4", ("hru",));  v[:] = np.array(seg_id, dtype=np.int32)
    v = ds.createVariable("Length", "f8", ("seg",));      v[:] = np.array(length); v.units = "m"
    v = ds.createVariable("Slope", "f8", ("seg",));       v[:] = np.array(slope);  v.units = "-"
    v = ds.createVariable("Basin_Area", "f8", ("hru",));  v[:] = np.array(basin_area); v.units = "m^2"
    ds.history = f"build_river_network.py from {shp} outlet={args.outlet_hybas_id}"
    ds.close()

    map_csv = os.path.join(args.output_dir, "hybas_map.csv")
    with open(map_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["compact_id", "hybas_id", "next_down_hybas_id", "tosegment_compact", "length_m", "area_m2"])
        for i, h in enumerate(ordered):
            w.writerow([compact[h], h, recs[h]["next_down"], tosegment[i], f"{length[i]:.3f}", f"{basin_area[i]:.1f}"])

    if args.landcover_tif:
        if not os.path.exists(args.landcover_tif):
            logger.error(f"input not found: {args.landcover_tif}")
            sys.exit(1)
        veg_by_hid, _igbp_modes = sample_landcover(shp, ordered, args.landcover_tif,
                                                   args.veg_scheme, args.dem_sample_deg)
        veg_source = os.path.basename(args.landcover_tif)
        veg_scheme_out = args.veg_scheme
    else:
        veg_by_hid = {h: args.veg_index for h in ordered}
        veg_source = "uniform --veg_index (ASSUMPTION, not data)"
        veg_scheme_out = args.veg_scheme or "unspecified"
        logger.warning(
            f"--veg_index writes ONE vegTypeIndex to all {len(ordered)} GRUs. vegTypeIndex sets canopy "
            f"height, monthly LAI and stomatal resistance -- i.e. ET, i.e. discharge. Prefer --landcover_tif.")

    _tot = float(sum(basin_area))
    _acc = {}
    for i, h in enumerate(ordered):
        k = str(veg_by_hid[h])
        _acc[k] = _acc.get(k, 0.0) + basin_area[i]
    veg_area_fraction = {k: round(v / _tot, 4) for k, v in sorted(_acc.items(), key=lambda kv: -kv[1])}
    logger.info(f"vegTypeIndex source={veg_source} scheme={veg_scheme_out} area_fraction={veg_area_fraction}")

    gru_csv = os.path.join(args.output_dir, "gru_hru_mapping.csv")
    with open(gru_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["gruId", "hruId", "lat", "lon", "elevation", "area_m2",
                    "tan_slope", "vegTypeIndex", "soilTypeIndex"])
        for i, h in enumerate(ordered):
            g = geo[h]
            relief = g["elev_max"] - g["elev_min"]
            ts = relief / math.sqrt(basin_area[i])
            ts = min(max(ts, 1.0e-4), 1.0)
            w.writerow([compact[h], compact[h], f"{g['lat']:.6f}", f"{g['lon']:.6f}",
                        f"{g['elev_mean']:.2f}", f"{basin_area[i]:.1f}",
                        f"{ts:.6f}", veg_by_hid[h], args.soil_index])

    print(json.dumps({
        "status": "success",
        "n_seg": len(ordered),
        "n_gru": len(ordered),
        "area_km2": round(area_km2, 1),
        "outlet_hybas_id": args.outlet_hybas_id,
        "outlet_seg_id": compact[args.outlet_hybas_id],
        "ntopo_nc": ntopo_nc,
        "hybas_map_csv": map_csv,
        "gru_hru_mapping_csv": gru_csv,
        "veg_source": veg_source,
        "veg_scheme": veg_scheme_out,
        "veg_area_fraction": veg_area_fraction,
    }, indent=2))


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        logger.error(f"build_river_network failed: {e}")
        import traceback; traceback.print_exc()
        sys.exit(2)
