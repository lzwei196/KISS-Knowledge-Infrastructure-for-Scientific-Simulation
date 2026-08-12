#!/usr/bin/env python3
"""
build_groundwater.py  --  WRF-Hydro Phase 2, Tool 4
====================================================
Build groundwater and ancillary domain files for WRF-Hydro:

  1. GWBASINS.nc       — groundwater basin IDs on LSM grid
  2. GWBUCKPARM.nc     — bucket model parameters per basin
  3. hydro2dtbl.nc     — 2D routing parameter lookup (OV_ROUGH, LKSAT, SMCMAX1, etc.)
  4. GEOGRID_LDASOUT_Spatial_Metadata.nc — spatial reference for output files

For a single-basin setup, all land cells get BASIN=1. The bucket parameters
use WRF-Hydro defaults (Coeff=1.0, Expon=3.0, Zmax=50, Zinit=10).

hydro2dtbl.nc is built by looking up HYDRO.TBL per-cell using ISLTYP and
IVGTYP from geo_em.

Usage
-----
    python build_groundwater.py \\
        --geo_em outputs/.../geo_em.d01.nc \\
        --domain_json outputs/.../domain_def.json \\
        --basin_shp data/shp/.../basin.shp \\
        --output_dir outputs/.../DOMAIN/
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

import geopandas as gpd
import netCDF4 as nc
import numpy as np
from pyproj import Transformer
from rasterio.crs import CRS as RioCRS
from rasterio.features import rasterize
from rasterio.transform import from_origin


DEFAULT_HYDRO_TBL = Path(os.path.join(os.environ.get("HYDROCRAFT_ROOT", "/mnt/disk1/Hydrocraft_server"), "model/wrf_hydro/source/trunk/NDHMS/Run/HYDRO.TBL"))


def parse_hydro_tbl(tbl_path):
    """Parse HYDRO.TBL for overland roughness and soil hydraulic params.

    Returns:
        ov_rough: dict veg_type (1-28) -> OV_ROUGH value
        soil_hydro: dict soil_type (1-19) -> {SATDK, MAXSMC, REFSMC, WLTSMC}
    """
    text = Path(tbl_path).read_text()
    lines = text.splitlines()

    # Part 1: OV_ROUGH (lines after the header until line with just a number)
    ov_rough = {}
    in_rough = False
    for line in lines:
        s = line.strip()
        if "SFC_ROUGH" in s:
            in_rough = True
            continue
        if in_rough:
            # Lines like "0.025, 'Urban and Built-Up Land'"
            m = re.match(r"([\d.]+)\s*,\s*'(.+)'", s)
            if m:
                val = float(m.group(1))
                idx = len(ov_rough) + 1
                ov_rough[idx] = val
            elif s.startswith("19") or s.startswith("28"):
                # Transition to soil section
                in_rough = False
                continue
            elif not s:
                continue

    # Part 2: Soil hydraulic params
    # Format: "SATDK  MAXSMC  REFSMC  WLTSMC  QTZ  '
    # Then: "4.66E-5, 0.339, 0.192, 0.010, 0.92, 'SAND'"
    soil_hydro = {}
    in_soil = False
    for line in lines:
        s = line.strip()
        if "SATDK" in s and "MAXSMC" in s:
            in_soil = True
            continue
        if in_soil:
            # Data: "4.66E-5, 0.339, 0.192, 0.010, 0.92, 'SAND'"
            data_part = re.sub(r"'[^']*'", "", s).strip().rstrip(",")
            parts = [p.strip() for p in data_part.split(",") if p.strip()]
            if len(parts) >= 4:
                try:
                    satdk = float(parts[0])
                    maxsmc = float(parts[1])
                    refsmc = float(parts[2])
                    wltsmc = float(parts[3])
                    sid = len(soil_hydro) + 1
                    soil_hydro[sid] = {
                        "SATDK": satdk, "MAXSMC": maxsmc,
                        "REFSMC": refsmc, "WLTSMC": wltsmc,
                    }
                except ValueError:
                    pass
            elif not s:
                if soil_hydro:
                    break

    print(f"  Parsed HYDRO.TBL: {len(ov_rough)} veg roughness, {len(soil_hydro)} soil types")
    return ov_rough, soil_hydro


def write_crs_variable(ds, dom, dx, dy):
    """Write a CRS variable and spatial reference global attrs to a NetCDF dataset."""
    cen_lat = dom["cen_lat"]
    stand_lon = dom["stand_lon"]
    truelat1 = dom["truelat1"]
    truelat2 = dom["truelat2"]
    earth_r = dom.get("wrf_earth_radius", 6370000.0)
    proj4 = dom["proj4"]
    x_sw = dom["x_sw"]
    y_sw = dom["y_sw"]
    e_sn = dom["e_sn"]

    y_top = y_sw + e_sn * dom["dy"]
    x_left = x_sw

    esri_pe = (
        f'PROJCS["unnamed",GEOGCS["GCS_Sphere",'
        f'DATUM["D_Sphere",SPHEROID["unnamed",{earth_r},0.0]],'
        f'PRIMEM["Greenwich",0.0],UNIT["Degree",0.0174532925199433]],'
        f'PROJECTION["Lambert_Conformal_Conic"],'
        f'PARAMETER["False_Easting",0.0],PARAMETER["False_Northing",0.0],'
        f'PARAMETER["Central_Meridian",{stand_lon}],'
        f'PARAMETER["Standard_Parallel_1",{truelat1}],'
        f'PARAMETER["Standard_Parallel_2",{truelat2}],'
        f'PARAMETER["Latitude_Of_Origin",{cen_lat}],'
        f'UNIT["Meter",1.0]]'
    )

    vcrs = ds.createVariable("crs", "S1", ())
    vcrs.transform_name = "lambert_conformal_conic"
    vcrs.grid_mapping_name = "lambert_conformal_conic"
    vcrs.esri_pe_string = esri_pe
    vcrs.long_name = "CRS definition"
    vcrs.longitude_of_prime_meridian = 0.0
    vcrs.GeoTransform = f"{x_left} {dx} 0 {y_top} 0 {-dy}"
    vcrs._CoordinateAxes = "y x"
    vcrs._CoordinateTransformType = "Projection"
    vcrs.standard_parallel = np.array([truelat1, truelat2], dtype=np.float64)
    vcrs.longitude_of_central_meridian = float(stand_lon)
    vcrs.latitude_of_projection_origin = float(cen_lat)
    vcrs.false_easting = 0.0
    vcrs.false_northing = 0.0
    vcrs.earth_radius = float(earth_r)
    vcrs.semi_major_axis = float(earth_r)
    vcrs.inverse_flattening = 0.0

    return esri_pe


def write_spatial_global_attrs(ds, dom, proj4, esri_pe):
    """Write standard spatial global attrs."""
    ds.Conventions = "CF-1.5"
    ds.GDAL_DataType = "Generic"
    ds.Source_Software = "HydroCraft WRF-Hydro build_groundwater.py"
    ds.proj4 = proj4
    ds.history = "Created by build_groundwater.py"
    ds.processing_notes = ""
    ds.spatial_ref = esri_pe
    ds.MAP_PROJ = 1
    ds.TRUELAT1 = float(dom["truelat1"])
    ds.TRUELAT2 = float(dom["truelat2"])
    ds.STAND_LON = float(dom["stand_lon"])
    ds.POLE_LAT = 90.0
    ds.POLE_LON = 0.0
    ds.MOAD_CEN_LAT = float(dom["cen_lat"])
    ds.CEN_LAT = float(dom["cen_lat"])
    ds.DX = float(dom["dx"])
    ds.DY = float(dom["dy"])


def build_groundwater(geo_em_path, domain_json_path, basin_shp_path, output_dir,
                      hydro_tbl_path=None, gw_coeff=None, gw_expon=None,
                      gw_zmax=None, gw_zinit=None, coeff_per_100km2=None):
    """Build GWBASINS.nc, GWBUCKPARM.nc, hydro2dtbl.nc, GEOGRID_LDASOUT_Spatial_Metadata.nc."""

    if hydro_tbl_path is None:
        hydro_tbl_path = DEFAULT_HYDRO_TBL

    print(f"[build_groundwater] Output dir: {output_dir}")
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # Load domain definition
    with open(domain_json_path) as f:
        dom = json.load(f)

    dx_lsm = dom["dx"]
    dy_lsm = dom["dy"]
    e_we = dom["e_we"]
    e_sn = dom["e_sn"]
    x_sw = dom["x_sw"]
    y_sw = dom["y_sw"]
    proj4 = dom["proj4"]
    cen_lat = dom["cen_lat"]
    stand_lon = dom["stand_lon"]
    truelat1 = dom["truelat1"]
    truelat2 = dom["truelat2"]
    earth_r = dom.get("wrf_earth_radius", 6370000.0)

    x_left = x_sw
    y_top = y_sw + e_sn * dy_lsm

    # Cell centers
    x_centers = x_left + (np.arange(e_we) + 0.5) * dx_lsm
    y_centers = y_top  - (np.arange(e_sn) + 0.5) * dy_lsm

    lcc_crs = RioCRS.from_proj4(proj4)
    lsm_transform = from_origin(x_left, y_top, dx_lsm, dy_lsm)

    # Read geo_em for soil/veg types
    print(f"  Reading geo_em: {geo_em_path}")
    geo = nc.Dataset(geo_em_path, "r")
    isltyp = geo["SCT_DOM"][0, :, :].astype(np.int32)
    ivgtyp = geo["LU_INDEX"][0, :, :].astype(np.int32)
    landmask = geo["LANDMASK"][0, :, :].astype(np.int32)
    geo.close()

    sn, we = e_sn, e_we
    print(f"  Grid: {sn} x {we}")

    # === 1. GWBASINS.nc ===
    print("  Building GWBASINS.nc...")

    # Rasterize basin to LSM grid — single basin = all cells get 1
    basin_gdf = gpd.read_file(basin_shp_path)
    basin_gdf = basin_gdf.to_crs(lcc_crs)
    shapes = [(geom, 1) for geom in basin_gdf.geometry if geom is not None]
    basin_grid = np.zeros((sn, we), dtype=np.int32)
    if shapes:
        basin_grid = rasterize(
            shapes, out_shape=(sn, we),
            transform=lsm_transform, fill=0, dtype=np.int32,
        )
    # Where LANDMASK is 0 (water), also set basin to 0
    # For GW, every land cell in the basin gets a basin ID
    n_basin_cells = int((basin_grid > 0).sum())
    print(f"    Basin land cells: {n_basin_cells}")

    gwbasins_path = Path(output_dir) / "GWBASINS.nc"
    out = nc.Dataset(str(gwbasins_path), "w", format="NETCDF4")
    out.createDimension("y", sn)
    out.createDimension("x", we)

    vy = out.createVariable("y", "f8", ("y",))
    vy.units = "m"
    vy[:] = y_centers

    vx = out.createVariable("x", "f8", ("x",))
    vx.units = "m"
    vx[:] = x_centers

    esri_pe = write_crs_variable(out, dom, dx_lsm, dy_lsm)

    vb = out.createVariable("BASIN", "i4", ("y", "x"), fill_value=False)
    vb.grid_mapping = "crs"
    vb[:] = basin_grid

    write_spatial_global_attrs(out, dom, proj4, esri_pe)
    out.close()
    print(f"    Written: {gwbasins_path}")

    # === 2. GWBUCKPARM.nc ===
    print("  Building GWBUCKPARM.nc...")

    # For single-basin: 1 feature
    unique_basins = np.unique(basin_grid[basin_grid > 0])
    n_basins = len(unique_basins)
    if n_basins == 0:
        n_basins = 1
        unique_basins = np.array([1])

    # Compute area per basin in km^2
    cell_area_km2 = (dx_lsm * dy_lsm) / 1.0e6
    basin_areas = np.array([
        float(np.sum(basin_grid == bid)) * cell_area_km2
        for bid in unique_basins
    ], dtype=np.float32)

    gwbuck_path = Path(output_dir) / "GWBUCKPARM.nc"

    # Check if UDMP mode: one bucket per reach (requires Route_Link.nc)
    route_link_path = Path(output_dir) / "Route_Link.nc"
    use_udmp = route_link_path.exists()

    if use_udmp:
        # UDMP mode: one groundwater bucket per channel reach
        # WRF-Hydro requires 'BasinDim' dimension (not 'feature_id') for UDMP_OPT=1
        rl = nc.Dataset(str(route_link_path))
        link_ids = rl['link'][:]
        n_links = len(link_ids)
        rl.close()

        out = nc.Dataset(str(gwbuck_path), "w", format="NETCDF4")
        out.createDimension("BasinDim", n_links)

        def write_1d(name, data, dtype):
            v = out.createVariable(name, dtype, ("BasinDim",))
            v[:] = data

        # Default bucket params per reach (same values, distributed)
        avg_area = float(basin_areas.sum()) / max(n_links, 1)
        write_1d("Basin", link_ids, "i4")
        write_1d("Coeff", np.full(n_links, 5.0, dtype=np.float32), "f4")
        write_1d("Expon", np.full(n_links, 2.0, dtype=np.float32), "f4")
        write_1d("Zmax", np.full(n_links, 200.0, dtype=np.float32), "f4")
        write_1d("Zinit", np.full(n_links, 10.0, dtype=np.float32), "f4")
        write_1d("Area_sqkm", np.full(n_links, max(avg_area, 1.0), dtype=np.float32), "f4")
        write_1d("ComID", link_ids, "i4")

        out.featureType = "point"
        out.history = "Created by build_groundwater.py (UDMP mode, 1 bucket per reach)"
        out.close()
        print(f"    Written: {gwbuck_path} (UDMP: {n_links} reach-based basins)")
    else:
        # Gridded mode: single or multi-basin bucket
        out = nc.Dataset(str(gwbuck_path), "w", format="NETCDF4")
        out.createDimension("feature_id", n_basins)

        def write_1d(name, data, dtype):
            v = out.createVariable(name, dtype, ("feature_id",))
            v[:] = data

        write_1d("Basin", unique_basins, "i4")
        # Gridded-mode bucket parameters. Legacy defaults (Coeff=1.0, Expon=3.0,
        # Zmax=50, Zinit=10) pin the bucket at Zmax on large humid basins
        # (dt_v013 / dag safety.hazards.gw_zmax_too_shallow: pure pass-through,
        # no recession). Override via CLI; --coeff_per_100km2 area-scales the
        # NWM reach-scale Coeff (~0.04 per ~100 km2) to the lumped basin.
        coeff_arr = np.ones(n_basins, dtype=np.float32)
        if coeff_per_100km2 is not None:
            coeff_arr = (basin_areas / 100.0 * float(coeff_per_100km2)).astype(np.float32)
        if gw_coeff is not None:
            coeff_arr = np.full(n_basins, float(gw_coeff), dtype=np.float32)
        expon_val = 3.0 if gw_expon is None else float(gw_expon)
        zmax_val = 50.0 if gw_zmax is None else float(gw_zmax)
        zinit_val = 10.0 if gw_zinit is None else float(gw_zinit)
        if zmax_val <= 50.0 and float(basin_areas.max()) > 10000.0:
            print("    WARNING: Zmax<=50 mm on a >10,000 km2 basin pins the bucket at"
                  " Zmax (dt_v013); pass --zmax 200-500 and size Coeff to the basin")
        print(f"    GWBUCKPARM gridded params: Coeff={coeff_arr.tolist()} Expon={expon_val}"
              f" Zmax={zmax_val} Zinit={zinit_val}")
        write_1d("Coeff", coeff_arr, "f4")
        write_1d("Expon", np.full(n_basins, expon_val, dtype=np.float32), "f4")
        write_1d("Zmax", np.full(n_basins, zmax_val, dtype=np.float32), "f4")
        write_1d("Zinit", np.full(n_basins, zinit_val, dtype=np.float32), "f4")
        write_1d("Area_sqkm", basin_areas, "f4")
        write_1d("ComID", unique_basins, "i4")

        out.featureType = "point"
        out.history = "Created by build_groundwater.py (gridded mode)"
        out.close()
        print(f"    Written: {gwbuck_path} ({n_basins} gridded basins)")

    # === 3. hydro2dtbl.nc ===
    print("  Building hydro2dtbl.nc...")

    ov_rough_tbl, soil_hydro_tbl = parse_hydro_tbl(hydro_tbl_path)
    # Fallbacks
    default_rough = 0.055  # Grassland
    default_soil = soil_hydro_tbl.get(6, {"SATDK": 3.38e-6, "MAXSMC": 0.439,
                                           "REFSMC": 0.329, "WLTSMC": 0.066})

    ov_rough2d = np.zeros((sn, we), dtype=np.float32)
    lksat2d    = np.zeros((sn, we), dtype=np.float32)
    smcmax1    = np.zeros((sn, we), dtype=np.float32)
    smcref1    = np.zeros((sn, we), dtype=np.float32)
    smcwlt1    = np.zeros((sn, we), dtype=np.float32)

    for j in range(sn):
        for i in range(we):
            vt = int(ivgtyp[j, i])
            st = int(isltyp[j, i])

            ov_rough2d[j, i] = ov_rough_tbl.get(vt, default_rough)

            sp = soil_hydro_tbl.get(st, default_soil)
            lksat2d[j, i]  = sp["SATDK"]
            smcmax1[j, i]  = sp["MAXSMC"]
            smcref1[j, i]  = sp["REFSMC"]
            smcwlt1[j, i]  = sp["WLTSMC"]

    hydro2d_path = Path(output_dir) / "hydro2dtbl.nc"
    out = nc.Dataset(str(hydro2d_path), "w", format="NETCDF4")
    out.createDimension("south_north", sn)
    out.createDimension("west_east", we)

    def w2d(name, data):
        v = out.createVariable(name, "f4", ("south_north", "west_east"), fill_value=False)
        v[:] = data

    w2d("LKSAT", lksat2d)
    w2d("OV_ROUGH2D", ov_rough2d)
    w2d("SMCMAX1", smcmax1)
    w2d("SMCREF1", smcref1)
    w2d("SMCWLT1", smcwlt1)

    # Copy global attrs from geo_em (same as wrfinput)
    geo2 = nc.Dataset(geo_em_path, "r")
    for attr in geo2.ncattrs():
        out.setncattr(attr, geo2.getncattr(attr))
    geo2.close()

    out.close()
    print(f"    Written: {hydro2d_path}")

    # === 4. GEOGRID_LDASOUT_Spatial_Metadata.nc ===
    print("  Building GEOGRID_LDASOUT_Spatial_Metadata.nc...")

    meta_path = Path(output_dir) / "GEOGRID_LDASOUT_Spatial_Metadata.nc"
    out = nc.Dataset(str(meta_path), "w", format="NETCDF4")
    out.createDimension("y", sn)
    out.createDimension("x", we)

    vy = out.createVariable("y", "f8", ("y",))
    vy.units = "m"
    vy.resolution = float(dy_lsm)   # CRITICAL: WRF-Hydro requires this attribute (dt_v037)
    vy[:] = y_centers

    vx = out.createVariable("x", "f8", ("x",))
    vx.units = "m"
    vx.resolution = float(dx_lsm)   # CRITICAL: WRF-Hydro requires this attribute (dt_v037)
    vx[:] = x_centers

    esri_pe2 = write_crs_variable(out, dom, dx_lsm, dy_lsm)
    write_spatial_global_attrs(out, dom, proj4, esri_pe2)

    # Additional corner coord attrs from geo_em
    geo3 = nc.Dataset(geo_em_path, "r")
    if "corner_lats" in geo3.ncattrs():
        out.corner_lats = geo3.getncattr("corner_lats")
        out.corner_lons = geo3.getncattr("corner_lons")
    geo3.close()

    out.close()
    print(f"    Written: {meta_path}")

    print(f"  [OK] All groundwater/ancillary files created in {output_dir}")
    return output_dir


def main():
    parser = argparse.ArgumentParser(
        description="Build GWBASINS.nc, GWBUCKPARM.nc, hydro2dtbl.nc, "
                    "GEOGRID_LDASOUT_Spatial_Metadata.nc for WRF-Hydro")
    parser.add_argument("--geo_em", required=True, help="Path to geo_em.d01.nc")
    parser.add_argument("--domain_json", required=True, help="Path to domain_def.json")
    parser.add_argument("--basin_shp", required=True, help="Path to basin shapefile")
    parser.add_argument("--output_dir", required=True, help="Output directory")
    parser.add_argument("--hydro_tbl", default=str(DEFAULT_HYDRO_TBL),
                        help="Path to HYDRO.TBL")
    parser.add_argument("--coeff", type=float, default=None,
                        help="Absolute GW bucket Coeff override (gridded mode)")
    parser.add_argument("--expon", type=float, default=None,
                        help="GW bucket Expon override (gridded mode)")
    parser.add_argument("--zmax", type=float, default=None,
                        help="GW bucket Zmax mm override (dag: 200-500 for deep-aquifer basins)")
    parser.add_argument("--zinit", type=float, default=None,
                        help="GW bucket Zinit mm override")
    parser.add_argument("--coeff_per_100km2", type=float, default=None,
                        help="Area-scale Coeff: Coeff_i = value * Area_sqkm_i/100 (dag Coeff~0.04 at ~100 km2 reach scale)")
    args = parser.parse_args()

    build_groundwater(
        geo_em_path=args.geo_em,
        domain_json_path=args.domain_json,
        basin_shp_path=args.basin_shp,
        output_dir=args.output_dir,
        hydro_tbl_path=args.hydro_tbl,
        gw_coeff=args.coeff,
        gw_expon=args.expon,
        gw_zmax=args.zmax,
        gw_zinit=args.zinit,
        coeff_per_100km2=args.coeff_per_100km2,
    )


if __name__ == "__main__":
    main()
