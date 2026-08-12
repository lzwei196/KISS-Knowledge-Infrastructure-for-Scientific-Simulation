#!/usr/bin/env python3
"""
build_tribs_spatial_maps.py — S2 spatial-map builder for tRIBS new basins.

Closes the documented S2 gap (the sibling of the now-resolved S1 mesh gap):
``convert_soil_params.py`` emits only the ``.sdt``/``.ldt`` *lookup tables*, but a
DISTRIBUTED tRIBS run also needs the basin-specific spatial **rasters** that map
each Voronoi node to a class / initial state:

    * ``.soi``  soil-texture-class ASCII grid   -> control file ``SOILMAPNAME:``
    * ``.lan``  land-use-class ASCII grid        -> control file ``LANDMAPNAME:``
    * ``.iwt``  initial water-table ASCII grid    -> control file ``GWATERFILE:``

No KI tool built any of these. This wraps the upstream **pytRIBS** processors
(already pip-installed in python_env, 0.5.0) which ship every needed writer:

    pytRIBS.soil.SoilProcessor.create_soil_map([sand,clay] -> .soi)  (InOut.write_ascii)
    pytRIBS.soil.SoilProcessor.write_soil_table(classes -> .sdt)
    pytRIBS.soil.SoilProcessor.run_soil_workflow(watershed, out)      (SoilGrids250 fetch; online)
    pytRIBS.soil.SoilProcessor.generate_uniform_groundwater(ws, value -> .iwt)
    pytRIBS.shared.InOut.write_ascii(reclassed landcover -> .lan)
    pytRIBS.shared.InOut.write_landuse_table(rows -> .ldt)

Inputs are the watershed boundary shapefile written by ``build_tribs_mesh.py``
(``<prefix>_watershed.shp``) plus local clipped sand/clay/landcover rasters
(HWSD / SoilGrids / NLCD-MODIS-ESA), OR ``--soil-mode workflow`` to let pytRIBS
fetch SoilGrids250 for the watershed bbox.

USAGE
    # Local rasters already clipped to the basin (no network):
    python3 build_tribs_spatial_maps.py \
        --watershed run/sounding_creek_watershed.shp \
        --epsg 32612 \
        --soil-mode local \
        --sand-raster soil/sand_pct.tif --clay-raster soil/clay_pct.tif \
        --landcover-raster land/landcover.tif --land-reclass land/reclass.json \
        --gw-depth 5.0 \
        --out-dir run/spatial

    # SoilGrids250 workflow (downloads soil grids for the watershed bbox):
    python3 build_tribs_spatial_maps.py \
        --watershed run/sounding_creek_watershed.shp --epsg 32612 \
        --soil-mode workflow --gw-depth 5.0 --out-dir run/spatial

Emits, under --out-dir:
    soil_classes.soi, soils.sdt, (scgrid.gdf if workflow), groundwater.iwt,
    landuse.lan, landuse.ldt   plus a control-file snippet (spatial_maps.in.txt).
"""
import argparse
import json
import os
import sys


def _load_watershed(watershed_path, epsg):
    import geopandas as gpd
    gdf = gpd.read_file(watershed_path)
    if gdf.crs is None:
        gdf = gdf.set_crs(epsg=int(epsg))
    elif gdf.crs.to_epsg() != int(epsg):
        gdf = gdf.to_crs(epsg=int(epsg))
    return gdf


def build_soil(soil, watershed, args):
    """Returns (soi_path, sdt_path[, scgrid_path])."""
    if args.soil_mode == "workflow":
        # Full SoilGrids250 fetch + classify (online); sets soilmapname/soiltablename/scgrid.
        soil.run_soil_workflow(watershed, args.out_dir)
        return (soil.soilmapname["value"], soil.soiltablename["value"],
                soil.scgrid["value"])
    # local: classify from already-clipped sand/clay percent rasters
    if not (args.sand_raster and args.clay_raster):
        sys.exit("--soil-mode local requires --sand-raster and --clay-raster")
    soi_path = os.path.join(args.out_dir, "soil_classes.soi")
    sdt_path = os.path.join(args.out_dir, "soils.sdt")
    grids = [{"type": "sand", "path": args.sand_raster},
             {"type": "clay", "path": args.clay_raster}]
    classes = soil.create_soil_map(grids, output=soi_path)
    soil.write_soil_table(classes, sdt_path, textures=True)
    return (soi_path, sdt_path, None)


def build_groundwater(soil, watershed, args):
    """Uniform initial water-table grid (.iwt / GWATERFILE)."""
    iwt_path = os.path.join(args.out_dir, "groundwater.iwt")
    soil.generate_uniform_groundwater(watershed, args.gw_depth, filename=iwt_path)
    return iwt_path


def build_land(args):
    """Reclassify a landcover raster to a tRIBS .lan grid + .ldt table."""
    from pytRIBS.shared.inout import InOut
    if not args.landcover_raster:
        return (None, None)
    import numpy as np
    import rasterio
    lan_path = os.path.join(args.out_dir, "landuse.lan")
    ldt_path = os.path.join(args.out_dir, "landuse.ldt")
    reclass = {}
    if args.land_reclass:
        with open(args.land_reclass) as fh:
            # {"source_value": tribs_class_id, ...}
            reclass = {int(k): int(v) for k, v in json.load(fh).items()}
    with rasterio.open(args.landcover_raster) as src:
        data = src.read(1)
        profile = src.profile
    out = data.copy()
    for src_val, cls in reclass.items():
        out[data == src_val] = cls
    InOut.write_ascii({"data": out, "profile": profile}, lan_path, dtype="int32")
    # Minimal .ldt: one default vegetation row per class present.
    rows = []
    for cls in sorted(int(c) for c in set(out.flatten().tolist())):
        # ID a b1 P S K bv LAI  (sane mid-range defaults; tune in calibration)
        rows.append([cls, 0.30, 0.60, 1.50, 0.40, 0.08, 0.40, 3.0])
    InOut.write_landuse_table(rows, ldt_path)
    return (lan_path, ldt_path)


def main():
    ap = argparse.ArgumentParser(description="Build tRIBS .soi/.lan/.iwt spatial maps (distributed mode).")
    ap.add_argument("--watershed", required=True, help="Watershed boundary shapefile (from build_tribs_mesh.py).")
    ap.add_argument("--epsg", required=True, type=int, help="UTM EPSG of the basin/rasters.")
    ap.add_argument("--out-dir", required=True, help="Output directory for spatial maps.")
    ap.add_argument("--soil-mode", choices=["local", "workflow"], default="local")
    ap.add_argument("--sand-raster", help="(local) sand-percent GeoTIFF clipped to basin.")
    ap.add_argument("--clay-raster", help="(local) clay-percent GeoTIFF clipped to basin.")
    ap.add_argument("--landcover-raster", help="Landcover class GeoTIFF clipped to basin.")
    ap.add_argument("--land-reclass", help="JSON {source_class: tribs_class} remap for the .lan grid.")
    ap.add_argument("--gw-depth", type=float, default=5.0, help="Uniform initial water-table depth (m) for .iwt.")
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    from pytRIBS.classes import Soil
    meta = {"Name": os.path.basename(args.out_dir.rstrip("/")), "EPSG": int(args.epsg), "Scenario": "Base"}
    soil = Soil(meta=meta)

    watershed = _load_watershed(args.watershed, args.epsg)
    soi, sdt, scgrid = build_soil(soil, watershed, args)
    iwt = build_groundwater(soil, watershed, args)
    lan, ldt = build_land(args)

    snippet = os.path.join(args.out_dir, "spatial_maps.in.txt")
    with open(snippet, "w") as fh:
        fh.write("OPTSOILTYPE:\n1\n")
        fh.write(f"SOILMAPNAME:\n{soi}\n")
        fh.write(f"SOILTABLENAME:\n{sdt}\n")
        if scgrid:
            fh.write(f"SCGRID:\n{scgrid}\n")
        fh.write("OPTGROUNDWATER:\n1\nOPTGWFILE:\n0\n")
        fh.write(f"GWATERFILE:\n{iwt}\n")
        if lan:
            fh.write(f"OPTLANDUSE:\n1\nLANDMAPNAME:\n{lan}\nLANDTABLENAME:\n{ldt}\n")
    print(f"[build_tribs_spatial_maps] soi={soi}")
    print(f"[build_tribs_spatial_maps] sdt={sdt}")
    print(f"[build_tribs_spatial_maps] iwt={iwt}")
    print(f"[build_tribs_spatial_maps] lan={lan} ldt={ldt}")
    print(f"[build_tribs_spatial_maps] control-file snippet -> {snippet}")


if __name__ == "__main__":
    sys.exit(main())
