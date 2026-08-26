#!/usr/bin/env python3
"""validate_yield_timeseries.py - build a TEMPORAL (sim,obs) yield sample so
Pearson r / NSE / KGE are DEFINED for DSSAT crop validation.

Single-year SPAM (ki_tools_common.crop_obs.get_observed_yield) returns ONE scalar
-> one (sim,obs) pair -> metrics.nse/pearson_r return NaN ('if o.size < 2: return
nan'), so the orchestrator's r<0.5 gate can never pass. This tool pairs a
multi-year DSSAT yield series against the multi-year GDHY gridded yield series at
the site (or the FAOSTAT national series), then computes all_metrics.

SIM SIDE — two supports, per dag.yaml outputs[HWAM].observability:
  --workdir DIR   ONE DSSAT point run's Summary.OUT (one HWAM per WYEAR)
                  -> obs_shape 'point_time_series'
  --sim_csv PATH  an EXTERNALLY AGGREGATED year,sim_kgha series, e.g. the
                  area-weighted output of s9_output_parsing/aggregate_grid_to_pixel.py
                  over a gridded ensemble built by
                  s8_batch_execution/run_grid_ensemble.py
                  -> obs_shape 'spatial_time_series' (the dag row whose caveat
                  reads "Requires a gridded ensemble of DSSAT point runs over
                  multiple seasons")

DETRENDING — dag.yaml outputs[HWAM].observability.detrending_options =
["none", "first_difference", "linear_residual", "decadal_mean"]. A gridded
ACTUAL-yield obs (GDHY) carries a technology/management trend that a
fixed-cultivar, fixed-N simulation cannot reproduce by construction, so temporal
metrics must be read on the detrended series. The RAW pbias (magnitude_accuracy)
is NEVER detrended -- a detrended series has ~zero mean, which would make pbias
meaningless -- and the raw r/NSE/KGE are ALWAYS retained alongside. Every value
is explicitly labelled raw vs detrended; nothing is overwritten.

REQUIRES >= 2 paired years.
"""
import argparse, csv, json, math, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # tools/
from dssat_workdir_setup import parse_summary
sys.path.insert(0, 'KISSPATH_KI_TOOLS_COMMON')
from ki_tools_common.crop_obs import get_observed_yield_series, get_faostat_yield_series
from ki_tools_common.metrics import all_metrics

DETREND_OPTIONS = ["none", "first_difference", "linear_residual", "decadal_mean"]


def _slope(years, vals):
    """OLS slope of vals on years (kg/ha per year), or None if undefined."""
    n = len(years)
    if n < 2:
        return None
    mx = sum(years) / n
    my = sum(vals) / n
    sxx = sum((x - mx) ** 2 for x in years)
    if sxx == 0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(years, vals))
    return sxy / sxx


def detrend(years, vals, method):
    """Return (detrended_years, detrended_vals) for a dag detrending_option.

    none             : unchanged
    first_difference : y[t] - y[t-1]           (drops the first year)
    linear_residual  : y[t] - OLS(y ~ year)[t]
    decadal_mean     : y[t] - mean(y in y[t]'s decade)
    """
    if method == "none":
        return list(years), list(vals)

    if method == "first_difference":
        return (list(years[1:]),
                [vals[i] - vals[i - 1] for i in range(1, len(vals))])

    if method == "linear_residual":
        s = _slope(years, vals)
        if s is None:
            return list(years), list(vals)
        mx = sum(years) / len(years)
        my = sum(vals) / len(vals)
        return list(years), [v - (my + s * (y - mx)) for y, v in zip(years, vals)]

    if method == "decadal_mean":
        by_dec = {}
        for y, v in zip(years, vals):
            by_dec.setdefault(y // 10, []).append(v)
        means = {d: sum(v) / len(v) for d, v in by_dec.items()}
        return list(years), [v - means[y // 10] for y, v in zip(years, vals)]

    raise ValueError(f"unknown detrend method {method!r}")


def _read_sim_csv(path):
    """Read an externally aggregated year,sim_kgha series -> {year: kg/ha}.

    Accepts the column names emitted by aggregate_grid_to_pixel.py
    (year, sim_kgha) and the common aliases sim/hwam/hwam_kgha/yield_kgha.
    """
    sim = {}
    with open(path, newline='') as fh:
        rd = csv.DictReader(fh)
        cols = {c.strip().lower(): c for c in (rd.fieldnames or [])}
        if 'year' not in cols:
            raise ValueError(f"{path}: needs a 'year' column, got {rd.fieldnames}")
        val_col = None
        for cand in ('sim_kgha', 'sim', 'hwam_kgha', 'hwam', 'yield_kgha'):
            if cand in cols:
                val_col = cols[cand]
                break
        if val_col is None:
            raise ValueError(
                f"{path}: needs a sim_kgha (or sim/hwam/hwam_kgha/yield_kgha) "
                f"column, got {rd.fieldnames}")
        for row in rd:
            try:
                sim[int(row[cols['year']])] = float(row[val_col])
            except (TypeError, ValueError):
                continue
    return sim


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--workdir', default=None,
                    help='DSSAT workdir containing Summary.OUT (single point run)')
    ap.add_argument('--sim_csv', default=None,
                    help='Externally aggregated year,sim_kgha series (e.g. the '
                         'area-weighted pixel series from '
                         'aggregate_grid_to_pixel.py). Mutually exclusive with '
                         '--workdir.')
    ap.add_argument('--lat', type=float, required=True)
    ap.add_argument('--lon', type=float, required=True)
    ap.add_argument('--crop', default='maize')
    ap.add_argument('--obs', default='gdhy', choices=['gdhy', 'faostat'],
                    help="Observation source: 'gdhy' (Iizumi gridded 1981-2016) or "
                         "'faostat' (national annual yield series 1961-2024).")
    ap.add_argument('--country', default='China, mainland',
                    help="FAOSTAT Area label (only used when --obs faostat), e.g. "
                         "'China, mainland', 'United States of America', 'World'.")
    ap.add_argument('--obs_shape', default=None,
                    choices=['point_time_series', 'spatial_time_series'],
                    help='dag.yaml observability row to score under. Default: '
                         'spatial_time_series when the sim came from --sim_csv '
                         '(an aggregated gridded ensemble), point_time_series '
                         'for a single --workdir run. FAOSTAT always forces '
                         'regional_aggregate_time_series.')
    ap.add_argument('--detrend', default='none', choices=DETREND_OPTIONS,
                    help='dag.yaml outputs[HWAM].observability.detrending_options. '
                         'Applied to the TEMPORAL metrics only; pbias stays raw.')
    ap.add_argument('--label', default=None,
                    help='Tag written into the result and the series CSV, so '
                         'several scorings can be told apart in evidence.')
    ap.add_argument('--series_csv', default=None,
                    help='Write the aligned date,obs,sim series here (evidence).')
    ap.add_argument('--out', default=None)
    a = ap.parse_args()

    if bool(a.workdir) == bool(a.sim_csv):
        sys.stderr.write("ERROR: give exactly one of --workdir or --sim_csv\n")
        sys.exit(1)

    # ---- SIM side -------------------------------------------------------
    if a.sim_csv:
        try:
            sim_by_year = _read_sim_csv(a.sim_csv)
        except (OSError, ValueError) as e:
            sys.stderr.write(f"ERROR: {e}\n")
            sys.exit(1)
        sim_support = 'aggregated_gridded_ensemble'
        sim_source = a.sim_csv
    else:
        sim_by_year = {}
        for r in parse_summary(a.workdir):
            wy = r.get('WYEAR'); hw = r.get('HWAM', r.get('HWAH'))
            try:
                wy = int(wy); hw = float(hw)
            except (TypeError, ValueError):
                continue
            if hw > 0:
                sim_by_year.setdefault(wy, []).append(hw)
        sim_by_year = {y: sum(v) / len(v) for y, v in sim_by_year.items()}
        sim_support = 'single_point_run'
        sim_source = a.workdir

    # ---- OBS side -------------------------------------------------------
    if a.obs == 'faostat':
        # FAOSTAT stores yield in kg/ha (element 5412); request kg/ha so it is
        # directly comparable to DSSAT HWAM (kg/ha).
        obs = get_faostat_yield_series(a.crop, country=a.country,
                                       years=list(sim_by_year), units='kg/ha')
        obs_source = f'FAOSTAT:{a.country}'
    else:
        obs = get_observed_yield_series(a.lat, a.lon, a.crop, years=list(sim_by_year))
        obs_source = 'GDHY_v1.2_v1.3'
    common = sorted(set(sim_by_year) & set(obs))
    sim = [sim_by_year[y] for y in common]
    obsv = [obs[y] for y in common]

    # ---- obs_shape contract (see dag.yaml outputs.HWAM.observability) --------
    # point_time_series      : ONE DSSAT point run vs a co-located gridded/point
    #                          obs; families [temporal_pattern_match,
    #                          magnitude_accuracy, ranking_quality].
    # spatial_time_series    : an area-weighted GRIDDED ENSEMBLE vs the same
    #                          gridded obs pixel — the row whose caveat reads
    #                          "Requires a gridded ensemble of DSSAT point runs
    #                          over multiple seasons"; families
    #                          [spatial_pattern_match, magnitude_accuracy].
    #                          Scoring a single point run under this row is a
    #                          run-SUPPORT mismatch, which is why the default is
    #                          driven by which sim flag was used.
    # regional_aggregate_ts  : FAOSTAT national aggregate carrying a smooth
    #                          technology/fertilizer trend a weather-only point
    #                          process model cannot (and should not) match ->
    #                          families [magnitude_accuracy, trend_match] ONLY.
    #                          Raw NSE/KGE/r are OUTSIDE the valid family, so the
    #                          dag-driven gate REJECTs them (REJECT_WRONG_METRIC)
    #                          and we must NOT report them as model quality.
    if a.obs == 'faostat':
        obs_shape = 'regional_aggregate_time_series'
    elif a.obs_shape:
        obs_shape = a.obs_shape
    else:
        obs_shape = ('spatial_time_series' if a.sim_csv else 'point_time_series')

    if obs_shape == 'spatial_time_series' and sim_support != 'aggregated_gridded_ensemble':
        # Loud, but not fatal: the caller may have aggregated elsewhere.
        sys.stderr.write(
            "WARNING: --obs_shape spatial_time_series with a single --workdir "
            "run. That dag row REQUIRES a gridded ensemble of point runs; the "
            "metrics below describe a support mismatch, not the model.\n")

    if len(common) < 2:
        met = {'nse': None, 'kge': None, 'r': None, 'pbias': None}
        valid_metric_families = []
        detrend_block = None
    else:
        m_raw = all_metrics(obsv, sim)
        sim_slope = _slope(common, sim)
        obs_slope = _slope(common, obsv)

        # Detrended temporal metrics (dag detrending_options). PBIAS is NEVER
        # taken from the detrended series: detrending centres it on ~0, so a
        # percent bias against a ~0 mean is not interpretable.
        dt_years, dt_obs = detrend(common, obsv, a.detrend)
        _,        dt_sim = detrend(common, sim,  a.detrend)
        # Detrending SPENDS degrees of freedom: linear_residual fits 2
        # parameters, decadal_mean 1 per decade, first_difference drops a year.
        # On a short series the residuals are then near-degenerate -- e.g. 3
        # years through linear_residual leaves 1 DOF, which forces |r| = 1 and
        # can make KGE's variance ratio NaN. Say so rather than letting a
        # degenerate r be read as skill.
        DETREND_DOF = {'none': 0, 'first_difference': 0,
                       'linear_residual': 2, 'decadal_mean': 1}
        eff_n = len(dt_years) - DETREND_DOF.get(a.detrend, 0)
        degenerate = a.detrend != 'none' and eff_n < 3
        if a.detrend != 'none' and len(dt_years) >= 2:
            m_dt = all_metrics(dt_obs, dt_sim)
            detrended = {'nse': m_dt['NSE'], 'kge': m_dt['KGE'], 'r': m_dt['r'],
                         'n_pairs': len(dt_years),
                         'effective_dof': eff_n,
                         'degenerate_small_sample': degenerate}
            if degenerate:
                sys.stderr.write(
                    f"WARNING: --detrend {a.detrend} on {len(dt_years)} paired "
                    f"year(s) leaves only {eff_n} effective degree(s) of "
                    f"freedom; the detrended r/NSE/KGE below are DEGENERATE "
                    f"(|r| is forced toward 1) and must not be read as skill. "
                    f"Use a longer series.\n")
        else:
            detrended = None

        if obs_shape == 'regional_aggregate_time_series':
            # magnitude_accuracy: PBIAS on the raw aggregate is valid (mean-bias).
            # trend_match: compare linear slopes.
            slope_ratio = (sim_slope / obs_slope
                           if (sim_slope is not None and obs_slope) else None)
            met = {
                # gate-valid (magnitude_accuracy) — ALWAYS the RAW series:
                'pbias': m_raw['PBIAS'],
                # gate-valid (trend_match):
                'sim_slope_kgha_yr': sim_slope,
                'obs_slope_kgha_yr': obs_slope,
                'slope_ratio': slope_ratio,
                'trend_sign_agree': (sim_slope is not None and obs_slope is not None
                                     and (sim_slope > 0) == (obs_slope > 0)),
                # INVALID for this obs_shape -> null so the gate does not treat a
                # structural scale mismatch as a model-quality failure:
                'nse': None, 'kge': None, 'r': None,
                # raw values retained for the record under a clearly-flagged key:
                '_raw_invalid_nse': m_raw['NSE'], '_raw_invalid_kge': m_raw['KGE'],
                '_raw_invalid_r': m_raw['r'],
            }
            valid_metric_families = ['magnitude_accuracy', 'trend_match']
        else:
            # point_time_series / spatial_time_series.
            # Headline r/NSE/KGE come from the DETRENDED series when a
            # detrending option was requested (the obs carries a technology
            # trend the fixed-cultivar sim cannot reproduce); the RAW values are
            # kept beside them, never overwritten. pbias is always raw.
            if detrended:
                met = {'nse': detrended['nse'], 'kge': detrended['kge'],
                       'r': detrended['r'], 'pbias': m_raw['PBIAS']}
            else:
                met = {'nse': m_raw['NSE'], 'kge': m_raw['KGE'],
                       'r': m_raw['r'], 'pbias': m_raw['PBIAS']}
            met.update({
                'raw_nse': m_raw['NSE'], 'raw_kge': m_raw['KGE'],
                'raw_r': m_raw['r'], 'raw_pbias': m_raw['PBIAS'],
                'sim_slope_kgha_yr': sim_slope,
                'obs_slope_kgha_yr': obs_slope,
            })
            valid_metric_families = (
                ['spatial_pattern_match', 'magnitude_accuracy']
                if obs_shape == 'spatial_time_series'
                else ['temporal_pattern_match', 'magnitude_accuracy',
                      'ranking_quality'])

        detrend_block = {
            'method': a.detrend,
            'options_from_dag': DETREND_OPTIONS,
            'applies_to': ['nse', 'kge', 'r'],
            'never_detrended': ['pbias'],
            'detrended_metrics': detrended,
            'headline_temporal_metrics_are': (
                'detrended' if detrended else 'raw'),
            'note': ('pbias is reported on the RAW series (magnitude_accuracy); '
                     'detrending centres the series on ~0 so a percent bias '
                     'against it is not interpretable.'),
        }

    result = {'metrics': met, 'obs_shape': obs_shape,
              'valid_metric_families': valid_metric_families,
              'detrending': detrend_block,
              'sim_support': sim_support, 'sim_source': sim_source,
              'n_pairs': len(common), 'years': common,
              'sim_kgha': {str(y): round(sim_by_year[y], 1) for y in common},
              'obs_kgha': {str(y): obs[y] for y in common},
              'obs_source': obs_source, 'crop': a.crop,
              'label': a.label}

    # ---- evidence: the aligned date,obs,sim series ----------------------
    if a.series_csv:
        os.makedirs(os.path.dirname(os.path.abspath(a.series_csv)) or '.',
                    exist_ok=True)
        with open(a.series_csv, 'w', newline='') as fh:
            w = csv.writer(fh)
            w.writerow(['date', 'obs', 'sim'])
            for y in common:
                # Annual yield: stamp the harvest-year end so the series is a
                # dated time series, matching the platform's dates= convention.
                w.writerow([f"{y}-12-31", obs[y], round(sim_by_year[y], 1)])
        result['series_csv'] = a.series_csv

    default_out = (os.path.join(a.workdir, 'validation_metrics.json')
                   if a.workdir else
                   os.path.join(os.path.dirname(os.path.abspath(a.sim_csv)),
                                'validation_metrics.json'))
    outp = a.out or default_out
    os.makedirs(os.path.dirname(os.path.abspath(outp)) or '.', exist_ok=True)
    with open(outp, 'w') as fh:
        json.dump(result, fh, indent=2)
    print(json.dumps(result, indent=2))
    if len(common) < 2:
        sys.stderr.write('WARNING: <2 paired years; configure start_year..end_year to span >=2 years for a defined r.\n')
        sys.exit(2)


if __name__ == '__main__':
    main()
