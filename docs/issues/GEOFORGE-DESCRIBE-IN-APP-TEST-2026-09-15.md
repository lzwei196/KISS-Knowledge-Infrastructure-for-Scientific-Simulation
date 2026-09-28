# Source-variable discovery: compiled-app / live-agent test

Date: 2026-09-15. Scope: issue 1, catalogue labels versus source fields.

## Current verdict

**Partially working, not closed end to end.** Real DeepSeek API and Kimi Code
turns were started through the compiled application's GUI. Both produced live
subset estimates for five dataset families using appropriate native NetCDF
names and initially empty variable selections for rasters. A remaining raster
selector defect was reproduced through the GUI: a completely nonexistent field
is accepted for estimation and still receives an inspection-approval button.

No jobs were created and no scientific files were downloaded in this test.
Download/file validation is pending explicit approval; this report must not be
read as evidence that those stages passed.

## Build and app startup

- Local test build: GeoForge Desktop 0.6.52, rebuilt with the source-schema
  integration described in `GEOFORGE-DESCRIBE-DESKTOP-INTEGRATION-2026-09-15.md`.
- Executable SHA-256:
  `d8424857edb2365c6e68052b4f831e6f3ad35d2a216693811e7013b9a36e641a`.
- Running bundle:
  `/Users/leo/kiss/builds/dist-describe-ui-20260915-v0.6.52/GeoForge Desktop.app`.
- Bundle signature verification passed (ad-hoc signing, not notarization).
- Started with `gui --port 61823 --no-browser --workroot /Users/leo/kiss`.
- The user's browser was still pointing to port 8878. Its existing tab was
  navigated to the functioning test server at `http://127.0.0.1:61823/`, and the
  application page was visibly verified. This startup observation is not a fix
  for stale-port navigation across future launches.
- No Git push, release publication or replacement of the separately running
  older native bundle was performed.

## Test method

Fresh conversations and project directories were created through the app GUI.
The providers were selected using the normal provider controls: DeepSeek API
(`deepseek-chat`) and Kimi Code CLI (its configured default model).

Both received the same initial task: a maize-data acquisition test in the North
China Plain, bbox `[115,37,115.1,37.1]`, CMFD dates `1989-01-01` through
`1989-01-02`, static products without dates, native grids, and a 100 MB download
budget. The prompt named five product families and scientific requirements but
did not supply catalogue IDs, exact native field names or tool commands.
It explicitly requested real searches/descriptions/estimates, all-member scope
disclosure, approval before jobs/downloads, and no model runs or fabrication.

Provider messages were inspected in the GUI, and actual app-owned acquisition
records in `.geoforge/subsets/` were checked independently of the agents' prose.
Two additional negative estimates were submitted manually through the GUI's
project-status form. These were estimates only, not acquisition approvals.

The earlier **190 passing regression tests** belong to the source-integration
report. They are separate evidence, not a substitute for these live-agent tests.

## Dataset results before acquisition

| Dataset | Selection produced by both agents initially | Live estimate / limitation |
|---|---|---|
| `cmfd_china_daily_010` | `lrad`, `prec`, `pres`, `rhum`, `shum`, `srad`, `temp`, `wind` | Eight fields matched, eight parts, 5,840 estimated bytes; awaiting approval. Source precipitation unit reported as flux, not the catalogue's daily-depth label. Actual delivered dates/values not yet checked. |
| `crop_calendar_global` (Sacks) | `harvest`, `plant`, `tot.days` | Exact names matched, nine crop files, one selected cell, 54 estimated data bytes; inspection only because coverage was unconfirmed. |
| `ggcmi_crop_calendar` | `maturity_day`, `planting_day` | Original box contains no native 0.5-degree cell centre: empty selection blocked. Expanded boxes include one centre and estimate 40 members / 160 data bytes. |
| `china_dem_90m` | `variables: []`, whole raster | Single raster, 30,752 estimated bytes; inspection only. No band selector was invented for the initial requests. |
| `hwsd_china` | `variables: []`, whole rasters | Two source members, 528 estimated bytes; inspection only. Both agents distinguished mapping-unit IDs from a complete soil profile. |

These sizes are server estimates, **not measured download sizes**. Small array
payloads can still produce larger containers. Server-side source I/O is distinct
from the size delivered to the desktop. Crop selection is not implemented by
inventing a member selector: current requests span all matching source members.

## Provider behavior

### Kimi Code

Kimi recovered from an initial keyword-quoting error and completed the read-only
checks. It independently diagnosed GGCMI's empty result as a grid-centre issue,
tested `[115,37,115.5,37.5]`, and asked the user to approve that changed scope or
drop the dataset. It retained empty raster variable selections. Its final turn
stopped awaiting the user, with no job IDs in the acquisition records.

### DeepSeek

The initial NetCDF selections and raster selections were correct. However:

1. It initially interpreted the empty GGCMI selection as missing maize coverage.
   That conclusion was unsupported; a native cell centre simply lay outside the
   tiny requested box.
2. It confused reading a large national source on the server with downloading
   that entire source to the desktop. A follow-up clarified the distinction.
3. The follow-up explicitly enlarged only GGCMI to `[115,37,115.6,37.6]` and asked
   to keep the other four requests. DeepSeek instead created revised estimates
   with enlarged boxes for all five products. No scope change was approved.
4. In that follow-up it introduced `variables: ["elevation_m"]` for DEM, despite
   the source description exposing bands rather than that selectable field.
   This exposed the contract gap below.

These observations distinguish provider reasoning/scope errors from the shared
source-discovery plumbing. They do not prove every provider or every dataset is
correct.

## Reproducible remaining defect: raster filters accepted without support

### Positive negative-control: NetCDF rejects a wrong name

Submitted through the GUI:

```json
{"dataset_id":"crop_calendar_global","bbox":[115,37,115.1,37.1],"variables":["planting_day"]}
```

Acquisition `55858047f09a425fa4ff3cfcac5951be` recorded
`estimate_failed`, HTTP 400, `unknown_variable`, and no job. The GUI displayed
describe-and-revise guidance, did not offer acquisition approval, and did not
offer an identical-request retry. Sacks uses `plant`; GGCMI's similarly named
scientific quantity legitimately uses `planting_day`.

### Failing negative-control: raster accepts a made-up name

Submitted through the same GUI form:

```json
{"dataset_id":"china_dem_90m","bbox":[115,37,115.1,37.1],"variables":["definitely_not_a_source_field"]}
```

Acquisition `f83f7c6c7db54f9b8a3f93eacd01a1cf` recorded:

```json
{
  "status":"needs_review",
  "blockers":[],
  "warnings":["variable_selection_unconfirmed","coverage_unknown_inspection_only"],
  "inspection_allowed":true,
  "estimate":{"subsettable":true,"kind":"raster","n_files":1,"estimated_output_bytes":30752},
  "job_id":null
}
```

The response omitted a confirmed variable selection. The GUI still offered
inspection approval. DeepSeek's `elevation_m` request, acquisition
`179e9fa06aa641e7917b4bcc6dba7425`, shows the same pattern.

Responsibilities:

- **Server, demonstrated at the estimate interface:** the raster estimate
  accepts an explicit unsupported variable filter. The reported strict
  unknown-name behavior is therefore not universal across formats. Job-time
  behavior has not been tested and must not be inferred.
- **Desktop:** `data_contract.normalize_estimate()` treats absent confirmation
  of a nonempty selection as a warning. With unknown coverage and no other
  blockers, it permits inspection approval. It does not currently distinguish
  an unsupported selector from merely incomplete legacy metadata.
- **Agent:** should use an empty variable list only when intentionally requesting
  a whole raster, after explaining that scope. It must not silently erase a
  rejected filter or assume a catalogue label is an implemented band selector.

Recommended next correction: reject unsupported explicit selectors (or require
  a supported, confirmed selection contract), preserving intentional whole-raster
  requests. Apply the rule generically by capabilities/response contract, not by
  a DEM-specific alias table. Add regression tests for a made-up raster name and
  correct empty-selector requests. This report does not claim that correction
  has been implemented or rebuilt.

## Local evidence and continuation

Project parent: `/Users/leo/kiss/projects/describe-ui-20260915`.

- DeepSeek session `ab97de8b62a9`:
  `2026-09-15-This-is-a-real-GeoForge-Database-data-acquisitio--ab97de8b62a9`
- Kimi session `5c4bfebf34bc`:
  `2026-09-15-This-is-a-real-GeoForge-Database-data-acquisitio--5c4bfebf34bc`

Each contains `memory/transcript.jsonl`, `runs/project-events.jsonl` and the
app-owned `.geoforge/subsets/*.json`. Kimi also wrote
`runs/approval-cards.json`; that agent-authored summary is secondary to the
app-owned records. Credential settings are not included in this report.

Candidate valid acquisitions for the next phase:

| Family | DeepSeek card | Kimi card |
|---|---|---|
| CMFD | `22bdcee4d3684b08883d1c671146ec75` | `f58b366b91fb4bc8aef067f1dfbc3acc` |
| Sacks | `2cc9041115674a0082cf09ad634783a4` | `c1613d5f6b94402d9069f312d26d80e0` |
| GGCMI, expanded bbox | `8382b6698a8b42038aeab7c9fcd94f76` | `bcfbd7ebdc1840e2b05c835296f8ac56` |
| DEM, empty selector | `aab3f3cdab9941f78ecc6c7d117e75fe` | `2e8292b22fbd43419c00b435fa92bfa8` |
| HWSD, empty selector | `a6dcf01c782b456e967c658cbae98a96` | `039cb94f07604deea95a0a2d18a81174` |

The attempted approval click was blocked by the automation approval boundary;
it was not bypassed. Explicit authorization has been requested for up to ten
small acquisitions across these two sessions, bounded by the study region and
100 MB combined download budget, with no model runs or national-file downloads.

Still untested in this live GUI run: job creation, polling, manifest acceptance,
file transfer/checksums, actual variable/dimension/unit/time checks and provider
interpretation of those delivered files. Full data suitability/masked-source
QA (issue 2) and model execution are separate from this test's issue-1 verdict.
