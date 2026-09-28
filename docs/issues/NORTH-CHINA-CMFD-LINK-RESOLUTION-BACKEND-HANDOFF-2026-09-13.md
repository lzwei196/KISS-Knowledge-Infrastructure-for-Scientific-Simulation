# North China Plain VIC → CaMa: CMFD download-link resolution

Date: 2026-09-13
Audience: GeoForge Database backend and GeoForge Desktop maintainers
Status: authenticated live API probes completed; coupled simulation not started.

## Executive summary

**Baidu links ARE available. Authentication and variable/year resolution work.**
The verified endpoint returns a Baidu handoff for an individual national
variable-year file. We cannot currently obtain a **spatially partitioned North
China/grid-specific delivery unit** through the documented API.

There are two distinct gaps:

1. Backend/interface: a North China bbox supplied to `/resolve` still returns
   national file IDs and national coverage. If spatially partitioned files and
   links already exist, we need their actual lookup endpoint and identifiers.
2. Desktop: the production client currently searches the local catalogue and
   downloads by ID; it does not call `/resolve`. It must integrate the real
   resolver rather than infer child IDs or prefer the Huai package by name.

Do not describe this as “the backend has no Baidu links” or “authentication fails.”
Neither statement is supported by these tests.

## Intended scientific workflow

User requested a real VIC + CaMa-Flood test in the North China Plain. Before
downloading, the agent must determine a scientifically suitable grid/domain,
period, required variables and coupling inputs. It should then show:

- Which exact data units cover the requested grid and period.
- Which files can be downloaded/prepared automatically after approval.
- Which files require the user to download from Baidu Pan.
- What local extraction/regridding/unit conversion remains necessary.

The bbox `[115,37,117,39]` and 1989–1990 used below are **diagnostic requests**,
not an approved model domain or final scientific plan. The two-variable query
is deliberately small; `prec,temp` are not a complete VIC forcing specification.

## Connection used

Base URL: `https://app.geoforgehhu.com/api/obs`

All requests used the existing valid activation token in the desktop process:

```http
Authorization: Bearer <REDACTED_EXISTING_ACTIVATION_TOKEN>
Accept: application/json, application/octet-stream
User-Agent: GeoForge-Desktop/obs-v1
```

No token, Baidu URL, or extraction code is included in this report. The child
handoff request may appear in the backend disclosure audit log. No dataset
payload was downloaded and no Baidu link was opened.

## Actual requests and observed results

### 1. Full live catalogue, not the cached JSON

Paged requests:

```http
GET https://app.geoforgehhu.com/api/obs/catalogue?offset=0&limit=500&q=
GET https://app.geoforgehhu.com/api/obs/catalogue?offset=500&limit=500&q=
GET https://app.geoforgehhu.com/api/obs/catalogue?offset=1000&limit=500&q=
```

Observed: **1,106 total / 1,106 returned**.
Relevant records include national CMFD daily/3-hourly products, the two Huai
subsets, and `china_gaugeflux_haihe` (served, 441,270 bytes). No explicit North
China spatial CMFD units were identified among the inspected CMFD records.
That does not prove no spatial files exist on disk or behind another endpoint.

### 2. Documented variable/year resolution works

```http
GET https://app.geoforgehhu.com/api/obs/resolve?parent_id=cmfd_china_daily_010&variables=prec,temp&start_year=1989&end_year=1990&time_step=daily
```

Observed response summary:

```json
{
  "total": 4,
  "coverage_complete": true,
  "gaps": [],
  "estimated_bytes": 1180000000,
  "query_bbox": [70.0, 15.0, 140.0, 55.0]
}
```

Returned IDs:

- `cmfd_china_daily_010__prec_1989`
- `cmfd_china_daily_010__prec_1990`
- `cmfd_china_daily_010__temp_1989`
- `cmfd_china_daily_010__temp_1990`

Every item has national bbox `[70,15,140,55]`. Precipitation size hints are
390,000,000 bytes per year; temperature hints are 200,000,000 bytes per year.

### 3. Adding a North China bbox does not produce spatial delivery units

```http
GET https://app.geoforgehhu.com/api/obs/resolve?parent_id=cmfd_china_daily_010&variables=prec,temp&start_year=1989&end_year=1990&time_step=daily&bbox=115,37,117,39
```

Observed: the same four IDs, `estimated_bytes: 1180000000`,
`coverage_complete: true`, `gaps: []`, and
`query_bbox: [70,15,140,55]`. Each item still has national coverage.

Important qualification: the supplied API addendum documents variable/year
resolution and explicitly says there is no spatial tiling. It does not document
`bbox` as a supported resolver parameter. Therefore this test demonstrates
absence of spatial resolution **through this request**, not a regression of a
documented bbox feature. It is also valid for a national file to cover the bbox;
coverage is not the same as a spatially reduced download.

### 4. The individual child's Baidu handoff works

```http
GET https://app.geoforgehhu.com/api/obs/child/cmfd_china_daily_010__prec_1989/download
```

Observed fields (private values redacted):

```json
{
  "served": false,
  "reason": "granular_child",
  "child_id": "cmfd_china_daily_010__prec_1989",
  "path_in_share": "daily/prec/prec_1989.nc",
  "baidu_url": "<PRESENT; REDACTED>",
  "baidu_pwd": "<PRESENT; REDACTED>"
}
```

Thus the correct national variable-year link can be queried. We have not
verified its contents or Baidu accessibility by downloading it. It is not
identified by the response as a North China/grid tile.

## What we need from the backend

If grid/region-partitioned files already exist, please provide:

1. The exact authenticated discovery/resolution route and supported parameters.
2. One working North China example: bbox → real tile/file IDs → each file's
   private download handoff. Describe coordinate order and CRS.
3. Per delivery unit: stable ID, bbox/geometry, variables, units, resolution,
   start/end, time step, size, checksum where available, and delivery mode.
4. Clear semantics separating requested area, source coverage, delivery extent,
   variable/time completeness and whether local extraction is required.
5. How these records enter the local JSON: normal catalogue pagination or a
   separate tile index/resolver. Include ETag/version and pagination rules.

If only national variable-year files exist, please explicitly confirm this.
The desktop can present them honestly as a manual national-file fallback,
with size and local extraction requirements, rather than silently selecting
Huai or calling the link grid-specific. A future clipping service is a
separate capability; we will not invent its URL or claim it exists.

For unsupported spatial parameters, prefer a clear validation error or explicit
`spatial_filter_applied: false`-equivalent metadata rather than a response that
could be mistaken for a spatially reduced download. This is a proposed contract
improvement, not a claim those fields exist today.

## Desktop responsibilities, independent of backend changes

- Integrate `/resolve` using its documented parameter names (not guessed aliases).
- Persist actual returned child records; reject invented child IDs.
- Bind selected delivery units and requirements to user approval and receipts.
- Never equate “bbox intersection” or “national data covers the bbox” with
  “grid-specific download.”
- Show manual versus automatic delivery and required preprocessing in Project
  status; keep private Baidu links/codes in the user-facing handoff only.

## Build/test context

The revised Mac app compiled successfully at:
`/Users/leo/kiss/builds/dist-north-china-grid-v0.6.52/GeoForge Desktop.app`.
Full desktop regressions: **389 passed, 1 skipped, 121 subtests passed**.
These are software tests, not proof of VIC–CaMa simulation completion. The
North China live simulation has not started; current work is interface diagnosis.
