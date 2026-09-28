# Project inputs, parameters and path bindings

Date: 2026-09-27. Status: **design proposal; partial runtime/UI implementation followed on September 28**. See the [implementation checkpoint](PLANNER-IMPLEMENTATION-2026-09-28.md) for exactly what is implemented and tested. The full table/schema design below is not all implemented.

Scope: Desktop planning and project input handling, reusing shared KI Harness/Flow contracts. Source baseline is mac-version `bdf2522e` plus the previously documented uncommitted activity-display work, which this audit did not modify. No live conversation, approval, download, model installation or provider was changed.

Library-wide follow-up: [KI planning pre-evaluation](KI-LIBRARY-PLANNING-PRE-EVALUATION-2026-09-27.md) covers all 127 repository KIs, the saved local snapshot and imported ArchDam RDC. It clarifies that the existing agent-readable KI knowledge is valuable: the agent should author the case-specific five-link mapping, while Desktop preserves every KI-local requirement and checks actual bindings. Missing canonical vocabulary matches must not hide user inputs or force a KI rewrite. The regression checks below concern Desktop handoff correctness, not a new scientific validation of the model library.

## 1. Intended experience

The user describes a scientific task. GeoForge explains which inputs the selected KI probably needs, distinguishes environmental data from parameters and run settings, and shows how each requirement will be satisfied. The user can inspect the full list, accept applicable defaults, provide their own files or values, compare available data sources, or ask the agent about an individual requirement.

The table is not another plan or another approval system. It is the common view/editor of the current plan's input requirements and bindings. The agent, approval display and executing tools must resolve the same selections.

```text
Task + selected KI + enabled processes
                  ↓
Requirements: data / parameters / initial states / run settings
                  ↓
For each requirement: default, own input, dataset, or upstream output
                  ↓
One review: choices, scope, preparation steps, size and unresolved issues
                  ↓ approve
Acquire/import → inspect → prepare model files → validate → execute
                  ↑                                  |
                  └──── same input table + evidence ──┘
```

Planning can include inputs that a later approved preparation step will produce. A prepared file need not already exist to approve its production. Execution of its consuming step must wait for the required evidence.

## 2. What already exists, and what does not

| Concern | Evidence in current code | Assessment |
|---|---|---|
| A project folder for each conversation | `kiss/kiss_cli/sessions.py:176,205` creates input categories, runs, outputs and model workspaces | Reuse; do not add a second session-folder system |
| Project role paths and shared software | `gui.py:2300` maps project inputs/outputs and installed binaries/interpreters; `:2361` materializes KI working copies | Reuse, but repair per-KI isolation |
| Agent receives attachment paths | `sessions.py:777`, `gui.py:3174` hand actual project-relative attachment paths to the conversation | Useful, but not equivalent to binding them to model requirements |
| Per-input upload | `sessions.py:490`, `gui.py:1915` store files and return actual saved paths | Storage works; upload does not establish inventory bindings |
| KI requirement descriptions | Shared `flow/ki_inputs.py:539`, `flow/declared.py:42` read input declarations, formats, units and notes | Reuse while preserving applicability and provenance |
| Plans, selections and evidence | Shared `flow/contracts.py:89`, `flow/plan.py`, `flow/receipts.py`; Desktop `plan_review`, `acquire`, `project_status` | Keep as authorities rather than duplicating them |
| Per-project tool execution | `execution.py:80` checks step/tool/cwd and runs in the project; `flowgate.py:224` records evidence | Extend to resolve selected bindings, not just accept independently constructed paths |
| Optional DB lookup and clipping | `obs_access`, `obs_subset`, `data_contract` | Keep existing transport, native-schema discovery and clipping; correct selection/presentation |
| Input explanation and full-list foundations | `web/app.html:1763,1787` already asks/explains in the current project; preparation normalization and status rows exist | Reuse current-project action; do not reuse Observatory's new-session action |

### What “the harness already has it” means

`harness.contract(ki_path, …)` (`ki_harness.py:188`) supplies KI usage instructions and tool locations. It has no project-directory or input-binding argument. Desktop supplies the conversation directory, path configuration and execution context separately. Shared Flow supplies the planning and evidence rules.

Thus substantial plumbing already exists, but loading the harness does not itself guarantee that every value, file in a nested namelist, or model-specific output directory is bound to the current conversation.

The current web server remains **unverified**: the known `/mnt/disk1/Hydrocraft_server` reference is unavailable locally. A subsequent [historical web comparison](WEB-HARNESS-COMPARISON-2026-09-27.md) inspected the August 29 source snapshot at commit `fc33a448`. It confirms useful project-relative references and producer-to-consumer artifact handoffs, but not a complete universal input-binding table. That export excludes the frontend and is not confirmed to match today's deployment. Shared contracts distinguish web agent-driven acquisition from Desktop host-driven acquisition; we should share the input semantics, not assume both environments have the same filesystem.

## 3. Findings that constrain the design

### Reproduced using production functions in isolated temporary projects

1. **Multi-KI output-role leakage.** `_session_config` treats an existing global project output role as an override; `_session_workspace` overwrites that global configuration after each KI. Model B inherits Model A's output directory, and B's materialized KI text embeds it. Per-KI interpreters remain distinct, but global config ends with B's interpreter. The invocation consequences require an execution test; a real model failure was not claimed.
2. **Upload is not binding.** Uploading `weather data.csv` for `forcing` returns `inputs/user/forcing/weather_data.csv`, while `runs/data-inventory.json` and its empty `local_paths` remain unchanged.

Reproduction: `python3 /tmp/geoforge_path_binding_replay.py`. Repeated with identical normalized results; generated fixtures were removed automatically.

### Other code/evidence findings

- The upload handler resumes any waiting request (`gui.py:1932`, `setup.py:269`), without proving that this upload satisfies that request. Supplying a file must not implicitly resolve an unrelated question or approve a plan.
- The CMFD source-choice bug reproduces on old and new code: selected NASA is absent from the card's options, while CMFD candidates inherit whole-catalogue/manual sizes. See `issues/APEX-PLAN-AND-ACTIVITY-2026-09-27.md`.
- Preparation currently mixes scientific role and acquisition action. Calibrated coefficients can appear as automatically prepared data, and run switches as files the user must find (`preparation.py:172,188`).
- Normalization drops applicability and hides single-model format details (`preparation.py:224,249`; `app.html:1546`). MODFLOW6 GWT/SFR-only requirements must not become unconditional requirements.
- Sampled normalized declarations (APEX 21, VIC 48, CaMa 21, MODFLOW6 23) have no typed `default` or `valid_range` fields. Defaults may exist in prose or tools; their absence from these fields is not proof the KI has no defaults. Do not manufacture values or display an unverified default as ready.
- Some current review groups display only the first eight rows (`app.html:1105`). The complete declared list must remain accessible.
- APEX `.SOL` combines soil properties and initial water/nutrient state. VIC soil files mix derived fields, calibrated coefficients and defaults. CaMa roughness can be a scalar or a spatial override. File type cannot be used as the scientific role.
- Execution evidence discovers file arguments, not every dependency inside a configuration deck (`flowgate.py:257`). Arbitrary tools cannot be made path-correct by replacing text globally.
- Some KI tools write scenario content under shared software roots. CaMa's `configure_simulation.py` uses the installed root for maps, scripts and default outputs; its `calib_run.py` is explicitly a Jinghong-specific driver. These require scoped KI changes or an explicit unsupported-case report, not merely a different process cwd.

## 4. The proposed table

### Main presentation

Keep a short plan summary above one expandable, scrollable table. Default groups:

1. **Data** — forcing, spatial properties, observations and external boundary/initial data.
2. **Model parameters** — coefficients, parameter sets, lookup/default methods and calibration choices.
3. **Run settings and generated inputs** — period, enabled processes, initial-state method, input decks and upstream results.

These are presentation groups, not mutually exclusive file types. Show tagged child requirements under mixed input-file groups. Expose an “All declared inputs” view with applicable/optional/not-applicable/unknown labels, search and counts; no silent truncation. Missing KI declarations are shown as incomplete coverage, not a promise that every possible model parameter has been enumerated.

| Input | Type and purpose | Current selection | Preparation/readiness | File or value | Actions |
|---|---|---|---|---|---|
| Weather forcing | Data: weather variables required by the KI | CMFD / supported public provider / own files | Describe → estimate → download → convert | Planned destination, then actual files | Compare sources · Add files · Ask Agent |
| Soil profile | Mixed file: soil properties + initial state | KI-supported preparation or own profile | Inspect and map fields; retain unresolved slots | Actual `.SOL` or equivalent model deck | View expected fields · Replace · Ask Agent |
| Infiltration coefficient | Model parameter | Explicit KI default, user value or calibration | Show value, unit, origin and applicability | Scalar or bound field file | Change · View source · Ask Agent |
| River runoff | Generated data consumed by CaMa | Output from approved VIC step | Waiting for producer; then routing preparation | Produced runoff files | Inspect dependency · Ask Agent |
| Simulation period | Run setting | User-confirmed dates | Drives all related data requests | Typed dates, not a dummy file | Edit · Ask Agent |

All entries here illustrate presentation, not scientifically approved choices for the current APEX project.

### Data row expansion

- Always offer **Use my files** and supported non-DB sources; lack of a GeoForge DB key must not prevent planning.
- With a configured and authorized DB connection, show relevant accessible candidates below that requirement. Query by required quantities, study scope and applicable KI, not an unfiltered catalogue dump.
- Keep credentials host-side. An unavailable or unauthorized connection is a visible condition, not “no datasets exist.”
- For each candidate show native variables, units, coverage, preparation needs, acquisition route and project-scoped estimate. Whole-product size is separately labeled only when relevant.
- Distinguish discovery from a verified offer. No estimate yet means “estimate required,” not “manual download only.” Old-scope offers are labeled stale until re-estimated for the new request.
- Explain variable derivation/conversion explicitly. Catalogue presence does not prove model suitability; missing requested variables does not prove the entire dataset is unavailable.
- A supported external provider is a real typed source option, not a fake catalogue ID. Selected sources must exist in the displayed options. Source fallback never silently changes a user choice.

### Parameter row expansion

- Show effective value or parameter file, units, known constraints, default/method provenance, scope/applicability and consuming steps.
- Differentiate explicit numeric defaults, lookup-derived values, calibration estimates and model run switches.
- “KI can prepare this” means a planned preparation method, not an already resolved value. Missing/ambiguous defaults remain visible and go to agent/user clarification.
- Show large parameter sets or input decks as expandable tables. Preserve unsupported fields and original files; do not rewrite whole files with a generic text replacement.
- If a scalar and a file override are both available, show which one takes precedence and require one effective selection.

### Ask Agent and user interaction

Use the current project conversation. Include input ID, relevant KI declarations, current choice, actual binding paths, candidate evidence and the user's question. Explanation is read-only: it does not select, approve, download, overwrite or start a model. “Use this option” and “Help prepare this input” are explicit separate actions.

An explanatory message while a plan review is pending must not consume the review or authorize execution. Queue interaction safely during an active turn; do not race input changes against an executing tool. Source/scope/value changes outside the approved plan require a new review. Calibration trials within approved parameter bounds and the approved calibration protocol do not require another approval for every trial; changed bounds, method or out-of-contract overrides do.

Candidate discovery and estimates run asynchronously with per-row progress and clear failures. Reading the table does not repeatedly start queries, downloads or approvals. Changing a request supersedes its old response; a late estimate cannot overwrite a newer selection. Requirements depend on the task: observation data needed for a calibration/validation objective must not become an unconditional download for a simulation that does not use that objective.

## 5. Input records: separate scientific meaning from storage

Evolve existing inventory items rather than replacing `runs/data-inventory.json`. The following are proposed concepts, not a finalized serialization schema:

| Concept | Information to retain |
|---|---|
| Requirement | Stable ID, display name, scientific role, required/optional/applicable status, KI/step consumers, units, format/shape, scope, declaration provenance |
| Selection | Typed source or value; user/default/derived/calibrated provenance; applicable default evidence; selected candidate; revision |
| Artifact binding | Actual project-relative file(s), file-set members or typed value; raw/prepared role; origin; integrity evidence; exact requirement(s) satisfied |
| Preparation | Approved producer/preparation step, transformation, expected outputs, model config field/argument that consumes them |
| Evidence | Acquired/present, inspected, prepared and scientifically validated remain distinct; unresolved reasons stay visible |

One artifact can satisfy multiple requirements; one requirement can need many files. Merging across KIs requires compatible variables, units, scope and preparation contracts—not merely the same label or canonical quantity. VIC runoff remains connected to its CaMa consumer as an explicit producer dependency.

Preserve the legacy `local_paths` read interface during migration, but do not treat agent-written path strings as verified bindings. Surface ambiguity instead of guessing.

## 6. Path rules

1. **Project-owned inputs/results live in the project; installed software remains shared.** User files belong to the project, not to the shared KI installation or generated KI source directory.
2. **Store owned paths relative to the project.** Resolve them to canonical absolute paths at runtime, using the current project and actual step KI. Reject escaping paths/symlinks and unsupported permissions consistently.
3. **Resolve model configuration per step KI.** A per-project global config must not choose another KI's interpreter or output root. Retain intentionally shared data explicitly; never inherit model-private outputs as generic overrides.
4. **Retain existing input categories.** Imported files can continue under `inputs/user/<input-id>/`; downloads retain their existing safe locations. New prepared files/work decks get explicit per-run/per-KI directories rather than changing every old project layout.
5. **Bind the returned saved path, not the proposed filename.** Handle sanitization, collisions, directories, multi-file formats and replacements without overwriting unrelated user files.
6. **Separate raw inputs from prepared inputs.** Preserve originals; record preparation lineage and the exact file the model will consume. Changes invalidate dependent preparation/validation evidence as appropriate.
7. **A remote dataset path is not a local file.** A server estimate/job/result becomes a local binding only after download/import and file verification. Never pass `/mnt/...` server paths to a Desktop model.
8. **External files are explicit.** Recommend copying/importing into the project by default. An optional read-only external reference for large inputs needs an explicit binding, user grant, existence/change checks and consistent CLI/API support; if unsupported, explain that and offer import. No global disk search or silent copying.
9. **Use KI-aware writers for model decks.** The resolver provides exact input references; the KI preparation tool writes the appropriate control files. Nested file dependencies must be inspected/declared before calling a model. Unsupported writers remain a visible blocker.
10. **Restart is not relocation.** Preserve current restart behavior. Moving a project requires relinking owned/external paths and rechecking evidence; do not claim arbitrary portability while legacy absolute paths remain.

Illustrative incremental layout (not a migration of existing folders):

```text
project/
  runs/plan.json                    approved scientific selections
  runs/data-inventory.json          requirements and planned selections
  runs/approval.json                signed approval
  runs/plan-review.json             persisted issued review
  inputs/user/<input-id>/           imported originals
  inputs/...                       existing downloads/forcing/static layout
  runs/<run-id>/work/<KI>/          prepared model deck and run-specific config
  models/<KI>/ki/                   generated KI working copy, not user inputs
  models/<KI>/kiss.toml             KI-specific software/role configuration
  outputs/<KI>/<run-id>/            run results
  .geoforge/                       acquisition state, receipts and saved user answers
```

## 7. Ownership and module interface

Prefer one project-input module with a small interface for:

- **view**: requirement/selection/binding/evidence projection used by UI and agent;
- **select**: edit a draft source/value choice and determine the affected dependencies;
- **supply**: import/register actual files for a requirement, returning their exact bindings;
- **resolve for step**: produce the approved KI-specific runtime input mapping or actionable unresolved reasons.

Names are provisional. The depth comes from hiding the currently scattered matching, path and evidence rules, not from wrapping existing helpers one by one.

Ownership:

- Shared KI/Flow: scientific declarations, common input semantics, validity/approval/evidence rules.
- Desktop: credentialed DB transport, file picker/import, local path resolution, UI and provider adapters.
- KI tools: scientific conversion, parameterization, model-specific config writing and validation.
- Harness: gives the agent the same project input view and required discipline; it is not a second path registry.

Reuse approved inventory + acquisition/execution receipts and their host-owned progress records. If binding metadata must be added, extend those owning records deliberately; do not introduce an independently editable `paths.json` that can diverge from the approved plan. Actual post-approval files/progress must not silently rewrite the signed inventory.

The owned remote DB gets the existing HTTP adapter plus fixture adapter in tests. Filesystem and local KI processes are tested in temporary projects. No new generic backend protocol is required just to bind Desktop inputs; missing metadata is reported rather than inferred.

## 8. Implementation checkpoints and exit tests

### P0 — Lock down the observed failures

Add red tests for the actual seams: old/current CMFD candidate display, NASA selected-but-not-offered, uploaded filename binding, multi-KI config isolation, mixed input-file roles, dropped applicability and hidden formats. Preserve unrelated dirty activity work.

### P1 — Correct project/KI paths and file bindings

Fix global/per-KI config ownership; ensure executor selects the actual step's config. Add host-owned import/bind behavior and stop unrelated upload→request-resume. Return exact bound paths to both agent adapters. Keep user files intact.

Exit tests: two fake KIs with different interpreters/output roots, two projects in parallel, upload collisions, Unicode/spaces, path escape/symlink refusal, missing/replaced files, restart, upload during unrelated review. These are infrastructure fixtures, not successful scientific simulation claims.

### P2 — Preserve and normalize requirement semantics

Retain role, representation, applicability, units, format and evidence-backed defaults. Expand formerly hidden internal parameters. Support mixed decks and scalar/file override precedence; keep unknowns explicit. Add backward-compatible inventory/schema handling and server compatibility fixtures before changing shared contracts.

Exit cases: APEX soil/initial-state deck; VIC calibrated vs derived fields; CaMa scalar roughness vs spatial override and upstream runoff; MODFLOW6 groundwater-only versus GWT/SFR applicability. Confirm no false “default ready” labels.

### P3 — Unify source selection and scoped offers

Use one candidate representation for DB, supported public providers, user files and upstream outputs. Enforce selected-option membership. Show current-scope estimates, re-estimate changed scope, preserve user selections and expose partial/unknown coverage honestly.

Exit cases: no DB credentials; expired credentials; offline cached catalogue; valid CMFD clip; incomplete variables; changed bbox/years; NASA as a displayed source; manual-only delivery; own files with no DB. No automatic source switching or accidental download before consent.

### P4 — Deliver the table and same-project explanations

Unify the existing fragmented views, preserving full input lists and simple summaries. Expand dataset choices under their requirement and parameter sets under their file group. Keep add/replace/inspect actions available after a file is supplied. Paths and status are from the common projection.

Test actual DOM events and endpoints: scrolling/all rows, comparison choice, exact imported path, inline explanation in same session, no approval consumption by chat, keyboard focus/accessibility, pending-turn interaction and stale-review rejection.

### P5 — Connect preparation and execution end to end

Resolve approved bindings at the execution seam, route them through KI-specific config writers and verify nested input references/expected outputs. Inspect tools that write scenario files into shared installation directories; fix supported paths or report unsupported scenarios explicitly.

Exit tests: user-supplied APEX input deck; a VIC→CaMa path/config coupling fixture; one process-conditional KI; model-specific default versus user override. Then staged compiled Mac tests using both Kimi CLI and DeepSeek API, starting with small real data requests and explicit scientific scope. Report download, preparation and scientific execution outcomes separately.

## 9. Recommendations and remaining decisions

- **Recommended:** default to project-owned imported inputs; offer external references only with explicit permission and fully shared resolution rules.
- **Recommended:** Ask Agent remains in this project, with the row's context attached; it does not create a disconnected conversation.
- **Recommended:** parameters remain inspectable, with only missing or scientifically consequential choices expanded initially. Do not force the user to answer every model coefficient individually.
- **Recommended:** deliver P0/P1 first, then P2/P3, then the table. A visual redesign on top of unbound files and cross-KI paths would conceal the underlying problem.
- **Optional server comparison:** request a redacted example of one web chat's input manifest, project layout, prepared model config, and launch command/cwd/env. This can validate semantic parity; access to all web source or user accounts is not required to start the Desktop fixes.

Not in this proposal: automatically migrating every existing project, changing calibrated science, replacing KI tools, imposing new agent-step limits, silently switching providers, or introducing a new approval popup.
