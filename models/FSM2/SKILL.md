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

# FSM2 v2.1.2 (Flexible Snow Model) — Knowledge Infrastructure

**Package**: `hydrocraft-fsm2-snow` v1.0.0
**Model**: FSM2 v2.1.2 — Flexible Snow Model
**Domain**: Cryosphere (snow accumulation, melt, forest canopy snow processes)
**Author**: Richard Essery, School of GeoSciences, University of Edinburgh
**Last updated**: 2026-03-26
**Stats**: 4 tools | 5 skill documents | 15+ diagnostic triplets
**Validation status**: `example_validated` (Alptal, Switzerland, 2004-2005)

---

## Overview

This knowledge infrastructure enables autonomous simulation of snow accumulation and
melt using FSM2 (Flexible Snow Model), a multi-physics energy balance model. FSM2
extends the Factorial Snow Model (FSM; Essery, 2015) with forest canopy options and
multi-point capability. Physics options are selected at **compile time** via C
preprocessor defines, making it a "factorial" model — each combination of options
produces a distinct model configuration.

**What FSM2 does**:
- Multi-layer snowpack energy and mass balance
- Prognostic/diagnostic snow albedo
- Snow density evolution (fixed, age-compaction, overburden)
- Snow grain growth (temperature-dependent or temperature-gradient)
- Snow cover fraction parameterizations
- Canopy snow interception, unloading, and melt drip
- 1- or 2-layer forest canopy radiative transfer (Beer-Lambert or two-stream)
- Multi-layer soil heat conduction with freeze/thaw
- Snow hydraulics (free-draining, bucket, gravitational drainage)
- Turbulent exchange (neutral or stability-corrected)
- Solar position and SW partitioning (diffuse/direct)
- NetCDF or ASCII text output
- Multi-point simulations (ASCII mode)

**Key difference from other cryosphere models**: FSM2 is compile-time configurable
with 11 binary/ternary physics switches, allowing factorial experiments across
hundreds of model configurations from the same source code.

---

## Installation

### Build from Source

```bash
# Prerequisites: gfortran (GCC Fortran compiler)
# Optional: libnetcdff-dev for NetCDF output

cd /path/to/FSM2/source/repo

# ASCII output build (default)
bash compil.sh          # produces ./FSM2

# NetCDF output build
bash compil_nc.sh       # produces ./FSM2 (requires netCDF-Fortran)
```

### Binary
```
FSM2 executable:  ./FSM2      (produced by compil.sh)
Source:           src/*.F90   (22 Fortran source files)
Compiler:         gfortran with -cpp -O3 flags
```

### Dependencies
```
gfortran          (required)
libnetcdff        (optional, for NetCDF output: PROFNC=1)
```

---

## Pipeline (7 stages)

| # | Stage | Tool(s) | Description |
|---|-------|---------|-------------|
| 1 | Configuration | (manual/namelist) | Select physics options in compil.sh |
| 2 | Met forcing | `convert_forcing_to_fsm2` | Convert global reanalysis → FSM2 ASCII format |
| 3 | Soil/site params | `convert_soil_params` | Derive soil properties from HWSD clay/sand fractions |
| 4 | Compilation | `compile_fsm2` | Build FSM2 binary with selected physics options |
| 5 | Namelist setup | (manual/tool) | Create namelist file with &params, &gridpnts, etc. |
| 6 | Execution | `run_fsm2` | Run FSM2 with forcing and namelist |
| 7 | Output parsing | `parse_fsm2_output` | Extract ASCII output to CSV with headers |

---

## Compile-Time Physics Options (OPTS.h)

These are the preprocessor defines set in compil.sh before compilation:

| Option | Values | Description |
|--------|--------|-------------|
| `ALBEDO` | 1, 2 | Snow albedo: 1=diagnostic, 2=prognostic (decay+refresh) |
| `CANINT` | 1, 2 | Canopy interception: 1=linear, 2=exponential saturation |
| `CANMOD` | 1, 2 | Forest canopy layers: 1=single layer, 2=two layers |
| `CANRAD` | 1, 2 | Canopy radiation: 1=Beer-Lambert, 2=two-stream |
| `CANUNL` | 1, 2 | Canopy unloading: 1=exponential+melt, 2=temp+wind driven |
| `CONDCT` | 0, 1 | Snow conductivity: 0=fixed (kfix), 1=density-dependent |
| `DENSTY` | 0, 1, 2 | Snow density: 0=fixed, 1=age-compaction, 2=overburden |
| `EXCHNG` | 0, 1 | Turbulent exchange: 0=neutral, 1=stability-corrected |
| `HYDROL` | 0, 1, 2 | Snow hydrology: 0=free-drain, 1=bucket, 2=gravitational |
| `SGRAIN` | 1, 2 | Grain growth: 1=temperature, 2=temperature-gradient |
| `SNFRAC` | 1, 2, 3 | Snow cover fraction: 1=linear, 2=tanh, 3=asymptotic |

### Driving Data Options

| Option | Values | Description |
|--------|--------|-------------|
| `DRIV1D` | 1, 2 | Format: 1=FSM native, 2=ESM-SnowMIP |
| `SWPART` | 0, 1 | SW partition: 0=all diffuse, 1=solar position split |
| `ZOFFST` | 0, 1 | Height offset: 0=none, 1=above canopy |

### Output Options

| Option | Values | Description |
|--------|--------|-------------|
| `PROFNC` | 0, 1 | Output: 0=ASCII text files, 1=NetCDF |

---

## Input Format

### Meteorological Driving Data (DRIV1D=1, FSM native)

Space-delimited ASCII file. One row per timestep (default: hourly, dt=3600s).

| Column | Variable | Unit | Description |
|--------|----------|------|-------------|
| 1 | year | - | Year (integer) |
| 2 | month | - | Month 1-12 (integer) |
| 3 | day | - | Day 1-31 (integer) |
| 4 | hour | - | Hour of day (real, e.g. 1.0, 2.0) |
| 5 | SW | W/m² | Incoming shortwave radiation |
| 6 | LW | W/m² | Incoming longwave radiation |
| 7 | Sf | kg/m²/s | Snowfall rate |
| 8 | Rf | kg/m²/s | Rainfall rate |
| 9 | Ta | K | Air temperature |
| 10 | RH | % | Relative humidity (0-100) |
| 11 | Ua | m/s | Wind speed |
| 12 | Ps | Pa | Surface air pressure |

### ESM-SnowMIP Format (DRIV1D=2)

| Column | Variable | Unit | Description |
|--------|----------|------|-------------|
| 1-4 | year,month,day,hour | - | Date/time |
| 5 | SW | W/m² | Incoming shortwave radiation |
| 6 | LW | W/m² | Incoming longwave radiation |
| 7 | Rf | kg/m²/s | Rainfall rate |
| 8 | Sf | kg/m²/s | Snowfall rate |
| 9 | Ta | K | Air temperature |
| 10 | Qa | kg/kg | Specific humidity |
| 11 | RH | % | Relative humidity |
| 12 | Ua | m/s | Wind speed |
| 13 | Ps | Pa | Surface air pressure |

**Note**: For DRIV1D=1, RH is converted to specific humidity internally. For
DRIV1D=2, specific humidity is read directly but RH is also read.

### Namelist File

Read from stdin. Contains 6 Fortran namelist blocks in order:

```fortran
&params       ! Model parameters (override defaults)
  acn0 = 0.06
  avg0 = 0.142
/
&gridpnts     ! Grid dimensions
  Npnts = 2   ! Number of simulation points
/
&gridlevs     ! Layer configuration (usually defaults are fine)
/
&drive        ! Driving data configuration
  met_file = 'met_Alptal_0405.txt'
  lat = 47.05        ! Latitude (degrees, converted to radians internally)
  zT = 35            ! Temperature measurement height (m)
  zU = 35            ! Wind measurement height (m)
/
&veg          ! Vegetation characteristics (per point)
  alb0 = 0.15, 0.15  ! Snow-free ground albedo
  vegh = 0.00, 25.0  ! Canopy height (m)
  VAI  = 0.00, 3.96  ! Vegetation area index
/
&initial      ! Initial conditions
/
&outputs      ! Output configuration
  runid = 'Alptal_'  ! Prefix for output files
/
```

---

## Output Format

### ASCII Output (PROFNC=0)

Three output files per run, with prefix `runid`:

**`{runid}flux.txt`** — Energy fluxes:
```
year month day hour  H  LE  LWout  Melt  Roff  subl  SWout
```
| Variable | Unit | Description |
|----------|------|-------------|
| H | W/m² | Sensible heat flux (positive upward) |
| LE | W/m² | Latent heat flux (positive upward) |
| LWout | W/m² | Outgoing longwave radiation |
| Melt | kg/m²/s | Surface melt rate |
| Roff | kg/m²/s | Runoff from snow |
| subl | kg/m²/s | Sublimation rate |
| SWout | W/m² | Outgoing shortwave radiation |

**`{runid}stat.txt`** — State variables:
```
year month day hour  snd  snw  svg  Tsoil(1:Nsoil)  Tsrf  Tveg(1:Ncnpy)
```
| Variable | Unit | Description |
|----------|------|-------------|
| snd | m | Snow depth |
| snw | kg/m² | Snow water equivalent (SWE) |
| svg | kg/m² | Snow mass on vegetation |
| Tsoil | K | Soil layer temperatures |
| Tsrf | K | Surface temperature |
| Tveg | K | Vegetation temperatures |

**`{runid}subc.txt`** — Subcanopy diagnostics:
```
year month day hour  LWsub  SWsub  Tsub  Usub
```

### Format specification
```fortran
100 format(3(i4),f8.3,*(e14.6))
```
- Date columns: 3 integers (i4) + 1 float (f8.3)
- Data columns: exponential notation (e14.6), space-separated

---

## Unit Trap Table

| Variable | WRONG unit | CORRECT unit | Symptom if wrong |
|----------|-----------|--------------|------------------|
| Ta | °C | K | Massive negative energy balance, no melt |
| Ps | hPa/kPa | Pa | Humidity conversion fails, specific humidity ~0 |
| RH | fraction 0-1 | percent 0-100 | Extremely dry atmosphere, no LW emission |
| Sf, Rf | mm/h or mm/day | kg/m²/s | Snow accumulation 3600x or 86400x too large |
| lat (namelist) | radians | degrees | Wrong solar zenith, bad SW partition |
| lat (internal) | degrees | radians | (internal conversion: lat_rad = pi/180 * lat_deg) |
| SW | - | W/m² | Must be ≥ 0 |
| LW | - | W/m² | Must be > 0 (typically 100-400) |
| Ua | - | m/s | Clamped to min 0.1 internally |
| vegh | - | m | If 0 → no canopy processes |
| VAI | - | dimensionless | If 0 → open site (no forest) |
| Dzsnow | - | m | Layer thickness, not cm |
| Dzsoil | - | m | Layer thickness, not cm |
| fcly, fsnd | - | fraction 0-1 | Clay + sand ≤ 1 |
| dt | - | s | Timestep in seconds (default 3600) |

---

## Key Parameters and Defaults

| Parameter | Default | Unit | Description |
|-----------|---------|------|-------------|
| asmn | 0.5 | - | Minimum snow albedo (melting) |
| asmx | 0.85 | - | Maximum snow albedo (fresh) |
| rhof | 100 | kg/m³ | Fresh snow density |
| hfsn | 0.1 | m | Snow cover fraction depth scale |
| kfix | 0.24 | W/m/K | Fixed snow thermal conductivity |
| z0sn | 0.001 | m | Snow roughness length |
| z0sf | 0.1 | m | Snow-free roughness length |
| fcly | 0.3 | fraction | Soil clay fraction |
| fsnd | 0.6 | fraction | Soil sand fraction |
| Wirr | 0.03 | fraction | Irreducible liquid water content |
| svai | 4.4 | kg/m² | Snow capacity per unit VAI |
| kext | 0.5 | - | Canopy light extinction coefficient |
| cvai | 3.6e4 | J/K/m² | Vegetation heat capacity per VAI |
| Nsmax | 3 | - | Maximum snow layers |
| Nsoil | 4 | - | Number of soil layers |
| Dzsnow | 0.1, 0.2, 0.4 | m | Min snow layer thicknesses |
| Dzsoil | 0.1, 0.2, 0.4, 0.8 | m | Soil layer thicknesses |

---

## Tool Reference

| Tool | Purpose | Input | Output |
|------|---------|-------|--------|
| `convert_forcing_to_fsm2.py` | Convert ERA5/MSWX/generic CSV → FSM2 met file | CSV with met variables | FSM2 ASCII met file |
| `convert_soil_params.py` | Derive FSM2 soil params from HWSD clay/sand | HWSD lookup or manual | Namelist &params block |
| `run_fsm2.py` | Compile and execute FSM2 | Source dir + namelist | Output files + binary |
| `parse_fsm2_output.py` | Parse ASCII output → CSV | FSM2 output files | CSV with headers |

---

## References

- Essery (2015). A Factorial Snowpack Model (FSM 1.0). *Geoscientific Model Development*, **8**, 3867-3876.
- Essery, Mazzotti, Barr, Jonas, Quaife and Rutter (2025). A Flexible Snow Model (FSM 2.1.1) including a forest canopy. *Geoscientific Model Development*, **18**, 3583-3605.
- Stähli and Gustafsson (2006). The role of snow interception in winter-time radiation processes of a coniferous sub-alpine forest. *Hydrological Processes*, **23**, 2498-2512.

---

## Quick Start

```bash
# 1. Build FSM2
cd /path/to/FSM2/source/repo
bash compil.sh

# 2. Run with example data
./FSM2 < nlst_Alptal.txt

# 3. View results
# Output files: Alptal_flux.txt, Alptal_stat.txt, Alptal_subc.txt
```
