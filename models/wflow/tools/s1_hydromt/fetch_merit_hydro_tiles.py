#!/usr/bin/env python3
"""
fetch_merit_hydro_tiles.py — stage MERIT-Hydro 5-degree tiles for a bbox.

RESTORED TOOL. This file is documented in SKILL.md (usage block, the non-China
checklist and the Tools Reference table) and is shelled out to by
`models/wflow/run_and_score_pelotas.py:stage_prep()`, but it was wiped from disk
by a KI snapshot rollback — `<ki>/.kdt_state.yaml` records
`{path: 'tools/s1_hydromt/fetch_merit_hydro_tiles.py', diff_lines: 160,
snap_bytes: 0, now_bytes: 6347}`. Without it no fresh basin can follow the
documented s1 workflow.

WHY NOT `tar xf` BY HAND (SKILL.md)
-----------------------------------
MERIT-Hydro ships 30x30-degree TAR archives, each holding thirty-six 5x5-degree
GeoTIFFs. Two different naming grids are in play and both are easy to get wrong:

  * a 5-deg TILE is named by its BOTTOM-LEFT corner, 2-digit lat + 3-digit lon
    -> `s30w055_dir.tif` spans lat [-30, -25], lon [-55, -50]
  * the 30-deg ARCHIVE stem is floor(lat/30)*30 / floor(lon/30)*30
    -> s30w055 lives in `dir_s30w060.tar`, NOT `dir_s30w055.tar`,
       under the member path `dir_s30w060/s30w055_dir.tif`

Getting either wrong surfaces only much later, as
`no MERIT-Hydro 'dir' tiles under <cache> for bbox (...)` out of
`run_hydromt_build.py`.

BEHAVIOUR
---------
  * bbox comes from `--shapefile` (+ `--pad_deg`) or directly from `--bbox`
  * resumable: a tile already present in `--out_dir` with a non-zero size is
    skipped, so re-running the whole pipeline costs nothing
  * never writes a partial GeoTIFF — each member is extracted to `<name>.part`
    in the destination directory and `os.replace`d into place only after the
    stream is fully written
  * fails loudly: a missing archive is an error, and by default so is a member
    that the archive does not contain (`--allow_missing_tiles` downgrades the
    latter to a reported warning, which is what you want only when the bbox
    genuinely reaches all-ocean tiles that MERIT-Hydro omits)

USAGE (exactly the CLI SKILL.md and run_and_score_pelotas.py already use)
------------------------------------------------------------------------
    python tools/s1_hydromt/fetch_merit_hydro_tiles.py \
      --shapefile data/shp/<basin>.shp --pad_deg 0.4 \
      --out_dir KISSPATH_DATA/merit_hydro_cache

    python tools/s1_hydromt/fetch_merit_hydro_tiles.py \
      --bbox -51.3 -29.2 -49.0 -27.5 --out_dir <cache> --kinds dir,upa,elv

`--kinds` defaults to `dir,upa` (what the coarse LDD upscaling needs). Add `elv`
when `run_hydromt_build.py` should derive RiverSlope from the sub-grid channel
profile rather than from the coarse D8 drop.
"""

import argparse
import json
import math
import os
import sys
import tarfile

DEFAULT_ARCHIVE_DIR = "KISSPATH_DATA/MERIT_Hydro/v1.0.1"
DEFAULT_KINDS = "dir,upa"


def tile_stem(lat_bottom, lon_left):
    """MERIT-Hydro 5-deg tile stem, named by the BOTTOM-LEFT corner."""
    ns = "n" if lat_bottom >= 0 else "s"
    ew = "e" if lon_left >= 0 else "w"
    return f"{ns}{abs(int(lat_bottom)):02d}{ew}{abs(int(lon_left)):03d}"


def archive_stem(lat_bottom, lon_left):
    """30-deg archive stem holding the 5-deg tile at (lat_bottom, lon_left)."""
    la = int(math.floor(lat_bottom / 30.0) * 30)
    lo = int(math.floor(lon_left / 30.0) * 30)
    ns = "n" if la >= 0 else "s"
    ew = "e" if lo >= 0 else "w"
    return f"{ns}{abs(la):02d}{ew}{abs(lo):03d}"


def tiles_for_bbox(bbox):
    """5-deg tile corners covering bbox=(minlon, minlat, maxlon, maxlat)."""
    minlon, minlat, maxlon, maxlat = bbox
    lat0 = int(math.floor(minlat / 5.0) * 5)
    lat1 = int(math.floor(maxlat / 5.0) * 5)
    lon0 = int(math.floor(minlon / 5.0) * 5)
    lon1 = int(math.floor(maxlon / 5.0) * 5)
    return [(la, lo)
            for la in range(lat0, lat1 + 1, 5)
            for lo in range(lon0, lon1 + 1, 5)]


def bbox_from_shapefile(path, pad_deg):
    import geopandas as gpd
    g = gpd.read_file(path)
    if g.crs is not None and g.crs.to_epsg() != 4326:
        g = g.to_crs(4326)
    minx, miny, maxx, maxy = g.total_bounds
    return (float(minx) - pad_deg, float(miny) - pad_deg,
            float(maxx) + pad_deg, float(maxy) + pad_deg)


def extract_tile(archive_path, member, dest, allow_missing):
    """Extract one member to `dest` atomically. Returns 'ok' or 'missing'."""
    tmp = dest + ".part"
    with tarfile.open(archive_path, "r") as tf:
        try:
            fh = tf.extractfile(member)
        except KeyError:
            fh = None
        if fh is None:
            if allow_missing:
                return "missing"
            raise FileNotFoundError(
                f"{archive_path} has no member {member}. MERIT-Hydro omits "
                f"all-ocean tiles; pass --allow_missing_tiles only if this tile "
                f"is genuinely offshore.")
        try:
            with open(tmp, "wb") as out:
                while True:
                    chunk = fh.read(8 << 20)
                    if not chunk:
                        break
                    out.write(chunk)
        finally:
            fh.close()
    if os.path.getsize(tmp) == 0:
        os.remove(tmp)
        raise IOError(f"extracted 0 bytes for {member} from {archive_path}")
    os.replace(tmp, dest)
    return "ok"


def fetch(bbox, out_dir, kinds, archive_dir=DEFAULT_ARCHIVE_DIR,
          allow_missing=False, force=False, verbose=True):
    os.makedirs(out_dir, exist_ok=True)
    corners = tiles_for_bbox(bbox)
    staged, cached, missing = [], [], []

    for kind in kinds:
        for la, lo in corners:
            stem = tile_stem(la, lo)
            name = f"{stem}_{kind}.tif"
            dest = os.path.join(out_dir, name)
            if not force and os.path.exists(dest) and os.path.getsize(dest) > 0:
                cached.append(name)
                continue
            astem = archive_stem(la, lo)
            apath = os.path.join(archive_dir, f"{kind}_{astem}.tar")
            if not os.path.exists(apath):
                raise FileNotFoundError(
                    f"MERIT-Hydro archive not found: {apath} (needed for tile "
                    f"{name}). Check --archive_dir; the 30-deg stem is "
                    f"floor(lat/30)*30 / floor(lon/30)*30.")
            member = f"{kind}_{astem}/{name}"
            if verbose:
                print(f"  extracting {member} <- {os.path.basename(apath)}",
                      file=sys.stderr)
            status = extract_tile(apath, member, dest, allow_missing)
            (staged if status == "ok" else missing).append(name)

    return {"status": "success",
            "bbox": [round(b, 4) for b in bbox],
            "kinds": kinds,
            "tiles_expected": [f"{tile_stem(la, lo)}" for la, lo in corners],
            "staged": sorted(staged),
            "already_cached": sorted(cached),
            "missing_in_archive": sorted(missing),
            "out_dir": out_dir}


def main():
    ap = argparse.ArgumentParser(
        description="Stage MERIT-Hydro 5-deg tiles for a basin bbox (resumable)")
    ap.add_argument("--shapefile", type=str, default="",
                    help="Basin shapefile; the bbox is its total_bounds + pad")
    ap.add_argument("--bbox", type=float, nargs=4, default=None,
                    metavar=("MINLON", "MINLAT", "MAXLON", "MAXLAT"),
                    help="Explicit bbox, alternative to --shapefile")
    ap.add_argument("--pad_deg", type=float, default=0.0,
                    help="Pad applied to the shapefile bounds (deg)")
    ap.add_argument("--out_dir", type=str, required=True,
                    help="MERIT-Hydro tile cache directory")
    ap.add_argument("--kinds", type=str, default=DEFAULT_KINDS,
                    help=f"Comma-separated MERIT layers (default {DEFAULT_KINDS}; "
                         "'elv' is needed for sub-grid RiverSlope)")
    ap.add_argument("--archive_dir", type=str, default=DEFAULT_ARCHIVE_DIR,
                    help="Directory of the 30-deg <kind>_<stem>.tar archives")
    ap.add_argument("--allow_missing_tiles", action="store_true",
                    help="Report, instead of failing on, a tile the archive "
                         "does not contain (all-ocean tiles)")
    ap.add_argument("--force", action="store_true",
                    help="Re-extract even if the tile is already cached")
    args = ap.parse_args()

    if args.bbox:
        bbox = tuple(args.bbox)
    elif args.shapefile:
        if not os.path.exists(args.shapefile):
            print(json.dumps({"status": "failed",
                              "error": f"shapefile not found: {args.shapefile}"},
                             indent=2))
            sys.exit(2)
        bbox = bbox_from_shapefile(args.shapefile, args.pad_deg)
    else:
        print(json.dumps({"status": "failed",
                          "error": "provide --shapefile or --bbox"}, indent=2))
        sys.exit(2)

    kinds = [k.strip() for k in args.kinds.split(",") if k.strip()]
    try:
        result = fetch(bbox, args.out_dir, kinds, args.archive_dir,
                       args.allow_missing_tiles, args.force)
    except (FileNotFoundError, IOError, tarfile.TarError) as e:
        print(json.dumps({"status": "failed", "error": str(e)}, indent=2))
        sys.exit(2)

    print(json.dumps(result, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
