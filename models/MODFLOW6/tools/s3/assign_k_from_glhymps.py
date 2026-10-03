"""
Assign hydraulic conductivity from GLHYMPS 2.0 global hydrogeology dataset.

Reads GLHYMPS shapefile (log-permeability in m², porosity) and assigns
K (m/day) and Sy per MODFLOW grid cell via spatial intersection.

Layer 1 (shallow water-table layer, 0-10 m) — SKILL.md fact #10: NOT GLHYMPS.
For shallow Layer 1: one of the --layer1_k routes. Two routes:
  alluvial_default (default)  K1 = 1.0 m/day everywhere (the documented
                              alluvial value, SKILL.md fact #10 / Wangjiaba test).
  hwsd                        K1 straight from the HWSD soil source, per active
                              cell, through the shared lookup
                              ki_tools_common.soil_utils.lookup_hwsd:
                                HWSD topsoil sand/clay -> USDA texture class ->
                                Ksat (cm/hr) by the Saxton-Rawls / Rawls,
                                Brakensiek & Saxton (1982) texture table
                                (lookup_hwsd()['hydraulics']['ksat_cm_hr']);
                                K_soil (m/day) = ksat_cm_hr * 0.24;
                                K1 = K_soil * 100 (--hwsd_aquifer_scale, triplet
                                dt_v004: soil Ksat is ~100x below aquifer K),
                                clipped to 0.1-50 m/day (dt_v004).
                              An ACTIVE cell where HWSD has no soil (sea, water
                              body, no texture in the map unit, no map unit) is
                              NOT filled: the tool lists those cells and exits 4
                              before reading GLHYMPS. Mask them out of the grid
                              (create_grid_from_basin.py) or use the default.
  (The former --soil_param route, which read Layer-1 Ksat from the VIC soil
  parameter file, was REMOVED on 2026-10-03: a model KI takes its input from
  the data source, not from another model's set-up files. dt_mf6_010.)
Deeper layers: GLHYMPS permeability converted to K.

Conversion: K(m/s) = k(m²) × ρg/μ = 10^(logK) × 9.81e6 / 1.002e-3
            K(m/day) = K(m/s) × 86400

Usage:
    python tools/s2/create_grid_from_basin.py --box LON_MIN LON_MAX LAT_MIN LAT_MAX \
        --nrow N --ncol M --out_nc outputs/<case>/grid.nc
    python assign_k_from_glhymps.py \
        --grid_nc outputs/<case>/grid.nc \
        --glhymps_shp data/groundwater/glhymps/GLHYMPS.shp \
        --nlayers 2 \
        --layer1_k hwsd \
        --output_dir outputs/<case>/modflow/layers \
        --basin_name <case>

Exit codes: 0 success; 1 = bad options;
4 = --layer1_k hwsd and some active cell has no soil value.
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

# Layer 1 (see the module docstring)
ALLUVIAL_DEFAULT_K1 = 1.0   # m/day, SKILL.md fact #10
CMHR_TO_MDAY = 0.24         # 1 cm/hr = 0.01 m * 24 h
HWSD_AQUIFER_SCALE = 100.0  # dt_v004: aquifer K ~ 100 x soil Ksat
HWSD_K1_CLIP = (0.1, 50.0)  # dt_v004 clip, m/day
EXIT_HWSD_NO_SOIL = 4
EXIT_BAD_INPUT = 1


def hwsd_no_soil_reason(props: dict):
    """Why lookup_hwsd() has no real soil here, or None if it has one.

    lookup_hwsd() always returns a texture: where there is no soil it hands back
    its own generic 40/40/20 placeholder. The only sign of that is the missing
    'hwsd_component' record (no map unit, or a unit with no CSV row) or a
    component record that says the map unit carries no texture.
    """
    comp = props.get("hwsd_component")
    if not props.get("mu_id"):
        return "no HWSD map unit (raster nodata / sea)"
    if comp is None:
        return f"HWSD map unit {props['mu_id']} has no soil record"
    if comp.get("quality") == "no_texture_in_map_unit":
        return f"HWSD map unit {props['mu_id']} has no topsoil texture (water / rock / glacier)"
    return None


def layer1_k_from_hwsd(lats, lons, mask, scale, hwsd_raster=None, hwsd_csv=None):
    """Layer-1 K (m/day) per ACTIVE cell from HWSD via the shared lookup.

    Returns (k1, info). Inactive cells (mask == 0) are not looked up and keep
    the alluvial default (they become IDOMAIN 0). info['no_soil'] lists every
    active cell without HWSD soil; the caller refuses the build if it is not empty.
    """
    import warnings
    from collections import Counter
    from ki_tools_common.soil_utils import lookup_hwsd

    nrow, ncol = len(lats), len(lons)
    k1 = np.full((nrow, ncol), ALLUVIAL_DEFAULT_K1)
    ksoil = np.full((nrow, ncol), np.nan)
    no_soil, textures, quality = [], Counter(), Counter()
    n_clipped_lo = n_clipped_hi = 0
    for i in range(nrow):
        for j in range(ncol):
            if mask[i, j] <= 0:
                continue
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                props = lookup_hwsd(float(lats[i]), float(lons[j]),
                                    hwsd_raster=hwsd_raster, hwsd_csv=hwsd_csv)
            reason = hwsd_no_soil_reason(props)
            if reason:
                no_soil.append({"row": i, "col": j, "lat": float(lats[i]),
                                "lon": float(lons[j]), "mu_id": props.get("mu_id"),
                                "reason": reason})
                continue
            quality[props["hwsd_component"]["quality"]] += 1
            textures[props["hydraulics"]["texture"]] += 1
            ks = float(props["hydraulics"]["ksat_cm_hr"]) * CMHR_TO_MDAY
            ksoil[i, j] = ks
            kk = ks * scale
            if kk < HWSD_K1_CLIP[0]:
                n_clipped_lo += 1
            elif kk > HWSD_K1_CLIP[1]:
                n_clipped_hi += 1
            k1[i, j] = float(np.clip(kk, *HWSD_K1_CLIP))
    looked = int((mask > 0).sum())
    info = {
        "method": ("ki_tools_common.soil_utils.lookup_hwsd -> USDA texture -> "
                   "Saxton-Rawls/Rawls-Brakensiek-Saxton(1982) Ksat (cm/hr) * 0.24 = m/day; "
                   f"x {scale:g} (dt_v004 aquifer scale), clipped to "
                   f"{HWSD_K1_CLIP[0]}-{HWSD_K1_CLIP[1]} m/day"),
        "active_cells_looked_up": looked,
        "cells_with_soil": looked - len(no_soil),
        "no_soil": no_soil,
        "texture_counts": dict(textures),
        "hwsd_component_quality_counts": dict(quality),
        "k_soil_mday_range": ([float(np.nanmin(ksoil)), float(np.nanmax(ksoil))]
                              if np.isfinite(ksoil).any() else None),
        "cells_clipped_low": n_clipped_lo,
        "cells_clipped_high": n_clipped_hi,
        "inactive_cells_kept_default": int((mask <= 0).sum()),
    }
    return k1, info


def logk_to_k_mday(logk_m2: float) -> float:
    """Convert log10(permeability in m²) to hydraulic conductivity in m/day."""
    k_m2 = 10.0 ** logk_m2
    k_ms = k_m2 * RHO_G_MU
    return k_ms * 86400.0


def main():
    parser = argparse.ArgumentParser(description="Assign K from GLHYMPS 2.0")
    parser.add_argument("--grid_nc", type=Path, required=True)
    parser.add_argument("--glhymps_shp", type=str,
                        default=str(Path(__file__).resolve().parents[5] /
                                    "data/groundwater/glhymps/GLHYMPS.shp"),
                        help="GLHYMPS shapefile; default is relative to the server installation, independent of the working directory")
    parser.add_argument("--nlayers", type=int, default=3)
    parser.add_argument("--layer1_k", choices=["alluvial_default", "hwsd"],
                        default=None,
                        help="Layer-1 K route: the documented alluvial default "
                             f"({ALLUVIAL_DEFAULT_K1} m/day, the default) or straight "
                             "from HWSD through ki_tools_common.soil_utils.lookup_hwsd")
    parser.add_argument("--hwsd_aquifer_scale", type=float, default=HWSD_AQUIFER_SCALE,
                        help="hwsd route: soil Ksat -> aquifer K factor (dt_v004)")
    parser.add_argument("--hwsd_raster", type=str, default=None,
                        help="hwsd route: hwsd.bil (default: the shared lookup's path)")
    parser.add_argument("--hwsd_csv", type=str, default=None,
                        help="hwsd route: HWSD_DATA.csv (default: the shared lookup's path)")
    parser.add_argument("--output_dir", type=Path, required=True)
    parser.add_argument("--basin_name", type=str, default="basin")
    args = parser.parse_args()

    layer1_route = args.layer1_k or "alluvial_default"

    import xarray as xr
    import geopandas as gpd
    from shapely.geometry import Point

    # Read grid
    ds = xr.open_dataset(args.grid_nc)
    lat_key = 'y' if 'y' in ds else 'lat'
    lon_key = 'x' if 'x' in ds else 'lon'
    lats = ds[lat_key].values
    lons = ds[lon_key].values
    mask = ds['mask'].values if 'mask' in ds else np.ones((len(lats), len(lons)))
    ds.close()
    nrow, ncol = len(lats), len(lons)

    logger.info("Grid: %d × %d, %d layers", nrow, ncol, args.nlayers)

    # ── Layer 1 K (SKILL.md fact #10: not GLHYMPS) ──
    # Done BEFORE the 3.9 GB GLHYMPS read so a refused HWSD build costs nothing.
    hwsd_info = None
    if layer1_route == "hwsd":
        src, tag = "HWSD", "hwsd"
        logger.info("Layer 1 K from HWSD (ki_tools_common.soil_utils.lookup_hwsd), "
                    "%d active cells ...", int((mask > 0).sum()))
        k_layer1, hwsd_info = layer1_k_from_hwsd(lats, lons, mask, args.hwsd_aquifer_scale,
                                                 args.hwsd_raster, args.hwsd_csv)
        info = hwsd_info
        if info["no_soil"]:
            bad_json = args.output_dir / f"layer1_{tag}_no_soil.json"
            args.output_dir.mkdir(parents=True, exist_ok=True)
            with open(bad_json, "w") as f:
                json.dump(info, f, indent=2)
            for c in info["no_soil"][:20]:
                logger.error("  no %s soil at row %d col %d (%.4f, %.4f): %s",
                             src, c["row"], c["col"], c["lat"], c["lon"], c["reason"])
            logger.error("REFUSED: %d of %d active cells have no %s soil; nothing is "
                         "filled. Set mask=0 for them in the grid NetCDF or use "
                         "--layer1_k alluvial_default. List: %s",
                         len(info["no_soil"]), info["active_cells_looked_up"], src, bad_json)
            print(json.dumps({"refused": f"{tag}_no_soil",
                              "n_no_soil": len(info["no_soil"]),
                              "no_soil": info["no_soil"]}, indent=2))
            return EXIT_HWSD_NO_SOIL
        logger.info("  Layer 1 K from %s: %.3f - %.2f m/day (median %.2f)%s",
                    src, k_layer1[mask > 0].min(), k_layer1[mask > 0].max(),
                    np.median(k_layer1[mask > 0]),
                    f"; textures {hwsd_info['texture_counts']}" if hwsd_info else "")
    else:
        k_layer1 = np.full((nrow, ncol), ALLUVIAL_DEFAULT_K1)
        logger.info("Layer 1 K: alluvial default %.1f m/day (SKILL.md fact #10)",
                    ALLUVIAL_DEFAULT_K1)

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
    k_array[0] = k_layer1  # Layer 1: alluvial default or HWSD (--layer1_k)
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
        "k_layer1_source": ("HWSD_lookup_hwsd_saxton_rawls_x%g" % args.hwsd_aquifer_scale
                            if layer1_route == "hwsd"
                            else "alluvial_default_%.1f_mday" % ALLUVIAL_DEFAULT_K1),
        "k_layer1_active_range_mday": ([float(k_array[0][mask > 0].min()),
                                        float(k_array[0][mask > 0].max()),
                                        float(np.median(k_array[0][mask > 0]))]
                                       if (mask > 0).any() else None),
        "k_layer1_hwsd": hwsd_info,
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
    return 0


if __name__ == "__main__":
    _rc = main()
    # KDT FIX (2026-08-11, frenchpiezo network run) — SEGFAULT AT EXIT, same
    # failure as s2/build_layers_from_global.py. This tool writes k/k33/sy/ss/
    # icelltype/porosity .npy + k_summary.json and prints its summary, then dies
    # with SIGSEGV (returncode 139/-11) while the interpreter tears down the
    # geopandas/GDAL + xarray stack. Reproduced on the Aquitaine 44x40 grid:
    # 2570 GLHYMPS polygons read, Layer 2 K 0.0001-25.55 m/day written correctly,
    # rc 139. A caller that checks the return code (the KI pipeline must, or a
    # genuine GLHYMPS failure silently becomes default K) would discard a
    # perfectly good K field and fall back to alluvial defaults. Exit explicitly
    # once the tool's documented contract is met.
    import os as _os
    sys.stdout.flush()
    sys.stderr.flush()
    _os._exit(_rc or 0)
