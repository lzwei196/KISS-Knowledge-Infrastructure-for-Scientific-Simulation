# C3 checkpoint: Desktop Plan Review

Date: 2026-09-27. Branch: `mac-version`, HEAD `96ac8a5b`, building on the uncommitted C1/C2 work. No commit, push, release or app rebuild was performed.

## Outcome and ownership

`kiss/kiss_cli/plan_review.py` now owns issuance and the ordered response transaction. The codebase-design skill guided a small shared interface that removes approval choreography from the turn driver:

- `issue(...)` creates the existing review card and persists the exact display/baseline it represents.
- `respond(...)` returns `unhandled`, `waiting`, `replan` or `approved` after checking the click, preserving answers, refreshing estimates and resolving provenance.
- `input_groups(...)` supplies the same read-only input presentation to review and project status. No circular import or duplicate classification was introduced.

`flowrun.pre` consumes the result. Only `approved` enters its existing subset-job creation, binding, acquisition and execution path. `flowrun.after` calls `issue`. The execution prompt still discloses accepted recommendations separately from KI defaults.

Desktop owns this consent interaction. Shared `flow.decisions` and `flow.approval` remain authoritative for decision records and signing. No harness instruction, KI science, approval policy or review-screen redesign was introduced. The shared core was not changed by C3.

## Preserved transaction and compatibility

1. Check the current plan/inventory against the host's issued record.
2. Check the browser's displayed-card echo; older clients without an echo retain the existing pending-card fallback.
3. Read saved answers before consuming the card. Preserve genuine changed choices against the issued baseline, not today's catalogue.
4. Re-pin or refresh data estimates; material changes produce an unsigned re-review with the user's choices retained.
5. Resolve shared decision provenance and open inputs. Re-read answer history after remote refresh before signing.
6. Put the decision revision inside the hashed plan and sign through shared Flow.
7. Clear the consumed review and let the turn driver begin approved data acquisition.

Existing paths and formats are unchanged: `runs/plan-review.json`, `setup-request.json`, `.geoforge/user-answers.json`, plan/inventory and approval files. Answer namespaces, legacy migration, item binding, approval request IDs and JavaScript numeric/hash normalization are preserved. Cards loaded from disk after restart remain usable. A missing or corrupt host snapshot requires re-review; the request's embedded copy is never authoritative.

Approving an unchanged recommendation still accepts it as a disclosed recommendation; it does not claim the user deliberately selected it. There is still one plan approval including selected data, not another popup before each tool or download.

## Intentional corrections, separate from extraction

The new lifecycle tests first reproduced these failures against the old implementation:

1. **Unshown/off-menu choices could mutate the plan.** Only answer recording filtered submitted choices; earlier plan mutations still received raw values. Admission now checks the issued baseline before any mutation. Unknown IDs, hidden scientific choices, catalogue-filtered options and invalid data selections cannot change the reviewed selection.
2. **An escaping refresh failure consumed the pending card.** The request was cleared before remote work. Expected data-refresh errors now return a recoverable waiting result without consuming the review or signing/starting work. Same-click plan changes are not persisted before refresh succeeds. Genuine answers remain recorded. Most lower-level I/O errors already become changed-estimate reasons; that existing unsigned re-review route is also tested.

Saved answer history surviving failure does not mean the old card visually restores modified radio selections. The retry regression explicitly resubmits the user's choices. This checkpoint does not claim visual selection restoration.

## Tests

Tests use local temporary projects, fake KI definitions, isolated signing keys and controlled catalogue/estimate fixtures. No DS/Kimi credentials, real dataset transfers, model runs or GUI interactions were used.

### Before migration

- Existing focused baseline: **131 passed, 2 skipped, 1 deselected** across flowrun, shared decision parity, CLI wrappers and subsets. The deselected process-local capability case needs localhost sockets and is included in the final broad suite.
- Initial new lifecycle characterization: **11 passed**.
- Adversarial extension: five baseline failures proved card loss and four unshown/off-menu mutation paths; unknown choice IDs were already ignored correctly.

### Final lifecycle checks

```sh
PYTHONPATH=kiss:ki_tools_common python3 -m pytest --import-mode=importlib \
  kiss/tests/test_plan_review_lifecycle.py -q
```

Result: **22 passed** in 28.14 seconds. Includes restart/catalogue refresh, tampered displayed card, absent/corrupt host record, changed data and science picks, rebound item IDs, stale older card, corrupt answers before/during refresh, refresh retry, and the real refresh wrapper's unsigned failure path.

The direct `issue/respond` test proves signing alone neither creates subset jobs, binds data, acquires inputs, runs tools nor moves into execution. Legacy helper tests in `test_flowrun.py` now import their new owner without weakening assertions; existing orchestration tests remain in place.

### Full local regression

```sh
PYTHONPATH=kiss:ki_tools_common python3 -m pytest --import-mode=importlib \
  ki_tools_common/tests/flow kiss/tests -q -rs
```

Result on the frozen production/test tree: **757 passed, 5 skipped, 121 subtests passed**, one pre-existing NumPy/native-extension warning, in 106.47 seconds. Permission was used for isolated localhost socket tests. No production or test files were changed during that run.

The five skips are two server decision-parity checks, two derivation checks needing the server ata-kdt KI tree, and one server harness-copy comparison. These are not passes and do not establish server parity. `git diff --check` and Python syntax compilation also passed; syntax compilation is not an app rebuild.

An intermediate focused run had 104 passes and one test-fixture failure: an `ObsAccessError` message was passed as its error code. The fixture now supplies both arguments; all safety assertions had already passed. That intermediate run is not the final acceptance result.

## Remaining limits

- Source/local regression acceptance only. Compiled Mac, GUI and live-provider/database checks remain C5 work; Windows was not tested.
- No new cross-process transaction lock or atomic multi-file storage guarantee. Ordinary storage failures outside the handled data-refresh path can still propagate; this extraction does not claim crash-proof approval issuance.
- Review enforcement retains the existing provider containment limits; host-owned records are not a new OS security boundary.
- Existing estimate tolerances, re-review rules and downstream failure handling remain unchanged.
- C1 manual-placement and C2 historical-failure completion policies remain the documented follow-ups from those checkpoints.

Next planned module: C4, consistent project status from existing evidence, with deeper model-process tracking deferred.
