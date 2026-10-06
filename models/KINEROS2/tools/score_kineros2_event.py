#!/usr/bin/env python3
"""score_kineros2_event.py -- compare a REAL-engine KINEROS2 outlet hydrograph with an observed one.

Event metrics for a single storm, computed in ABSOLUTE units (m3/s, m3) -- never in depth,
because the modelled contributing area and the gauge's nominal drainage area can differ
(Walnut Gulch flume 11: model 1551 ac, flume 2035 ac; the eastern part sits behind stock ponds).

Inputs
  --sim   run_result.json written by run_kineros2_engine.py (uses its outlet hydrograph CSV and
          its unit system), or a hydrograph CSV with columns time_min,...,discharge
  --sim-units  english|metric (only needed for a bare CSV)
  --obs   observed breakpoint file: either a USDA-ARS WGEW DAP runoff text export
          (eventID,Flume,Date,Start_Time,Elapsed_Time,Runoff_Rate,...; rate in cfs when the
          export header says 'Cubic Feet per Second') or a CSV with columns time_min,discharge_m3s
  --obs-offset-min  minutes from the rain-file clock origin to the obs time zero
          (WGEW 4 Aug 1980: rain clock 12:35, flume start 13:27 -> 52)

  --clock-origin  local date-time of the rain-file clock origin (gives metrics real timestamps)

Method: observed breakpoints are linearly interpolated onto the simulated output times
(zero outside the observed record, as the flume reads no flow there); NSE/KGE/PBIAS/r from
ki_tools_common.metrics.all_metrics; peak and volume errors from the curves themselves
(volume by trapezoid on each curve's own times).  Writes score.json, the paired obs/sim CSV that
was scored (<out stem>_paired.csv) and an optional figure.

Exit codes: 0 scored | 2 bad input
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _k2lib as k2  # noqa: E402


def _all_metrics(obs, sim, dates=None):
    try:
        from ki_tools_common.metrics import all_metrics
    except ImportError:
        sys.path.insert(0, "KISSPATH_KI_TOOLS_COMMON")
        from ki_tools_common.metrics import all_metrics
    return all_metrics(np.asarray(obs, float), np.asarray(sim, float), dates=dates, label="headline",
                       meta={"unit": "m3/s", "dates_applicable": dates is not None})


def event_dates(ts, clock_origin):
    """Wall-clock timestamps for minutes after the rain-file clock origin ('YYYY-MM-DD HH:MM')."""
    if not clock_origin:
        return None
    import pandas as pd
    return pd.Timestamp(clock_origin) + pd.to_timedelta(np.asarray(ts, float), unit="min")


def read_sim(path: Path, units: str | None):
    """Return (time_min, discharge_m3s, meta)."""
    meta = {"source": str(path)}
    if path.suffix == ".json":
        res = json.loads(path.read_text())
        if res.get("status") != "success":
            raise ValueError(f"{path}: run status is {res.get('status')!r}, refusing to score a failed run")
        units = res.get("units")
        outlet = res.get("outlet") or {}
        want = f"hydrograph_{str(outlet.get('type', '')).lower()}_{outlet.get('id')}.csv"
        cands = [Path(f) for f in res.get("hydrograph_files") or [] if Path(f).name == want]
        if not cands:
            raise ValueError(f"{path}: outlet {outlet.get('type')} {outlet.get('id')} has no hydrograph CSV "
                             f"(set PRINT = 2 on the outlet element and re-run)")
        path = cands[0]
        meta.update(run_result=str(meta["source"]), hydrograph=str(path), outlet=outlet)
    if units not in ("english", "metric"):
        raise ValueError("unknown sim units: pass --sim-units english|metric")
    t, q = [], []
    with open(path) as fh:
        for row in csv.DictReader(fh):
            t.append(float(row["time_min"]))
            q.append(float(row["discharge"]))
    f = k2.FT3_TO_M3 if units == "english" else 1.0
    meta["sim_units"] = units
    return np.array(t), np.array(q) * f, meta


def read_obs(path: Path):
    """Return (time_min_from_obs_zero, discharge_m3s, meta)."""
    text = path.read_text(errors="replace")
    meta = {"source": str(path)}
    if "Runoff_Rate" in text and "Elapsed_Time" in text:
        if "Cubic Feet per Second" not in text:
            raise ValueError(f"{path}: DAP export is not in cfs (header lacks 'Cubic Feet per Second'); "
                             f"re-export with units=cf -- a mm/hr export is per NOMINAL flume area")
        t, q = [], []
        for line in text.splitlines():
            if line.startswith("#") or not line.strip():
                continue
            p = [s.strip() for s in line.split(",")]
            if len(p) < 6:
                continue
            t.append(float(p[3]))
            q.append(float(p[4]))
            meta.setdefault("date", p[1]); meta.setdefault("start_time", p[2]); meta.setdefault("flume", p[0])
        mm = re.search(r"#Flume\s+\d+:(\d+(?:\.\d+)?)", text)
        if mm:
            meta["flume_area_acres"] = float(mm.group(1))
        meta["format"] = "WGEW DAP runoff breakpoint export (cfs)"
        return np.array(t), np.array(q) * k2.FT3_TO_M3, meta
    t, q = [], []
    with open(path) as fh:
        for row in csv.DictReader(fh):
            t.append(float(row["time_min"]))
            q.append(float(row["discharge_m3s"]))
    meta["format"] = "csv time_min,discharge_m3s"
    return np.array(t), np.array(q), meta


def _volume(t_min, q):
    return float(np.trapezoid(q, t_min * 60.0)) if hasattr(np, "trapezoid") else float(np.trapz(q, t_min * 60.0))


def score(ts, qs, to, qo, dates=None):
    qo_on_sim = np.interp(ts, to, qo, left=0.0, right=0.0)
    m = _all_metrics(qo_on_sim, qs, dates)
    ip_s, ip_o = int(np.argmax(qs)), int(np.argmax(qo))
    vol_s, vol_o = _volume(ts, qs), _volume(to, qo)
    return {
        "n_points": int(len(ts)),
        "nse": m.get("NSE"), "kge": m.get("KGE"), "pbias_pct": m.get("PBIAS"), "r": m.get("r"),
        "rmse_m3s": m.get("RMSE"),
        "peak_obs_m3s": float(qo[ip_o]), "peak_sim_m3s": float(qs[ip_s]),
        "peak_error_pct": 100.0 * (qs[ip_s] - qo[ip_o]) / qo[ip_o] if qo[ip_o] else None,
        "time_to_peak_obs_min": float(to[ip_o]), "time_to_peak_sim_min": float(ts[ip_s]),
        "peak_timing_error_min": float(ts[ip_s] - to[ip_o]),
        "volume_obs_m3": vol_o, "volume_sim_m3": vol_s,
        "volume_error_pct": 100.0 * (vol_s - vol_o) / vol_o if vol_o else None,
        "metric_note": "NSE/KGE/PBIAS/r on the sim time grid with obs interpolated (0 outside its record); "
                       "volumes integrate each curve on its own times",
    }


def figure(path, ts, qs, to, qo, sc, title):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(to, qo, color="black", lw=1.8, marker="o", ms=3, label="observed (flume)")
    ax.plot(ts, qs, color="#2563EB", lw=1.8, label="KINEROS2 (real engine)")
    ax.set_xlabel("minutes after rain-file clock origin")
    ax.set_ylabel("outlet discharge (m$^3$/s)")
    ax.set_title(title)
    hi = max(float(np.max(to)), float(ts[np.nonzero(qs > 0.001 * qs.max())[0][-1]]) if qs.max() > 0 else 60.0)
    ax.set_xlim(0, hi + 15)
    txt = (f"NSE {sc['nse']:.3f}   KGE {sc['kge']:.3f}   r {sc['r']:.3f}\n"
           f"peak obs {sc['peak_obs_m3s']:.2f}  sim {sc['peak_sim_m3s']:.2f} m$^3$/s ({sc['peak_error_pct']:+.1f}%)\n"
           f"time to peak obs {sc['time_to_peak_obs_min']:.1f}  sim {sc['time_to_peak_sim_min']:.1f} min\n"
           f"volume obs {sc['volume_obs_m3']:.0f}  sim {sc['volume_sim_m3']:.0f} m$^3$ ({sc['volume_error_pct']:+.1f}%)")
    ax.text(0.98, 0.97, txt, transform=ax.transAxes, ha="right", va="top", fontsize=9,
            bbox=dict(boxstyle="round", fc="white", ec="0.6"))
    ax.legend(loc="center right")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sim", required=True)
    ap.add_argument("--sim-units", choices=["english", "metric"])
    ap.add_argument("--obs", required=True)
    ap.add_argument("--obs-offset-min", type=float, required=True,
                    help="minutes from the rain-file clock origin to observed time zero")
    ap.add_argument("--out", required=True, help="score JSON path")
    ap.add_argument("--figure", help="PNG path (observed black, simulated #2563EB)")
    ap.add_argument("--title", default="KINEROS2 outlet hydrograph vs observed")
    ap.add_argument("--clock-origin", help="local date-time of the rain-file clock origin, 'YYYY-MM-DD HH:MM' "
                    "(WG11 4 Aug 1980: '1980-08-04 12:35'); gives the scored series real timestamps")
    ap.add_argument("--paired-csv", help="aligned series actually scored (date,time_min,obs,sim in m3/s); "
                    "default: <out stem>_paired.csv")
    a = ap.parse_args(argv)
    try:
        ts, qs, smeta = read_sim(Path(a.sim), a.sim_units)
        to, qo, ometa = read_obs(Path(a.obs))
    except (ValueError, KeyError, FileNotFoundError) as e:
        print(f"INPUT ERROR: {e}", file=sys.stderr)
        return 2
    to = to + a.obs_offset_min
    try:
        dates = event_dates(ts, a.clock_origin)
    except ValueError as e:
        print(f"INPUT ERROR: --clock-origin: {e}", file=sys.stderr)
        return 2
    sc = score(ts, qs, to, qo, dates)
    paired = Path(a.paired_csv) if a.paired_csv else Path(a.out).with_name(Path(a.out).stem + "_paired.csv")
    paired.parent.mkdir(parents=True, exist_ok=True)
    qo_on_sim = np.interp(ts, to, qo, left=0.0, right=0.0)
    with open(paired, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["date", "time_min", "obs", "sim"])
        for i in range(len(ts)):
            w.writerow([dates[i].strftime("%Y-%m-%d %H:%M:%S") if dates is not None else "",
                        f"{ts[i]:g}", f"{qo_on_sim[i]:.6f}", f"{qs[i]:.6f}"])
    out = {"tool": "score_kineros2_event.py", "sim": smeta, "obs": ometa,
           "obs_offset_min": a.obs_offset_min, "clock_origin": a.clock_origin,
           "paired_csv": str(paired), "metrics": sc}
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    k2.write_json(a.out, out)
    if a.figure:
        figure(a.figure, ts, qs, to, qo, sc, a.title)
    for k, v in sc.items():
        if k != "metric_note":
            print(f"  {k:24s} {v:.4g}" if isinstance(v, float) else f"  {k:24s} {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
