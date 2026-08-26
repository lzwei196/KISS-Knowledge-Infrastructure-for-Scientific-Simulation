"""
warming_levels.py -- Mode C: global-warming-level (GWL) window detection
(Framework §4.3). Pure numpy/pandas math over an already-supplied global
annual-mean-temperature series -- safe to import alongside ki_tools_common.

IMPORTANT LOCAL DATA GAP (documented, not silently worked around): Framework
§4.3 requires anomalies relative to the 1850-1900 pre-industrial baseline,
computed from "the original global GCM" temperature trajectory. Neither
ISIMIP3b (2015-2100 only, locally) nor HiCPC (1979-2100, China only, and
regional besides) covers 1850-1900 or provides a GLOBAL mean. Framework §4.3
itself says: "HiCPC is regional and therefore cannot by itself determine
global warming levels. Each HiCPC GCM must be linked to the corresponding
original CMIP6 global temperature trajectory." This module implements the
algorithm; it does NOT include a local 1850-1900 global-tas source -- the
caller must supply one (e.g. a downloaded CMIP6 historical global-mean tas
series for the same GCM/member) or Mode C cannot be run on this server yet.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

DEFAULT_WARMING_LEVELS = [1.5, 2.0, 3.0, 4.0]
PREINDUSTRIAL_BASELINE = ("1850-01-01", "1900-12-31")


@dataclass
class WarmingLevelWindow:
    level: float
    reached: bool
    crossing_year: int | None
    window_start_year: int | None
    window_end_year: int | None
    smoothed_anomaly_at_crossing: float | None


def global_annual_mean_anomaly(
    annual_mean_tas: pd.Series, baseline_years: tuple[int, int] = (1850, 1900)
) -> pd.Series:
    """Framework §4.3 step 1-2: annual global mean temperature -> anomaly vs baseline_years.

    Args:
        annual_mean_tas: pandas Series indexed by year (int), one global
            annual mean temperature value per year, spanning at least
            baseline_years through the period of interest.
        baseline_years: (start_year, end_year) inclusive, default 1850-1900
            per Framework §4.3.
    """
    lo, hi = baseline_years
    baseline_slice = annual_mean_tas.loc[lo:hi]
    if baseline_slice.empty:
        raise ValueError(
            f"annual_mean_tas has no data in the baseline period {lo}-{hi}. "
            f"Series covers {annual_mean_tas.index.min()}-{annual_mean_tas.index.max()}. "
            f"Mode C needs a global temperature trajectory that spans the pre-industrial "
            f"baseline -- see module docstring for the local-data-gap caveat."
        )
    baseline_mean = float(baseline_slice.mean())
    return annual_mean_tas - baseline_mean


def find_warming_level_windows(
    annual_mean_tas: pd.Series,
    levels: list[float] = DEFAULT_WARMING_LEVELS,
    baseline_years: tuple[int, int] = (1850, 1900),
    smoothing_years: int = 20,
    window_years: int = 20,
) -> list[WarmingLevelWindow]:
    """Framework §4.3 full algorithm: anomaly -> 20yr smooth -> first crossing -> 20yr
    window centered on the crossing year, per warming level.

    Example::

        >>> import numpy as np, pandas as pd
        >>> years = np.arange(1850, 2101)
        >>> # toy: 0 anomaly at baseline, linear +3C warming from 1850 to 2100
        >>> tas = pd.Series(14.0 + 3.0 * (years - 1850) / (2100 - 1850), index=years)
        >>> windows = find_warming_level_windows(tas, levels=[1.5, 2.0])
        >>> windows[0].reached, windows[1].reached
        (True, True)
        >>> windows[0].crossing_year < windows[1].crossing_year
        True
    """
    anomaly = global_annual_mean_anomaly(annual_mean_tas, baseline_years)
    smoothed = anomaly.rolling(window=smoothing_years, center=True, min_periods=smoothing_years).mean()

    results = []
    for level in levels:
        above = smoothed[smoothed >= level]
        if above.empty:
            results.append(WarmingLevelWindow(level, False, None, None, None, None))
            continue
        crossing_year = int(above.index.min())
        half = window_years // 2
        w_start = crossing_year - half
        w_end = w_start + window_years - 1
        results.append(
            WarmingLevelWindow(
                level=level,
                reached=True,
                crossing_year=crossing_year,
                window_start_year=w_start,
                window_end_year=w_end,
                smoothed_anomaly_at_crossing=float(smoothed.loc[crossing_year]),
            )
        )
    return results


def warming_level_change(
    values_in_window: np.ndarray, baseline_values: np.ndarray
) -> float:
    """Framework §4.3 output: Delta I_g,L = I_g,L - I_g,baseline, for one warming-level window.

    Args:
        values_in_window: the impact/variable of interest averaged (or however
            aggregated) over the warming-level window (Framework leaves the
            aggregation to the caller -- pass whatever summary is being compared).
        baseline_values: the same quantity computed over the project baseline period.
    """
    return float(np.nanmean(values_in_window) - np.nanmean(baseline_values))
