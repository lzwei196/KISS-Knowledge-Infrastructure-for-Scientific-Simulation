# GeoForge data workflow — first client-side consolidation

Date: 2026-09-14. Implements the first Desktop/shared-harness fixes from
[the strategy review](GEOFORGE-DATA-STRATEGY-REVIEW-2026-09-14.md).

**Source changes are implemented. This is not a claim that the entire generalized
data strategy, compiled release, or live Kimi/DeepSeek simulation is finished.**
No server deployment, new live download, provider turn, app rebuild, or Git push
was performed in this batch. Existing user work and historical test files remain.

## Implemented

### Shared query semantics

`kiss/kiss_cli/obs_access.py` now parses comma-separated variable requirements and
lists consistently. `prec,temp` finds a dataset containing both. Each search
term can still be a partial discovery hint, preserving queries such as
`discharge`; only an exact native/canonical name establishes metadata coverage.
Substring discovery is not promoted to proof of scientific suitability.

### Source/scope-bound receipts and safe reuse

`ki_tools_common/ki_tools_common/flow/receipts.py` fingerprints the inventory
selection (dataset/chosen source, requirements and acquisition identity).
Receipt reuse requires that selection to remain identical and checks hashes of
both acquired and extracted files within the project. Changing the selected
dataset or period under the same item ID no longer leaves it marked downloaded.

Legacy receipts lacking a selection fingerprint are **not automatically reused
against a supplied current inventory**, even if the plan hash is unchanged.
This matters because an inventory-only replan can leave the plan hash unchanged.
Legacy files are not deleted; they require provenance/selection revalidation or
re-acquisition. Do not manufacture new provenance for them from filenames.

### Provider-neutral acquisition offers

New `kiss/kiss_cli/data_contract.py` normalizes estimates with explicit blockers,
warnings and coverage uncertainty; no dataset-ID branches are used in this
module. Empty selections, invalid flags, unknown/zero sizes, known incomplete
coverage, unsupported transformations and budget violations cannot be approved.

Missing coverage is not changed into `true`. A bounded, declared-subsettable
request with unknown coverage offers a separate **approve acquisition for
inspection** action. It is an explicit user choice, not automatic suitability
acceptance. Static requests without dates label the temporal requirement
`not_applicable`; requested temporal coverage remains unknown when unspecified
by the service.

The saved 154-estimate replay now yields:

- 2 complete-coverage approval offers (the two CMFD products).
- 92 additional explicit inspection offers, with coverage still unknown.
- Remaining requests blocked/review-only. Among the 95 nonzero estimates,
  `qin2025_rice_ch4_1961_2020` exceeds the budget; it is not an inspection offer.
- No recorded estimate fields discarded by the public field whitelist in this
  replay; empty-selection and reason metadata are retained.

### Subset acquisition is connected to the scientific inventory

An inventory item can now contain:

```json
{
  "id": "forcing",
  "dataset_id": "<exact product returned by the database>",
  "acquisition_id": "<id returned by the Desktop subset estimate>",
  "requirements": {
    "bbox": [115, 37, 117, 39],
    "start": "1989-01-01",
    "end": "1990-12-31",
    "variable": "prec,temp"
  }
}
```

This is an interface example, not a complete VIC forcing specification.
The app validates the selected product and exact request, stamps a request hash
before plan review, and treats the subset as one logical input with multiple
assets. A parent product is valid in this path because it is paired with the
specific acquisition, not an unbounded whole-product download.

Acquisition approvals and completed acquisition evidence are signed using the
existing project receipt mechanism. Changing a stored request, estimate or job
ID invalidates the acquisition authorization. As with existing harness receipts,
assurance still depends on provider containment; this does not make broad-user-
rights CLI processes cryptographically isolated from the user's key files.

After data acquisition and plan approval, Desktop automatically creates the
normal signed download receipt for the approved inventory item and consuming
step. It appends a progress update without editing the signed plan/inventory.
Both orderings work: acquire then plan, or plan then acquire. Binding is
idempotent; altered/deleted files do not count as intact acquisitions.

API `download_observation_data` and CLI `obs-download` advance the same selected,
already user-authorized subset. They report queued/running as **data status**, not
a receipt. Once ready they can download, inspect and bind it. Neither interface
can approve the user's acquisition. A dependent KI tool step is denied when its
selected subset has no intact bound acquisition receipt.

### Manifest and real-file checks

`obs_subset.py` retains actual dates/counts, CRS origin, calendar, layer/band and
version fields in signed acquisition evidence. Generic manifest scope checks
reject contradictory variable/time/bounds metadata, not only CMFD metadata.
An explicitly advertised variable/year partition is checked without relying on
a CMFD ID or kind. Missing metadata remains pending, not invented.

Before publishing downloaded files:

- Existing size/SHA-256/path/part-count checks remain.
- Actual NetCDF files are opened; declared variables, available time endpoints
  and manifest time counts/ranges are checked against the request.
- TIFF signatures are checked; when rasterio is available, files are opened and
  structure/bounds are checked against supplied manifest facts.
- Missing optional readers or an unsupported native format leave inspection
  pending. These are not scientific passes.
- Local free space is checked; all files must be acquired before publication.

These checks catch the retained HWSD pseudo-TIFF and CN05 full-year-for-one-week
failures. They do not yet establish full grid/cell parity, temporal gap freedom,
scientific units/aggregation validity, datum authority, topology correctness, or
compatibility with a model's prepared input format.

### Status and operational changes

Project data shows `acquired; scientific checks pending`, not “model ready,” for
bound subsets. The normal file-available labels were clarified. Subset cards
show acquisition identity, coverage uncertainty, blockers, file checks and
binding errors; inspection approval is distinct from ordinary approval.
Plan-binding failures are recorded for the status panel rather than silently
treated as successful readiness.

Transfer locks are per acquisition/project rather than one global lock, so an
unrelated project is not serialized behind a long download. The per-acquisition
lock still means active-transfer cancellation is not yet interruptible.

## Verification

Regression tests cover multi-variable discovery, selection changes, legacy
receipt rejection, request tampering, complete versus inspection approval,
empty/invalid/over-budget requests, non-CMFD scope conflicts, actual wrong-format
and wrong-time files, plan binding in both acquisition orderings, immutable
approved inventory, idempotency, modified files and dependent-tool gating.

The binding test exercises the actual API and CLI adapters with replayed service
responses. It does not run a live Kimi or DeepSeek turn.

Final focused client/flow regression: **160 passed**, with the loopback bridge
test run separately as described below.

Broader Desktop suite run: **431 passed, 1 skipped, 121 subtests passed**;
2 failures and 1 deselection were investigated:

- The startup loopback failure was the sandbox's bind restriction. It passed
  when rerun with loopback permission.
- The deselected agent database bridge test also passed separately with loopback
  permission and fake credentials.
- The remaining portability failure is pre-existing: three Windows-invalid
  CE-QUAL-W2 output names occur in both the index and HEAD. The test's non-NUL
  Git parsing additionally misreads quoted Unicode filenames. None of these
  historical paths or that unrelated test were changed by this batch.

Shared flow suite: **79 passed, 2 skipped**. The existing NumPy/NetCDF binary-size
warning remains; exercised NetCDF checks nevertheless passed.

Python compilation, `git diff --check`, frontend JavaScript parsing, and isolated
subset-card inspection/blocker/escaping rendering checks passed.

Saved actual-file checks: **97 file instances examined: 91 passed the limited
structure/scope checks, 6 correctly rejected**. The six are retained bad HWSD
and CN05 outputs across original/retest batches, not six newly introduced
failures. Counts include repeated saved batches and multiple layers; they are
not 97 different datasets.

Evidence and reusable checks:

- `scripts/audit_geodata_strategy_offline.py`
- `output/geodata-strategy-audit-2026-09-14/offline-probes-after-fixes.json`
- `scripts/check_saved_subset_contracts.py`
- `output/geodata-strategy-audit-2026-09-14/native-file-checks.json`
- `kiss/tests/test_data_contract.py`, `kiss/tests/test_obs_subset.py`

## Still required before end-to-end acceptance

1. Agree the versioned backend coverage/asset/variable mapping contract. Inspection
   approval is a safe legacy bridge, not a substitute for authoritative metadata.
2. Backend cache invalidation/version binding for old invalid outputs. Client
   rejection stops acceptance but cannot repair a server's cached data.
3. Consolidate canonical KI requirements with live catalogue availability and
   remove the remaining legacy whole-file child-ID/forcing-provider assumptions.
4. Durable background coordination, restart/range resume, interruptible transfer
   cancellation, and a reviewed migration/revalidation flow for old acquisitions.
5. Complete scientific input validators and model-specific preparation, including
   VIC forcing conversion and CaMa network/topology preparation. “Acquired” does
   not satisfy those requirements automatically.
6. Rebuild and test the packaged app, then run fresh Kimi and DeepSeek acquisition,
   preparation and simulation sessions through the actual GUI workflow.

Do not describe this batch as all datasets or complete VIC–CaMa simulation being
fixed. It removes concrete client defects and joins the previously separate
subset path to the app's reviewed-plan evidence system.
