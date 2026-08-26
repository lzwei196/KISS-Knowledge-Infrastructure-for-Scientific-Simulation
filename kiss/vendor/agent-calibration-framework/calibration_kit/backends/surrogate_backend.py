"""Surrogate / Bayesian-optimization backend — for EXPENSIVE single-objective
calibration where each eval costs minutes-hours and you can afford only ~tens of
runs. Fits a Gaussian-process surrogate (GPyTorch via BoTorch) on the evaluated
points and proposes the next point by maximizing Expected Improvement.

This is the budget-frugal path codex recommended for national PCSE-style runs (after
a sensitivity screen + representative-subset). Single-objective only here; for
expensive MULTI-objective use BoTorch qNEHVI later.

Falls back to SMT (kriging) if BoTorch/torch is unavailable but SMT is.
"""
from __future__ import annotations
from .base import Backend, Problem, CalibResult


class SurrogateBackend(Backend):
    name = "surrogate"

    def __init__(self, init_points: int = 8, library: str = "botorch"):
        self.init_points = init_points
        self.library = library          # botorch | smt

    @staticmethod
    def available() -> bool:
        import importlib.util as u
        return (u.find_spec("botorch") is not None and u.find_spec("torch") is not None) \
            or u.find_spec("smt") is not None

    def optimize(self, problem: Problem, budget: int, seed: int = 0, **kw) -> CalibResult:
        if problem.is_multi_objective:
            raise ValueError("SurrogateBackend here is single-objective; use qNEHVI for "
                             "expensive multi-objective (to add).")
        import importlib.util as u
        use_botorch = (self.library == "botorch"
                       and u.find_spec("botorch") and u.find_spec("torch"))
        return (self._botorch if use_botorch else self._smt)(problem, budget, seed)

    # ---- BoTorch (GP + Expected Improvement) -------------------------------
    def _botorch(self, problem, budget, seed):
        import torch
        from botorch.models import SingleTaskGP
        from botorch.fit import fit_gpytorch_mll
        from gpytorch.mlls import ExactMarginalLogLikelihood
        from botorch.acquisition import ExpectedImprovement
        from botorch.optim import optimize_acqf

        torch.manual_seed(seed)
        dt = torch.double
        lo = torch.tensor(problem.lower, dtype=dt)
        hi = torch.tensor(problem.upper, dtype=dt)
        bounds = torch.stack([lo, hi])
        d = len(problem.names)

        history = []
        def f(x_row):
            losses = problem.evaluate([float(v) for v in x_row])
            loss = float(losses[0]) if losses else float("inf")
            history.append({"x": list(map(float, x_row)), "loss": loss})
            return loss

        # normalize x to unit cube for the GP; map back to evaluate
        def to_unit(X):  return (X - lo) / (hi - lo)
        def from_unit(U): return lo + U * (hi - lo)

        n_init = min(self.init_points, max(2, budget // 2))
        U = torch.rand(n_init, d, dtype=dt)
        Y = []
        for u_ in U:
            Y.append(f(from_unit(u_)))
        Y = torch.tensor([[-y if y < 1e29 else -1e29] for y in Y], dtype=dt)  # maximize -loss
        Ufit = U.clone()

        for _ in range(max(0, budget - n_init)):
            try:
                gp = SingleTaskGP(Ufit, Y)
                mll = ExactMarginalLogLikelihood(gp.likelihood, gp)
                fit_gpytorch_mll(mll)
                ei = ExpectedImprovement(gp, best_f=Y.max())
                cand, _ = optimize_acqf(
                    ei, bounds=torch.stack([torch.zeros(d, dtype=dt),
                                            torch.ones(d, dtype=dt)]),
                    q=1, num_restarts=5, raw_samples=64)
                u_next = cand.detach().squeeze(0)
            except Exception:
                u_next = torch.rand(d, dtype=dt)      # robust fallback: random probe
            y = f(from_unit(u_next))
            Ufit = torch.cat([Ufit, u_next.unsqueeze(0)])
            Y = torch.cat([Y, torch.tensor([[-y if y < 1e29 else -1e29]], dtype=dt)])

        finite = [h for h in history if h["loss"] < 1e29]
        if not finite:
            return CalibResult(best_x=[], best_loss=[float("inf")], backend="surrogate:botorch",
                               n_evaluations=len(history), notes="no finite eval")
        best = min(finite, key=lambda h: h["loss"])
        return CalibResult(best_x=best["x"], best_loss=[best["loss"]],
                           n_evaluations=len(history), history=history,
                           backend="surrogate:botorch",
                           notes=f"GP-EI; {len(finite)}/{len(history)} finite; best {best['loss']:.5g}")

    # ---- SMT (kriging EGO) fallback ----------------------------------------
    def _smt(self, problem, budget, seed):
        import numpy as np
        try:
            from smt.applications import EGO
            from smt.sampling_methods import LHS
        except Exception as e:
            return CalibResult(best_x=[], best_loss=[float("inf")], backend="surrogate:smt",
                               notes=f"SMT unavailable: {e}")
        xlimits = np.array(list(zip(problem.lower, problem.upper)), float)
        history = []
        def f(X):
            out = []
            for row in np.atleast_2d(X):
                losses = problem.evaluate([float(v) for v in row])
                loss = float(losses[0]) if losses else 1e30
                history.append({"x": list(map(float, row)), "loss": loss})
                out.append([loss if np.isfinite(loss) else 1e30])
            return np.array(out)
        n_init = min(self.init_points, max(2, budget // 2))
        # SMT's LHS/EGO option set varies by version; build defensively (botorch is
        # the primary surrogate path — SMT is a best-effort kriging fallback).
        np.random.seed(seed)
        try:
            sampler = LHS(xlimits=xlimits)
            ego = EGO(n_iter=max(1, budget - n_init), criterion="EI",
                      xdoe=sampler(n_init), xlimits=xlimits)
            x_opt, y_opt, _, _, _ = ego.optimize(fun=f)
        except Exception as e:
            # if any points were evaluated, still report the best seen
            if history:
                fin = [h for h in history if h["loss"] < 1e30]
                if fin:
                    b = min(fin, key=lambda h: h["loss"])
                    return CalibResult(best_x=b["x"], best_loss=[b["loss"]],
                                       n_evaluations=len(history), history=history,
                                       backend="surrogate:smt",
                                       notes=f"EGO API error ({e}); returned best LHS/DoE point")
            return CalibResult(best_x=[], best_loss=[float("inf")], backend="surrogate:smt",
                               n_evaluations=len(history), notes=f"EGO failed: {e}")
        # only a TRULY finite history entry counts — an all-fail run (every loss the
        # 1e30 penalty) must NOT report x_opt/y_opt as success (codex surrogate:140).
        finite = [h for h in history if np.isfinite(h["loss"]) and h["loss"] < 1e29]
        if not finite:
            return CalibResult(best_x=[], best_loss=[float("inf")], backend="surrogate:smt",
                               n_evaluations=len(history),
                               notes="no finite eval (all penalized) — calibration failed")
        best = min(finite, key=lambda h: h["loss"])
        return CalibResult(best_x=best["x"], best_loss=[best["loss"]],
                           n_evaluations=len(history), history=history,
                           backend="surrogate:smt", notes="kriging EGO")
