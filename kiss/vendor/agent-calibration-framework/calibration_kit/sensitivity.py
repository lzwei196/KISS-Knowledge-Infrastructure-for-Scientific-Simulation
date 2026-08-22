"""Sensitivity screening — rank parameters by influence on the calibration objective,
so calibration can start with the FEW most-sensitive params and ESCALATE (add more)
only if needed (codex's staged guidance; avoids equifinality / over-fit).

Method: Morris elementary effects (a cheap, standard screening design). For R random
base points in the unit box, perturb each parameter one-at-a-time by `delta` and
record the change in the scalar loss. The mean absolute elementary effect (mu*) ranks
sensitivity; the std (sigma) flags interactions/non-linearity. Cost = R*(d+1) evals —
much cheaper than a full calibration, and far cheaper than freeing all params at once.

evaluate(x) is the SAME scalar-loss callback the optimizer uses (lower = better);
non-finite losses are skipped so a failed run doesn't corrupt the ranking.
"""
from __future__ import annotations
import math


def morris_screen(evaluate, lower, upper, R: int = 4, delta: float = 0.1, seed: int = 0):
    """Return a dict: {ranking: [param_idx desc by mu*], mu_star: [...], sigma: [...]}.
    `evaluate` maps a full parameter vector (search space) -> scalar loss."""
    import numpy as np
    rng = np.random.default_rng(seed)
    lo = np.asarray(lower, float); hi = np.asarray(upper, float)
    span = hi - lo
    d = len(lo)
    eff = [[] for _ in range(d)]   # elementary effects per param

    for _ in range(max(1, R)):
        base_u = rng.random(d)                      # base point in unit box
        base_x = lo + base_u * span
        f_base = evaluate(list(base_x))
        if not _finite(f_base):
            continue
        for j in range(d):
            u2 = base_u.copy()
            step = delta if u2[j] + delta <= 1.0 else -delta   # stay in box
            u2[j] += step
            x2 = lo + u2 * span
            f2 = evaluate(list(x2))
            if not _finite(f2):
                continue
            # elementary effect normalized by the unit-box step
            eff[j].append(abs(f2 - f_base) / abs(step))

    mu_star = [float(sum(e) / len(e)) if e else 0.0 for e in eff]
    sigma = [float(_std(e)) for e in eff]
    ranking = sorted(range(d), key=lambda j: mu_star[j], reverse=True)
    return {"ranking": ranking, "mu_star": mu_star, "sigma": sigma,
            "n_effects": [len(e) for e in eff]}


def _finite(v):
    try:
        return math.isfinite(float(v))
    except (TypeError, ValueError):
        return False


def _std(xs):
    if len(xs) < 2:
        return 0.0
    m = sum(xs) / len(xs)
    return (sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) ** 0.5
