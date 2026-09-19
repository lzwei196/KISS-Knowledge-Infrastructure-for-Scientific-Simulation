# Request to the GeoForge Database backend: make the catalogue usable by the desktop planner

Date: 2026-09-11
From: GeoForge Desktop team
To: GeoForge Database / `app.geoforgehhu.com` observation-service developers
Status: evidence gathered from the live catalogue API on 2026-09-11 with a valid activation token
Priority: high. The desktop planner is being rewritten to pick datasets from this catalogue automatically. It can only be as good as the metadata below.

---

## 1. Why we are asking

GeoForge Desktop will download the full catalogue once (about 1,100 records of metadata) and let the
planning agent choose datasets locally by variable, place, period and station. Served datasets are
then downloaded automatically after the user approves the plan; manual datasets are shown to the
user with the Baidu link and target folder.

For that to work, every record needs machine-readable coverage, period, variables and delivery.
Today most records do not have them. The information often exists, but it is written in prose
inside `notes`, or is missing.

This is not about the search endpoint. Keyword search (`GET /catalogue?q=`) now returns the right
records for `Bengbu`, `discharge`, `gauge`, `huai`, `51080`, `CMFD` and `forcing`. Thank you for
the September 10 fix.

## 2. What the API returns today (measured 2026-09-11)

`GET /catalogue?offset=N&limit=100` paged to the end: 1,106 records.

Delivery: 826 served, 279 manual, 1 `unmeasured` (see 3.1).

Per-record fields and how many of the 1,106 are empty:

| Field | Empty | Comment |
|---|---:|---|
| `id`, `name`, `type`, `delivery` | 0 | good |
| `size` | 1 | good |
| `dataset_kind` | 6 | |
| `format` | 27 | |
| `applicable_domains` | 49 | |
| `shape` | 144 | |
| `n_records` | 280 | acceptable for non-tabular data |
| `sha256` | 280 | all manual records; fine |
| `spatial_coverage` | 433 | and 507 of the rest are free text, see 3.2 |
| `variables` | 796 | see 3.4 |
| `start_date` / `end_date` | 907 / 909 | see 3.3 |
| `lat` / `lon` | 1,036 | only gauges; fine if bbox exists |
| `resolution` | 1,029 | see 3.5 |

`spatial_coverage` value formats: 433 empty, 507 free-text place names ("Jornada Experimental
Range", "China — 淮河 (Huai River)"), 90 `bbox:minlon,minlat,maxlon,maxlat`, 36 `point:lat,lon`,
29 the single word `global` or `China`, 11 free text with degrees ("60N-10S, 90-160E").

`start_date` value formats: 907 empty, 108 `YYYY-MM-DD`, 85 `YYYY`, 5 `YYYY-MM`, 1 other.

`variables` entry shapes: 796 empty, 307 lists of `{"name": ...}` objects, 3 lists of plain
strings. No units, no canonical names.

## 3. Specific problems, with examples

### 3.1 Undefined delivery value

`cmfd_huai_3hr_025` has `delivery: "unmeasured"`, `size: null`, `variables: []`, and in the
detail endpoint `size: 7892006694`. The desktop only understands `served` and `manual`. Please
make delivery one of those two and fill `size` in the list response.

### 3.2 Coverage is in prose, not in fields

`cmfd_huai_daily_025` list record: `spatial_coverage: null`, `resolution: null`, `lat/lon: null`.
Its detail record carries the truth in `notes`:

```
Pre-clipped to Huai basin extent, ready to use as VIC/SWAT/etc forcing | Coverage: Huai River basin (31-35N, 112-120E) | Resolution: 0.25 deg
```

Same for `cmfd_china_daily_010` (`notes: "Coverage: All China (15-55N, 70-140E) | Resolution: 0.1 deg (~10 km)"`)
and all seven `cama_glb_*` records (no coverage at all, `variables: []`).

An agent cannot intersect a study area with "Huai River basin (31-35N, 112-120E)" inside a
sentence. It can with `bbox: [112, 31, 120, 35]`.

### 3.3 Period is missing or in mixed formats

907 records have no `start_date`. Of those that do, three formats are mixed. Examples:
`bengbu_51080` = `1950-01-01`, `cmfd_huai_daily_025` = `1960`, `grace_jpl_mascon` = `2002-04`.
Many static datasets legitimately have no period; please distinguish "static" from "unknown".

### 3.4 Variables are missing or unnamed

796 records have no variables. Where they exist there are no units and no canonical names, so
"precipitation" in one record and "prec" in another cannot be matched. The two national CMFD
records and the Huai daily subset each list 8 variables; the Huai 3-hourly subset lists none.

### 3.5 Resolution is missing for gridded data

1,029 records have no `resolution`. For gridded and forcing data the planner needs it to decide
whether a dataset fits a model grid.

### 3.6 No parent/child or tile relationships

`cmfd_china_daily_010` (242 GB) and `cmfd_huai_daily_025` (0.98 GB) are unrelated records. The
agent has no way to learn that the second is a subset of the first, or to find the smallest
piece that covers a study area. The same applies to the `cama_glb_*` family and to the per-basin
`*_basin` shapefiles. If the server holds CMFD split by region or grid, each piece should be its
own record with a `bbox` and a `parent_id`.

### 3.7 Duplicate records for one asset

Same size, different ids:

- `soilgrids_bengbu` and `soilgrids_global` (906,320 bytes)
- `dem_china_90m` and `china_dem_90m` (3,548,137,688)
- `hwsd_global` and `hwsd_global_raster` (about 1.87 GB)
- `cama_glb_15min` and `cama_maps_15min_extracted` (8,455,574,058)
- `rgi_v62` and `rgi_v62_glaciers`, `glhymps` and `glhymps_global`, `fan_wtd` and `fan_wtd_global`

Agents pin one id in the plan and users see two candidates that look identical. One canonical
id per asset, with `aliases: [...]` if old ids must keep working.

### 3.8 One field, two meanings

`type` and `dataset_kind` overlap and are used inconsistently (`type: forcing, dataset_kind: forcing`
for CMFD; `type: discharge, dataset_kind: gauge` for Bengbu; `type: shapefile, dataset_kind: static_dataset`
for basins; `type: lter_ecology, dataset_kind: ltar_library` for 539 LTAR records). Please define
each once, with a fixed value list, so the desktop can filter without guessing.

## 4. What we are asking for

### 4.1 Record schema (list and detail endpoints return the same fields)

```json
{
  "id": "cmfd_huai_daily_025",
  "aliases": [],
  "parent_id": "cmfd_china_daily_010",
  "name": "CMFD Huai River subset, daily, 0.25 deg",
  "category": "forcing",
  "shape": "gridded",
  "delivery": "manual",
  "size": 983789849,
  "sha256": null,
  "format": "netcdf",
  "bbox": [112.0, 31.0, 120.0, 35.0],
  "point": null,
  "region_names": ["Huai River basin", "淮河"],
  "resolution_deg": 0.25,
  "time_step": "1D",
  "start_date": "1960-01-01",
  "end_date": "2020-12-31",
  "temporal": "series",
  "variables": [
    {"name": "prec", "canonical": "precipitation_rate", "unit": "mm/day"},
    {"name": "temp", "canonical": "air_temperature", "unit": "K"}
  ],
  "notes": "Pre-clipped to Huai basin extent."
}
```

Rules:

- `delivery` is exactly `served` or `manual`.
- `bbox` is `[min_lon, min_lat, max_lon, max_lat]` in WGS84, required for every gridded, regional
  or basin record. `point` is `[lat, lon]` for gauges. A global dataset has `bbox: [-180,-90,180,90]`.
- `start_date` and `end_date` are `YYYY-MM-DD`. `temporal` is `series`, `static` or `climatology`;
  static records leave the dates null.
- `variables` always has `name` and `unit`; `canonical` uses one shared vocabulary that we can
  publish together (the desktop already uses ids such as `precipitation_rate`, `air_temperature`,
  `discharge`).
- `category` and `shape` each come from a fixed list you publish once.
- Everything that is in `notes` today as "Coverage: ..." or "Resolution: ..." moves into fields.
  `notes` stays for prose only.

### 4.2 Structured filters on the catalogue endpoint

Optional parameters, all combinable with `q`:

```
GET /catalogue?bbox=112,31,120,35&start=1980-01-01&end=1990-12-31&variable=precipitation_rate&category=forcing&delivery=served
```

- `bbox` returns records whose bbox intersects, or whose point lies inside.
- `start`/`end` return records whose period overlaps.
- `variable` matches `canonical` or `name`.

The desktop will also filter locally, so this is second priority behind 4.1.

### 4.3 Tiles for the large national products

If CMFD and similar products are stored by region or grid block on the server, publish each block
as a record with its own `bbox`, `size`, `delivery` and `parent_id`. The desktop will pick the
blocks that intersect the study area and show the user only those Baidu links.

### 4.4 Answers we need

1. What is the size limit for `served` delivery? The desktop currently refuses served downloads
   above 125 MB; we will raise it to match yours.
2. Can the server clip a gridded dataset by bbox and period on request, or is delivery always
   whole files? If clipping is possible, the Huai example becomes a 50 MB served download.
3. Is there an endpoint that returns the whole catalogue in one call, or should the desktop keep
   paging at 100? Paging works; one call would be simpler.
4. Is there a `last_modified` on records, or an ETag on the catalogue, so the desktop can refresh
   only when something changed?

## 5. Acceptance test

Using only the list endpoint and a study area of Bengbu, Huai River, 1980 to 1990, daily:

1. Filter records with `category: forcing`, bbox intersecting `[116,31,119,34]`, period overlapping
   1980 to 1990, and a variable with canonical `precipitation_rate`.
2. Expected result: the smallest CMFD piece that covers the area, with its `delivery`, `size` and
   `parent_id`, and not the 242 GB national record as the only option.
3. Filter `shape: point` inside the same bbox with canonical `discharge`: expected `bengbu_51080`
   and `huaibin_51020`, each with `point`, `start_date`, `end_date`, `n_records`, `sha256`.
4. No record in the whole catalogue has `delivery` outside `served`/`manual`, a gridded record
   without `bbox`, or a series record without `start_date`.

## 6. Data that the desktop will not ask for

Baidu links, extraction codes, signed download URLs and any credential stay out of the list and
detail endpoints. The desktop reads them only from the authenticated `/download` handoff after
plan approval, and never shows them to the agent.
