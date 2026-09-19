# GeoForge Database source-schema discovery — desktop integration

Date: 2026-09-15. Scope: issue 1 (catalogue labels versus source variable names).

## Result

The desktop source now exposes the deployed authenticated
`GET /api/obs/subsets/describe?dataset_id=...` through the shared database adapter.
No dataset-specific alias dictionary was added. The catalogue remains the
discovery index; source descriptions supply the exact fields for extraction.

The server deployment was reported in a screenshot. Its source code and the
server-side `/mnt/datasets/geo-subset-describe-2026-09-15.md` were not available
locally. Integration was checked against actual authenticated endpoint responses.

## Agent flow and interfaces

1. Search the local catalogue for candidates using the KI's requirements.
2. Read each candidate's live description. Inspect names, units, dimensions,
   member files and selection notes; do not infer aliases or unit conversions.
3. Discuss suitability/data choices with the user. Metadata is not proof that
   values exist or that the model can consume the data directly.
4. Request an estimate using exact source names, study bounds and dates.
5. Obtain explicit acquisition approval before creating a job/downloading.
6. Validate the actual delivered files; model execution remains separately gated.

API providers, including DeepSeek:

```json
{"describe_dataset_id": "crop_calendar_global"}
```

Pass this to `search_observation_data`, separately from `subset_request` or
`resolve_dataset_id`.

CLI providers, including Kimi, use their Desktop-provided command:

```text
geoforge-db --describe crop_calendar_global
```

The bundled database KI's `tools/search_catalogue.py` accepts the same option.
Standalone desktop CLI spelling: `obs-search --describe DATASET_ID`.
The loopback capability stays distinct from the database activation token;
provider helpers never receive the real database token.

## Implementation

- `kiss/kiss_cli/obs_access.py`: authenticated describe client, allowlisted
  metadata projection, dataset/variable-list validation, shared dispatch and
  discovery instructions. Preserves member files, raster bands, source version
  and the server's `files_truncated` flag. Unknown response fields are omitted.
- Descriptions are fetched live on each explicit call. No stale-cache fallback
  is presented as current file metadata. `source_version` is retained as an
  opaque version, not misrepresented as a verified content checksum.
- `api.py`, `cli.py`, `gui.py`, `flowrun.py` and the bundled database helper expose
  the same operation. Mixed describe/resolve/estimate modes are rejected.
- `obs_subset.py`: preserves HTTP 400 `unknown_variable`, supplies a concrete
  describe-and-revise recovery action, and retains estimated `n_files` metadata.
- `data_contract.py`: an explicit variable selection cannot be approved if the
  estimate contradicts it or silently reports `"all"`. Legacy estimates that omit
  selected names remain explicitly unconfirmed; manifest checks still apply.
- `web/app.html`: variable errors show correction guidance instead of offering
  the same failing request's retry button. Outages retain the retry action.
- Database KI documentation explains source discovery, approval boundaries,
  multi-member scope and raster selector limitations.

Describe-first is now an explicit shared agent instruction and an available
tool, not a new persisted workflow gate. Hard checks reject contradictory
estimates and the server rejects unknown field names. We have not claimed that
every provider will necessarily choose the correct scientific field on every turn.

## Live checks using the updated desktop adapter

All requests were authenticated metadata reads or estimates. No subset jobs,
scientific data downloads, model executions or paid provider turns were made.

| Dataset | Description | Estimate through desktop |
|---|---|---|
| `crop_calendar_global` | 11 real fields; nine crop members, including maize | `plant`, `harvest`, `tot.days` returned exactly; `needs_review` because completeness was not confirmed |
| `cmfd_china_daily_010` | Eight real fields with units and dimensions | All eight requested and returned; eight parts; `awaiting_approval` |
| `china_dem_90m` | One int16 band; nodata 32767; EPSG:4326 declared; resolution/bounds | Explicit empty variable selection for whole-raster clipping; `needs_review` because completeness was not confirmed |
| `crop_calendar_global` with `planting_day` | Catalogue-style label deliberately used as a negative test | HTTP 400 `unknown_variable`; `describe_and_revise`; no job or approval |

The initial exploratory `merit_dem` description returned `describable:false`,
`not_locally_indexed`, `delivery_fallback:manual`. The positive DEM check used the
catalogue-listed `china_dem_90m`; no claim is made that every DEM is mounted.

## Verification and limits

Regression coverage includes source metadata preservation/redaction, fresh
versions, malformed or incomplete responses, raster metadata, unmounted sources,
API-tool dispatch during planning, standalone CLI dispatch, both Kimi helper
implementations, capability-protected loopback dispatch, exact variable matching,
and actionable unknown-variable failures. Existing data/flow regression tests
were run alongside these additions.

Final focused suite: **190 passed** (42.45 seconds), including both isolated
loopback-server tests. Test database responses were synthetic fixtures and no
real provider keys were used. Command:

```text
PYTHONPATH=kiss python3 -m pytest kiss/tests/test_obs_describe.py kiss/tests/test_obs_access.py kiss/tests/test_obs_subset.py kiss/tests/test_data_contract.py kiss/tests/test_flowgate.py kiss/tests/test_flowrun.py -q
```

All inline JavaScript parses. The variable-error/retry cards were checked in
English and Chinese, including HTML escaping. The bundled database KI's five
structural preflight checks pass.

Remaining boundaries:

- A request for crop-calendar variables still selects those variables across
  all matching crop files. No crop/member selector was invented or added.
- DEM bands are descriptive; the current server API does not select bands.
- Described temporal coverage can represent inspected files, not the full
  product. For example, the observed CMFD description reported an inspected
  1989 time axis; it must not be used to exclude all other years.
- Header metadata does not prove valid data values or scientific suitability.
  Issue 2 (masked/missing data) is deliberately unchanged.
- No live Kimi/DeepSeek reasoning turn was tested in this change. Their tool
  interfaces were tested; actual autonomous field selection remains a next test.
- No application bundle was rebuilt, running application replaced, Git push or
  release publication performed in this change.
