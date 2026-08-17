---
name: summa
description: >-
  SUMMA. Covers Per-HRU vertical land-surface mass and energy conservation: vegetation
  canopy, snowpack, soil…; Radiation transmission and wind attenuation through canopy;
  Snow interception, accumulation, phase change, compaction, and melt; Evapotranspiration
  (canopy/ground evaporation, transpiration, sublimation); Soil water flow (Richards
  equation, van Genuchten-Mualem retention). Use when the task involves running,
  configuring, calibrating or interpreting SUMMA.
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
| s2 | build_summa_forcing_from_reanalysis | `tools/s2_forcing_prep/build_summa_forcing_from_reanalysis.py` | CMFD/MSWX -> SUMMA multi-HRU forcing NetCDF, sub-daily, lapse-corrected. Use when there is no VIC run to borrow forcing from |
| s3 | configure_decisions | `tools/s3_decisions/configure_decisions.py` | Generate decisions file with validation |
| s4 | set_trial_parameters | `tools/s4_parameters/set_trial_parameters.py` | Generate trial parameters NetCDF |
| s5 | create_initial_conditions | `tools/s5_initial_conditions/create_initial_conditions.py` | Generate cold-start initial conditions |
| s6 | create_file_manager | `tools/s6_execution/create_file_manager.py` | Generate fileManager.txt with absolute paths |
| s6 | validate_file_manager | `tools/s6_execution/validate_file_manager.py` | Check all paths and dimensions before running |
| s6 | run_summa | `tools/s6_execution/run_summa.py` | Execute SUMMA with progress monitoring |
| s6 | parse_summa_output | `tools/s6_execution/parse_summa_output.py` | Extract variables from output NetCDF |
| s7 | compare_physics | `tools/s7_physics_comparison/compare_physics.py` | Run multiple decision variants and compare |
| s7 | plot_summa_results | `tools/s7_physics_comparison/plot_summa_results.py` | Publication-quality result plots |
| s7 | compare_spatial_field | `tools/s7_physics_comparison/compare_spatial_field.py` | Score a per-HRU/GRU field against a GRIDDED obs product (GRUN, MOD16, ESA-CCI) on the obs grid: CSI + spatial R + all_metrics |

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
| `spatial_gw=singleBasin` | **NEVER USE — not implemented.** Passes `mDecisions.f90:675` (which only checks it is paired with `groundwatr=bigBuckt`), then aborts at run time: `run_oneGRU.f90:266` unconditionally sets `err=20, 'multi_driver/bigBucket groundwater code not transferred from old code base yet'`. Use `spatial_gw=localColumn` + `groundwatr=bigBuckt` for a lumped aquifer. | `run_oneGRU.f90:266` |

**Safe defaults** (from Reynolds Mountain reference case): `fDerivMeth=analytic`, `groundwatr=noXplict`, `hc_profile=constant`, `bcLowrSoiH=drainage`.

### 2c. Vegetation — SOURCE IT FROM LAND COVER, then match the table

**Vegetation is an input, never an assumption.** `vegTypeIndex` sets canopy height,
monthly LAI, rooting depth and stomatal resistance — i.e. it sets ET, and therefore
it sets discharge. There is no "safe default".

> **ALWAYS read back the veg class mix before running.** Both domain tools print
> `veg_area_fraction` in their stdout JSON. If an alpine, steppe or desert basin comes
> back dominated by a low-numbered class (1–5 = the forests), stop — that is `dt_030`,
> where "dominant class" was silently the *lowest-numbered class present* rather than
> the areal mode, biasing open basins toward a 20 m forest canopy. Fixed 2026-07-20;
> the same read-back catches a wrong `--veg_scheme` pairing too.

**Step 1 — derive `vegTypeIndex` from a land-cover raster.** Pass `--landcover_tif`
to `tools/s8_routing/build_river_network.py` (per-polygon modal IGBP class, crosswalked
via `ki_tools_common.landcover`). Its `--veg_index` writes ONE class to the whole domain
and now warns; use it only for a genuinely uniform single-HRU site.

| Dataset | Path | Legend | Epoch |
|---|---|---|---|
| AVHRR 1 km (**primary — already IGBP**) | `data/landcover/AVHRR_1km_LANDCOVER_1981_1994.GLOBAL.tif` | IGBP 0–16 | 1981–1994 |
| ESA-CCI-LC 0.1° | `KISSPATH_DATA/vegetation/ESA_CCI_LC_global/` | LCCS (needs its own crosswalk) | 1992–2020 |
| GLCFCS30 30 m | `KISSPATH_DATA/vegetation/GLCFCS30/` | 29-class (needs its own crosswalk) | 2015 |
| CLCD 30 m China | `KISSPATH_DATA/vegetation/CLCD_raw/` | 9-class | 2000–2024 |

**Step 1b — canopy height is a PARAMETER, not a table lookup.** SUMMA reads
`heightCanopyTop` / `heightCanopyBottom` from `localParamInfo.txt` / `trialParams.nc`
(`popMetadat.f90:212`) — it never consults MPTABLE's `HVT`/`HVB` for them. Shipped
defaults are **20.0 m / 2.0 m**, i.e. a forest on *every* HRU including alpine
grassland, unless you write them per-HRU. Pass `--veg_scheme` to
`set_trial_parameters.py --from_hwsd` so they come from `HVT`/`HVB` for the table you
actually chose. Without it the tool uses a hard-coded **USGS-27** dict, so a MODIS
class 1 (Evergreen Needleleaf, 20 m) lands on USGS 1 (Urban, height 0) and SUMMA dies
with `paramCheck/height of canopy top is less than the height of the canopy bottom`.

**Step 2 — make `vegeParTbl` agree with the numbering you wrote.**

| Basin Location | `vegeParTbl` Decision | `--veg_scheme` |
|---|---|---|
| **North America** | `USGS` | `usgs` |
| **Global / non-NA (incl. China)** | `MODIFIED_IGBP_MODIS_NOAH` | `modis` |

> **THE SILENT TRAP.** The two tables give the same integer different meanings.
> `vegTypeIndex 13` is **Evergreen Broadleaf Forest** under `USGS` and **Urban and
> Built-up** under `MODIFIED_IGBP_MODIS_NOAH`. `15` is Mixed Forest vs Snow/Ice. SUMMA
> does **not** validate the pairing — it reads whichever table `vegeParTbl` names and
> indexes it with whatever integers you wrote. `configure_decisions.py` defaults
> `vegeParTbl` to `USGS`; a non-NA basin that accepts that default while writing IGBP
> numbers mis-maps **every** class. Always set `vegeParTbl` explicitly, and set
> `--veg_scheme` to match it in the same breath.

- `USGS` (27 classes): NA-centric types (Tundra, Playa, White Sand). Shipped everywhere.
- `MODIFIED_IGBP_MODIS_NOAH` (20 classes): global IGBP numbering for classes 1–16.
  **Water is the one exception to "class numbers match"**: IGBP numbers water `0`,
  this table is 1-based with `ISWATER = 17`. `ki_tools_common.landcover.igbp_to_modis`
  handles it; a bare identity map hands SUMMA index 0 and reads outside the LAIM/HVT
  arrays.

> **The two tables live in two different files, under two different names.**
> `MODIFIED_IGBP_MODIS_NOAH` is a section of **`VEGPARM.TBL`** (line 44 of the shipped
> `case_study/base_settings/VEGPARM.TBL`; 20 classes, canopy height columns
> `ZTOPV`/`ZBOTV`) — that is the file SUMMA's `vegeParTbl` decision reads.
> **`MPTABLE.TBL` carries the same table under the Fortran namelist
> `&noah_mp_modis_parameters`** (canopy height rows `HVT`/`HVB`), which is what
> `set_trial_parameters.py --veg_scheme modis` parses. Both shipped files already
> contain their respective section — verified 2026-07-20.
> **`grep MODIFIED_IGBP_MODIS_NOAH MPTABLE.TBL` returns NOTHING, and that is correct,
> not a missing section.** Do not read that empty grep as "the table is absent" and
> take `dt_022`'s "fall back to USGS" escape — falling back without renumbering
> `vegTypeIndex` mis-maps every class, which is the exact trap this section exists to
> prevent. To check MPTABLE, grep `noah_mp_modis_parameters`; to check VEGPARM, grep
> `MODIFIED_IGBP_MODIS_NOAH`.

For **Chinese basins**: `MODIFIED_IGBP_MODIS_NOAH`. The USGS table has no rice paddy
type and the crosswalk is imprecise.

**Worked failure (Jinghong, Lancang, 142,695 km², 2026-07-10).** A driver derived
`vegTypeIndex` from elevation — `z<1800 m → USGS 13`, `<3000 m → 15`, else `7`.
AVHRR reads **closed shrubland** (canopy 1.1 m, LAI 0.0 in winter) for all 16 lowland
sub-basins and 15 of 18 mid-elevation ones. The rule gave 42% of the basin — the
wettest 42% — an evergreen 16–20 m canopy with LAI 4.5 in *every month*, which
transpired and re-evaporated intercepted water right through the dry season:
`scalarTotalET` 766.8 mm/yr against a `P − Q_obs` ceiling of 555 mm/yr, i.e. PBIAS
−66%. Three rounds of routing and calibration work chased a bias that vegetation had
already made unreachable. **Check `scalarTotalET < P − Q_obs` before touching routing
or parameters** — routing is mass-conserving and cannot move PBIAS.

### 2b. Soil Parameter Estimation — ROSETTA van Genuchten (RECOMMENDED)

SUMMA uses the **van Genuchten-Mualem** equations. All soil parameters must be self-consistent from ONE framework. Use `--from_hwsd`:

```bash
python tools/s4_parameters/set_trial_parameters.py \
  --attributes_nc settings/attributes.nc \
  --output_nc settings/trialParams.nc \
  --from_hwsd
```

**Pipeline**: HWSD raster → sand/clay% → USDA texture class → ROSETTA vGn → 5 core parameters + derived FC/WP:

```python
from ki_tools_common.soil_utils import lookup_hwsd, rosetta_vgn

soil = lookup_hwsd(lat, lon)
vgn = rosetta_vgn(soil['sand'], soil['clay'])
# Returns: theta_r, theta_s, alpha_1_per_m, n, ksat_cm_day, field_capacity, wilting_point
```

| SUMMA parameter | From `rosetta_vgn()` | Note |
|---|---|---|
| `theta_res` | `vgn['theta_r']` | Residual water content |
| `theta_sat` | `vgn['theta_s']` | Saturated water content |
| `vGn_alpha` | **`-vgn['alpha_1_per_m']`** | **MUST be negative** (matric head convention) |
| `vGn_n` | `vgn['n']` | Shape parameter |
| `k_soil` | `vgn['ksat_m_s']` | Already in m/s |
| `fieldCapacity` | `vgn['field_capacity']` | θ at -33 kPa |
| `critSoilWilting` | `vgn['wilting_point']` | θ at -1500 kPa |
| `critSoilTranspire` | Midpoint(WP, FC) | Derived |
| `heightCanopyTop/Bottom` | VEGPARM.TBL | ZTOPV/ZBOTV per vegTypeIndex |

**DO NOT mix Saxton-Rawls with ROSETTA** — they give inconsistent theta_res vs wilting point, causing SUMMA paramCheck failures (dt_026). Use `rosetta_vgn()` exclusively.

**vGn_alpha sign**: SUMMA uses **negative** alpha (matric head convention). Negate the value from `rosetta_vgn()`: `alpha = -vgn['alpha_1_per_m']`. Positive values cause NaN.

### 2d. Basin (GRU-level) Parameters — Routing and the Lumped Aquifer

SUMMA has TWO parameter namespaces. `localParamInfo.txt` holds HRU-level params;
`basinParamInfo.txt` holds GRU-level ones. `read_param.f90` resolves any
trialParams variable it does not recognise as an HRU param through `get_ixbpar()`
and reads it off the **`gru` dimension**. So basin params must be written on a
`gru` dimension — the HRU-dimension `--parameters` path cannot reach them.

| Basin parameter | Range | Active when |
|---|---|---|
| `routingGammaShape` | 2.0 – 3.0 | `subRouting=timeDlay` |
| `routingGammaScale` (s) | 1 – 5.0e6 | `subRouting=timeDlay` |
| `basin__aquiferHydCond` | 1e-4 – 10 | `groundwatr=bigBuckt` |
| `basin__aquiferScaleFactor` | 0.1 – 100 | `groundwatr=bigBuckt` |
| `basin__aquiferBaseflowExp` | 1 – 10 | `groundwatr=bigBuckt` |

```bash
python tools/s4_parameters/set_trial_parameters.py \
  --attributes_nc settings/attributes.nc --output_nc settings/trialParams.nc \
  --from_hwsd \
  --basin_parameters '{"routingGammaShape": 2.5, "routingGammaScale": 604800}'
```

**SUMMA HAS NO *INTERNAL* CHANNEL ROUTING — but this KI ships an EXTERNAL one.**
`averageRoutedRunoff` is the sub-grid **gamma time-delay histogram**, NOT channel
discharge. **NEVER score `averageRoutedRunoff × basin area` against a stream gauge.**
Doing so yields the signature `r >= 0.7` with `NSE <= 0.3` — right shape, all channel
travel time missing. That is a **workflow error, not a model verdict**
(`dag.yaml` hazard `averageRoutedRunoff_scored_as_channel_discharge`).
For gauged discharge you **MUST** run **Stage 8** (`tools/s8_routing/`, mizuRoute) —
see "Stage 8" below and `docs/s8_routing_skill.md`.

About the histogram itself:
`var_derive.f90:fracFuture` builds it with `dt = data_step` over `nTimeDelay=2000`
bins, so with daily forcing the delay can span 2000 days. Mean delay =
`routingGammaShape × routingGammaScale`. The **compiled default scale is 20000 s
(5.6 h)** — effectively no attenuation. Leaving it at the default is why lumped
runs on large basins produce a hydrograph far too flashy for the gauge:
Bengbu (121,330 km²) scored NSE −2.56 with r 0.38.

**Rule of thumb**: basins > ~5,000 km² need an explicit `routingGammaScale`.
Start at scale ≈ (basin concentration time)/shape, i.e. 1–10 days for 10⁴–10⁵ km².
`--from_hwsd` may be combined with `--parameters` (HRU overrides) and
`--basin_parameters` in one call.

### 3. CRITICAL: Output Mixed Units (dt_025 — cost 2 days to find)

SUMMA output variables use **two different unit systems in the same file**:

| Unit | Variables | mm/yr conversion |
|------|-----------|-----------------|
| **m/s** | scalarTotalRunoff, scalarRainPlusMelt, scalarInfiltration, scalarSoilDrainage, scalarSurfaceRunoff, averageRoutedRunoff | × 86400 × 365 × **1000** |
| **kg/m²/s** | scalarThroughfallRain, scalarTotalET, pptrate, scalarCanopyEvaporation, scalarGroundEvaporation | × 86400 × 365 |

**Discharge: Q(m³/s) = scalarTotalRunoff(m/s) × HRUarea(m²).** Do NOT divide by 1000.

**Sign convention:** Negative ET = evaporation (water leaving surface). Positive = condensation.

### 4. Input Unit Conversions (Silent Error Zone)

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

### 5b. Initial Conditions — matric head and moisture MUST agree (dt_034)

**`--init_moisture` alone does nothing.** `create_initial_conditions.py` writes
both `mLayerVolFracLiq` and `mLayerMatricHead`. Under this KI's default decision
`f_Richards = mixdform`, **matric head is the prognostic variable** in
unsaturated soil — SUMMA recomputes θ from ψ at the first step, so the head wins
and your `--init_moisture` is silently discarded. The tool used to write a flat
`-100 m` (inherited from Reynolds), which is near the **wilting point**.

On the default 4 m / 8-layer profile that is a ~600 mm storage deficit. The
basin then spends *years* filling it before generating any runoff, and the
failure presents as **dt_011 "all runoff is zero" with a perfectly closed water
balance** — every conservation and unit check passes, so the search goes to
parameters, routing and forcing first. Always pass the s4 file:

```bash
python tools/s5_initial_conditions/create_initial_conditions.py \
  --attributes_nc settings/attributes.nc --output_nc settings/coldState.nc \
  --trial_params_nc settings/trialParams.nc \
  --init_moisture_from field_capacity        # near-equilibrium start
```

The head is inverted from θ through the van Genuchten curve using the **same s4
parameters SUMMA will use** (`alpha = |vGn_alpha|`, since SUMMA stores it
negative). **s4 must now run BEFORE s5.** Read back the stdout JSON
`initial_soil_state`: `consistent` must be `true`, and with
`field_capacity` the mean head should land at **≈ −3.4 m** — field capacity is
*defined* as θ at −33 kPa = −3.37 m, so that is a free check that the inversion
is right. Without `--trial_params_nc` the tool still runs but logs a loud
WARNING and falls back to the contradictory constant.

Measured on Tangnaihai (74 GRUs, 9-month cold-start smoke, identical forcing /
parameters / decisions): Jan–Sep runoff **0.33 mm → 67.1 mm**.

### 6. Spinup Required — Two-Phase Strategy for Subtropical Basins

> **Scope check first.** The two-phase strategy below is a remedy for basins
> where `nrg_flux` **fails to converge from cold start** (documented on
> subtropical Bengbu). It is not a universal prescription, and applying it
> where it is not needed does harm: `presTemp` produces **zero ET**, so a
> `presTemp` spinup year fills the soil with water that should have evaporated
> and hands phase 2 a wetter-than-real profile. **Run a short cold-start
> `nrg_flux` smoke first** — if it completes, use single-phase `nrg_flux` and
> discard the spinup year. On Tangnaihai (74 GRUs, alpine, 4160 m) a 9-month
> cold-start `nrg_flux` smoke ran to completion with no convergence failures in
> 2 min, so single-phase was the correct choice.
>
> If the real problem is that runoff stays at zero, the cause is usually the
> initial **soil moisture**, not the temperature boundary condition — fix
> §5b/dt_034 at its source rather than papering over it with a spinup phase.

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
export F_MASTER=KISSPATH_BINARIES/summa
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

# 8. External channel routing -- REQUIRED whenever the obs is a stream gauge
PY=KISSPATH_PYTHON_ENV/bin/python
$PY tools/s8_routing/build_river_network.py --hybas_shp <hybas_as_lev07_v1c.shp> \
    --outlet_hybas_id <HYBAS_ID of the gauge sub-basin> --dem <dem.tif> \
    --output_dir <route/> --soil_index <N> \
    --landcover_tif KISSPATH_DATA/landcover/AVHRR_1km_LANDCOVER_1981_1994.GLOBAL.tif \
    --veg_scheme modis   # modis = MODIFIED_IGBP_MODIS_NOAH (non-NA); MUST match vegeParTbl (Sec 2c)
# stdout JSON carries veg_area_fraction -- read it. If a 4900 m Tibetan sub-basin
# came back "Evergreen Broadleaf Forest", the vegetation is wrong and so is the ET.
# -> route/ntopo.nc, route/gru_hru_mapping.csv, route/hybas_map.csv
#    stdout JSON carries outlet_seg_id -- you need it below.
# Re-run s1..s6 with route/gru_hru_mapping.csv (one GRU per sub-basin), then:
$PY tools/s8_routing/summa_to_mizuroute.py --summa_output_nc <summa_out.nc> \
    --ntopo_nc route/ntopo.nc --output_nc route/runoff.nc
$PY tools/s8_routing/run_mizuroute.py --ntopo_nc route/ntopo.nc --runoff_nc route/runoff.nc \
    --output_dir route/ --sim_start YYYY-MM-DD --sim_end YYYY-MM-DD \
    --outlet_seg_id <from build_river_network JSON> --dt 10800
# -> route/routed_discharge.csv  (date, Q_m3s)  <-- THIS is what you score
```

---

## Choosing the comparison path — gridded obs vs stream gauge

The obs shape decides the whole downstream workflow, and the two paths are
**opposites**. Read `dag.yaml` `outputs.<var>.observability.comparable_obs_shapes[]`
BEFORE building the domain, because the choice changes s1.

| Obs | obs_shape | Path | Stage 8 routing? |
|---|---|---|---|
| Stream gauge (GRDC, Huai, HYDAT) | `point_time_series` | s1 from `build_river_network.py` (one GRU per sub-basin) -> s8 mizuRoute -> score `routed_discharge.csv` | **MANDATORY** |
| Gridded product (GRUN runoff, MOD16 ET, ESA-CCI SM) | `spatial_time_series` | s1 `create_gru_hru.py --resolution` on the OBS grid -> `compare_spatial_field.py` | **NEVER — see below** |

**Do not route a gridded-obs comparison.** For `spatial_time_series` the dag caveat is
"Per-HRU/GRU runoff fields, not channel discharge". GRUN is a *runoff generation* field
per 0.5° cell — it is not routed to any outlet, so routing the model side would compare a
channel-delayed series against an undelayed field and destroy the timing on purpose.
Stage 8 is required for gauges precisely because a gauge IS channel discharge; the same
reasoning forbids it here.

**Mask thin edge cells, or you manufacture a bias.** A basin rarely fills a
0.5° cell. Where it covers only a sliver, the simulated value is a *basin-only*
mean facing a *whole-cell* observation — different support, and the resulting
bias is a masking artifact rather than a model verdict. Pass
`--min_cell_coverage 0.75` to `compare_spatial_field.py` and read back
`n_cells_dropped_by_coverage`. On Tangnaihai this keeps 38 of 74 cells.

**The scored pairs are written to CSV.** `compare_spatial_field.py` emits
`--output_csv` (default: the JSON path with a `.csv` suffix) with columns
`date,lat,lon,cell_coverage_fraction,obs,sim` in mm/day — one row per scored
cell-month. That file *is* the evidence for the headline metric; a number that
cannot be re-derived from disk is not a result.

**Align the model grid to the obs grid.** `create_gru_hru.py` snaps cell edges to
multiples of `--resolution`, so `--resolution 0.5` puts cell CENTRES on `x.25 / x.75` —
which is exactly GRUN's centre convention. A 0.5° run therefore maps 1:1 onto GRUN cells
with no regridding. Pick `--resolution` to match the obs product and the aggregation stays
honest; pick a mismatched resolution and `compare_spatial_field.py` has to area-weight
fragments across cell boundaries.

**Scale validity.** Running ONE point/lumped GRU and scoring it against a regional or
gridded aggregate is a SCALE MISMATCH, not a model verdict. Either run gridded over the
obs region, or report `scale_comparable: false`.

---

## Stage 8 — External Channel Routing (mizuRoute)

### When this stage is MANDATORY
If the observation is **gauged streamflow** (`point_time_series` discharge), Stage 8 is
**required** — at any basin size. There is no defensible proxy. Scoring
`averageRoutedRunoff × area` is a workflow error (`dag.yaml` hazard
`averageRoutedRunoff_scored_as_channel_discharge`).

### Binary and interpreter
- Router: `KISSPATH_BINARIES/mizuRoute/mizuRoute-main/route/bin/mizuroute.exe`
- **Always** invoke the s8 tools with `KISSPATH_PYTHON_ENV/bin/python`.
  The system/conda `lisflood` python raises `ValueError: numpy.dtype size changed`
  on `import netCDF4`. That is an env ABI mismatch, **not** a tool bug.

### Discretisation — a lumped GRU CANNOT be routed
A river-network router needs runoff **per sub-basin**
(`dag.yaml` hazard `lumped_discretisation_cannot_be_routed`).
`create_gru_hru.py` cannot produce this — it grids by `--resolution` and has no way to
emit one GRU per HydroBASINS polygon. Use `build_river_network.py`, which emits **both**
`ntopo.nc` **and** a `gru_hru_mapping.csv` (`gruId == hruId ==` compact seg id) that the
existing `create_local_attributes.py --gru_hru_csv` consumes unchanged.

### Silent contracts — get these wrong and the answer is quietly wrong
| Contract | Why |
|---|---|
| Feed **`scalarTotalRunoff`**, never `averageRoutedRunoff` | mizuRoute's `<doesBasinRoute> 1` applies the hillslope UH itself; feeding the already-delayed variable **double-routes**. Add `scalarTotalRunoff` to outputControl. |
| Units are **`m/s`, unconverted** | `read_control.f90:456` — `case('m'); length_conv = 1._dp`. SUMMA's `scalarTotalRunoff` is already m/s. Any scaling makes discharge **1000× wrong**. There is no `--scale` flag and there must not be one. |
| IDs are **renumbered 1..N** | HYBAS_ID reaches 4,071,348,160 > int32 max 2,147,483,647, and mizuRoute loads ntopo ids via `i4b` (`read_streamSeg.f90:254`). `build_river_network.py` renumbers and preserves originals in `hybas_map.csv`. |
| `route_opt=1` (IRF) is **hard-coded** | IRF's unit hydrograph uses reach `Length` + `velo`/`diff` only. Every other scheme (KWT/KW/MC/DW) consumes channel `Slope`, which HydroBASINS lacks — `build_river_network.py` writes a **nominal** slope solely to satisfy mizuRoute's required-from-file reader (`popMetadat.f90:134`). Exposing those schemes would silently route on a fabricated slope. |
| `--outlet_seg_id` | Read the `outlet_seg_id` field from `build_river_network.py`'s stdout JSON. It is the **compact** id, not the HYBAS_ID. |

### Forcing for a multi-GRU run — USE THE TOOL
> **This section used to say "no tool does this — build it inline". That is
> obsolete.** `tools/s2_forcing_prep/build_summa_forcing_from_reanalysis.py`
> does exactly this and is the required path — for routed multi-GRU runs *and*
> for gridded `--resolution` domains. Building it inline re-introduces the
> period-ending timestamp, RH-percent and shortwave-spike traps it already
> handles (dt_031, `qc_shortwave`). Corrected 2026-08-02.

```bash
$PY tools/s2_forcing_prep/build_summa_forcing_from_reanalysis.py \
    --attributes_nc settings/attributes.nc --source cmfd \
    --start_year 1980 --end_year 1990 \
    --reference_elev_nc <ki_tools_common.terrain.CMFD_ELEV_PATH> \
    --lapse_rate -0.0065 --output_dir forcing/
```

What it does per GRU, driven by `attributes.nc` (same contract as
`gru_hru_mapping.csv`): pulls the CMFD 3-hourly column at each centroid via
`ki_tools_common.load_forcing`, lapse-corrects air temperature from the CMFD
orography to the GRU's own elevation, recomputes pressure hydrostatically,
carries humidity at **preserved RH** (`ki_tools_common.humidity` — RH is in
**PERCENT**, clip 1..100), and sets `data_step = 10800`.

- **`--reference_elev_nc` is not optional in practice.** Without a real
  reference elevation field the lapse correction silently no-ops
  (`load_subdaily_forcing_points` returns no `elevation_m`). On the plateau a
  0.1° cell elevation and a 0.5° GRU mean differ by hundreds of metres, and
  snowmelt timing is set by near-freezing temperature.
- The dag's `boundary.temporal` is **hourly** (3600–10800 s); daily forcing
  (86400 s) is **outside** that bound and must not be used.
- CMFD load is ≈3–5 min per year per domain — always run this detached.

### `forcingFileList.txt` lives in **settingsPath**, not forcingPath (dt_032)
SUMMA splits the two:

```
ffile_info.f90:86    infile = trim(SETTINGS_PATH)//trim(FORCING_FILELIST)   ! the LIST
ffile_info.f90:120   the .nc names inside the list resolve against FORCING_PATH
```

The s2 builders only get `--output_dir`, so they write the list beside the
`forcing_YYYY.nc` files — the one place SUMMA will not look. **Do not hand-copy
it and do not point `forcingPath` at the settings dir to compensate.**
`create_file_manager.py` owns this contract: it copies the list into
settingsPath (or synthesises one from the sorted `*.nc`) and reports what it did
in its stdout JSON `forcing_list` field. Read `n_missing_in_forcing_path` — a
non-zero value means the list names files that are not there. Symptom if this
goes wrong: `validate_file_manager.py` exit 2, `forcingListFile: file not found
at '<settings>/forcingFileList.txt'`, at the very end of an expensive setup.

### Before you read any metric
Routing is a **mass-conserving redistribution in time**. It changes timing (NSE/KGE) and
**cannot change PBIAS**. Re-audit `validate_water_balance` on the corrected run first: a
large residual of the same magnitude as |PBIAS| means the bias is a **storage** problem
(on high-altitude basins, most often perpetual snow accumulating in the top elevation
bands — SUMMA has no glacier module), not a routing problem.

---

*This knowledge infrastructure was built using the knowledge dissection methodology (Zhang et al., Nature, under review).*
*Package: hydrocraft-summa v1.0.0 | 12 tools (~2,826 LOC) | 7 skill documents (~5,158 words) | 18 diagnostic triplets | 7 failure domains*
