# GeoForge compiled-app download test — 2026-09-16

## Result

The user approved five subset jobs in the GUI and then explicitly authorized
testing downloads. Four jobs were ready; all four download buttons were exercised
through the running compiled app, not substituted with a script that bypasses
the desktop guards. **Two acquisitions were accepted, two were rejected, and one
had already failed on the server. No models were run.**

| Dataset | Job | GUI download outcome |
| --- | --- | --- |
| CMFD daily | `acb7d2c0a8704324` | 181288 bytes transferred, rejected by actual NetCDF date check |
| Sacks crop calendar | `07889f89307f4560` | Rejected at manifest-bounds validation, before file transfer |
| HWSD China | `074a6809bf404f18` | Accepted: 2 TIFFs, 1610 bytes |
| China 90 m DEM | `5622d1d0c07b4256` | Accepted: 1 TIFF, 6636 bytes |
| GGCMI crop calendar | `852bc0c68458447d` | Server job failed; no downloadable result |

Ready on the server is not the same as a locally accepted acquisition. This run
demonstrated why the post-download checks are necessary.

## Environment and evidence location

- UI: `http://127.0.0.1:61823/`
- Session: `5c4bfebf34bc`, Kimi Code
- App: `/Users/leo/kiss/builds/dist-data-approval-retry-20260915-v0.6.52/GeoForge Desktop.app`
- Project: `/Users/leo/kiss/projects/describe-ui-20260915/2026-09-15-This-is-a-real-GeoForge-Database-data-acquisitio--5c4bfebf34bc`
- Acquisition state: `<project>/.geoforge/subsets/`
- Accepted files: `<project>/inputs/geoforge_subsets/`
- Database base: `https://app.geoforgehhu.com/api/obs`

No token or authorization header is included here. Follow-up backend diagnostics
used the normal authenticated client for read-only job/manifest requests. A
single CMFD part was inspected in memory for diagnosis; it was not published as
an accepted project input.

## 1. CMFD: confirmed backend temporal-subsetting defect

Approved request, unchanged between estimate and job:

```json
{
  "dataset_id": "cmfd_china_daily_010",
  "bbox": [115.0, 37.0, 115.1, 37.1],
  "variables": ["lrad", "prec", "pres", "rhum", "shum", "srad", "temp", "wind"],
  "start": "1989-01-01",
  "end": "1989-01-02"
}
```

The GUI transferred all 8 parts (181288 bytes), then reported:

```text
Actual NetCDF time range exceeds the approved request
```

The desktop did not publish the rejected temporary inputs. Local acquisition
`0ac9c3409cad4f05b4d9976e761a506c` is `download_failed`, without an accepted path.

An independent in-memory inspection of the manifest's first part, `lrad`, found:

- 22680 bytes; computed SHA-256 and response checksum header match the manifest.
- Dimensions: `time=365`, `lat=1`, `lon=1`.
- Decoded first timestamp: `1989-01-01 10:30:00`.
- Decoded last timestamp: `1989-12-31 10:30:00`.
- Calendar: `standard`.
- Manifest advertises `year=1989`, but no `time_range`, `n_time_steps`, or
  `time_subset_applied` for that part.

This is not a bad variable alias or corrupt transfer. The returned file contains
a full year where two days were approved. The desktop rejection is correct.
The other seven parts were transferred and checksum-checked during the app test,
but this independent date diagnosis examined one part, not all eight.

Backend follow-up: ensure the actual CMFD job writer applies the approved date
slice, then emits file-derived time range and step count in its manifest. Do not
fix this by widening the client request or weakening the date guard.

## 2. Sacks: one-cell bounds semantics mismatch

Approved request:

```json
{
  "dataset_id": "crop_calendar_global",
  "bbox": [115.0, 37.0, 115.1, 37.1],
  "variables": ["harvest", "plant", "tot.days"]
}
```

The GUI reported `Invalid manifest bounds` before downloading parts. All nine
manifest parts report:

```json
{
  "crs": "EPSG:4326",
  "bounds": [115.0417, 37.0417, 115.0417, 37.0417],
  "variables": ["harvest", "plant", "tot.days"]
}
```

The estimate has the same `snapped_output_bounds`, `n_selected_cells=1`,
`selection_empty=false`, `kind=netcdf_grid`, and `cell_selection=cell within bbox`.
Neither shape/resolution in the parts nor an output-grid definition was provided.
The nine parts total 98384 bytes on the server.

The server is reporting min/max coordinate centres for a single selected cell;
the desktop `_box()` validator requires positive-area extents. These are different
semantics. It is not evidence that the selection is empty or that the names are
wrong. No Sacks file contents were inspected in this run.

Follow-up: define explicit bounds semantics, shape and grid spacing/cell edges in
the shared contract, and add single-cell regression cases. Do not blindly treat
all zero-area geometry as a valid raster extent.

Desktop UX follow-up: this manifest preflight exception is only displayed in the
action feedback; the saved acquisition remains `ready`. Thus a later action can
replace the visible error while the affected row again looks ready to download.
Persist the stage/reason per acquisition so this blockage remains understandable.

## 3. HWSD and DEM: accepted downloads, independently opened

The app fetched, checked hashes and atomically saved these files. An independent
local `rasterio` read confirmed all three byte counts, SHA-256 hashes and manifest
bounds match. This additional inspection did not overwrite app state or promote
scientific readiness.

| File | Bytes | Shape (bands × rows × columns) | Finite unmasked cells | Numeric range |
| --- | ---: | --- | ---: | --- |
| `hwsd_china__HWSD_China_Albers.tif` | 876 | 1 × 12 × 10 | 120 / 120 | 11476–11525 |
| `hwsd_china__HWSD_China_Geo.tif` | 734 | 1 × 12 × 12 | 144 / 144 | 11476–11525 |
| `china_dem_90m__crop.tif` | 6636 | 1 × 124 × 124 | 15376 / 15376 | 26–40 |

The HWSD files have Albers and EPSG:4326 CRSs respectively. The DEM is EPSG:4326,
with nodata=32767; none of this small delivered crop is masked. HWSD values are
mapping-unit identifiers, not a soil-property profile.

Acquisition IDs:

- HWSD: `4b8c7373325a4856b741f4c451708b16`
- DEM: `8a9b630af37142f08dd7a8ea3797beaa`

Total accepted local delivery: **8246 bytes across 3 files**.

Desktop packaging gap: the frozen app reported
`content_validation.status=pending`, `raster_reader_unavailable`. Its optional
raster reader is not available in this build. The separate local reader worked,
but that does not mean the compiled app performed the same check. Scientific
validation remains pending; no model-input conversion or source-cell parity test
was performed.

## 4. GGCMI: backend exception, exact cause still requires server log

Read-only `GET /subsets/jobs/852bc0c68458447d` returned:

```json
{"status":"failed","stage":"failed","error":"internal_error: ValueError"}
```

Approved scope: dataset `ggcmi_crop_calendar`, bbox `[115,37,115.5,37.5]`, variables
`maturity_day` and `planting_day`, no date filter. The accepted estimate selected
one native grid cell across 40 members. The public response does not expose the
traceback; the exact backend cause must not be guessed.

## Conclusion

The approval/UI repair works, but end-to-end retrieval is **not fully working**.
Actual file testing established two usable transport deliveries, one correctly
rejected wrong-period delivery, one manifest contract mismatch, and one server
exception. Exact variable discovery alone does not establish correct clipping,
delivery semantics, compiled-reader availability, or scientific suitability.
