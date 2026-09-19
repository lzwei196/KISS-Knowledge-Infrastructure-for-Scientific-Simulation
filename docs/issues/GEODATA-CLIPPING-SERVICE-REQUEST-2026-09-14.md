# Request: authenticated server-side geodata subsetting

Proposed contract for the backend team, not a deployed endpoint.

## Objective

Let Desktop request only the source cells, variables and time interval needed by
a scientific project, instead of downloading whole-China CMFD files and clipping
them locally. Extend the same job interface to DEM and other spatial attributes.
Existing manual Baidu delivery remains a fallback, explicitly labelled.

The backend must have reliable access to the source bytes. A catalogue entry and
Baidu share link alone are not sufficient for efficient server-side subsetting.
Please confirm which source datasets are locally mounted, indexed, and readable.

## First release scope

- CMFD: native-grid spatial subset and temporal/variable subset; preserve original
  units, calendar, time step, fill values, coordinates and provenance.
- DEM: crop by bbox with an optional declared halo; preserve native CRS/resolution
  by default. Hydrological delineation can require a wider upstream area than the
  output map: do not infer sufficient catchment coverage from a display bbox.
- Soil/land-cover attributes: crop spatial raster data. Table-only datasets (e.g.
  an HWSD attribute MDB) must be identified as tables, not falsely treated as raster
  grids; optionally deliver referenced attribute rows alongside spatial units.
- Do not silently reproject, interpolate forcing, aggregate time, fill gaps or
  invent boundary values. Such transforms need explicit options and scientific
  approval. Categorical rasters must not use bilinear interpolation.

## Proposed asynchronous protocol

1. Estimate request (read-only calculation): source ID/version, bbox/CRS, time
   interval, variables, output format, native grid or explicit target grid.
   Return source coverage, snapped output bounds, estimated output bytes, source
   I/O bytes, transformations, missing data and any manual fallback.
2. Create job only after user approves the request/estimate. Bind an idempotency
   key to the caller and canonical request. No arbitrary source URL or filesystem
   path is accepted from the client.
3. Poll job status: queued, inspecting, reading, subsetting, packaging, ready,
   failed, cancelled or expired. Report stage, completed source units, last
   progress time and honest byte counts; do not invent progress percentages.
4. Fetch result manifest, then authenticated downloadable parts. Include total
   bytes, SHA-256 per part, file names, exact bounds/CRS/grid, variables/units,
   dates/calendar, NoData, source IDs/versions/hashes and transformations.
5. Cancel job and expire cached results through documented lifecycle operations.

Suggested route family: `/api/obs/subsets/estimate`, `/api/obs/subsets/jobs`,
`/api/obs/subsets/jobs/{id}` and result downloads. These are suggestions, not URLs
the Desktop will call until the backend confirms and implements the contract.

## Capacity and security

An output of a few GB is a reasonable configurable upper bound, but is not a
guarantee of cheap processing. Annual compressed files may require large reads or
decompression; bound source I/O, temporary disk, RAM, CPU time and concurrent jobs
as well as output size. Large jobs need a queue, cancellation and cleanup.

- Use the existing activation-token header and dataset access permissions.
- Authorize every job/status/result access; job IDs are not access credentials.
- Cache key includes canonical request, dataset version and processing version;
  shared byte caches must not bypass per-user authorization.
- Support resumable downloads, expiry and checksums. The current Desktop's served
  download cap is 100 MB: GB-sized subsets require a dedicated bounded downloader
  or manifest parts, not silently raising every catalogue-download limit.
- Never return internal paths, activation tokens or Baidu credentials to agents.
- Reject malformed/nonfinite bounds and unsupported grids. Explain dateline
  handling, cell-centre versus edge selection, CRS transforms and time endpoints.

## Desktop integration

Project status should distinguish: “estimate awaiting approval”, “server preparing
subset”, “download ready”, “local scientific checks”, and “manual download needed”.
Keep study extent, source extent and actual output extent separate. Bind request,
estimate/version and manifest to the plan and receipts; verify the actual files
before VIC/CaMa preparation. Resolver must return the actual delivery mode, not
merely flip a spatial boolean without a usable result/job reference.

## Acceptance cases

1. North China diagnostic bbox `[115,37,117,39]`, CMFD daily `prec,temp`, 1989–1990:
   output values match a direct selection from original files; correct grid,
   dates and units; neither Huai data nor fabricated values accepted.
2. DEM bbox in a non-native CRS: output bounds, transform, pixel alignment and
   NoData verified; requested halo retained.
3. Categorical land cover retains valid class codes; table-only source receives
   an explicit unsupported-spatial-operation response.
4. Unknown/partial coverage, missing variables, cancelled job, quota, expired
   result, unauthorized job lookup, retries and checksum mismatch fail clearly.
5. Same request with a changed source version must not reuse stale output.

Please return a deployed API contract and one reproducible test response before
Desktop implementation. No server configuration or deployment was performed here.
