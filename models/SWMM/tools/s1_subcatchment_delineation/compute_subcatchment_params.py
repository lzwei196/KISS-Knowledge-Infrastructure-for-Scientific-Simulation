#!/usr/bin/env python3
"""
Compute hydraulic and infiltration parameters for SWMM subcatchments.

Derives key SWMM subcatchment parameters from DEM and soil data:
  - Width: area / longest flow path (overland flow width)
  - Slope: mean slope within subcatchment (from DEM)
  - Infiltration parameters (one of three methods):
    * Green-Ampt: suction, conductivity, initial deficit (from HWSD soil)
    * Horton: max/min rate, decay constant, drying time
    * Curve Number: CN from land use + hydrologic soil group

Inputs:
  - Subcatchment shapefile (with area attribute)
  - DEM raster (GeoTIFF)
  - Infiltration method (GreenAmpt, Horton, or CurveNumber)
  - Optional soil data file (HWSD or custom CSV)

Outputs:
  - CSV with width, slope, and infiltration parameters per subcatchment
"""

import argparse
import csv
import os
import sys
from pathlib import Path

import numpy as np

# Default Green-Ampt parameters by USDA soil texture class
GREENAMPT_DEFAULTS = {
    "sand":         {"suction_mm": 49.5,  "ksat_mm_hr": 117.8, "imd": 0.417},
    "loamy_sand":   {"suction_mm": 61.3,  "ksat_mm_hr": 29.9,  "imd": 0.401},
    "sandy_loam":   {"suction_mm": 110.1, "ksat_mm_hr": 10.9,  "imd": 0.412},
    "loam":         {"suction_mm": 88.9,  "ksat_mm_hr": 3.4,   "imd": 0.434},
    "silt_loam":    {"suction_mm": 166.8, "ksat_mm_hr": 6.5,   "imd": 0.486},
    "sandy_clay_loam": {"suction_mm": 218.5, "ksat_mm_hr": 1.5, "imd": 0.330},
    "clay_loam":    {"suction_mm": 208.8, "ksat_mm_hr": 1.0,   "imd": 0.309},
    "silty_clay_loam": {"suction_mm": 273.0, "ksat_mm_hr": 1.0, "imd": 0.432},
    "sandy_clay":   {"suction_mm": 239.0, "ksat_mm_hr": 0.6,   "imd": 0.321},
    "silty_clay":   {"suction_mm": 292.2, "ksat_mm_hr": 0.5,   "imd": 0.423},
    "clay":         {"suction_mm": 316.3, "ksat_mm_hr": 0.3,   "imd": 0.385},
}

# Default Horton parameters by soil group
HORTON_DEFAULTS = {
    "A": {"f0_mm_hr": 250.0, "fmin_mm_hr": 25.0, "decay_1_hr": 4.0, "dry_time_hr": 7.0},
    "B": {"f0_mm_hr": 200.0, "fmin_mm_hr": 13.0, "decay_1_hr": 4.0, "dry_time_hr": 7.0},
    "C": {"f0_mm_hr": 125.0, "fmin_mm_hr": 6.0,  "decay_1_hr": 3.0, "dry_time_hr": 7.0},
    "D": {"f0_mm_hr": 75.0,  "fmin_mm_hr": 3.0,  "decay_1_hr": 3.0, "dry_time_hr": 7.0},
}


def compute_slope_from_dem(dem_path, geometry):
    """Compute mean slope (%) within a polygon from DEM."""
    try:
        import rasterio
        from rasterio.mask import mask as rio_mask
    except ImportError:
        return 2.0  # default 2% slope

    try:
        with rasterio.open(dem_path) as src:
            clipped, transform = rio_mask(src, [geometry], crop=True, nodata=-9999)
            elev = clipped[0].astype(float)
            elev[elev == -9999] = np.nan

            if np.all(np.isnan(elev)):
                return 2.0

            # Compute slope using numpy gradient
            res_x = abs(transform.a)
            res_y = abs(transform.e)
            # Convert degrees to meters if geographic CRS
            if res_x < 1:  # likely degrees
                lat_center = transform.f + elev.shape[0] * transform.e / 2
                res_x_m = res_x * 111320 * np.cos(np.radians(lat_center))
                res_y_m = res_y * 110540
            else:
                res_x_m = res_x
                res_y_m = res_y

            dy, dx = np.gradient(elev, res_y_m, res_x_m)
            slope = np.sqrt(dx**2 + dy**2) * 100  # percent
            mean_slope = float(np.nanmean(slope))
            return max(mean_slope, 0.01)  # SWMM needs slope > 0
    except Exception as e:
        print(f"WARNING: Slope computation failed: {e}", file=sys.stderr)
        return 2.0


def compute_width(area_m2, slope_pct):
    """
    Compute overland flow width.
    W = A / L where L = longest flow path.
    Approximate L = 1.4 * sqrt(A) for typical subcatchments.
    """
    if area_m2 <= 0:
        return 100.0
    flow_path = 1.4 * np.sqrt(area_m2)
    width = area_m2 / flow_path
    return max(width, 1.0)


def get_infiltration_params(method, soil_class="loam"):
    """Get default infiltration parameters for the given method and soil."""
    if method == "GreenAmpt":
        params = GREENAMPT_DEFAULTS.get(soil_class, GREENAMPT_DEFAULTS["loam"])
        return {
            "suction_mm": params["suction_mm"],
            "ksat_mm_hr": params["ksat_mm_hr"],
            "imd": params["imd"],
        }
    elif method == "Horton":
        # Map soil texture to hydrologic group
        group_map = {
            "sand": "A", "loamy_sand": "A", "sandy_loam": "B",
            "loam": "B", "silt_loam": "B", "sandy_clay_loam": "C",
            "clay_loam": "C", "silty_clay_loam": "C",
            "sandy_clay": "D", "silty_clay": "D", "clay": "D",
        }
        group = group_map.get(soil_class, "B")
        params = HORTON_DEFAULTS[group]
        return {
            "f0_mm_hr": params["f0_mm_hr"],
            "fmin_mm_hr": params["fmin_mm_hr"],
            "decay_1_hr": params["decay_1_hr"],
            "dry_time_hr": params["dry_time_hr"],
        }
    elif method == "CurveNumber":
        # Default CN by soil group
        cn_defaults = {"A": 60, "B": 70, "C": 80, "D": 85}
        group_map = {
            "sand": "A", "loamy_sand": "A", "sandy_loam": "B",
            "loam": "B", "silt_loam": "B", "sandy_clay_loam": "C",
            "clay_loam": "C", "silty_clay_loam": "C",
            "sandy_clay": "D", "silty_clay": "D", "clay": "D",
        }
        group = group_map.get(soil_class, "B")
        return {"curve_number": cn_defaults[group]}
    else:
        raise ValueError(f"Unknown infiltration method: {method}")


def main():
    parser = argparse.ArgumentParser(
        description="Compute SWMM subcatchment hydraulic and infiltration parameters"
    )
    parser.add_argument("--subcatchment_shp", required=True,
                        help="Subcatchment polygon shapefile")
    parser.add_argument("--dem", required=True, help="DEM raster (GeoTIFF)")
    parser.add_argument("--method", required=True,
                        choices=["GreenAmpt", "Horton", "CurveNumber"],
                        help="Infiltration method")
    parser.add_argument("--soil_data", default=None,
                        help="Soil data file (CSV with subcatchment_id, texture_class)")
    parser.add_argument("--output", required=True, help="Output CSV path")
    args = parser.parse_args()

    for fpath in [args.subcatchment_shp, args.dem]:
        if not os.path.isfile(fpath):
            print(f"ERROR: File not found: {fpath}", file=sys.stderr)
            sys.exit(1)

    # Load soil texture per subcatchment if provided
    soil_map = {}
    if args.soil_data:
        if not os.path.isfile(args.soil_data):
            print(f"ERROR: Soil data not found: {args.soil_data}", file=sys.stderr)
            sys.exit(1)
        with open(args.soil_data, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                soil_map[row["subcatchment_id"]] = row.get("texture_class", "loam")

    # Read subcatchments
    try:
        import geopandas as gpd
    except ImportError:
        print("ERROR: geopandas required. Install with: pip install geopandas",
              file=sys.stderr)
        sys.exit(1)

    gdf = gpd.read_file(args.subcatchment_shp)
    print(f"Processing {len(gdf)} subcatchments with {args.method} infiltration...")

    results = []
    for idx, row in gdf.iterrows():
        sc_id = row.get("id", f"S{idx}")
        geom = row.geometry

        # Area in m^2
        if gdf.crs and gdf.crs.is_geographic:
            # Approximate using centroid latitude
            lat = geom.centroid.y
            area_m2 = geom.area * (111320 * np.cos(np.radians(lat))) * 110540
        else:
            area_m2 = geom.area

        # Slope from DEM
        slope_pct = compute_slope_from_dem(args.dem, geom)

        # Width
        width_m = compute_width(area_m2, slope_pct)

        # Infiltration
        soil_class = soil_map.get(sc_id, "loam")
        infil_params = get_infiltration_params(args.method, soil_class)

        result = {
            "id": sc_id,
            "area_ha": round(area_m2 / 1e4, 4),
            "width_m": round(width_m, 2),
            "slope_pct": round(slope_pct, 4),
            "soil_class": soil_class,
        }
        result.update(infil_params)
        results.append(result)

    # Write output
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = list(results[0].keys()) if results else []
    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)

    print(f"Output written: {output_path} ({len(results)} subcatchments)")
    print(f"  Method: {args.method}")
    if results:
        slopes = [r["slope_pct"] for r in results]
        print(f"  Slope range: {min(slopes):.2f}% - {max(slopes):.2f}%")


if __name__ == "__main__":
    main()
