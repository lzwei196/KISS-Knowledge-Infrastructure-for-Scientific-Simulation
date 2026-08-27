# Shipping the observation mirror to GeoForge — findings and a proposed design

Server-side investigation, 2026-08-27. Written for whoever picks this up on the
macOS side; nothing here has been implemented yet.

## Before anything else: an open endpoint already serves this data

`GET /api/files/project?path=...` takes an absolute path, has no authentication
dependency, and `main.py` installs no auth middleware. Its `ALLOWED_ROOTS` are
very wide — `/mnt/disk1/Hydrocraft_server/data`, `/mnt/disk3`, `/mnt/disk4`,
`/mnt/datasets`, `/home/server`, `/media/server`, `/tmp` — and its extension
allowlist includes `.csv`, `.nc`, `.txt`, `.json`, `.zip`, `.pdf`, `.md`.

Measured against the mirror: **1,088 of the 1,104 dataset paths sit under an
allowed root, and 161 of them carry a servable extension.** Confirmed against
the running service rather than inferred — one request returned HTTP 200 and
2.4 MB of a landslide catalogue with no credentials presented.

Two consequences.

1. Building a token-guarded endpoint beside this one protects nothing. The
   token becomes decoration while the same bytes are reachable without it.
2. The exposure is wider than the mirror. `/home/server` is an allowed root and
   `.json`, `.md` and `.txt` are servable extensions, so agent configuration and
   notes under that home directory are in scope. I did not probe for specific
   credential files — that is not something to demonstrate by fetching — but
   the allowlist makes the class reachable, and that should be assumed until
   the roots are narrowed.

This is live on the running API, and it is a decision for the repository owner
rather than something to change underneath a service other people are using.
The fix is not complicated: narrow `ALLOWED_ROOTS` to the directories the chat
UI genuinely needs (`outputs`, `workspaces`, `uploads`), and attach an
authentication dependency. It should land before, not after, the work below.

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

Three quarters of the library is served for a tenth of the volume. The 281 large ones are where Baidu's folder-download requirement bites,
and those are exactly the ones a user is willing to fetch by hand once.

This also retires the open question below: with the index behind a login, the
1,104 links and passwords never need to enter a public repository at all.

## Authentication: an activation token, not a web account

The web application's login is the wrong instrument here. It identifies a
person using a site; this needs to authorise a *copy of a desktop application*
to reach research data, on machines we do not administer, in a product that is
downloaded rather than visited. Those are different problems, and binding data
access to `app.geoforgehhu.com` accounts would also mean every data user needs
a web account they otherwise have no use for.

So: an **activation token**, issued to members of the research group, entered
once in the desktop application, and presented on every request. One token
gates two things — downloading a served dataset, and being told the share link
and password for one that is too large to serve.

This is cross-platform by construction: it is an HTTP header, so it behaves
identically on macOS, Windows and Linux, and it needs no Baidu account for the
75% of the library that is served.

### What a token has to carry

Not a bare secret string. At minimum:

- an **identifier** for who it was issued to, so a leak can be traced and that
  token alone revoked
- an **expiry**, so an abandoned token stops working without anyone acting
- a **revocation check** on the server, since a token in a config file on
  someone's laptop is not recoverable once it spreads

A signed token (the backend already has a JWT secret and the library) gives
identity and expiry without a database round trip, but revocation still needs
server-side state. For a research group the honest answer is a small table of
issued tokens with `revoked_at` — simpler than a key hierarchy, and it makes
"who has access" answerable.

### What it must not become

- **not a shared password.** One token for everyone cannot be revoked without
  cutting off everyone, and it will end up in a screenshot or a paper's
  supplementary material.
- **not stored where the app can leak it.** It belongs where API keys already
  live in Settings, not in a file that ships inside the bundle.
- **not the only control.** A token authorises; it does not stop one holder
  pulling all 10.3 GB repeatedly. Rate limiting and per-token accounting are
  what make abuse visible.

### The pandisk half

For datasets over the threshold the token buys *the link and password*, not the
bytes. That is worth stating plainly: once disclosed, that pair is
independently shareable and cannot be recalled. Rotating a Baidu share is
manual work across 281 datasets, so disclosure should be logged per token, and
the group should accept that this tier is protected by convention rather than
by cryptography.

## What the backend already provides

Nothing has to be built from scratch.

- `backend/auth.py` — bcrypt password hashing, JWT sessions, secret from
  `HYDROCRAFT_JWT_SECRET` or a 0600 `.jwt_secret`. The signing machinery a
  token needs is already there, even though the account model is not what we
  want.
- `backend/api/files.py` — `FileResponse` serving with an extension allowlist
  and a directory guard.
- `obs_datasets.path` resolves for all 1,104 rows, so the file to serve is
  already recorded.

**One caveat that matters.** `main.py` installs CORS and no authentication
middleware, and `files.py` declares no `Depends`, so `/api/files/*` is open. An
observation endpoint must not follow that pattern — serving 10.3 GB of curated
data from an unauthenticated path would publish the library by accident.

## Implementation sketch

1. `GET /api/obs/catalogue` — the full list, token-guarded: id, name, type,
   variables, coverage, dates, size, and whether it is served or manual.
2. `GET /api/obs/{dataset_id}/download` — token-guarded `FileResponse` from
   `obs_datasets.path`. Enforce the 100 MB rule *server-side from the file on
   disk*, not from a stored number, so a dataset that grows past the threshold
   stops being served rather than quietly streaming 40 GB.
3. Over the threshold, return a structured refusal —
   `{"served": false, "baidu_url": ..., "baidu_pwd": ..., "size": ...}` — so the
   agent tells the user precisely what to fetch and where to put it, rather
   than reporting that data is unavailable.
4. In the desktop application the token sits in Settings beside the provider
   API keys, and its absence degrades to naming the dataset rather than
   blocking a project.

## Review findings (codex, gpt-5.5, adversarial pass on this plan)

Ranked. The first is recorded above as its own section because it is live.

**Corrections to what this document claimed**

- The token is **not device activation**. It is a bearer API key with a
  friendlier name: anyone holding it can replay it from curl, a script or CI,
  and nothing binds it to a copy of the application. Calling it activation is
  acceptable as product language, never as a security claim.
- Reusing the existing JWT machinery is fine; reusing its **secret, issuer or
  audience is not**, or a web session becomes a data token and vice versa.
  Separate key where practical, distinct issuer/audience/scope, and a `jti`.
- A revocation table must store **hashed** token identifiers. Storing raw
  tokens turns a database or log leak into a credential leak.
- The Baidu tier is protected **only until first disclosure**. A token holder
  can harvest all 281 link/password pairs in minutes, and revoking the token
  afterwards does nothing. Rotating 281 shares by hand is the only remedy, so
  disclosure must be logged per token and the group must accept that this tier
  rests on convention.
- `obs_datasets.path` "resolves" is not sufficient. Resolve symlinks, confirm
  the result is under an allowlisted root, reject directories, set a safe
  `Content-Disposition`, decide about range requests, and count bytes sent.

**Missing from the plan entirely**

- **Quotas.** One valid token can pull 10.3 GB repeatedly and saturate origin
  egress. Per-token daily limits, per-IP limits, a concurrency cap, byte
  counters and an emergency disable.
- **The catalogue is a shopping list.** Returning every id, size and
  served/manual flag hands an attacker the enumeration. Paginate, rate limit,
  and put the Baidu credentials behind an explicit per-dataset "reveal" action
  rather than in the listing.
- **Integrity.** Checksums for both tiers, or a corrupt or half-finished
  download will present as a model bug.
- **Download mechanics.** Resume, atomic partial files, cleanup after failure,
  Windows path length, non-ASCII names, proxy and TLS behaviour, and a defined
  place to put manually fetched Baidu data.
- **Token storage.** Keychain on macOS, Credential Manager or DPAPI on Windows,
  Secret Service on Linux with a documented fallback. A plain settings file
  leaks through logs, support bundles, screenshots and synced home directories.
- **Lifecycle.** Who issues, how identity is checked, default expiry, renewal,
  revocation UX, lost tokens, offboarding, emergency rotation, and whether an
  external collaborator gets the same powers as a group member.
- **Distinct failure states** for the agent: not configured, not authorised,
  manual download required, download failed, dataset does not exist. Collapsing
  these makes the agent behave brittly and leaves the user unsure what to fix.

**On the 100 MB boundary**

Directionally reasonable for an internal group, but 100 MB is not a cost model.
The right threshold follows from egress price, install count, cache hit rate
and concurrency. Worth revisiting once there is a real user count rather than
treating it as settled.

**On third-party hosting**

Codex's judgement, and it matches the geography problem already noted: this
design is an acceptable internal bootstrap, but not a distribution plan. For
users outside the group — or outside China — the large tier needs object
storage or a CDN rather than a consumer netdisk.

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
