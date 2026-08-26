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
| to run the pipeline stages | `tools/` (4 tools) | the executable pipeline. Read each tool's argparse (`--help`) before composing a command; SKILL.md's stage table says which tool serves which stage. |
| before running a stage | `docs/s*_*.md` (7 stage docs) | per-stage procedure, verification and traps — the how-to that SKILL.md's overview compresses. |
| on ANY error, before debugging | `diagnostics/triplets.yaml` (20 entries) | symptom → diagnosis → remedy for this model's known failure modes. Check here FIRST; the answer usually exists. Never renumber or rewrite entries. |
| to know what an output IS | `dag.yaml` | the model's identity: every output's medium, units, `validation_rank` (1 = the headline variable) and observability. Scoring and obs-binding read THIS — when asked 'what does this model predict', the dag is the answer, not a guess. |
| when building inputs / parsing outputs | `docs/format_spec.yaml` | exact I/O shapes + `known_issues`, projected from dag + triplets. Regenerate with `ki_tools_common/generate_format_spec.py` after changing either — never hand-edit. |
| to judge a run's skill | `docs/validation_convention.yaml` | how this model's field judges it validated: per-`dag_variable` metrics, directions and CITED pass-bands. A run is graded against these, not against intuition. |
| for claims and thresholds | `docs/gathered_papers.json` (22 papers) + `docs/papers_index.md` | the literature this KI is judged by; each entry's `text_path` is fetched full text in the central paper cache. `role: benchmark` marks the model's own skill paper. |
| for a machine-readable summary | `knowledge_infrastructure.yaml` | the manifest (package, pipeline, validation tier, counts) — projected by `ki_tools_common/generate_ki_manifest.py`; regenerate after structural changes, never hand-edit. |

*Projected 2026-08-17 from the KI's actual contents — 9 components present. Refresh: `python3 ki_tools_common/generate_skill_map.py --ki_dir <this KI>`.*
<!-- KI-MAP:END -->

<!-- KI-TOOL-INDEX:BEGIN (projected by generate_skill_map.py — the discoverability contract: every public tool, exact path; PURPOSE stays human-authored elsewhere) -->
### Executable tool index (projected — complete by construction)

Every public tool in this KI, by exact path. What each is FOR lives in the
human-written Tool Inventory above; `--help` on any of these prints its arguments.

| tool (exact path) | invocation |
|---|---|
| `tools/convert_forcing_to_elm.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_forcing_to_elm.py --help` |
| `tools/convert_surface_data.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_surface_data.py --help` |
| `tools/parse_elm_output.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/parse_elm_output.py --help` |
| `tools/run_elm.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/run_elm.py --help` |

*4 public tools; `_`-prefixed helpers and packaging files excluded.*
<!-- KI-TOOL-INDEX:END -->

# ELM (E3SM Land Model) — Knowledge Infrastructure

**Package**: hydrocraft-elm-landsurface v1.0.0
**Model**: ELM (E3SM Land Model) — component of E3SM v3
**Domain**: Land surface processes (energy, water, carbon, nitrogen, phosphorus)
**Created by**: Auto-dissection pipeline
**Last updated**: 2026-03-26
**Stats**: 4 tools | 7 skill documents | 20 diagnostic triplets | ~1,800 lines of validated Python
**Validation status**: `documentation_validated` (no HPC cluster available for execution)

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for CMFD unit documentation and known traps.
See `data_ki/FLUXNET/SKILL.md` for eddy covariance flux observations.


## 1. Overview

ELM (E3SM Land Model) is the land surface component of the Energy Exascale Earth
System Model (E3SM), developed by the U.S. Department of Energy. It is a
descendant of the Community Land Model (CLM) and simulates the exchange of
energy, water, carbon, nitrogen, and phosphorus between the land surface and the
atmosphere.

### Key capabilities

- **Biogeophysics**: Radiative transfer (two-stream), surface energy balance,
  turbulent fluxes (Monin-Obukhov), soil thermal diffusion (20-layer),
  snow physics (12-layer SNICAR), lake thermodynamics (10-layer).
- **Hydrology**: Canopy interception, infiltration, Richards equation soil
  water, subsurface drainage, surface runoff (TOPMODEL/VIC), groundwater.
- **Biogeochemistry**: C/N/P cycling with prognostic phenology, litter
  decomposition (Century cascade), methane production/oxidation, nitrification/
  denitrification, fire disturbance.
- **Vegetation dynamics**: Optional FATES (Functionally Assembled Terrestrial
  Ecosystem Simulator) for cohort-based vegetation.
- **Crop model**: Prognostic crop model with irrigation, fertilization.
- **Urban model**: CLMU urban canyon energy balance.

### What makes ELM different from other land models

| Feature | ELM | Noah-MP | JULES |
|---------|-----|---------|-------|
| Vertical soil layers | 20 hydro + 15 thermal | 4 | 4-20 |
| Biogeochemistry | Full C/N/P | None | C/N |
| Vegetation dynamics | FATES optional | None | TRIFFID |
| Snow layers | Up to 12 | 3 | 0-3 |
| Crop model | Built-in | None | None |
| Build system | CIME/CMake | Make | FCM |
| Execution | HPC batch (MPI+OpenMP) | Standalone | Standalone |

### Domain scope

ELM is designed for global simulations on DOE supercomputers. Running it on a
standalone workstation requires the full E3SM/CIME infrastructure. It cannot be
run as a simple command-line executable — it requires case creation, namelist
generation, compilation, and batch submission through the CIME framework.

---

## 2. Installation

### Prerequisites

ELM requires the full E3SM software stack:

- **HPC environment**: MPI implementation (mpich or openmpi)
- **Compilers**: Fortran 2003+ (gfortran 9+, Intel ifort 19+, or NVHPC)
- **Build tools**: CMake 3.18+, GNU Make
- **Libraries**: NetCDF-Fortran, HDF5, PIO/SCORPIO (parallel I/O)
- **CIME**: Common Infrastructure for Modeling the Earth (included in E3SM)
- **Python**: 3.7+ (for CIME scripts, namelist generation)

### Supported machines

ELM is designed for DOE Leadership Computing Facilities. Supported machines are
listed in `cime_config/machines/config_machines.xml`. Running on unsupported
machines requires creating a custom machine configuration.

```bash
# Check supported machines
cd /path/to/E3SM/cime/scripts
./query_config --machines
```

### Build procedure (on a supported machine)

```bash
# 1. Clone and initialize submodules
git clone --recursive https://github.com/E3SM-Project/E3SM.git
cd E3SM
git submodule update --init --recursive --depth=1

# 2. Create a land-only case
cd cime/scripts
./create_newcase --case ../../my_elm_case \
    --compset I1850CNPRDCTCBCTOP \
    --res ne4pg2_ne4pg2 \
    --mach <MACHINE_NAME>

# 3. Setup and build
cd ../../my_elm_case
./case.setup
./case.build     # ~10-30 min depending on machine

# 4. Submit
./case.submit
```

### Python tools dependencies (for this KI package)

```bash
pip install numpy pandas netCDF4 xarray matplotlib pyyaml
```

---

## 3. Pipeline Stages

The ELM simulation pipeline consists of 8 stages:

| Stage | Name | Tools | Description |
|-------|------|-------|-------------|
| s0 | Configuration | — | Install E3SM, configure machine, verify compilers |
| s1 | Surface Data | `convert_surface_data.py` | Create surface dataset (PFT fractions, soil texture, topography) |
| s2 | Forcing Data | `convert_forcing_to_elm.py` | Convert atmospheric forcing to DATM format (solar, precip, T, q, wind, LW) |
| s3 | Namelist Setup | — | Generate lnd_in namelist via CIME build-namelist |
| s4 | Initial Conditions | — | Create or interpolate finidat file for cold/warm start |
| s5 | Compilation | — | Build ELM with case.build |
| s6 | Execution | `run_elm.py` | Execute simulation via case.submit or direct mpirun |
| s7 | Output Analysis | `parse_elm_output.py` | Extract history variables from NetCDF output to CSV |
| s8 | Validation | — | Compare outputs against observations, compute metrics |

### Parallelism

- Stages s1 and s2 can run in parallel (independent data preparation)
- Stages s3 and s4 can run in parallel (both depend on s1)
- Stage s5 depends on s0, s3
- Stage s6 depends on s1, s2, s4, s5

---

## 4. Tools Reference

| Tool | Stage | Script | Lines | Purpose |
|------|-------|--------|-------|---------|
| convert_forcing_to_elm | s2 | `tools/convert_forcing_to_elm.py` | ~500 | Convert ERA5/GSWP3 forcing to DATM-compatible NetCDF |
| convert_surface_data | s1 | `tools/convert_surface_data.py` | ~450 | Generate surface dataset from HWSD/soil texture data |
| run_elm | s6 | `tools/run_elm.py` | ~350 | Execute ELM via CIME case.submit or direct MPI |
| parse_elm_output | s7 | `tools/parse_elm_output.py` | ~400 | Extract history fields from NetCDF to CSV/DataFrame |

---

## 5. Input Data Requirements

### Atmospheric forcing (DATM)

ELM receives forcing from a data atmosphere model (DATM) that reads NetCDF files.

| Variable | DATM Name | Units | Notes |
|----------|-----------|-------|-------|
| Air temperature | TBOT | K | **NOT °C** — dt_001 |
| Precipitation (rain) | PRECTmms | mm/s | **NOT mm/day or m/day** — dt_002 |
| Precipitation (snow) | SNOW | mm/s | Same as rain but frozen |
| Specific humidity | SHUM | kg/kg | **NOT relative humidity %** — dt_003 |
| Downwelling SW | FSDS | W/m² | Total (direct+diffuse) |
| Downwelling LW | FLDS | W/m² | Longwave radiation |
| Wind speed (zonal) | WIND | m/s | Magnitude at reference height |
| Surface pressure | PSRF | Pa | **NOT hPa or kPa** — dt_004 |
| Reference height | z | m | Measurement height (typically 10m for wind) |

### Surface dataset (surfdata_*.nc)

Created by `mksurfdata_map` tool or our `convert_surface_data.py`:

| Variable | Units | Source |
|----------|-------|--------|
| PCT_PFT | % (0-100) | Plant functional type fractions |
| PCT_SAND | % (0-100) | Sand fraction per soil layer |
| PCT_CLAY | % (0-100) | Clay fraction per soil layer |
| ORGANIC | kg/m³ | Soil organic matter density |
| MONTHLY_LAI | m²/m² | Monthly leaf area index per PFT |
| MONTHLY_SAI | m²/m² | Monthly stem area index per PFT |
| LANDFRAC_PFT | fraction (0-1) | Land fraction |
| TOPO | m | Surface elevation |
| SLOPE | degrees | Terrain slope |
| STD_ELEV | m | Standard deviation of elevation |

### Parameter file (clm_params_*.nc)

Contains ~500 PFT-level and global parameters:

| Parameter | Units | Description |
|-----------|-------|-------------|
| slatop | m²/gC | Specific leaf area at top of canopy |
| vcmaxha | J/mol | Activation energy for Vcmax |
| medlynslope | — | Medlyn stomatal slope parameter |
| froot_leaf | gC/gC | Fine root to leaf allocation ratio |
| stem_leaf | gC/gC | Stem to leaf allocation ratio |
| flnr | fraction | Fraction of leaf N in Rubisco |

---

## 6. Output Description

ELM writes history files in NetCDF format. Up to 6 independent output streams
(history tapes) can be configured with different variables and frequencies.

This section restates `dag.yaml`. The dag is the model identity for observable
outputs; if this section and `dag.yaml` ever disagree, `dag.yaml` wins.

### Headline output

> `QRUNOFF` — Total runoff (surface runoff plus sub-surface drainage) leaving the land column. (`mm/s`)

### DAG output inventory

| Output variable (dag `var`) | Rank | Unit | Description |
|-----------------------------|------|------|-------------|
| QRUNOFF | 1 | mm/s | Total runoff (surface runoff plus sub-surface drainage) leaving the land column. |
| QDRAI | — | See `dag.yaml` | Other dag output |
| H2OSOI | — | See `dag.yaml` | Other dag output |
| EFLX_LH_TOT | — | See `dag.yaml` | Other dag output |
| FSH | — | See `dag.yaml` | Other dag output |
| GPP | — | See `dag.yaml` | Other dag output |
| NEE | — | See `dag.yaml` | Other dag output |
| TSOI | — | See `dag.yaml` | Other dag output |
| TWS | — | See `dag.yaml` | Other dag output |

### Key output variables

| Variable | Long Name | Units | Frequency |
|----------|-----------|-------|-----------|
| GPP | Gross primary production | gC/m²/s | Monthly |
| NPP | Net primary production | gC/m²/s | Monthly |
| NEE | Net ecosystem exchange | gC/m²/s | Monthly |
| HR | Heterotrophic respiration | gC/m²/s | Monthly |
| FSH | Sensible heat flux | W/m² | Monthly |
| EFLX_LH_TOT | Total latent heat flux | W/m² | Monthly |
| QRUNOFF | Total runoff | mm/s | Monthly |
| QOVER | Surface runoff | mm/s | Monthly |
| QDRAI | Subsurface drainage | mm/s | Monthly |
| H2OSOI | Volumetric soil moisture | mm³/mm³ | Monthly |
| TSOI | Soil temperature | K | Monthly |
| H2OSNO | Snow water equivalent | mm | Monthly |
| SNOW_DEPTH | Snow depth | m | Monthly |
| TLAI | Total LAI | m²/m² | Monthly |
| TV | Vegetation temperature | K | Monthly |
| TG | Ground temperature | K | Monthly |
| FSA | Absorbed shortwave radiation | W/m² | Monthly |
| FIRA | Net longwave radiation | W/m² | Monthly |
| TOTECOSYSC | Total ecosystem carbon | gC/m² | Monthly |
| TOTECOSYSN | Total ecosystem nitrogen | gN/m² | Monthly |
| TOTECOSYSP | Total ecosystem phosphorus | gP/m² | Monthly |

### History file configuration (in user_nl_elm)

```fortran
! Daily output of water/energy variables
hist_nhtfrq(2) = -24
hist_mfilt(2) = 365
hist_fincl2 = 'GPP','NPP','QRUNOFF','FSH','EFLX_LH_TOT','H2OSOI','TSOI'

! Hourly output for a short period
hist_nhtfrq(3) = -1
hist_mfilt(3) = 8760
hist_fincl3 = 'FSA','FLDS','FSDS','RAIN','SNOW'
```

---

## 7. Namelist Configuration

ELM is configured through Fortran namelists in the `lnd_in` file, generated
by CIME's `build-namelist` utility. Key namelist groups:

### &elm_inparm (primary)

```fortran
&elm_inparm
  ! Time stepping
  dtime = 1800                    ! Model timestep (seconds) — dt_005

  ! CO2
  co2_type = 'constant'          ! 'constant', 'diagnostic', 'prognostic'
  co2_ppmv = 284.7               ! CO2 concentration for 1850

  ! BGC mode
  bgc_mode = 'bgc'               ! 'sp' (satellite phenology), 'cn', 'bgc'
  use_cn = .true.                 ! Carbon-nitrogen cycling
  use_crop = .false.              ! Crop model
  irrigate = .false.              ! Irrigation

  ! Input files
  fsurdat = '/path/to/surfdata.nc'
  finidat = '/path/to/finidat.nc'   ! '' for cold start
  paramfile = '/path/to/clm_params.nc'

  ! Soil decomposition
  soil_decomp = 'ctc'            ! 'ctc' (Century) or 'cn' (CLM-CN)

  ! Hydrology
  h2osfcflag = 1                 ! Surface water scheme (0 or 1)
  origflag = 0                   ! Original CLM4 hydrology (0=off, 1=on)

  ! Nutrient competition
  nu_com = 'RD'                  ! 'RD' (relative demand), 'ECA', 'MIC'

  ! History
  hist_nhtfrq = 0, -24, 0, 0, 0, 0    ! 0=monthly, -N=every N hours
  hist_mfilt = 12, 365, 1, 1, 1, 1    ! Max time samples per file
/
```

---

## 8. Unit Conversion Table and Critical Domain Knowledge

Exact I/O shapes live in `docs/format_spec.yaml`; this table summarizes the
unit conversions and unit-preservation rules called out by this KI.

### Unit table

| Variable | Source unit | Model or output unit | Factor | Type | Notes |
|----------|-------------|----------------------|--------|------|-------|
| TBOT | K | K | x1 | preserve | Air temperature forcing; do not convert to °C. |
| PRECTmms | mm/s | mm/s | x1 | preserve | Rain forcing; do not convert from or to mm/day. |
| SNOW | mm/s | mm/s | x1 | preserve | Frozen precipitation forcing; same rate convention as rain. |
| SHUM | kg/kg | kg/kg | x1 | preserve | Specific humidity; not relative humidity percent. |
| FSDS | W/m² | W/m² | x1 | preserve | Downwelling shortwave radiation. |
| FLDS | W/m² | W/m² | x1 | preserve | Downwelling longwave radiation. |
| WIND | m/s | m/s | x1 | preserve | Wind speed magnitude at reference height. |
| PSRF | Pa | Pa | x1 | preserve | Surface pressure; not hPa, kPa, or mbar. |
| z | m | m | x1 | preserve | Reference height. |
| PCT_PFT | % | % | x1 | preserve | Plant functional type fractions, 0-100. |
| PCT_SAND | % | % | x1 | preserve | Sand fraction per soil layer. |
| PCT_CLAY | % | % | x1 | preserve | Clay fraction per soil layer. |
| ORGANIC | kg/m³ | kg/m³ | x1 | preserve | Soil organic matter density. |
| MONTHLY_LAI | m²/m² | m²/m² | x1 | preserve | Monthly leaf area index per PFT. |
| MONTHLY_SAI | m²/m² | m²/m² | x1 | preserve | Monthly stem area index per PFT. |
| LANDFRAC_PFT | fraction (0-1) | fraction (0-1) | x1 | preserve | Land fraction. |
| TOPO | m | m | x1 | preserve | Surface elevation. |
| SLOPE | degrees | degrees | x1 | preserve | Terrain slope. |
| STD_ELEV | m | m | x1 | preserve | Standard deviation of elevation. |
| QRUNOFF | mm/s | mm/s | x1 | preserve | Rank-1 output: total runoff leaving the land column. |
| QDRAI | mm/s | mm/s | x1 | preserve | Subsurface drainage output/coupling flux. |

### Critical domain knowledge — unit trap table

These are the most common silent errors when setting up ELM. Each entry links
to a diagnostic triplet for automated detection.

| # | Trap | dt_ID | Symptom | Correct | Wrong |
|---|------|-------|---------|---------|-------|
| 1 | Temperature units | dt_001 | Unrealistic energy balance, model crash | K | °C |
| 2 | Precipitation units | dt_002 | 1000x too much/little rain, flooding or drought | mm/s | mm/day, m/day, mm/hr |
| 3 | Humidity format | dt_003 | Wrong latent heat, condensation everywhere | kg/kg (specific) | % (relative), g/kg |
| 4 | Pressure units | dt_004 | Wrong air density, bad turbulent fluxes | Pa | hPa, kPa, mbar |
| 5 | Timestep mismatch | dt_005 | Numerical instability, energy imbalance | 1800 s (30 min) | 3600 s without adjusting physics |
| 6 | LAI units | dt_006 | Zero or extreme photosynthesis | m²/m² (0-12) | % or fraction |
| 7 | Soil texture sum | dt_007 | Invalid hydraulic parameters | sand+clay ≤ 100% | sand+clay > 100% |
| 8 | Namelist quotes | dt_008 | Parse failure, model won't start | 'single quotes' | "double quotes" |
| 9 | Cold start spin-up | dt_009 | Carbon pools at zero, unrealistic NEE | 200-500 yr spin-up | Direct production run |
| 10 | SW radiation split | dt_010 | Wrong canopy absorption profile | direct+diffuse, vis+nir | Total only |
| 11 | Soil organic matter | dt_011 | Wrong thermal/hydraulic properties in permafrost | kg/m³ (0-130) | % or g/g |
| 12 | CO2 concentration | dt_012 | Wrong GPP magnitude | ppmv (284-420) | mol/mol or Pa |
| 13 | Calendar type | dt_013 | Date drift, wrong seasonal cycle | noleap (365-day) | gregorian unless forced |
| 14 | Grid orientation | dt_014 | Forcing applied to wrong location | S→N, W→E | Flipped latitude |
| 15 | PFT fraction sum | dt_015 | Missing or double-counted area | Sum = 100% per gridcell | Sum ≠ 100% |

---

## 9. Compset Reference

ELM compsets define the model configuration. Land-only compsets use DATM.

| Alias | BGC Mode | Features | Use Case |
|-------|----------|----------|----------|
| I1850ELMCN | CN | Carbon-nitrogen | Basic BGC |
| I1850CNPRDCTCBC | CNP+RD+CTC | C/N/P, relative demand, Century decomp | Standard BGC |
| I1850CNPRDCTCBCTOP | CNP+RD+CTC+TOP | Above + topographic radiation | Default recommended |
| I1850CNPRDCTCBCPHS | CNP+RD+CTC+PHS | Above + plant hydraulic stress | Drought studies |
| I1850CNPRDCTCBCWFM | CNP+RD+CTC+WFM | Above + water/farm management | Agricultural |
| I20TRELMCN | CN transient | 1850-2015 transient forcing | Historical runs |
| IELMCNCROP | CN+CROP | CN with crop model | Crop modeling |
| IELM (SP mode) | SP | Satellite phenology (prescribed LAI) | Fast testing |

---

## 10. Vertical Structure

ELM uses a multi-layer vertical discretization:

### Soil layers (default 20 hydrologically active)

| Layer | Depth (m) | Thickness (m) | Notes |
|-------|-----------|---------------|-------|
| 1 | 0.007 | 0.014 | Thin surface layer |
| 2 | 0.028 | 0.028 | |
| 3 | 0.062 | 0.055 | |
| 4 | 0.119 | 0.069 | |
| 5 | 0.212 | 0.117 | |
| ... | ... | ... | Exponentially increasing |
| 15 | 3.433 | 1.137 | |
| 20 | 8.001 | 2.326 | Bottom of hydro-active |

Additional 15 thermal-only layers extend to ~40 m depth for deep soil
temperature (important for permafrost simulations).

### Snow layers (up to 12)

Snow is modeled with dynamic layering — layers are added/removed as snow
accumulates/melts. Each layer tracks:
- Temperature (K)
- Liquid water content (kg/m²)
- Ice content (kg/m²)
- Grain size (µm) for SNICAR albedo

### Lake layers (10)

For lake grid cells, a 10-layer lake model computes:
- Temperature profile
- Ice cover fraction
- Mixing (wind-driven, convective)

---

## 11. Validated Results

This KI is marked `documentation_validated` because no HPC cluster was available
for execution. No achieved calibration or validation metric is claimed here.
Judgment of any future run should use `docs/validation_convention.yaml`, restated
below from the KI's convention facts.

### Performance metrics — judged against the field's bar, not intuition

| Dag variable | Metric | Direction | Bands (convention, cited) |
|--------------|--------|-----------|---------------------------|
| QRUNOFF | nse | maximize | very_good ≥ 0.8 (`moriasi2015`, `arnold2012`); good ≥ 0.7 (`moriasi2015`, `arnold2012`); satisfactory ≥ 0.5 (`moriasi2015`, `arnold2012`) |
| QRUNOFF | pbias | zero_centered | very_good ≤ 5.0 (`moriasi2015`); good ≤ 10.0 (`moriasi2015`); satisfactory ≤ 15.0 (`moriasi2015`) |
| QRUNOFF | csi | maximize | satisfactory: no cited threshold |
| QDRAI | nse | maximize | very_good ≥ 0.8 (`moriasi2015`); good ≥ 0.7 (`moriasi2015`); satisfactory ≥ 0.5 (`moriasi2015`) |
| QDRAI | pbias | zero_centered | very_good ≤ 5.0 (`moriasi2015`); good ≤ 10.0 (`moriasi2015`); satisfactory ≤ 15.0 (`moriasi2015`) |

### Data replacement tracking

| Component | Source | Status | Notes |
|-----------|--------|--------|-------|
| Forcing | Pipeline | Documentation validated | CMFD/MSWX/NASA POWER loaders are referenced by this KI. |
| Soil | Pipeline | Documentation validated | Surface dataset preparation is covered by `tools/convert_surface_data.py`. |
| Land cover | Pipeline | Documentation validated | PFT fractions are prepared in the surface dataset workflow. |
| Initial conditions | CIME/ELM case configuration | Documentation validated | Cold/warm start setup is covered in the pipeline stages. |
| Model execution | E3SM/CIME | Pending runtime validation | No HPC execution result is claimed by this KI. |

---

## 12. Key Physical Constants

| Constant | Value | Units | Used in |
|----------|-------|-------|---------|
| grav | 9.80616 | m/s² | Hydrology, turbulence |
| sb | 5.67e-8 | W m⁻² K⁻⁴ | Longwave radiation |
| vkc | 0.4 | — | Turbulent fluxes (von Karman) |
| denh2o | 1000 | kg/m³ | Water density |
| denice | 917 | kg/m³ | Ice density |
| hvap | 2.501e6 | J/kg | Latent heat of vaporization |
| hsub | 2.501e6 + 3.337e5 | J/kg | Latent heat of sublimation |
| cpair | 1005 | J kg⁻¹ K⁻¹ | Air specific heat |
| tfrz | 273.15 | K | Freezing point |

---

## 13. Coupling Points with Other Models

ELM exchanges fields with other E3SM components through the MCT coupler:

| Direction | Partner | Variables | Units |
|-----------|---------|-----------|-------|
| ATM → LND | EAM/DATM | Tbot, q, precip, SW, LW, wind, P | K, kg/kg, mm/s, W/m², m/s, Pa |
| LND → ATM | EAM | Sensible heat, latent heat, albedo, emissivity | W/m², fraction |
| LND → ROF | MOSART | Surface runoff, subsurface drainage | mm/s |
| ROF → LND | MOSART | Flooded fraction, water table | fraction, m |
| LND → GLC | MALI | Snow/ice mass balance per elevation class | kg/m²/s |
| GLC → LND | MALI | Ice sheet topography, ice fraction | m, fraction |

---

## 14. Diagnostic Triplets Summary

20 triplets covering 6 failure domains:

| ID | Severity | Domain | Summary |
|----|----------|--------|---------|
| dt_001 | silent | unit_conversion | Temperature in °C instead of K |
| dt_002 | silent | unit_conversion | Precipitation in mm/day instead of mm/s |
| dt_003 | silent | unit_conversion | Relative humidity instead of specific humidity |
| dt_004 | silent | unit_conversion | Pressure in hPa instead of Pa |
| dt_005 | degraded | parameter | Timestep too large for physics stability |
| dt_006 | silent | unit_conversion | LAI in wrong units |
| dt_007 | fatal | input_validation | Soil texture fractions sum > 100% |
| dt_008 | fatal | parameter_format | Double quotes in Fortran namelist |
| dt_009 | degraded | initialization | Missing spin-up causes zero C pools |
| dt_010 | silent | unit_conversion | SW radiation not split into components |
| dt_011 | silent | unit_conversion | Soil organic matter in wrong units |
| dt_012 | silent | unit_conversion | CO2 in wrong units |
| dt_013 | degraded | calendar | Calendar mismatch causes date drift |
| dt_014 | silent | grid | Latitude orientation flipped |
| dt_015 | degraded | input_validation | PFT fractions don't sum to 100% |
| dt_016 | degraded | runtime | MPI task count doesn't match decomposition |
| dt_017 | fatal | dependency | Missing NetCDF library at runtime |
| dt_018 | silent | initialization | finidat from wrong resolution |
| dt_019 | degraded | runtime | History file disk quota exceeded |
| dt_020 | silent | unit_conversion | Runoff units wrong in coupling |

---

## 15. Quick Start (on a supported machine)

```bash
# 1. Clone E3SM
git clone --recursive https://github.com/E3SM-Project/E3SM.git
cd E3SM

# 2. Create a land-only case with satellite phenology (fastest)
cd cime/scripts
./create_newcase --case ../../elm_test \
    --compset IELM \
    --res ne4pg2_ne4pg2 \
    --mach <YOUR_MACHINE>

# 3. Configure
cd ../../elm_test
./case.setup

# 4. Customize namelist (optional)
cat >> user_nl_elm << 'EOF'
hist_nhtfrq = 0
hist_mfilt = 12
hist_fincl1 = 'GPP','NPP','QRUNOFF','FSH','EFLX_LH_TOT'
EOF

# 5. Build
./case.build

# 6. Submit
./case.submit

# 7. Monitor
tail -f CaseStatus

# 8. Find output
./xmlquery DOUT_S_ROOT
ls $(./xmlquery --value DOUT_S_ROOT)/lnd/hist/
```

---

## 16. File Structure

```
ki/
├── SKILL.md                           # This file — agent entry point
├── knowledge_infrastructure.yaml      # Schema-compliant package definition
├── tools/
│   ├── convert_forcing_to_elm.py      # s2: Atmospheric forcing converter
│   ├── convert_surface_data.py        # s1: Surface/soil data converter
│   ├── run_elm.py                     # s6: Execution wrapper
│   └── parse_elm_output.py            # s7: Output NetCDF → CSV parser
├── docs/
│   ├── s0_configuration.md            # Environment and installation
│   ├── s1_surface_data.md             # Surface dataset preparation
│   ├── s2_forcing_data.md             # Atmospheric forcing preparation
│   ├── s3_namelist_setup.md           # Namelist configuration
│   ├── s4_initial_conditions.md       # Initial conditions and spin-up
│   ├── s6_execution.md               # Running the model
│   └── s7_output_analysis.md          # Analyzing model output
├── diagnostics/
│   └── triplets.yaml                  # 20 symptom→diagnosis→remedy entries
└── workflow/
    └── workflow.md                    # Pipeline workflow description
```
