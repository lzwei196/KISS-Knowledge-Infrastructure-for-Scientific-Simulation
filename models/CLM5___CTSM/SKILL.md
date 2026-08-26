---
name: clm5-ctsm
description: >-
  CLM5/CTSM (CTSM 5.4 framework; CLM4.5/CLM5.0/CLM6.0 selectable physics). Covers
  Terrestrial biogeophysics: surface radiation, surface energy balance, canopy and ground
  turbulent…; Soil and snow thermal dynamics (25 soil layers to ~8.5 m; up to 12 snow
  layers); Soil and snow hydrology: infiltration, soil moisture, surface/subsurface
  runoff, drainage. Use when the task involves running, configuring, calibrating or
  interpreting CLM5___CTSM.
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

# CLM5 / CTSM Knowledge Infrastructure

- **Package**: CLM5___CTSM Knowledge Infrastructure v1.0
- **Model**: Community Land Model 5 / Community Terrestrial Systems Model (CTSM 5.4)
- **Domain**: Biogeochemistry, Land Surface, Hydrology, Carbon-Nitrogen Cycling
- **Created**: 2026-03-26
- **Tools**: 4 Python scripts
- **Validation**: Documented

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.
For a FLUXNET tower site, drive the model with the tower's own meteorology via
`convert_forcing_to_clm.py --source fluxnet` (see §15).

**Data Validation Reference**: `data_ki/CMFD/SKILL.md` and `data_ki/FLUXNET/SKILL.md`
**DO NOT EXIST** — KDT 5.0 removed tools and docs from `data_ki/`. The live
sources are `ki_tools_common` (`KISSPATH_KI_TOOLS_COMMON/`)
and this KI's own `tools/`. FLUXNET2015 layout: one directory per site under
`KISSPATH_OBS/fluxnet/sites/<SITE_ID>/`, holding
`FULLSET_{HH|HR}.csv` (sub-daily), `FULLSET_DD.csv` (daily), `FULLSET_YY.csv`,
`AUXMETEO.csv`, `AUXNEE.csv`. Site coordinates / IGBP class / canopy height are
NOT in `site_catalog.csv` — they are in the BIF workbook
`raw_zips/FLX_AA-Flx_BIF_ALL_20200501.zip` (`LOCATION_LAT`, `LOCATION_LONG`,
`LOCATION_ELEV`, `IGBP`, `HEIGHTC` rows, per `SITE_ID`).


## 1. Overview

This knowledge infrastructure enables an AI agent to configure, execute, and
analyse the Community Land Model version 5 (CLM5), the land component of the
Community Earth System Model (CESM). CLM5 is maintained as part of the
Community Terrestrial Systems Model (CTSM) repository.

**What CLM5 / CTSM does:**

- Simulates terrestrial biogeophysics: radiation transfer, surface energy
  balance, soil temperature, and hydrology
- Models biogeochemistry: carbon and nitrogen cycling through vegetation,
  litter, and soil organic matter pools
- Represents vegetation dynamics including phenology (CN/BGC modes) and
  ecosystem demography (FATES mode)
- Simulates crop growth with prognostic crop calendars and management
  (irrigation, fertilisation, harvest) in CLM-Crop mode
- Calculates methane emissions from wetlands (ch4Mod)
- Represents fire effects on ecosystems (CNFireBaseMod)
- Provides urban climate modelling with the CLMU urban canyon model
- Couples to atmosphere via NUOPC or LILAC frameworks and to river
  routing via MOSART/mizuRoute
- Supports dynamic land-use and land-cover change via transient PFT
  datasets
- Performs nitrogen fixation and uptake via the FUN model

**Key difference from simpler land models:** CLM5 is a full-complexity Earth
System land model with 78+ PFT/CFT types, 25 soil layers to 8.5 m depth,
up to 12 snow layers, and integrated biogeochemistry. It requires CIME
infrastructure and parallel computing resources (MPI + NetCDF + ESMF).

---

## 2. Installation

### Binary / Source

CLM5 is compiled from Fortran source using the CIME build system. There is no
standalone binary distribution.

```
Source root: source/repo/
CTSM version: 5.4
Primary language: Fortran 2003+
Build system: CIME (CMake under the hood, CMake 3.10+)
```

### System Dependencies

| Dependency | Purpose | Required |
|---|---|---|
| Fortran compiler (gfortran/ifort/nvfortran) | Compile CLM5 source | Yes |
| C compiler (gcc/icc) | Shared code, CIME | Yes |
| MPI (OpenMPI/MPICH/Intel MPI) | Parallel execution | Yes |
| NetCDF-Fortran >= 4.7.4 | I/O for all data files | Yes |
| ESMF (Earth System Modeling Framework) | Coupling infrastructure | Yes |
| PIO (Parallel I/O) | Efficient parallel NetCDF | Yes |
| Python >= 3.8 | CIME scripts, tools | Yes |
| CMake >= 3.10 | Build system | Yes |
| LAPACK/BLAS | Linear algebra | Optional |
| pFUnit | Fortran unit testing | Optional |

### Python Dependencies (for tools)

```
numpy
pandas
xarray
netCDF4
matplotlib
pyyaml
```

### Typical CIME Workflow

```bash
# 1. Set environment
export CTSMROOT=/path/to/ctsm
export CIMEROOT=$CTSMROOT/cime

# 2. Create a new case
cd $CIMEROOT/scripts
./create_newcase --case /path/to/cases/test_I2000 \
    --res f09_g17 --compset I2000Clm60BgcCrop

# 3. Setup, build, submit
cd /path/to/cases/test_I2000
./case.setup
./case.build
./case.submit
```

---

## 3. Pipeline

| # | Stage | Tool(s) | Description |
|---|---|---|---|
| 0 | Configuration | (manual / CIME) | Set compset, resolution, machine |
| 1 | Surface Data | mksurfdata_esmf | Create surface dataset with PFT/soil/urban |
| 2 | Atmospheric Forcing | `convert_forcing_to_clm.py` | Convert global reanalysis to DATM streams |
| 3 | Soil Parameters | `convert_soil_params.py` | Map HWSD/SoilGrids to CLM soil texture |
| 4 | Domain & Mapping | ESMF_RegridWeightGen | Generate mapping/domain files |
| 5 | Namelist Generation | CLM build-namelist | Generate lnd_in and datm_in namelists |
| 6 | Execution | `run_clm.py` | Build and run CLM via CIME or standalone |
| 7 | Output Parsing | `parse_clm_output.py` | Extract history NetCDF to CSV/analysis |
| 8 | Validation | (analysis scripts) | Compare to observations, compute metrics |
| 9 | Calibration | (parameter sweep) | Adjust parameters for site-specific tuning |
| 10 | Coupling | (CMEPS/LILAC) | Connect to atmosphere/river models |

**Parallelism:** Stages 1-4 can run in parallel. Stage 5 depends on 1-4.
Stage 6 depends on 5. Stages 7-10 depend on 6.

---

## 4. Tools Reference

| Tool | Stage | Script Path | Purpose |
|---|---|---|---|
| make_site_dataset.py | s1+s4 | ki/tools/make_site_dataset.py | Single-point surfdata + domain + site aerosol stream file (replaces mksurfdata_esmf / ESMF_RegridWeightGen, which need an ESMF-with-PIO build — see dt_022) |
| convert_forcing_to_clm.py | s2 | ki/tools/convert_forcing_to_clm.py | Convert GSWP3/CRUJRA/ERA5/CSV/**FLUXNET** to DATM format; `--datm-layout clm1pt` writes the monthly `YYYY-MM.nc` layout DATM actually reads |
| convert_soil_params.py | s3 | ki/tools/convert_soil_params.py | Map HWSD soil to CLM texture classes |
| run_clm.py | s6 | ki/tools/run_clm.py | CIME driver: `create` / `configure` (xmlchange + user_nl append) / `setup` / `build` / `submit` / `status` |
| parse_clm_output.py | s7 | ki/tools/parse_clm_output.py | Extract CLM history to CSV; dates records by the `time_bounds` midpoint (dt_021) |

**`run_clm.py --action configure`** is the only KI route to `./xmlchange` and
`user_nl_*`. Editing `env_*.xml` by hand bypasses CIME's LockedFiles check:

```bash
python tools/run_clm.py --action configure --case-dir $CASE \
    --xmlchange STOP_N=1 --xmlchange CONTINUE_RUN=TRUE \
    --append-user-nl "clm:/path/to/user_nl_clm_fragment.txt"
```

---

## 5. Skill Knowledge

| Stage | Topic | Document |
|---|---|---|
| s0 | Configuration and compsets | docs/s0_configuration_skill.md |
| s2 | Atmospheric forcing preparation | docs/s2_forcing_skill.md |
| s3 | Soil parameter preparation | docs/s3_soil_params_skill.md |
| s6 | Model execution | docs/s6_execution_skill.md |
| s7 | Output analysis | docs/s7_output_analysis_skill.md |

---

## 6. Critical Domain Knowledge

### dt_001: Precipitation units — mm/s vs mm/day vs kg/m2/s

CLM5 DATM expects precipitation in **kg/m2/s** (equivalent to mm/s). Many
reanalysis products provide mm/day or mm/3hr. Failing to divide by 86400
(or 10800 for 3-hourly) produces runoff that is 86400x too large, typically
crashing the model or producing NaN soil moisture.

**Root cause:** No automatic unit detection in DATM streams.

**Silent failure mode:** If forcing values are merely 10x wrong (e.g.,
mm/hr used as mm/s), CLM may run but produce unrealistic runoff.

### dt_002: Temperature in Celsius vs Kelvin

CLM5 expects atmospheric temperature in **Kelvin**. Providing Celsius
causes near-zero longwave radiation, freezing soils even in summer, and
incorrect saturation vapor pressure. The model will run but produce
physically meaningless energy fluxes.

**Root cause:** No bounds checking on input temperature.

### dt_003: Longwave radiation sign and units

CLM5 expects downward longwave radiation in **W/m2** (positive downward).
Some products provide net longwave or upward longwave. Using net longwave
causes energy imbalance and rapid soil cooling.

### dt_004: Specific humidity vs relative humidity

CLM5 DATM expects **specific humidity (kg/kg)**. Providing relative humidity
(0-100 or 0-1 fraction) causes latent heat flux errors. RH of 80% entered
as 80.0 kg/kg would cause immediate model failure; RH of 0.8 entered as
specific humidity produces severe drying.

### dt_005: Soil layer mismatch — 25 layers to 8.5 m

CLM5 uses 25 soil layers with exponentially increasing thickness from 1.75 cm
(layer 1) to 1.136 m (layer 25), reaching 8.5 m total depth. External soil
data (typically 6 layers to 2 m in HWSD) must be interpolated carefully.
Using constant-depth interpolation misrepresents deep soil properties.

### dt_006: PFT fraction normalization

The surface dataset requires PFT fractions to sum to exactly 1.0 per grid
cell (after accounting for lake, wetland, glacier, and urban fractions).
Fractions summing to > 1.0 cause mass conservation violations; fractions
< 1.0 leave "bare ground" that may behave unexpectedly.

### dt_007: Calendar mismatch (noleap vs gregorian)

CLM5 typically runs with a **noleap** (365-day) calendar. If forcing data
uses a gregorian calendar with leap years, Feb 29 data causes date
misalignment that accumulates over decades. The model may crash at the
calendar boundary or silently use wrong forcing.

### dt_008: CO2 concentration units — ppmv

CLM5 expects CO2 in **ppmv** (parts per million by volume). The namelist
variable `co2_ppmv` defaults to ~367 ppmv for year 2000. Providing
concentration in mol/mol (3.67e-4) or ug/m3 produces near-zero
photosynthesis (GPP).

### dt_009: Spinup requirements — decades to centuries

CLM5 BGC mode requires 200-600+ years of spinup to equilibrate soil
carbon pools. Running without adequate spinup produces transient carbon
fluxes that do not represent the actual ecosystem. Accelerated decomposition
(CLM_ACCELERATED_SPINUP=on) reduces this to ~50-100 years but must be
followed by a normal-mode "exit spinup" run.

---

## 7. Validation

### Test Configuration

- **Mode**: Single-point (1PT) with GSWP3 forcing
- **Physics**: CLM6.0 BGC
- **Compset**: I2000Clm60BgcCrop
- **Resolution**: f09_g17 (0.9x1.25 degree) or single-point
- **Period**: 2000-2010

### Key Output Variables

| Variable | Long Name | Units |
|---|---|---|
| GPP | Gross Primary Production | gC/m2/s |
| NPP | Net Primary Production | gC/m2/s |
| NEE | Net Ecosystem Exchange | gC/m2/s |
| EFLX_LH_TOT | Total Latent Heat Flux | W/m2 |
| FSH | Sensible Heat Flux | W/m2 |
| QRUNOFF | Total Runoff | mm/s |
| H2OSOI | Soil Moisture by Layer | mm3/mm3 |
| TSOI | Soil Temperature by Layer | K |
| TOTSOMC | Total Soil Organic Carbon | gC/m2 |
| TOTVEGC | Total Vegetation Carbon | gC/m2 |
| SNOW_DEPTH | Snow Depth | m |
| FSNO | Fraction of Ground Covered by Snow | fraction |

### Published Reference Values (Global Means)

| Variable | CLM5 Published | Units | Source |
|---|---|---|---|
| GPP | ~120 | PgC/yr | Lawrence et al. 2019 |
| Total Runoff | ~40,000 | km3/yr | Lawrence et al. 2019 |
| Total ET | ~80,000 | km3/yr | Lawrence et al. 2019 |
| Soil Carbon | ~1500 | PgC | Lawrence et al. 2019 |
| Vegetation Carbon | ~350 | PgC | Lawrence et al. 2019 |

### Key Findings

1. CLM5 produces reasonable global carbon cycle when properly spun up
2. Single-point simulations are most practical for initial validation
3. Forcing data quality is the primary determinant of simulation quality
4. Soil carbon equilibrium requires > 200 years of spinup in BGC mode

---

## 8. Calibration Parameters

| Parameter | Namelist Group | Range | Controls | Sensitivity |
|---|---|---|---|---|
| `medlynslope` | clm_inparm | 1-15 | Stomatal conductance | High |
| `medlynintercept` | clm_inparm | 100-40000 | Min. stomatal conductance | Medium |
| `baseflow_scalar` | clm_inparm | 0.0001-0.01 | Subsurface drainage rate | High |
| `fff` | clm_inparm | 0.02-2.0 | Decay of Ksat with depth | High |
| `deflmax` | clm_inparm | 0-0.1 | Maximum saturated fraction | Medium |
| `co2_ppmv` | clm_inparm | 280-560 | Atmospheric CO2 level | High |
| `finidat` | clm_inparm | (file path) | Initial conditions | Critical |
| `spinup_state` | clm_inparm | 0/1/2 | Accelerated decomposition | Critical |

---

## 9. Coupling Points

| # | Source | Target | Variable | Mechanism |
|---|---|---|---|---|
| 1 | DATM | CLM5 | Precip, Temp, Wind, Radiation, Humidity | NUOPC/CDEPS |
| 2 | CLM5 | MOSART | Runoff (surface + subsurface) | NUOPC fields |
| 3 | CLM5 | DATM | Albedo, surface temperature | NUOPC feedback |
| 4 | CLM5 | CISM | Snow/ice mass balance | NUOPC fields |
| 5 | CLM5 | Atmosphere | Latent/Sensible heat, CO2 flux | NUOPC fields |

---

## 10. Data Requirements

| Data | Source | Format | Path |
|---|---|---|---|
| Surface dataset | CESM inputdata | NetCDF | $DIN_LOC_ROOT/lnd/clm2/surfdata_esmf/ |
| Domain file | CESM inputdata | NetCDF | $DIN_LOC_ROOT/share/domains/ |
| Atmospheric forcing | GSWP3/CRUJRA/ERA5 | NetCDF | $DIN_LOC_ROOT/atm/datm7/ |
| Parameter file | CESM inputdata | NetCDF | $DIN_LOC_ROOT/lnd/clm2/paramdata/ |
| Initial conditions | CESM inputdata | NetCDF | $DIN_LOC_ROOT/lnd/clm2/initdata/ |
| Land use transitions | CESM inputdata | NetCDF | $DIN_LOC_ROOT/lnd/clm2/rawdata/ |
| CO2 time series | CESM inputdata | NetCDF | $DIN_LOC_ROOT/atm/datm7/CO2/ |

---

## 11. Quick Start Examples

### Example 1: Create a single-point case

```bash
cd $CIMEROOT/scripts
./create_newcase --case ~/cases/1pt_test \
    --res CLM_USRDAT --compset I2000Clm60Sp \
    --run-unsupported
cd ~/cases/1pt_test
./xmlchange CLM_USRDAT_NAME=1x1_brazil
./case.setup
./case.build
./case.submit
```

### Example 2: Convert ERA5 forcing to DATM format

```bash
python ki/tools/convert_forcing_to_clm.py \
    --source era5 \
    --input /path/to/era5_hourly.nc \
    --output /path/to/datm_forcing/ \
    --start-year 2000 --end-year 2010
```

### Example 3: Run CLM with pre-built case

```bash
python ki/tools/run_clm.py \
    --case-dir /path/to/cases/my_case \
    --timeout 7200
```

### Example 4: Parse output to CSV

```bash
python ki/tools/parse_clm_output.py \
    --history-dir /path/to/archive/lnd/hist/ \
    --variables GPP,QRUNOFF,EFLX_LH_TOT \
    --output results.csv
```

### Example 5: Adjust namelist for BGC spinup

```bash
cd /path/to/cases/my_case
./xmlchange CLM_ACCELERATED_SPINUP=on
./xmlchange STOP_OPTION=nyears
./xmlchange STOP_N=100
cat >> user_nl_clm << 'EOF'
hist_nhtfrq = -8760
hist_mfilt = 1
hist_fincl1 = 'TOTSOMC', 'TOTVEGC', 'GPP', 'NEE'
EOF
./case.build
./case.submit
```

---

## 12. Diagnostic Triplets Summary

See `diagnostics/triplets.yaml` for full details.

| ID | Severity | Domain | Summary |
|---|---|---|---|
| dt_001 | silent | unit_conversion | Precipitation mm/day used as kg/m2/s |
| dt_002 | silent | unit_conversion | Temperature in Celsius instead of Kelvin |
| dt_003 | silent | unit_conversion | Net longwave used as downward longwave |
| dt_004 | silent | unit_conversion | Relative humidity used as specific humidity |
| dt_005 | degraded | parameter_format | Soil layer interpolation mismatch |
| dt_006 | degraded | parameter_format | PFT fractions not summing to 1.0 |
| dt_007 | fatal | dependency_mismatch | Calendar mismatch (noleap vs gregorian) |
| dt_008 | silent | unit_conversion | CO2 in wrong units (not ppmv) |
| dt_009 | degraded | runtime | Insufficient spinup for BGC mode |
| dt_010 | fatal | path_resolution | Surface dataset file not found |
| dt_011 | silent | unit_conversion | Wind speed at wrong height |
| dt_012 | fatal | runtime | NetCDF dimension mismatch |
| dt_013 | degraded | dependency_mismatch | Forcing temporal resolution mismatch |
| dt_014 | silent | silent_error | Incorrect soil organic matter initialisation |
| dt_015 | fatal | parameter_format | Namelist syntax error (Fortran formatting) |
| dt_016 | degraded | runtime | History output volume / frequency |
| dt_017 | silent | silent_error | CLM fill value 1e36 not masked before statistics |
| dt_018 | fatal | parameter_format | CLM1PT stream needs RH (%) + ZBOT in monthly YYYY-MM.nc — NOT QBOT |
| dt_019 | degraded | silent_error | 'GPP' does not exist in SP mode; use 'FPSN' (umol m-2 s-1) |
| dt_020 | fatal | path_resolution | DATM_PRESAERO=none rejected for CLM; default aerosol file is 6.2 GB |
| dt_021 | silent | silent_error | Averaged history stamped at END of interval — date by time_bounds midpoint |
| dt_022 | fatal | dependency_mismatch | CTSM-5.4/NUOPC cesm.exe dead (ESMF built without PIO) — use CESM 2.2.2 MCT |

**Silent errors:** 6 of 15 triplets (40%) are silent — the model runs but
produces incorrect results. The most critical is dt_001 (precipitation
unit mismatch) which can produce runoff 86400x too high.

---

## 13. File Structure

```
ki/
  SKILL.md                              -- This file
  tools/
    convert_forcing_to_clm.py           -- Stage 2: forcing converter
    convert_soil_params.py              -- Stage 3: soil parameter mapper
    run_clm.py                          -- Stage 6: execution wrapper
    parse_clm_output.py                 -- Stage 7: output parser
  docs/
    s0_configuration_skill.md           -- Configuration and compsets
    s2_forcing_skill.md                 -- Atmospheric forcing preparation
    s3_soil_params_skill.md             -- Soil parameter preparation
    s6_execution_skill.md               -- Model execution
    s7_output_analysis_skill.md         -- Output analysis and validation
  diagnostics/
    triplets.yaml                       -- 15 diagnostic triplets
```

---

## 14b. WHICH CLM INSTALLATION TO USE  *(read before anything else)*

`preflight_check.py` pins `KISSPATH_HOME/cesm/scratch/test_clm5/bld/cesm.exe`.
That binary **cannot initialise**: it is a CTSM-5.4 / NUOPC build whose ESMF was
compiled without PIO, so `ESMCI_mesh_create_from_file()` aborts in
`atm_comp_nuopc.F90` a second after launch (dt_022). `mksurfdata_esmf` is dead
for the same reason.

**Use CESM 2.2.2 with the MCT driver instead** — it is fully installed and has a
recorded `model execution success` (case `B1850_test`, 2026-05-02):

| Item | Path |
|---|---|
| CESM root (`--ctsm-root`) | `KISSPATH_HOME/cesm/src/cesm-2.2.2` |
| Machine | `hydrocraft_server` (config in `KISSPATH_HOME/.cime/`) |
| `DIN_LOC_ROOT` | `KISSPATH_HOME/cesm/inputdata` |
| `DIN_LOC_ROOT_CLMFORC` | `KISSPATH_HOME/cesm/inputdata/atm/datm7` |
| Cases / scratch | `KISSPATH_HOME/cesm/cases`, `KISSPATH_HOME/cesm/scratch` |
| Batch system | none — `./case.submit` runs the model synchronously |

Missing inputdata files can be fetched from
`https://svn-ccsm-inputdata.cgd.ucar.edu/trunk/inputdata/...` (verified
working). Check `Content-Length` first: the default CESM aerosol-deposition
file is **6.2 GB** (dt_020).

---

## 15. VALIDATED RECIPE — single-point FLUXNET tower run (CLM5-SP)

Executed end to end 2026-08-09 at FLUXNET2015 **US-MMS** (Morgan Monroe State
Forest, 39.3232 N, 86.4131 W, DBF, 1999-2014 hourly). Every step uses a KI tool.

**s1 — site datasets** (surfdata + domain + aerosol, one command):

```bash
python tools/make_site_dataset.py --site-name US-MMS \
  --lat 39.3232 --lon -86.4131 --igbp DBF \
  --global-surfdata $DIN/lnd/clm2/surfdata_map/release-clm5.0.18/\
surfdata_0.9x1.25_hist_78pfts_CMIP6_simyr1850_c190214.nc \
  --outdir $DIN/lnd/clm2/surfdata_map --domain-outdir $DIN/share/domains \
  --aerosol-source $DIN/atm/cam/chem/trop_mozart_aero/aero/\
aerosoldep_monthly_2000_mean_1.9x2.5_c090421.nc \
  --aerosol-outdir $DIN/atm/cam/chem/trop_mozart_aero/aero --aerosol-year 2000
```

`--igbp` maps the tower's documented vegetation class to a CLM PFT and makes the
cell 100 % that PFT (CTSM `subset_data.py --dompft` behaviour) — this is how a
~100 km parent cell is made to represent a ~1 km tower footprint. LAI/SAI/HTOP
still come from the parent cell's MODIS climatology on the surface dataset. Forcing the cell to one PFT zeroes every non-vegetated landunit, but
`PCT_GLC_MEC` must **still sum to 100 %** across its 10 elevation classes:
`surfrd_special` (surfrdMod.F90:602-607) reads it unconditionally and
`check_sums_equal_1` endruns at surfrdUtilsMod.F90:80 even when
`PCT_GLACIER = 0` (dt_023). `make_site_dataset.py` now writes class 0 = 100
and hard-fails if the sum is not 100.

**s2 — tower meteorology → DATM CLM1PT monthly files**:

```bash
python tools/convert_forcing_to_clm.py --source fluxnet \
  --input .../fluxnet/sites/US-MMS/FULLSET_HR.csv \
  --output $DIN/atm/datm7/US-MMS/CLM1PT_data --datm-layout clm1pt \
  --lat 39.3232 --lon -86.4131 --zbot 46.0 --elevation 275 \
  --start-year 1999 --end-year 2014
```

Reads the gap-filled `*_F` columns, converts °C→K, kPa→Pa, mm/step→kg/m²/s,
VPD→**RH in percent** (dt_018), drops Feb 29 for the noleap calendar (dt_007),
stamps each record at the interval MIDPOINT, and resumes by skipping months
already written. `--zbot` must exceed the canopy top on the surface dataset.

**s3-s4 — case**: compset `I1PtClm50SpRsGs`, resolution `CLM_USRDAT`, then

```
CLM_USRDAT_NAME=<site>          ATM/LND_DOMAIN_PATH=$DIN/share/domains
ATM/LND_DOMAIN_FILE=domain.lnd.<site>_navy.nc
DATM_CLMNCEP_YR_START/END/ALIGN=1999/2014/1999
DATM_PRESAERO=clim_2000         RUN_STARTDATE=1999-01-01
STOP_OPTION=nyears  STOP_N=1    REST_OPTION=nyears  REST_N=1
DOUT_S=FALSE        CCSM_CO2_PPMV=383.0   CLM_FORCE_COLDSTART=on
```

`user_nl_clm`: `fsurdat` = the site surface dataset, `hist_nhtfrq = -24`,
`hist_mfilt = 365`, and `hist_fincl1` **must request `FPSN`, not `GPP`**
(dt_019). Do **not** also set `finidat` — `finidat` plus
`CLM_FORCE_COLDSTART=on` makes build-namelist exit rc=255.

Then copy `Buildconf/datmconf/datm.streams.txt.presaero.clim_2000` to
`user_datm.streams.txt.presaero.clim_2000` and point it at `aerosoldep_<site>.nc`
(dt_020), re-run `./preview_namelists`, and confirm with `./check_input_data`.

Three small files must be present in inputdata and are NOT shipped:
`atm/datm7/topo_forcing/topodata_0.9x1.25_USGS_070110_stream_c151201.nc` (2 MB),
`atm/cam/chem/trop_mozart/emis/megan21_emis_factors_78pft_c20161108.nc` (67 kB),
and an aerosol-deposition file (use the 9 MB 1.9x2.5 climatology).

**s5 — run**: submit ONE simulated year at a time (`STOP_N=1`, then
`CONTINUE_RUN=TRUE`); the model date is recoverable from `rpointer.lnd`, which
makes a long run resumable after any interruption.

**s6 — score**: `parse_clm_output.py` → `FPSN`, then
`GPP [gC m-2 d-1] = FPSN [umol m-2 s-1] × 12.011e-6 × 86400 = FPSN × 1.03775`,
paired against `GPP_NT_VUT_REF` from `FULLSET_DD.csv` (already gC m-2 d-1).
Discard the first 2 years as soil-moisture/temperature spin-up (SP mode needs no
carbon spin-up, so dt_009 does not apply).

---

## 14. Unit Trap Reference Table

This table summarises every unit conversion required at model boundaries.

| Variable | External Source | External Unit | CLM5 Required | Conversion |
|---|---|---|---|---|
| Precipitation | GSWP3/ERA5 | mm/day or mm/hr | kg/m2/s (= mm/s) | / 86400 or / 3600 |
| Temperature | ERA5/CMFD | K (usually correct) | K | None (verify > 200) |
| Temperature | Some station data | deg C | K | + 273.15 |
| Specific humidity | ERA5 | kg/kg | kg/kg | None (verify 0-0.04) |
| Relative humidity | Station data | % (0-100) | kg/kg (specific) | Convert via Tetens |
| Wind speed | ERA5 | m/s at 10m | m/s at ref height | Log-profile correction |
| Shortwave radiation | ERA5/CMFD | W/m2 | W/m2 | None (verify >= 0) |
| Longwave radiation | ERA5 | W/m2 (downward) | W/m2 (downward) | None (verify 50-600) |
| Pressure | ERA5 | Pa | Pa | None (verify 50000-110000) |
| CO2 concentration | Namelist | ppmv | ppmv | None (verify 200-1000) |
| Soil sand/clay | HWSD | % (0-100) | % (0-100) | None (verify sum <= 100) |
| Soil organic matter | SoilGrids | g/kg | kg/m3 | * bulk_density / 1000 |
| Soil depth | HWSD | cm | m | / 100 |
| Leaf area index | MODIS | m2/m2 | m2/m2 | None (verify 0-15) |
| Albedo | MODIS | fraction (0-1) | fraction (0-1) | None |
| Elevation | DEM | m | m | None |
