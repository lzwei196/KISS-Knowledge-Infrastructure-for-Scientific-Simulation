# KISS — Knowledge Infrastructure for Scientific Simulation

**Structured operational knowledge that lets AI agents run Earth science models autonomously.**

![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue)
![License MIT](https://img.shields.io/badge/License-MIT-green)
![KI Packages 123](https://img.shields.io/badge/KI%20Packages-123-orange)

> *"Real Binary, Real Grid, Real Data"*

**Demonstration**: [https://Geoforgehhu.com](https://Geoforgehhu.com)

---

## Table of Contents

1. [What is Knowledge Infrastructure?](#what-is-knowledge-infrastructure)
2. [Key Contributions](#key-contributions)
3. [Demonstration](#demonstration)
4. [Quick Start](#quick-start)
5. [What a KI Package Contains](#what-a-ki-package-contains)
6. [The 3-Step Validation Protocol](#the-3-step-validation-protocol)
7. [Package Structure](#package-structure)
8. [Shared Library (ki_tools_common)](#shared-library-ki_tools_common)
9. [Templates](#templates)
10. [Examples](#examples)
11. [The Preflight Checklist](#the-preflight-checklist)
12. [Anti-Patterns](#anti-patterns)
13. [Model KI Examples](#model-ki-examples)
14. [Results](#results)
15. [Citation](#citation)
16. [License](#license)
17. [Acknowledgments](#acknowledgments)

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
*silently*. Across the 123 Earth science models packaged in KISS, **37% of all
errors are silent**: the model runs without any error message but produces
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

KISS ships 123 such packages plus the shared library, validators, and templates
needed to build and verify them.

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

## Key Contributions

| Contribution | Description |
|---|---|
| **123 validated KI packages** | Complete knowledge infrastructure across 15 Earth science domains, producing 650+ diagnostic triplets |
| **3-step validation protocol** | Developer data test, progressive data replacement, full autonomous run -- isolates silent errors systematically |
| **Shared utility library** | `ki_tools_common` with 8 modules consolidating patterns from 435+ model tool scripts: unit conversions, humidity, NetCDF handling, metrics, validation, I/O helpers, forcing source metadata |
| **Forcing preflight validator** | `preflight_forcing.py` catches unit mismatches before model execution by checking physical ranges and auto-detecting data sources |
| **Cal/val split enforcement** | `standard_calval.py` and `check_calval_split.py` prevent data leakage in calibrated models |
| **14-section SKILL.md template** | Standardized documentation format capturing all operational knowledge needed to run a model |
| **Diagnostic triplet system** | Structured error knowledge: symptom, diagnosis, remedy -- reusable across models and transferable to AI agents |

---

## Demonstration

A live deployment of KISS knowledge infrastructure is available at
[Geoforgehhu.com](https://Geoforgehhu.com), where AI agents drive the packaged
models end to end -- preparing data, running the real binaries, and interpreting
results.

---

## Quick Start

### Installation

```bash
git clone https://github.com/lzwei196/KISS---Knowledge-Infrastructure-for-Scientific-Simulation.git
cd KISS---Knowledge-Infrastructure-for-Scientific-Simulation/ki_tools_common
pip install -e .            # minimal (numpy only)
pip install -e ".[all]"     # with xarray, netCDF4, geopandas, scipy
pip install -e ".[dev]"     # adds pytest for running tests
```

### Example 1: Unit Conversion

```python
from ki_tools_common import units

# Convert CMFD precipitation from kg/m2/s to mm/day
precip_mmday = units.kgm2s_to_mmday(0.00003)       # -> 2.592 mm/day

# Universal dispatcher -- works with scalars and numpy arrays
temp_k = units.convert(25.0, 'C', 'K', 'temperature')   # -> 298.15
precip = units.convert(1.0, 'kg/m2/s', 'mm/day', 'precipitation')  # -> 86400.0

# Look up conversion factors for specific data sources
from ki_tools_common.forcing_sources import get_conversion_factor
factor = get_conversion_factor('CMFD', 'prec', 'mm/day')  # -> 86400.0
```

### Example 2: Forcing Preflight Check

```bash
# Auto-detect data source and check all variables against physical ranges
python validators/preflight_forcing.py /path/to/forcing/ --source auto
```

The preflight validator catches the most common silent error -- unit
mismatches -- before the model ever runs.

### Example 3: Metrics with Cal/Val Split

```python
from ki_tools_common.metrics import all_metrics
from validators.standard_calval import compute_calval_metrics

# All standard metrics in one call
m = all_metrics(obs, sim)
print(f"NSE={m['NSE']:.3f}  KGE={m['KGE']:.3f}  PBIAS={m['PBIAS']:.1f}%")

# Separate calibration and validation period metrics
calval = compute_calval_metrics(dates, obs, sim)
# Returns: {'calibration': {NSE, KGE, PBIAS, r, n},
#           'validation':  {NSE, KGE, PBIAS, r, n},
#           'full':        {NSE, KGE, PBIAS, r, n}}
```

### Running Tests

```bash
cd ki_tools_common
pytest tests/ -v
```

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
- **Preflight checks** -- physical-range and unit validation for the forcing the
  model consumes.

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

For the full protocol, see [`VALIDATION_PROTOCOL.md`](VALIDATION_PROTOCOL.md).

---

## Package Structure

```
kiss-release/
  README.md                          This file
  CHANGELOG.md                       Version history
  VALIDATION_PROTOCOL.md             3-step validation methodology
  PREFLIGHT.md                       Preflight checklist and unit traps
  LICENSE                            MIT License
  pyproject.toml                     Package metadata and dependencies
  ki_tools_common/                   Shared utility library
    __init__.py
    units.py                           Unit conversions (40+ constants, 30+ functions)
    humidity.py                        Tetens saturation vapour pressure, RH/q, VPD
    netcdf_utils.py                    Coordinate detection, subsetting, basin masking
    validation.py                      Physical range checks with unit-trap hints
    metrics.py                         NSE, KGE, PBIAS, RMSE, Pearson r (NaN-safe)
    io_helpers.py                      Standard JSON output, date parsing, obs readers
    forcing_sources.py                 CMFD/MSWX/ERA5/FLUXNET variable metadata
    pyproject.toml                     Library-specific dependencies
    README.md                          Module documentation
    tests/
      test_units.py                    45 unit tests for critical conversions
  validators/
    preflight_forcing.py               Pre-simulation forcing data checker (1,144 lines)
    check_calval_split.py              Data leakage detector (559 lines)
    standard_calval.py                 Cal/val period helper with scipy.optimize wrapper
  templates/
    SKILL_TEMPLATE.md                  14-section model documentation template
    knowledge_infrastructure_template.yaml   KI package schema
    stage_log_template.json            Completion tracking
    triplets_template.yaml             Diagnostic triplet format
    validation_sheet_template.md       Standardized validation report
  examples/
    unit_conversion_example.py         Self-contained unit conversion walkthrough
    validation_example.py              Metrics computation and cal/val split demo
  models/                            Complete KI packages (see Model KI Examples)
```

---

## Shared Library (ki_tools_common)

The shared library consolidates code patterns found duplicated across 435+
model tool scripts into 8 tested modules.

### units -- Unit Conversions

The most impactful module. Contains 40+ named constants, 30+ conversion
functions, and a universal `convert()` dispatcher.

```python
from ki_tools_common.units import (
    kgm2s_to_mmday,          # 86400.0
    kelvin_to_celsius,        # -273.15
    pa_to_hpa,                # /100
    wm2_to_mjm2day,           # radiation
    convert,                  # universal dispatcher
)

# Named functions for the most critical conversions
precip = kgm2s_to_mmday(2.315e-5)          # -> 2.0 mm/day
temp = kelvin_to_celsius(293.15)            # -> 20.0 degC

# Universal dispatcher handles any registered conversion
convert(300.0, 'W/m2', 'MJ/m2/day', 'radiation')  # -> 25.92
convert(101325.0, 'Pa', 'atm', 'pressure')         # -> 1.0
```

### humidity -- Vapour Pressure and Humidity

One canonical Tetens implementation, replacing 17 independent versions found
across model tools.

```python
from ki_tools_common.humidity import (
    saturation_vapor_pressure,   # Tetens formula
    specific_humidity_to_rh,     # q -> RH conversion
    vpd_from_temp_rh,            # vapour pressure deficit
    dewpoint_from_rh,            # dewpoint temperature
)

es = saturation_vapor_pressure(temp_c=20.0)         # -> 23.39 hPa
rh = specific_humidity_to_rh(q=0.01, temp_k=293.15, pres_pa=101325.0)
vpd = vpd_from_temp_rh(temp_c=25.0, rh=60.0)       # hPa
```

### metrics -- Performance Evaluation

All standard hydrological metrics, NaN-safe, with monthly aggregation.

```python
from ki_tools_common.metrics import all_metrics, monthly_metrics

m = all_metrics(obs, sim)
# Returns: {'NSE': ..., 'KGE': ..., 'PBIAS': ..., 'RMSE': ..., 'r': ...}

m_monthly = monthly_metrics(obs, sim, dates)
# Same metrics on monthly aggregated values (reduces noise)
```

### validation -- Range Checks and Unit-Trap Detection

Automatically detects whether data is likely in the wrong units by comparing
against physical ranges.

```python
from ki_tools_common.validation import validate_forcing_ranges

# Catches: precipitation still in kg/m2/s, temperature in C when K expected
warnings = validate_forcing_ranges({
    'temperature': temp_array,
    'precipitation': precip_array,
})
```

### forcing_sources -- Data Source Metadata

Conversion factor lookup for CMFD, MSWX, ERA5, and FLUXNET datasets.

```python
from ki_tools_common.forcing_sources import get_conversion_factor

get_conversion_factor('CMFD', 'prec', 'mm/day')   # -> 86400.0
get_conversion_factor('CMFD', 'prec', 'mm/hr')    # -> 3600.0
get_conversion_factor('CMFD', 'prec', 'm/day')    # -> 86.4
get_conversion_factor('ERA5', 'tp', 'mm/day')      # accumulated -> mm/day
```

For the full module reference, see [`ki_tools_common/README.md`](ki_tools_common/README.md).

---

## Templates

KISS provides five templates for standardizing model documentation:

| Template | Purpose | Sections |
|----------|---------|----------|
| [`SKILL_TEMPLATE.md`](templates/SKILL_TEMPLATE.md) | Primary operational documentation for a model | 14 sections: identity, description, inputs, build, execution, outputs, tools, unit conversions, diagnostics, coupling, results, limitations, spinup, references |
| [`knowledge_infrastructure_template.yaml`](templates/knowledge_infrastructure_template.yaml) | Machine-readable KI package schema | Pipeline structure, variable list, tool inventory |
| [`stage_log_template.json`](templates/stage_log_template.json) | KI build completion tracking | Status, metrics, timestamps |
| [`triplets_template.yaml`](templates/triplets_template.yaml) | Diagnostic error knowledge format | Error symptom, root cause diagnosis, remedy |
| [`validation_sheet_template.md`](templates/validation_sheet_template.md) | Standardized model performance report | Hydrographs, metrics tables, data provenance |

**Using templates for your own models**: Copy the SKILL_TEMPLATE.md into your
model's `ki/` directory and fill in all 14 sections. The unit conversion table
(Section 8) and diagnostic triplets (Section 9) are the most critical sections --
they capture the knowledge that prevents silent errors.

---

## Examples

### unit_conversion_example.py

Demonstrates five capabilities in a self-contained script (no external data):
direct conversion functions, the universal `convert()` dispatcher with numpy
array support, unit-trap validation that catches data in the wrong units,
forcing source registry lookups, and humidity conversions.

```bash
python examples/unit_conversion_example.py
```

### validation_example.py

Demonstrates the metrics and cal/val split workflow: generates 10 years of
synthetic discharge data, computes full-period metrics (NSE, KGE, PBIAS, RMSE,
r), applies a proper cal/val split (5-year calibration, 4-year validation,
1-year spinup discarded), and shows how full-period metrics inflate apparent
skill by 0.10--0.15 NSE compared to validation-only metrics.

```bash
python examples/validation_example.py
```

Key takeaway: **always report separate calibration and validation metrics.**

---

## The Preflight Checklist

Before deploying a KI package on a new basin, read
[`PREFLIGHT.md`](PREFLIGHT.md). It takes two minutes and prevents the errors
that took weeks to find across 123 models.

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

The full checklist also covers Fortran traps, column alignment, coupling traps,
spatial traps, domain-specific traps, platform traps, and spinup requirements.
See [`PREFLIGHT.md`](PREFLIGHT.md).

---

## Anti-Patterns

Seven documented failure modes from the validation protocol. Each was observed
in practice while building and validating the 123 KI packages.

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
| **VIC 5.1.0** | Distributed hydrology | SKILL.md + 10 tools (grid, soil, veg, forcing) + preflight | Basin → Grid → Soil → Veg → Forcing → VIC Run |
| **Lohmann Routing** | Channel discharge | SKILL.md + 2 tools (VIC preprocessing, routing params) + preflight | VIC Output → 22→7 cols → Flow direction → UH → Discharge |
| **CaMa-Flood 4.20** | River routing + flood | SKILL.md + 2 tools (VIC→NetCDF, date processing) + preflight | VIC Output → NetCDF → Map regionalization → Hydrodynamics |
| **DSSAT 4.8.5** | Crop simulation | SKILL.md + 9 tools + 1752-line triplets + workflow | Weather → Soil → Cultivar → FileX → Run → Parse yields |

### Using These KI Packages

1. Copy `models/<Name>/` into your project
2. Use `CLAUDE_TEMPLATE.md` as your master instruction file
3. Point your agent at the model: *"Read `models/VIC/SKILL.md` and run a simulation for Bengbu"*
4. The agent reads SKILL.md, calls validated tools, runs the binary, interprets results

See [`AGENT_SERVICE_GUIDE.md`](AGENT_SERVICE_GUIDE.md) for the full deployment guide with
VIC+Routing and VIC+CaMa-Flood workflow walkthroughs.

---

## Results

### Summary Statistics

KISS provides knowledge infrastructure for **123 Earth science models** across
**15 domains**:

| Domain | Count |
|--------|:-----:|
| Hydrology | 27 |
| Ocean | 8 |
| Cryosphere | 7 |
| Crop | 7 |
| Fire | 5 |
| Groundwater | 5 |
| Biogeochemistry | 6 |
| Geomorphology | 4 |
| Water quality | 5 |
| Urban | 3 |
| Framework | 6 |
| Atmospheric | 4 |
| Routing | 5 |
| Lake | 3 |
| Geophysics | 2 |

### Validation Coverage

- **55 models** validated with real observations (discharge, soil moisture,
  GPP, temperature, etc.)
- **42 models** validated with analytic benchmarks or developer test cases
- **77 models** running actual compiled binaries (Fortran, C, C++)
- **650+ diagnostic triplets** extracted, with top 20 universal traps
  identified
- **127 validation sheets** produced in standardized format

### Key Findings

- **37% of all errors are silent** -- the model runs without error but produces
  scientifically wrong results.
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
  across 123 Earth science models.

---

*Developed by the Jianyun Zhang Research Group, Hohai University.*
