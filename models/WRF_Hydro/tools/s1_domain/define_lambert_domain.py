#!/usr/bin/env python3
"""
define_lambert_domain.py  --  WRF-Hydro Phase 1, Tool 1
=========================================================
Define a Lambert Conformal Conic domain that covers a given basin shapefile.
Outputs a JSON file consumed by build_geo_em.py and all downstream tools.

WRF convention: the LCC projection uses an Earth *sphere* with R = 6370000 m,
NOT the WGS-84 ellipsoid. This script uses that sphere everywhere.

Usage
-----
    python define_lambert_domain.py \
        --basin_shp  data/shp/chaohe_zhangjiaofen_boundary_shp/chaohe_zhangjiaofen_boundary.shp \
        --dx 1000 \
        --truelat1 30 --truelat2 60 \
        --stand_lon 116.5 \
        --buffer_cells 3 \
        --output domain_def.json
"""

import argparse
import json
import sys
from pathlib import Path

import math

import geopandas as gpd
import numpy as np
from pyproj import Transformer

# ---------------------------------------------------------------------------
# WRF sphere radius (metres)
# ---------------------------------------------------------------------------
WRF_EARTH_RADIUS = 6370000.0


def compute_required_srtm_tiles(corner_lats_geo, corner_lons_geo, buffer_deg=0.5):
    """Compute the list of SRTM GL1 tile names needed to cover a domain.

    Parameters
    ----------
    corner_lats_geo : array-like
        Geographic latitudes of the domain corners (degrees).
    corner_lons_geo : array-like
        Geographic longitudes of the domain corners (degrees).
    buffer_deg : float
        Buffer in degrees added around the bounding box (default 0.5).

    Returns
    -------
    tiles : list[str]
        Sorted list of SRTM tile names, e.g. ["N30E110", "S27W053"].
    lat_min, lat_max, lon_min, lon_max : float
        Buffered bounding box used for tile computation.
    """
    lat_min = min(corner_lats_geo) - buffer_deg
    lat_max = max(corner_lats_geo) + buffer_deg
    lon_min = min(corner_lons_geo) - buffer_deg
    lon_max = max(corner_lons_geo) + buffer_deg

    tiles = []
    # SRTM naming: tile name = floor(lat), floor(lon).
    # Each tile covers 1x1 degree starting from that floor value.
    lat_start = math.floor(lat_min)
    lat_end = math.floor(lat_max)
    lon_start = math.floor(lon_min)
    lon_end = math.floor(lon_max)

    for lat in range(lat_start, lat_end + 1):
        for lon in range(lon_start, lon_end + 1):
            ns = "N" if lat >= 0 else "S"
            ew = "E" if lon >= 0 else "W"
            tile_name = f"{ns}{abs(lat):02d}{ew}{abs(lon):03d}"
            tiles.append(tile_name)

    tiles.sort()
    return tiles, lat_min, lat_max, lon_min, lon_max


def build_lcc_proj4(cen_lat: float, stand_lon: float,
                    truelat1: float, truelat2: float) -> str:
    """Return a PROJ.4 string for WRF Lambert on the WRF sphere."""
    return (
        f"+proj=lcc +R={WRF_EARTH_RADIUS} "
        f"+lat_0={cen_lat} +lon_0={stand_lon} "
        f"+lat_1={truelat1} +lat_2={truelat2} "
        f"+x_0=0 +y_0=0 +units=m +no_defs"
    )


def main():
    parser = argparse.ArgumentParser(
        description="Define WRF Lambert Conformal domain for a basin.")
    parser.add_argument("--basin_shp", required=True,
                        help="Path to basin boundary shapefile (.shp)")
    parser.add_argument("--dx", type=float, default=1000.0,
                        help="Grid spacing in metres (default 1000)")
    parser.add_argument("--truelat1", type=float, default=30.0,
                        help="First true latitude (default 30)")
    parser.add_argument("--truelat2", type=float, default=60.0,
                        help="Second true latitude (default 60)")
    parser.add_argument("--stand_lon", type=float, default=None,
                        help="Standard longitude (default = basin centre lon)")
    parser.add_argument("--buffer_cells", type=int, default=3,
                        help="Number of buffer cells around the basin (default 3)")
    parser.add_argument("--output", default="domain_def.json",
                        help="Output JSON path")
    args = parser.parse_args()

    # ------------------------------------------------------------------
    # 1. Read shapefile, get geographic bounds
    # ------------------------------------------------------------------
    shp_path = Path(args.basin_shp)
    if not shp_path.exists():
        sys.exit(f"ERROR: shapefile not found: {shp_path}")

    gdf = gpd.read_file(shp_path)
    if gdf.crs is None:
        print("WARNING: shapefile has no CRS, assuming EPSG:4326")
        gdf = gdf.set_crs("EPSG:4326")
    else:
        gdf = gdf.to_crs("EPSG:4326")

    bounds = gdf.total_bounds  # (minx, miny, maxx, maxy) = (W, S, E, N)
    lon_min, lat_min, lon_max, lat_max = bounds
    basin_cen_lat = 0.5 * (lat_min + lat_max)
    basin_cen_lon = 0.5 * (lon_min + lon_max)

    print(f"Basin bounds (WGS-84): W={lon_min:.4f} S={lat_min:.4f} "
          f"E={lon_max:.4f} N={lat_max:.4f}")
    print(f"Basin centre: lat={basin_cen_lat:.4f}  lon={basin_cen_lon:.4f}")

    # ------------------------------------------------------------------
    # 2. Projection parameters
    # ------------------------------------------------------------------
    dx = args.dx
    dy = dx  # WRF convention: square cells

    # Auto-set true latitudes for Southern Hemisphere
    if basin_cen_lat < 0 and args.truelat1 == 30.0 and args.truelat2 == 60.0:
        # User didn't override — use hemisphere-appropriate defaults
        truelat1 = basin_cen_lat - 10
        truelat2 = basin_cen_lat + 10
        print(f"  Southern Hemisphere: auto-setting truelat1={truelat1:.2f}, truelat2={truelat2:.2f}")
    else:
        truelat1 = args.truelat1
        truelat2 = args.truelat2

    stand_lon = args.stand_lon if args.stand_lon is not None else round(basin_cen_lon, 2)

    # Initial projection centred on basin centre (will be refined below)
    proj4_init = build_lcc_proj4(basin_cen_lat, stand_lon, truelat1, truelat2)
    to_lcc = Transformer.from_proj("EPSG:4326", proj4_init, always_xy=True)

    # ------------------------------------------------------------------
    # 3. Project basin corners to LCC, determine grid extent with buffer
    # ------------------------------------------------------------------
    # Project the four geographic corners
    corner_lons = [lon_min, lon_max, lon_max, lon_min]
    corner_lats = [lat_min, lat_min, lat_max, lat_max]
    xs, ys = to_lcc.transform(corner_lons, corner_lats)
    x_min_m, x_max_m = min(xs), max(xs)
    y_min_m, y_max_m = min(ys), max(ys)

    # Also project all geometry coordinates for tighter bounding
    for geom in gdf.geometry:
        if geom is None:
            continue
        if geom.geom_type == 'Polygon':
            polys = [geom]
        elif geom.geom_type == 'MultiPolygon':
            polys = list(geom.geoms)
        else:
            continue
        for poly in polys:
            lons_arr, lats_arr = np.array(poly.exterior.coords).T
            gx, gy = to_lcc.transform(lons_arr, lats_arr)
            x_min_m = min(x_min_m, np.min(gx))
            x_max_m = max(x_max_m, np.max(gx))
            y_min_m = min(y_min_m, np.min(gy))
            y_max_m = max(y_max_m, np.max(gy))

    buf = args.buffer_cells * dx
    x_min_m -= buf
    x_max_m += buf
    y_min_m -= buf
    y_max_m += buf

    # ------------------------------------------------------------------
    # 4. Grid dimensions
    # ------------------------------------------------------------------
    # e_we = number of mass-grid columns, e_sn = number of mass-grid rows
    # WRF convention: WEST-EAST_GRID_DIMENSION = e_we + 1 (stagger dim)
    e_we = int(np.ceil((x_max_m - x_min_m) / dx))
    e_sn = int(np.ceil((y_max_m - y_min_m) / dy))

    # Ensure at least 4 cells in each direction
    e_we = max(e_we, 4)
    e_sn = max(e_sn, 4)

    print(f"Grid: e_we={e_we}, e_sn={e_sn}  ({e_we}x{e_sn} mass-grid cells)")
    print(f"  dx={dx:.0f} m, dy={dy:.0f} m")

    # ------------------------------------------------------------------
    # 5. Domain centre = centre of the grid (in LCC metres)
    # ------------------------------------------------------------------
    # Grid spans from x_min_m to x_min_m + e_we*dx
    # Mass-grid cell centres: x_min_m + (i+0.5)*dx, i = 0..e_we-1
    # Domain centre = middle of the grid
    x_cen = x_min_m + 0.5 * e_we * dx
    y_cen = y_min_m + 0.5 * e_sn * dy

    # Convert domain centre back to geographic for CEN_LAT / CEN_LON
    from_lcc = Transformer.from_proj(proj4_init, "EPSG:4326", always_xy=True)
    cen_lon, cen_lat = from_lcc.transform(x_cen, y_cen)

    print(f"Domain centre: lat={cen_lat:.6f}  lon={cen_lon:.6f}")

    # ------------------------------------------------------------------
    # 6. Rebuild projection centred on the actual domain centre
    # ------------------------------------------------------------------
    # WRF's geogrid centres the projection on CEN_LAT, so lat_0 = CEN_LAT
    # and the grid origin (SW corner of mass grid) is offset from that.
    proj4_final = build_lcc_proj4(cen_lat, stand_lon, truelat1, truelat2)
    to_lcc_final = Transformer.from_proj("EPSG:4326", proj4_final, always_xy=True)

    # Re-project domain centre in the final projection (should be near 0,0
    # but not exactly because stand_lon != cen_lon in general)
    xc, yc = to_lcc_final.transform(cen_lon, cen_lat)

    # Grid SW corner in final projection
    x_sw = xc - 0.5 * e_we * dx
    y_sw = yc - 0.5 * e_sn * dy

    print(f"Final projection lat_0={cen_lat:.6f}, lon_0={stand_lon:.2f}")
    print(f"Grid SW corner (LCC m): x={x_sw:.1f}  y={y_sw:.1f}")

    # ------------------------------------------------------------------
    # 7. Save domain definition
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # Compute required SRTM tiles from domain geographic extent
    # ------------------------------------------------------------------
    # clats, clons are already computed from corners_x, corners_y below;
    # we need them here, so compute them early using a temporary inverse.
    from_lcc_final = Transformer.from_proj(proj4_final, "EPSG:4326", always_xy=True)
    corners_x = [x_sw, x_sw + e_we * dx, x_sw + e_we * dx, x_sw]
    corners_y = [y_sw, y_sw, y_sw + e_sn * dy, y_sw + e_sn * dy]
    clons, clats = from_lcc_final.transform(corners_x, corners_y)

    srtm_tiles, lat_min_geo, lat_max_geo, lon_min_geo, lon_max_geo = \
        compute_required_srtm_tiles(clats, clons)

    domain_def = {
        "cen_lat": float(cen_lat),
        "cen_lon": float(cen_lon),
        "truelat1": float(truelat1),
        "truelat2": float(truelat2),
        "stand_lon": float(stand_lon),
        "moad_cen_lat": float(cen_lat),
        "dx": float(dx),
        "dy": float(dy),
        "e_we": int(e_we),
        "e_sn": int(e_sn),
        "map_proj": 1,  # Lambert Conformal
        "x_sw": float(x_sw),
        "y_sw": float(y_sw),
        "proj4": proj4_final,
        "basin_shp": str(shp_path.resolve()),
        "wrf_earth_radius": WRF_EARTH_RADIUS,
        "srtm_tiles": srtm_tiles,
        "domain_lat_range": [float(lat_min_geo), float(lat_max_geo)],
        "domain_lon_range": [float(lon_min_geo), float(lon_max_geo)],
    }

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(domain_def, f, indent=2)

    print(f"\nDomain definition saved to: {out_path}")
    print(f"  Grid: {e_we} x {e_sn} cells  ({dx:.0f} m)")
    print(f"  CEN_LAT={cen_lat:.6f}, CEN_LON={cen_lon:.6f}")
    print(f"  TRUELAT1={truelat1}, TRUELAT2={truelat2}, STAND_LON={stand_lon}")

    # ------------------------------------------------------------------
    # 8. Validate
    # ------------------------------------------------------------------
    # clats, clons, from_lcc_final, corners_x, corners_y already computed above (section 7)
    print(f"\nDomain geographic extent:")
    print(f"  SW: {clats[0]:.4f}N {clons[0]:.4f}E")
    print(f"  SE: {clats[1]:.4f}N {clons[1]:.4f}E")
    print(f"  NE: {clats[2]:.4f}N {clons[2]:.4f}E")
    print(f"  NW: {clats[3]:.4f}N {clons[3]:.4f}E")

    # Check basin is inside domain
    bx, by = to_lcc_final.transform(
        [lon_min, lon_max], [lat_min, lat_max])
    if (min(bx) < x_sw or max(bx) > x_sw + e_we * dx or
            min(by) < y_sw or max(by) > y_sw + e_sn * dy):
        print("WARNING: Basin extends outside the domain! Increase --buffer_cells.")
    else:
        print("OK: Basin is fully contained within the domain.")

    # Report required SRTM tiles
    print(f"\n  Required SRTM tiles ({len(srtm_tiles)}): {', '.join(srtm_tiles)}")
    print(f"  Domain lat range: [{lat_min_geo:.4f}, {lat_max_geo:.4f}]")
    print(f"  Domain lon range: [{lon_min_geo:.4f}, {lon_max_geo:.4f}]")


if __name__ == "__main__":
    main()
