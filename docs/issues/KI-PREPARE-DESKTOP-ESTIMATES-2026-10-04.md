# KI preparation: Desktop estimate integration

Date: 2026-10-04. Status: local development candidate; not released.
Base: Windows `e2a5e76bcc1e235e6e7aa345eba151dbba291db2`.
Branch: `codex/ki-prepared-inputs`.

## Implemented

The new `estimate_preparation` agent tool sends an explicit model/KI, source,
output mode, period and site/grid to `/api/obs/prepare/estimate`. It is a separate
path from raw subset acquisition. Tokens remain inside the Desktop HTTP client.
The public OpenAPI was inspected on this date; it confirms the endpoint and the
13 request fields, but publishes no typed response schemas.

Estimates are sanitized and stored under `.geoforge/preparations`. They preserve
the requested identity and fingerprint, server cadence/transforms/output descriptions,
versions and blockers. Blockers override `preparable:true`. Unknown contracts,
missing plan details and malformed responses cannot become available plans.
Stored records are reclassified from their evidence when read.

The project Data panel has a bilingual preparation-plan card and an action to
ask the agent to inspect a plan using the project's actual settings. This card
does not present estimates as generated or validated inputs.

Available interfaces:

- Agent: `estimate_preparation` with the request fields directly as arguments.
- Desktop CLI: `obs-prepare-estimate --request REQUEST.json [--project PROJECT]`.
- CLI-agent Database helper: `--prepare-request REQUEST.json`, forwarded through
  the existing loopback capability; no activation token enters the child process.
- Local UI API: `POST /api/session/{id}/preparations/estimate`, body
  `{"request": {...}}`; `GET /api/session/{id}/preparations` returns `{"items": [...]}`.

These interfaces create no remote job or download. A `preparation_id` identifies
only a stored estimate; it cannot replace a raw `acquisition_id`. Acquisition,
input readiness and model readiness remain false. There is no automatic raw-data
fallback, converter execution, or change to the project's approval/Flow state.

## Example inspection

Save this explicit SHAW request as UTF-8 JSON, then invoke the estimate command:

```json
{"model":"shaw","source":"cmfd","mode":"daily","lat":47.43,"lon":126.97,
 "start":"2003-10-01","end":"2004-05-31"}
```

CRHM example: `model=crhm`, `source=nasa_power`, `mode=hourly`, site
`49.17,125.23`, the same dates. VIC example: `model=vic`, `source=cmfd`,
`mode=3-hourly`, bbox `[115.25,32.75,115.75,33.25]`, `grid_res=0.25`, dates
`2002-01-01` through `2003-12-31`. These examples do not invent a KI source revision.
The server decides supported combinations; Desktop never substitutes a source.

CLI exit codes: 0 means an inspectable plan was returned, not preparation success;
2 means a blocked/unsupported/failed estimate or invalid request; 3 means missing
or rejected authentication. Configure the Database token in Desktop Settings.

## Verification

194 focused tests passed in 4.95 seconds: adapter validation and redaction,
real API/CLI/GUI handlers with simulated transport, both CLI-agent helpers,
actual JavaScript card rendering, Database status, raw subset, source describe,
Database gating and data-contract regression tests. All prepared-response
fixtures are explicitly offline/synthetic; no scientific success is implied.

From the repository root, using the application's Python environment:

```powershell
$env:PYTHONPATH = "$((Resolve-Path ./kiss).Path);$((Resolve-Path ./ki_tools_common).Path)"
python -m pytest `
  kiss/tests/test_prepare_helpers.py kiss/tests/test_obs_prepare.py `
  kiss/tests/test_prepare_integration.py kiss/tests/test_prepare_display.py `
  kiss/tests/test_database_status_ui.py kiss/tests/test_obs_subset.py `
  kiss/tests/test_obs_describe.py kiss/tests/test_database_gate.py `
  kiss/tests/test_data_contract.py -q
```

On 2026-10-05 the user supplied a working credential. Normal Desktop activation
succeeds with 1,106 catalogue records. Authenticated Canadian NASA POWER
estimates succeed for CRHM hourly and SHAW daily. No preparation job or prepared
file download has been performed. The original Windows checkout's existing
local changes were preserved.

## Server work still needed

1. Correct or explicitly declare delivered time coverage. The handoff requests
   2003-10-01 through 2004-05-31 (244 days / 5,856 hours before any declared
   padding), but reports 731 SHAW days and 17,544 CRHM hours, exactly two years.
   The latest shared-loader commit `e016bbcc3795cb1cdefa1693224081212d371951`
   uses `period` for completeness checking; it does not crop returned arrays.
   The service must trim output explicitly or use a date-aware KI conversion.
2. Compare nonzero source precipitation and whole-request totals directly with
   delivered files, allowing only documented output rounding. A zero-rain day
   and the converter's own annual summary do not independently prove conservation.
3. Bind shared-loader/dependency and source versions to manifests and cache keys,
   as well as the wrapper tool hash. Supply the deployed source commit and full,
   sanitized estimate/job/poll/manifest examples for the prepared delivery adapter.
4. Make VIC prerequisites request-scoped and distinguish supported from ready.
   A missing soil/grid prerequisite remains a blocker even with `preparable:true`.
5. Validate temperature extrema with source samples and `TMAX >= TMIN`;
   genuinely constant-temperature days are valid.

Prepared job execution and checked downloads are not enabled in this candidate.
The user-supplied server handoff documents `POST /api/obs/prepare/jobs`, followed
by `GET /api/obs/subsets/jobs/{id}`, `/manifest` and `/parts/{n}`. Implementation
still needs authenticated job/manifest/file verification, typed prepared
inventory and approval binding. Reuse bounded multipart transfer primitives,
not raw-subset identity validation: prepared weather is not a raw raster clip.
Live estimates report tool hashes different from the selected local SHAW/CRHM
converters and omit shared-loader identity. Validate model/KI identity, actual
timestamps, cadence, units, required columns and checksums before readiness.
Observation archives and site inputs remain separate requirements.
The separate earlier CMFD reader candidate is also not merged here: upstream
`e016bbc` and that candidate contain overlapping scientific fixes that must be
integrated deliberately rather than overwriting either complete loader file.
