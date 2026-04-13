"""
Assign hydraulic conductivity from GLHYMPS 2.0 global hydrogeology dataset.

Reads GLHYMPS shapefile (log-permeability in m², porosity) and assigns
K (m/day) and Sy per MODFLOW grid cell via spatial intersection.

For shallow Layer 1: uses HWSD Ksat (from VIC soil params) if available.
For deeper layers: uses GLHYMPS permeability converted to K.

Conversion: K(m/s) = k(m²) × ρg/μ = 10^(logK) × 9.81e6 / 1.002e-3
            K(m/day) = K(m/s) × 86400

Usage:
    python assign_k_from_glhymps.py \
        --grid_nc outputs/<basin>/vic_temp/grid/basin_grid.nc \
        --glhymps_shp data/groundwater/glhymps/GLHYMPS.shp \
        --nlayers 3 \
        --soil_param outputs/<basin>/vic_temp/soil/SOIL_PARAM_COMPLETE.txt \
        --output_dir outputs/<basin>/modflow/layers \
        --basin_name bengbu
"""

import argparse
import json
import logging
import sys
from pathlib import Path

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("assign_k")

# Physical constants for permeability → K conversion
# ρ=1000 kg/m³, g=9.81 m/s², μ=1.002e-3 Pa·s → ρg/μ ≈ 9.79e6 (1/(m·s))
RHO_G_MU = 1000.0 * 9.81 / 1.002e-3  # ≈ 9.79e6

# Typical Sy by porosity (Sy ≈ 0.6 × porosity for unconfined)
SY_FROM_POROSITY_FACTOR = 0.6

# Default values for cells with no GLHYMPS coverage
DEFAULT_LOGK_M2 = -13.0    # ~0.001 m/day (typical clay/silt)
DEFAULT_POROSITY = 0.10
DEFAULT_SS = 1e-5           # 1/m, typical for most aquifers


def logk_to_k_mday(logk_m2: float) -> float:
    """Convert log10(permeability in m²) to hydraulic conductivity in m/day."""
    k_m2 = 10.0 ** logk_m2
    k_ms = k_m2 * RHO_G_MU
    return k_ms * 86400.0


def main():
    parser = argparse.ArgumentParser(description="Assign K from GLHYMPS 2.0")
    parser.add_argument("--grid_nc", type=Path, required=True)
    parser.add_argument("--glhymps_shp", type=str,
                        default="data/groundwater/glhymps/GLHYMPS.shp")
    parser.add_argument("--nlayers", type=int, default=3)
    parser.add_argument("--soil_param", type=str, default=None,
                        help="VIC SOIL_PARAM_COMPLETE.txt for shallow layer Ksat")
    parser.add_argument("--output_dir", type=Path, required=True)
    parser.add_argument("--basin_name", type=str, default="basin")
    args = parser.parse_args()

    import xarray as xr
    import geopandas as gpd
    from shapely.geometry import Point

    # Read grid
    ds = xr.open_dataset(args.grid_nc)
    lat_key = 'y' if 'y' in ds else 'lat'
    lon_key = 'x' if 'x' in ds else 'lon'
    lats = ds[lat_key].values
    lons = ds[lon_key].values
    ds.close()
    nrow, ncol = len(lats), len(lons)

    logger.info("Grid: %d × %d, %d layers", nrow, ncol, args.nlayers)

    # ── Layer 1 K from VIC soil params (HWSD-derived Ksat) ──
    k_layer1 = np.full((nrow, ncol), 1.0)  # default 1 m/day
    if args.soil_param and Path(args.soil_param).exists():
        logger.info("Reading VIC soil params for Layer 1 Ksat...")
        with open(args.soil_param) as f:
            for line in f:
                parts = line.strip().split()
                if len(parts) >= 10 and int(parts[0]) == 1:
                    lat, lon = float(parts[2]), float(parts[3])
                    # VIC Ksat is in mm/day, column index ~8 (varies)
                    # Find nearest grid cell
                    i = np.argmin(np.abs(lats - lat))
                    j = np.argmin(np.abs(lons - lon))
                    # VIC Ksat typically at columns 8-10 (per-layer)
                    # Use first layer Ksat
                    try:
                        ksat_mm = float(parts[8])  # Ksat layer 1 in mm/day
                        k_layer1[i, j] = ksat_mm / 1000.0  # convert to m/day
                    except (IndexError, ValueError):
                        pass

        valid = k_layer1[k_layer1 > 0.001]
        if len(valid) > 0:
            logger.info("  Layer 1 K from HWSD: %.3f - %.1f m/day (median %.2f)",
                         valid.min(), valid.max(), np.median(valid))

    # ── Deeper layers K from GLHYMPS ──
    logger.info("Reading GLHYMPS: %s", args.glhymps_shp)
    logger.info("  (This may take 1-2 minutes for the 3.9 GB shapefile...)")

    # GLHYMPS uses Cylindrical Equal Area (meters), not WGS84.
    # Reproject basin bbox to GLHYMPS CRS for spatial filtering.
    lat_min, lat_max = float(lats.min()) - 0.5, float(lats.max()) + 0.5
    lon_min, lon_max = float(lons.min()) - 0.5, float(lons.max()) + 0.5

    try:
        # Read a tiny sample to get the CRS
        sample = gpd.read_file(args.glhymps_shp, rows=1)
        glhymps_crs = sample.crs

        # Reproject bbox corners to GLHYMPS CRS
        from shapely.geometry import box
        bbox_wgs84 = gpd.GeoDataFrame(geometry=[box(lon_min, lat_min, lon_max, lat_max)], crs="EPSG:4326")
        bbox_proj = bbox_wgs84.to_crs(glhymps_crs)
        b = bbox_proj.total_bounds  # [minx, miny, maxx, maxy] in projected coords
        bbox = tuple(b)

        gdf = gpd.read_file(args.glhymps_shp, bbox=bbox)
        # Reproject to WGS84 for spatial join with grid points
        if gdf.crs != "EPSG:4326":
            gdf = gdf.to_crs("EPSG:4326")
        logger.info("  Loaded %d GLHYMPS polygons in bbox", len(gdf))
    except Exception as e:
        logger.error("Failed to read GLHYMPS: %s", e)
        logger.info("Using default K for all deeper layers")
        gdf = None

    # Find GLHYMPS column names
    # GLHYMPS logK values are stored ×100 (e.g., -1180 = logK of -11.80 m²)
    logk_col = None
    poro_col = None
    logk_scale = 100.0  # divide by this to get actual logK
    if gdf is not None and len(gdf) > 0:
        for c in gdf.columns:
            cl = c.lower()
            if 'logk' in cl and 'ferr' in cl:  # logK_Ferr_ = without permafrost
                logk_col = c
            elif 'logk' in cl and logk_col is None:
                logk_col = c
            elif 'poro' in cl:
                poro_col = c
        if logk_col:
            # Check if values are scaled (×100)
            sample_vals = gdf[logk_col].dropna().head(10).values
            if len(sample_vals) > 0 and np.abs(sample_vals).mean() > 50:
                logk_scale = 100.0  # values like -1180 → -11.80
            else:
                logk_scale = 1.0
            logger.info("  Using columns: logK=%s (÷%.0f), porosity=%s",
                        logk_col, logk_scale, poro_col)

    # Assign K to each grid cell
    k_deep = np.full((nrow, ncol), logk_to_k_mday(DEFAULT_LOGK_M2))
    porosity = np.full((nrow, ncol), DEFAULT_POROSITY)

    if gdf is not None and logk_col and len(gdf) > 0:
        # Spatial join: find which polygon each cell center falls in
        points = []
        indices = []
        for i, lat in enumerate(lats):
            for j, lon in enumerate(lons):
                points.append(Point(lon, lat))
                indices.append((i, j))

        points_gdf = gpd.GeoDataFrame(
            {"idx": range(len(points))},
            geometry=points,
            crs="EPSG:4326",
        )

        joined = gpd.sjoin(points_gdf, gdf, how="left", predicate="within")

        matched = 0
        for _, row in joined.iterrows():
            idx = int(row["idx"])
            i, j = indices[idx]
            if logk_col in row and not np.isnan(row[logk_col]):
                logk_val = row[logk_col] / logk_scale  # scale from ×100 to actual
                k_deep[i, j] = logk_to_k_mday(logk_val)
                matched += 1
            if poro_col and poro_col in row and not np.isnan(row[poro_col]):
                poro_val = row[poro_col]
                if poro_val > 1.0:
                    poro_val /= 100.0  # might be in percent
                porosity[i, j] = poro_val

        logger.info("  Matched %d / %d cells with GLHYMPS data", matched, len(indices))

    # ── Build K and Sy arrays ──
    k_array = np.zeros((args.nlayers, nrow, ncol))
    k_array[0] = k_layer1  # Layer 1: HWSD
    for k in range(1, args.nlayers):
        k_array[k] = k_deep  # Deeper layers: GLHYMPS

    # K33 (vertical K) = K / 10 (typical anisotropy)
    k33_array = k_array / 10.0

    # Storage — broadcast to 3D (nlay × nrow × ncol) for FloPy
    sy_2d = np.clip(porosity * SY_FROM_POROSITY_FACTOR, 0.01, 0.35)
    sy_array = np.broadcast_to(sy_2d, (args.nlayers, nrow, ncol)).copy()
    ss_array = np.full((args.nlayers, nrow, ncol), DEFAULT_SS)

    # ICELLTYPE: top layer(s) convertible, deepest confined
    icelltype = np.ones(args.nlayers, dtype=int)  # all convertible
    if args.nlayers >= 3:
        icelltype[-1] = 0  # deepest layer confined

    # Save
    args.output_dir.mkdir(parents=True, exist_ok=True)
    np.save(args.output_dir / "k.npy", k_array)
    np.save(args.output_dir / "k33.npy", k33_array)
    np.save(args.output_dir / "sy.npy", sy_array)
    np.save(args.output_dir / "ss.npy", ss_array)
    np.save(args.output_dir / "icelltype.npy", icelltype)
    np.save(args.output_dir / "porosity.npy", porosity)

    summary = {
        "basin": args.basin_name,
        "nlayers": args.nlayers,
        "k_layer1_source": "HWSD_via_VIC" if args.soil_param else "default_1.0_mday",
        "k_deep_source": "GLHYMPS_2.0" if (gdf is not None and logk_col) else "default",
        "k_range_mday": {
            f"layer_{k+1}": [float(k_array[k].min()), float(k_array[k].max())]
            for k in range(args.nlayers)
        },
        "sy_range": [float(sy_array.min()), float(sy_array.max())],
        "icelltype": icelltype.tolist(),
    }
    with open(args.output_dir / "k_summary.json", "w") as f:
        json.dump(summary, f, indent=2)

    logger.info("K assignment complete. Saved to %s", args.output_dir)
    for k in range(args.nlayers):
        logger.info("  Layer %d K: %.4f - %.2f m/day (median %.3f)",
                     k+1, k_array[k].min(), k_array[k].max(), np.median(k_array[k]))

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
