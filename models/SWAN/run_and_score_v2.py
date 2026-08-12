#!/usr/bin/env python3
"""
SWAN verifier (verify_2): significant wave height (HSIGN) at NDBC buoy 41002
(South Hatteras, US Atlantic / South Atlantic Bight, deep water), 2020.

Twin of the real-case (NDBC 42002, West Gulf of Mexico). Same KI pipeline and
same physical recipe applied at a DIFFERENT ocean basin to check consistency:
  - Flat deep-water Cartesian SWAN domain (800 km, 30x30 cells), buoy at centre.
  - Forced by the buoy's OWN measured 10-min wind (WSPD/WDIR) resampled hourly,
    converted from anemometer height (~4.1 m) to U10 via neutral log law, applied
    as a spatially-uniform, time-varying wind field.
  - GEN3 wind-sea physics + a CLIMATOLOGICAL background swell boundary whose Hs
    is set from THIS buoy's calm-wind (<4 m/s) Hs floor (1.0 m for 41002, the
    same methodology that gave 0.8 m for 42002), 30-min comp step, 24-h spin-up
    dropped.
  - Output hourly Hsig at the buoy; score against measured WVHT via all_metrics.

Resumable: if buoy.crv already exists and is non-empty, the SWAN run is skipped
and only parsing+scoring is redone. Writes the verifier result.json as the final
action.

Pipeline tools used: tools/run_swan.py (validate_swn_inputs, run_swan_binary),
tools/parse_swan_output.py (parse_table), ki_tools_common.metrics.all_metrics.
"""
import os, sys, shutil, subprocess, time, json, datetime
import numpy as np

KI    = "/mnt/disk1/Hydrocraft_server/models/SWAN/knowledge_infrastructure"
TOOLS = os.path.join(KI, "tools")
sys.path.insert(0, TOOLS)

import run_swan as RS
import parse_swan_output as PS
from ki_tools_common.metrics import all_metrics

# ---------------------------------------------------------------- config
BUOY     = "41002"
OBS_FILE = f"/mnt/disk1/Hydrocraft_server/data/obs/ndbc_buoys/{BUOY}_stdmet_2020.txt"
SWAN_EXE = ("/home/server/knowledge-dissection-toolkit/auto_dissect/_work/ADCIRC"
            "/source/repo/thirdparty/swan/swan.exe")
SWANINIT = "/mnt/disk1/Hydrocraft_server/outputs/swan_lekima/swaninit"
DET      = "/mnt/disk1/Hydrocraft_server/models/SWAN/detached/verify_2"
WORK     = os.environ.get("SWAN_WORK",   os.path.join(DET, "swanrun"))
RESULT   = os.environ.get("SWAN_RESULT", os.path.join(DET, "result.json"))

ANEM_H   = 4.1          # anemometer height (m), 3-m discus default (==real-case)
Z0       = 0.0002       # roughness for neutral log law (m)
U10_FAC  = np.log(10.0 / Z0) / np.log(ANEM_H / Z0)   # ~1.09

# --- recipe config (identical to real-case except site-derived swell floor) ---
L         = float(os.environ.get("SWAN_L", "800000"))
NC        = int(os.environ.get("SWAN_NC", "30"))
DT_MIN    = int(os.environ.get("SWAN_DT_MIN", "30"))
DEPTH     = float(os.environ.get("SWAN_DEPTH", "3000"))
# climatological background swell = THIS buoy's calm-wind Hs floor (calm mean 1.06)
SWELL_HS  = float(os.environ.get("SWAN_SWELL_HS", "1.0"))
SWELL_TP  = float(os.environ.get("SWAN_SWELL_TP", "9"))
SWELL_DIR = float(os.environ.get("SWAN_SWELL_DIR", "90"))
CEN       = L / 2.0
T0 = datetime.datetime.strptime(os.environ.get("SWAN_T0", "20200101"), "%Y%m%d")
T1 = datetime.datetime.strptime(os.environ.get("SWAN_T1", "20210101"), "%Y%m%d")

os.makedirs(WORK, exist_ok=True)
os.makedirs(os.path.dirname(RESULT), exist_ok=True)


# ---------------------------------------------------------------- obs / wind
def read_ndbc(path):
    rows = []
    with open(path) as f:
        for ln in f:
            if ln.startswith('#'):
                continue
            p = ln.split()
            if len(p) < 9:
                continue
            try:
                yy, mo, dd, hh, mm = (int(p[i]) for i in range(5))
                wdir = float(p[5]); wspd = float(p[6]); wvht = float(p[8])
            except ValueError:
                continue
            t = datetime.datetime(yy, mo, dd, hh, mm)
            rows.append((t, wdir, wspd, wvht))
    return rows


def hourly_series(rows):
    wind_bins = {}
    wv_bins   = {}
    for t, wdir, wspd, wvht in rows:
        hr = t.replace(minute=0, second=0)
        if wspd < 90.0 and wdir <= 360.0:
            th = np.deg2rad(wdir)
            u = -wspd * np.sin(th)
            v = -wspd * np.cos(th)
            wind_bins.setdefault(hr, []).append((u, v))
        if wvht < 90.0:
            wv_bins.setdefault(hr, []).append(wvht)
    wind = {h: (np.mean([a[0] for a in v]), np.mean([a[1] for a in v]))
            for h, v in wind_bins.items()}
    wv   = {h: float(np.mean(v)) for h, v in wv_bins.items()}
    return wind, wv


def build_wind_file(wind, path):
    times = []
    t = T0
    while t <= T1:
        times.append(t); t += datetime.timedelta(hours=1)
    have = sorted(wind.keys())
    if not have:
        raise RuntimeError("no valid wind samples")
    u_arr = np.full(len(times), np.nan); v_arr = np.full(len(times), np.nan)
    for i, tt in enumerate(times):
        if tt in wind:
            u_arr[i], v_arr[i] = wind[tt]

    def fill(a):
        last = None
        for i in range(len(a)):
            if not np.isnan(a[i]): last = a[i]
            elif last is not None: a[i] = last
        last = None
        for i in range(len(a) - 1, -1, -1):
            if not np.isnan(a[i]): last = a[i]
            elif last is not None: a[i] = last
        return a
    u_arr = fill(u_arr) * U10_FAC
    v_arr = fill(v_arr) * U10_FAC
    with open(path, 'w') as f:
        for i in range(len(times)):
            u, v = u_arr[i], v_arr[i]
            f.write(f"{u:.3f} {u:.3f}\n{u:.3f} {u:.3f}\n")
            f.write(f"{v:.3f} {v:.3f}\n{v:.3f} {v:.3f}\n")
    spd = np.sqrt(u_arr**2 + v_arr**2)
    print(f"[wind] {len(times)} hourly fields, U10 max {spd.max():.1f} m/s "
          f"mean {spd.mean():.1f} m/s")
    return times


def build_bot(path, depth=DEPTH):
    with open(path, 'w') as f:
        f.write(f"{depth:.1f} {depth:.1f}\n{depth:.1f} {depth:.1f}\n")


def write_swn(path):
    t0s = T0.strftime('%Y%m%d.%H%M%S')
    t1s = T1.strftime('%Y%m%d.%H%M%S')
    if SWELL_HS > 0:
        boun = ("$\n$ -- climatological background swell on all open sides\n"
                "BOUN SHAPE JONSWAP PEAK DSPR POWER\n"
                + "".join(f"BOUN SIDE {s} CCW CONSTANT PAR "
                          f"{SWELL_HS:.2f} {SWELL_TP:.1f} {SWELL_DIR:.0f} 8\n"
                          for s in ("N", "S", "E", "W")))
    else:
        boun = ""
    swn = f"""PROJ 'NDBC41002' 'V02'
SET LEVEL=0.0 DEPMIN=0.05 NAUTICAL
MODE NONSTAT
COORDINATES CARTESIAN
$
CGRID REGULAR 0. 0. 0. {L:.0f} {L:.0f} {NC} {NC} CIRCLE 36 0.04 1.0 31
$
$ -- flat deep bathymetry (positive down)
INPGRID BOTTOM REGULAR 0. 0. 0. 1 1 {L:.0f} {L:.0f}
READINP BOTTOM 1.0 'flat.bot' 4 0 FREE
$
$ -- spatially-uniform, time-varying wind from buoy (U east, V north)
INPGRID WIND REGULAR 0. 0. 0. 1 1 {L:.0f} {L:.0f} NONSTATIONARY {t0s} 1 HR {t1s}
READINP WIND 1.0 'wind.wnd' 4 0 FREE
{boun}$
$ -- physics: deep-water wind-sea generation
GEN3
$
NUM ACCUR 0.02 0.02 0.02 98.0 NONSTAT 2
$
POINTS 'B1' {CEN:.0f} {CEN:.0f}
TABLE 'B1' HEAD 'buoy.crv' TIME HSIG OUTPUT {t0s} 1.0 HR
$
COMPUTE NONSTAT {t0s} {DT_MIN} MIN {t1s}
$
STOP
"""
    with open(path, 'w') as f:
        f.write(swn)
    shutil.copy(path, os.path.join(os.path.dirname(path), "INPUT"))


# ---------------------------------------------------------------- run
def main():
    rows = read_ndbc(OBS_FILE)
    wind, wv = hourly_series(rows)
    print(f"[obs] hourly WVHT points: {len(wv)}  hourly wind hours: {len(wind)}")

    crv = os.path.join(WORK, "buoy.crv")
    swn = os.path.join(WORK, f"ndbc{BUOY}.swn")

    if not (os.path.isfile(crv) and os.path.getsize(crv) > 0):
        build_wind_file(wind, os.path.join(WORK, "wind.wnd"))
        build_bot(os.path.join(WORK, "flat.bot"))
        write_swn(swn)
        if os.path.isfile(SWANINIT):
            shutil.copy(SWANINIT, os.path.join(WORK, "swaninit"))
        pre = RS.validate_swn_inputs(swn, SWAN_EXE)
        print("[preflight]", pre['status'], "missing:", pre.get('missing_files'))
        t0 = time.time()
        res = RS.run_swan_binary(swn, swan_binary=SWAN_EXE, work_dir=WORK,
                                 timeout=86400, verbose=True)
        print(f"[swan] {res['status']} rc={res['return_code']} "
              f"runtime={res.get('runtime_s')}s ({(time.time()-t0)/60:.1f} min)")
        if not os.path.isfile(crv) or os.path.getsize(crv) == 0:
            raise RuntimeError(f"SWAN produced no buoy.crv (status={res['status']})")

    tab = PS.parse_table(crv)
    cols = [c.upper() for c in tab.get('columns', [])]
    data = tab['data']

    def col(name_options):
        for i, c in enumerate(cols):
            if c in name_options:
                return data[:, i]
        return None
    tcol = col({'TIME'})
    hcol = col({'HSIG', 'HSIGN', 'HS'})
    if tcol is None or hcol is None:
        tcol = data[:, 0]; hcol = data[:, 1]

    sim = {}
    for tv, hv in zip(tcol, hcol):
        s = f"{tv:.6f}"
        ymd, hms = s.split('.')
        ymd = ymd.zfill(8); hms = hms.ljust(6, '0')
        try:
            t = datetime.datetime(int(ymd[0:4]), int(ymd[4:6]), int(ymd[6:8]),
                                  int(hms[0:2]), int(hms[2:4]), int(hms[4:6]))
        except ValueError:
            continue
        if hv >= 0 and hv < 30:
            sim[t.replace(minute=0, second=0)] = float(hv)

    spinup_h = int(os.environ.get("SWAN_SPINUP_H", "24"))
    score_start = T0 + datetime.timedelta(hours=spinup_h)
    common = sorted(t for t in (set(sim.keys()) & set(wv.keys()))
                    if t >= score_start)
    obs_s = np.array([wv[t] for t in common])
    sim_s = np.array([sim[t] for t in common])
    print(f"[pair] overlapping hourly points: {len(common)}")

    m = all_metrics(obs_s, sim_s)
    split = datetime.datetime(2020, 9, 1)
    ci = [i for i, t in enumerate(common) if t < split]
    vi = [i for i, t in enumerate(common) if t >= split]
    mc = all_metrics(obs_s[ci], sim_s[ci]) if len(ci) > 2 else m
    mv = all_metrics(obs_s[vi], sim_s[vi]) if len(vi) > 2 else m

    out = {
        "model_id": "SWAN",
        "this_location": ("SITE:ndbc_41002 (South Hatteras, US Atlantic / "
                          "South Atlantic Bight, deep water, 2020)"),
        "obs_source": "NDBC",
        "status": "completed",
        "tools_used": ["run_swan.py", "parse_swan_output.py",
                       "ki_tools_common.metrics.all_metrics"],
        "tools_failed": [],
        "metrics": {
            "nse": _f(m["NSE"]), "kge": _f(m["KGE"]),
            "pbias": _f(m["PBIAS"]), "r": _f(m["r"]),
            "rmse": _f(m["RMSE"]),
            "nse_cal": _f(mc["NSE"]), "kge_cal": _f(mc["KGE"]),
            "nse_val": _f(mv["NSE"]), "kge_val": _f(mv["KGE"]),
            "pbias_val": _f(mv["PBIAS"]),
            "n_pairs": len(common),
            "period": "2020-01-02..2020-12-31 (cal Jan-Aug / val Sep-Dec)",
        },
        "water_balance": {"status": "N/A", "residual_pct": None},
        "notes": (
            f"Twin of real-case (NDBC 42002, Gulf) applied at NDBC 41002 "
            f"(US Atlantic, deep water) — same KI tools + same wind-sea SWAN "
            f"recipe (swan.exe native ELF, 800km/30x30 flat 3000m grid, GEN3, "
            f"buoy-measured U10 log-law x{U10_FAC:.3f}, 30-min step, 24-h spin-up "
            f"dropped). Climatological swell baseline Hs={SWELL_HS:.1f}m set from "
            f"41002's own calm-wind floor (calm mean 1.06m), exactly as 42002 used "
            f"0.8m. Hourly Hsig vs WVHT, n={len(common)}. NSE={m['NSE']:.3f} "
            f"r={m['r']:.3f} KGE={m['KGE']:.3f} PBIAS={m['PBIAS']:.1f}%."
        ),
    }
    with open(RESULT, 'w') as f:
        json.dump(out, f, indent=2)
    print("[result]", json.dumps(out["metrics"]))
    print("WROTE", RESULT)


def _f(x):
    try:
        xf = float(x)
        return None if (np.isnan(xf) or np.isinf(xf)) else round(xf, 4)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    main()
