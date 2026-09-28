# C0/C1 checkpoint: acquired-input evidence

Date: 2026-09-27. Starting branch: `mac-version`, HEAD `96ac8a5b`.

## Outcome

The shared receipt module now owns acquisition-receipt discovery, signature/kind checks, exact-request matching, file containment/integrity, and recovery conclusions. Acquisition, subset binding, execution permission, project status and final evidence use that interpretation.

The codebase-design skill guided the small read-only interface and deletion of repeated caller-side receipt scans. Delivery-specific acquisition and scientific validation remain separate. No new network protocol, provider policy, approval interaction, installer or scientific-model logic was introduced.

This checkpoint is source implementation and local regression verification only. There has been no build, GUI acceptance run, live DB/provider run, push or release.

## Interface and ownership

`ki_tools_common.flow.receipts` exposes:

- `inspect_downloads(project, inventory, approval_sha256=...)`: all acquisition evidence, including rejected records and explanations.
- `find_download(project, item, approval_sha256=..., recover=False, source=None)`: exact reusable evidence, or an explicitly requested recovery candidate.
- `DownloadEvidence`: request match, file condition, reason, reusable/recoverable/current-evidence conclusions. Source freshness remains `unknown`; scientific validation remains `not_assessed`.

Inspection does not create keys, rewrite receipts, approve a plan or download data. Results describe the files at inspection time and must not be cached as permanent permission.

Host recovery remains explicit. `record_download` can require the original expected file entries; changed bytes between inspection and issuance cause a refusal before signing. Recovered receipts retain the previous signed document, including when the receipt filename is reused, so the original evidence remains auditable.

The historical selection fingerprint algorithm is unchanged. It includes the item ID. Rename-only recovery checks the new candidate with the original ID against the old signed fingerprint; no inference from a dataset directory is involved.

## Intentional corrections

1. Served-data recovery no longer trusts a dataset folder when area, period, variables or selected source changed. A narrower area is not automatically treated as proven coverage.
2. Missing ZIP recovery requires an actual absent transport archive and intact, contained, recorded extracted files. Changed archives, directories at archive paths, missing nonarchives and escaped paths are rejected.
3. Recovery cannot silently bless bytes changed after inspection.
4. Malformed receipt documents/file-entry collections and wrong receipt kinds fail closed instead of crashing or counting as downloads.
5. Occupied destinations explain that no intact evidence proves the current request; existing data are not overwritten.

Safe exact reuse across approvals, rename-only recovery, and missing-ZIP recovery remain supported. Missing selection fingerprints cannot acquire new scope proof. Older current-approval receipts retain their existing final-evidence treatment but are not automatically reusable/recoverable.

## Files changed

| File | Change |
|---|---|
| `ki_tools_common/ki_tools_common/flow/receipts.py` | Shared inspection and recovery decisions; final evidence consumes them; guarded recovery issuance |
| `kiss/kiss_cli/acquire.py` | Remove duplicate receipt/file interpretation; explicit evidence-backed served recovery |
| `kiss/kiss_cli/obs_subset.py` | Use shared evidence when looking for an existing binding |
| `kiss/kiss_cli/flowgate.py` | Use shared evidence for the existing subset-input execution check |
| `kiss/kiss_cli/flowrun.py` | Replace raw status receipt scan with shared inspection |
| `scripts/audit_geodata_strategy_offline.py` | Migrate the removed private-helper call |
| `ki_tools_common/tests/flow/test_acquired_inputs.py` | 27 shared-interface and recovery regression cases |
| `kiss/tests/test_flowgate.py` | 24 unsafe-recovery cases; retain safe-recovery integration cases |
| `kiss/tests/test_obs_subset.py` | Cross-consumer agreement, immutable approval/inventory, no silent repair |

## Tests performed

Environment: Python 3.13.12, pytest 9.0.2, NumPy 2.4.2, netCDF4 1.7.4, xarray 2026.2.0. These are observations of this test environment, not application path/dependency requirements.

### Baseline, before production changes

```sh
PYTHONPATH=kiss:ki_tools_common python3 -m pytest --import-mode=importlib \
  ki_tools_common/tests/flow \
  kiss/tests/test_flowgate.py kiss/tests/test_flowrun.py \
  kiss/tests/test_flow_cli_wrappers.py kiss/tests/test_api_handoff.py \
  kiss/tests/test_obs_access.py kiss/tests/test_obs_subset.py \
  kiss/tests/test_obs_describe.py kiss/tests/test_data_contract.py -q
```

Result: 362 passed, 4 skipped, 2 failed because the sandbox denied temporary localhost socket binding. Both isolated loopback tests then passed outside the sandbox with permission. Their credentials/remote responses were test fixtures, not live accounts.

### Red-to-green regressions

- Served recovery: 24 new cases first failed because unsafe requests incorrectly returned `done`; two existing safe-recovery cases passed.
- Shared inspection: the initial 24 tests failed because the new interface did not exist; all passed after implementation.
- Independent review added three failing cases for the issuance race, directory-as-ZIP, and original signed provenance. All passed after corrections.

Final focused command:

```sh
PYTHONPATH=kiss:ki_tools_common python3 -m pytest --import-mode=importlib \
  ki_tools_common/tests/flow/test_acquired_inputs.py \
  kiss/tests/test_flowgate.py kiss/tests/test_obs_subset.py -q
```

Result: **117 passed**.

The subset integration test exercises both download-before-approval and approval-before-download orders. Inspection, acquisition, status, the execution check, and final evidence agree before/after file tampering. Approval, plan, inventory and receipt bytes remain unchanged; no additional fixture transport requests repair the tampered files.

### Broad regression checkpoint

```sh
PYTHONPATH=kiss:ki_tools_common python3 -m pytest --import-mode=importlib \
  ki_tools_common/tests/flow kiss/tests -q
```

Result: **689 passed, 5 skipped, 121 subtests passed**, one warning. Run with permission for local socket tests.

The five skips are two decision-parity cases requiring the server tree, two real-KI derivation cases requiring the server ata-kdt tree, and a harness comparison requiring the server copy. They do not establish server parity.

The warning (`numpy.ndarray size changed, may indicate binary incompatibility`) was already present in the baseline. Scientific/native dependency compatibility is not declared resolved by these test passes.

`git diff --check` passed. Repository search found no remaining Python callers of the removed private receipt helpers outside reference/build trees.

### Older offline audit limitation

`PYTHONPATH=kiss:ki_tools_common python3 scripts/audit_geodata_strategy_offline.py` still stops at its earlier synthetic subset approval with `Only an eligible estimate can be approved`, before the migrated receipt check. Running the unmodified HEAD version of that script gives the same failure at the same step. Updating its older fixture is separate work; this audit is not counted as passed.

## Explicit remaining limits

- Manual placement retains its prior semantics: the host signs files currently present as a newly placed acquisition. After re-planning, that can sign unchanged manual files for new requirements. This is not the served recovery path and was not silently changed in this refactor. Fresh manual confirmation/replacement detection needs a separate policy decision; do not claim universal protection against re-signing across every delivery path.
- Existing current-approval legacy receipts without files retain compatibility treatment in final evidence; they cannot satisfy a download step without file entries or establish exact-request reuse.
- Execution permission still checks the input scope it checked before (subset acquisitions). This change does not broaden gates over every legacy/local input.
- Hashes prove local integrity at inspection time, not remote source freshness, model readiness, or scientific validity. No long-lived file immutability or stronger provider containment is claimed.
- GUI/compiled-Mac checks, live DB retrieval, real agent/model runs and server-reference parity remain unperformed for this checkpoint. Shared Flow changes need coordinated server verification before rollout.

Next checkpoint: M2 approved-step execution, preserving agent diagnosis and explicit permitted reattempts rather than automatic scientific-tool retries.
