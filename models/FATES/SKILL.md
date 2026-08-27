> **MANDATORY EXECUTION POLICY** — READ BEFORE PROCEEDING
>
> You MUST run the **actual model binary or package** described in this document.
> If the model fails to import, compile, or execute, you MUST:
> 1. Check `diagnostics/triplets.yaml` for a matching error pattern
> 2. Try the fix suggested in the triplet's `remedy` section
> 3. If still failing, report the error to the user with full details
>
> You MUST NOT substitute a simplified Python formula, regression equation,
> or hand-coded approximation in place of the real model.
>
>
> Before starting, run: `python preflight_check.py` (in this KI directory)
> to verify that the model binary/package and required data are available.
>
> **DEBUGGING PROTOCOL** — When something goes wrong, follow this order:
> 1. **Check triplets** — `diagnostics/triplets.yaml` may already cover this error
> 2. **Read official docs** — The model's own documentation for expected formats/units
> 3. **Find working examples** — Check `outputs/` or the model's shipped test data
> 4. **Fix the tool** — With knowledge of what "correct" looks like
>
> Do NOT write custom debug scripts. The answers are in the docs and examples.

<!-- KI-MAP:BEGIN (projected by generate_skill_map.py — edit the KI, not this table) -->
## KI map — what to read, and when

| when you need | read | why |
|---|---|---|
| FIRST, always | `preflight_check.py` | run it (`python preflight_check.py`): proves env/binary/data are usable and emits a machine-readable `PREFLIGHT_REPORT=` line. Do not debug a run that never had a healthy environment. |
| to run the pipeline stages | `tools/` (5 tools) | the executable pipeline. Read each tool's argparse (`--help`) before composing a command; SKILL.md's stage table says which tool serves which stage. |
| before running a stage | `docs/s*_*.md` (5 stage docs) | per-stage procedure, verification and traps — the how-to that SKILL.md's overview compresses. |
| on ANY error, before debugging | `diagnostics/triplets.yaml` (18 entries) | symptom → diagnosis → remedy for this model's known failure modes. Check here FIRST; the answer usually exists. Never renumber or rewrite entries. |
| to know what an output IS | `dag.yaml` | the model's identity: every output's medium, units, `validation_rank` (1 = the headline variable) and observability. Scoring and obs-binding read THIS — when asked 'what does this model predict', the dag is the answer, not a guess. |
| when building inputs / parsing outputs | `docs/format_spec.yaml` | exact I/O shapes + `known_issues`, projected from dag + triplets. Regenerate with `ki_tools_common/generate_format_spec.py` after changing either — never hand-edit. |
| to judge a run's skill | `docs/validation_convention.yaml` | how this model's field judges it validated: per-`dag_variable` metrics, directions and CITED pass-bands. A run is graded against these, not against intuition. |
| for claims and thresholds | `docs/gathered_papers.json` (15 papers) + `docs/papers_index.md` | the literature this KI is judged by; each entry's `text_path` is fetched full text in the central paper cache. `role: benchmark` marks the model's own skill paper. |
| for a machine-readable summary | `knowledge_infrastructure.yaml` | the manifest (package, pipeline, validation tier, counts) — projected by `ki_tools_common/generate_ki_manifest.py`; regenerate after structural changes, never hand-edit. |

*Projected 2026-08-17 from the KI's actual contents — 9 components present. Refresh: `python3 ki_tools_common/generate_skill_map.py --ki_dir <this KI>`.*
<!-- KI-MAP:END -->

<!-- KI-TOOL-INDEX:BEGIN (projected by generate_skill_map.py — the discoverability contract: every public tool, exact path; PURPOSE stays human-authored elsewhere) -->
### Executable tool index (projected — complete by construction)

Every public tool in this KI, by exact path. What each is FOR lives in the
human-written Tool Inventory above; `--help` on any of these prints its arguments.

| tool (exact path) | invocation |
|---|---|
| `tools/convert_fates_params.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_fates_params.py --help` |
| `tools/convert_forcing_data.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_forcing_data.py --help` |
| `tools/convert_surface_data.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_surface_data.py --help` |
| `tools/parse_fates_output.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/parse_fates_output.py --help` |
| `tools/run_fates_case.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/run_fates_case.py --help` |

*5 public tools; `_`-prefixed helpers and packaging files excluded.*
<!-- KI-TOOL-INDEX:END -->

# FATES (Functionally Assembled Terrestrial Ecosystem Simulator) — Knowledge Infrastructure

**Package**: `hydrocraft-fates-vegetation` v1.0.0
**Model**: FATES (latest master, NGEET/fates)
**Domain**: Biogeochemistry / Dynamic Global Vegetation Model (DGVM)
**Created by**: Auto-dissect pipeline
**Last updated**: 2026-03-25
**Stats**: 5 tools | 5 skill documents | 18 diagnostic triplets | ~2,200 lines of validated Python
**Validation status**: `documentation_validated`

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for CMFD unit documentation and known traps.
See `data_ki/FLUXNET/SKILL.md` for eddy covariance flux observations.


## Overview

FATES is a size- and age-structured dynamic vegetation model that simulates terrestrial ecosystem
processes including plant growth, mortality, disturbance, and biogeochemistry. It is developed
primarily by the NGEE-Tropics project (DOE Office of Science) and runs as a **component within
host land models** — it cannot run standalone.

**What FATES simulates**:
- Cohort-based vegetation demographics (recruitment, growth, mortality)
- Plant carbon allocation via PARTEH (Plant Reactive Transport and Hydraulics)
- Canopy radiative transfer (Norman or Two-stream models)
- SPITFIRE fire dynamics (ignition, spread, scorch mortality)
- Plant hydraulics (experimental, Christoffersen et al. 2016)
- Selective logging and timber harvest
- Land use change (primary/secondary/pasture/cropland transitions)
- Carbon-Nitrogen-Phosphorus cycling (optional CNP mode)
- Phenology (evergreen, cold-deciduous, stress-deciduous)

**Key difference from standalone models**: FATES does not run independently. It requires a
host land model (HLM) that provides atmospheric forcing, soil physics, and the build/run
infrastructure. Supported HLMs:
- **CTSM/CLM** (Community Terrestrial Systems Model) — primary development platform
- **E3SM/ELM** (Energy Exascale Earth System Model / Energy Land Model)
- **CESM** (Community Earth System Model)

**Architecture**: Grid cells → Sites → Patches (age-structured) → Cohorts (size-structured)
- Each site represents a 10,000 m² notional forest area
- Patches are linked lists ordered by age (disturbance history)
- Cohorts are linked lists ordered by height (taller → shorter)
- 14 Plant Functional Types (PFTs): tropical/extratropical broadleaf, needleleaf, shrubs, grasses

---

## Installation

### Source Code
```
Repository:   https://github.com/NGEET/fates
Local clone:  source/repo/
Language:     Fortran 2003+ (89 files), Python (53 files), Shell (5 files)
Build system: CMake (requires CIME framework)
```

### Dependencies (External)
```
CIME          — Common Infrastructure for Modeling the Earth (build/case management)
ESMF          — Earth System Modeling Framework (coupling)
NetCDF-C      — libnetcdf (I/O)
NetCDF-Fortran — libnetcdff (restart/history files)
shr_* modules — CIME shared libraries (math, calendar, logging)
```

### Python Dependencies (for tools and testing)
```
numpy, pandas, xarray, netCDF4, matplotlib, scipy, json, argparse
```

### Host Model Setup (CTSM example)
```bash
# 1. Clone CTSM with FATES
git clone https://github.com/ESCOMP/CTSM.git
cd CTSM && ./manage_externals/checkout_externals

# 2. Create a single-point case with FATES
cd cime/scripts
./create_newcase --case ~/fates_test --compset I2000Clm51FatesRs \
    --res f09_g17 --run-unsupported

# 3. Build and run
cd ~/fates_test
./case.setup && ./case.build && ./case.submit
```

### Parameter Files
```
parameter_files/fates_params_default.json   — Default parameters (14 PFTs, 200+ params)
parameter_files/patch_default_bciopt224.json — BCI tropical site patch
parameter_files/archive/                    — Historical parameter versions
Format: JSON with dimensions, parameter names, units, and data arrays
```

### Functional Unit Tests (standalone, no host model needed)
```
functional_unit_testing/parteh/      — PARTEH allocation tests (Python + Fortran ctypes)
functional_unit_testing/leaf_biophys/ — Leaf photosynthesis tests
functional_unit_testing/hydro/       — Plant hydraulics tests
functional_unit_testing/radiation/   — Radiative transfer tests
```

---

## Pipeline (8 Stages)

| # | Stage | Tool(s) | Description |
|---|-------|---------|-------------|
| 0 | Configuration | (manual/CIME) | Select site, compset, resolution, FATES options |
| 1 | Parameter Setup | `convert_fates_params` | Prepare/modify JSON parameter file for target PFTs |
| 2 | Surface Data | `convert_surface_data` | Prepare surface dataset with soil/PFT mapping |
| 3 | Forcing Data | (host model) | Atmospheric forcing via DATM (data atmosphere) |
| 4 | Case Creation | `run_fates_case` | Create, configure, build CTSM/E3SM case |
| 5 | Execution | `run_fates_case` | Submit and monitor simulation |
| 6 | Output Analysis | `parse_fates_output` | Extract FATES history variables from NetCDF |
| 7 | Diagnostics | triplets.yaml | Troubleshoot common failures |

### Stage Dependencies
```
Stage 0 (config) → Stage 1 (params) + Stage 2 (surface) → Stage 3 (forcing)
                                                            ↓
Stage 4 (case creation) depends on 1, 2, 3
Stage 5 (execution) depends on 4
Stage 6 (output) depends on 5
Stage 7 (diagnostics) can run at any failure point
```

---

## Tools Reference

| Tool | Stage | Script Path | Purpose |
|------|-------|-------------|---------|
| `convert_fates_params` | s1 | `tools/convert_fates_params.py` | Read/modify/validate FATES JSON parameter files |
| `convert_surface_data` | s2 | `tools/convert_surface_data.py` | Generate surface dataset with soil and PFT mapping |
| `convert_forcing_data` | s3 | `tools/convert_forcing_data.py` | Convert atmospheric forcing to DATM units (K, mm/s, W/m2) |
| `run_fates_case` | s4-s5 | `tools/run_fates_case.py` | Create, build, and run CTSM case with FATES |
| `parse_fates_output` | s6 | `tools/parse_fates_output.py` | Parse FATES NetCDF history output to CSV/plots |

---

## 6. Output Description

**Source of truth**: `dag.yaml`. This section restates the KI's dag facts for the
reader. If this body ever disagrees with `dag.yaml`, the dag wins and this section is
the item to fix.

**Headline output** (dag `validation_rank: 1`):

> `FATES_GPP` — Vegetation gross primary production. (`kgC/m2/s`)

| Output variable (dag `var`) | Dag role | Unit | Description |
|-----------------------------|----------|------|-------------|
| `FATES_GPP` | rank-1 output | `kgC/m2/s` | Vegetation gross primary production. |

Other dag outputs listed by this KI:

| Output variable (dag `var`) |
|-----------------------------|
| `FATES_VEGC` |
| `FATES_NPP` |
| `FATES_LAI` |
| `FATES_NPLANT` |
| `FATES_MORTALITY` |
| `FATES_DISTURBANCE_RATE_FIRE` |

The host-model history stream may expose many additional FATES diagnostics, but the
observable-output contract for scoring and output binding is the dag list above.

---

## Critical Domain Knowledge

### Unit System (CRITICAL — causes silent failures)

| Variable | FATES Internal Unit | Common Source Unit | Conversion | Trap ID |
|----------|--------------------|--------------------|------------|---------|
| Biomass (all organs) | kgC / individual | tC/ha, gC/m² | ÷1000, ×area | dt_001 |
| Stem density | stems / m² | stems / ha | ÷ 10000 | dt_002 |
| Patch area | m² | ha | × 10000 | dt_003 |
| GPP flux | kgC / indiv / timestep | gC / m² / day | ÷1000, ×n, ÷dt | dt_004 |
| Temperature | K (Kelvin) | °C | + 273.15 | dt_005 |
| Precipitation | mm / s (HLM) | mm / day | ÷ 86400 | dt_006 |
| Radiation | W / m² | MJ / m² / day | ÷ 86400 × 1e6 | dt_007 |
| DBH | cm | mm, m | ÷10 or ×100 | dt_008 |
| Height | m | cm, ft | ÷100 or ×0.3048 | dt_009 |
| Crown area | m² | ha | × 10000 | dt_010 |
| Soil water | m³ / m³ (volumetric) | % | ÷ 100 | dt_011 |
| CO₂ concentration | ppmv | mol/mol | × 1e6 | dt_012 |

## 8. Unit Conversion Table

**Source of truth**: output units come from `dag.yaml`; conversion traps come from the
KI's diagnostics and existing unit-system notes. Do not infer units from variable names.

### Unit Table Scope

This unit table records sourced dag output units and the pipeline conversions already
documented by the KI's diagnostic triplets.

### Dag Output Units

| Variable | Unit from dag | Notes |
|----------|---------------|-------|
| `FATES_GPP` | `kgC/m2/s` | Rank-1 output; description in dag: Vegetation gross primary production. |
| `FATES_VEGC` | see `dag.yaml` | Dag-listed output; unit not restated here without a sourced dag value. |
| `FATES_NPP` | see `dag.yaml` | Dag-listed output; unit not restated here without a sourced dag value. |
| `FATES_LAI` | see `dag.yaml` | Dag-listed output; unit not restated here without a sourced dag value. |
| `FATES_NPLANT` | see `dag.yaml` | Dag-listed output; unit not restated here without a sourced dag value. |
| `FATES_MORTALITY` | see `dag.yaml` | Dag-listed output; unit not restated here without a sourced dag value. |
| `FATES_DISTURBANCE_RATE_FIRE` | see `dag.yaml` | Dag-listed output; unit not restated here without a sourced dag value. |

### Pipeline Unit Conversions

| Variable | Source unit | Model or internal unit | Conversion | Trap ID |
|----------|-------------|------------------------|------------|---------|
| Biomass (all organs) | tC/ha, gC/m² | kgC / individual | ÷1000, ×area | dt_001 |
| Stem density | stems / ha | stems / m² | ÷ 10000 | dt_002 |
| Patch area | ha | m² | × 10000 | dt_003 |
| GPP flux | gC / m² / day | kgC / indiv / timestep | ÷1000, ×n, ÷dt | dt_004 |
| Temperature | °C | K (Kelvin) | + 273.15 | dt_005 |
| Precipitation | mm / day | mm / s (HLM) | ÷ 86400 | dt_006 |
| Radiation | MJ / m² / day | W / m² | ÷ 86400 × 1e6 | dt_007 |
| DBH | mm, m | cm | ÷10 or ×100 | dt_008 |
| Height | cm, ft | m | ÷100 or ×0.3048 | dt_009 |
| Crown area | ha | m² | × 10000 | dt_010 |
| Soil water | % | m³ / m³ (volumetric) | ÷ 100 | dt_011 |
| CO₂ concentration | mol/mol | ppmv | × 1e6 | dt_012 |

### 9 Non-Obvious Facts That Cause Silent Failures

1. **dt_001: Biomass units are kgC per individual, not per m²**
   FATES tracks organ masses (leaf, root, sapwood, structure) as kgC per individual plant.
   To get ecosystem-level biomass (kgC/m²), multiply by stem density `n` [stems/m²].
   Forgetting the density scaling produces values orders of magnitude wrong.

2. **dt_002: The notional patch area is exactly 10,000 m² (1 ha)**
   All patch-level densities and fluxes are normalized to this area. If you interpret
   `n` as stems/ha instead of stems/m², everything is off by 10,000×.

3. **dt_003: FATES cannot run standalone — it needs a host model**
   Unlike GLM or VIC, there is no `fates` binary to execute directly. FATES is compiled
   into the host model (CLM/ELM) via CMake. Running FATES means running CTSM/E3SM.

4. **dt_013: JSON parameter files replaced the legacy netCDF CDL format**
   Old documentation may reference `.cdl` or `.nc` parameter files. Since ~2023, FATES
   uses JSON exclusively. Tools like `modify_fates_paramfile.py` work with JSON only.

5. **dt_014: PFT indices are 1-based in Fortran but 0-based in JSON arrays**
   When modifying parameters in JSON, the first PFT has index 0. When reading Fortran
   source, PFT indices start at 1. This causes off-by-one errors in parameter modification.

6. **dt_015: PARTEH mass units are kg (not gC or tC)**
   The PARTEH allocation module explicitly declares `mass_unit = 'kg'` and
   `mass_rate_unit = 'kg/day'`. Minimum allowed value: 1.0e-15 kg.

7. **dt_016: Fire model (SPITFIRE) is disabled by default**
   `hlm_spitfire_mode = 0` means no fire. Setting it to 1-4 enables different
   ignition sources. Without fire, mortality from burns is zero — which may be
   unrealistic for fire-prone ecosystems.

8. **dt_017: Plant hydraulics is EXPERIMENTAL and requires citation**
   If `hlm_use_planthydro = .true.`, the Christoffersen et al. (2016) hydraulics
   model activates. This is still under testing and may produce unreliable results.

9. **dt_018: The restart file format changes with code updates**
   FATES restart files are not backward-compatible across major versions. A restart
   from an older FATES version will crash or produce silent errors with newer code.

---

## Allometry System

FATES uses diameter at breast height (DBH, cm) as the primary state variable for tree
structure. All biomass pools are derived from DBH via allometric equations:

```
DBH [cm] → Height [m]           h_allom()
DBH [cm] → Leaf biomass [kgC]   blmax_allom()
DBH [cm] → Fine root [kgC]      bfineroot()  (= bleaf × l2fr)
DBH [cm] → Sapwood [kgC]        bsap_allom()
DBH [cm] → Structural [kgC]     bdead_allom()
DBH [cm] → Crown area [m²]      carea_allom()
DBH [cm] → AGB [kgC]            bagw_allom()
```

Allometric parameters are PFT-specific and stored in the JSON parameter file. The
allometric hypothesis is selected via `fates_allom_*` parameters.

---

## Output Variables (via Host Model History Files)

FATES writes ~200+ diagnostic variables to the host model's history stream (NetCDF).
Key output categories:

| Category | Example Variables | Units |
|----------|------------------|-------|
| Biomass pools | FATES_VEGC, FATES_LEAFC, FATES_SAPWOODC | kgC/m² |
| Carbon fluxes | FATES_GPP, FATES_NPP, FATES_AUTORESP | kgC/m²/s |
| Structure | FATES_LAI, FATES_CANOPY_AREA_HT | m²/m², m² |
| Demographics | FATES_NPLANT, FATES_MORTALITY | stems/m², stems/m²/yr |
| Disturbance | FATES_DISTURBANCE_RATE_FIRE | fraction/yr |
| Fire | FATES_FIRE_INTENSITY, FATES_AREA_BURNT | kW/m, fraction |
| Phenology | FATES_ELAI, FATES_ESAI | m²/m² |
| Size-binned | FATES_*_SZPF (by size class and PFT) | varies |
| Age-binned | FATES_*_AP (by patch age class) | varies |

**History output bins** (configurable in parameter file):
- Size classes: 13 bins (0, 1, 2, 5, 10, 15, 20, 30, 40, 50, 60, 70, 80+ cm DBH)
- Age classes: 7 bins (0, 1, 2, 5, 10, 20, 50+ years)
- Height classes: 6 bins (0, 1, 2, 5, 10, 20+ m)
- Damage classes: 2 bins (undamaged, damaged)

---

## Calibration Parameters (Priority Order)

| Parameter | Sensitivity | Range | Default | Description |
|-----------|------------|-------|---------|-------------|
| `fates_mort_scalar_cstarvation` | HIGH | 0.1–10 | 0.6 | Carbon starvation mortality rate |
| `fates_allom_d2bl1` | HIGH | PFT-specific | varies | DBH to leaf biomass allometric coeff |
| `fates_leaf_vcmax25top` | HIGH | 10–100 µmol/m²/s | PFT-specific | Max carboxylation rate |
| `fates_turnover_leaf` | HIGH | 0.5–10 yr | PFT-specific | Leaf longevity |
| `fates_recruit_seed_supplement` | HIGH | 0–1 | 0 | Seed rain supplementation |
| `fates_mort_scalar_hydrfailure` | MEDIUM | 0.1–10 | 0.6 | Hydraulic failure mortality |
| `fates_fire_nignitions` | MEDIUM | 0–0.1 /km²/day | 0.003 | Lightning ignition density |
| `fates_allom_d2h1` | MEDIUM | PFT-specific | varies | DBH to height allometric coeff |
| `fates_leaf_slatop` | MEDIUM | 0.005–0.05 m²/gC | PFT-specific | Specific leaf area at top |
| `fates_phen_drought_threshold` | MEDIUM | -2 to -0.5 MPa | -0.15 | Drought phenology threshold |

---

## Coupling Points

| Source → Target | Variable | Units | Tool |
|----------------|----------|-------|------|
| DATM → CTSM → FATES | Temperature, precip, radiation, wind, humidity | K, mm/s, W/m² | Host model |
| FATES → CLM soil BGC | Litter C/N/P fluxes | kgC/m²/s | FatesSoilBGCFluxMod |
| FATES → Atmosphere | Canopy albedo, ET, sensible heat | -, mm/s, W/m² | Host model |
| External → FATES | Land use transitions (LUH2) | fraction/yr | FatesLandUseChangeMod |
| External → FATES | Logging harvest rates | fraction/yr | EDLoggingMortalityMod |
| FATES → CH4 model | Root fraction profiles, GPP | -, kgC/m²/s | PrepCH4BCs |

---

## Quick Start Examples

```bash
# 1. List all parameters in the default file
python tools/modify_fates_paramfile.py \
    --fin parameter_files/fates_params_default.json --listparams

# 2. Query a specific parameter
python tools/modify_fates_paramfile.py \
    --fin parameter_files/fates_params_default.json \
    --queryparam fates_leaf_vcmax25top

# 3. Modify Vcmax for PFT 1 (tropical broadleaf evergreen)
python tools/modify_fates_paramfile.py \
    --fin parameter_files/fates_params_default.json \
    --fout parameter_files/custom_params.json \
    --param fates_leaf_vcmax25top --indices 1 --values 65.0

# 4. Convert FATES params and validate
python ki/tools/convert_fates_params.py \
    --fin parameter_files/fates_params_default.json \
    --operation validate --report params_report.json

# 5. Parse FATES output from a completed CTSM run
python ki/tools/parse_fates_output.py \
    --input /path/to/case/run/case.clm2.h0.*.nc \
    --variables FATES_GPP,FATES_LAI,FATES_VEGC \
    --output fates_timeseries.csv

# 6. Run a CTSM single-point case with FATES
python ki/tools/run_fates_case.py \
    --ctsm-root /path/to/CTSM --site-name BCI \
    --lat 9.15 --lon -79.85 --start 2000-01-01 --stop 2005-01-01
```

---

## Diagnostic Triplets Summary

| ID | Severity | Domain | Summary |
|----|----------|--------|---------|
| dt_001 | silent | unit_conversion | Biomass per individual vs per m² confusion |
| dt_002 | silent | unit_conversion | Stem density stems/m² vs stems/ha (10000×) |
| dt_003 | silent | unit_conversion | Patch area m² vs ha |
| dt_004 | silent | unit_conversion | GPP flux unit chain error |
| dt_005 | silent | unit_conversion | Temperature K vs °C offset missing |
| dt_006 | silent | unit_conversion | Precipitation mm/s vs mm/day |
| dt_007 | silent | unit_conversion | Radiation W/m² vs MJ/m²/day |
| dt_008 | silent | unit_conversion | DBH cm vs mm |
| dt_009 | silent | unit_conversion | Height m vs cm |
| dt_010 | silent | unit_conversion | Crown area m² vs ha |
| dt_011 | silent | unit_conversion | Soil water fraction vs percent |
| dt_012 | silent | unit_conversion | CO₂ ppmv vs mol/mol |
| dt_013 | degraded | parameter_format | JSON params replaced legacy CDL/netCDF |
| dt_014 | silent | parameter_format | PFT index off-by-one (0-based JSON vs 1-based Fortran) |
| dt_015 | silent | unit_conversion | PARTEH mass in kg not gC or tC |
| dt_016 | degraded | configuration | Fire model (SPITFIRE) disabled by default |
| dt_017 | degraded | configuration | Plant hydraulics experimental and unstable |
| dt_018 | fatal | runtime | Restart file version incompatibility |

**Silent error count**: 13/18 (72%)

---

## 11. Validated Results

**Source of truth**: `docs/validation_convention.yaml`. The convention file defines
which metrics judge each dag variable, which direction is better, and the cited
pass-bands. A null band in the convention is reported here exactly as
`no cited threshold`; no remembered thresholds are substituted.

### Convention Bars

| Dag variable | Metric | Direction | Satisfactory band | Citation key |
|--------------|--------|-----------|-------------------|--------------|
| `FATES_VEGC` | `pbias` | zero_centered | no cited threshold | `[]` |
| `FATES_VEGC` | `csi` | maximize | no cited threshold | `[]` |
| `FATES_VEGC` | `ilamb_overall_score` | maximize | no cited threshold | `[]` |
| `FATES_GPP` | `nse` | maximize | no cited threshold | `[]` |
| `FATES_GPP` | `rmse` | minimize | no cited threshold | `[]` |

### Rank-1 Output Bar

`FATES_GPP` is the dag rank-1 output. The validation convention lists `nse`
with direction `maximize` and `rmse` with direction `minimize`; both have
`no cited threshold`.

### Achieved Results

No achieved calibration, validation, or full-period metric values are restated in this
body section. When results exist, report them beside the convention bar above and keep
the threshold wording sourced from `docs/validation_convention.yaml`.

---

## File Structure

```
ki/
├── SKILL.md                          ← This file (master reference)
├── tools/
│   ├── convert_fates_params.py       ← Parameter file validation/conversion
│   ├── convert_surface_data.py       ← Surface dataset preparation (HWSD soil)
│   ├── convert_forcing_data.py       ← Atmospheric forcing unit converter (dt_005/006/007)
│   ├── run_fates_case.py             ← CTSM case creation and execution wrapper
│   └── parse_fates_output.py         ← NetCDF history output to CSV/plots
├── docs/
│   ├── s1_parameter_setup.md         ← Parameter file management skill
│   ├── s2_surface_data.md            ← Surface dataset preparation skill
│   ├── s3_forcing_data.md            ← Atmospheric forcing configuration skill
│   ├── s4_case_creation.md           ← CTSM case creation and build skill
│   └── s5_output_analysis.md         ← Output parsing and analysis skill
└── diagnostics/
    └── triplets.yaml                 ← 18 symptom->diagnosis->remedy entries
```

---

## References

- Fisher et al. (2015). Taking off the training wheels: the properties of a dynamic
  vegetation model without climate envelopes. *Ecological Modelling*, 101, 1–22.
- Koven et al. (2020). Benchmarking and parameter sensitivity of physiological and
  vegetation dynamics using the FATES model at tropical sites. *Biogeosciences*, 17, 4851–4881.
- FATES User's Guide: https://fates-users-guide.readthedocs.io/
- FATES Technical Docs: https://fates-docs.readthedocs.io/
- FATES GitHub: https://github.com/NGEET/fates
- FATES Discussions: https://github.com/NGEET/fates/discussions
