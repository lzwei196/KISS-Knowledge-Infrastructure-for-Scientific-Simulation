# Observation-data access API — contract for GeoForge Desktop

Live since 2026-09-09 at `https://app.geoforgehhu.com/api/obs/`. This is the
backend half of the design in `OBS_MIRROR_HANDOFF.md`; this file is the
contract the desktop side builds against. Server code:
`hydrocraft-web/backend/api/obs.py` + `backend/services/obs_access.py`,
battery `tests/test_obs_access.py` (12 tests).

## The idea in one paragraph

1,104 observation datasets. The 823 under 100 MB are served directly by this
API; the 281 larger ones get a JSON reply carrying the Baidu share link and
password instead of the bytes, and the agent tells the user to fetch that one
by hand. Everything — including being told a link — requires an **activation
token**: one per person, issued by the owner, 6-month expiry, revocable
individually. It is not the web login and never will be.

## Authentication

Send the token on every request, either way:

    Authorization: Bearer gfd_...
    ...or...      ?token=gfd_...

The token goes in **Settings beside the provider API keys**. Store it in the
OS keychain where available (Keychain / Credential Manager / Secret Service),
not a plain file — audit finding.

Failure states are distinct on purpose. Map each to its own user message:

| status | `detail.error` | what the user should be told |
|---|---|---|
| 401 | `missing_token` | paste your activation token in Settings |
| 401 | `invalid_token` | the token is wrong — check for a copy/paste miss |
| 401 | `expired_token` | ask the owner for a new token |
| 401 | `revoked_token` | this token was revoked — ask the owner |
| 429 | `quota_exceeded` | daily limit reached (20 GB or 2,000 requests); resets midnight server time |
| 404 | `unknown_dataset` | no dataset with that id |

Never collapse these into one "auth failed" — that is the exact mistake the
review told us to avoid.

## Endpoints

### `GET /api/obs/catalogue?offset=0&limit=100&q=`

Paginated list. `q` filters id/name/type. Each entry:

    { "id": "bengbu_51080", "name": "Bengbu", "type": "discharge",
      "dataset_kind": "gauge", "shape": "point_time_series", "format": "csv",
      "variables": [{"name": "discharge_m3s"}, ...],
      "lat": 32.93, "lon": 117.38,
      "start_date": "1950-01-01", "end_date": "1997-12-31", "n_records": 17532,
      "applicable_domains": ["hydrology", ...],
      "delivery": "served" | "manual" | "unmeasured",
      "size": 566225, "sha256": "99f6..." }

The catalogue **never contains Baidu links or passwords** — deliberate; the
listing must not be a bulk-harvest shopping list. `unmeasured` only appears
until the server-side backfill has visited that dataset.

### `GET /api/obs/{id}`

Metadata for one dataset, same fields plus `notes`. Cheap — does not build
anything. `delivery: "unavailable"` means the source path is gone server-side;
tell the user to report it, it is our fault.

### `GET /api/obs/{id}/download`

The main call. Three outcomes:

**Served (HTTP 200, binary body).** Headers:

    Content-Disposition: attachment; filename="<id>.<ext|zip>"
    X-Content-SHA256: <hex>
    Cache-Control: private, no-store

Directories arrive as a `.zip` (662 of the 823 served datasets are
directories). **Verify the SHA-256 after download** and re-fetch on mismatch —
a corrupt file must fail here, not later as a mysterious model bug. Save to a
temp name and rename only after the checksum passes.

**Manual (HTTP 200, JSON body).** The dataset is over 100 MB:

    { "served": false, "reason": "too_large", "size": 1300000000,
      "baidu_url": "https://pan.baidu.com/s/...", "baidu_pwd": "xxxx",
      "baidu_remote_path": "/geoforge_obs/<id>",
      "instructions": "..." }

The agent should present the link + password and say exactly where the file
belongs in the project. Each such reply is logged server-side per token —
tell users links are for their own use. Outside China, Baidu is impractical;
the agent should say so rather than let someone discover it.

**Errors** — the table above.

## What the desktop side needs to build

1. Settings field for the activation token (keychain-backed), plus a
   "test token" button hitting `/api/obs/catalogue?limit=1` and mapping the
   error states to the messages above.
2. A download helper: temp file → verify `X-Content-SHA256` → rename into the
   project's data location; resume is not supported server-side (v1), so
   re-fetch on interruption.
3. Agent wiring: when a project's data plan wants an observation dataset,
   query the catalogue, then download or relay the manual instructions.
4. Nothing else — quotas, logging, zipping, and checksums are server-side.

## v1 limits, stated plainly

- Any valid token can read any dataset (no per-user permissions).
- No resumable downloads; served files are ≤100 MB so re-fetch is fine.
- No checksums for the manual (Baidu) tier.
- Daily quotas only; no per-minute rate limit.
- Baidu links, once disclosed, cannot be recalled — logged, not locked.

## Server-side administration (owner only)

    cd hydrocraft-web
    python -m backend.obs_admin issue --to "Name"     # prints the secret ONCE
    python -m backend.obs_admin list
    python -m backend.obs_admin revoke <token_id>

Token DB: `hydrocraft-web/obs_access.db` (hashes only). Zip/checksum cache:
`hydrocraft-web/obs_cache/`.
