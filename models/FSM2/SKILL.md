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
| on ANY error, before debugging | `diagnostics/triplets.yaml` (25 entries) | symptom → diagnosis → remedy for this model's known failure modes. Check here FIRST; the answer usually exists. Never renumber or rewrite entries. |
| to know what an output IS | `dag.yaml` | the model's identity: every output's medium, units, `validation_rank` (1 = the headline variable) and observability. Scoring and obs-binding read THIS — when asked 'what does this model predict', the dag is the answer, not a guess. |
| when building inputs / parsing outputs | `docs/format_spec.yaml` | exact I/O shapes + `known_issues`, projected from dag + triplets. Regenerate with `ki_tools_common/generate_format_spec.py` after changing either — never hand-edit. |
| to judge a run's skill | `docs/validation_convention.yaml` | how this model's field judges it validated: per-`dag_variable` metrics, directions and CITED pass-bands. A run is graded against these, not against intuition. |
| for claims and thresholds | `docs/gathered_papers.json` (19 papers) + `docs/papers_index.md` | the literature this KI is judged by; each entry's `text_path` is fetched full text in the central paper cache. `role: benchmark` marks the model's own skill paper. |
| for a machine-readable summary | `knowledge_infrastructure.yaml` | the manifest (package, pipeline, validation tier, counts) — projected by `ki_tools_common/generate_ki_manifest.py`; regenerate after structural changes, never hand-edit. |
| what past runs learned | `.kdt_evolution.jsonl` | append-only memory of previous runs and fixes on this KI. |

*Projected 2026-08-23 from the KI's actual contents — 9 components present. Refresh: `python3 ki_tools_common/generate_skill_map.py --ki_dir <this KI>`.*
<!-- KI-MAP:END -->

<!-- KI-TOOL-INDEX:BEGIN (projected by generate_skill_map.py — the discoverability contract: every public tool, exact path; PURPOSE stays human-authored elsewhere) -->
### Executable tool index (projected — complete by construction)

Every public tool in this KI, by exact path. What each is FOR lives in the
human-written Tool Inventory above; `--help` on any of these prints its arguments.

| tool (exact path) | invocation |
|---|---|
| `tools/convert_forcing_to_fsm2.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_forcing_to_fsm2.py --help` |
| `tools/convert_soil_params.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/convert_soil_params.py --help` |
| `tools/parse_fsm2_output.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/parse_fsm2_output.py --help` |
| `tools/run_fsm2.py` | `KISSPATH_PYTHON_ENV/bin/python {KI}/tools/run_fsm2.py --help` |

*4 public tools; `_`-prefixed helpers and packaging files excluded.*
<!-- KI-TOOL-INDEX:END -->

# FSM2 v2.1.2 (Flexible Snow Model) — Knowledge Infrastructure

**Package**: `hydrocraft-fsm2-snow` v1.0.0
**Model**: FSM2 v2.1.2 — Flexible Snow Model
**Domain**: Cryosphere (snow accumulation, melt, forest canopy snow processes)
**Author**: Richard Essery, School of GeoSciences, University of Edinburgh
**Last updated**: 2026-03-26
**Stats**: 4 tools | 5 skill documents | 15+ diagnostic triplets
**Validation status**: `example_validated` (Alptal, Switzerland, 2004-2005)

---

## Data Preparation

### Forcing data

**Data Sources**: FSM2 is an energy-balance model and needs SUB-DAILY forcing, so
use `from ki_tools_common.load_forcing import load_hourly_forcing`, not the daily
loader:

```python
from ki_tools_common.load_forcing import load_hourly_forcing
d = load_hourly_forcing("nasa_power", lat, lon, 2001, 2019)   # hourly, global
# d: dates, srad_wm2, lrad_wm2, precip_mm (mm per step), temp_c, shum_kgkg,
#    wind_ms (10 m), wind2_ms (2 m), wind_height_m, pres_pa, timestep_seconds
```

- `nasa_power` — hourly, global, **starts 2001-01-01**. The only practical point
  source for a multi-year FSM2 run outside China. Set the namelist `zU` to the
  returned `wind_height_m` (see triplet T21 for why WS2M is not usable).
- `cmfd` / `mswx` — 3-hourly gridded (set `dt = 10800`). Extracting ONE point out
  of MSWX is impractically slow: the annual files are chunked `(1, 1800, 3600)`
  with gzip, so a single cell-year forces ~76 GB of decompression. Use them only
  when you need whole fields, and read them with `engine='h5netcdf'` (triplet T23).

Neither source gives FSM2 what DRIV1D=1 asks for directly — all of them publish
specific humidity rather than RH, and total precipitation rather than separate
snowfall and rainfall. `tools/convert_forcing_to_fsm2.py --shum-col --precip-col`
closes both gaps using FSM2's own formulas (triplets T19, T20). **FSM2 does not
partition precipitation itself.**

**Observations**: the rank-1 binding is `snowcci_swe_nh` (ESA CCI Snow L3C daily
SWE v2.0) at `KISSPATH_DATA/benchmarks/snowcci_swe/` — 0.1° global lat/lon,
variable `swe` in **mm, which is kg m-2 1:1 with FSM2 `snw`**. Read triplet T24
before using it: negative values are flags, `0` is a real no-snow observation,
and the product only exists for the snow season (~215 files per year, no summer).
Point SWE records: `snotel` (US), `canswe_canada`, `canadian_snow_survey_historical`.


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

Read from stdin. Contains 7 Fortran namelist blocks, in this fixed order
(`&params`, `&gridpnts`, `&gridlevs`, `&drive`, `&veg`, `&initial`,
`&outputs`). An unwanted block is still written, empty — see triplet T06.

```fortran
&params       ! Model parameters (override the FSM2_PARAMS defaults)
  acn0 = 0.06
  avg0 = 0.142
  fcly = 0.04        ! soil clay fraction — from tools/convert_soil_params.py
  fsnd = 0.87        ! soil sand fraction
/
&gridpnts     ! Grid dimensions
  Npnts = 2   ! Number of simulation points
  Nsmax = 3   ! Max snow layers   (default 3; Dzsnow must match if changed)
  Nsoil = 4   ! Soil layers       (default 4; Dzsoil must match if changed)
/
&gridlevs     ! Layer configuration (usually defaults are fine)
  Dzsnow = 0.1, 0.2, 0.4              ! Nsmax min snow-layer thicknesses (m)
  Dzsoil = 0.1, 0.2, 0.4, 0.8         ! Nsoil soil-layer thicknesses (m)
  fvg1 = 0.5                          ! fraction of VAI in the upper canopy layer
  zsub = 1.5                          ! subcanopy diagnostic height (m)
/
&drive        ! Driving data configuration
  met_file = 'met_Alptal_0405.txt'
  dt = 3600          ! Timestep (s). Default 3600; MUST equal the forcing interval.
  lat = 47.05        ! Latitude (degrees, converted to radians internally)
  noon = 12          ! Hour of SOLAR noon, in the met file's OWN time base.
                     ! Only used when SWPART=1. For a met file stamped in UTC
                     ! this is 12 - lon/15, NOT 12 (e.g. 10.224 at 26.63 E).
  zT = 35            ! Temperature measurement height (m)
  zU = 35            ! Wind measurement height (m) — must match the height the
                     ! wind in the met file was actually measured/derived at
/
&veg          ! Vegetation characteristics (per point)
  alb0 = 0.15, 0.15  ! Snow-free ground albedo
  vegh = 0.00, 25.0  ! Canopy height (m)
  VAI  = 0.00, 3.96  ! Vegetation area index
  ! alb0_file / vegh_file / VAI_file read the same per-point arrays from a file
/
&initial      ! Initial conditions
  fsat = 0.5, 0.5, 0.5, 0.5           ! Nsoil initial soil moisture, FRACTION of Vsat
  Tprf = 285, 285, 285, 285           ! Nsoil initial soil temperatures (K).
                                      ! The 285 K default is a temperate value —
                                      ! set it near the site's annual mean ground
                                      ! temperature for cold-region runs.
  start_file = 'none'                 ! restart from a previous run's dump file
/
&outputs      ! Output configuration
  runid = 'Alptal_'  ! Prefix for output files
  dump_file = 'dump' ! End-of-run state dump, written as <runid><dump_file>.
                     ! Feed it back through &initial start_file to chain a
                     ! spin-up run into the evaluation run.
/
```

**70-character limit (triplet T22).** `met_file`, `runid`, `dump_file`,
`alb0_file`, `vegh_file` and `VAI_file` are all `character(len=70)`. A longer
absolute path is silently truncated and FSM2 then fails to open a file that
plainly exists. Keep the met file in the run directory and use a short relative
name.

**FSM2 writes output EVERY timestep** — there is no output-frequency control.
Aggregate to the observation's frequency yourself (e.g. daily mean `snw`)
after `parse_fsm2_output.py`.

---

## Output Format

## 6. Output Description

**Source of truth**: `dag.yaml`. If this section and `dag.yaml` ever disagree,
the dag wins.

**Headline output** (`validation_rank: 1`):

> `snw` — Snow water equivalent (SWE) (`kg m-2`)

The dag's rank-1 output is `var='snw'`, `unit='kg m-2'`,
`description='Snow water equivalent (SWE)'`.

| Output variable (dag `var`) | Rank | Unit | Description / role |
|-----------------------------|------|------|--------------------|
| `snw` | 1 | `kg m-2` | Snow water equivalent (SWE) |

Other dag outputs listed by `dag.yaml`: `snd`, `svg`, `Tsrf`, `Tsoil`, `Tveg`,
`Melt`, `Roff`, `subl`, `H`, `LE`, `LWout`, `SWout`, `LWsub`, `SWsub`, `Tsub`,
`Usub`.

The ASCII file layout below documents the model output files used by the parser.

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

## 8. Unit Conversion Table

Exact input and output shapes live in `docs/format_spec.yaml`, projected from the
dag and diagnostics. The model-ready units below restate this KI's documented
FSM2 ASCII interface and the unit traps already called out for this pipeline.

| Variable | Source / interface unit | Model unit | Conversion | Type |
|----------|-------------------------|------------|------------|------|
| `SW` | `W/m²` | `W/m²` | `x1` | multiplicative |
| `LW` | `W/m²` | `W/m²` | `x1` | multiplicative |
| `Sf` | `kg/m²/s` | `kg/m²/s` | `x1` | multiplicative |
| `Rf` | `kg/m²/s` | `kg/m²/s` | `x1` | multiplicative |
| `Ta` | `K` | `K` | `x1` | multiplicative |
| `RH` (`DRIV1D=1`) | `%` | `%` | `x1` | multiplicative |
| `Qa` (`DRIV1D=2`) | `kg/kg` | `kg/kg` | `x1` | multiplicative |
| `Ua` | `m/s` | `m/s` | `x1` | multiplicative |
| `Ps` | `Pa` | `Pa` | `x1` | multiplicative |
| `lat` in namelist | degrees | degrees | converted internally to radians | angular |
| `dt` | `s` | `s` | `x1` | multiplicative |
| `Dzsnow` | `m` | `m` | `x1` | multiplicative |
| `Dzsoil` | `m` | `m` | `x1` | multiplicative |
| `fcly`, `fsnd` | fraction `0-1` | fraction `0-1` | `x1` | multiplicative |

### 8c. Sign Conventions and Output Units

| Variable | Convention in this model | Common alternative | Impact if wrong |
|----------|--------------------------|--------------------|-----------------|
| `H` | `W/m²`, sensible heat flux positive upward | opposite sign convention | Energy-balance metrics can be sign-flipped |
| `LE` | `W/m²`, latent heat flux positive upward | opposite sign convention | Latent heat and sublimation interpretation can be reversed |
| `Melt` | `kg/m²/s`, surface melt rate | accumulated depth per timestep | Magnitude error if treated as an accumulation |
| `Roff` | `kg/m²/s`, runoff from snow | accumulated depth per timestep | Magnitude error if treated as an accumulation |
| `subl` | `kg/m²/s`, sublimation rate | accumulated depth per timestep | Magnitude error if treated as an accumulation |
| `LWout`, `SWout` | `W/m²`, outgoing radiation | incoming radiation sign convention | Radiation balance can be inverted |
| `snw` | `kg m-2`, snow water equivalent (SWE) | depth in m or mm without density conversion | Rank-1 validation target becomes incomparable |
| `snd` | `m`, snow depth | SWE mass loading | Snow-depth validation target becomes incomparable |
| `svg` | `kg/m²`, snow mass on vegetation | canopy water depth in mm | Canopy snow-storage comparison can be mis-scaled |

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

## 11. Validated Results

### Test Site: Alptal, Switzerland

| Property | Value |
|----------|-------|
| Validation status | `example_validated` |
| Site | Alptal, Switzerland |
| Period | 2004-2005 |
| Headline dag variable | `snw` |
| Headline unit | `kg m-2` |
| Headline description | Snow water equivalent (SWE) |

### Performance Metrics -- judged against the field's bar, not intuition

**Source of truth**: `docs/validation_convention.yaml`. Null convention bands are
reported as `no cited threshold`; no threshold is inferred or substituted.

| Dag variable | Metric | Direction | Satisfactory band | Good band | Very good band | Citation keys |
|--------------|--------|-----------|-------------------|-----------|----------------|---------------|
| `snw` | `nse` | maximize | `0.0` | `0.64` | no cited threshold | `krinner2018`, `bams2021` |
| `snw` | `nrmse` | minimize | `1.0` | `0.6` | no cited threshold | `krinner2018`, `bams2021` |
| `snd` | `rmse` | minimize | `0.21` | `0.14` | no cited threshold | `mazzotti2020` |
| `snd` | `kge` | maximize | `0.54` | `0.54` | `0.8` | `mazzotti2020` |
| `svg` | `nse` | maximize | no cited threshold | no cited threshold | no cited threshold | none listed in convention |

### Data Replacement Tracking

| Component | Source | Status | Notes |
|-----------|--------|--------|-------|
| Forcing | Pipeline | documented | `convert_forcing_to_fsm2.py` prepares FSM2 ASCII meteorological forcing |
| Soil | Pipeline | documented | `convert_soil_params.py` derives FSM2 soil parameters from HWSD clay/sand inputs |
| Output parsing | Pipeline | documented | `parse_fsm2_output.py` parses ASCII output to CSV with headers |

## Tool Reference

| Tool | Purpose | Input | Output |
|------|---------|-------|--------|
| `convert_forcing_to_fsm2.py` | Convert ERA5/MSWX/NASA POWER/generic CSV → FSM2 met file | CSV with met variables | FSM2 ASCII met file |
| `convert_soil_params.py` | Derive FSM2 soil params from HWSD clay/sand | `--latlon LAT LON` (HWSD raster), `--fractions`, or `--texture` | Namelist &params block |
| `run_fsm2.py` | Compile and execute FSM2 | Source dir + namelist | Output files + binary |
| `parse_fsm2_output.py` | Parse ASCII output → CSV | FSM2 output files | CSV with headers |

**`convert_forcing_to_fsm2.py` derivations** (added 2026-08-21; without them the
documented "reanalysis → FSM2" recipe cannot be completed with KI tools alone):

```bash
python tools/convert_forcing_to_fsm2.py forcing.csv run/met.txt \
    --shum-col Qa      # RH derived from SPECIFIC humidity with FSM2's own
                       # saturation formula, so q -> RH -> q is EXACT (T20)
    --precip-col Pr    # Sf/Rf split from TOTAL precipitation with FSM2's own
                       # ramp: all snow <= 0 degC, all rain >= +2 degC (T19)
```
The `hour` column is written with 3 decimals, not rounded, so a half-hour
interval centre (0.5, 1.5, …) survives into `SOLARPOS` when `SWPART=1`.

**`run_fsm2.compile_fsm2` mutates the source tree** — it overwrites `src/OPTS.h`
and drops the binary in the repo root. Copy `source/repo/src` into the run's own
work directory and compile there, or every other FSM2 run on the machine silently
inherits your physics options.

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


## Forcing a point column from a reanalysis grid cell (PROPOSED protocol)

This protocol was MOVED to the waiting room pending validation — see
`docs/proposed_protocols.yaml` (id: pp_fsm2_esm_snowmip_forcing). Status: PROPOSED,
not validated by a clean run. The supporting tools (`--precip-scale`,
`--phase-logistic` on `tools/convert_forcing_to_fsm2.py`) are reviewer-approved and
inert by default; using them means following an UNPROVEN protocol — say so in your
report. Graduates back into this SKILL on one route='accept' run at a point-support
obs, or a second independent witness.
