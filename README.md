# KISS — Knowledge Infrastructure for Scientific Simulation

**Structured operational knowledge that lets AI agents run Earth science models autonomously.**

![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue)
![License MIT](https://img.shields.io/badge/License-MIT-green)
![KI Packages 453](https://img.shields.io/badge/KI%20Packages-453-orange)
![Shipped here 127](https://img.shields.io/badge/Shipped%20here-127-yellow)

> *"Real Binary, Real Grid, Real Data"*

**Demonstration**: [https://Geoforgehhu.com](https://Geoforgehhu.com)

---

## Table of Contents

1. [What is Knowledge Infrastructure?](#what-is-knowledge-infrastructure)
2. [What This Repository Contains](#what-this-repository-contains)
3. [Key Contributions](#key-contributions)
4. [Demonstration](#demonstration)
5. [Quick Start](#quick-start)
6. [What a KI Package Contains](#what-a-ki-package-contains)
7. [The 3-Step Validation Protocol](#the-3-step-validation-protocol)
8. [Repository Layout](#repository-layout)
9. [The Preflight Checklist](#the-preflight-checklist)
10. [Anti-Patterns](#anti-patterns)
11. [Model KI Examples](#model-ki-examples)
12. [Results](#results)
13. [Citation](#citation)
14. [License](#license)
15. [Acknowledgments](#acknowledgments)

---

## What is Knowledge Infrastructure?

### The Problem

Earth science models are operational black boxes. Running them requires deep
expertise beyond the underlying physics: input file formats with undocumented
column positions, unit conventions that differ between data sources and model
expectations, build systems tied to specific compilers, calibration workflows
with implicit assumptions. This knowledge is scattered across user manuals,
mailing list archives, doctoral theses, and the minds of experienced
practitioners.

When this knowledge is missing or wrong, models produce incorrect results --
*silently*. In the 123-model study reported in the KISS paper, **37% of all
errors were silent**: the model runs without any error message but produces
scientifically wrong output. The dominant source is unit mismatches.

### The Solution

**Knowledge Infrastructure (KI)** is structured, machine-readable operational
knowledge for a model -- packaged so that an AI agent, or any new user, can run
the model autonomously on a new basin or dataset. Each KI package contains:

- **Executable data preparation tools** -- Python scripts that turn raw forcing,
  soil, vegetation, and topography data into exactly the inputs the model expects.
- **Comprehensive documentation (the SKILL.md)** -- a single operational
  reference covering identity, inputs, build, execution, outputs, unit
  conversions, diagnostics, and limitations.
- **Structured error knowledge (diagnostic triplets)** -- symptom, diagnosis,
  remedy for every failure mode encountered, reusable across models and
  transferable to AI agents.
- **Preflight validation** -- range and unit checks that catch the silent errors
  before the model ever runs.

### The Core Insight

The most dangerous class of model errors is not the crash -- it is the silent
wrong answer. The canonical example: the CMFD forcing dataset stores
precipitation as `kg/m2/s`, but is widely documented as `mm/day`. The
difference is a factor of 86,400. Models read near-zero rainfall, produce
near-zero runoff, and run to completion without any warning. KI specifically
targets these silent errors through unit discovery, preflight validation, and
progressive data replacement testing.

### Philosophy

Every KI package is built on three non-negotiable principles:

1. **Real Binary** -- Run the actual model software (compiled Fortran binary,
   native package), not a Python surrogate or analytic reimplementation. The
   goal is to capture the knowledge needed to operate the *real* model.
2. **Real Grid** -- Run models in their intended distributed/gridded mode, not
   as lumped basin averages. Gridded forcing data exists; use it.
3. **Real Data** -- Validate with independently prepared forcing and observation
   data, not developer-bundled test cases. Developer data proves the binary
   works; your own data proves the knowledge infrastructure works.

---

## What This Repository Contains

This repository publishes the **KI packages** -- the operational knowledge
itself. It ships **127 complete packages**, drawn from a working library that
now stands at **453**.

| | Full KI library | Shipped in this repository |
|---|:---:|:---:|
| KI packages | 453 | 127 |
| `SKILL.md` operational references | 2,021 docs | 127 |
| Diagnostic triplets | 5,268 | 2,826 |
| Tool scripts | 1,742 | 1,263 |
| `preflight_check.py` | 334 | 127 |
| `format_spec.yaml` | 238 | 127 |
| `dag.yaml` execution graphs | — | 124 |
| `knowledge_infrastructure.yaml` | — | 116 |
| `REFERENCES.md` | — | 102 |
| `validation_convention.yaml` | — | 24 |
| `calibration.yaml` + `calib_run.py` | — | 14 |

The 127 packages were refreshed from the working tree on **2026-08-12**; library
counts are from the model registry. The KISS paper (arXiv 2605.17856) describes
the 123-package release; this repository tracks the library as it currently
stands.

Only knowledge artifacts are published -- operational documentation, format
specifications, diagnostic triplets, execution graphs, and tools. Run outputs,
calibration scratch, snapshots, and forcing archives are not.

> **Note on the shared library.** The KI packages were authored against a shared
> helper library, `ki_tools_common` (unit conversions, humidity, forcing loaders,
> soil utilities, metrics). **That library is not distributed as source in this
> repository** -- 126 of the 127 packages reference it (121 in their `SKILL.md`,
> 54 as a real import in `tools/*.py`), so `from ki_tools_common... import ...`
> will not resolve against a fresh clone. An archived snapshot is retained in
> [`kdt-release.zip`](kdt-release.zip). Every other part of a KI package -- the
> operational documentation, format specifications, diagnostic triplets, and the
> model-specific tools -- stands on its own.
>
> **Note on portability.** The packages were authored against the development
> server and carry absolute paths (`/mnt/disk1/Hydrocraft_server/...`) to
> binaries, forcing archives, and DEMs. Expect to repoint them at your own data
> before running -- see [Quick Start](#quick-start) step 4.

---

## Key Contributions

| Contribution | Description |
|---|---|
| **453 KI packages** | Knowledge infrastructure spanning 37 domain tags, carrying 5,268 diagnostic triplets and 1,742 tool scripts; 127 published here |
| **3-step validation protocol** | Developer data test, progressive data replacement, full autonomous run -- isolates silent errors systematically |
| **14-section SKILL.md format** | Standardized documentation capturing all operational knowledge needed to run a model |
| **Diagnostic triplet system** | Structured error knowledge: symptom, diagnosis, remedy -- reusable across models and transferable to AI agents |
| **Machine-readable format specs** | `format_spec.yaml` pins exact input/output file layouts, including fixed-width column positions |
| **Per-model preflight checks** | `preflight_check.py` catches unit and range errors before the binary runs |
| **Real-binary validation record** | 387 packages carry a path to an actual compiled binary; 2,568 recorded test runs across 154 scored models |

---

## Demonstration

A live deployment of KISS knowledge infrastructure is available at
[Geoforgehhu.com](https://Geoforgehhu.com), where AI agents drive the packaged
models end to end -- preparing data, running the real binaries, and interpreting
results.

---

## Quick Start

The KI packages are documentation and tooling, not an installable Python
distribution. To use one, point an agent at it.

### 1. Get the packages

```bash
git clone https://github.com/lzwei196/KISS---Knowledge-Infrastructure-for-Scientific-Simulation.git
cd KISS---Knowledge-Infrastructure-for-Scientific-Simulation
ls models/            # 127 KI packages
```

### 2. Read a package

Every package leads with its operational reference:

```bash
cat models/VIC/SKILL_en.md            # 14-section operational reference
cat models/DSSAT/diagnostics/triplets.yaml   # symptom / diagnosis / remedy
cat models/SHAW/knowledge_infrastructure.yaml # machine-readable manifest
```

### 3. Drive it with an agent

```bash
cp -r models/VIC /your/project/ki/
cp CLAUDE_TEMPLATE.md /your/project/CLAUDE.md
```

Then prompt the agent:

> *"Read `ki/VIC/SKILL_en.md` and run a VIC simulation for the Bengbu basin."*

The agent reads the SKILL.md, calls the packaged tools to prepare inputs, runs
the real binary, and interprets the output. See
[`AGENT_SERVICE_GUIDE.md`](AGENT_SERVICE_GUIDE.md) for full deployment walkthroughs
(VIC+Routing, VIC+CaMa-Flood) and [`DEPLOYMENT.md`](DEPLOYMENT.md) for
infrastructure setup.

### 4. Adapt the paths, then preflight

**The packages are authored against the development server, not against a fresh
clone.** All 127 packages contain absolute paths such as
`/mnt/disk1/Hydrocraft_server/...` for binaries, forcing archives, and DEMs, and
the 125 `preflight_check.py` scripts take no command-line arguments -- they check
a hardcoded environment. Read them as executable specifications of *what must be
present and in what units*, and repoint them at your own data before running:

```bash
grep -rn "/mnt/disk1\|/home/server" models/VIC/    # find what needs repointing
sed -n '1,60p' models/VIC/preflight_check.py       # see what it verifies
```

Preflight is the cheapest place to catch the errors described in
[The Preflight Checklist](#the-preflight-checklist).

---

## What a KI Package Contains

Every KI package follows the same structure so that an agent can read one and
operate any model the same way. A package bundles:

- **`SKILL.md`** -- the 14-section operational reference (identity, description,
  inputs, build, execution, outputs, tools, unit conversions, diagnostics,
  coupling, results, limitations, spinup, references).
- **`tools/*.py`** -- validated data preparation scripts (grid, soil, vegetation,
  forcing, routing, etc.) that produce the model's exact input formats.
- **`diagnostics/triplets.yaml`** -- structured error knowledge captured as
  symptom / diagnosis / remedy triplets.
- **`knowledge_infrastructure.yaml`** -- a machine-readable manifest of the
  pipeline structure, variable list, and tool inventory.
- **`format_spec.yaml`** -- exact input/output file layouts, including
  fixed-width column positions for Fortran models.
- **`dag.yaml`** -- the execution graph: stages, inputs, outputs, and the gate
  and metric definitions used to judge a run.
- **`preflight_check.py`** -- physical-range and unit validation for the forcing
  the model consumes.
- **`docs/REFERENCES.md`** -- literature and source-code references backing the
  operational claims.
- **`validation_convention.yaml`** (24 packages) -- the literature-grounded
  convention for what counts as an acceptable result for this model.
- **`calibration.yaml` + `calib_run.py`** (14 packages) -- parameter bounds and
  a runnable calibration entry point.

The validation status of each package is labelled `binary_only`,
`partial_replacement`, `full_replacement`, or `production_validated` so that
users know exactly how far each model has been verified.

---

## The 3-Step Validation Protocol

A KI package is NOT validated just because the model runs with
developer-provided test data. It is validated when the model produces reasonable
results using ONLY data prepared by the package's own tools.

**Step 1: Developer Data Test** -- Run with bundled example data. Proves the
binary works. Does NOT prove your tools can prepare correct inputs.

**Step 2: Progressive Data Replacement** -- Replace developer data with your own
pipeline-prepared data one component at a time. Verify after each replacement.

| Priority | Component | Verification |
|:--------:|-----------|-------------|
| 1 | Meteorological forcing | Compare T, P, SW, LW with developer values |
| 2 | Soil/subsurface properties | Compare texture, K, porosity |
| 3 | Land cover / vegetation | Compare dominant class |
| 4 | Topography / DEM | Compare elevation range, slope statistics |
| 5 | River network / routing | Compare stream order, drainage area |
| 6 | Initial conditions | Run spinup, discard first 6--12 months |
| 7 | Boundary conditions | Compare with developer BC values |
| 8 | Calibration parameters | Compare with developer calibrated values |

**Step 3: Full Autonomous Run** -- Run entirely on pipeline-prepared data (zero
developer data). Compare with literature, other models, and physical
reasonableness checks. This proves the knowledge infrastructure works.

**Validation status labels**: `binary_only` | `partial_replacement` |
`full_replacement` | `production_validated`

---

## Repository Layout

```
.
  README.md                          This file
  LICENSE                            MIT License
  CHANGELOG.md                       Version history
  VERSION                            Release version
  AGENT_SERVICE_GUIDE.md             Deploying KI with an agent service
  DEPLOYMENT.md                      Infrastructure setup guide
  CLAUDE_TEMPLATE.md                 Master agent instruction file template
  kdt-release.zip                    Archived shared-library snapshot (see note above)
  revalidation_3x3_results.xlsx      3x3 revalidation: 25 models, 254 runs
  models/                            127 KI packages
    VIC/
      SKILL_en.md                      Operational reference
      preflight_check.py               Forcing range/unit checks
      s1_grid/ s2_forcing/ s3_soil/ s4_veg/   Pipeline stages
      docs/                            References and stage documentation
    DSSAT/
      SKILL.md
      knowledge_infrastructure.yaml
      diagnostics/triplets.yaml
      tools/                           Data preparation scripts
      workflow/
    ...                                125 more
```

Package contents vary by model: not every package has reached the same
completeness. Across the 127 shipped packages, all 127 carry a `SKILL.md`,
a `preflight_check.py`, and a `format_spec.yaml`; 125 a `triplets.yaml`,
124 a `dag.yaml`, 116 a `knowledge_infrastructure.yaml`, and 102 a
`REFERENCES.md`.

---

## The Preflight Checklist

Before deploying a KI package on a new basin, run the package's
`preflight_check.py` and read its unit conversion section. It takes two minutes
and prevents the errors that took weeks to find.

### The #1 Silent Error: Unit Mismatches

**Golden rule: NEVER trust data documentation for units. ALWAYS verify by
reading the actual file.** The CMFD unit trap is the canonical example:

| Variable | Actual Unit (from NetCDF) | To mm/day | To mm/hr | To m/day |
|----------|--------------------------|:---------:|:--------:|:--------:|
| Precipitation | **kg/m2/s** | x86400 | x3600 | x86.4 |
| Temperature | **K** | -273.15 to degC | | |
| Pressure | **Pa** | /100 to hPa | | |

Each model expects different units. There is no single conversion factor:

| Model Expects | Conversion from kg/m2/s |
|---------------|:-----------------------:|
| mm/day (most models) | x86400 |
| cm/day | x8640 |
| inches/day | x3401.6 |
| mm/hr | x3600 |
| m/timestep | x3600 x dt_hr / 1000 |
| kg/m2/s native (land surface models) | x1 (no conversion) |
| m/day | x86.4 |

### Real Unit Errors Discovered During Packaging

| Model Type | Error | Impact |
|------------|-------|--------|
| Hydrology (multiple) | Precip read as mm/day but is kg/m2/s -- 86400x too low | Near-zero discharge |
| Lake model | Rain in mm/day instead of m/day -- 1000x too much | Lake overflows daily |
| Flood model | Precip in mm/3hr not converted to mm/hr | Flood depths 10--100x too high |
| Crop model | Wind m/s vs km/day | Evapotranspiration wrong |
| Soil model | van Genuchten alpha in 1/m not 1/cm (100x) | Infiltration wrong |
| BGC model | Solar radiation MJ/m2/day not converted to W/m2 (x11.574) | Cold bias |
| Routing model | mm/timestep not converted to mm/s rate | Discharge off by timestep ratio |

Beyond units, the per-model diagnostic triplets also cover Fortran traps, column
alignment, coupling traps, spatial traps, domain-specific traps, platform traps,
and spinup requirements.

---

## Anti-Patterns

Seven documented failure modes from the validation protocol. Each was observed
in practice while building and validating the KI packages.

1. **"It works with test data, ship it."** Developer data proves the binary
   works, NOT the knowledge infrastructure. You must complete all three
   validation steps.
2. **"I replaced everything at once and it works."** You got lucky. If it had
   failed, you would have no idea which component caused the failure. Always
   replace one input at a time.
3. **"The results are different but the model runs."** Different *how*? 10%
   different is calibration. 10x different is a unit error. 1000x different is
   a column mapping bug. Always quantify and explain the difference.
4. **"I'll calibrate it later."** Calibration fixes PARAMETERS, not DATA
   PREPARATION bugs. If forcing has wrong units, calibration will compensate
   by producing wrong parameters. The model will "work" on the calibration
   period but fail on any new period. Fix the data first, calibrate later.
5. **"The model doesn't have a [basin] example."** Then BUILD one. That is the
   entire point of the knowledge infrastructure -- to enable running any model
   on any basin autonomously.
6. **"The binary won't build, I'll write a Python surrogate."** No. A Python
   reimplementation proves the MATH works, not that your pipeline can drive the
   REAL MODEL. Analytic surrogates are only acceptable when the source code is
   genuinely unavailable (proprietary, dead link) and the user has explicitly
   approved the fallback.
7. **"I'll run it lumped to save time."** Models designed for distributed/
   gridded application MUST be run distributed. Gridded forcing data exists.
   Running a gridded model as a lumped basin average wastes the spatial
   information and produces worse results. Run it the way it was designed.

---

## Model KI Examples

Several complete KI packages are included as reproducible examples. Each contains
validated tools, diagnostic triplets, operational documentation, and preflight checks.

| Model | Domain | KI Contents | Key Workflow |
|-------|--------|-------------|-------------|
| **VIC 5.1.0** | Distributed hydrology | SKILL.md + 22 scripts (grid, forcing, soil, veg, calibration, plotting) + preflight | Basin → Grid → Soil → Veg → Forcing → VIC Run |
| **Lohmann Routing** | Channel discharge | SKILL.md + 2 tools (VIC preprocessing, routing params) + preflight | VIC Output → 22→7 cols → Flow direction → UH → Discharge |
| **CaMa-Flood 4.20** | River routing + flood | SKILL.md + 2 tools (VIC→NetCDF, date processing) + preflight | VIC Output → NetCDF → Map regionalization → Hydrodynamics |
| **DSSAT 4.8.5** | Crop simulation | SKILL.md + tools + 1,789-line triplets + workflow | Weather → Soil → Cultivar → FileX → Run → Parse yields |
| **SHAW** | Soil heat & water | SKILL.md + 7 pipeline stages + VIC coupling + preflight | Site → Weather → Plant → Initial conditions → Run |
| **SUMMA 3.x** | Modular hydrology | SKILL.md + decision configuration + ROSETTA soil params | GRU/HRU → Decisions → Trial params → Two-phase run |

### Using These KI Packages

1. Copy `models/<Name>/` into your project
2. Use `CLAUDE_TEMPLATE.md` as your master instruction file
3. Point your agent at the model: *"Read `models/VIC/SKILL_en.md` and run a simulation for Bengbu"*
4. The agent reads SKILL.md, calls validated tools, runs the binary, interprets results

See [`AGENT_SERVICE_GUIDE.md`](AGENT_SERVICE_GUIDE.md) for the full deployment guide with
VIC+Routing and VIC+CaMa-Flood workflow walkthroughs.

---

## Results

### Library Coverage

Knowledge infrastructure now spans **453 packages** across **37 domain tags**,
grouped below into domain families (registry snapshot, 2026-08-11):

| Domain family | Count |
|--------|:-----:|
| Atmosphere & atmospheric chemistry | 68 |
| Data infrastructure | 62 |
| Hydrology & water resources | 59 |
| Ocean & coastal | 47 |
| Flood & hydrodynamics | 29 |
| Cryosphere | 20 |
| Biogeochemistry | 18 |
| Crop & agriculture | 18 |
| Calibration & data assimilation | 16 |
| Groundwater & subsurface | 16 |
| Soil & land surface | 16 |
| Geomorphology & sediment | 14 |
| Water quality | 14 |
| Earth system & frameworks | 13 |
| Energy | 11 |
| Human systems & health | 8 |
| Wildfire | 8 |
| Geophysics | 6 |
| Urban | 5 |
| Lake | 2 |
| Other / uncategorized | 3 |

By package kind: **404 models**, **29 libraries**, **19 datasets**, 1 duplicate.

### Validation Coverage

Validation tier as recorded in the model registry, across all 453 packages:

| Tier | Count |
|------|:-----:|
| `tested` | 281 |
| `validated` | 85 |
| `analytic` | 33 |
| `failed` | 21 |
| `not_runnable` | 10 |
| `real` | 7 |
| `binary_exists` | 7 |
| `runs` | 1 |
| unset | 8 |

Supporting evidence in the registry:

- **387 packages** carry a path to an actual compiled binary (Fortran, C, C++).
- **2,568 recorded test runs** across **154 models** with at least one scorecard
  (299 scorecards total); **139 models** carry a recorded best NSE.
- **5,268 diagnostic triplets** extracted across the library.
- **334 packages** ship a preflight check; **238** ship a machine-readable
  `format_spec.yaml`.
- **3x3 revalidation**: 25 models, 254 runs, 49% consistent
  ([`revalidation_3x3_results.xlsx`](revalidation_3x3_results.xlsx)).

### Key Findings

- **37% of all errors are silent** (123-model study, KISS paper) -- the model
  runs without error but produces scientifically wrong results.
- **Unit mismatches are the #1 silent error**, affecting every model packaged.
- **Fixed-width column misalignment** is the #2 silent error in Fortran models.
- **Data leakage** (calibrating and validating on the same period) was found in
  5+ models, inflating NSE by approximately 0.10--0.15.

### The CMFD Case Study

The most impactful single finding: CMFD daily precipitation is documented as
`mm/day` in many community resources, but the actual NetCDF attribute is
`kg/m2/s`. The difference is a factor of 86,400. This error was propagated
silently through multiple models, causing near-zero simulated runoff. A unit
audit across all KI packages found and fixed two additional instances of this
specific error in production tool scripts.

---

## Citation

If you use the KISS knowledge-infrastructure packages in your research, please cite:

```bibtex
@article{li2026kiss,
  title         = {KISS - Knowledge Infrastructure for Scientific Simulation: A Scaffolding for Agentic Earth Science},
  author        = {Li, Ziwei and Zhu, Liujun and Liu, Yuchen and Zhao, Yichen and Li, Birk and Wu, Ruiqi and Jin, Junliang and Zhang, Jianyun},
  journal       = {arXiv preprint arXiv:2605.17856},
  year          = {2026},
  eprint        = {2605.17856},
  archivePrefix = {arXiv},
  url           = {https://arxiv.org/abs/2605.17856}
}
```

---

## License

MIT License. Copyright (c) 2026 Jianyun Zhang Research Group, Hohai University.
See [`LICENSE`](LICENSE) for the full text.

---

## Acknowledgments

- **GeoForge platform** ([Geoforgehhu.com](https://Geoforgehhu.com)) --
  Demonstration and deployment infrastructure for KISS knowledge infrastructure.
- **Hohai University** -- Institutional support and computational resources.
- **Jianyun Zhang and Junliang Jin Research Group** -- Development, testing, and validation
  across the KI library.

---

*Developed by the Jianyun Zhang Research Group, Hohai University.*
