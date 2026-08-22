# `calibration.yaml` — the per-model calibration contract

The calibration analog of `dag.yaml`. Where `dag.yaml` declares *what to compare and
which metric is gate-valid*, `calibration.yaml` declares *which parameters may be
tuned, where they live in the model's inputs, and how to vary them*. One file per
model KI, at `<ki_path>/calibration.yaml`.

Per codex's design review (2026-06-26), a contract of only `name/range/default/
transform` does NOT generalize across crop config files, MODFLOW packages, and SWMM
`.inp` sections. It must also capture **type, units, spatial scope + tying, activation
conditions, inter-parameter constraints, and an edit `address`**. The `address` is the
crux — it is how a generic optimizer writes a parameter value back into a
heterogeneous model input.

---

## Top-level shape

```yaml
template_version: "calib-0.1"
model_id: PCSE
identity:
  domain: crop
  binding: Wofost72_WLP_CWB        # the specific model/engine variant these params apply to

# Optional: which dag outputs this calibration targets (objectives derive from the
# dag's gate-valid metric_families for these vars; see objectives.py). If omitted,
# all observable dag outputs with a mapped obs are used.
targets:
  - var: TWSO                       # must exist in dag.outputs
    weight: 1.0                     # relative weight if scalarized

parameters:
  - name: TSUM1                     # human/optimizer-facing id (unique within file)
    description: "Temperature sum emergence->anthesis (°C·d)"
    type: continuous                # continuous | integer | categorical | bool
    units: "degC.day"
    default: 1050.0
    range: [800.0, 1300.0]          # required for continuous/integer
    # categories: [...]             # required for categorical
    transform: identity             # identity | log | logit  (search-space transform)

    # --- spatial scope + tying (REQUIRED for generalization) ---
    scope: global                   # global | per-crop | per-soil-class | per-HRU |
                                    # per-layer | per-subbasin | per-cell | per-zone
    tie: null                       # null = free; or "<other param name>" / a tie-group
                                    # id so several locations move together
    # zone_key: "crop"             # when scope != global: the grouping key in the model

    # --- when this parameter is even active ---
    activation: always              # always | "<expr over other params/config>"
                                    # e.g. "binding == 'Wofost72_WLP_CWB'"

    # --- WHERE to write it (the hard part) ---
    address:
      kind: yaml_path               # see "Address kinds" below
      file: "work/grid/maize.crop"  # relative to ki_path or run workdir
      path: "TSUM1"                 # kind-specific locator

  - name: SPAN
    description: "Life span of leaves at 35°C (d)"
    type: continuous
    units: "day"
    default: 33.0
    range: [25.0, 45.0]
    transform: identity
    scope: global
    address:
      kind: yaml_path
      file: "work/grid/maize.crop"
      path: "SPAN"

# --- cross-parameter constraints (hard feasibility, checked before a run) ---
constraints:
  - "TSUM1 + 200 <= TSUM2"          # python-eval expr over parameter names; False => infeasible

# --- calibration strategy hints (optional; the kit picks defaults from model class) ---
# --- HOW to run+score one candidate, programmatically (NOT a claude agent) ---
# Calibration does 100s of evals, so the run must be a cheap repeatable script that
# runs the model with the CURRENT inputs (applicator already wrote this candidate's
# params) and returns the gate-valid metrics dict. See runner.py.
runner:
  kind: subprocess                  # python | subprocess | detached
  # subprocess: command writes a JSON metrics dict; {workdir}/{metrics_json} substituted
  command: ["./venv/bin/python", "tools/calib_run.py", "--workdir", "{workdir}", "--out", "{metrics_json}"]
  metrics_file: "{metrics_json}"
  timeout: 900
  # python:   callable: "tools.calib_run:run_and_score"   # def run_and_score(workdir)->dict
  # detached: runner: "run_and_score.py"  interpreter: "venv/bin/python"  # poll result.json

strategy:
  cost_class: expensive             # cheap | moderate | expensive  (drives algo + subset/surrogate)
  default_algorithm: dds            # dds | sceua | nsga2 | nsga3 | dream | pestpp_ies | surrogate
  max_evaluations: 300
  holdout:                          # MANDATORY for credibility (codex pitfall #1)
    kind: years                     # years | sites | regions | random
    fraction: 0.3
  subset:                           # for expensive models: calibrate on a stratified subset
    kind: stratified_cells
    n: 40
    stratify_by: ["agro_zone"]
```

---

## Address kinds (how a value is written back)

The applicator (`applicator.py`) dispatches on `address.kind`. Each kind needs a
distinct locator so a generic optimizer can edit any model input format:

| kind          | locator fields                          | example target |
|---------------|-----------------------------------------|----------------|
| `yaml_path`   | `file`, `path` (dotted/bracket path)    | PCSE `.crop`/`.site` YAML, config.yaml |
| `json_path`   | `file`, `path`                          | JSON config |
| `namelist`    | `file`, `group`, `key`                  | Fortran `&PARAM var=` (wflow, CLM, SWAT old) |
| `ini_key`     | `file`, `section`, `key`                | INI/TOML configs |
| `text_token`  | `file`, `pattern` (regex, 1 capture grp)| free-form text decks; replace capture group |
| `table_cell`  | `file`, `row` (0-indexed), `col` (0-indexed), `delimiter` (REQUIRED for writes; whitespace read-only) | CSV/delimited tables, DSSAT *.SOL |
| `fixed_width` | `file`, `line` (1-indexed), `col_start`, `col_end` (1-indexed inclusive) | fixed-width Fortran decks (APEX/EPIC) |
| `modflow_pkg` | `file`, `package`, `record`, `field`    | MODFLOW package records (via flopy) |
| `swmm_inp`    | `file`, `section`, `obj_id`, `field`    | SWMM `.inp` `[SUBCATCHMENTS]` etc. |
| `api`         | `setter` (python "module:callable")     | in-process override (PCSE ParameterProvider, pyswmm) |

The applicator MUST be idempotent and round-trippable: write value V, read it back,
get V. Each kind has a paired reader so the contract can be self-tested
(`applicator.verify_roundtrip`).

---

## Rules (mirroring dag.yaml's R-rules)

- **C1 Membership.** Every `address.file` must exist (after a model run sets up its
  workdir). Validate at load; a dangling address is a contract error, not a silent skip.
- **C2 Observable target.** `targets[].var` must be a real `dag.outputs` var with a
  mapped obs — you can only calibrate toward something you can score.
- **C3 Scope honesty.** `scope != global` REQUIRES a `zone_key` the model actually
  groups by; otherwise the param is mis-tied and the search is meaningless.
- **C4 Identifiability.** Prefer FEW free parameters (codex pitfall: over-parameterization
  / equifinality). Use `tie` and hierarchical `scope` to reduce dimensionality before
  freeing more.
- **C5 Feasibility first.** `constraints` are hard — an infeasible vector is rejected
  WITHOUT a model run (cheap), never scored.
- **C6 Holdout mandatory.** `strategy.holdout` is required; a calibration that doesn't
  validate on held-out years/sites/regions is not promotable (over-fit risk).
- **C7 Round-trip.** Every `address` must pass `verify_roundtrip` before the param is
  used — a write/read that doesn't agree corrupts the search silently.

---

# v2 (2026-07-08) — `injection.mode`, provenance, and the runner contract  (READ THIS; supersedes pre-v2 runner semantics)

## `injection.mode: applicator | runner`  (top-level, default `applicator`)
Existing YAMLs are unchanged (default = `applicator`). The mode is per-KI, NOT per-parameter.

**`applicator` mode (default):** the KIT writes each param value into the model's input files via its
`address` (round-trip verified, C7). Valid ONLY when the model consumes stable files DIRECTLY. Address kinds:
- GENERIC FORMATS (central, reusable): `yaml_path` `json_path` `ini_key` `text_token` `namelist`
  `fixed_width` `table_cell`.
- MODEL/MECHANISM-specific (`modflow_pkg` `swmm_inp` `api`) are NOT applicator kinds — they raise a
  runner-mode error. Use `runner` mode for those (a central MODFLOW handler would reimplement flopy).

**`runner` mode:** the KIT does NOT write params. It writes the candidate vector to `kdt_params.json` in the
eval workdir and sets `KDT_CALIB_PARAMS` to its path; your `tools/calib_run.py` INJECTS them the model's own
way (e.g. `import flopy` / `pyswmm`), runs, and scores. **Required** when the KI regenerates its inputs each
run (a value written before the run would be overwritten). In runner mode `address` is optional documentation.

### Runner-mode output contract (mandatory — else the run is rejected, not trusted)
`tools/calib_run.py` MUST emit, in its metrics JSON, a reserved block:
```json
{ "...metrics...": ..., "__kdt__": { "applied_params": { "<name>": <value>, ... } } }
```
- The kit DIFFS `requested` vs `applied_params` on EVERY eval; any mismatch/missing → that eval scores +inf
  (fail-closed: a silently-non-injecting runner is never trusted).
- Before optimization, the kit runs a one-time RESPONSIVENESS check (default vs perturbed vector): if the
  objective doesn't move, calibration aborts (`status: runner_unresponsive`) — proves the injected params
  actually reach the SCORED run, not just some file.

## Parameter ranges — split soft prior from hard limit
- `hard_bounds: [lo, hi]` — true physical/numerical limits (constrain the search).
- `prior` / `expected_sensitivity` (optional) — soft, from published site ranges; seeds + ranks, does NOT
  prune. Literature-supported params are ALWAYS in the pool; the rest get a cheap residual Morris screen —
  never silently excluded (literature is a PRIOR, not a pruning oracle).

## Provenance (mandatory, mirrors the validation-convention citation gate)
Each sensitive param and the holdout choice carries `cite` + `confidence`. Uncited → `low_confidence`
(stays screenable / flagged), never silently trusted.

## Holdout — the generalization AXIS, not just kind/fraction
`strategy.holdout` records: `protocol` (blocked_temporal | leave_region_out | blocked_space_time |
differential_split_sample …), `grouping_key`, `generalization_axis` (must match the promotion claim),
`fraction`, `rationale`, `cite`. Default per obs_shape: point_time_series → contiguous blocked temporal;
multi-site/panel claiming transfer → leave-region-out; gridded → spatial block; spatiotemporal → blocked
space-time on the claimed axis.
