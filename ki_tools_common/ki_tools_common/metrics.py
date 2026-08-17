"""
metrics.py — Performance metrics for hydrological and ecological model evaluation.

Consolidates metric calculations duplicated across 42 ki/tools/ scripts.

All functions:
    - Are PURE (no side effects, no file I/O).
    - Handle NaN gracefully — paired NaN values are excluded before computation.
    - Accept 1-D numpy arrays (or array-like) for *obs* and *sim*.
    - Return ``float('nan')`` when there are insufficient valid data points.

Examples::

    >>> from ki_tools_common.metrics import nse, kge, all_metrics
    >>> import numpy as np
    >>> obs = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    >>> sim = np.array([1.1, 2.2, 2.9, 4.1, 4.8])
    >>> round(nse(obs, sim), 3)
    0.988
    >>> round(kge(obs, sim), 3)
    0.974
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple, Union

import numpy as np

Numeric1D = Union[np.ndarray, list, tuple]


def _prepare_paired_with_dates(obs, sim, dates=None):
    """Single source of the flatten -> truncate -> finite-pair mask, extended to carry a parallel
    date vector through the SAME positional mask.

    Returns (o, s, d): two 1-D float64 arrays of finite mutually-valid pairs, plus a 1-D object
    array of dates aligned to them (or None when no usable dates were supplied/derived).

    It NEVER pandas-index-aligns: dates are truncated and masked POSITIONALLY, exactly like the
    values, so the returned (o, s, d) is provably the same triple the metrics are computed from.
    This is the foundation of code-forced evidence capture — the dumped series must equal the
    scored series. Behaviour of the (o, s) it returns is byte-identical to the historical
    _prepare_paired (locked by test_metrics_golden.py).
    """
    import warnings as _warnings

    if dates is None:
        # preserve the historical dump behaviour: take a pandas Series index when present
        try:
            import pandas as _pd
            if isinstance(obs, _pd.Series):
                dates = list(obs.index)
            elif isinstance(sim, _pd.Series):
                dates = list(sim.index)
        except Exception:
            dates = None

    o = np.asarray(obs, dtype=np.float64).ravel()
    s = np.asarray(sim, dtype=np.float64).ravel()
    if o.size != s.size:
        _warnings.warn(
            f"obs ({o.size}) and sim ({s.size}) have different lengths. "
            f"Truncating to {min(o.size, s.size)}. This may indicate a "
            f"date alignment issue.",
            stacklevel=3,
        )
    min_len = min(o.size, s.size)
    o, s = o[:min_len], s[:min_len]

    d = None
    if dates is not None:
        d = np.asarray(list(dates), dtype=object).ravel()
        d = d[:min_len] if d.size >= min_len else None

    mask = np.isfinite(o) & np.isfinite(s)
    if d is not None:
        d = d[mask]
    return o[mask], s[mask], d


def _prepare_paired(
    obs: Numeric1D,
    sim: Numeric1D,
) -> Tuple[np.ndarray, np.ndarray]:
    """Flatten and remove paired NaN/Inf entries.

    Returns two 1-D float64 arrays of equal length containing only finite,
    mutually-valid pairs. Thin wrapper over _prepare_paired_with_dates so the mask/truncation rule
    has exactly ONE definition; the returned (o, s) is byte-identical to the historical impl.
    """
    o, s, _ = _prepare_paired_with_dates(obs, sim)
    return o, s


# ======================================================================
# Individual metrics
# ======================================================================

def nse(obs: Numeric1D, sim: Numeric1D) -> float:
    """Nash-Sutcliffe Efficiency (NSE).

    .. math::

        NSE = 1 - \\frac{\\sum (O_i - S_i)^2}{\\sum (O_i - \\bar{O})^2}

    Range: (-inf, 1.0]. Perfect score = 1.0. NSE < 0 means the model is
    worse than using the observed mean as a predictor.

    Args:
        obs: Observed values (1-D).
        sim: Simulated values (1-D).

    Returns:
        NSE value, or ``nan`` if fewer than 2 valid pairs.

    Example::

        >>> nse([1, 2, 3], [1, 2, 3])
        1.0
    """
    o, s = _prepare_paired(obs, sim)
    if o.size < 2:
        return float("nan")
    denominator = np.sum((o - np.mean(o)) ** 2)
    if denominator == 0.0:
        return float("nan")
    return float(1.0 - np.sum((o - s) ** 2) / denominator)


def kge(obs: Numeric1D, sim: Numeric1D) -> float:
    """Kling-Gupta Efficiency (KGE, 2009 formulation).

    .. math::

        KGE = 1 - \\sqrt{(r - 1)^2 + (\\alpha - 1)^2 + (\\beta - 1)^2}

    where *r* = Pearson correlation, *alpha* = std(sim)/std(obs),
    *beta* = mean(sim)/mean(obs).

    Range: (-inf, 1.0]. Perfect score = 1.0.

    Args:
        obs: Observed values (1-D).
        sim: Simulated values (1-D).

    Returns:
        KGE value, or ``nan`` if fewer than 2 valid pairs.

    Example::

        >>> round(kge([1, 2, 3, 4, 5], [1.1, 2.2, 2.9, 4.1, 4.8]), 3)
        0.974
    """
    o, s = _prepare_paired(obs, sim)
    if o.size < 2:
        return float("nan")

    o_mean = np.mean(o)
    s_mean = np.mean(s)
    o_std = np.std(o, ddof=0)
    s_std = np.std(s, ddof=0)

    if o_mean == 0.0 or o_std == 0.0:
        return float("nan")

    r = float(np.corrcoef(o, s)[0, 1])
    alpha = s_std / o_std
    beta = s_mean / o_mean

    ed = np.sqrt((r - 1.0) ** 2 + (alpha - 1.0) ** 2 + (beta - 1.0) ** 2)
    return float(1.0 - ed)


def pbias(obs: Numeric1D, sim: Numeric1D) -> float:
    """Percent bias (PBIAS).

    .. math::

        PBIAS = 100 \\times \\frac{\\sum (S_i - O_i)}{\\sum O_i}

    Positive PBIAS indicates overestimation; negative indicates underestimation.

    Args:
        obs: Observed values (1-D).
        sim: Simulated values (1-D).

    Returns:
        PBIAS in percent, or ``nan`` if sum of observations is zero.

    Example::

        >>> pbias([100, 200, 300], [110, 190, 310])
        1.666...
    """
    o, s = _prepare_paired(obs, sim)
    if o.size == 0:
        return float("nan")
    sum_obs = np.sum(o)
    if sum_obs == 0.0:
        return float("nan")
    return float(100.0 * np.sum(s - o) / sum_obs)


def rmse(obs: Numeric1D, sim: Numeric1D) -> float:
    """Root Mean Square Error (RMSE).

    .. math::

        RMSE = \\sqrt{\\frac{1}{n} \\sum (O_i - S_i)^2}

    Args:
        obs: Observed values (1-D).
        sim: Simulated values (1-D).

    Returns:
        RMSE value (same units as input), or ``nan`` if no valid pairs.

    Example::

        >>> rmse([1, 2, 3], [1, 2, 3])
        0.0
    """
    o, s = _prepare_paired(obs, sim)
    if o.size == 0:
        return float("nan")
    return float(np.sqrt(np.mean((o - s) ** 2)))


def pearson_r(obs: Numeric1D, sim: Numeric1D) -> float:
    """Pearson correlation coefficient.

    Args:
        obs: Observed values (1-D).
        sim: Simulated values (1-D).

    Returns:
        Pearson *r* in [-1, 1], or ``nan`` if fewer than 2 valid pairs or
        if either series has zero variance.

    Example::

        >>> pearson_r([1, 2, 3, 4], [2, 4, 6, 8])
        1.0
    """
    o, s = _prepare_paired(obs, sim)
    if o.size < 2:
        return float("nan")
    if np.std(o) == 0.0 or np.std(s) == 0.0:
        return float("nan")
    return float(np.corrcoef(o, s)[0, 1])


# ======================================================================
# Aggregated metrics
# ======================================================================

def all_metrics(obs: Numeric1D, sim: Numeric1D, *,
                dates=None, label: str = "headline", meta=None) -> Dict[str, float]:
    """Compute all five standard metrics at once, and (when a dump dir is set) capture the exact
    scored series as evidence.

    Backward compatible: ``all_metrics(obs, sim)`` returns the IDENTICAL metric dict as before
    (locked byte-for-byte by test_metrics_golden.py). The keyword-only args drive evidence capture
    and never affect the returned numbers:
        dates — parallel date vector (else taken from a pandas Series index); dumped WITH the series.
        label — series label recorded in the manifest ('headline'/'cal'/'val'/'basin'/...).
        meta  — extra manifest fields (unit, obs_source, sim_source, period_role, dates_applicable).

    Args:
        obs: Observed values (1-D).
        sim: Simulated values (1-D).

    Returns:
        Dict with keys ``'NSE'``, ``'KGE'``, ``'PBIAS'``, ``'RMSE'``,
        ``'r'``, each mapping to the corresponding float value.

    Example::

        >>> m = all_metrics([1, 2, 3, 4, 5], [1.1, 2.0, 3.1, 3.9, 5.2])
        >>> sorted(m.keys())
        ['KGE', 'NSE', 'PBIAS', 'RMSE', 'r']
    """
    # Prepare the paired arrays ONCE, compute every metric from that SAME (o, s), and dump exactly
    # those arrays. This guarantees the saved series provably backs the returned numbers (the metric
    # is re-derivable from the evidence). The metric VALUES are byte-identical to computing each
    # metric on the raw inputs, because the metric functions are idempotent on already-clean data
    # (locked by test_metrics_golden.py).
    o, s, d = _prepare_paired_with_dates(obs, sim, dates)
    result = {
        "NSE": nse(o, s),
        "KGE": kge(o, s),
        "PBIAS": pbias(o, s),
        "RMSE": rmse(o, s),
        "r": pearson_r(o, s),
    }
    try:
        dump_scored_series(d, o, s, label=label, meta=meta, metric_values=result)
    except Exception:
        pass  # capture is best-effort; scoring must never break because of it
    return result


def _scorer_identity():
    """(path, full-64-char sha256) of THIS scorer file, captured IN the scoring process. Recorded in
    the manifest so the record layer can verify a run scored with the CANONICAL scorer, not a shadow
    or stale copy — the permanent shadow guard (codex)."""
    import hashlib as _h, os as _os
    p = _os.path.abspath(__file__)
    try:
        return p, _h.sha256(open(p, "rb").read()).hexdigest()
    except Exception:
        return p, None


def _resolve_series_dump_dir():
    """KDT_SERIES_DUMP_DIR if set (the launcher forces it there); else discover the run's series dir
    by walking UP from CWD for a run_context.json (best-effort, for a child that lost the env).
    Returns an absolute dir or None (no dir -> no dump, silently)."""
    import os as _os, json as _json
    d = _os.environ.get("KDT_SERIES_DUMP_DIR")
    if d:
        return d
    # direct run-context channel (codex): survives when KDT_SERIES_DUMP_DIR was stripped but
    # KDT_RUN_CONTEXT was not, without depending on CWD being under the run dir.
    rc_env = _os.environ.get("KDT_RUN_CONTEXT")
    if rc_env and _os.path.isfile(rc_env):
        try:
            sd = (_json.load(open(rc_env)) or {}).get("series_dir")
            if sd:
                return sd
        except Exception:
            pass
    try:
        cur = _os.getcwd()
        for _ in range(8):
            rc = _os.path.join(cur, "run_context.json")
            if _os.path.isfile(rc):
                sd = (_json.load(open(rc)) or {}).get("series_dir")
                if sd:
                    return sd
            parent = _os.path.dirname(cur)
            if parent == cur:
                break
            cur = parent
    except Exception:
        pass
    return None


def dump_scored_series(dates, obs, sim, *, label="headline", period_role="full",
                       headline_candidate=True, metric_values=None, meta=None) -> None:
    """Persist the EXACT scored (date, obs, sim) arrays + one manifest line, atomically. Best-effort
    and silent on failure — scoring must never break because capture hiccuped.

    `obs`/`sim`/`dates` are the ALREADY-PREPARED arrays from _prepare_paired_with_dates, so the file
    is provably the series the metric came from. The manifest records the scorer's own identity
    (path + full sha256) captured here, in the scoring process — that, not the orchestrator's
    re-import, is what the trust gate verifies.
    """
    import os as _os, csv as _csv, json as _json, hashlib as _hash
    d = _resolve_series_dump_dir()
    if not d:
        return
    try:
        _os.makedirs(d, exist_ok=True)
        o = list(obs); s = list(sim)
        n = min(len(o), len(s))
        if n == 0:
            return
        dates_present = dates is not None and len(dates) >= n
        dd = list(dates)[:n] if dates_present else list(range(n))

        # unique, labeled, sequenced filename — no wall clock (unavailable/unstable in some contexts)
        seq = 0
        while _os.path.exists(_os.path.join(d, f"{label}.{seq:04d}.csv")):
            seq += 1
        base = f"{label}.{seq:04d}.csv"
        fp = _os.path.join(d, base)
        tmp = fp + ".tmp"
        with open(tmp, "w", newline="") as f:
            w = _csv.writer(f)
            w.writerow(["date", "obs", "sim"])
            for i in range(n):
                w.writerow([dd[i], o[i], s[i]])
        _os.replace(tmp, fp)  # atomic publish

        sha = _hash.sha256(open(fp, "rb").read()).hexdigest()
        spath, ssha = _scorer_identity()
        m = meta or {}
        row = {
            "file": base, "sha256": sha, "label": label,
            "period_role": m.get("period_role", period_role),
            "headline_candidate": bool(m.get("headline_candidate", headline_candidate)),
            "metric_values": metric_values or {}, "n_finite": n,
            "dates_present": bool(dates_present),
            "dates_applicable": bool(m.get("dates_applicable", True)),
            "date_start": (str(dd[0]) if dates_present else None),
            "date_end": (str(dd[-1]) if dates_present else None),
            "unit": m.get("unit"), "obs_source": m.get("obs_source"),
            "sim_source": m.get("sim_source"),
            "scorer_path": spath, "scorer_sha256": ssha,
        }
        line = (_json.dumps(row, default=str) + "\n").encode("utf-8")
        # single O_APPEND write = an atomic manifest append even under concurrent scorers
        fd = _os.open(_os.path.join(d, "manifest.jsonl"),
                      _os.O_WRONLY | _os.O_CREAT | _os.O_APPEND, 0o644)
        try:
            _os.write(fd, line)
        finally:
            _os.close(fd)
    except Exception:
        pass


def _maybe_dump_series(obs, sim) -> None:
    """Back-compat shim for any external caller of the old private name. Prepares the paired+dated
    arrays and routes through dump_scored_series."""
    try:
        o, s, d = _prepare_paired_with_dates(obs, sim)
        dump_scored_series(d, o, s)
    except Exception:
        pass


def monthly_metrics(
    obs_daily: Numeric1D,
    sim_daily: Numeric1D,
    dates: Numeric1D,
) -> Dict[str, float]:
    """Aggregate daily data to monthly means, then compute all metrics.

    Args:
        obs_daily: Daily observed values.
        sim_daily: Daily simulated values.
        dates: Array of dates (``numpy.datetime64``, ``pandas.Timestamp``,
            or anything with a ``.astype('datetime64[M]')`` method).

    Returns:
        Dict of metrics computed on monthly aggregates, same keys as
        :func:`all_metrics`.

    Example::

        >>> import numpy as np
        >>> dates = np.arange('2000-01-01', '2000-04-01', dtype='datetime64[D]')
        >>> obs = np.random.rand(len(dates)) * 100
        >>> sim = obs * 1.05  # 5% overestimate
        >>> m = monthly_metrics(obs, sim, dates)
        >>> 'NSE' in m
        True
    """
    obs_arr = np.asarray(obs_daily, dtype=np.float64).ravel()
    sim_arr = np.asarray(sim_daily, dtype=np.float64).ravel()
    dates_arr = np.asarray(dates)

    min_len = min(obs_arr.size, sim_arr.size, dates_arr.size)
    obs_arr = obs_arr[:min_len]
    sim_arr = sim_arr[:min_len]
    dates_arr = dates_arr[:min_len]

    # Convert dates to year-month keys
    try:
        months = dates_arr.astype("datetime64[M]")
    except (TypeError, ValueError):
        # Fall back: try pandas
        import pandas as pd

        months = pd.to_datetime(dates_arr).to_period("M")

    unique_months = np.unique(months)
    obs_monthly = []
    sim_monthly = []

    for m in unique_months:
        mask = months == m
        o_vals = obs_arr[mask]
        s_vals = sim_arr[mask]
        # Only include months with at least some valid data
        o_valid = o_vals[np.isfinite(o_vals)]
        s_valid = s_vals[np.isfinite(s_vals)]
        if o_valid.size > 0 and s_valid.size > 0:
            obs_monthly.append(np.mean(o_valid))
            sim_monthly.append(np.mean(s_valid))

    if len(obs_monthly) < 2:
        return {k: float("nan") for k in ("NSE", "KGE", "PBIAS", "RMSE", "r")}

    return all_metrics(np.array(obs_monthly), np.array(sim_monthly))


def trend_metrics(obs: Numeric1D, sim: Numeric1D) -> Dict[str, float]:
    """Trend-match metrics for regional_aggregate_time_series obs (e.g. FAOSTAT
    national yield). Implements the dag-declared ``trend_match`` family with
    ``linear_residual`` detrending.

    Secular technology trends in national/regional statistical yields are NOT a
    crop-model forcing, so raw inter-annual Pearson r is NOT a valid skill
    metric for this obs shape (see dag observability caveat). Use r_detr /
    r_firstdiff / slope_ratio instead.

    Returns:
        Dict with keys ``r_detr`` (Pearson r of linearly-detrended series),
        ``r_firstdiff`` (Pearson r of year-over-year first differences),
        ``slope_ratio`` (sim trend slope / obs trend slope), ``slope_obs``,
        ``slope_sim`` and ``PBIAS``. nan-filled when fewer than 3 valid pairs.
    """
    o, s = _prepare_paired(obs, sim)
    out = {
        "r_detr": float("nan"), "r_firstdiff": float("nan"),
        "slope_ratio": float("nan"), "slope_obs": float("nan"),
        "slope_sim": float("nan"), "PBIAS": pbias(o, s),
    }
    if o.size < 3:
        return out
    t = np.arange(o.size, dtype=np.float64)
    co = np.polyfit(t, o, 1)
    cs = np.polyfit(t, s, 1)
    out["slope_obs"], out["slope_sim"] = float(co[0]), float(cs[0])
    out["slope_ratio"] = float(cs[0] / co[0]) if co[0] != 0.0 else float("nan")
    out["r_detr"] = pearson_r(o - np.polyval(co, t), s - np.polyval(cs, t))
    out["r_firstdiff"] = pearson_r(np.diff(o), np.diff(s))
    return out


# ======================================================================
# Spatial-field metrics (obs_shape: spatial_time_series / spatial_snapshot)
# ======================================================================
#
# Added 2026-07-20 (VIC vs GRUN gridded-runoff real case).  The KDT dag
# declares ``determining_metric: csi`` and ``metric_families:
# [spatial_pattern_match, magnitude_accuracy]`` for the ``spatial_time_series``
# obs shape, but no implementation existed anywhere in ki_tools_common — every
# gridded comparison was therefore either hand-rolled or silently downgraded to
# a lumped time-series metric.  These two functions are the canonical
# implementation; do NOT re-derive CSI in a model KI.


def csi(
    obs: Numeric1D,
    sim: Numeric1D,
    threshold: float,
) -> Dict[str, float]:
    """Categorical skill of a *continuous* field, thresholded into an event.

    A cell(-time) is an "event" when its value **exceeds** ``threshold``.
    This is the standard contingency-table decomposition used for spatial
    verification of hydrometeorological fields (Wilks, *Statistical Methods in
    the Atmospheric Sciences*, ch. 8):

        hits (a)         obs event  & sim event
        false alarms (b) no obs     & sim event
        misses (c)       obs event  & no sim

        CSI  = a / (a + b + c)      (critical success index / threat score)
        POD  = a / (a + c)          (probability of detection)
        FAR  = b / (a + b)          (false alarm ratio)
        BIAS = (a + b) / (a + c)    (frequency bias; 1.0 = unbiased frequency)

    CSI ignores correct negatives, which is what makes it meaningful for
    fields where non-events dominate (e.g. dry cells in a runoff field).

    Args:
        obs: observed field values (any shape; flattened).
        sim: simulated field values, same shape as *obs*.
        threshold: event threshold, in the units of the field.

    Returns:
        Dict with ``csi``, ``pod``, ``far``, ``bias``, ``hits``,
        ``false_alarms``, ``misses``, ``correct_negatives``, ``n``,
        ``threshold``.  Metrics are nan when their denominator is zero.
    """
    o, s = _prepare_paired(obs, sim)
    out = {
        "csi": float("nan"), "pod": float("nan"), "far": float("nan"),
        "bias": float("nan"), "hits": 0, "false_alarms": 0, "misses": 0,
        "correct_negatives": 0, "n": int(o.size),
        "threshold": float(threshold),
    }
    if o.size == 0:
        return out

    obs_ev = o > threshold
    sim_ev = s > threshold
    a = int(np.count_nonzero(obs_ev & sim_ev))
    b = int(np.count_nonzero(~obs_ev & sim_ev))
    c = int(np.count_nonzero(obs_ev & ~sim_ev))
    d = int(np.count_nonzero(~obs_ev & ~sim_ev))
    out.update(hits=a, false_alarms=b, misses=c, correct_negatives=d)

    if a + b + c > 0:
        out["csi"] = a / (a + b + c)
    if a + c > 0:
        out["pod"] = a / (a + c)
        out["bias"] = (a + b) / (a + c)
    if a + b > 0:
        out["far"] = b / (a + b)
    return out


def spatial_metrics(
    obs: Numeric1D,
    sim: Numeric1D,
    thresholds: Optional[Numeric1D] = None,
) -> Dict[str, object]:
    """Full ``spatial_field_comparison`` metric set for a gridded comparison.

    Combines the two dag-valid metric families for a ``spatial_time_series``
    obs shape:

      * ``spatial_pattern_match`` — Pearson r / NSE / RMSE over all valid
        cell(-time) pairs, i.e. does the model put runoff in the right places.
      * ``magnitude_accuracy``    — PBIAS over the same pairs.

    plus the dag's ``determining_metric``, CSI, evaluated at one or more
    thresholds.  When *thresholds* is None the **observed** field's 25th, 50th
    and 75th percentiles are used, and the median (``p50``) is reported as the
    headline ``csi``.  Deriving the threshold from the observation (rather than
    a fixed physical value) keeps CSI comparable across climates: it asks
    "does the model identify the same cells as above-normal-runoff cells as the
    observation does".

    Args:
        obs: observed field (cells x time, or any shape; flattened).
        sim: simulated field, same shape as *obs*.
        thresholds: optional explicit event thresholds, in field units.

    Returns:
        Dict with ``nse``, ``kge``, ``pbias``, ``r``, ``rmse`` (from
        :func:`all_metrics`), ``csi`` (headline), ``csi_threshold``,
        ``csi_by_threshold`` (list of per-threshold :func:`csi` dicts) and
        ``n_pairs``.
    """
    o, s = _prepare_paired(obs, sim)
    out: Dict[str, object] = dict(all_metrics(o, s))
    out["n_pairs"] = int(o.size)
    out["csi"] = float("nan")
    out["csi_threshold"] = float("nan")
    out["csi_by_threshold"] = []
    if o.size == 0:
        return out

    if thresholds is None:
        thr_list = [float(np.percentile(o, p)) for p in (25.0, 50.0, 75.0)]
        headline_idx = 1                      # the p50 / median threshold
    else:
        thr_list = [float(t) for t in np.asarray(thresholds).ravel()]
        headline_idx = 0

    table = [csi(o, s, t) for t in thr_list]
    out["csi_by_threshold"] = table
    if table:
        out["csi"] = table[headline_idx]["csi"]
        out["csi_threshold"] = table[headline_idx]["threshold"]
    return out
