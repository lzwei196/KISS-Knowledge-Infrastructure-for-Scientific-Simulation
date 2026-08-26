---
name: classic
description: >-
  CLASSIC v1.0. Covers Surface exchange of energy, momentum, and water between atmosphere
  and land (CLASS physics); Multi-layer soil temperature and liquid/frozen soil moisture
  dynamics; Snowpack accumulation, melt, density, albedo (single-layer representation);
  Vegetation canopy interception, radiation cascade, and evapotranspiration; Surface
  ponding. Use when the task involves running, configuring, calibrating or interpreting
  CLASSIC.
---

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

# CLASSIC (Canadian Land Surface Scheme Including Biogeochemical Cycles) — Knowledge Infrastructure

**Package**: `hydrocraft-classic-biogeochem` v1.0.0
**Model**: CLASSIC (CLASS v3.6.2 + CTEM v2.0)
**Created by**: Knowledge Dissection Toolkit
**Last updated**: 2026-03-26
**Stats**: 4 tools | 5 skill documents | 18 diagnostic triplets | ~2,000 lines of validated Python
**Validation status**: `dissected`

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for CMFD unit documentation and known traps.
See `data_ki/FLUXNET/SKILL.md` for eddy covariance flux observations.


## Overview

This knowledge infrastructure enables simulation of land surface energy, water, and biogeochemical (carbon) cycles using the CLASSIC model. CLASSIC integrates the Canadian Land Surface Scheme (CLASS) for physics (energy/water balances of soil, snow, vegetation) with the Canadian Terrestrial Ecosystem Model (CTEM) for biogeochemistry (carbon pools, photosynthesis, respiration, phenology, disturbance).

**What CLASSIC does**: Coupled land surface physics + terrestrial carbon cycle model. Simulates:
- Energy balance: net radiation, sensible/latent heat flux, ground heat flux
- Water balance: precipitation partitioning, canopy interception, infiltration, runoff, baseflow, snow accumulation/melt, soil moisture
- Snow: mass, temperature, density, albedo, liquid water content
- Vegetation canopy: temperature, intercepted water, phenology (LAI cycle)
- Biogeochemistry (CTEM): photosynthesis (GPP), autotrophic/heterotrophic respiration, carbon allocation to leaves/stems/roots, litter/soil carbon dynamics
- Disturbance: fire (ignition, spread, emissions), mortality, land use change
- Methane: wetland CH4 emissions, soil CH4 uptake
- PFT competition: dynamic vegetation composition

**Key difference from hydrological models**: CLASSIC is a land surface model (energy + water + carbon), not a rainfall-runoff model. It can be run at a single point or over a global grid. Runoff is a diagnostic output, not the primary target. The primary outputs are surface fluxes (energy, water, carbon) exchanged with the atmosphere.

---

## Installation

### Binary

```
CLASSIC serial:  bin/CLASSIC_serial
Compiler:        gfortran (GNU Fortran)
Platform:        Linux x86-64
Source:          github.com/zshigrit/classic (or gitlab.com/cccma/classic)
```

### Dependencies

```
gfortran, make, libnetcdff-dev, netcdf-bin, zlib1g
Optional (parallel): mpich or openmpi, mpif90
```

### Build (serial mode — default)

```bash
cd /path/to/classic
make              # produces bin/CLASSIC_serial
# or explicitly:
make mode=serial  # produces bin/CLASSIC_serial
```

### Build (parallel mode)

```bash
make mode=parallel  # produces bin/CLASSIC_parallel (requires mpif90 + parallel netCDF)
```

### Test run

```bash
bin/CLASSIC_serial configurationFiles/template_job_options_file.txt 0/0
```

---

## Execution Pattern

### Point simulation (single grid cell)

```bash
bin/CLASSIC_serial <job_options_file> <longitude>/<latitude>
# Example:
bin/CLASSIC_serial configurationFiles/template_job_options_file.txt 105.23/40.91
# Whole domain shorthand:
bin/CLASSIC_serial configurationFiles/template_job_options_file.txt 0/0
```

### Grid simulation (regional/global, parallel)

```bash
mpirun -np <cores> bin/CLASSIC_parallel <job_options_file> <Wlon>/<Elon>/<Slat>/<Nlat>
# Example:
mpirun -np 4 bin/CLASSIC_parallel configurationFiles/template_job_options_file.txt 90.5/105.5/30.4/45.5
# Whole domain shorthand:
mpirun -np 4 bin/CLASSIC_parallel configurationFiles/template_job_options_file.txt 0/0/0/0
```

---

## Pipeline (7 stages)

| # | Stage | Tool(s) | Description |
|---|-------|---------|-------------|
| 0 | Configuration | (manual) | Site selection, period, CTEM on/off, fire/LUC switches |
| 1 | Met forcing | `convert_forcing_to_classic` | Convert global reanalysis to CLASSIC netCDF (unit conversions) |
| 2 | Soil/init file | `convert_soil_to_classic` | Build initialization netCDF from HWSD/GSDE + vegetation params |
| 3 | Parameters | (template) | Select run_parameters namelist (9 PFTs, peatlands, shrubs) |
| 4 | Job options | (edit template) | Configure job_options_file.txt (paths, switches, output) |
| 5 | Execution | `run_classic` | Compile and run CLASSIC with preflight checks |
| 6 | Output analysis | `parse_classic_output` | Extract netCDF outputs to CSV, compute diagnostics |

### Parallelism

Stages 1 and 2 can run in parallel (independent input preparation).
Stage 3-4 depend on 1-2 (paths must be set).
Stage 5 depends on 3-4.
Stage 6 depends on 5.

---

## Input File Formats

All inputs are **netCDF-4 format**. For parallel runs, files must be properly **chunked** (all timesteps for a grid cell in one chunk).

### Meteorological forcing (7 required files, one variable per file)

| Variable | File convention | Units | Description |
|----------|----------------|-------|-------------|
| FSS | dswrf*.nc | W m-2 | Downwelling shortwave radiation |
| FDL | dlwrf*.nc | W m-2 | Downwelling longwave radiation |
| PRE | pre*.nc | kg m-2 s-1 | Precipitation rate |
| TA | tmp*.nc | **deg C** (driver expects C, internal uses K) | Air temperature at reference height |
| QA | spfh*.nc | kg kg-1 | Specific humidity at reference height |
| VMOD | wind*.nc | m s-1 | Wind speed at reference height |
| PRES | pres*.nc | Pa | Surface air pressure |

**CRITICAL**: Time encoding is `"day as %Y%m%d.%f"` (e.g., 19010101.0 = midnight Jan 1, 1901). This is **not** standard CF-convention "days since" — it is an absolute date encoding.

**CRITICAL**: Temperature must be in **degrees Celsius** in the forcing file. The model converts to Kelvin internally.

**CRITICAL**: Meteorology must start at timestep 0 minutes, 0 hours, day 1.

### Initialization file (single netCDF)

Dimensions: `tile, lat, lon, layer, ic, icc, icp1, iccp1, iccp2, months, slope`

Key variables:
- Soil: SAND(%), CLAY(%), ORGM(%), SDEP(m), DRN, SOCI
- Vegetation (CLASS): FCAN, ALVC, ALIC, CMAS, LNZ0, PAMN, PAMX, ROOT (per `icp1`)
- Vegetation (CTEM): fcancmx (per `icc`)
- Prognostic: TBAR(K), THLQ(m3/m3), THIC(m3/m3), SNO(kg/m2), TSNO(K), ALBS, RHOS(kg/m3)
- Carbon: gleafmas, bleafmas, rootmass, stemmass, litrmass, soilcmas (kgC/m2)
- Grid: grclarea(km2), GC(-1 for land), FARE, MID, DELZ(m)

### GHG files

- CO2: Annual, variable name flexible, units **ppmv**, time as `"day as %Y%m%d.%f"`
- CH4: Annual, same format as CO2, units **ppmv**

### Other optional inputs

- Population density (POPD): Annual, people/km2
- Lightning (LGHT): Daily, strikes km-2 yr-1
- Land use change (LUC): Annual, PFT fractions
- Observed wetland fraction (OBSWETF): Daily, fraction

---

## Output Format

Outputs are **netCDF-4**, organized by temporal resolution:
- **Annual**: always produced (e.g., `outputFiles/*_yr.nc`)
- **Monthly**: controlled by `domonthoutput`, start year `JMOSTY`
- **Daily**: controlled by `dodayoutput`, date range `JDSTD`-`JDENDD`, `JDSTY`-`JDENDY`
- **Half-hourly**: controlled by `dohhoutput`, date range `JHHSTD`-`JHHENDD`, `JHHSTY`-`JHHENDY`

### Key output variables

| Short name | Long name | Units | Category |
|-----------|-----------|-------|----------|
| rss | Net shortwave radiation | W/m2 | Energy |
| rls | Net longwave radiation | W/m2 | Energy |
| hfss | Sensible heat flux | W/m2 | Energy |
| hfls | Latent heat flux | W/m2 | Energy |
| gpp | Gross primary productivity | kgC/m2/s or kgC/m2/month | Carbon |
| npp | Net primary productivity | kgC/m2/s or kgC/m2/month | Carbon |
| nep | Net ecosystem productivity | kgC/m2/s or kgC/m2/month | Carbon |
| nbp | Net biome productivity | kgC/m2/s or kgC/m2/month | Carbon |
| rh | Heterotrophic respiration | kgC/m2/s | Carbon |
| ra | Autotrophic respiration | kgC/m2/s | Carbon |
| mrro | Total runoff | kg/m2/s | Water |
| mrros | Surface runoff | kg/m2/s | Water |
| evspsbl | Evapotranspiration | kg/m2/s | Water |
| snw | Snow water equivalent | kg/m2 | Snow |
| lai | Leaf area index | m2/m2 | Vegetation |

Output variable metadata is defined in `configurationFiles/outputVariableDescriptors.xml`.

---

## Unit Trap Table

These are the most dangerous unit conversion errors when preparing CLASSIC inputs:

| Variable | Common source units | CLASSIC expected | Conversion | Trap severity |
|----------|-------------------|-----------------|------------|---------------|
| Temperature (TA) | K (Kelvin) | **deg C** | T_C = T_K - 273.15 | **CRITICAL** — model crashes or produces wrong energy balance |
| Precipitation (PRE) | mm/hr, mm/day, mm/3hr | **kg m-2 s-1** | mm/hr / 3600, mm/day / 86400 | **CRITICAL** — 1000x error in water balance |
| Specific humidity (QA) | g/kg | **kg/kg** | g/kg / 1000 | **CRITICAL** — huge evaporation error |
| Pressure (PRES) | hPa, kPa | **Pa** | hPa * 100, kPa * 1000 | **HIGH** — wrong atmospheric density |
| Shortwave (FSS) | — | **W/m2** | Clip to >= 0 | MEDIUM — negative SW causes numerical issues |
| Longwave (FDL) | — | **W/m2** | Must be > 0 | MEDIUM |
| Wind (VMOD) | — | **m/s** | Common, usually correct | LOW |
| Time encoding | CF "days since" | **"day as %Y%m%d.%f"** | Complete rewrite needed | **CRITICAL** — model reads wrong dates |
| Soil SAND | 0-1 fraction | **%** (0-100) | fraction * 100 | HIGH — wrong soil hydraulic properties |
| Soil depth (SDEP) | cm | **m** | cm / 100 | HIGH — wrong soil column |
| Carbon pools | gC/m2 | **kgC/m2** | gC/m2 / 1000 | HIGH — wrong C stocks |
| Grid cell area | m2, ha | **km2** | m2/1e6, ha/100 | MEDIUM — wrong fire/LUC calculations |
| Snow mass (SNO) | mm SWE | **kg/m2** | 1 mm SWE = 1 kg/m2 (identity) | LOW |
| Layer thickness (DELZ) | cm | **m** | cm / 100 | HIGH — wrong thermal conductivity |
| Rooting depth (ROOT) | cm | **m** | cm / 100 | MEDIUM |

---

## Tools Reference

| Tool | Stage | Script Path | Purpose |
|------|-------|-------------|---------|
| `convert_forcing_to_classic` | s1 | `tools/convert_forcing_to_classic.py` | Convert CRU-JRA/ERA5/CMFD reanalysis to CLASSIC met netCDF |
| `convert_soil_to_classic` | s2 | `tools/convert_soil_to_classic.py` | Build initialization netCDF from HWSD/GSDE soil data |
| `run_classic` | s5 | `tools/run_classic.py` | Compile and execute CLASSIC with validation |
| `parse_classic_output` | s6 | `tools/parse_classic_output.py` | Extract CLASSIC netCDF output to CSV/DataFrame |

---

## Configuration Files

### Job options file (`configurationFiles/template_job_options_file.txt`)

Fortran namelist `&joboptions` controlling:
- Meteorological options: `readMetStartYear`, `readMetEndYear`, `metLoop`, `leap`
- Met file paths: `metFileFss`, `metFileFdl`, `metFilePre`, `metFileTa`, `metFileQa`, `metFileUv`, `metFilePres`
- Init/restart: `init_file`, `rs_file_to_overwrite`
- Parameters: `runparams_file`
- CTEM switches: `ctem_on`, `spinfast`
- CO2/CH4: `transientCO2`, `CO2File`, `fixedYearCO2`, etc.
- Fire: `dofire`, `transientPOPD`, `POPDFile`, `transientLGHT`, `LGHTFile`
- Competition: `PFTCompetition`, `inibioclim`, `start_bare`
- Land use: `lnduseon`, `LUCFile`, `fixedYearLUC`
- Physics: `IDISP`, `IZREF`, `ZRFH`, `ZRFM`, `ZBLD`, `ISLFD`, `IPCP`, `IWF`, `isnoalb`
- Iteration: `ITC`, `ITCG`, `ITG` (use 1=bisection, NOT 2=Newton-Raphson)
- Output: `output_directory`, `xmlFile`, temporal controls

### Run parameters file (`configurationFiles/template_run_parameters.txt`)

Fortran namelist with PFT-specific parameters:
- `ican`: Number of CLASS PFTs (typically 4: NdlTr, BdlTr, Crops, Grass)
- `icc`: Number of CTEM PFTs (typically 9)
- `l2max`: Max CTEM PFTs per CLASS PFT (typically 3)
- PFT-specific physiological parameters

### Output variable descriptors (`configurationFiles/outputVariableDescriptors.xml`)

XML file defining all possible output variables, their names, units, and temporal variants.

---

## Plant Functional Types (PFTs)

### Standard 9-PFT configuration

| CLASS PFT | CTEM PFTs |
|-----------|-----------|
| Needleleaf tree (NdlTr) | Evergreen (NdlEvgTr), Deciduous (NdlDcdTr) |
| Broadleaf tree (BdlTr) | Evergreen (BdlEvgTr), Cold Deciduous (BdlDCoTr), Drought Deciduous (BdlDDrTr) |
| Crop (Crops) | C3 (CropC3), C4 (CropC4) |
| Grass (Grass) | C3 (GrassC3), C4 (GrassC4) |

### Peatland configuration (12 PFTs)

Adds: Evergreen Shrubs (BdlEvgSh), Deciduous Shrubs (BdlDCoSh), Sedges (Sedge)

### Shrubs configuration (10+ PFTs)

Adds: Broadleaf shrub as separate CLASS PFT with Evergreen/Deciduous CTEM sub-PFTs

---

## Soil Configuration

- Texture: SAND(%), CLAY(%), ORGM(%) per layer — residual is silt
- Special SAND flags: -2 = peat, -3 = bedrock, -4 = ice sheet
- Layer thickness (DELZ): any number of layers, minimum ~0.10 m each (explicit scheme stability)
- Permeable depth (SDEP): depth to bedrock in meters
- Drainage index (DRN): 0.005 typical, 0 for bogs, 1 for free draining
- Soil colour index (SOCI): 1-20 (1=bright, 20=dark), controls bare soil albedo

---

## Physics Settings for Field Data vs. GCM

| Setting | Field data | GCM/reanalysis |
|---------|-----------|----------------|
| IDISP | 1 (include displacement height) | 0 (terrain-following) |
| IZREF | 1 (surface = ground) | 2 (surface = roughness length) |
| ZRFH | Measurement height (m) | Model lowest level height |
| ZRFM | Measurement height (m) | Model lowest level height |
| ZBLD | 50 m (default) | 50 m (default) |
| ISLFD | 0 or 2 (2 if ZRFH != ZRFM) | 0 or 2 |
| IPCP | 1 (0C cutoff) | 1-3 (scheme choice) |

---

## Spin-up Protocol

1. **Physics spin-up**: Run with `ctem_on = .false.` for several decades to equilibrate soil temperatures and moisture
2. **Carbon spin-up**: Run with `ctem_on = .true.`, `spinfast = 5-10` (accelerated soil C), cycle meteorology (`metLoop > 1`) for centuries
3. **Transition**: Set `spinfast = 1` for final spin-up decade and transient runs
4. **Restart**: Copy init_file to rs_file_to_overwrite; model overwrites prognostic variables in restart file

**Tip**: Start simulations in snow-free conditions (initialize SNO, TSNO, ALBS, RHOS, WSNO to zero) to avoid persistent snow biases.

---

## Key Source Files

| File | Purpose |
|------|---------|
| `src/CLASSIC.F90` | Top-level driver, MPI initialization |
| `src/main.f90` | Main time stepping loop, calls physics and biogeochemistry |
| `src/modelStateDrivers.f90` | I/O: read init files, write restart, read met |
| `src/readFromJobOptions.f90` | Parse job options namelist |
| `src/metModule.f90` | Meteorological data handling, timezone adjustment |
| `src/energyBudgetDriver.f90` | Surface energy balance driver |
| `src/waterBudgetDriver.f90` | Water budget driver |
| `src/ctemDriver.f90` | CTEM biogeochemistry driver |
| `src/photosynCanopyConduct.f90` | Photosynthesis and canopy conductance |
| `src/heterotrophicRespirationMod.f90` | Soil/litter respiration |
| `src/phenolgy.f90` | Leaf phenology (onset, fall) |
| `src/disturb.f90` | Fire disturbance |
| `src/competitionMod.f90` | PFT competition for space |
| `src/landuseChangeMod.f90` | Land use change effects |
| `src/outputManager.f90` | NetCDF output writing |
| `src/prepareOutputs.f90` | Accumulate/average outputs at each time step |
| `src/soilProperties.f90` | Soil thermal/hydraulic properties from texture |
| `src/calcLandSurfParams.f90` | Vegetation structural parameters |
| `src/classGatherScatter.f90` | Gather/scatter for vectorized computation |
| `src/xmlParser.f90` / `xmlManager.f90` | Parse output variable XML |
