#!/usr/bin/env python3
"""
prepare_basic_grids.py — Derive EF5-compatible DEM/DDM/FAM from a raw DEM.

Implements Stage 1 of the CREST KI pipeline (DEM Preparation), which the
SKILL.md table references but which had no implementation in this KI deployment.
Wraps the WhiteboxTools Python interface (already a HydroCraft dependency)
to produce sink-filled DEM, D8 drainage direction (ESRI encoding), and
flow accumulation (self-inclusive cell count) that EF5 can traverse end-to-end.

Pipeline stage: s1 (DEM Preparation)
Pattern: validate → process → validate

Input:
  - Raw DEM in GeoTIFF or ESRI ASCII (meters)
  - Optional bounding box for clipping
  - Sink-handling method (breach or fill)

Output:
  - dem.asc / dem.tif    — clipped, sink-filled DEM (meters)
  - ddm.asc / ddm.tif    — D8 drainage direction (ESRI 1,2,4,8,16,32,64,128)
  - fam.asc / fam.tif    — flow accumulation, self-inclusive (cell count, min=1)
  - prepare_basic_grids_log.json — diagnostic summary

Why this tool exists:
  The SKILL.md pipeline table lists 'prepare_basic_grids' as the Stage-1 tool,
  and s1_dem_preparation.md recommends 'ef5 -p' as a fallback — but neither
  was implemented in this KI deployment of EF5 v1.2.3. The result was that
  externally-prepared DDM/FAM (e.g. via wflow's pcraster ldd_create) entered
  the pipeline with unfilled sinks and disconnected routing topology,
  producing zero-discharge runs at every Huai/Yarlung site tested.

Conventions enforced (matches s1_dem_preparation.md):
  - ESRIDDM=true encoding (1=E, 2=SE, 4=S, 8=SW, 16=W, 32=NW, 64=N, 128=NE)
  - SELFFAM=true (FAM minimum = 1, every cell counts itself)
  - PROJ=geographic (input DEM must be in WGS84 lon/lat unless --laea)
  - Nodata = -9999 in all three outputs
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import rasterio
from rasterio.warp import reproject, Resampling, transform_bounds
from rasterio.transform import from_origin
from rasterio.windows import from_bounds


EF5_NODATA = -9999.0
ESRI_DDM_VALUES = {0, 1, 2, 4, 8, 16, 32, 64, 128}


# ── Utilities ──────────────────────────────────────────────────────────────

def info(msg):
    print(f"[prepare_basic_grids] {msg}", flush=True)


def warn(msg):
    print(f"[prepare_basic_grids] WARNING: {msg}", file=sys.stderr, flush=True)


def fatal(msg, code=1):
    print(f"[prepare_basic_grids] FATAL: {msg}", file=sys.stderr, flush=True)
    sys.exit(code)


def read_raster(path):
    """Load a single-band raster as (array, profile, transform, crs, nodata)."""
    with rasterio.open(path) as src:
        return src.read(1), src.profile.copy(), src.transform, src.crs, src.nodata


def write_tif(path, arr, transform, crs, nodata=EF5_NODATA):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(
        path, "w",
        driver="GTiff",
        height=arr.shape[0], width=arr.shape[1],
        count=1, dtype=arr.dtype, crs=crs,
        transform=transform, nodata=nodata,
        compress="deflate",
    ) as dst:
        dst.write(arr, 1)


def write_asc(path, arr, transform, nodata=EF5_NODATA, decimals=6):
    """Write ESRI ASCII grid. Assumes square cells, north-up transform."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    nrows, ncols = arr.shape
    cellsize = float(transform.a)
    if abs(abs(transform.e) - cellsize) > 1e-9:
        warn(f"non-square cells (dx={cellsize}, dy={abs(transform.e)}); ASC assumes square — using dx")
    xll = float(transform.c)
    yll = float(transform.f) - nrows * cellsize  # transform.f is upper-left y
    fmt = f"%.{decimals}f"
    with open(path, "w") as f:
        f.write(f"ncols         {ncols}\n")
        f.write(f"nrows         {nrows}\n")
        f.write(f"xllcorner     {xll:.6f}\n")
        f.write(f"yllcorner     {yll:.6f}\n")
        f.write(f"cellsize      {cellsize:.6f}\n")
        f.write(f"NODATA_value  {nodata}\n")
        for row in arr:
            f.write(" ".join(fmt % v for v in row) + "\n")


# ── Stages ─────────────────────────────────────────────────────────────────

def stage_clip(dem_in, bbox, out_path):
    """Optional spatial clip via rasterio. bbox is (lon_min, lat_min, lon_max, lat_max)."""
    with rasterio.open(dem_in) as src:
        if src.crs is None:
            fatal(f"input DEM has no CRS: {dem_in}")
        # bbox in WGS84 lon/lat; reproject to source CRS
        if src.crs.to_epsg() != 4326:
            xmin, ymin, xmax, ymax = transform_bounds("EPSG:4326", src.crs, *bbox)
        else:
            xmin, ymin, xmax, ymax = bbox
        win = from_bounds(xmin, ymin, xmax, ymax, src.transform)
        arr = src.read(1, window=win)
        new_transform = src.window_transform(win)
        prof = src.profile.copy()
        prof.update(height=arr.shape[0], width=arr.shape[1], transform=new_transform,
                    compress="deflate", driver="GTiff")
        with rasterio.open(out_path, "w", **prof) as dst:
            dst.write(arr, 1)
    info(f"clip: wrote {out_path} (bbox={bbox})")


def stage_fillsink(dem_in, dem_out, method="breach"):
    """Sink-fill via WhiteboxTools."""
    import whitebox
    wbt = whitebox.WhiteboxTools()
    wbt.set_verbose_mode(False)
    if method == "breach":
        info("fill_sinks: BreachDepressionsLeastCost")
        rc = wbt.breach_depressions_least_cost(
            dem=str(dem_in), output=str(dem_out), dist=10, fill=True,
        )
    else:
        info("fill_sinks: FillDepressions")
        rc = wbt.fill_depressions(dem=str(dem_in), output=str(dem_out))
    if rc != 0:
        fatal(f"WhiteboxTools sink fill returned non-zero rc={rc}")


def stage_d8_pointer(dem_filled, ddm_out, esri=True):
    """D8 drainage direction (ESRI encoding)."""
    import whitebox
    wbt = whitebox.WhiteboxTools()
    wbt.set_verbose_mode(False)
    info(f"d8_pointer: ESRI encoding = {esri}")
    rc = wbt.d8_pointer(dem=str(dem_filled), output=str(ddm_out), esri_pntr=esri)
    if rc != 0:
        fatal(f"WhiteboxTools d8_pointer returned non-zero rc={rc}")


def stage_d8_flow_acc(dem_filled, fam_out, pntr=None, esri=True, selffam=True):
    """D8 flow accumulation (cell count). Adds +1 to enforce SELFFAM=true if needed.

    WBT API: when pntr is provided (path to a D8 pointer raster), pass it as `i=`
    and set the boolean flag `pntr=True`. When pntr is None, pass the DEM as `i=`
    and leave `pntr=False`.
    """
    import whitebox
    wbt = whitebox.WhiteboxTools()
    wbt.set_verbose_mode(False)
    if pntr is not None:
        info(f"d8_flow_accumulation: from D8 pointer {pntr}, esri={esri}, selffam={selffam}")
        rc = wbt.d8_flow_accumulation(
            i=str(pntr),
            output=str(fam_out),
            out_type="cells",
            pntr=True,
            esri_pntr=esri,
        )
    else:
        info(f"d8_flow_accumulation: from DEM {dem_filled}, esri={esri}, selffam={selffam}")
        rc = wbt.d8_flow_accumulation(
            i=str(dem_filled),
            output=str(fam_out),
            out_type="cells",
            pntr=False,
        )
    if rc != 0:
        fatal(f"WhiteboxTools d8_flow_accumulation returned non-zero rc={rc}")
    if selffam:
        # WBT D8FlowAccumulation default is 0 at ridge cells (don't count self).
        # EF5's SELFFAM=true expects min=1 so every valid cell counts itself.
        with rasterio.open(fam_out) as src:
            arr = src.read(1)
            prof = src.profile.copy()
            nodata = src.nodata if src.nodata is not None else -9999
        valid = (arr != nodata) & np.isfinite(arr)
        arr = np.where(valid, arr + 1.0, arr)
        prof.update(driver="GTiff", compress="deflate", nodata=nodata)
        with rasterio.open(fam_out, "w", **prof) as dst:
            dst.write(arr.astype(prof["dtype"]), 1)
        info("d8_flow_accumulation: applied +1 for SELFFAM=true convention")


# ── Verification ───────────────────────────────────────────────────────────

def verify_outputs(dem_path, ddm_path, fam_path, expected_outlet=None):
    """Sanity checks; returns a dict with diagnostics."""
    dem, _, dem_t, dem_crs, dem_nd = read_raster(dem_path)
    ddm, _, ddm_t, ddm_crs, ddm_nd = read_raster(ddm_path)
    fam, _, fam_t, fam_crs, fam_nd = read_raster(fam_path)

    diag = {
        "shape_match": (dem.shape == ddm.shape == fam.shape),
        "transform_match": (
            dem_t.almost_equals(ddm_t, precision=1e-9)
            and dem_t.almost_equals(fam_t, precision=1e-9)
        ),
        "crs_match": str(dem_crs) == str(ddm_crs) == str(fam_crs),
        "shape": list(dem.shape),
        "extent": [float(dem_t.c),
                   float(dem_t.f) + dem.shape[0]*float(dem_t.e),
                   float(dem_t.c) + dem.shape[1]*float(dem_t.a),
                   float(dem_t.f)],
        "cellsize_deg": float(dem_t.a),
        "ddm_values": sorted(int(v) for v in np.unique(ddm) if v != ddm_nd and np.isfinite(v)),
        "ddm_n_sinks": int(((ddm == 0) & np.isfinite(ddm)).sum()),
        "ddm_total_valid": int((ddm != ddm_nd).sum()),
        "fam_max": float(np.nanmax(fam[fam != fam_nd])),
        "fam_n_total": int((fam != fam_nd).sum()),
    }
    diag["ddm_sink_pct"] = 100.0 * diag["ddm_n_sinks"] / max(diag["ddm_total_valid"], 1)
    diag["ddm_encoding_ok"] = set(diag["ddm_values"]) <= ESRI_DDM_VALUES

    # Outlet check: at the highest-FAM cell, FAM should be close to total valid cells
    flat_idx = int(np.argmax(np.where(fam != fam_nd, fam, -np.inf)))
    r, c = divmod(flat_idx, fam.shape[1])
    diag["max_fam_cell_rc"] = [r, c]
    diag["max_fam_cell_lonlat"] = [
        float(dem_t.c) + (c + 0.5) * float(dem_t.a),
        float(dem_t.f) + (r + 0.5) * float(dem_t.e),
    ]
    diag["max_fam_coverage_pct"] = 100.0 * diag["fam_max"] / max(diag["fam_n_total"], 1)

    if expected_outlet is not None:
        lon, lat = expected_outlet
        oc = int((lon - dem_t.c) / dem_t.a)
        or_ = int((lat - dem_t.f) / dem_t.e)
        if 0 <= or_ < fam.shape[0] and 0 <= oc < fam.shape[1]:
            diag["expected_outlet_lonlat"] = [lon, lat]
            diag["expected_outlet_fam"] = float(fam[or_, oc])
            # Snap window: 3x3 around expected
            r0, r1 = max(0, or_-1), min(fam.shape[0], or_+2)
            c0, c1 = max(0, oc-1), min(fam.shape[1], oc+2)
            sub = np.where(fam[r0:r1, c0:c1] != fam_nd, fam[r0:r1, c0:c1], -np.inf)
            diag["expected_outlet_fam_3x3_max"] = float(sub.max())

    return diag


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description="Derive EF5-compatible DEM/DDM/FAM from a raw DEM (Stage 1)."
    )
    ap.add_argument("--dem", required=True, help="Input DEM (GeoTIFF or ESRI ASC), units: meters")
    ap.add_argument("--out-dir", required=True, help="Output directory for dem/ddm/fam grids")
    ap.add_argument("--bbox", nargs=4, type=float, default=None,
                    metavar=("LON_MIN", "LAT_MIN", "LON_MAX", "LAT_MAX"),
                    help="Optional WGS84 bbox to clip DEM before processing")
    ap.add_argument("--method", choices=["breach", "fill"], default="breach",
                    help="Sink handling: breach (least-cost, gentler) or fill (raise)")
    ap.add_argument("--no-selffam", action="store_true",
                    help="Skip SELFFAM=true +1 adjustment (use only if you'll set ESRIDDM with SELFFAM=false)")
    ap.add_argument("--out-format", choices=["asc", "tif", "both"], default="asc",
                    help="EF5 prefers ASC (TIF reader has rasterio bugs per known_issues)")
    ap.add_argument("--expected-outlet", nargs=2, type=float, default=None,
                    metavar=("LON", "LAT"),
                    help="Optional gauge lon/lat to verify FAM at expected outlet")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    log_path = out_dir / "prepare_basic_grids_log.json"

    t0 = time.time()
    log = {
        "tool": "prepare_basic_grids.py",
        "ki": "hydrocraft-crest-ef5 v1.0.0",
        "inputs": {"dem": str(args.dem), "bbox": args.bbox, "method": args.method,
                   "out_format": args.out_format},
        "stages": {},
    }

    # ── Stage A: optional clip ────────────────────────────────────────────
    # WhiteboxTools requires GeoTIFFs with valid geokeys; ESRI ASCII has no CRS,
    # so any ASC input must be promoted to TIF with EPSG:4326 (per
    # s1_dem_preparation.md PROJ=geographic default).
    work_dir = out_dir / "_work"
    work_dir.mkdir(exist_ok=True)
    dem_clipped = work_dir / "dem_clipped.tif"
    if args.bbox:
        stage_clip(args.dem, tuple(args.bbox), dem_clipped)
        # If clipped from ASC source, CRS may be missing — patch
        with rasterio.open(dem_clipped) as src:
            if src.crs is None:
                arr = src.read(1)
                t = src.transform
                nd = src.nodata
            else:
                t = None
        if t is not None:
            warn("clipped DEM had no CRS; assuming EPSG:4326 (PROJ=geographic)")
            write_tif(dem_clipped, arr.astype(np.float32), t,
                      "EPSG:4326", nodata=nd or EF5_NODATA)
        log["stages"]["clip"] = {"output": str(dem_clipped), "bbox": args.bbox}
        dem_for_fill = dem_clipped
    else:
        # Convert ASC to TIF if needed for WhiteboxTools (needs geokeys)
        if str(args.dem).lower().endswith(".asc"):
            arr, _, t, crs, nd = read_raster(args.dem)
            if crs is None:
                warn("input ASC has no CRS; assuming EPSG:4326 (PROJ=geographic per s1)")
                crs = "EPSG:4326"
            write_tif(dem_clipped, arr.astype(np.float32), t, crs,
                      nodata=nd if nd is not None else EF5_NODATA)
            dem_for_fill = dem_clipped
        else:
            # Verify CRS exists; if not, copy with EPSG:4326
            with rasterio.open(args.dem) as src:
                if src.crs is None:
                    warn(f"input TIF {args.dem} has no CRS; assuming EPSG:4326")
                    arr = src.read(1)
                    write_tif(dem_clipped, arr.astype(np.float32), src.transform,
                              "EPSG:4326", nodata=src.nodata or EF5_NODATA)
                    dem_for_fill = dem_clipped
                else:
                    dem_for_fill = Path(args.dem)
        log["stages"]["clip"] = {"skipped": True}

    # ── Stage B: sink fill ────────────────────────────────────────────────
    dem_filled = work_dir / "dem_filled.tif"
    stage_fillsink(dem_for_fill, dem_filled, method=args.method)
    log["stages"]["fillsink"] = {"method": args.method, "output": str(dem_filled)}

    # ── Stage C: D8 pointer (DDM) ─────────────────────────────────────────
    ddm_tif = work_dir / "ddm.tif"
    stage_d8_pointer(dem_filled, ddm_tif, esri=True)
    log["stages"]["d8_pointer"] = {"esri": True, "output": str(ddm_tif)}

    # ── Stage D: D8 flow accumulation (FAM) ───────────────────────────────
    fam_tif = work_dir / "fam.tif"
    stage_d8_flow_acc(dem_filled, fam_tif, pntr=ddm_tif, esri=True,
                      selffam=not args.no_selffam)
    log["stages"]["d8_flow_acc"] = {"out_type": "cells", "selffam": not args.no_selffam,
                                     "output": str(fam_tif)}

    # ── Stage E: write canonical outputs in requested format ──────────────
    final = {}
    for name, src in [("dem", dem_filled), ("ddm", ddm_tif), ("fam", fam_tif)]:
        arr, _, t, crs, nd = read_raster(src)
        # Standardize nodata to EF5_NODATA, but keep DDM as integer-coded (ESRI 1-128)
        arr = np.where(np.isfinite(arr) & (arr != nd), arr, EF5_NODATA).astype(np.float32)
        if args.out_format in ("asc", "both"):
            asc = out_dir / f"{name}.asc"
            write_asc(asc, arr, t, nodata=EF5_NODATA)
            final.setdefault(name, []).append(str(asc))
            info(f"wrote {asc}")
        if args.out_format in ("tif", "both"):
            tif = out_dir / f"{name}.tif"
            write_tif(tif, arr, t, crs, nodata=EF5_NODATA)
            final.setdefault(name, []).append(str(tif))
            info(f"wrote {tif}")
    log["outputs"] = final

    # ── Stage F: verify ───────────────────────────────────────────────────
    suffix = "asc" if args.out_format != "tif" else "tif"
    diag = verify_outputs(
        out_dir / f"dem.{suffix}",
        out_dir / f"ddm.{suffix}",
        out_dir / f"fam.{suffix}",
        expected_outlet=tuple(args.expected_outlet) if args.expected_outlet else None,
    )
    log["verification"] = diag
    log["wallclock_s"] = round(time.time() - t0, 3)

    # Hard checks (fail loudly if these fail)
    issues = []
    if not diag["shape_match"]:
        issues.append("shape mismatch between dem/ddm/fam")
    if not diag["transform_match"]:
        issues.append("transform mismatch between dem/ddm/fam")
    if not diag["ddm_encoding_ok"]:
        issues.append(f"DDM has non-ESRI values: {diag['ddm_values']}")
    if diag["ddm_sink_pct"] > 1.0:
        issues.append(f"DDM still has {diag['ddm_n_sinks']} sinks "
                      f"({diag['ddm_sink_pct']:.2f}% of basin) — fillsink incomplete")
    log["issues"] = issues

    log_path.write_text(json.dumps(log, indent=2, default=str))
    info(f"log: {log_path}")

    # Summary line
    info("─" * 60)
    info(f"shape: {diag['shape']}, cellsize: {diag['cellsize_deg']:.6f} deg")
    info(f"DDM unique values: {diag['ddm_values']}")
    info(f"DDM sinks: {diag['ddm_n_sinks']} ({diag['ddm_sink_pct']:.2f}%)")
    info(f"FAM max: {diag['fam_max']:.0f} cells "
         f"({diag['max_fam_coverage_pct']:.1f}% of basin)")
    if "expected_outlet_fam" in diag:
        info(f"expected outlet FAM: {diag['expected_outlet_fam']:.0f} "
             f"(3x3 max: {diag['expected_outlet_fam_3x3_max']:.0f})")
    if issues:
        for i in issues:
            warn(i)
        sys.exit(2)
    info("OK")


if __name__ == "__main__":
    main()
