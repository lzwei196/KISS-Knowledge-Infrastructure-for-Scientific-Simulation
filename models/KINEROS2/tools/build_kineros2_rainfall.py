#!/usr/bin/env python3
"""build_kineros2_rainfall.py -- write a KINEROS2 rainfall file (.pre) from gauge or gridded data.

A KINEROS2 rainfall file holds one block per rain gage:
    BEGIN GAGE 89
      SAT = 0.098                 ! optional initial relative saturation; OVERRIDES element SA
      X = 557250.4, Y = 275284.7  ! same coordinate system as the elements' X/Y (needed if >1 gage)
      N = 22
      TIME        DEPTH !(in)     ! minutes on ONE clock shared by all gages; cumulative depth
         0         0.00
        ...
    END
Depth is in the PARAMETER FILE's unit system (mm for METRIC, inches for ENGLISH); the engine does
not convert.  Times must increase, depths must not decrease (engine: 'decreasing depth value').

Sources (pick one)
  --from-wgew FILE   USDA-ARS WGEW DAP rain-gage breakpoint export (fetch_wgew_dap.py precip ...):
                     each gage's 'Time' start + 'Duration' minutes is placed on the run clock
                     given by --clock-origin HH:MM (all gages share it).
  --from-csv FILE    columns gage,time_min,depth (cumulative, already on the run clock).
  --from-gridded SRC --lat --lon --start YYYY-MM-DDTHH:MM --hours N
                     ONE gage from ki_tools_common.load_hourly_forcing (nasa_power|cmfd|mswx).
                     WARNING: grid-cell hourly rain smears convective storms (Walnut Gulch 2006:
                     NASA POWER wettest hour 1.9 mm/h vs gauge peaks of tens of mm/h) -- infiltration-
                     excess runoff will be strongly UNDER-predicted.  Last resort for ungauged sites.
Gage metadata (SAT, X, Y) are copied from --template PRE (blocks matched by gage id) or read from
--gauge-meta CSV (gage,x,y[,sat]).  With --tfin a final point is added at tfin + --hold-min holding
the storm total (the ARS sample file 4Aug80.pre does exactly this: 360 + 10 = 370).

Exit codes: 0 written and re-read OK | 2 bad input / validation failure
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import re
import sys
from collections import OrderedDict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _k2lib as k2  # noqa: E402


def _hhmm(s: str) -> int:
    h, m = s.strip().split(":")
    return int(h) * 60 + int(m)


def from_wgew(path: Path, origin_min: int, gages=None) -> OrderedDict:
    text = path.read_text(errors="replace")
    if "Breakpoint Data" not in text:
        raise ValueError(f"{path}: not a DAP rain BREAKPOINT export")
    unit = "in" if "depth in inches" in text.lower() else ("mm" if "depth in millimeters" in text.lower() else None)
    series = OrderedDict()
    starts = {}
    for line in text.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        p = [s.strip() for s in line.split(",")]
        gid, date, start, dur, depth = p[0], p[1], p[2], float(p[3]), float(p[4])
        if gages and gid not in gages:
            continue
        key = (gid, date, start)
        starts.setdefault(gid, set()).add((date, start))
        t = _hhmm(start) - origin_min + dur
        series.setdefault(gid, []).append((t, depth))
    multi = {g: s for g, s in starts.items() if len(s) > 1}
    if multi:
        raise ValueError(f"gage(s) {sorted(multi)} have more than one event in the export; fetch one storm "
                         f"(one day) per rainfall file")
    for gid, pts in series.items():
        if pts[0][0] < 0:
            raise ValueError(f"gage {gid} starts before the clock origin; use an earlier --clock-origin")
        if pts[0][0] > 0:
            pts.insert(0, (0.0, 0.0))
    return series, unit


def from_csv(path: Path) -> OrderedDict:
    series = OrderedDict()
    with open(path) as fh:
        for row in csv.DictReader(fh):
            series.setdefault(str(row["gage"]), []).append((float(row["time_min"]), float(row["depth"])))
    return series, None


def from_gridded(source, lat, lon, start, hours, units, forcing_dir=None):
    try:
        from ki_tools_common.load_forcing import load_hourly_forcing
    except ImportError:
        sys.path.insert(0, "KISSPATH_KI_TOOLS_COMMON")
        from ki_tools_common.load_forcing import load_hourly_forcing
    import numpy as np
    t0 = dt.datetime.fromisoformat(start)
    t1 = t0 + dt.timedelta(hours=hours)
    d = load_hourly_forcing(source, lat, lon, t0.year, t1.year, forcing_dir=forcing_dir, variables=["P"])
    dates = np.array([dt.datetime.fromisoformat(str(x)[:19]) for x in d["dates"]])
    step = float(d.get("timestep_seconds") or 3600) / 60.0
    p = np.asarray(d["precip_mm"], float)                     # mm per timestep (loader contract)
    sel = (dates >= t0) & (dates < t1)
    if not sel.any():
        raise ValueError("no forcing steps inside the requested window")
    if np.isnan(p[sel]).any():
        raise ValueError("forcing has gaps (NaN) in the window; refusing to invent rain")
    f = 1.0 if units == "metric" else 1.0 / k2.IN_TO_MM
    pts, cum = [(0.0, 0.0)], 0.0
    for i, (tt, pp) in enumerate(zip(dates[sel], p[sel])):
        cum += pp * f
        pts.append(((tt - t0).total_seconds() / 60.0 + step, cum))
    meta = {"source": source, "lat": lat, "lon": lon, "start": start, "hours": hours, "step_min": step,
            "max_step_mm": float(np.max(p[sel])), "total_mm": float(np.sum(p[sel]))}
    return OrderedDict([("1", pts)]), meta


def template_meta(path: Path) -> dict:
    tf = k2.read_tagged(path)
    out = {}
    for b in tf.blocks:
        m = re.search(r"(\d+)\s*$", b.label) or re.search(r"(\d+)", b.label)
        gid = m.group(1) if m else b.label
        out[gid] = {"sat": b.lookup("S")[0], "x": b.lookup("X")[0], "y": b.lookup("Y")[0], "block": b.name}
    return out


def write_pre(path: Path, series, meta: dict, depth_unit: str, header: list) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"! {h}" for h in header]
    for gid, pts in series.items():
        md = meta.get(gid, {})
        lines += ["", f"BEGIN GAGE {gid}"]
        if md.get("sat") is not None:
            lines.append(f"  SAT = {md['sat']}")
        if md.get("x") is not None and md.get("y") is not None:
            lines.append(f"  X = {md['x']}, Y = {md['y']}")
        lines += [f"  N = {len(pts)}", f"  TIME        DEPTH !({depth_unit})"]
        lines += [f"  {t:7.1f}     {d:10.4f}" for t, d in pts]
        lines.append("END")
    text = "\n".join(lines) + "\n"
    path.write_text(text)
    return text


def check(path: Path, units: str, n_gages: int) -> list:
    errs = []
    tf = k2.read_tagged(path)
    if len(tf.blocks) != n_gages:
        errs.append(f"re-read {len(tf.blocks)} blocks, wrote {n_gages}")
    for b in tf.blocks:
        n = int(b.get_float("N") or 0)
        ts = [b.get_float("T", i) for i in range(1, n + 1)]
        ds = [b.get_float("D", i) for i in range(1, n + 1)]
        if None in ts or None in ds:
            errs.append(f"{b.name}: N={n} but the engine lookup cannot read all TIME/DEPTH rows")
            continue
        if any(t2 <= t1 for t1, t2 in zip(ts, ts[1:])):
            errs.append(f"{b.name}: time not increasing")
        if any(d2 < d1 for d1, d2 in zip(ds, ds[1:])):
            errs.append(f"{b.name}: decreasing depth")
        if n_gages > 1 and (b.lookup("X")[0] is None or b.lookup("Y")[0] is None):
            errs.append(f"{b.name}: X/Y missing (required when there is more than one gage)")
    errs += k2.rain_units_check(tf, units)
    return errs


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--from-wgew"); src.add_argument("--from-csv"); src.add_argument("--from-gridded")
    ap.add_argument("--clock-origin", help="HH:MM local time that is minute 0 of the run (--from-wgew)")
    ap.add_argument("--gages", help="comma list to keep (default: all in the source)")
    ap.add_argument("--lat", type=float); ap.add_argument("--lon", type=float)
    ap.add_argument("--start", help="YYYY-MM-DDTHH:MM (--from-gridded)"); ap.add_argument("--hours", type=int)
    ap.add_argument("--forcing-dir")
    ap.add_argument("--units", choices=["metric", "english"], required=True,
                    help="the PARAMETER file's UNITS; depths are written in mm (metric) or inches (english)")
    ap.add_argument("--template", help="existing .pre to copy SAT/X/Y from, matched by gage id")
    ap.add_argument("--gauge-meta", help="CSV gage,x,y[,sat]")
    ap.add_argument("--sat", type=float, help="SAT for every gage (overrides template; overrides element SA!)")
    ap.add_argument("--tfin", type=float, help="run length; adds a final hold point at tfin + --hold-min")
    ap.add_argument("--hold-min", type=float, default=10.0)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    want_unit = "mm" if a.units == "metric" else "in"
    try:
        info = {}
        if a.from_wgew:
            if not a.clock_origin:
                raise ValueError("--from-wgew needs --clock-origin HH:MM")
            series, unit = from_wgew(Path(a.from_wgew), _hhmm(a.clock_origin),
                                     set(a.gages.split(",")) if a.gages else None)
            if unit and unit != want_unit:
                raise ValueError(f"export depths are in {unit} but the parameter file is {a.units} ({want_unit}); "
                                 f"re-fetch with --units {'inches' if want_unit == 'in' else 'mm'}")
            hdr = [f"Built from WGEW DAP export {Path(a.from_wgew).name}",
                   f"All gage elapsed times relative to {a.clock_origin}"]
        elif a.from_csv:
            series, _ = from_csv(Path(a.from_csv))
            hdr = [f"Built from {Path(a.from_csv).name} (times already on the run clock)"]
        else:
            if None in (a.lat, a.lon) or not a.start or not a.hours:
                raise ValueError("--from-gridded needs --lat --lon --start --hours")
            series, info = from_gridded(a.from_gridded, a.lat, a.lon, a.start, a.hours, a.units, a.forcing_dir)
            hdr = [f"Built from gridded {a.from_gridded} hourly precipitation at {a.lat},{a.lon} from {a.start}",
                   f"WARNING grid-cell rain: max step {info['max_step_mm']:.2f} mm -- convective peaks are smeared"]
            print(f"WARNING: {hdr[1]}; runoff will be under-predicted (dt_kineros2_036)", file=sys.stderr)
        if not series:
            raise ValueError("no gage data selected")
        meta = {}
        if a.template:
            meta = template_meta(Path(a.template))
        if a.gauge_meta:
            with open(a.gauge_meta) as fh:
                for row in csv.DictReader(fh):
                    meta[str(row["gage"])] = {"x": row["x"], "y": row["y"], "sat": row.get("sat") or None}
        if a.sat is not None:
            for g in series:
                meta.setdefault(g, {})["sat"] = a.sat
        missing = [g for g in series if g not in meta] if (a.template or a.gauge_meta) else []
        if missing:
            raise ValueError(f"no SAT/X/Y metadata for gage(s) {missing} in the template/gauge-meta")
        if a.tfin:
            for g, pts in series.items():
                if pts[-1][0] < a.tfin + a.hold_min:
                    pts.append((a.tfin + a.hold_min, pts[-1][1]))
        out = Path(a.out)
        write_pre(out, series, meta, want_unit, hdr)
        errs = check(out, a.units, len(series))
        for e in errs:
            print(f"ERROR: {e}", file=sys.stderr)
        tot = {g: round(float(pts[-1][1]), 4) for g, pts in series.items()}
        print(f"wrote {out}: {len(series)} gage(s); storm totals ({want_unit}) {tot}")
        return 2 if errs else 0
    except (ValueError, KeyError, FileNotFoundError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
