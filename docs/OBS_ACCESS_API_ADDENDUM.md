# Addendum 2026-09-10 — granular CMFD resolution

Answers the backend handoff `CMFD-GRANULAR-CATALOGUE-BACKEND-HANDOFF-2026-09-10.md`:
a basin project could previously only see the whole-China CMFD directories
(242 GB daily, 649 GB 3-hourly) and no smaller unit.

## What changed on the backend

1. The two Huai River subsets were uploaded and shared, so they now appear
   through the normal catalogue + `/download` path:
   - `cmfd_huai_daily_025` — 984 MB, Huai basin, 1960–2020, daily
   - `cmfd_huai_3hr_025` — 7.4 GB, Huai basin, 1960–2020, 3-hourly
   These were `deferred_forcing` before; they are `shared` now.

2. The whole-China products are exposed at their real delivery granularity —
   one file per variable per year — through two new endpoints. 1,183 children
   recorded (daily + 3-hourly, 8 variables × 74 years each).

## New endpoints (token-guarded, same as the rest)

### `GET /api/obs/resolve`

Query params: `parent_id`, `variables` (comma-separated), `start_year`,
`end_year`, `time_step` (`daily` | `3hr`).

    GET /api/obs/resolve?parent_id=cmfd_china_daily_010
        &variables=prec,temp,srad,lrad,wind,pres,shum
        &start_year=1980&end_year=1990&time_step=daily

Response:

    { "total": 77, "coverage_complete": true, "gaps": [],
      "estimated_bytes": 19200000000, "query_bbox": [70,15,140,55],
      "items": [ { "id": "cmfd_china_daily_010__prec_1980",
                   "parent_id": "cmfd_china_daily_010",
                   "variable": "prec", "year": 1980, "time_step": "daily",
                   "size_hint": 390000000, "bbox": [70,15,140,55] }, ... ] }

- No credentials in this response.
- `coverage_complete` + `gaps` tell the client whether the requested
  variables/years are all present; missing ones are listed, never silently
  dropped.
- CMFD is whole-China on a regular grid, so every child shares the national
  bbox; the client confirms the project area falls inside it. (There is no
  per-tile spatial split for CMFD — the real download unit is var×year, and
  the API's unit equals what the user can actually fetch.)

### `GET /api/obs/child/{child_id}/download`

Manual handoff for one child. Returns the parent's Baidu link + password and
the path to the single file inside the share:

    { "served": false, "reason": "granular_child",
      "child_id": "cmfd_china_daily_010__prec_1980",
      "baidu_url": "...", "baidu_pwd": "...",
      "path_in_share": "daily/prec/prec_1980.nc",
      "instructions": "download only that one file from inside the share" }

Each disclosure is logged per token, as with the whole-dataset manual path.

## Desktop guidance

For a China basin project needing CMFD forcing, prefer in this order:
1. the basin subset if one exists (`cmfd_huai_daily_025` for the Huai) —
   smallest, one download;
2. otherwise `/resolve` against the national parent for the exact variables and
   years, then `/child/{id}/download` for each — pin every child id in the data
   inventory, and use `coverage_complete` to confirm the set is whole before
   the plan is approved.

Never treat the whole-China parent as a data inventory when execution needs
child files.
