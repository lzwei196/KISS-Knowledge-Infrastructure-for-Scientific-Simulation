#!/usr/bin/env python3
"""
build_reservoir_grid.py — Generate CE-QUAL-W2 segment-layer bathymetry grid from DEM.

Traces the reservoir thalweg (deepest path) from upstream to dam, places cross-sections
at regular intervals, and extracts width-at-elevation for each segment-layer cell.
Outputs a JSON grid definition + bth_wb*.npt bathymetry file.

CRITICAL:
  - Boundary segments (first and last) MUST have zero width at all layers
  - Bottom elevations must be monotonically non-increasing downstream (dt_013)
  - Every active segment must have at least one non-zero width layer (dt_010)
  - Width matrix is [KMX layers] x [IMX segments]

Usage:
    python build_reservoir_grid.py \
        --dem /path/to/dem.tif \
        --reservoir_shp /path/to/reservoir_extent.shp \
        --dam_lat 32.54 --dam_lon 111.51 \
        --upstream_lat 33.10 --upstream_lon 111.80 \
        --segment_length 1000 --layer_thickness 1.0 \
        --output_dir /path/to/output

    # Idealized mode (no DEM):
    python build_reservoir_grid.py \
        --idealized \
        --reservoir_length_km 80 --max_depth 80 --surface_area_km2 745 \
        --dam_elevation 170 --segment_length 1000 --layer_thickness 1.0 \
        --output_dir /path/to/output
"""

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np

# Optional imports for DEM mode
try:
    import rasterio
    from rasterio.mask import mask as rio_mask
    HAS_RASTERIO = True
except ImportError:
    HAS_RASTERIO = False

try:
    import geopandas as gpd
    from shapely.geometry import LineString, Point
    HAS_GEO = True
except ImportError:
    HAS_GEO = False


def validate_inputs(args):
    """Validate input arguments."""
    errors = []

    if not args.idealized:
        if not HAS_RASTERIO:
            errors.append("rasterio required for DEM mode. Install or use --idealized.")
        if not HAS_GEO:
            errors.append("geopandas/shapely required for DEM mode. Install or use --idealized.")
        if args.dem and not os.path.isfile(args.dem):
            errors.append(f"DEM file not found: {args.dem}")
        if args.reservoir_shp and not os.path.isfile(args.reservoir_shp):
            errors.append(f"Reservoir shapefile not found: {args.reservoir_shp}")
        if args.dam_lat is None or args.dam_lon is None:
            errors.append("--dam_lat and --dam_lon required for DEM mode")
    else:
        if args.reservoir_length_km is None or args.reservoir_length_km <= 0:
            errors.append("--reservoir_length_km must be positive for idealized mode")
        if args.max_depth is None or args.max_depth <= 0:
            errors.append("--max_depth must be positive for idealized mode")
        if args.surface_area_km2 is None or args.surface_area_km2 <= 0:
            errors.append("--surface_area_km2 must be positive for idealized mode")

    if args.segment_length <= 0:
        errors.append("--segment_length must be positive (meters)")
    if args.layer_thickness <= 0:
        errors.append("--layer_thickness must be positive (meters)")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}))
        sys.exit(1)


def build_idealized_grid(args):
    """
    Build idealized bathymetry from basic reservoir parameters.

    Assumes:
    - Trapezoidal cross-section (width varies linearly with depth)
    - Width decreases linearly from surface to bottom
    - Width increases linearly from upstream to dam (downstream = widest)
    - Bottom elevation decreases linearly from upstream to dam

    This is a reasonable first approximation for elongated reservoirs.
    """
    length_m = args.reservoir_length_km * 1000
    max_depth = args.max_depth
    area_km2 = args.surface_area_km2
    dam_elev = args.dam_elevation if args.dam_elevation else max_depth
    seg_len = args.segment_length
    layer_thick = args.layer_thickness

    # Number of active segments (excluding 2 boundary segments)
    n_active = max(2, int(round(length_m / seg_len)))
    seg_len_actual = length_m / n_active
    n_segments = n_active + 2  # IMX = active + 2 boundary

    # Number of layers
    n_layers = max(2, int(round(max_depth / layer_thick)))
    layer_thick_actual = max_depth / n_layers

    # Estimate average surface width from area and length
    avg_width = (area_km2 * 1e6) / length_m  # m

    # Build segment coordinates (distance from upstream, km)
    seg_distances = np.zeros(n_segments)
    seg_distances[0] = 0  # boundary
    for i in range(1, n_segments - 1):
        seg_distances[i] = (i - 0.5) * seg_len_actual / 1000  # center of segment, km
    seg_distances[-1] = length_m / 1000  # boundary

    # Build bottom elevations (monotonically non-increasing downstream)
    # Dam is downstream (last active segment)
    # Upstream bottom is higher (shallower at upstream end)
    upstream_depth = max_depth * 0.3  # upstream is 30% of max depth
    bottom_elevations = np.zeros(n_segments)
    for i in range(1, n_segments - 1):
        frac = (i - 1) / max(1, n_active - 1)  # 0 at upstream, 1 at dam
        depth_at_seg = upstream_depth + frac * (max_depth - upstream_depth)
        bottom_elevations[i] = dam_elev - depth_at_seg
    bottom_elevations[0] = bottom_elevations[1]  # boundary matches first active
    bottom_elevations[-1] = bottom_elevations[-2]  # boundary matches last active

    # Layer elevations (top of each layer, from surface down)
    surface_elev = dam_elev
    layer_elevations = np.array([
        surface_elev - k * layer_thick_actual for k in range(n_layers + 1)
    ])

    # Build width matrix [n_layers x n_segments]
    # Width = 0 at bottom, increases to surface
    # Width also varies along reservoir (wider downstream)
    width_matrix = np.zeros((n_layers, n_segments))

    for j in range(1, n_segments - 1):  # active segments only
        frac_downstream = (j - 1) / max(1, n_active - 1)
        # Width factor: wider downstream (0.5 to 1.5 * avg)
        width_factor = 0.5 + frac_downstream
        seg_surface_width = avg_width * width_factor

        seg_bottom_elev = bottom_elevations[j]

        for k in range(n_layers):
            layer_top = layer_elevations[k]
            layer_mid = layer_top - layer_thick_actual / 2

            if layer_mid < seg_bottom_elev:
                width_matrix[k, j] = 0.0
            else:
                # Linear width decrease from surface to bottom
                depth_frac = (layer_mid - seg_bottom_elev) / max(0.01, surface_elev - seg_bottom_elev)
                width_matrix[k, j] = max(0.0, seg_surface_width * depth_frac)

    # Boundary segments have zero width
    width_matrix[:, 0] = 0.0
    width_matrix[:, -1] = 0.0

    # Build grid definition
    grid = {
        "n_waterbodies": 1,
        "n_branches": 1,
        "n_segments": n_segments,  # IMX (including boundaries)
        "n_active_segments": n_active,
        "n_layers": n_layers,  # KMX
        "segment_length_m": round(seg_len_actual, 1),
        "layer_thickness_m": round(layer_thick_actual, 2),
        "surface_elevation_m": round(surface_elev, 2),
        "max_depth_m": round(max_depth, 2),
        "reservoir_length_km": args.reservoir_length_km,
        "surface_area_km2": area_km2,
        "segment_distances_km": [round(d, 3) for d in seg_distances],
        "bottom_elevations_m": [round(e, 2) for e in bottom_elevations],
        "layer_elevations_m": [round(e, 2) for e in layer_elevations],
        "width_matrix": width_matrix.tolist(),
        "branch_info": [{
            "branch_id": 1,
            "waterbody_id": 1,
            "upstream_segment": 2,  # first active segment
            "downstream_segment": n_segments - 1,  # last active segment
            "upstream_head_segment": 0,  # external boundary
            "downstream_head_segment": 0,  # external boundary (dam)
            "slope": round(max_depth * 0.7 / length_m, 6),
        }],
        "mode": "idealized",
    }

    return grid


def build_dem_grid(args):
    """
    Build bathymetry grid from DEM data.

    This is a simplified approach that:
    1. Clips DEM to reservoir extent
    2. Creates evenly spaced cross-sections along the thalweg line
    3. Extracts width-at-elevation from each cross-section
    """
    import rasterio
    from rasterio.mask import mask as rio_mask
    import geopandas as gpd
    from shapely.geometry import LineString, Point, box

    # Load reservoir extent
    reservoir_gdf = gpd.read_file(args.reservoir_shp)
    if reservoir_gdf.crs and reservoir_gdf.crs.to_epsg() != 4326:
        reservoir_gdf = reservoir_gdf.to_crs(epsg=4326)

    reservoir_geom = reservoir_gdf.geometry.unary_union

    # Load and clip DEM
    with rasterio.open(args.dem) as src:
        out_image, out_transform = rio_mask(src, [reservoir_geom], crop=True, nodata=-9999)
        dem_data = out_image[0]
        dem_meta = src.meta.copy()

    # Get pixel coordinates
    rows, cols = np.where(dem_data > -9999)
    if len(rows) == 0:
        print(json.dumps({"status": "error", "errors": ["No DEM data within reservoir extent"]}))
        sys.exit(2)

    # Simple thalweg: straight line from upstream to dam
    dam_point = Point(args.dam_lon, args.dam_lat)
    up_point = Point(args.upstream_lon, args.upstream_lat)
    thalweg_line = LineString([up_point, dam_point])

    # Estimate length in meters (approximate using haversine)
    lat_mid = (args.dam_lat + args.upstream_lat) / 2
    dx = (args.dam_lon - args.upstream_lon) * 111320 * np.cos(np.radians(lat_mid))
    dy = (args.dam_lat - args.upstream_lat) * 110540
    length_m = np.sqrt(dx**2 + dy**2)

    # Number of segments
    n_active = max(2, int(round(length_m / args.segment_length)))
    seg_len_actual = length_m / n_active
    n_segments = n_active + 2

    # Find elevation range
    valid_elevs = dem_data[dem_data > -9999]
    min_elev = float(np.min(valid_elevs))
    max_elev_dam = float(np.percentile(valid_elevs, 95))  # approximate surface elevation

    max_depth = max_elev_dam - min_elev
    n_layers = max(2, int(round(max_depth / args.layer_thickness)))
    layer_thick = max_depth / n_layers

    surface_elev = max_elev_dam
    layer_elevations = np.array([surface_elev - k * layer_thick for k in range(n_layers + 1)])

    # Build width matrix using simplified cross-section extraction
    width_matrix = np.zeros((n_layers, n_segments))
    bottom_elevations = np.zeros(n_segments)
    seg_distances = np.zeros(n_segments)

    pixel_size_m = abs(out_transform[0]) * 111320 * np.cos(np.radians(lat_mid))

    for s in range(1, n_segments - 1):
        frac = (s - 0.5) / n_active
        seg_distances[s] = frac * length_m / 1000

        # Point along thalweg at this fraction
        pt = thalweg_line.interpolate(frac, normalized=True)

        # Extract cross-section: find DEM values within segment_length/2 perpendicular
        # Simplified: use all pixels within a buffer around the cross-section point
        pt_col = int((pt.x - out_transform[2]) / out_transform[0])
        pt_row = int((pt.y - out_transform[5]) / out_transform[4])

        buffer_pixels = max(1, int(args.segment_length / (2 * pixel_size_m)))

        r_min = max(0, pt_row - buffer_pixels)
        r_max = min(dem_data.shape[0], pt_row + buffer_pixels + 1)
        c_min = max(0, pt_col - buffer_pixels)
        c_max = min(dem_data.shape[1], pt_col + buffer_pixels + 1)

        cross_elevs = dem_data[r_min:r_max, c_min:c_max]
        cross_elevs = cross_elevs[cross_elevs > -9999]

        if len(cross_elevs) == 0:
            bottom_elevations[s] = min_elev
            continue

        seg_bottom = float(np.min(cross_elevs))
        bottom_elevations[s] = seg_bottom

        # For each layer, count pixels below the layer elevation = width proxy
        for k in range(n_layers):
            layer_mid = layer_elevations[k] - layer_thick / 2
            if layer_mid < seg_bottom:
                width_matrix[k, s] = 0.0
            else:
                # Pixels below this elevation = part of the water column
                n_wet = np.sum(cross_elevs <= layer_mid)
                width_matrix[k, s] = max(0.0, n_wet * pixel_size_m)

    # Ensure bottom elevations are monotonically non-increasing downstream
    for s in range(2, n_segments - 1):
        if bottom_elevations[s] > bottom_elevations[s - 1]:
            bottom_elevations[s] = bottom_elevations[s - 1]

    bottom_elevations[0] = bottom_elevations[1]
    bottom_elevations[-1] = bottom_elevations[-2]
    seg_distances[0] = 0
    seg_distances[-1] = length_m / 1000

    grid = {
        "n_waterbodies": 1,
        "n_branches": 1,
        "n_segments": n_segments,
        "n_active_segments": n_active,
        "n_layers": n_layers,
        "segment_length_m": round(seg_len_actual, 1),
        "layer_thickness_m": round(layer_thick, 2),
        "surface_elevation_m": round(surface_elev, 2),
        "max_depth_m": round(max_depth, 2),
        "reservoir_length_km": round(length_m / 1000, 2),
        "surface_area_km2": round(len(valid_elevs) * (pixel_size_m ** 2) / 1e6, 2),
        "segment_distances_km": [round(d, 3) for d in seg_distances],
        "bottom_elevations_m": [round(e, 2) for e in bottom_elevations],
        "layer_elevations_m": [round(e, 2) for e in layer_elevations],
        "width_matrix": width_matrix.tolist(),
        "branch_info": [{
            "branch_id": 1,
            "waterbody_id": 1,
            "upstream_segment": 2,
            "downstream_segment": n_segments - 1,
            "upstream_head_segment": 0,
            "downstream_head_segment": 0,
            "slope": round((bottom_elevations[1] - bottom_elevations[-2]) / length_m, 6),
        }],
        "mode": "dem",
        "dem_path": args.dem,
        "reservoir_shp": args.reservoir_shp,
    }

    return grid


def write_bathymetry_file(grid, output_dir, wb_id=1):
    """
    Write CE-QUAL-W2 bathymetry file (bth_wb*.npt).

    Format: Fixed-width, rows = layers (elevation descending), columns = segment widths.
    Each value is 8 characters wide, right-justified.

    CRITICAL: Fortran reads by column position. Each field is exactly 8 chars.
    """
    width_matrix = np.array(grid["width_matrix"])
    n_layers = width_matrix.shape[0]
    n_segments = width_matrix.shape[1]
    layer_elevations = grid["layer_elevations_m"]

    bth_path = os.path.join(output_dir, f"bth_wb{wb_id}.npt")

    with open(bth_path, "w") as f:
        # Header line with segment numbers
        header = "$ Seg:"
        for s in range(n_segments):
            header += f"{s + 1:>8d}"
        f.write(header + "\n")

        # Data rows: one per layer elevation
        for k in range(n_layers):
            elev = layer_elevations[k]
            line = f"{elev:8.2f}"
            for s in range(n_segments):
                line += f"{width_matrix[k, s]:8.1f}"
            f.write(line + "\n")

    return bth_path


def validate_outputs(grid, output_dir):
    """Validate the generated grid."""
    errors = []
    warnings = []

    width_matrix = np.array(grid["width_matrix"])
    n_layers, n_segments = width_matrix.shape

    # Check boundary segments are zero
    if np.any(width_matrix[:, 0] != 0):
        errors.append("Boundary segment 1 has non-zero widths")
    if np.any(width_matrix[:, -1] != 0):
        errors.append(f"Boundary segment {n_segments} has non-zero widths")

    # Check active segments have at least one non-zero width
    for s in range(1, n_segments - 1):
        if np.all(width_matrix[:, s] == 0):
            errors.append(f"Active segment {s + 1} has zero width at all layers (dt_010)")

    # Check bottom elevations are non-increasing downstream
    bottom_elevs = grid["bottom_elevations_m"]
    for s in range(2, n_segments - 1):
        if bottom_elevs[s] > bottom_elevs[s - 1] + 0.01:
            warnings.append(f"Bottom elevation increases at segment {s + 1}: "
                          f"{bottom_elevs[s]} > {bottom_elevs[s-1]} (dt_013)")

    # Check bathymetry file exists
    bth_path = os.path.join(output_dir, "bth_wb1.npt")
    if not os.path.isfile(bth_path):
        errors.append(f"Bathymetry file not created: {bth_path}")

    return errors, warnings


def process(args):
    """Main processing."""
    os.makedirs(args.output_dir, exist_ok=True)

    if args.idealized:
        grid = build_idealized_grid(args)
    else:
        grid = build_dem_grid(args)

    # Write bathymetry file
    bth_path = write_bathymetry_file(grid, args.output_dir)

    # Write grid JSON
    grid_json_path = os.path.join(args.output_dir, "reservoir_grid.json")
    with open(grid_json_path, "w") as f:
        json.dump(grid, f, indent=2)

    # Validate
    errors, warnings = validate_outputs(grid, args.output_dir)

    result = {
        "status": "error" if errors else "success",
        "grid_json": grid_json_path,
        "bathymetry_file": bth_path,
        "n_segments": grid["n_segments"],
        "n_layers": grid["n_layers"],
        "n_active_segments": grid["n_active_segments"],
        "segment_length_m": grid["segment_length_m"],
        "layer_thickness_m": grid["layer_thickness_m"],
        "surface_elevation_m": grid["surface_elevation_m"],
        "max_depth_m": grid["max_depth_m"],
        "mode": grid["mode"],
    }

    if errors:
        result["errors"] = errors
    if warnings:
        result["warnings"] = warnings

    print(json.dumps(result, indent=2))
    return 0 if not errors else 3


def main():
    parser = argparse.ArgumentParser(description="Build CE-QUAL-W2 reservoir grid")

    # DEM mode
    parser.add_argument("--dem", help="DEM raster file path")
    parser.add_argument("--reservoir_shp", help="Reservoir extent shapefile")
    parser.add_argument("--dam_lat", type=float, help="Dam latitude")
    parser.add_argument("--dam_lon", type=float, help="Dam longitude")
    parser.add_argument("--upstream_lat", type=float, help="Upstream point latitude")
    parser.add_argument("--upstream_lon", type=float, help="Upstream point longitude")

    # Idealized mode
    parser.add_argument("--idealized", action="store_true",
                       help="Use idealized geometry (no DEM needed)")
    parser.add_argument("--reservoir_length_km", type=float,
                       help="Reservoir length in km (idealized mode)")
    parser.add_argument("--max_depth", type=float,
                       help="Maximum depth in meters")
    parser.add_argument("--surface_area_km2", type=float,
                       help="Surface area in km^2")
    parser.add_argument("--dam_elevation", type=float, default=100.0,
                       help="Dam crest elevation in m ASL (default: 100)")

    # Grid parameters
    parser.add_argument("--segment_length", type=float, default=1000,
                       help="Target segment length in meters (default: 1000)")
    parser.add_argument("--layer_thickness", type=float, default=1.0,
                       help="Layer thickness in meters (default: 1.0)")

    # Output
    parser.add_argument("--output_dir", required=True,
                       help="Output directory for grid files")

    args = parser.parse_args()
    validate_inputs(args)
    sys.exit(process(args))


if __name__ == "__main__":
    main()
