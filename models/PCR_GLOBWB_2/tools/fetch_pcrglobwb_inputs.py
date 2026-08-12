#!/usr/bin/env python3
"""
PCR-GLOBWB 2 Input Acquisition
==============================
Downloads a bounding-box subset of the official ``global_30min`` input set from
the 4TU OPeNDAP server into a local directory laid out exactly as the .ini
expects (``{local_dir}/global_30min/...``), so a regional run needs no manual
file hunting.

Pipeline stage: s1b (Input Acquisition)
Pattern: validate_inputs -> process -> validate_outputs

The full global_30min tree is tens of gigabytes; a 22x20-cell clone needs about
5 MB. Every file is opened over OPeNDAP, sliced on its lat/lon axes to the
requested bbox, and rewritten locally with all other dimensions (time,
land-cover class, ...) intact.

RESUMABLE: a file whose local copy already opens cleanly is skipped, so an
interrupted fetch can simply be re-run. Pass ``--force`` to refetch everything.

Bounding box
------------
``--bbox lon_min lat_min lon_max lat_max`` is interpreted as CELL CENTRES: a
cell is kept when its centre lies inside the box. Feed it the clone's
``lon_min_centre``/``lat_min_centre``/... from ``{prefix}.clone.json``, or a
slightly larger box -- PCR-GLOBWB clips every input map to the clone anyway,
and a box smaller than the clone makes the model read missing values.

Initial conditions
------------------
``--ic-year YYYY`` fetches the official non-natural (human-influenced) initial
state for 31 December of that year. Start the transient run on 1 January of
YYYY+1 so the model picks up a spun-up state instead of an arbitrary one.
"""

import os
import sys
import time
import json
import argparse
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np

try:
    import netCDF4 as nc
except ImportError:  # pragma: no cover
    nc = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


DEFAULT_BASE_URL = (
    "https://opendap.4tu.nl/thredds/dodsC/data2/pcrglobwb/version_2019_11_beta/"
    "pcrglobwb2_input"
)

# The relative-elevation maps are named by the level in PERCENT of bankfull,
# zero-padded to four digits: level 0.05 -> dzRel0005.nc. Naming them by
# level*1000 yields dzRel0050..dzRel1000, which do not exist on the server and
# fail with 'NetCDF: file not found'.
DZREL_LEVELS = [0, 1, 5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100]

_LANDCOVER = {
    "naturalTall": ("Forest", "forestProperties.nc"),
    "naturalShort": ("Grassland", "grasslandProperties.nc"),
    "irrPaddy": ("IrrPaddy", "paddyProperties.nc"),
    "irrNonPaddy": ("IrrNonPaddy", "nonPaddyProperties.nc"),
}

# Initial-condition state variables of the official non-natural run.
_IC_COVER_STATES = ["interceptStor", "snowCoverSWE", "snowFreeWater",
                    "topWaterLayer", "storUpp", "storLow", "interflow"]
_IC_COVERS = ["forest", "grassland", "irrPaddy", "irrNonPaddy"]
_IC_SCALARS = [
    "storGroundwater", "storGroundwaterFossil", "baseflow",
    "avgNonFossilGroundwaterAllocationLong", "avgNonFossilGroundwaterAllocationShort",
    "avgTotalGroundwaterAbstraction", "avgTotalGroundwaterAllocationLong",
    "avgTotalGroundwaterAllocationShort", "relativeGroundwaterHead",
    "waterBodyStorage", "channelStorage", "readAvlChannelStorage",
    "avgDischargeLong", "avgDischargeShort", "m2tDischargeLong",
    "avgBaseflowLong", "riverbedExchange", "subDischarge",
    "avgLakeReservoirInflowShort", "avgLakeReservoirOutflowLong",
    "timestepsToAvgDischarge",
]


# ---------------------------------------------------------------------------
# Required vs OPTIONAL inputs
# ---------------------------------------------------------------------------
# Everything under waterUse/ is ANTHROPOGENIC water use (irrigation, human/
# industrial/livestock demand, desalination, abstraction zones, source
# partitioning). A NATURAL-flow discharge validation does not need any of it,
# and PCR-GLOBWB runs fine in natural mode with water use OFF. These files also
# happen to be the ones the 4tu.nl OPeNDAP server intermittently fails to serve
# (2026-07-13: 4 water-demand files unreachable for hours). So we treat them as
# OPTIONAL: if only optional inputs fail, DON'T hard-fail the whole fetch — emit
# a summary flagging natural-mode so the config step disables water use.
_OPTIONAL_PREFIXES = ("waterUse/",)


def is_optional(rel: str) -> bool:
    """True if `rel` is an anthropogenic-water-use input (skippable in natural mode)."""
    return any(rel.startswith(p) for p in _OPTIONAL_PREFIXES)


def build_manifest(ic_year=None):
    """Relative paths (under global_30min/) of every input a regional run reads."""
    rel = [
        "routing/ldd_and_cell_area/lddsound_30min.nc",
        "routing/ldd_and_cell_area/cellarea30min.nc",
        "routing/channel_properties/bankfull_width.nc",
        "routing/channel_properties/bankfull_depth.nc",
        "routing/channel_properties/channel_gradient.nc",
        "routing/kc_surface_water/cropCoefficientForOpenWater.nc",
        "routing/surface_water_bodies/waterBodies30min.nc",
        "landSurface/topography/topography_parameters_30_arcmin_october_2015.nc",
        "landSurface/soil/soilProperties.nc",
        "groundwater/properties/groundwaterProperties.nc",
        "groundwater/aquifer_thickness_estimate/thickness_30min.nc",
        "waterUse/irrigation/irrigated_areas/irrigationArea30ArcMin.nc",
        "waterUse/irrigation/irrigation_efficiency/efficiency.nc",
        "waterUse/waterDemand/domestic_water_demand_version_october_2014.nc",
        "waterUse/waterDemand/industrial_water_demand_version_october_2014.nc",
        "waterUse/waterDemand/livestock_water_demand_1960-2012.nc",
        "waterUse/desalination/desalination_water_use_version_october_2014.nc",
        "waterUse/abstraction_zones/abstraction_zones_30min_30min.nc",
        "waterUse/abstraction_zones/abstraction_zones_60min_30min.nc",
        "waterUse/groundwater_pumping_capacity/regional_abstraction_limit.nc",
        "waterUse/source_partitioning/surface_water_fraction_for_irrigation/AEI_SWFRAC.nc",
        "waterUse/source_partitioning/surface_water_fraction_for_irrigation/AEI_QUAL.nc",
        "waterUse/source_partitioning/surface_water_fraction_for_non_irrigation/max_city_sw_fraction.nc",
    ]

    rel += [f"routing/channel_properties/dzRel{lv:04d}.nc" for lv in DZREL_LEVELS]

    for cover, (kc_tag, props) in _LANDCOVER.items():
        rel.append(f"landSurface/landCover/{cover}/{props}")
        rel.append(f"landSurface/landCover/{cover}/"
                   f"Global_CropCoefficientKc-{kc_tag}_30min.nc")
    for cover, tag in (("naturalTall", "Forest"), ("naturalShort", "Grassland")):
        rel.append(f"landSurface/landCover/{cover}/interceptCapInput{tag}366days.nc")
        rel.append(f"landSurface/landCover/{cover}/coverFractionInput{tag}366days.nc")

    if ic_year:
        ic_dir = f"initialConditions/non-natural/consistent_run_201903XX/{ic_year}"
        stamp = f"{ic_year}-12-31"
        for state in _IC_COVER_STATES:
            for cover in _IC_COVERS:
                rel.append(f"{ic_dir}/{state}_{cover}_{stamp}.nc")
        for state in _IC_SCALARS:
            rel.append(f"{ic_dir}/{state}_{stamp}.nc")

    return rel


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_inputs(bbox, local_dir, year_start, year_end, ic_year):
    errors = []

    if nc is None:
        errors.append("netCDF4 is required (with OPeNDAP/DAP support)")

    lon_min, lat_min, lon_max, lat_max = bbox
    if lon_min >= lon_max:
        errors.append(f"bbox lon_min ({lon_min}) must be < lon_max ({lon_max})")
    if lat_min >= lat_max:
        errors.append(f"bbox lat_min ({lat_min}) must be < lat_max ({lat_max})")
    if not (-90 <= lat_min < lat_max <= 90):
        errors.append(f"bbox latitudes out of range: {lat_min}..{lat_max}")
    if not (-180 <= lon_min < lon_max <= 360):
        errors.append(f"bbox longitudes out of range: {lon_min}..{lon_max}")

    if year_start > year_end:
        errors.append(f"year-start {year_start} > year-end {year_end}")
    if ic_year and ic_year >= year_start:
        errors.append(
            f"ic-year {ic_year} must precede year-start {year_start}: the "
            f"initial state is dated 31 Dec of ic-year"
        )

    if errors:
        for e in errors:
            logger.error(e)
        raise ValueError(f"Input validation failed: {len(errors)} error(s)")

    os.makedirs(local_dir, exist_ok=True)
    logger.info("Input validation passed.")
    return True


def validate_outputs(local_dir, expected_rel, bbox):
    """Every manifest entry must exist locally, open, and cover the bbox."""
    missing, bad = [], []

    for rel in expected_rel:
        path = os.path.join(local_dir, "global_30min", rel)
        if not os.path.exists(path):
            missing.append(rel)
            continue
        # A file written moments ago by another thread can transiently fail to
        # open under HDF5 file locking; retry once before condemning it.
        err = None
        for attempt in range(2):
            try:
                with nc.Dataset(path, "r") as ds:
                    lat_name = _coord_name(ds, ("lat", "latitude", "y"))
                    lon_name = _coord_name(ds, ("lon", "longitude", "x"))
                    if lat_name is None or lon_name is None:
                        err = "no lat/lon coordinate"
                        break
                    nlat = ds.variables[lat_name].size
                    nlon = ds.variables[lon_name].size
                    if nlat == 0 or nlon == 0:
                        err = f"empty grid ({nlat}x{nlon}) -- bbox missed the data"
                    else:
                        err = None
                break
            except Exception as e:
                err = str(e)
                time.sleep(1.0)
        if err:
            bad.append(f"{rel}: {err}")

    # Optional (anthropogenic water-use) inputs are allowed to be absent —
    # a natural-mode run doesn't read them. Only required gaps are fatal.
    missing_req = [m for m in missing if not is_optional(m)]
    bad_req = [b for b in bad if not is_optional(b.split(":", 1)[0])]
    missing_opt = [m for m in missing if is_optional(m)]
    bad_opt = [b for b in bad if is_optional(b.split(":", 1)[0])]

    for m in missing_req:
        logger.error(f"MISSING {m}")
    for b in bad_req:
        logger.error(f"BAD     {b}")
    for m in missing_opt:
        logger.warning(f"missing optional (natural-mode OK): {m}")
    for b in bad_opt:
        logger.warning(f"bad optional (natural-mode OK): {b}")

    if missing_req or bad_req:
        raise ValueError(
            f"Output validation failed: {len(missing_req)} required missing, "
            f"{len(bad_req)} required bad"
        )

    n_ok = len(expected_rel) - len(missing_opt) - len(bad_opt)
    logger.info(f"Output validation passed: {n_ok}/{len(expected_rel)} files present "
                f"({len(missing_opt) + len(bad_opt)} optional water-use skipped), "
                f"all sliced to bbox {bbox}.")
    return True


# ---------------------------------------------------------------------------
# Subsetting
# ---------------------------------------------------------------------------

def _coord_name(ds, candidates):
    for c in candidates:
        if c in ds.variables:
            return c
    return None


def _slice_for(values, lo, hi):
    """Contiguous index slice of cell centres inside [lo, hi], axis-order agnostic."""
    vals = np.asarray(values, dtype=float)
    keep = np.where((vals >= lo) & (vals <= hi))[0]
    if keep.size == 0:
        raise ValueError(f"bbox [{lo}, {hi}] selects no cells from axis "
                         f"spanning {vals.min()}..{vals.max()}")
    return slice(int(keep[0]), int(keep[-1]) + 1)


def subset_one(url, dest, bbox, force=False):
    """Copy one OPeNDAP file to `dest`, sliced to bbox on its lat/lon axes."""
    if os.path.exists(dest) and not force:
        # Open twice before condemning: under concurrency HDF5 file locking can
        # make a perfectly good local file fail to open once. Deleting on the
        # first failure throws away a valid ~5 MB download and refetches it.
        for attempt in range(2):
            try:
                with nc.Dataset(dest, "r"):
                    return "cached"
            except Exception:
                time.sleep(1.0)
        os.remove(dest)  # genuinely corrupt / partial download; refetch

    lon_min, lat_min, lon_max, lat_max = bbox
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".part"

    with nc.Dataset(url, "r") as src:
        lat_name = _coord_name(src, ("lat", "latitude", "y"))
        lon_name = _coord_name(src, ("lon", "longitude", "x"))
        if lat_name is None or lon_name is None:
            raise ValueError(f"no lat/lon coordinate in {url}")

        lat_sl = _slice_for(src.variables[lat_name][:], lat_min, lat_max)
        lon_sl = _slice_for(src.variables[lon_name][:], lon_min, lon_max)
        lat_dim = src.variables[lat_name].dimensions[0]
        lon_dim = src.variables[lon_name].dimensions[0]
        slices = {lat_dim: lat_sl, lon_dim: lon_sl}

        with nc.Dataset(tmp, "w", format="NETCDF4") as dst:
            for name, dim in src.dimensions.items():
                if name in slices:
                    size = slices[name].stop - slices[name].start
                else:
                    size = len(dim)
                dst.createDimension(name, None if dim.isunlimited() else size)

            for name, var in src.variables.items():
                fill = getattr(var, "_FillValue", None)
                out = dst.createVariable(
                    name, var.dtype, var.dimensions,
                    fill_value=fill, zlib=True, complevel=4,
                )
                for attr in var.ncattrs():
                    if attr != "_FillValue":
                        out.setncattr(attr, var.getncattr(attr))
                idx = tuple(slices.get(d, slice(None)) for d in var.dimensions)
                out[...] = var[idx]

            for attr in src.ncattrs():
                # _NCProperties is reserved and rejected by the NetCDF4 library
                if attr != "_NCProperties":
                    dst.setncattr(attr, src.getncattr(attr))
            dst.subset_bbox = f"lon {lon_min}..{lon_max}, lat {lat_min}..{lat_max}"
            dst.subset_source = url

    os.replace(tmp, dest)
    return "ok"


# ---------------------------------------------------------------------------
# Main process
# ---------------------------------------------------------------------------

def process(bbox, local_dir, manifest, base_url, workers=4, force=False,
            retries=3):
    logger.info(f"Fetching {len(manifest)} files into {local_dir} (bbox={bbox})")
    results = {}

    def _one(rel):
        url = f"{base_url}/global_30min/{rel}"
        dest = os.path.join(local_dir, "global_30min", rel)
        last = None
        for attempt in range(retries):
            try:
                return rel, subset_one(url, dest, bbox, force=force)
            except Exception as e:          # OPeNDAP is flaky under concurrency
                last = e
                time.sleep(2.0 * (attempt + 1))
        return rel, f"FAIL {last}"

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_one, rel) for rel in manifest]
        for i, fut in enumerate(as_completed(futures), 1):
            rel, status = fut.result()
            results[rel] = status
            logger.info(f"[{i}/{len(manifest)}] {status:<7} {os.path.basename(rel)}")

    failed = {r: s for r, s in results.items() if str(s).startswith("FAIL")}
    failed_required = {r: s for r, s in failed.items() if not is_optional(r)}
    failed_optional = {r: s for r, s in failed.items() if is_optional(r)}

    # Required-input failure is fatal — the model cannot run without them.
    if failed_required:
        for r, s in failed_required.items():
            logger.error(f"REQUIRED {r}: {s}")
        raise RuntimeError(
            f"{len(failed_required)} of {len(manifest)} REQUIRED files failed to fetch")

    # Optional (anthropogenic water-use) failures degrade gracefully: warn,
    # recommend natural mode, and let the run proceed.
    if failed_optional:
        for r, s in failed_optional.items():
            logger.warning(f"OPTIONAL unavailable (natural-mode degrade): {r}: {s}")
        logger.warning(
            f"{len(failed_optional)} anthropogenic water-use input(s) unavailable — "
            f"proceeding in NATURAL mode (water use OFF). "
            f"The config step MUST disable water use for these inputs.")

    return {"results": results,
            "missing_optional": sorted(failed_optional.keys()),
            "natural_mode_recommended": bool(failed_optional)}


def main():
    parser = argparse.ArgumentParser(
        description="Fetch a bbox subset of the global_30min PCR-GLOBWB inputs"
    )
    parser.add_argument("--bbox", nargs=4, type=float, required=True,
                        metavar=("LON_MIN", "LAT_MIN", "LON_MAX", "LAT_MAX"),
                        help="Cell-centre bounding box of the clone")
    parser.add_argument("--local-dir", required=True,
                        help="Destination; global_30min/ is created beneath it")
    parser.add_argument("--year-start", type=int, required=True)
    parser.add_argument("--year-end", type=int, required=True)
    parser.add_argument("--ic-year", type=int, default=None,
                        help="Fetch the non-natural initial state of 31 Dec YYYY")
    parser.add_argument("--workers", type=int, default=1,
                        help="OPeNDAP is rate-limited/flaky under concurrency; "
                             "default 1 (serial). Capped by PCRGLOBWB_FETCH_MAX_WORKERS.")
    parser.add_argument("--force", action="store_true",
                        help="Refetch files that already exist locally")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)

    args = parser.parse_args()
    bbox = tuple(args.bbox)

    validate_inputs(bbox, args.local_dir, args.year_start, args.year_end,
                    args.ic_year)
    manifest = build_manifest(ic_year=args.ic_year)
    # HARD-CAP concurrency: the 4tu.nl OPeNDAP server rate-limits/drops requests
    # under parallel load (2026-07-13: verify_1 with --workers 2 saw 17/97 REQUIRED
    # files transiently fail). Serial (workers=1) trades speed for reliability and
    # the resumable-skip loop keeps re-runs cheap. Clamp overrides ANY --workers the
    # caller passes; override only via env if a mirror can take the load.
    _wmax = max(1, int(os.environ.get("PCRGLOBWB_FETCH_MAX_WORKERS", "1")))
    _workers = min(args.workers, _wmax)
    if _workers != args.workers:
        logger.warning(f"clamping fetch workers {args.workers} -> {_workers} "
                       f"(OPeNDAP concurrency limit; set PCRGLOBWB_FETCH_MAX_WORKERS to raise)")
    summary = process(bbox, args.local_dir, manifest, args.base_url,
                      workers=_workers, force=args.force)
    validate_outputs(args.local_dir, manifest, bbox)

    # Persist a machine-readable summary so the config/run step knows whether
    # to run in natural mode (water use OFF). Written whether or not anything
    # was skipped, so downstream can always rely on its presence.
    summary_path = os.path.join(args.local_dir, "fetch_summary.json")
    try:
        with open(summary_path, "w") as fh:
            json.dump({
                "natural_mode_recommended": summary.get("natural_mode_recommended", False),
                "missing_optional": summary.get("missing_optional", []),
                "n_manifest": len(manifest),
            }, fh, indent=2)
        logger.info(f"Wrote fetch summary -> {summary_path}")
    except Exception as e:                                      # noqa: BLE001
        logger.warning(f"could not write fetch_summary.json: {e}")

    if summary.get("natural_mode_recommended"):
        logger.warning(
            "NATURAL MODE RECOMMENDED: anthropogenic water-use inputs were "
            "unavailable. Set the PCR-GLOBWB config to disable water use "
            "(limitAbstractionToLocalRunoff / offlineNaturalRun / water-use OFF) "
            "before running; do NOT reference the missing waterUse/ files.")


if __name__ == "__main__":
    main()
