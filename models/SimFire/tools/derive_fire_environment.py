#!/usr/bin/env python3
"""
derive_fire_environment.py — S4 "Environment": dead fuel moisture from weather.

Stage S4 of the SimFire pipeline (`environment.moisture` + the fire initial
position) had NO tool in SKILL.md's table -- it just showed the literal
``moisture: 0.03`` from the shipped example configs.  That literal is the single
most sensitive uncalibrated knob in the whole model: `environment.moisture` is
Rothermel's M_f, it enters the moisture damping coefficient eta_M as the ratio
M_f/M_x, and every burnable FBFM-13 model has M_x between 0.12 and 0.40.  So

  * 0.03 (the example value) is a NEAR-CURED, extreme fire-weather state --
    eta_M ~ 0.9. Using it everywhere makes every simulated fire run hot;
  * a value >= M_x makes eta_M = 0 and the fire NEVER spreads (dt_009);
  * writing a PERCENT (3) instead of a fraction (0.03) also gives 0 spread
    (dt_004).

This tool replaces the literal with a weather-derived number.  It computes the
fine dead fuel equilibrium moisture content (EMC) from temperature and relative
humidity with the Simard (1968) piecewise relation used by NFDRS/BEHAVE, then
takes the mean over the PEAK BURNING PERIOD (default 13:00-17:00 local solar
time) rather than the daily mean, because that is the window a spread run is
meant to represent -- a daily-mean EMC is systematically too moist and biases
the rate of spread low.

Temperature, specific humidity and pressure come from
``ki_tools_common.load_forcing`` (NASA POWER hourly); RH is derived with
``ki_tools_common.humidity.specific_humidity_to_rh``.  Nothing is hard-coded.

Simard (1968) EMC, T in degF, RH in %, EMC in %:
    RH <  10 : EMC = 0.03229 + 0.281073*RH - 0.000578*RH*T
    RH <  50 : EMC = 2.22749 + 0.160107*RH - 0.014784*T
    else     : EMC = 21.0606 + 0.005565*RH^2 - 0.00035*RH*T - 0.483199*RH

Usage:
    python derive_fire_environment.py \\
        --lat 40.8838 --lon -119.5930 --date 2020-08-12 \\
        --output-dir ./fire_env/
"""

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import numpy as np

KI_TOOLS_COMMON_SRC = "KISSPATH_KI_TOOLS_COMMON"

# Physical guard rails for 1-h dead fuel moisture as a FRACTION.
MIN_DEAD_FM = 0.02   # below this, fuels are effectively bone dry
MAX_DEAD_FM = 0.35   # above the largest FBFM-13 M_x (0.40) nothing burns


def _ensure_ki_tools_common():
    if KI_TOOLS_COMMON_SRC not in sys.path:
        sys.path.insert(0, KI_TOOLS_COMMON_SRC)


def simard_emc_percent(temp_f, rh_pct):
    """Simard (1968) fine dead fuel equilibrium moisture content, in percent."""
    t = np.asarray(temp_f, dtype=float)
    h = np.clip(np.asarray(rh_pct, dtype=float), 0.0, 100.0)
    emc = np.where(
        h < 10.0,
        0.03229 + 0.281073 * h - 0.000578 * h * t,
        np.where(
            h < 50.0,
            2.22749 + 0.160107 * h - 0.014784 * t,
            21.0606 + 0.005565 * h ** 2 - 0.00035 * h * t - 0.483199 * h,
        ),
    )
    return emc


def derive_moisture(lat, lon, date, peak_start_hour=13, peak_end_hour=17):
    """Dead fuel moisture FRACTION for one fire-day at one point.

    Args:
        lat, lon: fire location (degrees).
        date: "YYYY-MM-DD" (the ignition / burn day).
        peak_start_hour, peak_end_hour: local solar hours bounding the peak
            burning period.

    Returns:
        dict with `moisture` (fraction, ready for `environment.moisture`) plus
        the full derivation for audit.
    """
    _ensure_ki_tools_common()
    from ki_tools_common.humidity import specific_humidity_to_rh
    from ki_tools_common.load_forcing import load_hourly_forcing

    day = dt.datetime.strptime(date, "%Y-%m-%d")
    fx = load_hourly_forcing("nasa_power", lat, lon, day.year, day.year)

    dates = fx["dates"].astype("datetime64[s]").astype(object)
    temp_c = np.asarray(fx["temp_c"], dtype=float)
    shum = np.asarray(fx["shum_kgkg"], dtype=float)
    pres = np.asarray(fx["pres_pa"], dtype=float)

    # NASA POWER hourly is UTC; convert the peak-burning window to UTC using
    # the longitude's solar offset (no tz database needed, and solar time is
    # what actually drives the diurnal moisture cycle).
    utc_offset_h = lon / 15.0
    lo = day + dt.timedelta(hours=peak_start_hour - utc_offset_h)
    hi = day + dt.timedelta(hours=peak_end_hour - utc_offset_h)

    mask = np.array([lo <= d <= hi for d in dates])
    if not mask.any():
        raise RuntimeError(f"NASA POWER has no hours in the peak window {lo}..{hi}")

    # TRAP: ki_tools_common.humidity.specific_humidity_to_rh takes temperature
    # in KELVIN (arg name `temp_k`), while load_forcing returns `temp_c` in
    # CELSIUS. Passing Celsius straight through is SILENT: Tetens is evaluated
    # ~273 K below the real temperature, e_s blows up and RH clips to 0.0, which
    # then yields EMC ~ 0.03% -> a moisture floor of 0.02 for every site on
    # Earth. Verified 2026-08-09 (31.4 degC, RH came out 0.0). See dt_022.
    rh = np.asarray(
        specific_humidity_to_rh(shum[mask], temp_c[mask] + 273.15, pres[mask]),
        dtype=float,
    )
    t_f = temp_c[mask] * 9.0 / 5.0 + 32.0
    emc_pct = simard_emc_percent(t_f, rh)

    good = np.isfinite(emc_pct)
    if not good.any():
        raise RuntimeError("All EMC values non-finite — check forcing for NaNs")

    emc_mean_pct = float(np.mean(emc_pct[good]))
    moisture = float(np.clip(emc_mean_pct / 100.0, MIN_DEAD_FM, MAX_DEAD_FM))

    return {
        "moisture": round(moisture, 4),   # -> environment.moisture (FRACTION)
        "provenance": {
            "source": "NASA POWER hourly via ki_tools_common.load_forcing; "
                      "RH via ki_tools_common.humidity.specific_humidity_to_rh",
            "method": "Simard (1968) fine dead fuel EMC, peak burning period mean",
            "lat": lat, "lon": lon, "date": date,
            "peak_window_local_solar": [peak_start_hour, peak_end_hour],
            "peak_window_utc": [str(lo), str(hi)],
            "n_hours": int(good.sum()),
            "mean_temp_c": round(float(np.mean(temp_c[mask])), 2),
            "mean_rh_pct": round(float(np.nanmean(rh)), 2),
            "emc_percent": round(emc_mean_pct, 3),
            "clamped_to": [MIN_DEAD_FM, MAX_DEAD_FM],
            "units": "fraction (0.05 = 5%), NOT percent — see dt_004",
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--lat", type=float, required=True)
    parser.add_argument("--lon", type=float, required=True)
    parser.add_argument("--date", type=str, required=True, help="YYYY-MM-DD")
    parser.add_argument("--peak-start-hour", type=int, default=13)
    parser.add_argument("--peak-end-hour", type=int, default=17)
    parser.add_argument("--output-dir", type=str, default=None)

    args = parser.parse_args()
    result = derive_moisture(
        args.lat, args.lon, args.date, args.peak_start_hour, args.peak_end_hour
    )
    if args.output_dir:
        out = Path(args.output_dir)
        out.mkdir(parents=True, exist_ok=True)
        with open(str(out / "fire_environment.json"), "w") as fh:
            json.dump(result, fh, indent=2)
        result["output"] = str(out / "fire_environment.json")

    print(json.dumps({"status": "success", "output": result}, indent=2))


if __name__ == "__main__":
    main()
