# GeoForge Database — consolidated backend handoff

Prepared 2026-09-16 from recorded live-service and compiled-desktop tests.
This consolidation made no new server requests or changes. Findings dated
September 14–15 need retesting if the backend has since changed.

## Overall result

Authentication, catalogue search and source-schema discovery work in the tested
paths. Retrieval is **not yet reliable end to end**. In the latest compiled-app
test, five user-approved acquisitions produced:

- Two accepted deliveries: HWSD China and China DEM, three TIFFs / 8,246 bytes.
- Two rejected deliveries: CMFD (wrong actual dates) and Sacks (bounds contract).
- One failed server job: GGCMI crop calendar.

These are acquisition tests, not completed simulations. Accepted transport does
not establish scientific suitability or equality to the original source pixels.

Base API: `https://app.geoforgehhu.com/api/obs`.
Endpoint paths below are relative to that base. Credentials are deliberately
excluded; use the normal authenticated client.

## Open issue inventory

| ID | Priority | Finding | Evidence / ownership |
| --- | --- | --- | --- |
| B1 | High | CMFD two-day request returns an entire year | Confirmed actual output; backend processing or stale-result path must be traced |
| B2 | High | Single-cell Sacks bounds cannot be interpreted consistently | Confirmed shared API/Desktop contract mismatch |
| B3 | High | GGCMI job fails with `internal_error: ValueError` | Confirmed server failure; traceback needed |
| B4 | High | Raster estimate accepts an unsupported explicit variable | Confirmed September 15; Desktop now blocks this, backend retest pending |
| B5 | High | Fixed processing can still reuse old invalid cached outputs | Confirmed September 14; no later closure evidence |
| B6 | Medium | Catalogue units conflict with native units; description coverage scope is unclear | Confirmed metadata discrepancy / contract clarification |
| B7 | Medium | HWSD geographic and Albers members disagree substantially | Confirmed discrepancy, not a proven subsetter defect |

### B1. CMFD: actual time clipping is wrong

Server job: `acb7d2c0a8704324`.
Request used for estimate and job:

```json
{
  "dataset_id": "cmfd_china_daily_010",
  "bbox": [115, 37, 115.1, 37.1],
  "variables": ["lrad", "prec", "pres", "rhum", "shum", "srad", "temp", "wind"],
  "start": "1989-01-01",
  "end": "1989-01-02"
}
```

All eight parts transferred through the GUI, totaling 181,288 bytes. The app
rejected the delivery with `Actual NetCDF time range exceeds the approved request`
and published no accepted inputs.

Independent inspection of the first part (`lrad`, 22,680 bytes) confirmed:

- `time=365`, `lat=1`, `lon=1`.
- First timestamp `1989-01-01 10:30:00`; last `1989-12-31 10:30:00`.
- SHA-256 matches the manifest and response checksum header.
- Manifest gives `year=1989`, but no actual time range or step count.

The independent inspection covered one part, not all eight. It is sufficient to
prove the returned acquisition violates the approved period. The precise cause
(current writer versus cached artifact) requires backend inspection.

**Required:** trace the job, apply the date slice to the actual output arrays,
and derive manifest dates/counts from the written files. Document inclusive
date-only end semantics so a two-day daily request retains both days, including
non-midnight timestamps. Do not widen the user request or weaken Desktop checks.

**Acceptance:** all eight requested variables contain exactly the requested two
daily samples; add within-year, cross-year, leap-day and supported nonstandard
calendar tests. Test both a fresh job and the identical previously failed request.

### B2. Sacks: coordinate centres are being treated as raster extents

Server job: `07889f89307f4560`.

```json
{
  "dataset_id": "crop_calendar_global",
  "bbox": [115, 37, 115.1, 37.1],
  "variables": ["harvest", "plant", "tot.days"]
}
```

All nine manifest parts report:

```json
{"crs":"EPSG:4326","bounds":[115.0417,37.0417,115.0417,37.0417]}
```

Estimate: one selected cell, `selection_empty=false`, same snapped bounds.
Desktop rejects `Invalid manifest bounds` before transferring files because its
extent validator requires positive area. A single coordinate centre can have
identical minima/maxima without representing an empty grid.

**Required shared contract:** distinguish coordinate-centre bounds from cell-edge
footprints; expose shape, native spacing or coordinate bounds, CRS, and selection
semantics. Do not invent spacing for irregular grids or blindly permit all
zero-area raster extents. Backend and Desktop must agree on these semantics.

**Acceptance:** one-cell, one-row, one-column, multi-cell and truly empty
selections are unambiguous and correctly handled. Verify actual file coordinates
against manifest metadata. Sacks contents were not inspected in this latest run.

### B3. GGCMI: server execution fails after a successful estimate

Server job: `852bc0c68458447d`.

```json
{
  "dataset_id": "ggcmi_crop_calendar",
  "bbox": [115, 37, 115.5, 37.5],
  "variables": ["maturity_day", "planting_day"]
}
```

Estimate selected one native 0.5-degree cell across 40 members. Job status:

```json
{"status":"failed","stage":"failed","error":"internal_error: ValueError"}
```

**Required:** retrieve this job's traceback, identify the failing operation/member,
fix that cause, and add a regression using the same request. The public error is
not enough to diagnose it. Return a safe actionable error code/stage and job ID;
retain private paths/tracebacks in server logs, not public responses.

### B4. Raster variable filters are not consistently enforced

September 15 GUI negative control:

```json
{
  "dataset_id": "china_dem_90m",
  "bbox": [115, 37, 115.1, 37.1],
  "variables": ["definitely_not_a_source_field"]
}
```

The server returned a positive raster estimate without confirming that selection.
In contrast, Sacks with the invalid field `planting_day` correctly returned
HTTP 400 `unknown_variable` (its actual field is `plant`).

**Required:** reject unsupported explicit selectors at both estimate and job
creation, or implement and advertise a real band/field selection contract.
An intentional `variables: []` whole-raster request remains valid. Never silently
reinterpret a nonempty rejected selection as all data.

Desktop has since added a hard block for an unconfirmed explicit selection.
That closes the client approval hole, not the backend inconsistency. Job-time
behavior for the invalid raster selector was not tested.

### B5. Invalid old results survive processing fixes

September 14 retest demonstrated:

- `hwsd_global`, bbox `[115,37,115.1,37.1]`, empty variables reused job
  `35497839150e49e3`: 288 raw bytes masquerading as TIFF. Alias
  `hwsd_global_raster` reused `c2783521191b401e` with the same failure.
- A nearby fresh bbox produced readable GeoTIFFs.
- `cn05.1_pre_daily_025`, bbox `[115,37,117,39]`, empty variables,
  January 1–7 1989 reused `7ee2ce4b2d7f4324`: 365 days, despite the old
  manifest claiming `time_subset_applied:true`.
- A fresh January 8–14 request produced the correct seven samples.

**Required:** bind cache identity to canonical request, actual source version,
processor version and contract version; invalidate or quarantine known-invalid
artifacts. Review aliases and job deduplication as well as direct result caching.

**Acceptance:** repeating the original scientific request returns corrected files
without asking the user to alter dates/bounds. An unchanged good result can still
be reused. No backend cache implementation was inspected locally, and closure
has not been retested since September 14.

### B6. Native metadata must remain authoritative and clearly scoped

CMFD catalogue precipitation is labelled `mm/day`; actual files and manifests
report `kg m-2 s-1`. The new describe path exposes native units, but catalogue
labels must not cause silent reinterpretation of the delivered numbers.

Also, the observed CMFD description represented an inspected 1989 time axis;
that does not establish the full product's temporal coverage.

**Required:** distinguish native name/unit from canonical quantity/unit and any
explicit conversion; distinguish inspected-file coverage from full-dataset
coverage. Preserve per-member differences and source-version provenance. Do not
publish sampled coverage as complete coverage. A versioned schema should explain
what was inspected and any truncation/unknowns.

**Acceptance:** discovery, describe, estimate, manifest and actual file metadata
are consistent or explicitly explain differences. Model-specific conversion is
a separately recorded preparation step, not an implicit download transformation.

### B7. HWSD source parity needs a data-provenance audit

Server job `074a6809bf404f18` delivered readable, checksum-correct geographic and
Albers soil-ID rasters. However, independent coordinate-aware comparisons found:

- Geographic centres sampled in Albers: 56/133 matching IDs (42.1%).
- Albers centres sampled in geographic: 45/93 matching IDs (48.4%).
- At 115.05 E, 37.05 N: geographic ID `11509`, Albers ID `11497`.

Different grids and class boundaries can explain some differences. This does
**not** prove interpolation corruption or a subset-service bug. The two products
must not be declared equivalent without investigating their source provenance.

**Required:** compare each delivered crop with its own original source window
(CRS, transform, mask and values), then audit upstream projection/resampling
history and identify the authoritative categorical product. Preserve IDs with
appropriate categorical handling. Soil-property lookup tables remain necessary;
these ID rasters are not ready-made model soil profiles.

## Additional protocol improvements, not proven current server failures

1. **Member selection:** Sacks returns nine crop members; GGCMI estimates 40.
   A variable selector is not a crop selector. Advertise all-member behavior
   clearly; consider explicit supported member IDs to request only maize, etc.
2. **Completeness and quality:** distinguish spatial/temporal/variable/member
   coverage, empty selection, unknown coverage and not-applicable dimensions.
   Header discovery cannot establish unmasked values. Report per-variable valid
   counts/fractions where supported; preserve real source masks rather than
   replacing missing values. This is the separate data-quality issue, not proof
   that every masked source is a backend error.
3. **Comparable estimates:** label whether size means uncompressed array payload
   or estimated transfer bytes. Small arrays can have much larger NetCDF headers;
   do not interpret that alone as a transfer defect.
4. **Source/offer binding:** make source and processor versions available across
   describe, estimate, job and manifest. A material change after approval should
   trigger a revised offer, not silently change the authorized acquisition.

## What has improved / should not be misreported as still broken

- Authenticated source descriptions work in the tested paths. Both Kimi and
  DeepSeek used correct native NetCDF fields in the compiled-app tests.
- Tested invalid NetCDF names receive `unknown_variable`, rather than all fields.
- DEM and HWSD China downloaded through the compiled app and opened with an
  independent local reader. Small file size is not itself an error.
- Earlier fresh-request checks succeeded for SoilGrids, CLCD, HWSD global and
  CN05. These checks did not establish every dataset or cached request is sound.
- The earlier CMFD all-variable test used two complete calendar years. Its pass
  did not test within-year slicing; the new two-day test exposed that gap.
- The September 14 transient 502/network outage recovered. There is no evidence
  here of a current outage or of its original cause.

## Desktop-only work — not requests for the backend team

- Bundle the raster content reader: this compiled app reports
  `raster_reader_unavailable` and content validation pending. An independent
  local reader was used for the TIFF checks; do not equate those with app checks.
- Persist manifest-preflight errors per acquisition. Sacks currently retains
  `ready` after its bounds rejection, so later UI actions can obscure the reason.
- Maintain project-relevant selection, approval/expiry feedback and explicit
  distinction between downloaded, content-checked and scientifically usable.
- Coordinate Desktop's B2 validator update with the agreed bounds contract;
  do not simply disable validation to obtain a passing download.

## Recommended order and closure evidence

1. Diagnose B1 and B3 by the supplied job IDs; settle B2's bounds contract.
2. Address B5 before accepting reruns, so old bad artifacts cannot hide fixes.
3. Enforce B4 consistently and reconcile B6 metadata.
4. Run B7 source-parity checks and keep scientific readiness pending meanwhile.
5. Repeat the five-dataset flow through the compiled app: search → describe →
   estimate → review/approve → job → download → inspect actual files.

For each fix return processor/contract version, regression tests, the old and
replacement job IDs, and file-derived evidence. Backend unit tests alone do not
close the desktop end-to-end test. Do not claim model readiness until KI-specific
preparation and input validation also succeed.

## Detailed evidence

- [Latest compiled-app acquisition test](GEOFORGE-DOWNLOAD-GUI-TEST-2026-09-16.md)
- [Actual raster inspection and HWSD comparison](GeoForge_downloaded_rasters_eda_report_2026-09-16.md)
- [Live-agent schema discovery and selector negative controls](GEOFORGE-DESCRIBE-IN-APP-TEST-2026-09-15.md)
- [Source-schema integration and scope limits](GEOFORGE-DESCRIBE-DESKTOP-INTEGRATION-2026-09-15.md)
- [Stale-cache regression and fresh-request comparisons](GEODATA-SUBSET-FIX-RETEST-2026-09-14.md)
- [CMFD whole-year, all-variable checks](CMFD-ALL-VARIABLES-LIVE-2026-09-14.md)
