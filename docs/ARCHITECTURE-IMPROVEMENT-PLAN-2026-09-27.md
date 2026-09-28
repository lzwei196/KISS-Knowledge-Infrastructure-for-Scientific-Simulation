# GeoForge Desktop: four-module improvement plan

- Date: 2026-09-27
- Baseline: mac-version at 96ac8a5b
- Status: C0 baseline and C1–C4 source implementation/local regression checks complete; C5 Mac build and frozen CLI smoke checks complete, with manual GUI/live-provider acceptance still pending.

C1 results and remaining limits are recorded in [ARCHITECTURE-M1-IMPLEMENTATION-2026-09-27.md](ARCHITECTURE-M1-IMPLEMENTATION-2026-09-27.md). This is not a compiled-app or live-server acceptance claim.

C2 results are recorded in [ARCHITECTURE-M2-IMPLEMENTATION-2026-09-27.md](ARCHITECTURE-M2-IMPLEMENTATION-2026-09-27.md). The final local suite passed 735 tests and 121 subtests, with five unavailable-server-reference skips.

C3 results are recorded in [ARCHITECTURE-M3-IMPLEMENTATION-2026-09-27.md](ARCHITECTURE-M3-IMPLEMENTATION-2026-09-27.md). Plan Review now owns issuance, answer preservation and signing order; the current approval screen is unchanged. The full local suite passed 757 tests and 121 subtests, with the same five server-reference skips.

C4 results are recorded in [ARCHITECTURE-M4-IMPLEMENTATION-2026-09-27.md](ARCHITECTURE-M4-IMPLEMENTATION-2026-09-27.md). The project panel, details and status button now use one read-only status projection. The full local suite passed 814 tests and 121 subtests, with the same five server-reference skips. Executable JavaScript tests are included; compiled/native GUI acceptance remains separate.

C5 build results are recorded in [ARCHITECTURE-MAC-BUILD-2026-09-27.md](ARCHITECTURE-MAC-BUILD-2026-09-27.md). The dated v0.6.54 Apple Silicon test bundle includes the current C1–C4 working tree. Frozen harness/Flow, calibration, module/source matching and signature checks passed. This is a local test build, not a release or a live scientific simulation acceptance result.

This plan turns the architecture walkthrough into a staged implementation. It deepens existing modules without replacing the accepted scientific flow, adding another approval step, or changing model science.

## 1. Agreed scope

| Module | Agreed change | Explicit limit |
|---|---|---|
| M1 — Acquired-input evidence | One interpretation of integrity, request matching and safe reuse | Exact-request reuse first; no automatic coverage-containment inference |
| M2 — Approved-step execution | One execution lifecycle used by direct-provider and CLI adapters | Report failures to the agent; no automatic host retries of scientific tools |
| M3 — Plan Review | Consolidate issuance, user-answer preservation and approval ordering | Preserve current approval behavior and review screen |
| M4 — Project status | Consistent interpretations based on existing observations | Deeper model-process tracking and streamed tool logs are a later stage |

The user explicitly confirmed the M2 retry choice and the M4 staging choice on 2026-09-27.

These are platform improvements, not new scientific workflows inside model KIs. KI usage instructions remain the harness's responsibility. Desktop collects consent; the shared Flow core records and checks it. An approved step belongs to an approved plan; it does not require a separate approval click for every execution attempt.

Terminology is recorded in the root CONTEXT.md. This plan contains implementation decisions and work items; the glossary does not.

## 2. Invariants to preserve

- One plan approval includes its selected data. No revived data-proposal popup.
- The approved plan and inventory are immutable during acquisition/execution; progress and receipts remain separate.
- GeoForge Database acquisition remains host-driven before scientific execution; retain existing permitted public-file behavior without expanding it.
- Shared Flow remains authoritative for stages, approval, tool policy and completion.
- File presence, valid acquisition evidence, scientific validation and source freshness remain distinct.
- No toy models, fabricated datasets or weakened scientific checks.
- No automatic overwriting or deletion of existing user inputs when evidence is missing.
- No new arbitrary agent-step or model-duration limits.
- Preserve provider-specific containment, capability isolation and honest enforcement labels.
- Production paths derive from the current project, selected KI and configured runtime; no developer-machine or server-only paths.
- No new network protocol or credentials are required for the initial consolidation.
- Shared ki_tools_common changes must remain coordinated with the server reference, not become a Desktop-only fork.

Design references: FLOW-TARGET-2026-09-17.md and the resolution section of FLOW-STEPS-1-3-REVIEW-2026-09-18.md. The current source takes precedence over historical progress notes: the three main status blocks already exist, and repaired approval/acquisition bugs must not be re-reported as open findings.

## 3. Delivery order and checkpoints

| Checkpoint | Work | Required result before continuing |
|---|---|---|
| C0 | Baseline and compatibility fixtures | Existing behavior characterized; failures and skips classified |
| C1 | M1 acquired-input evidence | All evidence consumers agree; safe reuse and refusal cases pass |
| C2 | M2 approved-step execution | Both adapters preserve common preconditions and outcome evidence |
| C3 | M3 Plan Review | Same user-visible approval behavior, including restart and re-review |
| C4 | M4 Project status | Main and detailed views use consistent, evidence-backed meanings |
| C5 | Integration and Mac build verification | Source and compiled-app checks reported separately |

M3 is conceptually independent of M2, but both touch orchestration code. Keep production edits sequential to reduce conflicts in flowrun.py and flowgate.py. Independent read-only reviews and isolated tests can run in parallel.

Keep each checkpoint reviewable. Separate characterization, consolidation and intentional behavior corrections so a regression can be traced to one change. Do not bundle unrelated KI-library, installer, KDT or Observatory work.

### C0 — Establish the baseline

1. Record HEAD, branch, tracked/untracked changes, interpreter and relevant dependency versions.
2. Run focused regressions in isolated temporary projects, using test credentials and fixtures rather than real provider accounts or user projects.
3. Preserve representative signed receipt, issued-review, answer-history and inventory fixtures.
4. Record expected failures, unavailable reference trees and sandbox-dependent tests separately; do not count skips as passes.
5. Before changing an interface, compare responsibilities and caller knowledge. Select a shape that actually hides ordering/interpretation rather than merely forwarding the old helper sequence.

The interface is the test surface. Keep useful integration tests. Replace implementation-coupled tests only after their behavioral scenarios are covered through the deeper module.

## 4. M1 — Acquired-input evidence

### Responsibility and seam

Deepen the existing shared receipt module around the evidence decision: whether recorded acquired files are intact and support the current selected request, and why.

Inspection must not silently create replacement receipts, authorize a different request or start a download. Receipt issuance/rebinding is an explicit host action after evidence supports it. Delivery-specific work remains with the served, subset and manual adapters.

This gives locality to trust/reuse rules and leverage to acquisition, execution permission, status and final verification. Deleting the module should force those rules back into its callers; otherwise the extraction has not added depth.

### Code targets

- ki_tools_common/ki_tools_common/flow/receipts.py
- kiss/kiss_cli/acquire.py: _receipt_for, _rebind_existing, _entries_valid
- kiss/kiss_cli/obs_subset.py: bind_approved
- kiss/kiss_cli/flowgate.py: check_step_tool
- kiss/kiss_cli/flowrun.py: plan_data_status

Keep request/manifest/native-file checks in obs_subset.py and data_contract.py. Do not absorb every downloader or scientific validator into the evidence module.

### Implementation sequence

1. Preserve existing reuse/tamper fixtures and add changed-requirement served-recovery cases.
2. Concentrate receipt verification, safe file checks, request matching and explanatory conclusions.
3. Migrate acquisition and subset binding, followed by execution permission, status and final evidence assessment.
4. Make renamed-input and missing-archive recovery consume the same evidence decision.
5. Remove duplicated raw receipt scans and private-helper composition from consumers after parity checks.

The current served recovery path can accept matching dataset-folder files without comparing the old and new requirements. Correct that path explicitly; do not disguise a behavior correction as a move-only refactor.

### Reuse and compatibility rules

| Case | Required behavior |
|---|---|
| Same selected request, unchanged files, new approval | Reuse without downloading again |
| Input renamed, request unchanged | Rebind only when equivalent source/scope can be established |
| Rename plus changed area, period, variables or source | No automatic exact-request reuse |
| Original archive missing, recorded extracted files intact | Recover only with valid selection evidence and safe paths; preserve recovery provenance |
| Files changed, missing or outside the permitted project | Refuse trusted reuse with an actionable explanation |
| Files present without supporting receipts | Do not invent provenance or overwrite them |
| Old data might cover a smaller new request | Compatibility is not established merely by apparent overlap |
| Unknown remote version | Keep source freshness unknown |
| Data acquired but not prepared/validated | Do not promote it to scientific readiness |

Legacy selection fingerprints include the item identifier, and some receipts do not store the original canonical selection. Where possible, compare the current candidate using the original recorded identifier against the signed fingerprint. If equivalence cannot be established, decline automatic rebinding rather than infer it from a directory name.

Do not re-sign old documents merely to fit a new shape. Any richer provenance should be additive and covered by old-reader/new-reader fixtures. A receipt without adequate scope evidence must not acquire fabricated scope/version facts.

### Tests and exit criteria

Cover exact reuse, rename alone, rename plus changed requirements, changed chosen source with an unchanged dataset ID, missing archive, tampered extracted files, escaped paths, forged/no receipts, removed items and subset mismatch.

Assert all consumers agree on evidence validity; approved inventory bytes remain unchanged; safe reuse causes no duplicate download; unknown evidence produces an explanation, not a scientific-validity claim.

## 5. M2 — Approved-step execution

### Responsibility and seam

Deepen one execution-attempt module: common preconditions, environment preparation, process outcome, evidence capture and receipt recording. Direct-provider and CLI adapters translate their caller formats through this real seam.

Leave setup, acquisition and conversational orchestration outside it. Shared Flow policy remains authoritative. Preserve provider-specific restrictions rather than pretending all providers have identical containment.

### Code targets

- kiss/kiss_cli/api.py: run_ki_tool handling
- kiss/kiss_cli/cli.py: cmd_run_tool
- kiss/kiss_cli/flowgate.py: step/tool checks, approved environment and record_tool_run
- Shared flow/tools.py, flow/policy.py and flow/receipts.py as existing authorities

### Characterize differences before migration

| Concern | Direct-provider adapter | CLI adapter |
|---|---|---|
| Approval and step checks | Shared FlowSession | Shared FlowSession |
| Tool forms | Python tools or declared model binaries | Also trusted shell/extensionless tools |
| Working directory | Selected project directory | Project root |
| Argument-root checks | Explicit | No equivalent adapter-level check |
| Environment | Sanitized; approved additions; provider proxy | Separately constructed sanitized/approved environment |
| Normal nonzero exit | Receipt through shared recorder | Receipt through shared recorder |
| Tool timeout | Existing 600-second default, capped at 3,600 | No corresponding tool timeout |
| Automatic scientific retry | None | None |

These are source-derived differences, not a conclusion that every difference is a defect.

### Implementation sequence

1. Capture both caller interfaces and their common invariants with local process fixtures.
2. Concentrate common lifecycle behavior without broadening tool/path permissions.
3. Migrate the direct adapter, retaining its response format and explicit settings.
4. Migrate the CLI adapter, retaining exit-code behavior, receipt marker and transport capability checks.
5. Delete duplicated choreography after cross-adapter regressions pass.

Preserve the existing adapter duration settings explicitly during extraction; do not accidentally inherit the direct adapter's limit in the CLI route or remove protections. Any subsequent duration-policy unification is a separate, visible change.

### Failure handling — agreed

Return a failed attempt and available diagnostics to the agent. The execution module does not automatically repeat scientific tools. The agent may request another permitted attempt; changes beyond the approved plan go through re-planning.

Conversation reconnect/replay is not an execution retry. Distinguish not launched, failed, timed out, interrupted and outcome unknown; none may become success merely because an agent reply completed.

### Tests and exit criteria

Test pre-approval refusal, missing acquisition evidence, KI/tool mismatch, changed approved tool, environment sanitization, successful execution, nonzero exit, launch failure, timeout/interruption and receipt-write failure.

Use small local processes for regression tests; label them fixtures, not real scientific-model runs. Both adapters must check approval before launch and preserve trustworthy outcome reporting afterward. Kimi containment remains honestly described; external shell activity without accepted evidence cannot establish project completion.

## 6. M3 — Plan Review

### Responsibility and seam

Deepen one Desktop Plan Review module around the issued display, answer preservation and consent-or-re-review outcome. The UI adapter displays the review and submits the response; it should not reconstruct approval invariants.

Keep shared flow.decisions and flow.approval as the canonical decision/signing implementation. This is consolidation of existing protections, not a new consent policy.

### Code targets

- kiss/kiss_cli/flowrun.py: approval portion of pre; _card; _issue_card; suggestion_baseline; shown_sha256; _issued_review; answer handling; decision_records
- kiss/kiss_cli/gui.py: approval-card routing
- kiss/kiss_cli/web/app.html: existing review payload and displayed-card echo
- ki_tools_common/ki_tools_common/flow/decisions.py and approval.py

### Implementation sequence

1. Preserve lifecycle scenarios for explicit choices, accepted recommendations, defaults and unresolved inputs.
2. Concentrate card issuance and its authoritative displayed snapshot; derive the baseline from the same rendered choices.
3. Concentrate answer identity, binding and preservation before any re-issued card.
4. Move the ordered consent transaction behind the module's interface.
5. Shrink the surrounding orchestration, then retire redundant helper-only test reconstruction.

Preserve this order: verify reviewed files/display → validate stored answers → apply and preserve genuine choices → refresh estimates → reissue unsigned if material changes require review → resolve provenance/open inputs → record decision revision → sign.

Host acquisition remains downstream of valid approval.

### Compatibility and exit criteria

Keep current persisted names/shapes, choice/item namespaces, displayed-card hashing and browser payload. Preserve numeric normalization across the browser round trip.

A valid issued card must survive restart. Changed or malformed cards must follow existing re-review behavior. Corrupt answer history must not silently become an empty history. Previous answers must survive a reissued card without transferring to unrelated items.

Keep current source/size refresh rules and tolerances. Regression tests and GUI checks must show the same approval behavior, with no extra popup or post-approval inventory mutation. Report unavailable server parity separately.

## 7. M4 — Project status

### Responsibility and seam

Deepen the interpretation of existing project facts into consistent status meanings, explanations and next actions. The browser adapter renders those conclusions instead of independently deriving readiness.

This is an in-process interpretation responsibility. Existing storage/acquisition/execution modules supply facts; Flow remains the stage/completion authority. Do not introduce another persistent state machine.

### Code targets

- kiss/kiss_cli/gui.py: _session_data and existing activity observations
- kiss/kiss_cli/flowrun.py: plan_data_status
- kiss/kiss_cli/projectrun.py: authoritative-stage and conversational-progress distinctions
- kiss/kiss_cli/web/app.html: renderData, main plan data, technical detail readiness and blocker precedence

### Implementation sequence

1. Define a behavior matrix from current Flow state, acquired-input evidence, execution outcomes, pending user requests and preparation facts.
2. Centralize status interpretation while preserving the existing three main blocks: Needs you, Data in this plan and Progress.
3. Make main and detailed views use the same meanings; keep useful technical evidence accessible.
4. Display observation source and age where already available.
5. Remove redundant browser/host readiness inference after rendering checks pass.

Keep poll-driven acquisition advancement working, but do not make the new status interpretation itself issue approvals, sign receipts or start downloads.

### Meaning rules

- File presence is weaker evidence than an intact, correctly bound acquisition receipt.
- Acquired data can still require model preparation and scientific checks.
- Agent-reported progress is not verified model execution.
- An agent heartbeat is not proof that the model child is progressing.
- A completed chat turn is not a completed scientific project.
- Missing/stale observation is unknown, not success.
- A user action, server wait and agent-permitted next action must be distinguishable.
- Quiet time may support a clearly labeled suspicion, not a confirmed “hung model” verdict.

### Stage limit — agreed

First use existing observations: acquisition bytes, agent/process activity, recent events/output and available execution evidence. Deeper model-child tracking, streamed tool logs and model-specific progress counters are deferred to a later stage with M2.

### Tests and exit criteria

Cover pending approval, manual file placement, remote acquisition wait/failure, present-but-unverified files, acquired-but-unvalidated data, failed/interrupted execution, idle chat with unfinished science, and completed verified output.

Main and detailed views must not disagree about the same evidence. Waiting actions remain reachable after panel close/reopen and restart. Status interpretation must not mutate evidence or change Flow state.

## 8. Verification plan

Commands below define the verification plan. C0–C4 executions and exact results are recorded in the checkpoint reports linked above; C5 remains planned. Run from the repository root with the configured project interpreter; python3 below denotes that interpreter, not a fixed installation path.

### Focused local suites

    PYTHONPATH=kiss:ki_tools_common python3 -m pytest --import-mode=importlib \
      ki_tools_common/tests/flow \
      kiss/tests/test_flowgate.py \
      kiss/tests/test_flowrun.py \
      kiss/tests/test_flow_cli_wrappers.py \
      kiss/tests/test_api_handoff.py \
      kiss/tests/test_obs_access.py \
      kiss/tests/test_obs_subset.py \
      kiss/tests/test_obs_describe.py \
      kiss/tests/test_data_contract.py -q

Use importlib mode to avoid test-package naming collisions when shared and Desktop tests run together.

### Broader regression checkpoint

    PYTHONPATH=kiss:ki_tools_common python3 -m pytest --import-mode=importlib \
      ki_tools_common/tests/flow kiss/tests -q

Record individual outcomes and environment-specific failures. If the server reference tree is absent, parity tests that skip do not establish server parity. Obtain that check before coordinated shared-core rollout.

### App-level checks

In a disposable project, after local regressions pass:

1. Create a real review through the GUI; inspect exactly what is shown.
2. Use a small CMFD subset and a small DEM subset, with request size checked before transfer; exercise a separate manual-placement fixture.
3. Approve through the intended user interaction, acquire files and verify recorded evidence against the actual files.
4. Restart/reopen and confirm safe reuse, unchanged consent and consistent status.
5. Change a request and confirm no unproven reuse or silent approval carry-over.
6. Modify a disposable test copy and confirm the evidence failure reaches status and execution permission.
7. Exercise both direct-provider and CLI execution routes; live DeepSeek/Kimi turns are a separate, explicitly identified check from local adapter fixtures.
8. Do not claim scientific model validation from small downloader tests or synthetic process fixtures.

Do not use a production user project for tampering/restart tests or quietly start large transfers. Record live provider use, dataset scope, bytes and outcomes separately.

### Compiled Mac check

After C1–C4 and source integration checks pass, build using the current Mac packaging recipe. Confirm the frozen app loads the intended harness and all required Flow modules, then repeat essential GUI checks in the actual build.

Source tests do not prove the compiled app works. This planning task does not build, replace the running app, publish a release or push Git branches.

## 9. Completion report and rollback discipline

For each checkpoint, report:

- Files changed and which duplicated caller knowledge was removed.
- Tests run, exact pass/fail/skip outcomes and unresolved environmental limits.
- Compatibility outcomes for old projects, receipts and review cards.
- Any intentional behavior change, separate from structural moves.
- Remaining gaps; no “all problems solved” statement without evidence.

Keep changes additive where persisted evidence is involved. Do not delete old signed records, source files, installed models or downloaded datasets as part of migration.

A rollback must not require rewriting user evidence. If a format change becomes unavoidable, stop before introducing it and review both upgrade and downgrade compatibility explicitly.

## 10. Immediate next checkpoint

C0–C4 source work is complete. Next is C5: integration and compiled Mac verification, with source, executable rendering, native GUI and live-provider results distinguished explicitly.

C1 deliberately preserves existing manual-placement issuance semantics: it signs what is present as a new manual acquisition. Unlike served-data recovery, this can re-sign existing placed bytes after a changed request. A fresh manual-placement confirmation/replacement policy remains an explicit follow-up, not a claim that exact-request recovery rules already cover every acquisition path.

C2 deliberately preserves shared final-evidence retry-history semantics: any bound failed historical run still blocks completion, even if a later permitted attempt passes. Defining explicit supersession without deleting history is a separate follow-up; no automatic retry or success promotion was introduced.

C3 preserves the current review UI and on-disk formats. It additionally refuses unshown/off-menu mutations and keeps a pending review on handled refresh failures. No cross-process transaction lock, crash-proof multi-file guarantee or compiled/live-provider acceptance is implied.

C4 removes stage-based readiness/completion claims, uses canonical pending requests and separates historical acquisition failures. Its in-memory metadata-invalidated evidence cache is presentation-only; execution gates remain fresh. Deeper model-child monitoring and the separate Observatory redesign remain outside this checkpoint.

Do not begin by splitting large files, rewriting all provider drivers or redesigning the UI. Success is less caller knowledge and consistent outcomes, not a higher module count.
