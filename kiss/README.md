# `kiss` — the KI initializer

Turn a downloaded KI package into a working model on your machine, and hand
whatever cannot be automated to your AI coding agent.

```bash
pip install -e kiss/

kiss list                    # what's here
kiss info VIC                # what VIC needs
kiss doctor                  # what would stop any of it working
kiss init VIC -w ~/vic       # set it up
kiss gui                     # ...or do all of that in a browser
```

---

## The problem this solves

Every KI in this repository was authored on one machine and carries that
machine's absolute paths. `kiss doctor` counts them:

| | |
|---|---|
| Packages with authoring-machine paths | **127 of 127** |
| Total path references | ~2,900 across ~600 files |
| Roles they fall into | 8 (`binaries`, `data`, `forcing`, `obs`, `static`, `outputs`, `python_env`, `ki_root`) |

So the first thing anyone downloading this repository discovers is that
nothing runs. `kiss` fixes that without editing a single KI file.

## How relocation works

The paths cluster into a small number of semantic **roles**. `kiss init` writes
a `kiss.toml` mapping each role to a real directory on your machine, then
relocates using one of three tiers:

| Tier | How | Edits the KI? | Needs |
|---|---|---|---|
| **`sandbox`** (default) | bind-mounts your directories onto the authoring prefixes in a user namespace | no | `bubblewrap` |
| `port` | rewrites literals to call `kiss_cli.paths.P()` | yes | — |
| `symlink` | creates the authoring prefixes as symlinks | no | write access to `/mnt` |

The sandbox tier overlays a tmpfs on `/mnt`, `/media` and `/home` before
binding underneath. That is not cosmetic: in an unprivileged user namespace you
cannot mount over a path inside a mount you do not own, and `/srv` is its
own filesystem on the authoring machine.

Result — a KI's hardcoded path resolves to your install, untouched:

```
$ kiss run MODFLOW6 -w ~/mf6 -- /srv/models/modflow6/mf6.6.1_linux/bin/mf6 --version
mf6: 6.6.1 02/10/2025
```

## The manifest

`dag.yaml` says what a model *is*. It never says how to *obtain* one. That gap
is the manifest, `kiss/manifests/<Model>.yaml`:

```yaml
kiss_manifest_version: 1
model: VIC
verified: observed
install_dir: VIC-5.1.0          # what this KI's hardcoded paths expect
depends_on: [CaMa_Flood]        # VIC has no routing of its own
acquire:
  strategy: build               # pip | download | build | wine | bundled | manual
  repo: https://github.com/UW-Hydro/VIC
  ref: "5.1.0"
  commands:
    - make -C vic/drivers/classic CC="gcc -fcommon"
  produces: vic/drivers/classic/vic_classic.exe
```

### `verified:` means what it says

| Value | Meaning |
|---|---|
| `observed` | the full recipe was executed on a clean machine and succeeded |
| `partial` | the end state was verified, but not the steps producing it |
| `unverified` | written from upstream docs, never executed here |
| `manual` | deliberately not automatable (licence, registration) |

Only `observed` is a promise. Nothing in this tool reports success it did not
watch happen — that rule is inherited from the KI execution policy, and it is
the whole point.

## What is verified today

| Model | Strategy | Status | Notes |
|---|---|---|---|
| WOFOST | `pip` | **observed** | PCSE 6.0.13; preflight passes |
| MODFLOW6 | `download` | **observed** | USGS 6.6.1 release; preflight passes |
| VIC | `build` | **observed** | compiles from tag `5.1.0`; needs `-fcommon` on modern GCC |
| SWAT_Plus | `build` | `unverified` | upstream cmake procedure, not executed here |
| APEX | `manual` | `manual` | `APEX0806.exe` is not redistributable |

The remaining 122 packages fall back to a stub inferred from `dag.yaml`, which
knows the source repository but not the build. `kiss init` says so plainly
rather than pretending.

## When automation stops

Most models will not install end to end, for honest reasons — 68 of the 127 are
`work_dir` builds whose recipes vary by compiler, and almost none of the
required forcing data is ours to redistribute. So `kiss init` always writes an
agent handoff:

```
~/vic/
  kiss.toml
  CLAUDE.md              # canonical: status, what failed, where things are
  AGENTS.md -> CLAUDE.md # Codex
  QWEN.md   -> CLAUDE.md # Qwen
  GEMINI.md -> CLAUDE.md # Gemini
  .agents/skills/kiss-vic/SKILL.md
```

Then:

> Open `~/vic` in your agent and say **"finish the VIC setup"**.

The agent reads exactly what failed, with the commands already attempted and a
pointer to that KI's own `diagnostics/triplets.md` — the error/cause/remedy
knowledge the package already carries. That is what makes a KI self-installing:
the knowledge needed to finish is already inside it.

## `kiss doctor`

Answers one question: *if someone downloaded this today, what would stop them?*

```
BLOCK  hardcoded-paths      127    authoring-machine paths
BLOCK  python-syntax          3    files that do not parse
WARN   no-manifest          122    install cannot be automated
WARN   dangling-ref         122    SKILL.md cites files not in the package
WARN   internal-leak        105    references to private tooling
WARN   no-source              7    identity.repo_url absent
WARN   dag-version            2    stale template_version
WARN   identity-mismatch      1    dag model_id != directory
```

Exit code is 1 when any BLOCK finding exists, so it works in CI.

## The GUI

`kiss gui` starts a local server on `127.0.0.1:8765` — one stdlib HTTP handler
and one HTML file, no Electron, no build step. It calls the same functions the
CLI does; it adds discovery and a progress view, never its own install logic.
If the two ever disagree, that is a bug in the GUI.
