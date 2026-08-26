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

## Using the KI harness

A KI tells an agent how to run one model. The **harness** is the layer above
that: one contract for how *any* agent uses *any* KI, so a chat session, a
batch loop and your own script all drive a model the same way. It ships here at
`ki_tools_common/ki_tools_common/harness/`, and an install puts it into the
model's environment.

```python
from pathlib import Path
from ki_tools_common import harness

ki = Path("models/MODFLOW6").resolve()
text = harness.contract(ki, execute=True, target_var="head")
```

`contract()` returns the text you inject into the agent's prompt — about 7.5 kB
for MODFLOW 6. It turns the KI's operating instructions into obligations: run
the real binary rather than a stand-in, follow `SKILL.md` in order, call tools
by absolute path, read units from the files rather than assuming them, run
preflight first, and never appoint yourself judge of your own output. Ten in
total, held as a registry in `ki_harness.py` rather than prose, so a parity test
fails the moment a driver quietly drops one.

The rest keeps the agent honest about what it is holding.

```python
m = harness.manifest(ki)
m["artifacts"]   # {'SKILL.md': True, 'dag.yaml': True, 'preflight_check.py': True, ...}
m["missing"]     # [] — say what is absent instead of discovering it mid-run
m["tools"]       # 30 tool scripts, as paths relative to the KI

harness.tool_command(ki, "tools/calib_run.py")
# '/usr/bin/python3 /abs/path/models/MODFLOW6/tools/calib_run.py'

harness.run_preflight(ki, timeout=60)
# {'report': ..., 'returncode': 1, 'raw_tail': ...}
```

`tool_command()` refuses rather than guesses: ask for a tool that is not there
and it raises `KiHarnessError`, because a fabricated path fails later and more
confusingly than a loud refusal now. `assert_injected(prompt)` is the
conformance hook — it raises unless the prompt carries the `[KI HARNESS v1]`
marker, so a spawn site that bypassed the contract fails immediately instead of
producing plausible unguided work.

| | |
|---|---|
| `HC_PROJECT_PYTHON` | the interpreter `tool_command()` and `run_preflight()` emit. Set it to your project's environment; otherwise the shipped default carries a `KISSPATH_` placeholder |
| `KI_HARNESS_FULL=1` | adds the run-time attention digest — dag caveats, format spec, top diagnostic triplets |

One function needs more than this repository. `resolve_ki_path()` maps a model
*id* to its KI directory through the database of the internal fleet the harness
was written for, and refuses to guess, because a folder name is not always the
model id. That mismatch is real here too: 8 of these 127 packages differ —
`SWAT+` lives in `SWAT_Plus`, `HEC-RAS` in `HEC_RAS`, `Noah-MP` in `Noah_MP`.
Against a plain clone there is no such database, so use the catalogue, which
resolves the same spellings and reports ambiguity rather than picking:

```python
from kiss_cli.catalog import Catalog
ki = Catalog.discover().get("SWAT+").root
```

The dissection toolkit that produced these packages — the pipeline that reads a
model's source and writes its KI — is a separate project:
[**KDT-single**](https://github.com/lzwei196/KDT-single).

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
