# Desktop check of the backend response, 2026-09-11

Every claim below was tested against `https://app.geoforgehhu.com/api/obs` with a valid activation
token on 2026-09-11, after the backend reported deployment.

## Confirmed live

- `delivery` is now only `served` (826) or `manual` (280). `cmfd_huai_3hr_025` is manual, 7.89 GB.
- `bbox` on 156 records, `point` on 69 gauges, `temporal` on all records
  (202 series, 234 static, 670 unknown), `resolution_deg` on 78, `parent_id` on the two Huai CMFD
  subsets. `etag` on every catalogue response.
- Structured filters work on the list endpoint. The acceptance query returns exactly the national
  daily CMFD and the Huai daily subset with its `parent_id`.
- No served record exceeds 100 MB.
- No credential, link or code appears in list, detail or resolve responses.

## Not as described, please fix

### A. `/resolve` ignores every parameter

All four of these return the same 1,183 items, the full national daily CMFD split by
variable and year, 1951 to 2024, estimated 1.22 TB, `query_bbox` all China:

```
/resolve?dataset_id=cmfd_china_daily_010&bbox=112,31,120,35&start=1980-01-01&end=1990-12-31&variable=prec
/resolve?dataset_id=cmfd_china_daily_010&start=1980-01-01&end=1990-12-31
/resolve?dataset_id=cmfd_huai_daily_025&start=1980-01-01&end=1990-12-31
/resolve?dataset_id=bengbu_51080
```

Expected for the first query: 11 items (`prec`, 1980 to 1990), about 2.4 GB. Expected for the
last: nothing, or the gauge itself; a discharge gauge has no CMFD children.

Also: `coverage_complete: true` and `gaps: []` are returned even though no filter was applied,
so the desktop cannot trust them yet. Please send `OBS_ACCESS_API_ADDENDUM.md`; it is not in
our repository and we have no contract for `/resolve` or `/obs/child/{id}/download`.

### B. Detail endpoint was not updated

`GET /{id}` still returns the old shape. For `cmfd_huai_daily_025` it gives `start_date: "1960"`,
`spatial_coverage: null`, no `bbox`, no `parent_id`, no `temporal`, no `resolution_deg`, while
the list endpoint gives the new fields. Until they match, the desktop will read metadata only
from the list endpoint. Please emit the same serializer on both.

### C. End dates are truncated to January 1

Year-only `end_date` values were normalised to `YYYY-01-01`: national CMFD ends `2024-01-01`,
the Huai subset ends `2020-01-01`, instead of `2024-12-31` and `2020-12-31`. A period-overlap
filter for December of the last year now returns nothing. Start dates should round down and end
dates should round up: `YYYY` to `YYYY-12-31`, `YYYY-MM` to the last day of that month.

### D. `bbox` still missing on some records that state coverage in prose

`cmfd_china_3hr_010` has no bbox while its daily sibling does. Same for `cmfd_huai_3hr_025`
(could inherit from `parent_id`, or from the daily subset), `era5_precip_china_daily` and
`mswx_precip_china_daily` (both say "100-125E, 20-53N" in `spatial_coverage`), and
`era5land_nh` ("NH 30-75N all-lon"). The prose parser covers `(31-35N, 112-120E)` but not
`100-125E, 20-53N` or `30-75N all-lon`.

### E2. `notes` is only on the detail endpoint

The list endpoint omits `notes`, so the prose coverage ("Coverage: Huai River basin ...") is
invisible to a client that reads the list only. Please include `notes` in list records.

### E. `variable` filter matches raw names only

`variable=discharge` returns nothing; `variable=discharge_m3s` returns 36 gauges. That is the
expected behaviour before canonical tagging. Until the vocabulary is agreed, the desktop will
filter locally by substring, so this is informational.

## Decisions the backend asked the desktop for

1. Served cap: the desktop will lower its limit from 125 MB to your 100 MB. No change needed
   on your side.
2. Whole-catalogue call: not needed. Paging at `limit=500` with the ETag is enough.
3. Clipping service: yes, please scope it. A bbox and period clip of gridded data is the single
   change that turns the Huai case from a manual 0.98 GB download into a served one. Scope it as
   `GET /clip?dataset_id=&bbox=&start=&end=&variables=` returning a served zip with sha256.
4. Canonical variable vocabulary, duplicate survivors and the `category` mapping: the desktop
   team will send these as one file. Do not tag or merge before then.

## What the desktop will do now

- Read metadata from the list endpoint only, refresh on ETag change.
- Use `bbox`, `point`, `temporal`, `parent_id`, `resolution_deg` where present; fall back to
  substring match on `name`, `spatial_coverage` and `notes` where not.
- Treat `/resolve` as unavailable until A is fixed and the addendum is received.

## F. Served vector and raster assets are incomplete (found in a live run, 2026-09-12)

During an end-to-end VIC run the desktop downloaded these served datasets by id, checksum
verified, and the KI tools could not use them:

- `huaihe_basin` (565,068 B, `format: vector`): the served file is the bare `.shp` only. No
  `.shx`, `.dbf`, `.prj`. GDAL cannot open a layer from a lone `.shp`, so basin delineation
  failed. Same shape for every served single-file vector: `bengbu_basin` (96,428 B),
  `wangjiaba_basin` (291,508 B), `xixian_basin` (90,684 B). Please serve vector datasets as a zip
  containing the full shapefile set (or as GeoPackage / GeoJSON, one self-contained file), and
  set `format` accordingly.
- `hwsd_raster` (32,739,328 B, name "HWSD raster"): the served file is `hwsd_raster.mdb`, the
  HWSD attribute database. The VIC KI can consume it, so this is a naming question rather than a
  blocker: please make `name`, `format` and `files` say what the file is, and list the raster
  (`hwsd.bil` + header) under its own id if it is also available.

Both files passed the SHA-256 check, so the desktop cannot detect a missing sidecar; only the
catalogue can say what a served file actually contains. A `files: [...]` list per served dataset (names and
sizes inside the zip) would let the planner check completeness before approval.
