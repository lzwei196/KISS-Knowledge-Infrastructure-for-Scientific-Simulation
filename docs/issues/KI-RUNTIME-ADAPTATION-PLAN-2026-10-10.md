# KI runtime adaptation implementation plan

Date: 2026-10-10
Status (updated 2026-10-11): Independently reviewed local implementation covers T1/T1b, T2a/T2b1, runtime resolution before KI materialization, private preflight scratch, exact project verification, stable helper identity, per-KI verification identity and bounded portable adaptation reuse. A separate published-package acceptance profile for official updates is implemented; authoring/edit gates remain unchanged. T2b2, runtime-content attestation, recipe-changing adaptation reconciliation, execution backends and the full update/model acceptance matrix remain pending. Verification evidence and precise limits appear below. No push or release was made.

GeoForge must install and verify a KI against an explicit local runtime, and repeat the relevant adaptation when an upstream KI or shared tool changes. The scientific KI remains versioned and protected. Windows native, Windows with WSL, macOS and Linux use the same lifecycle with different execution backends.

## Baseline and evidence

The working checkout is `D:/GeoForge-KI-Prepared-Inputs-20261004`, branch `codex/ki-prepared-inputs`. The previous test round left a local installation-location cache fix in `kiss/kiss_cli/gui.py` and `kiss/tests/test_gui_install_location_refresh.py`; 28 focused tests passed then. It is not deployed, committed or released. Preserve that work.

The GUI test report is `D:/GeoForge-Model-Tests-20261009/gui-test-report.json`. DSSAT compiled and started but preflight generated files inside the protected KI. WOFOST has an installed PCSE runtime but its KI expects incompatible paths and Python assumptions. WRF-Hydro has a complete case and WSL prerequisites, but no supported end-to-end WSL binding was established. None of these three tests completed a fresh scientific simulation.

Current source already contains OS/architecture manifests, role-based paths, shared-tool pinning, real preflight/import/executable checks, integrity gates, three-reviewer/KDT repair, verification invalidation, and a process supervisor. The work connects and extends those mechanisms rather than replacing them.

The earlier GUI used an existing development server whose exact loaded source revision was not established. Source findings and observed test failures are recorded separately. That server was stopped to contain a repeated setup scan; the installed desktop instances were preserved.

### Historical DSSAT regression confirmed on 2026-10-10

The user recalls DSSAT as an early successful Mac end-to-end case. A source-history audit found a concrete lost desktop adaptation, beyond the previously identified generic update-lifecycle risk:

- Mac 0.6.9 work imported by `aafad9f` / `aeffbe4` on 2026-08-20 explicitly made the China cultivar directory optional during installation verification.
- Canonical KI refresh `6c18863` on 2026-08-26 replaced that preflight with a structured `PREFLIGHT_REPORT` implementation. It made the China directory and four China cultivar files critical again, and added a no-argument native startup probe using `cwd=KI_DIR`.
- The preflight in the actual October 9 test snapshot (`e3ed93f067f2f2693294d0ff5d1f98ad`) has Git blob hash `b0aa4c20a7c247a073eb73f318990c1faea7739f`, exactly matching the August 26 replacement, current checkout and inspected Mac remote-tracking ref. These changes match the missing-cultivar and protected-KI-output blockers recorded in the October 9 GUI test.
- Not all earlier fixes were lost: the bundled generic soil profile and weather-field overflow fix from Mac 0.6.16 (`f1c61a5` / `b680202`, 2026-08-21) remain in the current reference runner; those two files have no diff against that revision in the current checkout.

An independent reviewer confirmed the history and unchanged preflight hash through later refreshes. The original successful Mac E2E run's raw outputs were not located in the tracked material examined; no historical run was reproduced. This confirms changed installation-preflight behavior matching the recent blockers, not every proposed cause of the failures or a later physical overwrite of an individual user's repaired installation. The user clarified that the assets are mandatory: preserve that requirement and audit their delivery before proposing a repair. Do not restore the old optional classification merely to pass installation. T4 retains the structured report contract and moves startup side effects out of the KI; missing mandatory assets require corrected packaging or acquisition. T5 must retain this update-regression case in its acceptance matrix.

## Invariants

1. One runtime configuration must identify the interpreter, model engine, shared tools, target OS/backend and path roles used by preparation, verification and execution.
2. Configuration selection cannot silently weaken engine versions, Python requirements, input requirements, scientific checks or result readers.
3. Upstream KI bytes, reviewed compatibility changes and machine-local configuration have separate identities. Every KI code/recipe/requirement edit uses the existing KDT adoption gate and three independent reviews where required by this workflow.
4. Deterministic binding is restricted to declared configuration. Arbitrary replacement code outside the KI is still an executable change and cannot bypass review by being called configuration.
5. Failed or cancelled attempts never retain a ready result. Inspection, failure reporting and cancellation remain possible when execution is blocked.
6. Installation/startup, reference-case success, project completion and scientific evaluation remain separate claims.
7. Existing working projects and installations must not be silently overwritten by a new KI or shared dependency. Adoption/rollback is explicit and evidence-preserving.
8. API and CLI providers use the same host-enforced final verification and job lifecycle. A provider's statement is not a verification result.

## Current call path

- `gui.Handler._stream_agent_setup` resolves the installation root and calls `setup.prepare`.
- `setup.prepare` loads `kiss.toml`, resolves Python/shared tools, materializes path tokens, protects the KI working copy and writes provider instructions.
- Normal setup tries preflight immediately. If it passes current manifest requirements, setup returns without an agent turn.
- Otherwise the API/CLI agent diagnoses the failure. `run_builtin_setup` is an optional tool.
- `_run_install` resolves Python and prepares the paired shared tools before materializing the KI, then prepares dependencies, acquires the engine, checks data/requirements and runs preflight in private scratch. Acquisition and preflight are skipped when their prerequisite stages fail.
- Normal agent setup finishes at `_record_agent_preflight`; installation-only setup instead reloads saved configuration and runs a startup/import probe.
- Library updates compose platform guidance and validate immutable package snapshots. They do not install model runtimes or execute universal reference cases.

## Delivery method

Each slice starts with a reproducible failure or a precise missing contract, receives independent review, implements one connected behavior, and finishes with focused automated evidence. A slice can be complete in source while deployment and model acceptance remain pending; those statuses must not be conflated.

For each slice retain: changed behavior, failing-before evidence, passing-after evidence, reviewer findings and dispositions, remaining limitations, and rollback boundary. Do not release or bulk update KIs merely to demonstrate a source change.

## T1 Saved runtime reaches final verification

Status: Complete in local source; two independent code reviews approved with no blocking findings. Not deployed or released.

Problem: `_installation_config_after_setup` reloads the saved environment for installation-only tests. Normal setup can retain the configuration object created before the agent installs or selects a replacement environment. Its final preflight, manifest checks and installation record can consequently use stale runtime values.

Change:

- Reuse the existing configuration loader at the normal final verification boundary.
- Validate the saved workspace identity against the workspace being verified.
- Use the same reloaded configuration for preflight, declared requirements and persisted installation evidence.
- A missing, malformed or relocated configuration fails closed and clears previous success through the normal status writer.
- A supplied early preflight result must not certify a different saved configuration. Reuse only when the relevant binding is unchanged, otherwise rerun the check.
- Preserve KI integrity checks, current snapshot requirements and cancellation checks.

Acceptance:

- A setup provider saves a different interpreter/environment; the normal final verifier uses it rather than the original object.
- Preflight, requirement checks and installation record agree on the selected runtime.
- Missing/malformed configuration and changed workspace root cannot retain `ok`, `verified_at` or `verification_identity`.
- Unchanged configuration preserves the early verified fast path without unnecessary duplicate preflight.
- Failed native preflight, changed KI digest and unmet manifest requirements still block readiness.
- Exercise the common final boundary used after both API and CLI setup without external LLM calls or model downloads.

Non-goals: This slice does not rebind already embedded KI path literals, solve environment selection before materialization, introduce WSL, modify model KIs, run model simulations or publish a release.

Implementation evidence:

- The exact workspace's saved configuration is read and validated at `_record_agent_preflight`. The loaded object is used for preflight, snapshot requirements and the installation record. A changed interpreter, path role or relocation setting invalidates an earlier supplied check.
- Missing, malformed or redirected configuration cannot fall back to the previous in-memory runtime. It clears saved success and revokes an existing installation receipt without recording a replacement binding.
- The initial 21-case regression reproduced the bug before the fix: **16 failed, 5 passed**. Five additional cases were subsequently added, making 26 new regression cases.
- After the fix, **57 focused tests passed**: 56 in the combined suite below and one existing saved-verification-state regression. These include both API and CLI completion paths and a real harmless Python preflight subprocess using the saved interpreter. That subprocess left the KI digest unchanged.
- Both independent reviewers inspected the source and test changes and found no blocking issues. Reviewers did not independently rerun the tests. `git diff --check` passed.

Validation commands (PowerShell, working directory `D:/GeoForge-KI-Prepared-Inputs-20261004/kiss`):

```powershell
# Before implementation: 16 failed, 5 passed.
& 'D:/GeoForge-Release-0.6.57/build-env/Scripts/python.exe' -m pytest tests/test_setup_final_runtime.py -q --tb=short

# After implementation: 56 passed.
& 'D:/GeoForge-Release-0.6.57/build-env/Scripts/python.exe' -m pytest tests/test_setup_final_runtime.py tests/test_setup_config_reload.py tests/test_snapshot_verification.py tests/test_project_setup_handoff.py tests/test_gui_install_location_refresh.py tests/test_runtime.py::InstallLocationTests -q --tb=short

# After implementation: 1 passed, 256 deselected.
& 'D:/GeoForge-Release-0.6.57/build-env/Scripts/python.exe' -m pytest tests/test_runtime.py -k test_agent_final_preflight_becomes_the_saved_verification_state -q --tb=short
```

Rollback boundary: the strict final configuration reload, binding-aware preflight reuse and installation-receipt invalidation are one source change. Preserve the earlier request-local installation-location cache fix if reverting T1. No KI package, runtime installation or user project was migrated by this slice.

Remaining limits: installed GUI build verification and model acceptance are pending; no new scientific model run, commit, push or release was performed. Concurrent configuration edits during verification and interruption recovery remain supervision work. T3 should centralize strict configuration parsing with the general configuration parser to avoid future divergence.

## T1b Invalidate verification when saved runtime bindings change

Status: Complete in local source; two independent code reviews approved after their findings were fixed. Not deployed or released.

The user's follow-up requires stable resolved paths after verification. The existing source and snapshot guards do not compare the saved runtime configuration with the one that passed. Add a versioned, deterministic fingerprint of workspace root, selected Python launcher, every path role and relocation mode to successful verification evidence. Parse values rather than hashing TOML formatting; preserve launcher and role symlink spelling.

Every KI follows the same GUI readiness gate, including bundled and imported packages: missing fingerprint, missing/invalid configuration or changed bindings requires re-verification. Preserve historical results, KI files and installations; status reads must not rewrite or silently repair them. Both normal agent and built-in installation writers record the configuration actually checked. Failure, cancellation and the start of another verification clear readiness. A configuration change detected during verification cannot receive a successful result.

Acceptance: verify then change interpreter, binary/helper path, relocation or workspace identity; readiness must fail. Delete or corrupt the saved configuration; readiness must fail. An unchanged binding survives reopening, comments and key reordering. Both writer paths produce matching evidence; interrupted or failed attempts cannot inherit a previous pass. Existing KI digest and snapshot/shared-tool update checks remain active.

Scope: this fingerprint binds configuration values; it does not detect executable/package contents changed at the same path, implement an OS execution backend, or prove the installed KI/project KI derivation. The separate `software_audit` report currently reads raw saved success rather than the GUI readiness gate; account for that reader before claiming universal report consistency. T3/T5 retain the broader runtime-content and update-reconciliation work.

Implementation and review evidence:

- Added `software_verification.runtime_identity`, recorded by normal final verification and built-in installation only on a successful full check. `_status_for` requires a matching saved binding before allowing execution for snapshot and non-snapshot KIs. Old reports without that fingerprint require a recheck, preserving their files and history.
- A post-check comparison rejects configuration changes observed during preflight. Both final writers use the explicit trusted installation root. This is a consistency checkpoint, not a filesystem lock against every possible concurrent change.
- Both verification boundaries revoke previous readiness before work that might throw. Failed or cancelled verification clears the fingerprint. Installation-only results remain separate from full verification.
- The initial 43-case regression produced **32 failures and 11 passes** before implementation. The completed regression file has **55 passing cases**, including later edge cases. The related suite passed **86 tests with one POSIX FIFO test skipped on Windows**. Final combined evidence: **141 passed, 1 skipped**. The earlier intermediate 108-pass run is superseded by these final results and is not an additional test count.
- Independent review identified two gaps: snapshot identity calculation occurred before revocation, and the built-in final comparison trusted `cfg.root` rather than the selected workspace. Both were fixed and covered by new regressions. Reviewers approved the revised code; they did not independently rerun tests. The test author ran the 55-case regression, and the root agent ran the 86-pass related suite. `git diff --check` passed.
- Mandatory KI assets and scientific requirements were not edited or demoted. The original mandatory-asset delivery question remains a separate packaging/acquisition audit.

Final validation commands (same interpreter and working directory as T1):

```powershell
# 55 passed.
& 'D:/GeoForge-Release-0.6.57/build-env/Scripts/python.exe' -m pytest tests/test_verified_runtime_binding.py -q --tb=short

# 86 passed, 1 skipped (POSIX FIFO; Windows blocked-read coverage passed).
& 'D:/GeoForge-Release-0.6.57/build-env/Scripts/python.exe' -m pytest tests/test_snapshot_verification.py tests/test_setup_final_runtime.py tests/test_setup_config_reload.py tests/test_project_setup_handoff.py tests/test_gui_install_location_refresh.py tests/test_runtime.py::InstallLocationTests tests/test_runtime.py::InstallStatusTests tests/test_runtime.py::AgentSetupTests::test_agent_final_preflight_becomes_the_saved_verification_state tests/test_stop_sync_work.py -q --tb=short
```

Rollback boundary: the configuration fingerprint, readiness comparison, pending revocation and final binding checkpoint form one application change. Existing installation files are not migrated or rewritten by status reads. T1's saved-runtime reload and the earlier location-cache fix are separate changes to preserve when reverting T1b. No new model simulation, installed-app deployment, commit, push or release occurred in this slice.

## T2 Setup supervision and bounded discovery

Status: T2a and T2b1 implemented in local source; T2b2 remains planned. No installed-app update or release in these slices.

Register standalone setup with the existing execution supervisor. Carry a job/attempt identity and Stop handle through API, CLI, built-in installation and preflight. Persist terminal failed/cancelled states even if the provider throws. Add Stop/reconnect behavior in the setup UI.

Use known-root discovery tools with explicit scope, depth/count/time budgets. Detect identical unsuccessful probes with unchanged evidence. Long compilations can continue with measurable progress; heartbeats alone do not count as progress. Ensure raw setup scripts cannot evade the discovery budget simply by wrapping a full-drive scan in Python.

Acceptance: cancel a setup command and prove all owned children stop, reconnect to saved job status, recover interrupted jobs after restart, reject repeated non-progressing scans, and allow a progressing build. No other application or WSL distribution may be stopped as collateral cleanup.

### T2a: supervised standalone setup

Implemented in `kiss_cli/setup_jobs.py`, `gui.py`, `runnable.py`, `python_script.py`, `execution.py` and `web/setup.html`:

- Persist a job ID, selected root/provider, generation, state and timestamps. OS-held leases exclude concurrent setup for both a model and its canonical installation folder, including separate app processes. A stale tab cannot stop a later attempt.
- Carry the same cancellation handle/generation through API and CLI providers, built-in setup, initial/final preflight, and direct/delegated installation probes. Preserve cancellation context across heartbeat threads.
- Keep ownership after browser disconnection. Saved status/log polling restores the page; slow requests are coalesced rather than continually invalidated by newer polls. Stop remains visible until the attempt finishes; English and Chinese controls follow server state.
- Serialize Stop against terminal bookkeeping. Cancellation revokes a late verification PASS and any successful installation-only report before releasing ownership. Public readiness stays false during an active attempt; completion still requires the full source/runtime/snapshot status gate.
- Apply the same ownership guard to built-in installation, location changes, resume and uploads. Recheck the selected location after acquiring its lease. Damaged KI manifests do not hide setup status or Stop.
- On stream-consumer failure, request Stop and wait for the provider thread before releasing ownership. Local signalling still happens if durable Stop persistence fails. Normal app shutdown schedules owned CLI termination before waiting for cleanup.
- Classify an abandoned host attempt as interrupted, revoke readiness, and signal the old generation if it still owns the root. Never terminate a process merely from a saved PID.

Independent reviews found and prompted fixes for: consumer-thread lifetime, shutdown scheduling, stale-location mutations, upload bypass, broken-manifest status, a source-integrity completion mismatch, slow-poll starvation, and failure to signal a live provider when Stop persistence fails. Each has a regression test or an existing process supervisor regression exercised by the combined suite.

Validation uses harmless fixture KIs and fake API/CLI providers, actual HTTP requests, actual JavaScript from the shipped page executed in Node, separate app processes, and real quiet parent/child processes. The process tests verify an unrelated sentinel survives. These tests do not establish scientific model correctness or successful live DeepSeek setup.

Final combined regression result: **576 passed, 29 skipped, 45 subtests passed in 84.21 seconds** on Windows. `git diff --check` and Python compilation checks passed. The skipped cases were not treated as passing evidence. Two independent reviewers approved the bounded GUI/manager/UI changes after the findings above were addressed; one independently reran both consumer-failure regressions (2 passed).

The 29 skips were checked again with `-rs`: 27 POSIX process-group/signal cases, one POSIX named-pipe (FIFO) case, and one executable-shell adapter case. They require Linux/macOS facilities and were intentionally skipped on Windows. Windows process, cancellation and blocked-read coverage ran. The skip audit itself produced 93 passed and 29 skipped; these are repeated checks, not additional unique test coverage.

Reproduce from `D:/GeoForge-KI-Prepared-Inputs-20261004/kiss`:

```powershell
& 'D:/GeoForge-Release-0.6.57/build-env/Scripts/python.exe' -m pytest tests/test_gui_setup_jobs.py tests/test_setup_jobs.py tests/test_runnable_cancellation.py tests/test_python_script_cancellation.py tests/test_setup_verification_ui.py tests/test_setup_final_runtime.py tests/test_verified_runtime_binding.py tests/test_snapshot_verification.py tests/test_gui_install_location_refresh.py tests/test_execution.py tests/test_api_stop_stream.py tests/test_stop_generation.py tests/test_stop_sync_work.py tests/test_python_script_contract.py tests/test_probe_runtime_environment.py tests/test_bounded_startup_probe.py tests/test_runtime.py tests/test_execution_adapters.py tests/test_stop_turn.py tests/test_project_setup_scope.py tests/test_project_setup_handoff.py tests/test_setup_config_reload.py -q --disable-warnings --maxfail=3 --tb=short
```

Remaining limits: a force-killed host may leave arbitrary native/CLI descendants alive. An interrupted job record proves the host lease was lost, not that every orphan exited; the old-generation marker only reaches cooperative children. Kill-on-host-exit containment and a real crash-with-child acceptance test remain a follow-up before claiming crash-safe retry. T2a alone did not bound filesystem discovery; T2b1 below bounds the host discovery step. Repeated probes and arbitrary provider filesystem work remain T2b2. No forced termination of the user's installed Desktop or model process was used for this test.

Rollback boundary: the job manager, GUI ownership/control wiring, cancellation scope for probes, heartbeat-thread lifetime, and Setup UI state handling form one T2a change. Preserve the earlier T1/T1b saved-runtime verification changes when reverting T2a.

### T2b1: one bounded host discovery pass

Status: Implemented in local source and independently reviewed. The full T2b enforcement contract is not complete.

Problem: the previous candidate helper used PATH lookups, platform indexes and conventional-directory enumeration without one shared execution budget. An empty or incomplete search could leave the agent repeating increasingly broad searches. API and CLI setup also needed the same current discovery evidence on resume.

Changes:

- Existing-install discovery runs once before the provider in a supervised child, using the setup job's cancellation handle and generation. It checks exact selected paths, exact PATH names and direct conventional-location entries. It does not recurse or query whole-machine indexes.
- The worker has an eight-second execution deadline, 512 entry/probe checks, 64 unique roots, 12 normalized hints, 24 candidates, and 64 KiB request/result caps. Worker startup and process cleanup add wall-clock overhead. Blocked filesystem calls are contained by terminating the child and its owned process tree.
- Source launches use the absolute host worker file with isolated Python (`-I -S`), preventing an agent-writable workspace from shadowing worker imports. Frozen builds have an internal dispatcher that inherits the parent's prepared environment instead of launching another login shell.
- A structured report records scope, limits, counts, completion state, reason and timestamps. The GUI adds job/generation identity, persists the report in `.geoforge/setup-discovery.json` and retains it through installation-record rewrites. A complete report describes only the finite advertised scope; it never establishes machine-wide absence or software readiness.
- API and CLI agents receive the same unverified candidates and report. No candidates means a structured request for an exact existing path before any provider is launched. Selecting a new installation remains an explicit mode change. A user-selected exact path does not require another discovery pass.
- Resumed CLI sessions receive the current mode, selected/discovered paths and installation-only restriction even when no discovery was needed. Old conversation paths cannot silently override the new selection. New-copy setup retains its existing build behavior and does not invoke discovery.

Independent review findings fixed: workspace module shadowing, malformed report handling, bounded scratch cleanup, Windows case-insensitive environment keys, overlapping PATH/conventional roots suppressing enumeration, report loss during record rewrites, and resumed CLI sessions missing newly selected paths or retaining a scientific-preflight instruction during installation-only setup. The overlapping-root regression failed before its fix. The independent integration reviewer approved the corrected source with no remaining blocking findings; the reviewer did not rerun the full regression.

Focused evidence: 27 worker tests passed, including real blocked-read worker/child processes stopped by deadline, callback and generation marker while an unrelated sentinel survives; 37 prompt/GUI tests passed, including API/CLI report delivery, empty/failed/timed-out discovery handoff, and selected/discovered-path resume in both normal and installation-only mode. Frozen dispatcher behavior is covered at the Python entrypoint level; no frozen executable was rebuilt or tested in this slice.

Final combined regression: **653 passed, 29 skipped, 45 subtests passed in 94.19 seconds** on Windows. The same 29 POSIX-only cases described under T2a were skipped; there were no failures. Python compilation and `git diff --check` passed. This combined run supersedes the intermediate focused counts; they must not be added together.

Reproduce from `D:/GeoForge-KI-Prepared-Inputs-20261004/kiss`:

```powershell
& 'D:/GeoForge-Release-0.6.57/build-env/Scripts/python.exe' -m pytest tests/test_gui_setup_discovery.py tests/test_setup_discovery.py tests/test_setup_discovery_guidance.py tests/test_windows_frozen_entry.py tests/test_gui_setup_jobs.py tests/test_setup_jobs.py tests/test_runnable_cancellation.py tests/test_python_script_cancellation.py tests/test_setup_verification_ui.py tests/test_setup_final_runtime.py tests/test_verified_runtime_binding.py tests/test_snapshot_verification.py tests/test_gui_install_location_refresh.py tests/test_execution.py tests/test_api_stop_stream.py tests/test_stop_generation.py tests/test_stop_sync_work.py tests/test_python_script_contract.py tests/test_probe_runtime_environment.py tests/test_bounded_startup_probe.py tests/test_runtime.py tests/test_execution_adapters.py tests/test_stop_turn.py tests/test_project_setup_scope.py tests/test_project_setup_handoff.py tests/test_setup_config_reload.py -q -rs --disable-warnings --maxfail=3 --tb=short
```

These are application/runtime fixtures, not new DSSAT, WOFOST, WRF-Hydro or scientific-model E2E results. The installed Desktop was not restarted or updated. The changes remain local and uncommitted; no release was built or uploaded.

### T2b2: remaining discovery enforcement

The bounded worker does not restrict arbitrary filesystem reads performed by a provider's shell or Python scripts. Existing API path checks inspect supplied arguments; scripts can hide recursive work internally, and CLI providers have different native sandbox capabilities. Prompt guidance is not an OS read sandbox. Pre-existing external metadata probes in `install_locations.info()` and CLI grant resolution also remain outside the worker budget.

Remaining work: define enforceable per-provider execution boundaries, prevent repeated unsuccessful probes without unchanged broad retries, and move remaining external metadata operations behind supervised limits. Preserve ordinary progressing builds. Add adversarial script/provider tests and crash containment evidence before claiming the full T2 acceptance contract.

Rollback boundary for T2b1: worker/module entrypoint, host invocation/report storage and provider guidance form one discovery change. Preserve T2a ownership/cancellation and T1/T1b verification. No KI source, mandatory asset requirement, installed application, model project or runtime was changed by these tests.

## T3 Runtime resolution before KI binding

Status: Partial implementation in local source. Runtime selection before materialization, exact project binding verification and launch guards are implemented in the slices below. Backend-tagged paths and executable/dependency content attestation remain planned.

Introduce a minimal versioned runtime record by extending existing `KissConfig`, installation records and role bindings. Runtime paths carry their backend/domain from the start; a future Linux path must not be interpreted through a Windows `Path`. Resolve selected/existing Python, required interpreter version and dependency environment before generating a new protected projection. Selecting an existing runtime must bind the declared interpreter deterministically rather than only pass an advisory candidate to the agent.

Keep the upstream package immutable. Prefer a runtime-context interface for tools; legacy source literals require a reviewed compatibility change. Reconcile existing `materialise_active` protection explicitly: a changed projection must not be silently enrolled as the previous KI.

Acceptance: install or reuse the requested compatible interpreter; reject an incompatible interpreter; preserve existing installations; materialization and verification use the same runtime; moving to paths with spaces/Chinese characters triggers correct rebinding without modifying test-case bytes. Reopen the app and obtain the same selected runtime.

## T4 Separate KI assets from writable run directories

Status: Partial implementation in local source. Host preflight runs in private scratch with retained logs and protected source integrity checks. DSSAT native placement/startup and CRHM preflight have real GUI evidence below. Full model-specific asset delivery and reference-case acceptance remain incomplete.

Supply explicit KI asset, runtime, data, run and scratch roots. Launch host-owned preflight in a disposable run directory. Preserve before/after KI integrity checks and report generated output as run evidence.

DSSAT also contains an internal `cwd=KI_DIR`; changing only the host caller will not fix it. Freeze the actual setup logs and runtime information, complete three valid independent reviews, create a KDT candidate and verify/adopt that candidate using the existing workflow. Preserve mandatory cultivar/support-file requirements and audit whether the delivered KI or its acquisition recipe provides every required asset. Repair missing delivery; do not fabricate files or demote required inputs.

Acceptance: two startup probes leave the KI tree unchanged, logs are retained in their own attempt directories, a deliberate KI write is rejected, and the repaired DSSAT reference case produces fresh native outputs read correctly by its reader.

## T5 Reconcile upstream updates with local runtimes

Status: Partial implementation in local source. Standalone library pinning, exact project verification, stable helper cache identity, per-KI verification identity and exact-context portable adaptation reuse are implemented. Existing projects retain their recorded bindings. Legacy projects without authentic portable lineage remain eligible only for local repair; changes to effective installation recipes require further reconciliation and cannot be registered as reusable adaptations by this slice. The full real update acceptance matrix, cross-OS runs and runtime-content attestation remain pending.

On every KI/shared-tool pull, stage the upstream package, select the target platform recipe, reconcile reviewed compatibility changes, resolve local runtime bindings and invalidate affected evidence. Structural package verification and machine execution verification have separate states.

The verification key must include the relevant KI/recipe/shared-tool identities and the actual runtime backend/interpreter/engine/dependency evidence. Avoid invalidating unrelated models solely because an unrelated library file changed. Reuse an installation only when its declared requirements remain satisfied.

Keep the last working installation and project binding until a replacement passes. Changed dependencies require side-by-side preparation where in-place mutation would break the old runtime. Never blindly replay a compatibility patch onto changed upstream source. Conflicts retain a staged candidate for KDT review.

Acceptance matrix: documentation-only update; changed entry point; changed dependency/engine; shared-tool update with dependent KIs; conflicting local compatibility change; failed verification; interrupted activation; rollback; existing project pinned to prior working version. Each case must show which evidence was retained/invalidated and why.

## T6 Target runtime backends

Status: Planned.

Use one backend interface for preparation, path resolution, execution, verification and cancellation. Start with native Windows and WSL Linux, retaining extension points for native Linux and macOS/architecture-specific recipes.

The backend determines the recipe: a Windows GUI using WSL selects Linux requirements. Store Windows display/staging paths separately from Linux execution paths. Run the full KI toolchain in the selected target environment, not just the final executable. A WSL runner must track and terminate its own Linux process group without shutting down unrelated WSL work.

Acceptance: WRF-Hydro exact requested engine version, Linux compiler/MPI/NetCDF checks in the chosen distribution, controlled case staging, fresh reference run, complete output coverage, and observed-data mapping/time convention checked separately before scoring. A different engine version cannot inherit a pass.

## T7 Reference case and catalogue acceptance

Status: Planned.

Add an explicit host-owned reference-case result alongside software readiness. Preserve original case inputs; use fresh run directories and output receipts. Cases can be bundled or obtained by a versioned download recipe with clear provenance. Missing cases remain untested, never inferred successful from a startup probe.

Pilot matrix:

| KI | Runtime target | Required evidence |
|---|---|---|
| WOFOST | Compatible native Windows Python/PCSE | Correct interpreter at every entry point, shipped crop case, dates/units/finite outputs and reader agreement |
| DSSAT | Native Windows | Clean preflight, exact engine, stock-case prerequisites, fresh Summary.OUT/PlantGro.OUT and reader agreement |
| WRF-Hydro | WSL Linux | Exact engine, native completion, fresh routed-flow outputs, coverage; observations/time alignment before skill metrics |
| CRHM, SHAW, VIC | Existing supported runtime | Preserve previously established behavior through focused regression cases |

After the pilot passes, inventory every shipped KI's platform recipe, dependency contract and reference-case availability. Report supported/verified/untested per runtime, not one platform-independent catalogue success label.

## Review and implementation ledger

| Item | Status | Evidence |
|---|---|---|
| Detailed plan | Approved by independent architecture and implementation reviewers | Review dispositions below |
| Prior installation-location cache fix | Local source only | Previous report: 28 tests passed; not deployed/released |
| T1 | Implemented and independently reviewed in local source | Before: 16 failed / 5 passed; after: 57 focused tests passed; two code reviews approved |
| T1b | Implemented and independently reviewed in local source | Initial regression: 32 failed / 11 passed; final focused evidence: 141 passed / 1 POSIX-only skip; mandatory requirements preserved |
| T2a | Implemented in local source | Supervised setup, Stop/reconnect, lease and cancellation regressions; limits documented above |
| T2b1 | Implemented and independently reviewed in local source | Bounded host discovery, real worker cancellation, structured evidence and current-binding resume |
| T3/T5 first verification slice | Implemented and independently reviewed in local source | Standalone library pin, signed exact-project verification, all-selected-KI GUI gate and API/CLI/calibration launch guards; evidence below |
| T2b2 and remaining T3–T7 | Planned | Provider-wide enforcement, backend/adaptation/update contracts and scientific model acceptance remain incomplete |

Plan/review/implementation status will be updated as each slice is completed. No KI source edit or scientific simulation is authorized by a unit-test fixture; actual model repairs/runs retain their normal gates.

## Independent review dispositions

- The architecture reviewer approved the saved plan, including supervision before new adaptation experiments and explicit per-KI update reconciliation. Retained constraints: backend-tagged paths from T3; enforceable discovery limits in T2 rather than prompt-only restrictions.
- The implementation reviewer approved T1 with failure-status persistence and trusted-workspace anchoring. Reload is centralized in `_record_agent_preflight`, which serves standalone and project API/CLI setup. Preserve its boolean interface. A supplied early check must be rerun when root/interpreter/roles/relocation differ.
- The existing project `flowrun.setup_verified` currently does not consume its configuration argument, and later session configuration reloads saved settings. No unrelated caller mutation or return-type redesign is needed for T1.
- Invalid configuration must not trigger a probe or be replaced by the stale in-memory configuration. Clear both status and any existing installation-record verification flag without inventing a valid replacement runtime.
- Runtime consistency tests are not scientific model verification. T1 does not resolve embedded KI paths or establish WOFOST/DSSAT/WRF-Hydro readiness.
- After implementation, both reviewers approved the actual code and tests: trusted-root loading, shared configuration across verification/requirements/receipt, changed-binding invalidation, invalid-config revocation and existing integrity/cancellation gates were confirmed. The external-interpreter selection and virtual-environment launcher spelling remain supported.
- Nonblocking follow-up: centralize configuration parsing during T3, and address concurrent changes/interrupted setup through T2's supervised lifecycle. Neither requires expanding T1 into a runtime redesign.

## Follow-up code and asset audit: 2026-10-10

Three independent read-only audits examined update activation, installation/project derivation and mandatory DSSAT delivery. T1/T1b source changes remain uncommitted and undeployed. No model simulation or KI edit occurred during this audit.

The following tables and findings record the pre-fix audit baseline. The later T3/T5 implementation section closes the standalone attempt-context and exact-project verification gaps only; other listed limits remain open.

### Existing mechanisms and their limits

| Boundary | Already implemented | Still missing |
|---|---|---|
| Downloaded library | Staging, hashes, structural/KDT verification for changed packages, unchanged-package comparison, quarantine on failure | Structural acceptance explicitly defers native execution; it is not machine readiness |
| Platform adaptation | Windows notes/recipe overlay with conflict checks | Does not carry reviewed KI Python/tool repairs into new upstream code; not a common backend adaptation record |
| Installed copy | Path materialization and integrity enrollment; changed protected projection is retained as a draft and blocked | No explicit derivation receipt proving the checked adaptation belongs to the selected upstream revision |
| Runtime readiness | Saved-config reload, parsed runtime fingerprint, installed-KI digest and snapshot identity checks | In-place executable/package changes are outside the configuration fingerprint; the separate audit report still uses raw saved success |
| Projects | Existing project KI/helper pairs retained; fresh snapshot projects use catalogue source; project paths separated from installation paths | Shared installation readiness does not prove that the actual fresh project KI passed; full old/new runtime pinning is incomplete |
| Updates during setup | Old immutable snapshot files are retained | Setup does not carry one immutable library context through the whole attempt |

`ki_verification.verify_candidate` deliberately validates the preflight contract in an isolated structural check, with native execution deferred. Update activation therefore cannot by itself certify every model installation or E2E case. This separation is appropriate; the subsequent runtime/project checks must be connected correctly.

### Confirmed project verification gap

An independent reviewer used isolated temporary fixtures with real harmless preflight subprocesses and the real host guard/status functions:

| Fixture operation | Observed result |
|---|---|
| Check an already host-enrolled installed adaptation | Preflight passed; shared `can_run=true` |
| Create a fresh project from the catalogue | Received catalogue preflight, not the installed adaptation |
| Execute that fresh project's harmless preflight | Failed with exit 7; shared `can_run` remained true |
| Change the snapshot content identity | Shared readiness correctly became false (`snapshot-changed`) |
| Attempt to replace the protected installation with a differing projection | Correctly blocked, preserving the installed copy |

The fixture starts with two independently accepted/enrolled trees. It does not exercise KDT adoption or establish that the GUI automatically creates this state. It proves that, once the state exists, the installed verification and fresh-project boundary do not reject the mismatch. `_record_agent_preflight` stores catalogue identity and the separately checked installed digest; `_session_workspace` creates a fresh project from catalogue bytes. An ordinary snapshot update is already invalidated; the missing relation is between the exact installed adaptation and exact project KI.

Required fix contract for T3/T5/T7: record upstream revision, reviewed portable adaptation, resolved runtime bindings and checked KI bytes together. Verify the actual project KI and its binding before scientific execution, including fresh projects without a pending repair record. Preserve plan approval, data-acquisition ordering and installation-only restrictions; do not run scientific cases merely while opening a project. Reuse a reviewed portable adaptation with new project-specific paths, not an already materialized copy carrying another project's absolute paths.

### Two additional lifecycle gaps

1. `serve.activate` changes the handler catalogue and library root while an earlier setup may retain an old KI object. `software_verification.identity` returns `None` for a KI outside the current library root, which is intentional for imported KIs but can misclassify an in-flight older snapshot. Capture selected KI, effective recipe, helper source and snapshot identity once per attempt. Regression: start setup on A, activate B, finish A; the receipt remains associated with A and cannot certify B.
2. `setup.prepare_common` includes the repository `source_commit` in its directory identity. An unrelated commit can move unchanged helpers to a new path and change embedded KI paths. `software_verification.identity` also includes whole-library content. Derive reuse from the relevant KI/recipe/helper contents and materialization policy; retain source commit as provenance. Regression: unrelated upstream changes preserve helper paths and installed/project KI bytes; relevant helper changes invalidate dependent evidence.

These are source findings; no concurrent library-update race or actual helper-path migration was run against the user's desktop.

### DSSAT mandatory asset delivery

The four required files (`MZCER048_China.CUL`, `WHCER048_China.CUL`, `RICER048_China.CUL`, `SBGRO048_China.CUL`) are absent from the inspected tracked repository tree, active test snapshot and installed DSSAT tree. They are explicitly critical in the preflight. The acquisition recipe clones/builds the official engine but declares no delivery step for this cultivar library. The workdir tool consumes and merges the files; it does not supply their authoritative coefficients.

The packaging spec includes the model tree, and no matching ignore rule was found: there is no evidence that the Windows packager stripped an existing payload. The missing files require an authoritative bundled asset or pinned download with provenance/checksums, plus explicit staging to `Data/Genotype/China/`. Contradictory guidance calling these optional must be reconciled through review/KDT while preserving the user's mandatory requirement.

`MODEL.ERR` is a different issue: the installed file exists under `DSSAT/Data/MODEL.ERR` (24,723 bytes), whereas the retained native `ERROR.OUT` reports looking under `DSSAT/build/bin/MODEL.ERR`. Repair the executable/support-file lookup or run staging without writing generated files inside the protected KI.

The shipped generic soil and reference runner are present; the runner obtains weather online. The manifest's `reference_case` is `--version`, not a simulation. A complete reproducible reference-case acceptance test remains necessary.

Remote freshness was checked with `git ls-remote`, and `origin/main` was fetched without changing the working branch or app library. At audit time main was `889a6e70332e31b21911efb0a08ac2fa2a067e03`, Mac was `de0b9282c05b9e88b4cd6c804fae8de18a707d72`; neither tree supplies the China cultivar payload. The new main commits since locally cached `44a17f3` do not change DSSAT or its shared manifest. No server-private asset store was queried.

### Implementation order after the audit

Continue T2 supervision before another long live setup. For the next runtime/project slice, pin one attempt's library context and add an actual-project verification receipt using the harmless mismatch regression above. Then establish reviewed adaptation derivation/reuse and stable helper identity, followed by mandatory asset delivery and real DSSAT reference-case acceptance. Preserve all existing KDT and scientific requirements throughout. No blanket copy of old installed KI files into a new snapshot is acceptable: existing regression tests correctly prevent resurrecting retired files and cases.

## T3/T5 first implementation slice: pinned setup and exact project verification

Status: Implemented in local source and independently reviewed. This is a subset of T3/T5, not completion of runtime adaptation or model acceptance. No KI requirements were weakened and no KI edit bypassed KDT. No commit, push, release build or release upload was made in this slice.

### Implemented boundaries

- **One library context per standalone attempt.** `Handler._with_setup_library` pins the handler's catalogue, library root and catalogue integrity errors around standalone agent and built-in setup. Preparation, effective manifests, helpers, dependency lookups and final installation evidence use the captured context. Starting on snapshot A, activating B and finishing A cannot silently classify A as an imported KI or certify B. Partially observed activation fails before starting a job. Request-local overrides and location/status caches are restored or cleared even on exceptions. Bundled, imported and explicitly selected catalogue behavior is retained.
- **A signed receipt for the actual project.** `project_verification.verify` checks the enrolled `models/<KI>/ki` tree, its exact saved per-KI configuration and effective manifest. It records KI content digest, runtime binding fingerprint, requirements, preflight evidence and attempt identity in a host-signed project receipt. It revokes an old pass before checking, rereads identity after checking and refuses superseded attempts. Missing, changed, invalid or unauthenticated evidence blocks readiness. Reading status does not execute preflight, repair configuration or adopt source files. A shared installation's pass cannot substitute for this project check.
- **All selected KIs must pass before Flow hands off.** The GUI verifies each selected project KI after the approved setup boundary and confirms all receipts are still current before `setup_verified`. A normal verification failure leaves `SETUP_REQUIRED`; stale evidence detected during execution causes replanning. Planning and data acquisition do not execute project preflight. The existing reviewed/adopted KI repair workflow retains its bounded environment-repair turn and exact-project recheck; an ordinary failed check is not automatically reclassified as an environment repair.
- **Checks at actual launch boundaries.** The common execution path used by API and CLI model tools requires current project evidence and compares the actual launch configuration with the recorded binding. Calibration dispatch also requires current project verification. The checks cover materialized project KIs, including aliases that resolve into that namespace; explicit legacy nonmaterialized routes retain their existing behavior. Provider messages cannot create a pass.
- **Stop and publication are ordered.** Final identity checks and signing remain inside the cancellation/worker scope. The host checks Stop again before publishing a pass, serializes receipt finalization and rejects an older attempt if a newer attempt owns the receipt. Review findings on late Stop and receipt publication were fixed and independently approved. Receipt files use short names and the existing extended Windows host-I/O helper; a real receipt path exceeding 260 characters is covered.

### Verification and review evidence

- The standalone library race regression initially produced **4 failures and 4 passes**. The completed `tests/test_setup_library_pin.py` has **14 passing tests**, covering API, CLI, built-in callbacks, early/final checks, activation/no-change, exception restoration, imported/bundled/custom catalogues and rejection of partial activation.
- The receipt-module owner's focused tests passed **35 cases**, including harmless real preflight, changed saved bindings, manifest/dependency requirements, signed evidence, stale/superseded attempts, cancellation during signing/replacement and concurrent status reads, aliases and the long Windows receipt path. These are application fixtures, not model simulations.
- Root's integrated GUI/repair verification suite passed **74 tests** after updating fixtures to compare actual saved bindings rather than configuration object identity. The final combined setup/runtime/GUI/execution/calibration regression run passed **919 tests, with 29 POSIX-only skips and 45 passing subtests in 265.89 seconds**. Focused counts overlap and must not be added as a unique-test total. One older preparation fixture initially lacked project-verification evidence; it now runs a real harmless preflight before tool execution, and the combined rerun is clean.
- Independent reviews inspected the standalone pin, receipt module, GUI/Flow handoff and launch/Stop boundaries. The discovered Windows receipt-path failure and final publication race were corrected. The bounded revised implementation has no remaining blocking review finding; the limitations below remain explicit.

Relevant regression files: `kiss/tests/test_setup_library_pin.py`, `test_project_verification.py`, `test_gui_project_verification.py`, `test_project_verification_dispatch.py`, `test_gui_investigation.py`, `test_project_setup_handoff.py` and `test_calibration_flow_binding.py`.

### Remaining limits and next live test

- Runtime fingerprints cover configuration values. They do not detect helper, executable or installed package contents changing at the same path, prove portable adaptation derivation, or supply a universal native/WSL backend contract.
- Receipt finalization uses a process-local KI operation lock. It is not a cross-process filesystem lock or protection against arbitrary same-user applications modifying files.
- Automatic shared-runtime installation in a project still starts from the first selected KI. A missing secondary shared runtime is reported and blocks handoff; this slice does not add automatic installation of every secondary KI.
- Long receipt paths are handled. Long KI/configuration paths and every native tool's path-length behavior have not been universally qualified.
- No new DSSAT, WOFOST, WRF-Hydro or other scientific E2E success is established by these fixtures. Reference-case completion, observed-data coverage and scientific scores remain separate acceptance work.

A new GUI pull of official main `889a6e70332e31b21911efb0a08ac2fa2a067e03` was rejected by six doctor path checks affecting **COAWST, DHSVM, DuMux, LPJmL, tRIBS and WRF**. The 11 flagged occurrences were unsupported reference-case patterns: explicitly overridable defaults, historical notes/comments, and pack metadata whose companion runner supplies a local-directory override. No KI source files were edited.

`reference_portability.py` now proves these narrowly recognized patterns and retains blocking findings for unknown or mandatory paths. Independent review found and drove fixes for environment alias mutation, import shadowing, annotated assignment, pack-dictionary escape and nested-closure loopholes. Regression evidence: **140 passing tests and 2 passing subtests** across `test_reference_portability.py`, `test_ki_update_quarantine.py`, `test_ki_updates.py` and `test_ki_update_components.py`; a separate independent rerun passed all **98** classifier tests. Doctor's validation policy is now `ki-doctor-reference-cases-v2`, so prior acceptance identities are not reused under the new rules.

The six actual quarantined KIs now have no blocking doctor findings under a read-only reclassification. This establishes static portability classification, not Windows software readiness or reference-case success. The subsequent GUI retry reached the encoding/publication-contract issues recorded below; fresh-project E2E remains pending.

Rollback boundary: standalone library pinning is a separate host change. Exact-project receipts, GUI readiness/Flow handoff and corresponding execution/calibration guards form one connected verification boundary. Preserve T1/T1b saved-runtime checks, T2 supervision/discovery and all existing KI integrity/KDT gates when reverting or revising this slice. No user KI or scientific project was migrated by the automated fixtures.

### Live pull follow-up: Windows encoding and the publication contract

The reviewed GUI retry passed the reference-path stage, then KDT's default `Path.read_text()` decoded UTF-8 package files using the Windows GBK locale. The host's existing private verifier view now uses a UTF-8-default Path subclass; explicit encodings/error policies, global pathlib, engine sources and required checks are unchanged. That fix introduced policy `ki-draft-kdt-v3-utf8-package-text`; the subsequent contained-alias boundary is versioned as `ki-draft-kdt-v4-contained-aliases`.

Six focused regressions failed before and passed after the encoding fix. The combined final classifier/update/KDT suite passed **187 tests and 2 subtests in 11.92 seconds**. An independent reviewer approved the encoding boundary. A real unchanged ADCIRC candidate recheck removed both decoding errors and the FILE5/6 crash, leaving only `docs/gathered_papers.json` missing.

The next issue was a published-package/authoring-contract mismatch: the desktop intentionally distributes `docs/papers.json` without private fetched-text paths, while the pinned authoring gate requires gathered-paper evidence. Two independent reviewers rejected treating them as interchangeable aliases. The separate versioned contract is now implemented locally and independently reviewed; its historical reproduction, current implementation and server handoff are recorded in [KI-PUBLISHED-VALIDATION-HANDOFF-2026-10-10.md](KI-PUBLISHED-VALIDATION-HANDOFF-2026-10-10.md).

`published_kdt.py` requires the exact reviewed KDT source and creates a private verifier with three explicit literature changes; all unrelated KDT checks and the installed authoring engine remain intact. `published_literature.py` checks the actual exported bibliography and citation relationships without inventing fetched/read evidence. Its current v2 policy matches exporter/pinned-KDT semantics: missing cross-file duplication of a DOI is an explicit coverage warning, while unknown citation keys, malformed metadata and deferred/validation contradictions remain failures. Title-only bibliography records and explicit unknown DOI sentinels do not become fetched/read or crosslinked evidence. This corrects the extra closure condition introduced by the historical v1 checker; it is not a KDT failure-prose filter.

`published_acceptance.py` issues separate signed publication reports from the official updater's exact commit/archive/source/effective-content origin. Retained Windows guidance from registered KIs still requires the source KI to be intact. For absent baselines only, `platform_guidance_provenance.py` authenticates every selected notes/recipe input against a fixed official Windows-branch HTTPS commit/tree anchor and verified local Git tree/blob objects. Exact bytes or explicit CRLF/LF-only equivalence are recorded with both SHA-256 values, blob identity and commit. Bounded retrieval, immutable signed caching and current-input rechecks do not grant a whole-KI baseline or authoring acceptance. Changed/invalid registered baselines cannot use this fallback. Generic host guidance otherwise retains its signed first-use inventory. Activation and enrollment require a signed managed-snapshot envelope covering every package and complete content. Unchanged packages require their exact intact previous host baseline and do not receive a new verification claim.

Publication receipts cannot cross into authoring, Studio, arbitrary imports or repair adoption. Removing signature/policy metadata cannot downgrade a snapshot to legacy unsigned acceptance. Engine/doctor changes invalidate reuse, and a profile fingerprint change during checking is rejected before signing. Unknown engine source fails closed. No KI or engine source bytes were edited to obtain acceptance, and no scientific requirement was relaxed.

The earlier combined publication/update/classifier/authoring/project-guard suite passed **375 tests and 2 subtests**. Subsequent independent runs passed **90 metadata/profile tests**, **25 guidance-provenance tests** and **72 alias-lifecycle/materialization/tree/extraction tests with 1 POSIX-only skip** after the final copy corrections. Independent reviews found no remaining blocking issue in these bounded slices. The earlier **919 passing tests, 29 POSIX-only skips and 45 subtests** remain evidence for the setup/runtime/GUI boundaries described above; these overlapping totals are not additive. Native model execution and scientific acceptance remain outside these test claims.

A separate [v2 published metadata audit](D:/GeoForge-Model-Tests-20261010/published-literature-audit-v2.json) checked unchanged metadata for **127 process-model KIs: 121 passed, 6 failed, with 254 warnings**. It supersedes the [historical v1 audit](D:/GeoForge-Model-Tests-20261010/published-literature-audit.json), whose **49 passes and 78 failures** included the additional cross-file DOI-duplication requirement. The current failures are BMI, Climate_Projection, EF5, EPIC, ESMF and PyMT; the handoff lists their exact missing/contradictory records. CRHM, SHAW, VIC and DSSAT retain explicit bibliography-coverage warnings. Both audits are read-only metadata/citation analysis, not full KDT or native acceptance, and found no `kiss/data_kis` component to test. No KI source changes account for the new count.

The [full read-only structure audit](D:/GeoForge-Model-Tests-20261010/published-structure-audit.json) of the old quarantine separately recorded **108 passes and 19 failures** through KDT plus doctor with the safe host preflight stub. Three failures concern old physically broken aliases, which remain untouched; other package-structure/contract failures remain concrete upstream findings. It created no signed acceptance, activated no library and executed no candidate/model code. A fresh GUI pull is the authoritative activation test.

`ki_tree.py` now accepts only bounded, physically traversable same-KI terminal aliases, hashes them separately without expanding tool counts and preserves legacy link-free identities. Native extraction/copy spelling is used on Windows. Chains, escapes, cycles, junctions/reparse points and mismatched physical targets fail. `ki_copy.py` and materialization check destination junctions before resolution/writes. Safe preflight and calibration overrides detach owned file aliases; calibration rejects an aliased `tools` root. Reviewer aliases expose only redacted/filtered copies. Independent review reproduced and confirmed fixes for junction writes and calibration writes through aliases. Old malformed quarantines were not repaired or re-enrolled.

The fifth GUI retry of official main `889a6e70332e31b21911efb0a08ac2fa2a067e03` completed all 127 package checks: **110 passed, 17 rejected**. Native Windows link extraction and exact official Windows-guidance authentication succeeded. The candidate remains quarantined at `D:/GeoForge-Model-Tests-20261010/ki-updates/quarantine/2356a31713e0`; no new library was activated. SHAW/DSSAT have stale tool declarations, VIC/WRF_Hydro lack the structured preflight report, and the other failures include missing descriptors, validation contradictions and KI-kind/template mismatches. The [handoff](KI-PUBLISHED-VALIDATION-HANDOFF-2026-10-10.md) records every affected package and the server-agent work order.

Final combined regressions: **522 passed, 1 POSIX-only skip, 2 subtests**. A subsequent presentation-only change passed **29 update UI tests** and was verified in the browser. The [GUI evidence manifest](D:/GeoForge-Model-Tests-20261010/gui-test-report.json) links the screenshot and complete candidate report. Fresh-project runtime verification, model execution, native output reading and scientific E2E remain blocked, not passed. The next steps are to reconcile the remaining package contracts through KDT, repeat the pull/activation, and then test fresh projects. No push, release build, release upload or KI-source edit was performed.

## DSSAT setup tracer: finalize runtime bindings before projection

The next app-only slice addresses a generic ordering defect found while preparing the DSSAT retry. Built-in GUI and CLI setup previously materialized and enrolled the KI with the bootstrap interpreter, then selected a workspace virtual environment and installed shared helpers. `KISSPATH_PYTHON_ENV/bin/python` is projected to the selected executable, so the KI could retain an old literal while `kiss.toml` named the new environment. The integrity guard correctly refused silently rewriting that active copy on retry. Agent setup had the same early-projection seam in `setup.prepare`.

Local implementation now uses one `setup.prepare_python` boundary in agent preparation, built-in GUI setup and CLI initialization. A fresh default workspace selects its managed environment first; explicit CLI interpreters and custom environment bindings are probed without automatic recreation. An active KI retains its exact saved interpreter. Missing, malformed or redirected saved configuration, including omitted root/Python fields, fails before a fallback probe or projection. Default environment symlinks/reparse points cannot enter the automatic recreation path. The shared helper binding is finalized and saved before active KI projection/enrollment; Python/helper failure leaves a fresh active KI absent. Existing helper copies are reused only if a private projection matches their actual relevant bytes, and a mismatch is preserved and reported rather than overwritten. Active KI drift still requires the existing verified adoption workflow.

The regression began with **8 failures before the fix** across GUI/CLI and bundled/snapshot sources. `test_setup_projection_binding.py` now contains **35 passing tests** using real temporary virtual environments, actual token projection and harmless native preflight processes; acquisition and pip/network work are replaced by narrow fixtures. Cases cover first setup, repeat setup, agent preparation followed by the built-in route, exact existing interpreter preservation, failures before enrollment, cached helper mismatch, explicit/custom environments, missing/malformed configuration, root redirection and frozen-host path selection. The final focused binding/Stop run passed **114 tests with 1 POSIX-only skip in 31.54 seconds**. This includes existing saved-binding/Stop regression files; counts overlap earlier results. An independent read review approved the bounded implementation without a remaining blocker.

This does not supply DSSAT's mandatory China cultivar files, resolve its native `MODEL.ERR` lookup, establish a universal backend, or claim a completed model run. The recorded prior native installation is under `D:/GeoForge-Uploaded-Cases-20261004/cfdb57c/geoforge-workroot/dssat`, not the empty installation shell selected in the October 9 project. Fresh GUI verification and scientific E2E remain separate live acceptance steps. No model KI bytes, mandatory requirements or KDT gates were changed by this slice; no push or release was made.

## Setup and paths tracer: real GUI follow-up

Evidence directory: `D:/GeoForge-Setup-Tracer-20261010`. These are local source changes, not a compiled or uploaded release. Model operations were requested through the GeoForge GUI using DeepSeek; independent filesystem audits and application regression tests did not launch additional scientific runs.

### Completed application changes

1. **Finalize the runtime before projecting the KI.** The saved interpreter and shared-helper paths are chosen first, then the KI is materialized and enrolled. Existing active KI/runtime bindings are preserved and checked rather than silently rewritten.
2. **Adopt the complete selected software distribution.** Explicit existing-installation selections are handled by the host before the agent. Nested executables keep sibling data/support directories. Both built-in GUI and CLI existing-installation routes avoid a new acquisition/build. Placement is recorded separately from verification; a directory link is not a readiness claim.
3. **Run preflight in a retained private copy.** The original and execution-copy KI digests, runtime binding and full output are retained. API, CLI and handoff instructions use the common host preflight route. Known direct launches against the protected KI are rejected. This is not an OS sandbox: arbitrary same-user subprocess wrappers still require post-run integrity checks. Full preflight output is retained even when the UI shows only a bounded tail.
4. **Reject unresolved execution paths before approval.** Project data-tool arguments/cwd containing unresolved `${...}` placeholders are rejected rather than passed literally. Supported plan environment expansion remains available. The existing output-only write boundary stays intact; exact reference-case staging belongs in a fresh `outputs/` directory. Locked diagnostic files now produce recoverable read errors, and terminal setup failures no longer retain the initial pending-verification message.

Core integrated regression result: **670 passed, 1 platform-specific skip, 40 passing subtests** in 119.98 seconds, recorded in `setup-tracer-regressions.xml`. A separate project-path suite passed **48 tests with 1 platform-specific skip**, recorded in `project-path-regressions.xml`. Focused/independent reruns overlap these counts and are not added. Two older CLI Flow wrapper fixtures now obtain actual harmless project-verification receipts before dispatch; no execution guard was bypassed to make them pass.

### DSSAT GUI evidence and remaining boundary

The older port-8792 test process established that a complete distribution and saved venv can run native DSSAT. Its private smoke run produced `Summary.OUT`, but the mandatory China cultivar library was absent and the stock KI's Windows launcher had additional executable/model-argument issues. Later scratch files appeared inside that attempt's protected KI, so integrity correctly blocked readiness. That attempt was preserved; it was not repaired or re-enrolled to manufacture a pass.

A fresh port-8793 process loaded the subsequent host fixes, with file hashes recorded in `server-v3-source-hashes.json`. In a new `workroot-v3/dssat` workspace, the host linked the complete selected `DSSAT` package before DeepSeek ran. The first real isolated preflight retained **19,808 characters and 30 parseable structured checks**. The original KI remained intact and its saved interpreter/runtime fingerprint matched the execution evidence. The selected external executable still matched the earlier SHA-256; a complete before/after external-tree inventory was not available.

This fresh run exposed a narrower path gap: the host knew the installed package at `binaries/DSSAT`, but did not initially discover the KI's workspace-root `DSSAT` expectation. The checker uses a local `check_executable(path, ...)` API that the static declaration reader did not recognize. DeepSeek repaired the workspace alias during this attempt; the host-side generic correction is tracked separately below. The final GUI preflight still refuses readiness because the four authoritative China cultivar files are absent. They must be supplied with provenance; stock files must not be renamed, coefficients fabricated, or mandatory checks downgraded to obtain a pass.

Independent final audit of attempt `4c1230e686ff`: **21 critical checks pass; 5 critical checks fail** (the China directory plus its four cultivar files); four advisory project-data checks also fail. The full 14,892-character report parses. Binary/startup, `MODEL.ERR` and six imports pass; this is not certification of every manifest dependency or a crop simulation. Active KI and runtime identity remain unchanged. The job is `waiting_for_user`, preflight return code is 1 and readiness remains false. Native startup generated four files only in retained scratch. `dssat-setup-v3-result.png` captures the actual GUI state.

### CRHM reference-case evidence boundary

The fresh CRHM installation passed its actual preflight and manifest checks. Project `6253b1b2b628` then obtained a separate authenticated exact-project verification receipt; the shared installation's pass was not substituted for it. This validates local project binding, not reviewed upstream-to-Windows adaptation derivation.

The initial native setup smoke produced 26,280 hourly data rows and final reference quantities within their declared tolerances, but its timestamps were eight hours earlier than the shipped expectation and it contained 56 infinity values across diagnostic variables. The strict KI runner rejects nonfinite output; neither timestamps nor values were repaired. The Windows branch's runner contains a process-local `TZ=UTC0` adaptation that the selected main-derived catalogue runner lacks. The fresh project plan therefore explicitly compares an unchanged baseline against a separate `TZ=UTC0` diagnostic using identical staged input bytes and separate outputs. It must report native reader/figure results and any failed acceptance honestly. The shipped observations file is meteorological forcing, not observed discharge or SWE; no calibration score or observed-data validation follows from this reference case.

Full current-main activation remains a separate failed publication test (110 accepted, 17 rejected). These model tests use the explicitly selected, previously enrolled catalogue; they do not claim that the whole latest main bundle was activated or all 127 models passed.

The first fresh-project execution successfully staged the two source files with authenticated receipt `CRHM_20261010T231013_51d6e0`: PRJ 5,893 bytes, SHA-256 prefix `6aa62239`; OBS 1,923,876 bytes, prefix `f1611bc7`. An independent audit compared complete hashes with the shipped manifest. Before native launch, API argument containment rejected the declared shared engine: its file symlink resolves to the prior external installation, outside the project's binary role root. This was an application path boundary failure; no new project native output, parsed CSV or figure existed at that point. A valid staging report did exist despite one contrary sentence in the agent's summary. Agent prose is not execution evidence.

Review also caught `TZ=UTC0` mentioned only in plan prose, without the structured `env` field. The GUI replan now contains the actual environment binding; it must retain the explicit verified executable argument and wait for the host fix. Existing signed-plan and source-integrity gates remain in force. These findings distinguish three separate items: a host runtime-reference bug, an agent planning omission, and scientific output acceptance still to be tested.

### Follow-up fixes from the real attempts

- **Expected software location:** `runnable.declared` now recognizes a statically proven local `check_executable` pattern, including the actual DSSAT declaration form. It checks the helper's file/executable test shape and excludes shadowing, rebinding, decorators and ambiguous arguments; it does not execute candidate code. `place_where_the_ki_expects` guards every destination before creating directories, links or copies. Outside-workspace/protected-KI targets, redirected parents and conflicting entries fail without replacing existing files. A Windows short/long parent-name regression was corrected. The final focused set passed **44 tests** and independent review approved the slice. This does not manufacture a missing suffixless executable or change external package filenames.
- **Verified shared executable arguments:** new `runtime_arguments.py` supplies the common API/CLI path boundary before launch. An external native executable is permitted only through a recognized named executable option, the selected model's binaries role, and its exact declared spelling and resolved file target. This is a file capability, not a grant to the installation directory. Undeclared files, positional external references, output paths in shared software, sibling files, bare escaping aliases, interpreter targets and wrong-model/runtime bindings remain rejected. `project-runtime-preflight-v3-declared-runtime` receipts sign the declaration-to-target mapping and recheck it after verification. Old receipts become stale, so the normal GUI verification flow obtains fresh evidence instead of editing or deleting receipts by hand. This pins path/target identity, not binary contents or an atomic lock against same-user mutation.

Both slices received independent review with no remaining blocker. The runtime owner's final batch passed **119 tests with 11 existing platform skips**; older preparation and multi-KI fixtures were migrated to explicit native declarations before real verification and named `--binary` arguments, retaining their original wrong-model/runtime/output assertions. No guard was mocked or relaxed. These counts overlap earlier regression runs. The owned port-8792 test process was restarted with these frozen changes; `server-v4-source-hashes.json` records the loaded source candidates. Other desktop servers were left running.

The project-authored independent checker also required GUI review corrections: finite-count checks initially always passed, failed reports returned zero, minute-only expected timestamps were compared with seconds-formatted strings, malformed interior timestamps could be skipped, and uniform row width was not compared with the header width. These are agent-authored test-harness defects, separate from the shipped CRHM KI. The reviewed replacement must preserve raw evidence, use parsed timestamp comparisons, require zero malformed/nonfinite values and return a failure for failed strict acceptance. A diagnostic figure never substitutes for that acceptance.

Final combined regression on the frozen host changes: **818 passed, 11 platform skips, 40 passing subtests** in 200.14 seconds (`final-path-regressions.xml`). The 105 warnings are Python venv deprecations. This run supersedes the earlier integrated count for its selected files; overlapping owner/reviewer results are not added.

A separate clean GUI placement test at port 8794 used `workroot-v4/dssat`. Host record `existing-placement.json` (job `adb40403173145c59565a9433b17c8e1`) shows both the complete distribution link and workspace-root `DSSAT` alias before DeepSeek ran. Initial preflight `33660cf37e8e` passes the binary, executable startup and `MODEL.ERR` checks; the source KI stays intact, generated files stay in scratch, and the full report is retained. Five China-asset checks and five imports in the newly created venv still fail. This bounded placement test was intentionally stopped through the GUI after the path proof; it is not a completed setup or crop run. `dssat-host-placement-v4.png` records its final cancelled state.

The longer CRHM plan subsequently hit the provider's response-length limit. The app's existing two-document `write_plan` support was available, but the agent's compressed proposal omitted typed project-data bindings and was correctly rejected. No guard was loosened. The live workflow was split into two phases: (1) short approved native baseline/TZ runs using the already staged inputs; (2) separately bind readers, figures and the independently reviewed checker to the actual retained outputs. The source-reviewed checker v4 digest is `5bd4c002912fb1d7b84fcb71e4ce7f1fd16924f9843368b51bba7132533f577b`; later generated variants are not implicitly approved. Planning success, tool reports and scientific acceptance remain separate evidence.

### CRHM native comparison on the corrected host

The normal GUI flow invalidated the old project receipt and completed a fresh real preflight. Authentic v3 receipt attempt `fa38306400cb4e0ea4108f3910da16d8` binds the selected CRHM file link to the exact existing external installation target. Preflight `c19b373ad06e` retained 16,138 characters including the full structured report; source/copy KI digest and saved runtime remain current. Both native runs then launched through the explicit declared `--crhm_exe` argument, proving the corrected path boundary in the live app.

| Independently measured raw output | Baseline | Approved `TZ=UTC0` diagnostic |
|---|---|---|
| Native data rows / columns | 26,280 / 272 | 26,280 / 272 |
| First timestamp | 1972-12-31T17:00 | 1973-01-01T01:00 |
| Last timestamp | 1975-12-31T16:00 | 1976-01-01T00:00 |
| Nonfinite numeric cells | 62 / 7,121,880 | 0 / 7,121,880 |
| Final `basinflow(1)` | 0.07 | 0.07 |
| Final `basingw(1)` | 0.04638258 | 0.04638228 |
| KI runner / host validation | exit 3 / failed | exit 0 / passed |

Baseline receipt `CRHM_20261010T233441_7770f1` and diagnostic receipt `CRHM_20261010T233510_958a4b` are authentic and bind the same approved plan. The PRJ and OBS bytes remain unchanged. Baseline raw output is retained at `outputs/badlake/crhm_output.txt.8238e7ba56b841c7b384d1a72008d62d.pending` (SHA-256 prefix `0a3733f0`); it was not promoted or repaired. Successful diagnostic output is `outputs/badlake-tz-diagnostic/crhm_output.txt` (prefix `565cd8`). The baseline's 62 nonfinite cells are independently counted in `net(2)` (4), `netD(1)` (24), `netD(2)` (24), `hru_evap_PT(2)` (1), `hru_evap_PT(1)` (4) and `net(1)` (5). The earlier setup smoke's 56-count observation must not be substituted for this fresh project result.

The approved structured plan contains `TZ=UTC0` only for the diagnostic; the captured/reviewed execution code applies the approved environment and the KI subprocess inherits it. Run receipts do not separately capture the actual child environment, so this is signed-plan plus execution-code evidence, not direct environment telemetry. The diagnostic satisfies the listed native reference criteria. It remains an explicitly configured run; no permanent KI adaptation was silently applied, and native success alone does not yet establish reader/figure completion or observed-data validation.

### Shipped reader and figures: real GUI completion

The approved four-step follow-up executed both shipped KI readers and plotting tools. Baseline reader receipt `CRHM_20261010T234410_e48600` records successful tool execution but failed output validation because the original nonfinite values are retained. Diagnostic reader receipt `CRHM_20261010T234433_af2d4e` passes. Plot receipts `CRHM_20261010T234454_55578d` and `CRHM_20261010T234500_93111f` pass their file-output checks. Independent verification authenticated all four receipts and matched every recorded output hash. These execution checks alone do not certify the scientific meaning of every plot.

Both readers produced CSV and NetCDF under `outputs/badlake-analysis/{baseline,tz-diagnostic}/parsed/`. An independent all-row native/CSV comparison found all 26,280 timestamps and 271 variable names aligned, no malformed rows, and exactly 62 baseline nonfinite cells versus zero diagnostic cells. The shipped reader explicitly serializes CSV to six significant digits (`parse_crhm_output.py:199`): every finite numeric difference is explained by that serialization, with zero unexplained differences. The diagnostic's largest absolute rounding difference is 0.005; relative rounding approaches 5e-6. This is not byte-exact numeric export, and an independent 1e-6-relative equality criterion can legitimately reject it. Do not silently relax that criterion or describe the CSV as full-precision preservation.

The diagnostic SWE figure, `outputs/badlake-analysis/tz-diagnostic/plots/swe_timeseries.png`, was visually inspected: 1,800 by 750 pixels, three HRUs, correctly labelled SWE in millimetres and explicit `TZ=UTC0 diagnostic` provenance. The baseline figure retains its failure label. Each plotting invocation also generated four ancillary images. One concrete KI bug remains: `plot_crhm_results.py:76` selects twelve `*outflow*` variables whose native units are `mm*km^2/int`, but line 109 labels them `m3/s` without conversion. The discharge figures are retained as evidence but must not be presented as correctly labelled discharge. Repair belongs in a reviewed KDT KI change, not an unrecorded project override.

The GUI also exposes a publishing mismatch: chat images and project image panels accept `artifacts/` paths, while DeepSeek wrote literal Markdown references to `outputs/`. The actual PNGs exist. The documented supported route is an unchanged published copy under `artifacts/`, with its corresponding Markdown path. Silently displaying unsupported image Markdown is a remaining usability gap; neither the scientific output nor the artifact-serving boundary should be rewritten to hide it.

The two independently reviewed v4 checkers then actually ran through the GUI's typed `run_project_data_tool` route. Reports are retained under `artifacts/badlake-analysis/check-baseline.json` and `check-tz-diagnostic.json`; both return strict failure (exit 4). Baseline receipt `CRHM_20261010T234856_edccc0` retains five failed checks: first/last timestamp, sampled native/CSV equality and both nonfinite counts. Diagnostic receipt `CRHM_20261010T234858_0bafab` fails only `native_vs_csv_first_middle_last_ok`: the serializer's six-digit rounding exceeds the unchanged 1e-6 comparison. Its native row count, time span, finite-value requirement and final reference quantities all pass. Therefore the run/reader/figure workflow executed end to end, but strict native-to-CSV equality is **not** passed. The reports and criteria were not changed to manufacture acceptance.

The live DS workflow still needed intervention: oversize proposals, missing argument/schema wrappers, a stale question after a successful plan write, and an attempt to approve an unchanged plan without current-turn resubmission. The normal guards rejected these attempts. Explicit compact proposals and correct `write_plan` wrappers completed the existing approval route; no fabricated registration, manual approval-state edit or guard bypass was needed. This is a remaining agent-harness usability issue, distinct from the repaired setup and executable paths.

The independent audit is saved at `D:/GeoForge-Setup-Tracer-20261010/crhm-reader-audit.json`, including all-row comparisons, exact rounding measurements, six authenticated reader/plot/check receipts and output hashes. It also identifies a checker-report serialization issue: the baseline v4 JSON contains nonstandard `-Infinity` tokens. The host correctly rejects its artifact structure in addition to the deliberate exit-4 failure. The diagnostic report is valid JSON. Preserve these original reports; a later checker repair should encode nonfinite evidence explicitly without changing the raw data or failure criteria.

A final one-step GUI approval rerendered the existing diagnostic CSV with the same shipped plotter into `artifacts/badlake-published/` (receipt `CRHM_20261010T235048_004349`, exit 0). The SWE image now renders in chat; no native model, reader or checker was rerun. This also exposed an app presentation gap: automatic artifact attachment appended all other newly generated PNGs even though the agent explicitly selected only SWE and warned that the discharge chart was not qualified. The discharge chart must retain that warning; automatic attachment should respect explicit figure selection/qualification. The final chat display uses the existing SWE artifact and preserves the strict checker failures.

The publication receipt is `execution_status=succeeded`, **validation=warning**, not a passed scientific run: the agent labelled the plotting step `kind=run`, so the host correctly found no numeric output. Its PNG decode/existence checks all pass. A later text-only summary then triggered `flowrun.py`'s no-new-receipts message, including the overbroad assertion that described outputs do not exist. The files and earlier signed receipts still exist; this message confuses current-turn execution, current-plan acceptance and historical artifact existence. Do not delete that diagnostic or claim the project is fully complete. `crhm-e2e-result.png` records the real final UI, including this remaining reporting issue; the actual SWE PNG is separately available under the project artifact path.

### Next tracer boundaries

1. **Update durability:** portable adaptation derivation/reuse and stable identities are implemented in the bounded slice below. Complete the live update -> fresh project -> exact verification -> reference run sequence. Source/path tests do not claim the full latest-main bundle activated; publication validation remains a separate gate.
2. **Mandatory DSSAT payload:** supply the four authoritative China cultivar files through a pinned, documented package/download. The fixed host paths and native startup do not replace these inputs.
3. **CRHM KI output contract:** apply the process-local timezone requirement, preserve adequate CSV precision and derive plotting units from the native output through the existing KDT review/adoption route. Do not copy old KI trees over updated main or reinterpret existing failed receipts.
4. **Agent workflow:** shorten/schema-bind plan generation, explain incomplete submissions accurately, prevent stale planning questions from confusing the next approval and publish figures to supported artifact paths. These are follow-up usability fixes, not reasons to weaken signed plan, runtime or KI-integrity gates.

## T5 tracer: stable bindings and portable repair reuse (2026-10-11)

Implemented and independently reviewed in local source. This is a bounded native-runtime lifecycle change, not completion of T2b2/T6/T7 or a release.

### Stable relevant identities

`helper_identity.py` inventories actual portable shared-tool bytes with contained-tree checks. `setup.prepare_common` keys a new immutable helper copy by those bytes, materialization policy and relevant runtime bindings, rather than by the repository commit alone. Unrelated repository commits preserve the helper location. A valid legacy bound cache is retained only after exact projection comparison; a changed source/runtime/policy produces a separate copy for a fresh workspace. A changed helper cache cannot be silently overwritten under an active KI, and a tampered existing cache fails before configuration mutation.

`software_verification.identity` schema 2 binds the selected KI bytes, effective manifest and portable helper source identity. Whole-library hashes and unrelated component labels no longer invalidate every model. Real relevant changes still invalidate readiness. Existing schema-1 success requires one ordinary recheck. The separate runtime fingerprint still binds configuration values and declared executable paths/targets; this slice does not attest to arbitrary package or executable bytes changed in place.

### Portable repairs and project paths

`ki_adaptations.py` retains authenticated portable sources and signed lineage outside the KI. Its context includes the upstream content, effective recipe, native platform/architecture, checked prepared-helper source identity and projection policy. Fresh snapshot projects can reuse an accepted repair only for that exact context, with a current KDT report. Each new project receives its own resolved paths and still requires its own preflight; no readiness is inherited. Existing project KI/config/helper bindings remain untouched.

When upstream, recipe, helper or policy context changes, the host preserves the accepted old repair as reconciliation evidence and uses the new source without blindly replaying the repair. Effective-recipe edits are rejected for reusable registration in this slice because setup still resolves the upstream recipe. Missing authentic lineage or unmarked/legacy helper proof allows only project-local repair. Imported/non-snapshot legacy preparation does not gain portable provenance automatically.

The existing three-reviewer investigation now freezes the portable source and lineage before review. A portable draft must pass KDT before materialization, and its exact materialized runtime candidate must separately pass KDT. Both reports, candidate bytes and saved configuration are rechecked before explicit adoption. Runtime activation comes first; reusable registry publication is last. Failed adoption publishes no new authority. Failed registry publication after local adoption is reported as local-only, with the failure retained. Approval is revoked and preflight becomes pending after adoption. Provider prompts and the English/Chinese investigation UI distinguish these scopes across API and CLI providers.

Independent review prompted additional checks of the actual bound helper cache, rejection of unsupported recipe changes, and path scanning across Python string literals, shell files, textual cases and supported text encodings. XML closing tags and Python division are not treated as machine paths. This remains bounded static checking, not proof that arbitrary tool code can never construct a local path dynamically.

### Regression evidence

- Combined lifecycle/runtime regression: **638 passed, 1 skipped**, 105 existing venv deprecation warnings, in 229.55 seconds. The skip is a POSIX special-file fixture on Windows. Report: `D:/GeoForge-Setup-Tracer-20261010/update-durability-final.xml`.
- Final path-scanner hardening and real Handler integration fixtures: **54 passed** independently after those last edits. These overlap the larger run and are not additive. The four Handler fixtures exercise accepted repair reuse, per-project paths, real harmless preflight, unrelated/relevant updates and tamper rejection.
- Frozen investigation/adoption tests use explicitly synthetic provider/KDT reports where appropriate; they prove host workflow and gating, not an actual LLM review or scientific model result.
- The later updater-routing slice passed **81 tests and 2 subtests** including the component suite; report: `D:/GeoForge-Setup-Tracer-20261010/update-guidance-routing.xml`. Its independent provenance-only rerun passed 38 tests. One existing Handler fixture needed its normal `workroot` attribute after the new effective-manifest lookup; no production guard was relaxed.

### Real GUI setup recheck

The owned GUI at port 8795 loaded the selected catalogue `e3ed93f067f2f2693294d0ff5d1f98ad` and reopened the saved CRHM project. Its former identity correctly became stale. The GUI's **Recheck with agent** action (DeepSeek API selected) completed the ordinary host early preflight and showed **Verified on this machine / No action needed**. The early pass required no new provider-authored repair and is not a new simulation.

Before/after audit files `v5-crhm-before-recheck.json` and `v5-crhm-after-recheck.json` under `D:/GeoForge-Setup-Tracer-20261010` show unchanged KI digest, saved configuration hash, helper location and helper file inventory. The helper remains `workroot/crhm/ktc/e059a95a3a3e`; the selected venv and declared external engine remain bound. Attempt `728923ce0497` retained the real preflight output in `workroot/crhm/.geoforge/preflight/`. Screenshot: `v5-crhm-recheck.jpg`.

### Live update routing defect

The first GUI retry of official main commit `889a6e70332e31b21911efb0a08ac2fa2a067e03` stopped at Windows-guidance authentication, before any package checks. Quarantine `41128d497fc7` retains that exact failed attempt. The displayed **Invalid Git object size** was an app defect: missing baselines for CaMa_Flood, Lohmann_Routing and VIC invoked the narrow official-guidance authentication route, which looked for Git objects inside an unpacked snapshot. Its specific unavailable-object exception was then accidentally caught as a generic integer-conversion error.

The reviewed fix separates the selected snapshot/input/proof identity from the optional application-checkout Git object store and preserves the original error. The checkout supplies untrusted bytes only: the fixed official HTTPS commit/tree anchor, object hashes and exact path membership still establish provenance. No KI is enrolled, no failed guard is bypassed, no extra object fetch is added. A packaged installation without the required objects or a current signed guidance proof still fails explicitly. This is a remaining distribution limitation, not a completed packaged-desktop solution.

Only the owned test server was restarted with the reviewed updater/runtime source; `server-v6-source-hashes.json` records the implementation files used for the GUI retry. The current catalogue and saved project remain selected until all update checks succeed. Full latest-main activation and a fresh post-activation scientific run must be reported separately from the setup recheck above.

### Final project-layout correction

A final independent integration review caught a genuine defect missed by the earlier isolated fixtures: three investigation boundaries loaded a project model's configuration through the standalone-installation parser. The configuration file lives at `project/models/<KI>/kiss.toml`, while its `kiss.root` correctly names `project`; the standalone parser expected the containing model folder instead and would reject a real portable repair.

The corrected `_project_runtime_config` uses the exact target validation and strict read-only parser from `project_verification`. Source capture, portable-lineage capture, KDT projection, `can_apply`/adoption checks and registration all use that same interpretation. Invalid configuration can still be captured for local diagnosis but cannot supply helper access or reusable repair authority. Configuration files are never repaired on disk, a foreign root is not normalized, and ancestor configurations are not borrowed. The corrected full investigation fixture uses `project_paths.model_config`, and a separate regression now runs the actual GUI Handler workspace -> investigation -> three fixture reviewers -> two KDT gates -> adoption -> fresh GUI project reuse chain. Native readiness remains pending until a fresh preflight.

The owner passed **55 investigation tests**, including wrong/missing roots, missing required fields, ancestor fallback and configuration changes at verification/adoption. The independent investigation/GUI review batch passed **60 tests**, with no remaining blocker. Root's final integration batch passed **195 tests** in 104.00 seconds across investigation, GUI investigation, GUI adaptation lifecycle, adaptations and provider review tests. Report: `update-repair-project-binding.xml`. These overlapping results supersede the earlier investigation fixtures rather than adding to their counts. The owned test server was restarted again with the corrected configuration reader; `server-v7-source-hashes.json` records its final source inventory. No installed release was changed.

### Final live pull result and next bounded fix

The GUI retry completed against main `889a6e70332e31b21911efb0a08ac2fa2a067e03`, reusing the cached archive. The corrected Git routing reached the actual guidance comparison, then stopped with **Selected guidance differs from official Windows source: kiss/manifests/APEX.yaml**. It ran **zero package checks** and activated nothing. Quarantine `77a7a550fe56` and `v6-update-report.json` retain the attempt; `v6-update-blocker.jpg` shows the GUI result. CRHM remains verified after reopening (`v6-crhm-reopened.jpg`). The earlier 110/17 publication result describes a different attempt and must not be substituted for this one.

Independent read-only analysis found a legitimate composition with missing legacy provenance. The snapshot's generic APEX recipe is 1,484 bytes, SHA-256 prefix `8c116ddb`, exactly matching local Git objects for main `8352acb` and `889a6e`; the Windows `1136e56` version is 2,348 bytes, prefix `eda538ce`. Its 2,040-byte Windows-specific recipe, prefix `44c0b730`, is reproduced byte-for-byte by composing the Windows recipe with the main recipe using the recorded overlay mechanism. The APEX KI's existing host baseline is intact. These facts explain the bytes; they do not supply the missing signed composition authority. This legacy snapshot has no publication envelope or overlay source proof, and its older checkout-bound guidance receipt cannot simply be transferred.

The next tracer should separate raw Windows guidance from previously composed library content. Authenticate both raw Windows and incoming main inputs, record their immutable identities plus the composition policy/output hashes, and replay the composition before signing/activating it. Legacy migration needs newly authenticated inputs and exact comparison of all selected outputs; unsigned marker fields or accepting whichever raw branch happens to match are insufficient. This also needs a packaged-desktop source/proof path that does not depend on a development Git checkout. The current fixes preserve the old library while this contract remains unfinished. This attempt establishes an app update/migration gap, not a model runtime failure.

## T5 follow-up: raw platform inputs across repeated updates (2026-10-11)

The updater now obtains Windows metadata as a separate immutable component. The official Windows commit response anchors its Git tree. A development checkout may supply object bytes, but every object and selected path is checked against that anchor. Packaged installations can obtain the same evidence through a bounded recursive tree response and immutable raw-file downloads without requiring Git. Only installation notes and recipes are retained; model tools, model membership documents and shared helpers are not copied from Windows over main. Model membership is recorded as tree evidence instead of fabricating `SKILL.md` files in this metadata cache.

`ki_guidance_composition.py` combines those raw inputs with the freshly extracted main archive exactly once. The signed publication origin includes both source commits, the raw component identity, main archive/source hashes, composition policy, and input/output file hashes. It checks raw evidence before and after composition, preserves generic main metadata and existing main platform files, and checks every generated output. An existing merged snapshot is never reused as raw input. True concurrent recipe conflicts still refuse activation.

The update fast path resolves Windows guidance before deciding that main is unchanged. A Windows-only change therefore triggers validation even when the composition adds no files. Refusal identities also include this component, allowing a repaired Windows source to be retried. Every registered active model/data KI is checked independently before replacement; a new official component cannot conceal an altered current KI. An unchanged old KI without a guard baseline goes through fresh publication validation rather than being silently enrolled or labelled already verified.

Independent review added Python 3.11 Windows junction/reparse checks to the metadata cache and fixed the integrity check for KIs whose recipe exists only in the shared manifest directory. Rejected candidates remain separate from the active catalogue; existing project configuration and helper bindings are preserved. These checks establish update provenance and package acceptance only. They do not confer native setup, scientific validation, KDT authoring approval, or cross-platform runtime support.

### Follow-up regression evidence

- The integrated raw-component, composition, updater, quarantine, shared-component and publication suites passed **220 tests and 2 subtests** in 33.22 seconds. Report: `D:/GeoForge-Setup-Tracer-20261010/raw-guidance-integrated.xml`. Authenticated fake HTTPS/Git objects exercise the real composition and signed-origin contracts; isolated KDT fixtures do not establish model execution.
- Independent transport hardening added an HTTPS-only redirect handler to the existing verified TLS/proxy route. Its **26 tests** exercise urllib's actual redirect dispatch and bounded responses without a live network. The combined transport/updater/component batch passed **66 tests and 2 subtests**; overlapping tests are not added to the first count.
- Independent reviews found no remaining blocker in the raw component or deterministic composition boundaries. The raw suite's 40 cases include actual Windows junction tests on the bundled Python 3.11, and the wrapper suite's 29 cases cover changed/undeclared outputs, existing-main preservation and both source identities.
- Only the owned GUI test server at port 8795 was restarted. `server-v8-source-hashes.json` records its frozen updater and runtime files. The fresh pull was initiated by the GUI's **KI updates → Check again** control; its outcome is recorded below separately from unit tests.

### Live authenticated component

The live GUI created raw component `64ba4da3a9fa909065e2e1e48fe8f0f0b10eb7cfe3d3380ebb91da9802749a2b` for Windows commit `1136e56e6bf27b8361d7495a80904c31529afd59`. An independent read-only audit authenticated its current signed proof: 127 model membership records and 192 metadata files, totaling 378,278 bytes. Content inventory SHA-256 is `1fe1d05b19c4f8480e3c499f5d03af53b9a7db8ad7482f306987ac766cb511f2`. APEX's 2,348-byte generic recipe, 2,490-byte Windows recipe and 4,283-byte notes match the official Git objects byte for byte. No `SKILL.md`, model tools or source code was materialized in this component. The audit neither altered the candidate nor ran a model.

### Completed GUI pull and remaining gate (2026-10-12)

The attempt begun at 23:59:41 on October 11 completed after midnight. It cleared the previous APEX/raw-guidance error and reached `package_validation` against main `889a6e70332e31b21911efb0a08ac2fa2a067e03`. Of 127 model packages, **106 matched intact existing baselines, 17 passed fresh publication checks, and 4 were rejected**. The 106 remain `unchanged_existing`; they do not acquire new KDT or native evidence. CRHM, SHAW, WOFOST and WRF_Hydro are in that unchanged group. DSSAT and VIC are among the rejected packages. Do not interpret the count as 123 fresh passes, or substitute the earlier 110/17 attempt.

Quarantine `1b6f7bc33d2f` preserves the complete candidate and report; `v8-update-report.json` and `v8-update-package-findings.jpg` preserve the current GUI outcome. Its authenticated composition records Windows source `1136e56`, main source `889a6e7`, the cached archive hash `8a373ec514a8ede5d22ae73da31994d9af14219b4f7ffc48a4750cb6ffa26213`, exact metadata inputs and composed outputs. The new provenance fields render in the GUI diagnostics.

Independent read-only triage found stale tool metadata in DSSAT and SWAT_Plus, a literal-medium wording issue in VELMA's discharge description, and an actually missing structured preflight report in VIC. The [current server handoff](KI-PUBLISHED-VALIDATION-HANDOFF-2026-10-10.md) gives exact files and required KDT corrections. No KI, scientific criteria, active snapshot, approval or guard was edited to make this pull pass.

`v8-crhm-before-update.json` and `v8-crhm-after-update.json` compare the exact CRHM KI digest, saved config hash, helper location, every helper file hash and update-state hash: all are unchanged. The earlier v5 helper inventory excluded receipt/egg-info files; those inventory-format differences are not source changes. Reopening CRHM during the real update still showed **Verified on this machine / No action needed** (`v8-crhm-during-update.jpg`). The final update activated nothing, and the existing project remains usable.

This completes the bounded raw-guidance/composition fix and its real GUI reproduction. It does not complete the full latest-main activation → new project → verification → scientific reference run sequence; that next sequence remains behind the four package corrections. No compiled release or push was performed in this follow-up.

## T5/T7 follow-up: current checks for every incoming KI (2026-10-12)

Review of the 106 `unchanged_existing` rows found a remaining evidence gap. Their exact bytes and host baselines were intact, but that did not establish acceptance by the current KDT publication rules. The updater now performs current publication validation for every package in a candidate snapshot. Prior registered source integrity is checked separately, including when upstream has changed, so fresh validation cannot hide an unreviewed local edit. Existing projects and their native runtime receipts remain pinned and are not rewritten.

Publication policy `official-published-ki-v2` and snapshot contract `all-packages-current-published-kdt-v1` invalidate the earlier update fast path. Both snapshot sealing and loading require complete package coverage, exact digests, `PublishedPackageAccepted` rows and current signed reports bound to the same official origin. A legacy baseline, a stale report, or a report copied from another origin cannot authorize the new snapshot. The current-publication requirement also applies to catalogue enrollment. This changes package acceptance, not native or scientific verification.

The GUI now reports current-attempt stages and actual completed package checks in English and Chinese. Starting a new attempt clears old errors, findings, counters and candidate identity; refusal caching remains private. A failed retry cannot show the previous commit as the new attempt's commit. Terminal and interrupted states clear their running progress. Counts say **checks finished**, not passed. Active component information remains explicitly labelled as the active library while a candidate is being checked.

The final integrated acceptance/update/progress/boundary suite passed **212 tests and 2 subtests** in 32.69 seconds (`current-publication-final.xml`). The earlier run had one obsolete warning-preview fixture relying on the removed bypass; its repaired fixture supplies real staged origin evidence and an explicit isolated KDT result without weakening its warning assertions. Independent review covered the update path, signed receipt/enrollment boundary and current-attempt reporting. No scientific model was run by these regressions.

### Complete fresh GUI check

The owned v9 GUI attempt started at **08:02:15 China time on October 12** and freshly checked all 127 packages from main `889a6e70332e31b21911efb0a08ac2fa2a067e03`: **110 `PublishedPackageAccepted`, 17 `PublicationRejected`, zero activation**. No unchanged-baseline shortcut remained. The same authenticated raw Windows component and composition passed. The GUI displayed real package-check counts, including 57/127 and 117/127, then a terminal rejection report without stale progress or the previous attempt's four-package finding.

Evidence: `server-v9-source-hashes.json`, `current-publication-final.xml`, `v9-current-package-progress.jpg`, `v9-full-validation-result.jpg`, and `v9-update-report.json` under `D:/GeoForge-Setup-Tracer-20261010`. Quarantine `c4a5ae135ab6` retains the candidate and full validation report. The current server handoff now lists all 17 package-contract findings. CRHM and WOFOST passed publication checks; SHAW, DSSAT, VIC and WRF_Hydro require the listed corrections. No model execution or database request was performed by package validation.

`v9-crhm-before-update.json` and `v9-crhm-after-update.json` match the CRHM KI digest, configuration hash, helper location, every helper file hash and saved update-state hash. Existing project files and library selection did not change. Current publication acceptance does not overwrite that project's separate native evidence.

The downloaded packages lack the normal authoring gate's gathered-paper evidence, so editing/adopting those KIs locally cannot be represented as KDT-approved authoring. The original authoring sources are needed for the server correction path. No literature evidence, acceptance receipt, KI source or scientific criteria were fabricated or relaxed to make the update pass. Full latest-main activation and fresh post-activation E2E remain pending those legitimate corrections.

### Activation recovery and truthful reporting

Independent review found that the updater saved `state.json` before invoking the live catalogue callback. A callback failure could therefore leave the saved selection on the new snapshot while the GUI still used the old catalogue, then falsely report that the current library was kept. Ten initial regression cases reproduced this family of failures against the previous implementation.

Activation now captures the exact saved-state bytes before validation, checks for observed selection changes before and after the live callback, and only then saves the new pointer. Callback or write failure attempts to restore the previous session without writing an old pointer over a separately changed selection. A writer that raises after replacement is reconciled against the observed pointer; an already committed update is not relabelled as retained. Failed recovery or an unreadable outcome is explicitly uncertain and prevents another update activation in that session until restart. These comparisons are not a cross-process compare-and-swap or an OS transaction.

Report-storage failure still leaves a terminal, truthful status in memory, including when failure occurs before the worker starts or after activation commits. Restart records the previous activation as history and rebuilds current component labels from the actually loaded catalogue; a historical restart warning cannot disable retries forever. English and Chinese summaries distinguish committed, restored and uncertain outcomes, report the current session separately from the saved selection, and hide unproven active-source labels when recovery is uncertain.

The bounded fault-injection tests cover callback failure before/after a partial switch, pointer write failure before/after replacement, concurrent selection changes, rollback/read failures, fast-path activation, post-commit report failure, persistent report-write failure and restart recovery. They assert pinned project/KI/helper bytes remain unchanged. The actual GUI callback still exposes per-package enrollment errors through the existing catalogue contract; a successful callback is not a claim that every KI has native verification. These regression fixtures are not a live activation of the currently rejected main catalogue.

Validation after this change: the combined suite recorded **248 passes, 2 passing subtests and one obsolete fixture failure** in 40.25 seconds (`activation-current-publication-final.xml`). That component test mocked an active catalogue without a matching saved pointer. Its corrected fixture now seeds a real accepted snapshot and changes only the saved validation policy; the complete affected component file then passed **24 tests**. The correction preserves the assertion that all checks rerun even when authenticated archive bytes are cached. Production was unchanged by the fixture repair. The owner's backend batch passed **81 tests and 2 subtests**; independent review passed **37 backend/UI tests**. These are overlapping results, not additive counts. No failing test remains unresolved.

The final owned GUI server at port 8795 uses the frozen source recorded in `server-v10-source-hashes.json`; all 18 recorded source hashes still match. The browser confirms the saved 110/17 result and the updated all-incoming-package scope (`v10-update-result.jpg`). Reopening CRHM confirms **Verified on this machine / No action needed**, its existing executable path, and the saved setup log (`v10-crhm-reopened.jpg`). `v10-crhm-preservation.json` again matches the KI, configuration, helper path/all helper files and saved library pointer against the pre-update audit. This was a reopen/preservation check, not a new preflight or scientific run. No compiled release, commit or push was performed in this follow-up.

## Maintenance evidence reuse and GUI tracer tests (2026-10-12)

The bounded maintenance path is now implemented after the three independent
reviews. It freezes and reuses unchanged published bibliography metadata, applies
one supported deterministic recipe in a KDT draft, and requires current
whole-package KDT checks plus a separate signed maintenance receipt. Scientific
definitions/evidence cannot change through this path. Ordinary authoring,
import/export and official catalogue acceptance remain unchanged.

Real GUI testing applied SHAW's one-line `total_tools: 13 -> 12` correction to
project `cd93028eda4b`, with all other files unchanged and fresh preflight/plan
review required. VIC's authenticated rejected download completed three reviews
and real KDT verification for an additive preflight-report repair; all seven
behavior fixtures passed. That candidate remains a verified draft, not an
activated library/project KI. The test exposed and fixed broken-KI selection,
silent picker errors, linked review evidence and Windows newline copying.

See [maintenance implementation and GUI evidence](KI-MAINTENANCE-GUI-2026-10-12.md)
for exact digests, evidence, regressions and remaining activation limits. These
tests do not change the saved 110/17 official update result or claim new native
scientific runs. A dedicated activation consumer for maintained rejected
packages remains separate from the completed draft/check path.
