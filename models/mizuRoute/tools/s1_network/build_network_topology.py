#!/usr/bin/env python3
"""build_network_topology.py — Build mizuRoute river network topology NetCDF from DEM + basin shapefile.

Uses WhiteboxTools (already installed on HydroCraft server) for:
1. Breach depressions -> D8 flow direction -> flow accumulation
2. Stream extraction (threshold-based)
3. Stream link identification (unique reach IDs)
4. Sub-basin delineation (catchments = HRUs)

Then computes reach properties and builds the mizuRoute-format network topology NetCDF.

Output NetCDF contains:
  - seg_id, tosegment, seg_length, seg_slope (reach properties)
  - hru_id, hru_seg_id, hru_area, hru_lat, hru_lon (HRU properties)

Usage:
    python build_network_topology.py \\
        --basin_shp data/shp/chaohe_boundary/chaohe_boundary.shp \\
        --dem data/dem/china_dem_90m/china_dem_90m.tif \\
        --output outputs/<run>/mizuroute_input/network_topology.nc \\
        --stream_threshold 500 \\
        --min_slope 0.0001
"""
import argparse
import json
import os
import sys
import tempfile
import shutil
from pathlib import Path

import numpy as np
import netCDF4 as nc


def validate_inputs(args):
    """Validate inputs."""
    errors = []
    if not os.path.isfile(args.basin_shp):
        errors.append(f"Basin shapefile not found: {args.basin_shp}")
    if not os.path.isfile(args.dem):
        errors.append(f"DEM file not found: {args.dem}")
    if args.stream_threshold < 10:
        errors.append(f"stream_threshold too low ({args.stream_threshold}), minimum 10")
    if args.min_slope <= 0:
        errors.append(f"min_slope must be positive, got {args.min_slope}")
    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        return False
    return True


def clip_dem_to_basin(dem_path, shp_path, output_dem, buffer_deg=0.05):
    """Clip DEM to basin extent with buffer."""
    import rasterio
    from rasterio.mask import mask as rio_mask
    import geopandas as gpd

    gdf = gpd.read_file(shp_path)
    if gdf.crs and gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)

    # Buffer the geometry
    bounds = gdf.total_bounds  # minx, miny, maxx, maxy
    from shapely.geometry import box
    clip_box = box(bounds[0] - buffer_deg, bounds[1] - buffer_deg,
                   bounds[2] + buffer_deg, bounds[3] + buffer_deg)

    with rasterio.open(dem_path) as src:
        out_image, out_transform = rio_mask(src, [clip_box], crop=True, nodata=-9999)
        out_meta = src.meta.copy()
        out_meta.update({
            'driver': 'GTiff',
            'height': out_image.shape[1],
            'width': out_image.shape[2],
            'transform': out_transform,
            'nodata': -9999,
        })

    with rasterio.open(output_dem, 'w', **out_meta) as dst:
        dst.write(out_image)

    return output_dem


def run_whitebox_pipeline(clipped_dem, workdir, stream_threshold):
    """Run WhiteboxTools stream extraction and sub-basin delineation.

    Returns paths to output rasters.
    """
    try:
        from whitebox import WhiteboxTools
    except ImportError:
        from WBT.whitebox_tools import WhiteboxTools

    wbt = WhiteboxTools()
    wbt.set_working_dir(workdir)
    wbt.set_verbose_mode(False)

    dem_name = os.path.basename(clipped_dem)

    # 1. Breach depressions
    breached = os.path.join(workdir, 'dem_breached.tif')
    print("  Breaching depressions...")
    wbt.breach_depressions(clipped_dem, breached)

    # 2. D8 flow direction
    d8_flowdir = os.path.join(workdir, 'd8_flowdir.tif')
    print("  Computing D8 flow direction...")
    wbt.d8_pointer(breached, d8_flowdir)

    # 3. D8 flow accumulation
    d8_accum = os.path.join(workdir, 'd8_accum.tif')
    print("  Computing flow accumulation...")
    wbt.d8_flow_accumulation(breached, d8_accum, out_type='cells')

    # 4. Extract streams (threshold-based)
    streams = os.path.join(workdir, 'streams.tif')
    print(f"  Extracting streams (threshold={stream_threshold} cells)...")
    wbt.extract_streams(d8_accum, streams, threshold=stream_threshold)

    # 5. Stream link identification (unique ID per reach)
    stream_links = os.path.join(workdir, 'stream_links.tif')
    print("  Identifying stream links...")
    wbt.stream_link_identifier(d8_flowdir, streams, stream_links)

    # 6. Sub-basin delineation (one per stream link = HRU)
    subbasins = os.path.join(workdir, 'subbasins.tif')
    print("  Delineating sub-basins (HRUs)...")
    wbt.subbasins(d8_flowdir, streams, subbasins)

    return {
        'dem_breached': breached,
        'd8_flowdir': d8_flowdir,
        'd8_accum': d8_accum,
        'streams': streams,
        'stream_links': stream_links,
        'subbasins': subbasins,
    }


def compute_reach_properties(rasters, min_slope):
    """Compute reach properties from the raster outputs.

    For each stream link (unique ID in stream_links raster):
    - seg_id: unique reach ID
    - seg_length: reach length in meters (from cell count * resolution)
    - seg_slope: bed slope (elevation drop / length)
    - tosegment: downstream reach ID (0 = outlet)

    For each sub-basin:
    - hru_id: sub-basin ID
    - hru_seg_id: which reach this sub-basin drains to
    - hru_area: area in m^2
    - hru_lat, hru_lon: centroid
    """
    import rasterio
    from scipy import ndimage

    # Read rasters
    with rasterio.open(rasters['stream_links']) as src:
        links = src.read(1)
        transform = src.transform
        crs = src.crs
        res_x = abs(transform[0])
        res_y = abs(transform[4])

    with rasterio.open(rasters['dem_breached']) as src:
        dem = src.read(1)

    with rasterio.open(rasters['d8_flowdir']) as src:
        flowdir = src.read(1)

    with rasterio.open(rasters['subbasins']) as src:
        subbasins = src.read(1)

    with rasterio.open(rasters['d8_accum']) as src:
        accum = src.read(1)

    # Get unique link IDs (excluding nodata/0)
    link_ids = np.unique(links)
    link_ids = link_ids[link_ids > 0]

    nrows, ncols = links.shape

    # Approximate cell size in meters (at basin center latitude)
    center_lat = transform[5] + nrows / 2 * transform[4]
    lat_rad = np.radians(abs(center_lat))
    cell_size_x = res_x * 111320 * np.cos(lat_rad)  # degrees to meters
    cell_size_y = res_y * 110540  # degrees to meters
    cell_area = cell_size_x * cell_size_y

    # WhiteboxTools D8 pointer values: 1=E, 2=NE, 4=N, 8=NW, 16=W, 32=SW, 64=S, 128=SE
    d8_row_offset = {1: 0, 2: -1, 4: -1, 8: -1, 16: 0, 32: 1, 64: 1, 128: 1}
    d8_col_offset = {1: 1, 2: 1, 4: 0, 8: -1, 16: -1, 32: -1, 64: 0, 128: 1}

    # Build reach properties
    reaches = {}
    for lid in link_ids:
        cells = np.argwhere(links == lid)
        if len(cells) == 0:
            continue

        # Reach length: count cells * cell diagonal/straight
        n_cells = len(cells)
        avg_cell_len = np.sqrt(cell_size_x ** 2 + cell_size_y ** 2) / np.sqrt(2)
        seg_length = n_cells * avg_cell_len

        # Reach slope: (max_elev - min_elev) / length
        elev_at_reach = dem[cells[:, 0], cells[:, 1]]
        elev_range = np.max(elev_at_reach) - np.min(elev_at_reach)
        seg_slope = max(elev_range / max(seg_length, 1.0), min_slope)

        # Find downstream reach: follow flowdir from the most downstream cell
        # (cell with highest flow accumulation on this reach)
        accum_at_reach = accum[cells[:, 0], cells[:, 1]]
        outlet_idx = np.argmax(accum_at_reach)
        outlet_row, outlet_col = cells[outlet_idx]

        # Follow one step downstream
        fd_val = int(flowdir[outlet_row, outlet_col])
        tosegment = 0  # default: outlet

        if fd_val in d8_row_offset:
            next_row = outlet_row + d8_row_offset[fd_val]
            next_col = outlet_col + d8_col_offset[fd_val]
            if 0 <= next_row < nrows and 0 <= next_col < ncols:
                next_link = links[next_row, next_col]
                if next_link > 0 and next_link != lid:
                    tosegment = int(next_link)

        # Upstream drainage area for channel width estimation
        max_accum = float(np.max(accum_at_reach))
        upstream_area_km2 = max_accum * cell_area / 1e6

        # Channel width from power law: W = a * A^b (Leopold & Maddock, 1953)
        # Default coefficients for moderate climate
        width = max(1.0, 2.7 * (upstream_area_km2 ** 0.35))

        reaches[int(lid)] = {
            'seg_id': int(lid),
            'tosegment': tosegment,
            'seg_length': float(seg_length),
            'seg_slope': float(seg_slope),
            'seg_width': float(width),
            'seg_manning_n': 0.03,
        }

    # Build HRU properties from sub-basins
    hru_ids = np.unique(subbasins)
    hru_ids = hru_ids[hru_ids > 0]

    hrus = {}
    for hid in hru_ids:
        cells = np.argwhere(subbasins == hid)
        if len(cells) == 0:
            continue

        # Area
        area_m2 = len(cells) * cell_area

        # Centroid (in geographic coordinates)
        mean_row = np.mean(cells[:, 0])
        mean_col = np.mean(cells[:, 1])
        centroid_lat = transform[5] + mean_row * transform[4]
        centroid_lon = transform[2] + mean_col * transform[0]

        # Which reach does this HRU drain to?
        # Find the stream link that intersects this sub-basin
        links_in_hru = links[cells[:, 0], cells[:, 1]]
        links_in_hru = links_in_hru[links_in_hru > 0]

        if len(links_in_hru) > 0:
            # Most common link ID in this sub-basin
            unique_links, counts = np.unique(links_in_hru, return_counts=True)
            hru_seg_id = int(unique_links[np.argmax(counts)])
        else:
            hru_seg_id = 0

        hrus[int(hid)] = {
            'hru_id': int(hid),
            'hru_seg_id': hru_seg_id,
            'hru_area': float(area_m2),
            'hru_lat': float(centroid_lat),
            'hru_lon': float(centroid_lon),
        }

    return reaches, hrus


def write_network_netcdf(reaches, hrus, output_path):
    """Write the network topology NetCDF in mizuRoute format."""

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    n_seg = len(reaches)
    n_hru = len(hrus)

    seg_ids = sorted(reaches.keys())
    hru_ids = sorted(hrus.keys())

    with nc.Dataset(output_path, 'w', format='NETCDF4') as ds:
        # Dimensions
        ds.createDimension('seg', n_seg)
        ds.createDimension('hru', n_hru)

        # Reach segment variables
        v = ds.createVariable('seg_id', 'i4', ('seg',))
        v.long_name = 'Unique reach segment identifier'
        v[:] = [reaches[s]['seg_id'] for s in seg_ids]

        v = ds.createVariable('tosegment', 'i4', ('seg',))
        v.long_name = 'Downstream segment ID (0=outlet)'
        v[:] = [reaches[s]['tosegment'] for s in seg_ids]

        v = ds.createVariable('seg_length', 'f8', ('seg',))
        v.long_name = 'Reach segment length'
        v.units = 'm'
        v[:] = [reaches[s]['seg_length'] for s in seg_ids]

        v = ds.createVariable('seg_slope', 'f8', ('seg',))
        v.long_name = 'Reach bed slope'
        v.units = 'm/m'
        v[:] = [reaches[s]['seg_slope'] for s in seg_ids]

        v = ds.createVariable('seg_width', 'f8', ('seg',))
        v.long_name = 'Channel width'
        v.units = 'm'
        v[:] = [reaches[s]['seg_width'] for s in seg_ids]

        v = ds.createVariable('seg_manning_n', 'f8', ('seg',))
        v.long_name = "Manning's roughness coefficient"
        v.units = '-'
        v[:] = [reaches[s]['seg_manning_n'] for s in seg_ids]

        # HRU variables
        v = ds.createVariable('hru_id', 'i4', ('hru',))
        v.long_name = 'Unique HRU identifier'
        v[:] = [hrus[h]['hru_id'] for h in hru_ids]

        v = ds.createVariable('hru_seg_id', 'i4', ('hru',))
        v.long_name = 'Reach segment ID that this HRU drains to'
        v[:] = [hrus[h]['hru_seg_id'] for h in hru_ids]

        v = ds.createVariable('hru_area', 'f8', ('hru',))
        v.long_name = 'HRU contributing area'
        v.units = 'm^2'
        v[:] = [hrus[h]['hru_area'] for h in hru_ids]

        v = ds.createVariable('hru_lat', 'f8', ('hru',))
        v.long_name = 'HRU centroid latitude'
        v.units = 'degrees_north'
        v[:] = [hrus[h]['hru_lat'] for h in hru_ids]

        v = ds.createVariable('hru_lon', 'f8', ('hru',))
        v.long_name = 'HRU centroid longitude'
        v.units = 'degrees_east'
        v[:] = [hrus[h]['hru_lon'] for h in hru_ids]

        # Global attributes
        ds.title = 'mizuRoute river network topology'
        ds.source = 'build_network_topology.py (HydroCraft)'
        ds.conventions = 'mizuRoute'
        ds.n_segments = n_seg
        ds.n_hrus = n_hru
        from datetime import datetime
        ds.history = f'Created {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}'

    return output_path


def process(args):
    """Main processing pipeline."""
    workdir = tempfile.mkdtemp(prefix='mizuroute_network_')

    try:
        # 1. Clip DEM
        clipped_dem = os.path.join(workdir, 'dem_clipped.tif')
        print("Step 1: Clipping DEM to basin extent...")
        clip_dem_to_basin(args.dem, args.basin_shp, clipped_dem)

        # 2. WhiteboxTools pipeline
        print("Step 2: Running WhiteboxTools stream extraction...")
        rasters = run_whitebox_pipeline(clipped_dem, workdir, args.stream_threshold)

        # 3. Compute reach and HRU properties
        print("Step 3: Computing reach and HRU properties...")
        reaches, hrus = compute_reach_properties(rasters, args.min_slope)
        print(f"  Reaches: {len(reaches)}, HRUs: {len(hrus)}")

        # 4. Validate topology
        print("Step 4: Validating network topology...")
        # Check for dangling references
        seg_ids = set(reaches.keys())
        for sid, reach in reaches.items():
            if reach['tosegment'] != 0 and reach['tosegment'] not in seg_ids:
                print(f"  WARNING: reach {sid} points to non-existent segment {reach['tosegment']}, setting to outlet")
                reach['tosegment'] = 0

        # Check single outlet
        outlets = [s for s, r in reaches.items() if r['tosegment'] == 0]
        print(f"  Outlet reaches: {len(outlets)} (IDs: {outlets[:5]}...)")
        if len(outlets) == 0:
            raise RuntimeError("No outlet found in network (circular topology!)")
        if len(outlets) > 1:
            print(f"  WARNING: Multiple outlets detected ({len(outlets)}). "
                  f"mizuRoute expects a single tree network. (dt_m015)")

        # 5. Write output
        print("Step 5: Writing network topology NetCDF...")
        write_network_netcdf(reaches, hrus, args.output)

        result = {
            'output_file': args.output,
            'n_segments': len(reaches),
            'n_hrus': len(hrus),
            'n_outlets': len(outlets),
            'stream_threshold': args.stream_threshold,
            'min_slope': args.min_slope,
        }

    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    return result


def validate_outputs(result):
    """Validate the output network topology."""
    errors = []

    if not os.path.isfile(result['output_file']):
        errors.append(f"Output file not created: {result['output_file']}")
        return errors

    with nc.Dataset(result['output_file'], 'r') as ds:
        required_vars = ['seg_id', 'tosegment', 'seg_length', 'seg_slope',
                        'hru_id', 'hru_seg_id', 'hru_area']
        for v in required_vars:
            if v not in ds.variables:
                errors.append(f"Required variable '{v}' missing")

        if 'seg_slope' in ds.variables:
            slopes = ds.variables['seg_slope'][:]
            if np.any(slopes <= 0):
                errors.append("Some reaches have zero or negative slope (dt_m007)")

        if 'seg_length' in ds.variables:
            lengths = ds.variables['seg_length'][:]
            if np.any(lengths <= 0):
                errors.append("Some reaches have zero or negative length")

    return errors


def main():
    parser = argparse.ArgumentParser(description='Build mizuRoute network topology from DEM')
    parser.add_argument('--basin_shp', required=True, help='Basin boundary shapefile')
    parser.add_argument('--dem', required=True, help='DEM raster (GeoTIFF)')
    parser.add_argument('--output', required=True, help='Output network topology NetCDF')
    parser.add_argument('--stream_threshold', type=int, default=500,
                       help='Flow accumulation threshold for stream extraction (cells, default: 500)')
    parser.add_argument('--min_slope', type=float, default=0.0001,
                       help='Minimum reach slope m/m (default: 0.0001)')

    args = parser.parse_args()

    if not validate_inputs(args):
        sys.exit(1)

    try:
        result = process(args)

        errors = validate_outputs(result)
        if errors:
            for e in errors:
                print(f"OUTPUT VALIDATION ERROR: {e}", file=sys.stderr)
            sys.exit(3)

        print(json.dumps(result, indent=2))
        print("\nSUCCESS: Network topology built for mizuRoute")

    except Exception as e:
        print(f"PROCESSING ERROR: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(2)


if __name__ == '__main__':
    main()
