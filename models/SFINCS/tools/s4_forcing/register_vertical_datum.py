#!/usr/bin/env python3
"""Derive the DEM-vs-gauge vertical offset from METADATA ONLY -- never by
fitting to the observations.

Motivation (dt_v024, Fraser Agassiz, 2026-08-05)
------------------------------------------------
The run registered SFINCS water levels against HYDAT 08MF035 stage using a
constant -1.4035 m offset FITTED on the 2021 observations.  That makes the
calibration PBIAS zero by construction (-1.65e-15) and silently absorbs
whatever the DEM gets wrong -- global DEMs such as Copernicus GLO-30 carry no
channel bathymetry, so a fitted offset mostly encodes the missing bed.
dag.yaml sets outputs[point_zs].observability.detrending_options: ['none'],
so an obs-fitted offset is a calibrated parameter, not a datum registration.

HYDAT already carries the real conversion.  For 08MF035:
    STATIONS.DATUM_ID = 35   GEODETIC SURVEY OF CANADA DATUM
    STN_DATUM_CONVERSION 35 -> 605  CANADIAN GEODETIC VERTICAL DATUM
                                    2013:EPOCH2010,  +0.163 m
and the remaining CGVD2013 -> DEM-datum step is a geoid difference that PROJ
computes exactly from published grids.

This tool chains STATIONS.DATUM_ID -> DATUM_LIST -> STN_DATUM_CONVERSION to
reach a geodetic datum, then applies the documented geoid relationship to the
DEM's vertical datum, and writes datum_registration.json.  If no metadata
chain exists it FAILS rather than falling back to a fit.

Sign convention
---------------
HYDAT CONVERSION_FACTOR is the value ADDED to a water level referenced to
DATUM_ID_FROM to express it in DATUM_ID_TO.  Every offset in this tool follows
the same direction: offset_m is ADDED to a gauge stage to express it in the
DEM's vertical datum, i.e.  h_dem_datum = stage_gauge_datum + offset_m.

Outputs
-------
<output_dir>/datum_registration.json

Exit codes
----------
0  a metadata chain was resolved (see `complete` for whether the DEM-datum
   geoid step was also resolved), or a forced fitted offset was stamped
1  no metadata chain exists -- the caller must NOT fit an offset instead
2  usage / input error
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import deque
from pathlib import Path

# --------------------------------------------------------------------------
# HYDAT DATUM_ID -> EPSG vertical CRS, for the PROJ geoid step.
# Only datums with an unambiguous published realisation are listed; anything
# absent here simply stops the chain (the tool reports it, never guesses).
# --------------------------------------------------------------------------
DATUM_ID_TO_EPSG = {
    605: 6647,  # CANADIAN GEODETIC VERTICAL DATUM 2013:EPOCH2010 -> CGVD2013 height
    35: 5713,   # GEODETIC SURVEY OF CANADA DATUM  ~ CGVD28 height
}
# Preference order when several geodetic datums are reachable.
PREFERRED_TARGET_DATUMS = [605, 35]

# DEM vertical datum name -> EPSG vertical CRS.
DEM_DATUM_TO_EPSG = {
    "EGM2008": 3855,   # Copernicus GLO-30 / GLO-90, SRTM v3 (EGM96 for older SRTM)
    "EGM96": 5773,     # SRTM v2, ASTER GDEM
    "CGVD2013": 6647,
    "CGVD28": 5713,
    "NAVD88": 5703,
}
# Datums that are NOT geoid-based orthometric systems need separate handling.
ELLIPSOIDAL_DATUMS = {"WGS84", "WGS84_ELLIPSOID", "ELLIPSOIDAL", "ITRF", "NAD83"}


def _connect(db_path):
    if not Path(db_path).exists():
        raise SystemExit(f"[error] HYDAT database not found: {db_path}")
    # immutable=1 is required as well as mode=ro: HYDAT ships in WAL mode and a
    # plain read-only open fails on read-only media.
    return sqlite3.connect(f"file:{db_path}?mode=ro&immutable=1", uri=True)


def _datum_names(con):
    return {row[0]: row[1] for row in con.execute("SELECT DATUM_ID, DATUM_EN FROM DATUM_LIST")}


def _station_row(con, station):
    row = con.execute(
        "SELECT STATION_NUMBER, STATION_NAME, LATITUDE, LONGITUDE, DATUM_ID "
        "FROM STATIONS WHERE STATION_NUMBER = ?",
        (station,),
    ).fetchone()
    if row is None:
        raise SystemExit(f"[error] station {station} not present in HYDAT STATIONS")
    return row


def _resolve_chain(con, station, start_datum, names):
    """Breadth-first walk of STN_DATUM_CONVERSION from the station's own datum.

    Returns (target_datum_id, chain) for the most preferred reachable geodetic
    datum, or (None, []) when no conversion row exists for this station.
    """
    rows = con.execute(
        "SELECT DATUM_ID_FROM, DATUM_ID_TO, CONVERSION_FACTOR "
        "FROM STN_DATUM_CONVERSION WHERE STATION_NUMBER = ?",
        (station,),
    ).fetchall()
    if not rows:
        return None, []

    edges = {}
    for a, b, f in rows:
        edges.setdefault(a, []).append((b, float(f)))
        # The inverse conversion is exact: subtract instead of add.
        edges.setdefault(b, []).append((a, -float(f)))

    paths = {start_datum: []}
    queue = deque([start_datum])
    while queue:
        node = queue.popleft()
        for nxt, factor in edges.get(node, []):
            if nxt in paths:
                continue
            paths[nxt] = paths[node] + [
                {
                    "from_datum_id": node,
                    "from_datum": names.get(node, f"DATUM_ID {node}"),
                    "to_datum_id": nxt,
                    "to_datum": names.get(nxt, f"DATUM_ID {nxt}"),
                    "conversion_factor": factor,
                    "source": "HYDAT STN_DATUM_CONVERSION",
                }
            ]
            queue.append(nxt)

    for target in PREFERRED_TARGET_DATUMS:
        if target in paths and target != start_datum:
            return target, paths[target]
    if start_datum in DATUM_ID_TO_EPSG:
        return start_datum, []
    return None, []


def _geoid_step(from_epsg, to_epsg, lat, lon, allow_network):
    """Exact geoid difference between two vertical CRSs at a point, via PROJ."""
    step = {
        "from_epsg": from_epsg,
        "to_epsg": to_epsg,
        "method": "pyproj_geoid_grid",
        "status": "unresolved",
        "conversion_factor": None,
    }
    if from_epsg == to_epsg:
        step.update(status="identity", conversion_factor=0.0)
        return step
    try:
        import pyproj
        from pyproj import Transformer
    except ImportError as exc:
        step["error"] = f"pyproj unavailable: {exc}"
        return step

    if allow_network:
        try:
            pyproj.network.set_network_enabled(True)
            step["network_enabled"] = True
        except Exception:
            step["network_enabled"] = False

    try:
        tr = Transformer.from_crs(
            f"EPSG:4326+{from_epsg}", f"EPSG:4326+{to_epsg}", always_xy=True
        )
        _, _, dz = tr.transform(lon, lat, 0.0)
        if dz is None or dz != dz or abs(dz) > 1e6:
            step["error"] = "PROJ returned no finite result (geoid grid unavailable)"
            return step
        # tr.description is only populated once proj_trans has actually run.
        step.update(
            status="resolved",
            conversion_factor=float(dz),
            proj_operation=tr.description,
            proj_pipeline=tr.to_proj4() if hasattr(tr, "to_proj4") else None,
            pyproj_version=pyproj.__version__,
        )
    except Exception as exc:
        step["error"] = f"{type(exc).__name__}: {exc}"
    return step


def main():
    ap = argparse.ArgumentParser(
        description="Derive the DEM-vs-gauge vertical offset from HYDAT metadata, never from obs."
    )
    ap.add_argument("--hydat_db", required=True)
    ap.add_argument("--station", required=True)
    ap.add_argument(
        "--dem_vertical_datum",
        required=True,
        help="vertical datum of the DEM, e.g. EGM2008 for Copernicus GLO-30",
    )
    ap.add_argument("--output_dir", required=True)
    ap.add_argument(
        "--require_complete",
        action="store_true",
        help="exit non-zero unless the DEM-datum geoid step also resolved",
    )
    ap.add_argument(
        "--no_network",
        action="store_true",
        help="do not let PROJ fetch geoid grids from cdn.proj.org",
    )
    ap.add_argument(
        "--force_fitted_offset_m",
        type=float,
        help="LAST RESORT: an obs-fitted offset. Stamps method='fitted' and "
        "metric_disqualified=true for the fitting period.",
    )
    ap.add_argument("--fitted_on", help="period the forced offset was fitted on, YYYY-MM-DD..YYYY-MM-DD")
    args = ap.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "datum_registration.json"

    con = _connect(args.hydat_db)
    names = _datum_names(con)
    sid, sname, lat, lon, datum_id = _station_row(con, args.station)

    result = {
        "tool": "register_vertical_datum.py",
        "station_id": sid,
        "station_name": sname,
        "lat": lat,
        "lon": lon,
        "gauge_datum_id": datum_id,
        "gauge_datum": names.get(datum_id, f"DATUM_ID {datum_id}"),
        "dem_vertical_datum": args.dem_vertical_datum,
        "sign_convention": "h_dem_datum = stage_gauge_datum + offset_m",
        "provenance": {
            "hydat_db": str(args.hydat_db),
            "tables": ["STATIONS", "DATUM_LIST", "STN_DATUM_CONVERSION"],
        },
    }

    # ---- forced fitted offset: allowed, but permanently marked -------------
    if args.force_fitted_offset_m is not None:
        result.update(
            method="fitted",
            offset_m=float(args.force_fitted_offset_m),
            chain=[],
            complete=False,
            fitted_on=args.fitted_on,
            metric_disqualified=True,
            metric_disqualified_period=args.fitted_on,
            warning=(
                "This offset was fitted to the observations. dag.yaml sets "
                "detrending_options: ['none'] for point_zs, so it is a calibrated parameter: "
                "the period it was fitted on can NEVER be reported as a score."
            ),
        )
        out_path.write_text(json.dumps(result, indent=2, default=str))
        print(f"[FITTED] offset {result['offset_m']} m -- metric_disqualified for {args.fitted_on}")
        print(f"[written] {out_path}")
        con.close()
        return 0

    # ---- metadata chain ----------------------------------------------------
    target_id, chain = _resolve_chain(con, sid, datum_id, names)
    con.close()

    if target_id is None:
        result.update(
            method="metadata",
            status="FAILED",
            offset_m=None,
            chain=chain,
            complete=False,
            error=(
                f"No STN_DATUM_CONVERSION chain from DATUM_ID {datum_id} "
                f"({result['gauge_datum']}) to a geodetic datum for station {sid}. "
                f"Do NOT fit an offset to the observations instead -- choose a gauge whose "
                f"datum is documented, or report the metric as NULL."
            ),
        )
        out_path.write_text(json.dumps(result, indent=2, default=str))
        print(f"[FAIL] {result['error']}", file=sys.stderr)
        print(f"[written] {out_path}")
        return 1

    hydat_offset = sum(step["conversion_factor"] for step in chain)
    result["geodetic_datum_id"] = target_id
    result["geodetic_datum"] = names.get(target_id, f"DATUM_ID {target_id}")
    result["gauge_to_geodetic_offset_m"] = float(hydat_offset)

    # ---- geodetic datum -> DEM vertical datum ------------------------------
    dem_key = args.dem_vertical_datum.strip().upper()
    from_epsg = DATUM_ID_TO_EPSG.get(target_id)
    to_epsg = DEM_DATUM_TO_EPSG.get(dem_key)

    if dem_key in ELLIPSOIDAL_DATUMS:
        dem_step = {
            "method": "not_applicable",
            "status": "unresolved",
            "conversion_factor": None,
            "error": (
                f"{args.dem_vertical_datum} is an ellipsoidal reference, not an orthometric "
                f"height system; supply a geoid model name (EGM2008, EGM96, CGVD2013, ...)"
            ),
        }
    elif from_epsg is None or to_epsg is None:
        dem_step = {
            "method": "epsg_lookup",
            "status": "unresolved",
            "conversion_factor": None,
            "error": (
                f"no EPSG vertical CRS mapped for "
                f"{'geodetic DATUM_ID %s' % target_id if from_epsg is None else ''}"
                f"{' and ' if from_epsg is None and to_epsg is None else ''}"
                f"{'DEM datum %s' % args.dem_vertical_datum if to_epsg is None else ''}"
            ),
        }
    else:
        dem_step = _geoid_step(from_epsg, to_epsg, lat, lon, allow_network=not args.no_network)
        dem_step.setdefault("from_datum", result["geodetic_datum"])
        dem_step.setdefault("to_datum", args.dem_vertical_datum)

    result["dem_datum_step"] = dem_step

    full_chain = list(chain)
    if dem_step.get("conversion_factor") is not None:
        full_chain.append(
            {
                "from_datum_id": target_id,
                "from_datum": result["geodetic_datum"],
                "to_datum_id": None,
                "to_datum": args.dem_vertical_datum,
                "conversion_factor": float(dem_step["conversion_factor"]),
                "source": dem_step.get("proj_operation", dem_step.get("method")),
            }
        )
    result["chain"] = full_chain
    result["method"] = "metadata"

    if dem_step.get("conversion_factor") is not None:
        result["offset_m"] = float(hydat_offset + dem_step["conversion_factor"])
        result["complete"] = True
        result["status"] = "OK"
    else:
        result["offset_m"] = float(hydat_offset)
        result["complete"] = False
        result["status"] = "PARTIAL"
        result["warning"] = (
            "Only the HYDAT gauge-datum step resolved; the geoid step to the DEM's vertical "
            "datum did not. offset_m therefore expresses the stage in "
            f"{result['geodetic_datum']}, NOT in {args.dem_vertical_datum}. Install the PROJ "
            "geoid grid (or allow network access to cdn.proj.org) before scoring. Do NOT make "
            "up the difference by fitting to the observations."
        )

    out_path.write_text(json.dumps(result, indent=2, default=str))

    print(f"[{result['status']}] {sid} {sname}")
    for step in full_chain:
        print(
            f"    {step['from_datum']} -> {step['to_datum']}: "
            f"{step['conversion_factor']:+.4f} m   ({step['source']})"
        )
    print(f"    offset_m = {result['offset_m']:+.4f} m  (method=metadata, complete={result['complete']})")
    if result.get("warning"):
        print(f"[WARN] {result['warning']}")
    print(f"[written] {out_path}")

    if args.require_complete and not result["complete"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
