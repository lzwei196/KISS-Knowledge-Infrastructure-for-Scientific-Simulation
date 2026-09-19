# Handoff: CMFD regional/tile records are not exposed to GeoForge Desktop

Date: 2026-09-10  
Audience: HydroCraft DB / `app.geoforgehhu.com` observation-service developers, with notes for the GeoForge Desktop team  
Status: **backend catalogue exposure gap confirmed; exact backend implementation fault not yet located**  
Priority: **high for real VIC, WRF-Hydro, CRHM, SWAT+ and coupled routing projects in China**

## 1. Executive summary

HydroCraft is understood to contain CMFD data split by grid or region, with separate Baidu Pan
links for the downloadable pieces. GeoForge Desktop should therefore be able to select only the
CMFD pieces intersecting a project's study area and time period.

That is not what the currently deployed observation catalogue exposes. During a live Desktop test,
an authenticated search for `cmfd` returned only five top-level records. The two useful forcing
records were entire-China directories: approximately 242 GB for daily data and 649 GB for
three-hourly data. Searches for the known Huai River subset IDs returned no results.

Consequently, DeepSeek did not have a smaller CMFD option to choose. It could only see the
whole-China parent records and reasonably concluded that the user would have to perform a very
large manual download. For a Bengbu VIC–CaMa-Flood project, that conclusion is operationally
wrong even if the catalogue response itself is being interpreted correctly.

This is primarily a **HydroCraft DB → observation catalogue API publication/indexing issue**, not
an LLM reasoning failure and not a model-execution failure.

The desired chain is:

```text
HydroCraft CMFD grid/region records + PanDisk mappings
                         ↓
authenticated catalogue index with spatial/time/variable metadata
                         ↓
resolve the minimal records intersecting the project request
                         ↓
approved GeoForge plan pins the exact child dataset IDs
                         ↓
manual PanDisk handoff for those IDs only
                         ↓
user places files under the exact project inputs path
```

The current chain stops at the second step because only aggregate parent records are visible.

## 2. User scenario that exposed the problem

The test request was a VIC–CaMa-Flood simulation for the Bengbu gauge in the Huai River basin,
covering 1980–1990. The project needs meteorological forcing for only the basin and requested
period, not all CMFD variables for all of China from 1951–2024.

The Agent searched the authenticated HydroCraft catalogue during planning. It found the aggregate
CMFD records and treated the data requirement as a 242/649 GB manual download. The user pointed
out that CMFD had already been split and that each grid/region should have its own PanDisk link.

This distinction matters:

- The large parent records are useful descriptions of the complete holdings.
- They are not appropriate download units for a basin-scale Desktop project.
- The Agent cannot infer hidden child IDs or private download mappings.
- The Agent must not invent or synthesize forcing when the real catalogue appears incomplete.

## 3. Evidence from the deployed catalogue

On 2026-09-10, an authenticated Desktop catalogue request equivalent to:

```http
GET /api/obs/catalogue?q=cmfd&limit=100
Authorization: Bearer <activation token>
```

returned `total: 5` and only these CMFD-related entries:

| Dataset ID | Delivery | Approximate size | Period | Meaning |
|---|---:|---:|---|---|
| `cmfd_china_3hr_010` | manual | 649,142,267,059 bytes | 1951–2024 | whole-China 0.1° three-hourly directory |
| `cmfd_china_daily_010` | manual | 242,207,573,601 bytes | 1951–2024 | whole-China 0.1° daily directory |
| `cmfd_china_monthly_010` | manual | 994,639,138 bytes | 1951–2024 | whole-China monthly product |
| `cmfd_mean_daily_clim_1951_2020` | served | 653,077 bytes | 1951–2020 | mean daily climatology, not project forcing |
| `cmfd_rainbelt_annual_jja_1951_2024` | manual | 172,630,327 bytes | 1951–2024 | derived annual rain-belt product |

The detail responses for the first two records described directory-level national products. They
did not expose child regions, tiles, grid records or a discoverable relationship to smaller
download units. This is correct with respect to keeping Baidu credentials out of catalogue
metadata, but the absence of child dataset metadata makes spatial selection impossible.

Exact catalogue searches returned zero matches for:

```text
cmfd_huai_daily_025
cmfd_huai_3hr_025
huai cmfd
forcing huai
```

A complete scan of the 1,104 records exposed by the API found only the same five records whose ID,
name or dataset kind identified them as CMFD/forcing. This rules out the simple explanation that
the child records were present under another page of the catalogue.

No Baidu URL or extraction code was requested or printed during this diagnosis. Those values
should remain restricted to the authenticated `/download` handoff response.

## 4. Evidence that smaller CMFD holdings are known elsewhere

The repository's server data registry contains the following records:

```yaml
- id: cmfd_huai_daily_025
  name: "CMFD Huai River subset (0.25deg)"
  path: /media/server/hc_ssd/forcing/huai/Data_forcing_01dy_025deg/
  period: "1960-2020"
  coverage: "Huai River basin (31-35N, 112-120E)"
  priority: "primary for Bengbu basin models"

- id: cmfd_huai_3hr_025
  name: "CMFD Huai River subset 3-Hourly (0.25deg)"
  path: /media/server/hc_ssd/forcing/huai/Data_forcing_03hr_025deg/
  period: "1960-2020"
```

Source:
`auto_dissect_general/auto_dissect/data_registry/server_datasets.yaml`.

This file proves that the KDT/data-planning layer knows about regional Huai products. It does
**not**, by itself, prove that every claimed grid/region PanDisk row is present in the production
HydroCraft DB. The server team must verify that independently.

## 5. Confirmed facts versus remaining hypotheses

### Confirmed

1. GeoForge Desktop successfully authenticated to the live observation service.
2. The deployed catalogue contained 1,104 records at test time.
3. Searching/scanning those records exposed only five CMFD-related entries.
4. The useful forcing entries were aggregate China-level records.
5. Known Huai subset IDs in the repository registry were absent from the live catalogue.
6. Desktop currently sends only `q`, `offset` and `limit` to the catalogue API.
7. Desktop can already consume an exact dataset ID and perform a gated manual-download handoff.

### Reported by the user, requiring backend verification

1. CMFD has already been physically split into grid/region download units.
2. Each unit has its own Baidu Pan link.
3. Those mappings are already stored in HydroCraft DB.

### Possible backend causes; not yet proven

- The CMFD child rows exist in HydroCraft DB but were omitted by the observation-catalogue import.
- Only parent records were marked publishable/active.
- An importer grouped or deduplicated child records into the two national parents.
- Child rows use a dataset kind or visibility flag excluded by `/api/obs/catalogue`.
- The search index omits spatial child rows even though `/api/obs/{id}` could address them.
- The serializer returns parent metadata but has no `parent_id`, `bbox`, `tile_id` or asset-index
  fields with which a client could discover the children.

The server code and production database were not inspected in this Desktop-side diagnosis, so the
handoff must not name one of these hypotheses as the root cause until the server team traces it.

## 6. Why this is a backend issue first

The Agent can only choose from records returned by its typed tool
`search_observation_data`. That tool calls the authenticated catalogue and returns the response
without manufacturing additional datasets. This is the correct safety behavior.

GeoForge Desktop already implements:

- activation-token storage in the operating-system secret store;
- authenticated catalogue search;
- exact dataset lookup;
- plan-time selection without downloading;
- approval-gated execution;
- direct downloads with checksum verification for small served files;
- private manual handoff for large Baidu-delivered datasets; and
- path confinement below the project's `inputs/` directory.

Relevant Desktop files:

- `kiss/kiss_cli/obs_access.py`
- `kiss/kiss_cli/api.py`
- `kiss/kiss_cli/flowgate.py`
- `kiss/kiss_cli/gui.py`
- `kiss/kiss_cli/web/app.html`
- `docs/OBS_DESKTOP_INTEGRATION.md`

The current client cannot retrieve records the server does not publish. Improving the prompt or
changing providers from DeepSeek to Kimi/Claude/Codex would not make the hidden IDs discoverable.

## 7. Required backend result

The backend should publish CMFD at the actual delivery-unit granularity while retaining the
national products as parent/catalogue summaries.

At minimum, every downloadable child record needs non-secret metadata similar to:

```json
{
  "id": "cmfd_<stable-child-id>",
  "parent_id": "cmfd_china_daily_010",
  "name": "CMFD daily — <region/tile>, <period>",
  "dataset_kind": "forcing",
  "variables": ["prec", "temp", "srad", "lrad", "wind", "pres", "shum"],
  "units": {
    "prec": "mm/day",
    "temp": "K"
  },
  "bbox": [112.0, 31.0, 120.0, 35.0],
  "period": {"start": "1960-01-01", "end": "2020-12-31"},
  "resolution": "0.25 degree",
  "time_step": "daily",
  "format": "NetCDF",
  "delivery": "manual",
  "size": 123456789,
  "applicable_domains": ["hydrology", "land_surface", "routing", "flood"]
}
```

The example ID and size above are illustrative; the server must use real stable IDs and verified
metadata. `baidu_url` and `baidu_pwd` must **not** appear in catalogue/search responses. They should
be returned only by the already-authenticated download/handoff route for the selected exact ID.

### Preferred query contract

Free-text `q` should remain available, but scientific data resolution should not depend on the LLM
guessing the exact English name of a Chinese basin. Add structured filters, either to
`GET /api/obs/catalogue` or to a dedicated resolve endpoint:

```http
GET /api/obs/catalogue?
    dataset_kind=forcing&
    parent_id=cmfd_china_daily_010&
    bbox=112,31,120,35&
    start=1980-01-01&
    end=1990-12-31&
    variables=prec,temp,srad,lrad,wind,pres,shum&
    time_step=daily&
    limit=100
```

The response should return only records that spatially intersect the requested bounding box,
overlap the requested period and satisfy the required variables/time step. It should also report
whether the returned children completely cover the request.

Suggested response additions:

```json
{
  "total": 12,
  "coverage_complete": true,
  "query_bbox": [112.0, 31.0, 120.0, 35.0],
  "items": []
}
```

If the backend stores one Pan share containing several spatial cells, the child record should
represent that share/download unit rather than inventing one record per mathematical grid cell.
The API's unit of selection must equal the unit the user can actually download and verify.

## 8. Desktop follow-up after the backend is fixed

There are two levels of Desktop compatibility:

### Minimal compatibility

If the backend publishes searchable child IDs through the existing `q` endpoint, the current
Desktop can already:

1. search for the child record;
2. pin its exact ID in `runs/data-inventory.json`;
3. wait for plan approval;
4. invoke `download_observation_data`; and
5. display the private PanDisk link, code and required local destination.

This is enough for a first repair.

### Robust spatial selection

After the backend adds structured filtering, Desktop should extend both the API client and typed
Agent tool to accept:

- bounding box or study-area geometry reference;
- start/end date;
- required variables;
- time step/resolution;
- parent collection ID; and
- pagination until coverage is complete.

The project plan should then pin every exact delivery-unit ID. A parent ID alone must not count as
a complete data inventory when execution requires child files.

## 9. Backend investigation checklist

1. Confirm the physical CMFD partition scheme: grid point, tile, basin, period, variable bundle or
   some combination.
2. Count the real CMFD delivery units in HydroCraft DB.
3. Confirm each unit's stable ID, parent product, spatial bounds, period, variables, size, checksum
   if available, and active/visibility state.
4. Confirm which units have valid Baidu URL/password mappings.
5. Trace the job that produced the 1,104-row observation catalogue.
6. Compare its CMFD source-row count with its published CMFD count (`5` at the Desktop test).
7. Check grouping, deduplication, visibility and dataset-kind filters.
8. Ensure child metadata is searchable without disclosing credentials.
9. Ensure `/api/obs/{child-id}/download` returns the correct private manual handoff.
10. Rebuild/reindex the catalogue and record the resulting counts.

## 10. Acceptance tests

The backend repair is complete only when all of the following pass.

### A. Discovery

- An authenticated `q=cmfd` request returns the parent records and discoverable child/download
  units, or returns parent records with a documented child-resolution route.
- Exact lookup of `cmfd_huai_daily_025` succeeds if that remains an official production ID.
- A Bengbu/Huai spatial query returns a bounded subset, not the whole-China directory alone.
- A 1980–1990 query excludes children that do not overlap that period.
- Required VIC variables are machine-readable, including their units.

### B. Coverage and honesty

- The API explicitly reports whether the selected children completely cover the requested bbox,
  period and variables.
- Missing cells/years/variables are reported as gaps; they are not silently treated as complete.
- The catalogue never claims that a climatology or rain-belt derivative is interchangeable with
  time-varying VIC forcing.

### C. Credential boundary

- Catalogue and detail responses contain no Pan URL, password, activation token or NAS path.
- `/api/obs/{child-id}/download`, with a valid token, returns the Pan handoff only for that exact
  child record.
- Invalid, expired and revoked tokens retain their distinct error responses.

### D. End-to-end Desktop test

1. Start a new project: “Run VIC–CaMa-Flood for Bengbu, 1980–1990.”
2. Use any supported Agent provider.
3. During planning, search the real observation catalogue.
4. Confirm the Agent selects only CMFD records covering the Huai/Bengbu domain and period.
5. Confirm `runs/data-inventory.json` contains the exact child IDs and marks them unavailable until
   the user completes the handoff.
6. Approve the plan.
7. Confirm the Desktop presents only the required PanDisk downloads and exact destinations.
8. Confirm the Agent waits; it must not fabricate forcing files or claim a download occurred.
9. Place the real files and continue.
10. Confirm local input checks validate file existence, variables, units, temporal coverage and
    spatial coverage before model execution.

The test does not need to run VIC or CaMa-Flood to completion to validate this issue. It needs to
prove correct discovery, selection, handoff and input validation.

## 11. Definition of done

This issue is done when a basin-scale China project can resolve a minimal, real CMFD data inventory
from the authenticated service without selecting either whole-China archive; every selected item
maps to a real delivery unit; Pan credentials remain private; and GeoForge Desktop can pin,
present and validate those exact items without provider-specific prompting.

## 12. Ownership summary

| Work item | Primary owner |
|---|---|
| Verify CMFD child rows and Pan mappings in HydroCraft DB | Backend/data team |
| Publish/index child records | Backend/data team |
| Add spatial/time/variable resolution API | Backend/API team |
| Preserve private credential boundary | Backend/API + Desktop |
| Add structured query arguments to Desktop tools | Desktop team, after API contract is fixed |
| Pin exact child IDs and validate coverage | Desktop flow/planning layer |
| Scientific selection among returned real records | Agent, under KI harness and plan gate |

The immediate blocker is backend catalogue exposure. Provider tuning should not be used as a
workaround for missing catalogue records.
