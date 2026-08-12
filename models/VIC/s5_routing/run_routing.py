#!/usr/bin/env python3
"""
s5_routing/run_routing.py — run the Lohmann `route_1.0` binary for a basin whose
routing grid was already built by ``s5_routing/build_routing_param.py`` (step s9),
and inspect the impulse response it produces.

VIC does NOT route (dt_vic_019).  Step s10 of SKILL.md's chain is this binary.
Before this module every run_and_score_*.py re-implemented the same three things
inline, and each copy carried the same three traps:

  1. the 7-column flux -> `vic_in` slice, which is valid ONLY for the exact
     21-OUTVAR order of docs/vic_param/global_param_template.txt (dt_vic_027);
  2. `rout` opens ``<STA>.uh_s`` with Fortran ``status='new'`` — a stale file from a
     previous run makes it die, and a *copied* one silently reuses the previous
     velocity's unit hydrograph (dt_vic_029);
  3. nobody ever checked that the routed travel time was plausible for the basin.
     VELOCITY defaults to 1.5 m/s, tuned at Bengbu (121,330 km2).  At 哈尔滨
     (398,330 km2) that yields a basin-mean travel time of 6.2 d against an
     observed lag of ~28 d, capping r at 0.59 and NSE at 0.35 (dt_vic_028).

Public API
----------
    prepare_vic_in(vic_result_dir, vic_in_dir, prefix) -> int
    route(routing_param_dir, velocity, diffusivity, ...) -> pandas.Series (m3/s, daily)
    basin_mean_uh_lag(uh_s_path) -> dict
    observed_lag_days(obs, sim, max_lag=60) -> dict

`route()` is pure: it never mutates ``routing_param/``; each call gets its own
scratch directory, so a (velocity, diffusivity) sweep is safe to parallelise.
One call costs ~7 s for 866 cells because it reuses the VIC flux output —
velocity and diffusivity affect ONLY the routing stage, never vic_classic.exe.
"""
from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd

ROUT_EXE = os.environ.get(
    "VIC_ROUT_EXE", "/mnt/disk1/Hydrocraft_server/model/route_1.0/src/rout")

# The 7 columns Lohmann `rout` reads: year month day prec evap runoff baseflow.
# Indices into the ASCII flux file of the KI's 21-OUTVAR global param template.
FLUX_COLS_FOR_ROUT = [0, 1, 2, 3, 18, 16, 17]
FLUX_HEADER_LINES = 3          # '# SIMULATION', '# MODEL_VERSION', column header

# VIC names flux files '<OUTFILE>_fluxes_<LAT>_<LON>[.txt]'.  Do NOT use [\d.]+ for the
# coordinates: it is greedy and swallows the '.' of the '.txt' suffix, so the longitude
# parses as '127.6250.' and float() raises (or, worse, an unanchored variant silently
# writes 'fluxes_45.1250_126.6250.' into vic_in, which `rout` then never opens).
# Anchor on the end of the name, with the extension optional — `rout`'s own vic_in
# files carry no extension, VIC's flux files carry '.txt'.
FLUX_NAME_RE = re.compile(
    r"fluxes_(-?\d+(?:\.\d+)?)_(-?\d+(?:\.\d+)?)(?:\.txt)?$")

# rout.f PARAMETERs — exceeding these is silent corruption, so assert instead.
ROUT_UH_DAY = 96               # max routed impulse-response length, days
ROUT_PMAX = 10000              # max upstream cells


# ---------------------------------------------------------------------------
def prepare_vic_in(vic_result_dir, vic_in_dir, prefix, overwrite=False) -> int:
    """Slice every VIC flux file down to the 7 columns `rout` expects.

    Writes ``<vic_in_dir>/fluxes_<LAT>_<LON>`` (rout's hard-coded naming).
    Returns the number of cells written.  Resumable: existing files are kept
    unless ``overwrite``.
    """
    vic_result_dir, vic_in_dir = Path(vic_result_dir), Path(vic_in_dir)
    vic_in_dir.mkdir(parents=True, exist_ok=True)

    src = sorted(vic_result_dir.glob(f"{prefix}*fluxes_*"))
    if not src:
        src = sorted(vic_result_dir.glob("*fluxes_*"))
    if not src:
        raise FileNotFoundError(f"no VIC flux files under {vic_result_dir}")

    n = 0
    for f in src:
        m = FLUX_NAME_RE.search(f.name)
        if not m:
            continue
        out = vic_in_dir / f"fluxes_{m.group(1)}_{m.group(2)}"
        if out.exists() and out.stat().st_size > 0 and not overwrite:
            n += 1
            continue
        d = pd.read_csv(f, sep=r"\s+", skiprows=FLUX_HEADER_LINES, header=None)
        if d.shape[1] <= max(FLUX_COLS_FOR_ROUT):
            raise ValueError(
                f"{f.name} has {d.shape[1]} columns; the 7-column rout slice "
                f"{FLUX_COLS_FOR_ROUT} needs >= {max(FLUX_COLS_FOR_ROUT) + 1}. "
                "The global param OUTVAR list was reordered — see dt_vic_027.")
        d.iloc[:, FLUX_COLS_FOR_ROUT].to_csv(
            out, sep="\t", header=False, index=False, float_format="%.4f")
        n += 1

    if n == 0:
        raise ValueError(
            f"{len(src)} flux files under {vic_result_dir} but none matched "
            f"{FLUX_NAME_RE.pattern!r} — refusing to hand `rout` an empty vic_in "
            f"(it would route zeros and still exit 0). Example: {src[0].name}")
    if n > ROUT_PMAX:
        raise ValueError(f"{n} cells exceeds rout.f PMAX={ROUT_PMAX}")
    return n


# ---------------------------------------------------------------------------
def _rout_global(station, velocity, diffusivity, y0, m0, y1, m1,
                 write_y0=None, write_m0=None, write_y1=None, write_m1=None) -> str:
    return f"""# Routing Information File for {station} (generated by s5_routing/run_routing.py)
# NAME OF FLOW DIRECTION FILE
./{station}_direc.txt
# NAME OF VELOCITY FILE
.false.
{velocity}
# NAME OF DIFF FILE
.false.
{diffusivity}
# NAME OF XMASK FILE
.true.
./{station}_xmask.txt
# NAME OF FRACTION FILE
.true.
./{station}_frac.txt
# NAME OF STATION FILE
./{station}_staloc.txt
# PATH OF INPUT FILES AND PRECISION
./vic_in/fluxes_
4
# PATH OF OUTPUT FILES
./rout_out/
# YEAR AND MONTH OF VIC OUTPUT TO ROUTE & ROUTED OUTPUT TO WRITE
{y0} {m0:02d} {y1} {m1:02d}
{write_y0 or y0} {(write_m0 or m0):02d} {write_y1 or y1} {(write_m1 or m1):02d}
# NAME OF UNIT HYDROGRAPH FILE
./UH.all
"""


def route(routing_param_dir, velocity=1.5, diffusivity=800.0,
          route_start=(1980, 1), route_end=(1987, 12),
          write_start=None, write_end=None,
          station=None, scratch=None, keep_scratch=False, timeout=1800):
    """Run the real Lohmann `rout` binary and return daily discharge in m3/s.

    Never mutates ``routing_param_dir``.  ``velocity`` (m/s) and ``diffusivity``
    (m2/s) are the two Lohmann (1996) channel parameters; they change the unit
    hydrograph only, so no VIC re-run is needed.

    Returns a ``pandas.Series`` indexed by date.  Attaches ``.attrs['uh_lag_days']``
    and ``.attrs['uh_s_path']``.
    """
    src = Path(routing_param_dir)
    station = station or os.environ.get("VIC_STATION_NAME") or _infer_station(src)

    scratch = Path(scratch or (src / "scratch" / f"v{velocity}_d{diffusivity}"))
    if scratch.exists():
        shutil.rmtree(scratch)
    (scratch / "rout_out").mkdir(parents=True)

    for suffix in ("_direc.txt", "_frac.txt", "_xmask.txt", "_staloc.txt"):
        shutil.copy(src / f"{station}{suffix}", scratch / f"{station}{suffix}")
    shutil.copy(src / "UH.all", scratch / "UH.all")

    vic_in = src / "vic_in"
    if not vic_in.is_dir():
        raise FileNotFoundError(f"{vic_in} missing — call prepare_vic_in() first")
    (scratch / "vic_in").symlink_to(vic_in)

    # dt_vic_029: rout does `open(98, file=NAME5//'.uh_s', status='new')`.  The
    # scratch dir is fresh, so the file cannot exist -- which is exactly the point:
    # copying a stale .uh_s in would silently reuse the PREVIOUS velocity's UH.
    (scratch / "rout_global.txt").write_text(_rout_global(
        station, velocity, diffusivity,
        route_start[0], route_start[1], route_end[0], route_end[1],
        *(write_start or (None, None)), *(write_end or (None, None))))

    log = scratch / "rout.log"
    with open(log, "w") as fh:
        rc = subprocess.call([ROUT_EXE, "rout_global.txt"], cwd=scratch,
                             stdout=fh, stderr=subprocess.STDOUT, timeout=timeout)
    if rc != 0:
        raise RuntimeError(f"rout rc={rc}; see {log}\n{log.read_text()[-1500:]}")

    # rout pads the station name to 5 chars (NAME5), so the file is 'HRB  .day'
    day = sorted((scratch / "rout_out").glob("*.day"))
    day = [p for p in day if not p.name.endswith(".day_mm")]
    if not day or day[0].stat().st_size == 0:
        raise RuntimeError(f"rout wrote no .day output; see {log}")

    d = pd.read_csv(day[0], sep=r"\s+", header=None, names=["y", "m", "d", "q"])
    s = pd.Series(d["q"].values,
                  index=pd.to_datetime(dict(year=d.y, month=d.m, day=d.d)),
                  name="discharge_m3s")

    uh = sorted(scratch.glob("*.uh_s"))
    if uh:
        s.attrs["uh_lag_days"] = basin_mean_uh_lag(uh[0])["basin_mean_lag_days"]
        s.attrs["uh_s_path"] = str(uh[0])
    s.attrs["velocity"] = velocity
    s.attrs["diffusivity"] = diffusivity

    if not keep_scratch:
        shutil.rmtree(scratch, ignore_errors=True)
    return s


def _infer_station(src: Path) -> str:
    cand = sorted(src.glob("*_staloc.txt"))
    if not cand:
        raise FileNotFoundError(f"no *_staloc.txt in {src}; set VIC_STATION_NAME")
    return cand[0].name[:-len("_staloc.txt")]


# ---------------------------------------------------------------------------
def basin_mean_uh_lag(uh_s_path) -> dict:
    """Mean travel time of the routed impulse response, from rout's own .uh_s.

    This is the number to compare against the observed lag BEFORE trusting a
    hydrograph.  ``rout`` renormalises UH_S (unit_hyd_routines.f), so the routing
    is mass-conserving at any velocity — a wrong velocity shifts timing, never
    volume.  A velocity error therefore shows up in `r`/NSE and NEVER in PBIAS.
    """
    u = np.loadtxt(uh_s_path)
    if u.ndim == 1:
        u = u[None, :]
    t = np.arange(1, u.shape[1] + 1)
    per_cell = (u * t).sum(1) / u.sum(1)
    mean_uh = u.mean(0)
    mean_uh = mean_uh / mean_uh.sum()
    tail = float(mean_uh[ROUT_UH_DAY - 1:].sum())
    return {
        "n_cells": int(u.shape[0]),
        "basin_mean_lag_days": float((mean_uh * t).sum()),
        "cell_lag_min_days": float(per_cell.min()),
        "cell_lag_max_days": float(per_cell.max()),
        "peak_day": int(t[mean_uh.argmax()]),
        "mass_beyond_UH_DAY": tail,
        "truncated": bool(tail > 1e-3),
    }


def observed_lag_days(obs: pd.Series, sim: pd.Series, max_lag: int = 60) -> dict:
    """Lag (days) at which sim best correlates with obs, and the r it reaches.

    ``best_lag > 0`` means the simulation is EARLY — the routed travel time is too
    short.  Because ``r`` caps NSE at ``r**2``, run this before concluding that a
    poor NSE needs soil-parameter calibration: at 哈尔滨 the zero-lag r of 0.589
    capped NSE at 0.347, and no soil parameter could have lifted it (dt_vic_028).
    """
    j = pd.DataFrame({"obs": obs, "sim": sim}).dropna()
    if len(j) < 30:
        raise ValueError(f"only {len(j)} paired days")
    scan = {L: j.obs.corr(j.sim.shift(L)) for L in range(0, max_lag + 1)}
    best = max(scan, key=lambda k: scan[k])
    return {
        "best_lag_days": int(best),
        "r_at_best_lag": float(scan[best]),
        "r_at_zero_lag": float(scan[0]),
        "nse_ceiling_at_zero_lag": float(scan[0] ** 2),
        "sim_leads_obs": bool(best > 0),
    }


if __name__ == "__main__":  # pragma: no cover
    import argparse
    import json
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("routing_param_dir")
    ap.add_argument("--velocity", type=float, default=1.5)
    ap.add_argument("--diffusivity", type=float, default=800.0)
    ap.add_argument("--route-start", default="1980-01")
    ap.add_argument("--route-end", default="1987-12")
    ap.add_argument("--out", default=None, help="write routed daily CSV here")
    a = ap.parse_args()
    ys, ms = (int(x) for x in a.route_start.split("-"))
    ye, me = (int(x) for x in a.route_end.split("-"))
    s = route(a.routing_param_dir, a.velocity, a.diffusivity, (ys, ms), (ye, me))
    print(json.dumps({"n_days": len(s), "mean_m3s": float(s.mean()),
                      "uh_lag_days": s.attrs.get("uh_lag_days")}, indent=2))
    if a.out:
        s.to_csv(a.out)
