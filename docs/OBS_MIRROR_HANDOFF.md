# Shipping the observation mirror to GeoForge — findings and a proposed design

Server-side investigation, 2026-08-27. Written for whoever picks this up on the
macOS side; nothing here has been implemented yet.

## What exists

`obs_datasets` in the HydroCraft database holds **1,138 observation datasets**,
of which **1,104 carry a Baidu Netdisk share link**, each with its own link,
password and remote path:

| column | example |
|---|---|
| `baidu_url` | `https://pan.baidu.com/s/1vdkDixqzGPZkKLM-IjiSzg` |
| `baidu_pwd` | `a586` |
| `baidu_remote_path` | `/geoforge_obs/bengbu_51080` |
| `baidu_status` | `shared` (1,074), `shared_zip` (28), `deferred_forcing` (29) |

Links are per dataset — 1,104 rows produce 1,104 distinct links, not one bundle.
The local tree behind them is **103 GB**. By kind: LTAR library 539, database
178, gauge 124, static 70, gridded 48, statistical 33, remote sensing 27.

Each row already carries what an agent needs to decide whether it wants the
dataset: `variables`, `lat`/`lon`, `start_date`/`end_date`, `n_records`,
`applicable_domains`, `format`, `dataset_kind`, and the `data_ki` + `tool` that
reads it.

## What blocks the obvious approach

**We cannot ship credentials.** BaiduPCS-Py keeps its authentication in
`~/.baidupcs-py/accounts.pk`, a pickled store of BDUSS cookies. That is the
account, not a scoped token: anyone holding it can read, overwrite and delete
everything in that Netdisk. A PyInstaller bundle is trivially unpacked, so
embedding it would publish the account to every user who downloads the app.

**A share link alone is not enough either.** Fetching one anonymously returns
302 to `pan.baidu.com/share/init?surl=…`, the 提取码 page. The password gets
past that, but the mirrored entries are folders, and Baidu requires a
logged-in account to save or download a folder.

So the data cannot be handed over without *the user* having a Baidu account.

**And Baidu is not cross-platform in the sense that matters.** BaiduPCS-Py is
pip-installable and runs anywhere, so the OS question is easy. The real limit
is geography: outside China, Baidu registration needs a mainland phone number
and download speeds are unusable. A "cross-platform capability" built only on
Baidu is a China-only capability.

## The design, and why the split works

Serve what is small over an authenticated endpoint; point at the Netdisk for
what is not. The measured split is unusually favourable:

| tier | datasets | volume | route |
|---|---|---|---|
| under 100 MB | **823** (75%) | **10.3 GB** | served by `app.geoforgehhu.com`, behind login |
| over 100 MB | 281 | ~93 GB | agent hands the user the share link and password |

Three quarters of the library is served for a tenth of a percent of the
storage. The 281 large ones are where Baidu's folder-download requirement bites,
and those are exactly the ones a user is willing to fetch by hand once.

This also retires the open question below: with the index behind a login, the
1,104 links and passwords never need to enter a public repository at all.

## What the backend already provides

Nothing has to be built from scratch.

- `backend/auth.py` — bcrypt password hashing, user accounts, JWT sessions via
  `create_token(user_id, username)`, secret from `HYDROCRAFT_JWT_SECRET` or a
  0600 `.jwt_secret`. The login the service needs already exists.
- `backend/api/files.py` — `FileResponse` serving with an extension allowlist
  and a directory guard. The serving mechanics exist too.
- `obs_datasets.path` resolves for all 1,104 rows, so the file to serve is
  already recorded.

**One caveat that matters.** `main.py` installs CORS and no authentication
middleware, and `files.py` declares no `Depends`, so `/api/files/*` is open. An
observation endpoint must not follow that pattern — serving 10.3 GB of curated
data from an unauthenticated path would publish the library by accident.
Attach the JWT dependency explicitly on the new routes.

## Implementation sketch

1. `GET /api/obs/catalogue` — the full list behind the login: id, name, type,
   variables, coverage, dates, size, and whether it is served or manual. This
   is the page a user browses.
2. `GET /api/obs/{dataset_id}/download` — JWT-guarded `FileResponse` from
   `obs_datasets.path`. Enforce the 100 MB rule *server-side* from the file on
   disk rather than from a stored number, so a dataset that grows past the
   threshold stops being served rather than quietly streaming 40 GB.
3. Over the threshold, return the share link and password in a structured
   refusal — `{"served": false, "baidu_url": ..., "baidu_pwd": ..., "size": ...}`
   — so the agent can tell the user precisely what to fetch and where to put it,
   rather than reporting that data is unavailable.
4. In the app, the agent asks the service first and falls back to the manual
   instruction. Credentials are the user's GeoForge login, which they already
   have; no Baidu account is needed for the 75% that is served.

## A "pandisk KI"

This fits the existing `data_ki` pattern rather than needing a new concept. A
data-access KI would document how to obtain a mirrored dataset, what arrives,
and which tool reads it — the same shape as `ObservedQ`, which already declares
`tool: read_station.py`. It ships knowledge and holds no secrets.

## Still unknown

- what `app.geoforgehhu.com` costs in egress if the served tier becomes popular
- whether the 29 `deferred_forcing` rows should be mirrored at all, given the
  grid x year tiling that deferred them
- whether existing GeoForge accounts are the right identity for this, or
  whether data access needs its own tier
