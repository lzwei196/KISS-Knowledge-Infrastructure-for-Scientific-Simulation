#!/usr/bin/env python3
"""Build the QUINCY engine forcing file climate.dat (+ climate_meta.json).

Two routes, both read by the REAL engine (qs.bin), format taken from
mo_qs_atmland_forcing.f90 read_or_calculate_forcing:

  --source fluxnet     tower meteorology from FLUXNET2015 FULLSET_HH/HR (half-hourly or hourly),
                       written as TIMESTEP forcing (is_daily_forcing=.FALSE.), columns
                       year doy hour sw lw t_air q_air press rain snow wind co2 dC13 DC14 nhx noy p
  --source nasa_power | cmfd | mswx
                       daily data via ki_tools_common.load_daily_forcing, written as DAILY forcing
                       (is_daily_forcing=.TRUE., read_precipitation=.TRUE.), columns
                       year doy hour sw lw tmin tmax q_air press precip wind co2 dC13 DC14 nhx noy p
                       The engine makes the sub-daily cycle itself.

Units the engine expects (it rescales inside the reader, so these are FILE units):
  sw, lw            W m-2 (daily route: 24-h mean)
  t_air/tmin/tmax   K
  q_air             g kg-1 (engine divides by 1000)
  press             hPa (engine multiplies by 100)
  rain/snow/precip  mm day-1 as a RATE, also for half-hourly rows (engine divides by 86400)
  wind              m s-1
  co2               ppm; dC13 / DC14 permil (ignored when flag_read_dC13/DC14 = .FALSE.)
  nhx, noy, p       deposition in mg m-2 day-1 (engine: / molar mass * 1000 / 86400)

Other rules from the source: the calendar has 365 days and the file is read line by line,
so Feb 29 is dropped here; the solar clock is local solar time, so FLUXNET local standard
time is used as is. Snow is written as 0 and the engine splits rain/snow by temperature
(flag_forcing_with_snow_data = .FALSE., set by the run tool from climate_meta.json).

Exit codes: 0 ok, 2 bad arguments or missing/invalid data, 3 physical-range check failed.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _quincy_common import finite, noleap_doy  # noqa: E402

FLUXNET_SITES = Path("KISSPATH_OBS/fluxnet/sites")
CO2_DIR = Path("KISSPATH_KI_ROOT/QUINCY/inputs/co2")
FLX_COLS = ["TIMESTAMP_START", "SW_IN_F", "LW_IN_F", "TA_F", "VPD_F", "PA_F", "P_F", "WS_F", "CO2_F_MDS"]


def annual_co2() -> dict[int, float]:
    """Annual mean CO2 [ppm]: Law Dome/Mauna Loa 1901-2014, then Mauna Loa annual means."""
    out = {}
    for line in (CO2_DIR / "co2_1901_2014.txt").read_text().splitlines():
        p = line.split()
        if len(p) >= 2 and p[0].isdigit():
            out[int(p[0])] = float(p[1])
    for line in (CO2_DIR / "co2_annmean_mlo.txt").read_text().splitlines():
        p = line.split()
        if len(p) >= 2 and not line.startswith("#") and p[0].isdigit() and int(p[0]) not in out:
            out[int(p[0])] = float(p[1])
    return out


def qair_gkg(ta_c, vpd_hpa, pa_hpa):
    """Specific humidity [g/kg] from air temperature, VPD and pressure (Tetens over water)."""
    es = 6.1078 * np.exp(17.27 * ta_c / (ta_c + 237.3))
    e = np.clip(es - vpd_hpa, 0.01, None)
    return 622.0 * e / (pa_hpa - 0.378 * e)


def from_fluxnet(site, y0, y1, co2_tab):
    import pandas as pd
    sdir = FLUXNET_SITES / site
    f = next((p for p in (sdir / "FULLSET_HH.csv", sdir / "FULLSET_HR.csv") if p.exists()), None)
    if f is None:
        raise FileNotFoundError(f"no FULLSET_HH.csv / FULLSET_HR.csv under {sdir}")
    hdr = f.open().readline().strip().split(",")
    missing = [c for c in FLX_COLS[:-1] if c not in hdr]
    if missing:
        raise ValueError(f"{f} lacks required columns {missing}")
    use = [c for c in FLX_COLS if c in hdr]
    d = pd.read_csv(f, usecols=use, na_values=[-9999, -9999.0])
    t = pd.to_datetime(d.TIMESTAMP_START.astype(str), format="%Y%m%d%H%M")
    keep = (t.dt.year >= y0) & (t.dt.year <= y1) & ~((t.dt.month == 2) & (t.dt.day == 29))
    d, t = d[keep].reset_index(drop=True), t[keep].reset_index(drop=True)
    if d.empty:
        raise ValueError(f"{site}: no rows in {y0}-{y1}")
    step_s = int((t.iloc[1] - t.iloc[0]).total_seconds())
    if step_s not in (1800, 3600):
        raise ValueError(f"{site}: unexpected time step {step_s} s")
    years = sorted(t.dt.year.unique())
    if years[0] != y0 or years[-1] != y1 or len(d) != (y1 - y0 + 1) * 365 * 86400 // step_s:
        raise ValueError(f"{site}: {len(d)} rows for {y0}-{y1} -> the tower record does not cover full years "
                         f"(found years {years[0]}-{years[-1]})")
    nan = {c: int(d[c].isna().sum()) for c in FLX_COLS[1:-1] if c in d}
    if any(nan.values()):
        raise ValueError(f"{site}: gap-filled met still has NaN rows {nan}; choose other years")
    co2_site = d["CO2_F_MDS"] if "CO2_F_MDS" in d else pd.Series(np.nan, index=d.index)
    co2_fill = t.dt.year.map(co2_tab)
    if co2_fill.isna().any():
        raise ValueError("annual CO2 record does not cover the requested years")
    n_co2_filled = int(co2_site.isna().sum())
    pa = d.PA_F.to_numpy() * 10.0                      # kPa -> hPa
    ta = d.TA_F.to_numpy()
    rows = {
        "year": t.dt.year.to_numpy(), "doy": np.array([noleap_doy(x) for x in t.dt.date]),
        "hour": (t.dt.hour + t.dt.minute / 60.0).to_numpy(),
        "sw": np.clip(d.SW_IN_F.to_numpy(), 0, None), "lw": d.LW_IN_F.to_numpy(),
        "t_air": ta + 273.15, "q_air": qair_gkg(ta, d.VPD_F.to_numpy(), pa), "press": pa,
        "rain": d.P_F.to_numpy() * 86400.0 / step_s,  # mm per step -> mm/day rate
        "snow": np.zeros(len(d)), "wind": d.WS_F.to_numpy(),
        "co2": co2_site.fillna(co2_fill).to_numpy(),
    }
    info = {"route": "timestep", "dtime_s": step_s, "source_file": str(f),
            "co2_rows_filled_from_annual_record": n_co2_filled}
    return rows, info


def from_daily(source, lat, lon, y0, y1, forcing_dir, co2_tab):
    from ki_tools_common.load_forcing import load_daily_forcing
    kw = {"forcing_dir": forcing_dir} if forcing_dir else {}
    data = load_daily_forcing(source, lat, lon, y0, y1, **kw)
    import pandas as pd
    t = pd.to_datetime(data["dates"])
    keep = ~((t.month == 2) & (t.day == 29))
    need = ["srad_wm2", "lrad_wm2", "temp_min_c", "temp_max_c", "shum_kgkg", "pres_pa", "precip_mm", "wind_ms"]
    absent = [k for k in need if k not in data]
    if absent:
        raise ValueError(f"{source}: loader returned no {absent}")
    arr = {k: np.asarray(data[k], dtype=float)[keep] for k in need}
    t = t[keep]
    bad = {k: int(np.isnan(v).sum()) for k, v in arr.items() if np.isnan(v).any()}
    if bad:
        raise ValueError(f"{source}: NaN in loaded forcing {bad}")
    if len(t) != (y1 - y0 + 1) * 365:
        raise ValueError(f"{source}: {len(t)} days for {y0}-{y1}, expected {(y1 - y0 + 1) * 365}")
    co2 = np.array([co2_tab[y] for y in t.year])
    rows = {
        "year": t.year.to_numpy(), "doy": np.array([noleap_doy(x.date()) for x in t]),
        "hour": np.zeros(len(t)), "sw": np.clip(arr["srad_wm2"], 0, None), "lw": arr["lrad_wm2"],
        "tmin": arr["temp_min_c"] + 273.15, "tmax": arr["temp_max_c"] + 273.15,
        "q_air": arr["shum_kgkg"] * 1000.0, "press": arr["pres_pa"] / 100.0,
        "precip": arr["precip_mm"], "wind": arr["wind_ms"], "co2": co2,
    }
    info = {"route": "daily", "dtime_s": 1800, "wind_height_m": data.get("wind_height_m")}
    return rows, info


def validate_outputs(rows, route):
    """Physical plausibility of the FILE units (catches K/degC, Pa/hPa, kg/g and rate mistakes)."""
    errs = []
    tair = rows["t_air"] if route == "timestep" else 0.5 * (rows["tmin"] + rows["tmax"])
    pr = rows["rain"] if route == "timestep" else rows["precip"]
    checks = [("mean air temperature [K]", np.mean(tair), 230, 315),
              ("mean SW [W m-2]", np.mean(rows["sw"]), 40, 350),
              ("mean LW [W m-2]", np.mean(rows["lw"]), 150, 450),
              ("mean specific humidity [g kg-1]", np.mean(rows["q_air"]), 0.3, 30),
              ("mean pressure [hPa]", np.mean(rows["press"]), 500, 1100),
              ("mean precipitation [mm day-1]", np.mean(pr), 0.05, 15),
              ("mean wind [m s-1]", np.mean(rows["wind"]), 0.1, 20),
              ("mean CO2 [ppm]", np.mean(rows["co2"]), 270, 450)]
    for name, v, lo, hi in checks:
        if not (lo <= v <= hi) or not math.isfinite(v):
            errs.append(f"{name} = {v:.3f} outside [{lo}, {hi}]")
    if route == "daily" and np.any(rows["tmin"] > rows["tmax"] + 1e-6):
        errs.append("tmin > tmax on some days")
    return errs


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", required=True, choices=["fluxnet", "nasa_power", "cmfd", "mswx"])
    ap.add_argument("--site", help="FLUXNET site id (required for --source fluxnet), e.g. FI-Hyy")
    ap.add_argument("--lat", type=float)
    ap.add_argument("--lon", type=float)
    ap.add_argument("--start_year", type=int, required=True)
    ap.add_argument("--end_year", type=int, required=True)
    ap.add_argument("--forcing_dir", help="override the loader's data directory (cmfd/mswx)")
    ap.add_argument("--ndep_kgN_ha_yr", type=float, required=True,
                    help="total N deposition [kg N ha-1 yr-1]; no server dataset exists, give a cited site value")
    ap.add_argument("--nhx_fraction", type=float, default=0.5, help="share of N deposition as NHx (rest NOy)")
    ap.add_argument("--pdep_kgP_ha_yr", type=float, required=True, help="P deposition [kg P ha-1 yr-1]")
    ap.add_argument("--out_dir", required=True)
    a = ap.parse_args(argv)
    try:
        if a.end_year < a.start_year:
            raise ValueError("end_year < start_year")
        ndep = finite(a.ndep_kgN_ha_yr, "ndep_kgN_ha_yr", 0, 200)
        pdep = finite(a.pdep_kgP_ha_yr, "pdep_kgP_ha_yr", 0, 20)
        fx = finite(a.nhx_fraction, "nhx_fraction", 0, 1)
        co2_tab = annual_co2()
        if a.source == "fluxnet":
            if not a.site:
                raise ValueError("--site is required with --source fluxnet")
            rows, info = from_fluxnet(a.site, a.start_year, a.end_year, co2_tab)
        else:
            if a.lat is None or a.lon is None:
                raise ValueError("--lat and --lon are required for gridded sources")
            finite(a.lat, "lat", -90, 90)
            finite(a.lon, "lon", -180, 180)
            rows, info = from_daily(a.source, a.lat, a.lon, a.start_year, a.end_year, a.forcing_dir, co2_tab)
    except (ValueError, FileNotFoundError, KeyError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    errs = validate_outputs(rows, info["route"])
    if errs:
        print("ERROR: forcing failed physical-range checks:\n  " + "\n  ".join(errs), file=sys.stderr)
        return 3
    # deposition: kg ha-1 yr-1 -> mg m-2 day-1 (1 kg/ha = 100 mg/m2), engine year = 365 days
    n_mg = ndep * 100.0 / 365.0
    nhx, noy, p_mg = n_mg * fx, n_mg * (1 - fx), pdep * 100.0 / 365.0
    out = Path(a.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if info["route"] == "timestep":
        cols = ["sw", "lw", "t_air", "q_air", "press", "rain", "snow", "wind", "co2"]
        head = "year doy hour sw_srf_down lw_srf_down t_air q_air press_srf rain snow wind_air co2_mixing_ratio"
    else:
        cols = ["sw", "lw", "tmin", "tmax", "q_air", "press", "precip", "wind", "co2"]
        head = "year doy hour sw_srf_down lw_srf_down tmin tmax q_air press_srf precip wind_air co2_mixing_ratio"
    head += " co2_dC13 co2_DC14 nhx_srf_down noy_srf_down p_srf_down"
    tail = f" -8.0 0.0 {nhx:.6f} {noy:.6f} {p_mg:.6f}\n"
    src = a.site or f"{a.lat},{a.lon}"
    with open(out / "climate.dat", "w") as fh:
        fh.write(f"QUINCY climate forcing from {a.source} {src} {a.start_year}-{a.end_year} "
                 f"(tools/build_quincy_climate.py)\n{head}\n")
        n = len(rows["year"])
        for i in range(n):
            vals = " ".join(f"{rows[c][i]:.5f}" for c in cols)
            fh.write(f"{int(rows['year'][i])} {int(rows['doy'][i])} {rows['hour'][i]:.2f} {vals}{tail}")
    tmean = rows["t_air"] if info["route"] == "timestep" else 0.5 * (rows["tmin"] + rows["tmax"])
    pr = rows["rain"] if info["route"] == "timestep" else rows["precip"]
    meta = {
        "source": a.source, "site": a.site, "lat": a.lat, "lon": a.lon,
        "start_year": a.start_year, "end_year": a.end_year, "n_rows": int(n),
        "is_daily_forcing": info["route"] == "daily", "read_precipitation": info["route"] == "daily",
        "dtime_s": info["dtime_s"], "calendar": "365_day (Feb 29 dropped)",
        "deposition_mg_m2_day": {"nhx": nhx, "noy": noy, "p": p_mg},
        "deposition_inputs": {"ndep_kgN_ha_yr": ndep, "nhx_fraction": fx, "pdep_kgP_ha_yr": pdep},
        "summary": {"t_air_mean_C": float(np.mean(tmean) - 273.15),
                    "precip_mm_yr": float(np.mean(pr) * 365.0),
                    "sw_mean_wm2": float(np.mean(rows["sw"])), "co2_mean_ppm": float(np.mean(rows["co2"]))},
        **{k: v for k, v in info.items() if k not in ("route", "dtime_s")},
    }
    (out / "climate_meta.json").write_text(json.dumps(meta, indent=2))
    print(json.dumps({"climate": str(out / "climate.dat"), **meta["summary"], "n_rows": n}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
