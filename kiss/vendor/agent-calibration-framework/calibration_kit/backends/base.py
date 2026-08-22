"""Calibration backend interface.

Every optimizer (SPOTPY/DDS, pymoo/NSGA-II, surrogate/BoTorch, PEST++/iES) is a
pluggable Backend over a shared Problem. The Problem is model-agnostic: it knows
how to evaluate a parameter VECTOR (apply -> run -> score) and the search bounds;
it does NOT know which model it is. This keeps the per-model integration in ONE
adapter (evaluator.py + applicator.py), per codex's "don't let any one library be
the integration surface" guidance.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, Sequence


@dataclass
class Problem:
    """A model-agnostic calibration problem handed to any backend."""
    names: list[str]                       # parameter names (order == vector order)
    lower: list[float]                     # search-space lower bounds (post-transform)
    upper: list[float]                     # search-space upper bounds (post-transform)
    objective_names: list[str]             # one per objective (>=1)
    # evaluate(x) -> list[float] of losses to MINIMIZE (one per objective_name).
    # Must return +inf for an infeasible/failed vector (never raise into the optimizer).
    evaluate: Callable[[Sequence[float]], list[float]]
    is_multi_objective: bool = False
    constraints_ok: Callable[[Sequence[float]], bool] | None = None  # hard feasibility


@dataclass
class CalibResult:
    best_x: list[float]                    # best parameter vector (search space)
    best_loss: list[float]                 # loss vector at best_x
    pareto_x: list[list[float]] = field(default_factory=list)   # multi-obj front params (if any)
    pareto_f: list[list[float]] = field(default_factory=list)   # multi-obj front objective values (losses)
    n_evaluations: int = 0
    history: list[dict] = field(default_factory=list)            # per-eval log
    backend: str = ""
    notes: str = ""
    posterior: dict | None = None      # per-parameter posterior summary (DREAM only; None otherwise)


class Backend:
    """Optimizer plugin. Subclasses wrap an established library; they must NOT
    contain any model-specific logic — only the optimization loop."""

    name = "base"

    def optimize(self, problem: Problem, budget: int, seed: int = 0,
                 **kw) -> CalibResult:
        raise NotImplementedError

    @staticmethod
    def available() -> bool:
        """Whether the wrapped library is importable in this env."""
        return False
