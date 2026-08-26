"""
uncertainty.py -- ensemble uncertainty decomposition (Framework §12). Pure
numpy/array math -- safe to import alongside ki_tools_common.

Framework §12: U = U_GCM + U_SSP + U_climate_product + U_process_model +
U_parameters + U_initial_state + U_disaggregation. This module implements
the two concrete, generically-computable pieces of that: (a) ensemble
summary statistics across GCMs/members for one SSP/model configuration,
and (b) a simple two-way (GCM x SSP) variance decomposition. The other
axes (climate_product = ISIMIP-vs-HiCPC, process_model, parameters,
initial_state, disaggregation) require running the SAME experiment under
each alternative choice and differencing the results -- that is an
experiment-design decision for the calling workflow (Framework §8), not
something this module can compute from a single ensemble array.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class EnsembleStats:
    median: float
    iqr: float
    p5: float
    p95: float
    frac_positive: float
    frac_negative: float
    n_members: int
    historical_variability: float
    signal_to_noise: float

    def robust_change(self, majority_threshold: float = 0.66, snr_threshold: float = 1.0) -> bool:
        """Framework §12: 'A robust change may be defined using both: (1) a strong majority of
        GCMs agreeing on the sign, and (2) the ensemble change exceeding an agreed
        historical-variability threshold.' Thresholds must be declared BEFORE inspecting the
        result (Framework's own rule) -- pass them explicitly, do not tune post hoc.
        """
        majority_sign = max(self.frac_positive, self.frac_negative)
        return majority_sign >= majority_threshold and abs(self.signal_to_noise) >= snr_threshold


def ensemble_stats(deltas: np.ndarray, historical_variability: float) -> EnsembleStats:
    """Framework §12 minimum-report stats across an ensemble of per-GCM/member deltas.

    Args:
        deltas: 1-D array, one future-minus-baseline change value per
            GCM/member (Framework §4.1 Delta_g,s,p = I_g,s,p - I_g,baseline).
        historical_variability: A pre-agreed measure of natural historical
            variability for the same quantity (e.g. interannual std dev of
            the baseline period) -- used as the denominator for
            signal-to-noise, and must be computed the SAME way every time
            this is called for comparable results.

    Example::

        >>> import numpy as np
        >>> d = np.array([1.0, 1.5, 0.8, -0.2, 2.0])
        >>> s = ensemble_stats(d, historical_variability=0.5)
        >>> round(s.median, 2), round(s.frac_positive, 2)
        (1.0, 0.8)
    """
    deltas = np.asarray(deltas, dtype=float)
    deltas = deltas[np.isfinite(deltas)]
    if deltas.size == 0:
        raise ValueError("ensemble_stats received no finite values.")
    if historical_variability <= 0:
        raise ValueError("historical_variability must be > 0 to compute a meaningful signal-to-noise ratio.")

    median = float(np.median(deltas))
    q25, q75 = np.percentile(deltas, [25, 75])
    p5, p95 = np.percentile(deltas, [5, 95])
    frac_pos = float(np.mean(deltas > 0))
    frac_neg = float(np.mean(deltas < 0))
    snr = median / historical_variability

    return EnsembleStats(
        median=median,
        iqr=float(q75 - q25),
        p5=float(p5),
        p95=float(p95),
        frac_positive=frac_pos,
        frac_negative=frac_neg,
        n_members=int(deltas.size),
        historical_variability=float(historical_variability),
        signal_to_noise=float(snr),
    )


@dataclass
class VarianceDecomposition:
    total_variance: float
    gcm_variance: float
    ssp_variance: float
    interaction_variance: float
    gcm_fraction: float
    ssp_fraction: float
    interaction_fraction: float


def two_way_variance_decomposition(deltas_by_gcm_ssp: dict[tuple[str, str], float]) -> VarianceDecomposition:
    """Framework §12 hierarchical decomposition -- simple balanced two-way ANOVA-style split
    of a (gcm, ssp) -> delta table into GCM, SSP, and interaction/residual variance
    components. Requires a BALANCED design (every gcm x ssp combination present) -- raises
    otherwise rather than silently computing a biased estimate on an unbalanced subset.

    Example::

        >>> d = {("A","ssp126"): 1.0, ("A","ssp585"): 3.0,
        ...      ("B","ssp126"): 1.2, ("B","ssp585"): 3.4}
        >>> vd = two_way_variance_decomposition(d)
        >>> round(vd.ssp_fraction, 2) > round(vd.gcm_fraction, 2)
        True
    """
    gcms = sorted({g for g, _ in deltas_by_gcm_ssp})
    ssps = sorted({s for _, s in deltas_by_gcm_ssp})
    missing = [(g, s) for g in gcms for s in ssps if (g, s) not in deltas_by_gcm_ssp]
    if missing:
        raise ValueError(
            f"two_way_variance_decomposition requires a balanced gcm x ssp grid; missing: {missing}. "
            f"Framework §10.1: 'Do not require every GCM to contain every SSP' for the ensemble itself, "
            f"but a variance decomposition specifically needs a balanced subset -- restrict to the "
            f"GCM x SSP combinations that ARE all present before calling this."
        )

    grid = np.array([[deltas_by_gcm_ssp[(g, s)] for s in ssps] for g in gcms])
    grand_mean = grid.mean()
    gcm_means = grid.mean(axis=1, keepdims=True)
    ssp_means = grid.mean(axis=0, keepdims=True)

    total_var = float(((grid - grand_mean) ** 2).sum())
    gcm_var = float(((gcm_means - grand_mean) ** 2).sum() * len(ssps))
    ssp_var = float(((ssp_means - grand_mean) ** 2).sum() * len(gcms))
    interaction_var = max(total_var - gcm_var - ssp_var, 0.0)

    denom = total_var if total_var > 0 else 1e-12
    return VarianceDecomposition(
        total_variance=total_var,
        gcm_variance=gcm_var,
        ssp_variance=ssp_var,
        interaction_variance=interaction_var,
        gcm_fraction=gcm_var / denom,
        ssp_fraction=ssp_var / denom,
        interaction_fraction=interaction_var / denom,
    )
