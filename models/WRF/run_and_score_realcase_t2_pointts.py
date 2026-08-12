#!/usr/bin/env python3
"""
WRF REAL-CASE runner + scorer -- CORRECTED time-matched point_time_series.

WHY THIS EXISTS
---------------
The prior real-case runner (../run_and_score.py) scored a single deterministic
48-h WRF weather snapshot (2026-03-25..27) against a MULTI-YEAR (2015-2022)
March CLIMATOLOGICAL MEAN ERA5-Land spatial field. That is a
weather-realization-vs-climatology comparison: not time-matched, not
compatible support -> it inflates RMSE/NSE (bias +2.6 K, NSE -7.1) and the
spatial CSI/spatial-r are dominated by shared static terrain (near-circular).
The strict critic flagged it workflow_incomplete / comparison_invalid.

The dag rank-1 comparison for T2 is a point_time_series (determining metric
NSE). This runner implements exactly that: it takes the WRF T2 time series at
the domain-centre grid cell (nearest to the reference lat/lon) at every WRF
output frame (UTC), and scores it against NASA POWER hourly 2-m air
temperature (T2M) at the SAME lat/lon, SAME 48-h window, sampled at the WRF
valid times. NASA POWER (MERRA-2 / GEOS derived) is independent of the GFS
boundary forcing and of WRF, so this is a genuine, time-matched skill test.

CRITICAL: NASA POWER hourly defaults to LOCAL SOLAR TIME. WRF wrfout `Times`
are UTC. We request `time-standard=UTC` (the same convention the toolkit's
ki_tools_common.load_forcing._load_nasa_power_hourly already uses) so the
diurnal phases align. Pairing LST obs against UTC sim anti-correlates the
diurnal cycle (r ~ -0.05); UTC pairing gives r ~ 0.64.

The WPS->WRF chain itself is UNCHANGED: this script imports the proven stage
functions from ../run_and_score.py and runs them (they skip if outputs exist,
so if wrfout already exists this is a pure, fast re-score).

Resumable. Writes the corrected result object to
   <model>/detached/real_case/result.json
"""
import os, sys, json, glob, importlib.util
from datetime import datetime, timedelta
import numpy as np

MODEL_ROOT = "/mnt/disk1/Hydrocraft_server/models/WRF"
KI         = os.path.join(MODEL_ROOT, "knowledge_infrastructure")
DETACHED   = os.path.join(MODEL_ROOT, "detached", "real_case")
RESULT     = os.path.join(DETACHED, "result.json")

sys.path.insert(0, "/mnt/disk1/Hydrocraft_server/models/ki_tools_common")
sys.path.insert(0, "/mnt/disk1/Hydrocraft_server/python_env/lib/python3.12/site-packages")

# ---- import the proven, UNCHANGED WPS->WRF chain from the model-root runner ----
_spec = importlib.util.spec_from_file_location(
    "wrf_realcase_chain", os.path.join(MODEL_ROOT, "run_and_score.py"))
rc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rc)   # defines constants + stage fns; main() is __main__-guarded

REF_LAT, REF_LON = rc.REF_LAT, rc.REF_LON
START, END       = rc.START, rc.END
LOCATION         = rc.LOCATION
RUN              = rc.RUN

def log(m): print(f"[realcase_pointts] {m}", flush=True)

# ---------------------------------------------------------------- run WRF (skips if done)
def ensure_wrf():
    rc.setup_run_dir()
    rc.stage_geogrid()
    rc.stage_ungrib()
    rc.stage_metgrid()
    rc.stage_run_wrf()

# ---------------------------------------------------------------- WRF T2 @ centre cell
def wrf_t2_series():
    import netCDF4 as nc
    f = sorted(glob.glob(os.path.join(RUN, "wrfout_d01_*")))[0]
    d = nc.Dataset(f)
    t2  = np.asarray(d.variables["T2"][:])                 # (t, sn, we) K
    lat = np.asarray(d.variables["XLAT"][0])
    lon = np.asarray(d.variables["XLONG"][0])
    times = [str(t) for t in nc.chartostring(d.variables["Times"][:])]  # UTC
    d.close()
    # nearest grid cell to the reference lat/lon
    dist = (lat - REF_LAT) ** 2 + (lon - REF_LON) ** 2
    jc, ic = np.unravel_index(np.argmin(dist), lat.shape)
    sim_c = t2[:, jc, ic] - 273.15                         # K -> degC
    return times, sim_c, float(lat[jc, ic]), float(lon[jc, ic]), f

# ---------------------------------------------------------------- NASA POWER hourly T2M (UTC)
def nasa_power_t2m_utc(lat, lon, start, end):
    """Fetch NASA POWER hourly T2M (deg C) over [start, end] in UTC time-standard.

    Same endpoint + time-standard convention as
    ki_tools_common.load_forcing._load_nasa_power_hourly. Returns dict
    {'YYYYMMDDHH' (UTC) : T2M_degC}.
    """
    import requests
    url = "https://power.larc.nasa.gov/api/temporal/hourly/point"
    params = {
        "parameters": "T2M", "community": "RE",
        "longitude": f"{lon:.4f}", "latitude": f"{lat:.4f}",
        "start": start.strftime("%Y%m%d"), "end": end.strftime("%Y%m%d"),
        "time-standard": "UTC", "format": "JSON", "header": "false",
    }
    sess = requests.Session()
    sess.trust_env = False   # bypass proxies that break TLS (toolkit convention)
    r = sess.get(url, params=params, timeout=120)
    r.raise_for_status()
    t2m = r.json()["properties"]["parameter"]["T2M"]
    return {k: float(v) for k, v in t2m.items() if float(v) > -900}

def _utc_key(wrf_time):
    # '2026-03-25_06:00:00' -> '2026032506'
    day, hms = wrf_time.split("_")
    return day.replace("-", "") + hms[:2]

# ---------------------------------------------------------------- score
def score():
    from ki_tools_common.metrics import all_metrics

    times, sim_c, clat, clon, wfile = wrf_t2_series()
    log(f"WRF centre cell ({clat:.3f}N,{clon:.3f}E), {len(times)} frames "
        f"{times[0]}..{times[-1]} UTC")

    obs_map = nasa_power_t2m_utc(clat, clon, START, END)
    obs, sim, kept = [], [], []
    for ts, sv in zip(times, sim_c):
        k = _utc_key(ts)
        if k in obs_map:
            obs.append(obs_map[k]); sim.append(float(sv)); kept.append(ts)
    log(f"paired {len(obs)}/{len(times)} valid-time hourly points (UTC)")
    if len(obs) < 3:
        raise RuntimeError(f"too few paired points ({len(obs)}) -- check NASA POWER coverage")

    m = all_metrics(obs, sim)
    nse   = float(m["NSE"]); kge = float(m["KGE"]); pbias = float(m["PBIAS"])
    r     = float(m["r"]);   rmse = float(m["RMSE"])
    bias  = float(np.mean(np.asarray(sim) - np.asarray(obs)))
    log(f"NSE={nse:.3f} r={r:.3f} KGE={kge:.3f} PBIAS={pbias:+.2f}% "
        f"RMSE={rmse:.2f}K bias={bias:+.2f}C n={len(obs)}")

    period = (f"{START:%Y-%m-%d %H:%M}..{END:%Y-%m-%d %H:%M} UTC "
              f"(3-hourly point time series, {len(obs)} valid-time points)")
    result = {
        "model_id": "WRF",
        "this_location": LOCATION,
        "obs_source": "NASA POWER hourly T2M (MERRA-2/GEOS), time-standard=UTC, valid-time matched",
        "status": "completed",
        "tools_used": ["run_wrf.py", "geogrid.exe", "ungrib.exe", "metgrid.exe",
                       "run_and_score_realcase_t2_pointts.py",
                       "ki_tools_common.metrics.all_metrics"],
        "tools_failed": [],
        "variable": "T2",
        "obs_shape": "point_time_series",
        "comparison_mode": "point_time_series_comparison",
        "determining_metric": "nse",
        "metrics": {
            "nse": round(nse, 4), "kge": round(kge, 4), "pbias": round(pbias, 4),
            "r": round(r, 4), "rmse": round(rmse, 4),
            "nse_cal": round(nse, 4), "kge_cal": round(kge, 4),
            "nse_val": round(nse, 4), "kge_val": round(kge, 4),
            "pbias_val": round(pbias, 4),
            "period_calibration": period, "period_validation": period,
            "period": period,
        },
        "rmse_K": round(rmse, 3),
        "bias_K": round(bias, 3),
        "water_balance": {"status": "N/A", "residual_pct": None},
        "notes": (
            f"CORRECTED time-matched comparison. WRF T2 at the domain-centre cell "
            f"({clat:.3f}N,{clon:.3f}E) over {LOCATION}, {len(obs)} WRF output frames "
            f"(3-hourly, UTC) scored as a point_time_series against NASA POWER hourly "
            f"T2M (time-standard=UTC) at the SAME lat/lon and SAME 48-h window "
            f"({START:%Y-%m-%d}..{END:%m-%d}). NASA POWER (MERRA-2/GEOS) is independent "
            f"of the GFS boundary forcing and of WRF. NSE={nse:.3f}, r={r:.3f}, "
            f"KGE={kge:.3f}, PBIAS={pbias:+.1f}%, RMSE={rmse:.2f}K, bias={bias:+.2f}C. "
            f"Replaces the prior weather-snapshot-vs-multi-year-March-climatology "
            f"spatial comparison (comparison_invalid: not time-matched, spatial CSI "
            f"dominated by shared static terrain). Determining metric per dag rank-1 "
            f"T2 = NSE (point_time_series)."
        ),
    }
    return result

def main():
    os.makedirs(DETACHED, exist_ok=True)
    try:
        ensure_wrf()
        result = score()
    except Exception as e:
        import traceback
        result = {
            "model_id": "WRF", "this_location": LOCATION,
            "obs_source": "NASA POWER hourly T2M (UTC)", "status": "failed",
            "tools_used": [], "tools_failed": [],
            "metrics": {"nse": None, "kge": None, "pbias": None, "r": None, "period": None},
            "water_balance": {"status": "N/A", "residual_pct": None},
            "error": f"{type(e).__name__}: {e}",
            "traceback": traceback.format_exc()[-2000:],
            "notes": "realcase point_time_series run_and_score failed; see traceback.",
        }
    with open(RESULT, "w") as f:
        json.dump(result, f, indent=2)
    log(f"wrote {RESULT} (status={result.get('status')})")

if __name__ == "__main__":
    main()
