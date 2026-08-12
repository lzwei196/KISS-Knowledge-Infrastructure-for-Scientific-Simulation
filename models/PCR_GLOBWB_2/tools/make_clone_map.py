#!/usr/bin/env python3
"""
PCR-GLOBWB 2 Clone / Landmask Builder
=====================================
Builds the two PCRaster boundary-condition maps a regional PCR-GLOBWB run
needs -- the ``clone`` (grid definition: rows, cols, cellsize, upper-left
corner) and the ``landmask`` (which cells are computed) -- directly from the
model's OWN local drainage direction network (LDD), so that the modelled
catchment is guaranteed to be the set of cells that actually drain to the
gauge on the grid the model routes on.

Pipeline stage: s1 (Clone / Landmask)
Pattern: validate_inputs -> process -> validate_outputs

Why trace the LDD instead of using a shapefile?
-----------------------------------------------
PCR-GLOBWB routes water on ``lddsound_30min.nc``. A basin polygon digitised
from a different DEM will disagree with that LDD along the divide, and the
discharge at the gauge cell is the accumulation of exactly the LDD-upstream
cells -- not of the polygon. Tracing the model's own LDD makes the simulated
contributing area directly comparable with the gauge's reported drainage area,
which is the only cheap, decisive check that the gauge was snapped to the
right cell (see ``validate_outputs``).

Gauge snapping
--------------
A reported station lon/lat rarely falls on the 30 arcmin cell that carries the
river. ``--snap-search N`` searches the (2N+1)^2 neighbourhood and selects the
cell whose LDD-traced upstream area best matches ``--target-area-km2``. At
Songhua/Harbin the reported (45.75, 126.60) snaps to cell centre
(45.75, 126.25): 391,310 km2 traced vs 389,769 km2 reported (+0.40%).

Corner alignment (hazard: clone_corner_misalignment)
----------------------------------------------------
The clone's upper-left corner is derived from the LDD's own cell centres
(``xUL = lon_centre_min - cellsize/2``), so it lands exactly on the global
grid's corner lattice. A clone whose corners are offset by a fraction of a
cell makes every subsequently-read input map resample by half a cell, which
PCR-GLOBWB does silently.

Outputs
-------
  {out_dir}/{prefix}.clone.map      PCRaster boolean, TRUE over the whole extent
  {out_dir}/{prefix}.landmask.map   PCRaster boolean, TRUE on catchment cells
  {out_dir}/{prefix}.clone.json     machine-readable metadata consumed by
                                    downstream stages (s1b, s2, s7):
                                      rows, cols, cellsize, xUL, yUL, xLR, yLR
                                      gauge_row, gauge_col (GLOBAL grid indices)
                                      gauge_cell_lat, gauge_cell_lon
                                      catchment_ncells, catchment_area_km2
                                      clone_map, landmask_map (absolute paths)

Must be run under the PCRaster interpreter (``pcrglobwb_python3``).
"""

import os
import sys
import json
import argparse
import logging
from collections import deque

import numpy as np

try:
    import netCDF4 as nc
except ImportError:  # pragma: no cover
    nc = None

try:
    import pcraster as pcr
except ImportError:  # pragma: no cover
    pcr = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


DEFAULT_LDD_NC = (
    "https://opendap.4tu.nl/thredds/dodsC/data2/pcrglobwb/version_2019_11_beta/"
    "pcrglobwb2_input/global_30min/routing/ldd_and_cell_area/lddsound_30min.nc"
)
DEFAULT_CELLAREA_NC = (
    "https://opendap.4tu.nl/thredds/dodsC/data2/pcrglobwb/version_2019_11_beta/"
    "pcrglobwb2_input/global_30min/routing/ldd_and_cell_area/cellarea30min.nc"
)

# PCRaster LDD codes are the numeric keypad: 5 is a pit, and every other code
# points at the neighbour in that keypad direction. Rows increase SOUTHWARD
# (the NetCDF lat axis is descending), so "north" is row-1.
LDD_OFFSETS = {
    1: (+1, -1), 2: (+1, 0), 3: (+1, +1),
    4: (0, -1), 5: (0, 0), 6: (0, +1),
    7: (-1, -1), 8: (-1, 0), 9: (-1, +1),
}
LDD_PIT = 5


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_inputs(gauge_lat, gauge_lon, target_area_km2, cellsize,
                    buffer_cells, snap_search):
    errors = []

    if nc is None:
        errors.append("netCDF4 is required to read the LDD")
    if pcr is None:
        errors.append(
            "pcraster is required to write .map files -- run this tool under "
            "the pcrglobwb_python3 interpreter"
        )
    if not (-90.0 <= gauge_lat <= 90.0):
        errors.append(f"Invalid gauge latitude: {gauge_lat}")
    if not (-180.0 <= gauge_lon <= 360.0):
        errors.append(f"Invalid gauge longitude: {gauge_lon}")
    if target_area_km2 is not None and target_area_km2 <= 0:
        errors.append(f"target-area-km2 must be positive, got {target_area_km2}")
    if cellsize <= 0:
        errors.append(f"cellsize must be positive, got {cellsize}")
    if buffer_cells < 0:
        errors.append(f"buffer-cells must be >= 0, got {buffer_cells}")
    if snap_search < 0:
        errors.append(f"snap-search must be >= 0, got {snap_search}")

    if errors:
        for e in errors:
            logger.error(e)
        raise ValueError(f"Input validation failed: {len(errors)} error(s)")

    logger.info("Input validation passed.")
    return True


def validate_outputs(meta, target_area_km2, area_tolerance_pct):
    """Fail loudly when the traced catchment does not match the gauge.

    A wrong snap is the single most damaging silent error in a regional
    PCR-GLOBWB setup: the model runs, writes discharge, and scores against a
    gauge that drains a different area. The reported-vs-traced area check is
    the cheapest way to catch it.
    """
    errors = []

    for key in ("clone_map", "landmask_map"):
        if not os.path.exists(meta[key]):
            errors.append(f"{key} was not written: {meta[key]}")

    if meta["catchment_ncells"] < 1:
        errors.append("Traced catchment is empty -- gauge cell has no upstream cells")

    if meta["rows"] < 1 or meta["cols"] < 1:
        errors.append(f"Degenerate clone extent: {meta['rows']}x{meta['cols']}")

    # corner alignment: xUL/yUL must sit exactly on the global corner lattice
    cs = meta["cellsize"]
    for name, val, origin in (("xUL", meta["xUL"], -180.0), ("yUL", meta["yUL"], 90.0)):
        offset = abs((val - origin) / cs)
        if abs(offset - round(offset)) > 1e-6:
            errors.append(
                f"hazard clone_corner_misalignment: {name}={val} is not an "
                f"integer number of cells from {origin}"
            )

    if target_area_km2:
        err_pct = 100.0 * (meta["catchment_area_km2"] - target_area_km2) / target_area_km2
        meta["area_error_pct"] = round(err_pct, 3)
        msg = (f"Traced upstream area {meta['catchment_area_km2']:.0f} km2 vs "
               f"reported {target_area_km2:.0f} km2 ({err_pct:+.2f}%)")
        if abs(err_pct) > area_tolerance_pct:
            errors.append(
                f"{msg} -- exceeds +/-{area_tolerance_pct}%. The gauge probably "
                f"snapped to the wrong cell; widen --snap-search or check the "
                f"reported coordinates."
            )
        else:
            logger.info(msg)

    for e in errors:
        logger.error(e)
    if errors:
        raise ValueError(f"Output validation failed: {len(errors)} error(s)")

    logger.info("Output validation passed.")
    return True


# ---------------------------------------------------------------------------
# LDD reading and tracing
# ---------------------------------------------------------------------------

def _pick_grid_var(ds, hint):
    """Return the 2-D data variable of a PCR-GLOBWB input map."""
    coords = {"lat", "latitude", "lon", "longitude", "time", "x", "y"}
    named = [v for v in ds.variables if hint in v.lower() and v.lower() not in coords]
    if named:
        return named[0]
    twod = [v for v in ds.variables
            if v.lower() not in coords and ds.variables[v].ndim == 2]
    if not twod:
        raise KeyError(f"No 2-D grid variable found; have {list(ds.variables)}")
    return twod[0]


def read_ldd(ldd_nc, cellarea_nc):
    """Read the global LDD and the per-cell area (m2).

    Returns (ldd, area_km2, lats, lons) with lats DESCENDING, i.e. row 0 is the
    northernmost row -- the layout every PCR-GLOBWB input map uses.
    """
    logger.info(f"Reading LDD from {ldd_nc}")
    with nc.Dataset(ldd_nc, "r") as ds:
        vname = _pick_grid_var(ds, "ldd")
        ldd = np.asarray(ds.variables[vname][:]).astype(np.int16)
        lats = np.asarray(ds.variables["lat"][:], dtype=float)
        lons = np.asarray(ds.variables["lon"][:], dtype=float)
    if lats[0] < lats[-1]:
        raise ValueError(
            "LDD latitude axis is ascending; PCR-GLOBWB input maps are stored "
            "north-to-south. Refusing to guess the row order."
        )

    logger.info(f"Reading cell area from {cellarea_nc}")
    with nc.Dataset(cellarea_nc, "r") as ds:
        aname = _pick_grid_var(ds, "cellarea")
        area_m2 = np.asarray(ds.variables[aname][:], dtype=float)
    if area_m2.shape != ldd.shape:
        raise ValueError(f"cellarea shape {area_m2.shape} != ldd shape {ldd.shape}")

    logger.info(f"LDD grid: {ldd.shape[0]} rows x {ldd.shape[1]} cols, "
                f"lat {lats[0]}..{lats[-1]}, lon {lons[0]}..{lons[-1]}")
    return ldd, area_m2 / 1.0e6, lats, lons


def build_upstream_index(ldd):
    """Map every cell to the list of cells that flow INTO it."""
    nrow, ncol = ldd.shape
    children = {}
    for r in range(nrow):
        row = ldd[r]
        for c in range(ncol):
            code = int(row[c])
            if code not in LDD_OFFSETS or code == LDD_PIT:
                continue
            dr, dc = LDD_OFFSETS[code]
            rr, cc = r + dr, c + dc
            if 0 <= rr < nrow and 0 <= cc < ncol:
                children.setdefault((rr, cc), []).append((r, c))
    return children


def trace_upstream(children, outlet):
    """Every cell draining to `outlet`, inclusive, by breadth-first search."""
    seen = {outlet}
    queue = deque([outlet])
    while queue:
        cell = queue.popleft()
        for up in children.get(cell, ()):
            if up not in seen:
                seen.add(up)
                queue.append(up)
    return seen


def snap_gauge(children, area_km2, lats, lons, gauge_lat, gauge_lon,
               target_area_km2, snap_search):
    """Pick the cell in the search window whose traced area best matches.

    With no target area, the reported coordinates are trusted as-is.
    """
    r0 = int(np.argmin(np.abs(lats - gauge_lat)))
    c0 = int(np.argmin(np.abs(lons - gauge_lon)))

    if not target_area_km2 or snap_search == 0:
        cells = trace_upstream(children, (r0, c0))
        logger.info(f"No snapping (target area not given): using cell "
                    f"({lats[r0]}, {lons[c0]})")
        return (r0, c0), cells

    nrow, ncol = area_km2.shape
    # RIVER-IDENTITY GUARD (hazard: wrong_river_snap).
    # Matching on area ALONE is not sufficient to identify a gauge cell: a
    # neighbouring tributary can carry a near-identical upstream area and win
    # the area contest while being a completely different river. Observed at
    # Wangjiaba (Huai, 2026-07-19): reported (32.4275, 115.595), target
    # 30630 km2. With --snap-search 2 the area-only rule selected
    # (33.25, 115.75) at 30884 km2 (+0.83%) -- but that cell is on the
    # Shaying/Ying tributary, and the Huai mainstem gauges UPSTREAM of
    # Wangjiaba (Xixian, Huaibin) are NOT in its catchment. The correct
    # mainstem cell (32.25, 115.75) carries 44414 km2 (+45%).
    #
    # A gauge cell must lie on the flow path of the reported location, so the
    # cell CONTAINING the reported coordinates must be in the candidate's
    # upstream catchment (or be the candidate itself). That is a cheap, purely
    # topological test which the area contest cannot fake.
    candidates = []
    for dr in range(-snap_search, snap_search + 1):
        for dc in range(-snap_search, snap_search + 1):
            r, c = r0 + dr, c0 + dc
            if not (0 <= r < nrow and 0 <= c < ncol):
                continue
            cells = trace_upstream(children, (r, c))
            a = float(sum(area_km2[rr, cc] for rr, cc in cells))
            err = abs(a - target_area_km2)
            on_path = (r0, c0) in cells
            dist = max(abs(dr), abs(dc))
            logger.info(f"  candidate ({lats[r]:.2f}, {lons[c]:.2f}): "
                        f"{len(cells)} cells, {a:.0f} km2 "
                        f"({100.0 * (a - target_area_km2) / target_area_km2:+.2f}%)"
                        f"{'' if on_path else '  [OFF reported flow path]'}")
            candidates.append((err, dist, (r, c), cells, a, on_path))

    if not candidates:
        raise ValueError("Snap window fell entirely outside the LDD grid")

    on_path = [k for k in candidates if k[5]]
    if on_path:
        # tie-break on distance so the nearest of several equally good area
        # matches wins rather than an arbitrary far one
        _, _, cell, cells, a, _ = min(on_path, key=lambda k: (k[0], k[1]))
        guard = "PASS"
    else:
        _, _, cell, cells, a, _ = min(candidates, key=lambda k: (k[0], k[1]))
        guard = "FAIL"
        logger.warning(
            "RIVER-IDENTITY GUARD FAILED: no candidate in the snap window has "
            f"the reported location ({gauge_lat}, {gauge_lon}) on its flow "
            "path. The selected cell may be on a DIFFERENT river that happens "
            "to carry a similar upstream area. Verify against a known "
            "upstream gauge before trusting the discharge, or reduce "
            "--snap-search.")

    best_any = min(candidates, key=lambda k: (k[0], k[1]))
    if guard == "PASS" and best_any[2] != cell:
        logger.warning(
            f"Area-only snapping would have chosen ({lats[best_any[2][0]]:.2f}, "
            f"{lons[best_any[2][1]]:.2f}) at {best_any[4]:.0f} km2, but that "
            "cell is OFF the reported flow path (different river); using the "
            f"on-path cell ({lats[cell[0]]:.2f}, {lons[cell[1]]:.2f}) at "
            f"{a:.0f} km2 instead.")

    logger.info(f"Snapped gauge ({gauge_lat}, {gauge_lon}) -> cell centre "
                f"({lats[cell[0]]}, {lons[cell[1]]}): {a:.0f} km2 over "
                f"{len(cells)} cells [river-identity guard: {guard}]")
    snap_gauge.last_guard = guard
    return cell, cells


# ---------------------------------------------------------------------------
# Map writing
# ---------------------------------------------------------------------------

def write_maps(out_dir, prefix, mask, rows, cols, cellsize, xUL, yUL):
    """Write the boolean clone (all TRUE) and landmask (catchment TRUE)."""
    os.makedirs(out_dir, exist_ok=True)
    clone_path = os.path.join(out_dir, f"{prefix}.clone.map")
    landmask_path = os.path.join(out_dir, f"{prefix}.landmask.map")

    pcr.setclone(rows, cols, cellsize, xUL, yUL)

    ones = np.ones((rows, cols), dtype=np.uint8)
    pcr.report(pcr.numpy2pcr(pcr.Boolean, ones, 255), clone_path)
    pcr.report(pcr.numpy2pcr(pcr.Boolean, mask.astype(np.uint8), 255), landmask_path)

    logger.info(f"Wrote {clone_path} ({rows}x{cols} @ {cellsize} deg, UL {xUL},{yUL})")
    logger.info(f"Wrote {landmask_path} ({int(mask.sum())} TRUE cells)")
    return os.path.abspath(clone_path), os.path.abspath(landmask_path)


# ---------------------------------------------------------------------------
# Main process
# ---------------------------------------------------------------------------

def process(out_dir, prefix, gauge_lat, gauge_lon, target_area_km2,
            cellsize, buffer_cells, snap_search, ldd_nc, cellarea_nc):
    ldd, area_km2, lats, lons = read_ldd(ldd_nc, cellarea_nc)

    if abs(float(lats[0] - lats[1])) - cellsize > 1e-9:
        raise ValueError(
            f"--cellsize {cellsize} does not match the LDD grid spacing "
            f"{abs(float(lats[0] - lats[1]))}"
        )

    children = build_upstream_index(ldd)
    (grow, gcol), cells = snap_gauge(children, area_km2, lats, lons,
                                     gauge_lat, gauge_lon, target_area_km2,
                                     snap_search)

    rr = np.array([c[0] for c in sorted(cells)])
    cc = np.array([c[1] for c in sorted(cells)])
    r_min = max(int(rr.min()) - buffer_cells, 0)
    r_max = min(int(rr.max()) + buffer_cells, ldd.shape[0] - 1)
    c_min = max(int(cc.min()) - buffer_cells, 0)
    c_max = min(int(cc.max()) + buffer_cells, ldd.shape[1] - 1)

    rows = r_max - r_min + 1
    cols = c_max - c_min + 1

    # Corners come straight off the LDD's own cell centres, so they inherit the
    # global grid's corner lattice exactly.
    xUL = float(lons[c_min]) - cellsize / 2.0
    yUL = float(lats[r_min]) + cellsize / 2.0
    xLR = xUL + cols * cellsize
    yLR = yUL - rows * cellsize

    mask = np.zeros((rows, cols), dtype=bool)
    for r, c in cells:
        mask[r - r_min, c - c_min] = True

    clone_path, landmask_path = write_maps(out_dir, prefix, mask, rows, cols,
                                           cellsize, xUL, yUL)

    meta = {
        "cellsize": cellsize,
        "ldd_source": ldd_nc,
        # "PASS" = the reported lon/lat lies on the snapped cell's flow path,
        # so the snap stayed on the same river. "FAIL" = it did not; the area
        # match may be a different river (see wrong_river_snap in snap_gauge).
        "river_identity_guard": getattr(snap_gauge, "last_guard", "NOT_APPLIED"),
        "gauge_row": int(grow),
        "gauge_col": int(gcol),
        "gauge_cell_lat": float(lats[grow]),
        "gauge_cell_lon": float(lons[gcol]),
        "catchment_ncells": int(len(cells)),
        "catchment_area_km2": round(float(sum(area_km2[r, c] for r, c in cells)), 1),
        "xUL": xUL, "yUL": yUL, "xLR": xLR, "yLR": yLR,
        "rows": rows, "cols": cols,
        "lat_min_centre": float(lats[r_max]),
        "lat_max_centre": float(lats[r_min]),
        "lon_min_centre": float(lons[c_min]),
        "lon_max_centre": float(lons[c_max]),
        "clone_map": clone_path,
        "landmask_map": landmask_path,
    }
    return meta


def main():
    parser = argparse.ArgumentParser(
        description="Build PCR-GLOBWB clone + landmask by tracing the model's LDD"
    )
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--prefix", required=True,
                        help="Basename for the .clone.map/.landmask.map/.clone.json")
    parser.add_argument("--gauge-lat", type=float, required=True)
    parser.add_argument("--gauge-lon", type=float, required=True)
    parser.add_argument("--target-area-km2", type=float, default=None,
                        help="Reported drainage area; enables gauge snapping")
    parser.add_argument("--cellsize", type=float, default=0.5,
                        help="Grid spacing in degrees (0.5 for global_30min)")
    parser.add_argument("--buffer-cells", type=int, default=1,
                        help="Cells of padding around the traced catchment")
    parser.add_argument("--snap-search", type=int, default=1,
                        help="Half-width of the gauge snap window, in cells")
    parser.add_argument("--area-tolerance-pct", type=float, default=10.0,
                        help="Fail if |traced - reported| area exceeds this")
    parser.add_argument("--ldd-nc", default=DEFAULT_LDD_NC)
    parser.add_argument("--cellarea-nc", default=DEFAULT_CELLAREA_NC)

    args = parser.parse_args()

    validate_inputs(args.gauge_lat, args.gauge_lon, args.target_area_km2,
                    args.cellsize, args.buffer_cells, args.snap_search)

    meta = process(args.out_dir, args.prefix, args.gauge_lat, args.gauge_lon,
                   args.target_area_km2, args.cellsize, args.buffer_cells,
                   args.snap_search, args.ldd_nc, args.cellarea_nc)

    validate_outputs(meta, args.target_area_km2, args.area_tolerance_pct)

    meta_path = os.path.join(args.out_dir, f"{args.prefix}.clone.json")
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
    logger.info(f"Wrote {meta_path}")
    print(json.dumps(meta, indent=2))


if __name__ == "__main__":
    main()
