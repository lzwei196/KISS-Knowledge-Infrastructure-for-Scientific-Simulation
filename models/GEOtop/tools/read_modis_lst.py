#!/usr/bin/env python3
"""read_modis_lst.py -- GEOtop stage s8 (Validation): MODIS MOD11A2 LST at a point.

THE MISSING OBSERVATION TOOL. The GEOtop KI shipped tools for s2/s4/s6/s7 but
nothing to read an observation, so every LST validation run had to hand-roll
HDF/sinusoidal handling -- the exact situation the KI is supposed to prevent.
This tool extracts the MOD11A2 (Terra, 1 km, 8-day composite) land surface
temperature record for one lat/lon from a directory of .hdf granules.

WHY THIS IS NOT TRIVIAL (each of these silently corrupts the comparison):

  1. SINUSOIDAL GRID. MOD11A2 is on the MODIS sinusoidal projection, NOT
     lat/lon. The pixel must be found by reprojecting the point with the
     granule's own CRS + GeoTransform; assuming a regular lat/lon grid puts you
     tens of km away.

  2. SCALE FACTORS, AND THEY DIFFER PER FIELD.
        LST_Day_1km / LST_Night_1km : x0.02  -> KELVIN  (then -273.15 for C)
        Day_view_time / Night_view_time : x0.1 -> hours of LOCAL SOLAR TIME
     Fill value is 0 in every field (NOT -9999); an unmasked 0 enters the
     series as 0 K / 0 h.

  3. VIEW TIME IS LOCAL SOLAR TIME, NOT UTC. The composite is the mean clear-sky
     LST at the overpass instant, ~10.5-11.5 h (day) and ~22 h (night) local
     SOLAR time. To sample a model driven by UTC forcing you must convert:
         t_utc = view_time_local_solar - lon/15
     Comparing MODIS "day" against model local noon, or against a fixed UTC
     hour, mis-samples the diurnal cycle by hours -- on a clear winter day the
     skin-temperature error from that alone is >5 K.

  4. QC. Bits 0-1 of QC_Day/QC_Night are the mandatory QA flag:
        00 produced, good quality        01 produced, check other QA
        10 not produced (cloud)          11 not produced (other)
     10/11 must be dropped. Bits 6-7 give the LST error class
     (00 <=1 K, 01 <=2 K, 10 <=3 K, 11 >3 K).

  5. AN 8-DAY COMPOSITE IS NOT AN INSTANT. The value is the average over the
     clear-sky days within the 8-day window starting at the granule's A-date.
     The matching model quantity is the model skin temperature at the overpass
     instant averaged over the SAME window -- not a single day, and not a
     daily-mean. Use the emitted window_start/window_end to aggregate.

Usage:
    python read_modis_lst.py --dir KISSPATH_DATA/obs/nasa/modis_lst \
        --tile h27v05 --lat 36.0 --lon 116.0 \
        --start 2018-01-01 --end 2018-01-31 \
        --output /path/to/modis_lst_point.csv

Output CSV columns:
    window_start, window_end, overpass (day|night), view_time_local_solar_h,
    view_time_utc_h, obs_datetime_utc, lst_k, lst_c, qc, qa_mandatory,
    lst_error_class, granule
"""
import argparse
import glob
import json
import os
import re
import sys
from datetime import datetime, timedelta

SCALE_LST = 0.02
SCALE_VIEWTIME = 0.1
FILL = 0  # MOD11A2 fill value is 0 in LST, view-time and QC fields

QA_MANDATORY = {0: "good_quality", 1: "produced_check_qa",
                2: "not_produced_cloud", 3: "not_produced_other"}
LST_ERR_CLASS = {0: "<=1K", 1: "<=2K", 2: "<=3K", 3: ">3K"}


def granule_date(path):
    """A2018001 -> datetime(2018,1,1) (window START of the 8-day composite)."""
    m = re.search(r"\.A(\d{4})(\d{3})\.", os.path.basename(path))
    if not m:
        return None
    return datetime(int(m.group(1)), 1, 1) + timedelta(days=int(m.group(2)) - 1)


def open_point(hdf_path, lat, lon):
    """Return {subdataset_name: raw value} at (lat, lon) for one granule."""
    from osgeo import gdal
    gdal.UseExceptions()
    from pyproj import Transformer

    ds = gdal.Open(hdf_path)
    subs = {s[0].split(":")[-1].strip('"'): s[0] for s in ds.GetSubDatasets()}
    if "LST_Day_1km" not in subs:
        raise ValueError(f"{hdf_path}: no LST_Day_1km subdataset")

    ref = gdal.Open(subs["LST_Day_1km"])
    gt = ref.GetGeoTransform()
    # Reproject the point into the granule's own sinusoidal CRS (trap #1).
    tr = Transformer.from_crs("EPSG:4326", ref.GetProjection(), always_xy=True)
    x, y = tr.transform(lon, lat)
    col = int((x - gt[0]) / gt[1])
    row = int((y - gt[3]) / gt[5])
    if not (0 <= col < ref.RasterXSize and 0 <= row < ref.RasterYSize):
        raise ValueError(f"{hdf_path}: point ({lat},{lon}) outside tile "
                         f"(row={row}, col={col})")

    out = {"_row": row, "_col": col}
    for name in ("LST_Day_1km", "LST_Night_1km", "QC_Day", "QC_Night",
                 "Day_view_time", "Night_view_time",
                 "Clear_sky_days", "Clear_sky_nights"):
        if name in subs:
            out[name] = float(gdal.Open(subs[name]).ReadAsArray(col, row, 1, 1)[0, 0])
    return out


def extract(hdf_dir, tile, lat, lon, start, end, drop_not_produced=True):
    pattern = os.path.join(hdf_dir, f"*{tile}*.hdf" if tile else "*.hdf")
    files = sorted(f for f in glob.glob(pattern) if not os.path.basename(f).startswith("BROWSE"))
    rows, skipped = [], []

    for f in files:
        d0 = granule_date(f)
        if d0 is None:
            continue
        d1 = d0 + timedelta(days=8)
        if end and d0 > end:
            continue
        if start and d1 <= start:
            continue

        vals = open_point(f, lat, lon)
        for overpass, lst_key, qc_key, vt_key, clr_key in (
                ("day", "LST_Day_1km", "QC_Day", "Day_view_time", "Clear_sky_days"),
                ("night", "LST_Night_1km", "QC_Night", "Night_view_time", "Clear_sky_nights")):
            raw = vals.get(lst_key, FILL)
            qc = int(vals.get(qc_key, 0))
            vt_raw = vals.get(vt_key, FILL)
            qa = qc & 0b11                       # trap #4
            if raw == FILL or vt_raw == FILL:
                skipped.append({"granule": os.path.basename(f), "overpass": overpass,
                                "reason": "fill_value"})
                continue
            if drop_not_produced and qa >= 2:
                skipped.append({"granule": os.path.basename(f), "overpass": overpass,
                                "reason": QA_MANDATORY[qa]})
                continue

            vt_local = vt_raw * SCALE_VIEWTIME            # local SOLAR hours (trap #2/#3)
            vt_utc = vt_local - lon / 15.0                # -> UTC
            lst_k = raw * SCALE_LST
            rows.append({
                "window_start": d0.strftime("%Y-%m-%d"),
                "window_end": (d1 - timedelta(days=1)).strftime("%Y-%m-%d"),
                "overpass": overpass,
                "view_time_local_solar_h": round(vt_local, 3),
                "view_time_utc_h": round(vt_utc, 3),
                # nominal instant: window start + the UTC overpass hour
                "obs_datetime_utc": (d0 + timedelta(hours=vt_utc)).strftime("%Y-%m-%d %H:%M"),
                "lst_k": round(lst_k, 3),
                "lst_c": round(lst_k - 273.15, 3),
                # trap #5: how many of the 8 days actually contributed. The
                # model must be averaged over the SAME number of (clearest)
                # days, not over all 8 -- clouds damp the diurnal amplitude.
                "clear_sky_count": int(vals.get(clr_key, 0)),
                "qc": qc,
                "qa_mandatory": QA_MANDATORY[qa],
                "lst_error_class": LST_ERR_CLASS[(qc >> 6) & 0b11],
                "granule": os.path.basename(f),
            })

    rows.sort(key=lambda r: (r["window_start"], r["overpass"]))
    return rows, skipped


def validate(rows):
    """Sanity-check the extracted series; returns a list of warnings."""
    warnings = []
    if not rows:
        warnings.append("CRITICAL: no usable MODIS LST observations extracted.")
        return warnings
    lst = [r["lst_k"] for r in rows]
    if min(lst) < 200 or max(lst) > 340:
        warnings.append(f"LST outside physical 200-340 K range: "
                        f"{min(lst):.1f}-{max(lst):.1f} K. Check the 0.02 scale factor.")
    day = [r["view_time_local_solar_h"] for r in rows if r["overpass"] == "day"]
    night = [r["view_time_local_solar_h"] for r in rows if r["overpass"] == "night"]
    if day and not all(9.0 <= v <= 13.5 for v in day):
        warnings.append(f"Day view times {min(day):.1f}-{max(day):.1f} h outside the "
                        "expected 10-12 h local-solar Terra window. Check the 0.1 scale.")
    if night and not all(20.0 <= v <= 24.0 or 0.0 <= v <= 2.0 for v in night):
        warnings.append(f"Night view times {min(night):.1f}-{max(night):.1f} h outside "
                        "the expected ~22 h local-solar Terra window.")
    if day and night:
        import statistics
        dmean, nmean = (statistics.mean(r["lst_k"] for r in rows if r["overpass"] == o)
                        for o in ("day", "night"))
        if dmean <= nmean:
            warnings.append(f"Day mean LST ({dmean:.1f} K) <= night mean ({nmean:.1f} K) -- "
                            "day/night fields are likely swapped.")
    return warnings


def main():
    ap = argparse.ArgumentParser(description="Extract MOD11A2 LST at a point")
    ap.add_argument("--dir", required=True, help="Directory of MOD11A2 .hdf granules")
    ap.add_argument("--tile", default="", help="MODIS tile filter, e.g. h27v05")
    ap.add_argument("--lat", type=float, required=True)
    ap.add_argument("--lon", type=float, required=True)
    ap.add_argument("--start", default="", help="YYYY-MM-DD (inclusive)")
    ap.add_argument("--end", default="", help="YYYY-MM-DD (inclusive)")
    ap.add_argument("--keep-not-produced", action="store_true",
                    help="Keep QA 'not produced' pixels (default: drop)")
    ap.add_argument("--output", required=True, help="Output CSV path")
    args = ap.parse_args()

    start = datetime.strptime(args.start, "%Y-%m-%d") if args.start else None
    end = datetime.strptime(args.end, "%Y-%m-%d") if args.end else None

    rows, skipped = extract(args.dir, args.tile, args.lat, args.lon, start, end,
                            drop_not_produced=not args.keep_not_produced)
    warnings = validate(rows)

    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    cols = ["window_start", "window_end", "overpass", "view_time_local_solar_h",
            "view_time_utc_h", "obs_datetime_utc", "lst_k", "lst_c",
            "clear_sky_count", "qc", "qa_mandatory", "lst_error_class", "granule"]
    with open(args.output, "w") as fh:
        fh.write(",".join(cols) + "\n")
        for r in rows:
            fh.write(",".join(str(r[c]) for c in cols) + "\n")

    print(json.dumps({
        "status": "error" if not rows else ("warning" if warnings else "ok"),
        "n_obs": len(rows), "n_skipped": len(skipped),
        "skipped": skipped, "warnings": warnings, "output": args.output,
    }, indent=2), file=sys.stderr)
    if not rows:
        sys.exit(1)


if __name__ == "__main__":
    main()
