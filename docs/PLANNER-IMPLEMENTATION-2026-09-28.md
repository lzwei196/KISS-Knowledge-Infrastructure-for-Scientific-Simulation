# Desktop planner: implementation checkpoint

Date: 2026-09-28. Working branch: `mac-version`.

This is a source-development checkpoint, **not a release qualification or a claim that all KIs have completed real model runs**. No new planner schema or substitute scientific planner was introduced.

## Intended flow and ownership

```text
Selected KI + user goal
          ↓
Shared KI planning contract: inspect SKILL, DAG, tools, A2A/coupling knowledge
          ↓
One unresolved decision → user answer → retain answer → next decision
          ↓
Settled plan + input inventory → Desktop review → explicit user approval
          ↓
Data acquisition: obtain the selected raw files
          ↓
KI execution: inspect/convert data, prepare parameter/config files, run model
```

The KI supplies scientific requirements, supported defaults and actual preparation tools. Shared Flow supplies planning instructions, plan/inventory validation, state and evidence contracts. Desktop owns question cards, project directories, approval, download coordination and provider transport. Merely loading the narrow KI harness does not implement those host responsibilities.

The existing five-link model remains: requirement → selected source/value → actual or planned files → preparation step → consuming KI step. Proposed scalar values remain in existing scientific choices; an invented file must not be used to make a scalar appear ready.

## Implemented in this checkpoint

### Sequential planning, without premature approval

- The shared planning prompt asks one unresolved decision at a time. It preserves previous answers and requires KI evidence for a proposed default. It treats a critical parameter set as one inspectable decision, not a question for every coefficient.
- During the interview, the conversation and host question/answer records retain progress. The agent is instructed to read only the references needed for the current question and to defer full plan/inventory serialization until the decisions are settled. This removes repeated full-draft rewrites between questions; it does not automatically turn an answer into a validated model input.
- An unanswered question blocks final review even if both draft JSON files were saved. Interrupted providers preserve the question and worktree drafts.
- API and native CLI planners have a real question-card handoff. The native launcher calls the running Desktop, not a second app executable.
- Native question writes use a distinct project-bound capability. They cannot create a question in another chat by changing the claimed working directory, approve a plan, or grant filesystem/network permission.
- Kimi/Codex planning worktrees also support a bounded, turn-bound question outbox when the loopback helper is inaccessible. The host reads it from the exact owned worktree, validates it, and creates the card. Old question files are not carried into the next worktree. This fallback does not add an intake write permission or broadly enable network access.
- User choice cards preserve more than eight candidates and offer a custom answer/file-location choice. No default is automatically submitted. “Ask about these choices” is clarification, not consent; invalid/stale answer metadata cannot resume the question.
- The review's first eight input rows remain compact, but all remaining rows are expandable rather than hidden behind a count.
- Desktop status now distinguishes planning, raw-data acquisition, and KI execution. Waiting questions retain their actual options in project status. The shared web display-state mapping is unchanged.

### Dataset discovery and truthful review

- Ordinary catalogue search uses the existing populated local cache immediately. It does not synchronously refresh the server or touch Keychain merely because the cache is old.
- Explicit refresh still refreshes; an absent cache retains the first-fetch path. Snapshot mode can reuse existing project metadata.
- Results expose freshness, last-refresh errors, pagination and catalogue incompleteness. Cached metadata does not prove current authorization, native variable names, or model suitability.
- Live describe/estimate and approved acquisition remain separate; their checks were not bypassed.
- A selected, stamped CMFD subset now displays its project-specific size and period in the source-choice card. Unestimated alternatives are not presented as verified project clips. Changed scope still has to pass the existing estimate/stamp checks.

### Project paths and user files

- Each selected KI has an exact `models/<KI>/kiss.toml`; the neutral project config is not the interpreter/binary authority for all KIs.
- Execution selects the requested KI's runtime, software location and roles, including CLI/API callers and child `P()` resolution. Project cwd remains the conversation directory.
- Existing project-local overrides are retained. Ambiguous legacy cross-KI output ownership is surfaced instead of silently migrated. Custom root roles are not discarded during normalization.
- Materialization rejects existing destination symlinks before copying; this is existing-alias protection, not a claim of a race-resistant filesystem sandbox.
- Uploads use exclusive storage and disclose the actual returned project-relative path. They do not silently bind an input, validate a file, answer an unrelated popup, approve a plan or start the agent.

## Verification and what the tests mean

Automated tests cross the production handoffs: serialized native helper → Desktop handler → persisted question → end-of-turn gate; real reply handler → recorded answer; actual shipped picker JavaScript → explicit action; actual child interpreter → model-specific path discovery. Separate tests exercise plan review, cache-first search, stamped subset presentation, uploads and legacy configuration migration.

These tests answer concrete platform questions: “Did a draft skip an unanswered question?”, “Did choosing a value accidentally approve execution?”, “Did a CMFD clip inherit a whole-product size?”, and “Did model B use model A's output folder?” They do not repeat the server's scientific validation of every KI.

Final verification of this source checkpoint:

- Desktop suite: **1,009 passed, 1 skipped, 123 subtests passed** in 147.13 seconds, after the final interview-prompt correction. Localhost tests were run with sandbox escalation rather than skipped.
- Shared Flow suite: **131 passed, 4 skipped**. The interpreter reported an existing NumPy/NetCDF ABI-size warning; no scientific acceptance is inferred from this test result.
- Picker/review JavaScript suite, including the subsequently added all-inputs expansion test: **17 passed**. This executes the shipped JavaScript with a minimal DOM fixture, not a visual-layout test.
- Actual Kimi CLI was tested through isolated source-app HTTP sessions with public APEX and a synthetic Harbin-maize goal, database off. The sequence and limitations are recorded below; it was **not a complete plan or model run**.
- The initial broader smoke proposal was blocked before launch because it would share the cached local catalogue with Kimi. The narrower tests did not read or transmit the user's catalogue or existing project data. Live GeoForge DB choice behavior was therefore **not tested**.

### Real Kimi interview regression

| Test | Observed outcome | Resulting correction |
|---|---|---|
| First-question smoke | Real waiting simulation-period card at about 176 seconds; test completed at about 178 seconds. | Prioritize the current question, distinguish example-site defaults from project validation, and correct Desktop planning status. |
| First custom-answer transition | First question at 71.838 seconds. The explicit 2003–2005 custom answer was accepted, but the next question did not arrive within 180 seconds. The agent rewrote 20,862 bytes of full plan/inventory first. | Explicitly defer full-draft serialization until the interview is settled, on every turn. |
| Targeted repeat | First question at 69.126 seconds; custom answer accepted; a different next question, “Maize management schedule,” at 42.692 seconds. Second turn exited naturally with code 0 at 46.917 seconds. | Interview sequencing regression passed. No full-draft writes appeared, and both drafts' hashes remained unchanged across host and worktrees. |

The latest first turn was test-stopped after a 12-second post-card allowance before sending the answer; only the second turn is verified to have finished naturally. The second question retained the chosen period and described transferred example parameters as an unvalidated proposal. However, the first card still spoke prematurely of CMFD as the selected source and called the transplanted example a “verified path.” **Scientifically grounded recommendations and current data availability are not certified by this test.**

All three tests used temporary project/settings/helper/Flow state, normal Kimi login, and public inputs. No approval, acquisition, installation or simulation was requested. No approval/download/receipt artifacts appeared. The tests exercised actual Desktop session/chat/provider handlers, not browser interaction. Production source hashes were unchanged during the runs; the latest evidence matches the current five watched production files. These are bounded reproductions, not provider performance benchmarks.

Local evidence (temporary, not release artifacts): `/private/tmp/geoforge-kimi-planner-smoke.XaL6Yw`, `/private/tmp/geoforge-kimi-twoquestion.YPu0oK`, and `/private/tmp/geoforge-kimi-interview.0rF4Af`. Each retains its report and structured evidence; the final directory contains `RESULT.md`, `evidence.json`, and timestamped turn records.

The shared suite must be run separately from Desktop tests (test-package naming collides), with both `kiss` and `ki_tools_common` on `PYTHONPATH` and isolated `GEOFORGE_FLOW_REGISTRY` / `GEOFORGE_FLOW_KEYS`. A preliminary command omitted those settings and failed environmental imports/registry checks; the correctly configured run above passed.

## Remaining limits before claiming the whole design is finished

1. **The general input/parameter binding table remains incremental work.** This checkpoint reuses the existing inventory and choices. It does not introduce a universal scalar/input-deck editor or automatically bind every uploaded file into every KI config.
2. **Strict three-phase acquisition is not yet universal.** GeoForge catalogue/manual/subset inputs are host-acquired before execution. Public non-catalogue URLs still have the older permitted `fetch_data` execution route. Generalizing that route requires an explicit approved acquisition request, not merely moving a UI label or disabling a working provider.
3. **Preprocessing and simulation share execution state.** Approved preparation tools run with execution receipts, but there is not yet a separate universal model-input-readiness stage or a host scheduler enforcing every producer/consumer dependency.
4. **Provider behavior needs full live acceptance.** The two-question Kimi transition is not a complete interview, final-plan review, acquisition or simulation. Scientific recommendation quality still needs checks, particularly example-to-project transfer and premature source selection. Native Codex/Claude and API-provider behavior have deterministic transport coverage, not equivalent live acceptance. Browser interaction/layout was not verified by the HTTP tests.
5. **Current web implementation is not fully available.** The comparison used the historical August 29 web-harness export, commit `fc33a448`, not a verified copy of today's deployment. No private snapshot or live server credentials are included in this checkpoint.
6. **A2A semantics remain grounded in existing KI declarations.** No new universal variable dictionary was invented. Missing mappings/default evidence remain explicit rather than being treated as a failed model or silently omitted.

## Next acceptance checks before a stable push

1. Complete a public-input interview through the final plan review. Check that every user answer, selected source, raw file, preparation step and consuming KI step remains consistent; do not accept a plausible conversation as proof of a correct saved plan.
2. With authorization to share the local catalogue with the chosen provider, verify relevant cached GeoForge DB alternatives, a custom local-file choice, and a CMFD subset choice. Require source selection before describing an option as selected.
3. Approve only a synthetic test plan and verify its acquisition scope and receipts. Check that no download happens during the interview and that acquired files are not labeled scientifically ready merely because they exist.
4. Finish the non-catalogue public-download adaptation, including approved-request matching and the user's proxy configuration, before claiming all sources follow the same three phases.
5. Exercise the browser cards and a rebuilt app. These source-app HTTP/provider and JavaScript-fixture checks do not qualify a compiled release by themselves.

## Main source map

| Area | Files |
|---|---|
| Shared planning instructions and provider tool policy | `ki_tools_common/ki_tools_common/flow/contracts.py`, `flow/policy.py` |
| Question/final-plan orchestration, status and native handoff | `kiss/kiss_cli/flowrun.py`, `api.py`, `cli.py`, `gui.py`, `setup.py`, `projectrun.py`, `project_status.py` |
| Per-KI project runtime and safe materialization | `project_paths.py`, `execution.py`, `paths.py`, `port.py` |
| Cached discovery and subset review facts | `obs_access.py`, `plan_review.py` |
| Upload storage and user-visible picker/review | `sessions.py`, `web/app.html` |

Related design: [Project inputs and paths](PROJECT-INPUTS-AND-PATHS-PLAN-2026-09-27.md). Library census: [KI planning pre-evaluation](KI-LIBRARY-PLANNING-PRE-EVALUATION-2026-09-27.md). Historical comparison: [Web harness comparison](WEB-HARNESS-COMPARISON-2026-09-27.md).
