#!/usr/bin/env python3
"""
Knowledge Infrastructure — Validated Tool
==========================================
Tool ID:      validate_against_faostat
Stage:        s8_yield_analysis
Description:  obs_shape-AWARE validation of a WOFOST yield time series against a
              FAOSTAT NATIONAL/regional yield aggregate.

              WHY THIS TOOL EXISTS (codified 2026-06-08):
              Every prior WOFOST-vs-FAOSTAT run (USA maize, NL/AU wheat, Morocco
              wheat, China maize) hand-rolled metrics in an ad-hoc driver and
              reported RAW NSE / r / KGE as the headline. Comparing a point (or
              few-point) WOFOST sim to a FAOSTAT NATIONAL series is the
              `regional_aggregate_time_series` obs_shape. Per dag.yaml
              `outputs.TWSO.observability`, the ONLY scientifically valid
              metric_families for that obs_shape are:
                  [trend_match, magnitude_accuracy]
              Raw inter-annual NSE/r/KGE belong to `temporal_pattern_match`,
              which is NOT valid here: the national aggregate is spatially
              smoothed, partly irrigated, and rides a multi-decade technology
              trend a fixed-parameter weather-driven model cannot reproduce, so
              raw NSE/KGE are structurally very negative and raw r is low
              REGARDLESS of model quality. The dag-driven pre-retry gate REJECTS
              raw-family metrics on this obs_shape as REJECT_WRONG_METRIC.

              This tool therefore reports the VALID families as the headline:
                magnitude_accuracy : pbias, decadal_mean_pbias, mean_abs_pct_err
                trend_match        : detrended (linear-residual) r,
                                     first-difference r, trend-slope ratio
              and relegates raw NSE/r/KGE to an `invalid_for_obs_shape` block,
              flagged so no caller treats them as a skill verdict.

Inputs (CLI):
  SIM_CSV   path to a CSV with columns: year, sim_tha  (yield in t/ha)
  CROP      FAOSTAT crop name (e.g. "maize", "wheat")
  COUNTRY   FAOSTAT area name (e.g. "United States of America")
  OUT_JSON  output JSON path
  [UNITS]   obs units, default t/ha

Outputs:
  JSON with obs_shape, comparison_mode, valid metric families (headline),
  the paired series, and an invalid_for_obs_shape diagnostic block.

Exit codes: 0 success, 1 input error, 2 processing error
"""
import sys
import os
import json
import logging
import csv

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

sys.path.insert(0, "KISSPATH_KI_TOOLS_COMMON")

# This obs_shape contract MUST match dag.yaml outputs.TWSO.observability.
OBS_SHAPE = "regional_aggregate_time_series"
COMPARISON_MODE = "aggregate_trend_comparison"
VALID_METRIC_FAMILIES = ["trend_match", "magnitude_accuracy"]


def _read_sim(path):
    years, sim = [], []
    with open(path) as fh:
        rdr = csv.DictReader(fh)
        cols = {c.lower(): c for c in rdr.fieldnames}
        ycol = cols.get("year")
        scol = cols.get("sim_tha") or cols.get("wofost_tha") or cols.get("sim")
        if not ycol or not scol:
            raise ValueError(f"SIM_CSV must have year + sim_tha columns; got {rdr.fieldnames}")
        for row in rdr:
            years.append(int(float(row[ycol])))
            sim.append(float(row[scol]))
    return years, sim


def _linfit(x, y):
    import numpy as np
    return np.polyfit(np.asarray(x, float), np.asarray(y, float), 1)


def process(sim_csv, crop, country, out_json, units):
    import numpy as np
    from ki_tools_common.crop_obs import get_faostat_yield_series

    sim_years, sim_vals = _read_sim(sim_csv)
    sim_map = dict(zip(sim_years, sim_vals))

    obs_map = get_faostat_yield_series(crop=crop, country=country, units=units)

    years = sorted(set(sim_map) & set(obs_map))
    if len(years) < 3:
        raise ValueError(f"Only {len(years)} overlapping years between sim and FAOSTAT — need >=3")

    sim = np.array([sim_map[y] for y in years], float)
    obs = np.array([obs_map[y] for y in years], float)

    # ---- magnitude_accuracy family (VALID) ----
    pbias = 100.0 * (sim.sum() - obs.sum()) / obs.sum()
    mean_abs_pct_err = float(np.mean(np.abs(sim - obs) / obs) * 100.0)
    # decadal-mean pbias: compare decade-averaged means (removes inter-annual noise)
    decades = {}
    for y, s, o in zip(years, sim, obs):
        decades.setdefault((y // 10) * 10, []).append((s, o))
    dec_s = np.array([np.mean([p[0] for p in v]) for v in decades.values()])
    dec_o = np.array([np.mean([p[1] for p in v]) for v in decades.values()])
    decadal_mean_pbias = float(100.0 * (dec_s.sum() - dec_o.sum()) / dec_o.sum())

    # ---- trend_match family (VALID) ----
    # linear-residual (detrended) r — weather-driven anomaly skill
    sd = sim - np.polyval(_linfit(years, sim), years)
    od = obs - np.polyval(_linfit(years, obs), years)
    r_detrended = float(np.corrcoef(sd, od)[0, 1]) if sd.std() > 0 and od.std() > 0 else float("nan")
    # first-difference r — year-on-year change agreement
    ds = np.diff(sim); do = np.diff(obs)
    r_firstdiff = float(np.corrcoef(ds, do)[0, 1]) if ds.std() > 0 and do.std() > 0 else float("nan")
    # trend-slope ratio (sim trend / obs trend); ~0 expected for fixed-param sim vs tech-trended obs
    slope_sim = float(_linfit(years, sim)[0])
    slope_obs = float(_linfit(years, obs)[0])
    trend_slope_ratio = float(slope_sim / slope_obs) if slope_obs != 0 else float("nan")

    # ---- raw temporal-pattern metrics: INVALID for this obs_shape, kept for diagnosis only ----
    raw_nse = float(1 - np.sum((sim - obs) ** 2) / np.sum((obs - obs.mean()) ** 2))
    raw_r = float(np.corrcoef(sim, obs)[0, 1])
    a = sim.std() / obs.std(); b = sim.mean() / obs.mean()
    raw_kge = float(1 - np.sqrt((raw_r - 1) ** 2 + (a - 1) ** 2 + (b - 1) ** 2))

    result = {
        "obs_shape": OBS_SHAPE,
        "comparison_mode": COMPARISON_MODE,
        "valid_metric_families": VALID_METRIC_FAMILIES,
        "crop": crop,
        "country": country,
        "units": units,
        "n_years": len(years),
        "period": [years[0], years[-1]],
        # HEADLINE — only valid-family metrics
        "magnitude_accuracy": {
            "pbias": round(pbias, 2),
            "decadal_mean_pbias": round(decadal_mean_pbias, 2),
            "mean_abs_pct_err": round(mean_abs_pct_err, 2),
            "sim_mean_tha": round(float(sim.mean()), 3),
            "obs_mean_tha": round(float(obs.mean()), 3),
        },
        "trend_match": {
            "r_detrended": round(r_detrended, 3),
            "r_firstdiff": round(r_firstdiff, 3),
            "trend_slope_ratio": round(trend_slope_ratio, 3),
            "slope_sim_tha_per_yr": round(slope_sim, 4),
            "slope_obs_tha_per_yr": round(slope_obs, 4),
        },
        # NOT a skill verdict for this obs_shape — gate REJECTS these as the headline.
        "invalid_for_obs_shape": {
            "_warning": ("raw NSE/r/KGE are temporal_pattern_match metrics; INVALID for "
                         "regional_aggregate_time_series. Do NOT report as the comparison verdict "
                         "(gate -> REJECT_WRONG_METRIC). Shown for diagnosis only."),
            "raw_nse": round(raw_nse, 3),
            "raw_r": round(raw_r, 3),
            "raw_kge": round(raw_kge, 3),
        },
        "years": years,
        "sim_tha": [round(float(x), 3) for x in sim],
        "obs_tha": [round(float(x), 3) for x in obs],
    }

    with open(out_json, "w") as fh:
        json.dump(result, fh, indent=2)
    logger.info(f"obs_shape={OBS_SHAPE}; valid families={VALID_METRIC_FAMILIES}")
    logger.info(f"magnitude_accuracy: pbias={pbias:+.2f}%  decadal_pbias={decadal_mean_pbias:+.2f}%")
    logger.info(f"trend_match: r_detrended={r_detrended:.3f}  r_firstdiff={r_firstdiff:.3f}")
    logger.info(f"(invalid-for-shape raw NSE={raw_nse:.2f} r={raw_r:.2f} — NOT the verdict)")
    return result


if __name__ == "__main__":
    if len(sys.argv) < 5:
        logger.error("Usage: validate_against_faostat.py SIM_CSV CROP COUNTRY OUT_JSON [UNITS]")
        sys.exit(1)
    sim_csv, crop, country, out_json = sys.argv[1:5]
    units = sys.argv[5] if len(sys.argv) >= 6 else "t/ha"
    if not os.path.exists(sim_csv):
        logger.error(f"SIM_CSV not found: {sim_csv}")
        sys.exit(1)
    try:
        res = process(sim_csv, crop, country, out_json, units)
    except Exception as e:
        logger.error(f"Validation failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(2)
    print(json.dumps(res, indent=2))
    sys.exit(0)
