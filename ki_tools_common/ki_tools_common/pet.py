"""FAO-56 Penman-Monteith reference evaporation from the shared daily loader.

One place for the daily FAO-56 PM sum, for KI tools whose model needs
potential evaporation (PET) while the forcing sources (CMFD, MSWX, NASA POWER)
give none. It is the same sum as the AquaCrop_python KI's eto_fao56_pm
(FAO-56 eq. 6 with eq. 13, 21, 37, 39, 47; ea from specific humidity and
pressure).

Rules:
  - Only real loader fields are used: temp_min_c, temp_max_c, srad_wm2,
    shum_kgkg, pres_pa, wind_ms. A missing or non-finite value stops; nothing
    is filled.
  - wind_ms from load_daily_forcing is the 10 m wind for every source (the
    loader contract); it is brought to 2 m with FAO-56 eq. 47. The height is
    recorded, never guessed from the numbers.
  - Elevation (for clear-sky radiation, eq. 37) must be given by the caller.
  - A negative daily value (net condensation) is set to 0 and the number of
    such days is returned in the record, never done silently.

The caller decides that PET is to be calculated (an explicit method choice);
this module never runs as a hidden fallback.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

LOADER_WIND_HEIGHT_M = 10.0   # load_daily_forcing wind_ms (all sources)


def _col(data, key, low, high, n=None):
    if key not in data:
        raise ValueError(f"FAO-56 PM needs '{key}' from the loader; it is absent. Nothing filled.")
    a = np.asarray(data[key], dtype=float)
    if n is not None and a.size != n:
        raise ValueError(f"'{key}' has {a.size} values, dates have {n}")
    bad = ~np.isfinite(a) | (a < low) | (a > high)
    if bad.any():
        i = np.flatnonzero(bad)[:5]
        raise ValueError(f"'{key}' missing or outside [{low}, {high}] on {int(bad.sum())} days "
                         f"(first indices {i.tolist()}, values {a[i].tolist()}). Nothing filled.")
    return a


def wind_to_2m(wind_ms, height_m):
    """FAO-56 eq. 47 (log wind profile over short grass)."""
    if not (0.5 <= float(height_m) <= 100.0):
        raise ValueError(f"wind height {height_m} m outside 0.5-100 m")
    return np.asarray(wind_ms, dtype=float) * (4.87 / math.log(67.8 * float(height_m) - 5.42))


def fao56_pm_daily(tmin, tmax, rs_mjm2, ea_kpa, u2, lat_deg, elev_m, doy, pressure_kpa):
    """FAO-56 PM reference ET (mm/day); may be < 0 (see pet_from_daily_loader)."""
    tmean = 0.5 * (tmin + tmax)
    delta = 4098.0 * (0.6108 * np.exp(17.27 * tmean / (tmean + 237.3))) / (tmean + 237.3) ** 2
    gamma = 0.000665 * pressure_kpa
    es = 0.5 * (0.6108 * np.exp(17.27 * tmax / (tmax + 237.3))
                + 0.6108 * np.exp(17.27 * tmin / (tmin + 237.3)))
    lat = math.radians(lat_deg)
    dr = 1.0 + 0.033 * np.cos(2.0 * math.pi * doy / 365.0)
    decl = 0.409 * np.sin(2.0 * math.pi * doy / 365.0 - 1.39)
    ws = np.arccos(np.clip(-np.tan(lat) * np.tan(decl), -1.0, 1.0))
    ra = (24.0 * 60.0 / math.pi) * 0.0820 * dr * (
        ws * math.sin(lat) * np.sin(decl) + math.cos(lat) * np.cos(decl) * np.sin(ws))
    rso = (0.75 + 2e-5 * elev_m) * ra
    if np.any(rso <= 0):
        raise ValueError("clear-sky radiation is not positive (polar night); "
                         "FAO-56 daily PM is not defined here")
    rns = (1 - 0.23) * rs_mjm2
    rnl = 4.903e-9 * 0.5 * ((tmax + 273.16) ** 4 + (tmin + 273.16) ** 4) \
        * (0.34 - 0.14 * np.sqrt(ea_kpa)) * (1.35 * np.clip(rs_mjm2 / rso, 0.0, 1.0) - 0.35)
    rn = rns - rnl
    num = 0.408 * delta * rn + gamma * (900.0 / (tmean + 273.0)) * u2 * (es - ea_kpa)
    den = delta + gamma * (1.0 + 0.34 * u2)
    return num / den


def pet_from_daily_loader(data, lat_deg, elev_m):
    """PET (mm/day) for every day of a load_daily_forcing result.

    Returns (pet_mm_day ndarray, record dict).
    """
    if elev_m is None:
        raise ValueError("FAO-56 PM needs the site elevation (m); give it explicitly")
    elev_m = float(elev_m)
    if not (-500.0 <= elev_m <= 9000.0):
        raise ValueError(f"elevation {elev_m} m outside -500..9000")
    if not (-90.0 <= float(lat_deg) <= 90.0):
        raise ValueError(f"latitude {lat_deg} outside -90..90")
    dates = pd.DatetimeIndex(pd.to_datetime(data["dates"]))
    n = len(dates)
    tmin = _col(data, "temp_min_c", -70, 50, n)
    tmax = _col(data, "temp_max_c", -60, 60, n)
    if (tmin > tmax).any():
        raise ValueError(f"temp_min_c > temp_max_c on {int((tmin > tmax).sum())} days")
    rs = _col(data, "srad_wm2", 0, 1500, n) * 0.0864           # W/m2 -> MJ/m2/day
    q = _col(data, "shum_kgkg", 0, 0.1, n)
    p_kpa = _col(data, "pres_pa", 30000, 110000, n) / 1000.0
    u2 = wind_to_2m(_col(data, "wind_ms", 0, 100, n), LOADER_WIND_HEIGHT_M)
    ea = q * p_kpa / (0.622 + 0.378 * q)
    es_max = 0.6108 * np.exp(17.27 * tmax / (tmax + 237.3))
    bad = (ea <= 0) | (ea > es_max)
    if bad.any():
        i = np.flatnonzero(bad)[:5]
        raise ValueError(f"vapour pressure outside (0, es(Tmax)] on {int(bad.sum())} days "
                         f"(first indices {i.tolist()}). Nothing filled.")
    pet = fao56_pm_daily(tmin, tmax, rs, ea, u2, float(lat_deg), elev_m,
                         dates.dayofyear.to_numpy(), p_kpa)
    neg = pet < 0
    record = {
        "method": "FAO-56 Penman-Monteith daily (ki_tools_common.pet)",
        "inputs": "temp_min_c, temp_max_c, srad_wm2, shum_kgkg, pres_pa, wind_ms",
        "wind_height_m": LOADER_WIND_HEIGHT_M,
        "wind_to_2m": "FAO-56 eq. 47",
        "elevation_m": elev_m,
        "negative_days_set_to_0": int(neg.sum()),
        "negative_min_mm": float(pet[neg].min()) if neg.any() else None,
        "mean_mm_day": float(np.mean(np.where(neg, 0.0, pet))),
    }
    return np.where(neg, 0.0, pet), record
