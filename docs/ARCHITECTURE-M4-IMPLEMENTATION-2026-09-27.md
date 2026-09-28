# C4 checkpoint: consistent project status

Date: 2026-09-27. Branch: `mac-version`, HEAD `96ac8a5b`, building on the uncommitted C1–C3 work. No app rebuild, live provider turn, commit, push or release was performed.

## Outcome

`kiss/kiss_cli/project_status.py` supplies one read-only status interpretation to the project panel and fast status-button query. The codebase-design skill guided a small `snapshot(...)` interface: callers provide existing report, preparation and activity observations; the module checks existing Flow and receipt evidence and returns consistent meanings, explanations and next actors.

The existing three main blocks remain: Needs you, Progress and Data in this plan. Details remain accessible. This is not a new persistent state machine, a change to scientific completion policy, or deeper model-process monitoring.

## What changed

| Concern | Before | Now |
|---|---|---|
| Chat says complete | Could make project status say complete | Completion requires Flow COMPLETED, current valid approval and the shared evidence gate |
| Running/results stage | Could make all technical input groups say Ready to use | Stage indicates current focus, not input validation; unevidenced groups remain unconfirmed |
| Timeline | Earlier stages gained checkmarks from ordering alone | Checkmarks require projected project completion |
| All downloads failed | Main data-summary pill could be green | Failed inputs block both main summary and technical overview |
| Files on disk | Generic done state | Present but unverified; no acquisition-integrity or scientific claim |
| Download receipt | Mixed done/acquired wording | Acquired, with scientific checks still separately required |
| Generated output | Trusted unsigned evidence.json step list | Produced only from current approval-bound shared receipt evidence |
| Needs-you request | Preferred an older sanitized blocker; action buttons sometimes used another request | All displays/actions use the same canonical pending request, preserving full plan-review data |
| Cleared request | Historical report could revive it | Report-only historical blockers do not become new pending requests |
| Acquisition failure | Could survive into a different approved plan | Current approval-bound acquisition is separate from retained acquisition history |
| Agent activity detail | One JS function accidentally read browser window.status | Reads the current agent observation explicitly |

Failures with leftover local bytes remain failures, rather than being hidden by file presence. Shared final-evidence semantics are unchanged: this does not erase failed historical attempts or silently treat exit zero as scientific validation.

## Interface and integration

`snapshot(project, report=..., plans=..., preparation=..., activity=..., now=...)` returns:

- `progress`: projected status/stage, goal/KIs, explanation, next actor and observation age. Agent-reported status/summary remain labeled observations, not authority.
- `request`: the canonical waiting request, or null.
- `plan_data` and `data_summary`: one input interpretation and consistent severity/counts.
- `technical`: conservative per-lane descriptions. A lane is a KI declaration; there is no invented mapping from overall stage to per-input scientific proof.
- `observations`, `execution`, `acquisition`, and `acquisition_history`: provenance, age and supporting facts.

`gui._session_data` retains its existing poll-driven acquisition advancement **before** calling the read-only projection. Existing report adoption also remains outside it. `GET /session/:id/run` uses the same projection for the status button. `flowrun.plan_data_status` is a compatibility query delegating to the new owner.

`setup.request(..., archive_obsolete=False)` lets status reads suppress an obsolete Kimi runtime permission request without archiving it. Existing callers retain the legacy migration default. Malformed/invalid-UTF-8 requests become status errors instead of breaking the query or implying success.

The browser now renders host conclusions instead of inferring readiness. Respond, file-placement confirmation, Modify and Copy path all address the same displayed request. Missing projection is unconfirmed, not a fallback to an old green state.

## Large-file polling and evidence cache

A naive first integration would have rehashed acquired files twice on every fast status poll. The final implementation shares a single download inspection with the shared evidence summary and caches presentation checks in memory while metadata is unchanged.

Cache invalidation includes plan/inventory/approval, receipt documents, referenced-file and artifact membership, file size/inode/mtime/ctime, symlink metadata and resolved target, signing-key metadata, approval identity and enforcement mode. Mutation during inspection produces an unconfirmed/error result instead of caching mixed evidence. The map is bounded to 32 projects, and slow inspection does not hold its global lock.

The response exposes the inspection timestamp rather than pretending a cache hit is a new file check. This cache is **only for presentation**: approval, acquisition and execution gates keep their existing fresh inspection behavior. The additive private `_download_inspection` keyword on shared `receipts.evidence` avoids a duplicate inspection within this status query; omitted by existing enforcement callers, its behavior is unchanged.

This is not a multi-GB performance benchmark or a replacement for byte checks. Metadata scans and initial/invalidation-triggered hashing still have a cost. No remote source-freshness query or scientific re-validation is implied by a cache hit.

## Verification

All fixtures use temporary projects and signing keys. No real agent credentials, remote downloads, scientific executables, installed models or live projects were used.

- Initial evidence/lifecycle characterization: **9 passed** before the new projection.
- Executing the old render function reproduced both false-green defects: all-failed summary and unevidenced technical readiness at running stage.
- Final lifecycle file: **33 cases**, covering pending review/manual placement, acquisition waits/failures, leftover bytes, stale approval, local/acquired/produced distinctions, completion, current requests, corrupt state/request, heartbeat, read-only behavior and GUI projection delegation.
- Final rendering file: **17 cases** executing actual app JavaScript and request handlers under Node with minimal DOM stand-ins. This is stronger than substring checks, but is not visual/native GUI acceptance.
- Final cache file: **7 cases**, including one inspection on unchanged repeated reads, invalidation on bytes/receipts/artifact/scope/approval changes, key removal, symlink escape and mutation during inspection.
- Intermediate expanded local regression: **301 passed** across status, rendering, flowrun and runtime tests. Further cache safeguards were tested before the final broad run.

Independent review reproduced and then checked corrections for read-time request archival, stale acquisition binding, repeated large-file hashing, timeline checkmarks, key deletion and symlink retargeting. Each corrected failure has a regression test.

### Full frozen-tree regression

```sh
PYTHONPATH=kiss:ki_tools_common python3 -m pytest --import-mode=importlib \
  ki_tools_common/tests/flow kiss/tests -q -rs
```

Result on the frozen production/test tree: **814 passed, 5 skipped, 121 subtests passed**, one pre-existing NumPy/native-extension warning, in 105.36 seconds. Permission was used for isolated localhost socket tests. No production or test files were changed during this run.

The five skips remain two server decision-parity cases, two derivation cases requiring the server ata-kdt tree, and one server harness-copy comparison. They are not passes and do not establish server parity. `git diff --check` and Python syntax compilation passed; syntax compilation is not an app rebuild.

## Scope limits / next checkpoint

- Source and executable-render tests only. No compiled Mac, live DS/Kimi/database, native-window or Windows acceptance yet.
- Deeper model-child tracking, streamed tool logs and model-specific counters remain deferred. A provider heartbeat is not model progress.
- Technical requirements without item-level evidence remain unconfirmed even when a later project stage is known. Completion follows the existing shared gate, not a new independent scientific audit of every input.
- Existing provider containment/assurance caveats remain. Neither UI cache nor status text grants execution permission.
- The separate Observatory live view was not redesigned in this checkpoint; this scope covers the main project-status panel, its details and status button.
- Server-reference parity and the C1/C2 follow-ups remain open as documented. The shared additive inspection hook must accompany these source changes when coordinating other builds.

Next: C5 integration and compiled Mac verification, reported separately from these local tests.
