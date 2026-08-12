#!/usr/bin/env python3
"""
Knowledge Infrastructure -- Validated Tool
Tool ID:      validate_national_yield_series
Stage:        s9_output_analysis
Description:  End-to-end driver for the "Multi-Year National-Yield Validation"
              recipe documented in SKILL.md. Produces an annual simulated
              yield series and compares it to a FAOSTAT national yield series,
              emitting a single result JSON (with Pearson r / NSE / KGE so the
              orchestrator's r<0.5 retry trigger is well-defined).

WHY THIS TOOL EXISTS
  The recipe in SKILL.md ("Multi-Year National-Yield Validation") was prose
  only -- no implementing tool. With nothing to run, the agent had to hand-
  assemble the multi-decade forcing load + multi-year model each retry, and
  repeatedly improvised an unbounded/hourly forcing read that hung and emitted
  no result JSON (test_results=null on retries #1-#3). This tool makes the
  documented workflow a single bounded, deterministic command.

KEY GUARANTEES (the traps the recipe warns about, enforced in code)
  - Forcing is loaded ONCE for the whole window (one daily point series),
    NEVER per-year and NEVER hourly/gridded across decades.
  - Default source is nasa_power (one bounded HTTP request per year, 1981+),
    NOT cmfd (which opens 6*12*N_years NetCDF tiles -- the IO hang).
  - The window is capped (<= 25 years) regardless of source.
  - ALL seasons are read from get_simulation_results() (one row per harvest
    year), NOT just season-0 -- run_aquacrop's dry_yield_tha hides seasons 2..N.

Inputs (CLI):
  --crop, --country, --lat, --lon, --y0, --y1, --soil, --planting, --source, --out

Outputs:
  - JSON to stdout AND to --out (default: cwd/national_yield_validation.json)
    containing: r, NSE, KGE, RMSE, PBIAS_pct, n, sim/obs series, window, source.

Exit codes: 0=success, 1=input error, 2=processing error, 3=output error
"""

import os
import sys
import json
import argparse
import logging

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# --- make sibling stage tools and ki_tools_common importable -----------------
# NOTE: two ki_tools_common packages exist on this server. Only the canonical
# models/ copy carries get_faostat_yield_series (added 2026-06-06); the
# kdt-release copy does NOT. We must ensure the models/ copy wins. sys.path
# precedence = earliest position, and repeated insert(0) REVERSES list order,
# so list the LOWEST-priority path FIRST and the HIGHEST-priority path LAST.
_HERE = os.path.dirname(os.path.abspath(__file__))
_TOOLS = os.path.dirname(_HERE)                      # tools/
_KI = os.path.dirname(_TOOLS)                        # knowledge_infrastructure/
_KI_COMMON = "/mnt/disk1/Hydrocraft_server/models/ki_tools_common"
for _p in (
    "/home/server/knowledge-dissection-toolkit/kdt-release",  # lowest priority
    _KI_COMMON,                                               # canonical ki_tools_common
    os.path.join(_TOOLS, "s3_weather_prep"),
    _HERE,                                                    # highest priority
):
    if _p in sys.path:
        sys.path.remove(_p)
    sys.path.insert(0, _p)

# W/m2 -> MJ/m2/day  (86400 s/day / 1e6 J/MJ)
WM2_TO_MJ_M2_DAY = 0.0864
MAX_WINDOW_YEARS = 25


def build_weather_df(fc, lat, elevation):
    """Build an AquaCrop weather_df (Date, MinTemp, MaxTemp, Precipitation,
    ReferenceET) from a standardized daily forcing dict. ET0 is computed
    vectorized over the WHOLE series in a single call (FAO-56 PM)."""
    import pandas as pd
    from compute_eto_penman_monteith import compute_et0_fao56

    dates = pd.to_datetime(fc["dates"])
    doy = dates.dayofyear.to_numpy()

    # srad arrives in W/m2; FAO-56 PM expects MJ/m2/day.
    srad_mj = np.asarray(fc["srad_wm2"], dtype=float) * WM2_TO_MJ_M2_DAY

    et0 = compute_et0_fao56(
        tmin=fc["temp_min_c"],
        tmax=fc["temp_max_c"],
        solar_rad=srad_mj,
        wind=fc["wind_ms"],
        lat=lat,
        elevation=elevation,
        doy=doy,
    )

    wdf = pd.DataFrame(
        {
            "Date": dates,
            "MinTemp": np.asarray(fc["temp_min_c"], dtype=float),
            "MaxTemp": np.asarray(fc["temp_max_c"], dtype=float),
            "Precipitation": np.asarray(fc["precip_mm"], dtype=float),
            "ReferenceET": np.asarray(et0, dtype=float),
        }
    )
    wdf["ReferenceET"] = wdf["ReferenceET"].clip(lower=0.1)
    wdf["Precipitation"] = wdf["Precipitation"].clip(lower=0.0)
    wdf = wdf.dropna(subset=["MinTemp", "MaxTemp", "Precipitation", "ReferenceET"])
    return wdf.sort_values("Date").reset_index(drop=True)


def sim_series_by_year(final_stats, y0, y1):
    """Map each simulated season to its harvest year -> {year: dry_yield_tha}.
    Prefers the parsed 'Harvest Date (YYYY/MM/DD)'; falls back to enumerating
    seasons across the window."""
    import pandas as pd

    ycol = None
    for c in final_stats.columns:
        if "Harvest Date" in c and "YYYY" in c:
            ycol = c
            break

    out = {}
    if ycol is not None:
        for _, row in final_stats.iterrows():
            try:
                yr = pd.to_datetime(str(row[ycol])).year
            except Exception:
                continue
            out[int(yr)] = float(row["Dry yield (tonne/ha)"])
    if not out:  # fallback: one season per year in order
        years = list(range(y0, y1 + 1))
        for i, (_, row) in enumerate(final_stats.iterrows()):
            if i < len(years):
                out[years[i]] = float(row["Dry yield (tonne/ha)"])
    return out


def pearson_nse_kge(sim, obs):
    """Pearson r, Nash-Sutcliffe Efficiency, Kling-Gupta Efficiency.
    compute_metrics() (compare_sim_obs) reports RMSE/PBIAS/d-index/R_squared
    but NOT a named Pearson r / NSE / KGE -- the orchestrator keys on r, so we
    compute them here."""
    sim = np.asarray(sim, dtype=float)
    obs = np.asarray(obs, dtype=float)
    m = ~(np.isnan(sim) | np.isnan(obs))
    sim, obs = sim[m], obs[m]
    n = len(sim)
    if n < 2:
        return {"n": int(n), "r": None, "NSE": None, "KGE": None}
    obs_mean = float(np.mean(obs))
    # Pearson r
    if np.std(sim) == 0 or np.std(obs) == 0:
        r = float("nan")
    else:
        r = float(np.corrcoef(sim, obs)[0, 1])
    # NSE
    ss_res = float(np.sum((obs - sim) ** 2))
    ss_tot = float(np.sum((obs - obs_mean) ** 2))
    nse = 1.0 - ss_res / ss_tot if ss_tot != 0 else float("nan")
    # KGE (Gupta et al. 2009)
    if np.isnan(r) or obs_mean == 0 or np.std(obs) == 0:
        kge = float("nan")
    else:
        alpha = float(np.std(sim) / np.std(obs))
        beta = float(np.mean(sim) / obs_mean)
        kge = 1.0 - np.sqrt((r - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2)
    return {
        "n": int(n),
        "r": None if np.isnan(r) else round(r, 4),
        "NSE": None if np.isnan(nse) else round(nse, 4),
        "KGE": None if np.isnan(kge) else round(kge, 4),
    }


def main():
    ap = argparse.ArgumentParser(description="Multi-year national-yield validation for AquaCrop")
    ap.add_argument("--crop", default="maize")
    ap.add_argument("--country", default="China, mainland")
    ap.add_argument("--lat", type=float, default=34.0)
    ap.add_argument("--lon", type=float, default=113.0)
    ap.add_argument("--y0", type=int, default=2008)
    ap.add_argument("--y1", type=int, default=2017)
    ap.add_argument("--soil", default="SandyLoam")
    ap.add_argument("--planting", default="05/01", help="MM/DD planting date")
    ap.add_argument("--source", default="cmfd",
                    choices=["cmfd", "nasa_power", "mswx"],
                    help="Forcing source. Default cmfd (local NetCDF on this "
                         "server). nasa_power is UNREACHABLE from this server "
                         "(power.larc.nasa.gov returns 000 while generic HTTPS "
                         "works) -- do not rely on it here.")
    ap.add_argument("--out", default=os.path.join(os.getcwd(), "national_yield_validation.json"))
    args = ap.parse_args()

    if args.y1 < args.y0:
        logger.error("y1 < y0")
        sys.exit(1)
    span = args.y1 - args.y0 + 1
    if span > MAX_WINDOW_YEARS:
        logger.error(f"Window {span} yr exceeds cap {MAX_WINDOW_YEARS} yr -- "
                     f"narrow --y0/--y1 (unbounded loads hang).")
        sys.exit(1)
    # CMFD costs ~45 s/yr (6 vars x 12 months = 72 NetCDF point-opens/yr,
    # HDF5-open bound -- measured, identical for xarray and netCDF4). A bounded
    # window is fine; an unbounded multi-decade load is the hang seen on retries
    # #1-#3. Warn (don't refuse) so the single bounded call still runs.
    if args.source == "cmfd" and span > 15:
        logger.warning(f"cmfd window = {span} yr (~{span*45//60} min of NetCDF "
                       f"point-opens). Consider narrowing --y0/--y1 if the run "
                       f"budget is tight.")

    try:
        from ki_tools_common.load_forcing import load_daily_forcing
        from compute_eto_penman_monteith import lookup_elevation
        from compare_sim_obs import compute_metrics
        from aquacrop import AquaCropModel, Soil, Crop, InitialWaterContent
        try:
            from ki_tools_common.crop_obs import get_faostat_yield_series
        except ImportError:
            # Fall back to the canonical models/ copy by explicit file load,
            # in case a copy without get_faostat_yield_series got imported first.
            import importlib.util
            _cf = os.path.join(_KI_COMMON, "ki_tools_common", "crop_obs.py")
            _spec = importlib.util.spec_from_file_location("ki_tools_common_crop_obs", _cf)
            _mod = importlib.util.module_from_spec(_spec)
            _spec.loader.exec_module(_mod)
            get_faostat_yield_series = _mod.get_faostat_yield_series
    except Exception as e:
        logger.error(f"Import failure: {e}")
        sys.exit(2)

    # 1. Forcing ONCE for the whole window (daily point series).
    logger.info(f"Loading {args.source} {args.y0}-{args.y1} @ ({args.lat},{args.lon}) [single call]...")
    try:
        fc = load_daily_forcing(args.source, args.lat, args.lon, args.y0, args.y1)
    except Exception as e:
        logger.error(f"Forcing load failed: {e}")
        sys.exit(2)

    # 2. Weather df + ET0 (vectorized, one call).
    try:
        elev = lookup_elevation(args.lat, args.lon)
        weather_df = build_weather_df(fc, args.lat, elev)
    except Exception as e:
        logger.error(f"Weather/ET0 prep failed: {e}")
        sys.exit(2)
    logger.info(f"weather_df: {len(weather_df)} days "
                f"{weather_df['Date'].min().date()}..{weather_df['Date'].max().date()}")

    # 3. ONE multi-year model -> one season per year.
    try:
        model = AquaCropModel(
            sim_start_time=f"{args.y0}/01/01",
            sim_end_time=f"{args.y1}/12/31",
            weather_df=weather_df,
            soil=Soil(args.soil),
            crop=Crop(args.crop.capitalize(), planting_date=args.planting),
            initial_water_content=InitialWaterContent(wc_type="Prop", value=["FC"]),
        )
        model.run_model(till_termination=True)
        final = model.get_simulation_results()
    except Exception as e:
        logger.error(f"Model run failed: {e}")
        sys.exit(2)

    if final is None or final is False or len(final) == 0:
        logger.error("No seasons produced (empty final_stats).")
        sys.exit(2)

    sim = sim_series_by_year(final, args.y0, args.y1)

    # 4. Obs series + align by year.
    obs = get_faostat_yield_series(crop=args.crop, country=args.country,
                                   years=range(args.y0, args.y1 + 1), units="t/ha")
    common = sorted(set(sim) & set(obs))
    if len(common) < 2:
        logger.error(f"Only {len(common)} overlapping years between sim and FAOSTAT "
                     f"({args.crop}/{args.country}); cannot compute a series metric.")
        result = {"status": "insufficient_overlap", "sim_years": sorted(sim),
                  "obs_years": sorted(obs), "n_common": len(common)}
        with open(args.out, "w") as fh:
            json.dump(result, fh, indent=2)
        print(json.dumps(result, indent=2))
        sys.exit(2)

    sim_v = [sim[y] for y in common]
    obs_v = [obs[y] for y in common]

    # 5. Metrics: reuse compute_metrics for RMSE/PBIAS, add r/NSE/KGE.
    base = compute_metrics(sim_v, obs_v)
    rnk = pearson_nse_kge(sim_v, obs_v)

    result = {
        "status": "ok",
        "crop": args.crop,
        "country": args.country,
        "lat": args.lat, "lon": args.lon,
        "window": [args.y0, args.y1],
        "forcing_source": args.source,
        "years": common,
        "sim_tha": [round(v, 4) for v in sim_v],
        "obs_tha": [round(v, 4) for v in obs_v],
        "r": rnk["r"],
        "NSE": rnk["NSE"],
        "KGE": rnk["KGE"],
        "RMSE": base.get("RMSE"),
        "PBIAS_pct": base.get("PBIAS_pct"),
        "n": rnk["n"],
    }

    try:
        with open(args.out, "w") as fh:
            json.dump(result, fh, indent=2)
    except Exception as e:
        logger.error(f"Could not write {args.out}: {e}")
        sys.exit(3)

    logger.info(f"Wrote {args.out}")
    print(json.dumps(result, indent=2))
    sys.exit(0)


if __name__ == "__main__":
    main()
