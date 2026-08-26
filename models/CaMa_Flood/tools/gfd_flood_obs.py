#!/usr/bin/env python3
"""
gfd_flood_obs.py -- Global Flood Database v1.4 (Tellman et al. 2021) observation reader.

dag.yaml binds the flood-extent outputs of this model to an observation the KI could not read:

    fldfrc (rank 6) -> gfd_v1_4_global (flood_extent_raster), obs_shape spatial_snapshot,
                       comparison categorical_event_comparison, determining_metric csi
    fldare (rank 7) -> gfd_v1_4_global, obs_shape regional_aggregate_time_series

There was no tool in tools/ that could open that product, so those two dag outputs were
unvalidatable. This is that tool: it resolves a DFO event, extracts its GeoTIFF from the
archive, and aggregates the 250 m flood mask onto whatever regular lat/lon grid the model side
lives on -- the CaMa 15-min grid, or the high-resolution grid produced by
`parse_cama_output.py --downscale`.

The model side of the pair is parse_cama_output.py, NOT the shell scripts in tools/downscale/:
those are symlinks to macOS-only scripts with a hard-coded /Volumes/... workspace root and
cannot run here (dt_cama_016). `parse_cama_output.py --downscale` drives the same official
utility; `--downscaled_dir` then reduces its output to a field on exactly the grid this module
produces (row 0 = north, col 0 = west, cell centres), so the two rasters align cell-for-cell.

ARCHIVE LAYOUT (verified 2026-08-20)
  KISSPATH_DATA/GFD_v1_4_full.zip                       16.3 GB, 913 events
    GFD_v1_4_full/DFO_{id}_From_{YYYYMMDD}_to_{YYYYMMDD}.zip     <- one NESTED zip per event
      DFO_{id}_From_{YYYYMMDD}_to_{YYYYMMDD}.tif                 <- 5-band GeoTIFF, EPSG:4326
      DFO_{id}_properties.json, README_GFD.pdf, LICENSE.txt
  Pixel size 0.002245788210298804 deg (~250 m).
  Bands: 1 flooded, 2 duration, 3 clear_views, 4 clear_perc, 5 jrc_perm_water.
  Values: 1 = yes, 0 = no, -inf = nodata. There is no nodata NAN -- test with np.isfinite.

CRITICAL SEMANTICS
  * band 1 'flooded' is the MAXIMUM extent observed across the whole event window, i.e. a
    composite snapshot -- the model side must be reduced the same way (max over the window),
    not sampled on one day.
  * band 1 EXCLUDES permanent water. CaMa's downscaler does the opposite: it forces every
    pixel flagged in <res>.rivwth.bin up to >= 0.1 m. Comparing the two without removing
    permanent water scores the world's rivers as false alarms. Use --exclude_perm_water
    (default) and threshold the model ABOVE 0.1 m.
  * MODIS cannot see through cloud: band 3/4 record how many clear views a pixel got. Pixels
    with few clear views under-report flooding. Screen with --min_clear_perc.

Usage:
    # list candidate events for a region/period
    python gfd_flood_obs.py --list --west 98 --east 110 --south 8 --north 22 \\
                            --date_start 2001-01-01 --date_end 2001-12-31

    # extract one event and aggregate it onto a target grid
    python gfd_flood_obs.py --event_id 1781 \\
        --west 98 --east 109.5 --south 8.5 --north 21.7 --resolution 0.0166666666666667 \\
        --out_nc /tmp/gfd_1781_1min.nc
"""

import argparse
import json
import os
import sys
import zipfile

import numpy as np

ARCHIVE_ZIP = "KISSPATH_DATA/GFD_v1_4_full.zip"
CATALOG_JSON = ("KISSPATH_OBS/flood/gfd_v1_4_asia_rice_belt/"
                "gfd_v1_4_global_event_catalog.json")
DEFAULT_CACHE = "KISSPATH_OBS/flood/gfd_v1_4_events"

BAND_FLOODED = 1
BAND_DURATION = 2
BAND_CLEAR_VIEWS = 3
BAND_CLEAR_PERC = 4
BAND_PERM_WATER = 5


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------

def load_catalog(catalog_json=CATALOG_JSON):
    """Return the list of GFD event records (913 entries, one per DFO event)."""
    if not os.path.isfile(catalog_json):
        raise FileNotFoundError(
            f"GFD catalog not found: {catalog_json}. It is a projection of {ARCHIVE_ZIP}; "
            "rebuild it by listing the archive's nested zip names.")
    with open(catalog_json) as f:
        doc = json.load(f)
    return doc["records"] if isinstance(doc, dict) else doc


def find_events(records, west=None, east=None, south=None, north=None,
                date_start=None, date_end=None, min_severity=None):
    """Filter catalog records by DFO centroid bbox / event date range / severity.

    NOTE: dfo_centroid_x/y is the DFO *report* centroid, not the raster footprint -- an event
    whose centroid sits outside the bbox can still cover it. Widen the bbox rather than trusting
    the centroid, and confirm the real footprint from the extracted GeoTIFF's bounds.
    """
    out = []
    for r in records:
        x, y = r.get("dfo_centroid_x"), r.get("dfo_centroid_y")
        if west is not None and (x is None or x < west):
            continue
        if east is not None and (x is None or x > east):
            continue
        if south is not None and (y is None or y < south):
            continue
        if north is not None and (y is None or y > north):
            continue
        if date_start is not None and r.get("ended", "") < str(date_start):
            continue
        if date_end is not None and r.get("began", "") > str(date_end):
            continue
        if min_severity is not None and (r.get("dfo_severity") or 0) < min_severity:
            continue
        out.append(r)
    return out


def get_event(records, event_id):
    for r in records:
        if int(r["id"]) == int(event_id):
            return r
    raise KeyError(f"DFO event {event_id} not in the GFD catalog")


# ---------------------------------------------------------------------------
# Extraction (resumable: never re-extracts an event already on disk)
# ---------------------------------------------------------------------------

def extract_event(event, cache_dir=DEFAULT_CACHE, archive_zip=ARCHIVE_ZIP):
    """Extract one event's GeoTIFF from the nested-zip archive. Returns the .tif path.

    Resumable by design: a 16 GB outer zip is opened only when the target .tif is absent.
    """
    entry = event.get("_zip_entry")
    if not entry:
        raise KeyError(f"event {event.get('id')} has no _zip_entry in the catalog")
    inner_name = os.path.basename(entry)                  # DFO_1781_From_..._to_....zip
    stem = inner_name[:-4]
    ev_dir = os.path.join(cache_dir, stem)
    tif_path = os.path.join(ev_dir, stem + ".tif")
    if os.path.isfile(tif_path) and os.path.getsize(tif_path) > 0:
        return tif_path

    os.makedirs(ev_dir, exist_ok=True)
    if not os.path.isfile(archive_zip):
        raise FileNotFoundError(f"GFD archive not found: {archive_zip}")
    with zipfile.ZipFile(archive_zip) as outer:
        inner_bytes = outer.read(entry)
    inner_tmp = os.path.join(ev_dir, inner_name + ".part")
    with open(inner_tmp, "wb") as f:
        f.write(inner_bytes)
    with zipfile.ZipFile(inner_tmp) as inner:
        inner.extractall(ev_dir)
    os.remove(inner_tmp)

    if not os.path.isfile(tif_path):
        cands = [f for f in os.listdir(ev_dir) if f.endswith(".tif")]
        if not cands:
            raise FileNotFoundError(f"no .tif inside {inner_name}")
        tif_path = os.path.join(ev_dir, cands[0])
    return tif_path


# ---------------------------------------------------------------------------
# Aggregation to a target regular grid
# ---------------------------------------------------------------------------

def aggregate_to_grid(tif_path, west, east, south, north, resolution,
                      min_clear_perc=0.0, exclude_perm_water=True, block_rows=512):
    """Aggregate the 250 m GFD event mask onto a regular lat/lon grid.

    The GFD pixel (0.002245788 deg) is not an integer divisor of either the CaMa 15-min grid or
    the 1-min downscaling grid, so this bins pixel CENTRES into target cells rather than
    reshaping -- a reshape-based "upscale" would silently mis-register the mask.

    Returns dict with 2-D arrays on the target grid (row 0 = NORTH, col 0 = WEST):
      flood_frac  flooded pixels / usable pixels        (nan where no usable pixel)
      perm_frac   permanent-water pixels / all valid pixels
      valid_frac  usable pixels / target-cell pixel capacity
      n_valid     usable pixel count per cell
      lats, lons  cell centres
    plus the raster footprint and the pixel-level totals used for the area check.
    """
    import rasterio

    nx = int(round((east - west) / resolution))
    ny = int(round((north - south) / resolution))
    if nx <= 0 or ny <= 0:
        raise ValueError(f"empty target grid: nx={nx}, ny={ny}")

    flood_cnt = np.zeros(ny * nx, dtype=np.int64)
    perm_cnt = np.zeros(ny * nx, dtype=np.int64)
    valid_cnt = np.zeros(ny * nx, dtype=np.int64)      # finite AND clear enough AND (optionally) not permanent water
    allvalid_cnt = np.zeros(ny * nx, dtype=np.int64)   # finite, before the clear/permanent screens

    px_flood = px_valid = px_perm = 0

    with rasterio.open(tif_path) as src:
        tr = src.transform
        H, W = src.height, src.width
        bounds = src.bounds
        for r0 in range(0, H, block_rows):
            nr = min(block_rows, H - r0)
            win = rasterio.windows.Window(0, r0, W, nr)
            flooded = src.read(BAND_FLOODED, window=win)
            perm = src.read(BAND_PERM_WATER, window=win)
            clearp = src.read(BAND_CLEAR_PERC, window=win)

            rows = np.arange(r0, r0 + nr)
            lat = tr.f + (rows + 0.5) * tr.e                 # tr.e is negative (north-up)
            lon = tr.c + (np.arange(W) + 0.5) * tr.a

            in_lat = (lat > south) & (lat < north)
            in_lon = (lon > west) & (lon < east)
            if not in_lat.any() or not in_lon.any():
                continue
            ri = np.where(in_lat)[0]
            ci = np.where(in_lon)[0]
            flooded = flooded[np.ix_(ri, ci)]
            perm = perm[np.ix_(ri, ci)]
            clearp = clearp[np.ix_(ri, ci)]
            lat_s, lon_s = lat[ri], lon[ci]

            tr_row = np.clip(((north - lat_s) / resolution).astype(np.int64), 0, ny - 1)
            tr_col = np.clip(((lon_s - west) / resolution).astype(np.int64), 0, nx - 1)
            flat = (tr_row[:, None] * nx + tr_col[None, :]).ravel()

            finite = np.isfinite(flooded).ravel()
            is_flood = (flooded == 1).ravel()
            is_perm = (perm == 1).ravel()
            clear_ok = np.where(np.isfinite(clearp), clearp, 0.0).ravel() >= min_clear_perc

            usable = finite & clear_ok
            if exclude_perm_water:
                usable &= ~is_perm

            allvalid_cnt += np.bincount(flat[finite], minlength=ny * nx)
            valid_cnt += np.bincount(flat[usable], minlength=ny * nx)
            flood_cnt += np.bincount(flat[usable & is_flood], minlength=ny * nx)
            perm_cnt += np.bincount(flat[finite & is_perm], minlength=ny * nx)

            px_valid += int(usable.sum())
            px_flood += int((usable & is_flood).sum())
            px_perm += int((finite & is_perm).sum())

        px_area_km2 = abs(tr.a * tr.e) * (111.32 ** 2)   # approximate, cos(lat) applied below

    flood_cnt = flood_cnt.reshape(ny, nx)
    perm_cnt = perm_cnt.reshape(ny, nx)
    valid_cnt = valid_cnt.reshape(ny, nx)
    allvalid_cnt = allvalid_cnt.reshape(ny, nx)

    with np.errstate(invalid="ignore", divide="ignore"):
        flood_frac = np.where(valid_cnt > 0, flood_cnt / np.maximum(valid_cnt, 1), np.nan)
        perm_frac = np.where(allvalid_cnt > 0, perm_cnt / np.maximum(allvalid_cnt, 1), np.nan)

    capacity = (resolution / abs(tr.a)) * (resolution / abs(tr.e))
    valid_frac = valid_cnt / capacity

    lats = north - (np.arange(ny) + 0.5) * resolution     # descending, N->S
    lons = west + (np.arange(nx) + 0.5) * resolution

    # flooded area: pixel area scaled by cos(latitude) of each pixel row's target cell
    cos_lat = np.cos(np.radians(lats))[:, None]
    flooded_area_km2 = float(np.nansum(flood_cnt * px_area_km2 * cos_lat))

    return {
        "flood_frac": flood_frac, "perm_frac": perm_frac, "valid_frac": valid_frac,
        "n_valid": valid_cnt, "n_flood": flood_cnt,
        "lats": lats, "lons": lons, "resolution": resolution,
        "west": west, "east": east, "south": south, "north": north,
        "raster_bounds": [bounds.left, bounds.bottom, bounds.right, bounds.top],
        "pixels_valid": px_valid, "pixels_flooded": px_flood, "pixels_perm_water": px_perm,
        "flooded_area_km2": flooded_area_km2,
        "min_clear_perc": min_clear_perc, "exclude_perm_water": bool(exclude_perm_water),
        "source_tif": tif_path,
    }


def write_nc(agg, out_nc, event=None):
    import xarray as xr
    ds = xr.Dataset(
        {
            "flood_frac": (("lat", "lon"), agg["flood_frac"].astype("float32")),
            "perm_frac": (("lat", "lon"), agg["perm_frac"].astype("float32")),
            "valid_frac": (("lat", "lon"), agg["valid_frac"].astype("float32")),
            "n_valid": (("lat", "lon"), agg["n_valid"].astype("int32")),
        },
        coords={"lat": agg["lats"], "lon": agg["lons"]},
        attrs={
            "title": "GFD v1.4 flood extent aggregated to a regular grid",
            "source": "Tellman et al. 2021, Global Flood Database v1.4 (DFO/MODIS)",
            "source_tif": agg["source_tif"],
            "min_clear_perc": agg["min_clear_perc"],
            "exclude_perm_water": str(agg["exclude_perm_water"]),
            "pixels_flooded": agg["pixels_flooded"],
            "pixels_valid": agg["pixels_valid"],
            "flooded_area_km2": agg["flooded_area_km2"],
        },
    )
    if event:
        ds.attrs.update({"dfo_id": int(event["id"]), "began": event["began"],
                         "ended": event["ended"], "countries": event.get("countries", "")})
    os.makedirs(os.path.dirname(os.path.abspath(out_nc)), exist_ok=True)
    ds.to_netcdf(out_nc)
    ds.close()
    return out_nc


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--list", action="store_true", help="List matching events and exit")
    p.add_argument("--event_id", type=int, help="DFO event id to extract")
    p.add_argument("--west", type=float)
    p.add_argument("--east", type=float)
    p.add_argument("--south", type=float)
    p.add_argument("--north", type=float)
    p.add_argument("--resolution", type=float, default=0.25,
                   help="Target grid resolution in degrees (default 0.25 = CaMa 15min)")
    p.add_argument("--date_start")
    p.add_argument("--date_end")
    p.add_argument("--min_severity", type=float)
    p.add_argument("--min_clear_perc", type=float, default=0.0,
                   help="Drop pixels whose GFD clear_perc is below this (0-1)")
    p.add_argument("--keep_perm_water", action="store_true",
                   help="Keep JRC permanent-water pixels (default: excluded, matching the "
                        "'flooded' band's own definition)")
    p.add_argument("--cache_dir", default=DEFAULT_CACHE)
    p.add_argument("--out_nc")
    args = p.parse_args()

    records = load_catalog()

    if args.list or args.event_id is None:
        hits = find_events(records, args.west, args.east, args.south, args.north,
                           args.date_start, args.date_end, args.min_severity)
        print(f"{len(hits)} matching GFD events (of {len(records)} in the archive):")
        for r in sorted(hits, key=lambda r: r["began"]):
            print(f"  DFO {r['id']:>5}  {r['began']} .. {r['ended']}  sev={r['dfo_severity']}  "
                  f"({r['dfo_centroid_x']:.2f}, {r['dfo_centroid_y']:.2f})  "
                  f"{r.get('dfo_main_cause','')} | {r.get('countries','')[:60]}")
        return

    event = get_event(records, args.event_id)
    print(f"DFO {event['id']}: {event['began']} .. {event['ended']} | {event.get('countries')}")
    tif = extract_event(event, cache_dir=args.cache_dir)
    print(f"  GeoTIFF: {tif}")

    if None in (args.west, args.east, args.south, args.north):
        import rasterio
        with rasterio.open(tif) as src:
            print(f"  raster footprint: {src.bounds}, {src.width}x{src.height}, "
                  f"res {src.res}, bands {src.descriptions}")
        print("  (pass --west/--east/--south/--north --resolution to aggregate)")
        return

    agg = aggregate_to_grid(tif, args.west, args.east, args.south, args.north,
                            args.resolution, min_clear_perc=args.min_clear_perc,
                            exclude_perm_water=not args.keep_perm_water)
    ff = agg["flood_frac"]
    print(f"  target grid: {ff.shape[1]} lon x {ff.shape[0]} lat @ {args.resolution} deg")
    print(f"  usable pixels {agg['pixels_valid']:,}, flooded {agg['pixels_flooded']:,}, "
          f"permanent water {agg['pixels_perm_water']:,}")
    print(f"  observed flooded area: {agg['flooded_area_km2']:,.0f} km2")
    print(f"  cells with any flooding: {int(np.nansum(ff > 0))} / {ff.size}")

    if args.out_nc:
        write_nc(agg, args.out_nc, event)
        print(f"  Wrote: {args.out_nc}")


if __name__ == "__main__":
    main()
