<p align="center">
  <img src="assets/logo.svg" alt="GeoForge" width="120">
</p>

<h1 align="center">GeoForge Desktop</h1>

<p align="center">
  <b>Run Earth-system models by asking for what you want.</b><br>
  127 scientific models, each packaged with the knowledge an AI agent needs to install and drive it.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/macOS-Apple%20Silicon-black">
  <img src="https://img.shields.io/badge/models-127-orange">
  <img src="https://img.shields.io/badge/License-MIT-green">
</p>

---

Running a hydrology or land-surface model normally means a week of compiler
flags, NetCDF versions and undocumented input formats before the first
timestep. GeoForge Desktop puts an agent in front of that work. You describe
the task; it picks the model, sets it up on your machine, and runs it.

The models are real: MODFLOW 6, WRF-Hydro, SWAT+, VIC, TOPMODEL, SUMMA,
ADCIRC, and 120 more — the same binaries the research groups publish, not
reimplementations.

## Install

**macOS (Apple Silicon)** — download from
[Releases](../../releases/latest):

```bash
unzip GeoForge-Desktop-macos-arm64.app.zip
xattr -dr com.apple.quarantine "GeoForge Desktop.app"   # unsigned build
open "GeoForge Desktop.app"
```

The `xattr` line is needed because the app is not yet notarised by Apple.
Without it macOS refuses to open it.

**Everything else** — run from source. Works on Linux, macOS and Windows:

```bash
git clone https://github.com/lzwei196/KISS---Knowledge-Infrastructure-for-Scientific-Simulation.git
cd KISS---Knowledge-Infrastructure-for-Scientific-Simulation
pip install -e kiss/
kiss gui            # opens the same interface in your browser
```

> Intel Macs: not in the current release. GitHub's Intel runners have been
> unavailable for hours at a time, so those builds are best-effort and the
> release ships without one rather than waiting. Build from source meanwhile.

## The manual

A complete walkthrough of the desktop app, following one scientific model from
project creation through KI selection, data preparation, the points where it
hands back to you, execution, results, and calibration.

- [English](docs/manual/GeoForge-Desktop-Manual-EN-v0.6.24.pdf)
- [简体中文](docs/manual/GeoForge-Desktop-Manual-ZH-CN-v0.6.24.pdf)
- [Bilingual / 中英合订版](docs/manual/GeoForge-Desktop-Manual-Bilingual-v0.6.24.pdf)

These document the v0.6.24 interface. Later releases add per-requirement data
questions and clearer setup and permission handoffs, but the workflow is the
same.

## Before the first run

GeoForge needs *one* of these to think with. It checks on startup and tells
you what it found.

| | |
|---|---|
| **An agent CLI you already use** | `claude`, `codex`, `gemini`, `kimi` or `qwen` — nothing to configure |
| **An API key** | Anthropic, OpenAI, DeepSeek or OpenRouter — paste it into ⚙ Settings |

Switch between the two with the **CLI / API** button in the menu bar, and pick
the provider and model per session.

## Using it

Sessions live on the left, like any chat app. Describe what you want:

> *"Simulate groundwater drawdown from a well field over ten years."*

With **Models: Auto**, GeoForge reads the catalogue and chooses — MODFLOW 6
here. Pin a model yourself if you would rather decide.

**KISS Library** (top right) is the other half: every model, its setup state,
and a green or red dot.

- **Green** — the model runs on this machine. Verified by executing it, not by
  checking that a file exists.
- **Red** — it does not run, and the reason is stated: a missing shared
  library, an absent .NET runtime, a binary built for another architecture.

Press **Install** and the agent does the setup. For a model with no recipe yet
it reads the KI's documentation, searches upstream for build instructions,
proposes a recipe, and then *runs it* — a proposal that fails to install is
discarded, never recorded.

## Verifying an install

The question "is this model usable" is answered by four tests, in order:

```
$ kiss verify MODFLOW6
  runs   MODFLOW6   runnable (elf) — mf6: 6.6.1 02/10/2025
```

That version string came out of the binary. The four tests are **present**
(the file is there), **shaped** (right architecture for this machine),
**linked** (every shared library and import resolves) and **responds** (it
actually executes).

What counts as runnable depends on the model, and the check knows the
difference: 87 of the 127 are compiled and need a working binary, while 36 are
Python packages where importing *is* running.

Twenty-nine packages declare neither a binary nor an import for the checker to
test. Those report **`cannot verify`** — not green. A check that examines
nothing would always pass, and a green light that means "nothing was tested"
is worse than an honest gap.

## The literature

Each package ships `docs/papers.json` — 2,301 papers across 124 models, with
the DOI, the role each plays, and which quantities it covers:

```
$ kiss papers TOPMODEL --quantity discharge
TOPMODEL — 17 papers covering discharge
  [open] A history of TOPMODEL
          https://doi.org/10.5194/hess-25-527-2021  supporting
  ...
```

**Metadata only — no PDFs.** 1,138 of those papers are subscription articles;
redistributing them would be republishing other people's work. The DOI
travels, the article stays with its publisher. Roughly half (1,163) are open
access and anyone can download them.

This matters more than it sounds. An agent that has read the paper describing
a model's snow routine sets that model up far better than one working from a
title. If you have institutional access, download the ones for your task and
drop them beside the KI.

## What a model package holds

```
models/MODFLOW6/
├── SKILL.md                  how an agent drives this model, start to finish
├── dag.yaml                  inputs, outputs, units — machine-readable
├── preflight_check.py        what must be present before running
├── diagnostics/triplets.md   symptom → cause → fix, from real failures
├── docs/
│   ├── papers.json           the literature, as metadata
│   ├── REFERENCES.md         official documentation and manuals
│   └── format_spec.yaml      exact input file formats
└── tools/                    setup and post-processing scripts
```

The `diagnostics` file is the unusual one. It records failures that produce
*plausible wrong numbers* rather than crashes — a unit confusion between
permeability and hydraulic conductivity is seven orders of magnitude and no
error message.

## Driving a KI with your own agent — the KI harness

> **The KI tells an agent how to run one model. The harness makes sure the
> agent is actually told.** Three lines, and any agent — Claude, codex, your
> own loop — drives any of the 127 models the same way.

```python
from pathlib import Path
from ki_tools_common import harness

contract = harness.contract(Path("models/MODFLOW6").resolve(), execute=True)
```

Put `contract` in your system prompt. That is the whole integration.

### Why it exists

This started as two copies of the same thing. The chat application and the
self-improve loop each had their own way of pointing an agent at a KI, and they
drifted: one kept its rules in a branch table where 29 of them sat in the wrong
branch, and its per-KI review gate reached 3 of 458 packages. The other embedded
its rules in one place and could not be partial.

The lesson was **chokepoint, not routing** — a rule that lives at a junction can
be skipped by whoever takes the other road. So the two were replaced by one
function that every caller goes through, with no branch on who is asking.

### What the contract says

`contract()` renders the KI's operating instructions as obligations. Ten of
them, held as a registry in `ki_harness.py` rather than as prose, so a parity
test can fail the moment any driver drops one:

| | |
|---|---|
| **Run the real thing** | no toy substitute, no literature value passed off as a result |
| **Follow SKILL.md in order** | the protocol is a sequence, not a menu |
| **Absolute tool paths** | run tools with the project interpreter — do not search, do not disk-glob |
| **Know the outputs** | before running, not after |
| **Units from the files** | from the file's own attributes, never from documentation |
| **Preflight first** | check the environment before the run |
| **Failure ladder** | triplets, then documentation, then think — in that order |
| **Never weaken** | do not quietly relax the test to make it pass |
| **Not your own judge** | verdicts belong to the caller |
| **Evidence series** | write the simulated series to CSV, so the result is reproducible |

### The rest of the API

```python
m = harness.manifest(ki)          # what this KI actually ships
m["artifacts"]                    # {'SKILL.md': True, 'dag.yaml': True, ...}
m["missing"]                      # [] — stated up front, not discovered mid-run
m["tools"]                        # 30 tool scripts for MODFLOW 6

harness.tool_command(ki, "tools/calib_run.py")
# '/usr/bin/python3 /abs/path/models/MODFLOW6/tools/calib_run.py'

harness.run_preflight(ki, timeout=60)
# {'report': ..., 'returncode': 1, 'raw_tail': ...}

harness.assert_injected(prompt)   # raises unless the prompt carries the contract
```

Two of these refuse rather than guess. `tool_command()` raises `KiHarnessError`
for a tool that is not there, because a fabricated path fails later and more
confusingly. `assert_injected()` is the conformance hook: it raises unless the
prompt carries the `[KI HARNESS v1]` marker, so a spawn site that bypassed the
contract fails immediately instead of producing plausible unguided work. Wire it
into your own runner and the same guarantee applies.

| | |
|---|---|
| `HC_PROJECT_PYTHON` | interpreter for `tool_command()` and `run_preflight()`. Set it to your project environment |
| `KI_HARNESS_FULL=1` | adds the run-time attention digest: dag caveats, format spec, top triplets |

### How it was verified

Each piece shipped with its own proof, not a green tick: resolution tested on
four naming cases, the contract rendered against three models and *refused* on a
KI too thin to execute, prompts checked for the marker, the numeric strip proven
to leave zero threshold statements on the runner path, and the spawn
environment proven to send a bare `python` to the project interpreter. The chat
application adopted it behind a flag with a byte-level diff against the old
text, because that prompt had been tested heavily and a silent rewrite was not
acceptable. Live proof came from an HBV run against its Eidselva baseline.

### Resolving a model name

`resolve_ki_path()` maps a model *id* to its directory through the database of
the fleet the harness was written for, and refuses to guess — a folder name is
not always the model id. That is real here too: 8 of these 127 packages differ,
`SWAT+` living in `SWAT_Plus`, `HEC-RAS` in `HEC_RAS`, `Noah-MP` in `Noah_MP`.
A plain clone has no such database, so use the catalogue, which resolves the
same spellings and reports ambiguity rather than picking one:

```python
from kiss_cli.catalog import Catalog
ki = Catalog.discover().get("SWAT+").root
```

The toolkit that writes these packages from a model's source is a separate
project: [**KDT-single**](https://github.com/lzwei196/KDT-single).

## Terminal use

The same engine without the window:

```bash
kiss list                    # the 127 packages
kiss info SWAT_Plus          # what this model needs
kiss init MODFLOW6           # set it up here
kiss verify                  # what actually runs on this machine
kiss papers WRF_Hydro        # the literature behind it
kiss doctor                  # what would stop a KI working elsewhere
```

## Honest status

- **127** model packages, **123** with a full `dag.yaml` contract
- **19** installs have a recorded, executed recipe. The other 108 go through
  the agent, which works but is slower and can fail
- macOS builds are **unsigned** — hence the `xattr` step
- Apple Silicon only in the current release

## Digging deeper

The idea behind the packaging — why operational knowledge has to be
structured, and the validation protocol behind these numbers — is in
[docs/KNOWLEDGE_INFRASTRUCTURE.md](docs/KNOWLEDGE_INFRASTRUCTURE.md).

Live demonstration: [Geoforgehhu.com](https://Geoforgehhu.com)

## License

MIT for the KI packages and the application. **The models themselves keep
their own licences** — some are public domain (USGS, EPA), others require
registration or a licence agreement. `kiss info <model>` states which, and the
installer will tell you when a model needs you to accept terms yourself.
