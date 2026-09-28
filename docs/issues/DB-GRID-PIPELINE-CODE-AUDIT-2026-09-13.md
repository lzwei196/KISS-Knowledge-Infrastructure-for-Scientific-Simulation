# GeoForge DB grid-selection and simulation pipeline audit

Scope: current uncommitted local source on `mac-version`, 2026-09-13.
Read-only code inspection and isolated in-memory probes; no real provider turn,
DB credential access, backend request, approval, or project mutation. This report
is not a new end-to-end acceptance result. No implementation fixes in this audit.

## Conclusion

The desktop implements authenticated catalogue discovery and dataset-ID download,
not a grid-bound data-resolution contract. The recent prompt changes describe the
desired behaviour but do not enforce it. Current gates can approve unsuitable or
nonexistent catalogue selections and can over-credit historical download evidence.
These are desktop/flow integration defects, not proof of a defective scientific KI
or a provider-specific problem.

## Findings

### P1: Grid requirements do not bind discovery, approval and download

`kiss/kiss_cli/api.py:563` exposes optional bbox/time/variable search filters.
`obs_access.py:675` applies intersection and period overlap, not full requested
coverage. Records without geometry remain candidates. This is reasonable for
discovery, but there is no separate suitability gate.
`ki_tools_common/ki_tools_common/flow/plan.py:682` validates structural readiness,
not requested grid/period/variable coverage. `flowgate.py:327` checks inventory and
step membership; `obs_access.py:315` downloads by dataset ID only. No production
resolver or clipping endpoint call was found in the DB client/bridge code.

Probe: a single-grid query for 1989–1990 returns a national record covering only
two days in 1989, plus a record with unknown geometry. This is NOT inherently a
search bug; treating such candidates as resolved inputs without coverage validation is.
Malformed bbox `not-a-bbox` also returns records rather than rejecting the query.

### P1: Nonexistent child records pass catalogue validation

`obs_access.py:822` accepts a syntactically matching child ID whenever its parent
exists. `stamp_inventory` then constructs child metadata from that parent without
checking a resolver response, variable availability, year availability, or delivery.

Probe: `cmfd_china_daily_010__unicorn_9999` produces zero stamp errors when the parent
exists. This proves false planning acceptance, not that the server will download it.
The server may reject it later, after user approval.

### P1: Alternatives are treated as a selected source

`obs_access.py:850` searches `acceptable_sources` when determining the pinned ID,
including fuzzy matching. `flowgate.py:327` also permits a requested dataset if it
occurs in `acceptable_sources`, even when another `dataset_id`/`chosen_source` exists.

Probe: an item with `chosen_source: undecided` and one acceptable catalogue source
gets that source assigned as `dataset_id`, with no error. The execution permission
for alternatives is confirmed by source inspection, not a live download.

### P1: Historical download reuse is not bound to the selected dataset

`flow/receipts.py:478` checks the inventory item ID and raw-file hashes, but not
the currently selected dataset, request, grid, variable set or period. A replan can
reuse item ID `forcing` for a different source and retain credit for the old source.

In-memory probe (file existence/hash mocked): old receipt + same item ID + different
dataset returns True. A real signature is checked separately by callers; this issue
concerns a genuinely signed old receipt, not a forged one.

### P1: Status checks and final evidence checks are inconsistent

`flow/receipts.py:557` accepts a signed download bound to the current plan without
rechecking the downloaded bytes. The cross-plan path rechecks only `raw_files`.
For archives, `processed_files` may therefore have changed while the archive stays
intact. Their paths still enter the evidence set. The recent `plan_data_status`
change checks signatures and raw hashes, but does not fix this final evidence path
or verify extracted model inputs. It also hashes files on each status refresh;
large-data performance has not been measured.

### P2: Manual placement is only a presence check

`setup.py:226` now excludes common partial files and empty directories, but a single
nonempty payload is sufficient. It does not inspect the CMFD variables, dates, grid,
units or archive completeness. A source with multiple required files cannot be
declared complete on this basis. The handoff object has no structured required-file
manifest or dataset/grid binding (`setup.py:106`). KI inspection remains necessary.

### P2: Unavailable catalogue silently bypasses ID stamping

`obs_access.py:870` returns no errors when there are no catalogue records, even for
an explicit database ID. Probe: a made-up explicit ID with an empty catalogue is
accepted by the stamper. Offline local inputs should remain usable, but explicit
DB selections need an unavailable/unverified state, not implicit success.

## Backend capability versus desktop implementation

`docs/OBS_ACCESS_API_ADDENDUM.md` documents basin packages and national
variable-by-year children, explicitly not spatial tiles. This is a historical
contract, not a fresh verification of the deployed backend. Even if the server now
supports per-grid links, this desktop code does not call a grid resolver.
Do not invent an endpoint or assume that the actual Baidu files are spatially split.

## Recommended implementation sequence

1. Represent a forcing request independently from its candidate datasets: model
   grid/extent and CRS, variables/units, resolution, warmup and simulation period.
2. Connect to the actual backend resolver contract and preserve the returned exact
   delivery units. Distinguish spatial tiles, variable-year files and regional
   packages. Reject malformed filters; represent unknown coverage explicitly.
3. Validate requested versus provided coverage before approval. Require an explicit
   user choice for larger regional packages and their local extraction procedure.
4. Permit only the selected dataset or explicitly approved selected bundle at
   download time. Alternatives remain alternatives; no fuzzy commitment.
5. Bind receipts to the request and selected delivery-unit identity; verify raw and
   extracted input hashes before execution/evidence completion, including replans.
6. Validate manual deliveries against a manifest and scientific input checks.
7. Repeat actual DeepSeek and Kimi runs only after these contract tests pass.

Existing passing tests do not prove these properties: most are catalogue plumbing,
structural flow and provider transport tests. Add negative tests for the cases
above, including a Huai-wide package offered for a single-grid request.
