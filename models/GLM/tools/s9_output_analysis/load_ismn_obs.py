#!/usr/bin/env python3
"""
load_ismn_obs.py — Load ISMN (International Soil Moisture Network) cleaned
observations for validation of near-surface temperature / moisture.

Obs store (server): KISSPATH_DATA/ismn_clean.db  (sqlite3)
  stations(network, station_id, lat, lon, depth_cm, depth_from_m, depth_to_m,
           variable, start, end, n_obs_days, qc_pass, qc_reason, ...)
  observations(station_id, network, lat, lon, date, depth_cm, variable, value,
               qc_flag, depth_from_m, depth_to_m)

TRAPS this tool handles (see dt_037):
  * The DB is opened READ-ONLY and IMMUTABLE. `mode=ro` alone fails on a
    WAL-journalled DB sitting on read-only media -- `immutable=1` is required.
  * `depth_cm` is a ROUNDED integer label (5, 10, 20, 51, 102). The physically
    matched depth is `depth_from_m`/`depth_to_m` in METRES (0.0508, 0.1016,
    0.2032, 0.508, 1.016). ALWAYS pair a model layer against depth_from_m, not
    depth_cm/100 -- 51 cm vs 0.508 m is a 0.4 % error, but 2 in vs 5 cm is 60 %.
  * `value` rows are already DAILY MEANS of the sub-daily sensor record, and
    only rows the ISMN QC passed (qc_flag 'G') should be scored.
  * Several stations carry >1 sensor at the same nominal depth; rows are
    averaged per (date, depth).

Usage:
    python load_ismn_obs.py --station Cullman-NAHRC --network SCAN \
        --variable soil_temperature --start 2015-01-01 --end 2020-12-31 \
        --output obs_ismn.csv --meta_out obs_meta.json

    python load_ismn_obs.py --lat 34.19 --lon -86.80 --radius_km 25 \
        --variable soil_temperature --list      # discover nearby stations

Output CSV: date,depth_cm,depth_m,value   (long form, one row per date+depth)
"""

import argparse
import json
import math
import os
import sqlite3
import sys

import pandas as pd

DB_DEFAULT = "KISSPATH_DATA/ismn_clean.db"


def connect(db_path):
    """Read-only, immutable connection (WAL-safe on read-only media)."""
    if not os.path.exists(db_path):
        print(json.dumps({"status": "error",
                          "errors": [f"ISMN db not found: {db_path}"]}))
        sys.exit(1)
    return sqlite3.connect(f"file:{db_path}?mode=ro&immutable=1", uri=True)


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) *
         math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2)
    return R * 2 * math.asin(math.sqrt(a))


def list_stations(conn, variable, lat=None, lon=None, radius_km=50.0,
                  min_days=0, qc_only=True):
    q = "SELECT network,station_id,lat,lon,depth_cm,depth_from_m,depth_to_m," \
        "start,end,n_obs_days,qc_pass,qc_reason FROM stations WHERE variable=?"
    df = pd.read_sql(q, conn, params=(variable,))
    if qc_only:
        df = df[df.qc_pass == 1]
    if min_days:
        df = df[df.n_obs_days >= min_days]
    if lat is not None and lon is not None:
        df["distance_km"] = [round(haversine_km(lat, lon, a, b), 3)
                             for a, b in zip(df.lat, df.lon)]
        df = df[df.distance_km <= radius_km].sort_values("distance_km")
    return df.reset_index(drop=True)


def load_series(conn, station_id, variable, network=None, start=None, end=None,
                depths_cm=None, good_only=True):
    q = ("SELECT date, depth_cm, depth_from_m, depth_to_m, value, qc_flag "
         "FROM observations WHERE station_id=? AND variable=?")
    params = [station_id, variable]
    if network:
        q += " AND network=?"
        params.append(network)
    if start:
        q += " AND date>=?"
        params.append(start)
    if end:
        q += " AND date<=?"
        params.append(end)
    df = pd.read_sql(q, conn, params=params)
    if good_only and "qc_flag" in df.columns:
        df = df[df.qc_flag.astype(str).str.upper().str.startswith("G")]
    if depths_cm:
        df = df[df.depth_cm.isin(depths_cm)]
    if df.empty:
        return df.assign(depth_m=[])
    # physical depth in metres (NOT depth_cm/100 -- see docstring)
    df["depth_m"] = df["depth_from_m"].where(df["depth_from_m"].notna(),
                                             df["depth_cm"] / 100.0)
    df["date"] = pd.to_datetime(df["date"])
    out = (df.groupby(["date", "depth_cm", "depth_m"], as_index=False)["value"]
             .mean().sort_values(["depth_cm", "date"]).reset_index(drop=True))
    return out


def main():
    p = argparse.ArgumentParser(description="Load ISMN cleaned observations")
    p.add_argument("--db", default=DB_DEFAULT)
    p.add_argument("--variable", default="soil_temperature",
                   help="soil_temperature | soil_moisture")
    p.add_argument("--station", help="station_id")
    p.add_argument("--network", help="ISMN network (e.g. SCAN, SNOTEL, USCRN)")
    p.add_argument("--lat", type=float)
    p.add_argument("--lon", type=float)
    p.add_argument("--radius_km", type=float, default=50.0)
    p.add_argument("--min_days", type=int, default=0)
    p.add_argument("--start")
    p.add_argument("--end")
    p.add_argument("--depths_cm", help="comma-separated nominal depths to keep")
    p.add_argument("--list", action="store_true",
                   help="list matching stations instead of loading a series")
    p.add_argument("--output", help="output CSV (long form)")
    p.add_argument("--meta_out", help="output JSON with station metadata")
    args = p.parse_args()

    conn = connect(args.db)

    if args.list or not args.station:
        st = list_stations(conn, args.variable, args.lat, args.lon,
                           args.radius_km, args.min_days)
        print(st.to_json(orient="records", indent=2))
        if args.meta_out:
            st.to_json(args.meta_out, orient="records", indent=2)
        return

    depths = ([int(x) for x in args.depths_cm.split(",")]
              if args.depths_cm else None)
    ser = load_series(conn, args.station, args.variable, args.network,
                      args.start, args.end, depths)
    if ser.empty:
        print(json.dumps({"status": "error", "errors": [
            f"no ISMN {args.variable} rows for {args.station} in window"]}))
        sys.exit(1)

    meta = list_stations(conn, args.variable).query(
        "station_id == @args.station")
    if args.network:
        meta = meta[meta.network == args.network]

    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        ser.to_csv(args.output, index=False)

    summary = {
        "status": "success",
        "station_id": args.station,
        "network": args.network or (meta.network.iloc[0] if len(meta) else None),
        "variable": args.variable,
        "lat": float(meta.lat.iloc[0]) if len(meta) else None,
        "lon": float(meta.lon.iloc[0]) if len(meta) else None,
        "n_rows": int(len(ser)),
        "period": [str(ser.date.min().date()), str(ser.date.max().date())],
        "depths_cm": sorted(int(d) for d in ser.depth_cm.unique()),
        "depths_m": sorted(round(float(d), 4) for d in ser.depth_m.unique()),
        "output": args.output,
    }
    if args.meta_out:
        os.makedirs(os.path.dirname(args.meta_out) or ".", exist_ok=True)
        with open(args.meta_out, "w") as f:
            json.dump({"summary": summary,
                       "stations": json.loads(meta.to_json(orient="records"))},
                      f, indent=2)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
