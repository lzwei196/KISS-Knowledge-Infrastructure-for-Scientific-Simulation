# C2 checkpoint: approved KI-tool execution

Date: 2026-09-27. Branch: `mac-version`, HEAD `96ac8a5b`, building on the uncommitted C1 changes. Existing work was preserved; no commit, push, release or app rebuild was performed.

## Outcome

The direct-provider `run_ki_tool` route and CLI `run-tool` route now share one execution lifecycle in `kiss/kiss_cli/execution.py`. The codebase-design skill guided a single execution interface with local fixture tests; adapters still own their admission rules and response format.

`execute_ki_tool(...)` handles fresh Flow checks, approved environment, snapshots, exactly one process launch, observed outcome and receipt capture. It returns `ExecutionResult`, keeping the process outcome separate from receipt-writing failure and scientific validation. Permission refusal happens before launch.

No automatic retry was introduced. A failed invocation returns diagnostics to the agent, which may request another permitted attempt. This module does not change Flow stage or decide scientific success.

## Preserved adapter differences

| Concern | Direct provider | CLI |
|---|---|---|
| Tool forms | Shipped Python or declared model binary | Also trusted shell/extensionless tools |
| Arguments | Existing root/count/length checks | Existing CLI argument admission |
| Working directory | Existing project subdirectory choice | Project root |
| Tool deadline | Existing 600s default; 1–3,600s bounded setting | No tool deadline |
| Proxy | Selected provider setting applied | Existing inherited environment |
| Output | `exit_code` / `[RECEIPT]` tool response | Printed output / `[RECEIPT]` and command exit code |

Both routes retain inherited-secret filtering, framework/KI runtime paths and approved step environment. The legacy direct route with no Flow session remains untracked and cannot obtain an approved execution receipt; this refactor does not broaden it.

## Corrections made alongside consolidation

- Reload persisted Flow state, plan, inventory and approval before execution. Confirm the loaded request matches the approval and reject stale session/tool/state information.
- Capture the approval issuance at launch. A later valid reapproval cannot attach that earlier attempt to a different approval. Receipt writing uses the captured ID rather than a subsequently mutable cached value.
- Distinguish `succeeded` (exit zero only), `failed`, `timed_out`, `interrupted`, `not_launched` and `outcome_unknown`.
- Track process creation separately from output collection with `Popen`. An observation error after launch is not mislabeled as a launch failure.
- Preserve captured stdout/stderr when receipt writing fails. Report receipt failure without automatically repeating the command.
- Retain outcome and available diagnostics if cleanup fails; report unconfirmed termination rather than claiming cleanup succeeded. Cleanup waits are bounded separately from execution deadlines.
- Give each attempt a distinct log filename, preventing same-second attempts from overwriting one another.
- Resolve recorded relative input arguments against the child's working directory, including the first argument to a direct executable. Newly generated outputs are not incorrectly listed as original inputs.

New receipt fields `execution_status` and nullable `process_started` are additive. Older writer calls retain their prior shape and behavior. The legacy `binary_actually_ran` field remains boolean; new `process_started=null` distinguishes unknown launch observation from `false` for a confirmed creation failure. These observations refer to the approved entrypoint process, not proof that a nested scientific engine ran successfully.

## Files for review

| File | Responsibility |
|---|---|
| `kiss/kiss_cli/execution.py` | Shared execution interface, launch observation and evidence capture |
| `kiss/kiss_cli/api.py` | Direct admission/response adapter delegates the execution lifecycle |
| `kiss/kiss_cli/cli.py` | CLI admission/exit-code adapter delegates the same lifecycle |
| `kiss/kiss_cli/flowgate.py` | Receipt approval binding, unique logs and cwd-aware input evidence |
| `ki_tools_common/ki_tools_common/flow/receipts.py` | Additive execution-outcome fields; earlier C1 changes remain |
| `kiss/tests/test_execution_adapters.py` | 25 public-adapter cases using actual small local programs |
| `kiss/tests/test_execution.py` | 21 shared-interface cases, with injected process/recording failures |

The KI-tool lifecycle is consolidated; installation probes and the separate calibration orchestrator were not moved into it. Deeper model-child tracking/live logs remain deferred.

## Verification

No provider credentials, live DS/Kimi turns, real model installations, remote dataset transfers or scientific simulations were used. Local byte/process fixtures test execution behavior, not model science.

### Characterization before production changes

The initial 17 public-adapter tests passed against the old implementation. They characterized approval/state/step refusal, actual failed processes without retries, signed receipts, approved environment, direct timeout, CLI completion, working-directory/path restrictions and shell-tool differences.

Combined baseline:

```sh
PYTHONPATH=kiss:ki_tools_common python3 -m pytest --import-mode=importlib \
  kiss/tests/test_flowgate.py kiss/tests/test_flow_cli_wrappers.py \
  kiss/tests/test_api_handoff.py kiss/tests/test_execution_adapters.py -q
```

Result: **87 passed** before migration, and again after initial migration.

Independent review reproduced a post-launch `OSError` that the first extraction mislabeled `not_launched`. The implementation moved to explicit process-creation observation and added constructor-versus-collection regressions. Cleanup interruption/pipe-close regressions were added and corrected before the final frozen-tree verification.

### Final focused regression

```sh
PYTHONPATH=kiss:ki_tools_common python3 -m pytest --import-mode=importlib \
  kiss/tests/test_execution.py kiss/tests/test_execution_adapters.py \
  kiss/tests/test_flowgate.py kiss/tests/test_flow_cli_wrappers.py \
  kiss/tests/test_api_handoff.py -q
```

Result: **116 passed**.

Coverage includes preapproval refusal, tool/step mismatch and approved-tool drift, acquired-input checks inherited from C1, inherited-secret removal, approved environment, direct-only proxy settings, nonzero exit, real missing interpreter, timeout, interruption, unknown observation, receipt-writing failure, cleanup failure, no retries, stale state/plan, reapproval during execution, independent logs, relative inputs and preserved deadline differences.

### Final broad regression

```sh
PYTHONPATH=kiss:ki_tools_common python3 -m pytest --import-mode=importlib \
  ki_tools_common/tests/flow kiss/tests -q -rs
```

Result: **735 passed, 5 skipped, 121 subtests passed**, one pre-existing NumPy/native-extension warning, in 74.34 seconds. Permission was used for the suite's isolated localhost socket tests.

The five skips remain: two server decision-parity cases, two derivation cases needing the server ata-kdt KI tree, and one server harness-copy comparison. These are not passes and do not establish server parity.

An earlier broad run collected an older assertion while the new cleanup test was being edited (734 passed, one wording-assertion failure). The final result above was obtained after code and tests stopped changing. It supersedes that moving-tree run.

`git diff --check` passed. No compiled-app verification is implied by source test success.

## Remaining limits and follow-ups

1. **Retry-history completion policy is unchanged.** Shared final evidence still uses any bound failed historical run to block completion, even if a later attempt passes. A future change must define explicit supersession while preserving history; this checkpoint does not erase or ignore failures. This is source-confirmed, not a new end-to-end retry-completion acceptance claim.
2. **No live-provider or GUI/build acceptance yet.** DS and Kimi wrapper behavior was exercised through local interfaces, not real model conversations. C5 still needs compiled Mac checks and coordinated server validation.
3. **No process-tree monitoring guarantee.** Cleanup addresses the launched tool. Nested model processes and Windows inherited-pipe/reader-thread behavior need dedicated checks; Windows was not tested here.
4. **Receipts are observations, not model-success certificates.** Exit zero, launched entrypoint or a written receipt does not establish successful scientific simulation. Existing output validation remains authoritative.
5. **No global atomic execution lock introduced.** Fresh checks and captured approval prevent stale/new-approval rebinding; they are not a claim of immutable files or process cancellation whenever another actor changes approval.
6. **C1 manual-placement and legacy-evidence limitations remain.** See the C1 report; this work did not silently alter those policies.

Next planned module: C3 Plan Review consolidation, preserving existing consent and review behavior.
