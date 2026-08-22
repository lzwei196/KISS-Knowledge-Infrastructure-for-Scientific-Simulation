# Agent-Driven Calibration Framework

A **model-agnostic** autonomous calibration framework. Given a physical model's
**Knowledge Infrastructure (KI)** — its documented observables, parameters, and run
tools — an LLM agent **authors a standalone calibration pipeline**
(`calibration.yaml` + `tools/calib_run.py`) that then runs *without the agent*. A
fixed engine supplies all the numerical machinery, so the agent never writes an
optimizer — it only **chooses and configures** one by reasoning about the problem.

## Two layers

1. **Engine — `calibration_kit/`** (fixed, model-agnostic, self-contained)
   - a Morris **sensitivity screen**
   - four optimizer backends: **DDS / SCE-UA / DREAM** (via `spotpy`) and **NSGA-II**
     (via `pymoo`); optional PEST++ / surrogate backends
   - a fail-closed, per-objective, **out-of-sample holdout gate** (correlation floor,
     magnitude backstop, beats-baseline) that returns an honest
     **promotable / not-promotable** verdict — the framework knows when *not* to
     promote (or not to calibrate) a result.

2. **Authoring — `authoring/`** (the calib-dev agent, shown as reference)
   - given a KI + a target case, an LLM authors the `calibration.yaml` (parameter pool
     + literature-grounded ranges + targets + **optimizer choice + rationale** + strategy)
     and `tools/calib_run.py` (inject params → run the model's own tools → score → emit
     metrics). The agent **reasons the optimizer from problem structure** — single- vs
     multi-objective, cost per eval, and whether parameter *uncertainty* is the deliverable
     — never a fixed default.
   - *This layer spawns LLM / codex CLI agents; it is included here as the authoring
     contract + prompt reference and depends on the host environment's agent-spawning
     helper (`orchestrator`).* The engine below runs fully without it.

## Engine usage

```python
from calibration_kit import calib

report = calib.calibrate(
    ki_path="/path/to/model_KI",            # holds calibration.yaml + tools/calib_run.py
    workdir="/tmp/run",
    obs_shape_by_var={"Q": "point_time_series"},
    budget=300, seed=0,
)
report["promotable"]        # honest out-of-sample gate verdict
report["best_params"]       # committed parameter vector
```

- Force a specific optimizer with `KDT_CALIB_ALGO=dds|sceua|dream|nsga2`.
- Per-eval hang guard: `KDT_CALIB_EVAL_TIMEOUT=<seconds>`.
- Multi-objective Pareto commit uses an exhaustive, holdout-gated minimax selection
  (`KDT_CALIB_FRONT_SELECT=1`).

## The authoring contract

An authored pipeline follows **`calibration_kit/CALIBRATION_YAML_SCHEMA.md`**. The runner
receives params as a **file path** (`KDT_CALIB_PARAMS`), injects them the model's own way,
echoes `__kdt__.applied_params` (verified fail-closed every eval), and emits **var-scoped**
metrics. The engine probes the runner and drops any declared objective it doesn't emit.

## Dependencies

`numpy`, `spotpy` (DDS/SCE-UA/DREAM), `pymoo` (NSGA-II), `pyyaml`. Optional: `pyemu`/PEST++
and a surrogate backend. *Detached-eval mode additionally needs the host `orchestrator`;
the default in-process / subprocess eval modes are fully self-contained.*

## Design docs

- `calibration_kit/CALIBRATION_FRAMEWORK_DESIGN.md` — architecture & rationale
- `calibration_kit/CALIBRATION_YAML_SCHEMA.md` — the authoring contract
- `calibration_kit/calibration.example.yaml` — a worked contract
