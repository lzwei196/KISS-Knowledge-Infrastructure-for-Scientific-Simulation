# GeoForge DB subset audit: actionable backend failures

Test date: 2026-09-14. Authenticated requests to
`https://app.geoforgehhu.com/api/obs`. Tokens and private download links omitted.
These are live backend/client tests, not simulated responses or model runs.

## Completed catalogue screen

All **1,106 unique cached catalogue IDs** received a read-only estimate request.
Four bounded workers were used; no jobs were created by this screen.

| Response observed | Records |
| --- | ---: |
| Positive subset estimate with nonzero output | 46 |
| `subsettable:true` but zero bytes and unspecified kind | 41 |
| Explicit non-subsettable with manual fallback | 955 |
| HTTP 500 | 62 |
| HTTP 400 `no_coverage` for test area | 2 |

The 46 nonzero estimates comprise 32 generic NetCDF, 9 continuous rasters,
3 categorical rasters and 2 CMFD grid records. These counts describe this
catalogue snapshot and these probes, not the backend's total intrinsic capability
or a claim that all 46 have been fully downloaded and scientifically validated.
No dataset ID was omitted from the estimate screen. The 955 fallback responses
include many tables and other non-spatial records; they are not 955 failures.

## 1. HWSD jobs report ready but deliver unreadable raster bytes

Request to `POST /subsets/estimate`, then `POST /subsets/jobs`:

```json
{"dataset_id":"hwsd_global","bbox":[115,37,115.1,37.1],"variables":[]}
```

- Job `35497839150e49e3`: ready, one part, 288 bytes.
- Manifest filename `hwsd_global__crop.tif`, source file `hwsd.bil`, CRS `UNSET`.
- SHA-256 `9020053c6a0d73d82b85f28cc83664baa5df6351252d355b97b635e1a097b30c`.
- Estimate says 12 × 12, native/target CRS `UNSET(assume EPSG:4326)`.
- Checksum and byte count match; rasterio cannot open the downloaded file.
- `file` identifies it only as `data`, not TIFF. Initial bytes are
  `05 2d 05 2d d4 2c d4 2c`, not a TIFF/BigTIFF signature.
- Same failure for alias `hwsd_global_raster`, job `c2783521191b401e`.

Likely cause (inference, backend source not inspected): the crop writer retained
the source BIL driver but assigned a `.tif` extension, delivering raw pixels
without the necessary sidecars. Set output driver explicitly to GTiff with valid
georeferencing, or deliver a complete, correctly named BIL bundle. Do not merely
rename bytes. Resolve CRS from trusted metadata; do not silently assume it.

Acceptance: downloaded output opens independently, contains correct CRS/transform,
has 12 × 12 expected cells and categorical codes, and can be matched to the
original source window. Hash correctness alone is insufficient.

## 2. Generic NetCDF ignores requested day interval

```json
{"dataset_id":"cn05.1_pre_daily_025","bbox":[115,37,117,39],"variables":[],"start":"1989-01-01","end":"1989-01-07"}
```

- Job `7ee2ce4b2d7f4324`: ready.
- Download: `cn05.1_pre_daily_025__CN05.1_Pre_1961-2022_daily_025x025_subset.nc`,
  168,502 bytes; checksum verified.
- Spatial subset is 9 × 9 cells within the requested bbox.
- Actual time axis: **365 daily samples, 1989-01-01 through 1989-12-31**.
- Request was **7 days**, not an annual delivery request.
- The `pre` variable in the result has no `units` attribute. Original-file units
  were not independently inspected, so loss during clipping is not established.

Apply temporal slicing to actual coordinates, not just filename/year selection.
Return actual dates/calendar and `time_subset_applied` in the manifest. A temporal
request that cannot be honored should fail or disclose a different delivery for
approval, not report an apparently successful precise subset.

## 3. Estimate errors and ambiguous positive responses

The full catalogue probe results, including each exact request, are in
`output/geodata-subset-audit-2026-09-14/estimates.json`.

Examples reproducibly returning HTTP 500: `hwsd_china`, `soilgrids_global`,
`clcd_china_land_cover`. Requests use the saved catalogue-centre or explicitly
labelled unlocated North-China probe. Unsupported readers or unavailable local
sources should return structured non-subsettable/manual status, not HTTP 500.
Do not infer the internal cause from the HTTP status alone.

Some entries return `subsettable:true`, zero estimated bytes, and no `kind`,
`over_output_cap`, or `coverage_complete`. A focused `argo_salinity` probe returned
only `coverage`, `estimated_output_bytes`, `n_selected_cells`, `subsettable`.
Distinguish capability from an actual nonempty selection. These positives are
not counted as ready-to-download evidence.

Raster and generic NetCDF estimates also lack the CMFD coverage contract. Desktop
currently leaves those in review; this audit uses explicit test-authorized jobs
without changing or fabricating Desktop scientific approvals.

## Successful small delivery checks (not full scientific certification)

| Dataset | Live result |
| --- | --- |
| `china_dem_90m` | Valid GeoTIFF, 124 × 124, EPSG:4326, 6,636 bytes; bounds/resolution/NoData read |
| `avhrr_landcover` | Valid categorical GeoTIFF, 10 × 10, EPSG:4326, 526 bytes; integer values 8–11 |
| `dtb_china` | Valid GeoTIFF, 120 × 120, EPSG:4326, 65,950 bytes; finite data |
| `crop_calendar_global` | 9 readable NetCDFs, 24 × 24, 387,863 bytes total; coordinates inside study bbox |

Crop-calendar `index` / `filled.index` layers can be entirely masked, while
plant/harvest layers contain data. This was recorded, not indiscriminately treated
as corruption. Original-source parity, crop meaning and model suitability still
need domain-specific checks. Its real variable names also differ from catalogue
friendly names; agent requests need authoritative variable mappings.

## Scope limits

Catalogue estimates are capability probes, NOT downloads of every record.
Unknown spatial coverage uses a labelled test bbox, so a negative/empty probe
does not prove global unavailability. Catalogue IDs may alias the same source.
Small actual downloads cover seven non-CMFD records; four pass delivery checks,
two HWSD entries fail raster decoding, and CN05 fails the requested time window.
No DEM delineation, routing, scientific simulation or calibration was performed.
