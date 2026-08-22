# Calibration Framework — Design (v2, 2026-07-08)

A standalone, domain-general calibration framework parallel to self-improve, for all 400+ model KIs. This
doc captures the v2 refinements: KI-as-execution-backbone, literature-grounded sensitivity/holdout, and the
applicator-vs-runner injection split.

## Two foundations (shared with self-improve + validation conventions)
1. **The KI is the execution backbone.** NOTHING runs the model except the KI's own run/forcing/execute
   tools. Calibration never reimplements execution — it *wraps* the KI. Guarantees the thing you calibrate ==
   the thing self-improve validated; KI execution improvements flow to calibration for free; sensitivity,
   optimize, and holdout all use ONE execution path.
2. **The literature is the grounding.** What to tune, how to hold out, and what "good" means come from
   `dag.yaml` + model docs + sensitivity-analysis papers + calibration/validation papers — NOT generic
   defaults. This is the SAME per-model literature pass that produces the validation convention.

## Pipeline
```
calibrate.py --model X --case Y
  → GATE 1 READINESS  (self_improve_runs: only calibrate a model validated as RUNNING)
  → CAPABILITY-DEV (once, if missing): author calibration.yaml + tools/calib_run.py (see below)
  → ENGINE:  sensitivity(Morris, literature-seeded) → optimize(DDS/NSGA-II/BoTorch) → GATE 2 HOLDOUT(field protocol)
  → CASE-APPLY best params → case_params/<case>.json   (NEVER the KI)
  → RECORD calibration_runs (engine_status ≠ scientific_verdict; promotion_scope ∈ {none,case})
```

## Part 1 — the per-KI capability = a wrapper over a CALIBRATABLE EXECUTION ENTRYPOINT (two-phase)
Calibration wraps the KI — but "wrap the KI" must mean a **stable non-interactive case executor**, NOT "re-run
whatever self-improve did" (that would re-do setup/download/build every eval — the optimize loop runs 100s–
1000s of times). So the contract is TWO-PHASE (Codex):

**`prepare_case` — ONCE:** build / download / convert / force → an IMMUTABLE prepared base for this case.
**`run_candidate` — MANY times:** run in a PASSED eval workdir with a passed split/seed; **no redownload, no
shared mutable paths, stale outputs cleared; ALL writes under the eval workdir** (shared caches read-only).
Returns metrics + `__kdt__.applied_params` + `__kdt__.run_root` + the effective input artifact(s) read back.

**`tools/calib_run.py` is the thin wrapper**: (1) inject params, (2) call `run_candidate` in this eval workdir,
(3) score. No model logic. Honors `KDT_CALIB_SPLIT`.

**INJECTION-ORDERING RULE (critical):** if the KI **regenerates** runtime inputs each run (forcing converters,
workdir builders), a value injected into a file BEFORE the run gets overwritten → it never reaches execution.
Therefore: **applicator mode is valid ONLY for directly-consumed STABLE files. If execution regenerates the
input you'd edit, that KI is RUNNER mode, full stop** — inject at the right point in the pipeline and prove
readback from the *effective* artifact.

**Agent-run dependency (honest gate):** a KI whose only run path is LLM-driven (no programmatic entrypoint) is
NOT calibratable yet. `calib_run.py`/`prepare_case`/`run_candidate` can be the extracted entrypoint — until it
exists, calibration REFUSES (records not-ready), rather than pretending a wrapper is thin.

**(b) `calibration.yaml`** — the literature-grounded contract (below). The ITERATION is the general engine
(Morris + the 7–8 optimizers). Per-KI work = extract/confirm the two-phase entrypoint + author the contract.

## Part 2 — sensitivity + holdout are literature-grounded (literature = PRIOR, not a pruning oracle)
- **Params:** literature-supported params are ALWAYS in the candidate pool; everything else mechanistically
  plausible (from dag/docs) gets a CHEAP RESIDUAL Morris screen — NOT a free pass to exclusion. Encoding
  "a paper said this mattered *there*" as "only these knobs exist *here*" would miss site-specific
  sensitivities. Low-confidence params stay screenable, never silently dropped.
- **Ranges — separate two fields:** `hard_bounds` (true physical/numerical limits) vs `prior` /
  `expected_sensitivity` (soft, from published site ranges). Priors seed + rank; hard_bounds constrain search.
- **Holdout — needs the GENERALIZATION AXIS, not just kind/fraction.** Defaults keyed on obs_shape + the
  claimed transfer: `point_time_series` → contiguous blocked temporal split; `multi-site`/panel → grouped
  region holdout if claiming spatial transfer, else blocked temporal within site; `gridded` → spatial block /
  leave-region-out; `spatiotemporal` → blocked space-time with the held-out axis = the promotion claim.
  From the model's **calibration/validation papers** where they exist (Klemeš split-sample / differential
  split-sample), the principled default otherwise.
- **Pass threshold:** the **validation convention** (already literature-grounded) — headline metric + band.
- **PROVENANCE (mandatory, mirrors the convention's citation gate):** `calibration.yaml` records a citation +
  confidence for BOTH each sensitive param AND the holdout choice. Uncited → `low_confidence` (screenable /
  flagged), NOT trusted. Otherwise "literature-grounded" isn't auditable.
- One literature read → (a) validation convention [gate] AND (b) calibration design [params/holdout]. Unified.

## Injection — applicator (generic formats) vs runner (model-specific). Taxonomy fixed.
The old "address kinds" mixed two levels. Corrected split:
| kind | level | home |
|---|---|---|
| yaml_path, json_path, ini_key, text_token, **namelist**, **fixed_width**, **table_cell** | generic **format** | **applicator** (central, reusable, C7-verified) |
| **modflow_pkg**, **swmm_inp**, **api** | **model/mechanism**-specific | **runner mode** — `calib_run.py` uses the model's native lib (flopy, pyswmm) / KI tools |

- Do NOT centralize model-specific kinds (a central `modflow_pkg` would reimplement flopy). They go to runner mode.
- Fill only the generic-format applicator stubs: namelist, fixed_width, table_cell (high reuse).
- `injection.mode: applicator | runner` per KI (default applicator; existing YAMLs unchanged). No per-param mixing.

## Runner-mode safety — delegated injection must PROVE ITSELF TWICE (else silent-non-injection lies)
1. **Round-trip, every eval:** wrapper injects → reads back from the effective artifact the model consumes →
   any unwritten param → exit nonzero, emit NO metrics. Echo `__kdt__.applied_params`; the kit diffs
   requested vs applied every eval; mismatch = eval FAILED, not "trust the metrics."
2. **Responsiveness, once at commissioning:** default vs perturbed vector in isolated workdirs; if applied
   matches but the metric doesn't move → reject `fix_driver` (caught "wrote a file, not the one the run uses").

## Build steps
1. Schema: add `injection.mode` + reserved `__kdt__.applied_params`; document literature-grounded
   params/priors/holdout fields.
2. calib-dev prompt (stage_calibrate.py): author the WRAPPER (inject → KI run tools → score), NOT a bespoke
   run; ground params/ranges/holdout in dag+docs+sensitivity+calib papers; commissioning self-test.
3. calib.py: branch on injection.mode; request-vs-applied diff every eval; one-time responsiveness gate;
   seed Morris from literature priors.
4. applicator: fill namelist, fixed_width, table_cell (generic). Remove modflow_pkg/swmm_inp/api from the
   central kind-list (they are runner-mode).
5. Keep readiness + holdout + case-scoped-apply + calibration_runs exactly as-is.
```
