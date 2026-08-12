"""
MARRMoT Forcing Converter
=========================
Convert global meteorological data (ERA5, CMFD, MSWX, generic CSV/NetCDF)
into the 3-column climate array required by MARRMoT: [P, Ep, T].

Units:
  - Precipitation (P): mm/d
  - Potential evapotranspiration (Ep): mm/d
  - Temperature (T): deg C

CRITICAL: MARRMoT expects [P, Ep, T] column order, NOT [P, T, Ep].
  Swapping columns is a silent error (dt_011).

CRITICAL: MARRMoT does NOT compute PET internally. If your source only
  has radiation or Tmin/Tmax, you must compute PET externally first
  (Hargreaves or Penman-Monteith). Passing radiation as PET is dt_004.

Usage:
  python convert_forcing.py --input era5_daily.nc --format era5 \
    --lat 35.5 --lon 117.3 --start 2000-01-01 --end 2010-12-31 \
    --output forcing.csv

  python convert_forcing.py --input local_data.csv --format csv \
    --p-col precip_mm_d --ep-col pet_mm_d --t-col temp_c \
    --output forcing.csv
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta

import numpy as np

try:
    import pandas as pd
except ImportError:
    pd = None

try:
    import xarray as xr
except ImportError:
    xr = None


# ── Unit conversion constants ────────────────────────────────────────
KG_M2_S_TO_MM_D = 86400.0       # kg/m2/s -> mm/d  (ERA5 precip)
M_D_TO_MM_D = 1000.0            # m/d -> mm/d
K_TO_C = -273.15                 # K -> deg C
LATENT_HEAT_VAPORISATION = 2.45  # MJ/kg (approx at 20C)
MJ_M2_D_TO_MM_D = 1.0 / LATENT_HEAT_VAPORISATION  # radiation to ET equiv


def validate_inputs(args):
    """Validate all inputs before processing."""
    errors = []

    # nasa_power needs no input file (fetched live via load_forcing)
    if args.format != "nasa_power":
        if not args.input or not os.path.isfile(args.input):
            errors.append(f"Input file not found: {args.input}")

    if args.format not in ("era5", "cmfd", "mswx", "csv", "generic",
                           "caravan", "nasa_power"):
        errors.append(f"Unknown format: {args.format}. "
                       "Use era5, cmfd, mswx, csv, generic, caravan, "
                       "or nasa_power.")

    if args.format in ("era5", "cmfd", "mswx", "nasa_power"):
        if args.lat is None or args.lon is None:
            errors.append("--lat and --lon required for gridded formats.")
        if args.lat is not None and not (-90 <= args.lat <= 90):
            errors.append(f"Latitude out of range: {args.lat}")
        if args.lon is not None and not (-180 <= args.lon <= 360):
            errors.append(f"Longitude out of range: {args.lon}")

    if args.start and args.end:
        try:
            s = datetime.strptime(args.start, "%Y-%m-%d")
            e = datetime.strptime(args.end, "%Y-%m-%d")
            if s >= e:
                errors.append("--start must be before --end")
        except ValueError as exc:
            errors.append(f"Date parse error: {exc}")

    if errors:
        print(json.dumps({"status": "error", "errors": errors}),
              file=sys.stdout)
        sys.exit(1)


def hargreaves_pet(tmin, tmax, tmean, doy, lat_rad):
    """
    Compute Hargreaves PET estimate (mm/d).

    Parameters
    ----------
    tmin, tmax, tmean : array-like, deg C
    doy : array-like, day of year (1-366)
    lat_rad : float, latitude in radians

    Returns
    -------
    pet : ndarray, mm/d
    """
    # Solar declination
    dr = 1 + 0.033 * np.cos(2 * np.pi * doy / 365)
    delta = 0.4093 * np.sin(2 * np.pi * doy / 365 - 1.39)

    # Sunset hour angle
    ws = np.arccos(-np.tan(lat_rad) * np.tan(delta))

    # Extra-terrestrial radiation (MJ/m2/d)
    Gsc = 0.0820  # solar constant
    Ra = (24 * 60 / np.pi) * Gsc * dr * (
        ws * np.sin(lat_rad) * np.sin(delta) +
        np.cos(lat_rad) * np.cos(delta) * np.sin(ws)
    )

    # Hargreaves equation
    tdiff = np.maximum(tmax - tmin, 0.0)
    pet = 0.0023 * Ra * np.sqrt(tdiff) * (tmean + 17.8) * MJ_M2_D_TO_MM_D
    return np.maximum(pet, 0.0)


def _extraterrestrial_radiation(doy, lat_rad):
    """Extra-terrestrial radiation Ra (MJ/m2/d) from day-of-year and latitude."""
    dr = 1 + 0.033 * np.cos(2 * np.pi * doy / 365)
    delta = 0.4093 * np.sin(2 * np.pi * doy / 365 - 1.39)
    ws = np.arccos(np.clip(-np.tan(lat_rad) * np.tan(delta), -1.0, 1.0))
    Gsc = 0.0820  # solar constant MJ/m2/min
    Ra = (24 * 60 / np.pi) * Gsc * dr * (
        ws * np.sin(lat_rad) * np.sin(delta) +
        np.cos(lat_rad) * np.cos(delta) * np.sin(ws)
    )
    return Ra


def oudin_pet(tmean, doy, lat_rad):
    """Oudin (2005) temperature-based PET (mm/d).

    PE = Ra/(lambda*rho) * (Tmean+5)/100  when Tmean+5 > 0, else 0.
    With Ra in MJ/m2/d, lambda=2.45 MJ/kg, rho=1000 kg/m3 this reduces to
    PE[mm/d] = Ra*(Tmean+5)/(245).

    Unlike Hargreaves, Oudin needs ONLY daily mean T + latitude -- the correct
    choice for daily-mean-only reanalyses such as CMFD daily 0.25deg, where
    Tmin==Tmax so Hargreaves' sqrt(Tmax-Tmin) term collapses PET to 0 (a silent
    trap). Oudin is also the PET the GR4J/GR-family models were derived with,
    so it pairs naturally with m_07_gr4j_4p_2s.
    """
    Ra = _extraterrestrial_radiation(np.asarray(doy, dtype=float), lat_rad)
    pe = Ra * (np.asarray(tmean, dtype=float) + 5.0) / 245.0
    return np.maximum(pe, 0.0)


def priestley_taylor_pet(srad, lrad, tmean, pres, albedo=0.23, alpha=1.26):
    """Priestley-Taylor (1972) PET (mm/d) from downwelling radiation.

    PE = alpha * Delta/(Delta+gamma) * (Rn - G) / lambda

    Parameters
    ----------
    srad : array-like, downwelling SHORTwave radiation, W/m2
    lrad : array-like, downwelling LONGwave radiation, W/m2
    tmean : array-like, daily mean air temperature, deg C
    pres : array-like, surface pressure, Pa
    albedo : float, surface albedo (0.23 = FAO-56 reference grass)
    alpha : float, Priestley-Taylor coefficient (1.26 = wet-surface standard)

    Why this exists (dt_019): Oudin/Hargreaves are temperature-index PET
    formulae calibrated on temperate lowlands. On cold, high-insolation,
    high-altitude terrain (e.g. the Tibetan Plateau) they structurally
    UNDER-estimate atmospheric demand, so Ep falls below the mass-balance
    requirement Ep >= P - Q. MARRMoT bounds Ea by Ep, so the optimiser then
    has no evaporative exit for the water surplus and drives whatever flux
    can remove mass (for m_07_gr4j_4p_2s: the x2 groundwater-exchange term)
    hard against its bound -- yielding a respectable NSE from a non-physical,
    non-identifiable fit that only a P-Ea-Q check catches.

    Passing --pres-col matters at altitude: the sea-level fallback
    (101325 Pa) inflates the psychrometric constant gamma and therefore
    under-estimates Ep exactly where the trap bites.
    """
    srad = np.asarray(srad, dtype=float)
    lrad = np.asarray(lrad, dtype=float)
    tmean = np.asarray(tmean, dtype=float)
    pres = np.asarray(pres, dtype=float)

    # Saturation vapour pressure slope Delta (kPa/degC)
    es = 0.6108 * np.exp(17.27 * tmean / (tmean + 237.3))
    delta = 4098.0 * es / np.power(tmean + 237.3, 2)

    # Psychrometric constant gamma (kPa/degC); pres Pa -> kPa
    gamma = 0.665e-3 * (pres / 1000.0)

    # Net radiation Rn (W/m2): net shortwave + net longwave.
    # Outgoing longwave via Stefan-Boltzmann at surface emissivity 0.98.
    SIGMA = 5.670374419e-8  # W/m2/K4
    EMIS = 0.98
    tk = tmean - K_TO_C  # K_TO_C is -273.15, so this is degC + 273.15
    rn_sw = (1.0 - albedo) * srad
    rn_lw = lrad - EMIS * SIGMA * np.power(tk, 4)
    rn = rn_sw + rn_lw

    # W/m2 -> MJ/m2/d
    rn_mj = rn * 0.0864

    # Ground heat flux G ~ 0 at daily timestep
    pe = alpha * (delta / (delta + gamma)) * rn_mj * MJ_M2_D_TO_MM_D
    return np.maximum(pe, 0.0)


def convert_era5(input_path, lat, lon, start, end):
    """Convert ERA5 daily NetCDF to MARRMoT forcing."""
    if xr is None:
        print(json.dumps({"status": "error",
                          "errors": ["xarray required for ERA5 conversion"]}))
        sys.exit(1)

    ds = xr.open_dataset(input_path)
    # Select nearest grid cell
    ds = ds.sel(latitude=lat, longitude=lon, method="nearest")

    if start and end:
        ds = ds.sel(time=slice(start, end))

    times = pd.DatetimeIndex(ds.time.values)

    # Precipitation: ERA5 tp is m/d or kg/m2/s depending on product
    if "tp" in ds:
        p_raw = ds["tp"].values
        # Detect units: if max < 1, likely m/d
        if np.nanmax(p_raw) < 1.0:
            precip = p_raw * M_D_TO_MM_D
            print("Converted precip from m/d to mm/d", file=sys.stderr)
        else:
            precip = p_raw * KG_M2_S_TO_MM_D
            print("Converted precip from kg/m2/s to mm/d", file=sys.stderr)
    else:
        raise KeyError("No precipitation variable found (expected 'tp')")

    # Temperature: ERA5 t2m is in K
    if "t2m" in ds:
        temp = ds["t2m"].values + K_TO_C
        print("Converted temperature from K to deg C", file=sys.stderr)
    elif "T2M" in ds:
        temp = ds["T2M"].values + K_TO_C
    else:
        raise KeyError("No temperature variable found (expected 't2m')")

    # PET: compute via Hargreaves if Tmin/Tmax available, else use provided
    if "pet" in ds or "pev" in ds:
        varname = "pet" if "pet" in ds else "pev"
        pet_raw = ds[varname].values
        # ERA5 PET is negative (energy leaving surface) and in m/d
        pet = np.abs(pet_raw) * M_D_TO_MM_D
        print(f"Converted PET from {varname} (m/d) to mm/d", file=sys.stderr)
    else:
        # Estimate PET from temperature using Hargreaves
        lat_rad = np.radians(lat)
        doy = times.dayofyear.values
        # Approximate Tmin/Tmax as T +/- 5 C (rough estimate)
        tmin = temp - 5.0
        tmax = temp + 5.0
        pet = hargreaves_pet(tmin, tmax, temp, doy, lat_rad)
        print("Estimated PET using Hargreaves (no PET in source)",
              file=sys.stderr)

    ds.close()
    return times, precip, pet, temp


def convert_caravan(input_path, start, end, obs_output=None):
    """Convert a Caravan / GRDC-Caravan-extension NetCDF file to MARRMoT forcing.

    The Caravan dataset bundles catchment-mean ERA5-Land meteorology AND the
    observed streamflow in a single per-gauge NetCDF, already on a lumped
    (basin-averaged) 0-D footing -- exactly what a lumped rainfall-runoff
    model such as MARRMoT consumes. For a large catchment (e.g. Moselle at
    Cochem, ~27,000 km2) this catchment-mean forcing is far more
    representative than re-extracting a single grid cell at the outlet.

    Variables read (Caravan convention, all already in MARRMoT units):
      - total_precipitation_sum  -> P  (mm/d)
      - potential_evaporation_sum-> Ep (mm/d; clipped to >=0)
      - temperature_2m_mean      -> T  (deg C)
      - streamflow               -> observed Q (mm/d), written to obs_output

    The Caravan ``potential_evaporation_sum`` is ERA5-Land PET that can be
    slightly negative at night-dominated winter days; negatives are clipped
    to 0 (a non-negative PET is physically required by MARRMoT's Ep input).
    """
    try:
        import netCDF4
    except ImportError:
        print(json.dumps({"status": "error",
                          "errors": ["netCDF4 required for caravan format"]}))
        sys.exit(1)
    if pd is None:
        print(json.dumps({"status": "error",
                          "errors": ["pandas required for caravan format"]}))
        sys.exit(1)

    ds = netCDF4.Dataset(input_path)
    date_var = ds.variables["date"]
    # Decode 'days since YYYY-MM-DD' time axis
    times = pd.DatetimeIndex(
        netCDF4.num2date(date_var[:], date_var.units,
                         only_use_cftime_datetimes=False))

    precip = np.asarray(ds.variables["total_precipitation_sum"][:], dtype=float)
    pet = np.asarray(ds.variables["potential_evaporation_sum"][:], dtype=float)
    temp = np.asarray(ds.variables["temperature_2m_mean"][:], dtype=float)
    qobs = None
    if "streamflow" in ds.variables:
        qobs = np.asarray(ds.variables["streamflow"][:], dtype=float)
    ds.close()

    # Clip physically-impossible negative PET (ERA5-Land nighttime artifact)
    n_neg = int(np.sum(pet < 0))
    if n_neg:
        print(f"Clipped {n_neg} negative PET values to 0 (ERA5-Land artifact)",
              file=sys.stderr)
        pet = np.maximum(pet, 0.0)

    # Subset to requested period (inclusive)
    mask = np.ones(len(times), dtype=bool)
    if start:
        mask &= (times >= pd.Timestamp(start))
    if end:
        mask &= (times <= pd.Timestamp(end))
    times = times[mask]
    precip, pet, temp = precip[mask], pet[mask], temp[mask]
    if qobs is not None:
        qobs = qobs[mask]

    # Emit observed streamflow CSV (already mm/d -- no area conversion needed)
    if obs_output and qobs is not None:
        os.makedirs(os.path.dirname(obs_output) or ".", exist_ok=True)
        with open(obs_output, "w") as f:
            f.write("date,Q_mm_d\n")
            for i in range(len(times)):
                f.write(f"{times[i].strftime('%Y-%m-%d')},{qobs[i]:.6f}\n")
        print(f"Wrote {len(times)} observed Q (mm/d) to {obs_output}",
              file=sys.stderr)

    return times, precip, pet, temp


def convert_nasa_power(lat, lon, start, end):
    """Fetch daily forcing from NASA POWER via ki_tools_common.load_forcing and
    build the MARRMoT [P, Ep, T] arrays.

    This is the canonical, no-input-file path documented in SKILL.md ("Use
    ki_tools_common.load_forcing for CMFD/MSWX/NASA POWER"). NASA POWER returns
    daily P, Tmin, Tmax, Tmean (deg C) at a point -- ideal for a lumped basin
    centroid. MARRMoT does NOT compute PET internally (dt_004), so Ep is derived
    here with Hargreaves from the daily Tmin/Tmax/Tmean (the only radiation-free
    PET method that needs nothing beyond the NASA POWER temperature triplet).
    """
    if pd is None:
        print(json.dumps({"status": "error",
                          "errors": ["pandas required for nasa_power format"]}))
        sys.exit(1)
    from ki_tools_common import load_forcing as _lf

    sy = int(start[:4]) if start else None
    ey = int(end[:4]) if end else None
    if sy is None or ey is None:
        print(json.dumps({"status": "error", "errors": [
            "nasa_power format requires --start and --end (YYYY-MM-DD)"]}))
        sys.exit(1)

    d = _lf.load_daily_forcing("nasa_power", lat, lon, sy, ey)
    times = pd.DatetimeIndex(pd.to_datetime(d["dates"]))
    precip = np.asarray(d["precip_mm"], dtype=float)
    temp = np.asarray(d["temp_mean_c"], dtype=float)
    tmin = np.asarray(d["temp_min_c"], dtype=float)
    tmax = np.asarray(d["temp_max_c"], dtype=float)

    doy = times.dayofyear.values
    pet = hargreaves_pet(tmin, tmax, temp, doy, np.radians(lat))
    print(f"NASA POWER: {len(times)} days; Hargreaves PET mean "
          f"{np.nanmean(pet):.2f} mm/d", file=sys.stderr)

    # Subset to exact day boundaries (load_forcing returns whole calendar years)
    mask = np.ones(len(times), dtype=bool)
    if start:
        mask &= (times >= pd.Timestamp(start))
    if end:
        mask &= (times <= pd.Timestamp(end))
    return times[mask], precip[mask], pet[mask], temp[mask]


def convert_csv(input_path, p_col, ep_col, t_col, date_col, start, end,
                pet_method="column", tmin_col=None, tmax_col=None,
                lat=None, srad_col=None, lrad_col=None, pres_col=None):
    """Convert generic CSV to MARRMoT forcing.

    PET handling (dt_004): MARRMoT does NOT compute PET internally. The CSV
    path supports two ways to supply it:
      - pet_method='column'     : read pre-computed PET from ``ep_col`` (default).
      - pet_method='hargreaves' : compute Hargreaves PET from daily Tmin/Tmax
        (``tmin_col``/``tmax_col``) + mean T (``t_col``) and ``lat``. Use this
        when the only available PET product is unreliable (e.g. ERA5-Land
        potential_evaporation, which overestimates by ~2x and over-dries the
        soil store). Requires --lat, --tmin-col, --tmax-col.
      - pet_method='oudin'      : compute Oudin (2005) PET from daily MEAN T
        (``t_col``) + ``lat`` only. Use this for daily-mean-only reanalyses
        such as CMFD daily 0.25deg, where Tmin==Tmax makes Hargreaves collapse
        to 0. Requires --lat only. This is the GR-family reference PET.
      - pet_method='priestley_taylor' : compute Priestley-Taylor PET from
        downwelling shortwave (``srad_col``, W/m2), downwelling longwave
        (``lrad_col``, W/m2), mean T (``t_col``) and surface pressure
        (``pres_col``, Pa). Use this wherever the forcing ships radiation
        (CMFD, MSWX, ERA5 all do) and ESPECIALLY on cold/high-altitude
        basins where the temperature-index methods under-estimate demand
        and break the Ep >= P - Q mass-feasibility requirement (dt_019).
        Requires --lat, --srad-col, --lrad-col; --pres-col strongly
        recommended at altitude (sea-level fallback inflates gamma).
    """
    if pd is None:
        print(json.dumps({"status": "error",
                          "errors": ["pandas required for CSV conversion"]}))
        sys.exit(1)

    df = pd.read_csv(input_path, parse_dates=[date_col])
    df = df.sort_values(date_col).reset_index(drop=True)

    if start:
        df = df[df[date_col] >= start]
    if end:
        df = df[df[date_col] <= end]

    times = pd.DatetimeIndex(df[date_col].values)
    precip = df[p_col].values.astype(float)
    temp = df[t_col].values.astype(float)

    if pet_method == "hargreaves":
        if tmin_col is None or tmax_col is None or lat is None:
            print(json.dumps({"status": "error", "errors": [
                "pet_method=hargreaves requires --tmin-col, --tmax-col and --lat"]}))
            sys.exit(1)
        tmin = df[tmin_col].values.astype(float)
        tmax = df[tmax_col].values.astype(float)
        doy = times.dayofyear.values
        pet = hargreaves_pet(tmin, tmax, temp, doy, np.radians(lat))
        print(f"Computed Hargreaves PET from Tmin/Tmax at lat={lat} "
              f"(mean {np.nanmean(pet):.2f} mm/d)", file=sys.stderr)
    elif pet_method == "oudin":
        if lat is None:
            print(json.dumps({"status": "error", "errors": [
                "pet_method=oudin requires --lat"]}))
            sys.exit(1)
        doy = times.dayofyear.values
        pet = oudin_pet(temp, doy, np.radians(lat))
        print(f"Computed Oudin PET from mean T at lat={lat} "
              f"(mean {np.nanmean(pet):.2f} mm/d)", file=sys.stderr)
    elif pet_method == "priestley_taylor":
        missing = [n for n, v in (("--srad-col", srad_col),
                                  ("--lrad-col", lrad_col)) if v is None]
        if missing or lat is None:
            if lat is None:
                missing.append("--lat")
            print(json.dumps({"status": "error", "errors": [
                "pet_method=priestley_taylor requires "
                + ", ".join(missing)]}))
            sys.exit(1)
        srad = df[srad_col].values.astype(float)
        lrad = df[lrad_col].values.astype(float)
        if pres_col is not None:
            pres = df[pres_col].values.astype(float)
        else:
            pres = np.full(len(df), 101325.0)
            print("WARNING: --pres-col not given; assuming sea-level "
                  "101325 Pa. At altitude this inflates gamma and "
                  "UNDER-estimates Ep (dt_019).", file=sys.stderr)
        pet = priestley_taylor_pet(srad, lrad, temp, pres)
        print(f"Computed Priestley-Taylor PET from srad/lrad at lat={lat} "
              f"(mean {np.nanmean(pet):.2f} mm/d, "
              f"{np.nanmean(pet) * 365.25:.1f} mm/yr)", file=sys.stderr)
    else:
        pet = df[ep_col].values.astype(float)

    return times, precip, pet, temp


def process(args):
    """Main processing: convert forcing data."""
    if args.format == "nasa_power":
        times, precip, pet, temp = convert_nasa_power(
            args.lat, args.lon, args.start, args.end)
    elif args.format == "caravan":
        times, precip, pet, temp = convert_caravan(
            args.input, args.start, args.end, obs_output=args.obs_output)
    elif args.format == "era5":
        times, precip, pet, temp = convert_era5(
            args.input, args.lat, args.lon, args.start, args.end)
    elif args.format in ("csv", "generic"):
        times, precip, pet, temp = convert_csv(
            args.input, args.p_col, args.ep_col, args.t_col,
            args.date_col, args.start, args.end,
            pet_method=args.pet_method, tmin_col=args.tmin_col,
            tmax_col=args.tmax_col, lat=args.lat,
            srad_col=args.srad_col, lrad_col=args.lrad_col,
            pres_col=args.pres_col)
    else:
        # CMFD/MSWX: similar to ERA5 but with different variable names
        # For now, treat as ERA5 with auto-detection
        times, precip, pet, temp = convert_era5(
            args.input, args.lat, args.lon, args.start, args.end)

    # Gauge-undercatch / orographic precip correction. NASA POWER (MERRA-2)
    # systematically under-catches precip in mountainous / interior / snowy
    # basins (documented Moyie x1.25, Coldwater x1.7). A multiplicative
    # correction closes the water balance; it is reported so it is never silent.
    precip_scale = float(getattr(args, "precip_scale", 1.0) or 1.0)
    if precip_scale != 1.0:
        precip = precip * precip_scale
        print(f"Applied precip_scale={precip_scale} (undercatch correction)",
              file=sys.stderr)

    # Cold-day (snowfall) undercatch correction. Gauge AND reanalysis
    # (MERRA-2/NASA POWER) under-catch SOLID precipitation far more than rain --
    # unshielded gauges miss 30-100% of snowfall (Goodison WMO; Rasmussen 2012).
    # For snowmelt-dominated basins the spring freshet (the NSE-dominant signal)
    # is driven by accumulated winter snow, so under-caught snowfall systematically
    # damps the simulated freshet. A multiplicative factor applied ONLY on days
    # with T < --cold-precip-threshold boosts winter accumulation without
    # inflating ET-dominated summer months (which a global --precip-scale does,
    # over-producing runoff -- observed at this very basin). Reported, never silent.
    cold_scale = float(getattr(args, "cold_precip_scale", 1.0) or 1.0)
    cold_thr = float(getattr(args, "cold_precip_threshold", 0.0))
    if cold_scale != 1.0:
        cold_mask = temp < cold_thr
        n_cold = int(np.sum(cold_mask))
        precip = np.where(cold_mask, precip * cold_scale, precip)
        print(f"Applied cold_precip_scale={cold_scale} on {n_cold} days with "
              f"T<{cold_thr}C (snowfall undercatch correction)", file=sys.stderr)

    result = {
        "status": "success",
        "n_timesteps": len(times),
        "start_date": str(times[0].date()),
        "end_date": str(times[-1].date()),
        "precip_scale": precip_scale,
        "cold_precip_scale": cold_scale,
        "precip_mean_mm_d": float(np.nanmean(precip)),
        "precip_total_mm": float(np.nansum(precip)),
        "pet_mean_mm_d": float(np.nanmean(pet)),
        "temp_mean_c": float(np.nanmean(temp)),
        "warnings": [],
    }

    # Sanity checks on values
    if np.nanmean(precip) > 50:
        result["warnings"].append(
            "Mean precip > 50 mm/d -- possible unit error (dt_001/dt_002)")
    if np.nanmean(precip) < 0.01:
        result["warnings"].append(
            "Mean precip < 0.01 mm/d -- check if units are m/d (dt_003)")
    if np.nanmean(temp) > 100:
        result["warnings"].append(
            "Mean temp > 100 -- likely Kelvin, subtract 273.15 (dt_006)")
    if np.any(pet < 0):
        result["warnings"].append(
            "Negative PET values found -- check sign convention")
    if np.nanmean(pet) > 20:
        result["warnings"].append(
            "Mean PET > 20 mm/d -- possible radiation input (dt_004)")

    # Write CSV output: columns are P, Ep, T (MARRMoT order!)
    output_path = args.output
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    header = "# MARRMoT forcing file\n"
    header += "# Columns: date, P(mm/d), Ep(mm/d), T(degC)\n"
    header += "# Generated by convert_forcing.py\n"
    header += f"# Period: {result['start_date']} to {result['end_date']}\n"

    with open(output_path, "w") as f:
        f.write(header)
        f.write("date,P_mm_d,Ep_mm_d,T_degC\n")
        for i in range(len(times)):
            f.write(f"{times[i].strftime('%Y-%m-%d')},"
                    f"{precip[i]:.4f},{pet[i]:.4f},{temp[i]:.4f}\n")

    result["output_file"] = output_path
    print(f"Wrote {len(times)} timesteps to {output_path}", file=sys.stderr)
    return result


def validate_outputs(result):
    """Validate output data quality."""
    warnings = result.get("warnings", [])

    if result["n_timesteps"] < 365:
        warnings.append("Less than 1 year of data -- consider longer period")

    if result["precip_total_mm"] < 100:
        warnings.append("Total precip < 100 mm -- unusually dry, check units")

    result["warnings"] = warnings
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Convert meteorological data to MARRMoT forcing format")
    parser.add_argument("--input", required=False, default=None,
                        help="Input file (NetCDF or CSV); not needed for "
                             "nasa_power (fetched live)")
    parser.add_argument("--format", default="csv",
                        choices=["era5", "cmfd", "mswx", "csv", "generic",
                                 "caravan", "nasa_power"],
                        help="Input data format")
    parser.add_argument("--output", required=True,
                        help="Output CSV file path")
    parser.add_argument("--obs-output", default=None,
                        help="Optional observed Q CSV path (caravan format: "
                             "extracts bundled streamflow in mm/d)")
    parser.add_argument("--lat", type=float, default=None,
                        help="Latitude for gridded data extraction")
    parser.add_argument("--lon", type=float, default=None,
                        help="Longitude for gridded data extraction")
    parser.add_argument("--start", default=None,
                        help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", default=None,
                        help="End date (YYYY-MM-DD)")
    parser.add_argument("--precip-scale", type=float, default=1.0,
                        help="Multiplicative precip correction for gauge "
                             "undercatch / orographic deficit (e.g. 1.3 for "
                             "NASA POWER in snowy/interior basins). Default 1.0")
    parser.add_argument("--cold-precip-scale", type=float, default=1.0,
                        help="Multiplicative precip correction applied ONLY on "
                             "cold days (T < --cold-precip-threshold), for "
                             "solid-precip (snowfall) undercatch. Boosts the "
                             "snowmelt freshet without inflating summer ET "
                             "months. Typical 1.5-2.0 for NASA POWER. Default 1.0")
    parser.add_argument("--cold-precip-threshold", type=float, default=0.0,
                        help="Daily mean-T threshold (degC) below which "
                             "--cold-precip-scale applies. Default 0.0")
    parser.add_argument("--p-col", default="P_mm_d",
                        help="Precipitation column name (CSV format)")
    parser.add_argument("--ep-col", default="Ep_mm_d",
                        help="PET column name (CSV format)")
    parser.add_argument("--t-col", default="T_degC",
                        help="Temperature column name (CSV format)")
    parser.add_argument("--date-col", default="date",
                        help="Date column name (CSV format)")
    parser.add_argument("--pet-method", default="column",
                        choices=["column", "hargreaves", "oudin",
                                 "priestley_taylor"],
                        help="CSV PET source: 'column' (read ep-col), "
                             "'hargreaves' (from Tmin/Tmax + lat), or "
                             "'oudin' (from mean T + lat; use for daily-mean-"
                             "only CMFD where Tmin==Tmax breaks Hargreaves)")
    parser.add_argument("--tmin-col", default=None,
                        help="Daily Tmin column (for --pet-method hargreaves)")
    parser.add_argument("--tmax-col", default=None,
                        help="Daily Tmax column (for --pet-method hargreaves)")
    parser.add_argument("--srad-col", default=None,
                        help="Downwelling SHORTwave radiation column, W/m2 "
                             "(for --pet-method priestley_taylor)")
    parser.add_argument("--lrad-col", default=None,
                        help="Downwelling LONGwave radiation column, W/m2 "
                             "(for --pet-method priestley_taylor)")
    parser.add_argument("--pres-col", default=None,
                        help="Surface pressure column, Pa (for --pet-method "
                             "priestley_taylor). Strongly recommended at "
                             "altitude; sea-level fallback under-estimates Ep")

    args = parser.parse_args()

    validate_inputs(args)
    result = process(args)
    result = validate_outputs(result)

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
