#!/usr/bin/env python3
"""
build_tribs_mesh.py — S1 mesh builder for tRIBS new basins.

Wraps the upstream **pytRIBS** preprocessing toolkit (pytRIBS.mesh.Preprocess +
GenerateMesh + shared.InOut) to turn a DEM + outlet coordinate into a tRIBS
``.points`` file (UTM x, y, z + boundary codes) suitable for ``OPTMESHINPUT 1``.
tRIBS performs its own Delaunay/Voronoi triangulation from this point cloud, so
no separate ``.nodes/.edges/.tri/.z`` build is required.

This closes the documented S1 STRUCTURAL BLOCKER: previously no KI tool built a
TIN mesh, so brand-new basins could not be set up (only the shipped Zenodo
benchmarks, which already contain meshes, were runnable).

Pipeline (all steps via pytRIBS / WhiteboxTools, already on disk):
    DEM ──fill_depressions──> filled DEM
        ──generate_flow_direction_raster──> D8 pointer
        ──generate_flow_accumulation_raster──> flow accumulation
        ──create_outlet(x,y,...)──> snapped pour-point shapefile
        ──generate_streams_raster(threshold_area)──> streams raster
        ──generate_watershed_mask──> watershed raster
        ──generate_watershed_boundary──> watershed boundary
        ──GenerateMesh.extract_points_from_significant_details(threshold)──>
              points [x, y, z, bnd_code]  (stream nodes code 3, boundary 1, interior 0)
        ──InOut.write_point_file──> <out_prefix>.points

Boundary codes follow the tRIBS convention documented in
docs/s1_mesh_preparation.md: 0=interior, 1=closed boundary, 2=open boundary,
3=stream node. pytRIBS assigns code 3 along the extracted stream path and
boundary codes around the watershed polygon.

Spatial soil/landuse maps (.soi/.lan/.iwt) are NOT produced here; use pytRIBS
SoilProcessor.run_soil_workflow() / LandProcessor for those (see SKILL.md S2).

USAGE
    python3 build_tribs_mesh.py \
        --dem /path/to/dem_utm.tif \
        --outlet-x 480000 --outlet-y 5710000 \
        --epsg 32612 \
        --threshold-area 1.0e6 \
        --snap-distance 200 \
        --mesh-threshold 0.5 \
        --out-prefix /path/to/run/sounding_creek

The DEM MUST already be in a metric UTM projection (meters). Outlet coordinates
are in the SAME UTM CRS (use --outlet-lat/--outlet-lon to supply lat/lon and let
the tool reproject to the given --epsg).
"""
import argparse
import os
import sys


def _reproject_lonlat(lon, lat, epsg):
    """Project a lon/lat pair to the target UTM EPSG (meters)."""
    from pyproj import Transformer
    tr = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
    x, y = tr.transform(lon, lat)
    return x, y


def build_mesh(dem, outlet_x, outlet_y, epsg, threshold_area,
               snap_distance, mesh_threshold, out_prefix, verbose=True):
    """Run the pytRIBS DEM->.points pipeline. Returns the .points path."""
    # Imported lazily so --help works without pytRIBS installed.
    from pytRIBS.mesh.mesh import Preprocess, GenerateMesh
    from pytRIBS.shared.inout import InOut

    workdir = os.path.dirname(os.path.abspath(out_prefix)) or "."
    os.makedirs(workdir, exist_ok=True)
    meta = {"Name": os.path.basename(out_prefix), "EPSG": int(epsg), "Scenario": "Base"}

    # Preprocess: outlet given as (x, y) in the DEM's UTM CRS.
    pre = Preprocess(
        outlet=(outlet_x, outlet_y),
        snap_distance=snap_distance,
        threshold_area=threshold_area,
        dem_path=dem,
        verbose_mode=verbose,
        meta=meta,
        dir_proccesed=workdir,
    )

    filled = pre.fill_depressions()
    d8 = pre.generate_flow_direction_raster(filled)
    facc = pre.generate_flow_accumulation_raster(d8)
    outlet_shp = pre.create_outlet(outlet_x, outlet_y, facc, snap_distance)
    streams = pre.generate_streams_raster(facc, threshold_area)
    ws_mask = pre.generate_watershed_mask(d8, outlet_shp)
    # generate_watershed_boundary returns (gdf, path); force a .shp output so
    # the downstream gpd.read_file gets a real vector (the pytRIBS default
    # writes a vector to a ".tif"-named path, which geopandas mishandles).
    _ws_bound_gdf, ws_bound = pre.generate_watershed_boundary(
        ws_mask, output_path=out_prefix + "_watershed.shp")
    streams_shp = pre.convert_stream_raster_to_vector(streams, d8)

    # GenerateMesh: variable-resolution point cloud with boundary codes.
    gm = GenerateMesh(
        path_to_raster=filled,
        path_to_watershed=ws_bound,
        path_to_stream_network=streams_shp,
        path_to_outlet=outlet_shp,
    )
    points, _buffered_ws = gm.extract_points_from_significant_details(mesh_threshold)
    gdf = GenerateMesh.convert_points_to_gdf(points)

    points_path = out_prefix + ".points"
    InOut.write_point_file(gdf, points_path)
    return points_path


def main():
    ap = argparse.ArgumentParser(description="Build a tRIBS .points mesh from a DEM (OPTMESHINPUT=1).")
    ap.add_argument("--dem", required=True, help="DEM GeoTIFF in metric UTM (meters).")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--outlet-xy", nargs=2, type=float, metavar=("X", "Y"),
                   help="Outlet X Y in the DEM's UTM CRS (meters).")
    g.add_argument("--outlet-lonlat", nargs=2, type=float, metavar=("LON", "LAT"),
                   help="Outlet lon lat (deg); reprojected to --epsg.")
    ap.add_argument("--epsg", required=True, type=int, help="UTM EPSG code of the DEM/outlet.")
    ap.add_argument("--threshold-area", type=float, default=1.0e6,
                    help="Stream-init flow-accumulation threshold in m^2 (default 1e6).")
    ap.add_argument("--snap-distance", type=float, default=200.0,
                    help="Pour-point snap distance in meters (default 200).")
    ap.add_argument("--mesh-threshold", type=float, default=0.5,
                    help="Wavelet significance threshold for node density (default 0.5).")
    ap.add_argument("--out-prefix", required=True,
                    help="Output path prefix; writes <prefix>.points.")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    if args.outlet_lonlat is not None:
        lon, lat = args.outlet_lonlat
        ox, oy = _reproject_lonlat(lon, lat, args.epsg)
    else:
        ox, oy = args.outlet_xy

    points = build_mesh(
        dem=args.dem, outlet_x=ox, outlet_y=oy, epsg=args.epsg,
        threshold_area=args.threshold_area, snap_distance=args.snap_distance,
        mesh_threshold=args.mesh_threshold, out_prefix=args.out_prefix,
        verbose=not args.quiet,
    )
    print(f"[build_tribs_mesh] wrote {points}")
    print("[build_tribs_mesh] set in .in:  OPTMESHINPUT\\n1\\nINPUTDATAFILE\\n" + args.out_prefix)


if __name__ == "__main__":
    sys.exit(main())
