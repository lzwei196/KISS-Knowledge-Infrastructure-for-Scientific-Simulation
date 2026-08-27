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

## Proposed design

Three layers, in the order they are worth building.

### 1. Ship the index, never the credentials

Export the mirror as metadata the app already knows how to carry — dataset id,
name, type, variables, coverage, date range, format, `data_ki`, and the share
link and password. The agent can then tell a user exactly which dataset serves
the quantity it needs and where to get it, instead of reporting that data is
missing. This is knowledge, which is what this project ships.

Costs nothing at runtime, works on every platform, and is the fallback the
other two layers degrade to.

### 2. The user's own Baidu account, entered like an API key

Settings already takes provider API keys. A Baidu login belongs in the same
place. With it present the app can install BaiduPCS-Py on demand and perform
save-then-download without the user leaving the application.

- credentials belong to the user, are entered by the user, and stay on their
  machine — the same trust model as their Anthropic or DeepSeek key
- absent credentials must degrade to layer 1, never block a project
- install BaiduPCS-Py lazily; it pulls fastapi, uvicorn, pillow and
  cryptography, which is a lot to impose on someone who will never use it

### 3. A neutral mirror for everyone else

Baidu solves this for users in China. For anyone else the answer is anonymous
HTTPS — Zenodo for citable datasets, object storage or release assets for the
rest. That is a migration rather than a feature, but without it the capability
is regional.

## A "pandisk KI"

This fits the existing `data_ki` pattern rather than needing a new concept. A
data-access KI would document how to obtain a mirrored dataset, what arrives,
and which tool reads it — the same shape as `ObservedQ`, which already declares
`tool: read_station.py`. It would ship knowledge and links, and hold no
secrets, so it can go in the public repository as it stands.

## Open question for the repository owner

Publishing `docs/` with 1,104 share links and passwords in a public repository
makes those datasets effectively public and search-indexable, permanently. That
appears to be the intent — the mirror exists to distribute them — but it is not
reversible once indexed, so it needs an explicit decision before the index is
committed. Until then this document contains one example link only.

## What is not yet known

- whether Baidu rate-limits or blocks a share accessed by many accounts
- whether `deferred_forcing` (29 rows) should be mirrored at all, given the
  grid × year tiling that deferred them
- how large a typical dataset is, and therefore what a download costs a user
