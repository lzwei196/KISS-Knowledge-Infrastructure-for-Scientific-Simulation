# GeoForge data strategy: end-to-end architecture review

Date: 2026-09-14. Scope: the current local Desktop source, shared KI harness,
Database bridge, subset adapter, UI, and saved live-service evidence.

## Verdict

The concern is justified. We have reusable infrastructure, but **not yet a
generalized end-to-end data workflow**. The current implementation combines a
catalogue search, a largely CMFD-shaped delivery resolver, a separate subset
prototype, and agent instructions asking the agent to join them together.

This is not exclusively a backend issue, nor evidence that VIC/CaMa KIs or a
particular provider are defective. The Desktop integration itself has structural
gaps. My recent subset implementation added a second acquisition path without
completing its integration into plan/inventory/receipt handling. Calling the
backend format tests successful did not establish Desktop workflow success.

**A thousand-entry local JSON catalogue is a reasonable discovery mechanism.**
Its size is not the problem. What is missing is a consistent contract connecting
scientific requirements, dataset identity, delivery options, approved scope,
validated files, and the model inputs that consume those files.

This review changes no production behavior, server state, or installed app. It
adds an offline diagnostic script and this report. No new server jobs, downloads,
provider turns, builds, or pushes were performed for this review.

## Evidence and reproducibility

Source baseline: `cc7093d889590bfe99fc6ca0cd32c3f034f0291f`, **plus the current
uncommitted working tree**, including untracked `obs_subset.py`. This is not an
audit of a clean checkout or of the compiled app currently installed.

Commands executed:

```sh
PYTHONPATH=kiss:ki_tools_common python3 -m pytest kiss/tests/test_obs_access.py kiss/tests/test_obs_subset.py -q
PYTHONPATH=kiss:ki_tools_common python3 -m pytest kiss/tests/test_flowrun.py kiss/tests/test_flowgate.py -q -k 'data_actions or plan_data_status or catalogue_download or planning_agent_can_search'
PYTHONPATH=kiss:ki_tools_common python3 scripts/audit_geodata_strategy_offline.py --output output/geodata-strategy-audit-2026-09-14/offline-probes.json
```

Existing tests: **55 + 6 passed**, with 70 tests deselected in the second command.
This was not the whole application test suite. The additional probes describe
current defects; their successful execution is not an acceptance pass.

| Offline probe | Observed behavior |
| --- | --- |
| Replay all 154 saved regression estimates through the actual Desktop estimate handler | 152 `needs_review`, 2 `awaiting_approval` |
| Nonzero subset estimates in that replay | 95; 93 omit `coverage_complete`; only the two CMFD products become eligible |
| Search `prec,temp` against a fixture containing both variables | 0 results; `assess_dataset` on the same record/variables says `covered` |
| Generic manifest with contradictory bounds/variable/time metadata and valid byte hashes | Transport download accepted, science explicitly pending; time/count/CRS-origin metadata discarded |
| Empty-selection fixture with `coverage_complete:true` and zero bytes | Eligible; `selection_empty` is discarded |
| Valid old receipt, unchanged bytes and item ID, but newly selected dataset and period | Reuse predicate accepts it; Project status reports the new selection `done` |

The generic-file and empty-selection cases are **synthetic fixtures**, not claims
that the server returned those exact combinations. The generic fixture is
deliberately not a scientific file: it establishes transport-layer behavior,
not a failed scientific validator. The receipt fixture uses isolated test keys,
not a production key. No secrets are read by these probes.

Saved live evidence is separate:

- [Backend regression and stale cache](GEODATA-SUBSET-FIX-RETEST-2026-09-14.md):
  new requests produced readable HWSD/DEM/SoilGrids/CLCD/crop-calendar/CN05 files;
  identical old requests still returned previously bad cached artifacts at the
  time of those tests. Server cache internals were not inspected.
- [CMFD variable tests](CMFD-ALL-VARIABLES-LIVE-2026-09-14.md): eight individual
  variables plus combined delivery passed the documented checks for one daily
  product, area and two years. Catalogue/file precipitation units disagree.
- [Initial integration](SUBSET-INTEGRATION-RESULTS-2026-09-14.md): direct source-GUI
  CMFD acquisition worked, but no provider-driven subset-to-model run was proven.

The 154-record replay is a targeted regression, not all 1,106 catalogue records,
and a positive estimate is not a successful download or simulation. This review
does not assert the live backend is unchanged since those recorded tests.

## Findings

### 1. Acquisition is split into two disconnected paths — Desktop, high priority

The established path in `kiss/kiss_cli/flowgate.py:327` checks current plan
approval, pins the selected dataset to an inventory item and consuming step,
downloads, records a signed receipt, and appends an inventory update.

The subset path in `kiss/kiss_cli/obs_subset.py:84` stores separate state under
`.geoforge/subsets`, approves a request independently, and publishes files under
`inputs/geoforge_subsets`. It records neither an inventory item/plan-step binding
nor the normal signed data receipt. The offline download probe confirms zero
signed data receipts and no inventory update.

`kiss/kiss_cli/flowrun.py:608` derives plan-data status from the approved/draft
inventory and receipt store, not subset state. The UI renders both systems
separately in `kiss/kiss_cli/web/app.html:1477`.

The Database KI instructions explicitly tell the agent to inspect the subset
state and bind files later (`system_kis/GeoForge_Database/docs/s1_scope_query.md:31`).
That is an instruction, not an implemented, atomic binding operation. It can
leave successfully acquired files disconnected from the plan's data requirements.

Separate approval for exploratory data acquisition can be legitimate; this is
not a claim that it authorizes a model run. The defect is the missing durable
relationship and reconciliation between acquisition and scientific planning.

### 2. The supposedly generic subset gate is CMFD-shaped — shared contract/Desktop

`obs_subset.py:91` requires `coverage_complete is True` for every data type. The
recorded raster/generic-NetCDF estimates do not supply that field: **93 of 95
nonzero estimates therefore cannot reach the normal approval button**.

At download time, `obs_subset.py:182` checks variable/year combinations and
requested bounds only for `kind == 'cmfd_grid'`. Generic deliveries receive byte
integrity checks, but no equivalent request-versus-result scope check. Science
is honestly marked pending; the missing piece is the subsequent automatic check
and binding, not a falsely asserted scientific pass.

Removing `coverage_complete` would open the button but would not solve this.
Coverage must distinguish spatial, temporal, variable and layer completeness,
with `complete`, `partial`, `none`, `unknown`, and `not_applicable` semantics.
For example, time coverage is not applicable to a static DEM, not “unknown time.”

### 3. Product identity and delivery identity are conflated — Desktop/protocol

`obs_access.py:929` recognizes child IDs using `parent__variable_YEAR` syntax.
`Client.download` chooses its child route from that regex (`:348`), while
`stamp_inventory` forces such children to `delivery='manual'` (`:1033`).

The same inventory stamping rejects a whole-product parent based on the
presence of cached children, even though the subset interface legitimately
takes that parent as the source of a small dynamic clip. The plan instruction
also says never to pin a parent, while the new subset instruction needs it.

This assumes one variable/year packaging model. It does not naturally represent
tiles, multiple soil depths, annual land cover, station records, multi-variable
files, or generated subsets. Dataset IDs should be opaque; capability and asset
relationships should determine delivery, not spelling.

### 4. Scientific discovery and live availability are separate knowledge systems

There is useful existing semantic work: `flow/plan.py:163` builds canonical input,
forcing-provider, dataset and coupling indexes from cards. It should be reused.
However, these indexes are not the live authenticated catalogue's availability
model. `_pick_forcing_provider` (`:412`) uses fixed CMFD/MSWX/NASA/ERA5 preferences
and date/location rules, not current delivery offers for the request.

The live search in `obs_access.py:639–808` instead uses variable names/canonical
strings, keyword substrings, simple bbox/date checks and textual ranking.
Search interprets `variable='prec,temp'` as a single substring; assessment splits
it into two names. The offline probe reproduces the disagreement.

`stamp_inventory` also uses fuzzy identifiers as a convenience. That may help
suggest a candidate, but it should not establish an approved source identity.

The metadata is already divergent: the bundled CMFD provider card has its own
native names and a server-local data path; the catalogue and delivered file
have independent names/units. The recorded CMFD precipitation discrepancy and
crop-calendar friendly/native-name discrepancy show the practical consequence.
This is not a claim that the Desktop currently executes that server-local path.

Canonical definitions and native-variable mappings need versioned provenance.
Do not invent mappings from a similar name or silently trust catalogue prose
over inspected file metadata when they disagree. KI-required conversions remain
explicit, validated transformations, not downloader guesses.

### 5. Important protocol evidence is discarded — Desktop, high priority

The estimate whitelist (`obs_subset.py:23`) drops `selection_empty`,
`n_selected_cells`, and `reason`. The saved-response replay demonstrates those
losses. Its predicate permits zero bytes and does not check empty selection.
The synthetic complete-but-empty case becomes eligible.

The downloaded-part whitelist (`:218`) loses `time_range`, `n_time_steps`,
`time_subset_applied`, and `crs_source`. Those are precisely the fields introduced
to explain the recent time-slice and inferred-CRS problems. A hash cannot replace
them. Private source paths should still be excluded, but public provenance must
be explicitly modeled, retained, and checked.

### 6. Reusing a receipt is not tied strongly enough to the selected data — harness/Desktop

`flow/receipts.py:478` accepts an older download when its item ID still appears
in the inventory and its raw file hashes match. It does not compare the newly
selected dataset, time/space/variables, or current bound file set. The predicate
is used by both receipt reuse and the plan-data status logic.

A signed fixture for source A, followed by an inventory selecting B and a new
period under the same `forcing` ID, is still reported `done`. This proves a
readiness/status identity defect; it does **not** prove a wrong model simulation
was completed. Fix reuse around immutable acquisition identity and explicit
compatibility checks, not item labels alone. Reuse should remain possible when
the same validated assets genuinely satisfy a revised requirement.

### 7. Versioned reproducibility is incomplete — server plus Desktop contract

The recorded regression shows fixed processing for fresh HWSD/CN05 requests but
stale bad outputs for identical old requests. A cache identity must bind the
normalized request, actual source revision, processor version and contract
version; superseded invalid artifacts must not be served as current results.

Desktop approval currently stores a request and a timestamp, not a server-bound
estimate identity/revision. Job creation repeats the body. A 15-minute expiry is
useful but does not prove the approved source/output semantics stayed unchanged.
Source changes, expanded scope or changed transformations need a refreshed offer
and, when material, renewed approval.

### 8. Acquisition lifecycle is attached too closely to UI/network calls — Desktop

The global `obs_subset.LOCK` encloses polling, job creation, and the entire
download. Consequently unrelated projects serialize and cancellation cannot
interrupt an active transfer through this interface. There is no range resume.

The subset UI polls while its panel remains open (`app.html:1494`). Closing it
does not cancel server work, but stops that polling loop; there is no durable
app-level coordinator here to progress and notify the project independently.
Job approval and file download are separate user clicks; the agent-facing
interface only estimates. This is not yet the requested “approve a data choice,
then let the agent/app acquire and continue” workflow.

## What to retain

- One app-wide metadata cache, pagination, stale-cache disclosure, and local search.
- App-held activation token, proxy configuration, and redaction of private links.
- The scientific KI input/canonical-variable/coupling cards as domain knowledge.
- Explicit user decisions and plan approval; no fabricated source/coverage.
- Atomic file publication, safe paths/archives, bounded transfers and hashes.
- Existing signed receipts and explicit `scientific_validation='pending'`.

Do not rebuild the whole app or move authenticated orchestration into prompts.
Consolidate these pieces into one data service used by every UI and provider.

## Proposed generalized design — not implemented yet

### One flow, multiple delivery methods

```text
User goal + selected KIs
           ↓
Scientific data requirements (including warmup, grid and coupling requirements)
           ↓
Search catalogue/local assets → resolve request-specific options + gaps
           ↓
Discuss options with user → bind selected source/scope to reviewed plan
           ↓
One acquisition coordinator
  ├─ verified local reuse
  ├─ direct asset download
  ├─ server subset job
  └─ manual handoff → import received assets
           ↓
Integrity check → content/scope checks → KI preparation → input validation
           ↓
Bound input evidence → harness permits the corresponding simulation step
```

The conversation stays natural: the user asks to simulate a region, the agent
identifies real data choices and missing requirements, and the user confirms.
Users should not have to type internal dataset IDs, repair JSON, or manually
join subset folders to plan rows.

### Shared entities

| Entity | Required purpose |
| --- | --- |
| Data requirement | Stable requirement ID and consuming KI input; canonical variables, required units/time semantics, spatial footprint/grid/topology, period including warmup, required depths/bands, validation policy |
| Dataset specification | Opaque product ID and revision; native variables and authoritative mappings, dimensions/CRS/calendar/nodata, real coverage, citations/licence; metadata provenance and uncertainty |
| Delivery offer | Exact normalized request, dataset/source/processor revisions, selected assets/layers, per-dimension coverage and gaps, output/source-I/O estimates, transformations, expiry, offered acquisition methods and reason codes |
| Acquisition | Selected offer fingerprint, project/requirement links, user authorization scope, durable job/transfer state, retry/cancel information |
| Asset manifest | Every file's bytes/hash, actual bounds/time/variables/layers/units/CRS provenance, source revision, processor version and actual applied operations |
| Input binding | Acquired assets and validated prepared outputs satisfying a requirement, with validator/tool versions and reusable evidence |

Keep one scientific inventory requirement for a logical input; attach however
many assets fulfill it. A seven-variable, two-year forcing requirement should
not have to become fourteen independent scientific choices just because the
server partitions files that way.

Use typed coverage and diagnostic reasons. `reader_error`, `not_mounted`,
`unsupported_geometry`, `empty_selection`, `quota_exceeded`, and `schema_mismatch`
are different outcomes with different actions. Missing metadata is not success;
neither is it automatically proof the source has no data.

Unknown scientific suitability may permit explicitly approved inspection/download
when delivery is safe and bounded, but never an automatic “model input ready.”
Definite noncoverage or empty selections cannot satisfy the original requirement.

### Responsibilities

| Component | Owns |
| --- | --- |
| Database backend | Authoritative source catalogue/mappings, capabilities, source-aware readers, deterministic request resolution, job processing, access control/quota, versioned cache and manifests |
| Desktop app-wide data service | Shared search semantics, local cache, proposal/approval binding, acquisition lifecycle, integrity/content checks, manual import, receipts and status events |
| KI and harness | Scientific input requirements, preparation tools, domain validation, coupling contracts; gate actual execution on the validated bindings |
| Agent | Explain the user's goal, propose supported choices, ask about genuine tradeoffs/gaps, invoke the shared service; not manufacture availability, approval, provenance, or validation |
| UI | Present the same service state as agent tools, including waiting owner/reason and actionable next step |

The Database system KI can teach the agent how to use this service. It should
not be the only place the workflow's rules exist. Kimi and DeepSeek adapters
must call the same service operations with the same request/project IDs.

### Generalized does not mean every dataset gets the same bbox cutter

- Rectilinear forcing: select time, variables, spatial cells and calendar-aware
  intervals, preserving native values until an explicitly planned conversion.
- Raster DEM/soil/land cover: choose actual bands/depths/years, native CRS and
  nodata rules; distinguish cropping from reprojection/resampling.
- Station time series: select station identity and period; do not raster-crop a CSV.
- Vector boundaries: spatial filtering/intersection with declared geometry rules.
- Model-native parameter/network packages: use their declared selection adapter
  or acquire a compatible whole package. Never infer support from the extension.

In particular the current CaMa KI declares next-downstream cell indices,
catchment areas and a runoff input matrix (`models/CaMa_Flood/dag.yaml:32–74`).
It needs a topology-aware preparation/validation contract, not an arbitrary
rectangular cut of each binary. VIC also has separate forcing and parameter
requirements. A small forcing clip alone does not establish a runnable VIC–CaMa
project. Generalization means each type has an explicit, tested capability or
honest fallback, not that every catalogue row must support raster subsetting.

### User-visible status

Derive all status from the common requirement/acquisition/binding records:

`needs choice → approved → preparing on server → downloading / waiting for manual files
→ integrity verified → checking content → preparing KI inputs → model-ready`.

Show source and revision, requested versus delivered extent/period/variables,
actual bytes/progress, what the app can do, what the user must do, and blockers.
“No data,” “data exists but needs manual delivery,” “server unreachable,” and
“files downloaded but not validated” must never be collapsed into one label.

Approval should cover the selected data request and bounded operations. Ordinary
polling/retries or packaging changes within that approved scope should not keep
prompting. Changed data source, scientific scope or material resource/transform
cost needs a revised proposal. Optional exploratory acquisition may precede a
final simulation plan, but must subsequently bind through the same validated
asset mechanism and never implicitly authorize model execution.

## Implementation order and acceptance gates

1. **Agree and fixture the shared contract first.** Define the entities, coverage
   semantics, error codes and version binding with the backend. Add a legacy
   normalizer with explicit unknowns, not guessed completeness. Inspect saved
   responses for each supported data family before changing approval logic.
2. **Unify data identity and binding.** Replace regex/fuzzy identity decisions
   with explicit IDs/relationships; fix receipt reuse. Connect subset/manual/
   direct/local assets to one inventory requirement and acquisition record.
3. **Unify lifecycle and provider interfaces.** Move acquisition out of panel
   polling/global transfer locks; add durable progress, bounded retries, restart
   reconciliation and cancellation. API and CLI call the same operations.
4. **Add content and KI input validators.** Preserve full public manifests;
   validate actual variables, timestamps, grid/CRS, masks/layers and conversions.
   Integrate reusable existing KI validators rather than duplicating science.
5. **Then exercise the full workflow with Kimi and DeepSeek.** Approve a real
   data proposal, acquire, inspect, prepare, bind, run VIC and CaMa, and report
   model outputs and failures honestly. Calibration is a separate acceptance
   target requiring suitable observations and agreed objectives.

Acceptance must include:

- A previously unseen dataset using an existing supported schema/reader works
  without edits to Desktop, prompts or dataset-ID conditionals.
- All catalogue records have honest capability/unsupported/unknown responses;
  downloadable sources and supported types get bounded end-to-end coverage.
  Not every year/global file needs downloading to establish protocol coverage.
- Non-CMFD NetCDF, geographic/projected raster, categorical layers, layered soil,
  annual products, station/table, manual package and model-native topology cases.
- Every required variable/layer tested, partial coverage, empty selections,
  unknown units/CRS, calendar variations, changed source/processor versions,
  expired jobs, network failures, cancellation, restart and limited disk space.
- Search/assessment agree; changing dataset/scope invalidates stale bindings;
  unchanged verified assets can still be reused when compatibility is proven.
- Generic manifest scope conflicts cannot progress to validated input; byte hashes
  alone cannot satisfy science. Source-value parity checked on controlled samples.
- Kimi and DeepSeek reach the same data-state transitions through the actual
  Desktop interfaces, including user choices and the resumed run.
- Packaged-app tests after source tests; no claim that source-only results prove
  the compiled release works.

The next change should be this consolidation, not another CMFD/DEM-specific
exception or merely relaxing `coverage_complete`.
