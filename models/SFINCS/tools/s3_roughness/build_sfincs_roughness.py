#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      build_sfincs_roughness
Stage:        s3_roughness
Description:  Generate spatially varying Manning's n from AVHRR land cover classification.

Inputs:
  --grid_info:    Path to grid_info.json from s1_domain
  --lulc_path:    Path to land use/land cover raster (default: AVHRR 1km, resolved through
                  dataset_index.yaml -> parameter_sourcing.land_cover.avhrr_landcover)
  --output_dir:   Output directory
  --uniform_n:    Use uniform Manning's n instead of LULC-based (optional)
  --index_file / --topobathy_dir: s2's sfincs.ind. REQUIRED — without it this tool exits
                  non-zero rather than writing a full grid SFINCS would misread (dt_v023).

Outputs:
  - sfincs.man:   Manning's n as a COMPRESSED SFINCS binary map: n_active float32 in
                  sfincs.ind order (Fortran, row 0 = SOUTH), NOT an nmax*mmax grid.
  - roughness_summary.json

Exit codes:
  0 — success, 1 — input error, 2 — processing error, 3 — output error
"""

import sys
import os
import json
import logging
import argparse
import numpy as np
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# AVHRR land cover class to Manning's n lookup table
# Source: Chow (1959), Arcement & Schneider (1989), SFINCS documentation
MANNING_LOOKUP = {
    # AVHRR class: (Manning's n, description)
    0:  (0.025, "Water"),
    1:  (0.100, "Evergreen Needleleaf Forest"),
    2:  (0.100, "Evergreen Broadleaf Forest"),
    3:  (0.100, "Deciduous Needleleaf Forest"),
    4:  (0.100, "Deciduous Broadleaf Forest"),
    5:  (0.100, "Mixed Forest"),
    6:  (0.040, "Closed Shrubland"),
    7:  (0.035, "Open Shrubland"),
    8:  (0.040, "Woody Savannas"),
    9:  (0.035, "Savannas"),
    10: (0.035, "Grasslands"),
    11: (0.030, "Permanent Wetlands"),
    12: (0.040, "Croplands"),
    13: (0.080, "Urban and Built-Up"),
    14: (0.040, "Cropland/Natural Vegetation Mosaic"),
    15: (0.015, "Snow and Ice"),
    16: (0.030, "Barren or Sparsely Vegetated"),
}

# Default AVHRR land cover (same source as the VIC vegetation parameters).
# dt_v022: "KISSPATH_DATA/..." is a REMOVABLE drive that is not mounted on this
# server, so the auto-discovery glob returned [] and every domain silently fell back to
# uniform n=0.04 — stage s3 was a no-op without ever erroring. The correct on-disk copy is
# the one registered in dataset_index.yaml as
# parameter_sourcing.land_cover.avhrr_landcover, so that registry is resolved FIRST
# (registry_lookup below actually reads it — the paths in AVHRR_SEARCH_PATHS are only a
# last-resort fallback for when the registry is missing or unparseable).
DATASET_INDEX = "KISSPATH_DATA_KI/dataset_index.yaml"
AVHRR_REGISTRY_ID = "avhrr_landcover"
AVHRR_REGISTRY_CATEGORY = "parameter_sourcing.land_cover"
AVHRR_SEARCH_PATHS = [
    "KISSPATH_DATA/landcover/AVHRR_1km_LANDCOVER_1981_1994.GLOBAL.tif",
    "KISSPATH_DATA/landcover/",
    "KISSPATH_FORCING/AVHRR/",
]
AVHRR_DEFAULT = AVHRR_SEARCH_PATHS[0]


def registry_lookup(index_path, entry_id, category=None):
    """Resolve a dataset path through the KI registry (data_ki/dataset_index.yaml).

    Returns the registered path, or None if the registry / PyYAML / the entry is absent
    (the caller then falls back to AVHRR_SEARCH_PATHS)."""
    try:
        import yaml
    except ImportError:
        logger.warning("PyYAML unavailable — cannot read %s, falling back to the hardcoded "
                       "search paths", index_path)
        return None
    p = Path(index_path)
    if not p.exists():
        logger.warning("Dataset registry not found: %s — falling back to the hardcoded "
                       "search paths", p)
        return None
    try:
        with open(p) as f:
            idx = yaml.safe_load(f) or {}
    except Exception as e:
        logger.warning("Could not parse %s (%s) — falling back to the hardcoded search "
                       "paths", p, e)
        return None
    for entry in idx.get("entries", []) or []:
        if entry.get("id") != entry_id:
            continue
        if category and entry.get("category") != category:
            continue
        path = entry.get("path")
        if path:
            logger.info("Registry %s -> %s (%s, path_status=%s)", entry_id, path,
                        entry.get("category"), entry.get("path_status"))
            return path
    logger.warning("No entry '%s' in %s — falling back to the hardcoded search paths",
                   entry_id, p)
    return None


def validate_inputs(args):
    errors = []
    if not Path(args.grid_info).exists():
        errors.append(f"Grid info not found: {args.grid_info}")
    if args.lulc_path and not Path(args.lulc_path).exists():
        errors.append(f"LULC raster not found: {args.lulc_path}")
    if not args.output_dir:
        errors.append("--output_dir is required")
    if args.uniform_n is not None and (args.uniform_n < 0.001 or args.uniform_n > 1.0):
        errors.append(f"Manning's n must be 0.001-1.0, got {args.uniform_n}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def process(args):
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    with open(args.grid_info) as f:
        grid = json.load(f)

    mmax = grid["mmax"]
    nmax = grid["nmax"]
    dx = grid["dx"]
    dy = grid["dy"]
    x0 = grid["x0"]
    y0 = grid["y0"]
    epsg = grid["epsg"]

    if args.uniform_n is not None:
        # Uniform Manning's n
        manning = np.full((nmax, mmax), args.uniform_n, dtype=np.float32)
        logger.info(f"Using uniform Manning's n = {args.uniform_n}")
        class_counts = {"uniform": mmax * nmax}
        method = "uniform"
        lulc_path = None
    else:
        # LULC-based Manning's n
        import rasterio
        from rasterio.warp import reproject, Resampling
        from rasterio.transform import from_origin
        from pyproj import CRS

        lulc_path = args.lulc_path
        if not lulc_path:
            # dt_v022: the registry is the source of truth for this dataset; the hardcoded
            # roots are only searched if it cannot be read. Skip AppleDouble ._ files.
            import glob
            registered = registry_lookup(args.dataset_index, AVHRR_REGISTRY_ID,
                                         AVHRR_REGISTRY_CATEGORY)
            roots = ([registered] if registered else []) + AVHRR_SEARCH_PATHS
            avhrr_files = []
            for root in roots:
                if os.path.isfile(root):
                    avhrr_files = [root]
                elif os.path.isdir(root):
                    avhrr_files = [f for f in sorted(glob.glob(os.path.join(root, "**/*.tif"),
                                                               recursive=True))
                                   if not os.path.basename(f).startswith("._")]
                if avhrr_files:
                    break
            if avhrr_files:
                lulc_path = avhrr_files[0]
                logger.info(f"Auto-selected AVHRR: {lulc_path}")

        if lulc_path:
            target_crs = CRS.from_epsg(epsg)
            y_top = y0 + nmax * dy
            target_transform = from_origin(x0, y_top, dx, dy)

            with rasterio.open(lulc_path) as src:
                lulc_grid = np.zeros((nmax, mmax), dtype=np.int16)
                reproject(
                    source=rasterio.band(src, 1),
                    destination=lulc_grid,
                    src_transform=src.transform,
                    src_crs=src.crs,
                    dst_transform=target_transform,
                    dst_crs=target_crs,
                    resampling=Resampling.nearest,
                    dst_nodata=-1,
                )

            # Map LULC classes to Manning's n
            manning = np.full((nmax, mmax), 0.04, dtype=np.float32)  # default
            class_counts = {}
            for cls, (n_val, desc) in MANNING_LOOKUP.items():
                mask = (lulc_grid == cls)
                count = int(np.sum(mask))
                if count > 0:
                    manning[mask] = n_val
                    class_counts[f"{cls}_{desc}"] = count

            logger.info(f"LULC class distribution: {class_counts}")
            method = "lulc_based"
        else:
            # No LULC anywhere: still produce a VALID (compressed) map below rather than
            # returning early with an uncompressed grid — the fallback is a physical
            # simplification, not a licence to write a file SFINCS would misread.
            logger.warning("No LULC data found (registry %s + %s). Falling back to uniform "
                           "n=0.04", AVHRR_REGISTRY_ID, AVHRR_SEARCH_PATHS)
            manning = np.full((nmax, mmax), 0.04, dtype=np.float32)
            class_counts = {"fallback_uniform": mmax * nmax}
            method = "fallback_uniform"

    # Write Manning's n binary file.
    # dt_v023: manningfile is a SFINCS *binary map*, exactly like depfile/mskfile — it
    # holds ONLY the active cells, in sfincs.ind order (Fortran, row 0 = SOUTH). Writing
    # the full nmax*mmax C-order grid makes SFINCS take the first n_active values, i.e. a
    # scrambled roughness field, without any error message. Point --index_file (or
    # --topobathy_dir) at s2's sfincs.ind to get the compression right.
    man_path = output_dir / "sfincs.man"
    ind_file = args.index_file
    if not ind_file and args.topobathy_dir:
        ind_file = str(Path(args.topobathy_dir) / "sfincs.ind")
    if not ind_file and (output_dir / "sfincs.ind").exists():
        ind_file = str(output_dir / "sfincs.ind")

    if not (ind_file and Path(ind_file).exists()):
        logger.error("No sfincs.ind found (--index_file / --topobathy_dir / %s). A FULL "
                     "uncompressed grid would be MISREAD by SFINCS as a compressed map "
                     "(dt_v023): it would take the first n_active values as the roughness "
                     "field and run a scrambled domain WITHOUT any error. Refusing to write "
                     "sfincs.man — run s2 (build_sfincs_topobathy.py) first and pass its "
                     "index file.", output_dir / "sfincs.ind")
        sys.exit(3)

    ind = np.fromfile(ind_file, dtype=np.int32)
    if ind.size < 1:
        logger.error("Index file is empty: %s", ind_file)
        sys.exit(2)
    n_active, idx = int(ind[0]), ind[1:]

    # Cross-check s3's grid against the grid s2 actually indexed. Without this a
    # differently-shaped-but-same-size roughness grid yields a silently SCRAMBLED
    # sfincs.man, and an index built for a bigger grid yields an opaque IndexError.
    if manning.size != nmax * mmax:
        logger.error("Internal error: manning grid has %d cells, expected nmax*mmax = %d",
                     manning.size, nmax * mmax)
        sys.exit(2)
    if len(idx) != n_active:
        logger.error("%s header says %d active cells but carries %d indices — the index "
                     "file is truncated or corrupt.", ind_file, n_active, len(idx))
        sys.exit(2)
    if n_active == 0:
        logger.error("%s reports 0 active cells — s2 produced an empty domain.", ind_file)
        sys.exit(2)
    tb_summary = Path(ind_file).parent / "topobathy_summary.json"
    if tb_summary.exists():
        try:
            with open(tb_summary) as f:
                tb_shape = json.load(f).get("grid_shape")
        except Exception as e:
            logger.warning("Could not read %s for the grid cross-check: %s", tb_summary, e)
            tb_shape = None
        if tb_shape and list(tb_shape) != [nmax, mmax]:
            logger.error("Grid mismatch: s2 indexed a %s grid (%s) but this run's "
                         "grid_info.json is [%d, %d]. Compressing against a foreign index "
                         "would scramble sfincs.man.", tb_shape, tb_summary, nmax, mmax)
            sys.exit(2)
    if int(idx.min()) < 1 or int(idx.max()) > manning.size:
        logger.error("%s indexes cell %d of a grid with only %d cells (nmax=%d, mmax=%d) — "
                     "this index was built for a DIFFERENT domain.", ind_file,
                     int(idx.max()), manning.size, nmax, mmax)
        sys.exit(2)

    man_south = manning[::-1, :].flatten(order="F")
    man_south[idx - 1].astype(np.float32).tofile(str(man_path))
    compressed = True
    logger.info(f"Wrote COMPRESSED sfincs.man for {n_active} active cells "
                f"(index: {ind_file})")
    logger.info(f"Wrote: {man_path} ({man_path.stat().st_size} bytes)")
    if man_path.stat().st_size != n_active * 4:
        logger.error("dt_v023 format invariant violated: sfincs.man is %d bytes, must be "
                     "%d float32 = %d. Refusing to leave a malformed binary map on disk.",
                     man_path.stat().st_size, n_active, n_active * 4)
        sys.exit(3)

    summary = {
        "status": "success",
        "man_file": str(man_path),
        "compressed_to_active_cells": compressed,
        "index_file": ind_file,
        "n_active_cells": n_active,
        "grid_shape": [nmax, mmax],
        "lulc_source": lulc_path,
        "method": method,
        "manning_min": float(np.min(manning)),
        "manning_max": float(np.max(manning)),
        "manning_mean": float(np.mean(manning)),
        "manning_median": float(np.median(manning)),
        "class_counts": class_counts,
    }

    summary_path = output_dir / "roughness_summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(json.dumps(summary, indent=2))
    return str(summary_path)


def validate_outputs(output_path):
    if not Path(output_path).exists():
        logger.error(f"Summary not created: {output_path}")
        sys.exit(3)
    parent = Path(output_path).parent
    man_path = parent / "sfincs.man"
    if not man_path.exists() or man_path.stat().st_size == 0:
        logger.error(f"Manning's n file missing or empty: {man_path}")
        sys.exit(3)
    logger.info("Output validation passed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build SFINCS Manning's n roughness")
    parser.add_argument("--grid_info", required=True, help="Path to grid_info.json")
    parser.add_argument("--lulc_path", default=None, help="LULC raster path")
    parser.add_argument("--dataset_index", default=DATASET_INDEX,
                        help="KI dataset registry used to resolve the default AVHRR land "
                             "cover (entry parameter_sourcing.land_cover.avhrr_landcover)")
    parser.add_argument("--output_dir", required=True, help="Output directory")
    parser.add_argument("--uniform_n", type=float, default=None, help="Uniform Manning's n (overrides LULC)")
    parser.add_argument("--index_file", default=None,
                        help="Path to s2's sfincs.ind. REQUIRED for a correct sfincs.man: "
                             "manningfile is a compressed binary map (dt_v023).")
    parser.add_argument("--topobathy_dir", default=None,
                        help="Dir containing sfincs.ind (alternative to --index_file)")
    args = parser.parse_args()

    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs(args)

    try:
        output_path = process(args)
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(2)

    validate_outputs(output_path)
    sys.exit(0)
