> **MANDATORY EXECUTION POLICY** — READ BEFORE PROCEEDING
>
> You MUST run the **actual model binary or package** described in this document.
> If the model fails to import, compile, or execute, you MUST:
> 1. Check `diagnostics/triplets.yaml` for a matching error pattern
> 2. Try the fix suggested in the triplet's `remedy` section
> 3. If still failing, report the error to the user with full details
>
> You MUST NOT substitute a simplified Python formula, regression equation,
> or hand-coded approximation in place of the real model. Doing so produces
> scientifically invalid results and defeats the purpose of the KI.
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

---

## Data Preparation

### Forcing data

**Data Sources**: Use `from ki_tools_common.load_forcing import load_daily_forcing` for CMFD/MSWX/NASA POWER.
SUMMA forcing tool: `convert_vic_forcing_to_summa.py` — Converts VIC forcing to SUMMA NetCDF format.

**Data Validation Reference**: See `data_ki/CMFD/SKILL.md` for CMFD unit documentation and known traps.

---

# SUMMA Knowledge Infrastructure

**SUMMA** (Structure for Unifying Multiple Modeling Alternatives) is a flexible multi-physics hydrologic modeling framework developed by NCAR (Clark et al., 2015a,b). Unlike traditional hydrologic models that hardcode one set of process representations, SUMMA lets you **choose** which physics to use for each process via "model decisions" -- then systematically compare alternatives. This knowledge infrastructure enables autonomous AI operation of SUMMA.

**Model**: SUMMA (CH-Earth/summa), Fortran 90, NetCDF I/O
**Domain**: Multi-physics distributed hydrology
**Key Feature**: Model decisions -- 35 categories of physics options (snow, soil, vegetation, radiation, groundwater)
**Executable**: `model/summa/bin/summa.exe`
**Configuration**: `fileManager.txt` (master config pointing to all other files)

---

## Pipeline Overview (7 Stages)

| Stage | Name | Key Tool | Output |
|-------|------|----------|--------|
| s1 | Domain Setup (GRU/HRU) | `create_gru_hru.py`, `create_local_attributes.py` | `attributes.nc` |
| s2 | Forcing Preparation | `convert_vic_forcing_to_summa.py` | `forcing_YYYY.nc` |
| s3 | Model Decisions | `configure_decisions.py` | `decisions.txt` |
| s4 | Parameter Configuration | `set_trial_parameters.py` | `trialParams.nc` |
| s5 | Initial Conditions | `create_initial_conditions.py` | `coldState.nc` |
| s6 | Execution | `create_file_manager.py`, `validate_file_manager.py`, `run_summa.py`, `parse_summa_output.py` | SUMMA output NetCDF |
| s7 | Physics Comparison | `compare_physics.py`, `plot_summa_results.py` | Comparison CSV + plots |

**Dependencies**: s1 -> s2, s4, s5; s3 is independent; s1+s2+s3+s4+s5 -> s6 -> s7

---

## Tools Reference

| Stage | Tool | Script | Purpose |
|-------|------|--------|---------|
| s1 | create_gru_hru | `tools/s1_domain_setup/create_gru_hru.py` | Create GRU/HRU structure from shapefile + DEM |
| s1 | create_local_attributes | `tools/s1_domain_setup/create_local_attributes.py` | Generate SUMMA attributes NetCDF |
| s2 | convert_vic_forcing_to_summa | `tools/s2_forcing_prep/convert_vic_forcing_to_summa.py` | VIC forcing -> SUMMA NetCDF with unit conversions |
| s3 | configure_decisions | `tools/s3_decisions/configure_decisions.py` | Generate decisions file with validation |
| s4 | set_trial_parameters | `tools/s4_parameters/set_trial_parameters.py` | Generate trial parameters NetCDF |
| s5 | create_initial_conditions | `tools/s5_initial_conditions/create_initial_conditions.py` | Generate cold-start initial conditions |
| s6 | create_file_manager | `tools/s6_execution/create_file_manager.py` | Generate fileManager.txt with absolute paths |
| s6 | validate_file_manager | `tools/s6_execution/validate_file_manager.py` | Check all paths and dimensions before running |
| s6 | run_summa | `tools/s6_execution/run_summa.py` | Execute SUMMA with progress monitoring |
| s6 | parse_summa_output | `tools/s6_execution/parse_summa_output.py` | Extract variables from output NetCDF |
| s7 | compare_physics | `tools/s7_physics_comparison/compare_physics.py` | Run multiple decision variants and compare |
| s7 | plot_summa_results | `tools/s7_physics_comparison/plot_summa_results.py` | Publication-quality result plots |

---

## Critical Domain Knowledge

### 1. fileManager.txt -- The Master Config

fileManager.txt is SUMMA's single entry point. It references all other config files. **Every path MUST be absolute** -- SUMMA Fortran resolves from the executable's CWD. controlVersion MUST be `'SUMMA_FILE_MANAGER_V3.0.0'`. Paths must end with `/` for directories. Always run `validate_file_manager.py` before running SUMMA.

### 2. Decisions -- SUMMA's Unique Feature

Unlike VIC/CaMa-Flood/SWAT+ which have fixed physics, SUMMA lets you choose. 35 decision categories control which equations are solved. Example: `snowLayers jrdn1991` vs `snowLayers CLM_2010` selects different snow layer management algorithms. Some decision names use intentional abbreviations: `itertive` (not `iterative`), `numericl` (not `numerical`).

**CRITICAL DECISION CONSTRAINTS** (from `mDecisions.f90`, SUMMA crashes if violated):

| Constraint | Rule | Source |
|------------|------|--------|
| `fDerivMeth` | Must be `analytic` — `numericl` crashes immediately ("cross derivatives" error) | `soilLiqFlx.f90:305` |
| `groundwatr=qTopmodl` | Requires `bcLowrSoiH=zeroFlux` AND `hc_profile=pow_prof` | `mDecisions.f90:660,669` |
| `spatial_gw=singleBasin` | Requires `groundwatr=bigBuckt` | `mDecisions.f90:675` |

**Safe defaults** (from Reynolds Mountain reference case): `fDerivMeth=analytic`, `groundwatr=noXplict`, `hc_profile=constant`, `bcLowrSoiH=drainage`.

### 2c. Vegetation Table Selection — Ask User About Region

| Basin Location | `vegeParTbl` Decision | Land Cover Input | Crosswalk Needed? |
|---|---|---|---|
| **North America** | `USGS` | AVHRR IGBP → USGS crosswalk in `create_gru_hru.py` | Yes (IGBP→USGS) |
| **Global / non-NA** | `MODIFIED_IGBP_MODIS_NOAH` | AVHRR IGBP values used directly (class numbers match) | No |

**Always ask the user**: "Is this basin in North America? This determines the vegetation lookup table (USGS for NA, IGBP/MODIS for global)."

- `USGS` (27 classes): NA-centric types (Tundra, Playa, White Sand). Requires IGBP→USGS crosswalk when using AVHRR data. Shipped with all SUMMA installations.
- `MODIFIED_IGBP_MODIS_NOAH` (20 classes): Global IGBP standard. AVHRR pixel values map directly. Requires MPTABLE.TBL to contain the `MODIFIED_IGBP_MODIS_NOAH` section — copy from `case_study/base_settings/MPTABLE.TBL` if missing.

For **Chinese basins**: Use `MODIFIED_IGBP_MODIS_NOAH` — IGBP class 12 (Cropland) and 14 (Cropland/Natural Mosaic) directly represent the dominant land uses. The USGS table has no rice paddy type and the crosswalk is imprecise.

### 2b. vGn_alpha -- NEGATIVE Sign Convention

SUMMA uses **negative** values for `vGn_alpha` (van Genuchten alpha). This is because SUMMA's matric head convention uses negative values for unsaturated conditions. From `localParamInfo.txt`: range is **[-1.0, -0.01]**, default **-0.84**.

Reference values from SOILPARM.TBL: Sand=-3.524, Loamy Sand=-3.475, Loam=-1.112, Clay Loam=-1.581, Clay=-1.496.

**Positive values cause NaN** in the Richards equation solver (`soil_utils.f90:volFracLiq`).

### 3. Unit Conversions (Silent Error Zone)

| Variable | VIC Unit | SUMMA Unit | Conversion | If wrong |
|----------|----------|------------|------------|----------|
| Precipitation | mm/3hr | kg m-2 s-1 | / 10800 | Runoff 8x wrong |
| Temperature | C | K | + 273.15 | Energy balance fails |
| Pressure | kPa | Pa | * 1000 | ET 100x wrong |
| Shortwave | W/m² | W/m² | none | — |
| Longwave | W/m² | W/m² | none | — |
| Humidity | kg/kg | kg/kg | none | — |
| Wind | m/s | m/s | none | — |

**CRITICAL: VIC Column Order Mismatch (dt_023)**

HydroCraft VIC forcing uses column order: `AIR_TEMP, PREC, PRESSURE, SWDOWN, LWDOWN, VP, WIND` (7 cols).
Classic VIC documentation describes: `PREC, TMAX, TMIN, WIND, SW, LW, PRESSURE, QAIR` (8 cols).
The `convert_vic_forcing_to_summa.py` tool defaults to `--column_order hydrocraft`. Use `--column_order classic` only for non-HydroCraft VIC setups.

**Always verify forcing after conversion:**
```python
from netCDF4 import Dataset; import numpy as np
ds = Dataset('forcing_YYYY.nc')
print(f"P={np.nanmean(ds['pptrate'][:])*86400:.1f} mm/day")    # expect 1-5
print(f"T={np.nanmean(ds['airtemp'][:])-273.15:.1f} °C")       # expect 10-20
print(f"P={np.nanmean(ds['airpres'][:]):.0f} Pa")              # expect 99000-103000
```

### 4. Fortran Path Truncation

SUMMA uses CHARACTER(256) for file paths. Paths exceeding 256 characters are silently truncated, causing "file not found" or reading the wrong file. Use symlinks for deep directory structures. This is the same trap as DSSAT, VIC routing, and RZWQM2 (cross-model triplet cm_008).

### 5. HRU Configuration — Performance vs Accuracy Trade-off

SUMMA's runtime scales linearly with the number of HRUs. The `create_gru_hru.py` tool has two modes:

| Mode | Flag | HRU/GRU | Use case | Runtime |
|------|------|---------|----------|---------|
| **Single (default)** | (none) | 1:1 | Standard distributed modeling, comparable to VIC grid cells | Fast |
| **Multi-HRU** | `--multi_hru` | N:1 | Sub-grid heterogeneity: elevation bands, slope aspects, vegetation patches | 10-50x slower |

**Guidance from Clark et al. 2015**: GRUs are spatially contiguous with no lateral moisture exchange; HRUs within a GRU can share a conceptual aquifer. Use multi-HRU for mountain basins where sub-grid variability matters (e.g., north vs south facing slopes). For flat/uniform basins, 1 HRU per GRU is standard practice.

**Example**: Bengbu 0.25° with 224 GRUs: single-HRU ran in 98 min; multi-HRU (8304 HRUs) was estimated at 35+ hours.

### 6. Spinup Required — Two-Phase Strategy for Subtropical Basins

Cold-start initial conditions produce 1-2 years of unrealistic output. More critically, `nrg_flux` (full energy balance) frequently fails to converge on cold-start because soil temperature profiles are unrealistic.

**Two-phase spinup (recommended for subtropical/temperate basins):**
1. **Phase 1** (1 year): Run with `bcUpprTdyn=presTemp` — stable, builds realistic soil moisture profile
2. Save the restart file from Phase 1
3. **Phase 2** (production): Switch to `bcUpprTdyn=nrg_flux` using Phase 1 restart — full energy balance + ET

**Why this matters**: `presTemp` bypasses the energy balance and produces **zero ET**. Without ET, no runoff is generated (all water goes to soil storage). `presTemp` is a diagnostic mode, not for production hydrology. You MUST use `nrg_flux` for scientifically valid results — but it needs warm initial conditions.

**Alternative**: Use `groundwatr=bigBuckt` with properly calibrated `aquiferScaleFactor` and `aquiferBaseflow` parameters to generate baseflow even without ET. But this still produces wrong water balance without `nrg_flux`.

### 7. Regional Applicability — Cold-Region Bias

**SUMMA was designed for cold-region hydrology** (NCAR, Clark et al. 2015). The `canopySnow` module runs at every timestep and handles phase-change calculations for canopy ice/liquid. This causes convergence failures (`failed to converge [mass]`) when:

- Basin has **seasonal freezing transitions** (subtropical/temperate with brief winters)
- `nrg_flux` boundary condition is used (full energy balance triggers the stiff phase-change equations)
- Large distributed domains (>50 GRUs) — more HRUs means more chances for one to fail

**Confirmed behavior on Bengbu (Huai River, 32-35°N)**:
- `nrg_flux` crashes at the first freezing event (Dec/Jan) for ALL GRUs
- `presTemp` runs but produces zero ET → zero runoff (diagnostic mode only)
- Summer start (Jul-Nov) runs successfully for 5 months, crashes when Dec freezing begins

**Recommended basin types for SUMMA**:
- Snow-dominated mountain basins (Reynolds Mountain, Bow River, etc.)
- Cold-region hydrology (permafrost, Arctic/subarctic)
- Basins where canopy snow interception is physically important

**For subtropical/temperate basins** (China, SE Asia, S. Europe): Use VIC, mHM, HYPE, or wflow instead. These models handle seasonal freezing without convergence issues.

**USGS vegetation table limitation**: No rice paddy or subtropical cropland types. The `create_gru_hru.py` tool now applies IGBP→USGS crosswalk (dt_024) to avoid the critical misclassification where AVHRR class 11 (Wetland/Cropland, 74% of Bengbu) was mapped to USGS class 11 (Deciduous Broadleaf Forest, 20m canopy) — causing `canopySnow` convergence failures due to excessive canopy snow interception on what should be flat rice paddies.

### 6. HRU ID Consistency

ALL NetCDF files (attributes, forcing, coldState, trialParams) must have identical hruId values in identical order. Regenerating any one file without the others causes immediate crashes.

---

## VIC Coupling

SUMMA can share forcing data with VIC through the `convert_vic_forcing_to_summa.py` tool. This enables head-to-head comparison of VIC vs SUMMA for the same basin, forcing, and period -- isolating the effect of model structure.

**Coupling workflow**:
1. Run HydroCraft VIC workflow (Steps 1-7) as usual
2. After VIC forcing is prepared, run `convert_vic_forcing_to_summa.py`
3. Configure SUMMA domain from the same basin shapefile
4. Run SUMMA with decisions that approximate VIC's physics
5. Compare outputs (runoff, ET, soil moisture)

---

## Diagnostic Triplets Summary

| ID | Stage | Domain | Severity | Description |
|----|-------|--------|----------|-------------|
| dt_001 | s6 | path_resolution | fatal | Missing file in fileManager |
| dt_002 | s6 | path_resolution | fatal | Path exceeds CHARACTER(256) |
| dt_003 | s2 | unit_conversion | **silent** | Precip divisor wrong (8x error) |
| dt_004 | s2 | unit_conversion | fatal | Pressure in kPa not Pa |
| dt_005 | s2 | dependency_mismatch | fatal | HRU ID mismatch forcing/attributes |
| dt_006 | s5 | parameter_format | fatal | Soil layer count mismatch |
| dt_007 | s6 | runtime | fatal | Convergence failure |
| dt_008 | s6 | runtime | fatal | NetCDF dimension error (STOP 20) |
| dt_009 | s3 | parameter_format | fatal | Invalid decision option (STOP 30) |
| dt_010 | s1 | dependency_mismatch | fatal | Inconsistent IDs across files |
| dt_011 | s6 | **silent_error** | silent | All runoff is zero |
| dt_012 | s2 | **silent_error** | silent | ET unrealistically high |
| dt_013 | s6 | runtime | degraded | NaN for some HRUs |
| dt_014 | s4 | **silent_error** | silent | Trial params silently ignored |
| dt_015 | s5 | **silent_error** | silent | Spinup artifacts in output |
| dt_016 | s6 | environment | fatal | Missing shared library |
| dt_017 | s7 | dependency_mismatch | silent | Identical results for different physics |
| dt_018 | s1 | **silent_error** | silent | CRS mismatch -> all HRUs identical |

**5 silent errors** (28%) -- the most dangerous. See `diagnostics/triplets.yaml` for full details.

---

## Installation

### Dependencies
- gfortran (GCC 6+)
- NetCDF-Fortran (libnetcdff-dev)
- LAPACK/BLAS (liblapack-dev)

### Build (Makefile method)
```bash
cd model/summa/build
export F_MASTER=/mnt/disk1/Hydrocraft_server/model/summa
export FC=gfortran
export FC_EXE=gfortran
export INCLUDES='-I/usr/include'
export LIBRARIES='-L/usr/lib/x86_64-linux-gnu -lnetcdff -llapack -lblas'
make
```

### Verify
```bash
model/summa/bin/summa.exe
# Should print usage information with -m, -s, -r, -p flags
```

---

## Quick Start

```bash
# 1. Create domain
python tools/s1_domain_setup/create_gru_hru.py --basin_shp ... --dem ... --output_dir ...
python tools/s1_domain_setup/create_local_attributes.py --gru_hru_csv ... --output_nc ...

# 2. Convert forcing
python tools/s2_forcing_prep/convert_vic_forcing_to_summa.py --vic_forcing_dir ... --attributes_nc ...

# 3. Configure decisions
python tools/s3_decisions/configure_decisions.py --output ... --use_defaults

# 4. Set parameters
python tools/s4_parameters/set_trial_parameters.py --attributes_nc ... --output_nc ... --parameters '{}'

# 5. Create initial conditions
python tools/s5_initial_conditions/create_initial_conditions.py --attributes_nc ... --output_nc ...

# 6. Run
python tools/s6_execution/create_file_manager.py --settings_path ... --forcing_path ... --output_path ...
python tools/s6_execution/validate_file_manager.py --file_manager ...
python tools/s6_execution/run_summa.py --summa_exe ... --file_manager ...

# 7. Compare physics (optional)
python tools/s7_physics_comparison/compare_physics.py --file_manager ... --summa_exe ... --variations '...'
```

---

*This knowledge infrastructure was built using the knowledge dissection methodology (Zhang et al., Nature, under review).*
*Package: hydrocraft-summa v1.0.0 | 12 tools (~2,826 LOC) | 7 skill documents (~5,158 words) | 18 diagnostic triplets | 7 failure domains*
