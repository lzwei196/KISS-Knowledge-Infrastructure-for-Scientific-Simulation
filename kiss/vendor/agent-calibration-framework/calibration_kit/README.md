# calibration_kit

Model-agnostic **calibration** for the self-improve KI engine. Sibling to the loop:
the self-improve KI makes a model **run correctly**; this kit tunes its **parameters**
to fit the dag-defined obs. **Data assimilation** (sequential state estimation) is a
**separate** sibling module (OpenDA-based) — not here.

Design from a codex architecture review (2026-06-26): one shared model adapter/
evaluator, calibration libraries as pluggable backends above it.

## Layers
```
calib.calibrate()            # entry: load contract+dag -> objectives -> backend -> validate
  objectives.py              # derive a SMALL set of losses from the dag's gate-valid metric_families
  evaluator.py               # the ONE per-model adapter: apply params -> run model -> dag metrics
    applicator.py            # write a value into a model input via `address` (yaml/namelist/.inp/...)
  backends/                  # pluggable optimizers (no model-specific logic)
    spotpy_backend.py        # DEFAULT: DDS / SCE-UA / DREAM  (single-objective)
    pymoo_backend.py         # MULTI-OBJECTIVE: NSGA-II/III, MOEA/D
    (surrogate: BoTorch+GPyTorch/SMT; pestpp_ies: pyEMU)   # to add
```

## Recommended stack (codex)
- **Default:** SPOTPY → DDS then SCE-UA; DREAM for posteriors.
- **Multi-objective:** pymoo (NSGA-II for 2–3 objs, NSGA-III/MOEA-D beyond).
- **Surrogate (expensive):** BoTorch + GPyTorch (+ SMT for kriging/multi-fidelity).
- **High-dim / regularized:** PEST++ / pyEMU (`pestpp-glm`, `pestpp-ies`).

## Two contracts
- `dag.yaml` (exists) → **objectives** (gate-valid metric_families per output).
- `calibration.yaml` (new, per model) → **parameters**: name/type/units/range/transform
  **+ spatial scope & tying + activation + constraints + an edit `address`**. The
  address (yaml_path, namelist, table_cell, modflow_pkg, swmm_inp, api, …) is what
  lets a generic optimizer edit any model's inputs. See `CALIBRATION_YAML_SCHEMA.md`.

## Key principles (codex)
- Gates stay HARD feasibility; derive a **small** number of normalized losses; Pareto
  only for real trade-offs, else scalarize. Don't make one objective per metric-per-site.
- **Few free parameters** first (equifinality); use `tie`/hierarchical `scope` before freeing more.
- **Holdout validation is mandatory** (years/sites/regions) — over-fit risk otherwise.
- **Expensive models** (PCSE national, distributed hydro): staged —
  sensitivity screen (pestpp-sen / SPOTPY FAST) → representative-subset calibration →
  tied/hierarchical parameterization → surrogate-assisted → full-domain confirm on a shortlist.
  Start with **DDS or regularized PEST++**, not population MOEAs.

## Reuses the platform's strengths
- **Obs-support alignment** (codex's #1 source of false "improvements") is already handled
  by the dag gate + run-validity critic — the evaluator scores through them.
- **Orchestration** (caching/resume/parallel/crash-classification) is the detached +
  parallel infra the self-improve KI already has — a generation of candidates is just
  parallel detached runs.

## Status
Skeleton: schema + contract loader + objectives + applicator (yaml/json/ini/text done;
namelist/table/modflow/swmm/api stubbed) + evaluator + backend interfaces (SPOTPY/pymoo
bodies stubbed). Next: wire `Evaluator.run_model` to the KI run path, fill one backend
end-to-end (DDS), add the holdout step, and a `calibration.yaml`-generation campaign
(like dag-gen) to author the per-model contracts.
