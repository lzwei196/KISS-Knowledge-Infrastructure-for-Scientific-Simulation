"""
delta_perturbation.py -- Mode B: observation-anchored climate-signal
perturbation (Framework §4.2). Pure numpy/xarray math over already-loaded
arrays -- safe to import alongside ki_tools_common.

Framework §4.2 formulas:
    additive:        X*_f = X_ref + (X_GCM,f - X_GCM,h)
    multiplicative:   X*_f = X_ref * (X_GCM,f / X_GCM,h)
    quantile-delta:   per-quantile version of either, used when changes in
                      variability/extremes matter (not just the mean shift).

Framework §4.2 variable -> transform table (VARIABLE_TRANSFORM below):
    tas: additive_quantile | ps: additive | rlds: additive_or_quantile
    pr: multiplicative_quantile | sfcWind: multiplicative_quantile_lower_bound
    rsds: quantile_with_physical_bounds | huss: quantile_then_saturation_check
    hurs: bounded_or_thermodynamic | prsn: derive_from_pr_and_snow_fraction
"""

from __future__ import annotations

import numpy as np
import xarray as xr

VARIABLE_TRANSFORM = {
    "tas": "additive_quantile",
    "tasmax": "additive_quantile",
    "tasmin": "additive_quantile",
    "ps": "additive",
    "rlds": "additive_or_quantile",
    "pr": "multiplicative_quantile",
    "sfcWind": "multiplicative_quantile_lower_bound",
    "rsds": "quantile_with_physical_bounds",
    "huss": "quantile_then_saturation_check",
    "hurs": "bounded_or_thermodynamic",
    "prsn": "derive_from_pr_and_snow_fraction",
}


def additive_delta(x_ref: xr.DataArray, x_gcm_future: xr.DataArray, x_gcm_hist: xr.DataArray) -> xr.DataArray:
    """Framework §4.2: X*_f = X_ref + (X_GCM,f - X_GCM,h). For approximately additive variables
    (temperature, pressure, longwave radiation).

    x_ref must be a daily climatology or a full reference series; x_gcm_future/x_gcm_hist are
    the GCM's future and historical values for the SAME calendar alignment (e.g. both daily
    climatologies, or both full time series of matching length) as x_ref.
    """
    out = x_ref + (x_gcm_future - x_gcm_hist)
    out.attrs = dict(x_ref.attrs)
    out.attrs["perturbation_method"] = "additive_delta"
    return out


def multiplicative_delta(
    x_ref: xr.DataArray, x_gcm_future: xr.DataArray, x_gcm_hist: xr.DataArray,
    lower_bound: float | None = 0.0, hist_floor: float = 1e-8,
) -> xr.DataArray:
    """Framework §4.2: X*_f = X_ref * (X_GCM,f / X_GCM,h). For non-negative/multiplicative
    variables (precipitation, wind speed).

    Args:
        lower_bound: clip the result to this minimum (e.g. 0.0 for precip/wind -- Framework
            §4.2 'Wind speed: Multiplicative quantile delta with lower bound').
        hist_floor: x_gcm_hist values below this are treated as the floor to avoid
            division blow-up on near-zero historical values (e.g. dry days).
    """
    ratio = x_gcm_future / xr.where(np.abs(x_gcm_hist) < hist_floor, hist_floor, x_gcm_hist)
    out = x_ref * ratio
    if lower_bound is not None:
        out = out.clip(min=lower_bound)
    out.attrs = dict(x_ref.attrs)
    out.attrs["perturbation_method"] = "multiplicative_delta"
    return out


def apply_physical_bounds(x: xr.DataArray, lo: float | None = None, hi: float | None = None) -> xr.DataArray:
    """Framework §4.2 'Shortwave radiation: Quantile delta with physical bounds'."""
    return x.clip(min=lo, max=hi)


def quantile_delta_mapping(
    x_ref: np.ndarray,
    x_gcm_hist: np.ndarray,
    x_gcm_future: np.ndarray,
    kind: str = "additive",
    n_quantiles: int = 100,
    lower_bound: float | None = None,
) -> np.ndarray:
    """Framework §4.2 quantile-delta-mapping (QDM), Cannon-style: for each point in x_ref,
    find its quantile rank within x_ref's own distribution, look up the GCM historical->future
    change AT THAT SAME QUANTILE (from x_gcm_hist/x_gcm_future's distributions), and apply that
    quantile-specific change to x_ref -- rather than one single mean-based factor for every value.

    Args:
        x_ref, x_gcm_hist, x_gcm_future: 1-D arrays (e.g. a full daily time series, or a
            climatological sample for a given day-of-year window). x_gcm_hist and
            x_gcm_future represent the SAME GCM's historical and future distributions for
            the quantity being perturbed.
        kind: 'additive' (change = quantile(future) - quantile(hist), added to x_ref) or
            'multiplicative' (change = quantile(future) / quantile(hist), multiplied into x_ref).
        n_quantiles: number of quantile bins used to build the empirical change function.
        lower_bound: optional clip after transformation (e.g. 0.0 for precipitation/wind).

    Returns:
        Perturbed version of x_ref, same shape.

    Example::

        >>> import numpy as np
        >>> rng = np.random.default_rng(0)
        >>> x_ref = rng.normal(10, 2, 1000)
        >>> x_hist = rng.normal(10, 2, 1000)
        >>> x_fut = rng.normal(13, 2, 1000)  # +3 shift, roughly uniform across quantiles
        >>> out = quantile_delta_mapping(x_ref, x_hist, x_fut, kind="additive")
        >>> abs((out.mean() - x_ref.mean()) - 3.0) < 0.5
        True
    """
    x_ref = np.asarray(x_ref, dtype=float)
    x_gcm_hist = np.asarray(x_gcm_hist, dtype=float)
    x_gcm_future = np.asarray(x_gcm_future, dtype=float)
    if kind not in ("additive", "multiplicative"):
        raise ValueError(f"kind must be 'additive' or 'multiplicative', got {kind!r}")

    probs = np.linspace(0.0, 1.0, n_quantiles + 1)
    q_hist = np.quantile(x_gcm_hist, probs)
    q_fut = np.quantile(x_gcm_future, probs)
    q_ref = np.quantile(x_ref, probs)

    # rank of each x_ref value within x_ref's own empirical distribution
    ref_ranks = np.clip(np.searchsorted(np.sort(x_ref), x_ref, side="right") / x_ref.size, 0.0, 1.0)
    # map that rank onto the GCM hist/fut quantile grid to get the local change
    change_at_hist_q = (q_fut - q_hist) if kind == "additive" else np.divide(
        q_fut, np.where(np.abs(q_hist) < 1e-8, 1e-8, q_hist)
    )
    local_change = np.interp(ref_ranks, probs, change_at_hist_q)

    if kind == "additive":
        out = x_ref + local_change
    else:
        out = x_ref * local_change

    if lower_bound is not None:
        out = np.clip(out, lower_bound, None)
    return out


def derive_snowfall_from_fraction(pr_hicpc: xr.DataArray, pr_isimip: xr.DataArray, prsn_isimip: xr.DataArray) -> tuple[xr.DataArray, xr.DataArray]:
    """Framework §5.2 'Precipitation-phase coupling': transfer the ISIMIP snow FRACTION onto
    HiCPC's total precipitation, rather than combining HiCPC pr with ISIMIP prsn amounts
    directly (which would double-count/mismatch two independently bias-corrected totals).

        f_snow = clip(prsn_ISIMIP / pr_ISIMIP, 0, 1)
        prsn_hybrid = pr_HiCPC * f_snow
        pr_rain = pr_HiCPC - prsn_hybrid

    Returns (prsn_hybrid, pr_rain) -- conservation of total precipitation is exact by
    construction (pr_rain + prsn_hybrid == pr_HiCPC).
    """
    f_snow = (prsn_isimip / xr.where(pr_isimip.values == 0, 1e-12, pr_isimip)).clip(min=0.0, max=1.0)
    prsn_hybrid = pr_hicpc * f_snow
    pr_rain = pr_hicpc - prsn_hybrid
    prsn_hybrid.attrs["derived_from"] = "pr_HiCPC * clip(prsn_ISIMIP/pr_ISIMIP, 0, 1)"
    pr_rain.attrs["derived_from"] = "pr_HiCPC - prsn_hybrid"
    return prsn_hybrid, pr_rain
