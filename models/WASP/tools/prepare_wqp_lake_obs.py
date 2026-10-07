#!/usr/bin/env python3
"""
prepare_wqp_lake_obs.py -- WQP lake observations (DO, water temperature) as station-day values with cruise QC.

Data folder: --wqp-dir -> $WASP_WQP_DIR -> KISSPATH_OBS/water_quality/wqp
(one sub-folder per lake, <lake>/<lake>_Dissolved_oxygen_DO.csv and <lake>_Temperature_water.csv).
The server's WQP lake folders were pulled by drainage area: for Lake_Erie_Central most stations are
TRIBUTARY STREAMS (682 of 800 resolved stations are "River/Stream", only 60 "Great Lake"). The CSVs
carry no coordinates and no station type, so this tool looks every MonitoringLocationIdentifier up
in the WQP Station service (cached to --station-cache) and keeps only the requested --site-types
inside --bbox.

EPA GLNPO CTD profiles carry no depth column: the sample depth is only in ResultCommentText
("- E073A12-PRFL-15" = 15 m). With --max-depth-m only values whose depth is parsed from that text
and is <= max are kept (others dropped and counted); without it every value of a station-day is
used (a whole-water-column mean in summer = epilimnion + hypolimnion mixed).

Output is FIXED SUPPORT: exactly ONE row per station and day (support='station_day'; the wqp_lakes
binding: "compare per-station or as the network mean - never one pinned gauge"). Each row keeps TWO
values side by side, so the unfiltered baseline is never lost:
  value      ALL data: mean of the per-cruise means of EVERY cruise that sampled the station-day
             (no cruise QC applied; only the unit and range filters)
  value_qc   QC subset: mean of the per-cruise means of the cruises with NO excluding flag; empty
             when every cruise of the station-day has an excluding flag
'cruise' lists every cruise in 'value' (';'-joined), 'cruises_qc_excluded' the ones left out of
'value_qc', 'qc_flag' the union of their EXCLUDING flags, 'qc_diag' the union of DIAGNOSTIC flags
(diagnostic flags never remove data). A per-day mean over whatever stations a cruise reached that
day (1 to 11) has no fixed support, so it is only written with --network-mean
(support='network_mean_variable'): value = mean of the station-day 'value', value_qc = mean of the
station-day 'value_qc' that exist (n_stations_qc of them); flags are unions.
Units are checked per record: deg F is converted to deg C, % saturation DO is dropped (never mixed
with mg/L), other units are refused. Output CSV columns: date, station_id, lat, lon, value,
value_qc, n_values, n_values_qc, n_cruises, cruise, cruises_qc_excluded, qc_flag, qc_diag, support
(with --network-mean: date, value, value_qc, n_stations, n_stations_qc, n_values,
sd_between_stations, cruise, cruises_qc_excluded, qc_flag, qc_diag, support).

Cruise sensor QC (--variable do; no-op for temperature). A CTD DO sensor can fail for a WHOLE cruise
and every such record is still 'Accepted' in WQP, so status flags cannot catch it. A cruise is
(OrganizationIdentifier, ResultAnalyticalMethod/MethodIdentifier, year-month). The QC uses ONLY the
cruise's own data and same-cast temperature, never model output, and is run on ALL depths (ignores
--max-depth-m) BEFORE the range filter, so a dead sensor is flagged and reported instead of
silently vanishing. Sensor flags apply only to in-situ sensor methods (--qc-sensor-methods, default
LG301 Seabird CTD and LG501Y YSI meter); Winkler titrations (LG501, LG501A) and any other method get
their stats recorded but are never flagged (sensor_checks='not_applicable' in the QC json).
EXCLUDING flags (left out of value_qc) need evidence that the SENSOR is wrong, not just low DO:
  sensor_dead       share of DO < 0 (a negative concentration is impossible) > --qc-dead-frac (0.5)
  winkler_disagree  an independent instrument disagrees AT THE SAME DEPTH: median CTD / median Winkler
                    (LG501/LG501A) over Winkler samples with a known depth (PRFL-<z> text, else
                    ResultDepthHeightMeasure in m or ft) matched to CTD values of the same station and
                    date within --qc-winkler-dz (1.0 m), outside --qc-winkler-range (0.85 1.15);
                    near anoxia (Winkler median < 1 mg/L) the test is |CTD - Winkler| > --qc-winkler-low-abs
                    (0.5 mg/L) instead, so 0 mg/L readings never divide by zero
DIAGNOSTIC flags (reported in the QC json and qc_diag, never remove data; only on cruises without an
excluding flag):
  sat_offset_unconfirmed      DO / APHA saturation(T) (same-cast pairs: station, date, PRFL depth, with
                    the sibling <lake>_Temperature_water.csv, at --elev 174 m) has a whole-column
                    median outside --qc-sat-range (0.70 1.30). Low DO alone is not proof of a sensor
                    fault (summer hypolimnion depletion is real), so this never excludes data. The QC
                    json also records the near-surface (z <= 5 m) median and whether the column was
                    mixed (column_mixed: median over casts of the temperature SD between depths <=
                    --qc-mixed-sd 1.0 deg C, casts with >= 3 depths) to help a human judge it.
  winkler_disagree_unmatched_depth  only when no depth-matched pair exists: median CTD (z <= 5 m) vs
                    median Winkler of any or unknown depth at the same station and date, disagreeing by
                    the same test. The depths may differ (GLNPO Winkler records carry no depth),
                    so this never excludes data.
Every cruise with its stats and flags goes to <out>.cruise_qc.json (written BEFORE the empty-data
exit, so an all-dead-sensor selection still keeps its diagnosis). Out-of-range values are counted in
the QC and then left out of the value table (they cannot be a concentration).

Usage
  python prepare_wqp_lake_obs.py --lake Lake_Erie_Central --variable do \
      --bbox -82.6 41.35 -80.4 42.6 --site-types "Great Lake" --start 2005-01-01 --end 2014-12-31 \
      --station-cache stations.csv --out obs_do.csv
Exit codes: 0 ok; 1 no usable data / lookup failed; 2 bad command line.
"""
import argparse
import io
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import requests

DEFAULT_WQ = "KISSPATH_OBS/water_quality/wqp"
FILES = {"do": "Dissolved_oxygen_DO", "temperature": "Temperature_water"}
UNITS = {"do": {"mg/L": 1.0, "mg/l": 1.0}, "temperature": {"deg C": None, "deg F": "F"}}
RANGE = {"do": (0.0, 25.0), "temperature": (-2.0, 40.0)}
STATION_URL = "https://www.waterqualitydata.us/data/Station/search?mimeType=csv"
METHOD = "ResultAnalyticalMethod/MethodIdentifier"
UNIT = "ResultMeasure/MeasureUnitCode"
WINKLER = {"LG501", "LG501A"}
SENSOR_METHODS = ["LG301", "LG501Y"]  # in-situ sensors (Seabird CTD, YSI meter): the only QC targets
PRFL_RE = r"PRFL-(\d+(?:\.\d+)?)"
EXCLUDING = ("sensor_dead", "winkler_disagree")
DIAGNOSTIC = ("sat_offset_unconfirmed", "winkler_disagree_unmatched_depth")


def wqp_dir(arg=None):
    """WQP data root: --wqp-dir -> $WASP_WQP_DIR -> server default."""
    return Path(arg or os.environ.get("WASP_WQP_DIR") or DEFAULT_WQ).expanduser().absolute()


def lookup_stations(ids, cache):
    """WQP Station metadata for ids (cached). Proxy is bypassed: the WQP API answers directly."""
    have = pd.read_csv(cache) if cache and Path(cache).is_file() else pd.DataFrame()
    known = set(have.get("MonitoringLocationIdentifier", []))
    todo = sorted(i for i in ids if i not in known and "\n" not in i)
    s = requests.Session()
    s.trust_env = False
    got, bad = [have] if len(have) else [], []

    def fetch(chunk):
        r = s.post(STATION_URL, json={"siteid": chunk}, timeout=180)
        if r.status_code == 200:
            if r.text.strip():
                got.append(pd.read_csv(io.StringIO(r.text)))
        elif len(chunk) == 1:
            bad.append(chunk[0])
        else:
            fetch(chunk[:len(chunk) // 2])
            fetch(chunk[len(chunk) // 2:])
    for i in range(0, len(todo), 100):
        fetch(todo[i:i + 100])
    st = pd.concat(got).drop_duplicates("MonitoringLocationIdentifier") if got else pd.DataFrame()
    if cache and todo:
        st.to_csv(cache, index=False)
    return st, bad


def prfl_depth(df):
    """GLNPO sample depth (m) parsed from ResultCommentText 'PRFL-<z>'; NaN when absent."""
    return pd.to_numeric(df.ResultCommentText.astype(str).str.extract(PRFL_RE)[0], errors="coerce")


def sample_depth(df):
    """Sample depth (m): PRFL-<z> text first, else ResultDepthHeightMeasure (m or ft); NaN when unknown."""
    z = prfl_depth(df)
    vcol, ucol = "ResultDepthHeightMeasure/MeasureValue", "ResultDepthHeightMeasure/MeasureUnitCode"
    if vcol in df and ucol in df:
        v = pd.to_numeric(df[vcol], errors="coerce")
        u = df[ucol].astype(str).str.strip().str.lower()
        fac = u.map({"m": 1.0, "meters": 1.0, "ft": 0.3048, "feet": 0.3048})
        z = z.fillna(v * fac)
    return z


def cruise_key(df):
    return (df.OrganizationIdentifier.astype(str) + ":" + df[METHOD].astype(str) + ":"
            + df.date.dt.strftime("%Y-%m"))


def _union(flags):
    """Sorted union of comma-joined flag strings; '' when none."""
    return ",".join(sorted({f for x in flags for f in str(x).split(",") if f and f != "nan"}))


def _join(cruises):
    """Sorted union of ';'-joined cruise lists; '' when none."""
    return ";".join(sorted({c for x in cruises for c in str(x).split(";") if c and c != "nan"}))


def station_days(df):
    """ONE row per (date, station) with both values: 'value' over every cruise (all data, no QC) and
    'value_qc' over the cruises without an excluding qc_flag (NaN when there is none)."""
    pc = (df.groupby(["date", "MonitoringLocationIdentifier", "cruise"])
          .agg(v=("v", "mean"), n=("v", "size"), qc_flag=("qc_flag", "first"),
               qc_diag=("qc_diag", "first")).reset_index())
    rows = []
    for (d, sid), g in pc.groupby(["date", "MonitoringLocationIdentifier"]):
        clean = g[g.qc_flag == ""]
        rows.append({"date": d, "station_id": sid,
                     "value": float(g.v.mean()),
                     "value_qc": float(clean.v.mean()) if len(clean) else np.nan,
                     "n_values": int(g.n.sum()), "n_values_qc": int(clean.n.sum()),
                     "n_cruises": int(len(g)),
                     "cruise": ";".join(sorted(g.cruise)),
                     "cruises_qc_excluded": ";".join(sorted(g[g.qc_flag != ""].cruise)),
                     "qc_flag": _union(g.qc_flag), "qc_diag": _union(g.qc_diag)})
    return pd.DataFrame(rows)


def network_mean(sd):
    """Per-day mean over the station-day rows: value over all of them, value_qc over the station-days
    that have a value_qc; flags and cruise lists are unions (never dropped)."""
    out = sd.groupby("date").agg(
        value=("value", "mean"), value_qc=("value_qc", "mean"),
        n_stations=("value", "size"), n_stations_qc=("value_qc", "count"),
        n_values=("n_values", "sum"), sd_between_stations=("value", "std"),
        cruise=("cruise", _join), cruises_qc_excluded=("cruises_qc_excluded", _join),
        qc_flag=("qc_flag", _union), qc_diag=("qc_diag", _union)).reset_index()
    out["support"] = "network_mean_variable"
    return out


def do_sat_mgl(t_c, elev_m):
    """APHA (1992) fresh-water DO saturation, mg/L, times p/p0 from the standard atmosphere."""
    tk = np.asarray(t_c, float) + 273.15
    ln = (-139.34411 + 1.575701e5 / tk - 6.642308e7 / tk ** 2 + 1.243800e10 / tk ** 3
          - 8.621949e11 / tk ** 4)
    return np.exp(ln) * (1 - 2.25577e-5 * elev_m) ** 5.25588


def _outside(x, rng):
    return x is not None and not (rng[0] <= x <= rng[1])


def winkler_compare(ctd_med, w_med, a):
    """(ratio or None, disagree). The ratio CTD/Winkler is used when the Winkler median is >= 1 mg/L;
    near anoxia (Winkler < 1 mg/L, including 0) the absolute difference is used instead
    (disagree when > --qc-winkler-low-abs), so zero readings never divide by zero."""
    ctd_med, w_med = float(ctd_med), float(w_med)
    if w_med >= 1.0:
        r = ctd_med / w_med
        return round(r, 4), _outside(r, a.qc_winkler_range)
    return None, abs(ctd_med - w_med) > a.qc_winkler_low_abs


def cruise_qc(do, tsrc, keep_ids, start, end, a):
    """Per-cruise sensor QC from the cruise's own casts. `do` = DO rows (mg/L, all depths, NOT
    range-filtered) already limited to keep_ids and [start, end]. Returns {cruise: stats}."""
    t = pd.read_csv(tsrc, low_memory=False) if tsrc.is_file() else pd.DataFrame()
    cast_sd = pd.Series(dtype=float)
    if len(t):
        t = t[t.MonitoringLocationIdentifier.isin(keep_ids)].copy()
        t["date"] = pd.to_datetime(t.ActivityStartDate, errors="coerce")
        t = t[(t.date >= start) & (t.date <= end) & t[UNIT].astype(str).isin(UNITS["temperature"])].copy()
        t["t"] = pd.to_numeric(t.ResultMeasureValue, errors="coerce")
        f = t[UNIT] == "deg F"
        t.loc[f, "t"] = (t.loc[f, "t"] - 32.0) * 5.0 / 9.0
        t["z"] = prfl_depth(t)
        t = (t[t.z.notna() & t.t.between(*RANGE["temperature"])]
             .groupby(["MonitoringLocationIdentifier", "date", "z"]).t.mean())
        # mixing of each cast: temperature SD between its depths (casts with >= 3 depths only)
        g3 = t.groupby(level=[0, 1])
        cast_sd = g3.std()[g3.size() >= 3]
    else:
        print(f"WARNING: no {tsrc}; cruise QC runs without the saturation test", file=sys.stderr)
    do = do.copy()
    do["cruise"], do["z"] = cruise_key(do), prfl_depth(do)
    is_w = do[METHOD].isin(WINKLER)
    wk = do[is_w & do.v.between(*RANGE["do"])
            & ~do.ResultCommentText.astype(str).str.contains("fail", case=False)].copy()
    wk["zw"] = sample_depth(wk)
    wink_any = wk.groupby(["MonitoringLocationIdentifier", "date"]).v.median()  # depth unknown/mixed
    wink_z = wk[wk.zw.notna()][["MonitoringLocationIdentifier", "date", "zw", "v"]].rename(columns={"v": "w"})
    res = {}
    for c, g in do.groupby("cruise"):
        r = {"n": int(len(g)), "neg_frac": round(float((g.v < 0).mean()), 4),
             "stations": sorted(g.MonitoringLocationIdentifier.unique()),
             "dates": sorted(g.date.dt.strftime("%Y-%m-%d").unique()),
             "col_sat_median": None, "n_sat_pairs": 0, "surf_sat_median": None, "n_surf_sat_pairs": 0,
             "cast_temp_sd_median": None, "n_casts_mixing": 0, "column_mixed": None,
             "winkler_ratio": None, "n_winkler": 0,
             "winkler_ratio_unmatched_depth": None, "n_winkler_unmatched_depth": 0}
        if len(t):
            gz = g[g.z.notna()].join(t, on=["MonitoringLocationIdentifier", "date", "z"], how="inner")
            gz = gz[gz.t.notna()]
            if len(gz):
                ratio = gz.v / do_sat_mgl(gz.t, a.elev)
                r["col_sat_median"] = round(float(np.median(ratio)), 4)
                r["n_sat_pairs"] = int(len(gz))
                surf = ratio[gz.z <= 5.0]
                if len(surf):
                    r["surf_sat_median"] = round(float(np.median(surf)), 4)
                    r["n_surf_sat_pairs"] = int(len(surf))
            casts = pd.MultiIndex.from_frame(
                g[g.z.notna()][["MonitoringLocationIdentifier", "date"]].drop_duplicates())
            sds = cast_sd.reindex(casts).dropna()
            if len(sds):
                r["cast_temp_sd_median"] = round(float(sds.median()), 4)
                r["n_casts_mixing"] = int(len(sds))
        # a cruise key includes the method, so a cruise is single-method
        sensor = bool(g[METHOD].astype(str).isin(a.qc_sensor_methods).all())
        r["sensor_checks"] = "applied" if sensor else "not_applicable"
        if r["cast_temp_sd_median"] is not None:
            r["column_mixed"] = bool(r["cast_temp_sd_median"] <= a.qc_mixed_sd)
        w_bad = wu_bad = False
        if sensor and len(wink_z):
            # Winkler with a known depth, matched to CTD values of the same station/date within dz
            ctd = g[g.z.notna()][["MonitoringLocationIdentifier", "date", "z", "v"]]
            m = ctd.merge(wink_z, on=["MonitoringLocationIdentifier", "date"])
            m = m[(m.z - m.zw).abs() <= a.qc_winkler_dz]
            if len(m):
                per = m.groupby(["MonitoringLocationIdentifier", "date", "zw"]).agg(ctd=("v", "median"),
                                                                                   w=("w", "median"))
                r["winkler_ctd_median"] = round(float(per.ctd.median()), 4)
                r["winkler_median"] = round(float(per.w.median()), 4)
                r["winkler_ratio"], w_bad = winkler_compare(per.ctd.median(), per.w.median(), a)
                r["n_winkler"] = int(len(per))
        if sensor and len(wink_any):
            ctd5 = g[g.z.notna() & (g.z <= 5.0)].groupby(["MonitoringLocationIdentifier", "date"]).v.median()
            both = pd.concat([ctd5.rename("ctd"), wink_any.rename("w")], axis=1, join="inner")
            if len(both):
                r["winkler_ratio_unmatched_depth"], wu_bad = winkler_compare(both.ctd.median(),
                                                                            both.w.median(), a)
                r["n_winkler_unmatched_depth"] = int(len(both))
        flags, diag = [], []
        if sensor:
            if r["neg_frac"] > a.qc_dead_frac:
                flags.append("sensor_dead")
            if w_bad:
                flags.append("winkler_disagree")
            if _outside(r["col_sat_median"], a.qc_sat_range):
                diag.append("sat_offset_unconfirmed")
            if r["n_winkler"] == 0 and wu_bad:
                diag.append("winkler_disagree_unmatched_depth")
        # a diagnostic flag marks a cruise that is KEPT but looks odd; an excluded cruise needs none
        r["flags"], r["diagnostic_flags"] = flags, ([] if flags else diag)
        res[c] = r
    return res


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--lake", required=True, help="folder under the WQP data root (see --wqp-dir)")
    ap.add_argument("--variable", required=True, choices=sorted(FILES))
    ap.add_argument("--wqp-dir", help=f"WQP data root (else $WASP_WQP_DIR, else {DEFAULT_WQ})")
    ap.add_argument("--bbox", nargs=4, type=float, required=True, metavar=("W", "S", "E", "N"))
    ap.add_argument("--site-types", nargs="+", default=["Great Lake"],
                    help="WQP MonitoringLocationTypeName values to keep")
    ap.add_argument("--start", required=True)
    ap.add_argument("--end", required=True)
    ap.add_argument("--max-depth-m", type=float,
                    help="keep only values with parsed sample depth <= this (GLNPO PRFL-<z> text)")
    ap.add_argument("--station-cache", help="CSV cache of WQP Station metadata")
    ap.add_argument("--elev", type=float, default=174.0,
                    help="lake surface elevation m, for the cruise-QC DO saturation (default 174)")
    ap.add_argument("--qc-dead-frac", type=float, default=0.5,
                    help="cruise flagged sensor_dead when this share of its DO values is < 0")
    ap.add_argument("--qc-sat-range", type=float, nargs=2, default=[0.70, 1.30], metavar=("LO", "HI"),
                    help="whole-column median DO/saturation band; outside -> DIAGNOSTIC sat_offset_unconfirmed "
                         "(never excludes data)")
    ap.add_argument("--qc-mixed-sd", type=float, default=1.0,
                    help="column_mixed in the QC json when the median over a cruise's casts of the "
                         "temperature SD between depths is <= this (deg C); information only")
    ap.add_argument("--qc-winkler-low-abs", type=float, default=0.5,
                    help="when the Winkler median is < 1 mg/L (near anoxia) CTD and Winkler disagree if they "
                         "differ by more than this (mg/L) instead of the ratio test")
    ap.add_argument("--qc-winkler-dz", type=float, default=1.0,
                    help="max depth difference (m) for a CTD value to be compared with a Winkler sample")
    ap.add_argument("--qc-winkler-range", type=float, nargs=2, default=[0.85, 1.15], metavar=("LO", "HI"),
                    help="cruise flagged winkler_disagree when CTD/Winkler median ratio is outside")
    ap.add_argument("--qc-sensor-methods", nargs="+", default=SENSOR_METHODS,
                    help="ResultAnalyticalMethod ids the sensor tests apply to (default LG301 LG501Y); "
                         "other methods, e.g. Winkler LG501/LG501A, are never sensor-flagged")
    ap.add_argument("--network-mean", action="store_true",
                    help="write the per-day mean over the stations sampled that day instead "
                         "(support='network_mean_variable'; NOT fixed support)")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    root = wqp_dir(a.wqp_dir)
    src = root / a.lake / f"{a.lake}_{FILES[a.variable]}.csv"
    if not src.is_file():
        print(f"ERROR: no such WQP file {src} (set --wqp-dir or $WASP_WQP_DIR)", file=sys.stderr)
        return 2
    df = pd.read_csv(src, low_memory=False)
    try:
        st, bad = lookup_stations(set(df.MonitoringLocationIdentifier.dropna()), a.station_cache)
    except requests.RequestException as e:
        print(f"ERROR: WQP Station lookup failed: {e}", file=sys.stderr)
        return 1
    w, s, e, n = a.bbox
    keep = st[st.MonitoringLocationTypeName.isin(a.site_types)
              & st.LongitudeMeasure.between(w, e) & st.LatitudeMeasure.between(s, n)]
    keep_ids = set(keep.MonitoringLocationIdentifier)
    df = df[df.MonitoringLocationIdentifier.isin(keep_ids)].copy()
    df["date"] = pd.to_datetime(df.ActivityStartDate, errors="coerce")
    df = df[(df.date >= a.start) & (df.date <= a.end)]
    df["v"] = pd.to_numeric(df.ResultMeasureValue, errors="coerce")
    u = df[UNIT].astype(str)
    allowed = UNITS[a.variable]
    dropped_units = u[~u.isin(allowed)].value_counts().to_dict()
    df = df[u.isin(allowed) & df.v.notna()].copy()
    if a.variable == "temperature":
        f = df[UNIT] == "deg F"
        df.loc[f, "v"] = (df.loc[f, "v"] - 32.0) * 5.0 / 9.0
    df["cruise"] = cruise_key(df)
    # Cruise QC on ALL depths and the RAW sign, before the depth and range filters.
    tsrc = root / a.lake / f"{a.lake}_{FILES['temperature']}.csv"
    qc = cruise_qc(df, tsrc, keep_ids, a.start, a.end, a) if a.variable == "do" else {}
    flag_of = {c: ",".join(r["flags"]) for c, r in qc.items()}
    diag_of = {c: ",".join(r["diagnostic_flags"]) for c, r in qc.items()}
    n_nodepth = 0
    if a.max_depth_m is not None:
        z = prfl_depth(df)
        n_nodepth = int(z.isna().sum())
        df = df[z.notna() & (z <= a.max_depth_m)].copy()
    lo, hi = RANGE[a.variable]
    out_rng = df[~df.v.between(lo, hi)]
    n_out = len(out_rng)
    out_by_cruise = out_rng.cruise.value_counts().to_dict()
    df = df[df.v.between(lo, hi)]
    flagged = {c: r["flags"] for c, r in qc.items() if r["flags"]}
    diagnosed = {c: r["diagnostic_flags"] for c, r in qc.items() if r["diagnostic_flags"]}
    if a.variable == "do":
        # written BEFORE the empty-observation exit: a dead-sensor-only selection keeps its diagnosis
        for c, r in qc.items():
            r["n_out_of_range_in_output_depths"] = int(out_by_cruise.get(c, 0))
        qc_path = Path(a.out).with_name(Path(a.out).stem + ".cruise_qc.json")
        qc_path.parent.mkdir(parents=True, exist_ok=True)
        qc_path.write_text(json.dumps({"elev_m": a.elev, "qc_dead_frac": a.qc_dead_frac,
                                       "qc_sat_range": a.qc_sat_range, "qc_mixed_sd": a.qc_mixed_sd,
                                       "qc_winkler_range": a.qc_winkler_range,
                                       "qc_sensor_methods": a.qc_sensor_methods,
                                       "excluding_flags": list(EXCLUDING),
                                       "diagnostic_flags": list(DIAGNOSTIC),
                                       "qc_winkler_dz": a.qc_winkler_dz,
                                       "qc_winkler_low_abs": a.qc_winkler_low_abs,
                                       "cruises": qc}, indent=1))
        print(f"cruise QC: {len(qc)} cruises, {len(flagged)} with an excluding flag, "
              f"{len(set(diagnosed) - set(flagged))} with a diagnostic flag only -> {qc_path}")
        for c in sorted(set(flagged) | set(diagnosed)):
            r = qc[c]
            print(f"  {'EXCLUDED' if r['flags'] else 'DIAGNOSTIC'} {c}: "
                  f"{','.join(r['flags'] + r['diagnostic_flags'])}  (neg_frac={r['neg_frac']}, "
                  f"col_sat_median={r['col_sat_median']}, surf_sat_median={r['surf_sat_median']}, "
                  f"cast_temp_sd_median={r['cast_temp_sd_median']}, winkler_ratio={r['winkler_ratio']}, "
                  f"winkler_ratio_unmatched_depth={r['winkler_ratio_unmatched_depth']})")
    if df.empty:
        print("ERROR: no usable observations after site-type/bbox/unit/range filters", file=sys.stderr)
        return 1
    df["qc_flag"] = df.cruise.map(flag_of).fillna("")
    df["qc_diag"] = df.cruise.map(diag_of).fillna("")
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    sd = station_days(df)
    if a.network_mean:
        out = network_mean(sd)
    else:
        ll = keep.set_index("MonitoringLocationIdentifier")[["LatitudeMeasure", "LongitudeMeasure"]]
        out = sd.join(ll, on="station_id").rename(columns={"LatitudeMeasure": "lat",
                                                           "LongitudeMeasure": "lon"})
        out["support"] = "station_day"
        out = out[["date", "station_id", "lat", "lon", "value", "value_qc", "n_values", "n_values_qc",
                   "n_cruises", "cruise", "cruises_qc_excluded", "qc_flag", "qc_diag", "support"]
                  ].sort_values(["date", "station_id"])
    out.to_csv(a.out, index=False, date_format="%Y-%m-%d", float_format="%.4f")
    print(f"wrote {a.out}: {len(out)} rows ({out.support.iloc[0]}; {int(out.value_qc.notna().sum())} with "
          f"a value_qc), {df.date.nunique()} days, "
          f"{df.MonitoringLocationIdentifier.nunique()} stations ({', '.join(a.site_types)}), "
          f"{df.cruise.nunique()} cruises, {len(df)} values, "
          f"{int((sd.n_cruises > 1).sum())} station-days merged from >1 cruise; dropped units "
          f"{dropped_units}, {n_out} out-of-range values (counted in the cruise QC on all depths "
          f"first, not silently lost), {n_nodepth} without parsable depth (dropped when "
          f"--max-depth-m), {len(bad)} ids not resolvable by WQP")
    return 0


if __name__ == "__main__":
    sys.exit(main())
