#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      hydat_to_sfincs_boundary
Stage:        s4_forcing
Description:  Build SFINCS river boundary conditions and observation points directly from
              an OBSERVED gauge network (HYDAT, Canada). Writes sfincs.src + sfincs.dis
              from a daily-discharge station, sfincs.obs from one or more water-level
              stations, and dumps the observed daily level series used for scoring.

Why this tool exists
--------------------
Before this tool the only river BC path in the KI was `cama_to_sfincs_boundary.py`
(CaMa-Flood -> SFINCS), i.e. a MODEL boundary. Validating SFINCS `point_zs` against a
stage gauge then had only two options, both invalid:
  * force SFINCS with the discharge measured AT the same gauge and score the level there
    -> circular (the reviewer audit of 2026-08-02 flagged exactly this), or
  * run pluvial-only -> no river signal at all.
Forcing the domain with the discharge measured at an UPSTREAM gauge and scoring the water
level at a DIFFERENT, downstream gauge is a genuine, non-circular hydrodynamic test: the
model must convert an inflow hydrograph into a stage through its own bathymetry, roughness
and momentum equations.

Inputs:
  --hydat_db:       HYDAT sqlite3 (default: /mnt/disk4/Hydat_sqlite3_20260116/Hydat.sqlite3)
  --grid_info:      grid_info.json from s1_domain (for the projection)
  --flow_station:   COMMA LIST of HYDAT station numbers whose DLY_FLOWS drive sfincs.src/.dis.
                    Include every unforced in-domain tributary (dt_v024).
  --obs_stations:   comma list of HYDAT station numbers to write into sfincs.obs
  --start_date/--end_date/--tref: simulation window; times in .dis are seconds since tref
  --topobathy_dir:  dir with sfincs.dep/sfincs.msk — used to snap the source onto the
                    LOWEST ACTIVE cells near the gauge (the channel), not the bank
  --n_src:          spread the inflow over N adjacent channel cells (default 1)
  --output_dir:     output directory

Outputs:
  - sfincs.src                      one "x y" row per SOURCE CELL; with a comma-list
                                    --flow_station the stations are CONCATENATED in CLI
                                    order, n_src cells per station.
  - sfincs.dis                      "t_seconds Q1 .. QN", t = seconds since tref.
                                    N = sum over stations of THAT station's n_src cells --
                                    NOT --n_src, and NOT the number of stations. Station k
                                    owns a contiguous block of n_src_cells[k] columns, each
                                    carrying Q_k / n_src_cells[k] m3/s, so columns are
                                    identical only WITHIN one station's block. The row sum
                                    is the total inflow sum_k Q_k for any grouping. The
                                    authoritative column mapping is written to
                                    hydat_boundary_summary.json as flow_stations[].n_src_cells
                                    and n_src_cells_total -- read it, never infer N.
  - sfincs.obs                      observation points ("x y name"), one per --obs_stations
  - obs_levels_<station>.csv        observed daily mean water level (date,level_m)
  - hydat_boundary_summary.json     the AUTHORITATIVE description of what was written,
                                    emitted by the writer at lines ~289-304 of this file:
                                      flow_stations[]  = one entry per --flow_station, in CLI
                                                         order, each carrying station_id,
                                                         station_name, lat/lon, datum, snap and
                                                         n_src_cells (that station's column
                                                         block width);
                                      n_src_cells_total = sum of those widths = the number of
                                                         discharge columns in sfincs.dis;
                                      flow_station      = back-compatible scalar key, the single
                                                         flow_stations[0] DICT when exactly one
                                                         station was forced, else null;
                                      obs_stations[]    = sfincs.obs points, with datum_name and
                                                         the obs_levels_<station>.csv path.
                                    Consumers must read flow_stations[]/n_src_cells_total for the
                                    sfincs.dis column mapping and never infer it from the count.

HYDAT layout traps handled here
-------------------------------
  * The sqlite3 lives on read-only media and the file is in WAL mode, so `mode=ro` alone
    fails — the connection string needs `immutable=1`.
  * DLY_FLOWS / DLY_LEVELS are MONTH-per-row with 31 wide columns (FLOW1..FLOW31 /
    LEVEL1..LEVEL31); non-existent days are NULL and must be skipped, not zero-filled.
  * Water levels are metres in the station's OWN vertical datum (STATIONS.DATUM_ID ->
    DATUM_LIST). Only a geodetic datum is directly comparable with a DEM; the datum name
    is written into the summary so the caller can decide (dag caveat "requires shared
    datum for zs").

Exit codes:
  0 — success, 1 — input error, 2 — processing error, 3 — output error
"""

import sys
import os
import json
import sqlite3
import logging
import argparse
import datetime as dtm
from pathlib import Path

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_HYDAT = "/mnt/disk4/Hydat_sqlite3_20260116/Hydat.sqlite3"


def connect_hydat(path):
    """Open HYDAT read-only. `immutable=1` is REQUIRED: the file is WAL-mode on read-only
    media, where plain `mode=ro` raises 'attempt to write a readonly database'."""
    return sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)


def parse_date(s):
    return dtm.datetime.strptime(s, "%Y-%m-%d")


def station_info(con, stn):
    row = con.execute(
        "SELECT STATION_NUMBER, STATION_NAME, LATITUDE, LONGITUDE, DRAINAGE_AREA_GROSS, DATUM_ID "
        "FROM STATIONS WHERE STATION_NUMBER=?", (stn,)).fetchone()
    if row is None:
        raise ValueError(f"HYDAT station not found: {stn}")
    datum = con.execute("SELECT DATUM_EN FROM DATUM_LIST WHERE DATUM_ID=?", (row[5],)).fetchone()
    return {
        "station_id": row[0], "station_name": row[1],
        "lat": row[2], "lon": row[3],
        "drainage_area_km2": row[4],
        "datum_id": row[5], "datum_name": datum[0] if datum else None,
    }


def daily_series(con, table, prefix, stn, d0, d1):
    """Read a HYDAT wide daily table into {date: value} for d0..d1 inclusive."""
    cols = ",".join(f"{prefix}{d}" for d in range(1, 32))
    out = {}
    for row in con.execute(
            f"SELECT YEAR,MONTH,{cols} FROM {table} WHERE STATION_NUMBER=? "
            "AND YEAR BETWEEN ? AND ?", (stn, d0.year, d1.year)):
        y, m = row[0], row[1]
        for d in range(1, 32):
            v = row[1 + d]
            if v is None:
                continue
            try:
                day = dtm.date(y, m, d)
            except ValueError:
                continue  # 31st of a 30-day month etc.
            if d0.date() <= day <= d1.date():
                out[day] = float(v)
    return out


def snap_source_cells(args, grid, lon, lat, n_cells):
    """Return (x, y) of the n lowest ACTIVE grid cells within --src_search_m of the gauge.

    A river gauge coordinate is on the BANK as often as in the channel. Injecting a
    10,000 m3/s point source into a bank cell builds an unphysical mound and can even land
    outside the active mask, where SFINCS silently discards the volume."""
    from pyproj import Transformer

    tr = Transformer.from_crs("EPSG:4326", f"EPSG:{grid['epsg']}", always_xy=True)
    xg, yg = tr.transform(lon, lat)

    x0, y0, dx, dy = grid["x0"], grid["y0"], grid["dx"], grid["dy"]
    mmax, nmax = grid["mmax"], grid["nmax"]

    if not args.topobathy_dir:
        return [(xg, yg)], {"snapped": False}

    # dt_v023: sfincs.dep/.msk are COMPRESSED (active cells only, Fortran order, row 0 =
    # south). np.fromfile(...).reshape(nmax, mmax) is wrong — go through the s2 reader.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "s2_topobathy"))
    from build_sfincs_topobathy import read_binary_map
    dep, msk = read_binary_map(args.topobathy_dir, nmax, mmax)
    dep = np.nan_to_num(dep, nan=9e9)

    # read_binary_map returns NORTH-up grids (row 0 = north), while y0 is the SOUTH edge.
    # np.floor, NOT int(): int() truncates toward zero, so a gauge west/south of the origin
    # would map to index 0 instead of a negative index and look like it was inside.
    col = int(np.floor((xg - x0) / dx))
    row_from_south = int(np.floor((yg - y0) / dy))
    row = nmax - 1 - row_from_south

    # A gauge outside the domain is the EXPECTED failure here — the whole premise of this
    # tool is forcing from an UPSTREAM gauge, which may well sit off the grid. Without this
    # check a negative row/col makes `min(nmax, row + rad + 1)` negative, so dep[r0:r1] is a
    # valid near-whole-grid slice rather than an empty one: the "No ACTIVE cell within ..."
    # guard never fires and the inflow is silently snapped to the lowest active cell
    # ANYWHERE in the domain.
    if not (0 <= col < mmax and 0 <= row < nmax):
        logger.error(
            "Flow gauge (%.4f, %.4f) -> projected (%.1f, %.1f) -> grid (row=%d, col=%d) "
            "falls OUTSIDE the domain (nmax=%d, mmax=%d; x0=%.1f, y0=%.1f, dx=%.1f, "
            "dy=%.1f). The discharge source must be injected inside the active grid — "
            "extend the s1 domain to include the gauge, or pick a gauge on the modelled "
            "reach.", lon, lat, xg, yg, row, col, nmax, mmax, x0, y0, dx, dy)
        sys.exit(2)

    rad = int(np.ceil(args.src_search_m / dx))

    r0, r1 = max(0, row - rad), min(nmax, row + rad + 1)
    c0, c1 = max(0, col - rad), min(mmax, col + rad + 1)
    sub_dep = dep[r0:r1, c0:c1]
    sub_msk = msk[r0:r1, c0:c1]
    cand = np.argwhere(sub_msk == 1)
    if len(cand) == 0:
        logger.warning("No ACTIVE cell within %.0f m of (%.4f,%.4f) — using the raw gauge "
                       "coordinate; SFINCS may discard this source.", args.src_search_m, lon, lat)
        return [(xg, yg)], {"snapped": False}

    order = np.argsort([sub_dep[r, c] for r, c in cand])
    picks = cand[order[:max(1, n_cells)]]
    pts = []
    for r, c in picks:
        gr, gc = r + r0, c + c0
        px = x0 + (gc + 0.5) * dx
        py = y0 + (nmax - 1 - gr + 0.5) * dy
        pts.append((float(px), float(py)))
    info = {
        "snapped": True,
        "gauge_xy": [float(xg), float(yg)],
        "bed_levels_m": [float(sub_dep[r, c]) for r, c in picks],
        "search_radius_m": args.src_search_m,
    }
    logger.info("Snapped source onto %d active cell(s), bed %s m",
                len(pts), [round(b, 2) for b in info["bed_levels_m"]])
    return pts, info


def process(args):
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    with open(args.grid_info) as f:
        grid = json.load(f)

    d0, d1 = parse_date(args.start_date), parse_date(args.end_date)
    tref = parse_date(args.tref) if args.tref else d0

    con = connect_hydat(args.hydat_db)
    summary = {"status": "success", "hydat_db": args.hydat_db,
               "tref": tref.strftime("%Y-%m-%d"), "files": {}}

    # ---------------- discharge boundary ----------------
    # --flow_station accepts a COMMA-SEPARATED LIST (dt_v024). A single upstream
    # gauge leaves every in-domain tributary unforced, which both misses water and
    # makes any downstream stage gauge a pure rating transform of the one inflow.
    # Adding the tributary as a second source is what makes a downstream target
    # informative — see tools/s9_validation/screen_obs_independence.py.
    flow_stations = [s.strip() for s in (args.flow_station or "").split(",") if s.strip()]
    if flow_stations:
        days = [d0.date() + dtm.timedelta(days=i) for i in range((d1.date() - d0.date()).days + 1)]
        sources = []   # one entry per flow station, in CLI order

        for stn in flow_stations:
            info = station_info(con, stn)
            q = daily_series(con, "DLY_FLOWS", "FLOW", stn, d0, d1)
            if not q:
                logger.error("HYDAT has no DLY_FLOWS for %s between %s and %s",
                             stn, args.start_date, args.end_date)
                sys.exit(2)

            # Fill interior gaps by linear interpolation on the daily axis, then anchor the
            # series at tstart and tstop so SFINCS never extrapolates.
            have = np.array([d in q for d in days])
            vals = np.array([q.get(d, np.nan) for d in days], dtype=float)
            n_gap = int((~have).sum())
            if n_gap:
                idx = np.arange(len(days))
                vals = np.interp(idx, idx[have], vals[have])
                logger.warning("%d of %d days missing in %s DLY_FLOWS — linearly interpolated",
                               n_gap, len(days), stn)

            pts, snap = snap_source_cells(args, grid, info["lon"], info["lat"], args.n_src)
            sources.append({"info": info, "vals": vals, "pts": pts,
                            "n_gap": n_gap, "snap": snap})

        all_pts = [p for s in sources for p in s["pts"]]
        n_pts_total = len(all_pts)

        src_path = output_dir / "sfincs.src"
        with open(src_path, "w") as f:
            for x, y in all_pts:
                f.write(f"{x:.2f} {y:.2f}\n")

        def _row(i):
            """Per-cell discharge for day index i, in sfincs.src column order."""
            out = []
            for s in sources:
                per = s["vals"][i] / len(s["pts"])
                out.extend(f"{per:.3f}" for _ in s["pts"])
            return " ".join(out)

        # sfincs.dis: "t_seconds Q1 .. Qn", t relative to tref and >= 0 (dt_010).
        # HYDAT values are DAILY MEANS, so they are stamped at the CENTRE of their day;
        # SFINCS interpolates linearly between rows, which preserves the daily mean.
        dis_path = output_dir / "sfincs.dis"
        with open(dis_path, "w") as f:
            t_first = (dtm.datetime.combine(days[0], dtm.time(0)) - tref).total_seconds()
            f.write(f"{t_first:.0f} " + _row(0) + "\n")
            for i, day in enumerate(days):
                t = (dtm.datetime.combine(day, dtm.time(12)) - tref).total_seconds()
                if t <= t_first:
                    continue
                f.write(f"{t:.0f} " + _row(i) + "\n")
            t_last = (dtm.datetime.combine(days[-1], dtm.time(23, 59)) - tref).total_seconds()
            f.write(f"{t_last:.0f} " + _row(len(days) - 1) + "\n")

        flow_meta = []
        for s in sources:
            info, vals = s["info"], s["vals"]
            logger.info("Discharge BC from HYDAT %s (%s): %d days, %.1f-%.1f m3/s over %d cell(s)",
                        info["station_id"], info["station_name"], len(days),
                        float(vals.min()), float(vals.max()), len(s["pts"]))
            flow_meta.append({**info, "n_days": len(days), "n_interpolated": s["n_gap"],
                              "q_min_m3s": float(vals.min()), "q_max_m3s": float(vals.max()),
                              "n_src_cells": len(s["pts"]), "snap": s["snap"]})

        summary["files"]["src_file"] = str(src_path)
        summary["files"]["dis_file"] = str(dis_path)
        summary["flow_stations"] = flow_meta
        summary["n_src_cells_total"] = n_pts_total
        # Back-compatible scalar key for single-station decks.
        summary["flow_station"] = flow_meta[0] if len(flow_meta) == 1 else None

    # ---------------- observation points ----------------
    obs_meta = []
    if args.obs_stations:
        from pyproj import Transformer
        tr = Transformer.from_crs("EPSG:4326", f"EPSG:{grid['epsg']}", always_xy=True)
        obs_path = output_dir / "sfincs.obs"
        with open(obs_path, "w") as f:
            for stn in [s.strip() for s in args.obs_stations.split(",") if s.strip()]:
                info = station_info(con, stn)
                x, y = tr.transform(info["lon"], info["lat"])
                inside = (grid["x0"] <= x <= grid["x0"] + grid["mmax"] * grid["dx"] and
                          grid["y0"] <= y <= grid["y0"] + grid["nmax"] * grid["dy"])
                if not inside:
                    logger.error("Observation station %s falls OUTSIDE the domain — SFINCS "
                                 "will not write a his record for it.", stn)
                    sys.exit(2)
                f.write(f"{x:.2f} {y:.2f} HYDAT_{stn}\n")

                lev = daily_series(con, "DLY_LEVELS", "LEVEL", stn, d0, d1)
                csv = output_dir / f"obs_levels_{stn}.csv"
                with open(csv, "w") as g:
                    g.write("date,level_m\n")
                    for d in sorted(lev):
                        g.write(f"{d.isoformat()},{lev[d]:.4f}\n")
                logger.info("Obs point %s (%s): %d daily levels, datum '%s'",
                            stn, info["station_name"], len(lev), info["datum_name"])
                obs_meta.append({**info, "x": float(x), "y": float(y),
                                 "n_levels": len(lev), "levels_csv": str(csv),
                                 "level_min_m": min(lev.values()) if lev else None,
                                 "level_max_m": max(lev.values()) if lev else None})
        summary["files"]["obs_file"] = str(obs_path)
    summary["obs_stations"] = obs_meta
    con.close()

    summary_path = output_dir / "hydat_boundary_summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(json.dumps(summary, indent=2, default=str))
    return str(summary_path)


def validate_inputs(args):
    errors = []
    if not Path(args.hydat_db).exists():
        errors.append(f"HYDAT sqlite not found: {args.hydat_db}")
    if not Path(args.grid_info).exists():
        errors.append(f"Grid info not found: {args.grid_info}")
    if not args.flow_station and not args.obs_stations:
        errors.append("Nothing to do: give --flow_station and/or --obs_stations")
    if args.topobathy_dir and not (Path(args.topobathy_dir) / "sfincs.dep").exists():
        errors.append(f"sfincs.dep not found in {args.topobathy_dir}")
    if errors:
        for e in errors:
            logger.error(e)
        sys.exit(1)
    logger.info("Input validation passed.")


def validate_outputs(summary_path):
    with open(summary_path) as f:
        summary = json.load(f)
    for key, path in summary.get("files", {}).items():
        p = Path(path)
        if not p.exists() or p.stat().st_size == 0:
            logger.error("Output missing or empty: %s (%s)", path, key)
            sys.exit(3)
    logger.info("Output validation passed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HYDAT gauge -> SFINCS boundary/observation files")
    parser.add_argument("--hydat_db", default=DEFAULT_HYDAT)
    parser.add_argument("--grid_info", required=True)
    parser.add_argument("--flow_station", default=None,
                        help="Comma list of HYDAT station numbers providing inflow hydrographs "
                             "(DLY_FLOWS). Give EVERY unforced in-domain tributary, not just the "
                             "upstream mainstem — a single inflow makes any downstream stage gauge "
                             "a rating transform of it (dt_v024).")
    parser.add_argument("--obs_stations", default=None,
                        help="Comma list of HYDAT station numbers for sfincs.obs (DLY_LEVELS)")
    parser.add_argument("--start_date", required=True)
    parser.add_argument("--end_date", required=True)
    parser.add_argument("--tref", default=None, help="SFINCS tref (default: --start_date)")
    parser.add_argument("--topobathy_dir", default=None)
    parser.add_argument("--n_src", type=int, default=1,
                        help="Spread the inflow evenly over the N lowest active cells")
    parser.add_argument("--src_search_m", type=float, default=600.0)
    parser.add_argument("--output_dir", required=True)
    args = parser.parse_args()

    logger.info(f"Running tool: {os.path.basename(__file__)}")
    validate_inputs(args)
    try:
        out = process(args)
    except SystemExit:
        raise
    except Exception as e:
        logger.error(f"Processing failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(2)
    validate_outputs(out)
    sys.exit(0)
