"""pymoo backend — true MULTI-OBJECTIVE (NSGA-II / NSGA-III / MOEA/D).

Use when the dag yields >=2 genuinely-conflicting objectives (e.g. crop yield
magnitude vs phenology timing). Returns the Pareto front; best_x is a knee/min-sum
representative for callers that want a single point.

Non-finite losses (failed/infeasible evals) are clamped to a large finite penalty —
pymoo's selection mishandles inf/NaN, so we map them to a big number that the search
strongly avoids without breaking the dominance sort.
"""
from __future__ import annotations
from .base import Backend, Problem, CalibResult

_PENALTY = 1e12        # finite stand-in for inf/NaN losses (pymoo-safe)


class PymooBackend(Backend):
    name = "pymoo"

    def __init__(self, algorithm: str = "nsga2", pop_size: int = 40):
        self.algorithm = algorithm          # nsga2 | nsga3 | moead
        self.pop_size = pop_size

    @staticmethod
    def available() -> bool:
        import importlib.util as u
        return u.find_spec("pymoo") is not None

    def optimize(self, problem: Problem, budget: int, seed: int = 0, **kw) -> CalibResult:
        import numpy as np
        from pymoo.core.problem import Problem as PymooProblem
        from pymoo.optimize import minimize

        n_var = len(problem.names)
        n_obj = len(problem.objective_names)
        xl = np.asarray(problem.lower, float)
        xu = np.asarray(problem.upper, float)
        history = {"n": 0}
        # remember which evaluated x were FULLY FINITE (codex pymoo:53) — penalized
        # points must NOT be selectable as a "best"/Pareto solution.
        finite_pts = []   # list of (x_tuple, losses) with all-finite losses

        def _clamp(v):
            v = float(v)
            return v if np.isfinite(v) else _PENALTY

        class _P(PymooProblem):
            def __init__(s):
                super().__init__(n_var=n_var, n_obj=n_obj, xl=xl, xu=xu)

            def _evaluate(s, X, out, *a, **k):
                F = []
                for row in np.atleast_2d(X):
                    xr = [float(z) for z in row]
                    losses = problem.evaluate(xr)
                    history["n"] += 1
                    if not losses:
                        losses = [_PENALTY] * n_obj
                    if all(np.isfinite(z) for z in losses):
                        finite_pts.append((xr, [float(z) for z in losses]))
                    F.append([_clamp(z) for z in losses])
                out["F"] = np.asarray(F, float)

        algo = self._make_algorithm(n_obj)
        res = minimize(_P(), algo, ("n_eval", int(budget)), seed=seed, verbose=False)

        if not finite_pts:
            # every evaluation was infeasible/failed -> NOT a calibration (so
            # calib.py routes to the failure/restore path, not a bogus "completed").
            return CalibResult(best_x=[], best_loss=[float("inf")] * n_obj,
                               backend=f"pymoo:{self.algorithm}", n_evaluations=history["n"],
                               notes="no fully-finite evaluation (all penalized)")
        if res.X is None:
            X = np.asarray([p[0] for p in finite_pts], float)
            F = np.asarray([p[1] for p in finite_pts], float)
        else:
            # keep only returned-front points that were actually finite (drop penalized)
            Xr = np.atleast_2d(res.X); Fr = np.atleast_2d(res.F)
            keep = [i for i in range(len(Fr)) if np.all(np.isfinite(Fr[i]))
                    and Fr[i].max() < _PENALTY / 2]
            if keep:
                X = Xr[keep]; F = Fr[keep]
            else:
                X = np.asarray([p[0] for p in finite_pts], float)
                F = np.asarray([p[1] for p in finite_pts], float)
        # single representative = min normalized-sum across the front (a simple knee proxy)
        Fn = (F - F.min(0)) / (np.ptp(F, axis=0) + 1e-12)
        best_i = int(Fn.sum(1).argmin())
        return CalibResult(
            best_x=X[best_i].tolist(), best_loss=F[best_i].tolist(),
            pareto_x=X.tolist(), pareto_f=F.tolist(), n_evaluations=history["n"],
            backend=f"pymoo:{self.algorithm}",
            notes=f"Pareto front of {len(X)} solution(s); best = min-normalized-sum knee")

    def _make_algorithm(self, n_obj: int):
        if self.algorithm == "nsga2":
            from pymoo.algorithms.moo.nsga2 import NSGA2
            return NSGA2(pop_size=self.pop_size)
        from pymoo.util.ref_dirs import get_reference_directions
        # das-dennis partitions tuned so the reference set ~ pop_size
        n_part = max(1, 12 if n_obj <= 2 else 6)
        ref = get_reference_directions("das-dennis", n_obj, n_partitions=n_part)
        if self.algorithm == "nsga3":
            from pymoo.algorithms.moo.nsga3 import NSGA3
            return NSGA3(ref_dirs=ref, pop_size=self.pop_size)
        if self.algorithm == "moead":
            from pymoo.algorithms.moo.moead import MOEAD
            return MOEAD(ref_dirs=ref, n_neighbors=min(15, len(ref)))
        raise ValueError(f"unknown pymoo algorithm {self.algorithm!r}")
