#!/usr/bin/env python3
"""
build_lpjguess_cf_forcing.py -- daily point forcing for the REAL LPJ-GUESS
engine's CF input module (`guess -input cf`).

Loads daily weather with ki_tools_common.load_daily_forcing (nasa_power | cmfd
| mswx) and writes one CF NetCDF file per variable on a 1x1 lat/lon grid, plus
the CF gridlist (`0 0 <site>` = x/y INDICES, not lon/lat) and a
forcing_meta.json that run_lpjguess_engine.py reads.

What cfinput.cpp (LPJ-GUESS 4.1.1) checks, and therefore what this tool writes:
  temp      air_temperature                         K
  prec      precipitation_flux                      kg m-2 s-1
  insol     surface_downwelling_shortwave_flux_in_air  W m-2 (24-h mean)
  min_temp / max_temp  air_temperature              K
  relhum    relative_humidity                       1 (fraction)
  wind      wind_speed                              m s-1
Time: "days since <start>-01-01 00:00:00", calendar "standard" (leap days are
skipped by the engine). The engine builds its spin-up climate from the FIRST
30 years of the file (CFInput::NYEAR_SPINUP_DATA), so fewer than 30 complete
years is refused here (exit 2) instead of failing inside the engine.

Exit codes: 0 ok, 2 bad input / validation failure, 3 data load failed.

Usage:
  python build_lpjguess_cf_forcing.py --site DE-Tha --lat 50.9624 --lon 13.5652 \
      --start_year 1984 --end_year 2014 --source nasa_power --out_dir forcing/
"""
import argparse
import json
import os
import sys

import numpy as np

NYEAR_SPINUP_DATA = 30  # modules/cfinput.h

# name -> (CF standard_name, units, loader key or derived)
VARS = {
    "temp": ("air_temperature", "K"),
    "prec": ("precipitation_flux", "kg m-2 s-1"),
    "insol": ("surface_downwelling_shortwave_flux_in_air", "W m-2"),
    "min_temp": ("air_temperature", "K"),
    "max_temp": ("air_temperature", "K"),
    "relhum": ("relative_humidity", "1"),
    "wind": ("wind_speed", "m s-1"),
}
NEEDED_KEYS = ["precip_mm", "temp_mean_c", "temp_max_c", "temp_min_c",
               "srad_wm2", "wind_ms", "shum_kgkg", "pres_pa"]


def relative_humidity(shum_kgkg, pres_pa, temp_c):
    """RH fraction from specific humidity, pressure, temperature (Bolton 1980 es)."""
    e = shum_kgkg * pres_pa / (0.622 + 0.378 * shum_kgkg)
    es = 611.2 * np.exp(17.67 * temp_c / (temp_c + 243.5))
    return np.clip(e / es, 0.01, 1.0)


def load(source, lat, lon, y0, y1, forcing_dir):
    from ki_tools_common.load_forcing import load_daily_forcing
    # on_missing='nan': NASA POWER has no lrad_wm2, which LPJ-GUESS does not
    # need; the variables it DOES need are checked for gaps below.
    d = load_daily_forcing(source, lat, lon, y0, y1, forcing_dir=forcing_dir,
                           on_missing="nan")
    missing = [k for k in NEEDED_KEYS if k not in d]
    if missing:
        raise KeyError(f"loader returned no {missing}")
    gaps = {k: int(np.isnan(np.asarray(d[k], float)).sum()) for k in NEEDED_KEYS}
    gaps = {k: n for k, n in gaps.items() if n}
    if gaps:
        raise ValueError(f"{source} has gaps (days missing per variable): {gaps}. "
                         "Gaps are not filled; choose another period or source.")
    return d


def to_cf_arrays(d):
    t = np.asarray(d["temp_mean_c"], float)
    out = {
        "temp": t + 273.15,
        "prec": np.asarray(d["precip_mm"], float) / 86400.0,  # mm/day -> kg m-2 s-1
        "insol": np.asarray(d["srad_wm2"], float),
        "min_temp": np.asarray(d["temp_min_c"], float) + 273.15,
        "max_temp": np.asarray(d["temp_max_c"], float) + 273.15,
        "relhum": relative_humidity(np.asarray(d["shum_kgkg"], float),
                                    np.asarray(d["pres_pa"], float), t),
        "wind": np.asarray(d["wind_ms"], float),
    }
    return out


def validate_outputs(arrs, dates, y0, y1):
    """Physical plausibility on the CF-unit arrays. Returns list of errors."""
    errs = []
    years = np.unique(dates.astype("datetime64[Y]").astype(int) + 1970)
    if len(years) < NYEAR_SPINUP_DATA:
        errs.append(f"only {len(years)} years ({y0}-{y1}); the CF input module needs "
                    f">= {NYEAR_SPINUP_DATA} full years to build its spin-up climate")
    if str(dates[0])[5:] != "01-01":
        errs.append(f"series starts {dates[0]}, not on 1 January")
    tc = arrs["temp"].mean() - 273.15
    if not -25 < tc < 32:
        errs.append(f"mean air temperature {tc:.1f} degC implausible (K/degC mix-up?)")
    p = arrs["prec"].mean() * 86400 * 365
    if not 20 < p < 6000:
        errs.append(f"annual precipitation {p:.0f} mm implausible (flux/amount unit?)")
    s = arrs["insol"].mean()
    if not 40 < s < 350:
        errs.append(f"mean shortwave {s:.0f} W m-2 implausible (MJ vs W m-2?)")
    if (arrs["min_temp"] > arrs["max_temp"] + 1e-6).any():
        errs.append("min_temp > max_temp on some days")
    for k, a in arrs.items():
        if not np.isfinite(a).all():
            errs.append(f"{k} has non-finite values")
    if (arrs["prec"] < 0).any() or (arrs["insol"] < 0).any():
        errs.append("negative precipitation or shortwave")
    try:
        from ki_tools_common.validation import validate_forcing_ranges
        for w in validate_forcing_ranges({"temperature": arrs["temp"],
                                          "precipitation": arrs["prec"] * 86400,
                                          "shortwave": arrs["insol"]}):
            print("  [range warning]", w)
    except Exception as e:  # warnings only; the hard checks are above
        print("  [range check skipped]", e)
    return errs


def write_nc(path, name, values, dates, lat, lon, y0):
    import netCDF4
    std, units = VARS[name]
    with netCDF4.Dataset(path, "w", format="NETCDF3_64BIT_OFFSET") as nc:
        nc.createDimension("lat", 1)
        nc.createDimension("lon", 1)
        nc.createDimension("time", len(values))
        v = nc.createVariable("lat", "f8", ("lat",))
        v.standard_name, v.units, v[:] = "latitude", "degrees_north", [lat]
        v = nc.createVariable("lon", "f8", ("lon",))
        v.standard_name, v.units, v[:] = "longitude", "degrees_east", [lon]
        v = nc.createVariable("time", "f8", ("time",))
        v.units, v.calendar = f"days since {y0}-01-01 00:00:00", "standard"
        v.standard_name = "time"
        days = (dates - np.datetime64(f"{y0}-01-01")).astype(int)
        v[:] = days
        v = nc.createVariable(name, "f4", ("lat", "lon", "time"))
        v.standard_name, v.units = std, units
        v[0, 0, :] = values.astype("f4")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--site", required=True, help="site label written to the gridlist")
    ap.add_argument("--lat", type=float, required=True)
    ap.add_argument("--lon", type=float, required=True)
    ap.add_argument("--start_year", type=int, required=True)
    ap.add_argument("--end_year", type=int, required=True)
    ap.add_argument("--source", choices=["nasa_power", "cmfd", "mswx"], required=True,
                    help="nasa_power = global, 1984+ for shortwave; cmfd = China only")
    ap.add_argument("--forcing_dir", default=None, help="store root for cmfd/mswx")
    ap.add_argument("--out_dir", required=True)
    a = ap.parse_args()

    if a.end_year - a.start_year + 1 < NYEAR_SPINUP_DATA:
        print(f"ERROR: {a.start_year}-{a.end_year} is shorter than the {NYEAR_SPINUP_DATA} "
              "years the CF input module needs for spin-up (see triplets).", file=sys.stderr)
        return 2
    try:
        d = load(a.source, a.lat, a.lon, a.start_year, a.end_year, a.forcing_dir)
    except Exception as e:
        print(f"ERROR loading {a.source}: {e}", file=sys.stderr)
        return 3
    try:
        dates = np.asarray(d["dates"]).astype("datetime64[D]")
        arrs = to_cf_arrays(d)
        if any(len(v) != len(dates) for v in arrs.values()):
            raise ValueError("loader arrays and dates differ in length")
    except (KeyError, ValueError, TypeError) as e:
        print(f"ERROR: loader output unusable: {e}", file=sys.stderr)
        return 3
    errs = validate_outputs(arrs, dates, a.start_year, a.end_year)
    if errs:
        for e in errs:
            print("ERROR:", e, file=sys.stderr)
        return 2

    files = {}
    gl = os.path.join(a.out_dir, "gridlist_cf.txt")
    try:
        os.makedirs(a.out_dir, exist_ok=True)
        for name, vals in arrs.items():
            p = os.path.join(a.out_dir, f"{name}.nc")
            write_nc(p, name, vals, dates, a.lat, a.lon, a.start_year)
            files[name] = {"file": os.path.abspath(p), "variable": name}
        with open(gl, "w") as f:
            f.write(f"0 0 {a.site}\n")
    except (OSError, RuntimeError) as e:   # netCDF4 raises RuntimeError on write errors
        print(f"ERROR: cannot write forcing to {a.out_dir}: {e}", file=sys.stderr)
        return 2
    meta = {
        "site": a.site, "lat": a.lat, "lon": a.lon, "source": a.source,
        "start_year": a.start_year, "end_year": a.end_year, "n_days": int(len(dates)),
        "gridlist": os.path.abspath(gl), "files": files,
        "summary": {
            "mean_temp_c": round(float(arrs["temp"].mean() - 273.15), 2),
            "annual_precip_mm": round(float(arrs["prec"].mean() * 86400 * 365.25), 1),
            "mean_insol_wm2": round(float(arrs["insol"].mean()), 1),
            "mean_relhum": round(float(arrs["relhum"].mean()), 3),
        },
    }
    try:
        with open(os.path.join(a.out_dir, "forcing_meta.json"), "w") as f:
            json.dump(meta, f, indent=2)
    except OSError as e:
        print(f"ERROR: cannot write forcing_meta.json: {e}", file=sys.stderr)
        return 2
    print(json.dumps({"status": "success", **meta["summary"], "out_dir": a.out_dir}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
