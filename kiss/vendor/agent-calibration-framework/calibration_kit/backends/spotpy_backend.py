"""SPOTPY backend — the model-agnostic DEFAULT (DDS, SCE-UA, DREAM).

SPOTPY is purpose-built for environmental-model calibration/uncertainty and ships
DDS, SCE-UA, DREAM, PA-DDS, NSGA-II, and NSE/KGE/PBIAS. We use it as the
SINGLE-OBJECTIVE default (DDS first, then SCE-UA) and for DREAM posterior sampling.
For TRUE multi-objective use pymoo_backend (cleaner MOEA support).

Wiring notes (spotpy 1.6.x):
  - DDS HARDCODES optimization_direction="maximize", so our loss-minimization is
    expressed by returning -loss from objectivefunction.
  - We don't trust ParameterSet extraction for the best vector; instead we record
    every (x, loss) the evaluator sees and pick the min-loss vector ourselves.
"""
from __future__ import annotations
from .base import Backend, Problem, CalibResult


class SpotpyBackend(Backend):
    name = "spotpy"
    # Single-objective optimizers/samplers verified through this backend.
    # (PA-DDS is multi-objective — route it via the multi-objective path, not here.)
    _ALGOS = ("dds", "sceua", "dream")

    def __init__(self, algorithm: str = "dds"):
        if algorithm not in self._ALGOS:
            raise ValueError(f"unknown spotpy algorithm {algorithm!r}; choose {self._ALGOS}")
        self.algorithm = algorithm

    @staticmethod
    def available() -> bool:
        import importlib.util as u
        return u.find_spec("spotpy") is not None

    def optimize(self, problem: Problem, budget: int, seed: int = 0, **kw) -> CalibResult:
        import spotpy
        import numpy as np

        if problem.is_multi_objective:
            raise ValueError("SpotpyBackend is single-objective; use PymooBackend for "
                             "multi-objective problems.")
        try:
            np.random.seed(seed)
        except Exception:
            pass

        history: list[dict] = []          # every (x, loss) the optimizer evaluated
        names, lo, hi = problem.names, problem.lower, problem.upper

        class _Setup:
            def parameters(self):
                return spotpy.parameter.generate([
                    spotpy.parameter.Uniform(n, float(a), float(b))
                    for n, a, b in zip(names, lo, hi)])

            def simulation(self, vector):
                x = [float(v) for v in vector]
                losses = problem.evaluate(x)
                loss = float(losses[0]) if losses else float("inf")
                # spotpy can't store non-finite "simulations"; clamp for storage but
                # keep the real loss for our own best-tracking.
                history.append({"x": x, "loss": loss})
                return [loss if np.isfinite(loss) else 1e30]

            def evaluation(self):
                return [0.0]              # target loss is 0

            def objectivefunction(self, simulation, evaluation):
                # DDS HARDCODES maximize -> return -loss so maximize(-loss) minimizes
                # loss. Other algos accept optimization_direction="minimize" below and
                # take +loss directly. (best-vector tracking is via `history`, so it's
                # direction-independent — only the sampler's SEARCH direction matters.)
                s = simulation[0] if simulation else 1e30
                return -s if _maximize else s

        # dds HARDCODES maximize; DREAM is a Bayesian sampler that draws proportional to the
        # objective read AS A LIKELIHOOD (higher == better fit), so it too must be handed -loss and
        # maximize — feeding +loss/minimize made it sample toward the WORST fits (latent bug: no dream
        # run existed before). sceua minimizes +loss directly.
        _maximize = self.algorithm in ("dds", "dream")
        sampler_cls = getattr(spotpy.algorithms, self.algorithm)
        _dir_kw = {} if _maximize else {"optimization_direction": "minimize"}
        sampler = sampler_cls(_Setup(), dbname="calib", dbformat="ram",
                              save_sim=False, **_dir_kw)
        sampler.sample(int(budget))

        finite = [h for h in history if h["loss"] < 1e30]
        if not finite:
            return CalibResult(best_x=[], best_loss=[float("inf")], backend=self.name,
                               n_evaluations=len(history),
                               notes="no finite evaluation — all runs infeasible/failed")
        best = min(finite, key=lambda h: h["loss"])

        # DREAM is a POSTERIOR sampler — its deliverable is the parameter distribution, not just the
        # best point. The posterior is the ACCEPTED post-burn-in chain (sampler.bestpar, shape
        # (nchains, niter, nparam) — the state AFTER Metropolis accept/reject; getdata() stores the
        # PROPOSED runs before accept/reject and best-X% filtering is GLUE, which understates
        # uncertainty — codex review). Discard the first half as burn-in, flatten chains, drop
        # non-finite, summarize per-parameter percentiles + 95% credible interval. dds/sceua leave
        # posterior=None. Best-effort: any failure degrades to None, never breaks the run.
        posterior = None
        if self.algorithm == "dream":
            try:
                bp = np.asarray(getattr(sampler, "bestpar"), float)   # (nchains, niter, nparam)
                if bp.ndim == 3 and bp.shape[2] == len(names):
                    # DREAM stops EARLY at convergence, leaving bestpar's tail pre-allocated
                    # (NaN/zero). Keep only the FILLED iterations, then discard the first half of
                    # those as burn-in — never split on the allocated length.
                    valid = (np.isfinite(bp).all(axis=(0, 2))
                             & (np.abs(bp).sum(axis=(0, 2)) > 0))       # (niter,) filled iterations
                    idx = np.where(valid)[0]
                    if idx.size < 8:
                        raise ValueError(f"only {idx.size} filled DREAM iterations")
                    lo, hi = int(idx[0]), int(idx[-1]) + 1
                    burn = lo + (hi - lo) // 2                          # first half of filled = burn-in
                    samples = bp[:, burn:hi, :].reshape(-1, bp.shape[2])
                    samples = samples[np.isfinite(samples).all(axis=1)]
                    posterior = {"method": "dream_postburnin_chain",
                                 "n_chains": int(bp.shape[0]), "burn_in_frac": 0.5,
                                 "filled_iters": hi - lo, "n_samples": int(samples.shape[0])}
                    for j, nm in enumerate(names):
                        col = samples[:, j]
                        col = col[np.isfinite(col)]
                        if col.size < 2:
                            continue
                        p2, p50, p97 = (float(np.percentile(col, q)) for q in (2.5, 50, 97.5))
                        posterior[nm] = {"p2_5": p2, "p50": p50, "p97_5": p97,
                                         "mean": float(np.mean(col)), "std": float(np.std(col)),
                                         "ci95_width": p97 - p2}
                else:
                    posterior = {"_error": f"unexpected bestpar shape {getattr(bp,'shape',None)}"}
            except Exception as e:
                posterior = {"_error": f"{type(e).__name__}: {e}"}

        return CalibResult(
            best_x=best["x"], best_loss=[best["loss"]],
            n_evaluations=len(history),
            history=history, backend=f"spotpy:{self.algorithm}", posterior=posterior,
            notes=f"{len(finite)}/{len(history)} finite evals; best loss {best['loss']:.5g}")
