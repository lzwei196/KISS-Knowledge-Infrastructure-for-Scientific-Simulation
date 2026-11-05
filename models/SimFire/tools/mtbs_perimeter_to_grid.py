#!/usr/bin/env python3
"""
mtbs_perimeter_to_grid.py — S7 validation support: MTBS fire perimeters -> SimFire grid.

Stage S7 ("Validation") of the SimFire pipeline had NO tool: SKILL.md's tool
table listed it as "—", so every agent had to hand-roll the observed-perimeter
side of the comparison.  That is exactly where the dag's hard caveat bites:

    "Compared maps must share grid size and georeferencing;
     size mismatch is a hard failure."     (dag.yaml, fire_map/spatial_snapshot)

This tool owns both halves of that contract.

Sub-commands
------------
select     Filter the MTBS national perimeter shapefile down to a set of fires
           (region bbox, ignition year, incident type, burned-area band, and a
           maximum perimeter span so the fire fits a runnable SimFire domain)
           and emit a JSON manifest with, per fire, the SimFire `operational`
           block needed to build its domain.

rasterize  Burn one fire's perimeter polygon onto the EXACT grid SimFire
           simulated on, read from the LandFire GeoTIFF that simfire cached in
           SF_HOME, and write `observed_perimeter.npy` (1 = burned) that
           `parse_simfire_output.py --observed-perimeter` consumes directly.

Why the GeoTIFF and not the config
----------------------------------
simfire does NOT simulate on the grid the config asks for.  `LandFireLatLongBox`
downloads a raster, then crops it to `[:floor(height/30), :floor(width/30)]`
(layers.py:123-127) starting at the raster's top-left cell; `Config._load_area`
then OVERWRITES `area.screen_size` with the cropped shape (config.py:477-481).
The only trustworthy georeference for the simulated array is therefore the
cached GeoTIFF's own affine transform plus that top-left crop — which is what
`grid_reference()` below reconstructs.  Reconstructing it from the config's
lat/lon instead re-introduces simfire's isotropic-degrees error (see
convert_landfire_to_simfire.isotropize_bbox).

MTBS notes (verified 2026-08-09 against mtbs_perims_DD.shp, 30730 features)
--------------------------------------------------------------------------
  * CRS is EPSG:4269 (NAD83 geographic), NOT 4326 — reproject, don't assume.
  * `BurnBndLat` / `BurnBndLon` / `BurnBndAc` are stored as STRINGS in the
    .dbf; comparing them numerically without `pd.to_numeric` raises
    `TypeError: '>' not supported between instances of 'str' and 'float'`.
  * `BurnBndLat/Lon` is the burn-boundary CENTROID, not the ignition point.
    MTBS ships no ignition coordinate and no containment date — only `Ig_Date`.
  * `Incid_Type` distinguishes Wildfire / Prescribed Fire / Wildland Fire Use;
    only `Wildfire` is a spread-model validation target.

Usage
-----
    python mtbs_perimeter_to_grid.py select \\
        --shapefile .../mtbs_perims_DD.shp \\
        --bbox -120.5 36.0 -114.0 42.5 --year 2020 \\
        --min-acres 5000 --max-acres 60000 --max-span-km 11 \\
        --margin-frac 0.45 --max-cells 480 \\
        --output manifest.json

    python mtbs_perimeter_to_grid.py rasterize \\
        --shapefile .../mtbs_perims_DD.shp --event-id NV4083911966720200812 \\
        --landfire-tif ~/.simfire/landfire/2020/lf_.../j....tif \\
        --rows 400 --cols 400 \\
        --output observed_perimeter.npy
"""

import argparse
import json
import math
import os
import sys
from pathlib import Path

import numpy as np

MTBS_DEFAULT_SHP = (
    "KISSPATH_OBS/fire_perimeters/mtbs/"
    "mtbs_perims/mtbs_perims_DD.shp"
)

# simfire's hard-coded "30 m in degrees" constant (config.py:340-342).
SIMFIRE_DEG_PER_PIXEL = 0.00027777777803598015


def _read_mtbs(shapefile):
    """Load the MTBS perimeter layer with its string columns coerced to numbers."""
    import geopandas as gpd
    import pandas as pd

    gdf = gpd.read_file(shapefile)
    gdf["Ig_Date"] = pd.to_datetime(gdf["Ig_Date"], errors="coerce")
    for col in ("BurnBndLat", "BurnBndLon", "BurnBndAc"):
        if col in gdf.columns:
            gdf[col] = pd.to_numeric(gdf[col], errors="coerce")
    return gdf


def _local_albers(lat, lon):
    """The AOI-centred Albers CRS LFPS returns for a native-projection request.

    LFPS does not hand back EPSG:5070; it builds a custom
    ``Albers_Conic_Equal_Area`` centred on the AOI.  For measuring spans and
    laying out a square 30 m domain any locally-centred equal-area projection
    is equivalent, so this is only used for SELECTION geometry.  The
    `rasterize` sub-command uses the GeoTIFF's OWN crs, never this.
    """
    from pyproj import CRS

    return CRS.from_proj4(
        f"+proj=aea +lat_0={lat} +lon_0={lon} +lat_1={lat - 0.5} "
        f"+lat_2={lat + 0.5} +x_0=0 +y_0=0 +datum=NAD83 +units=m +no_defs"
    )


def cmd_select(args):
    """Pick a set of MTBS fires and size a SimFire domain for each."""
    gdf = _read_mtbs(args.shapefile)
    n_total = len(gdf)

    sel = gdf[gdf["Incid_Type"] == args.incident_type]
    if args.year is not None:
        sel = sel[sel["Ig_Date"].dt.year == args.year]
    minx, miny, maxx, maxy = args.bbox
    sel = sel[
        (sel["BurnBndLon"] > minx)
        & (sel["BurnBndLon"] < maxx)
        & (sel["BurnBndLat"] > miny)
        & (sel["BurnBndLat"] < maxy)
    ]
    sel = sel[
        (sel["BurnBndAc"] >= args.min_acres) & (sel["BurnBndAc"] <= args.max_acres)
    ]
    sel = sel.sort_values("BurnBndAc", ascending=False)

    fires, rejected = [], []
    for _, row in sel.iterrows():
        lat_c, lon_c = float(row["BurnBndLat"]), float(row["BurnBndLon"])
        aea = _local_albers(lat_c, lon_c)
        geom_m = (
            sel.loc[[row.name], "geometry"].to_crs(aea).iloc[0]
        )
        gminx, gminy, gmaxx, gmaxy = geom_m.bounds
        span_m = max(gmaxx - gminx, gmaxy - gminy)
        poly_acres = geom_m.area / 4046.856

        # DATA-QUALITY GATE. `BurnBndAc` is an ATTRIBUTE; the polygon is the
        # observation. Some MTBS records disagree badly -- e.g. 2020 "NORTH"
        # (CA3983312003820200802) reports BurnBndAc 34120 while the shipped
        # perimeter is 6823 ac, a 5x mismatch. Scoring against such a record
        # means you do not know which number the obs actually is, so drop it
        # rather than silently pick one.
        tol = args.acreage_tolerance
        tol = None if (tol is not None and tol < 0) else tol
        rel = abs(poly_acres - float(row["BurnBndAc"])) / max(1.0, float(row["BurnBndAc"]))
        if tol is not None and rel > tol:
            rejected.append({
                "event_id": row["Event_ID"], "name": row["Incid_Name"],
                "reason": (f"polygon {poly_acres:.0f} ac vs BurnBndAc "
                           f"{float(row['BurnBndAc']):.0f} ac -> {rel:.0%} "
                           f"mismatch > tolerance {tol:.0%}"),
            })
            continue

        if span_m / 1000.0 > args.max_span_km:
            rejected.append(
                {
                    "event_id": row["Event_ID"],
                    "name": row["Incid_Name"],
                    "reason": f"span {span_m/1000:.1f} km > max_span_km {args.max_span_km}",
                }
            )
            continue

        # Square domain: fire bbox + margin, snapped to whole 30 m cells.
        side_m = span_m * (1.0 + 2.0 * args.margin_frac)
        n_cells = int(math.ceil(side_m / 30.0))
        if n_cells > args.max_cells:
            rejected.append(
                {
                    "event_id": row["Event_ID"],
                    "name": row["Incid_Name"],
                    "reason": f"needs {n_cells} cells > max_cells {args.max_cells}",
                }
            )
            continue
        side_m = n_cells * 30.0

        # Domain centred on the perimeter centroid, in the local equal-area CRS.
        cx, cy = 0.5 * (gminx + gmaxx), 0.5 * (gminy + gmaxy)
        tl_x, tl_y = cx - side_m / 2.0, cy + side_m / 2.0

        from pyproj import Transformer

        to_deg = Transformer.from_crs(aea, "EPSG:4326", always_xy=True)
        tl_lon, tl_lat = to_deg.transform(tl_x, tl_y)
        # Ignition = perimeter centroid. MTBS ships no ignition point; the
        # centroid is the only prior-free choice available from this obs.
        ig_lon, ig_lat = to_deg.transform(cx, cy)

        fires.append(
            {
                "event_id": row["Event_ID"],
                "name": row["Incid_Name"],
                "ig_date": row["Ig_Date"].strftime("%Y-%m-%d"),
                "burn_bnd_acres": float(row["BurnBndAc"]),
                "polygon_acres": round(poly_acres, 1),
                "centroid_lat": lat_c,
                "centroid_lon": lon_c,
                "span_km": round(span_m / 1000.0, 3),
                "ignition_lat": round(ig_lat, 6),
                "ignition_lon": round(ig_lon, 6),
                "domain_cells": n_cells,
                # The SimFire `operational` block. height == width == n*30 m so
                # the crop floor(h/30) x floor(w/30) yields exactly n x n cells.
                "operational": {
                    "seed": None,
                    "latitude": round(tl_lat, 6),
                    "longitude": round(tl_lon, 6),
                    "height": int(n_cells * 30),
                    "width": int(n_cells * 30),
                    "resolution": 30,
                    # LF2016 Remap is the pre-2022 fuel vintage; for a 2020 fire
                    # it is the closest PRE-fire fuel state available.
                    "year": 2022 if row["Ig_Date"].year >= 2022 else 2020,
                },
            }
        )
        if args.limit and len(fires) >= args.limit:
            break

    manifest = {
        "shapefile": str(args.shapefile),
        "n_features_total": n_total,
        "filters": {
            "bbox": list(args.bbox),
            "year": args.year,
            "incident_type": args.incident_type,
            "min_acres": args.min_acres,
            "max_acres": args.max_acres,
            "max_span_km": args.max_span_km,
            "margin_frac": args.margin_frac,
            "max_cells": args.max_cells,
            "acreage_tolerance": args.acreage_tolerance,
            "limit": args.limit,
        },
        "n_selected": len(fires),
        "n_rejected": len(rejected),
        "rejected": rejected,   # never drop coverage silently
        "fires": fires,
    }
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w") as fh:
            json.dump(manifest, fh, indent=2)
    return manifest


def grid_reference(landfire_tif, rows, cols):
    """Reconstruct the georeference of the array SimFire actually simulated on.

    simfire reads the cached GeoTIFF whole and then crops
    ``[:rows, :cols]`` from index (0, 0), so the cropped array shares the
    parent raster's CRS and origin and differs only in extent.

    Returns:
        (crs, transform, (rows, cols)) — an affine transform valid for the
        cropped array.
    """
    import rasterio
    from rasterio.windows import Window

    with rasterio.open(str(landfire_tif)) as src:
        if src.height < rows or src.width < cols:
            raise RuntimeError(
                f"LandFire raster {src.width}x{src.height} is SMALLER than the "
                f"requested crop {cols}x{rows}: simfire silently truncated the "
                f"domain. Widen the AOI (see isotropize_bbox) and re-download."
            )
        transform = src.window_transform(Window(0, 0, cols, rows))
        return src.crs, transform, (rows, cols)


def cmd_rasterize(args):
    """Burn one MTBS perimeter onto SimFire's simulated grid."""
    import rasterio.features

    gdf = _read_mtbs(args.shapefile)
    match = gdf[gdf["Event_ID"] == args.event_id]
    if match.empty:
        raise SystemExit(f"Event_ID not found in {args.shapefile}: {args.event_id}")

    crs, transform, (rows, cols) = grid_reference(
        args.landfire_tif, args.rows, args.cols
    )
    geom = match.to_crs(crs).geometry.iloc[0]

    observed = rasterio.features.rasterize(
        [(geom, 1)],
        out_shape=(rows, cols),
        transform=transform,
        fill=0,
        all_touched=False,   # pixel-CENTRE rule, the standard burned/not test
        dtype="uint8",
    )

    obs_pixels = int(observed.sum())
    coverage = obs_pixels / float(rows * cols)
    result = {
        "event_id": args.event_id,
        "grid_shape": [rows, cols],
        "crs": str(crs),
        "observed_burned_pixels": obs_pixels,
        "observed_area_ha": round(obs_pixels * 900.0 / 10000.0, 2),
        "observed_area_acres": round(obs_pixels * 900.0 / 4046.856, 2),
        "mtbs_reported_acres": float(match["BurnBndAc"].iloc[0]),
        "domain_burned_fraction": round(coverage, 5),
        "warnings": [],
    }
    if obs_pixels == 0:
        result["warnings"].append(
            "ZERO observed pixels — the perimeter does not intersect the "
            "simulated grid. Georeferencing or domain placement is wrong."
        )
    if coverage > 0.85:
        result["warnings"].append(
            "Perimeter fills >85% of the domain; enlarge margin_frac so the "
            "model has room to over-predict (else commission error is capped)."
        )

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        np.save(args.output, observed)
        result["output"] = str(args.output)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    sub = parser.add_subparsers(dest="cmd", required=True)

    ps = sub.add_parser("select", help="filter MTBS fires and size SimFire domains")
    ps.add_argument("--shapefile", default=MTBS_DEFAULT_SHP)
    ps.add_argument("--bbox", type=float, nargs=4, required=True,
                    metavar=("MINLON", "MINLAT", "MAXLON", "MAXLAT"))
    ps.add_argument("--year", type=int, default=None)
    ps.add_argument("--incident-type", default="Wildfire")
    ps.add_argument("--min-acres", type=float, default=5000)
    ps.add_argument("--max-acres", type=float, default=60000)
    ps.add_argument("--max-span-km", type=float, default=11.0)
    ps.add_argument("--margin-frac", type=float, default=0.45,
                    help="domain margin on EACH side, as a fraction of the span")
    ps.add_argument("--max-cells", type=int, default=480)
    ps.add_argument("--acreage-tolerance", type=float, default=0.10,
                    help="max |polygon area - BurnBndAc| / BurnBndAc; records "
                         "beyond it are rejected as internally inconsistent. "
                         "Pass a negative value to disable.")
    ps.add_argument("--limit", type=int, default=0)
    ps.add_argument("--output", default=None)

    pr = sub.add_parser("rasterize", help="burn one perimeter onto the sim grid")
    pr.add_argument("--shapefile", default=MTBS_DEFAULT_SHP)
    pr.add_argument("--event-id", required=True)
    pr.add_argument("--landfire-tif", required=True)
    pr.add_argument("--rows", type=int, required=True)
    pr.add_argument("--cols", type=int, required=True)
    pr.add_argument("--output", default=None)

    args = parser.parse_args()
    result = cmd_select(args) if args.cmd == "select" else cmd_rasterize(args)
    print(json.dumps({"status": "success", "output": result}, indent=2, default=str))


if __name__ == "__main__":
    main()
